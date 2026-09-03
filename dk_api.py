#!/usr/bin/env python3
"""DraftKings SGP API helper.

Uses curl_cffi with Chrome TLS impersonation to bypass Akamai bot protection.
Called from Node.js server via subprocess.

Usage:
  python3 dk_api.py games                       # Get today's MLB games
  python3 dk_api.py markets <eventId>           # Get markets for a game (scoped)
  python3 dk_api.py featured <eventId>          # Auto-build + price SGPs for game
  python3 dk_api.py price                       # Price SGP (selections via stdin JSON)
"""

import sys
import json
import re
import random
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests as cffi_requests
from curl_cffi.requests import exceptions as cffi_exceptions

DK_MLB_LEAGUE_ID = "84240"
# NBA league ID on DraftKings' nav endpoint. Override-able via env if DK
# ever renumbers. Verified against the /nav/leagues response April 2026.
import os as _os
DK_NBA_LEAGUE_ID = _os.environ.get("DK_NBA_LEAGUE_ID", "42648")
# Tennis (men's French Open) league ID. DK uses per-tournament league IDs
# for grand slams. Default is a placeholder — set DK_TENNIS_LEAGUE_ID in
# the environment to the live French Open Men's league ID (check the
# /nav/leagues response or the DK URL on the slate page).
DK_TENNIS_LEAGUE_ID = _os.environ.get("DK_TENNIS_LEAGUE_ID", "40841")
# FIFA World Cup league ID. Empty default: get_games_soccer() auto-resolves
# via the public slug page on first use (same scrape as tennis). Set
# DK_WORLDCUP_LEAGUE_ID to pin it and skip the extra request.
DK_WORLDCUP_LEAGUE_ID = _os.environ.get("DK_WORLDCUP_LEAGUE_ID", "")
DK_WORLDCUP_SLUG = _os.environ.get("DK_WORLDCUP_SLUG", "world-cup-2026")

# ---------------------------------------------------------------------------
# Soccer league registry. The soccer SGP engine (DK combo grammar + Pinnacle
# devig) is entirely league-agnostic — only the league IDs differ — so adding a
# league is just adding an entry here plus (if its clubs abbreviate words) a
# name-alias set below. Each entry pins:
#   dk_id:   DraftKings sportscontent/eventGroup league id (games + markets)
#   dk_slug: DK public-page slug, used to auto-resolve dk_id when it's blank
#   pin_id:  Pinnacle guest-API league id (fair no-vig lines)
# All values are env-overridable so IDs can be corrected without a redeploy if
# DK/Pinnacle ever renumber. Verified live 2026-08-22: DK EPL eventGroup 40253
# (SGP-tagged), Pinnacle EPL league 1980.
# (key, label, dk_id, dk_slug, pin_id). Verified live 2026-08-22 from DK's
# soccer landing page (eventGroupInfos) + Pinnacle /sports/29/leagues. The
# "scrape all" sweep walks these in order; add a row to cover another league.
_SOCCER_LEAGUE_ROWS = [
    ("epl",        "English Premier League", "40253", "england---premier-league", "1980"),
    ("laliga",     "La Liga",                "40031", "spain---la-liga",           "2196"),
    ("seriea",     "Serie A",                "40030", "italy---serie-a",           "2436"),
    ("bundesliga", "Bundesliga",             "40481", "germany---1.bundesliga",    "1842"),
    ("ligue1",     "Ligue 1",                "40032", "france---ligue-1",          "2036"),
    ("ucl",        "Champions League",       "40685", "champions-league",          "2627"),
    ("eredivisie", "Eredivisie",             "41372", "netherlands---eredivisie",  "1928"),
    ("primeira",   "Primeira Liga",          "44069", "portugal---primeira-liga",  "2386"),
    ("championship","EFL Championship",       "40817", "england---championship",    "1977"),
    ("mls",        "MLS",                    "89345", "usa---mls",                 "2663"),
    ("ligamx",     "Liga MX",                "44525", "mexico---liga-mx",          "2242"),
    ("brasileirao","Brazil Serie A",         "38529", "brazil---serie-a",          "1834"),
    ("saudi",      "Saudi Pro League",       "72057", "saudi-arabia---premier",    "10419"),
]

# Per-league env overrides: DK_LEAGUE_ID_<KEY> / PIN_LEAGUE_ID_<KEY> (uppercased
# key) correct an id without a redeploy if DK/Pinnacle renumber.
SOCCER_LEAGUES = {}
for _k, _label, _dk, _slug, _pin in _SOCCER_LEAGUE_ROWS:
    SOCCER_LEAGUES[_k] = {
        "label": _label,
        "dk_id": _os.environ.get("DK_LEAGUE_ID_" + _k.upper(), _dk),
        "dk_slug": _slug,
        "pin_id": _os.environ.get("PIN_LEAGUE_ID_" + _k.upper(), _pin),
    }

# Ordered keys the "scrape all major soccer" sweep covers. Override with the
# SOCCER_LEAGUES_SWEEP env (comma-separated keys) to narrow/reorder.
_sweep_env = (_os.environ.get("SOCCER_LEAGUES_SWEEP", "") or "").strip()
MAJOR_SOCCER_LEAGUES = ([k.strip() for k in _sweep_env.split(",") if k.strip()]
                        if _sweep_env else [r[0] for r in _SOCCER_LEAGUE_ROWS])
DEFAULT_SOCCER_LEAGUE = _os.environ.get("DEFAULT_SOCCER_LEAGUE", "epl")


def _soccer_league(key):
    """Resolve a league key (e.g. 'epl') to its registry entry. Unknown/blank
    keys fall back to the configured default so old callers keep working."""
    if key and str(key).lower() in SOCCER_LEAGUES:
        return SOCCER_LEAGUES[str(key).lower()]
    return SOCCER_LEAGUES.get(DEFAULT_SOCCER_LEAGUE) or next(iter(SOCCER_LEAGUES.values()))
# State site prefix for the sportscontent API (dkusnj = NJ, dkusil = IL, ...).
# Both return identical event/market data for national leagues, but keep it
# env-overridable to mirror DK_PRICE_HOST's state scoping.
DK_SITE = _os.environ.get("DK_SITE", "dkusnj")
# League/games feed. DK retired the old navigation endpoint
# (.../sportscontent/navigation/dkusnj/v1/nav/leagues/{id} → 404, mid-2026)
# and moved the same payload to the sportscontent leagues route. Response now
# carries events with `id`/`startEventDate` (was `eventId`/`startDate`) plus,
# for MLB, each team's `startingPitcherPlayerName` in participant metadata.
DK_LEAGUES = f"https://sportsbook-nash.draftkings.com/api/sportscontent/{DK_SITE}/v1/leagues"
# Backwards-compat alias: older call sites / env docs referred to DK_NAV.
DK_NAV = DK_LEAGUES
# Per-event SGP feed. Still live, and now embeds every market's selections
# (odds included) alongside clientMetadata.subCategories in a single response —
# so get_markets() reads it directly instead of fanning out one request per
# subcategory to the (also-retired) controldata endpoint.
DK_SGP = "https://sportsbook-nash.draftkings.com/sites/US-SB/api/sportscontent/parlays/v1/sgp/events"
# Pricing host is state-scoped and Akamai-guarded separately from the
# sportsbook-nash market hosts. When one state host starts 403-ing every
# calculateBets POST (2026-07-04 outage), another often still serves —
# override from the environment without a code change, e.g.
# DK_PRICE_HOST=gaming-us-ny.draftkings.com
DK_PRICE_HOST = _os.environ.get("DK_PRICE_HOST", "gaming-us-nj.draftkings.com")
DK_PRICE = f"https://{DK_PRICE_HOST}/api/wager/v1/calculateBets"

# calculateBets is what a logged-out browser POSTs from the bet slip; Akamai
# expects the request to look like it came from the sportsbook page. Bare
# JSON POSTs (no Origin/Referer, no .draftkings.com cookies) are exactly the
# profile it 403s.
DK_PRICE_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://sportsbook.draftkings.com",
    "Referer": "https://sportsbook.draftkings.com/",
}

# Rotate TLS fingerprints so Akamai can't pin a single one as "bot" and 403
# every subcategory request for the remainder of the subprocess. Order is
# deliberate: latest "chrome" first because Akamai aggressively 503s the
# pinned-version fingerprints (chrome120/116/etc) on some IPs, while latest
# "chrome" stays under the radar. We round-robin in this order on each rotate
# rather than random.choice'ing — guarantees we exhaust all fingerprints in
# at most N attempts instead of stochastically retrying the bad ones.
#
# The flip side: some egress paths reset the newest "chrome" ClientHello at
# the transport layer (curl error 35, before any HTTP). That is handled at
# runtime — a profile that resets is retired for the process and skipped by
# rotation (see _dead_profiles) — so the order above stays Akamai-optimal
# without hard-coding around any one network. DK_IMPERSONATE still pins the
# list outright when you already know what an egress accepts.
_IMPERSONATES = ["chrome", "chrome120", "chrome116", "chrome110", "chrome107",
                 "chrome101", "edge101", "edge99", "safari17_2_ios"]
# Optional override (comma-separated curl_cffi profiles), e.g.
# DK_IMPERSONATE=chrome116,safari17_2_ios — pins the fingerprint list when an
# egress path rejects the newest "chrome" TLS profile (some corporate/proxy
# networks reset it). Empty = the default rotation above.
_imp_env = (_os.environ.get("DK_IMPERSONATE", "") or "").strip()
if _imp_env:
    _override = [p.strip() for p in _imp_env.split(",") if p.strip()]
    if _override:
        _IMPERSONATES = _override

_session_lock = threading.Lock()
_imp_idx = 0

# Optional outbound proxy for all DK/Pinnacle curl_cffi traffic. Set DK_PROXY to
# a residential/rotating proxy URL (http://user:pass@host:port) when DK's Akamai
# edge scores this deployment's datacenter IP and 403s even with a valid cookie
# — the last lever short of moving hosts. Empty = go direct (default). Pinnacle
# rides the same session, which is harmless (it works over any egress).
_DK_PROXY = (_os.environ.get("DK_PROXY", "") or "").strip()
_PROXIES = {"https": _DK_PROXY, "http": _DK_PROXY} if _DK_PROXY else None


def _new_session(imp):
    kw = {"impersonate": imp}
    if _PROXIES:
        kw["proxies"] = _PROXIES
    s = cffi_requests.Session(**kw)
    # Remember which fingerprint this session speaks so a retry loop can
    # retire the profile *it* failed on — not whichever happens to be current
    # by the time it reports back (worker threads race through here).
    s._dk_impersonate = imp
    return s


session = _new_session(_IMPERSONATES[0])

# Throttle gate: once DK returns a 403 we pause all threads for a cool-off.
# Without this, every in-flight request races into the Akamai block and the
# retry budget burns out in a fraction of a second.
_cooloff_until = 0.0


# Fingerprints this process has proven cannot even complete a TLS handshake
# on its egress. Some intermediaries (corporate/agent proxies, certain
# datacenter routes) reset the newest "chrome" ClientHello outright — curl
# error 35, before any HTTP happens — and that is deterministic per profile:
# retrying the same fingerprint can never succeed, unlike a timeout or a DNS
# blip. The retry loops used to rotate only on a 403 *status*, never on an
# exception, so a "chrome"-first egress burned every attempt on the dead
# profile and could not scrape at all. Rotation now skips retired profiles;
# if every profile ends up retired the set is cleared so we cycle rather
# than deadlock with nothing left to try.
_dead_profiles = set()

# curl codes that mean "the transport rejected this fingerprint": 35 = SSL
# connect error (the reset-by-peer case above), 55/56 = send/recv failure
# during the handshake. Timeouts (28), DNS (6), refused (7) are NOT profile
# faults — the same profile may well succeed on the next try.
_PROFILE_FAULT_CURL_CODES = (35, 55, 56)


def _is_profile_fault(exc):
    """True when `exc` is a TLS/impersonation-level failure the same
    fingerprint will hit again, so the caller should retire that profile and
    rotate immediately instead of sleeping and re-sending on it."""
    if isinstance(exc, cffi_exceptions.ImpersonateError):
        return True
    return getattr(exc, "code", None) in _PROFILE_FAULT_CURL_CODES


def _retire_profile(sess, exc):
    """Retire the fingerprint `sess` used and swap in the next live one.
    Returns True when `exc` was a profile fault (and so was handled by
    rotation); False means it was transient and the caller should back off."""
    if not _is_profile_fault(exc):
        return False
    _rotate_session(retire=getattr(sess, "_dk_impersonate", None))
    return True


def _tls_diag():
    """Which fingerprint the shared session speaks now, and which ones this
    process gave up on — surfaced next to the cookie diag so an empty +EV
    state can say "your egress resets chrome/chrome120" without shell access."""
    with _session_lock:
        return {"tls_profile": getattr(session, "_dk_impersonate", None),
                "dead_profiles": sorted(_dead_profiles)}


def _rotate_session(retire=None):
    global session, _imp_idx
    with _session_lock:
        if retire:
            _dead_profiles.add(retire)
            if len(_dead_profiles) >= len(_IMPERSONATES):
                _dead_profiles.clear()
            # A sibling thread that hit the same reset may already have moved
            # us off that profile; the session it built is good as-is.
            if _IMPERSONATES[_imp_idx] != retire:
                return
        for _ in range(len(_IMPERSONATES)):
            _imp_idx = (_imp_idx + 1) % len(_IMPERSONATES)
            if _IMPERSONATES[_imp_idx] not in _dead_profiles:
                break
        fresh = _new_session(_IMPERSONATES[_imp_idx])
        # Carry the cookie jar over: Akamai clearance cookies (_abck/bm_sz on
        # .draftkings.com) are what let the pricing POSTs through, and losing
        # them on every rotation put each new fingerprint back at square one.
        try:
            fresh.cookies.update(session.cookies)
        except Exception:
            pass
        session = fresh


_warmup_done = False

# ---------------------------------------------------------------------------
# Validated-cookie provider for the pricing POST.
#
# calculateBets sits behind Akamai Bot Manager, which requires a *validated*
# _abck cookie. A plain homepage GET only yields an UNVALIDATED _abck (the
# value's 2nd `~`-delimited field is `-1`); Akamai flips it to validated only
# after its in-page sensor JS POSTs telemetry back. curl_cffi can't execute
# that JS, so on its own it can never satisfy the wager endpoint — every POST
# 403s ("AkamaiGHost / Access Denied") while the market GETs, which don't
# enforce validation, keep working. That is the "legs matched, 0 SGPs priced"
# failure. The homepage warmup added earlier collects the cookie but not a
# *validated* one, which is why it didn't resolve the 403 storm.
#
# Cookie sources, highest priority first:
#   1. DK_COOKIES env — a raw "name=value; name=value" string pasted from a
#      real logged-out browser (DevTools > Application > Cookies). Immediate
#      stopgap; refresh it when it expires. Must include a validated _abck.
#   2. DK_COOKIE_BROWSER=1 — mint cookies with a headless browser that runs
#      the sensor JS, cached with a TTL and re-minted when stale. Durable, but
#      needs Playwright + Chromium in the image; off by default.
#   3. homepage warmup (legacy) — collects an unvalidated _abck. Kept as the
#      last-ditch fallback so behavior never regresses when neither of the
#      above is configured.
_cookie_source = None  # which source last seeded the jar (surfaced in diag)
_cookie_mint_lock = threading.Lock()
_BROWSER_COOKIE_CACHE = {"ts": 0.0, "cookies": None}
_BROWSER_COOKIE_TTL_S = float(_os.environ.get("DK_COOKIE_BROWSER_TTL", "600"))


def _abck_validation_state(jar):
    """Return 'validated' | 'unvalidated' | 'absent' for the _abck cookie.
    Akamai encodes the state in the 2nd `~`-delimited field: -1 = unvalidated,
    anything else (0, a positive request count) = validated."""
    try:
        for c in jar:
            if c.name == "_abck":
                parts = (c.value or "").split("~")
                if len(parts) > 1 and parts[1] != "-1":
                    return "validated"
                return "unvalidated"
    except Exception:
        pass
    return "absent"


def _load_cookie_string_into(sess, cookie_str):
    """Parse a "name=value; name=value" header string and set each pair on the
    session jar, scoped to .draftkings.com so it rides along to the gaming-us
    pricing host. Returns how many cookies were loaded."""
    n = 0
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, val = pair.split("=", 1)
        name, val = name.strip(), val.strip()
        if not name:
            continue
        try:
            sess.cookies.set(name, val, domain=".draftkings.com", path="/")
            n += 1
        except Exception:
            pass
    return n


def _mint_cookies_with_browser():
    """Best-effort: launch a headless browser, load the DK sportsbook so the
    Akamai sensor validates _abck, and return a {name: value} dict. Cached with
    a TTL. Returns None if Playwright/Chromium is unavailable or the mint fails,
    so callers transparently fall back to the warmup path.

    Enabling this in production requires Playwright + a Chromium build in the
    image. Point DK_CHROMIUM_PATH at the browser binary if it isn't on the
    default Playwright search path."""
    now = _time.time()
    cache = _BROWSER_COOKIE_CACHE
    if cache["cookies"] and now - cache["ts"] < _BROWSER_COOKIE_TTL_S:
        return cache["cookies"]
    with _cookie_mint_lock:
        now = _time.time()
        if cache["cookies"] and now - cache["ts"] < _BROWSER_COOKIE_TTL_S:
            return cache["cookies"]
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return None
        exe = _os.environ.get("DK_CHROMIUM_PATH") or None
        proxy = _os.environ.get("HTTPS_PROXY") or _os.environ.get("https_proxy")
        try:
            with sync_playwright() as p:
                launch_kw = {"headless": True, "args": ["--no-sandbox"]}
                if exe:
                    launch_kw["executable_path"] = exe
                if proxy:
                    launch_kw["proxy"] = {"server": proxy}
                browser = p.chromium.launch(**launch_kw)
                ctx = browser.new_context(ignore_https_errors=bool(proxy))
                page = ctx.new_page()
                page.goto("https://sportsbook.draftkings.com/",
                          wait_until="domcontentloaded", timeout=45000)
                cookies = {}
                # Poll until _abck flips to validated (sensor POST completes).
                for _ in range(12):
                    page.wait_for_timeout(1000)
                    jar = ctx.cookies()
                    ab = next((c for c in jar if c["name"] == "_abck"), None)
                    if ab and (ab["value"].split("~")[1:2] or ["-1"])[0] != "-1":
                        cookies = {c["name"]: c["value"] for c in jar}
                        break
                if not cookies:
                    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                browser.close()
                if cookies:
                    cache["ts"] = now
                    cache["cookies"] = cookies
                return cookies or None
        except Exception:
            return None


def _warm_dk_cookies():
    """Seed the shared jar with the best DK cookies available before the first
    calculateBets POST. Tries the explicit/browser sources (which can supply a
    *validated* _abck) and falls back to a one-time homepage GET otherwise.

    Records which source was used and the resulting _abck state on _PRICE_DIAG
    so the +EV empty state can say whether the block is an unvalidated-cookie
    problem (fixable via DK_COOKIES/DK_COOKIE_BROWSER) without shell access."""
    global _warmup_done, _cookie_source

    env_cookies = _os.environ.get("DK_COOKIES", "").strip()
    if env_cookies:
        with _session_lock:
            _load_cookie_string_into(session, env_cookies)
        _cookie_source = "env"
    elif _os.environ.get("DK_COOKIE_BROWSER", "").strip().lower() not in ("", "0", "false", "no"):
        minted = _mint_cookies_with_browser()
        if minted:
            with _session_lock:
                for name, val in minted.items():
                    try:
                        session.cookies.set(name, val, domain=".draftkings.com", path="/")
                    except Exception:
                        pass
            _cookie_source = "browser"
        else:
            _cookie_source = _cookie_source or "warmup"
            _legacy_warmup()
    else:
        _cookie_source = "warmup"
        _legacy_warmup()

    try:
        _PRICE_DIAG["cookie_source"] = _cookie_source
        _PRICE_DIAG["abck"] = _abck_validation_state(session.cookies.jar)
    except Exception:
        pass


def _legacy_warmup():
    """One-time best-effort GET of the sportsbook page to collect Akamai
    cookies. Yields an unvalidated _abck — kept only as a fallback."""
    global _warmup_done
    if _warmup_done:
        return
    with _session_lock:
        if _warmup_done:
            return
        _warmup_done = True
    sess = session
    try:
        sess.get("https://sportsbook.draftkings.com/", timeout=10,
                 headers={"Accept": "text/html,application/xhtml+xml"})
    except Exception as e:
        # A reset here means the profile is dead for the real requests too;
        # retire it now so the first market GET doesn't rediscover it.
        try:
            _retire_profile(sess, e)
        except Exception:
            pass


def _trigger_cooloff(seconds):
    global _cooloff_until
    target = _time.time() + seconds
    if target > _cooloff_until:
        _cooloff_until = target


def _wait_for_cooloff():
    now = _time.time()
    if _cooloff_until > now:
        _time.sleep(_cooloff_until - now + random.uniform(0, 0.25))


def _get_with_retry(url, params=None, timeout=15, attempts=6):
    """GET with exponential backoff + session rotation on Akamai blocks.

    DK-bound GETs also get the DK_COOKIES jar (when configured): market/games
    GETs normally pass without cookies, but some egress IPs (Railway) get the
    Akamai edge 403 on plain GETs too — a real browser cookie clears those the
    same way it clears the pricing POST."""
    global _get_warmup_done
    if not _get_warmup_done and "draftkings.com" in url:
        _get_warmup_done = True
        try:
            _warm_dk_cookies()
        except Exception:
            pass
    return _get_with_retry_inner(url, params=params, timeout=timeout, attempts=attempts)


_get_warmup_done = False


def _get_with_retry_inner(url, params=None, timeout=15, attempts=6):
    """GET with exponential backoff + session rotation on Akamai blocks.

    DK rate-limits aggressively once we fan out across ~100 subcategory
    fetches; once Akamai 403s one request it will 403 the rest in flight. Before
    giving up we:
      - rotate the curl_cffi TLS impersonation profile (new fingerprint)
      - hold a global cool-off so parallel threads don't burn their retry budget
        hammering the block
      - back off with jitter."""
    last_exc = None
    last_status = None
    attempt = 0
    # A profile fault (the transport resetting this fingerprint) is fixed by
    # rotating, not by waiting, so it doesn't consume an attempt — otherwise a
    # 2-attempt caller like the soccer sweep dies before reaching a live
    # profile. Bounded by the profile count so a fully-dead list terminates.
    faults = 0
    while attempt < attempts:
        _wait_for_cooloff()
        sess = session
        try:
            r = sess.get(url, params=params, timeout=timeout)
            last_status = r.status_code
            if r.status_code == 200:
                return r
            if r.status_code in (403, 429, 502, 503, 504):
                # 403 = Akamai bot block — longer cool-off + session rotation.
                if r.status_code in (403, 429):
                    _trigger_cooloff(1.5 + attempt * 1.2)
                    if attempt >= 1:
                        _rotate_session()
                _time.sleep(0.6 * (2 ** attempt) + random.uniform(0, 0.4))
                attempt += 1
                continue
            # Any other non-200 is unrecoverable
            r.raise_for_status()
        except Exception as e:
            last_exc = e
            if faults < len(_IMPERSONATES) and _retire_profile(sess, e):
                faults += 1
                continue
            _time.sleep(0.6 * (2 ** attempt) + random.uniform(0, 0.4))
        attempt += 1
    if last_exc:
        raise last_exc
    raise RuntimeError(f"DK request failed after {attempts} attempts: {url} (last status={last_status})")


def _post_with_retry(url, json=None, timeout=15, attempts=4, headers=None):
    """POST with the same Akamai-survival kit as _get_with_retry.

    calculateBets POSTs used to be a single bare session.post() — no retry, no
    fingerprint rotation, no cool-off participation. When Akamai starts 403ing,
    the GET paths (games/markets) recover by rotating the TLS fingerprint but
    every pricing POST dies on the first block, which reads as "legs matched,
    0 SGPs priced" in the +EV tabs. Retry only transient blocks (403/429/5xx);
    return the response for any other status so callers keep their 422/400
    semantics. On exhaustion, return the last response (status tallies feed
    _PRICE_DIAG) or raise if we never got one."""
    _warm_dk_cookies()
    # Both callers today are the calculateBets endpoint; gate the breaker on the
    # host so a future non-pricing POST doesn't inherit it.
    is_price = DK_PRICE_HOST in str(url)
    last_exc = None
    r = None
    attempt = 0
    faults = 0  # profile faults rotate for free; see _get_with_retry_inner
    while attempt < attempts:
        _wait_for_cooloff()
        sess = session
        try:
            r = sess.post(url, json=json, timeout=timeout, headers=headers)
            if is_price:
                _note_price_status(r.status_code)
            if r.status_code not in (403, 429, 502, 503, 504):
                return r
            # A tripped breaker means the remaining attempts would only collect
            # more 403s; hand back the response so the 403 still lands in the
            # diag tally, just without burning the backoff.
            if is_price and _price_blocked():
                return r
            if r.status_code in (403, 429):
                _trigger_cooloff(1.5 + attempt * 1.2)
                if attempt >= 1:
                    _rotate_session()
            _time.sleep(0.6 * (2 ** attempt) + random.uniform(0, 0.4))
        except Exception as e:
            last_exc = e
            if faults < len(_IMPERSONATES) and _retire_profile(sess, e):
                faults += 1
                continue
            _time.sleep(0.6 * (2 ** attempt) + random.uniform(0, 0.4))
        attempt += 1
    if r is not None:
        return r
    raise last_exc if last_exc else RuntimeError(f"DK POST failed: {url}")


def _ev_id(e):
    """Event id across API generations. The retired nav endpoint used
    `eventId`; the sportscontent leagues feed uses `id`."""
    return e.get("id") or e.get("eventId") or ""


def _ev_start(e):
    """Event start time across API generations (`startEventDate` new,
    `startDate` old)."""
    return e.get("startEventDate") or e.get("startDate") or ""


def get_games():
    """Return today's MLB games from DraftKings."""
    r = _get_with_retry(f"{DK_LEAGUES}/{DK_MLB_LEAGUE_ID}")
    events = r.json().get("events", [])
    out = []
    for e in events:
        tags = e.get("tags", [])
        participants = e.get("participants", [])
        home = next((p for p in participants if p.get("venueRole") == "Home"), {})
        away = next((p for p in participants if p.get("venueRole") == "Away"), {})
        out.append({
            "id": _ev_id(e),
            "name": e.get("name", ""),
            "startDate": _ev_start(e),
            "homeTeam": home.get("name", e.get("teamName2", "")),
            "awayTeam": away.get("name", e.get("teamName1", "")),
            "homeShort": home.get("metadata", {}).get("shortName", e.get("teamShortName2", "")),
            "awayShort": away.get("metadata", {}).get("shortName", e.get("teamShortName1", "")),
            "homeStarterId": home.get("metadata", {}).get("startingPitcherPlayerId", ""),
            "awayStarterId": away.get("metadata", {}).get("startingPitcherPlayerId", ""),
            "homeStarter": home.get("metadata", {}).get("startingPitcherPlayerName", ""),
            "awayStarter": away.get("metadata", {}).get("startingPitcherPlayerName", ""),
            "hasSGP": "SGP" in tags,
            "isLive": e.get("isLive", False),
            "status": e.get("status", ""),
        })
    out.sort(key=lambda x: x["startDate"])
    return {"events": out}


def get_games_nba():
    """Return today's NBA games from DraftKings. Mirrors get_games() but
    scoped to the NBA league ID. Response shape is identical so any
    downstream code that iterates `events` works unchanged."""
    r = _get_with_retry(f"{DK_LEAGUES}/{DK_NBA_LEAGUE_ID}")
    events = r.json().get("events", [])
    out = []
    for e in events:
        tags = e.get("tags", [])
        participants = e.get("participants", [])
        home = next((p for p in participants if p.get("venueRole") == "Home"), {})
        away = next((p for p in participants if p.get("venueRole") == "Away"), {})
        out.append({
            "id": _ev_id(e),
            "name": e.get("name", ""),
            "startDate": _ev_start(e),
            "homeTeam": home.get("name", e.get("teamName2", "")),
            "awayTeam": away.get("name", e.get("teamName1", "")),
            "homeShort": home.get("metadata", {}).get("shortName", e.get("teamShortName2", "")),
            "awayShort": away.get("metadata", {}).get("shortName", e.get("teamShortName1", "")),
            "hasSGP": "SGP" in tags,
            "isLive": e.get("isLive", False),
            "status": e.get("status", ""),
        })
    out.sort(key=lambda x: x["startDate"])
    return {"events": out}


def resolve_tennis_league_by_slug(slug="french-open-men"):
    """Resolve a DK public-URL slug (e.g. 'french-open-men') to the
    numeric league ID by scraping the public league page.

    DK's public URLs switched to slug-based routing
    (sportsbook.draftkings.com/leagues/tennis/<slug>), but the backend
    API still keys on the numeric ID. The page itself bakes the ID
    into its Next.js initial state — we fetch the HTML and regex it
    out. Multiple fallback patterns are tried; the first hit wins.

    Returns {"slug": ..., "league_id": "12345", "source": "page-scrape"}
    or {"slug": ..., "error": "..."} on failure."""
    if not slug:
        slug = "french-open-men"
    url = f"https://sportsbook.draftkings.com/leagues/tennis/{slug}"
    try:
        r = _get_with_retry(url, attempts=4, timeout=12)
    except Exception as e:
        return {"slug": slug, "error": f"fetch failed: {e}"}
    html = r.text or ""
    # Patterns in declining order of specificity — first match wins.
    patterns = [
        r'"leagueId"\s*:\s*"?(\d{3,7})"?',
        r'"league_id"\s*:\s*"?(\d{3,7})"?',
        r'/nav/leagues/(\d{3,7})',
        r'data-leagueid="(\d{3,7})"',
        r'/leagues/(\d{3,7})\b',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return {"slug": slug, "league_id": m.group(1),
                    "source": "page-scrape"}
    return {"slug": slug, "error": "no league id found in page",
            "html_len": len(html)}


def get_games_tennis(league_id=None):
    """Return today's men's French Open matches from DraftKings.

    DK scopes grand slams under a per-tournament league ID. Singles
    matches have two participants (the two players); we surface both
    names so the frontend can match by either side. `hasSGP` is honored
    so we skip events without SGP support.

    `league_id` (caller-provided) wins over the `DK_TENNIS_LEAGUE_ID`
    env default so the UI can switch leagues without a redeploy. To find
    the right ID, open the DK page (sportsbook.draftkings.com/leagues/
    tennis/<id>) in a browser and grab the trailing number."""
    lid = str(league_id) if league_id else DK_TENNIS_LEAGUE_ID
    r = _get_with_retry(f"{DK_LEAGUES}/{lid}")
    events = r.json().get("events", [])
    out = []
    for e in events:
        tags = e.get("tags", [])
        participants = e.get("participants", []) or []
        # Tennis singles: participants come in via venueRole Home/Away
        # most of the time, but DK occasionally flips that for tennis.
        # Fall back to index order if both roles are absent.
        home = next((p for p in participants if p.get("venueRole") == "Home"), None)
        away = next((p for p in participants if p.get("venueRole") == "Away"), None)
        if not home and len(participants) >= 1: home = participants[0]
        if not away and len(participants) >= 2: away = participants[1]
        home = home or {}
        away = away or {}
        out.append({
            "id": _ev_id(e),
            "name": e.get("name", ""),
            "startDate": _ev_start(e),
            "homePlayer": home.get("name", e.get("teamName2", "")),
            "awayPlayer": away.get("name", e.get("teamName1", "")),
            "homeShort": home.get("metadata", {}).get("shortName", e.get("teamShortName2", "")),
            "awayShort": away.get("metadata", {}).get("shortName", e.get("teamShortName1", "")),
            "hasSGP": "SGP" in tags,
            "isLive": e.get("isLive", False),
            "status": e.get("status", ""),
        })
    out.sort(key=lambda x: x["startDate"])
    return {"events": out, "leagueId": lid}


def _extract_player_name(market_name, market_type, subcat_name):
    """Strip market type/subcategory suffix from the market name to get the player name."""
    name = market_name
    for suffix in [market_type, subcat_name]:
        if not suffix:
            continue
        for pat in [suffix, suffix.replace(" O/U", ""), suffix.replace(" Milestones", "")]:
            if pat and name.lower().endswith(pat.lower()):
                name = name[:-len(pat)].strip()
                break
    # Fallback: split on known stat keywords
    if name == market_name:
        for kw in ["Strikeouts", "Earned Runs", "Walks", "Hits Allowed",
                    "Pitching Outs", "Total Bases", "Home Runs", "RBIs",
                    "Hits", "Runs", "Singles", "Doubles", "Stolen Bases",
                    # NBA player-prop stat names used by the DK market catalog.
                    # 3-Pointers Made has several DK spellings — all three are
                    # kept so the split-on-keyword fallback catches every variant.
                    "3-Pointers Made", "3-Point Made", "Threes Made",
                    "Points", "Rebounds", "Assists", "Steals", "Blocks",
                    "Turnovers"]:
            idx = market_name.find(kw)
            if idx > 0:
                name = market_name[:idx].strip()
                break
    return name


def get_markets(event_id, pitcher_only=False, batter_only=False, nba_only=False, tennis_only=False, soccer_only=False):
    """Return all markets and selections for an event, scoped properly to that event.

    When pitcher_only=True, skip subcategories that are clearly batter/team/game
    markets before making the per-subcat HTTP call. DK's subcategory endpoint is
    the slowest/most rate-limited part of the flow, so dropping ~80% of the
    fetches (we only care about pitcher props for SGP pricing) is the biggest
    lever we have on end-to-end latency.

    When batter_only=True, the inverse: keep only subcategories whose names
    suggest batter props (Hits, Runs, RBI, TB, HR, Walks, Singles/Doubles/
    Triples, Stolen Bases). Used by find_sgps_teammate to scope teammate-pair
    pricing to a manageable set of fetches per game.

    When nba_only=True, keep only subcats whose names suggest supported NBA
    player props (Points, Rebounds, Assists, 3-Pointers Made). Used by
    find_sgps_nba to scope per-event fetches to the 4 props we actually
    have correlation data for in v1 — Steals/Blocks/Turnovers/PRA/etc.
    scans would burn Akamai quota with no downstream benefit."""
    # Step 1: Fetch the per-event SGP feed. It carries event metadata
    # (subcategories + market groups) AND every SGP-eligible market with its
    # selections + odds embedded. One request replaces the old per-subcategory
    # fan-out to the retired controldata endpoint, and touching a single URL is
    # far less likely to trip Akamai's rate limiter than ~100 parallel GETs.
    r0 = _get_with_retry(f"{DK_SGP}/{event_id}")
    payload = r0.json()
    data = payload.get("data", {})
    events_in = data.get("events", []) or []
    if not events_in:
        # No SGP feed for this event (e.g. event isn't SGP-eligible).
        return {"eventId": event_id, "totalMarkets": 0, "totalSelections": 0,
                "marketGroups": [], "props": []}
    evt = events_in[0]
    subcats = evt.get("clientMetadata", {}).get("subCategories", [])
    market_groups = evt.get("marketGroups", [])
    # Name lookup over the *unfiltered* subcategory list, so kept markets can
    # be labelled even after the per-mode subcat filters below narrow `subcats`.
    subcat_name_by_id = {str(sc.get("id")): sc.get("name", "") for sc in subcats}
    feed_markets = data.get("markets", []) or []

    if pitcher_only:
        _SC_BATTER_HINTS = ("batter", "hitter", "home run", "rbi", "total bases",
                            "at bat", "stolen base", "singles", "doubles", "batting",
                            "team total", "game prop", "game lines", "moneyline",
                            "run line", "first inning", "first 5", "1st 5",
                            "innings", "player combo", "alternate run",
                            "parlay", "quick pick")
        _SC_PITCHER_HINTS = ("pitcher", "pitching", "strikeout", "earned run",
                             "walks allowed", "walk allowed", "hits allowed",
                             "outs recorded", "outs o/u", "outs thrown")
        def _keep(sc):
            n = (sc.get("name") or "").lower()
            if any(h in n for h in _SC_BATTER_HINTS):
                return False
            return any(k in n for k in _SC_PITCHER_HINTS)
        subcats = [sc for sc in subcats if _keep(sc)]
    elif batter_only:
        # Symmetric to pitcher_only: keep batter subcats, drop pitcher/team/
        # game-line subcats. Note "home run" appears in both batter (Player
        # Home Runs) and team (Team Total Home Runs) names; the team-line
        # exclusion below catches the latter.
        _SC_BATTER_HINTS = ("hits", "runs", "rbi", "total bases", "home run",
                            "at bat", "stolen base", "singles", "doubles",
                            "triples", "walks", "batter", "hitter", "batting",
                            "extra base")
        _SC_TEAM_OR_GAME_HINTS = ("team total", "team to", "moneyline",
                                  "run line", "game prop", "game lines",
                                  "first inning", "first 5", "1st 5",
                                  "innings", "alternate run line", "spread")
        _SC_PITCHER_HINTS = ("pitcher", "pitching", "strikeout", "earned run",
                             "walks allowed", "walk allowed", "hits allowed",
                             "outs recorded", "outs o/u", "outs thrown")
        def _keep_batter(sc):
            n = (sc.get("name") or "").lower()
            if any(h in n for h in _SC_PITCHER_HINTS):
                return False
            if any(h in n for h in _SC_TEAM_OR_GAME_HINTS):
                return False
            return any(k in n for k in _SC_BATTER_HINTS)
        subcats = [sc for sc in subcats if _keep_batter(sc)]
    elif nba_only:
        # Keep NBA player-prop subcats for our 4 supported stats, drop
        # team/game lines + quarter/half splits + unsupported-stat subcats.
        # "Pointers" catches all the "3-Pointers Made" spellings DK uses.
        _SC_NBA_HINTS = ("points", "rebounds", "assists", "pointers",
                         "three-point", "3-point", "3 pt", "threes")
        _SC_NBA_EXCLUDE = ("team total", "team to", "moneyline", "spread",
                           "game prop", "game lines", "quarter", "half",
                           "1st quarter", "2nd quarter", "3rd quarter",
                           "4th quarter", "first quarter", "first half",
                           "parlay", "quick pick", "race to", "alternate",
                           "steals", "blocks", "turnovers",
                           "double-double", "triple-double", "same game",
                           "player combo", "pra", "points+", "points +")
        def _keep_nba(sc):
            n = (sc.get("name") or "").lower()
            if any(h in n for h in _SC_NBA_EXCLUDE):
                return False
            return any(k in n for k in _SC_NBA_HINTS)
        subcats = [sc for sc in subcats if _keep_nba(sc)]
    elif tennis_only:
        # Keep only subcats relevant to the tennis SGP build. DK's actual
        # subcategory names (verified on French Open 2026) are:
        #   - "Total Games - Listed Set" → 1st-set total games (alt lines)
        #   - "Games Spread"             → full-match game handicap
        # Earlier hints ("1st set", "game handicap", ...) never matched any
        # real DK subcat, so every event dropped 0 markets through.
        _SC_TENNIS_HINTS = ("total games - listed set", "games spread")
        _SC_TENNIS_EXCLUDE = ("moneyline", "to win", "winner", "match winner",
                              "set betting", "set winner", "tie break",
                              "tiebreak", "aces", "double fault",
                              "break point", "service", "fastest serve",
                              "in-play", "live", "quick pick")
        def _keep_tennis(sc):
            n = (sc.get("name") or "").lower()
            if any(h in n for h in _SC_TENNIS_EXCLUDE):
                return False
            return any(k in n for k in _SC_TENNIS_HINTS)
        subcats = [sc for sc in subcats if _keep_tennis(sc)]
    elif soccer_only:
        # Keep subcats that could hold the full-match combo markets we price
        # (BTTS & Total, BTTS & Result, Result & Total, HT/FT, Odd/Even &
        # Total). DK's exact soccer subcat names are unverified — the tennis
        # scan taught us hint lists miss real names — so this is exclude-first
        # (drop the obviously irrelevant prop families) and keep-generous on
        # anything score/result/goal/half-flavored. The response surfaces the
        # fetched market names so mismatches are debuggable from the UI.
        _SC_SOCCER_EXCLUDE = ("player", "shot", "assist", "saves", "foul",
                              "offside", "penalt", "minute", "time of",
                              "to score in", "quick pick", "parlay",
                              "same game", "race to", "method", "interval",
                              "first/last", "1st corner", "first card",
                              "to receive", "goalkeeper", "each half",
                              "1st half", "2nd half", "- 1st", "- 2nd",
                              "halves", "either half", "combined",
                              "goalscorer &", "goalscorer /",
                              "team first goalscorer", "last goalscorer",
                              "either player", "any player", "outside",
                              "header", "tackle", "from behind",
                              "highest scoring", "3+ goals", "2+ goals")
        _SC_SOCCER_HINTS = ("score", "result", "goal", "half", "margin",
                            "total", "winner", "game lines", "moneyline",
                            "odd", "even", "1x2", "combo", "corner",
                            "card", "booking", "goalscorer", "clean sheet",
                            "spread", "handicap", "double chance",
                            "tie no bet", "bands", "multi")
        def _keep_soccer(sc):
            n = (sc.get("name") or "").lower()
            # 1st-half moneyline lives in "Moneyline - Halves (3-Way)" —
            # needed as the HT leg of HT/FT SGPs, so it survives the
            # halves/period exclusions below.
            if "moneyline - halves" in n:
                return True
            if any(h in n for h in _SC_SOCCER_EXCLUDE):
                return False
            return any(k in n for k in _SC_SOCCER_HINTS)
        subcats = [sc for sc in subcats if _keep_soccer(sc)]

    # Step 2: Select markets from the embedded SGP feed, keeping only those in
    # the subcategories retained above (no extra HTTP — the feed already carries
    # every market's selections inline). Each selection maps to a DK
    # calculateBets `id`, so pricing is unaffected by this change.
    kept_subcat_ids = {str(sc.get("id")) for sc in subcats}
    event_id_s = str(event_id)
    all_markets = []
    all_selections = []
    sel_by_mkt = {}

    for m in feed_markets:
        # The feed is single-event, but guard anyway.
        if str(m.get("eventId", event_id_s)) != event_id_s:
            continue
        cm = m.get("clientMetadata") or {}
        sub_id = cm.get("subCategoryId")
        sub_id = str(sub_id) if sub_id is not None else ""
        if sub_id not in kept_subcat_ids:
            continue
        m["_subCategoryName"] = subcat_name_by_id.get(sub_id, "")
        m["_subCategoryId"] = sub_id
        sels = m.get("selections", []) or []
        all_markets.append(m)
        mid = m.get("id", "")
        # Normalize each selection's marketId so downstream sel_by_mkt keys line
        # up (feed selections carry their own marketId, but be defensive).
        for s in sels:
            s.setdefault("marketId", mid)
        sel_by_mkt[mid] = sels
        all_selections.extend(sels)

    # Step 3: Build structured output
    # Pitcher prop detector: match against name AND subcategory AND market type.
    # Order matters — more specific matches first. Skip batter markets explicitly.
    PITCHER_KEYWORDS = ("strikeout", "earned run", "walks", "walk ", "hits allowed",
                        "pitching out", "pitcher", "outs recorded", "pitching strikeouts",
                        "outs o/u", "outs thrown")
    BATTER_HINTS = ("rbi", "total bases", "home run", "at bat", "stolen base", "singles",
                    "doubles", "triples", "batting")
    # Batter prop detector: complement of pitcher detector. A prop is batter
    # if its name/subcat/type blob is clearly batter-flavored AND lacks any
    # pitcher signal. "Walks"/"Hits" alone are ambiguous (pitcher walks-
    # allowed and batter walks both contain "walks"); the pitcher-keyword
    # exclusion disambiguates via the "allowed"/"pitching" qualifier.
    BATTER_KEYWORDS = ("hits", "runs", "rbi", "total bases", "home run",
                       "at bat", "stolen base", "singles", "doubles",
                       "triples", "walks", "batter", "hitter")
    props = []
    for m in all_markets:
        mname = m.get("name", "")
        mtype = m.get("marketType", {}).get("name", "")
        subcat = m.get("_subCategoryName", "")
        mid = m.get("id", "")
        m_sels = sel_by_mkt.get(mid, [])

        blob_lower = (mname + " " + mtype + " " + subcat).lower()
        # Only pitcher if pitcher keywords hit AND no batter hints
        is_pitcher = any(kw in blob_lower for kw in PITCHER_KEYWORDS) and \
                     not any(bh in blob_lower for bh in BATTER_HINTS)
        # Only batter if batter keywords hit AND no pitcher signal. The
        # "team total" / "1st inning" exclusion happens at subcat-keep time
        # for batter_only=True; here we additionally guard so a stray team-
        # total market that slipped through doesn't get tagged as batter.
        is_batter = (any(kw in blob_lower for kw in BATTER_KEYWORDS)
                     and not any(pkw in blob_lower for pkw in PITCHER_KEYWORDS)
                     and "team" not in blob_lower)
        # NBA player prop: one of our 4 supported stats in the market blob,
        # no team/game-line qualifier. The subcat-keep filter already drops
        # PRA / combo / quarter markets for nba_only scans; this guard is
        # the belt+suspenders for per-market classification.
        _NBA_STAT_KWS = ("points", "rebounds", "assists", "pointers",
                         "3-point", "three-point", "3 pt", "threes")
        _NBA_EXCLUDE = ("team", "quarter", "half", "1st", "2nd", "3rd", "4th",
                        "race to", "parlay", "double-double", "triple-double",
                        "pra", "steal", "block", "turnover", "combo")
        is_nba_prop = (any(kw in blob_lower for kw in _NBA_STAT_KWS)
                       and not any(ex in blob_lower for ex in _NBA_EXCLUDE)
                       and not is_pitcher and not is_batter)
        player_name = _extract_player_name(mname, mtype, m.get("_subCategoryName", ""))

        for s in m_sels:
            # Milestone selections (e.g. "5+", "4 or Fewer") omit outcomeType,
            # points, and players entirely — the threshold is in `label` and
            # `milestoneValue`, and the pitcher is in `participants`. Fall back
            # through those so milestone legs actually get matched downstream.
            outcome_type = s.get("outcomeType") or s.get("name") or s.get("label") or ""
            points = s.get("points")
            if points is None:
                points = s.get("milestoneValue")
            if points is None:
                # Last resort: parse an integer threshold out of the label text
                # (handles "5+", "5 or More", "4 or Fewer", etc.)
                label = s.get("label") or ""
                m_pts = re.search(r"\d+", label)
                if m_pts:
                    points = int(m_pts.group(0))
            display = f"{outcome_type} {points}" if points is not None else outcome_type
            sel_players = s.get("players") or s.get("participants") or []
            pname = sel_players[0].get("name", "") if sel_players else player_name

            props.append({
                "selectionId": s.get("id", ""),
                "marketId": mid,
                "marketName": mname,
                "marketType": mtype,
                "subcategory": m.get("_subCategoryName", ""),
                "player": pname,
                "participantRole": (sel_players[0].get("venueRole", "")
                                    if sel_players else ""),
                "outcomeType": outcome_type,
                "label": s.get("label", ""),
                # Full DK selection name / bet-slip line. For most markets this
                # duplicates the label, but some combos (e.g. EPL Half Time /
                # Full Time) put the only copy of the paired result here —
                # label is null and outcomeType is a single token — so the
                # soccer HT/FT matcher falls back to it.
                "betslipLine": s.get("betslipLine") or s.get("name") or "",
                "displayPoints": display,
                "points": points,
                "oddsAmerican": s.get("displayOdds", {}).get("american", ""),
                "oddsDecimal": s.get("trueOdds"),
                "isPitcherProp": is_pitcher,
                "isBatterProp": is_batter,
                "isNbaProp": is_nba_prop,
                "isDisabled": s.get("isDisabled", False),
            })

    return {
        "eventId": event_id,
        "totalMarkets": len(all_markets),
        "totalSelections": len(all_selections),
        "marketGroups": [{"id": mg["id"], "name": mg["name"], "count": mg.get("marketsCount", 0)} for mg in market_groups],
        "props": props,
    }


def _american_from_decimal(dec):
    if not dec or dec <= 1:
        return ""
    if dec >= 2:
        return f"+{round((dec - 1) * 100)}"
    return f"{round(-100 / (dec - 1))}"


# Rolling tally of calculateBets outcomes. When SGP pricing silently fails
# (every combo shows "no match"), this is the only way to see WHY from the
# API response without shell access to production — find_sgps_worldcup
# returns a snapshot as `sgp_price_diag`.
_PRICE_DIAG = {"calls": 0, "ok": 0, "incompatible": 0, "no_bet": 0,
               "exceptions": 0, "http": {}, "cookie_source": None, "abck": None,
               "breaker_tripped": False, "skipped_blocked": 0}

# calculateBets circuit breaker.
#
# When Akamai has scored the egress IP, EVERY pricing POST 403s — a validated
# cookie doesn't help (that is the "IP-flagged" case the soccer status line
# calls out). The sweep prices up to ~30 combos, each retried 4× with backoff,
# behind a 95s deadline, so a blocked IP spent the entire budget re-POSTing
# into the block and then reported rows as "deadline" — which reads as "slow,
# try again" when the truth is "this IP can't price, set DK_PROXY". Observed
# 2026-09-03: 27 of 29 calls 403, 103s elapsed, 87 rows marked deadline.
#
# So: once this many pricing 403s land back-to-back, stop POSTing for the rest
# of the process and report the rows honestly. ANY success resets the streak,
# which is what separates a hard block from mere rate-limiting — a flagged-but-
# not-blocked IP (a couple through, then a burst of 403s) keeps pricing instead
# of being written off after the first bad patch. Tune with
# DK_PRICE_BREAKER_403S; 0 disables the breaker entirely.
try:
    _PRICE_BREAKER_403S = int(_os.environ.get("DK_PRICE_BREAKER_403S", "12") or 12)
except ValueError:
    _PRICE_BREAKER_403S = 12
_price_breaker = {"streak": 0, "tripped": False}
_price_breaker_lock = threading.Lock()


def _price_blocked():
    """True once the breaker has tripped — callers should skip the POST."""
    if _PRICE_BREAKER_403S <= 0:
        return False
    with _price_breaker_lock:
        return _price_breaker["tripped"]


def _note_price_status(status):
    """Feed a pricing response's status to the breaker. 403 extends the streak
    (and trips at the threshold); anything else clears it, because a served
    response proves this IP can still price."""
    if _PRICE_BREAKER_403S <= 0:
        return
    with _price_breaker_lock:
        if status == 403:
            _price_breaker["streak"] += 1
            if (not _price_breaker["tripped"]
                    and _price_breaker["streak"] >= _PRICE_BREAKER_403S):
                _price_breaker["tripped"] = True
                _PRICE_DIAG["breaker_tripped"] = True
        else:
            _price_breaker["streak"] = 0


def _price_combo(selection_ids):
    """Call calculateBets for a list of selection IDs. Returns None on incompat/error."""
    # Blocked IP: skip the POST entirely rather than spend the caller's deadline
    # rediscovering the block once per combo.
    if _price_blocked():
        _PRICE_DIAG["skipped_blocked"] += 1
        return None
    _PRICE_DIAG["calls"] += 1
    try:
        payload = {
            "selections": [],
            "selectionsForYourBet": [{"id": sid, "yourBetGroup": 0} for sid in selection_ids],
            "selectionsForCombinator": [],
            "selectionsForProgressiveParlay": [],
            "oddsStyle": "american",
        }
        r = _post_with_retry(DK_PRICE, json=payload, timeout=10, headers=DK_PRICE_HEADERS)
        if r.status_code != 200:
            k = str(r.status_code)
            _PRICE_DIAG["http"][k] = _PRICE_DIAG["http"].get(k, 0) + 1
            return None
        data = r.json()
        if data.get("combinabilityRestrictions"):
            _PRICE_DIAG["incompatible"] += 1
            return None
        bet = next((b for b in data.get("bets", [])
                   if b.get("trueOdds") and len(b.get("selectionsMapped", [])) >= 2), None)
        if not bet:
            _PRICE_DIAG["no_bet"] += 1
            return None
        _PRICE_DIAG["ok"] += 1
        return {
            "sgpOdds": bet.get("displayOdds", ""),
            "sgpDecimal": bet.get("trueOdds"),
            "legInfo": data.get("selectionsForYourBet", []),
        }
    except Exception:
        _PRICE_DIAG["exceptions"] += 1
        return None


def get_featured(event_id):
    """Auto-build and price a handful of interesting SGPs for the game."""
    mkts_data = get_markets(event_id)
    props = mkts_data["props"]

    # Group props by player (only Over/Under O/U markets on pitcher props)
    by_player = {}
    for p in props:
        if not p["isPitcherProp"] or p["outcomeType"] not in ("Over", "Under"):
            continue
        # Only standard O/U markets (skip milestones which have no Over/Under semantics)
        if "O/U" not in p["subcategory"]:
            continue
        by_player.setdefault(p["player"], []).append(p)

    # Identify pitchers - they should each have an Over and Under
    pitchers = []
    for player, legs in by_player.items():
        over = next((l for l in legs if l["outcomeType"] == "Over"), None)
        under = next((l for l in legs if l["outcomeType"] == "Under"), None)
        if over and under and over["points"] == under["points"]:
            pitchers.append({"name": player, "over": over, "under": under, "line": over["points"]})

    # Also collect team total strikeout props
    team_total_k = []
    for p in props:
        if "Total" in p["marketName"] and "Strikeout" in p["marketName"] and p["outcomeType"] in ("Over", "Under"):
            team_total_k.append(p)

    # Build candidate SGPs
    candidates = []

    # Cross-pitcher combos: both starters Over, both Under, split directions
    if len(pitchers) >= 2:
        # Take the two most common (typically the starters)
        p1, p2 = pitchers[0], pitchers[1]
        candidates.append({
            "title": "Both Starters Over K's",
            "legs": [p1["over"], p2["over"]],
            "thesis": "Dominant pitching duel — both starters rack up strikeouts",
        })
        candidates.append({
            "title": "Both Starters Under K's",
            "legs": [p1["under"], p2["under"]],
            "thesis": "Bullpen game / both starters exit early",
        })
        candidates.append({
            "title": f"{p1['name']} Over + {p2['name']} Under K's",
            "legs": [p1["over"], p2["under"]],
            "thesis": f"{p1['name']} dominates, {p2['name']} struggles",
        })
        candidates.append({
            "title": f"{p1['name']} Under + {p2['name']} Over K's",
            "legs": [p1["under"], p2["over"]],
            "thesis": f"{p2['name']} dominates, {p1['name']} struggles",
        })

    # Individual pitcher + opposing team total K combos
    # (Pitcher K Over is positively correlated with opposing team K Total Over)
    for pitcher in pitchers[:2]:
        for tt in team_total_k[:2]:
            candidates.append({
                "title": f"{pitcher['name']} Over {pitcher['line']} K + {tt['marketName']} {tt['displayPoints']}",
                "legs": [pitcher["over"], tt],
                "thesis": f"{pitcher['name']} getting strikeouts correlates with team K total {tt['outcomeType'].lower()}",
            })

    # Limit to 6 candidates max
    candidates = candidates[:6]

    # Price all candidates in parallel
    def _price_candidate(c):
        sel_ids = [l["selectionId"] for l in c["legs"]]
        price = _price_combo(sel_ids)
        if not price:
            return None
        # Compute uncorrelated parlay price for comparison
        uncorr_dec = 1.0
        for l in c["legs"]:
            if l["oddsDecimal"]:
                uncorr_dec *= l["oddsDecimal"]
        return {
            "title": c["title"],
            "thesis": c["thesis"],
            "legs": [{
                "player": l["player"],
                "description": f"{l['displayPoints']} {l['subcategory'] or l['marketName']}",
                "selectionId": l["selectionId"],
                "oddsAmerican": l["oddsAmerican"],
                "oddsDecimal": l["oddsDecimal"],
            } for l in c["legs"]],
            "sgpOdds": price["sgpOdds"],
            "sgpDecimal": price["sgpDecimal"],
            "uncorrelatedOdds": _american_from_decimal(uncorr_dec),
            "uncorrelatedDecimal": uncorr_dec,
            "correlationFactor": price["sgpDecimal"] / uncorr_dec if uncorr_dec else None,
        }

    priced = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_price_candidate, c) for c in candidates]
        for f in as_completed(futs):
            try:
                result = f.result()
                if result:
                    priced.append(result)
            except Exception:
                pass

    # Sort by correlation factor (DK-loosened SGPs first — usually more interesting)
    priced.sort(key=lambda x: -(x.get("correlationFactor") or 0))

    return {
        "eventId": event_id,
        "pitchers": [{"name": p["name"], "line": p["line"]} for p in pitchers],
        "sgps": priced,
    }


def _normalize_name(n):
    """Normalize a player name for fuzzy matching."""
    n = (n or "").lower().strip()
    n = re.sub(r"[^a-z\s]", "", n)
    return " ".join(n.split())


def _pitcher_matches(name_a, name_b):
    """Fuzzy match two pitcher names. Handles 'Kris Bubic' vs 'K Bubic' vs 'kris bubic'."""
    a = _normalize_name(name_a)
    b = _normalize_name(name_b)
    if not a or not b:
        return False
    if a == b:
        return True
    a_parts = a.split()
    b_parts = b.split()
    if len(a_parts) >= 2 and len(b_parts) >= 2:
        # Last name match + first-letter match
        if a_parts[-1] == b_parts[-1] and a_parts[0][0] == b_parts[0][0]:
            return True
    # Last name only match (some OCR might drop first name)
    if len(a_parts) >= 1 and len(b_parts) >= 1 and a_parts[-1] == b_parts[-1] and len(a_parts[-1]) > 3:
        return True
    return False


def _stat_matches_market(stat_str, market_blob):
    """Check if the leg's stat type matches the DK market's name/subcategory."""
    stat_lower = stat_str.lower()
    # Strip "strikeout" from market so it doesn't pollute the outs check
    # (strikeouts contains "out" as a substring)
    market_lower = market_blob.lower()
    market_no_so = market_lower.replace("strikeouts", "").replace("strikeout", "")

    if "earned run" in stat_lower:
        return "earned run" in market_lower
    if "hits allowed" in stat_lower or stat_lower == "hits":
        return ("hits allowed" in market_lower or "hits" in market_lower) and \
               ("pitch" in market_lower or "allow" in market_lower or "pitcher" in market_lower)
    if "walk" in stat_lower:
        return "walk" in market_lower
    if "strikeout" in stat_lower:
        return "strikeout" in market_lower
    if "out" in stat_lower:
        # Any "outs" market — Pitching Outs, Outs Recorded, Total Outs, or just Outs
        # (strikeouts already filtered out above)
        return "outs" in market_no_so
    return False


def _stat_cat(leg):
    """Short stat category for a canonical leg string, used to canonicalize
    2-leg combo ordering so ("Over 4.5 SO", "Under 2.5 ER") always renders
    with the same leg first regardless of matched[] insertion order.
    Alphabetical over: BB < ER < H < OUTS < SO."""
    s = leg or ""
    if "Strikeout" in s:
        return "SO"
    if "Earned Run" in s:
        return "ER"
    if "Walk" in s:
        return "BB"
    if "Hit" in s:
        return "H"
    if "Out" in s:
        return "OUTS"
    return "ZZZ"


def _selection_direction(outcome_type):
    """Resolve a DK selection's outcomeType to 'Over' / 'Under', handling
    milestone selections whose outcomeType may be literal text like '5+' or
    '4 or Fewer' instead of the plain word."""
    if not outcome_type:
        return None
    ot = str(outcome_type).strip()
    if ot in ("Over", "Under"):
        return ot
    lo = ot.lower()
    if "fewer" in lo or "or less" in lo or "at most" in lo:
        return "Under"
    if "or more" in lo or "at least" in lo or ot.endswith("+"):
        return "Over"
    return None


def _match_leg_to_dk(leg, props, pitcher):
    """Given an OCR'd leg (dict with 'leg', 'avg_fv'), find the matching DK selection ID."""
    leg_str = leg.get("leg", "")
    # Parse: "Over 5.5 Strikeouts" → direction, line, stat
    parts = leg_str.split(None, 2)
    if len(parts) < 3:
        return None
    direction, line_str, stat_str = parts[0], parts[1], parts[2]
    try:
        line = float(line_str)
    except (ValueError, TypeError):
        return None

    # DK exposes pitcher Strikeouts / Hits Allowed as milestone markets (5+,
    # 4 or Fewer, …) as well as O/U markets. Over X.5 is equivalent to the
    # "X+1 or more" milestone; Under X.5 is equivalent to "X or fewer". So we
    # accept both the exact .5 line and the integer milestone threshold.
    if direction == "Over":
        accept_points = (line, line + 0.5)
    elif direction == "Under":
        accept_points = (line, line - 0.5)
    else:
        accept_points = (line,)

    for p in props:
        if not p.get("isPitcherProp"):
            continue
        if not _pitcher_matches(pitcher, p.get("player", "")):
            continue
        if _selection_direction(p.get("outcomeType")) != direction:
            continue
        pts = p.get("points")
        if pts is None or pts not in accept_points:
            continue
        blob = (p.get("marketName", "") + " " + p.get("subcategory", "") + " " + p.get("marketType", ""))
        if _stat_matches_market(stat_str, blob):
            return p.get("selectionId")
    return None


def _stat_matches_batter_market(stat_str, market_blob):
    """Batter version of _stat_matches_market. Caller has already scoped
    `market_blob` to a batter prop (via batter_only subcat filter), so we
    only need to disambiguate within batter stats. Stat strings here are
    the canonical leg labels emitted by the FV-sheet OCR normalizer:
    Hits, Runs, RBIs, Home Runs, Total Bases, Walks, Stolen Bases,
    Singles, Doubles, Triples."""
    s = (stat_str or "").lower().strip()
    m = (market_blob or "").lower()

    # Order matters: more specific stats first so "Total Bases" doesn't
    # collide with the bare "bases" in "Stolen Bases", and "Home Runs"
    # doesn't collide with plain "Runs".
    if "total base" in s or s == "tb":
        return "total base" in m
    if "home run" in s or s == "hr":
        return "home run" in m
    if "stolen base" in s or s == "sb":
        return "stolen base" in m
    if "single" in s or s == "1b":
        return "single" in m
    if "double" in s or s == "2b":
        return "double" in m
    if "triple" in s or s == "3b":
        return "triple" in m
    if "rbi" in s:
        return "rbi" in m
    if "walk" in s or s == "bb":
        return "walk" in m
    if s == "runs" or s == "r":
        # Plain runs — must NOT be Home Runs / RBIs (caller-side stat
        # already excluded those above; market side may still mention
        # "Home Runs" so guard here).
        return ("runs" in m) and ("home run" not in m) and ("rbi" not in m)
    if s == "hits" or s == "h":
        # Plain batter Hits market. The pitcher Hits-Allowed disambiguation
        # is upstream (subcat filter) — within batter scope, "hits" is hits.
        return "hits" in m
    return False


def _match_leg_to_dk_batter(leg_str, props, player):
    """Batter analog of _match_leg_to_dk. Same .5 O/U ↔ integer-milestone
    equivalence as the pitcher path: Over 0.5 Hits ≡ "1+ Hits"; Under 1.5
    Total Bases ≡ "1 or Fewer Total Bases".

    Returns a dict { selection_id, direction, points, stat_str,
    over_american, under_american, market_blob } or None when the primary
    leg can't be matched. over_american / under_american are ints when
    DK offers that side at the matched threshold (used by hybrid-mode
    no-vig), else None. Callers expecting just the legacy selection-id
    string should read `.selection_id` off the dict.

    Hybrid mode (commit plan #1) needs BOTH sides of the matched
    threshold to compute no-vig fair probability on the missing-FV leg,
    so we do the opposite-direction lookup here once and cache both
    onto the return dict rather than scanning props[] twice downstream."""
    parts = (leg_str or "").split(None, 2)
    if len(parts) < 3:
        return None
    direction, line_str, stat_str = parts[0], parts[1], parts[2]
    try:
        line = float(line_str)
    except (ValueError, TypeError):
        return None

    if direction == "Over":
        accept_points = (line, line + 0.5)
    elif direction == "Under":
        accept_points = (line, line - 0.5)
    else:
        accept_points = (line,)

    def _american_of(sel):
        """Parse '+250'/'−140'/'140' into an int, or None."""
        raw = (sel or {}).get("oddsAmerican") or ""
        if not raw:
            return None
        s = str(raw).replace("−", "-").replace("+", "").strip()
        try:
            return int(s)
        except (ValueError, TypeError):
            return None

    # Two-pass match. DK offers most batter stats in BOTH a milestone
    # form ("1+ Hits" at points=1) and a two-way O/U form ("Hits O/U"
    # Over 0.5 at points=0.5). For hybrid-mode no-vig we need the
    # two-way variant so the opposite-direction lookup succeeds. Prefer
    # subcategories containing "O/U" on the first pass; fall back to any
    # match on the second. Full-FV candidates don't care which flavor
    # gets picked — any priced selectionId works for calculateBets.
    def _scan(prefer_two_way):
        for p in props:
            if not p.get("isBatterProp"):
                continue
            if not _pitcher_matches(player, p.get("player", "")):
                continue
            if _selection_direction(p.get("outcomeType")) != direction:
                continue
            pts = p.get("points")
            if pts is None or pts not in accept_points:
                continue
            subcat = (p.get("subcategory") or "")
            if prefer_two_way and ("o/u" not in subcat.lower()):
                continue
            blob = (p.get("marketName", "") + " " + subcat + " " + p.get("marketType", ""))
            if _stat_matches_batter_market(stat_str, blob):
                return p
        return None

    matched = _scan(prefer_two_way=True) or _scan(prefer_two_way=False)

    if not matched:
        return None

    # Find the opposite-direction selection at the SAME matched points
    # value. Must be same player + same stat-market blob + same threshold
    # + same subcategory (so we don't cross-match a milestone 2+ partner
    # against an O/U Over 1.5 primary). If DK only priced one side (common
    # on milestone-only markets), this lookup returns None and the
    # caller's hybrid-mode skip path kicks in.
    opposite_dir = "Under" if direction == "Over" else "Over"
    matched_pts = matched.get("points")
    matched_subcat = matched.get("subcategory") or ""
    opp = None
    for p in props:
        if not p.get("isBatterProp"):
            continue
        if not _pitcher_matches(player, p.get("player", "")):
            continue
        if _selection_direction(p.get("outcomeType")) != opposite_dir:
            continue
        if p.get("points") != matched_pts:
            continue
        if (p.get("subcategory") or "") != matched_subcat:
            continue
        blob = (p.get("marketName", "") + " " + p.get("subcategory", "") + " " + p.get("marketType", ""))
        if _stat_matches_batter_market(stat_str, blob):
            opp = p
            break

    matched_am = _american_of(matched)
    opp_am = _american_of(opp) if opp else None
    over_am  = matched_am if direction == "Over"  else opp_am
    under_am = matched_am if direction == "Under" else opp_am

    return {
        "selection_id":     matched.get("selectionId"),
        "direction":        direction,
        "points":           matched_pts,
        "stat_str":         stat_str,
        "over_american":    over_am,
        "under_american":   under_am,
        "opposite_selection_id": (opp.get("selectionId") if opp else None),
    }


def _normalize_team(name):
    """Normalize a team string to a comparable token. Phase-1 teammate data
    uses full city + nickname ("San Francisco Giants"); DK exposes the same
    under homeTeam/awayTeam. Lowercase + strip non-alpha covers the "St."
    vs "Saint" / "A's" vs "As" edge cases."""
    n = (name or "").lower()
    n = re.sub(r"[^a-z0-9 ]+", "", n)
    return " ".join(n.split())


# Tokens that are city prefixes (NOT part of the nickname). Includes both
# full city words ("kansas", "city", "los", "angeles") and DK's 2-3 letter
# city codes ("kc", "laa", "wsh"). Anything not in this set is treated as a
# nickname token. Lets us treat "Kansas City Royals" / "KC Royals" / "Royals"
# as the same team without an alias table.
_TEAM_CITY_TOKENS = {
    "arizona","atlanta","baltimore","boston","chicago","cincinnati",
    "cleveland","colorado","detroit","houston","kansas","city","la",
    "los","angeles","miami","milwaukee","minnesota","new","york",
    "oakland","philadelphia","pittsburgh","san","diego","francisco",
    "seattle","st","saint","louis","tampa","bay","texas","toronto",
    "washington",
    "ari","atl","bal","bos","chc","cws","cin","cle","col","det",
    "hou","kc","laa","lad","mia","mil","min","nym","nyy","ath","oak",
    "phi","pit","sd","sf","sea","stl","tb","tex","tor","wsh","was",
}


def _team_nickname(name):
    """Extract a comparable nickname from a team string. Strips city
    prefix (full words or DK short codes) and returns the remainder.
    Examples:
      'Kansas City Royals' -> 'royals'
      'KC Royals'           -> 'royals'
      'Boston Red Sox'      -> 'red sox'
      'BOS Red Sox'         -> 'red sox'
      'Athletics'           -> 'athletics'
      'Diamondbacks'        -> 'diamondbacks'
    """
    n = _normalize_team(name)
    if not n:
        return ""
    tokens = n.split()
    for i, t in enumerate(tokens):
        if t not in _TEAM_CITY_TOKENS:
            return " ".join(tokens[i:])
    return tokens[-1]  # all-city fallback (shouldn't happen for real team names)


def _team_in_event(team_str, event):
    """Match a Phase-1 team string against a DK event. Returns 'home',
    'away', or None. Compares on nickname so "Kansas City Royals" vs
    "KC Royals" / "Royals" all collapse to 'royals'."""
    nick = _team_nickname(team_str)
    if not nick:
        return None
    home_full_nick = _team_nickname(event.get("homeTeam"))
    away_full_nick = _team_nickname(event.get("awayTeam"))
    home_short_nick = _team_nickname(event.get("homeShort"))
    away_short_nick = _team_nickname(event.get("awayShort"))
    if nick and nick in (home_full_nick, home_short_nick):
        return "home"
    if nick and nick in (away_full_nick, away_short_nick):
        return "away"
    return None


def find_sgps_teammate(payload):
    """Price a batch of teammate 2-leg SGP candidates against DraftKings.

    Input shape (passed via stdin JSON):
      {
        "candidates": [
          {
            "id": "<arbitrary frontend handle>",     # echoed back; used to align response rows
            "team": "Kansas City Royals",            # full team name from Phase-1 teammate dataset
            "player_a": "Bobby Witt Jr.",
            "leg_a":    "Over 0.5 Hits",             # canonical leg string (same shape as pitcher side)
            "player_b": "Salvador Perez",
            "leg_b":    "Over 0.5 RBIs"
          },
          ...
        ]
      }

    Output:
      {
        "results": [
          {
            "id": ...,
            "event_id": "...",
            "game_name": "...",
            "matched": true|false,
            "missing": ["player_a leg_a", ...],   # only present when matched=false
            "dk_odds": "+350",                     # only present when matched=true
            "dk_decimal": 4.5,
            "selection_a": "...",
            "selection_b": "..."
          }, ...
        ],
        "events_scanned": [eid, ...],
        "team_event_map": { "<team>": eid|null },
        "truncated": bool
      }

    Invariants:
      - Each unique team is scanned exactly once (via batter_only get_markets).
      - Each unique (player, leg) is matched to a selectionId exactly once.
      - Each unique unordered (sel_a, sel_b) pair is priced at most once;
        candidates that map to the same pair share the price.
      - Soft 110s deadline mirrors find_sgps; whatever is missing comes back
        as matched=false rather than failing the whole request.
    """
    from itertools import combinations  # noqa: F401  (kept for future expansion)
    import concurrent.futures

    pricing_deadline = _time.monotonic() + 110.0
    truncated = False

    candidates = (payload or {}).get("candidates", []) or []
    if not isinstance(candidates, list) or not candidates:
        return {"error": "candidates array required"}

    # Dedupe teams.
    needed_teams = []
    seen_teams = set()
    for c in candidates:
        t = c.get("team")
        if not t:
            continue
        nt = _normalize_team(t)
        if nt in seen_teams:
            continue
        seen_teams.add(nt)
        needed_teams.append(t)

    # Resolve team → DK event.
    try:
        games_data = get_games()
    except Exception as e:
        return {"error": f"DK games endpoint unavailable: {e}. Try again in a moment."}
    events = [e for e in games_data["events"] if e.get("hasSGP")]

    team_event_map = {}
    for t in needed_teams:
        chosen = None
        for e in events:
            if _team_in_event(t, e):
                chosen = e["id"]
                break
        team_event_map[t] = chosen

    needed_event_ids = sorted({eid for eid in team_event_map.values() if eid})

    # Scan markets per event in parallel. Same low max_workers (and the
    # nested batter_only get_markets uses its own workers=2) so effective
    # concurrency against DK stays at 4 — the level pitcher find_sgps
    # established as safe against Akamai's 403 cascade.
    event_markets = {}
    def scan(eid):
        try:
            md = get_markets(eid, batter_only=True)
            return eid, md
        except Exception as ex:
            sys.stderr.write(f"dk_api: teammate event {eid} scan failed: {ex}\n")
            return eid, None

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(scan, eid): eid for eid in needed_event_ids}
        for fut in as_completed(futs):
            eid, md = fut.result()
            if md is not None:
                event_markets[eid] = md

    # Match each unique (event, player, leg) to a DK match-record exactly
    # once. match-record is a dict with selection_id + per-leg over/under
    # American odds (needed by the client for hybrid-mode no-vig on a
    # missing-FV leg). See _match_leg_to_dk_batter.
    leg_match_cache = {}  # key: (eid, player_norm, leg_str) -> match-record | None

    def match_leg(eid, player, leg_str):
        if not eid or eid not in event_markets:
            return None
        key = (eid, _normalize_name(player), leg_str)
        if key in leg_match_cache:
            return leg_match_cache[key]
        m = _match_leg_to_dk_batter(leg_str, event_markets[eid]["props"], player)
        leg_match_cache[key] = m
        return m

    # Resolve every candidate to a (sel_a, sel_b) pair + both legs'
    # match-records so the response can carry per-leg over/under prices.
    resolved = []  # parallel to `candidates`
    for c in candidates:
        team = c.get("team")
        eid = team_event_map.get(team)
        game_info = next((e for e in events if e["id"] == eid), {}) if eid else {}
        ma = match_leg(eid, c.get("player_a"), c.get("leg_a")) if eid else None
        mb = match_leg(eid, c.get("player_b"), c.get("leg_b")) if eid else None
        sa = ma["selection_id"] if ma else None
        sb = mb["selection_id"] if mb else None
        missing = []
        if not eid:
            missing.append(f"team:{team}")
        else:
            if not sa:
                missing.append(f"{c.get('player_a')} :: {c.get('leg_a')}")
            if not sb:
                missing.append(f"{c.get('player_b')} :: {c.get('leg_b')}")
        resolved.append({
            "id": c.get("id"),
            "event_id": eid,
            "game_name": game_info.get("name", "") if eid else "",
            "selection_a": sa,
            "selection_b": sb,
            "match_a": ma,
            "match_b": mb,
            "missing": missing,
        })

    # Dedupe pricing on the unordered selection pair.
    price_cache = {}  # key: frozenset({sa, sb}) -> price dict|None|"pending"
    pricing_jobs = []
    for r in resolved:
        if not r["selection_a"] or not r["selection_b"]:
            continue
        if r["selection_a"] == r["selection_b"]:
            continue  # same selection used twice would fail calculateBets anyway
        key = frozenset({r["selection_a"], r["selection_b"]})
        if key in price_cache:
            continue
        price_cache[key] = "pending"
        pricing_jobs.append((key, r["selection_a"], r["selection_b"]))

    def price_one(key, sa, sb):
        return key, _price_combo([sa, sb])

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(price_one, *job) for job in pricing_jobs]
        remaining = max(0.5, pricing_deadline - _time.monotonic())
        try:
            for f in as_completed(futs, timeout=remaining):
                try:
                    key, price = f.result()
                    price_cache[key] = price  # may be None on incompat / DK error
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            truncated = True
            for f in futs:
                f.cancel()

    # Build response rows. Per-leg over/under American odds surface on
    # every matched result regardless of hybrid vs full-FV usage — the
    # client decides which prices it needs based on its own FV coverage.
    # Carrying both sides of both legs costs ~16 bytes per candidate in
    # the JSON payload; trivially small next to the SGP pricing calls
    # this function already makes.
    results = []
    for src, r in zip(candidates, resolved):
        ma = r.get("match_a") or {}
        mb = r.get("match_b") or {}
        out = {
            "id": r["id"],
            "event_id": r["event_id"],
            "game_name": r["game_name"],
            "team": src.get("team"),
            "player_a": src.get("player_a"),
            "leg_a": src.get("leg_a"),
            "player_b": src.get("player_b"),
            "leg_b": src.get("leg_b"),
            "selection_a": r["selection_a"],
            "selection_b": r["selection_b"],
            # Per-leg DK prices (for hybrid-mode no-vig). None when the
            # matched prop had no opposite-direction selection priced on
            # DK — caller's hybrid path then skips the candidate.
            "leg_a_over_american":  ma.get("over_american"),
            "leg_a_under_american": ma.get("under_american"),
            "leg_b_over_american":  mb.get("over_american"),
            "leg_b_under_american": mb.get("under_american"),
        }
        if r["missing"]:
            out["matched"] = False
            out["missing"] = r["missing"]
            results.append(out)
            continue
        key = frozenset({r["selection_a"], r["selection_b"]})
        price = price_cache.get(key)
        if price in (None, "pending"):
            out["matched"] = False
            out["missing"] = ["dk:price_unavailable"]
            results.append(out)
            continue
        out["matched"] = True
        out["dk_odds"] = price["sgpOdds"]
        out["dk_decimal"] = price["sgpDecimal"]
        results.append(out)

    response = {
        "results": results,
        "events_scanned": needed_event_ids,
        "team_event_map": team_event_map,
    }
    if truncated:
        response["truncated"] = True
    return response


def _stat_matches_market_nba(stat_str, market_blob):
    """NBA stat → market blob matcher. Caller has already scoped
    `market_blob` to an NBA player prop via the nba_only subcat filter
    + isNbaProp check, so this only disambiguates within the 4 supported
    stats. Order matters: 3-Pointers Made first so a bare "points" match
    doesn't grab 3-point markets. Canonical stat_str values come from the
    nbaEvTab.js enumerator: Points, Rebounds, Assists, 3-Pointers Made."""
    s = (stat_str or "").lower().strip()
    m = (market_blob or "").lower()
    # 3-Pointers Made has many DK spellings. Check for any of them first.
    if "3-pointer" in s or "3-point" in s or "three" in s or s == "3pm":
        return ("3-point" in m or "3 point" in m or "threes" in m
                or "pointers" in m or "3pt" in m or "3 pt" in m)
    if s == "points":
        # Plain Points — must NOT be 3-Point, PRA, or a combo market. We
        # exclude "rebound"/"assist" substrings because DK sometimes
        # emits combo markets (PRA, PR) under Points subcats.
        return ("point" in m
                and "3-point" not in m and "3 point" not in m
                and "three" not in m and "pointers" not in m
                and "rebound" not in m and "assist" not in m)
    if s == "rebounds":
        return "rebound" in m and "assist" not in m and "point" not in m
    if s == "assists":
        return "assist" in m and "rebound" not in m and "point" not in m
    return False


def _match_leg_to_dk_nba(player, prop, side, line, props):
    """NBA analog of _match_leg_to_dk_batter. Takes structured inputs
    directly — nbaEvTab.js emits (player, prop, side, line) fields, not
    the "Over 0.5 Hits" composite string the MLB paths parse, so
    building a string and re-parsing would be a needless round-trip.

    Line matching is exact (points == line). NBA doesn't use the
    .5 ↔ milestone equivalence MLB has; line-approximation already
    happened upstream in nbaEvTab.js's line-ignorant enumerator (the
    candidate here has the FV line; the caller wants DK's selectionId
    at that exact line, if DK offers it).

    Returns a dict { selection_id, direction, points, prop,
    over_american, under_american, opposite_selection_id } when DK has
    the leg + an opposite-direction partner at the same points/subcat.
    Returns None if DK doesn't offer the primary leg. The opposite-
    direction side may still be absent (opp_american=None) — the
    caller's no-vig path handles that."""
    if not prop or side not in ("over", "under") or line is None:
        return None
    try:
        line = float(line)
    except (ValueError, TypeError):
        return None
    direction = "Over" if side == "over" else "Under"

    def _american_of(sel):
        raw = (sel or {}).get("oddsAmerican") or ""
        if not raw:
            return None
        t = str(raw).replace("−", "-").replace("+", "").strip()
        try:
            return int(t)
        except (ValueError, TypeError):
            return None

    matched = None
    for p in props:
        if not p.get("isNbaProp"):
            continue
        if not _pitcher_matches(player, p.get("player", "")):
            continue
        if _selection_direction(p.get("outcomeType")) != direction:
            continue
        pts = p.get("points")
        try:
            if pts is None or float(pts) != line:
                continue
        except (ValueError, TypeError):
            continue
        blob = (p.get("marketName", "") + " " + p.get("subcategory", "") + " " + p.get("marketType", ""))
        if _stat_matches_market_nba(prop, blob):
            matched = p
            break
    if not matched:
        return None

    # Opposite-direction lookup at the same (points, subcat) for no-vig.
    opposite_dir = "Under" if direction == "Over" else "Over"
    matched_pts = matched.get("points")
    matched_subcat = matched.get("subcategory") or ""
    opp = None
    for p in props:
        if not p.get("isNbaProp"):
            continue
        if not _pitcher_matches(player, p.get("player", "")):
            continue
        if _selection_direction(p.get("outcomeType")) != opposite_dir:
            continue
        if p.get("points") != matched_pts:
            continue
        if (p.get("subcategory") or "") != matched_subcat:
            continue
        blob = (p.get("marketName", "") + " " + p.get("subcategory", "") + " " + p.get("marketType", ""))
        if _stat_matches_market_nba(prop, blob):
            opp = p
            break

    matched_am = _american_of(matched)
    opp_am = _american_of(opp) if opp else None
    over_am  = matched_am if direction == "Over"  else opp_am
    under_am = matched_am if direction == "Under" else opp_am
    return {
        "selection_id":     matched.get("selectionId"),
        "direction":        direction,
        "points":           matched_pts,
        "prop":             prop,
        "over_american":    over_am,
        "under_american":   under_am,
        "opposite_selection_id": (opp.get("selectionId") if opp else None),
    }


def _norm_team_nba(s):
    """Lowercase, strip non-alphanumeric, collapse whitespace. Used to
    compare NBA team names across FV-sheet formats (short codes,
    nickname, full-city-plus-nickname) without a fragile equality check."""
    if not s:
        return ""
    s = re.sub(r"[^a-z0-9 ]+", " ", str(s).lower())
    return " ".join(s.split())


def _event_for_nba_candidate(c, events):
    """Resolve an NBA candidate → DK event. FV sheets in the wild use
    three formats for the team/game columns:

      1. Short codes: team="PHI", game="PHI@BOS"
      2. Nicknames:   team="76ers", game="76ers @ Celtics"
      3. Full names:  team="Philadelphia 76ers", game="Philadelphia 76ers @ Boston Celtics"

    Try all three against each DK event's homeShort / awayShort /
    homeTeam / awayTeam. Substring match in both directions on the
    team-field path so "76ers" matches "philadelphia 76ers" and
    vice versa. Game-string path checks that every token of both
    teams' full-name forms appears in the normalized game string —
    robust against punctuation and "@" / "vs" / "at" separators.

    Module-level (not a closure inside find_sgps_nba) so the unit
    tests can exercise it without spinning up a full pricing request
    that would hit DK over the network. Returns the event dict or None."""
    team_raw = (c.get("team") or "").strip()
    game_raw = (c.get("game") or "").strip()
    tn = _norm_team_nba(team_raw)
    gn = _norm_team_nba(game_raw)

    if tn:
        for e in events:
            hs = (e.get("homeShort") or "").lower()
            as_ = (e.get("awayShort") or "").lower()
            ht = _norm_team_nba(e.get("homeTeam"))
            at = _norm_team_nba(e.get("awayTeam"))
            if tn == hs or tn == as_:
                return e
            if ht and (tn in ht or ht in tn):
                return e
            if at and (tn in at or at in tn):
                return e
    if gn:
        # gn is already normalized: lowercased, non-alnum stripped to space,
        # whitespace collapsed. So "PHI@BOS" → "phi bos", "PHI vs BOS" →
        # "phi vs bos", "Philadelphia 76ers @ Boston Celtics" →
        # "philadelphia 76ers boston celtics". Split on whitespace and
        # drop the common connector tokens so both short-code and
        # full-name game strings flow through the same splitter.
        #
        # NOTE: earlier attempt used re.split(r"[@vs\s]+", gn) which is a
        # character class — splits on v OR s individually, so "phi bos"
        # became ["phi", "bo"] (the 's' got eaten). Char-class regex is
        # the wrong tool for multi-character separators.
        parts = [p for p in gn.split() if p not in ("vs", "at", "v")]
        if len(parts) == 2 and all(len(p) <= 4 for p in parts):
            want = {parts[0], parts[1]}
            for e in events:
                have = {(e.get("homeShort") or "").lower(), (e.get("awayShort") or "").lower()}
                if want == have:
                    return e
        for e in events:
            ht = _norm_team_nba(e.get("homeTeam"))
            at = _norm_team_nba(e.get("awayTeam"))
            if not ht or not at:
                continue
            if all(tok in gn for tok in ht.split()) and all(tok in gn for tok in at.split()):
                return e
    return None


def find_sgps_nba(payload):
    """Price a batch of NBA same-player 2-leg SGP candidates against DK.

    Input shape (passed via stdin JSON):
      {
        "candidates": [
          {
            "id": "<frontend candidate handle>",   # echoed back
            "player": "Donovan Mitchell",
            "game":   "CLE@BOS",                   # optional, tiebreaker
            "team":   "CLE",                       # optional, tiebreaker
            "prop1":  "Points", "side1": "over", "line1": 27.5,
            "prop2":  "Rebounds", "side2": "over", "line2": 4.5
          }, ...
        ]
      }

    Output (mirrors find_sgps_teammate shape so nbaEvTab.js can reuse
    the same merge logic):
      {
        "results": [
          { "id", "event_id", "game_name", "matched": bool,
            "missing": [...],                   # when matched=false
            "dk_odds": "+275", "dk_decimal": 3.75,
            "selection_1", "selection_2",
            "leg_1_over_american", "leg_1_under_american",
            "leg_2_over_american", "leg_2_under_american"
          }, ...
        ],
        "events_scanned": [...]
      }

    Flow:
      1. Resolve each candidate to a DK NBA event via team short code
         or game-string parse.
      2. Scan each unique needed event's markets with nba_only=True
         (Akamai-safe max_workers=2 same as teammate path).
      3. Match each candidate's two legs to DK selectionIds via
         _match_leg_to_dk_nba. Per-(event, player, prop, side, line)
         results cached so repeated lookups are free.
      4. Dedupe pairs (unordered selection_1/selection_2) and price
         once via _price_combo. 110s soft deadline — whatever isn't
         priced by then comes back as matched=false truncated=true.
      5. Response rows carry per-leg over/under American odds so the
         client's no-vig path has both sides when available.
    """
    import concurrent.futures
    candidates = (payload or {}).get("candidates", []) or []
    if not isinstance(candidates, list) or not candidates:
        return {"error": "candidates array required"}

    # Step 1: resolve candidate → event via team/game.
    try:
        games_data = get_games_nba()
    except Exception as e:
        return {"error": f"DK NBA games endpoint unavailable: {e}. Try again in a moment."}
    events = [e for e in games_data["events"] if e.get("hasSGP")]

    cand_event_map = {}   # cand id -> event dict (or None)
    for c in candidates:
        cand_event_map[c.get("id")] = _event_for_nba_candidate(c, events)

    # Step 2: scan each unique event's NBA markets in parallel.
    needed_eids = sorted({(e or {}).get("id") for e in cand_event_map.values() if e and e.get("id")})
    event_markets = {}
    def _scan(eid):
        try:
            return eid, get_markets(eid, nba_only=True)
        except Exception as ex:
            sys.stderr.write(f"dk_api: nba event {eid} scan failed: {ex}\n")
            return eid, None
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(_scan, eid): eid for eid in needed_eids}
        for fut in as_completed(futs):
            eid, md = fut.result()
            if md is not None:
                event_markets[eid] = md

    # Step 3: match each candidate's two legs. Cache by (eid, player,
    # prop, side, line) — candidates that share a leg reuse the match.
    leg_cache = {}
    def _match(eid, player, prop, side, line):
        if not eid or eid not in event_markets:
            return None
        key = (eid, _normalize_name(player or ""), prop, side, line)
        if key in leg_cache:
            return leg_cache[key]
        m = _match_leg_to_dk_nba(player, prop, side, line, event_markets[eid]["props"])
        leg_cache[key] = m
        return m

    resolved = []
    for c in candidates:
        e = cand_event_map.get(c.get("id")) or {}
        eid = e.get("id")
        m1 = _match(eid, c.get("player"), c.get("prop1"), c.get("side1"), c.get("line1"))
        m2 = _match(eid, c.get("player"), c.get("prop2"), c.get("side2"), c.get("line2"))
        s1 = m1["selection_id"] if m1 else None
        s2 = m2["selection_id"] if m2 else None
        missing = []
        if not eid:
            # Include a sample of available DK events so the user can tell
            # apart "my team/game string didn't match anything DK has" from
            # "DK returned 0 NBA events (wrong league ID, off-season, etc.)".
            avail = ", ".join(
                f"{(e.get('awayShort') or '?')}@{(e.get('homeShort') or '?')}"
                for e in events[:6]
            )
            hint = f" (dk events: {avail})" if avail else " (dk events: none — check league ID / slate)"
            missing.append(f"event:{c.get('team') or c.get('game') or '(no team/game)'}{hint}")
        else:
            if not s1: missing.append(f"leg1:{c.get('player')} :: {c.get('side1')} {c.get('line1')} {c.get('prop1')}")
            if not s2: missing.append(f"leg2:{c.get('player')} :: {c.get('side2')} {c.get('line2')} {c.get('prop2')}")
        resolved.append({"src": c, "event_id": eid, "game_name": e.get("name", "") if eid else "",
                         "selection_1": s1, "selection_2": s2, "match_1": m1, "match_2": m2, "missing": missing})

    # Step 4: dedupe + price unordered pairs.
    price_cache = {}
    pricing_jobs = []
    for r in resolved:
        if not r["selection_1"] or not r["selection_2"] or r["selection_1"] == r["selection_2"]:
            continue
        key = frozenset({r["selection_1"], r["selection_2"]})
        if key in price_cache:
            continue
        price_cache[key] = "pending"
        pricing_jobs.append((key, r["selection_1"], r["selection_2"]))

    truncated = False
    deadline = _time.monotonic() + 110.0
    def _price_one(job):
        k, sa, sb = job
        return k, _price_combo([sa, sb])
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(_price_one, j) for j in pricing_jobs]
        remaining = max(0.5, deadline - _time.monotonic())
        try:
            for f in as_completed(futs, timeout=remaining):
                try:
                    k, price = f.result()
                    price_cache[k] = price
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            truncated = True
            for f in futs:
                f.cancel()

    # Step 5: build response.
    results = []
    for r in resolved:
        c = r["src"]
        m1 = r.get("match_1") or {}
        m2 = r.get("match_2") or {}
        out = {
            "id": c.get("id"), "event_id": r["event_id"], "game_name": r["game_name"],
            "player": c.get("player"),
            "prop1": c.get("prop1"), "side1": c.get("side1"), "line1": c.get("line1"),
            "prop2": c.get("prop2"), "side2": c.get("side2"), "line2": c.get("line2"),
            "selection_1": r["selection_1"], "selection_2": r["selection_2"],
            "leg_1_over_american":  m1.get("over_american"),
            "leg_1_under_american": m1.get("under_american"),
            "leg_2_over_american":  m2.get("over_american"),
            "leg_2_under_american": m2.get("under_american"),
        }
        if r["missing"]:
            out["matched"] = False
            out["missing"] = r["missing"]
            results.append(out)
            continue
        key = frozenset({r["selection_1"], r["selection_2"]})
        price = price_cache.get(key)
        if price in (None, "pending"):
            out["matched"] = False
            out["missing"] = ["dk:price_unavailable"]
            results.append(out)
            continue
        out["matched"] = True
        out["dk_odds"] = price["sgpOdds"]
        out["dk_decimal"] = price["sgpDecimal"]
        results.append(out)

    response = {"results": results, "events_scanned": needed_eids}
    if truncated:
        response["truncated"] = True
    return response


# ===== Tennis (men's French Open) SGP pricing =====
#
# Build target per the user's spec:
#   leg 1 — "Over X.5 1st Set Total"          (X in {8.5, 9.5, 10.5, 12.5})
#   leg 2 — "<Underdog Player> +Y.5 Game Handicap"  (full-match games spread, dog side)
#
# Correlations are hardcoded client-side (sport-wide priors for men's
# ATP grand slam). We just resolve DK selection IDs + price the combo
# here; the joint/EV math runs in the browser via sgpMath.js.

_TENNIS_SET1_KEYWORDS = ("1st set", "first set")
_TENNIS_SET_TOTAL_KEYWORDS = ("total", "games")
_TENNIS_HANDICAP_KEYWORDS = ("game handicap", "games handicap",
                              "match handicap", "handicap")


def _is_tennis_set1_total_market(market_blob):
    """True iff this DK market is the 1st-Set total-games market."""
    name = (market_blob.get("marketName") or market_blob.get("name") or "").lower()
    mtype = (market_blob.get("marketTypeName") or "").lower()
    subcat = (market_blob.get("subcategory") or "").lower()
    blob = " ".join([name, mtype, subcat])
    if not any(k in blob for k in _TENNIS_SET1_KEYWORDS):
        return False
    if "total" not in blob and "games" not in blob:
        return False
    # Filter out 1st-set winner/spread markets that mention "1st set"
    # but aren't totals.
    if "winner" in blob or "to win" in blob:
        return False
    # 1st-set spread/handicap is a different market.
    if "handicap" in blob or "spread" in blob:
        return False
    return True


def _is_tennis_match_handicap_market(market_blob):
    """True iff this DK market is the full-match game handicap (per player).
    DK exposes this as marketName/subcategory "Games Spread" (not "Handicap").
    The 1st-set version is "1st Set Game Spread" — explicitly excluded."""
    name = (market_blob.get("marketName") or market_blob.get("name") or "").lower()
    mtype = (market_blob.get("marketTypeName") or market_blob.get("marketType") or "").lower()
    subcat = (market_blob.get("subcategory") or "").lower()
    blob = " ".join([name, mtype, subcat])
    if "1st set" in blob or "first set" in blob or "set total" in blob:
        return False
    if "set handicap" in blob or "set game spread" in blob:
        # Per-set spread, not the full-match games spread. Skip.
        return False
    return ("games spread" in blob
            or "game handicap" in blob or "games handicap" in blob
            or "match handicap" in blob
            or ("handicap" in blob and "games" in blob))


def _match_tennis_set1_total(line, side, props):
    """Find the DK selection for Over/Under <line> 1st Set Total.
    Returns dict with selection_id + over/under american odds, or None."""
    side_l = (side or "").lower()
    line_f = float(line)
    best = None
    for p in props:
        if not _is_tennis_set1_total_market(p):
            continue
        try:
            pts = float(p.get("points"))
        except (TypeError, ValueError):
            continue
        if abs(pts - line_f) > 0.01:
            continue
        otype = (p.get("outcomeType") or "").lower()
        if otype != side_l:
            continue
        best = {
            "selection_id": p.get("selectionId"),
            "line": pts,
            "side": otype,
            "market_name": p.get("marketName", ""),
            "american": p.get("oddsAmerican"),
        }
        # Capture sibling Over/Under for client-side no-vig if present.
        sibling = "under" if side_l == "over" else "over"
        sib = next((q for q in props
                    if _is_tennis_set1_total_market(q)
                    and (q.get("outcomeType") or "").lower() == sibling
                    and abs(float(q.get("points") or 0) - pts) < 0.01), None)
        best["over_american"]  = p.get("oddsAmerican") if side_l == "over"  else (sib or {}).get("oddsAmerican")
        best["under_american"] = p.get("oddsAmerican") if side_l == "under" else (sib or {}).get("oddsAmerican")
        return best
    return best


def _match_tennis_match_handicap(player_name, line, props):
    """Find the DK selection for <player> +<line> Game Handicap.
    Returns dict with selection_id + american odds, or None.
    Player matching is normalized so "M. Berrettini" matches "Matteo Berrettini"
    (DK's canonical form), and last-name-only also matches."""
    if not player_name:
        return None
    line_f = float(line)
    norm_target = _normalize_name(player_name)
    # Also keep a last-name fallback ("berrettini").
    parts = norm_target.split()
    last_name = parts[-1] if parts else ""
    # And a "first-initial + last" form: "m berrettini" if input was "m. berrettini".
    initials_form = None
    if len(parts) >= 2 and len(parts[0]) == 1:
        initials_form = parts[0] + " " + parts[-1]
    best = None
    for p in props:
        if not _is_tennis_match_handicap_market(p):
            continue
        try:
            pts = float(p.get("points"))
        except (TypeError, ValueError):
            continue
        if abs(pts - line_f) > 0.01:
            continue
        # Selection participant name is usually in `player` or
        # `outcomeName`. Compare normalized.
        sel_name = p.get("player") or p.get("outcomeName") or p.get("participantName") or ""
        norm_sel = _normalize_name(sel_name)
        matched = False
        if norm_sel == norm_target:
            matched = True
        elif last_name and norm_sel.endswith(last_name):
            matched = True
        elif initials_form and initials_form in norm_sel:
            matched = True
        if not matched:
            continue
        best = {
            "selection_id": p.get("selectionId"),
            "line": pts,
            "player": sel_name,
            "american": p.get("oddsAmerican"),
        }
        return best
    return best


def _event_for_tennis_candidate(c, events):
    """Resolve a tennis candidate to a DK event. Match by player name
    against either participant. Falls back to the `event` string if the
    candidate carries one (e.g. "Berrettini vs Rinderknech")."""
    if not events:
        return None
    dog = (c.get("player_dog") or "").strip()
    norm_dog = _normalize_name(dog)
    dog_last = norm_dog.split()[-1] if norm_dog else ""
    for e in events:
        for side in ("homePlayer", "awayPlayer"):
            nm = _normalize_name(e.get(side) or "")
            if not nm:
                continue
            if nm == norm_dog or (dog_last and nm.endswith(dog_last)):
                return e
    # Last-resort: scan the event `name` string for the dog's last name.
    if dog_last:
        for e in events:
            if dog_last in _normalize_name(e.get("name") or ""):
                return e
    return None


def find_sgps_tennis(payload):
    """Price a batch of tennis 2-leg SGP candidates against DK.

    Input shape (passed via stdin JSON):
      {
        "candidates": [
          {
            "id": "<frontend candidate handle>",  # echoed back
            "player_dog": "Matteo Berrettini",    # underdog (gets +X.5 handicap)
            "event": "Berrettini vs Rinderknech", # optional, tiebreaker
            "set1_total_line": 12.5,              # 1st-set total games line (Over)
            "match_handicap_line": 3.5            # dog's full-match game handicap (+X.5)
          }, ...
        ]
      }

    Output mirrors find_sgps_nba so the frontend's merge logic can be
    reused with only field-name swaps.
    """
    import concurrent.futures
    candidates = (payload or {}).get("candidates", []) or []
    if not isinstance(candidates, list) or not candidates:
        return {"error": "candidates array required"}

    lid = (payload or {}).get("league_id")
    try:
        games_data = get_games_tennis(league_id=lid)
    except Exception as e:
        return {"error": f"DK tennis games endpoint unavailable: {e}. "
                          f"League ID = {lid or DK_TENNIS_LEAGUE_ID}. "
                          f"Open sportsbook.draftkings.com/leagues/tennis/<id> "
                          f"in a browser to find the right one."}
    events = games_data["events"]

    cand_event_map = {}
    for c in candidates:
        cand_event_map[c.get("id")] = _event_for_tennis_candidate(c, events)

    needed_eids = sorted({(e or {}).get("id") for e in cand_event_map.values() if e and e.get("id")})
    event_markets = {}
    def _scan(eid):
        try:
            return eid, get_markets(eid, tennis_only=True)
        except Exception as ex:
            sys.stderr.write(f"dk_api: tennis event {eid} scan failed: {ex}\n")
            return eid, None
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(_scan, eid): eid for eid in needed_eids}
        for fut in as_completed(futs):
            eid, md = fut.result()
            if md is not None:
                event_markets[eid] = md

    leg_cache_total = {}
    leg_cache_hcap = {}
    def _match_total(eid, line, side):
        if not eid or eid not in event_markets: return None
        key = (eid, line, side)
        if key in leg_cache_total: return leg_cache_total[key]
        m = _match_tennis_set1_total(line, side, event_markets[eid]["props"])
        leg_cache_total[key] = m
        return m
    def _match_hcap(eid, player, line):
        if not eid or eid not in event_markets: return None
        key = (eid, _normalize_name(player or ""), line)
        if key in leg_cache_hcap: return leg_cache_hcap[key]
        m = _match_tennis_match_handicap(player, line, event_markets[eid]["props"])
        leg_cache_hcap[key] = m
        return m

    resolved = []
    for c in candidates:
        e = cand_event_map.get(c.get("id")) or {}
        eid = e.get("id")
        line_total = c.get("set1_total_line")
        line_hcap  = c.get("match_handicap_line")
        side_total = c.get("set1_total_side") or "Over"
        m1 = _match_total(eid, line_total, side_total)
        m2 = _match_hcap(eid, c.get("player_dog"), line_hcap)
        s1 = m1["selection_id"] if m1 else None
        s2 = m2["selection_id"] if m2 else None
        missing = []
        if not eid:
            avail = ", ".join(
                f"{(e.get('awayPlayer') or '?')} vs {(e.get('homePlayer') or '?')}"
                for e in events[:6]
            )
            hint = f" (dk events: {avail})" if avail else " (dk events: none — check DK_TENNIS_LEAGUE_ID)"
            missing.append(f"event:{c.get('player_dog') or c.get('event') or '(no player)'}{hint}")
        else:
            if not s1: missing.append(f"leg1:1st Set {side_total} {line_total}")
            if not s2: missing.append(f"leg2:{c.get('player_dog')} +{line_hcap} Game Handicap")
        resolved.append({"src": c, "event_id": eid,
                         "game_name": e.get("name", "") if eid else "",
                         "selection_1": s1, "selection_2": s2,
                         "match_1": m1, "match_2": m2,
                         "missing": missing})

    price_cache = {}
    pricing_jobs = []
    for r in resolved:
        if not r["selection_1"] or not r["selection_2"] or r["selection_1"] == r["selection_2"]:
            continue
        key = frozenset({r["selection_1"], r["selection_2"]})
        if key in price_cache: continue
        price_cache[key] = "pending"
        pricing_jobs.append((key, r["selection_1"], r["selection_2"]))

    truncated = False
    deadline = _time.monotonic() + 110.0
    def _price_one(job):
        k, sa, sb = job
        return k, _price_combo([sa, sb])
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(_price_one, j) for j in pricing_jobs]
        remaining = max(0.5, deadline - _time.monotonic())
        try:
            for f in as_completed(futs, timeout=remaining):
                try:
                    k, price = f.result()
                    price_cache[k] = price
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            truncated = True
            for f in futs:
                f.cancel()

    results = []
    for r in resolved:
        c = r["src"]
        m1 = r.get("match_1") or {}
        m2 = r.get("match_2") or {}
        out = {
            "id": c.get("id"), "event_id": r["event_id"], "game_name": r["game_name"],
            "player_dog": c.get("player_dog"),
            "set1_total_line": c.get("set1_total_line"),
            "set1_total_side": c.get("set1_total_side") or "Over",
            "match_handicap_line": c.get("match_handicap_line"),
            "selection_1": r["selection_1"], "selection_2": r["selection_2"],
            "leg_1_over_american":  m1.get("over_american"),
            "leg_1_under_american": m1.get("under_american"),
            "leg_2_american":       m2.get("american"),
        }
        if r["missing"]:
            out["matched"] = False
            out["missing"] = r["missing"]
            results.append(out)
            continue
        key = frozenset({r["selection_1"], r["selection_2"]})
        price = price_cache.get(key)
        if price in (None, "pending"):
            out["matched"] = False
            out["missing"] = ["dk:price_unavailable"]
            results.append(out)
            continue
        out["matched"] = True
        out["dk_odds"] = price["sgpOdds"]
        out["dk_decimal"] = price["sgpDecimal"]
        results.append(out)

    response = {"results": results, "events_scanned": needed_eids,
                "league_id": lid or DK_TENNIS_LEAGUE_ID}
    if truncated:
        response["truncated"] = True
    return response


def enumerate_sgps_tennis(payload=None):
    """Auto-enumerate ALL 1st-Set-Total × dog Game-Handicap SGP candidates
    on the current tennis slate, price each via DK, return ready-to-render
    rows. No FV-sheet upload required — DK is both leg-fair source
    (two-sided no-vig) AND the SGP-price source.

    Output row shape (one per (event, total_line, handicap_line) combo):
      {
        "id":               "<event_id>::<total_line>::<dog_last>::<hcap_mag>",
        "event_id":         "<dk event id>",
        "game_name":        "Quentin Halys vs Ugo Humbert",
        "set1_total_line":  9.5,
        "leg_1_over_american":  -150,
        "leg_1_under_american": +110,
        "set1_over_selection_id": "...",
        "dog_player":            "Matteo Berrettini",
        "fav_player":            "Arthur Rinderknech",
        "match_handicap_line":   3.5,                   # always positive (dog side)
        "leg_2_dog_american":    -225,
        "leg_2_fav_american":    +175,
        "dog_handicap_selection_id": "...",
        "selection_1": "...", "selection_2": "...",
        "matched":     bool,
        "dk_odds":     "+350",
        "dk_decimal":  4.50,
        "missing":     [...]                             # when matched=false
      }

    Supported set-1 total lines are pinned to the four lines with hardcoded
    correlation priors (8.5 / 9.5 / 10.5 / 12.5). Optional payload keys:
      {
        "lines":        [8.5, 9.5, 10.5, 12.5],   # subset to enumerate
        "max_handicap": 9.5                         # cap on dog handicap magnitude
      }
    """
    import concurrent.futures

    payload = payload or {}
    supported_lines = payload.get("lines") or [8.5, 9.5, 10.5, 12.5]
    supported_lines = [float(x) for x in supported_lines]
    max_handicap = payload.get("max_handicap")
    if max_handicap is not None:
        try:
            max_handicap = float(max_handicap)
        except (TypeError, ValueError):
            max_handicap = None

    lid = payload.get("league_id")
    try:
        games_data = get_games_tennis(league_id=lid)
    except Exception as e:
        return {"error": f"DK tennis games endpoint unavailable: {e}. "
                          f"League ID = {lid or DK_TENNIS_LEAGUE_ID}. "
                          f"Open sportsbook.draftkings.com/leagues/tennis/<id> "
                          f"in a browser to find the right one."}
    events = [e for e in games_data["events"]
              if e.get("hasSGP") and not e.get("isLive")]

    # Step 1: per-event market scan in parallel.
    event_markets = {}
    def _scan(eid):
        try:
            return eid, get_markets(eid, tennis_only=True)
        except Exception as ex:
            sys.stderr.write(f"dk_api: tennis event {eid} scan failed: {ex}\n")
            return eid, None
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(_scan, e["id"]): e["id"] for e in events if e.get("id")}
        for fut in as_completed(futs):
            eid, md = fut.result()
            if md is not None:
                event_markets[eid] = md

    # Step 2: enumerate legs per event.
    # Each event yields:
    #   totals_by_line:  { line: {"over": prop, "under": prop} }
    #   handicaps_by_mag: { mag: {"dog": prop, "fav": prop} }
    # where mag is the absolute handicap magnitude (DK lists the dog at
    # +mag and the favorite at -mag in the same market).
    enriched_events = []
    for e in events:
        eid = e.get("id")
        md = event_markets.get(eid)
        if not md:
            continue
        props = md.get("props", [])
        totals = {}
        for p in props:
            if not _is_tennis_set1_total_market(p):
                continue
            try:
                line = float(p.get("points"))
            except (TypeError, ValueError):
                continue
            side = (p.get("outcomeType") or "").lower()
            if side not in ("over", "under"):
                continue
            totals.setdefault(line, {})[side] = p
        # Game handicap selections: group by absolute magnitude. Each
        # mag bucket should hold one dog (points > 0) and one fav
        # (points < 0). Skip mags missing one side.
        hcap_buckets = {}
        for p in props:
            if not _is_tennis_match_handicap_market(p):
                continue
            try:
                pts = float(p.get("points"))
            except (TypeError, ValueError):
                continue
            mag = round(abs(pts) * 2) / 2  # snap to half-game grid
            side = "dog" if pts > 0 else "fav"
            hcap_buckets.setdefault(mag, {})[side] = p
        # Drop incomplete bucket entries (need both dog + fav).
        handicaps_by_mag = {m: b for m, b in hcap_buckets.items() if "dog" in b and "fav" in b}
        enriched_events.append({
            "event": e,
            "totals_by_line": totals,
            "handicaps_by_mag": handicaps_by_mag,
        })

    # Step 3: build candidate combos. For each event × supported total ×
    # handicap magnitude (optionally capped). Total leg is always Over.
    candidates = []
    for ev in enriched_events:
        e = ev["event"]
        for line in supported_lines:
            tot = ev["totals_by_line"].get(line)
            if not tot or "over" not in tot:
                continue
            over_prop = tot["over"]
            under_prop = tot.get("under") or {}
            for mag in sorted(ev["handicaps_by_mag"].keys()):
                if max_handicap is not None and mag > max_handicap:
                    continue
                bucket = ev["handicaps_by_mag"][mag]
                dog_prop = bucket["dog"]
                fav_prop = bucket["fav"]
                dog_player = dog_prop.get("player") or dog_prop.get("outcomeType") or ""
                fav_player = fav_prop.get("player") or fav_prop.get("outcomeType") or ""
                dog_last = _normalize_name(dog_player).split()[-1] if dog_player else "p"
                cid = f"{e.get('id')}::{line}::{dog_last}::{mag}"
                candidates.append({
                    "id": cid,
                    "event_id": e.get("id"),
                    "game_name": e.get("name") or f"{e.get('awayPlayer','')} vs {e.get('homePlayer','')}",
                    "set1_total_line": line,
                    "set1_over_selection_id":  over_prop.get("selectionId"),
                    "set1_under_selection_id": under_prop.get("selectionId"),
                    "leg_1_over_american":  over_prop.get("oddsAmerican"),
                    "leg_1_under_american": under_prop.get("oddsAmerican"),
                    "dog_player": dog_player,
                    "fav_player": fav_player,
                    "match_handicap_line":  mag,
                    "dog_handicap_selection_id": dog_prop.get("selectionId"),
                    "fav_handicap_selection_id": fav_prop.get("selectionId"),
                    "leg_2_dog_american":  dog_prop.get("oddsAmerican"),
                    "leg_2_fav_american":  fav_prop.get("oddsAmerican"),
                    "selection_1": over_prop.get("selectionId"),
                    "selection_2": dog_prop.get("selectionId"),
                })

    # Step 4: dedupe + price each unique selection pair via calculateBets.
    price_cache = {}
    pricing_jobs = []
    for c in candidates:
        s1, s2 = c["selection_1"], c["selection_2"]
        if not s1 or not s2 or s1 == s2:
            continue
        key = frozenset({s1, s2})
        if key in price_cache:
            continue
        price_cache[key] = "pending"
        pricing_jobs.append((key, s1, s2))

    truncated = False
    deadline = _time.monotonic() + 110.0
    def _price_one(job):
        k, sa, sb = job
        return k, _price_combo([sa, sb])
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(_price_one, j) for j in pricing_jobs]
        remaining = max(0.5, deadline - _time.monotonic())
        try:
            for f in as_completed(futs, timeout=remaining):
                try:
                    k, price = f.result()
                    price_cache[k] = price
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            truncated = True
            for f in futs:
                f.cancel()

    # Step 5: stitch prices back into candidate rows.
    out_rows = []
    for c in candidates:
        s1, s2 = c["selection_1"], c["selection_2"]
        row = dict(c)
        if not s1 or not s2:
            row["matched"] = False
            row["missing"] = ["dk:selection_missing"]
            out_rows.append(row); continue
        key = frozenset({s1, s2})
        price = price_cache.get(key)
        if price in (None, "pending"):
            row["matched"] = False
            row["missing"] = ["dk:price_unavailable"]
            out_rows.append(row); continue
        row["matched"] = True
        row["dk_odds"] = price["sgpOdds"]
        row["dk_decimal"] = price["sgpDecimal"]
        out_rows.append(row)

    resp = {
        "candidates": out_rows,
        "events_scanned": list(event_markets.keys()),
        "events_total":   len(events),
        "league_id":      lid or DK_TENNIS_LEAGUE_ID,
    }
    if truncated:
        resp["truncated"] = True
    return resp


# ===== Soccer / World Cup =====

def resolve_soccer_league_by_slug(slug=None):
    """Resolve a DK public soccer slug (e.g. 'fifa-world-cup') to the numeric
    league ID by scraping the public league page. Mirrors
    resolve_tennis_league_by_slug — see that docstring for why."""
    slug = slug or DK_WORLDCUP_SLUG
    url = f"https://sportsbook.draftkings.com/leagues/soccer/{slug}"
    try:
        r = _get_with_retry(url, attempts=4, timeout=12)
    except Exception as e:
        return {"slug": slug, "error": f"fetch failed: {e}"}
    html = r.text or ""
    patterns = [
        r'"leagueId"\s*:\s*"?(\d{3,7})"?',
        r'"league_id"\s*:\s*"?(\d{3,7})"?',
        r'/nav/leagues/(\d{3,7})',
        r'data-leagueid="(\d{3,7})"',
        r'/leagues/(\d{3,7})\b',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return {"slug": slug, "league_id": m.group(1),
                    "source": "page-scrape"}
    return {"slug": slug, "error": "no league id found in page",
            "html_len": len(html)}


def get_games_soccer(league_id=None, slug=None, league=None):
    """Return soccer events for a league (default: FIFA World Cup).

    Resolution order: explicit league_id > `league` registry key (e.g. 'epl')
    > env default > slug page-scrape. The last lets a league work with zero
    config the day it shows up on DK."""
    if not league_id and league:
        entry = _soccer_league(league)
        league_id = entry.get("dk_id") or None
        slug = slug or entry.get("dk_slug")
    lid = str(league_id) if league_id else DK_WORLDCUP_LEAGUE_ID
    resolved_from = None
    if not lid:
        res = resolve_soccer_league_by_slug(slug)
        if res.get("error"):
            raise RuntimeError(f"league id unset and slug resolve failed: {res['error']}")
        lid = res["league_id"]
        resolved_from = res.get("slug")
    r = _get_with_retry(f"{DK_LEAGUES}/{lid}")
    events = r.json().get("events", [])
    out = []
    for e in events:
        tags = e.get("tags", [])
        participants = e.get("participants", []) or []
        home = next((p for p in participants if p.get("venueRole") == "Home"), None)
        away = next((p for p in participants if p.get("venueRole") == "Away"), None)
        if not home and len(participants) >= 1: home = participants[0]
        if not away and len(participants) >= 2: away = participants[1]
        home = home or {}
        away = away or {}
        out.append({
            "id": _ev_id(e),
            "name": e.get("name", ""),
            "startDate": _ev_start(e),
            "homeTeam": home.get("name", e.get("teamName2", "")),
            "awayTeam": away.get("name", e.get("teamName1", "")),
            "hasSGP": "SGP" in tags,
            "isLive": e.get("isLive", False),
            "status": e.get("status", ""),
        })
    out.sort(key=lambda x: x["startDate"])
    resp = {"events": out, "leagueId": lid}
    if resolved_from:
        resp["resolvedFromSlug"] = resolved_from
    return resp


def _norm_soccer(s):
    """Lowercase, fold accents-ish, collapse whitespace for team matching."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


# Country names that differ between Pinnacle and DK (official FIFA name vs
# common short form). Each set's members all refer to the same nation.
_SOCCER_COUNTRY_ALIASES = [
    {"czechia", "czech republic"},
    {"south korea", "korea republic"},
    {"north korea", "korea dpr"},
    {"usa", "united states", "united states of america"},
    {"iran", "ir iran"},
    {"turkey", "turkiye"},
    {"ivory coast", "cote d'ivoire", "cote divoire"},
    {"bosnia", "bosnia and herzegovina", "bosnia & herzegovina"},
    {"cape verde", "cabo verde"},
    {"uae", "united arab emirates"},
    {"dr congo", "congo dr", "democratic republic of congo"},
]

# Club names that differ between Pinnacle (fuller form) and DK (short form).
# Substring matching already handles truncations ("Newcastle" ⊂ "Newcastle
# United", "Tottenham" ⊂ "Tottenham Hotspur"); these sets cover the cases where
# a WORD is abbreviated, which substring can't catch — "Man City" vs
# "Manchester City", "Wolves" vs "Wolverhampton", "Spurs" vs "Tottenham", etc.
# EPL-focused; extend as leagues are added.
_SOCCER_CLUB_ALIASES = [
    {"manchester city", "man city"},
    {"manchester united", "man utd", "man united"},
    {"tottenham hotspur", "tottenham", "spurs"},
    {"wolverhampton wanderers", "wolverhampton", "wolves"},
    {"nottingham forest", "nott'm forest", "nottm forest", "notts forest"},
    {"brighton & hove albion", "brighton and hove albion",
     "brighton hove albion", "brighton"},
    {"west ham united", "west ham"},
    {"newcastle united", "newcastle"},
    {"leeds united", "leeds"},
    {"ipswich town", "ipswich"},
    {"queens park rangers", "qpr"},
    {"west bromwich albion", "west bromwich", "west brom", "wba"},
    {"sheffield united", "sheffield utd", "sheff united", "sheff utd"},
    {"sheffield wednesday", "sheff wednesday", "sheff wed"},
    {"leicester city", "leicester"},
    {"norwich city", "norwich"},
    {"afc bournemouth", "bournemouth"},
]

def _team_matches_soccer(want, have):
    w, h = _norm_soccer(want), _norm_soccer(have)
    if not w or not h:
        return False
    if w == h or w in h or h in w:
        return True
    return any(w in al and h in al
               for al in _SOCCER_COUNTRY_ALIASES + _SOCCER_CLUB_ALIASES)


def _event_for_soccer_match(home, away, events):
    """Pick the DK event whose two participants match the Pinnacle teams
    (either orientation — Pinnacle and DK occasionally disagree on which
    side is 'home' for neutral-venue tournament games)."""
    for e in events:
        ht, at = e.get("homeTeam", ""), e.get("awayTeam", "")
        straight = _team_matches_soccer(home, ht) and _team_matches_soccer(away, at)
        flipped  = _team_matches_soccer(home, at) and _team_matches_soccer(away, ht)
        if straight or flipped:
            return e
    return None


# Per-half / per-period qualifiers that disqualify a DK market from matching
# our full-match Pinnacle groups — EXCEPT ht_ft, which spans both halves and
# legitimately contains "half"-flavored wording.
_SOCCER_PERIOD_EXCLUDE = ("1st half", "first half", "2nd half", "second half",
                          "1st 30", "first 15", "1st 15", "extra time",
                          "halftime result", "half time result")

def _soccer_market_kind(blob):
    """Classify a DK market name blob into one of our Pinnacle combo keys,
    or None. Patterns are deliberately loose ('&' vs 'and', 'result' vs
    'winner' vs 'moneyline') because DK's exact soccer market names vary."""
    b = blob.lower()
    if "halftime/fulltime" in b or "half time/full time" in b or \
       "halftime / fulltime" in b or "ht/ft" in b or "double result" in b:
        # "Half Time / Full Time / Over/Under 2.5" is a 3-way combo we don't
        # price — without this guard its selections shadow the plain HT/FT
        # market's (same "Mexico/Tie" labels, different odds).
        if re.search(r"\b(over|under)\b", b) or "total" in b or "o/u" in b:
            return None
        return "ht_ft"
    if any(p in b for p in _SOCCER_PERIOD_EXCLUDE):
        return None
    has_btts   = "both teams to score" in b or "btts" in b
    has_total  = ("total" in b) or ("over/under" in b) or ("o/u" in b) or \
                 re.search(r"\b(over|under)\b", b) is not None
    has_result = ("result" in b) or ("winner" in b) or ("moneyline" in b) or ("1x2" in b)
    has_oddeven = ("odd" in b and "even" in b)
    if has_btts and has_total:
        return "btts_total"
    if has_btts and has_result:
        return "btts_winner"
    if has_oddeven and re.search(r"\b(over|under)\b|o/u|over/under", b):
        # Plain "Total Goals Odd/Even" (no O/U dimension) is the SGP *leg*
        # market — _soccer_straight_kind classifies it as "oddeven".
        return "oddeven_total"
    if has_result and has_total and not has_btts:
        return "winner_total"
    return None


def _soccer_straight_kind(market_name, subcat):
    """Classify a DK straight (non-combo) market into one of the extended
    Pinnacle group kinds. Name-anchored — these were verified against the
    live World Cup 2026 slate. Returns None for anything unrecognized."""
    n = (market_name or "").strip()
    nl = n.lower()
    sl = (subcat or "").lower()
    blob = nl + " " + sl
    # SGP leg markets that intentionally precede the period guard:
    if nl == "moneyline 1st half" or nl == "moneyline - 1st half":
        return "ml_1h"
    if any(p in blob for p in _SOCCER_PERIOD_EXCLUDE) or \
       "1st half" in blob or "2nd half" in blob:
        return None
    if nl == "moneyline":
        return "moneyline"
    if nl in ("total goals odd/even", "total goals - odd/even"):
        return "oddeven"
    if nl == "total goals":
        return "total_goals"
    if nl == "spread" and ("asian handicap" in sl or sl == "spread"):
        # Main + quarter lines sit under the "Asian Handicap" subcat; the
        # ±1.5/±2.5 alternate lines sit under a subcat literally named
        # "Spread" (verified on the World Cup 2026 knockout slate).
        return "spread"
    if nl.endswith(": team total goals"):
        return "team_goals"
    if nl == "double chance":
        return "double_chance"
    if nl == "tie no bet" or nl == "draw no bet":
        return "draw_no_bet"
    if nl == "both teams to score":
        return "btts"
    if nl == "multi goals":
        return "total_goals_range"
    if nl == "winning margin":
        return "winning_margin"
    if nl == "1st goal" or nl == "first goal":
        return "first_team_to_score"
    if nl == "team clean sheet":
        return "team_to_score"
    if nl == "total corners":
        return "corners_total"
    if nl.endswith(": team total corners"):
        return "team_corners"
    if nl == "total cards":
        return "cards_total"
    if nl.endswith(": team total cards"):
        return "team_cards"
    if nl == "anytime goalscorer":
        return "player_to_score"
    return None


def _label_result_token(token, home, away):
    """Map a label fragment to 'home'/'draw'/'away' or None. DK says 'Tie',
    Pinnacle says 'Draw'. Strip DK's 'Win'/'and' filler before team-matching
    so 'Mexico Win and' still resolves to the home side."""
    t = _norm_soccer(token)
    t = re.sub(r"\b(win|and|to|or)\b", " ", t).strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return None
    if "draw" in t or "tie" in t:
        return "draw"
    if _team_matches_soccer(home, t):
        return "home"
    if _team_matches_soccer(away, t):
        return "away"
    return None


def _label_has_word(label, word):
    return re.search(r"\b" + re.escape(word) + r"\b", label, re.I) is not None


def _label_total(label, points):
    """Extract (side, line) from a label like '... & Over 2.5'."""
    side = "Over" if _label_has_word(label, "over") else \
           ("Under" if _label_has_word(label, "under") else None)
    line = None
    m = re.search(r"(\d+(?:\.\d+)?)", label)
    if m:
        line = float(m.group(1))
    elif points is not None:
        try: line = float(points)
        except (TypeError, ValueError): pass
    return side, line


def _match_soccer_selection(cand, props_for_kind, home, away):
    """Find the DK selection matching one Pinnacle combo candidate.

    Verified DK label formats (World Cup 2026 slate):
      winner_total ("Moneyline / Over/Under 2.5"):
        "Mexico Win and Over 2.5" / "Tie and Over 2.5"
      btts_winner ("Moneyline / Both Teams to Score"):
        "Mexico Win and Both to Score" (= home & Yes)
        "Mexico Win to Zero"           (= home & No)
        "Tie with Goals" / "Tie without Goals" (= draw & Yes / draw & No)
      ht_ft ("Half Time / Full Time"): the paired result is in the DK
        selection's bet-slip line — "Mexico/Tie" (World Cup) or
        "Nottingham Forest/Leeds" (EPL, where label is null and outcomeType is
        only the FT side). Falls back to label for older/other formats.
      btts_total ("Both Teams to Score / Over 2.5 Goals"):
        labels are just "Yes"/"No", the total lives in the MARKET name —
        and DK's "No" is the complement of (Yes & Over), NOT Pinnacle's
        "No & Over". Only the Yes cell maps 1:1.

    cand fields by market_key:
      btts_total:    btts (Yes/No), total_side (Over/Under), total_line
      btts_winner:   btts, result (home/draw/away)
      winner_total:  result, total_side, total_line
      oddeven_total: odd_even (Odd/Even), total_side, total_line
      ht_ft:         ht (home/draw/away), ft (home/draw/away)
    """
    key = cand.get("market_key")
    for p in props_for_kind:
        label = p.get("label") or p.get("outcomeType") or ""
        if not label:
            continue

        if key == "ht_ft":
            # The HT/FT pairing lives in the bet-slip line ("Home/Away" style);
            # DK's EPL feed leaves `label` null and `outcomeType` = FT side only.
            pair = p.get("betslipLine") or label
            parts = re.split(r"\s*/\s*", pair)
            if len(parts) != 2:
                parts = re.split(r"\s+-\s+", pair)
            if len(parts) != 2:
                continue
            ht = _label_result_token(parts[0], home, away)
            ft = _label_result_token(parts[1], home, away)
            if ht and ft and ht == cand.get("ht") and ft == cand.get("ft"):
                return p
            continue

        if key == "btts_total":
            if str(cand.get("btts", "")).lower() != "yes":
                continue  # DK only lists the Yes cell; "No" is a complement
            mside, mline = _label_total(p.get("marketName", ""), None)
            if mside != cand.get("total_side"):
                continue
            want_line = cand.get("total_line")
            if want_line is not None and mline is not None and \
               abs(float(want_line) - mline) > 1e-6:
                continue
            if _label_has_word(label, "yes"):
                return p
            continue

        if key == "btts_winner":
            lab = label.lower()
            is_yes = ("both to score" in lab or "both teams to score" in lab
                      or "with goals" in lab)
            is_no = ("to zero" in lab or "to nil" in lab or "without goals" in lab)
            want_yes = str(cand.get("btts", "")).lower() == "yes"
            if (want_yes and not is_yes) or (not want_yes and not is_no):
                continue
            # outcomeType carries Home/Tie/Away cleanly on this market.
            ot = (p.get("outcomeType") or "").lower()
            res = {"home": "home", "tie": "draw", "draw": "draw",
                   "away": "away"}.get(ot)
            if res is None:
                res = _label_result_token(
                    re.sub(r"\b(both to score|with goals|without goals|to zero|to nil)\b",
                           "", lab), home, away)
            if res == cand.get("result"):
                return p
            continue

        if key == "winner_total":
            side, line = _label_total(label, p.get("points"))
            if side != cand.get("total_side"):
                continue
            want_line = cand.get("total_line")
            if want_line is not None and line is not None and \
               abs(float(want_line) - line) > 1e-6:
                continue
            res_part = re.sub(r"\b(over|under)\b.*$", "", label, flags=re.I)
            if _label_result_token(res_part, home, away) == cand.get("result"):
                return p
            continue

        if key in ("moneyline", "ml_1h"):
            ot = (p.get("outcomeType") or "").lower()
            res = {"home": "home", "tie": "draw", "draw": "draw",
                   "away": "away"}.get(ot) or _label_result_token(label, home, away)
            if res == cand.get("result"):
                return p
            continue

        if key == "oddeven":
            want_odd = str(cand.get("odd_even", "")).lower() == "odd"
            if want_odd == _label_has_word(label, "odd") and \
               want_odd != _label_has_word(label, "even"):
                return p
            continue

        if key in ("total_goals", "corners_total", "cards_total"):
            ot = (p.get("outcomeType") or "").title()
            if ot != cand.get("total_side"):
                continue
            pts = p.get("points")
            if pts is None or cand.get("total_line") is None or \
               abs(float(pts) - float(cand["total_line"])) > 1e-6:
                continue
            return p

        if key in ("team_goals", "team_corners", "team_cards"):
            team_name = home if cand.get("team") == "home" else away
            if not _team_matches_soccer(team_name,
                                        (p.get("marketName") or "").split(":")[0]):
                continue
            ot = (p.get("outcomeType") or "").title()
            if ot != cand.get("total_side"):
                continue
            pts = p.get("points")
            if pts is None or cand.get("total_line") is None or \
               abs(float(pts) - float(cand["total_line"])) > 1e-6:
                continue
            return p

        if key == "spread":
            ot = (p.get("outcomeType") or "").lower()
            side = {"home": "home", "away": "away"}.get(ot)
            if side != cand.get("team"):
                continue
            pts = p.get("points")
            if pts is None or cand.get("line") is None or \
               abs(float(pts) - float(cand["line"])) > 1e-6:
                continue
            return p

        if key == "double_chance":
            ot = (p.get("outcomeType") or "").upper()
            want = {"home_draw": "1X", "home_away": "12", "draw_away": "X2"}.get(cand.get("dc"))
            if ot == want and want:
                return p
            # Fallback on label text ("Mexico or Tie")
            if not want:
                continue
            toks = re.split(r"\bor\b", label, flags=re.I)
            if len(toks) == 2:
                a = _label_result_token(toks[0], home, away)
                b = _label_result_token(toks[1], home, away)
                pairs = {"home_draw": {"draw", "home"}, "home_away": {"away", "home"},
                         "draw_away": {"away", "draw"}}
                if {a, b} == pairs.get(cand.get("dc"), set()):
                    return p
            continue

        if key == "draw_no_bet":
            ot = (p.get("outcomeType") or "").lower()
            res = {"home": "home", "away": "away"}.get(ot) or \
                  _label_result_token(label, home, away)
            if res == cand.get("result"):
                return p
            continue

        if key == "btts":
            want_yes = str(cand.get("btts", "")).lower() == "yes"
            if want_yes == _label_has_word(label, "yes") and \
               want_yes != _label_has_word(label, "no"):
                return p
            continue

        if key == "total_goals_range":
            # DK "Multi Goals" bands: "1-2 Goals" (Yes side only; the
            # "Anything Other Than" rows are complements).
            if (p.get("outcomeType") or "").lower() == "no" or \
               "anything other" in label.lower():
                continue
            m_band = re.match(r"^(\d+)\s*-\s*(\d+) Goals?$", label.strip(), re.I)
            if m_band and f"{m_band.group(1)}-{m_band.group(2)}" == cand.get("range"):
                return p
            continue

        if key == "winning_margin":
            ot = (p.get("outcomeType") or "").lower()
            side = {"home": "home", "tie": "draw", "away": "away"}.get(ot)
            if side != cand.get("side"):
                continue
            lab = label.lower()
            margin = cand.get("margin")
            if margin == "score_draw":
                if "score tie" in lab and "no score" not in lab:
                    return p
            elif margin == "no_goal":
                if "no score tie" in lab or "no goal" in lab:
                    return p
            elif margin and margin.endswith("+"):
                if re.search(rf"by {margin[:-1]} goals? or more", lab):
                    return p
            elif margin:
                if re.search(rf"by {margin} goals?$", lab.strip()):
                    return p
            continue

        if key == "first_team_to_score":
            ot = (p.get("outcomeType") or "").lower()
            res = {"home": "home", "away": "away", "tie": "neither"}.get(ot)
            if res is None:
                res = "neither" if "no goal" in label.lower() else \
                      _label_result_token(label, home, away)
            if res == cand.get("result"):
                return p
            continue

        if key == "team_to_score":
            # DK lists "Team Clean Sheet" per team: clean sheet for team T
            # means the OPPONENT doesn't score, so home-to-score=Yes maps to
            # away clean sheet=No (and vice versa).
            opp = "away" if cand.get("team") == "home" else "home"
            opp_name = home if opp == "home" else away
            # Participant names can be localized ("Sudáfrica") — venueRole is
            # the reliable team identifier on this market.
            role = (p.get("participantRole") or "").lower()
            if role in ("home", "away"):
                if role != opp:
                    continue
            elif not _team_matches_soccer(opp_name, p.get("player") or ""):
                continue
            is_yes = _label_has_word(label, "yes")
            want_cs_yes = not cand.get("yes")  # to-score Yes ⇒ clean sheet No
            if is_yes == want_cs_yes:
                return p
            continue

        if key == "player_to_score":
            if not cand.get("yes"):
                continue  # DK lists anytime-scorer Yes prices only
            pl, ll = _norm_soccer(cand.get("player", "")), _norm_soccer(label)
            if pl and ll and (pl in ll or ll in pl):
                return p
            continue

        if key == "oddeven_total":
            # DK doesn't list an Odd/Even × Total combo on this slate; this
            # branch only fires if one ever appears with explicit labels.
            want_odd = str(cand.get("odd_even", "")).lower() == "odd"
            if want_odd != _label_has_word(label, "odd"):
                continue
            side, line = _label_total(label, p.get("points"))
            if side != cand.get("total_side"):
                continue
            want_line = cand.get("total_line")
            if want_line is not None and line is not None and \
               abs(float(want_line) - line) > 1e-6:
                continue
            return p
    return None


_SOCCER_COMBO_KINDS = {"btts_total", "btts_winner", "winner_total", "ht_ft",
                       "oddeven_total"}


def _price_event_combos(md, home, away, candidates, sgp_only=False, deadline=None):
    """Match Pinnacle combo candidates to one already-fetched DK event's markets
    (md = get_markets(eid, soccer_only=True)) and price the real 2-leg SGPs via
    calculateBets. Shared by find_sgps_worldcup (one game) and
    find_sgps_soccer_all (sweep). Returns (results, had_jobs, truncated)."""
    import concurrent.futures as _cf
    props_by_kind = {}
    market_names_by_kind = {}
    for p in md["props"]:
        blob = " ".join([p.get("marketName", ""), p.get("marketType", ""),
                         p.get("subcategory", "")])
        kind = _soccer_market_kind(blob) or \
               _soccer_straight_kind(p.get("marketName", ""), p.get("subcategory", ""))
        if not kind:
            continue
        props_by_kind.setdefault(kind, []).append(p)
        market_names_by_kind.setdefault(kind, set()).add(p.get("marketName", ""))

    def _leg_specs(c):
        key = c.get("market_key")
        tot = {"market_key": "total_goals",
               "total_side": c.get("total_side"),
               "total_line": c.get("total_line")}
        if key == "btts_total":
            return [{"market_key": "btts", "btts": c.get("btts")}, tot]
        if key == "btts_winner":
            return [{"market_key": "btts", "btts": c.get("btts")},
                    {"market_key": "moneyline", "result": c.get("result")}]
        if key == "winner_total":
            return [{"market_key": "moneyline", "result": c.get("result")}, tot]
        if key == "ht_ft":
            return [{"market_key": "ml_1h", "result": c.get("ht")},
                    {"market_key": "moneyline", "result": c.get("ft")}]
        if key == "oddeven_total":
            return [{"market_key": "oddeven", "odd_even": c.get("odd_even")}, tot]
        return None

    def _match_prebuilt(c):
        pool = props_by_kind.get(c.get("market_key"), [])
        return _match_soccer_selection(c, pool, home, away) if pool else None

    resolved = []
    for c in candidates:
        entry = {"c": c, "legs": None, "prebuilt": None, "leg_fail": None}
        if c.get("market_key") in _SOCCER_COMBO_KINDS:
            legs = []
            for sp in _leg_specs(c) or []:
                pool = props_by_kind.get(sp["market_key"], [])
                m = _match_soccer_selection(sp, pool, home, away) if pool else None
                if not m:
                    entry["leg_fail"] = sp["market_key"]
                    legs = None
                    break
                legs.append(m)
            entry["legs"] = legs
            entry["prebuilt"] = _match_prebuilt(c)
        else:
            entry["prebuilt"] = _match_prebuilt(c)
        resolved.append(entry)

    price_cache = {}
    jobs = []
    for e in resolved:
        if e["legs"]:
            ids = frozenset(l["selectionId"] for l in e["legs"])
            if len(ids) == 2 and ids not in price_cache:
                price_cache[ids] = "pending"
                jobs.append(ids)

    truncated = False
    if deadline is None:
        deadline = _time.monotonic() + 110.0

    def _price_job(ids):
        return ids, _price_combo(sorted(ids))
    # Breaker already tripped by an earlier game in the sweep: don't stand up a
    # thread pool whose only product is 403s. The rows report price_blocked.
    if jobs and _price_blocked():
        jobs = []
    if jobs:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(_price_job, j) for j in jobs]
            try:
                for f in as_completed(futs, timeout=max(0.5, deadline - _time.monotonic())):
                    try:
                        k, price = f.result()
                        price_cache[k] = price
                    except Exception:
                        pass
            except _cf.TimeoutError:
                truncated = True
                for f in futs:
                    f.cancel()

    results = []
    for e in resolved:
        c = e["c"]
        key = c.get("market_key")
        out = {"id": c.get("id"), "market_key": key}
        if key in _SOCCER_COMBO_KINDS:
            price = None
            if e["legs"]:
                ids = frozenset(l["selectionId"] for l in e["legs"])
                price = price_cache.get(ids)
                if price == "pending":
                    price = None
            if price:
                out["matched"] = True
                out["via"] = "sgp"
                out["dk_american"] = price.get("sgpOdds")
                out["dk_decimal"] = price.get("sgpDecimal")
                out["dk_market"] = "SGP: " + " + ".join(
                    l.get("marketName", "") for l in e["legs"])
                out["dk_label"] = " + ".join(
                    (l.get("label") or l.get("outcomeType") or "") for l in e["legs"])
            elif e["prebuilt"] and not sgp_only:
                m = e["prebuilt"]
                out["matched"] = True
                out["via"] = "prebuilt"
                out["dk_american"] = m.get("oddsAmerican")
                out["dk_decimal"] = m.get("oddsDecimal")
                out["dk_label"] = m.get("label") or m.get("outcomeType")
                out["dk_market"] = m.get("marketName")
                out["isDisabled"] = m.get("isDisabled", False)
            else:
                out["matched"] = False
                # Legs resolved but DK never priced them because this IP is
                # blocked — a different problem from a leg that didn't match,
                # and the only one a proxy fixes. Flag it so the caller can say
                # so instead of reporting "no match".
                if e["legs"] and _price_blocked():
                    out["price_blocked"] = True
                sgp_why = ("sgp leg unresolved: " + str(e.get("leg_fail"))
                           if not e["legs"] else
                           "dk:sgp_price_unavailable (combination refused or timed out)")
                if sgp_only and e["prebuilt"]:
                    out["missing"] = (sgp_why +
                                      "; a prebuilt combo exists but sgp_only is set "
                                      "(prebuilt straight markets aren't SGPs)")
                else:
                    out["missing"] = sgp_why + "; no prebuilt combo market either"
            results.append(out)
            continue
        m = e["prebuilt"]
        if m:
            out["matched"] = True
            out["via"] = "prebuilt"
            out["dk_american"] = m.get("oddsAmerican")
            out["dk_decimal"] = m.get("oddsDecimal")
            out["dk_label"] = m.get("label") or m.get("outcomeType")
            out["dk_market"] = m.get("marketName")
            out["isDisabled"] = m.get("isDisabled", False)
        else:
            pool = props_by_kind.get(key, [])
            out["matched"] = False
            out["missing"] = ("no DK market of this kind" if not pool
                              else "no selection matched in: " +
                                   ", ".join(sorted(market_names_by_kind.get(key, []))[:4]))
        results.append(out)

    return results, bool(jobs), truncated


def find_sgps_worldcup(payload):
    """Match a batch of Pinnacle soccer combo candidates against DK's listed
    combo markets for one match and return DK's posted odds.

    Unlike the tennis flow there is no SGP pricing call: DK lists these
    combos (BTTS & Total, Result & BTTS, Result & Total, HT/FT) as straight
    markets, so the posted selection odds ARE the SGP price.

    Input (stdin JSON):
      { "league": "epl",             # optional registry key (worldcup|epl|...)
        "league_id": "...",          # optional explicit DK id (wins over key)
        "league_slug": "...",        # optional slug override
        "sgp_only": true,            # optional; drop the prebuilt-combo fallback
        "home": "Mexico", "away": "South Africa",
        "candidates": [ { "id", "market_key", ...key-specific fields } ] }

    sgp_only: DK also lists some of these joint outcomes as *prebuilt straight
    markets* (BTTS & Total, HT/FT, ...). Those are NOT Same Game Parlays and do
    not satisfy DK's SGP promos, so when sgp_only is set a combo counts as
    matched only if it priced as a real 2-leg SGP via calculateBets — the
    prebuilt fallback is suppressed.
    """
    payload = payload or {}
    candidates = payload.get("candidates", []) or []
    if not isinstance(candidates, list) or not candidates:
        return {"error": "candidates array required"}
    sgp_only = bool(payload.get("sgp_only"))
    home, away = payload.get("home", ""), payload.get("away", "")
    if not home or not away:
        return {"error": "home and away team names required"}

    try:
        games_data = get_games_soccer(league_id=payload.get("league_id"),
                                      slug=payload.get("league_slug"),
                                      league=payload.get("league"))
    except Exception as e:
        return {"error": f"DK soccer games unavailable: {e}. Set "
                         f"the league id/slug or pass league_id from the UI "
                         f"(grab it from sportsbook.draftkings.com/leagues/soccer/...)."}
    events = games_data["events"]
    event = _event_for_soccer_match(home, away, events)
    if not event:
        avail = ", ".join(f"{e.get('awayTeam','?')} @ {e.get('homeTeam','?')}"
                          for e in events[:10])
        return {"error": f"no DK event matches {home} vs {away}",
                "league_id": games_data.get("leagueId"),
                "dk_events": avail or "(none on slate)"}

    eid = event["id"]
    try:
        md = get_markets(eid, soccer_only=True)
    except Exception as e:
        return {"error": f"DK market scan failed for event {eid}: {e}"}

    results, had_jobs, truncated = _price_event_combos(
        md, home, away, candidates, sgp_only=sgp_only)

    # Unique fetched market names — the debugging lifeline when DK renames
    # things (the tennis scan shipped blind and burned a day on this).
    seen_markets = sorted({p.get("marketName", "") for p in md["props"] if p.get("marketName")})
    resp = {"results": results,
            "event_id": eid,
            "event_name": event.get("name", ""),
            "league_id": games_data.get("leagueId"),
            "home": event.get("homeTeam"), "away": event.get("awayTeam"),
            "available_markets": seen_markets[:80]}
    if had_jobs:
        resp["sgp_price_diag"] = dict(_PRICE_DIAG, http=dict(_PRICE_DIAG["http"]), **_tls_diag())
    if truncated:
        resp["truncated"] = True
    return resp


# ===== Pinnacle guest API (live World Cup specials — no PDF needed) =====
# Pinnacle's own web app talks to guest.api.arcadia.pinnacle.com with a
# static guest key baked into the JS bundle. curl_cffi's Chrome TLS
# fingerprint gets through their Cloudflare layer the same way it gets
# through DK's Akamai. Output shape intentionally mirrors the PDF parser
# (pinnacleSoccer.js) so the front end has one code path for both sources.
PIN_API = "https://guest.api.arcadia.pinnacle.com/0.1"
PIN_GUEST_KEY = _os.environ.get("PINNACLE_GUEST_KEY",
                                "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi2R")
PIN_WC_LEAGUE_ID = _os.environ.get("PINNACLE_WC_LEAGUE_ID", "2686")

# Pinnacle special "description" → our canonical market keys. Same anchored
# patterns as MARKET_DEFS in pinnacleSoccer.js — full-match combos only.
_PIN_SPECIAL_KEYS = [
    ("btts_total",    re.compile(r"^Both Teams To Score/Total Goals$", re.I)),
    ("btts_winner",   re.compile(r"^Both Teams To Score/Winner$", re.I)),
    ("winner_total",  re.compile(r"^Winner/Total Goals$", re.I)),
    ("ht_ft",         re.compile(r"^Half-Time/Full-Time$", re.I)),
    ("oddeven_total", re.compile(r"^Odd/Even ?/ ?Total Goals$", re.I)),
    ("btts",          re.compile(r"^Both Teams To Score\?$", re.I)),
]


def _pin_get(path, attempts=4):
    headers = {"X-API-Key": PIN_GUEST_KEY, "Accept": "application/json"}
    last_err = None
    i = 0
    faults = 0  # profile faults rotate for free; see _get_with_retry_inner
    while i < attempts:
        _wait_for_cooloff()
        sess = session
        try:
            r = sess.get(f"{PIN_API}{path}", headers=headers, timeout=15)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}"
            if r.status_code in (403, 429, 503):
                _trigger_cooloff(1.5 * (i + 1))
                _rotate_session()
        except Exception as e:
            last_err = str(e)
            if faults < len(_IMPERSONATES) and _retire_profile(sess, e):
                faults += 1
                continue
        _time.sleep(0.5 * (i + 1))
        i += 1
    raise RuntimeError(f"pinnacle GET {path} failed: {last_err}")


def pinnacle_wc_games(league_id=None, league=None):
    """List a soccer league's matches straight from Pinnacle's guest API.

    Resolution: explicit league_id > `league` registry key (e.g. 'epl') > the
    World Cup env default. Name kept for back-compat; serves any league."""
    if league_id:
        lid = str(league_id)
    elif league:
        lid = _soccer_league(league).get("pin_id") or PIN_WC_LEAGUE_ID
    else:
        lid = PIN_WC_LEAGUE_ID
    data = _pin_get(f"/leagues/{lid}/matchups")
    out = []
    for m in data:
        if m.get("type") != "matchup" or m.get("parentId"):
            continue
        ps = {p.get("alignment"): p.get("name") for p in m.get("participants", [])}
        if not ps.get("home") or not ps.get("away"):
            continue
        out.append({
            "id": m.get("id"),
            "home": ps.get("home"),
            "away": ps.get("away"),
            "startTime": m.get("startTime", ""),
        })
    out.sort(key=lambda x: x["startTime"])
    return {"matches": out, "leagueId": lid}


def _pin_amer_to_prob(o):
    o = float(o)
    return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def _pin_prob_to_amer(p):
    if p <= 0 or p >= 1:
        return None
    return int(round(-p / (1 - p) * 100)) if p >= 0.5 else int(round((1 - p) / p * 100))


def _pin_devig(sels):
    """Multiplicative devig in place. Valid only for mutually exclusive,
    exhaustive partitions — every group built below is one."""
    probs = [_pin_amer_to_prob(s["odds"]) for s in sels]
    t = sum(probs)
    if t <= 0:
        return
    for s, p in zip(sels, probs):
        s["fair_prob"] = round(p / t, 6)


def _pin_is_half_line(x):
    """True for clean .5 lines (2.5, 9.5). Quarter/integer lines carry push /
    half-win semantics that break the straight-devig assumption."""
    try:
        return abs(float(x) * 2 - round(float(x) * 2)) < 1e-9 and \
               int(round(float(x) * 2)) % 2 == 1
    except (TypeError, ValueError):
        return False


def _pin_result_of(name, home, away):
    n = _norm_soccer(name)
    if "draw" in n or "tie" in n:
        return "draw"
    if _team_matches_soccer(home, n):
        return "home"
    if _team_matches_soccer(away, n):
        return "away"
    return None


def _pin_combo_fields(key, name, home, away):
    """Structured DK-matcher fields for a combo selection name (mirrors
    structureSelection in worldcupEvTab.js, which still serves the PDF path)."""
    def total_of(s):
        side = "Over" if re.search(r"\bover\b", s, re.I) else \
               ("Under" if re.search(r"\bunder\b", s, re.I) else None)
        m = re.search(r"(\d+(?:\.\d+)?)", s)
        return side, (float(m.group(1)) if m else None)
    parts = [p.strip() for p in name.split("&")]
    if key == "btts_total" and len(parts) == 2:
        side, line = total_of(parts[1])
        if re.match(r"^(yes|no)$", parts[0], re.I) and side:
            return {"btts": parts[0].title(), "total_side": side, "total_line": line}
    if key == "btts_winner" and len(parts) == 2:
        r = _pin_result_of(parts[1], home, away)
        if re.match(r"^(yes|no)$", parts[0], re.I) and r:
            return {"btts": parts[0].title(), "result": r}
    if key == "winner_total" and len(parts) == 2:
        r = _pin_result_of(parts[0], home, away)
        side, line = total_of(parts[1])
        if r and side:
            return {"result": r, "total_side": side, "total_line": line}
    if key == "oddeven_total" and len(parts) == 2:
        side, line = total_of(parts[1])
        if re.match(r"^(odd|even)$", parts[0], re.I) and side:
            return {"odd_even": parts[0].title(), "total_side": side, "total_line": line}
    if key == "ht_ft":
        seg = re.split(r"\s+-\s+", name)
        if len(seg) == 2:
            ht, ft = _pin_result_of(seg[0], home, away), _pin_result_of(seg[1], home, away)
            if ht and ft:
                return {"ht": ht, "ft": ft}
    return None


def pinnacle_wc_specials(matchup_id):
    """Fetch one match's markets live from Pinnacle.

    Returns the legacy {markets} dict (combo specials — same shape as the
    PDF parser) PLUS a richer "groups" list covering every devig-able
    partition we can pair with a DK market: 3-way moneyline, totals, asian
    spread (.5 lines), team goals, double chance / draw-no-bet (derived
    from the devigged moneyline), BTTS, goal bands, winning margin, first
    team to score, team to score, corners + cards totals (team & match),
    and per-player "To Score" specials. Each group selection carries
    fair_prob (no-vig) and the structured fields the DK matcher consumes."""
    mid = int(matchup_id)
    rel = _pin_get(f"/matchups/{mid}/related")
    parent = next((m for m in rel if m.get("type") == "matchup"
                   and m.get("id") == mid), None)
    if parent is None:
        parent = next((m for m in rel if m.get("type") == "matchup"), None)
    if parent is None:
        return {"error": f"matchup {matchup_id} not found on pinnacle"}
    ps = {p.get("alignment"): p.get("name") for p in parent.get("participants", [])}
    home, away = ps.get("home"), ps.get("away")

    # Sub-matchups: corners and bookings ride along as separate matchup ids.
    corners_id = next((m.get("id") for m in rel if m.get("type") == "matchup"
                       and m.get("units") == "Corners"), None)
    bookings_id = next((m.get("id") for m in rel if m.get("type") == "matchup"
                        and m.get("units") == "Bookings"), None)

    # Classify every special matchup we know how to price.
    combo_specials = {}   # special matchup id -> (combo key, pid->name)
    other_specials = {}   # special matchup id -> (kind, payload)
    for m in rel:
        if m.get("type") != "special":
            continue
        sp = m.get("special") or {}
        desc = (sp.get("description") or "").strip()
        parts = {p.get("id"): p.get("name") for p in m.get("participants", [])}
        matched_combo = False
        for key, pat in _PIN_SPECIAL_KEYS:
            if pat.match(desc):
                combo_specials[m.get("id")] = (key, parts)
                matched_combo = True
                break
        if matched_combo:
            continue
        if desc == "Total Goals Range":
            other_specials[m.get("id")] = ("total_goals_range", parts)
        elif desc == "Winning Margin":
            other_specials[m.get("id")] = ("winning_margin", parts)
        elif desc == "First Team To Score":
            other_specials[m.get("id")] = ("first_team_to_score", parts)
        elif home and desc == f"{home} To Score?":
            other_specials[m.get("id")] = ("team_to_score:home", parts)
        elif away and desc == f"{away} To Score?":
            other_specials[m.get("id")] = ("team_to_score:away", parts)
        elif sp.get("category") == "Player Props" and desc.endswith(" To Score"):
            player = desc[: -len(" To Score")].strip()
            other_specials[m.get("id")] = (f"player_to_score:{player}", parts)

    prices = _pin_get(f"/matchups/{mid}/markets/related/straight")

    groups = []   # [{key, label, kind, sels:[{name, odds, fair_prob, fields}]}]
    markets = {}  # legacy combo dict (PDF-parser shape)

    def add_group(key, label, kind, sels, devig=True):
        if not sels:
            return
        if devig:
            _pin_devig(sels)
        groups.append({"key": key, "label": label, "kind": kind, "sels": sels})

    def special_sels(price_entry, parts):
        out = []
        for pr in price_entry.get("prices", []):
            name = parts.get(pr.get("participantId"))
            price = pr.get("price")
            if name and isinstance(price, (int, float)):
                out.append({"name": name, "odds": int(price)})
        return out

    ml_fair = None  # {'home':p,'draw':p,'away':p} once the moneyline devigs

    for mk in prices:
        if mk.get("period") not in (0, None):
            continue
        sid = mk.get("matchupId")
        mtype = mk.get("type")

        # --- combo specials (legacy behavior, now with fields + fair) ---
        if sid in combo_specials and mtype == "moneyline":
            key, parts = combo_specials[sid]
            sels = special_sels(mk, parts)
            if sels:
                markets[key] = [{"name": s["name"], "odds": s["odds"]} for s in sels]
                for s in sels:
                    s["fields"] = _pin_combo_fields(key, s["name"], home, away)
                labels = {"btts_total": "BTTS / Total Goals",
                          "btts_winner": "BTTS / Winner",
                          "winner_total": "Winner / Total Goals",
                          "ht_ft": "HT / FT",
                          "oddeven_total": "Odd-Even / Total",
                          "btts": "Both Teams To Score"}
                if key == "btts":
                    for s in sels:
                        s["fields"] = {"btts": s["name"].title()}
                add_group(key, labels.get(key, key), key, sels)
            continue

        # --- named non-combo specials ---
        if sid in other_specials and mtype == "moneyline":
            kind, parts = other_specials[sid]
            sels = special_sels(mk, parts)
            if not sels:
                continue
            if kind == "total_goals_range":
                for s in sels:
                    s["fields"] = {"range": re.sub(r"\s*-\s*", "-", s["name"]).strip()}
                add_group("total_goals_range", "Total Goals Range", "total_goals_range", sels)
            elif kind == "winning_margin":
                for s in sels:
                    n = s["name"]
                    m_by = re.match(r"^(.*?) By (\d+\+?)$", n)
                    if m_by:
                        side = _pin_result_of(m_by.group(1), home, away)
                        s["fields"] = {"side": side, "margin": m_by.group(2)} if side else None
                    elif "Any Score Draw" in n:
                        s["fields"] = {"side": "draw", "margin": "score_draw"}
                    elif n.strip() == "No Goal":
                        s["fields"] = {"side": "draw", "margin": "no_goal"}
                    else:
                        s["fields"] = None
                add_group("winning_margin", "Winning Margin", "winning_margin", sels)
            elif kind == "first_team_to_score":
                for s in sels:
                    r = "neither" if "neither" in s["name"].lower() else \
                        _pin_result_of(s["name"], home, away)
                    s["fields"] = {"result": r} if r else None
                add_group("first_team_to_score", "First Team To Score",
                          "first_team_to_score", sels)
            elif kind.startswith("team_to_score:"):
                team = kind.split(":", 1)[1]
                team_name = home if team == "home" else away
                for s in sels:
                    s["fields"] = {"team": team,
                                   "yes": s["name"].strip().lower() == "yes"}
                add_group(f"team_to_score_{team}", f"{team_name} To Score",
                          "team_to_score", sels)
            elif kind.startswith("player_to_score:"):
                player = kind.split(":", 1)[1]
                for s in sels:
                    s["fields"] = ({"player": player, "yes": True}
                                   if s["name"].strip().lower() == "yes" else None)
                add_group(f"player_to_score_{_norm_soccer(player).replace(' ', '_')}",
                          f"{player} To Score", "player_to_score", sels)
            continue

        # --- parent / corners / bookings straight markets ---
        scope = ("goals" if sid == mid else
                 "corners" if sid == corners_id else
                 "cards" if sid == bookings_id else None)
        if scope is None:
            continue

        if mtype == "moneyline" and scope == "goals":
            sels = []
            for pr in mk.get("prices", []):
                d = pr.get("designation")
                if d in ("home", "draw", "away") and isinstance(pr.get("price"), (int, float)):
                    name = home if d == "home" else (away if d == "away" else "Draw")
                    sels.append({"name": name, "odds": int(pr["price"]),
                                 "fields": {"result": d}})
            add_group("moneyline", "Moneyline (3-way)", "moneyline", sels)
            if len(sels) == 3:
                ml_fair = {s["fields"]["result"]: s["fair_prob"] for s in sels}

        elif mtype == "total":
            line = next((pr.get("points") for pr in mk.get("prices", [])
                         if pr.get("points") is not None), None)
            if not _pin_is_half_line(line):
                continue
            kind = {"goals": "total_goals", "corners": "corners_total",
                    "cards": "cards_total"}[scope]
            label = {"goals": "Total Goals", "corners": "Total Corners",
                     "cards": "Total Cards"}[scope]
            sels = []
            for pr in mk.get("prices", []):
                d = pr.get("designation")
                if d in ("over", "under") and isinstance(pr.get("price"), (int, float)):
                    sels.append({"name": f"{d.title()} {line:g}", "odds": int(pr["price"]),
                                 "fields": {"total_side": d.title(), "total_line": float(line)}})
            add_group(f"{kind}_{line:g}", f"{label} {line:g}", kind, sels)

        elif mtype == "team_total":
            side = mk.get("side")
            line = next((pr.get("points") for pr in mk.get("prices", [])
                         if pr.get("points") is not None), None)
            if side not in ("home", "away") or not _pin_is_half_line(line):
                continue
            kind = {"goals": "team_goals", "corners": "team_corners",
                    "cards": "team_cards"}[scope]
            noun = {"goals": "Goals", "corners": "Corners", "cards": "Cards"}[scope]
            team_name = home if side == "home" else away
            sels = []
            for pr in mk.get("prices", []):
                d = pr.get("designation")
                if d in ("over", "under") and isinstance(pr.get("price"), (int, float)):
                    sels.append({"name": f"{team_name} {d.title()} {line:g}",
                                 "odds": int(pr["price"]),
                                 "fields": {"team": side, "total_side": d.title(),
                                            "total_line": float(line)}})
            add_group(f"{kind}_{side}_{line:g}", f"{team_name} {noun} {line:g}", kind, sels)

        elif mtype == "spread" and scope == "goals":
            prs = mk.get("prices", [])
            hline = next((pr.get("points") for pr in prs
                          if pr.get("designation") == "home"), None)
            if hline is None or not _pin_is_half_line(hline):
                continue
            sels = []
            for pr in prs:
                d = pr.get("designation")
                if d in ("home", "away") and isinstance(pr.get("price"), (int, float)):
                    pts = float(pr.get("points"))
                    team_name = home if d == "home" else away
                    sels.append({"name": f"{team_name} {pts:+g}", "odds": int(pr["price"]),
                                 "fields": {"team": d, "line": pts}})
            add_group(f"spread_{hline:+g}", f"Spread {home} {hline:+g}", "spread", sels)

    # Derived 2-from-3 markets: exact transforms of the devigged moneyline.
    if ml_fair and all(k in ml_fair for k in ("home", "draw", "away")):
        dc = [
            {"name": f"{home} or Draw", "fields": {"dc": "home_draw"},
             "fair_prob": ml_fair["home"] + ml_fair["draw"]},
            {"name": f"Draw or {away}", "fields": {"dc": "draw_away"},
             "fair_prob": ml_fair["draw"] + ml_fair["away"]},
            {"name": f"{home} or {away}", "fields": {"dc": "home_away"},
             "fair_prob": ml_fair["home"] + ml_fair["away"]},
        ]
        for s in dc:
            s["odds"] = None
        add_group("double_chance", "Double Chance (from ML)", "double_chance",
                  dc, devig=False)
        ph, pa = ml_fair["home"], ml_fair["away"]
        if ph + pa > 0:
            dnb = [
                {"name": home, "fields": {"result": "home"}, "odds": None,
                 "fair_prob": round(ph / (ph + pa), 6)},
                {"name": away, "fields": {"result": "away"}, "odds": None,
                 "fair_prob": round(pa / (ph + pa), 6)},
            ]
            add_group("draw_no_bet", "Draw No Bet (from ML)", "draw_no_bet",
                      dnb, devig=False)

    for g in groups:
        for s in g["sels"]:
            if "fair_prob" in s and s["fair_prob"] is not None:
                s["fair_american"] = _pin_prob_to_amer(s["fair_prob"])

    return {
        "ok": True,
        "source": "pinnacle-api",
        "matchup_id": mid,
        "home": home,
        "away": away,
        "league": (parent.get("league") or {}).get("name", "FIFA - World Cup"),
        "kickoff": parent.get("startTime", ""),
        "markets": markets,
        "groups": groups,
        "sgp_markets_found": [k for k in markets
                              if k in ("btts_total", "btts_winner", "winner_total",
                                       "ht_ft", "oddeven_total")
                              and len(markets[k]) >= 2],
    }


def find_sgps(legs, enum_size=2):
    """Given OCR'd legs, auto-match them to DK selections, enumerate combos
    of the requested size, and return DK-priced SGPs. Frontend computes FV
    and EV.

    enum_size=2 (default, back-compat) enumerates pairs; enum_size=3 enumerates
    triplets. DK's calculateBets endpoint is N-leg native, so the pricing call
    itself is unchanged — only the combination generator and the per-pitcher
    worst-case price-call budget differ. A pitcher with k matched legs yields
    C(k,2) pairs or C(k,3) triplets; the 110s soft deadline still bounds total
    pricing. Any combos not priced before the deadline surface truncated=True
    and the caller should retry or narrow the leg list."""
    from itertools import combinations
    import concurrent.futures

    if enum_size not in (2, 3):
        return {"error": f"enum_size must be 2 or 3, got {enum_size}"}

    # Soft deadline: return partial results before Node's spawn timeout SIGTERMs us.
    pricing_deadline = _time.monotonic() + 110.0
    truncated = False

    # Group by pitcher
    by_pitcher = {}
    for l in legs:
        by_pitcher.setdefault(l.get("pitcher", ""), []).append(l)
    by_pitcher.pop("", None)

    if not by_pitcher:
        return {"error": "No pitcher legs provided"}

    # Fetch games list (graceful on DK rate-limit failure so the subprocess
    # doesn't exit 1 and surface as an opaque "dk_api.py exited with code 1"
    # to the frontend).
    try:
        games_data = get_games()
    except Exception as e:
        return {"error": f"DK games endpoint unavailable: {e}. Try again in a moment."}
    events = [e for e in games_data["events"] if e.get("hasSGP")]

    # Scan games in parallel to find each pitcher's event
    event_markets = {}
    pitcher_events = {}
    unfound = set(by_pitcher.keys())

    def scan(eid):
        try:
            md = get_markets(eid, pitcher_only=True)
            return eid, md
        except Exception:
            return eid, None

    # max_workers=2: each per-event scan itself fans out 2 subcat workers, so
    # effective concurrency against DK is 4. Anything higher triggers Akamai's
    # 403 cascade and the whole find-sgps call ends up retrying through a block.
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(scan, e["id"]): e["id"] for e in events[:15]}
        for fut in as_completed(futs):
            eid, md = fut.result()
            if md is None:
                continue
            event_markets[eid] = md
            for p in md["props"]:
                if not p.get("isPitcherProp"):
                    continue
                player = p.get("player", "")
                if not player:
                    continue
                for pitcher in list(unfound):
                    if _pitcher_matches(pitcher, player):
                        pitcher_events[pitcher] = eid
                        unfound.discard(pitcher)
            if not unfound:
                # Cancel remaining futures
                for f in futs:
                    f.cancel()
                break

    results = {}
    for pitcher, plegs in by_pitcher.items():
        eid = pitcher_events.get(pitcher)
        game_info = next((e for e in events if e["id"] == eid), {}) if eid else {}
        if not eid or eid not in event_markets:
            results[pitcher] = {"error": "Pitcher not found in today's DK games"}
            continue

        md = event_markets[eid]
        matched = []
        unmatched = []
        for l in plegs:
            dk_id = _match_leg_to_dk(l, md["props"], pitcher)
            if dk_id:
                matched.append({
                    "leg": l.get("leg"),
                    "avg_fv": l.get("avg_fv"),
                    "_fv_suspicious": bool(l.get("_fv_suspicious", False)),
                    "dk_selection_id": dk_id,
                })
            else:
                unmatched.append(l.get("leg"))

        base = {
            "event_id": eid,
            "game_name": game_info.get("name", ""),
            "start_date": game_info.get("startDate", ""),
            "matched_legs": matched,
            "unmatched_legs": unmatched,
        }

        min_legs = enum_size
        combos_key = f"combos_{enum_size}"
        if len(matched) < min_legs:
            results[pitcher] = {**base, combos_key: [],
                               "warning": f"Need {min_legs}+ matched legs ({len(matched)}/{len(plegs)} matched to DK)"}
            continue

        if _time.monotonic() >= pricing_deadline:
            truncated = True
            results[pitcher] = {**base, combos_key: [],
                               "warning": "Skipped: pricing time budget exceeded. Try again."}
            continue

        # Enumerate combos of the requested size (indices into matched[]).
        # combinations() returns canonical ascending indices, but matched[]
        # order follows OCR row order, so the same logical combo can render
        # with legs in different positions across sheets. Sort each combo's
        # indices by the leg's stat category (alphabetical) so the tuple is
        # stable regardless of OCR order — downstream (frontend card render,
        # correlation lookup) relies on a consistent orientation.
        combo_indices = []
        for combo in combinations(range(len(matched)), enum_size):
            ordered = sorted(combo, key=lambda i: _stat_cat(matched[i].get("leg")) or "")
            combo_indices.append(list(ordered))

        # DK 3-leg pricing also rejects some triplets as incompatible (e.g.
        # all-same-stat combos that can't legally parlay in an SGP — "Over 4+ K"
        # with "5+ K" etc.). _price_combo returns None for those; they're
        # simply omitted from the returned combos list rather than surfaced
        # as errors, matching the 2-leg contract.
        def price_one(idx, indices):
            sel_ids = [matched[i]["dk_selection_id"] for i in indices]
            price = _price_combo(sel_ids)
            return idx, indices, price

        priced = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(price_one, i, idx) for i, idx in enumerate(combo_indices)]
            remaining = max(0.5, pricing_deadline - _time.monotonic())
            try:
                for f in as_completed(futs, timeout=remaining):
                    try:
                        _i, indices, price = f.result()
                        if price:
                            priced[tuple(indices)] = price
                    except Exception:
                        pass
            except concurrent.futures.TimeoutError:
                truncated = True
                for f in futs:
                    f.cancel()

        priced_combos_out = []
        for indices in combo_indices:
            price = priced.get(tuple(indices))
            if not price:
                continue
            entry = {
                "leg_indices": indices,
                "dk_odds": price["sgpOdds"],
                "dk_decimal": price["sgpDecimal"],
            }
            # Per-leg DK pricing (trueOdds = vigged decimal per leg) is needed
            # for the DK-hold / correlation-price sanity line on 3-leg cards.
            # Kept out of the 2-leg shape to stay byte-for-byte back-compat.
            # _price_combo returns selectionsForYourBet as `legInfo`; each
            # entry there carries trueOdds as the vigged decimal.
            if enum_size == 3:
                entry["leg_true_odds"] = [lg.get("trueOdds") for lg in price.get("legInfo", [])]
            priced_combos_out.append(entry)

        results[pitcher] = {**base, combos_key: priced_combos_out}

    out = {"pitchers": results}
    if truncated:
        out["truncated"] = True
    # Same diagnosability the World Cup path got in the 2026-07-04 fix: when
    # every combo silently fails to price, the tally says WHY (Akamai 403
    # storm vs incompatible legs vs DK outage) without shell access to prod.
    out["sgp_price_diag"] = dict(_PRICE_DIAG, http=dict(_PRICE_DIAG["http"]), **_tls_diag())
    return out


def get_price(selection_ids):
    """Get correlated SGP price from DraftKings."""
    payload = {
        "selections": [],
        "selectionsForYourBet": [{"id": sid, "yourBetGroup": 0} for sid in selection_ids],
        "selectionsForCombinator": [],
        "selectionsForProgressiveParlay": [],
        "oddsStyle": "american",
    }
    r = _post_with_retry(DK_PRICE, json=payload, timeout=15, headers=DK_PRICE_HEADERS)

    if r.status_code == 422:
        return {"error": "Incompatible leg combination", "incompatible": True}

    if r.status_code != 200:
        # Return the status instead of raising: an opaque exit-1 from the
        # subprocess hides WHICH way calculateBets is failing (Akamai 403 vs
        # payload 400 vs outage 5xx), and that distinction is the whole
        # diagnosis when every SGP price call starts dying at once.
        return {"error": f"calculateBets HTTP {r.status_code}",
                "status": r.status_code,
                "body": (r.text or "")[:300]}
    data = r.json()

    restrictions = data.get("combinabilityRestrictions", [])
    if restrictions:
        return {"error": "Legs cannot be combined", "incompatible": True, "restrictions": restrictions}

    bets = data.get("bets", [])
    bet = next((b for b in bets if b.get("trueOdds") and len(b.get("selectionsMapped", [])) >= 2), None)
    if not bet:
        return {"error": "No valid SGP price returned"}

    legs = []
    for sel in data.get("selectionsForYourBet", []):
        legs.append({
            "id": sel.get("id"),
            "displayOdds": sel.get("displayOdds", ""),
            "trueOdds": sel.get("trueOdds"),
            "points": sel.get("points"),
        })

    return {
        "sgpOdds": bet.get("displayOdds", ""),
        "sgpDecimal": bet.get("trueOdds"),
        "legs": legs,
        "legCount": len(legs),
    }


def _parse_iso_epoch(s):
    """Best-effort ISO-8601 -> unix seconds. Returns None on failure."""
    if not s:
        return None
    import datetime
    t = str(s).strip().replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(t).timestamp()
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(t, fmt).timestamp()
        except Exception:
            continue
    return None


def _dk_games_for_league(key, attempts=2):
    """Fetch one league's DK games with a SHORT retry budget so a blocked league
    (Akamai 403 from a flagged IP) fails fast instead of burning the sweep's
    time budget. Returns (events_list, error_str)."""
    entry = _soccer_league(key)
    lid = entry.get("dk_id")
    if not lid:
        return None, "no dk_id configured"
    try:
        r = _get_with_retry(f"{DK_LEAGUES}/{lid}", attempts=attempts, timeout=12)
    except Exception as e:
        return None, str(e)[:160]
    out = []
    for e in r.json().get("events", []) or []:
        parts = e.get("participants", []) or []
        home = next((p for p in parts if p.get("venueRole") == "Home"), None) or (parts[0] if parts else {})
        away = next((p for p in parts if p.get("venueRole") == "Away"), None) or (parts[1] if len(parts) > 1 else {})
        out.append({"id": _ev_id(e),
                    "homeTeam": (home or {}).get("name", ""),
                    "awayTeam": (away or {}).get("name", ""),
                    "hasSGP": "SGP" in (e.get("tags", []) or [])})
    return out, None


def find_sgps_soccer_all(payload):
    """One-button sweep of the major soccer leagues: every upcoming game's
    Pinnacle combo fair lines (BTTS/Total, BTTS/Winner, Winner/Total,
    Odd-Even/Total, HT/FT) vs DK's real 2-leg SGP price, as one flat EV-ranked
    list. No league/game picking.

    The Pinnacle side always works (guest API). The DK side is best-effort: if
    DK's Akamai edge 403s this server's IP, DK is marked unavailable and rows
    still carry Pinnacle fair lines (the price to beat).

    Input (all optional): { sgp_only, max_games, window_hours, leagues[],
                            deadline_s }
    """
    payload = payload or {}
    sgp_only = payload.get("sgp_only", True)
    max_games = int(payload.get("max_games", 24))
    window_hours = float(payload.get("window_hours", 72))
    leagues = payload.get("leagues") or MAJOR_SOCCER_LEAGUES
    deadline = _time.monotonic() + float(payload.get("deadline_s", 95))
    now = _time.time()
    lo, hi = now - 3 * 3600, now + window_hours * 3600

    # --- Phase 1: Pinnacle games per league (concurrent) ---
    def _pin_games(key):
        try:
            g = pinnacle_wc_games(league=key)
            return key, g.get("matches", []), None
        except Exception as e:
            return key, [], str(e)[:120]

    league_errors = {}
    all_games = []  # (kickoff_epoch, league_key, match)
    with ThreadPoolExecutor(max_workers=6) as ex:
        for key, matches, err in ex.map(_pin_games, leagues):
            if err:
                league_errors[key] = "pinnacle: " + err
            for m in matches:
                ep = _parse_iso_epoch(m.get("startTime"))
                if ep is None or (lo <= ep <= hi):
                    all_games.append(((ep or hi), key, m))
    all_games.sort(key=lambda t: t[0])
    all_games = all_games[:max_games]

    # --- Phase 2: Pinnacle specials -> combo candidates per game (concurrent) ---
    def _specials(item):
        ep, key, m = item
        try:
            spec = pinnacle_wc_specials(m["id"])
            if spec.get("error"):
                return item, None, spec["error"]
            return item, spec, None
        except Exception as e:
            return item, None, str(e)[:120]

    games = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for item, spec, err in ex.map(_specials, all_games):
            ep, key, m = item
            if not spec:
                continue
            home, away = spec.get("home") or m.get("home"), spec.get("away") or m.get("away")
            cands = []
            for g in spec.get("groups", []):
                if g.get("kind") not in _SOCCER_COMBO_KINDS:
                    continue
                for i, s in enumerate(g.get("sels", [])):
                    if s.get("fair_prob") is None or not s.get("fields"):
                        continue
                    c = {"id": g["key"] + ":" + str(i), "market_key": g["kind"],
                         "group_label": g.get("label", ""),
                         "selection": s.get("name", ""),
                         "pin_american": s.get("odds"),
                         "fair_american": s.get("fair_american"),
                         "fair_prob": s.get("fair_prob")}
                    c.update(s["fields"])
                    cands.append(c)
            if cands:
                games.append({"key": key, "home": home, "away": away,
                              "game": (away or "?") + " @ " + (home or "?"),
                              "start": m.get("startTime", ""), "candidates": cands})

    # --- Phase 3: DK match + price per league (best-effort, IP-block-aware) ---
    dk_events_by_league = {}
    dk_error_by_league = {}
    dk_blocked = False
    leagues_with_games = [k for k in leagues if any(g["key"] == k for g in games)]
    for key in leagues_with_games:
        if dk_blocked:
            dk_error_by_league[key] = "skipped (DK unreachable from this IP)"
            continue
        evs, err = _dk_games_for_league(key)
        if err:
            dk_error_by_league[key] = err
            if not dk_events_by_league:   # first failure, no prior success => IP block
                dk_blocked = True
            continue
        dk_events_by_league[key] = evs

    def _amer_to_dec(a):
        try:
            a = float(str(a).replace("−", "-"))
        except (TypeError, ValueError):
            return None
        return 1 + (a / 100.0 if a > 0 else 100.0 / -a)

    rows = []
    priced_any = False
    for g in games:
        dk_result_by_id = {}
        dk_status = "blocked" if (dk_blocked or g["key"] not in dk_events_by_league) else None
        if dk_status is None:
            event = _event_for_soccer_match(g["home"], g["away"], dk_events_by_league[g["key"]])
            if not event:
                dk_status = "no_dk_event"
            elif _price_blocked() and not priced_any:
                # Every pricing POST is 403ing and nothing has priced all
                # sweep: the remaining games can't do better, so skip their
                # market fetches too and finish now with an honest status.
                dk_status = "pricing_blocked"
            elif _time.monotonic() >= deadline:
                dk_status = "deadline"
            else:
                try:
                    md = get_markets(event["id"], soccer_only=True)
                    res, _hj, _tr = _price_event_combos(
                        md, g["home"], g["away"], g["candidates"],
                        sgp_only=sgp_only, deadline=deadline)
                    dk_result_by_id = {r["id"]: r for r in res}
                    dk_status = "scanned"
                except Exception as e:
                    dk_status = "dk_error:" + str(e)[:60]
        lg_label = _soccer_league(g["key"]).get("label", g["key"])
        for c in g["candidates"]:
            row = {"league": lg_label, "game": g["game"], "start": g["start"],
                   "market_key": c["market_key"], "group_label": c["group_label"],
                   "selection": c["selection"], "pin_american": c["pin_american"],
                   "fair_american": c["fair_american"], "fair_prob": c["fair_prob"],
                   "dk_american": None, "dk_decimal": None, "ev_pct": None,
                   "kelly_pct": None, "via": None, "dk_status": dk_status}
            dr = dk_result_by_id.get(c["id"])
            if dr and dr.get("matched"):
                dec = dr.get("dk_decimal")
                if not dec or dec <= 1:
                    dec = _amer_to_dec(dr.get("dk_american"))
                row["dk_american"] = dr.get("dk_american")
                row["dk_decimal"] = dec
                row["via"] = dr.get("via")
                if dec and dec > 1:
                    row["ev_pct"] = (c["fair_prob"] * dec - 1) * 100
                    row["kelly_pct"] = (c["fair_prob"] * dec - 1) / (dec - 1) * 100
                    priced_any = True
                row["dk_status"] = "priced"
            elif dr:
                row["dk_status"] = "pricing_blocked" if dr.get("price_blocked") else "no_match"
            rows.append(row)

    def _sort_key(r):
        if r["ev_pct"] is not None:
            return (0, -r["ev_pct"])
        if r["dk_american"] is not None:
            return (1, 0)
        return (2, -(r["fair_prob"] or 0))
    rows.sort(key=_sort_key)

    summary = {
        "leagues_swept": len(leagues), "games_found": len(all_games),
        "games_with_candidates": len(games), "rows": len(rows),
        "dk_blocked": dk_blocked, "dk_priced_any": priced_any,
        "dk_errors": dk_error_by_league, "pinnacle_errors": league_errors,
    }
    if games:
        summary["sgp_price_diag"] = dict(_PRICE_DIAG, http=dict(_PRICE_DIAG["http"]), **_tls_diag())
    return {"rows": rows, "summary": summary, "sgp_only": bool(sgp_only)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: dk_api.py <games|markets|featured|price|games-tennis|find-sgps-tennis> [args]"}))
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        if cmd == "games":
            result = get_games()
        elif cmd == "markets" and len(sys.argv) >= 3:
            result = get_markets(sys.argv[2])
        elif cmd == "featured" and len(sys.argv) >= 3:
            result = get_featured(sys.argv[2])
        elif cmd == "find-sgps":
            stdin_data = sys.stdin.read().strip()
            parsed = json.loads(stdin_data) if stdin_data else []
            # Back-compat: bare array payload means legs only, enum_size=2.
            # Richer {legs, enumSize} object enables 3-leg enumeration without
            # breaking older callers.
            if isinstance(parsed, dict):
                legs = parsed.get("legs", [])
                enum_size = int(parsed.get("enumSize", 2))
            else:
                legs = parsed
                enum_size = 2
            result = find_sgps(legs, enum_size=enum_size)
        elif cmd == "find-sgps-teammate":
            stdin_data = sys.stdin.read().strip()
            payload = json.loads(stdin_data) if stdin_data else {}
            result = find_sgps_teammate(payload)
        elif cmd == "find-sgps-nba":
            stdin_data = sys.stdin.read().strip()
            payload = json.loads(stdin_data) if stdin_data else {}
            result = find_sgps_nba(payload)
        elif cmd == "games-tennis":
            result = get_games_tennis()
        elif cmd == "find-sgps-tennis":
            stdin_data = sys.stdin.read().strip()
            payload = json.loads(stdin_data) if stdin_data else {}
            result = find_sgps_tennis(payload)
        elif cmd == "enumerate-sgps-tennis":
            stdin_data = sys.stdin.read().strip()
            payload = json.loads(stdin_data) if stdin_data else {}
            result = enumerate_sgps_tennis(payload)
        elif cmd == "soccer-leagues":
            result = {
                "leagues": [
                    {"key": k, "label": v["label"], "dk_id": v["dk_id"],
                     "dk_slug": v["dk_slug"], "pin_id": v["pin_id"]}
                    for k, v in SOCCER_LEAGUES.items()
                ],
                "default": DEFAULT_SOCCER_LEAGUE,
            }
        elif cmd == "games-worldcup":
            # arg may be a numeric DK league id or a registry key (e.g. 'epl').
            arg = sys.argv[2] if len(sys.argv) >= 3 else None
            if arg and not arg.isdigit():
                result = get_games_soccer(league=arg)
            else:
                result = get_games_soccer(league_id=arg)
        elif cmd == "find-sgps-worldcup":
            stdin_data = sys.stdin.read().strip()
            payload = json.loads(stdin_data) if stdin_data else {}
            result = find_sgps_worldcup(payload)
        elif cmd == "find-sgps-soccer-all":
            stdin_data = sys.stdin.read().strip()
            payload = json.loads(stdin_data) if stdin_data else {}
            result = find_sgps_soccer_all(payload)
        elif cmd == "pinnacle-wc-games":
            # arg may be a numeric Pinnacle league id or a registry key.
            arg = sys.argv[2] if len(sys.argv) >= 3 else None
            if arg and not arg.isdigit():
                result = pinnacle_wc_games(league=arg)
            else:
                result = pinnacle_wc_games(league_id=arg)
        elif cmd == "pinnacle-wc-specials" and len(sys.argv) >= 3:
            result = pinnacle_wc_specials(sys.argv[2])
        elif cmd == "resolve-worldcup-league":
            slug = sys.argv[2] if len(sys.argv) >= 3 else None
            result = resolve_soccer_league_by_slug(slug)
        elif cmd == "resolve-tennis-league":
            slug = sys.argv[2] if len(sys.argv) >= 3 else "french-open-men"
            result = resolve_tennis_league_by_slug(slug)
        elif cmd == "price":
            stdin_data = sys.stdin.read().strip()
            if stdin_data:
                selection_ids = json.loads(stdin_data)
            elif len(sys.argv) >= 4:
                selection_ids = sys.argv[3:]
            else:
                selection_ids = []
            if len(selection_ids) < 2:
                result = {"error": "Need at least 2 selection IDs"}
            else:
                result = get_price(selection_ids)
        else:
            result = {"error": f"Unknown command or missing args: {cmd}"}
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
