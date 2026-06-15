#!/usr/bin/env python3
"""
run_today.py  -  one command to produce today's Long Ball card, fully automated.

Pulls every input live (Savant distances + xHR, DK anytime-HR odds, DK game totals),
merges them through build_card(), and prints the ranked card plus the two filtered views
the strategy cares about:

  * UNDER FLOOR   -- only bats whose split would clear MIN_PAYOUT_FLOOR (<=~50 entries)
  * LAUNCHPAD     -- when one game's carry is an outlier, the cheap high-ceiling darts in it

No manual uploads. Savant CSVs are cached in data/ and refreshed daily; DK odds/totals are
pulled fresh each run.

  python3 run_today.py             # full card + views
  python3 run_today.py --refresh   # force a fresh Savant pull too
"""

import sys

import pandas as pd

import savant
import dk_odds
import totals
import longball


def gather(force_savant=False):
    """Fetch all inputs and return (card, parks, odds, totals_list, calib)."""
    savant.refresh(force=force_savant)
    calib = longball.load_calibration()
    tot = totals.fetch_totals()
    parks = totals.build_parks(tot, calib)
    odds = dk_odds.fetch_hr_odds()
    card = longball.build_card(parks=parks, odds=odds, calib=calib)
    return card, parks, odds, tot, calib


def main():
    force = "--refresh" in sys.argv
    pd.set_option("display.width", 220)
    card, parks, odds, tot, calib = gather(force_savant=force)

    n_odds = int(card.hr_odds.notna().sum())
    print("\n" + "=" * 100)
    print(f"  LONG BALL JACKPOT MODEL   |   {len(card)} bats on slate   |   "
          f"{len(tot)} games   |   {n_odds} with live HR odds   |   "
          f"games elapsed: {calib.get('games_elapsed')}")
    print("=" * 100)
    print(longball._fmt(card).head(20).to_string(index=False))
    print("-" * 100)
    print("  EV$ = expected FanCash per $5 ticket.  src: live=board, odds=odds curve, est=guess.")
    print("  Target: Ceil 445+ AND odds ~+350..+700 (LIGHT/DART). Confirm lineups before betting.\n")

    floor = longball.under_floor(card, calib)
    if not floor.empty:
        print(f"  -- UNDER FLOOR (split clears ${calib['min_payout_floor']}; the default view) --")
        print(longball._fmt(floor).head(15).to_string(index=False), "\n")

    stack = longball.launchpad_stack(card)
    if not stack.empty:
        hot = max(tot, key=lambda g: g["total"])
        print(f"  -- LAUNCHPAD STACK ({hot['label']} O/U {hot['total']}; spread the darts) --")
        print(longball._fmt(stack).to_string(index=False), "\n")


if __name__ == "__main__":
    main()
