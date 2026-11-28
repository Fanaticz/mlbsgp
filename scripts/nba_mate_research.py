#!/usr/bin/env python3
"""Teammates' assists and rebounds: what two seasons of games say, and what
Novig charges. Research only; nothing on the boards reads this.

  python3 scripts/nba_teammate_logs.py      # first: fills .cache/nba_games_<season>.json
  python3 scripts/nba_mate_research.py          # the measurement
  python3 scripts/nba_mate_research.py --novig  # then quote Novig's open games (1 ask a second)

One row per ordered pair of teammates per game both played 20+ minutes. A
leg is "Over his line", the line being his median over his previous 15 such
games (an integer median is tried as both the line below and above it, and
the four results averaged). r is the Gaussian-copula correlation that gives
the share of games both legs hit, pooled over every pair in a group; +/- is
one standard error from resampling team-games. The assist link (A's assists
to B a game) is counted on the pair's PREVIOUS games together, 10 or more,
so it is what was knowable before the game.

Measured 11-24 (1,494 games, 2025-26 and 2026-27 to date):
  A's assists + B's points   +0.07 for any pair; +0.08 where A feeds B 1 to 2
                             assists a game, +0.12 +/- 0.035 at 2 or more.
  A's assists + B's threes   +0.07; +0.10 at 0.75+ three-point assists a game.
  rebounds + rebounds        0.00 (+0.006 +/- 0.006), and within 0.03 of zero
                             by size of line (a 7 with a 4: -0.01), starter or
                             bench, and position.
  A pair's own r is noise: over 150 to 190 pairs with 40+ games together, r
  on their odd games against r on their even games correlates -0.07 to +0.07.
Novig the same night, three reads on the 8 teams with books open for the
next day: rebounds + rebounds implied r +0.04 to +0.055 at the median (61 to
64 slips a read, -0.09 to +0.11), assists + a fed teammate's points +0.10 to
+0.115 (17 to 18 slips). After the parlay fee: medians -11% to -12%; four
slips of about 240 above fair (best +3.2%), none of them on the next read.

Measured again 11-28 (1,516 games), every pairing between two of a team's
top four scorers (top_four): points + points +0.01, rebounds + rebounds
0.00, assists + assists -0.01, threes + threes 0.00, points with the
other's rebounds +0.02 to +0.03, points or threes with the other's assists
+0.05 to +0.07, points with the other's threes -0.01; each +/- 0.01.
Novig, 549 quotes on that night's 10 teams: its implied r was within 0.03
of each of those at the median and between -0.17 and +0.23 slip to slip
(the NFL's teammates ran to -0.30). After the fee every pairing's median was
-7% to -10%; 5 slips at +3% or better, 2 of them still there on two more
asks, one of those because a leg's own price had moved.
"""
import argparse
import collections
import json
import os
import statistics
import sys
import time

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-ast-pts-sgp"))
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-sgp-fv"))
import sgp  # noqa: E402

games = []
for s in (2026, 2027):
    path = os.path.join(ROOT, ".cache", f"nba_games_{s}.json")
    if not os.path.exists(path):
        sys.exit(f"{path} is missing: run scripts/nba_teammate_logs.py first")
    for g in json.load(open(path)):
        g["season"] = s
        games.append(g)
games.sort(key=lambda g: (g["d"], g["id"]))
print(len(games), "games to", games[-1]["d"])
MINM=20; WIN=15
hist=collections.defaultdict(lambda: collections.defaultdict(list))   # aid -> stat -> previous values (20+ min games)
link=collections.defaultdict(lambda:[0,0,0])   # "a>b" -> games together, assists a->b, 3pt assists
rows=[]   # one per ordered teammate pair per game
def line(vals):
    if len(vals)<WIN: return None
    return float(np.median(vals[-WIN:]))
for gi,g in enumerate(games):
    byteam=collections.defaultdict(list)
    for aid,p in g["p"].items():
        if p["min"]>=MINM: byteam[p["t"]].append(aid)
    for t,aids in byteam.items():
        L={a:{s:line(hist[a][s]) for s in ("pts","reb","ast","tpm")} for a in aids}
        for a in aids:
            for b in aids:
                if a==b: continue
                k=f"{a}>{b}"; lk=link[k]
                e=g["ae"].get(k,[0,0])
                rows.append((gi,t,a,b,L[a],L[b],g["p"][a],g["p"][b],lk[0],lk[1],lk[2],e[0]+e[1],e[1]))
    for t,aids in byteam.items():
        for a in aids:
            for b in aids:
                if a==b: continue
                k=f"{a}>{b}"; e=g["ae"].get(k,[0,0]); lk=link[k]
                lk[0]+=1; lk[1]+=e[0]+e[1]; lk[2]+=e[1]
    for aid,p in g["p"].items():
        if p["min"]>=MINM:
            for s in ("pts","reb","ast","tpm"): hist[aid][s].append(p[s])
print(len(rows),"pair-games")

def tetra(n11,n10,n01,n00):
    n=n11+n10+n01+n00
    if n==0: return None
    pa=(n11+n10)/n; pb=(n11+n01)/n; j=n11/n
    if not 0<pa<1 or not 0<pb<1: return None
    return sgp.devig_r(j,pa,pb) if j>0 else -1
def over(v,l,up):   # line l is the median (integer or .5); up: Over (m+0.5) else (m-0.5)
    if l!=int(l): return v>l
    return v>l+0.5 if up else v>l-0.5
def bucket(sel, sa, sb, label, boots=150, quiet=False):
    if len(sel)<300:
        if not quiet: print(f"{label:46s} n={len(sel)} (too few)")
        return None
    va=np.array([r[6][sa] for r in sel],float); la=np.array([r[4][sa] for r in sel],float)
    vb=np.array([r[7][sb] for r in sel],float); lb=np.array([r[5][sb] for r in sel],float)
    ia=la==np.floor(la); ib=lb==np.floor(lb)
    X=[va>np.where(ia,la+(0.5 if u else -0.5),la) for u in (0,1)]
    Y=[vb>np.where(ib,lb+(0.5 if u else -0.5),lb) for u in (0,1)]
    cid={}; c=np.array([cid.setdefault((r[0],r[1]),len(cid)) for r in sel]); K=len(cid)
    def est(w):
        vals=[]
        for x in X:
            for y in Y:
                n11=w[x&y].sum(); n10=w[x&~y].sum(); n01=w[~x&y].sum(); n00=w[~x&~y].sum()
                v=tetra(n11,n10,n01,n00)
                if v is not None: vals.append(v)
        return sum(vals)/len(vals)
    r0=est(np.ones(len(sel)))
    rng=np.random.default_rng(1); bs=[]
    for _ in range(boots):
        cw=np.bincount(rng.integers(0,K,K),minlength=K).astype(float)
        bs.append(est(cw[c]))
    se=float(np.std(bs))
    x,y=X[1],Y[1]; pa,pb,j=x.mean(),y.mean(),(x&y).mean()
    if not quiet: print(f"{label:46s} n={len(sel):6d} tg={K:5d}  r {r0:+.3f} ± {se:.3f}   both {j:.1%} vs indep {pa*pb:.1%}")
    return r0,se


def ok(r, sa, sb):
    return r[4][sa] is not None and r[5][sb] is not None


def measure(sel, tag):
    print(f"\n== {tag}: A's assists Over + B's points Over, by A's assists to B a game before this one ==")
    base = [r for r in sel if ok(r, "ast", "pts") and r[4]["ast"] >= 3 and r[5]["pts"] >= 10]
    bucket(base, "ast", "pts", "any pair (A's assists line 3+, B's points 10+)")
    for lo, hi in ((0, 1.0), (1.0, 2.0), (2.0, 9)):
        bucket([r for r in base if r[8] >= 10 and lo <= r[9] / r[8] < hi], "ast", "pts", f"  {lo:g} to {hi:g} assists a game")
    print(f"== {tag}: A's assists Over + B's threes Over, by three-point assists a game ==")
    base = [r for r in sel if ok(r, "ast", "tpm") and r[4]["ast"] >= 3 and r[5]["tpm"] >= 1]
    bucket(base, "ast", "tpm", "any pair (A's assists line 3+, B's threes 1+)")
    for lo, hi in ((0, 0.75), (0.75, 9)):
        bucket([r for r in base if r[8] >= 10 and lo <= r[10] / r[8] < hi], "ast", "tpm", f"  {lo:g} to {hi:g} a game")
    print(f"== {tag}: rebounds Over + rebounds Over (A the higher line) ==")
    rb = [r for r in sel if ok(r, "reb", "reb") and (r[4]["reb"], r[2]) > (r[5]["reb"], r[3])]
    bucket(rb, "reb", "reb", "any pair")
    bucket([r for r in rb if 6 <= r[4]["reb"] < 9 and 3.5 <= r[5]["reb"] < 5.5], "reb", "reb", "  a line of 6 to 9 with one of 3.5 to 5.5")
    bucket([r for r in rb if r[4]["reb"] >= 9 and r[5]["reb"] >= 5.5], "reb", "reb", "  9+ with 5.5+")
    for sa, sb, lab in ((1, 1, "two starters"), (1, 0, "starter + bench"), (0, 0, "two off the bench")):
        bucket([r for r in rb if {r[6]["st"], r[7]["st"]} == {sa, sb}], "reb", "reb", "  " + lab)
    return rb


def top_four(sel):
    """Every stat pairing between two of a team's top four scorers (by points
    line, among those at 20+ minutes with a line), A the higher points line."""
    by = collections.defaultdict(dict)
    for r in sel:
        if r[4]["pts"] is not None:
            by[(r[0], r[1])][r[2]] = r[4]["pts"]
    rank = {k: {a: i for i, (a, _) in enumerate(sorted(v.items(), key=lambda kv: -kv[1]))} for k, v in by.items()}
    low = {"pts": 8, "reb": 2.5, "ast": 1.5, "tpm": 1}
    print("\n== two of a team's top four scorers, A the higher points line ==")
    for sa in ("pts", "reb", "ast", "tpm"):
        for sb in ("pts", "reb", "ast", "tpm"):
            if {sa, sb} == {"reb", "ast"} or {sa, sb} == {"reb", "tpm"}:
                continue
            bucket([r for r in sel if ok(r, sa, sb) and r[4][sa] >= low[sa] and r[5][sb] >= low[sb]
                    and rank[(r[0], r[1])].get(r[2], 9) < rank[(r[0], r[1])].get(r[3], 9) < 4], sa, sb, f"A's {sa} + B's {sb}", boots=80)


def split(sa, sb, sel, lab):
    """Is a pair's own r real? Its r on odd games against its r on even games."""
    by = collections.defaultdict(list)
    for r in sel:
        by[(r[2], r[3])].append(r)
    xs, ys = [], []
    for rs in by.values():
        if len(rs) < 40:
            continue
        v = [np.corrcoef([x[6][sa] for x in rs[h::2]], [x[7][sb] for x in rs[h::2]])[0, 1] for h in (0, 1)]
        if not np.isnan(v).any():
            xs.append(v[0]), ys.append(v[1])
    print(f"{lab:28s} {len(xs):4d} pairs  mean r {np.mean(xs + ys):+.3f}  a half's r spreads {np.std(xs):.3f}"
          f"  odd against even {np.corrcoef(xs, ys)[0, 1]:+.3f}")


def novig_probe(spread):
    """Novig's quote on every such slip in its open pregame games: the r its
    price implies, and EV after the parlay fee at the measured r."""
    import novig
    import scan
    names = {}
    for g in games:
        names.update(g["names"])
    byname = {novig.norm(n): a for a, n in names.items()}
    logs = json.load(open(os.path.join(ROOT, "public", "data", "nba_teammate_logs.json")))
    team = {p["id"]: p["team"] for p in logs["players"]}
    ms = novig.fetch("NBA", ("pts", "reb", "ast", "tpm"))
    now, P, teams = time.time() * 1000, {}, collections.defaultdict(list)
    for nm in {novig.player_name(m) for m in ms}:
        aid = byname.get(novig.norm(nm))
        _, rows_ = novig.ladder(ms, nm)
        starts = min((r["starts"] for v in rows_.values() for r in v), default=0)
        if aid not in team or starts < now:
            continue
        main = {}
        for s in scan.STATS:
            t = [r for r in rows_.get(s, []) if scan.usable(r, spread)]
            two = [r for r in rows_.get(s, []) if r.get("mid") is not None]
            if t and abs(scan.main_line(t)["line"] - min(two, key=lambda r: abs(r["mid"] - 0.5))["line"]) <= 1:
                main[s] = scan.main_line(t)
        P[aid] = (nm, main)
        teams[team[aid]].append(aid)

    def per_game(a, b):
        lk = link.get(f"{a}>{b}", [0, 0, 0])
        return lk[1] / lk[0] if lk[0] >= 10 else 0.0

    asks = []
    for t, aids in teams.items():
        rb = sorted((a for a in aids if P[a][1].get("reb", {"line": 0})["line"] >= 2.5), key=lambda a: -P[a][1]["reb"]["line"])
        asks += [("reb + reb", t, a, "reb", b, "reb", 0.0, 0.0) for i, a in enumerate(rb[:3]) for b in rb[i + 1:]]
        fed = sorted(((per_game(a, b), a, b) for a in aids for b in aids if a != b and "pts" in P[b][1]
                      and P[a][1].get("ast", {"line": 0})["line"] >= 2.5), reverse=True)
        asks += [("ast + pts", t, a, "ast", b, "pts", lk, 0.12 if lk >= 2 else 0.08) for lk, a, b in fed[:3] if lk >= 1.0]
    out = collections.defaultdict(list)
    for kind, t, a, sa, b, sb, lk, r in asks:
        ra, rb_ = P[a][1][sa], P[b][1][sb]
        q, why = novig.parlay([ra["ids"]["over"], rb_["ids"]["over"]])
        time.sleep(1.1)
        if q is None:
            continue
        imp, ev = sgp.devig_r(q, ra["fo"], rb_["fo"]), sgp.joint(r, ra["fo"], rb_["fo"]) * novig.slip_multiplier(q) - 1
        out[kind].append((imp, ev))
        print(f"{kind} {t:4s} {P[a][0][:20]:20s} o{ra['line']:<4g} {ra['fo']:.2f} | {P[b][0][:20]:20s} o{rb_['line']:<4g} {rb_['fo']:.2f}"
              f"  fed {lk:.2f}/g  Novig's r {imp:+.2f}  ours {r:+.2f}  {novig.slip_multiplier(q):.2f}x  EV {ev:+.1%}", flush=True)
    for kind, v in out.items():
        print(f"{kind}: {len(v)} slips, Novig's r {statistics.median(x[0] for x in v):+.3f} at the median, EV {statistics.median(x[1] for x in v):+.1%},"
              f" {sum(x[1] > 0 for x in v)} above fair, best {max(x[1] for x in v):+.1%}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--novig", action="store_true", help="also quote Novig's open pregame games")
    ap.add_argument("--max-spread", type=float, default=0.08, help="widest Novig book for a leg in the probe")
    a = ap.parse_args()
    first = min(i for i, g in enumerate(games) if g["season"] == 2027)
    measure([r for r in rows if r[0] >= first], "2026-27 to date")
    rb = measure(rows, "both seasons")
    top_four(rows)
    print("\n== a pair's own r, pairs with 40+ games together ==")
    split("ast", "pts", [r for r in rows if ok(r, "ast", "pts") and r[4]["ast"] >= 3 and r[5]["pts"] >= 10], "assists + points")
    split("ast", "tpm", [r for r in rows if ok(r, "ast", "tpm") and r[4]["ast"] >= 3 and r[5]["tpm"] >= 1], "assists + threes")
    split("reb", "reb", rb, "rebounds + rebounds")
    if a.novig:
        novig_probe(a.max_spread)


if __name__ == "__main__":
    main()
