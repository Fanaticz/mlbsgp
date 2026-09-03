#!/usr/bin/env python3
"""Smoke test for TLS-fingerprint retirement in the DK retry layer.

Guards the 2026-09 fix for egress paths that reset the newest "chrome"
ClientHello at the transport layer (curl error 35) — seen behind an agent
proxy, and the same shape as a corporate route that does it. Before the fix
_get_with_retry_inner / _post_with_retry / _pin_get rotated the impersonation
profile only on a 403 *status*; a reset arrives as an *exception*, so every
attempt re-sent on the same dead fingerprint and the whole scrape failed
("Recv failure: Connection reset by peer") even though the next profile in
the list works fine.

Checks, with the network stubbed at _new_session:
  * a reset on the first profile(s) retires them, rotates, and the request
    succeeds on the first live profile WITHOUT consuming the attempt budget
    (the soccer sweep fetches each league with attempts=2);
  * once retired, a profile is skipped by later 403-driven rotations too,
    including on wrap-around;
  * a timeout is NOT a profile fault (same profile, normal backoff);
  * an all-dead list terminates (no spin) and clears itself;
  * a late retire() of a profile the session already left is a no-op (the
    worker-thread race the per-session tag exists for);
  * _post_with_retry, _pin_get and the homepage warmup share the behavior;
  * the diag snapshot names the live profile and the retired ones.
Run: python3 scripts/smoke_dk_tls_rotation.py  (exit 0 = pass)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.pop("DK_IMPERSONATE", None)  # exercise the default list, not an env pin
import dk_api  # noqa: E402
from curl_cffi.requests import exceptions as cx  # noqa: E402

failures = []


def check(c, m):
    print(("  ok: " if c else "  FAIL: ") + m)
    if not c:
        failures.append(m)


# Backoff math isn't under test, only control flow — don't actually sleep.
dk_api._time.sleep = lambda s: None
# Cookie warmup is covered by its own check below; keep it out of the others.
dk_api._warmup_done = True
dk_api._get_warmup_done = True

URL = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1/leagues/40253"
RESET = cx.SSLError("Failed to perform, curl: (35) Recv failure: Connection reset by peer", 35)
TIMEOUT = cx.Timeout("Failed to perform, curl: (28) Operation timed out", 28)

CALLS = []      # (profile, method) for every request that reached the "wire"
BEHAVIOR = {}   # profile -> exception to raise, or status code to answer


class _Resp:
    def __init__(self, status):
        self.status_code = status

    def json(self):
        return {"ok": True}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise cx.HTTPError("HTTP %d" % self.status_code)


class _Jar(dict):
    def update(self, other):
        pass


class _FakeSession:
    """Stands in for curl_cffi's Session: answers per BEHAVIOR for its profile."""

    def __init__(self, imp):
        self._dk_impersonate = imp
        self.cookies = _Jar()

    def _do(self, method):
        CALLS.append((self._dk_impersonate, method))
        b = BEHAVIOR.get(self._dk_impersonate, 200)
        if isinstance(b, BaseException):
            raise b
        return _Resp(b)

    def get(self, *a, **k):
        return self._do("get")

    def post(self, *a, **k):
        return self._do("post")


dk_api._new_session = lambda imp: _FakeSession(imp)


def reset(profiles, behavior):
    global BEHAVIOR
    BEHAVIOR = behavior
    CALLS.clear()
    dk_api._IMPERSONATES = list(profiles)
    dk_api._dead_profiles.clear()
    dk_api._imp_idx = 0
    dk_api._cooloff_until = 0.0
    dk_api.session = dk_api._new_session(profiles[0])


def profiles_hit():
    return [c[0] for c in CALLS]


PROFILES = ["chrome", "chrome120", "chrome116", "edge101"]

print("fault classifier:")
check(dk_api._is_profile_fault(RESET), "curl 35 (reset during handshake) is a profile fault")
check(dk_api._is_profile_fault(cx.ConnectionError("recv failure", 56)), "curl 56 is a profile fault")
check(dk_api._is_profile_fault(cx.ImpersonateError("unknown profile")), "ImpersonateError is a profile fault")
check(not dk_api._is_profile_fault(TIMEOUT), "curl 28 (timeout) is NOT a profile fault")
check(not dk_api._is_profile_fault(cx.ConnectionError("refused", 7)), "curl 7 (refused) is NOT a profile fault")
check(not dk_api._is_profile_fault(RuntimeError("x")), "a non-curl exception is NOT a profile fault")

print("\nGET: two dead profiles ahead of a live one, attempts=2 (the sweep's budget):")
reset(PROFILES, {"chrome": RESET, "chrome120": RESET})
r = dk_api._get_with_retry(URL, attempts=2)
check(r.status_code == 200, "request succeeds")
check(profiles_hit() == ["chrome", "chrome120", "chrome116"],
      "each dead profile tried once, then the live one (%s)" % profiles_hit())
check(dk_api._dead_profiles == {"chrome", "chrome120"}, "both reset profiles retired")
check(dk_api.session._dk_impersonate == "chrome116", "shared session now speaks the first live profile")

print("\nGET: a later 403-driven rotation skips retired profiles (wrap-around):")
BEHAVIOR = {"chrome": RESET, "chrome120": RESET, "chrome116": 403}
CALLS.clear()
r = dk_api._get_with_retry(URL, attempts=3)
check(r.status_code == 200, "request succeeds after the 403 rotation")
check("chrome" not in profiles_hit() and "chrome120" not in profiles_hit(),
      "retired profiles never re-tried (%s)" % profiles_hit())
check(profiles_hit()[-1] == "edge101", "rotation landed on the next live profile")
reset(["chrome", "chrome120", "chrome116"], {"chrome": RESET, "chrome120": RESET, "chrome116": 403})
try:
    dk_api._get_with_retry(URL, attempts=3)
except Exception:
    pass
check(set(profiles_hit()[2:]) == {"chrome116"},
      "with only one live profile, wrap-around stays on it instead of revisiting dead ones (%s)" % profiles_hit())

print("\nGET: a timeout is transient — same profile, normal backoff:")
reset(PROFILES, {"chrome": TIMEOUT})
try:
    dk_api._get_with_retry(URL, attempts=2)
    raised = None
except Exception as e:
    raised = e
check(isinstance(raised, cx.Timeout), "timeout still raises after the attempt budget")
check(profiles_hit() == ["chrome", "chrome"], "timeout retries the SAME profile (%s)" % profiles_hit())
check(not dk_api._dead_profiles, "timeout retires nothing")

print("\nGET: every profile dead — terminates and clears:")
reset(["chrome", "chrome120"], {"chrome": RESET, "chrome120": RESET})
try:
    dk_api._get_with_retry(URL, attempts=1)
    raised = None
except Exception as e:
    raised = e
check(isinstance(raised, cx.SSLError), "raises the reset rather than spinning")
check(len(CALLS) <= 3, "bounded wire calls (%d)" % len(CALLS))
check(not dk_api._dead_profiles, "dead set cleared once everything was retired (next call starts fresh)")

print("\nthread race: a late retire() of a profile the session already left:")
reset(PROFILES, {})
dk_api._rotate_session()                  # e.g. a 403 rotation moved us to chrome120
dk_api._rotate_session(retire="chrome")   # a worker that failed on chrome reports late
check(dk_api.session._dk_impersonate == "chrome120", "does not rotate again")
check("chrome" in dk_api._dead_profiles, "...but chrome is still recorded as dead")

print("\nPOST (calculateBets path) shares the behavior:")
reset(PROFILES, {"chrome": RESET})
r = dk_api._post_with_retry(dk_api.DK_PRICE, json={}, attempts=1, headers=dk_api.DK_PRICE_HEADERS)
check(r.status_code == 200, "POST succeeds with attempts=1 after retiring the dead profile")
check(CALLS == [("chrome", "post"), ("chrome120", "post")], "one reset, then the live profile (%s)" % CALLS)

print("\nPinnacle GET shares the behavior:")
reset(PROFILES, {"chrome": RESET})
j = dk_api._pin_get("/sports", attempts=1)
check(j == {"ok": True}, "Pinnacle GET succeeds after retiring the dead profile")
check(profiles_hit() == ["chrome", "chrome120"], "one reset, then the live profile (%s)" % profiles_hit())

print("\nhomepage cookie warmup retires a reset profile up front:")
reset(PROFILES, {"chrome": RESET})
dk_api._warmup_done = False
dk_api._legacy_warmup()
dk_api._warmup_done = True
check("chrome" in dk_api._dead_profiles, "warmup reset retired the profile")
check(dk_api.session._dk_impersonate == "chrome120", "session already on the next profile before the first market GET")

print("\ndiag:")
d = dk_api._tls_diag()
check(d["tls_profile"] == "chrome120" and d["dead_profiles"] == ["chrome"],
      "reports live profile + retired list (%s)" % d)

print("\n%s" % ("ALL TLS ROTATION SMOKE CHECKS PASSED" if not failures else "%d FAILURE(S)" % len(failures)))
sys.exit(1 if failures else 0)
