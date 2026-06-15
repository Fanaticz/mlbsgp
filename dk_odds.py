#!/usr/bin/env python3
"""
dk_odds.py  -  automated DraftKings anytime-HR odds for the Long Ball model.

Input #4 in the spec, and the sharpest one: the de-vigged anytime-HR price is a better
P(HR) than season xHR, AND short odds are a pre-game popularity proxy (entries don't
exist until games start). We pull "{Player} Home Runs" markets from every game's
"Batter Props" category and take the "1+" milestone -- that's the anytime-HR line.

  -> {display_name: american_odds}   e.g. {"James Wood": 336, "Aaron Judge": 185}

Name normalization is critical: DK uses "First Last" (often no accents), Savant uses
"Last, First" with accents/suffixes. We return DK's display form and let names.norm_key
do the accent-/suffix-insensitive join in build_card(). Unmatched names are logged.

CLI:
  python3 dk_odds.py            # print today's anytime-HR odds, sorted
  python3 dk_odds.py --json     # emit {name: odds} JSON to stdout (for the server)
"""

import datetime as dt
import json
import os
import sys

import dk_api
from totals import _category_markets, _american, savant_abbrev

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# DK groups player HR props under this category; the per-player market is named
# "{Player} Home Runs" with a "Home Runs Milestones" market type. The anytime line is
# the milestoneValue==1 ("1+") selection.
_HR_CATEGORY = "Batter Props"


def _hr_markets(markets):
    """Player anytime-HR markets: '{Player} Home Runs', excluding the O/U variant."""
    out = []
    for m in markets:
        name = m.get("name", "")
        if name.endswith("Home Runs") and "O/U" not in name:
            out.append(m)
    return out


def _anytime_selection(selections, market_id):
    """The '1+' milestone selection for a HR market (anytime to hit a home run)."""
    cands = [s for s in selections if s.get("marketId") == market_id]
    one = next((s for s in cands if s.get("milestoneValue") == 1), None)
    if one is None:                              # fallback: lowest milestone present
        graded = [s for s in cands if s.get("milestoneValue") is not None]
        one = min(graded, key=lambda s: s["milestoneValue"]) if graded else None
    return one


def fetch_hr_odds_detailed(events=None) -> list:
    """Return [{player, team, american, odds_str, event}] for every anytime-HR market."""
    events = events or dk_api.get_games()["events"]
    rows = []
    for e in events:
        try:
            mkts, sels = _category_markets(e["id"], _HR_CATEGORY)
        except Exception as ex:
            sys.stderr.write(f"dk_odds: {e['id']} batter props failed: {ex}\n")
            continue
        for m in _hr_markets(mkts):
            sel = _anytime_selection(sels, m["id"])
            if not sel:
                continue
            odds = _american(sel)
            if odds is None:
                continue
            parts = sel.get("participants") or []
            player = parts[0].get("name") if parts else m.get("name", "").replace(" Home Runs", "")
            role = parts[0].get("venueRole", "") if parts else ""
            team = savant_abbrev(e["homeShort"]) if "Home" in role else savant_abbrev(e["awayShort"])
            rows.append({
                "player": player,
                "team": team,
                "american": odds,
                "event": f"{savant_abbrev(e['awayShort'])}@{savant_abbrev(e['homeShort'])}",
            })
    return rows


def fetch_hr_odds(events=None) -> dict:
    """Return {display_name: american_odds} -- the form build_card(odds=...) expects."""
    return {r["player"]: r["american"] for r in fetch_hr_odds_detailed(events)}


def cache_odds(odds=None) -> str:
    """Persist today's odds to data/ so the button/server can re-read without re-pulling."""
    odds = odds if odds is not None else fetch_hr_odds()
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, f"dk_hr_odds_{dt.date.today().isoformat()}.json")
    with open(path, "w") as f:
        json.dump(odds, f, indent=2)
    return path


def main():
    rows = fetch_hr_odds_detailed()
    if "--json" in sys.argv:
        print(json.dumps({r["player"]: r["american"] for r in rows}))
        return
    rows.sort(key=lambda r: r["american"])
    print(f"dk_odds: {len(rows)} anytime-HR markets")
    for r in rows:
        o = f"+{r['american']}" if r["american"] > 0 else str(r["american"])
        print(f"  {o:>6}  {r['player']:<24} {r['team']:<4} {r['event']}")
    cache_odds({r["player"]: r["american"] for r in rows})


if __name__ == "__main__":
    main()
