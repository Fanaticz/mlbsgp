#!/usr/bin/env python3
"""Novig tennis: same-match parlays of the game spread with the total games
(and the moneyline with the total), against a fair value from a tennis model.

  python3 tennis.py                 # every open best-of-three singles match
  python3 tennis.py Alcaraz         # matches with this name in them
  python3 tennis.py --min-ev 3      # print rows at this EV% or better (default 0)
  python3 tennis.py --json          # rows as JSON lines

Why these slips: the legs nearly imply each other. Over 21.5 games with the
underdog +4.5 only loses on the Over when the favourite wins a lopsided
three-setter; a straight-sets match of 22 or more games is never won by five.
Most of Novig's pricers know this (median -21% on 200 slips, 11-20). One
sometimes doesn't, and prices the pair as if loosely related: Alcaraz v
Cobolli 11-20, Cobolli +4.5 + Over 21.5 at 3.02x against a fair +159.

Model (best of three, tiebreak sets): every point on a player's serve is won
with his own fixed chance, which gives the exact chance of every score. The
gap between the two players' serve levels varies match to match (normal, sd
sigma: "day form"), which is what makes sets go the same way more often than
fixed chances allow; without it the model has far too many three-setters.
Three numbers (serve level, mean gap, sigma) are fitted to three Novig prices:
the moneyline, the main total and the main game spread. Fitted that way it
gave Novig's other lines and its set markets within a point or two (11-20).
Fair value is the lowest joint over the sigmas that fit about as well as the
best, so it is the careful end; "to" shows the other end.

Checked against results (scripts/tennis_model_check.py, 36,435 best-of-three
ATP tour matches from 2005 on, grouped by the favourite's chance and fitted
the same way): the game spread + total slips' joint is within 3% of the
counted share on average in every group (-5% to +3%), and the underdog's
moneyline + Over runs 5% to 8% too high where the favourite is 70% or more.
Where the model ran high the fair value is cut by that much (TRIM below, read
from public/data/tennis_model_check.json); where it ran low it is left alone.
Those groups mix many players and take the favourite from an Elo rating, not
a market price, and they are tour matches: Challengers and the WTA are not
in the data. Treat a row as a lead.

Asking: one ask a slip (see SKILL.md: a second ask inside a minute can come
back lower). The main lines' four slips first; a match's other lines only
where one of those came back at --grid-ev or better.
"""
import argparse
import collections
import functools
import json
import math
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
import concurrent.futures

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "nba-sgp-fv"))
import novig  # noqa: E402  catalog, parlay, slip_multiplier, american

MAX_SPREAD = 0.04       # widest Novig book a leg's fair value is read from
STEP = 0.004            # grid of serve levels and gaps the match tables are built on
SIGMAS = (0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08)
FIT_SLACK = 0.008       # a sigma counts as fitting if its miss is within this of the best one's


def hold(p):
    """Chance the server wins a game, winning each point with chance p."""
    q = 1 - p
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * (p * p / (1 - 2 * p * q))


def tiebreak(pa, pb):
    """Chance A wins a first-to-seven tiebreak, A serving first."""
    @functools.lru_cache(None)
    def f(a, b):
        if a >= 7 and a - b >= 2:
            return 1.0
        if b >= 7 and b - a >= 2:
            return 0.0
        if a == 6 and b == 6:
            w, lose = pa * (1 - pb), (1 - pa) * pb
            return w / (w + lose)
        n = a + b
        p = pa if (n == 0 or ((n - 1) // 2) % 2 == 1) else 1 - pb
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)
    return f(0, 0)


def set_scores(pa, pb, a_first):
    """{(games A, games B): chance} for one tiebreak set."""
    ha, hb, tb = hold(pa), hold(pb), tiebreak(pa, pb)
    out, live = collections.defaultdict(float), {(0, 0): 1.0}
    for n in range(12):
        w = ha if (a_first if n % 2 == 0 else not a_first) else 1 - hb
        nxt = collections.defaultdict(float)
        for (a, b), pr in live.items():
            for s2, q in (((a + 1, b), w), ((a, b + 1), 1 - w)):
                x, y = s2
                if (x >= 6 or y >= 6) and abs(x - y) >= 2 or x == 7 or y == 7:
                    out[s2] += pr * q
                else:
                    nxt[s2] += pr * q
        live = nxt
    pr = live.get((6, 6), 0.0)
    out[(7, 6)] += pr * tb
    out[(6, 7)] += pr * (1 - tb)
    return out


@functools.lru_cache(20000)
def match(pa, pb):
    """{(A wins, sets played, games A, games B): chance}, best of three,
    averaged over who serves first."""
    out = collections.defaultdict(float)
    S = {f: list(set_scores(pa, pb, f).items()) for f in (True, False)}

    def go(sa, sb, ga, gb, pr, a_first):
        if sa == 2 or sb == 2:
            out[(sa == 2, sa + sb, ga, gb)] += pr
            return
        for (a, b), q in S[a_first]:
            go(sa + (a > b), sb + (b > a), ga + a, gb + b, pr * q, a_first if (a + b) % 2 == 0 else not a_first)
    for first in (True, False):
        go(0, 0, 0, 0, 0.5, first)
    return dict(out)


def P(d, f):
    return sum(q for k, q in d.items() if f(*k))


def mix(s, m, sigma):
    """The match table at serve level s, mean gap m, day-form sd sigma."""
    si, clip = round(s / STEP), lambda x: round(min(0.97, max(0.03, x)), 6)
    lo, hi = math.floor((m - 3.2 * sigma) / STEP), math.ceil((m + 3.2 * sigma) / STEP)
    w = [(i, math.exp(-0.5 * ((i * STEP - m) / sigma) ** 2)) for i in range(lo, hi + 1)]
    z = sum(x for _, x in w)
    out = collections.defaultdict(float)
    for di, x in w:
        for k, q in match(clip(si * STEP + di * STEP), clip(si * STEP - di * STEP)).items():
            out[k] += x / z * q
    return out


def fit(p_win, tot_line, p_over, sp_line, p_cover):
    """A is the favourite; p_cover = P(games A - games B > sp_line).
    [(miss, sigma, serve level, table)] for every sigma, best fit first: the
    moneyline is matched exactly, the total to the nearest grid step, and
    the miss is what is left on the total and the spread."""
    out = []
    for sg in SIGMAS:
        def at(s):
            lo, hi = 0.0, 0.30
            for _ in range(16):
                m = (lo + hi) / 2
                lo, hi = (m, hi) if P(mix(s, m, sg), lambda w, n, a, b: w) < p_win else (lo, m)
            return mix(s, (lo + hi) / 2, sg)
        lo, hi = round(0.50 / STEP), round(0.80 / STEP)   # more serve, more games
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if P(at(mid * STEP), lambda w, n, a, b: a + b > tot_line) < p_over else (lo, mid)
        best = None
        for si in (lo, hi):
            d = at(si * STEP)
            miss = abs(P(d, lambda w, n, a, b: a + b > tot_line) - p_over) + abs(P(d, lambda w, n, a, b: a - b > sp_line) - p_cover)
            if best is None or miss < best[0]:
                best = (miss, sg, si * STEP, d)
        out.append(best)
    return sorted(out, key=lambda x: x[0])


CHECK = os.path.join(HERE, "..", "..", "..", "public", "data", "tennis_model_check.json")
try:
    TRIM = json.load(open(CHECK))["all"]
except (OSError, ValueError, KeyError):
    TRIM = []


def trim(shape, p_fav):
    """How far the model's joint ran above the counted share for this kind of
    slip at this strength of favourite (mean over the lines checked), never
    under 0: the fair value is divided by 1 + this."""
    for b in TRIM:
        if b["fav"][0] <= p_fav < b["fav"][1] + (0.01 if b["fav"][1] >= 1 else 0):
            return max(0.0, (b["slips"].get(shape) or {}).get("mean_off") or 0.0)
    return 0.0


def events():
    out, after = {}, None
    for _ in range(20):
        q = {"limit": 5000, "status": "OPEN_PREGAME"}
        if after:
            q["after"] = after
        req = urllib.request.Request(f"{novig.HOST}/v3/public/catalog/events?" + urllib.parse.urlencode(q),
                                     headers={"Accept": "application/json", "User-Agent": "nba-sgp-fv"})
        page = json.load(urllib.request.urlopen(req, timeout=30))
        for e in page["items"]:
            if e.get("sport") == "TENNIS":
                out[e["eventId"]] = e
        after = page.get("next")
        if not after:
            break
    return out


def book(m):
    """A two-way market as {name: (outcome id, fair chance)} plus its width, or None."""
    a, b = m["outcomes"]
    if not (a.get("bid") and b.get("bid")):
        return None
    pa, pb = float(a["bid"]["price"]), float(b["bid"]["price"])
    w = 1 - pa - pb
    if not 0 <= w <= MAX_SPREAD + 1e-9:
        return None
    return {"width": w, a["name"]: (a["outcomeId"], pa + w / 2), b["name"]: (b["outcomeId"], pb + w / 2)}


def matches(want):
    """Every open singles match with a tight moneyline, total and game spread:
    its names, lines and fitted tables."""
    ev = events()
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for m in novig.catalog({"eventStatus": "OPEN_PREGAME", "marketType": "MONEY,SPREAD,TOTAL"}):
        if m["eventId"] in ev and len(m["outcomes"]) == 2:
            b = book(m)
            if b:
                by[m["eventId"]][m["marketType"]].append(b)
    out, skipped = [], []
    for eid, T in by.items():
        e = ev[eid]
        if "/" in e["description"].split(" @ ")[0] or e["startsTs"] / 1000 < time.time() + 300:
            continue   # doubles, or about to start
        if want and want.lower() not in e["description"].lower():
            continue
        if not (T["MONEY"] and T["TOTAL"] and T["SPREAD"]):
            skipped.append(e["description"])
            continue
        ml = {k: v for k, v in T["MONEY"][0].items() if k != "width"}
        fav = max(ml, key=lambda k: ml[k][1])
        dog = next(k for k in ml if k != fav)
        totals = {float(k.split()[1]): {"over" if k.startswith("Over") else "under": v for k, v in b.items() if k != "width"}
                  for b in T["TOTAL"] for k in b if k.startswith("Over")}
        for b in T["TOTAL"]:
            for k, v in b.items():
                if k.startswith("Under"):
                    totals[float(k.split()[1])]["under"] = v
        spreads = {}   # the favourite's line as games he must win by -> {"fav": .., "dog": ..}
        for b in T["SPREAD"]:
            f = next((k for k in b if k.startswith(fav + " ")), None)
            d = next((k for k in b if k.startswith(dog + " ")), None)
            if f and d:
                spreads[-float(f.rsplit(" ", 1)[1])] = {"fav": b[f], "dog": b[d]}
        if not totals or not spreads:
            skipped.append(e["description"])
            continue
        tl = min(totals, key=lambda t: abs(totals[t]["over"][1] - 0.5))
        sl = min(spreads, key=lambda s: abs(spreads[s]["fav"][1] - 0.5))
        if tl > 29.5:
            skipped.append(e["description"] + " (best of five: not modelled)")
            continue
        fits = fit(ml[fav][1], tl, totals[tl]["over"][1], sl, spreads[sl]["fav"][1])
        keep = [f for f in fits if f[0] <= fits[0][0] + FIT_SLACK]
        out.append({"id": eid, "league": e["league"], "starts": e["startsTs"], "fav": fav, "dog": dog, "ml": ml,
                    "totals": totals, "spreads": spreads, "tl": tl, "sl": sl, "tables": [f[3] for f in keep],
                    "miss": fits[0][0], "sigma": fits[0][1], "serve": fits[0][2]})
    return sorted(out, key=lambda g: g["starts"]), skipped


def slips(g, sls, tls, ml=True):
    """The candidate slips of a match on these spread and total lines."""
    out = []
    for tl in tls:
        if tl not in g["totals"] or "under" not in g["totals"][tl]:
            continue
        over, under = g["totals"][tl]["over"], g["totals"][tl]["under"]
        for sl in sls:
            if sl not in g["spreads"]:
                continue
            out.append(("dog_games_over", f"{g['dog']} {sl:+g} games + Over {tl}", [g["spreads"][sl]["dog"], over],
                        lambda w, n, a, b, sl=sl, tl=tl: a - b < sl and a + b > tl))
            out.append(("fav_games_under", f"{g['fav']} {-sl:+g} games + Under {tl}", [g["spreads"][sl]["fav"], under],
                        lambda w, n, a, b, sl=sl, tl=tl: a - b > sl and a + b < tl))
        if ml:
            out.append(("fav_ml_under", f"{g['fav']} ML + Under {tl}", [g["ml"][g["fav"]], under], lambda w, n, a, b, tl=tl: w and a + b < tl))
            out.append(("dog_ml_over", f"{g['dog']} ML + Over {tl}", [g["ml"][g["dog"]], over], lambda w, n, a, b, tl=tl: (not w) and a + b > tl))
    rows = []
    for shape, label, legs, f in out:
        cut = trim(shape, g["ml"][g["fav"]][1])
        fs = [P(d, f) / (1 + cut) for d in g["tables"]]
        rows.append({"match": f"{g['fav']} v {g['dog']}", "league": g["league"], "starts": g["starts"], "event": g["id"],
                     "label": label, "ids": [x[0] for x in legs], "leg_fair": [round(x[1], 4) for x in legs],
                     "shape": shape, "trim": cut, "fair": min(fs), "fair_hi": max(fs)})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", default="", help="only matches with this in their name")
    ap.add_argument("--min-ev", type=float, default=0.0, help="print rows at this EV%% or better")
    ap.add_argument("--grid-ev", type=float, default=-3.0, help="a match's other lines are asked when a main-line slip is at this EV%% or better")
    ap.add_argument("--unit", type=float, default=250.0, help="dollars a unit (1u = 1%% of bankroll)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="print every row, not only --min-ev and better")
    a = ap.parse_args()
    games, skipped = matches(a.name)
    say = (lambda *x: print(*x, file=sys.stderr)) if a.json else print
    say(f"Novig tennis · {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} · {len(games)} matches with tight books"
        + (f" · {len(skipped)} without" if skipped else ""))
    lock, last = threading.Lock(), [0.0]

    def ask(r):
        with lock:   # one request a second
            wait = last[0] + 1.05 - time.time()
            if wait > 0:
                time.sleep(wait)
            last[0] = time.time()
        q, why = novig.parlay(r["ids"])
        if not q:
            r["why"] = why
            return r
        M = novig.slip_multiplier(q)
        b = M - 1
        k = max(0.0, (r["fair"] * b - (1 - r["fair"])) / b) / 4 * 100
        r.update(quote=q, slip_x=M, ev=r["fair"] * M - 1, ev_hi=r["fair_hi"] * M - 1, qk=k, wager=k * a.unit, at=time.time())
        return r
    rows = []
    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        first = [r for g in games for r in slips(g, [g["sl"]], [g["tl"]])]
        rows += list(pool.map(ask, first))
        best = collections.defaultdict(lambda: -9.0)
        for r in rows:
            if "ev" in r:
                best[r["event"]] = max(best[r["event"]], r["ev"])
        asked = {tuple(r["ids"]) for r in rows}
        more = [r for g in games if best[g["id"]] * 100 >= a.grid_ev
                for r in slips(g, [g["sl"] - 1, g["sl"], g["sl"] + 1], [g["tl"] - 1, g["tl"], g["tl"] + 1])
                if tuple(r["ids"]) not in asked]
        rows += list(pool.map(ask, more))
    priced = sorted((r for r in rows if "ev" in r), key=lambda r: -r["ev"])
    if a.json:
        for r in priced:
            print(json.dumps(r))
        return
    show = priced if a.all else [r for r in priced if r["ev"] * 100 >= a.min_ev]
    evs = sorted(r["ev"] for r in priced)
    say(f"{len(priced)} slips priced ({len(rows) - len(priced)} with no quote), {sum(1 for r in priced if r['ev'] > 0)} above fair"
        + (f", median {evs[len(evs) // 2]:+.1%}" if evs else ""))
    if show:
        print("| Match | Starts (UTC) | Legs | Fair | to | Novig | EV | to | QK | Wager |")
        print("|---|---|---|---|---|---|---|---|---|---|")
    for r in show:
        print(f"| {r['match']} {r['league']} | {time.strftime('%m-%d %H:%M', time.gmtime(r['starts'] / 1000))} | {r['label']} | "
              f"{novig.american(r['fair']):+d} | {novig.american(r['fair_hi']):+d} | {r['slip_x']:.2f}x | {r['ev']:+.1%} | {r['ev_hi']:+.1%} | "
              f"{r['qk']:.2f}u | ${r['wager']:.0f} |")
    for r in show:
        if r["ev"] > 0:
            print(f"\n{r['match']}: {r['label']}\n  https://novig.onelink.me/JHQQ/events/{','.join(r['ids'])}")


if __name__ == "__main__":
    main()
