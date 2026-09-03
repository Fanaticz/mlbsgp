#!/usr/bin/env python3
"""Smoke test for the calculateBets circuit breaker.

Guards the 2026-09-03 fix for the IP-flagged case: when Akamai has scored the
egress IP, every pricing POST 403s even with a validated cookie. The sweep used
to spend its whole 95s deadline re-POSTing into that block (observed: 27 of 29
calls 403, 103s elapsed) and then reported rows as "deadline" — which reads as
"slow, try again" when the truth is "this IP can't price, set DK_PROXY".

Checks:
  * the breaker trips only after DK_PRICE_BREAKER_403S *consecutive* 403s;
  * ANY served response clears the streak, so a merely rate-limited IP (a few
    through, then a burst of 403s) keeps pricing instead of being written off —
    this is the check that stops the breaker from costing real prices;
  * once tripped, _price_combo skips the POST entirely (no wire call) and tallies
    skipped_blocked;
  * _post_with_retry abandons its remaining attempts once tripped, but still
    returns the response so the 403 lands in the diag;
  * DK_PRICE_BREAKER_403S=0 disables the breaker;
  * end-to-end sweep with DK pricing hard-blocked: finishes fast, every row
    still carries its Pinnacle fair line, and rows say pricing_blocked rather
    than no_match/deadline.
Run: python3 scripts/smoke_dk_price_breaker.py  (exit 0 = pass)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.pop("DK_IMPERSONATE", None)
import dk_api  # noqa: E402

failures = []


def check(c, m):
    print(("  ok: " if c else "  FAIL: ") + m)
    if not c:
        failures.append(m)


dk_api._time.sleep = lambda s: None      # control flow only, don't wait out backoff
dk_api._warm_dk_cookies = lambda: None   # no cookie work in these paths
dk_api._warmup_done = True
dk_api._get_warmup_done = True

POSTS = []  # every POST that reached the "wire"


class _Resp:
    def __init__(self, status):
        self.status_code = status

    def json(self):
        return {"bets": [{"trueOdds": 2.5, "displayOdds": "+150",
                          "selectionsMapped": [1, 2]}],
                "selectionsForYourBet": []}


class _Sess:
    """Answers pricing POSTs from a scripted status sequence."""

    _dk_impersonate = "stub"

    def __init__(self):
        self.cookies = type("J", (), {"jar": [], "update": lambda *a: None})()

    def post(self, url, **k):
        POSTS.append(url)
        return _Resp(SEQ.pop(0) if SEQ else 403)


SEQ = []


def reset(threshold=12, seq=None):
    global SEQ
    dk_api._PRICE_BREAKER_403S = threshold
    dk_api._price_breaker["streak"] = 0
    dk_api._price_breaker["tripped"] = False
    dk_api._PRICE_DIAG.update({"calls": 0, "ok": 0, "incompatible": 0, "no_bet": 0,
                               "exceptions": 0, "http": {}, "breaker_tripped": False,
                               "skipped_blocked": 0})
    SEQ = list(seq or [])
    POSTS.clear()
    dk_api.session = _Sess()


IDS = ["sel_a", "sel_b"]

print("breaker trips only on a CONSECUTIVE run of 403s:")
reset(threshold=4, seq=[403] * 3)
for _ in range(3):
    dk_api._note_price_status(403)
check(not dk_api._price_blocked(), "3 of 4 403s: not tripped yet")
dk_api._note_price_status(403)
check(dk_api._price_blocked(), "4th consecutive 403 trips it")
check(dk_api._PRICE_DIAG["breaker_tripped"], "diag records breaker_tripped")

print("\na served response clears the streak (rate-limited != blocked):")
reset(threshold=4)
for _ in range(3):
    dk_api._note_price_status(403)
dk_api._note_price_status(200)          # one got through
check(dk_api._price_breaker["streak"] == 0, "success reset the streak")
for _ in range(3):
    dk_api._note_price_status(403)
check(not dk_api._price_blocked(),
      "3 more 403s after that success still do NOT trip it (would have at 6 without the reset)")
reset(threshold=4)
for _ in range(2):
    dk_api._note_price_status(403)
dk_api._note_price_status(422)          # a real DK rejection, not a block
check(dk_api._price_breaker["streak"] == 0, "a non-403 served status also clears the streak")

print("\nonce tripped, _price_combo skips the POST entirely:")
reset(threshold=1, seq=[403])
r = dk_api._price_combo(IDS)
check(r is None, "first (403) call returns None")
n_after_first = len(POSTS)
r = dk_api._price_combo(IDS)
check(r is None, "second call returns None")
check(len(POSTS) == n_after_first, "no additional POST hit the wire (%d total)" % len(POSTS))
check(dk_api._PRICE_DIAG["skipped_blocked"] >= 1, "skipped_blocked tallied")

print("\n_post_with_retry stops retrying once tripped, but still returns the response:")
reset(threshold=1, seq=[403, 403, 403, 403])
r = dk_api._post_with_retry(dk_api.DK_PRICE, json={}, attempts=4,
                            headers=dk_api.DK_PRICE_HEADERS)
check(r is not None and r.status_code == 403, "returns the 403 response (diag still sees it)")
check(len(POSTS) == 1, "abandoned the remaining 3 attempts (%d POSTs)" % len(POSTS))

print("\nunrelated hosts are not gated by the pricing breaker:")
reset(threshold=1, seq=[403, 200])
dk_api._post_with_retry(dk_api.DK_PRICE, json={}, attempts=1, headers={})
check(dk_api._price_blocked(), "breaker tripped on the pricing host")
n = len(POSTS)
dk_api._post_with_retry("https://sportsbook-nash.draftkings.com/some/other/post",
                        json={}, attempts=1, headers={})
check(len(POSTS) == n + 1, "a non-pricing POST still goes out")

print("\nDK_PRICE_BREAKER_403S=0 disables the breaker:")
reset(threshold=0, seq=[403] * 30)
for _ in range(20):
    dk_api._note_price_status(403)
check(not dk_api._price_blocked(), "never trips when disabled")
r = dk_api._price_combo(IDS)
check(len(POSTS) > 0, "POSTs still go out when disabled")

# --- end-to-end: the sweep with pricing hard-blocked ---
print("\nsweep with DK pricing hard-blocked (the Railway case):")
DK_FEED = json.load(open(os.path.join(ROOT, "scripts", "fixtures", "dk_epl_sgp_event.json")))
HOME, AWAY = "Nottingham Forest", "Leeds United"


def fake_pin_games(league=None, league_id=None):
    return {"matches": [{"id": 999, "home": HOME, "away": AWAY,
                         "startTime": "2099-01-01T00:00:00Z"}]}


def fake_pin_specials(mid):
    return {"home": HOME, "away": AWAY, "groups": [
        {"key": "btts_total", "kind": "btts_total", "label": "BTTS/Total", "sels": [
            {"name": "Yes & Over 2.5", "odds": 140, "fair_prob": 0.40, "fair_american": 150,
             "fields": {"btts": "Yes", "total_side": "Over", "total_line": 2.5}},
            {"name": "No & Under 2.5", "odds": 154, "fair_prob": 0.37, "fair_american": 167,
             "fields": {"btts": "No", "total_side": "Under", "total_line": 2.5}},
        ]},
        {"key": "winner_total", "kind": "winner_total", "label": "Winner/Total", "sels": [
            {"name": "Draw & Under 2.5", "odds": 330, "fair_prob": 0.217, "fair_american": 360,
             "fields": {"result": "draw", "total_side": "Under", "total_line": 2.5}},
        ]},
    ]}


class _R:
    def json(self):
        return DK_FEED


dk_api.pinnacle_wc_games = fake_pin_games
dk_api.pinnacle_wc_specials = fake_pin_specials
dk_api._get_with_retry = lambda *a, **k: _R()
dk_api._parse_iso_epoch = lambda s: None
dk_api._dk_games_for_league = lambda key, attempts=2: (
    [{"id": DK_FEED["data"]["events"][0]["id"], "homeTeam": "Nottingham Forest",
      "awayTeam": "Leeds", "hasSGP": True}], None)

reset(threshold=2, seq=[403] * 200)
res = dk_api.find_sgps_soccer_all({"leagues": ["epl"], "max_games": 5,
                                   "sgp_only": True, "window_hours": 99999})
rows, s = res["rows"], res["summary"]
check(len(rows) >= 3, "Pinnacle rows still returned (%d)" % len(rows))
check(all(r["fair_american"] is not None for r in rows),
      "every row still carries its Pinnacle fair line")
check(not s["dk_priced_any"], "nothing priced, as expected")
statuses = {r["dk_status"] for r in rows}
check("pricing_blocked" in statuses,
      "rows report pricing_blocked (got %s)" % sorted(statuses))
check("deadline" not in statuses,
      "no row is mislabelled 'deadline' (got %s)" % sorted(statuses))
diag = s.get("sgp_price_diag") or {}
check(diag.get("breaker_tripped") is True, "summary diag flags breaker_tripped")
check(len(POSTS) <= 8,
      "the whole sweep made at most a handful of pricing POSTs (%d)" % len(POSTS))

print("\n%s" % ("ALL PRICE BREAKER SMOKE CHECKS PASSED" if not failures
                else "%d FAILURE(S)" % len(failures)))
sys.exit(1 if failures else 0)
