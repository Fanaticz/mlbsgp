#!/usr/bin/env python3
"""Novig SGP scanner: same-player 2-leg parlays for every open pregame NBA
player, ranked by EV at what Novig's slip pays.

  python3 scan.py                 # main-line Points + Threes, one slip a player
  python3 scan.py --scope all     # everything listed below (many more quotes)
  python3 scan.py --scope ladder  # NBA shooters' higher lines only, one-way lines included
  python3 scan.py --league nfl --scope ladder   # NFL: higher yards lines + TD / receptions / passing TDs
  python3 scan.py --tier 1        # Points + Threes only (about 2 minutes)
  python3 scan.py --max 120       # stop after 120 quotes
  python3 scan.py --min-ev 3      # print only rows at +3% or better
  python3 scan.py --league nfl    # NFL: a player's own props, QB + receiver stacks, props + game lines
  python3 scan.py --league nfl --kind stacks   # one kind only: props, stacks or lines
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
  Everything after 1 is asked only for players whose best main-line Points +
  Threes quote came back above --gate (0%), or who have no such quote.
  1b Up the ladder for the shooters (r at least --ladder-r): every higher
     points line Novig lists (to main + 10) with threes at main, +1 and +2.
     Fair is modelled, not read off a book: each leg is shifted from the
     main line (price.py's `from`: normal for points, normal + count model
     for threes), then the usual copula joint. Rows are marked * on the
     page. --ladder-fix also scales the joint by LADDER_FIX, the model's
     shortfall on 128 shooters' game logs (x1.00 at the main lines up to
     x1.28 at +8 points, +2 threes); it is off by default because other
     books' SGP prices say that correction is too generous.
  1d Triple-doubles for players whose rebounds and assists main lines are
     both 5.5+: 10+ rebounds · 10+ assists with points at the lowest line
     from 10+, then the next two up (no higher than his main line).
  1c Build-your-own double-doubles: 10+ with 10+ on points, rebounds and
     assists, for players whose main lines are both at least 5.5. Modelled
     like the ladder (legs shifted from the main lines), marked *.
  2  Over + Over at main lines, where r is at least --min-r: Points +
     Rebounds for big men only (centres, and forwards averaging 9.5+
     rebounds), and REB·3PM, AST·3PM for anyone. Points + Assists and
     Rebounds + Assists are not asked, and nothing is asked Over + Under.
  4  Three legs: the best --tri two-leg Over + Over rows (at --tri-min-ev or
     better) each get every other stat's main-line Over added, wherever no
     pair in the three has a negative r.
Under + Under is never asked: Novig rejects it for one player. Legs on books
wider than --max-spread are skipped, not guessed.

NFL (--league nfl): WRs, TEs and RBs in public/data/nfl_correlations.json,
whose shrunk r's are already copula correlations. Over + Over at main lines
on Receptions·Yards, Receptions·TD and Yards·TD (TD = Novig's TOUCHDOWNS 0.5,
any touchdown, as the data counts receiving + rushing), then the three
together (--scope all). Quarterbacks: Over + Over at main lines on pass
attempts, completions, passing yards and passing TDs, every pair with r at
least --min-r (attempts + passing TDs, about 0.11, falls under it), and
rushing yards with his anytime TD. Running backs: rushing yards, rushing +
receiving yards and carries, each with anytime TD.

The same NFL pass then asks two kinds of slip across markets (--kind picks
one). Stacks: a QB's passing Over with one of his own receivers' Over:
passing yards + receiving yards, passing TDs + anytime TD, completions +
receptions, passing yards + anytime TD. Lines: a player's prop Over with the game total, his team's
spread or his team's total, on whichever side goes with it (RB rushing yards
+ his team covering; QB pass attempts + the other team covering), where |r|
is at least --line-r. Both use league-wide r's by role (position and targets
or carries a game) from public/data/nfl_stack_correlations.json, ten
seasons of nflverse; each player gets his --per highest-r combos of each.

Soccer (--league soccer): for every open match with team-corners books it
asks Max's shape, favourite to win (3-way) + favourite's corners Under +
underdog's corners Over, alone and with goals Over 1.5 or Over 2.5. A
leading favourite sits back and the underdog chases, so the legs hit
together more often than unrelated legs would. Fair value = the legs'
product times SOCCER_LIFT, measured on 17,934 top-five-league matches
(2015-16 on, football-data.co.uk: results, corners, closing odds) with
corner lines nearest 50/50: x1.25 to x1.33 with no goals leg, x1.31 to
x1.38 with Over 1.5, x1.40 to x1.61 with Over 2.5, larger for weaker
favourites. League averages, not match-specific: rows are leads.

EV and the stake use the fair value as shown (American odds), like price.py:
quarter Kelly, 1u = 1% of bankroll = --unit dollars.
"""
import argparse
import concurrent.futures
import itertools
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
LABEL = {"pts": "PTS", "reb": "REB", "ast": "AST", "tpm": "3PM", "rec": "REC", "yds": "YDS", "td": "TD",
         "att": "PASS ATT", "cmp": "CMP", "pyds": "PASS YDS", "ptd": "PASS TD",
         "car": "CAR", "ryds": "RUSH YDS", "rry": "RUSH+REC YDS"}
PAIRS = [("pts", "reb"), ("pts", "ast"), ("reb", "ast"), ("reb", "tpm"), ("ast", "tpm")]
NFL_STATS = ("rec", "yds", "td", "att", "cmp", "pyds", "ptd", "car", "ryds", "rry")
NFL_PAIRS = {("rec", "yds"): "rec_yds", ("rec", "td"): "rec_td", ("yds", "td"): "yds_td",
             # quarterbacks (the data has these pairs for QBs only)
             ("att", "cmp"): "att_cmp", ("att", "pyds"): "att_pyds", ("cmp", "pyds"): "cmp_pyds",
             ("att", "ptd"): "att_ptd", ("cmp", "ptd"): "cmp_ptd", ("pyds", "ptd"): "pyds_ptd",
             # running backs, and a QB's rushing yards with his anytime TD. Novig won't
             # parlay carries with rushing yards, or rushing yards with rushing + receiving.
             ("ryds", "td"): "ryds_td", ("rry", "td"): "rry_td", ("car", "td"): "car_td"}
NFL_DATA = os.path.join(HERE, "..", "..", "..", "public", "data", "nfl_correlations.json")


def nfl_r(p, x, y):
    """The player's shrunk copula r for the pair, or None when he has too few games."""
    k = NFL_PAIRS.get((x, y)) or NFL_PAIRS.get((y, x))
    return ((p.get(k) or {}).get("shrunk") or {}).get("r")


# actual / modelled hit rate of both legs, by (points above main rounded to 2, threes above main):
# 128 rotation shooters, lines relative to each player's own average (ladder backtest, 11-10).
LADDER_FIX = {(0, 0): 1.00, (0, 1): 1.06, (0, 2): 1.13, (2, 0): 1.00, (2, 1): 1.05, (2, 2): 1.16,
              (4, 0): 1.04, (4, 1): 1.09, (4, 2): 1.20, (6, 0): 1.08, (6, 1): 1.12, (6, 2): 1.23,
              (8, 0): 1.18, (8, 1): 1.20, (8, 2): 1.28}


BOOKS = {"on": True, "ladders": None, "check": None}   # pulled once, on the first shifted leg


def shifted(p, stat, row, main):
    """A leg at `row`'s line with its fair value shifted from the main line's."""
    po = main["fo"] if row is main else price.leg_prob(
        p, {"stat": stat, "side": 1, "line": row["line"], "from": main["line"], "p_over": main["fo"],
            "over": None, "under": None})[0]
    # Novig's own ask on that line is a ceiling: someone is selling the Over
    # there, so the true chance is below it however wide the book is.
    if row is not main and row.get("ask") is not None:
        po = min(po, row["ask"])
    if row is not main and row.get("bid") is not None:   # and a buyer there is a floor
        po = max(po, row["bid"])
    if row is not main and BOOKS["on"]:   # DK / FanDuel one-way price, least margin out: a ceiling
        if BOOKS["ladders"] is None:
            import books
            BOOKS["ladders"], BOOKS["check"] = books.load(), books.check
        cap = BOOKS["check"](BOOKS["ladders"], p["name"], stat, row["line"])[0]
        if cap is not None:
            po = min(po, cap)
    return {"stat": stat, "side": "over", "line": row["line"], "p": po, "fair": sgp.american(po),
            "width": main["spread"], "id": row["ids"]["over"], "from": None if row is main else main["line"]}


def big(p):
    """A centre, or a forward who rebounds like one (Wembanyama, Giannis and
    Sabonis are listed as F)."""
    return p.get("position") == "C" or (p.get("position") == "F" and (p.get("reb_mean") or 0) >= 9.5)


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


def nfl_candidates(markets, by, a):
    """NFL: Over + Over at main lines on each pair with r at least --min-r,
    most lift over independent legs first. Same shapes as candidates()."""
    key = {novig.norm(n): n for n in by}
    out, ctx = [], {}
    for nm in sorted({novig.player_name(m) for m in markets}):
        p = by.get(key.get(novig.norm(nm), ""))
        if not p:
            continue
        _, rows = novig.ladder(markets, nm)
        # Anytime TD is the 0.5 line only: 2+ TDs is a longshot the r wasn't fit for.
        main = {s: main_line(v) for s in NFL_STATS
                for v in [[r for r in rows.get(s, []) if usable(r, a.max_spread) and (s != "td" or r["line"] == 0.5)]] if v}
        starts = min((r["starts"] for v in rows.values() for r in v), default=None)
        ctx[p["athlete_id"]] = (p, main, starts)
        for x, y in NFL_PAIRS:
            r = nfl_r(p, x, y)
            if x not in main or y not in main or r is None or r < a.min_r:
                continue
            la, lb = leg(x, main[x], 1), leg(y, main[y], 1)
            j = sgp.joint(r, la["p"], lb["p"])
            out.append({"key": f"{la['id']},{lb['id']}", "tier": 2, "player": p["name"], "id": p["athlete_id"],
                        "team": p.get("team_abbr") or "", "starts": starts, "legs": [la, lb],
                        "label": f"{leg_text(la)} · {leg_text(lb)}", "r": r, "j": j, "forced": False,
                        "devig_r": sgp.devig_r(j, la["p"], lb["p"]),
                        "rough": max(la["width"], lb["width"]) > novig.MAX_SPREAD + 1e-9})
    out.sort(key=lambda c: -c["j"] / (c["legs"][0]["p"] * c["legs"][1]["p"]))
    return (out[:a.max] if a.max else out), ctx


# NFL ladder: a yards line above the main line (one-way lines included) with
# the partner leg at its own main line.
NFL_LADDER = (("yds", "td"), ("yds", "rec"), ("ryds", "td"), ("pyds", "ptd"))


def nfl_ladder_candidates(markets, by, a):
    """NFL ladder (--scope ladder): for each player, every yards line Novig
    lists above his main line, with anytime TD (a QB: passing TDs; a receiver
    also receptions) at its main line. The yards leg is shifted from the main
    line with nfl_shift (a gamma at the spread the books' own ladders imply)
    unless Novig has a tight two-way book on that line. The main line is
    Novig's when it has a tight one near even money, else DK's or FanDuel's
    two-way line. A shifted leg is held under Novig's ask, over its bid, and
    under DK's / FanDuel's one-way price on that line."""
    import nfl_shift
    lad = None
    if BOOKS["on"]:
        import books
        lad = books.load(league="nfl")
    key = {novig.norm(n): n for n in by}
    out, ctx = [], {}
    for nm in sorted({novig.player_name(m) for m in markets}):
        p = by.get(key.get(novig.norm(nm), ""))
        if not p:
            continue
        _, rows = novig.ladder(markets, nm)
        tight = {s: [r for r in rows.get(s, []) if usable(r, a.max_spread) and (s != "td" or r["line"] == 0.5)]
                 for s in NFL_STATS}
        main = {s: main_line(v) for s, v in tight.items() if v}
        starts = min((r["starts"] for v in rows.values() for r in v), default=None)
        ctx[p["athlete_id"]] = (p, main, starts)
        for y, z in NFL_LADDER:
            r = nfl_r(p, y, z)
            if r is None or r < a.min_r or z not in main or not rows.get(y):
                continue
            if y in main and abs(main[y]["fo"] - 0.5) <= 0.15:
                m_line, m_p, m_w, src = main[y]["line"], main[y]["fo"], main[y]["spread"], None
            else:
                bm = lad and books.main_line(lad, nm, y)
                if not bm:
                    continue
                m_line, m_p, src = bm
                m_w = 0.0
            lz = leg(z, main[z], 1)
            for row in rows[y]:
                if row["line"] <= m_line or "over" not in row["ids"] or row["line"] > 3 * m_line + 0.5:
                    continue
                if usable(row, a.max_spread):
                    po, frm, width = row["fo"], None, row["spread"]
                else:
                    try:
                        po = nfl_shift.over(y, m_line, m_p, row["line"])
                    except (ValueError, ZeroDivisionError, OverflowError):
                        continue
                    asks = [x["ask"] for x in rows[y] if x["line"] <= row["line"] and x["ask"] is not None]
                    bids = [x["bid"] for x in rows[y] if x["line"] >= row["line"] and x["bid"] is not None]
                    cap = lad and books.check(lad, nm, y, row["line"])[0]
                    po = min([po] + asks + ([cap] if cap else []))
                    po, frm, width = max([po] + bids), m_line, m_w
                if not 0 < po < 1:
                    continue
                ly = {"stat": y, "side": "over", "line": row["line"], "p": po, "fair": sgp.american(po),
                      "width": width, "id": row["ids"]["over"], "from": frm}
                if src and frm is not None:
                    ly["src"] = src
                j = sgp.joint(r, po, lz["p"])
                if a.ladder_fair and not a.ladder_fair[0] <= sgp.american(j) <= a.ladder_fair[1]:
                    continue
                out.append({"key": f"{ly['id']},{lz['id']}", "tier": 2, "player": p["name"], "id": p["athlete_id"],
                            "team": p.get("team_abbr") or "", "starts": starts, "legs": [ly, lz],
                            "label": f"{leg_text(ly)} · {leg_text(lz)}", "r": r, "j": j, "forced": False,
                            "devig_r": None if frm is not None else sgp.devig_r(j, po, lz["p"]),
                            "model": frm is not None, "fix": 1.0,
                            "rough": max(width, lz["width"]) > novig.MAX_SPREAD + 1e-9})
    out.sort(key=lambda c: -c["r"])
    return (out[:a.max] if a.max else out), ctx


STACK_DATA = os.path.join(HERE, "..", "..", "..", "public", "data", "nfl_stack_correlations.json")
STACK_PROPS = ("pyds", "ptd", "cmp", "att", "yds", "rec", "td", "ryds", "car", "rry")
# QB stat + teammate's stat asked by default; --scope all adds the weaker two.
STACK_PAIRS = (("pyds", "yds"), ("ptd", "td"), ("cmp", "rec"), ("pyds", "td"))
STACK_MORE = (("pyds", "rec"), ("ptd", "yds"))
LINE_TYPES = {"over": "TOTAL", "cover": "SPREAD", "tt": "TEAM_TOTAL"}


def role_r(table, vol, **match):
    """The role's r from nfl_stack_correlations.json: the row matching
    `match` whose volume bucket holds `vol` (targets or carries a game)."""
    for e in table:
        if all(e.get(k) == v for k, v in match.items()) and (
                e["by"] is None or (vol is not None and e["min"] <= vol and (e["max"] is None or vol < e["max"]))):
            return e["r"]
    return None


def two_way(m):
    """A two-outcome game market as fair values for each side, or None when
    a side has no bid."""
    o = m["outcomes"]
    if len(o) != 2 or not all(x.get("bid") for x in o):
        return None
    b0, b1 = float(o[0]["bid"]["price"]), float(o[1]["bid"]["price"])
    if not 0 < b0 < 1 - b1 < 1:
        return None
    f0, f1 = sgp.devig_worst(1 - b1, 1 - b0)
    return {"desc": m["description"], "strike": float(m["strike"]), "p": (f0, f1), "spread": 1 - b1 - b0,
            "ids": (o[0]["outcomeId"], o[1]["outcomeId"]), "names": (o[0]["name"], o[1]["name"]),
            "volume": m["volume"]}


def nflx_candidates(a, game):
    """NFL bets across two markets in one game, priced with league-wide role
    correlations (scripts/nfl_stack_correlations.py, nflverse):
      stacks (game=False)  a QB's passing Over + one of his own receivers' Over
      lines (game=True)    a player's prop Over + the game total, his team's
                           spread or team total, on the side that goes with it
                           (QB pass attempts Over goes with the OTHER team covering)
    Each player gets his --per highest-r combos of each kind."""
    d, S = json.load(open(NFL_DATA)), json.load(open(STACK_DATA))
    cur = str(max(d["seasons"]))
    by = {novig.norm(p["name"]): p for p in d["players"]}
    types = [novig.ALL_TYPES[s] for s in STACK_PROPS] + (list(LINE_TYPES.values()) if game else ["TOTAL"])
    items = novig.catalog({"league": "NFL", "eventStatus": "OPEN_PREGAME", "marketType": ",".join(types)})
    props = [m for m in items if m["marketType"] in novig.STAT]
    events = {}   # eventId -> {"teams": (away, home), "lines": {type: [two_way rows]}}
    for m in items:
        if m["marketType"] in novig.STAT:
            continue
        ev = events.setdefault(m["eventId"], {"teams": None, "lines": {}})
        if m["marketType"] == "TOTAL" and " @ " in m["description"]:
            ev["teams"] = tuple(m["description"].rsplit(" t", 1)[0].split(" @ "))
        t = two_way(m)
        if t and t["spread"] <= a.max_spread + 1e-9:
            ev["lines"].setdefault(m["marketType"], []).append(t)

    def vol(p, k):
        s = (p.get("by_season") or {}).get(cur) or {}
        return (s if s.get("games", 0) >= 3 else p).get(k)

    people = {}   # eventId -> team -> [(player, main lines, starts)]
    for nm in sorted({novig.player_name(m) for m in props}):
        p = by.get(novig.norm(nm))
        if not p:
            continue
        _, rows = novig.ladder(props, nm)
        main = {s: main_line(v) for s in STACK_PROPS
                for v in [[r for r in rows.get(s, []) if usable(r, a.max_spread) and (s != "td" or r["line"] == 0.5)]] if v}
        eid = next(m["eventId"] for m in props if novig.player_name(m) == nm)
        teams = (events.get(eid) or {}).get("teams")
        if not main or not teams or p.get("team_abbr") not in teams:
            continue   # no tight book, or he has changed teams since the data was built
        starts = min(r["starts"] for v in rows.values() for r in v)
        people.setdefault(eid, {}).setdefault(p["team_abbr"], []).append((p, main, starts))

    def row(p, starts, la, lb, r, kind, tier):
        j = sgp.joint(r, la["p"], lb["p"])
        return {"key": f"{la['id']},{lb['id']}", "tier": tier, "player": p["name"], "id": p["athlete_id"],
                "team": p.get("team_abbr") or "", "starts": starts, "legs": [la, lb], "kind": kind,
                "label": f"{la['text']} · {lb['text']}", "r": r, "j": j, "forced": False,
                "devig_r": sgp.devig_r(j, la["p"], lb["p"]),
                "rough": max(la["width"], lb["width"]) > novig.MAX_SPREAD + 1e-9}

    def prop(p, s, main, who=""):
        L = leg(s, main[s], 1)
        L["text"] = f"{who}{leg_text(L)}"
        return L

    out = []
    for eid, sides in people.items():
        ev = events[eid]
        for team, ps in sides.items():
            if not game:
                qbs = [x for x in ps if x[0]["group"] == "QB"]
                if not qbs:
                    continue
                qb, qmain, _ = max(qbs, key=lambda x: x[0].get("att_mean") or 0)
                who = qb["name"].split()[-1] + " "
                for p, main, starts in ps:
                    if p["group"] == "QB":
                        continue
                    mine = []
                    for qs, ts in STACK_PAIRS + (STACK_MORE if a.scope == "all" else ()):
                        r = role_r(S["stack"], vol(p, "tgt_mean"), qb=qs, stat=ts, pos=p["group"], by="tgt")
                        if qs in qmain and ts in main and r is not None and r >= a.min_r:
                            mine.append(row(p, starts, prop(qb, qs, qmain, who), prop(p, ts, main), r, "stack", 7))
                    out += sorted(mine, key=lambda c: -c["r"])[:a.per]
                continue
            opp = next(t for t in ev["teams"] if t != team)
            for p, main, starts in ps:
                mine = []
                for s in main:
                    for line, typ in LINE_TYPES.items():
                        # A back's rushing and his TD go by his carries, everything else by targets.
                        by_ = None if p["group"] == "QB" else "car" if p["group"] == "RB" and s in ("ryds", "car", "rry", "td") else "tgt"
                        r = role_r(S["game"], by_ and vol(p, by_ + "_mean"), line=line, stat=s, pos=p["group"], by=by_)
                        if r is None or abs(r) < a.line_r:
                            continue
                        ms = ev["lines"].get(typ, [])
                        if line == "tt":
                            ms = [m for m in ms if m["desc"].startswith(p.get("team_name") or "?")]
                        if not ms:
                            continue
                        m = min(ms, key=lambda m: (abs(m["p"][0] - 0.5) + m["spread"], -m["volume"]))
                        if line == "cover":   # his team's side when r > 0, the other team's when r < 0
                            i = next(i for i, n in enumerate(m["names"]) if n.split()[0] == (team if r > 0 else opp))
                            text = m["names"][i]
                        else:
                            i = 0 if r > 0 else 1
                            what = " @ ".join(ev["teams"]) if line == "over" else team + " team total"
                            text = f"{what} {'Over' if i == 0 else 'Under'} {m['strike']:g}"
                        lb = {"stat": line, "side": "over" if i == 0 else "under", "line": m["strike"], "p": m["p"][i],
                              "fair": sgp.american(m["p"][i]), "width": m["spread"], "id": m["ids"][i], "text": text}
                        mine.append(row(p, starts, prop(p, s, main), lb, abs(r), line, 8))
                out += sorted(mine, key=lambda c: -c["r"])[:a.per]
    out.sort(key=lambda c: -c["j"] / (c["legs"][0]["p"] * c["legs"][1]["p"]))
    return out[:a.max] if a.max else out


# (favourite's win probability up to, lift over unrelated legs) by goals leg:
# how much more often the whole slip hits than the product of its legs.
SOCCER_LIFT = {None: [(0.50, 1.33), (0.60, 1.29), (0.70, 1.26), (1.0, 1.25)],
               "1.5": [(0.50, 1.38), (0.60, 1.32), (0.70, 1.31), (1.0, 1.31)],
               "2.5": [(0.50, 1.61), (0.60, 1.51), (0.70, 1.40), (1.0, 1.42)]}
SOCCER_LEAGUES = ("EPL", "Serie A", "La Liga", "Bundesliga", "Ligue 1", "Champions League", "Europa League",
                  "MLS", "Liga MX", "UEFA Nations League", "FIFA World Cup", "FIFA Club World Cup")


def soccer_candidates(a):
    """Favourite ML + goals Over + favourite corners Under + underdog corners
    Over, per match, against the unrelated-legs price."""
    out, failed = [], []
    for lg in SOCCER_LEAGUES:
        try:
            items = novig.catalog({"league": lg, "eventStatus": "OPEN_PREGAME",
                                   "marketType": "MONEYLINE_3_WAY_WIN,TOTAL,TEAM_TOTAL_CORNERS"})
        except Exception as e:   # one league not answering shouldn't lose the rest
            failed.append(f"{lg} ({getattr(e, 'code', None) or type(e).__name__})")
            continue
        time.sleep(0.4)   # twelve catalog calls in a row trip the per-IP throttle
        ev = {}
        for m in items:
            o = m["outcomes"]
            if len(o) != 2 or not all(x.get("bid") for x in o):
                continue
            b0, b1 = float(o[0]["bid"]["price"]), float(o[1]["bid"]["price"])
            if not 0 < b0 < 1 - b1 < 1:
                continue
            f0, f1 = sgp.devig_worst(1 - b1, 1 - b0)
            ev.setdefault(m["eventId"], []).append(
                {"type": m["marketType"], "desc": m["description"], "strike": m.get("strike"), "starts": m["startsTs"],
                 "p": (f0, f1), "width": 1 - b1 - b0, "ids": (o[0]["outcomeId"], o[1]["outcomeId"])})
        for eid, ms in ev.items():
            wins = sorted((m for m in ms if m["type"] == "MONEYLINE_3_WAY_WIN" and m["width"] <= 0.08),
                          key=lambda m: -m["p"][0])
            if len(wins) < 2:
                continue
            fav, dog = (m["desc"].replace(" MONEYLINE_3_WAY_WIN", "") for m in wins[:2])

            def corners(team):
                v = [m for m in ms if m["type"] == "TEAM_TOTAL_CORNERS" and m["desc"].startswith(team + " ") and m["width"] <= 0.30]
                return min(v, key=lambda m: abs(m["p"][0] - 0.5) + m["width"]) if v else None
            fc, dc = corners(fav), corners(dog)
            if not fc or not dc:
                continue

            def L(m, i, stat, text):
                return {"stat": stat, "side": "under" if i else "over", "line": float(m["strike"] or 0), "p": m["p"][i],
                        "fair": sgp.american(m["p"][i]), "width": m["width"], "id": m["ids"][i], "text": text}
            base = [L(wins[0], 0, "ml", f"{fav} win"), L(fc, 1, "crn", f"{fav} U{fc['strike']} corners"),
                    L(dc, 0, "crn", f"{dog} O{dc['strike']} corners")]
            shapes = [(None, base)]
            for line in ("1.5", "2.5"):
                t = next((m for m in ms if m["type"] == "TOTAL" and m["strike"] == line and m["width"] <= 0.30), None)
                if t:
                    shapes.append((line, [base[0], L(t, 0, "tot", f"Over {line}")] + base[1:]))
            for goals, legs in shapes:
                unrelated = math.prod(x["p"] for x in legs)
                lift = next(v for top, v in SOCCER_LIFT[goals] if base[0]["p"] <= top)
                out.append({"key": ",".join(x["id"] for x in legs), "tier": 5, "player": f"{fav} v {dog}", "id": eid,
                            "team": lg, "starts": wins[0]["starts"], "legs": legs, "label": " · ".join(x["text"] for x in legs),
                            "r": None, "j": min(unrelated * lift, 0.99), "forced": False, "devig_r": None,
                            "lift": lift, "unrelated_x": 1 / unrelated, "rough": max(x["width"] for x in legs) > novig.MAX_SPREAD + 1e-9})
    if failed and not out:
        raise SystemExit("Novig's catalog didn't answer for " + ", ".join(failed))
    return (out[:a.max] if a.max else out), {}


def candidates(markets, d, by, a):
    """(every 2-leg combo worth a quote, in quoting order; {player id: (player,
    his main-line rows by stat)} for the 3-leg pass)."""
    key = {novig.norm(n): n for n in by}
    t1, lad, dds, rest, ctx = [], [], [], [], {}
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
            if r > 0 and (a.scope != "ladder" or r >= a.ladder_r):
                P, T = main["pts"], main["tpm"]
                threes = [T] + beside([x for x in rows.get("tpm", []) if usable(x, a.alt_spread)], T)
                t1 += [dict(combo(1, r, leg("pts", P, 1), leg("tpm", t, 1)), main=t is T) for t in threes
                       if t is T or a.scope == "all"]
                have = {c["key"] for c in t1}
                if r >= a.ladder_r and a.ladder:
                    for pr in rows["pts"]:
                        dp = pr["line"] - P["line"]
                        for tr in rows["tpm"]:
                            dt = tr["line"] - T["line"]
                            if (not 0 <= dp <= a.ladder_pts or dt not in range(a.ladder_3s + 1) or (dp == 0 and dt == 0)
                                    or "over" not in pr["ids"] or "over" not in tr["ids"]
                                    or 3 * (math.floor(tr["line"]) + 1) > pr["line"]):
                                continue
                            try:
                                la, lb = shifted(p, "pts", pr, P), shifted(p, "tpm", tr, T)
                            except (ValueError, ZeroDivisionError, OverflowError):
                                continue
                            c = combo(6, r, la, lb)
                            if c["key"] in have:
                                continue
                            # The game-log tail correction is off unless asked for: on the
                            # two slips checked against other books (McCain 14+/3+ and
                            # 15+/3+, 11-10) the corrected fair sat right on the books'
                            # own SGP price, i.e. too generous; the plain model sat about
                            # 6% under it, where a fair value should.
                            fix = LADDER_FIX[(min(8, 2 * round(dp / 2)), min(2, int(dt)))] if a.ladder_fix else 1.0
                            # never past what near-perfect dependence would give
                            c.update(j=min(c["j"] * fix, sgp.joint(0.97, la["p"], lb["p"])), model=True, fix=fix, devig_r=None)
                            if a.ladder_fair and not a.ladder_fair[0] <= sgp.american(c["j"]) <= a.ladder_fair[1]:
                                continue   # outside the fair-value band the ladder is kept to
                            lad.append(c)
        if a.tier == 0 and a.dd:
            for x, y in (("pts", "reb"), ("pts", "ast"), ("reb", "ast")):
                rx = next((q for q in rows.get(x, []) if q["line"] == 9.5 and "over" in q["ids"]), None)
                ry = next((q for q in rows.get(y, []) if q["line"] == 9.5 and "over" in q["ids"]), None)
                if not rx or not ry or x not in main or y not in main or min(main[x]["line"], main[y]["line"]) < 5.5:
                    continue
                try:
                    c = combo(7, price.shrunk_r(d, by, p, x, y)[0], shifted(p, x, rx, main[x]), shifted(p, y, ry, main[y]))
                except (ValueError, ZeroDivisionError, OverflowError):
                    continue
                c.update(model=True, dd=True, fix=1.0, devig_r=None)
                dds.append(c)
        # Triple-doubles for the players who threaten one (rebounds and assists
        # main lines both 5.5+): 10+ rebounds, 10+ assists and points at the
        # lowest line listed from 10+, then the next two lines up, no higher
        # than his main line.
        if a.tier == 0 and a.dd and all(k in main for k in ("pts", "reb", "ast")) \
                and min(main["reb"]["line"], main["ast"]["line"]) >= 5.5:
            rr = next((q for q in rows["reb"] if q["line"] == 9.5 and "over" in q["ids"]), None)
            ra = next((q for q in rows["ast"] if q["line"] == 9.5 and "over" in q["ids"]), None)
            pts = [q for q in rows["pts"] if 9.5 <= q["line"] <= max(main["pts"]["line"], 9.5) and "over" in q["ids"]][:3]
            if rr and ra and pts:
                rpr, rpa, rra = (price.shrunk_r(d, by, p, x, y)[0] for x, y in (("pts", "reb"), ("pts", "ast"), ("reb", "ast")))
                for pq in pts:
                    try:
                        legs = [shifted(p, "pts", pq, main["pts"]), shifted(p, "reb", rr, main["reb"]), shifted(p, "ast", ra, main["ast"])]
                        j = price.tri_joint([L["p"] for L in legs], [[1, rpr, rpa], [rpr, 1, rra], [rpa, rra, 1]])
                    except (ValueError, ZeroDivisionError, OverflowError):
                        continue
                    dds.append({"key": ",".join(L["id"] for L in legs), "tier": 8, "player": p["name"], "id": p["athlete_id"],
                                "team": p.get("team_abbr") or "", "starts": starts, "legs": legs,
                                "label": " · ".join(leg_text(L) for L in legs), "r": min(rpr, rpa, rra), "j": j,
                                "forced": False, "devig_r": None, "model": True, "td": True, "fix": 1.0,
                                "rough": max(L["width"] for L in legs) > novig.MAX_SPREAD + 1e-9})
        if a.tier == 1:
            continue
        for x, y in PAIRS:
            if x not in main or y not in main:
                continue
            r = price.shrunk_r(d, by, p, x, y)[0]
            # Max's cuts (11-10): no Points + Assists or Rebounds + Assists,
            # and Points + Rebounds only for big men. None has paid in any test.
            if (x, y) in (("pts", "ast"), ("reb", "ast")) or ((x, y) == ("pts", "reb") and not big(p)):
                continue
            if r >= a.min_r and a.tier in (0, 2):
                rest.append(combo(2, r, leg(x, main[x], 1), leg(y, main[y], 1)))
    if a.scope == "ladder":
        # The Ladder board is the higher lines only: the main-line slips are
        # the NBA board's, and asking them here doubled those auctions.
        t1 = []
    t1.sort(key=lambda c: -c["r"])
    # Most lift over independent legs first: that's where a price can be off.
    rest.sort(key=lambda c: -c["j"] / (c["legs"][0]["p"] * c["legs"][1]["p"]))
    lad.sort(key=lambda c: -c["r"])
    dds.sort(key=lambda c: -c["j"])
    seen = {c["key"] for c in t1 + lad + rest}
    out = t1 + lad + rest + [c for c in dds if c["key"] not in seen]
    return (out[:a.max] if a.max else out), ctx


def triples(rows, ctx, stats, rfun, a):
    """Three-leg combos: the best two-leg Over + Over rows, each with one more
    stat's main-line Over. rfun(player, stat, stat) is the pair's r (or None)."""
    base = sorted((c for c in rows if len(c["legs"]) == 2 and not c.get("model") and not c.get("kind") and all(L["side"] == "over" for L in c["legs"])
                   and c["ev"] * 100 >= a.tri_min_ev), key=lambda c: -c["ev"])[:a.tri]
    out, seen = [], set()
    for c in base:
        p, main, starts = ctx[c["id"]]
        la, lb = c["legs"]
        for s in stats:
            if s in (la["stat"], lb["stat"]) or s not in main:
                continue
            lc = leg(s, main[s], 1)
            ids = frozenset((la["id"], lb["id"], lc["id"]))
            if ids in seen:   # the same three legs, reached from another pair
                continue
            seen.add(ids)
            rac, rbc = (rfun(p, L["stat"], s) for L in (la, lb))
            if rac is None or rbc is None or min(rac, rbc) < 0:
                continue
            # Forced points (see candidates): the parlay is threes + the new leg.
            j = (sgp.joint(rbc, lb["p"], lc["p"]) if c["forced"] else
                 price.tri_joint([la["p"], lb["p"], lc["p"]], [[1, c["r"], rac], [c["r"], 1, rbc], [rac, rbc, 1]]))
            out.append({"key": f"{c['key']},{lc['id']}", "tier": 4, "player": c["player"], "id": c["id"], "team": c["team"],
                        "starts": starts, "legs": [la, lb, lc], "label": f"{c['label']} · {leg_text(lc)}",
                        "r": min(c["r"], rac, rbc), "j": j, "forced": c["forced"], "devig_r": None,
                        "rough": c["rough"] or lc["width"] > novig.MAX_SPREAD + 1e-9})
    return out


# Max's big-stat players (11-12): their three-leg slips are always asked, at
# main lines, whatever their two-leg price. --star-pts adds anyone whose points
# main line is that high, so the list needn't name every star.
STARS = ("Luka Doncic", "Stephen Curry", "Victor Wembanyama", "Shai Gilgeous-Alexander", "Ty Jerome",
         "Jayson Tatum", "Nikola Jokic")


def star_triples(ctx, rfun, a):
    """Every three-stat Over slip at main lines (points, rebounds, assists,
    threes: up to four a player) for the STARS and the --star-pts scorers."""
    names = {novig.norm(n) for n in STARS}
    out = []
    for p, main, starts in ctx.values():
        pts = main.get("pts")
        if novig.norm(p["name"]) not in names and not (pts and a.star_pts and pts["line"] >= a.star_pts):
            continue
        for trio in itertools.combinations([s for s in STATS if s in main], 3):
            legs = [leg(s, main[s], 1) for s in trio]
            rs = [rfun(p, x, y) for x, y in ((trio[0], trio[1]), (trio[0], trio[2]), (trio[1], trio[2]))]
            if any(r is None for r in rs):
                continue
            # k threes are 3k points: when the threes leg alone clears the
            # points line the slip is just the other two legs.
            forced = "pts" in trio and "tpm" in trio and 3 * (math.floor(main["tpm"]["line"]) + 1) > main["pts"]["line"]
            try:
                if forced:
                    rest = [L for L in legs if L["stat"] != "pts"]
                    j = sgp.joint(rfun(p, rest[0]["stat"], rest[1]["stat"]), rest[0]["p"], rest[1]["p"])
                else:
                    j = price.tri_joint([L["p"] for L in legs], [[1, rs[0], rs[1]], [rs[0], 1, rs[2]], [rs[1], rs[2], 1]])
            except (ValueError, ZeroDivisionError, OverflowError):
                continue
            if not 0 < j < 1:
                continue
            out.append({"key": ",".join(L["id"] for L in legs), "tier": 4, "player": p["name"], "id": p["athlete_id"],
                        "team": p.get("team_abbr") or "", "starts": starts, "legs": legs,
                        "label": " · ".join(leg_text(L) for L in legs), "r": min(rs), "j": j, "forced": forced,
                        "devig_r": None, "star": True,
                        "rough": max(L["width"] for L in legs) > novig.MAX_SPREAD + 1e-9})
    out.sort(key=lambda c: -c["j"])
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
    if a.league == "soccer":
        d = {"generated_at": time.strftime("%Y-%m-%d")}
        cands, ctx = soccer_candidates(a)
        stats, rfun, a.tri = (), None, 0
    elif a.league == "nfl":
        d = json.load(open(NFL_DATA))
        cands, ctx = [], {}
        if a.scope == "ladder":
            cands, ctx = nfl_ladder_candidates(novig.fetch("NFL", NFL_STATS), {p["name"]: p for p in d["players"]}, a)
            a.kind = "ladder"
        if a.kind in ("all", "props"):
            cands, ctx = nfl_candidates(novig.fetch("NFL", NFL_STATS), {p["name"]: p for p in d["players"]}, a)
        if a.kind in ("all", "stacks"):
            cands = cands + nflx_candidates(a, False)
        if a.kind in ("all", "lines"):
            cands = cands + nflx_candidates(a, True)
        stats, rfun = NFL_STATS, nfl_r
    else:
        d, by = sgp.load()
        cands, ctx = candidates(novig.fetch(), d, by, a)
        stats, rfun = STATS, lambda p, x, y: price.shrunk_r(d, by, p, x, y)[0]
    # Everything else waits for the main-line Points + Threes quotes: a player
    # whose best one isn't above --gate (0%: above fair) gets nothing more
    # asked, no higher lines, other pairs, double-doubles or three-leg slips.
    # Every big play on the 11-10 boards came from a player whose main line
    # was already good, and each quote is an auction sent to every pricer.
    # A player with no Points + Threes price at all (a big with no threes
    # line) has no signal either way, so his few combos are still asked.
    ladder = [c for c in cands if c["tier"] == 6]
    cands = [c for c in cands if c["tier"] != 6]
    emit({"type": "start", "total": len(cands), "players": len({c["id"] for c in cands}),
          "league": a.league, "data": d["generated_at"][:10], "at": t0})
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
        first = [c for c in cands if c["tier"] == 1]
        list(pool.map(one, first))
        best, asked = {}, {c["id"] for c in first}
        for c in list(rows):
            best[c["id"]] = max(best.get(c["id"], -9.0), c["ev"])

        def go(c):
            return c["id"] not in asked or best.get(c["id"], -9.0) * 100 > a.gate
        rest = [c for c in cands if c["tier"] != 1]
        if first:   # leagues with no Points + Threes tier are not gated
            up, kept = [c for c in ladder if go(c)], [c for c in rest if go(c)]
            emit({"type": "more", "add": len(up) + len(kept) - len(rest)})
        else:
            up, kept = ladder, rest
            if up:
                emit({"type": "more", "add": len(up), "players": len({c["id"] for c in up + kept})})
        list(pool.map(one, up + kept))
        cands = first + up + kept
        if a.league == "nba" and a.scope != "ladder" and a.stars:
            asked_keys = {c["key"] for c in cands}
            more = [c for c in star_triples(ctx, rfun, a) if c["key"] not in asked_keys]
            if more:
                emit({"type": "more", "add": len(more)})
                cands = cands + more
                list(pool.map(one, more))
        if a.tri and a.tier in (0, 4):
            more = triples([c for c in rows if go(c)], ctx, stats, rfun, a)
            emit({"type": "more", "add": len(more)})
            cands = cands + more
            list(pool.map(one, more))
    emit({"type": "done", "quoted": len(cands), "priced": len(rows), "seconds": time.time() - t0, "at": time.time()})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="nba", choices=("nba", "nfl", "soccer"))
    ap.add_argument("--kind", default="all", choices=("all", "props", "stacks", "lines"),
                    help="NFL: one kind of slip only (default: a player's own props, then stacks, then game lines)")
    ap.add_argument("--per", type=int, default=3, help="NFL stacks / lines: combos asked per player of each kind, highest r first")
    ap.add_argument("--line-r", type=float, default=0.25, help="NFL lines: smallest |r| between a prop and a game line")
    ap.add_argument("--scope", default="main", choices=("main", "ladder", "all"),
                    help="main (default): NBA asks one slip a player, his main-line Points + Threes, and NFL asks no "
                         "three-leg slips. all: also the second threes milestone, higher lines, other pairs, "
                         "double- and triple-doubles and three legs. ladder (NBA): the shooters at --ladder-r or better, "
                         "every higher points line Novig lists (to main + 15, "
                         "one-way lines included) with threes at main to + 3, inside --ladder-fair (the main-line slips are the NBA board's). "
                         "ladder (NFL): each player's yards lines above his main line with anytime TD, receptions or "
                         "passing TDs at its main line")
    ap.add_argument("--tier", type=int, default=0, choices=(0, 1, 2, 3), help="one two-leg group only (default: all, then three legs)")
    ap.add_argument("--tri", type=int, default=12, help="two-leg rows to extend to three legs (0 = none)")
    ap.add_argument("--tri-min-ev", type=float, default=-6.0, help="only extend two-leg rows at this EV%% or better")
    ap.add_argument("--max", type=int, default=0, help="quote at most this many combos (default: all)")
    ap.add_argument("--ladder-r", type=float, default=0.70, help="smallest PTS-3PM r for the higher-line combos")
    ap.add_argument("--ladder-pts", type=int, default=None, help="highest points line on the ladder, above main (10; ladder scope 15)")
    ap.add_argument("--ladder-3s", type=int, default=None, help="highest threes line on the ladder, above main (2; ladder scope 3)")
    ap.add_argument("--ladder-fair", type=float, nargs=2, default=None, metavar=("LOW", "HIGH"),
                    help="ask only ladder slips whose fair value is in this American-odds band "
                         "(ladder scope: 500 800; '0 0' = every slip)")
    ap.add_argument("--gate", type=float, default=None,
                    help="ask a player's other combos only if his best main-line PTS+3PM EV%% is above this (-100 = everyone)")
    ap.add_argument("--no-books", action="store_true",
                    help="don't cap shifted legs at DK's and FanDuel's one-way prices")
    ap.add_argument("--no-stars", dest="stars", action="store_false",
                    help="NBA: skip the three-leg main-line slips always asked for the STARS list")
    ap.add_argument("--star-pts", type=float, default=26.5,
                    help="NBA: also ask those three-leg slips for anyone whose points main line is this high (0 = the list only)")
    ap.add_argument("--ladder-fix", action="store_true", help="scale higher-line joints by LADDER_FIX (off: plain model)")
    ap.add_argument("--no-dd", dest="dd", action="store_false", help="skip the build-your-own double-doubles")
    ap.add_argument("--no-ladder", dest="ladder", action="store_false", help="skip the higher-line combos")
    ap.add_argument("--min-r", type=float, default=0.15, help="smallest r for an Over + Over on the other pairs")
    ap.add_argument("--max-spread", type=float, default=novig.MAX_SPREAD, help="widest Novig book for a leg (prob)")
    ap.add_argument("--alt-spread", type=float, default=0.08, help="widest book for the second threes milestone")
    ap.add_argument("--workers", type=int, default=3, help="quotes in flight at once")
    ap.add_argument("--unit", type=float, default=250.0, help="dollars per unit, 1u = 1%% of bankroll")
    ap.add_argument("--kelly", type=float, default=0.25, help="Kelly fraction (default quarter)")
    ap.add_argument("--min-ev", type=float, default=None, help="print only rows at this EV%% or better")
    ap.add_argument("--top", type=int, default=25, help="rows to print (default 25; 0 = all)")
    ap.add_argument("--json", action="store_true", help="stream events as JSON lines instead of a table")
    a = ap.parse_args()
    BOOKS["on"] = not a.no_books
    if a.gate is None:
        # Ladder scope asks down to a main line 10% under fair: on the ungated
        # pass of 11-11, players at -10% to 0% held 46 of the 81 ladder slips
        # at +10% or better; those under -10% held 4 (of 74 asked).
        a.gate = -10.0 if a.scope == "ladder" else 0.0
    if a.ladder_fair is None and a.scope == "ladder":
        # Max, 11-11: the +2000 fairs are modelled too far from the main line
        # to trust. Keep the ladder to slips around +500 to +800.
        a.ladder_fair = [500.0, 800.0]
    if a.ladder_fair and not any(a.ladder_fair):
        a.ladder_fair = None
    if a.ladder_pts is None:
        a.ladder_pts = 15 if a.scope == "ladder" else 10
    if a.ladder_3s is None:
        a.ladder_3s = 3 if a.scope == "ladder" else 2
    if a.scope == "ladder":
        if a.league == "soccer":
            raise SystemExit("--scope ladder is NBA and NFL only")
        a.tri, a.dd, a.ladder = 0, False, True
        if a.league == "nba":
            a.tier = 1
    if a.scope == "main":
        # Max, 11-10: every quote is an auction the pricers see, and plays were
        # being repriced while the wider scans ran. One ask per player.
        a.tri, a.ladder, a.dd = 0, False, False
        if a.league == "nba":
            a.tier = 1

    if a.json:
        out = threading.Lock()

        def emit(e):
            with out:
                print(json.dumps(e), flush=True)
        scan(a, emit)
        return

    def emit(e):
        if e["type"] == "more" and e["add"]:
            print(f"+ {e['add']} more combos", file=sys.stderr)
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
        rtxt = "unrel." if c["r"] is None else f"{c['r']:+.2f}"
        print(f"| {c['player']} {c['team']} | {c['label']}{' *' if c.get('model') else ''}{' ~' if c['rough'] else ''} | {legs} | {rtxt} | "
              f"{c['fair']:+d} | {c['slip_x']:.2f}x | {c['ev']:+.1%} | {c['qk']:.2f}u | ${c['wager']:,.0f} |")
    if any(c.get("model") for c in shown):
        print("* a higher line: fair value modelled from the main line, not read off a book")
    if any(c["rough"] for c in shown):
        print("~ a leg sits on a Novig book wider than 4c: rough fair value")


if __name__ == "__main__":
    main()
