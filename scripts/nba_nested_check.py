#!/usr/bin/env python3
"""A player's points with his points + rebounds + assists, on one slip: how
often both hit, and the model the Kalshi NBA board prices that slip with
(scan_kalshi.nest_joint). Research and a check; nothing reads its output.

  python3 scripts/nba_nested_check.py
  python3 scripts/nba_nested_check.py 0.52 0.49 24.5 39.5 13.5   # one slip: P(points), P(PRA), the two lines, his rebounds + assists a game

Novig refuses a combined stat with one of its own parts; Kalshi combines
them (Max, 11-28: Franz Wagner 25+ points with 40+ PRA at 2.15x).

The two legs are one stat inside the other, so no single correlation fits:
it depends on how the gap between the two lines compares with what he
usually adds in rebounds and assists. On four seasons of box scores
(public/data/nba_game_boxes.json; players at 20+ minutes whose points
median over their previous 15 such games is 15+; each leg on the 5-apart
milestone nearest his median, as Kalshi's are) the games both hit sit 0.75 of the way from unrelated legs to
always together where the gap is his usual rebounds + assists, and 0.93 of
the way where it is 3.5 or more either side.

The model: points and rebounds + assists are two normal counts with the
spreads and the correlation (0.17) these games show, set so each leg hits as
often as its own price says. It gives the share of games both hit to within
0.004 in every group below, and so the two slips with one Yes and one No.
"""
import collections
import json
import os
import sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-sgp-fv"))
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-ast-pts-sgp"))
import scan_kalshi  # noqa: E402
import sgp  # noqa: E402


def mile(m):
    """Kalshi's milestone nearest a median: x4.5 or x9.5."""
    return round((m - 4.5) / 5) * 5 + 4.5


def main():
    if len(sys.argv) == 6:
        pp, pq, lp, lq, ra = map(float, sys.argv[1:])
        j = scan_kalshi.nest_joint(pp, pq, lp, lq, ra)
        print(f"both {j:.3f}, fair {1 / j:.2f}x; points Yes + PRA No {pp - j:.3f}, {1 / (pp - j):.1f}x; "
              f"points No + PRA Yes {pq - j:.3f}, {1 / (pq - j):.1f}x")
        return
    d = json.load(open(os.path.join(ROOT, "public", "data", "nba_game_boxes.json")))
    hist, rows = collections.defaultdict(list), []
    for gid in sorted(d, key=int):
        for ps in d[gid].values():
            for aid, mn, pts, reb, ast, _ in ps:
                if mn < 20:
                    continue
                v = {"pts": pts, "ra": reb + ast, "pra": pts + reb + ast}
                h = hist[aid]
                if len(h) >= 15:
                    rows.append((v, {k: float(np.median([x[k] for x in h[-15:]])) for k in v}))
                h.append(v)
    rows = [r for r in rows if r[1]["pts"] >= 15]
    dp = np.array([v["pts"] - m["pts"] for v, m in rows])
    dr = np.array([v["ra"] - m["ra"] for v, m in rows])
    mp, mr = np.array([m["pts"] for _, m in rows]), np.array([m["ra"] for _, m in rows])
    print(len(rows), "player-games")
    print("spread of points about his median, by median:", [(lo, round(float(dp[(mp >= lo) & (mp < lo + 5)].std()), 2)) for lo in (15, 20, 25, 30)])
    print("spread of rebounds + assists, by median:", [(lo, round(float(dr[(mr >= lo) & (mr < lo + 4)].std()), 2)) for lo in (4, 8, 12, 16)])
    print("correlation of the two:", round(float(np.corrcoef(dp, dr)[0, 1]), 3))

    def show(label, sel):
        """Counted against the model, for games alike in how the two lines sit: the
        legs set to the group's own rates, as the board sets them to their prices."""
        if len(sel) < 400:
            return
        x = np.array([v["pts"] > mile(m["pts"]) for v, m in sel])
        y = np.array([v["pra"] > mile(m["pra"]) for v, m in sel])
        pa, pb, j = x.mean(), y.mean(), (x & y).mean()
        mj = float(np.mean([scan_kalshi.nest_joint(pa, pb, mile(m["pts"]), mile(m["pra"]), m["ra"] + 0.5) for _, m in sel[::max(1, len(sel) // 400)]]))
        print(f"  {label:<44} n={len(sel):5d}  legs {pa:.3f} / {pb:.3f}  both {j:.3f} / {mj:.3f}   "
              f"points alone {pa - j:.3f} / {pa - mj:.3f}   PRA alone {pb - j:.3f} / {pb - mj:.3f}   of the way to always together {sgp.devig_r(j, pa, pb):.2f}")

    gap = lambda r: mile(r[1]["pra"]) - mile(r[1]["pts"]) - r[1]["ra"]   # noqa: E731
    bands = ((-9, -2.5), (-2.5, -0.5), (-0.5, 1.5), (1.5, 3.5), (3.5, 9))
    print("\ncounted / model, by (PRA line - points line) less his median rebounds + assists")
    for lo, hi in bands:
        show(f"gap {lo:+.1f} to {hi:+.1f}", [r for r in rows if lo <= gap(r) < hi])
    print("and within each, by scorer and by how much he rebounds and passes")
    for lo, hi in bands:
        for name, test in (("points under 20", lambda m: m["pts"] < 20), ("points 20+", lambda m: m["pts"] >= 20),
                           ("reb + ast under 10", lambda m: m["ra"] < 10), ("reb + ast 10+", lambda m: m["ra"] >= 10)):
            show(f"gap {lo:+.1f} to {hi:+.1f}, {name}", [r for r in rows if lo <= gap(r) < hi and test(r[1])])


if __name__ == "__main__":
    main()
