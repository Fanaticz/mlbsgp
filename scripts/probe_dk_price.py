#!/usr/bin/env python3
"""Probe: can THIS egress (bare / VPN / DK_PROXY) price a DK same-game parlay?

DK's calculateBets endpoint sits behind Akamai, which 403s on two separate
grounds — a datacenter-scored egress IP, and an unvalidated `_abck` cookie —
and the bare "Access Denied" page doesn't say which. This probe runs one
real 2-leg pitcher SGP price through the same session dk_api.py uses and
prints a verdict that separates the two, so a VPN / residential-proxy trial
gets a clean answer instead of "still 403".

Run it once per egress you want to evaluate:

    python3 scripts/probe_dk_price.py                      # bare
    DK_PROXY='http://user-session-{session}:pass@host:port' python3 scripts/probe_dk_price.py
    # …or connect the VPN first and run it bare.

    --mint-only   stop before calculateBets: just mint a cookie with the
                  headless browser (DK_COOKIE_BROWSER=1) and report the
                  engine, the _abck state, and whether the browser and
                  curl_cffi leave from the same IP. No wager-endpoint call.

Cookie sources are the ones dk_api.py already honours, highest first:
    DK_COOKIES="…"        raw cookie string copied from a browser that was on
                          THIS SAME egress (Akamai binds _abck to the IP)
    DK_COOKIE_BROWSER=1   mint one here (patchright / playwright / SeleniumBase
                          UC, see DK_COOKIE_BROWSER_ENGINE) — through DK_PROXY
                          when set, so cookie and POST share one exit. Point
                          DK_CHROMIUM_PATH at the binary if it isn't on the
                          default search path.

Exit codes: 0 = DK priced the combo (egress + cookie both fine)
            2 = 403 from Akamai (see verdict for which variable to change)
            1 = anything else (network, no games, DK outage)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import dk_api  # noqa: E402


def proxy_line():
    """DK_PROXY as it may be printed: host only, never the credentials, plus
    what we know about stickiness."""
    if not dk_api._DK_PROXY:
        return "(none — direct)"
    d = dk_api._proxy_diag() or {}
    if d.get("session"):
        how = "sticky: {session} = " + d["session"]
    elif d.get("sticky"):
        how = "sticky: DK_PROXY_SESSION pinned"
    else:
        how = ("stickiness unknown — no {session} placeholder in DK_PROXY; if the "
               "provider rotates per request, the cookie and the POST won't share an IP")
    return f"{d.get('host')} [{how}]"


def egress_ip():
    """The IP DK will see: goes through the same curl_cffi session (and so
    the same DK_PROXY / TLS profile) as the pricing POST."""
    try:
        r = dk_api.session.get("https://api.ipify.org?format=json", timeout=10)
        return r.json().get("ip") or "?"
    except Exception as e:
        return f"unavailable ({type(e).__name__})"


def browser_egress_ip():
    """The IP the cookie-minting browser exits from. Must equal egress_ip()
    or the minted _abck is bound to the wrong address. Uses the same driver,
    binary and proxy the mint does (skipped for the UC engine)."""
    engine, sp = dk_api._mint_engine()
    if not engine:
        return "skipped (no browser driver installed)"
    if engine == "uc":
        return "skipped (uc engine)"
    proxy_kw = dk_api._browser_proxy_kw(dk_api._mint_proxy_url())
    try:
        with sp() as p:
            kw = {"headless": True, "args": ["--no-sandbox"]}
            exe = os.environ.get("DK_CHROMIUM_PATH")
            if exe:
                kw["executable_path"] = exe
            if proxy_kw:
                kw["proxy"] = proxy_kw
            b = p.chromium.launch(**kw)
            try:
                pg = b.new_context(ignore_https_errors=bool(proxy_kw)).new_page()
                pg.goto("https://api.ipify.org?format=json", timeout=20000)
                return json.loads(pg.inner_text("body")).get("ip") or "?"
            finally:
                b.close()
    except Exception as e:
        return f"unavailable ({type(e).__name__})"


def mint_report(curl_ip):
    """Run the browser mint now and describe it. Returns the _abck state."""
    cookies = dk_api._mint_cookies_with_browser()
    m = dk_api._MINT_DIAG
    abck = dk_api._abck_state_of_value((cookies or {}).get("_abck"))
    print(f"\nbrowser mint: engine={m.get('engine')} source={m.get('source')} "
          f"cookies={len(cookies or {})} _abck={abck}")
    if m.get("source") == "unavailable":
        print("  no driver: pip install patchright && patchright install chromium "
              "(or playwright / seleniumbase); see LOCAL_RUN.md")
    bip = browser_egress_ip()
    print(f"  browser egress ip : {bip}")
    print(f"  curl egress ip    : {curl_ip}")
    if bip and curl_ip and not bip.startswith(("skipped", "unavailable")) \
            and not curl_ip.startswith("unavailable") and bip != curl_ip:
        print("  !! the browser and the pricing POST leave from DIFFERENT IPs — the")
        print("     minted cookie is bound to the wrong address. With DK_PROXY, that")
        print("     means the session isn't sticky: put {session} in the proxy username.")
    return abck


def pick_legs(props, pitcher):
    """Two cross-stat legs on one pitcher — the shape DK always allows in an
    SGP, so a 'Legs cannot be combined' answer can't be mistaken for a block.
    Prefers K Over + ER Under; falls back to any two distinct market types."""
    mine = [p for p in props if p.get("isPitcherProp") and p.get("player") == pitcher]
    k_over = next((p for p in mine if p["marketType"] == "Strikeouts Thrown O/U"
                   and p["outcomeType"] == "Over"), None)
    er_under = next((p for p in mine if p["marketType"] == "Earned Runs Allowed O/U"
                     and p["outcomeType"] == "Under"), None)
    if k_over and er_under:
        return [k_over, er_under]
    seen = {}
    for p in mine:
        seen.setdefault(p["marketType"], p)
        if len(seen) == 2:
            return list(seen.values())
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mint_only = "--mint-only" in sys.argv[1:]
    want = args[0] if args else None
    use_browser = bool(os.environ.get("DK_COOKIE_BROWSER", "").strip()) \
        and os.environ.get("DK_COOKIE_BROWSER", "").strip().lower() not in ("0", "false", "no")

    requested = ('DK_COOKIES' if os.environ.get('DK_COOKIES')
                 else 'DK_COOKIE_BROWSER' if use_browser
                 else 'homepage warmup (unvalidated)')
    curl_ip = egress_ip()
    print("egress:")
    print(f"  DK_PROXY      : {proxy_line()}")
    print(f"  ip as DK sees : {curl_ip}")
    print(f"  tls profile   : {dk_api._tls_diag().get('tls_profile')}")
    print(f"  cookie source : {requested} (requested; see calculateBets line for what was used)")
    if use_browser:
        print(f"  mint engine   : {dk_api._mint_engine()[0] or 'none installed'}")

    if mint_only:
        if not use_browser:
            print("\n--mint-only needs DK_COOKIE_BROWSER=1 (nothing to mint otherwise).")
            return 1
        abck = mint_report(curl_ip)
        if abck == "validated":
            print("\nMINT OK — Akamai validated _abck on this exit. Now run the probe without")
            print("--mint-only to price a real combo, or start the app with the same env.")
            return 0
        print(f"\nMINT FAILED (_abck {abck}) — the sensor did not validate on this exit.")
        print("From a datacenter IP that is expected (Akamai scores the address, not the")
        print("browser); it needs a residential/mobile DK_PROXY. On a home connection,")
        print("try DK_COOKIE_BROWSER_ENGINE=uc with DK_COOKIE_BROWSER_HEADLESS=0.")
        return 2

    try:
        games = dk_api.get_games()
    except Exception as e:
        print(f"\nFAIL: DK games endpoint unreachable: {e}")
        return 1
    events = [e for e in games.get("events", []) if e.get("hasSGP") and not e.get("isLive")]
    if not events:
        print("\nFAIL: no pre-game SGP-eligible MLB events on the board right now")
        return 1
    print(f"\nread endpoints: ok ({len(events)} SGP-eligible games)")

    legs = None
    for ev in events:
        for pitcher in (ev.get("awayStarter"), ev.get("homeStarter")):
            if not pitcher or (want and want.lower() not in pitcher.lower()):
                continue
            try:
                md = dk_api.get_markets(ev["id"], pitcher_only=True)
            except Exception as e:
                print(f"  markets {ev['id']} failed: {e}")
                continue
            legs = pick_legs(md.get("props", []), pitcher)
            if legs:
                break
        if legs:
            break
    if not legs:
        print("\nFAIL: couldn't find two pitcher legs to price" + (f" for '{want}'" if want else ""))
        return 1

    print(f"\ncombo: {ev['name']} — {legs[0]['player']}")
    for l in legs:
        print(f"  {l['marketType']:28s} {l['betslipLine']:12s} {l['oddsAmerican']}")

    res = dk_api.get_price([l["selectionId"] for l in legs])
    diag = dk_api._PRICE_DIAG
    abck = dk_api._abck_validation_state(dk_api.session.cookies.jar)
    print(f"\ncalculateBets: cookie={diag.get('cookie_source')} _abck={abck}")
    if diag.get("mint"):
        m = diag["mint"]
        print(f"  mint: engine={m.get('engine')} source={m.get('source')} _abck={m.get('abck')}")

    if res.get("sgpOdds"):
        print(f"\nPASS — DK priced the SGP at {res['sgpOdds']} (decimal {res.get('sgpDecimal')}).")
        print("This egress + cookie can drive the +EV finder.")
        return 0
    if res.get("incompatible"):
        print("\nPASS — calculateBets answered (legs rejected as incompatible, but the")
        print("endpoint served us). Egress and cookie are fine; pick different legs.")
        return 0

    status = res.get("status")
    print(f"\nresult: {json.dumps(res)[:300]}")
    if status == 403:
        if abck == "validated":
            print("\nFAIL (403, cookie validated) — Akamai has scored this IP itself.")
            if dk_api._DK_PROXY:
                d = dk_api._proxy_diag() or {}
                if d.get("sticky"):
                    print("DK_PROXY is on and sticky, so this proxy's exit is scored too. Try")
                    print("another location / a mobile pool, or a new session id")
                    print("(DK_PROXY_SESSION=<anything new>) to draw a different exit.")
                else:
                    print("DK_PROXY is on but nothing pins the exit: if the provider rotates,")
                    print("the cookie was minted on one IP and the POST left from another.")
                    print("Put {session} in the proxy username (see LOCAL_RUN.md) and rerun.")
            else:
                print("The cookie isn't the problem; only the egress is. Try another VPN")
                print("exit / a residential DK_PROXY, then rerun.")
        else:
            print(f"\nFAIL (403, _abck {abck}) — AMBIGUOUS: an unvalidated cookie 403s on")
            print("every IP, so this doesn't yet say whether the egress is the problem.")
            print("Rerun on this same egress with a validated cookie. On a VPN that means")
            print("the browser and this script must share the VPN (Akamai binds _abck to")
            print("the IP that minted it):")
            print("  1. connect the VPN; open draftkings.com in a normal browser; open a")
            print("     game and add 2 legs to the bet slip (this is what validates _abck)")
            print("  2. DevTools console: copy(document.cookie)")
            print("  3. DK_COOKIES='<paste>' python3 scripts/probe_dk_price.py")
            if requested == 'DK_COOKIE_BROWSER':
                m = diag.get("mint") or {}
                print(f"(DK_COOKIE_BROWSER was requested; the mint reported engine={m.get('engine')}")
                print(f" source={m.get('source')} _abck={m.get('abck')}. From a flagged IP the sensor")
                print(" never validates whatever the engine — that needs a residential DK_PROXY.")
                print(" Use --mint-only to iterate on the mint without touching calculateBets.)")
        return 2
    print(f"\nFAIL (HTTP {status}) — not an Akamai block; see body above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
