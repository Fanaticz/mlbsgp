#!/usr/bin/env python3
"""Generate a synthetic NBA correlations xlsx for unit/smoke tests.

NBA v1 scope: same-player only, 4 props (Points, Rebounds, Assists,
3-Pointers Made). Produces the 18-column schema with 50-100 plausible rows
across 5-10 fake players so the parser, upload endpoint, and downstream
enumerator can be exercised without the user's real production file.

To exercise reject paths, --include-teammate emits a handful of
cross-player rows. They should be rejected by the parser, not persisted.

Usage:
  python3 scripts/nba_generate_test_xlsx.py --out /tmp/synthetic.xlsx [--seed 42]
"""

from __future__ import annotations

import argparse
import itertools
import random

HEADER = [
    "Player_1", "Prop_1", "Side_1",
    "Player_2", "Prop_2", "Side_2",
    "Line_1", "Line_2",
    "Correlation", "Adjusted_Correlation",
    "P_Value", "Total_Games",
    "Hit_Rate_1", "Hit_Rate_2",
    "Independent_Prob", "Adjusted_Prob", "Empirical_Prob",
    "Type",
]

PLAYERS = [
    "Jalen Test", "Marcus Demo", "Tyrese Sample",
    "Kawhi Fixture", "Devin Stub", "Anthony Mock",
    "Luka Synthetic", "Joel Placeholder",
]

# Only the 4 supported props per NBA v1 spec. PRA / Steals / Blocks etc. are
# intentionally absent — they have no correlation data and would skew tests.
PROPS = {
    "Points":        [14.5, 17.5, 21.5, 24.5, 28.5, 32.5],
    "Assists":       [3.5, 5.5, 7.5, 9.5],
    "Rebounds":      [5.5, 7.5, 9.5, 11.5],
    "3-Pointers Made": [1.5, 2.5, 3.5, 4.5],
}

SAME_PLAYER_TYPE = "Same Player"
TEAMMATE_TYPE = "Teammate"


def _row_for(p1: str, p2: str, rng: random.Random, ttype: str) -> list:
    prop1, prop2 = rng.sample(list(PROPS.keys()), 2) if rng.random() < 0.75 \
        else (rng.choice(list(PROPS.keys())), rng.choice(list(PROPS.keys())))
    line1 = rng.choice(PROPS[prop1])
    line2 = rng.choice(PROPS[prop2])
    side1 = rng.choice(["Over", "Under"])
    side2 = rng.choice(["Over", "Under"])

    hit1 = round(rng.uniform(0.35, 0.70), 4)
    hit2 = round(rng.uniform(0.35, 0.70), 4)
    indep = round(hit1 * hit2, 4)
    corr = max(-0.4, min(0.6, round(rng.gauss(0.10, 0.18), 4)))
    adj_corr = round(corr * rng.uniform(0.85, 1.05), 4)
    # Lift empirical joint above/below independent by correlation sign.
    lift = 1 + corr * rng.uniform(0.4, 0.8)
    empirical = round(max(0.02, min(0.95, indep * lift)), 4)
    adjusted_prob = round(max(0.02, min(0.95, indep * (1 + adj_corr * 0.6))), 4)
    p_value = round(rng.uniform(0.001, 0.4), 4)
    games = rng.randint(22, 72)

    return [
        p1, prop1, side1,
        p2, prop2, side2,
        line1, line2,
        corr, adj_corr,
        p_value, games,
        hit1, hit2,
        indep, adjusted_prob, empirical,
        ttype,
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--rows", type=int, default=75)
    ap.add_argument("--players", type=int, default=7)
    ap.add_argument("--include-teammate", action="store_true",
                    help="Emit a few cross-player rows to exercise the reject path.")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    player_pool = PLAYERS[:max(5, min(args.players, len(PLAYERS)))]

    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "correlations"
    ws.append(HEADER)

    emitted = 0
    # Same-player rows: each player gets a roughly equal share.
    while emitted < args.rows:
        p = player_pool[emitted % len(player_pool)]
        ws.append(_row_for(p, p, rng, SAME_PLAYER_TYPE))
        emitted += 1

    teammate_emitted = 0
    if args.include_teammate:
        for a, b in itertools.islice(itertools.combinations(player_pool, 2), 5):
            ws.append(_row_for(a, b, rng, TEAMMATE_TYPE))
            teammate_emitted += 1

    wb.save(args.out)
    print(f"wrote {emitted} same-player rows + {teammate_emitted} teammate rows to {args.out}")


if __name__ == "__main__":
    main()
