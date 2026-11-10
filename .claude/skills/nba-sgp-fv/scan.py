#!/usr/bin/env python3
"""Novig SGP scanner: same-player 2-leg parlays for every open pregame NBA
player, ranked by EV at what Novig's slip pays.

  python3 scan.py                 # whole slate, best prospects first
  python3 scan.py --tier 1        # Points + Threes only (about 2 minutes)
  python3 scan.py --max 120       # stop after 120 quotes
  python3 scan.py --min-ev 3      # print only rows at +3% or better
  python3 scan.py --json          # one JSON object per line as quotes land
                                  # (server.js reads this for the Scanner page)

Fair value: each leg is Novig's own exchange book at that line, devigged
worst case (novig.py), and the two are joined with the player's shrunk
correlation in a Gaussian copula (price.py), exactly as
`price.py ... novig` does. Price: Novig's public parlay quote after its 10%
parlay fee (novig.slip_multiplier), which is the multiplier on the app's slip.

What gets quoted, in this order (a quote takes about 3 seconds, and Novig
allows one a second, so the order is the scan's budget):
  1  Points Over + Threes Over, highest r first: the points main line with
     the threes main line and the next milestone beside it (that second one
     may sit on a book up to --alt-spread wide; flagged ~).
  2  Over + Over on the other pairs (PTS·REB, PTS·AST, REB·AST, REB·3PM,
     AST·3PM) at main lines, where r is at least --min-r.
  3  Over + Under both ways at main lines, where r is at most -(--neg-r).
  4  Three legs: the best --tri two-leg Over + Over rows (at --tri-min-ev or
     better) each get every other stat's main-line Over added, wherever no
     pair in the three has a negative r.
Under + Under is never asked: Novig rejects it for one player. Legs on books
wider than --max-spread are skipped, not guessed.

EV and the stake use the fair value as shown (American odds), like price.py:
quarter Kelly, 1u = 1% of bankroll = --unit dollars.
"""
import argparse
import concurrent.futures
import json
import math
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "nba-ast-pts-sgp"))
import novig  # noqa: E402
import price  # noqa: E402  shrunk_r
import sgp  # noqa: E402  joint, american, prob, load

STATS = ("pts", "reb", "ast", "tpm")
LABEL = {"pts": "PTS", "reb": "REB", "ast": "AST", "tpm": "3PM"}
PAIRS = [("pts", "reb"), ("pts", "ast"), ("reb", "ast"), ("reb", "tpm"), ("ast", "tpm")]


def usable(r, spread):
    return r["spread"] is not None and r["spread"] <= spread + 1e-9 and 0 < r["bid"] < r["ask"] < 1


def main_line(rows):
    """The line nearest 50/50 among these books, ties to the tighter, busier one."""
    return min(rows, key=lambda r: (abs(r["fo"] - 0.5) + r["spread"], -r["volume"]))


def beside(rows, main):
    """The milestones around even money other than `main`, one line away: the
    last Over at 50% or better and the first under it (3+ at -130, 4+ at +140)."""
    fav = [r for r in rows if r["fo"] >= 0.5]
    dog = [r for r in rows if r["fo"] < 0.5]
    out = ([max(fav, key=lambda r: r["line"])] if fav else []) + ([min(dog, key=lambda r: r["line"])] if dog else [])
    return [r for r in out if abs(r["line"] - main["line"]) == 1]


def leg(stat, row, side):
    p = row["fo"] if side > 0 else row["fu"]
    return {"stat": stat, "side": "over" if side > 0 else "under", "line": row["line"], "p": p,
            "fair": sgp.american(p), "width": row["spread"], "id": row["ids"]["over" if side > 0 else "under"]}


def leg_text(L):
    """'13+ PTS' for Over 12.5 (Novig's "13+ Points · Yes"), 'U26.5 PTS' for an Under."""
    if L["side"] == "over":
        return f"{math.floor(L['line']) + 1}+ {LABEL[L['stat']]}"
    return f"U{L['line']:g} {LABEL[L['stat']]}"


def candidates(markets, d, by, a):
    """(every 2-leg combo worth a quote, in quoting order; {player id: (player,
    his main-line rows by stat)} for the 3-leg pass)."""
    key = {novig.norm(n): n for n in by}
    t1, rest, ctx = [], [], {}
    for nm in sorted({novig.player_name(m) for m in markets}):
        p = by.get(key.get(novig.norm(nm), ""))
        if not p:
            continue
        _, rows = novig.ladder(markets, nm)
        tight = {s: [r for r in rows.get(s, []) if usable(r, a.max_spread)] for s in STATS}
        main = {s: main_line(v) for s, v in tight.items() if v}
        starts = min((r["starts"] for v in rows.values() for r in v), default=None)
        ctx[p["athlete_id"]] = (p, main, starts)

        def combo(tier, r, la, lb):
            same = la["side"] == lb["side"]
            # k threes are 3k points: a threes Over that forces the points
            # Over makes the parlay just the threes leg.
            forced = (same and la["stat"] == "pts" and lb["stat"] == "tpm" and la["side"] == "over"
                      and 3 * (math.floor(lb["line"]) + 1) > la["line"])
            j = min(la["p"], lb["p"]) if forced else sgp.joint(r if same else -r, la["p"], lb["p"])
            return {"key": f"{la['id']},{lb['id']}", "tier": tier, "player": p["name"], "id": p["athlete_id"],
                    "team": p.get("team_abbr") or "", "starts": starts, "legs": [la, lb],
                    "label": f"{leg_text(la)} · {leg_text(lb)}", "r": r, "j": j, "forced": forced,
                    "devig_r": sgp.devig_r(j, la["p"], lb["p"]),
                    "rough": max(la["width"], lb["width"]) > novig.MAX_SPREAD + 1e-9}

        if a.tier in (0, 1) and "pts" in main and "tpm" in main:
            r = price.shrunk_r(d, by, p, "pts", "tpm")[0]
            if r > 0:
                P, T = main["pts"], main["tpm"]
                threes = [T] + beside([x for x in rows.get("tpm", []) if usable(x, a.alt_spread)], T)
                t1 += [combo(1, r, leg("pts", P, 1), leg("tpm", t, 1)) for t in threes]
        if a.tier == 1:
            continue
        for x, y in PAIRS:
            if x not in main or y not in main:
                continue
            r = price.shrunk_r(d, by, p, x, y)[0]
            if r >= a.min_r and a.tier in (0, 2):
                rest.append(combo(2, r, leg(x, main[x], 1), leg(y, main[y], 1)))
            elif r <= -a.neg_r and a.tier in (0, 3):
                rest += [combo(3, r, leg(x, main[x], sx), leg(y, main[y], -sx)) for sx in (1, -1)]
    t1.sort(key=lambda c: -c["r"])
    rest.sort(key=lambda c: -abs(c["r"]))
    out = t1 + rest
    return (out[:a.max] if a.max else out), ctx


def triples(rows, ctx, d, by, a):
    """Three-leg combos: the best two-leg Over + Over rows, each with one more
    stat's main-line Over."""
    base = sorted((c for c in rows if len(c["legs"]) == 2 and all(L["side"] == "over" for L in c["legs"])
                   and c["ev"] * 100 >= a.tri_min_ev), key=lambda c: -c["ev"])[:a.tri]
    out, seen = [], set()
    for c in base:
        p, main, starts = ctx[c["id"]]
        la, lb = c["legs"]
        for s in STATS:
            if s in (la["stat"], lb["stat"]) or s not in main:
                continue
            lc = leg(s, main[s], 1)
            ids = frozenset((la["id"], lb["id"], lc["id"]))
            if ids in seen:   # the same three legs, reached from another pair
                continue
            seen.add(ids)
            rac, rbc = (price.shrunk_r(d, by, p, L["stat"], s)[0] for L in (la, lb))
            if min(rac, rbc) < 0:
                continue
            # Forced points (see candidates): the parlay is threes + the new leg.
            j = (sgp.joint(rbc, lb["p"], lc["p"]) if c["forced"] else
                 price.tri_joint([la["p"], lb["p"], lc["p"]], [[1, c["r"], rac], [c["r"], 1, rbc], [rac, rbc, 1]]))
            out.append({"key": f"{c['key']},{lc['id']}", "tier": 4, "player": c["player"], "id": c["id"], "team": c["team"],
                        "starts": starts, "legs": [la, lb, lc], "label": f"{c['label']} · {leg_text(lc)}",
                        "r": min(c["r"], rac, rbc), "j": j, "forced": c["forced"], "devig_r": None,
                        "rough": c["rough"] or lc["width"] > novig.MAX_SPREAD + 1e-9})
    return out


class Pace:
    """Novig's limit is a 10-request burst per IP, then one a second."""

    def __init__(self, burst=5, every=1.1):
        self.lock, self.left, self.every, self.next = threading.Lock(), burst, every, 0.0

    def wait(self):
        with self.lock:
            if self.left > 0:
                self.left -= 1
                return
            t = max(time.time(), self.next)
            self.next = t + self.every
        time.sleep(max(0.0, t - time.time()))


def finish(c, quote, unit, kelly):
    """Add the slip price, EV and stake to a quoted combo."""
    fair = sgp.american(c["j"])
    p, slip = sgp.prob(fair), novig.slip_multiplier(quote)   # EV at the FV as shown
    b = slip - 1
    qk = max(0.0, (p * b - (1 - p)) / b) * kelly * 100
    c.update(fair=fair, fair_x=1 / p, quote=quote, raw_x=1 / quote, slip_x=slip, slip=sgp.american(1 / slip),
             ev=p * slip - 1, qk=qk, wager=qk * unit, at=time.time())
    return c


def scan(a, emit):
    """Quote every candidate; emit(event dict) as things happen. Returns the priced rows."""
    t0 = time.time()
    d, by = sgp.load()
    cands, ctx = candidates(novig.fetch(), d, by, a)
    emit({"type": "start", "total": len(cands), "players": len({c["id"] for c in cands}),
          "data": d["generated_at"][:10], "at": t0})
    pace, rows, lock = Pace(), [], threading.Lock()

    def one(c):
        pace.wait()
        quote, why = novig.parlay([L["id"] for L in c["legs"]])
        with lock:
            if quote:
                rows.append(finish(c, quote, a.unit, a.kelly))
                emit(dict(c, type="row"))
            else:
                emit({"type": "miss", "key": c["key"], "player": c["player"], "label": c["label"], "why": why})

    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        list(pool.map(one, cands))
        if a.tri and a.tier in (0, 4):
            more = triples(list(rows), ctx, d, by, a)
            emit({"type": "more", "add": len(more)})
            cands = cands + more
            list(pool.map(one, more))
    emit({"type": "done", "quoted": len(cands), "priced": len(rows), "seconds": time.time() - t0, "at": time.time()})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", type=int, default=0, choices=(0, 1, 2, 3), help="one two-leg group only (default: all, then three legs)")
    ap.add_argument("--tri", type=int, default=12, help="two-leg rows to extend to three legs (0 = none)")
    ap.add_argument("--tri-min-ev", type=float, default=-6.0, help="only extend two-leg rows at this EV%% or better")
    ap.add_argument("--max", type=int, default=0, help="quote at most this many combos (default: all)")
    ap.add_argument("--min-r", type=float, default=0.15, help="smallest r for an Over + Over on the other pairs")
    ap.add_argument("--neg-r", type=float, default=0.05, help="Over + Under is asked when r is at most minus this")
    ap.add_argument("--max-spread", type=float, default=novig.MAX_SPREAD, help="widest Novig book for a leg (prob)")
    ap.add_argument("--alt-spread", type=float, default=0.08, help="widest book for the second threes milestone")
    ap.add_argument("--workers", type=int, default=3, help="quotes in flight at once")
    ap.add_argument("--unit", type=float, default=250.0, help="dollars per unit, 1u = 1%% of bankroll")
    ap.add_argument("--kelly", type=float, default=0.25, help="Kelly fraction (default quarter)")
    ap.add_argument("--min-ev", type=float, default=None, help="print only rows at this EV%% or better")
    ap.add_argument("--top", type=int, default=25, help="rows to print (default 25; 0 = all)")
    ap.add_argument("--json", action="store_true", help="stream events as JSON lines instead of a table")
    a = ap.parse_args()

    if a.json:
        out = threading.Lock()

        def emit(e):
            with out:
                print(json.dumps(e), flush=True)
        scan(a, emit)
        return

    def emit(e):
        if e["type"] == "more" and e["add"]:
            print(f"+ {e['add']} three-leg combos", file=sys.stderr)
        if e["type"] == "start":
            print(f"{e['total']} combos on {e['players']} players · r data {e['data']} · "
                  f"about {max(1, round(e['total'] * 1.1 / 60))} min", file=sys.stderr)
    rows = scan(a, emit)
    rows.sort(key=lambda c: -c["ev"])
    shown = [c for c in rows if a.min_ev is None or c["ev"] * 100 >= a.min_ev]
    shown = shown[:a.top] if a.top else shown
    print(f"Novig SGP scan · {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} · "
          f"{len(rows)} priced, {sum(c['ev'] > 0 for c in rows)} above fair")
    print("| Player | Legs | Leg fairs | r | Fair | Novig | EV | QK | Wager |")
    print("|---|---|---|---|---|---|---|---|---|")
    for c in shown:
        legs = " / ".join(f"{L['fair']:+d}" for L in c["legs"])
        print(f"| {c['player']} {c['team']} | {c['label']}{' ~' if c['rough'] else ''} | {legs} | {c['r']:+.2f} | "
              f"{c['fair']:+d} | {c['slip_x']:.2f}x | {c['ev']:+.1%} | {c['qk']:.2f}u | ${c['wager']:,.0f} |")
    if any(c["rough"] for c in shown):
        print("~ a leg sits on a Novig book wider than 4c: rough fair value")


if __name__ == "__main__":
    main()
