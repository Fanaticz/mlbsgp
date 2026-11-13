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
  python3 scan.py --league nfl    # NFL: a player's own props, QB + receiver stacks, props + game lines, three legs
  python3 scan.py --league nfl --kind stacks   # one kind only: props, stacks, lines or tri
  python3 scan.py --league nfl --kind tri      # NFL three-leg slips alone
  python3 scan.py --league nhl    # NHL: a skater's goals, assists, points and shots on goal, every pair
  python3 scan.py --league cfb    # college football: slips across a game's own lines
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
receptions, passing yards + anytime TD. Lines: a player's prop Over with a game line, on whichever
side goes with it (RB rushing yards + his team covering; QB pass attempts +
the other team covering), where |r| is at least --line-r. The game lines are
the total, his team's spread, moneyline and team total, and the first
half's total, spread and moneyline. Both use league-wide r's by role
(position and targets or carries a game) from
public/data/nfl_stack_correlations.json, ten seasons of nflverse. A stack
gets his --per highest-r combos; lines get his best prop with each kind of
line, and his --per highest over the total, spread and team total.
The moneyline's r is measured within games of the same closing spread and
comes out as the spread's (winning and covering are one margin); first-half
r's run about three quarters of the full game's for scoring props and about
the same for a back's carries and yards.

NFL three legs (the same pass; --kind tri for these alone): every leg at its main line, all
three pulling the same way. Three of a player's own props; two of them with
a game line; a QB's passing Over, his receiver's Over and a game line; a QB
leg with two of the receiver's, or two QB legs with one. The joint is the
three-leg Gaussian copula on the three pair r's (the player's own for his
two props, role r's across players and with lines). Each player leads his
--per (3) best by lift, at most two of a shape and one of each line kind.

NHL (--league nhl): skaters in public/data/nhl_correlations.json (40+ games
of 10+ minutes; scripts/nhl_fetch_correlations.py, history from
MoneyPuck.com). Yes + Yes on goals + shots on goal, each at its main line
(--scope all: every tight line). Novig refuses any slip with a skater's points and another of his
stats ("Invalid parlay combination", 11-12), so points pairs are not asked
unless --nhl-points; it lists no blocked-shots market. A pair where one leg
forces the other is moved up a line or dropped: 1+ goal is 1+ shot on goal,
so goals go with 2+ shots. The r is the copula correlation of the two legs'
hit / miss indicators at those exact lines, shrunk toward the skater's
position. Goals + shots runs 0.3 to 0.6. Goals + assists and assists +
shots on goal are about zero, under --min-r (NHL: 0.10), so they are not
asked (Max, 11-12); --min-r -1 asks them. Stakes at $500 a unit.

The same NHL pass then asks teammates (--kind mates for these alone): one
skater's leg with a teammate's in the same game, Yes + Yes at main lines,
from public/data/nhl_teammate_correlations.json (the games both played 10+
minutes for the same team). Points + points, a goal + the other's points,
shots on goal + the other's points or shots, wherever r is at least
--mate-r (0.20), at most --per (3) slips led by one skater. Two teammates'
points run 0.15 on average and 0.3 to 0.4 for linemates, and a goal with a
linemate's assist the same; a skater's shots with a teammate's points or
shots is about 0 (0.05 for linemates), so those fall under the cut.

Its own pass (--kind lines, the NHL Lines board): a skater's points with a game line, on the side that
goes with it: his team's moneyline, the puck line, the game total or his
team's total, from public/data/nhl_line_correlations.json (league-wide by
position and ice time; scores from ESPN). Where |r| is at least --line-r,
his --per (4) highest. A top forward's point runs 0.5 with his team's total,
0.38 with a win, 0.32 with the game over. --line-stats adds goal, assists
or shots legs.

Soccer (--league soccer): for every open match with team-corners books it
asks Max's shape, favourite to win (3-way) + favourite's corners Under +
underdog's corners Over, alone and with goals Over 1.5 or Over 2.5. A
leading favourite sits back and the underdog chases, so the legs hit
together more often than unrelated legs would. Each leg's fair value is
Pinnacle's no-vig price on that line (pinnacle.py), or the middle of
Novig's own book where Pinnacle has no such line (marked ~ when that book
is wide: corner books often are). Fair value = the legs'
product times SOCCER_LIFT, measured on 17,934 top-five-league matches
(2015-16 on, football-data.co.uk: results, corners, closing odds) with
corner lines nearest 50/50: x1.25 to x1.33 with no goals leg, x1.31 to
x1.38 with Over 1.5, x1.40 to x1.61 with Over 2.5, larger for weaker
favourites. League averages, not match-specific: rows are leads.

College football (--league cfb): Novig lists no player props for NCAAF, only
game lines, so the slips are across a game's own lines: the underdog's
moneyline + the game Under (main line, and the Under nearest +230), those two
with the underdog's team total Over, the favourite's spread + Over and the
underdog's spread + Under. Five asks a game at most. The correlation comes
from a two-score model fitted to that game's own ladders: the margin's and
the total's spread (sd) from Novig's alt spreads and alt totals, the two
teams' scores tied by what those two sds imply, and the margin tied to the
total by CFB_KAPPA x spread / total (an assumption, not measured on college
results; Novig's own quotes imply about the same). On 182 quotes over four
games (11-13) Novig priced these within a point or two of that model, so
after the fee nearly every row is under fair: rows are leads.

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
         "car": "CAR", "ryds": "RUSH YDS", "rry": "RUSH+REC YDS",
         "g": "G", "sog": "SOG", "blk": "BLK"}
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


NHL_STATS = ("g", "ast", "pts", "sog", "blk")
NHL_PAIRS = [(x, y) for i, x in enumerate(NHL_STATS) for y in NHL_STATS[i + 1:]]
NHL_PART_OF = {"g": ("pts", "sog"), "ast": ("pts",)}   # n goals are n points and n shots on goal
NHL_DATA = os.path.join(HERE, "..", "..", "..", "public", "data", "nhl_correlations.json")


def nhl_nested(x, lx, y, ly):
    """One leg forces the other: n+ goals with n+ (or fewer) points or shots."""
    return (y in NHL_PART_OF.get(x, ()) and ly <= lx) or (x in NHL_PART_OF.get(y, ()) and lx <= ly)


# Novig's spelling -> the data's (ESPN's), where no rule finds it.
NHL_ALIAS = {"nicholaspaul": "nickpaul", "timstuetzle": "timstutzle", "yurovdanila": "danilayurov",
             "yegorchinakhov": "egorchinakhov"}


def nhl_find(d):
    """A lookup from Novig's name to the one skater it means, or None: the
    full name, else the same surname with one first name a short form of the
    other ("Alex Wennberg" for "Alexander Wennberg"; "Andre Lee" is not
    "Anders Lee")."""
    by, last = {}, {}
    for p in d["players"]:
        by.setdefault(novig.norm(p["name"]), []).append(p)
        w = p["name"].split()
        last.setdefault(novig.norm(w[-1]), []).append((novig.norm(w[0]), p))

    def find(name):
        key = novig.norm(name)
        hits = by.get(NHL_ALIAS.get(key, key))
        if not hits:
            w = name.split()
            first = novig.norm(w[0])
            hits = [p for f, p in last.get(novig.norm(w[-1]), []) if len(w) > 1 and min(len(f), len(first)) >= 3
                    and (f.startswith(first) or first.startswith(f))]
        return hits[0] if len(hits) == 1 else None
    return find


def nhl_r(d, p, x, lx, y, ly):
    """(r, games behind it) for the pair at these exact lines: the skater's
    shrunk r, or his position's average when a leg is one he almost never or
    almost always hits. (None, 0) when the data has neither."""
    k = f"{lx}|{ly}"
    own = (p["pairs"].get(f"{x}_{y}") or {}).get(k)
    if own:
        return own[0], p["n_games"]
    prior = ((d["shrinkage"]["priors"].get(p["grp"]) or {}).get(f"{x}_{y}") or {}).get(k)
    return (prior["r"], 0) if prior else (None, 0)


def nhl_candidates(markets, d, a):
    """NHL: Yes + Yes on every pair of a skater's goals, assists, shots on goal
    and blocked shots (points too with --nhl-points: Novig refuses those) with
    r at least --min-r, each stat at its main line (--scope all: every tight
    line), nested pairs moved up or left out. Most lift over independent legs
    first."""
    find = nhl_find(d)
    out, ctx = [], {}
    for nm in sorted({novig.player_name(m) for m in markets}):
        p = find(nm)
        if not p:   # not in the data (under 40 games), or two skaters of that name
            continue
        _, rows = novig.ladder(markets, nm)
        tight = {s: [r for r in rows.get(s, []) if usable(r, a.max_spread)] for s in NHL_STATS}
        main = {s: main_line(v) for s, v in tight.items() if v}
        starts = min((r["starts"] for v in rows.values() for r in v), default=None)
        ctx[p["athlete_id"]] = (p, main, starts)
        for x, y in NHL_PAIRS:
            if x not in main or y not in main or ("pts" in (x, y) and not a.nhl_points):
                continue
            if a.scope == "all":
                picks = [(rx, ry) for rx in tight[x] for ry in tight[y] if not nhl_nested(x, rx["line"], y, ry["line"])]
            else:
                rx, ry = main[x], main[y]
                if nhl_nested(x, rx["line"], y, ry["line"]):
                    # Move the stat that contains the other up to its first line that isn't forced.
                    if y in NHL_PART_OF.get(x, ()):
                        ry = next((r for r in tight[y] if r["line"] > rx["line"]), None)
                    else:
                        rx = next((r for r in tight[x] if r["line"] > ry["line"]), None)
                picks = [(rx, ry)] if rx and ry else []
            for rx, ry in picks:
                r, n = nhl_r(d, p, x, rx["line"], y, ry["line"])
                if r is None or r < a.min_r:
                    continue
                la, lb = leg(x, rx, 1), leg(y, ry, 1)
                j = sgp.joint(r, la["p"], lb["p"])
                out.append({"key": f"{la['id']},{lb['id']}", "tier": 2, "player": p["name"], "id": p["athlete_id"],
                            "team": p.get("team_abbr") or "", "starts": starts, "legs": [la, lb],
                            "label": f"{leg_text(la)} · {leg_text(lb)}", "r": r, "j": j, "forced": False,
                            "devig_r": sgp.devig_r(j, la["p"], lb["p"]), "games": n,
                            "rough": max(la["width"], lb["width"]) > novig.MAX_SPREAD + 1e-9})
    out.sort(key=lambda c: -c["j"] / (c["legs"][0]["p"] * c["legs"][1]["p"]))
    return (out[:a.max] if a.max else out), ctx


NHL_MATES = os.path.join(HERE, "..", "..", "..", "public", "data", "nhl_teammate_correlations.json")
# (skater A's stat, teammate B's stat). Points + points once per pair; the rest both ways round.
NHL_MATE_KINDS = (("pts", "pts"), ("g", "pts"), ("g", "ast"), ("ast", "ast"), ("sog", "pts"), ("sog", "ast"), ("sog", "sog"))
NHL_LINES = os.path.join(HERE, "..", "..", "..", "public", "data", "nhl_line_correlations.json")
NHL_TEAM = {"LAK": "LA", "NJD": "NJ", "SJS": "SJ", "TBL": "TB", "UTAH": "UTA"}   # Novig's code -> the data's


def nhl_line_candidates(markets, d, a):
    """NHL: a skater's leg (points, goal, assists, shots on goal at its main
    line) with a game line, on the side that goes with it: his team's
    moneyline, the puck line (-1.5 or +1.5, whichever his team has), the game
    total, his team's total. League-wide r by position and ice time
    (nhl_line_correlations.json), wherever |r| is at least --line-r; each
    skater gets his --per highest."""
    T = json.load(open(NHL_LINES))
    full = {novig.norm(v): k for k, v in T["teams"].items()}
    find = nhl_find(d)
    items = novig.catalog({"league": "NHL", "eventStatus": "OPEN_PREGAME", "marketType": "MONEY,SPREAD,TOTAL,TEAM_TOTAL"})
    events = {}
    for m in items:
        ev = events.setdefault(m["eventId"], {"teams": None, "lines": {}})
        if m["marketType"] == "TOTAL" and " @ " in m["description"]:
            ev["teams"] = tuple(NHL_TEAM.get(t, t) for t in m["description"].rsplit(" t", 1)[0].split(" @ "))
        t = two_way(m)
        if t and t["spread"] <= a.max_spread + 1e-9:
            ev["lines"].setdefault(m["marketType"], []).append(t)

    def role(p, stat, line, ev, strike):
        for e in T["game"]:
            if (e["grp"] == p["grp"] and e["stat"] == stat and e["line"] == line and e["ev"] == ev and e["strike"] == strike
                    and e["min"] <= p["toi_mean"] and (e["max"] is None or p["toi_mean"] < e["max"])):
                return e["r"]
        return None

    def code(name):   # "TBL -1.5" -> ("TB", "-1.5")
        w = name.split()
        return NHL_TEAM.get(w[0], w[0]), (w[1] if len(w) > 1 else "")

    out = []
    for nm in sorted({novig.player_name(m) for m in markets}):
        p = find(nm)
        if not p:
            continue
        eid = next(m["eventId"] for m in markets if novig.player_name(m) == nm)
        ev = events.get(eid) or {}
        team = p.get("team_abbr")
        if not ev.get("teams") or team not in ev["teams"]:
            continue
        opp = next(t for t in ev["teams"] if t != team)
        _, rows = novig.ladder(markets, nm)
        main = {s: main_line(v) for s in ("pts", "g", "ast", "sog")
                for v in [[r for r in rows.get(s, []) if usable(r, a.max_spread) and (s != "g" or r["line"] == 0.5)]] if v}
        starts = min(r["starts"] for v in rows.values() for r in v)
        # (kind, the event in the data, its strike, market, index of the side that is the event, text for each side)
        offers = []
        for m in ev["lines"].get("MONEY", []):
            i = next((i for i, n in enumerate(m["names"]) if code(n)[0] == team), None)
            if i is not None:
                offers.append(("win", "win", None, m, i, (f"{team} ML", f"{opp} ML")))
        for m in ev["lines"].get("SPREAD", []):
            if abs(m["strike"]) != 1.5:
                continue
            i = next((i for i, n in enumerate(m["names"]) if code(n)[0] == team), None)
            if i is not None:
                sign = code(m["names"][i])[1]
                offers.append(("cover", "m15" if sign.startswith("-") else "p15", None, m, i,
                               (f"{team} {sign}", f"{opp} {code(m['names'][1 - i])[1]}")))
        tot = ev["lines"].get("TOTAL", [])
        if tot:
            m = min(tot, key=lambda m: (abs(m["p"][0] - 0.5) + m["spread"], -m["volume"]))
            what = " @ ".join(ev["teams"])
            offers.append(("over", "over", m["strike"], m, 0, (f"{what} Over {m['strike']:g}", f"{what} Under {m['strike']:g}")))
        tt = [m for m in ev["lines"].get("TEAM_TOTAL", []) if full.get(novig.norm(m["desc"].rsplit(" ", 2)[0])) == team]
        if tt:
            m = min(tt, key=lambda m: (abs(m["p"][0] - 0.5) + m["spread"], -m["volume"]))
            offers.append(("tt", "tt", m["strike"], m, 0, (f"{team} team total Over {m['strike']:g}",
                                                           f"{team} team total Under {m['strike']:g}")))
        mine = []
        for s in main:
            if s not in a.line_stats:
                continue
            for kind, evn, strike, m, i, texts in offers:
                r = role(p, s, main[s]["line"], evn, strike)
                if r is None or abs(r) < a.line_r:
                    continue
                i, text = (i, texts[0]) if r > 0 else (1 - i, texts[1])   # the other side when they move apart
                la = leg(s, main[s], 1)
                la["text"] = leg_text(la)
                lb = {"stat": evn, "side": "over" if i == 0 else "under", "line": m["strike"], "p": m["p"][i],
                      "fair": sgp.american(m["p"][i]), "width": m["spread"], "id": m["ids"][i], "text": text}
                j = sgp.joint(abs(r), la["p"], lb["p"])
                mine.append({"key": f"{la['id']},{lb['id']}", "tier": 2, "player": p["name"], "id": p["athlete_id"],
                             "team": team, "starts": starts, "legs": [la, lb], "kind": kind,
                             "label": f"{la['text']} · {text}", "r": abs(r), "j": j, "forced": False,
                             "devig_r": sgp.devig_r(j, la["p"], lb["p"]), "games": 0, "role": True,
                             "rough": max(la["width"], lb["width"]) > novig.MAX_SPREAD + 1e-9})
        out += sorted(mine, key=lambda c: -c["r"])[:a.per]
    out.sort(key=lambda c: -c["j"] / (c["legs"][0]["p"] * c["legs"][1]["p"]))
    return out[:a.max] if a.max else out


def nhl_mate_r(M, a, b, x, lx, y, ly):
    """(r, games together) for A's leg with teammate B's: the pair's own
    shrunk r when they have 40+ games together, else the average for their
    positions at the lower of their ice times. (None, 0) with neither."""
    kind, lines = f"{x}_{y}", f"{lx}|{ly}"
    pair = M["pairs"].get(f"{a['key']}>{b['key']}") or {}
    own = (pair.get(kind) or {}).get(lines)
    if own:
        return own[0], pair["n"]
    prior = ((M["priors"]["values"].get(a["grp"] + b["grp"]) or {}).get(kind) or {}).get(lines)
    return (price.interp(prior["knots"], min(a["toi_mean"], b["toi_mean"])), 0) if prior else (None, 0)


def nhl_mate_candidates(markets, d, a):
    """NHL teammates: one skater's leg with a teammate's, Yes + Yes at main
    lines: points + points, a goal + the other's points, shots on goal + the
    other's points or shots, wherever r is at least --mate-r. Linemates'
    points run 0.3 to 0.4; a skater's shots say nothing about a teammate's
    points (r about 0), so the shots slips fall under the cut. Each skater
    leads at most --per slips, highest r first."""
    M = json.load(open(NHL_MATES))
    find = nhl_find(d)
    sides = {}   # (event, team) -> [(skater, main lines, starts)]
    for nm in sorted({novig.player_name(m) for m in markets}):
        p = find(nm)
        if not p:
            continue
        _, rows = novig.ladder(markets, nm)
        main = {s: main_line(v) for s in ("pts", "g", "ast", "sog")
                for v in [[r for r in rows.get(s, []) if usable(r, a.max_spread) and (s != "g" or r["line"] == 0.5)]] if v}
        if not main:
            continue
        eid = next(m["eventId"] for m in markets if novig.player_name(m) == nm)
        starts = min(r["starts"] for v in rows.values() for r in v)
        sides.setdefault((eid, p.get("team_abbr")), []).append((p, main, starts))
    out = []
    for group in sides.values():
        for i, (pa, ma, starts) in enumerate(group):
            mine = []
            for k, (pb, mb, _) in enumerate(group):
                if k == i:
                    continue
                for x, y in NHL_MATE_KINDS:
                    if x not in ma or y not in mb or (x == y and k < i):
                        continue
                    r, n = nhl_mate_r(M, pa, pb, x, ma[x]["line"], y, mb[y]["line"])
                    if r is None or r < a.mate_r:
                        continue
                    la, lb = leg(x, ma[x], 1), leg(y, mb[y], 1)
                    la["text"], lb["text"] = leg_text(la), f"{pb['name'].split()[-1]} {leg_text(lb)}"
                    j = sgp.joint(r, la["p"], lb["p"])
                    mine.append({"key": f"{la['id']},{lb['id']}", "tier": 2, "player": f"{pa['name']} + {pb['name']}",
                                 "id": pa["athlete_id"], "team": pa.get("team_abbr") or "", "starts": starts,
                                 "legs": [la, lb], "kind": "mate", "label": f"{la['text']} · {lb['text']}",
                                 "r": r, "j": j, "forced": False, "devig_r": sgp.devig_r(j, la["p"], lb["p"]),
                                 "games": n, "rough": max(la["width"], lb["width"]) > novig.MAX_SPREAD + 1e-9})
            out += sorted(mine, key=lambda c: -c["r"])[:a.per]
    out.sort(key=lambda c: -c["r"])
    return out[:a.max] if a.max else out


# actual / modelled hit rate of both legs, by (points above main rounded to 2, threes above main):
# 128 rotation shooters, lines relative to each player's own average (ladder backtest, 11-10).
LADDER_FIX = {(0, 0): 1.00, (0, 1): 1.06, (0, 2): 1.13, (2, 0): 1.00, (2, 1): 1.05, (2, 2): 1.16,
              (4, 0): 1.04, (4, 1): 1.09, (4, 2): 1.20, (6, 0): 1.08, (6, 1): 1.12, (6, 2): 1.23,
              (8, 0): 1.18, (8, 1): 1.20, (8, 2): 1.28}


BOOKS = {"on": True, "ladders": None, "check": None, "seen": None}   # pulled once, on the first shifted leg


def shifted(p, stat, row, main):
    """A leg at `row`'s line with its fair value shifted from the main line's."""
    book_text = ""
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
        cap, _, book_text = BOOKS["check"](BOOKS["ladders"], p["name"], stat, row["line"])
        if cap is not None:
            po = min(po, cap)
    out = {"stat": stat, "side": "over", "line": row["line"], "p": po, "fair": sgp.american(po),
           "width": main["spread"], "id": row["ids"]["over"], "from": None if row is main else main["line"]}
    if book_text:
        out["books"] = book_text   # shown in the open row: "DK +552 · FD +600"
    return out


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
        cvs = {}
        for y, z in NFL_LADDER:
            r = nfl_r(p, y, z)
            if r is None or r < a.min_r or z not in main or not rows.get(y):
                continue
            if y not in cvs:   # his own spread, from the book's ladder for him
                fl = lad and books.fair_ladder(lad, nm, y)
                cvs[y] = fl and nfl_shift.fit_cv(y, *fl)
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
                # DK's / FanDuel's one-way price on this line, least margin out,
                # is a ceiling whatever Novig's own book says.
                cap, _, book_text = books.check(lad, nm, y, row["line"]) if lad else (None, None, "")
                if usable(row, a.max_spread):
                    po, frm, width = min(row["fo"], cap or 1), None, row["spread"]
                else:
                    try:
                        po = nfl_shift.over(y, m_line, m_p, row["line"], cvs[y])
                    except (ValueError, ZeroDivisionError, OverflowError):
                        continue
                    asks = [x["ask"] for x in rows[y] if x["line"] <= row["line"] and x["ask"] is not None]
                    bids = [x["bid"] for x in rows[y] if x["line"] >= row["line"] and x["bid"] is not None]
                    po = max([min([po] + asks)] + bids)
                    po, frm, width = min(po, cap or 1), m_line, m_w
                if not 0 < po < 1:
                    continue
                ly = {"stat": y, "side": "over", "line": row["line"], "p": po, "fair": sgp.american(po),
                      "width": width, "id": row["ids"]["over"], "from": frm}
                if src and frm is not None:
                    ly["src"] = src
                if book_text:
                    ly["books"] = book_text
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
    BOOKS["seen"] = dict({b: len(v) for b, v in (lad or {}).items()}, errors=dict(books.ERRORS)) if BOOKS["on"] else None
    return (out[:a.max] if a.max else out), ctx


STACK_DATA = os.path.join(HERE, "..", "..", "..", "public", "data", "nfl_stack_correlations.json")
STACK_PROPS = ("pyds", "ptd", "cmp", "att", "yds", "rec", "td", "ryds", "car", "rry")
# QB stat + teammate's stat asked by default; --scope all adds the weaker two.
STACK_PAIRS = (("pyds", "yds"), ("ptd", "td"), ("cmp", "rec"), ("pyds", "td"))
STACK_MORE = (("pyds", "rec"), ("ptd", "yds"))
# Game lines a prop is asked with, and Novig's market type for each. "win" is
# the moneyline; the h1 ones are the first half's total, spread and moneyline.
LINE_TYPES = {"over": "TOTAL", "cover": "SPREAD", "win": "MONEY", "tt": "TEAM_TOTAL",
              "h1over": "TOTAL_1H", "h1cover": "SPREAD_1H", "h1win": "MONEY_1H"}


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


def nfl_slate(a, game):
    """This week's NFL board for the slips across markets: (the role
    correlations, {eventId: {"teams": (away, home), "lines": {market type:
    [two_way rows on tight books]}}}, {eventId: {team: [(player, his main
    lines by stat, start time)]}}, vol(player, "tgt_mean" | "car_mean"))."""
    d, S = json.load(open(NFL_DATA)), json.load(open(STACK_DATA))
    cur = str(max(d["seasons"]))
    by = {novig.norm(p["name"]): p for p in d["players"]}
    types = [novig.ALL_TYPES[s] for s in STACK_PROPS] + (list(LINE_TYPES.values()) if game else ["TOTAL"])
    items = novig.catalog({"league": "NFL", "eventStatus": "OPEN_PREGAME", "marketType": ",".join(types)})
    props = [m for m in items if m["marketType"] in novig.STAT]
    events = {}
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

    people = {}
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
    return S, events, people, vol


def prop_leg(p, s, main, who=""):
    L = leg(s, main[s], 1)
    L["text"] = f"{who}{leg_text(L)}"
    return L


def line_r(S, vol, p, s, line):
    """The role's r between his stat and a game line. A back's rushing and
    his TD go by his carries, everything else by targets; a QB has one role."""
    by_ = None if p["group"] == "QB" else "car" if p["group"] == "RB" and s in ("ryds", "car", "rry", "td") else "tgt"
    return role_r(S["game"], by_ and vol(p, by_ + "_mean"), line=line, stat=s, pos=p["group"], by=by_)


def line_leg(ev, p, team, line, side):
    """The game-line leg nearest 50/50 on a tight book, or None. side > 0 is
    the Over, or his team (covering, winning, leading at the half); side < 0
    the Under, or the other team."""
    ms = ev["lines"].get(LINE_TYPES[line], [])
    if line == "tt":
        ms = [m for m in ms if m["desc"].startswith(p.get("team_name") or "?")]
    if not ms:
        return None
    m = min(ms, key=lambda m: (abs(m["p"][0] - 0.5) + m["spread"], -m["volume"]))
    half = " 1H" if line.startswith("h1") else ""
    if line in ("cover", "win", "h1cover", "h1win"):
        want = team if side > 0 else next(t for t in ev["teams"] if t != team)
        i = next((i for i, n in enumerate(m["names"]) if n.split()[0] == want), None)
        if i is None:
            return None
        text = m["names"][i] + half + (" moneyline" if line.endswith("win") else "")
    else:
        i = 0 if side > 0 else 1
        what = team + " team total" if line == "tt" else " @ ".join(ev["teams"]) + half
        text = f"{what} {'Over' if i == 0 else 'Under'} {m['strike']:g}"
    return {"stat": line, "side": "over" if i == 0 else "under", "line": m["strike"], "p": m["p"][i],
            "fair": sgp.american(m["p"][i]), "width": m["spread"], "id": m["ids"][i], "text": text}


def nflx_candidates(a, game):
    """NFL bets across two markets in one game, priced with league-wide role
    correlations (scripts/nfl_stack_correlations.py, nflverse):
      stacks (game=False)  a QB's passing Over + one of his own receivers' Over
      lines (game=True)    a player's prop Over + a game line on the side that
                           goes with it: the game total, his team's spread,
                           moneyline or team total, or the first half's total,
                           spread or moneyline (QB pass attempts Over goes
                           with the OTHER team covering or winning)
    Stacks: his --per highest-r combos. Lines: for each kind of line his
    highest-r prop, and his --per highest over the total, spread and team
    total whatever the prop."""
    S, events, people, vol = nfl_slate(a, game)

    def row(p, starts, la, lb, r, kind, tier):
        j = sgp.joint(r, la["p"], lb["p"])
        return {"key": f"{la['id']},{lb['id']}", "tier": tier, "player": p["name"], "id": p["athlete_id"],
                "team": p.get("team_abbr") or "", "starts": starts, "legs": [la, lb], "kind": kind,
                "label": f"{la['text']} · {lb['text']}", "r": r, "j": j, "forced": False,
                "devig_r": sgp.devig_r(j, la["p"], lb["p"]),
                "rough": max(la["width"], lb["width"]) > novig.MAX_SPREAD + 1e-9}

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
                            mine.append(row(p, starts, prop_leg(qb, qs, qmain, who), prop_leg(p, ts, main), r, "stack", 7))
                    out += sorted(mine, key=lambda c: -c["r"])[:a.per]
                continue
            for p, main, starts in ps:
                mine = []
                for s in main:
                    for line in LINE_TYPES:
                        r = line_r(S, vol, p, s, line)
                        if r is None or abs(r) < a.line_r:
                            continue
                        lb = line_leg(ev, p, team, line, r)   # his team's side when r > 0, the other when r < 0
                        if lb:
                            mine.append(row(p, starts, prop_leg(p, s, main), lb, abs(r), line, 8))
                mine.sort(key=lambda c: -c["r"])
                keep = {c["key"] for c in [c for c in mine if c["kind"] in ("over", "cover", "tt")][:a.per]}
                for line in LINE_TYPES:   # and his best prop with each kind of line
                    keep |= {c["key"] for c in [c for c in mine if c["kind"] == line][:1]}
                out += [c for c in mine if c["key"] in keep]
    out.sort(key=lambda c: -c["j"] / (c["legs"][0]["p"] * c["legs"][1]["p"]))
    return out[:a.max] if a.max else out


def tri_safe(ps, rs):
    """Three legs' joint from their pairwise r's (legs a, b, c: r_ab, r_ac,
    r_bc). Role r's come from different samples, so three of them needn't be
    a possible set: shrink them together until they are. Never above the
    tightest pair's own joint."""
    rab, rac, rbc = rs
    while 1 + 2 * rab * rac * rbc - rab ** 2 - rac ** 2 - rbc ** 2 < 0.02:
        rab, rac, rbc = 0.97 * rab, 0.97 * rac, 0.97 * rbc
    j = price.tri_joint(ps, [[1, rab, rac], [rab, 1, rbc], [rac, rbc, 1]])
    return min(j, sgp.joint(rab, ps[0], ps[1]), sgp.joint(rac, ps[0], ps[2]), sgp.joint(rbc, ps[1], ps[2]))


def nfl_tri_candidates(a):
    """NFL three-leg slips (part of the NFL pass; --kind tri alone), every leg at
    its main line and all three pulling the same way:
      own3       three of one player's props (receptions + yards + TD; a
                 QB's completions + passing yards + passing TDs)
      pairline   two of his props + a game line
      stackline  a QB's passing Over + his receiver's Over + a game line
      stack3     a QB's passing Over + two of one receiver's props, or two
                 of the QB's props + one of the receiver's
    The game line is any of LINE_TYPES, on the side that goes with both
    props (each at r 0.10 or better with it, one at --line-r). Pair r's: the
    player's own (nfl_correlations.json) for two of his props, the league-wide
    role r's (nfl_stack_correlations.json) across a QB and his receiver or
    with a game line. Each player leads his --per best by lift over unrelated
    legs, at most two of one shape and one of each kind of game line."""
    S, events, people, vol = nfl_slate(a, True)
    lift = {}

    def pair_lift(r, la, lb):
        k = (la["id"], lb["id"])
        if k not in lift:
            lift[k] = sgp.joint(r, la["p"], lb["p"]) / (la["p"] * lb["p"])
        return lift[k]

    def own_r(p, x, y):
        r = nfl_r(p, x, y)
        return r if r is not None and r >= 0 else None

    def with_line(ev, team, pa, la, pb, lb, rab):
        """(legs, pair r's, kind of line) for the two prop legs with each
        game line that goes the same way as both."""
        for line in LINE_TYPES:
            ra, rb = line_r(S, vol, pa, la["stat"], line), line_r(S, vol, pb, lb["stat"], line)
            if ra is None or rb is None:
                continue
            side = 1 if ra + rb > 0 else -1
            if min(ra * side, rb * side) < 0.10 or max(ra * side, rb * side) < a.line_r:
                continue
            lc = line_leg(ev, pa, team, line, side)
            if lc:
                yield [la, lb, lc], (rab, ra * side, rb * side), line

    out, seen = [], set()
    for eid, sides in people.items():
        ev = events[eid]
        for team, ps in sides.items():
            qbs = [x for x in ps if x[0]["group"] == "QB"]
            qb, qmain, _ = max(qbs, key=lambda x: x[0].get("att_mean") or 0) if qbs else (None, {}, None)
            who = qb["name"].split()[-1] + " " if qb else ""
            for p, main, starts in ps:
                L = {s: prop_leg(p, s, main) for s in main}
                own = [(x, y, r) for x, y in itertools.combinations(main, 2) for r in [own_r(p, x, y)] if r is not None]
                rown = {frozenset(k[:2]): k[2] for k in own}
                mine = []   # (shape, kind of line, legs, pair r's)
                for x, y, z in itertools.combinations(main, 3):
                    rs = [rown.get(frozenset(k)) for k in ((x, y), (x, z), (y, z))]
                    if None not in rs and max(rs) >= a.min_r:
                        mine.append(("own3", None, [L[x], L[y], L[z]], tuple(rs)))
                for x, y, r in own:
                    if r >= a.min_r:
                        mine += [("pairline", line, legs, rs) for legs, rs, line in with_line(ev, team, p, L[x], p, L[y], r)]
                if qb and p is not qb:
                    Q = {s: prop_leg(qb, s, qmain, who) for s in qmain}
                    st = {(qs, ts): r for qs, ts in STACK_PAIRS + STACK_MORE if qs in Q and ts in L
                          for r in [role_r(S["stack"], vol(p, "tgt_mean"), qb=qs, stat=ts, pos=p["group"], by="tgt")]
                          if r is not None and r >= a.min_r}
                    for (qs, ts), r in st.items():
                        mine += [("stackline", line, legs, rs) for legs, rs, line in with_line(ev, team, qb, Q[qs], p, L[ts], r)]
                    for (qs, t1), r1 in st.items():
                        for (q2, t2), r2 in st.items():
                            if q2 == qs and t1 < t2 and frozenset((t1, t2)) in rown:   # one QB leg, two of the receiver's
                                mine.append(("stack3", None, [Q[qs], L[t1], L[t2]], (r1, r2, rown[frozenset((t1, t2))])))
                            rq = own_r(qb, qs, q2) if t2 == t1 and qs < q2 else None   # two QB legs, one of his
                            if rq is not None:
                                mine.append(("stack3", None, [Q[qs], Q[q2], L[t1]], (rq, r1, r2)))
                # Ranked on the product of the three pair lifts (quick, and
                # close); the exact three-leg joint is worked out for the kept.
                def rough(c):
                    (la, lb, lc), (rab, rac, rbc) = c[2], c[3]
                    return pair_lift(rab, la, lb) * pair_lift(rac, la, lc) * pair_lift(rbc, lb, lc)
                shapes, lines_used, n = {}, set(), 0
                for shape, line, legs, rs in sorted(mine, key=lambda c: -rough(c)):
                    ids = frozenset(x["id"] for x in legs)
                    if n >= a.per or shapes.get(shape, 0) >= 2 or line in lines_used or ids in seen:
                        continue
                    try:
                        j = tri_safe([x["p"] for x in legs], rs)
                    except (ValueError, ZeroDivisionError, OverflowError):
                        continue
                    if not 0 < j < 1:
                        continue
                    seen.add(ids)
                    n += 1
                    shapes[shape] = shapes.get(shape, 0) + 1
                    if line:
                        lines_used.add(line)
                    out.append({"key": ",".join(x["id"] for x in legs), "tier": 9, "player": p["name"], "id": p["athlete_id"],
                                "team": p.get("team_abbr") or "", "starts": starts, "legs": legs, "kind": shape, "line": line,
                                "label": " · ".join(x["text"] for x in legs), "r": min(rs), "rs": [round(r, 3) for r in rs],
                                "j": j, "forced": False, "devig_r": None,
                                "rough": max(x["width"] for x in legs) > novig.MAX_SPREAD + 1e-9})
    out.sort(key=lambda c: -c["j"] / (c["legs"][0]["p"] * c["legs"][1]["p"] * c["legs"][2]["p"]))
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
    Over, per match, against the unrelated-legs price. Each leg's fair value
    is Pinnacle's no-vig price on that line where it has one (pinnacle.py),
    else the middle of Novig's own book."""
    out, failed = [], []
    try:
        import pinnacle
        pin = pinnacle.board()
    except Exception as e:
        pin = []
        print(f"Pinnacle didn't answer ({type(e).__name__}): leg fair values from Novig's own books", file=sys.stderr)
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

            game, fside = pinnacle.match(pin, fav, dog, wins[0]["starts"] / 1000, wins[0]["p"][0]) if pin else (None, None)
            dside = "away" if fside == "home" else "home"

            def crn(m, side, way):
                return game and game["corners"].get((side, float(m["strike"])), {}).get(way)

            def corners(team, side):
                """The team's line nearest 50/50: among the lines Pinnacle prices
                if it has any (by its price), else by Novig's book."""
                v = [m for m in ms if m["type"] == "TEAM_TOTAL_CORNERS" and m["desc"].startswith(team + " ") and m["width"] <= 0.30]
                sharp = [m for m in v if crn(m, side, "over")]
                if sharp:
                    return min(sharp, key=lambda m: abs(crn(m, side, "over")[0] - 0.5))
                return min(v, key=lambda m: abs(m["p"][0] - 0.5) + m["width"]) if v else None
            fc, dc = corners(fav, fside), corners(dog, dside)
            if not fc or not dc:
                continue

            def L(m, i, stat, text, sharp=None):
                """sharp: Pinnacle's (fair chance, American price) on this leg, or None."""
                leg = {"stat": stat, "side": "under" if i else "over", "line": float(m["strike"] or 0), "p": m["p"][i],
                       "fair": sgp.american(m["p"][i]), "width": m["width"], "id": m["ids"][i], "text": text}
                if sharp:
                    leg.update(p=sharp[0], fair=sgp.american(sharp[0]), sharp=True, novig_p=m["p"][i],
                               books=f"Pinnacle {sharp[1]:+d}, Novig's book says {sgp.american(m['p'][i]):+d}")
                return leg
            base = [L(wins[0], 0, "ml", f"{fav} win", game and game["ml"][fside]),
                    L(fc, 1, "crn", f"{fav} U{fc['strike']} corners", crn(fc, fside, "under")),
                    L(dc, 0, "crn", f"{dog} O{dc['strike']} corners", crn(dc, dside, "over"))]
            shapes = [(None, base)]
            for line in ("1.5", "2.5"):
                t = next((m for m in ms if m["type"] == "TOTAL" and m["strike"] == line and m["width"] <= 0.30), None)
                if t:
                    shapes.append((line, [base[0], L(t, 0, "tot", f"Over {line}",
                                                     game and game["goals"].get(float(line), {}).get("over"))] + base[1:]))
            for goals, legs in shapes:
                unrelated = math.prod(x["p"] for x in legs)
                lift = next(v for top, v in SOCCER_LIFT[goals] if base[0]["p"] <= top)
                out.append({"key": ",".join(x["id"] for x in legs), "tier": 5, "player": f"{fav} v {dog}", "id": eid,
                            "team": lg, "starts": wins[0]["starts"], "legs": legs, "label": " · ".join(x["text"] for x in legs),
                            "r": None, "j": min(unrelated * lift, 0.99), "forced": False, "devig_r": None,
                            "lift": lift, "unrelated_x": 1 / unrelated, "sharp": sum(1 for x in legs if x.get("sharp")),
                            "rough": any(x["width"] > novig.MAX_SPREAD + 1e-9 for x in legs if not x.get("sharp"))})
    if failed and not out:
        raise SystemExit("Novig's catalog didn't answer for " + ", ".join(failed))
    return (out[:a.max] if a.max else out), {}


CFB_KAPPA = 0.5            # corr(favourite's margin, total) = CFB_KAPPA x spread / total
CFB_SD = (14.6, 15.0)      # margin and total sd where a game's ladder is too short to fit
CFB_MIN_DOG = 0.10         # no underdog-moneyline slips on a longer shot than this


def cfb_fit(points, default_sd):
    """(line, P(X > line)) pairs -> (mean, sd) of a normal by least squares on
    z. Under four points, or a fitted sd outside 10 to 22, the sd is the
    default and the mean comes from the line nearest even money."""
    pts = [(x, sgp.nppf(p)) for x, p in points if 0.08 < p < 0.92]
    if len(pts) >= 4:
        n, sx, sz = len(pts), sum(x for x, _ in pts), sum(z for _, z in pts)
        sxx, sxz = sum(x * x for x, _ in pts), sum(x * z for x, z in pts)
        b = (n * sxz - sx * sz) / ((n * sxx - sx * sx) or 1e-9)   # z = a + b x = (mu - x) / sd
        if b < 0 and 10 <= -1 / b <= 22:
            return -(sz - b * sx) / n / b, -1 / b
    x, p = min(points, key=lambda q: abs(q[1] - 0.5))
    return x + default_sd * sgp.nppf(p), default_sd


def cfb_candidates(a):
    """College football slips across one game's lines (see the module docstring)."""
    items = novig.catalog({"league": "NCAAF", "eventStatus": "OPEN_PREGAME", "marketType": "MONEY,SPREAD,TOTAL,TEAM_TOTAL"})
    games = {}
    for m in items:
        games.setdefault(m["eventId"], []).append(m)
    out = []
    for eid, ms in games.items():
        money = next((m for m in ms if m["marketType"] == "MONEY"), None)
        name = next((m["description"].rsplit(" t", 1)[0] for m in ms if m["marketType"] == "TOTAL" and " @ " in m["description"]), None)
        tw = money and two_way(money)
        if not tw or not name:
            continue
        f = 0 if tw["p"][0] >= 0.5 else 1
        fav, dog = tw["names"][f], tw["names"][1 - f]
        sub = {o.get("subjectId"): o["name"] for o in money["outcomes"]}
        legs = []   # every side of every two-sided line
        for m in ms:
            t = two_way(m)
            if not t:
                continue
            for i, o in enumerate(m["outcomes"]):
                L = {"p": t["p"][i], "fair": sgp.american(t["p"][i]), "width": t["spread"], "id": o["outcomeId"],
                     "line": t["strike"], "side": "over"}
                if m["marketType"] == "MONEY":
                    L.update(stat="ml", team=o["name"], text=f"{o['name']} ML")
                elif m["marketType"] == "SPREAD":
                    tm, _, ln = o["name"].rpartition(" ")
                    L.update(stat="cover", team=tm, line=float(ln), text=o["name"])
                elif m["marketType"] == "TOTAL":
                    L.update(stat="tot", team=None, side="over" if i == 0 else "under", text=f"{'Over' if i == 0 else 'Under'} {t['strike']:g}")
                elif m["marketType"] == "TEAM_TOTAL" and o.get("subjectId") in sub:
                    tm = sub[o["subjectId"]]
                    L.update(stat="tt", team=tm, side="over" if i == 0 else "under",
                             text=f"{tm} team total {'Over' if i == 0 else 'Under'} {t['strike']:g}")
                else:
                    continue
                legs.append(L)
        fit = [L for L in legs if L["width"] <= 0.05 + 1e-9]   # the ladders the model is fitted to
        sp = [(-L["line"], L["p"]) for L in fit if L["stat"] == "cover" and L["team"] == fav]
        to = [(L["line"], L["p"]) for L in fit if L["stat"] == "tot" and L["side"] == "over"]
        if not sp or not to:
            continue
        (mu_m, sd_m), (mu_t, sd_t) = cfb_fit(sp, CFB_SD[0]), cfb_fit(to, CFB_SD[1])
        if mu_t <= 0:
            continue
        # The two scores: variances and covariance from the margin's and the
        # total's sd, the favourite's share of the variance from CFB_KAPPA.
        rho = min(0.6, max(0.0, CFB_KAPPA * mu_m / mu_t))
        both, cfd, diff = (sd_m ** 2 + sd_t ** 2) / 2, (sd_t ** 2 - sd_m ** 2) / 4, rho * sd_m * sd_t
        vf, vd = (both + diff) / 2, (both - diff) / 2

        def vec(L):
            """The leg as weights on (favourite's score, underdog's score), signed so it wins when that is high."""
            if L["stat"] in ("ml", "cover"):
                s = 1 if L["team"] == fav else -1
                return (s, -s)
            s = 1 if L["side"] == "over" else -1
            return (s, s) if L["stat"] == "tot" else (s, 0) if L["team"] == fav else (0, s)

        def corr(x, y):
            (a1, b1), (a2, b2) = vec(x), vec(y)
            cov = lambda p, q, r, t: p * r * vf + q * t * vd + (p * t + q * r) * cfd   # noqa: E731
            return cov(a1, b1, a2, b2) / math.sqrt(cov(a1, b1, a1, b1) * cov(a2, b2, a2, b2))

        def both_scores(ls):
            """P(every leg hits) for three or more legs. They are all cuts of
            the same two scores, so their correlation matrix has no inverse
            and price.tri_joint can't take it: integrate over the first score
            and, at each value, take the stretch of the second that wins every leg."""
            l11 = math.sqrt(vf)
            l21 = cfd / l11
            l22 = math.sqrt(vd - l21 * l21)
            cuts = []
            for L in ls:
                wf, wd = vec(L)
                x, y = wf * l11 + wd * l21, wd * l22
                n = math.hypot(x, y)
                cuts.append((x / n, y / n, sgp.nppf(1 - L["p"])))   # hits when x X1 + y X2 > t
            n, tot = 2000, 0.0
            for i in range(n + 1):
                x1 = -8 + 16 * i / n
                lo, hi, ok = -math.inf, math.inf, True
                for x, y, t in cuts:
                    if abs(y) < 1e-12:
                        ok = ok and x * x1 > t
                    elif y > 0:
                        lo = max(lo, (t - x * x1) / y)
                    else:
                        hi = min(hi, (t - x * x1) / y)
                if ok and hi > lo:
                    w = 1 if i in (0, n) else 4 if i % 2 else 2
                    tot += w * math.exp(-x1 * x1 / 2) * (sgp.ncdf(hi) - sgp.ncdf(lo))
            return tot * (16 / n) / 3 / math.sqrt(2 * math.pi)

        def pick(stat, team=None, side="over", target=0.5, within=0.12):
            v = [L for L in legs if L["stat"] == stat and L["team"] == team and L["side"] == side
                 and L["width"] <= a.max_spread + 1e-9 and abs(L["p"] - target) <= within]
            return min(v, key=lambda L: abs(L["p"] - target) + L["width"]) if v else None
        dog_ml = pick("ml", dog, target=tw["p"][1 - f], within=0.01)
        if dog_ml and dog_ml["p"] < CFB_MIN_DOG:
            dog_ml = None
        under, under_alt = pick("tot", side="under"), pick("tot", side="under", target=0.30, within=0.08)
        dog_tt = pick("tt", dog)
        shapes = [("dogml", [dog_ml, under]), ("dogml", [dog_ml, under_alt]), ("dogml", [dog_ml, under, dog_tt]),
                  ("cover", [pick("cover", fav), pick("tot")]), ("cover", [pick("cover", dog), under])]
        for kind, ls in shapes:
            if any(L is None for L in ls) or len({L["id"] for L in ls}) < len(ls):
                continue
            R = [[1.0 if i == j else corr(x, y) for j, y in enumerate(ls)] for i, x in enumerate(ls)]
            j = sgp.joint(R[0][1], ls[0]["p"], ls[1]["p"]) if len(ls) == 2 else both_scores(ls)
            out.append({"key": ",".join(L["id"] for L in ls), "tier": 9, "player": name, "id": eid, "team": "NCAAF",
                        "starts": money["startsTs"], "legs": [dict(L) for L in ls], "kind": kind,
                        "label": " · ".join(L["text"] for L in ls), "forced": False,
                        "r": min(R[i][k] for i in range(len(ls)) for k in range(i)), "j": j,
                        "devig_r": sgp.devig_r(j, ls[0]["p"], ls[1]["p"]) if len(ls) == 2 else None,
                        "rough": max(L["width"] for L in ls) > novig.MAX_SPREAD + 1e-9})
    out.sort(key=lambda c: c["starts"])
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
    elif a.league == "cfb":
        d = {"generated_at": time.strftime("%Y-%m-%d")}
        cands, ctx = cfb_candidates(a)
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
        if a.kind in ("all", "tri"):   # three legs, asked with the rest of the NFL tab
            cands = cands + nfl_tri_candidates(a)
        stats, rfun = NFL_STATS, nfl_r
    elif a.league == "nhl":
        d = json.load(open(NHL_DATA))
        markets = novig.fetch("NHL", NHL_STATS)
        # "all" is a skater's own props and teammates; game lines are their own
        # pass (--kind lines: the NHL Lines board), about as many quotes again.
        cands, ctx = nhl_candidates(markets, d, a) if a.kind in ("all", "props") else ([], {})
        if a.kind in ("all", "mates"):
            cands = cands + nhl_mate_candidates(markets, d, a)
        if a.kind == "lines":
            cands = cands + nhl_line_candidates(markets, d, a)
        stats, rfun, a.tri = (), None, 0
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
    if BOOKS["ladders"] is not None:   # the NBA ladder's lazy pull
        import books as _b
        BOOKS["seen"] = dict({b: len(v) for b, v in BOOKS["ladders"].items()}, errors=dict(_b.ERRORS))
    emit({"type": "start", "total": len(cands), "players": len({c["id"] for c in cands}),
          "league": a.league, "data": d["generated_at"][:10], "at": t0, "books": BOOKS["seen"]})
    pace, rows, lock = Pace(), [], threading.Lock()

    def soonest(cs):
        """Earliest game first, so a slate's early games are priced before
        they start; within a game the order the candidates came in."""
        return sorted(cs, key=lambda c: c.get("starts") or float("inf"))

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
        first = soonest(c for c in cands if c["tier"] == 1)
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
        list(pool.map(one, soonest(up + kept)))
        cands = first + up + kept
        if a.league == "nba" and a.scope != "ladder" and a.stars:
            asked_keys = {c["key"] for c in cands}
            more = [c for c in star_triples(ctx, rfun, a) if c["key"] not in asked_keys]
            if more:
                emit({"type": "more", "add": len(more)})
                cands = cands + more
                list(pool.map(one, soonest(more)))
        if a.tri and a.tier in (0, 4):
            more = triples([c for c in rows if go(c)], ctx, stats, rfun, a)
            emit({"type": "more", "add": len(more)})
            cands = cands + more
            list(pool.map(one, soonest(more)))
    emit({"type": "done", "quoted": len(cands), "priced": len(rows), "seconds": time.time() - t0, "at": time.time()})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="nba", choices=("nba", "nfl", "nhl", "soccer", "cfb"))
    ap.add_argument("--kind", default="all", choices=("all", "props", "stacks", "lines", "tri", "mates"),
                    help="NFL: one kind of slip only (default: a player's own props, stacks, game lines, "
                         "then tri, the three-leg slips). "
                         "NHL: props (a skater's own goals + shots), mates (two teammates) or lines (points + a game line)")
    ap.add_argument("--per", type=int, default=None,
                    help="NFL stacks / lines / three legs, NHL teammates: combos asked per player of each kind, highest r first "
                         "(3; NHL lines 4: moneyline, puck line, total and team total)")
    ap.add_argument("--line-r", type=float, default=0.25, help="NFL / NHL lines: smallest |r| between a prop and a game line")
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
    ap.add_argument("--min-r", type=float, default=None,
                    help="smallest r for an Over + Over on the other pairs (0.15; NHL 0.10)")
    ap.add_argument("--line-stats", nargs="+", default=["pts"], choices=("pts", "g", "ast", "sog"),
                    help="NHL game lines: the skater legs asked with a game line (default: points)")
    ap.add_argument("--mate-r", type=float, default=0.20, help="NHL teammates: smallest r for a slip across two skaters")
    ap.add_argument("--nhl-points", action="store_true",
                    help="NHL: also ask pairs with the skater's points (Novig refused them on 11-12)")
    ap.add_argument("--max-spread", type=float, default=novig.MAX_SPREAD, help="widest Novig book for a leg (prob)")
    ap.add_argument("--alt-spread", type=float, default=0.08, help="widest book for the second threes milestone")
    ap.add_argument("--workers", type=int, default=3, help="quotes in flight at once")
    ap.add_argument("--unit", type=float, default=None, help="dollars per unit, 1u = 1%% of bankroll (250; NHL 500)")
    ap.add_argument("--kelly", type=float, default=0.25, help="Kelly fraction (default quarter)")
    ap.add_argument("--min-ev", type=float, default=None, help="print only rows at this EV%% or better")
    ap.add_argument("--top", type=int, default=25, help="rows to print (default 25; 0 = all)")
    ap.add_argument("--json", action="store_true", help="stream events as JSON lines instead of a table")
    a = ap.parse_args()
    BOOKS["on"] = not a.no_books
    if a.per is None:
        a.per = 4 if a.league == "nhl" and a.kind == "lines" else 3
    if a.unit is None:
        a.unit = 500.0 if a.league == "nhl" else 250.0
    if a.min_r is None:
        a.min_r = 0.10 if a.league == "nhl" else 0.15
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
    if a.kind == "tri" and (a.league != "nfl" or a.scope == "ladder"):
        raise SystemExit("--kind tri is NFL only (and not with --scope ladder)")
    if a.scope == "ladder":
        if a.league in ("soccer", "cfb"):
            raise SystemExit("--scope ladder is NBA and NFL only")
        if a.league == "nhl":
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
