#!/usr/bin/env python3
"""NBA Assists x Points SGP helper.

  python3 sgp.py players [--min-ast 5] [--min-pts 20] [--max-r 0]
      Today's high-assist players (from public/data/nba_correlations.json)
      whose shrunk PTS-AST margin r is negative, plus the Vulture command.

  python3 sgp.py fv legs.json
      legs.json: {"Cade Cunningham": {"ast": {"line": 9.5, "over": 128, "under": -125},
                                      "pts": {"line": 24.5, "over": 104, "under": -104}}, ...}
      Fair values are the avg_fv column from Vulture. A missing side is
      filled from the other side's complement. Prints both opposite-direction
      combos (Ast U + Pts O, Ast O + Pts U): shrunk margin r, the binary corr
      it implies at those lines, and the Gaussian-copula joint / FV.
"""
import argparse
import json
import math
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CORR = os.path.join(ROOT, "public", "data", "nba_correlations.json")


def prob(o):
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def american(p):
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def ncdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def nppf(p):
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if ncdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def joint(r, a, b):
    """P(U < a-quantile, V < b-quantile) under a Gaussian copula with margin
    corr r. Plackett: d/drho Phi2(x,y;rho) = phi2(x,y;rho); Simpson in rho."""
    x, y = nppf(a), nppf(b)
    n = 200
    h = r / n
    tot = 0.0
    for i in range(n + 1):
        rho = i * h
        q = 1 - rho * rho
        f = math.exp(-(x * x - 2 * rho * x * y + y * y) / (2 * q)) / (2 * math.pi * math.sqrt(q))
        tot += f * (1 if i in (0, n) else 4 if i % 2 else 2)
    return a * b + tot * h / 3


def binary(r, a, b):
    j = joint(r, a, b)
    return (j - a * b) / math.sqrt(a * (1 - a) * b * (1 - b))


def margin_r(by, name):
    """Recency-weighted within-season PTS-AST r, shrunk toward high-assist
    starters (>=4 AST, >=24 MPG, >=60 games). Per-player r carries ~0.10 of
    sampling noise vs ~0.08 of real spread, so raw r's overstate differences."""
    pool = [p for p in by.values()
            if p["ast_mean"] >= 4 and p["n_games"] >= 60 and p["min_mean"] >= 24]
    rs = [p["pts_ast"]["weighted"]["r"] for p in pool]
    noise = [(1 - r * r) ** 2 / p["effective_n"] for r, p in zip(rs, pool)]
    prior = sum(rs) / len(rs)
    var = sum((r - prior) ** 2 for r in rs) / len(rs)
    tau2 = max(var - sum(noise) / len(noise), 1e-4)
    p = by[name]
    r = p["pts_ast"]["weighted"]["r"]
    w = tau2 / (tau2 + (1 - r * r) ** 2 / p["effective_n"])
    return w * r + (1 - w) * prior


def load():
    d = json.load(open(CORR))
    return d, {p["name"]: p for p in d["players"]}


def players(args):
    d, by = load()
    teams = {t for g in d["schedule_today"]["games"] for t in g["team_abbrs"]}
    rows = [p for p in d["players"]
            if p["team_abbr"] in teams and p["n_games"] >= 20
            and p["ast_mean"] >= args.min_ast and p["pts_mean"] >= args.min_pts
            and margin_r(by, p["name"]) < args.max_r]
    rows.sort(key=lambda p: margin_r(by, p["name"]))
    print(f"slate {d['schedule_today']['date']}  (data {d['generated_at']})")
    for p in rows:
        w = p["pts_ast"]["weighted"]
        print(f"  {p['name']:26} {p['team_abbr']:5} ast {p['ast_mean']:4.1f} pts {p['pts_mean']:4.1f}"
              f"  raw r {w['r']:+.3f}  shrunk {margin_r(by, p['name']):+.3f} (n {p['n_games']})")
    names = ", ".join(p["name"] for p in rows)
    print("\nVulture:\ncommand_name:twa markets:player assist, player points bet_names:"
          f"{names} books:dk")


def sides(leg):
    o, u = leg.get("over"), leg.get("under")
    po = prob(o) if o is not None else 1 - prob(u)
    pu = prob(u) if u is not None else 1 - prob(o)
    return po, pu


def fv(args):
    _, by = load()
    legs = json.load(open(args.legs))
    print(f"{'player':20} {'combo':22} {'margin':>7} {'binary':>6} {'joint':>6} {'FV':>6} {'fair x':>7}")
    for name, L in legs.items():
        if name not in by or "ast" not in L or "pts" not in L:
            print(f"{name:20} missing correlation or a leg")
            continue
        # Opposite-direction combos: corr(AST, -PTS) = -margin r.
        r = -margin_r(by, name)
        ao, au = sides(L["ast"])
        po, pu = sides(L["pts"])
        for label, a, b in (
            (f"A U{L['ast']['line']} + P O{L['pts']['line']}", au, po),
            (f"A O{L['ast']['line']} + P U{L['pts']['line']}", ao, pu),
        ):
            j = joint(r, a, b)
            print(f"{name:20} {label:22} {r:+.3f} {binary(r, a, b):+.3f} {j*100:5.1f}%"
                  f" {american(j):+6d} {1/j:6.2f}x")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("players")
    s.add_argument("--min-ast", type=float, default=5)
    s.add_argument("--min-pts", type=float, default=17)
    s.add_argument("--max-r", type=float, default=0)
    s.set_defaults(fn=players)
    s = sub.add_parser("fv")
    s.add_argument("legs")
    s.set_defaults(fn=fv)
    a = ap.parse_args()
    a.fn(a)
