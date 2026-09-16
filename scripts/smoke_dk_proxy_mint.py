#!/usr/bin/env python3
"""Smoke test for the sticky-proxy + browser-mint plumbing (2026-09-16).

Guards the invariant behind the DK_PROXY plan: the Akamai `_abck` cookie is
bound to the IP that earned it, so the curl_cffi pricing POST and the browser
that mints the cookie must leave from the SAME proxy exit — across the
separate dk_api.py subprocesses server.js spawns per request.

Checks (all offline — the browser driver is faked):
  * `{session}` in DK_PROXY resolves to one id, reused by a "second
    subprocess" (module reload) from the state dir, re-drawn after
    DK_PROXY_SESSION_TTL or when the proxy host changes, pinned by
    DK_PROXY_SESSION; curl_cffi and the browser get the same resolved URL;
  * the diag / host helpers never leak credentials;
  * the browser proxy kwarg splits user:pass out of the URL (Chromium rejects
    them inline), unquotes them, keeps socks5 schemes;
  * the mint rides DK_PROXY over an ambient HTTPS_PROXY;
  * engine selection: pinned engine, missing engine → None, unknown → auto;
  * a mint through a fake driver: proxy passed at launch, HeadlessChrome UA
    rewritten, polls until _abck validates, clicks through to the second page
    when the homepage alone doesn't validate, caches to disk keyed by the
    exit, and a fresh process reuses the disk cache without launching;
  * a driver crash degrades to None (warmup fallback) and says so in the diag;
  * _warm_dk_cookies surfaces proxy + mint in _PRICE_DIAG.
Run: python3 scripts/smoke_dk_proxy_mint.py  (exit 0 = pass)
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STATE = tempfile.mkdtemp(prefix="dkstate-")
for k in ("DK_PROXY", "DK_PROXY_SESSION", "DK_COOKIES", "DK_COOKIE_BROWSER",
          "DK_COOKIE_BROWSER_ENGINE", "DK_IMPERSONATE", "DK_CHROMIUM_PATH"):
    os.environ.pop(k, None)
os.environ["DK_STATE_DIR"] = STATE
os.environ["DK_PROXY"] = "http://user-session-{session}:p%40ss@gate.example.com:7000"

import dk_api  # noqa: E402

failures = []


def check(c, m):
    print(("  ok: " if c else "  FAIL: ") + m)
    if not c:
        failures.append(m)


def reload_dk():
    global dk_api
    dk_api = importlib.reload(dk_api)
    return dk_api


print("[1] sticky session id")
sid = dk_api._proxy_session_id()
check(len(sid) == 8 and all(ch in "0123456789abcdef" for ch in sid), f"8-hex session id drawn ({sid})")
check("{session}" not in dk_api._DK_PROXY and sid in dk_api._DK_PROXY, "placeholder substituted in resolved DK_PROXY")
check(dk_api._PROXIES["https"] == dk_api._DK_PROXY == dk_api._PROXIES["http"], "curl_cffi proxies use the resolved URL")
check(dk_api._DK_PROXY_RAW.count("{session}") == 1, "raw URL keeps the placeholder")
sess_ids = {dk_api._proxy_session_id() for _ in range(5)}
check(sess_ids == {sid}, "id stable across calls in one process")
reload_dk()
check(dk_api._proxy_session_id() == sid, "second subprocess (reload) reuses the id from the state dir")
check(sid in dk_api._DK_PROXY, "…and resolves DK_PROXY with it")
st = json.load(open(os.path.join(STATE, "proxy_session.json")))
st["ts"] = time.time() - dk_api._PROXY_SESSION_TTL_S - 5
json.dump(st, open(os.path.join(STATE, "proxy_session.json"), "w"))
reload_dk()
sid2 = dk_api._proxy_session_id()
check(sid2 != sid and len(sid2) == 8, "expired session (past TTL) is re-drawn")
os.environ["DK_PROXY"] = "http://user-session-{session}:pw@other.example.net:8000"
reload_dk()
sid3 = dk_api._proxy_session_id()
check(sid3 != sid2, "proxy host change re-draws the id")
os.environ["DK_PROXY_SESSION"] = "pinned01"
reload_dk()
check(dk_api._proxy_session_id() == "pinned01" and "pinned01" in dk_api._DK_PROXY, "DK_PROXY_SESSION pins the id")
d = dk_api._proxy_diag()
check(d["sticky"] is True and d["session"] == "pinned01", "diag reports sticky + session")
os.environ.pop("DK_PROXY_SESSION")
mode = oct(os.stat(os.path.join(STATE, "proxy_session.json")).st_mode & 0o777)
check(mode == "0o600", f"state file is owner-only ({mode})")
# Unwritable state dir: the id must still be the same in every subprocess.
os.environ["DK_STATE_DIR"] = os.path.join(STATE, "proxy_session.json")  # a file, not a dir
reload_dk()
ro1 = dk_api._proxy_session_id()
reload_dk()
ro2 = dk_api._proxy_session_id()
check(ro1 == ro2 and len(ro1) == 8, f"unwritable state dir → deterministic per-host id, stable across reloads ({ro1})")
check(ro1 != sid3, "…and it isn't the disk-backed id")
os.environ["DK_STATE_DIR"] = STATE
reload_dk()

print("[2] no credential leaks")
os.environ["DK_PROXY"] = "http://brd-customer-x-session-{session}:S3cretPw@brd.superproxy.io:33335"
reload_dk()
host = dk_api._proxy_host(dk_api._DK_PROXY)
check(host == "http://brd.superproxy.io:33335", f"_proxy_host strips creds ({host})")
diag_blob = json.dumps(dk_api._proxy_diag())
check("S3cretPw" not in diag_blob and "brd-customer" not in diag_blob, "proxy diag carries neither password nor username")
check(dk_api._proxy_host("") is None and dk_api._proxy_diag() is not None, "_proxy_host('') → None; diag present when proxy set")
key = dk_api._browser_cookie_cache_key()
check(key.startswith("http://brd.superproxy.io:33335|") and len(key.split("|")[1]) == 8, f"cookie cache key = exit|session ({key})")

print("[3] browser proxy kwarg")
kw = dk_api._browser_proxy_kw("http://user-session-abc:p%40ss@gate.example.com:7000")
check(kw == {"server": "http://gate.example.com:7000", "username": "user-session-abc", "password": "p@ss"},
      f"creds split out and unquoted ({kw})")
check(dk_api._browser_proxy_kw("http://gate.example.com:7000") == {"server": "http://gate.example.com:7000"}, "no creds → server only")
check(dk_api._browser_proxy_kw("") is None and dk_api._browser_proxy_kw(None) is None, "empty → None")
check(dk_api._browser_proxy_kw("socks5://h:1080")["server"] == "socks5://h:1080", "socks5 scheme kept")
check(dk_api._browser_proxy_kw("http://gate.example.com")["server"] == "http://gate.example.com", "no port → no :port")

print("[4] mint proxy precedence")
os.environ["HTTPS_PROXY"] = "http://agent.local:3128"
check(dk_api._mint_proxy_url() == dk_api._DK_PROXY, "DK_PROXY wins over HTTPS_PROXY for the mint")
os.environ["DK_PROXY"] = ""
reload_dk()
check(dk_api._mint_proxy_url() == "http://agent.local:3128", "no DK_PROXY → ambient HTTPS_PROXY")
check(dk_api._proxy_diag() is None and dk_api._PROXIES is None, "no DK_PROXY → no proxies, diag None")
check(dk_api._browser_cookie_cache_key() == "direct|", "cache key 'direct|' with no proxy")
os.environ.pop("HTTPS_PROXY")
os.environ["DK_PROXY"] = "http://user-session-{session}:pw@gate.example.com:7000"
reload_dk()

print("[5] engine selection")
os.environ["DK_COOKIE_BROWSER_ENGINE"] = "playwright"
name, sp = dk_api._mint_engine()
have_pw = name == "playwright"
check(have_pw and callable(sp), f"pinned engine honoured ({name}; playwright installed here)")
real_import = importlib.import_module


def _no_such(mod, *a, **k):
    if mod in ("seleniumbase", "patchright.sync_api", "playwright.sync_api"):
        raise ImportError(mod)
    return real_import(mod, *a, **k)


dk_api.importlib.import_module = _no_such
os.environ["DK_COOKIE_BROWSER_ENGINE"] = "uc"
check(dk_api._mint_engine() == (None, None), "engine 'uc' without seleniumbase → (None, None)")
os.environ["DK_COOKIE_BROWSER_ENGINE"] = "auto"
check(dk_api._mint_engine() == (None, None), "auto with nothing installed → (None, None)")
dk_api.importlib.import_module = real_import
os.environ["DK_COOKIE_BROWSER_ENGINE"] = "bogus"
check(dk_api._mint_engine()[0] in ("patchright", "playwright"), "unknown engine name → auto order")
os.environ.pop("DK_COOKIE_BROWSER_ENGINE")


print("[6] mint through a fake driver")
LAUNCHES = []


class FakePage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.urls = []

        class M:
            def move(self, *a): pass

            def wheel(self, *a): pass
        self.mouse = M()

    def goto(self, url, **kw):
        self.urls.append(url)
        self.ctx.browser.visits.append(url)
        if url.rstrip("/").endswith(dk_api._MINT_SECOND_PATH):
            self.ctx.browser.hopped = True

    def evaluate(self, js):
        return self.ctx.browser.ua

    def wait_for_timeout(self, ms): pass

    def inner_text(self, sel): return "{}"


class FakeCtx:
    def __init__(self, browser, **kw):
        self.browser = browser
        self.kw = kw
        self.polls = 0

    def new_page(self): return FakePage(self)

    def cookies(self):
        self.polls += 1
        b = self.browser
        validated = b.validate_after_polls is not None and (
            self.polls >= b.validate_after_polls and (not b.needs_hop or b.hopped))
        ab = "AAA~0~BBB" if validated else "AAA~-1~BBB"
        return [{"name": "_abck", "value": ab, "domain": ".draftkings.com"},
                {"name": "bm_sz", "value": "zz", "domain": ".draftkings.com"}]

    def close(self): pass


class FakeBrowser:
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/141.0.0.0 Safari/537.36"
    validate_after_polls = 2
    needs_hop = False

    def __init__(self, **kw):
        self.launch_kw = kw
        self.contexts = []
        self.visits = []
        self.hopped = False
        LAUNCHES.append(self)

    def new_context(self, **kw):
        c = FakeCtx(self, **kw)
        self.contexts.append(c)
        return c

    def close(self): self.closed = True


class FakeChromium:
    def launch(self, **kw): return FakeBrowser(**kw)


class FakePW:
    chromium = FakeChromium()

    def __enter__(self): return self

    def __exit__(self, *a): return False


def fake_sync_playwright(): return FakePW()


dk_api._mint_engine = lambda: ("patchright", fake_sync_playwright)
os.environ["DK_CHROMIUM_PATH"] = "/opt/fake/chrome"
dk_api._MINT_WAIT_S = 3.0
cookies = dk_api._mint_cookies_with_browser()
b = LAUNCHES[-1]
check(cookies and cookies.get("_abck") == "AAA~0~BBB" and cookies.get("bm_sz") == "zz", "mint returns the validated jar")
check(b.launch_kw.get("proxy") == dk_api._browser_proxy_kw(dk_api._DK_PROXY), "browser launched through the resolved DK_PROXY (creds split)")
check(b.launch_kw.get("executable_path") == "/opt/fake/chrome" and b.launch_kw.get("headless") is True, "DK_CHROMIUM_PATH + headless honoured")
real_ctx = b.contexts[-1]
check("HeadlessChrome" not in real_ctx.kw.get("user_agent", "") and "Chrome/141.0.0.0" in real_ctx.kw.get("user_agent", ""),
      "HeadlessChrome token dropped from the UA, version kept")
check(real_ctx.kw.get("ignore_https_errors") is True, "ignore_https_errors on when proxied")
check(b.visits[0] == dk_api._DK_MINT_URL and not b.hopped, "validated on the homepage → no second-page hop")
check(getattr(b, "closed", False), "browser closed")
check(dk_api._MINT_DIAG == {"engine": "patchright", "source": "fresh", "abck": "validated", "error": None}, f"mint diag fresh/validated ({dk_api._MINT_DIAG})")
disk = json.load(open(os.path.join(STATE, "browser_cookies.json")))
check(disk["key"] == dk_api._browser_cookie_cache_key() and disk["cookies"] == cookies and disk["abck"] == "validated",
      "disk cache written, keyed to the exit")

n_before = len(LAUNCHES)
dk_api._BROWSER_COOKIE_CACHE.update(ts=0.0, cookies=None)  # "new subprocess": memory empty
again = dk_api._mint_cookies_with_browser()
check(again == cookies and len(LAUNCHES) == n_before, "fresh process reuses the disk cache without launching a browser")
check(dk_api._MINT_DIAG["source"] == "disk", "diag says the jar came from disk")

os.environ["DK_PROXY_SESSION"] = "newexit1"
reload_dk()
dk_api._mint_engine = lambda: ("patchright", fake_sync_playwright)
dk_api._MINT_WAIT_S = 3.0
FakeBrowser.needs_hop = True
c2 = dk_api._mint_cookies_with_browser()
b2 = LAUNCHES[-1]
check(len(LAUNCHES) == n_before + 1, "a different exit (new session id) ignores the old cache and re-mints")
check(b2.hopped and c2 and c2["_abck"] == "AAA~0~BBB", "homepage didn't validate → clicked through to the league page, then validated")
check("newexit1" in b2.launch_kw["proxy"]["username"], "re-mint went through the new session's exit")
FakeBrowser.needs_hop = False
os.environ.pop("DK_PROXY_SESSION")

FakeBrowser.validate_after_polls = None
dk_api._BROWSER_COOKIE_CACHE.update(ts=0.0, cookies=None)
os.environ["DK_PROXY_SESSION"] = "neverval"
reload_dk()
dk_api._mint_engine = lambda: ("patchright", fake_sync_playwright)
dk_api._MINT_WAIT_S = 1.0
c3 = dk_api._mint_cookies_with_browser()
check(c3 and c3["_abck"] == "AAA~-1~BBB" and dk_api._MINT_DIAG["abck"] == "unvalidated",
      "never validates → returns what it has, diag says unvalidated (probe/status line can tell)")
FakeBrowser.validate_after_polls = 2
os.environ.pop("DK_PROXY_SESSION")

print("[7] driver failure degrades")


class BoomChromium:
    def launch(self, **kw): raise RuntimeError("no display")


class BoomPW(FakePW):
    chromium = BoomChromium()


os.environ["DK_PROXY_SESSION"] = "boom0001"
reload_dk()
dk_api._mint_engine = lambda: ("playwright", lambda: BoomPW())
check(dk_api._mint_cookies_with_browser() is None, "launch failure → None")
check(dk_api._MINT_DIAG["source"] == "failed:RuntimeError" and dk_api._MINT_DIAG["error"] == "no display",
      f"diag names the failure + message ({dk_api._MINT_DIAG['source']}, {dk_api._MINT_DIAG['error']})")
dk_api._mint_engine = lambda: (None, None)
check(dk_api._mint_cookies_with_browser() is None and dk_api._MINT_DIAG["source"] == "unavailable", "no driver → None, diag 'unavailable'")
os.environ.pop("DK_PROXY_SESSION")

print("[8] _warm_dk_cookies diag")
os.environ["DK_COOKIE_BROWSER"] = "1"
os.environ["DK_PROXY_SESSION"] = "warm0001"
reload_dk()
dk_api._mint_engine = lambda: ("patchright", fake_sync_playwright)
dk_api._MINT_WAIT_S = 3.0
dk_api._warm_dk_cookies()
pd = dk_api._PRICE_DIAG
check(pd["cookie_source"] == "browser" and pd["abck"] == "validated", f"browser-minted jar loaded into the session ({pd['cookie_source']}, {pd['abck']})")
check(pd["proxy"] == {"host": "http://gate.example.com:7000", "sticky": True, "session": "warm0001"}, f"diag.proxy ({pd['proxy']})")
check(pd["mint"] == {"engine": "patchright", "source": "fresh", "abck": "validated", "error": None}, f"diag.mint ({pd['mint']})")
jar_abck = next((c.value for c in dk_api.session.cookies.jar if c.name == "_abck"), None)
check(jar_abck == "AAA~0~BBB", "curl_cffi session carries the minted _abck")
check("pw" not in json.dumps(pd), "price diag never carries the proxy password")

shutil.rmtree(STATE, ignore_errors=True)
if failures:
    print(f"\n{len(failures)} FAILURE(S):")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("\nALL PROXY/MINT SMOKE CHECKS PASSED")
