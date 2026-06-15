#!/usr/bin/env python3
"""
pick3.py  -  build the candidate pool + context for the "Today's 3" button.

Split of responsibilities (see the add-on spec):
  * THE MODEL does the math here — build_card() produces distances, P(HR), entries,
    payout, EV. We filter that to a candidate pool and emit it as DATA.
  * CLAUDE does the judgment, in server.js: it reads this JSON and returns 3 players.
    Claude is never asked to compute numbers or recall stats — only to choose among
    the candidates we hand it.

This script fetches everything live (cached ~15 min by the fetchers' own day-caches),
builds the card, and prints a JSON context blob to stdout for the /api/pick3 endpoint:

  {
    "date": "...","floor": 1000, "ceiling_gate": 445,
    "candidates": [ {player, team, game, total, top5_dist, max_dist, ceil_adj,
                     hr_odds, p_hr, tier, est_entries, payout_if_win, p_long, EV,
                     in_launchpad, lineup_confirmed}, ... ],   # top ~12 by EV
    "launchpad": [ ...same shape... ],
    "biggest_total": {"game": "PIT@ATH", "total": 10.5},
    "winning_distances": [...],
    "fallback_top3": [player, player, player]   # top-3 by EV, for the server's fallback
  }

CLI:
  python3 pick3.py            # emit the context JSON
"""

import datetime as dt
import json
import sys

import savant
import dk_odds
import totals
import longball


def _team_game_maps(tot):
    """team_abbrev -> game label, and team_abbrev -> game total."""
    game, total = {}, {}
    for g in tot:
        for t in (g["away"], g["home"]):
            game[t] = g["label"]
            total[t] = g["total"]
    return game, total


def _row_to_candidate(row, game_map, total_map, launchpad_names):
    return {
        "player": row.display,
        "team": row.team_abbrev,
        "game": game_map.get(row.team_abbrev, ""),
        "total": total_map.get(row.team_abbrev),
        "top5_dist": round(float(row.top5)),
        "max_dist": round(float(row.max_d)),
        "ceil_adj": round(float(row.ceil)),
        "hr_odds": int(row.hr_odds) if row.hr_odds == row.hr_odds and row.hr_odds is not None else None,
        "p_hr": round(float(row.phr), 3),
        "tier": row.tier or None,
        "est_entries": round(float(row.entries)),
        "payout_if_win": round(float(row.payout_if_win)),
        "p_long": round(float(row.p_long), 4),
        "EV": round(float(row.EV), 2),
        "in_launchpad": row.display in launchpad_names,
        # No lineup feed wired in yet -> unknown. Claude is told null == unconfirmed
        # and instructed to penalize accordingly. Confirm lineups before betting.
        "lineup_confirmed": None,
    }


def build_context():
    savant.refresh()                       # day-cached; cheap on repeat clicks
    calib = longball.load_calibration()
    tot = totals.fetch_totals()
    parks = totals.build_parks(tot, calib)
    odds = dk_odds.fetch_hr_odds()
    card = longball.build_card(parks=parks, odds=odds, calib=calib)

    floor = calib["min_payout_floor"]
    gate = calib["ceiling_gate"]
    game_map, total_map = _team_game_maps(tot)

    stack = longball.launchpad_stack(card)
    launchpad_names = set(stack.display) if not stack.empty else set()

    # candidate pool: ceiling-gated AND clears the payout floor
    pool = card[(card.ceil >= gate) & (card.payout_if_win >= floor)]
    if len(pool) < 6:                      # relax ceiling so Claude has options
        pool = card[(card.ceil >= gate - 5) & (card.payout_if_win >= floor)]

    candidates = [_row_to_candidate(r, game_map, total_map, launchpad_names)
                  for r in pool.head(12).itertuples()]
    launchpad = [_row_to_candidate(r, game_map, total_map, launchpad_names)
                 for r in stack.itertuples()] if not stack.empty else []

    biggest = max(tot, key=lambda g: g["total"]) if tot else None
    return {
        "date": dt.date.today().isoformat(),
        "floor": floor,
        "ceiling_gate": gate,
        "candidates": candidates,
        "launchpad": launchpad,
        "biggest_total": ({"game": biggest["label"], "total": biggest["total"]}
                          if biggest else None),
        "winning_distances": calib.get("winning_distances", []),
        "fallback_top3": [c["player"] for c in candidates[:3]],
    }


def main():
    try:
        ctx = build_context()
    except SystemExit as e:                # build_card exits when slate/odds missing
        print(json.dumps({"error": str(e)}))
        return
    except Exception as e:
        print(json.dumps({"error": f"pick3 build failed: {e}"}))
        return
    print(json.dumps(ctx))


if __name__ == "__main__":
    main()
