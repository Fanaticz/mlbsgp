#!/usr/bin/env python3
"""A stat with a combined stat it is part of (points with points + rebounds
+ assists), or two combined stats that share a part, on one slip: the check
on the r the Kalshi NBA board prices them with (scan_kalshi.nest_r).
Research and a check; nothing reads its output.

  python3 scripts/nba_nested_check.py
  python3 scripts/nba_nested_check.py pts pra 0.52 0.49 23.5 6.5 6.5   # one slip: the two stats, each leg's chance, his points, rebounds and assists a game

Novig refuses these slips; Kalshi combines them (Max, 11-28: Franz Wagner
25+ points with 40+ PRA at 2.15x; then every player and every pairing).

The model: points, rebounds and assists are three counts, each with a spread
that goes with the player's average and with the correlations four seasons
of games show (public/data/nba_game_boxes.json, 47,223 player-games at 20+
minutes, each stat about his average of his previous 15 such games: points
with rebounds 0.19, points with assists 0.09, rebounds with assists 0.14).
Any two sums of them then move together at an r that follows from those
(a 24-point scorer's points with his PRA: about 0.90), and the slip's chance
is the copula joint at that r with each leg at its own price.

The check, for each of the 15 pairings: games are grouped by where the two
lines sit against his averages and by the r, so that a group's two hit rates
stand for every game in it; in each group the model's share of games both
legs hit, at the group's own rates, is set against the count. Over all
groups the model is within 0.004 of the count for every pairing, for both
legs and for each leg alone; a single group of 150+ games misses by 0.003 to
0.010 on average, which is what that many games gives by chance.
"""
import collections
import json
import os
import sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-sgp-fv"))
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-ast-pts-sgp"))
import scan_kalshi as K  # noqa: E402
import sgp  # noqa: E402


def line(stat, m):
    """A milestone like Kalshi's nearest his average: 5 apart, or 2 apart for rebounds and assists."""
    return max(1.5, round((m - 1.5) / 2) * 2 + 1.5) if stat in ("reb", "ast") else round((m - 4.5) / 5) * 5 + 4.5


def main():
    if len(sys.argv) == 8:
        a, b = sys.argv[1:3]
        pa, pb, pts, reb, ast = map(float, sys.argv[3:])
        r = K.nest_r(a, b, {"pts": pts, "reb": reb, "ast": ast})
        j = sgp.joint(r, pa, pb)
        print(f"r {r:+.2f}: both {j:.3f}, fair {1 / j:.2f}x; {a} Yes + {b} No {pa - j:.3f}, {1 / (pa - j):.1f}x; "
              f"{a} No + {b} Yes {pb - j:.3f}, {1 / (pb - j):.1f}x")
        return
    d = json.load(open(os.path.join(ROOT, "public", "data", "nba_game_boxes.json")))
    hist, rows = collections.defaultdict(list), []
    for gid in sorted(d, key=int):
        for ps in d[gid].values():
            for aid, mn, pts, reb, ast, _ in ps:
                if mn < 20:
                    continue
                v, h = {"pts": pts, "reb": reb, "ast": ast}, hist[aid]
                if len(h) >= 15:
                    rows.append((v, {k: float(np.mean([x[k] for x in h[-15:]])) for k in v}))
                h.append(v)
    print(len(rows), "player-games")
    dev = {k: np.array([v[k] - m[k] for v, m in rows]) for k in ("pts", "reb", "ast")}
    avg = {k: np.array([m[k] for _, m in rows]) for k in ("pts", "reb", "ast")}
    for k, edges in (("pts", (0, 5, 8, 11, 14, 17, 20, 24, 28, 40)), ("reb", (0, 2, 3, 4, 5, 6, 8, 10, 13, 20)), ("ast", (0, 1, 2, 3, 4, 5, 6, 8, 10, 15))):
        print(f"spread of {k} by his average:", [(round(float(avg[k][(avg[k] >= lo) & (avg[k] < hi)].mean()), 1),
                                                 round(float(dev[k][(avg[k] >= lo) & (avg[k] < hi)].std()), 2)) for lo, hi in zip(edges, edges[1:])])
    for a, b in (("pts", "reb"), ("pts", "ast"), ("reb", "ast")):
        print(f"{a} with {b}: {np.corrcoef(dev[a], dev[b])[0, 1]:+.3f}")
    val = lambda v, s: sum(v[x] for x in K.NEST_PARTS[s])   # noqa: E731
    print("\npairing: games | both, counted / model | first leg alone | second leg alone | a group's mean miss, the worst group")
    for a, b in K.NEST_PAIRS:
        cells = collections.defaultdict(list)
        for v, m in rows:
            ma, mb = val(m, a), val(m, b)
            if (a in ("reb", "ast") and m[a] < 2.5) or ma < 4 or mb < 8:
                continue
            r = K.nest_r(a, b, m)
            la, lb = line(a, ma), line(b, mb)
            if lb <= la and set(K.NEST_PARTS[a]) < set(K.NEST_PARTS[b]):
                continue
            sa = sum(K.price.interp(K.NEST_SD[x], m[x]) ** 2 for x in K.NEST_PARTS[a]) ** 0.5
            sb = sum(K.price.interp(K.NEST_SD[x], m[x]) ** 2 for x in K.NEST_PARTS[b]) ** 0.5
            cells[(round((la - ma) / sa * 2.5), round((lb - mb) / sb * 2.5), round(r * 12))].append((val(v, a) > la, val(v, b) > lb, r))
        n = j = mj = a1 = b1 = 0
        miss = []
        for c in cells.values():
            if len(c) < 150:
                continue
            x, y = np.array([t[0] for t in c]), np.array([t[1] for t in c])
            pa, pb, both = x.mean(), y.mean(), (x & y).mean()
            if not (0.05 < pa < 0.95 and 0.05 < pb < 0.95):
                continue
            model = sgp.joint(float(np.mean([t[2] for t in c])), pa, pb)
            n, j, mj, a1, b1 = n + len(c), j + len(c) * both, mj + len(c) * model, a1 + len(c) * pa, b1 + len(c) * pb
            miss.append((abs(model - both), len(c)))
        print(f"{a:>4} + {b:<4}{n:7d} | {j / n:.3f} / {mj / n:.3f} | {(a1 - j) / n:.3f} / {(a1 - mj) / n:.3f} | {(b1 - j) / n:.3f} / {(b1 - mj) / n:.3f} | "
              f"{sum(e * k for e, k in miss) / n:.4f}  {max(e for e, _ in miss):.3f}  ({len(miss)} groups)")


if __name__ == "__main__":
    main()
