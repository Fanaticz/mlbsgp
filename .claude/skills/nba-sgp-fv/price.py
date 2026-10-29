#!/usr/bin/env python3
"""Fair value of an NBA same-player SGP (two or more legs).

  python3 price.py "Victor Wembanyama" \\
      "pts over 25.5 odds +114 -113" \\
      "tpm over 2.5 odds +150 -197" \\
      "reb over 9.5 from 11.5 odds +115 -114"

Each leg: <stat> <over|under> <line> [from <posted line>] odds <over> [<under>]
  stat   pts, reb, ast, tpm (3pm / threes accepted)
  odds   Over and Under prices of the posted line: Vulture's Fair column, or a
         book's two-way price (normalizing the pair strips its vig). With one
         side only, that price is taken as fair.
  from   the odds belong to another line (a Novig milestone like 25+ against
         a posted 23.5): the leg is shifted with the player's game-log spread.

Correlations are margin r's between the stat lines, shrunk toward rotation
players in a similar role. Points pairs come from the data file
(scripts/nba_fetch_correlations.py); the others are computed here the same
way. The joint is a Gaussian copula: exact for two legs, an integral for
three, Monte Carlo beyond.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nba-ast-pts-sgp"))
import sgp  # noqa: E402  prob, american, nppf, ncdf, joint, binary, stat_sd, load

STATS = {"pts": "pts", "points": "pts", "reb": "reb", "rebounds": "reb", "ast": "ast",
         "assists": "ast", "tpm": "tpm", "3pm": "tpm", "threes": "tpm"}
SIDES = {"over": 1, "o": 1, "yes": 1, "under": -1, "u": -1, "no": -1}
ORDER = ["pts", "reb", "ast", "tpm"]
DATA_PAIR = {("pts", "reb"): "pts_reb", ("pts", "ast"): "pts_ast", ("pts", "tpm"): "pts_3pm"}
# Pairs the data file doesn't carry: shrink toward rotation players binned by
# this box stat, like the data script does for its pairs.
COVARIATE = {("reb", "ast"): "ast_mean", ("reb", "tpm"): "reb_mean", ("ast", "tpm"): "tpm_mean"}
POOL = {"min_mpg": 20.0, "min_games": 40}
BINS = 5


def parse_leg(text):
    t = text.lower().replace(",", " ").split()
    leg = {"stat": STATS[t[0]], "side": SIDES[t[1]], "line": float(t[2]), "from": None}
    i = 3
    if t[i] == "from":
        leg["from"] = float(t[i + 1])
        i += 2
    if t[i] != "odds":
        raise SystemExit(f"leg {text!r}: expected 'odds' after the line")
    nums = [int(x) for x in t[i + 1:i + 3]]
    leg["over"], leg["under"] = nums[0], (nums[1] if len(nums) > 1 else None)
    return leg


def over_prob(over, under):
    po = sgp.prob(over)
    return po if under is None else po / (po + sgp.prob(under))


def season_games(p):
    by = {}
    for g in p["recent_games"]:
        if not g.get("short"):
            by.setdefault(g["s"], []).append(g)
    return by


def nb_over(p, stat, posted, target, p_posted):
    """Negative binomial through the posted line, with the player's own
    within-season dispersion; returns P(stat > target)."""
    seasons = [[g[stat] for g in v] for v in season_games(p).values() if len(v) > 1]
    var = sum(sum((x - sum(v) / len(v)) ** 2 for x in v) for v in seasons) / sum(len(v) - 1 for v in seasons)
    mean = sum(sum(v) for v in seasons) / sum(len(v) for v in seasons)
    q = 1 / max(var / mean, 1.0001)

    def sf(k, mu):  # P(X >= k)
        r = mu * q / (1 - q)
        return 1 - sum(math.exp(math.lgamma(x + r) - math.lgamma(r) - math.lgamma(x + 1)
                                + r * math.log(q) + x * math.log(1 - q)) for x in range(k))
    lo, hi = 0.05, 80.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if sf(math.ceil(posted), mid) < p_posted:
            lo = mid
        else:
            hi = mid
    return sf(math.ceil(target), mid)


def leg_prob(p, leg):
    """(probability the leg hits, note)"""
    po = over_prob(leg["over"], leg["under"])
    note = ""
    if leg["from"] is not None and leg["from"] != leg["line"]:
        sd = sgp.stat_sd(p, leg["stat"])
        mu = leg["from"] - sd * sgp.nppf(1 - po)
        normal = 1 - sgp.ncdf((leg["line"] - mu) / sd)
        if leg["stat"] == "pts":
            po, note = normal, f"shifted from {leg['from']:g} (SD {sd:.1f})"
        else:  # small counts: average the normal with a count model
            nb = nb_over(p, leg["stat"], leg["from"], leg["line"], po)
            po, note = (normal + nb) / 2, f"shifted from {leg['from']:g}: normal {normal:.1%}, count model {nb:.1%}"
    elif leg["under"] is None:
        note = "one side only"
    return (po if leg["side"] > 0 else 1 - po), note


def wcorr(p, a, b, weights):
    """Recency-weighted, within-season r of two box stats and its Kish n."""
    xs, ys, ws = [], [], []
    for s, v in season_games(p).items():
        if len(v) < 3:
            continue
        ma, mb = sum(g[a] for g in v) / len(v), sum(g[b] for g in v) / len(v)
        for g in v:
            xs.append(g[a] - ma); ys.append(g[b] - mb); ws.append(weights.get(int(s), 0.0))
    sw = sum(ws)
    sxx = sum(w * x * x for w, x in zip(ws, xs)); syy = sum(w * y * y for w, y in zip(ws, ys))
    if len(xs) < 10 or not sw or not sxx or not syy:
        return None, None
    return sum(w * x * y for w, x, y in zip(ws, xs, ys)) / math.sqrt(sxx * syy), sw * sw / sum(w * w for w in ws)


def interp(knots, x):
    if x <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return knots[-1][1]


def shrunk_r(d, by, p, a, b):
    """(r, how) for the pair, oriented as corr(a, b)."""
    key = tuple(sorted((a, b), key=ORDER.index))
    if key in DATA_PAIR:
        pair = p[DATA_PAIR[key]]
        if "shrunk" in pair:
            return pair["shrunk"]["r"], "data file"
        return pair["weighted"]["r"] or 0.0, "data file (unshrunk)"
    weights = {int(k): v for k, v in d["weighting"]["per_game_season_weights"].items()}
    cov = COVARIATE[key]
    pool = []
    for q in by.values():
        if q["min_mean"] >= POOL["min_mpg"] and q["n_games"] >= POOL["min_games"]:
            r, n = wcorr(q, a, b, weights)
            if r is not None:
                pool.append((q[cov], r, n))
    pool.sort()
    knots = []
    for i in range(BINS):
        bin_ = pool[i * len(pool) // BINS:(i + 1) * len(pool) // BINS]
        xs = sorted(x for x, _, _ in bin_)
        knots.append((xs[len(xs) // 2], sum(r for _, r, _ in bin_) / len(bin_)))
    resid = [r - interp(knots, x) for x, r, _ in pool]
    tau2 = max(sum(e * e for e in resid) / len(resid)
               - sum((1 - r * r) ** 2 / n for _, r, n in pool) / len(pool), 0.02 ** 2)
    prior = interp(knots, p[cov])
    r, n = wcorr(p, a, b, weights)
    if r is None:
        return prior, "role prior (too few games)"
    w = tau2 / (tau2 + (1 - r * r) ** 2 / n)
    return w * r + (1 - w) * prior, f"game logs, own {r:+.3f} -> prior {prior:+.3f}"


def tri_joint(ps, R):
    """P(all three legs hit), legs oriented so each hits below its quantile."""
    a, b, c = (sgp.nppf(1 - q) for q in ps)  # same as the upper orthant at 1-p
    rab, rac, rbc = R[0][1], R[0][2], R[1][2]
    sy, sz = math.sqrt(1 - rab ** 2), math.sqrt(1 - rac ** 2)
    rc = (rbc - rab * rac) / (sy * sz)
    n, hi = 400, max(a, 0) + 9
    step, tot = (hi - a) / n, 0.0
    for i in range(n + 1):
        x = a + i * step
        h, k = (b - rab * x) / sy, (c - rac * x) / sz
        # P(Y > h', Z > k') = Phi2(-h, -k; rc), via the bivariate copula
        up = sgp.joint(rc, sgp.ncdf(-h), sgp.ncdf(-k))
        tot += math.exp(-x * x / 2) / math.sqrt(2 * math.pi) * up * (1 if i in (0, n) else 4 if i % 2 else 2)
    return tot * step / 3


def mc_joint(ps, R, draws=4_000_000):
    import numpy as np
    vals, vecs = np.linalg.eigh(np.array(R))
    C = vecs @ np.diag(np.clip(vals, 1e-6, None)) @ vecs.T
    C /= np.sqrt(np.outer(np.diag(C), np.diag(C)))
    Z = np.random.default_rng(7).multivariate_normal(np.zeros(len(ps)), C, size=draws)
    return float(np.mean(np.all(Z < np.array([sgp.nppf(q) for q in ps]), axis=1)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("player")
    ap.add_argument("legs", nargs="+")
    args = ap.parse_args()
    d, by = sgp.load()
    hits = [n for n in by if args.player.lower() in n.lower()]
    exact = [n for n in hits if n.lower() == args.player.lower()]
    if len(exact) == 1:
        hits = exact
    if len(hits) != 1:
        raise SystemExit(f"player {args.player!r}: {'no match' if not hits else 'ambiguous: ' + ', '.join(hits)}")
    p = by[hits[0]]
    legs = [parse_leg(t) for t in args.legs]
    if len(legs) < 2:
        raise SystemExit("need at least two legs")
    print(f"{hits[0]} ({p['team_abbr']}) · data {d['generated_at'][:10]}")
    ps = []
    for leg in legs:
        q, note = leg_prob(p, leg)
        ps.append(q)
        side = "over" if leg["side"] > 0 else "under"
        print(f"  {leg['stat']} {side} {leg['line']:g}: {q:.1%}" + (f"  ({note})" if note else ""))
    n = len(legs)
    R = [[1.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            r, how = shrunk_r(d, by, p, legs[i]["stat"], legs[j]["stat"])
            R[i][j] = R[j][i] = legs[i]["side"] * legs[j]["side"] * r
            print(f"  r {legs[i]['stat']}-{legs[j]['stat']} {r:+.3f} ({how})")
    if n == 2:
        j = sgp.joint(R[0][1], ps[0], ps[1])
        print(f"  plug-in r at these lines {sgp.binary(R[0][1], ps[0], ps[1]):+.3f}")
    elif n == 3:
        j = tri_joint(ps, R)
    else:
        j = mc_joint(ps, R)
    print(f"  joint {j:.1%} (independent {math.prod(ps):.1%})")
    print(f"FV {sgp.american(j):+d} ({1 / j:.2f}x)")


if __name__ == "__main__":
    main()
