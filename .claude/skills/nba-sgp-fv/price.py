#!/usr/bin/env python3
"""Fair value of an NBA same-player SGP (two or more legs).

  python3 price.py "Victor Wembanyama" \\
      "pts over 25.5 odds +114 -113" \\
      "tpm over 2.5 odds +150 -197" \\
      "reb over 9.5 from 11.5 odds +115 -114" --payout 6.58

--payout is the slip's price (3.80, 3.80x or +280), or "novig" to ask Novig
for its parlay price at the legs' lines (player-stat legs only): its quote
after the 10% parlay fee, which is what the slip shows. --before-fee takes
that fee off a payout given by hand (Pikkit's Novig price is the raw quote:
+359 there is 4.25x on the slip). The payout adds EV% and a
quarter-Kelly stake at the FV as shown: units = f/4 x 100 (1u = 1% of
bankroll), dollars = units x --unit (default $250, Max's unit).

Each leg: <stat> <over|under> <line> [from <posted line>] odds <over> [<under>]
      or: <stat> <over|under> <line> [from <posted line>] odds novig
  stat   pts, reb, ast, tpm (3pm / threes accepted), or a score leg: op = the
         opponent's team total, tm = his team's total, tot = the game total
         (DK's "Team Total - IND" on a BKN player is op)
  odds   Over and Under prices of the posted line: Vulture's Fair column, or a
         book's two-way price. With both, the leg's side is its worst-case
         devig (lowest of multiplicative, additive, power, Shin), as Vulture
         does: +132/-173 prices an Over at +153 and an Under at -147. A pair
         at or under 100% (Vulture's Fair pair) is used as is. With one side
         only, that price is taken as fair.
  novig  pull the fair value from Novig's exchange (novig.py): the worst-case
         devig of the two sides' asks at the leg's line, or, when that line
         is missing or wider than --novig-spread, the nearest tight line,
         shifted.
  from   the odds belong to another line (a Novig milestone like 25+ against
         a posted 23.5): the leg is shifted with the player's game-log spread.

Correlations are margin r's between the stat lines, shrunk toward rotation
players in a similar role. Points pairs and the score-REB pairs come from the
data file (scripts/nba_fetch_correlations.py); the others are computed here
the same way, from his game logs. The joint is a Gaussian copula: exact for two legs, an integral for
three, Monte Carlo beyond.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nba-ast-pts-sgp"))
import sgp  # noqa: E402  prob, american, nppf, ncdf, joint, binary, stat_sd, load
import novig  # noqa: E402

STATS = {"pts": "pts", "points": "pts", "reb": "reb", "rebounds": "reb", "ast": "ast",
         "assists": "ast", "tpm": "tpm", "3pm": "tpm", "threes": "tpm",
         "op": "op", "opp": "op", "tm": "tm", "team": "tm", "tot": "tot", "total": "tot"}
SCORE = ("tot", "tm", "op")  # game total, his team's score, the opponent's score
SIDES = {"over": 1, "o": 1, "yes": 1, "under": -1, "u": -1, "no": -1}
ORDER = ["pts", "reb", "ast", "tpm", "tot", "tm", "op"]
DATA_PAIR = {("pts", "reb"): "pts_reb", ("pts", "ast"): "pts_ast", ("pts", "tpm"): "pts_3pm",
             ("reb", "tot"): "tot_reb", ("reb", "tm"): "tm_reb", ("reb", "op"): "op_reb"}
# Pairs the data file doesn't carry: shrink toward rotation players binned by
# this box stat, like the data script does for its pairs. REB·AST moves with
# minutes, as PTS·REB and PTS·AST do, so its role is minutes.
COVARIATE = {("reb", "ast"): "min_mean", ("reb", "tpm"): "reb_mean", ("ast", "tpm"): "tpm_mean"}
# Any other pair (points, assists or threes against a score) bins on minutes.
POOL = {"min_mpg": 20.0, "min_games": 40}
BINS = 5
# Line shifts (`from`): the count model's share of the shifted leg, the normal
# taking the rest. Walk-forward on about 30k player-games a stat (11-11): above
# the posted line the normal alone gave 44-72% of the real hit rate on points at
# +8 to +15 and 36-57% on threes at +2 to +3, the count model 96-112% (points
# +15: 128%, so points keep a fifth of the normal). Both-legs rates on the
# ladder went from 52-80% of actual to 81-101%. DK's and FanDuel's one-way
# ladders agree: their price over the count-model fair is their margin.
UP_WEIGHT = {"pts": 0.8, "reb": 1.0, "ast": 1.0, "tpm": 1.0}
DOWN_WEIGHT = {"pts": 0.0, "reb": 0.5, "ast": 0.5, "tpm": 0.5}


def parse_leg(text):
    t = text.lower().replace(",", " ").split()
    leg = {"stat": STATS[t[0]], "side": SIDES[t[1]], "line": float(t[2]), "from": None}
    i = 3
    if t[i] == "from":
        leg["from"] = float(t[i + 1])
        i += 2
    if t[i] == "novig":  # "... novig" short for "... odds novig"
        t.insert(i, "odds")
    if t[i] != "odds":
        raise SystemExit(f"leg {text!r}: expected 'odds' after the line")
    if t[i + 1:i + 2] == ["novig"]:
        leg["novig"], leg["over"], leg["under"] = True, None, None
        return leg
    nums = [int(x) for x in t[i + 1:i + 3]]
    leg["over"], leg["under"] = nums[0], (nums[1] if len(nums) > 1 else None)
    return leg


def decimal_odds(text):
    """3.80 / 3.80x -> 3.80; +280 / -120 / 280 -> decimal."""
    t = text.strip().lower().rstrip("x")
    v = float(t)
    if t.startswith(("+", "-")) or abs(v) >= 100:
        return 1 + v / 100 if v > 0 else 1 + 100 / abs(v)
    return v


def over_prob(over, under, side):
    """P(over) at the posted line, as seen from the side the leg takes. With
    both prices each side is its worst-case devig (sgp.devig_worst), so an
    Under leg reads 1 - (the Under's own fair), not the Over's complement."""
    po = sgp.prob(over)
    if under is None:
        return po
    fo, fu = sgp.devig_worst(po, sgp.prob(under))
    return fo if side > 0 else 1 - fu


def season_games(p, keep_short=False):
    """Game log by season. Short-minute games are left out of the spread used
    to shift lines (keep_short=False) but count in correlations: the props are
    action in them, and they are where the stats drop together."""
    by = {}
    for g in p["recent_games"]:
        if keep_short or not g.get("short"):
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
    po = leg["p_over"] if "p_over" in leg else over_prob(leg["over"], leg["under"], leg["side"])
    note = leg.get("note", "")
    if leg["from"] is not None and leg["from"] != leg["line"]:
        sd = sgp.stat_sd(p, leg["stat"])
        mu = leg["from"] - sd * sgp.nppf(1 - po)
        normal = 1 - sgp.ncdf((leg["line"] - mu) / sd)
        up = leg["line"] > leg["from"]
        if leg["stat"] in SCORE:
            po, note = normal, note + f"shifted from {leg['from']:g} (SD {sd:.1f})"
        else:
            # Box stats are skewed: a normal fits the lines under the posted one
            # but runs far short above it (points at +10: 54% of the real hit
            # rate, threes at +3: 36%), where the count model holds. UP_WEIGHT
            # is the count model's share above the line (11-11 study).
            nb = nb_over(p, leg["stat"], leg["from"], leg["line"], po)
            w = UP_WEIGHT[leg["stat"]] if up else DOWN_WEIGHT[leg["stat"]]
            po = w * nb + (1 - w) * normal
            note += (f"shifted from {leg['from']:g} (SD {sd:.1f})" if w == 0 else
                     f"shifted from {leg['from']:g}: normal {normal:.1%}, count model {nb:.1%}")
        # Novig's own ladder bounds the shifted leg: a seller of the Over at
        # this line or a lower one is a ceiling, a buyer at this line or a
        # higher one a floor (a one-way line still gives one of the two).
        lo, hi = leg.get("bounds", (None, None))
        if hi is not None and po > hi:
            po, note = hi, note + f", capped at Novig's {hi:.1%} ask"
        if lo is not None and po < lo:
            po, note = lo, note + f", raised to Novig's {lo:.1%} bid"
        # FanDuel's one-way price on this exact line, margin out, is a
        # ceiling too (books.py).
        cap, _, text = leg.get("book", (None, None, ""))
        if cap is not None and po > cap:
            po, note = cap, note + f", capped by {text} ({cap:.1%} with the least margin out)"
        elif text:
            note += f"; {text}"
    elif leg["under"] is None and "p_over" not in leg:
        note = "one side only"
    return (po if leg["side"] > 0 else 1 - po), note


def wcorr(p, a, b, weights):
    """Recency-weighted, within-season r of two box stats and its Kish n, over
    every game played."""
    xs, ys, ws = [], [], []
    for s, v in season_games(p, keep_short=True).items():
        v = [g for g in v if g.get(a) is not None and g.get(b) is not None]  # scores can be missing
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


_PRIORS = {}  # pair -> (knots, tau2): the pool is every rotation player, so build it once


def role_prior(d, by, key, weights):
    """(knots, tau2) for a pair the data file doesn't carry: rotation players'
    r binned by the pair's covariate, and the real spread between players."""
    if key not in _PRIORS:
        a, b = key
        cov = COVARIATE.get(key, "min_mean")
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
        # Sampling noise evaluated at the prior, as the data script does: at a
        # player's own r, a small sample that ran high would get the most weight.
        resid = [r - interp(knots, x) for x, r, _ in pool]
        tau2 = max(sum(e * e for e in resid) / len(resid)
                   - sum((1 - interp(knots, x) ** 2) ** 2 / n for x, _, n in pool) / len(pool), 0.02 ** 2)
        _PRIORS[key] = (knots, tau2)
    return _PRIORS[key]


def shrunk_r(d, by, p, a, b):
    """(r, how) for the pair, oriented as corr(a, b)."""
    key = tuple(sorted((a, b), key=ORDER.index))
    if key in DATA_PAIR:
        pair = p[DATA_PAIR[key]]
        if "shrunk" in pair:
            return pair["shrunk"]["r"], "data file"
        return pair["weighted"]["r"] or 0.0, "data file (unshrunk)"
    weights = {int(k): v for k, v in d["weighting"]["per_game_season_weights"].items()}
    knots, tau2 = role_prior(d, by, key, weights)
    prior = interp(knots, p[COVARIATE.get(key, "min_mean")])
    r, n = wcorr(p, a, b, weights)
    if r is None:
        return prior, "role prior (too few games)"
    w = tau2 / (tau2 + (1 - prior * prior) ** 2 / n)
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


def novig_payout(rows, legs):
    """Novig's parlay quote for the slip as decimal odds text, before its
    parlay fee. Every leg must be a player stat posted on Novig at its own line."""
    ids = []
    for leg in legs:
        row = next((r for r in rows.get(leg["stat"], []) if r["line"] == leg["line"]), None)
        side = "over" if leg["side"] > 0 else "under"
        if row is None or side not in row["ids"]:
            raise SystemExit(f"--payout novig: {leg['stat']} {leg['line']:g} isn't posted on Novig; pass the payout by hand")
        ids.append(row["ids"][side])
    price, why = novig.parlay(ids)
    if price is None:
        raise SystemExit(f"--payout novig: {why}; pass the payout by hand")
    return f"{1 / price:.4f}"


def novig_legs(name, rows, legs, max_spread):
    """Fill each 'odds novig' leg from Novig: p_over (worst-case devig of the
    two sides' asks, from the leg's side), from, and a note."""
    for leg in legs:
        if not leg.get("novig"):
            continue
        want = leg["from"] if leg["from"] is not None else leg["line"]
        r = novig.pick(rows.get(leg["stat"], []), want, max_spread)
        if r is None:
            raise SystemExit(f"{leg['stat']} {want:g}: no Novig line tighter than {max_spread * 100:g}c; "
                             f"see novig.py \"{name}\" {leg['stat']} and pass odds by hand")
        leg["p_over"] = r["fo"] if leg["side"] > 0 else 1 - r["fu"]
        leg["note"] = (f"Novig {r['line']:g} fair O {r['fo']:.1%} / U {r['fu']:.1%} (mid {r['mid']:.1%}), "
                       f"{r['spread'] * 100:.1f}c wide; ")
        if r["line"] != leg["line"]:
            leg["from"] = r["line"]
            book = rows.get(leg["stat"], [])
            asks = [x["ask"] for x in book if x["line"] <= leg["line"] and x["ask"] is not None]
            bids = [x["bid"] for x in book if x["line"] >= leg["line"] and x["bid"] is not None]
            leg["bounds"] = (max(bids) if bids else None, min(asks) if asks else None)
        else:
            leg["from"] = None
            leg["note"] = leg["note"][:-2]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("player")
    ap.add_argument("legs", nargs="+")
    ap.add_argument("--payout", help="slip price: decimal (3.80, 3.80x) or American (+280), or 'novig' for Novig's parlay quote")
    ap.add_argument("--before-fee", action="store_true",
                    help="--payout is Novig's raw quote (Pikkit's Novig price): take its 10%% parlay fee off")
    ap.add_argument("--unit", type=float, default=250.0, help="dollars per unit, 1u = 1%% of bankroll")
    ap.add_argument("--kelly", type=float, default=0.25, help="Kelly fraction (default quarter)")
    ap.add_argument("--no-books", action="store_true",
                    help="don't cap a shifted leg at FanDuel's one-way price on its line")
    ap.add_argument("--novig-spread", type=float, default=novig.MAX_SPREAD,
                    help="widest Novig market (ask - bid, probability) to price a novig leg from")
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
    ask_novig = (args.payout or "").lower() == "novig"
    if ask_novig or any(leg.get("novig") for leg in legs):
        name, rows = novig.ladder(novig.fetch(), hits[0])
        if not name:
            raise SystemExit(f"{hits[0]}: not on Novig's open pregame NBA props")
        if ask_novig:
            args.payout, args.before_fee = novig_payout(rows, legs), True
        novig_legs(name, rows, legs, args.novig_spread)
    shifted = [leg for leg in legs if leg["from"] is not None and leg["from"] != leg["line"]
               and leg["stat"] not in SCORE]
    if shifted and not args.no_books:
        import books
        ladders = books.load(p.get("team_name"))
        for leg in shifted:
            leg["book"] = books.check(ladders, hits[0], leg["stat"], leg["line"])
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
        print(f"  devig r (devig tool's Correlation box) {sgp.devig_r(j, ps[0], ps[1]):+.3f}")
    elif n == 3:
        j = tri_joint(ps, R)
    else:
        j = mc_joint(ps, R)
    print(f"  joint {j:.1%} (independent {math.prod(ps):.1%})")
    # Any number of legs: the devig tool's Correlation box takes "<joint>=<legs>"
    # and derives its own r from it, so it reproduces this joint exactly.
    legs_am = ",".join(f"{sgp.american(q):+d}" for q in ps)
    print(f"  devig tool: Leg Odds {legs_am} · Correlation {sgp.american(j):+d}={legs_am}")
    fv = sgp.american(j)
    print(f"\nFV = {fv:+d}")
    if args.payout:
        # EV and stake use the FV as shown, so the block checks by hand.
        p, dec = sgp.prob(fv), decimal_odds(args.payout)
        if args.before_fee:
            raw, dec = dec, novig.slip_multiplier(round(1 / dec, 3))  # Novig quotes to 0.001
            print(f"Novig pays {dec:.2f}x ({sgp.american(1 / dec):+d}): its {raw:.2f}x quote after the 10% parlay fee")
        b = dec - 1
        units = max(0.0, (p * b - (1 - p)) / b) * args.kelly * 100
        print(f"EV% = {(p * dec - 1) * 100:.1f}%")
        print(f"Kelly Wager = ${units * args.unit:,.2f}")
        print(f"QK={units:.2f}u")


if __name__ == "__main__":
    main()
