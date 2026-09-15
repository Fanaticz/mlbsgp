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
    DK_PROXY=http://user:pass@host:443 python3 scripts/probe_dk_price.py
    # …or connect the VPN first and run it bare.

Cookie sources are the ones dk_api.py already honours, highest first:
    DK_COOKIES="…"        raw cookie string copied from a browser that was on
                          THIS SAME egress (Akamai binds _abck to the IP)
    DK_COOKIE_BROWSER=1   mint one here with headless Chromium
                          (needs `pip install playwright`; point
                          DK_CHROMIUM_PATH at the binary if not on the
                          default search path)

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


def egress_ip():
    """The IP DK will see: goes through the same curl_cffi session (and so
    the same DK_PROXY / TLS profile) as the pricing POST."""
    try:
        r = dk_api.session.get("https://api.ipify.org?format=json", timeout=10)
        return r.json().get("ip") or "?"
    except Exception as e:
        return f"unavailable ({type(e).__name__})"


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
    want = sys.argv[1] if len(sys.argv) > 1 else None

    requested = ('DK_COOKIES' if os.environ.get('DK_COOKIES')
                 else 'DK_COOKIE_BROWSER' if os.environ.get('DK_COOKIE_BROWSER')
                 else 'homepage warmup (unvalidated)')
    print("egress:")
    print(f"  DK_PROXY      : {os.environ.get('DK_PROXY') or '(none — direct)'}")
    print(f"  ip as DK sees : {egress_ip()}")
    print(f"  tls profile   : {dk_api._tls_diag().get('tls_profile')}")
    print(f"  cookie source : {requested} (requested; see calculateBets line for what was used)")

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
                print("(DK_COOKIE_BROWSER was requested but the headless mint fell back to")
                print(" warmup — Akamai denied the headless browser, or Playwright/Chromium")
                print(" isn't usable here. Use the DK_COOKIES paste instead.)")
        return 2
    print(f"\nFAIL (HTTP {status}) — not an Akamai block; see body above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
