#!/usr/bin/env python3
"""BetOnline MMA-props scraper + DraftKings profit-boost comparator.

BetOnline fronts www.betonline.ag with a Cloudflare rule that 403s most
datacenter traffic and rejects a Chrome TLS fingerprint outright, so requests
are made with curl_cffi impersonating Safari. The odds themselves never appear
in the page HTML (Astro shell + Diffusion push), but the same data is served by
the REST offering API the SPA calls, which only needs the brand header
`gsetting: bolsassite` -- no account or token.

Usage:
  python3 scripts/betonline_mma_props.py list
  python3 scripts/betonline_mma_props.py fight <slug>
  python3 scripts/betonline_mma_props.py compare --dk dk_method_of_victory.json [--boost 0.5]

The compare payload maps a fighter to their DraftKings method-of-victory
prices, which is the one market both books post for every fight on a card:

  {"Dan Hooker": {"ko": 900, "sub": 1600, "dec": 1400}, ...}
"""

import argparse
import json
import os
import sys

from curl_cffi import requests

OFFERING_API = "https://api-offering.betonline.ag"
GSETTING = "bolsassite"  # webAppConfig.BRAND_G_SETTING_OFFERING
IMPERSONATE = "safari18_0"  # chrome* fingerprints get reset by their edge

HEADERS = {
    "origin": "https://www.betonline.ag",
    "referer": "https://www.betonline.ag/sportsbook",
    "accept": "application/json",
    "content-type": "application/json",
    "utc-offset": "0",
    "gsetting": GSETTING,
}


def _session():
    proxies = {"https": os.environ["HTTPS_PROXY"]} if os.environ.get("HTTPS_PROXY") else None
    kwargs = {"impersonate": IMPERSONATE, "timeout": 60}
    if proxies:
        kwargs["proxies"] = proxies
        if os.path.exists("/root/.ccr/ca-bundle.crt"):
            kwargs["verify"] = "/root/.ccr/ca-bundle.crt"
    return requests.Session(**kwargs)


def _post(session, path, body):
    r = session.post(OFFERING_API + path, headers=HEADERS, data=json.dumps(body))
    r.raise_for_status()
    return r.json()


def list_fights(session):
    """Every fight currently carrying an MMA Props board, as (name, slug)."""
    menu = _post(session, "/api/offering/Sports/get-menu", 0)

    def walk(items):
        for item in items or []:
            if item.get("Name") == "MMA Props":
                return item
            found = walk(item.get("SubMenuItems"))
            if found:
                return found
        return None

    node = walk(menu.get("MenuItems")) or {}
    return [(s["Name"], s["URL"].rsplit("/", 1)[-1]) for s in node.get("SubMenuItems") or []]


def fetch_fight(session, slug):
    """All prop markets for one fight: {market: {selection: american odds}}."""
    data = _post(
        session,
        "/api/offering/Sports/get-contests-by-contest-type2",
        {"ContestType": "mma-props", "ContestType2": slug, "filterTime": 0},
    )
    offerings = data["ContestOfferings"]
    markets = {}
    for group in (offerings.get("DateGroup") or [{}])[0].get("DescriptionGroup") or []:
        for time_group in group.get("TimeGroup") or []:
            extended = time_group.get("ContestExtended") or {}
            for line in extended.get("ContestGroupLine") or []:
                for c in line.get("Contestants") or []:
                    odds = ((c.get("Line") or {}).get("MoneyLine") or {}).get("Line") or 0
                    if odds:
                        markets.setdefault(group["Description"], {})[c["Name"]] = odds
    return offerings.get("ContestType2") or slug, markets


# --- odds helpers -----------------------------------------------------------

def to_decimal(american):
    return 1 + american / 100 if american > 0 else 1 + 100 / -american


def to_american(decimal):
    profit = decimal - 1
    return f"+{round(profit * 100)}" if profit >= 1 else f"-{round(100 / profit)}"


def boosted(american, boost):
    """A profit boost multiplies winnings, not the stake."""
    return 1 + (1 + boost) * (to_decimal(american) - 1)


def devig(prices):
    """Multiplicative devig across a whole market."""
    implied = {k: 1 / to_decimal(v) for k, v in prices.items()}
    total = sum(implied.values())
    return {k: v / total for k, v in implied.items()}, total


# --- comparison -------------------------------------------------------------

MOV_PATTERNS = {
    "ko": ("KO/TKO", "TKO/KO"),
    "sub": ("Submission",),
    "dec": ("Points", "Decision"),
}
MOV_LABELS = {"ko": "KO/TKO/DQ", "sub": "Submission", "dec": "Decision"}


def _fighters(fight_name):
    return [p.strip() for p in fight_name.split(" vs ")]


def _match(dk_name, bol_name):
    """DraftKings and BetOnline spell middle names differently."""
    return dk_name.split()[-1].lower() == bol_name.split()[-1].lower()


def compare(session, dk_by_fighter, boost):
    rows = []
    for fight_name, slug in list_fights(session):
        _, markets = fetch_fight(session, slug)
        mov = markets.get("Method of Victory") or {}
        if not mov:
            continue
        bol_probs, bol_hold = devig(mov)

        for bol_fighter in _fighters(fight_name):
            dk_name = next((n for n in dk_by_fighter if _match(n, bol_fighter)), None)
            if not dk_name:
                continue
            dk_prices = dk_by_fighter[dk_name]
            # Devig DraftKings across just this fight's six method prices.
            dk_market = {
                f"{n} {k}": v[k]
                for n in dk_by_fighter
                if any(_match(n, f) for f in _fighters(fight_name))
                for k, v in [(k, dk_by_fighter[n]) for k in MOV_PATTERNS]
            }
            dk_probs, _ = devig(dk_market)

            for key, patterns in MOV_PATTERNS.items():
                if key not in dk_prices:
                    continue
                sel = next(
                    (
                        (n, v) for n, v in mov.items()
                        if _match(bol_fighter, n.split(" by ")[0])
                        and any(p in n for p in patterns)
                    ),
                    None,
                )
                if not sel:
                    continue
                bol_name, bol_odds = sel
                dk_odds = dk_prices[key]
                payout = boosted(dk_odds, boost)
                p_bol = bol_probs[bol_name]
                # BetOnline's board carries a draw; DraftKings' does not. Scale
                # the DraftKings devig into the same space before blending.
                p_dk = dk_probs[f"{dk_name} {key}"] * (1 - bol_probs.get("Draw", 0))
                p_blend = (p_bol + p_dk) / 2
                rows.append({
                    "fight": fight_name,
                    "selection": f"{dk_name} {MOV_LABELS[key]}",
                    "dk": dk_odds,
                    "dk_boosted": to_american(payout),
                    "bol": bol_odds,
                    "p_bol": p_bol,
                    "p_dk": p_dk,
                    "p_blend": p_blend,
                    "ev_bol": p_bol * payout - 1,
                    "ev_blend": p_blend * payout - 1,
                    "bol_hold": bol_hold - 1,
                })
    rows.sort(key=lambda r: -r["ev_blend"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["list", "fight", "compare"])
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--dk", help="JSON file of DraftKings method-of-victory prices")
    ap.add_argument("--boost", type=float, default=0.5, help="profit boost, e.g. 0.5 for 50%%")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    session = _session()

    if args.command == "list":
        for name, slug in list_fights(session):
            print(f"{name:45} {slug}")
        return

    if args.command == "fight":
        if not args.slug:
            sys.exit("fight requires a slug (see `list`)")
        name, markets = fetch_fight(session, args.slug)
        if args.json:
            print(json.dumps({name: markets}, indent=1))
            return
        print(f"# {name}")
        for market, sels in markets.items():
            print(f"\n### {market}")
            for sel, odds in sorted(sels.items(), key=lambda kv: to_decimal(kv[1])):
                print(f"   {sel:52} {odds:+6d}")
        return

    if not args.dk:
        sys.exit("compare requires --dk")
    rows = compare(session, json.load(open(args.dk)), args.boost)
    if args.json:
        print(json.dumps(rows, indent=1))
        return
    pct = int(args.boost * 100)
    print(f"{'Selection':38} {'DK':>6} {f'+{pct}%':>8} {'BOL':>6} {'fair':>6} {'EV':>7}")
    print("-" * 76)
    for r in rows:
        print(f"{r['selection']:38} {r['dk']:+6d} {r['dk_boosted']:>8} "
              f"{r['bol']:+6d} {r['p_blend']*100:5.1f}% {r['ev_blend']*100:+6.1f}%")


if __name__ == "__main__":
    main()
