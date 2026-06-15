#!/usr/bin/env python3
"""
totals.py  -  automated DraftKings game O/U totals -> per-team carry (PARKS).

The model treats environment as book-driven: a game's over/under is the market's read
on how many runs (and therefore how much carry / how launch-friendly the park+weather is)
tonight. `longball.env_from_total` turns the O/U into feet of carry; this module pulls the
totals for every game on the slate and builds the `PARKS` dict build_card() expects.

DK's game total lives in the "Game Lines" category as the "Total" market (Over/Under N).

CLI:
  python3 totals.py            # print today's totals + derived carry per team
"""

import datetime as dt
import json
import os
import sys

import dk_api
from longball import env_from_total, load_calibration

# DK short codes -> Baseball Savant team_abbrev (only the ones that differ). Savant uses
# ATH (A's), AZ (Arizona), WSH (Washington), CWS (White Sox); DK uses A's/OAK, ARI, WAS, CHW.
DK_TO_SAVANT = {
    "A'S": "ATH", "ATH": "ATH", "OAK": "ATH",
    "ARI": "AZ",  "AZ": "AZ",
    "WAS": "WSH", "WSH": "WSH",
    "CHW": "CWS", "CWS": "CWS",
    "SDP": "SD",  "SFG": "SF",  "TBR": "TB",  "KCR": "KC",  "NYM": "NYM",
}

DK_CATEGORIES = ("https://sportsbook-nash.draftkings.com/sites/US-SB/api/sportscontent"
                 "/dkusnj/v1/events/{eid}/categories")


def savant_abbrev(dk_short: str) -> str:
    """Normalize a DK team short code to the Savant team_abbrev used everywhere else."""
    k = (dk_short or "").strip().upper()
    return DK_TO_SAVANT.get(k, k)


def _category_markets(event_id, category_name):
    """Fetch one event category's markets+selections, reusing dk_api's Akamai-robust GET."""
    base = DK_CATEGORIES.format(eid=event_id)
    d = dk_api._get_with_retry(base).json()
    ev = d["events"][0]
    cat = next((c for c in ev.get("categories", []) if c.get("name") == category_name), None)
    if not cat:
        return [], []
    d2 = dk_api._get_with_retry(f"{base}/{cat['id']}").json()
    return d2.get("markets", []), d2.get("selections", [])


def _american(sel):
    """Parse DK's displayOdds.american -> int. DK renders negatives with a unicode minus."""
    s = (sel.get("displayOdds", {}) or {}).get("american", "")
    s = s.replace("−", "-").replace("+", "").strip()
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def fetch_totals(events=None) -> list:
    """Return [{event_id, label, away, home, total}] for each game with a posted total.
    `away`/`home` are Savant abbrevs. `total` is the O/U number (e.g. 9.0)."""
    events = events or dk_api.get_games()["events"]
    out = []
    for e in events:
        try:
            mkts, sels = _category_markets(e["id"], "Game Lines")
        except Exception as ex:
            sys.stderr.write(f"totals: {e['id']} game lines failed: {ex}\n")
            continue
        tot_mkt = next((m for m in mkts if m.get("name", "").strip() == "Total"), None)
        if not tot_mkt:
            continue
        tsels = [s for s in sels if s.get("marketId") == tot_mkt["id"]]
        points = next((s.get("points") for s in tsels if s.get("points") is not None), None)
        if points is None:
            continue
        away, home = savant_abbrev(e.get("awayShort")), savant_abbrev(e.get("homeShort"))
        out.append({
            "event_id": e["id"],
            "label": f"{away}@{home}",
            "away": away, "home": home,
            "total": float(points),
        })
    return out


def build_parks(totals=None, calib=None) -> dict:
    """Turn fetched totals into {team_abbrev: carry_ft}. Both teams in a game share the
    game total, so both get the same carry. This dict IS the slate for build_card()."""
    calib = calib or load_calibration()
    env = calib.get("env", {})
    totals = totals if totals is not None else fetch_totals()
    parks = {}
    for g in totals:
        carry = env_from_total(g["total"], mult=env.get("mult", 1.8),
                               cap=env.get("cap", 9.0), base=env.get("base", 8.5))
        parks[g["away"]] = carry
        parks[g["home"]] = carry
    return parks


def main():
    totals = fetch_totals()
    parks = build_parks(totals)
    print(f"totals: {len(totals)} games")
    for g in sorted(totals, key=lambda x: -x["total"]):
        print(f"  {g['label']:<10} O/U {g['total']:>4}  ->  carry {parks[g['away']]:+.1f} ft")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "dk_totals_today.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump({"date": dt.date.today().isoformat(), "totals": totals, "parks": parks}, f, indent=2)


if __name__ == "__main__":
    main()
