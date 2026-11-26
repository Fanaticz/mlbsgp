#!/usr/bin/env python3
"""Novig SGP scanner: same-player 2-leg parlays for every open pregame NBA
player, ranked by EV at what Novig's slip pays.

  python3 scan.py                 # main-line Points + Threes, one slip a player
  python3 scan.py --scope all     # everything listed below (many more quotes)
  python3 scan.py --scope ladder  # NBA shooters' higher lines only, one-way lines included
  python3 scan.py --league nfl --scope ladder   # NFL: higher yards lines + TD / receptions / passing TDs
  python3 scan.py --scope ladder --kalshi       # the Ladder boards as the server runs them: Kalshi's price for the same slip too
  python3 scan.py --tier 1        # Points + Threes only (about 2 minutes)
  python3 scan.py --max 120       # stop after 120 quotes
  python3 scan.py --min-ev 3      # print only rows at +3% or better
  python3 scan.py --kind team     # NBA Team board: a player's prop with the spread, and a game's own lines
  python3 scan.py --league nfl    # NFL: a player's own props, QB + receiver stacks, props + game lines, three legs
  python3 scan.py --league nfl --kind stacks   # one kind only: props, stacks, lines or tri
  python3 scan.py --league nfl --kind tri      # NFL three-leg slips alone
  python3 scan.py --league nhl    # NHL: a skater's goals, assists, points and shots on goal, every pair
  python3 scan.py --league cfb    # college football: slips across a game's own lines
  python3 scan.py --league cbb    # college basketball: spread + total
  python3 scan.py --league nfl --games         # the open games and their ids
  python3 scan.py --league nfl --events ID ID  # only those games (the page's game picker)
  python3 scan.py --league nfl --before MS     # only games starting before that time (Auto-scan: today's games)
  python3 scan.py --json          # one JSON object per line as quotes land
                                  # (server.js reads this for the Scanner page)

Fair value (NBA: where Kalshi lists the same line, the tighter of the two
exchanges' books, as on the Kalshi boards: two_books): each leg is Novig's own exchange book at that line, devigged
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
  T  Teammates: each team's two highest points lines, Over + Over, priced
     as unrelated legs (nba_mate_candidates: that is what four seasons of
     box scores say, and Novig often prices them as if they pulled against
     each other). Not gated: one slip a team.
Under + Under is never asked: Novig rejects it for one player. Legs on books
wider than --max-spread are skipped, not guessed.

NBA Team (--league nba --kind team): slips with a game line in them
(nba_team_candidates). A player's main-line Over on points, rebounds,
assists, threes or points + rebounds + assists with the game's spread on
the side that goes with it, and his Under with the other side. The r is
league-wide for a player with that line on a team with tonight's spread
(public/data/nba_line_correlations.json, built by
scripts/nba_line_correlations.py from four seasons of box scores against
closing lines), and it turns on who is favoured: a 20-to-25-point scorer's
Over goes with his team covering at +0.42 as an 8-point underdog, +0.19 in
a pick'em and -0.08 as a 10-point favourite; a 25-point scorer on a
12-point favourite is -0.26, so his Over is asked with the other team
covering. Asked where the fitted |r| is at least --line-r (0.42 here; 0.15
when the prop goes against his own team covering, and then only on a
favourite of 11 or more), and priced at the fit less one standard error;
each player's --per (3) highest pairings, players at 20+ minutes a game
only. His role in the data comes from the line and its price (nba_role).
--team-lines adds the first-half spread, his team's total, the other
team's, the game total or the first half's. Then six slips across each
game's own lines (NBA_GAME_SHAPES: team totals with each other and with the
game total, the underdog's moneyline + Under, the favourite's first-half
moneyline + his moneyline) at each shape's measured r. A team total takes
Pinnacle's no-vig price on the same line where Novig's own book is wider
than --max-spread.
Tested 11-13 on nine games, about 700 quotes. Game lines alone (99 quotes,
33 shapes on three games): Novig's quote before its fee sits on the
measured r (favourite covers + his team total Over 0.62 quoted, 0.58
measured), so after the 10% fee every shape's median was under fair, -5% to
-12%. A prop with a team total (206 quotes) or a game total (18): medians
-6.4% and -4.6%, none at +3%. A prop with the spread is the exception,
because Novig's r for it barely moves with who is favoured. Priced at the
fit less one standard error: at a fitted r of 0.42 or better (a main scorer
on a team getting 8 or more) 33 of 42 quotes over two passes were above
fair, median +2.0%; a star's prop against his own team covering as a
favourite of 11+, 5 of 6, median +5.3%; at 0.30 to 0.42, 8 of 45, median
-4.0%; with the first-half spread, 3 of 16, median -3.6%.
The r's were checked the same day (Max: is Wembanyama's right?). A rolling
line (his previous 15 games) in place of the season median gives the same
r's. Fitted on three seasons and tested on the fourth, each in turn, the
plain fit was within 1% of the share of slips that hit in every group but
the top one (0.42+: 30.5% hit, the fit said 31.5%, the fit less one
standard error 30.3%), and held at every size of spread on the underdog
side for points and PRA. The favourite side is real from 11 points
(28.8% hit at 11 to 14, unrelated legs 24.2%) and absent at 8 to 11 (26.9%
against 26.6%), which a straight line misses. Threes were in the wrong
role for 26 of 83 players when the role was read off the line alone.

NFL (--league nfl): WRs, TEs and RBs in public/data/nfl_correlations.json,
whose shrunk r's are already copula correlations. Over + Over at main lines,
and Under + Under on the same pairs at the same r (Max, 11-15: Unders are
fair play; Novig prices one NFL player's Under + Under, unlike the NBA's;
--no-unders leaves every Under out), on Receptions·Yards, Receptions·TD and Yards·TD (TD = Novig's TOUCHDOWNS 0.5,
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
Unders get that allowance again: a stack's Under + Under; a QB's pass
attempts against his back's carries (-0.29 for a lead back) and his passing
yards against the back's rushing yards (-0.15), Over + Under both ways; and
a prop's Under with the line's other side (a back's rushing yards Under +
the other team covering). Three-leg slips are still all Overs.
With the spread and the moneyline (and their first-half versions) the r
used is the one for his team's side of today's spread: underdog of 3.5+,
favourite of 3.5+, or between. A QB's attempts go against his team covering
at -0.44 as a favourite and -0.15 as an underdog; a lead back's carries go
with it at +0.22 as a favourite and +0.54 otherwise.
The moneyline's r is measured within games of the same closing spread and
comes out near the spread's (winning and covering are one margin); first-half
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
together more often than unrelated legs would. Every leg's fair value is
Pinnacle's no-vig price on that line (pinnacle.py), never Novig's own book:
a match Pinnacle doesn't list, or a leg on a line it doesn't price, is not
asked, and if Pinnacle doesn't answer nothing is. Leagues: the top five,
the Champions League, MLS and Liga MX. In a close game (the underdog
at least 26% to win, SOCCER_DOG_MIN) it also asks the mirror: underdog to win + favourite's corners Over +
underdog's corners Under (a favourite who is behind piles up corners). Each
three-leg slip is asked again with a corner leg moved one line either way,
where Pinnacle prices that line. Fair value
is a Gaussian copula's joint at the legs' own prices, with each pair of
legs' r measured on 19,761 top-five-league matches (2015-16 on,
football-data.co.uk: results, corners, closing odds) by strength of
favourite, times the shape's scale so it matches the counted hit rate on
average (scripts/soccer_corner_correlations.py; within 5% at every corner
line tested; the same r's on MLS and Liga MX, where they were checked
against each league's own matches). The fixed lifts it replaced (SOCCER_LIFT, x1.25 to x1.61,
right only at the 50/50 corner lines) are kept for when that file is
missing. League averages, not match-specific: rows are leads.

College football (--league cfb): Novig lists no player props for NCAAF, only
game lines, so the slips are across a game's own lines: the underdog's
moneyline + the game Under (main line, and the Under nearest +230), those two
with the underdog's team total Over, the favourite's spread + Over and the
underdog's spread + Under; then, on Novig's own team-total and first-half
books (tight on about half a Saturday's games): the underdog's spread + his
team total Under, the favourite's team total Under + Under, both team totals
Under, the favourite's first-half spread + his spread, and the first-half
Under + Under. Ten asks a game at most. The correlation comes
from a two-score model fitted to that game's own ladders: the margin's and
the total's spread (sd) from Novig's alt spreads and alt totals, the two
teams' scores tied by what those two sds imply, and the margin tied to the
total by CFB_KAPPA x spread / total (an assumption, not measured on college
results; Novig's own quotes imply about the same). On 182 quotes over four
games (11-13) Novig priced these within a point or two of that model, so
after the fee nearly every row is under fair: rows are leads.

College basketball (--league cbb): the same model on NCAAB, six asks a game.
The favourite's spread + Over and the underdog's spread + Under; then, with
team-total and first-half legs priced off Pinnacle (pinnacle.lines: Novig's
own books on those run 6c to 28c wide, none of 314 team totals inside 4c on
11-13): the underdog's spread + the underdog's team total Under, the
favourite's team total Under + Under, both team totals Under, and the
favourite's first-half spread + his spread. A leg takes Pinnacle's price
only on the same line; a game Pinnacle doesn't list gets the first two
slips only. The margin is close to unrelated to the total (r 0.01 in a close
game, 0.10 at a 30-point spread), so there is no underdog-moneyline slip.
The correlations on this board are measured, not modelled: each shape's
copula r on 17,319 games of 2023-24 to 2025-26 against closing lines, by
size of spread (scripts/cbb_line_correlations.py): underdog covers + his
team total Under -0.60, the favourite's team total Under + game Under
+0.83, first-half spread + spread +0.63, each the same at every spread; and
two that follow a curve by spread (cbb_r): both team totals Under +0.37 to a
10-point spread, +0.33 at 20, +0.25 at 30, +0.20 at 35 (DraftKings paid more
than the one-r fair on those, 11-17), and spread + total -0.04 to 10 points,
+0.01 at 20, +0.12 at 30.
Each two-leg slip is asked again with each leg moved one line either way,
where that line has a fair value (Pinnacle's on team totals and the first
half, Novig's own tight book on the game's spread and total): Novig's price
does not follow the line the way the fair value does, so the line beside
can be the better play. Team-total and first-half slips always; a spread +
total slip only when it priced at --alt-gate (-8%) or better.
Tested 11-13: 89 quotes on Novig's own books, none above fair, median -10%;
106 quotes with Pinnacle's team totals and first halves, 5 above fair,
median -9.5%. The four Pinnacle shapes asked here were the best of 27 by
median (-2% to -8%).

EV and the stake use the fair value as shown (American odds), like price.py:
quarter Kelly, 1u = 1% of bankroll = --unit dollars.
"""
import argparse
import concurrent.futures
import heapq
import itertools
import json
import math
import os
import sys
import threading
import time
import types

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
         "g": "G", "sog": "SOG", "blk": "BLK", "pra": "PTS+REB+AST"}
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


def inside(po, bid, ask):
    """A modelled chance held to the line's own book. An ask is a ceiling and
    a bid a floor. With both, a model that falls outside them takes the book's
    own fair value (each side devigged worst case), not the edge nearest the
    model: the book as a whole says the model is off, and its edge is the
    most the model's way it could be (11-25: Lendeborg's 3+ threes modelled
    0.349 from his 2+ line against 27 / 30 on Kalshi and 25.5 / 30.5 on
    Novig, held at the ask, made 20+ points + 3+ threes fair +225, likelier
    than the threes leg alone). Inside the book the model stands."""
    ok = lambda x: x is not None and 0 < x < 1   # noqa: E731
    if ok(bid) and ok(ask) and bid < ask:
        return po if bid <= po <= ask else sgp.devig_worst(ask, 1 - bid)[0]
    if ok(ask):
        po = min(po, ask)
    if ok(bid):
        po = max(po, bid)
    return po


def shifted(p, stat, row, main):
    """A leg at `row`'s line with its fair value shifted from the main line's."""
    book_text = ""
    po = main["fo"] if row is main else price.leg_prob(
        p, {"stat": stat, "side": 1, "line": row["line"], "from": main["line"], "p_over": main["fo"],
            "over": None, "under": None})[0]
    # Novig's own ask on that line is a ceiling: someone is selling the Over
    # there, so the true chance is below it however wide the book is. A buyer there is a floor.
    if row is not main:
        po = inside(po, row.get("bid"), row.get("ask"))
    if row is not main and BOOKS["on"]:   # FanDuel one-way price, least margin out: a ceiling
        if BOOKS["ladders"] is None:
            import books
            BOOKS["ladders"], BOOKS["check"] = books.load(), books.check
        cap, _, book_text = BOOKS["check"](BOOKS["ladders"], p["name"], stat, row["line"])
        if cap is not None:
            po = min(po, cap)
    out = {"stat": stat, "side": "over", "line": row["line"], "p": po, "fair": sgp.american(po),
           "width": main["spread"], "id": row["ids"]["over"], "from": None if row is main else main["line"]}
    if row is main and row.get("kal"):
        out["kal"] = row["kal"]
    if book_text:
        out["books"] = book_text   # shown in the open row: "FD +600"
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


# spread: widest Kalshi book a leg is read from. size: contracts ($1 each) on the thinner side of
# Kalshi's best bid and ask for its book to count beside Novig's. props: its NBA props, pulled once a run.
KALSHI = {"spread": 0.05, "size": 500, "props": None}


def two_books(nv, kbid, kask, max_spread, kalshi_spread=None, ksize=None):
    """One line's fair value from the two exchanges' books on it: (Over, Under,
    width, "novig" | "kalshi" | "both"), or None when neither has a book tight
    enough. The tighter book, each side devigged worst case; where the two are
    within a cent of each other in width, the average of their fair values.
    nv: Novig's row on the line (novig.quote) or None. kbid, kask: Kalshi's
    Yes bid and ask on the same milestone. The one rule for every NBA board,
    Novig's and Kalshi's (Max, 11-22: the same slip read +132 on one and +125
    on the other, the Novig board having priced off Novig's book alone).
    ksize: the contracts on the thinner side of Kalshi's best bid and ask.
    Under KALSHI["size"] (or not known), Novig's book is used where it has
    one: Kalshi's cent-wide books are mostly a few contracts (11-22: Klay
    15+ points 50 / 51 with 7 contracts bid and 150 traded, against 9,500 bid
    and 87,000 traded on Novig; the slate's median 23 contracts against
    3,700). A thin Kalshi book still prices a line Novig has no tight book on,
    held inside Novig's bid and ask on that line where it has them. nv may be
    a Novig row of any width: it is a book only inside max_spread."""
    books = []
    if nv is not None and usable(nv, max_spread):
        books.append((nv["spread"], nv["fo"], nv["fu"], "novig"))
    ks = KALSHI["spread"] if kalshi_spread is None else kalshi_spread
    if kbid is not None and kask is not None and 0 < kbid < kask < 1 and kask - kbid <= ks + 1e-9:
        books.append((kask - kbid,) + tuple(sgp.devig_worst(kask, 1 - kbid)) + ("kalshi",))
    if not books:
        return None
    thin = ksize is None or ksize < KALSHI["size"]
    if len(books) == 2 and thin:
        books = books[:1]
    if len(books) == 2 and abs(books[0][0] - books[1][0]) <= 0.01 + 1e-9:
        return (books[0][1] + books[1][1]) / 2, (books[0][2] + books[1][2]) / 2, max(books)[0], "both"
    width, fo, fu, src = min(books)
    if src == "kalshi" and thin and nv is not None:
        # A thin Kalshi book pricing the line alone is held inside Novig's own
        # bid and ask there, however wide (Max, 11-22: Stirtz 15+ points read
        # 0.395 off a Kalshi book 38 / 41 minutes after it opened, Novig's
        # wider one on 14.5 offering it near 0.29; the slip showed +487, the
        # books +815).
        bid, ask = nv.get("bid"), nv.get("ask")
        if ask is not None and 0 < ask < 1:
            fo, fu = min(fo, ask), max(fu, 1 - ask)
        if bid is not None and 0 < bid < 1:
            fo, fu = max(fo, bid), min(fu, 1 - bid)
    return fo, fu, width, src


def kalshi_blend(nm, rows, max_spread):
    """Novig's ladder rows for one NBA player, each line Kalshi also lists
    re-priced by two_books. A row that changes carries "kal" (Kalshi's ticker,
    for the refresh) and "src". Kalshi unreachable: the rows stay Novig's."""
    if KALSHI["props"] is None:
        try:
            import scan_kalshi
            KALSHI["props"] = scan_kalshi.kalshi_props()
        except (SystemExit, Exception) as e:  # noqa: BLE001
            print(f"Kalshi's books were not read ({e}): fair values are off Novig's alone", file=sys.stderr)
            KALSHI["props"] = {}
    who = KALSHI["props"].get(novig.norm(nm))
    for stat, rs in rows.items() if who else ():
        ks = {k["line"]: k for k in who["stats"].get(stat, [])}
        for r in rs:
            k = ks.get(r["line"])
            if not k or r.get("spread") is None or not 0 < r["bid"] < r["ask"] < 1:
                continue
            b = two_books(r, k["bid"], k["ask"], max_spread, ksize=k.get("size"))
            if b and b[3] != "novig":
                r.update(fo=b[0], fu=b[1], spread=b[2], src=b[3], kal=k["ticker"])


# The Ladder boards' second price (Max, 11-27: when we do ladders, look up Novig and Kalshi;
# make sure a slip taken on Novig isn't better on Kalshi). The Ladder tab then shows each slip at
# whichever of the two pays more (Max, the same day: make ladders adaptive), so Kalshi is asked for
# every slip Novig prices, not only the ones that are plays on Novig: ev is the Novig EV% under
# which it is not asked (-100: none), best first. max: asks a pass. stake: dollars a request is sized at.
KALSHI_LOOK = {"ev": -100.0, "max": 150, "stake": 100.0, "nfl": None}
KALSHI_FIELDS = ("kalshi_x", "kalshi_ev", "kalshi_qk", "kalshi_quote", "kalshi_why", "kalshi_url", "kalshi_at", "kalshi_legs")


def kalshi_same(c, league):
    """A Novig slip as the same bet on Kalshi: ([{"id", "event"} a leg], its game's
    page on Kalshi, None), or (None, None, why) when Kalshi does not list every
    leg on the same line (its milestones are 5 points or 10 yards apart where
    Novig's ladder has every line). An Over is Yes on the milestone: Over 24.5
    is "25+". Reads Kalshi's open props once a run; no key needed."""
    import scan_kalshi
    nfl = league == "nfl"
    try:
        if nfl and KALSHI_LOOK["nfl"] is None:
            KALSHI_LOOK["nfl"] = scan_kalshi.kalshi_props(series=scan_kalshi.NFL_SERIES)
        if not nfl and not KALSHI["props"]:   # not read yet, or the fair values' read failed: once more
            KALSHI["props"] = scan_kalshi.kalshi_props()
    except (SystemExit, Exception) as e:  # noqa: BLE001
        return None, None, f"Kalshi's props could not be read ({e})"
    who = (KALSHI_LOOK["nfl"] if nfl else KALSHI["props"]).get(novig.norm(c["player"]))
    if not who:
        return None, None, "Kalshi lists no props for him"
    legs = []
    for L in c["legs"]:
        k = next((k for k in who["stats"].get(L["stat"], []) if k["line"] == L["line"]), None) if L["side"] == "over" else None
        if not k:
            return None, None, f"Kalshi does not list {leg_text(L)}"
        legs.append({"id": k["ticker"], "event": k["event"]})
    game = "kxnflgame" if nfl else "kxnbagame"
    return legs, f"https://kalshi.com/markets/{game}/game/{game}-{who['game'].lower()}", None


def kalshi_look(c, league, stake=None, kelly=0.25):
    """Kalshi's price for a row Novig has priced, as the fields to put on it:
    kalshi_x (what $1 pays on the same slip after Kalshi's taker fee),
    kalshi_ev and kalshi_qk (EV and quarter-Kelly units at this row's fair
    value), kalshi_quote (Yes a contract before the fee), kalshi_legs (the
    legs as Kalshi markets, for the Bet button) and kalshi_url; or kalshi_why
    where there is no price. One
    request for quote, signed with the server's Kalshi key (scan_kalshi.ask);
    nothing is accepted. Raises scan_kalshi.Refused, and SystemExit when the
    key is not set."""
    import scan_kalshi
    legs, url, why = kalshi_same(c, league)
    if not legs:
        return {"kalshi_why": why, "kalshi_at": time.time()}
    yes, why = scan_kalshi.ask({"legs": legs}, types.SimpleNamespace(stake=stake or KALSHI_LOOK["stake"], wait=3.0, polls=2))
    if not yes:
        return {"kalshi_why": why, "kalshi_url": url, "kalshi_legs": legs, "kalshi_at": time.time()}
    x, p = scan_kalshi.slip_x(yes), 1 / c["fair_x"]
    return {"kalshi_x": x, "kalshi_ev": x * p - 1, "kalshi_qk": max(0.0, (p * (x - 1) - (1 - p)) / (x - 1)) * kelly * 100,
            "kalshi_quote": yes, "kalshi_url": url, "kalshi_legs": legs, "kalshi_at": time.time()}


def kalshi_set(c, got):
    """Put a look's fields on the row, dropping the last look's."""
    for k in KALSHI_FIELDS:
        c.pop(k, None)
    c.update(got)
    return c


def leg(stat, row, side):
    p = row["fo"] if side > 0 else row["fu"]
    return {"stat": stat, "side": "over" if side > 0 else "under", "line": row["line"], "p": p,
            "fair": sgp.american(p), "width": row["spread"], "id": row["ids"]["over" if side > 0 else "under"],
            **({"kal": row["kal"]} if row.get("kal") else {})}


def leg_text(L):
    """'13+ PTS' for Over 12.5 (Novig's "13+ Points · Yes"), 'U26.5 PTS' for an Under."""
    if L["side"] == "over":
        return f"{math.floor(L['line']) + 1}+ {LABEL[L['stat']]}"
    return f"U{L['line']:g} {LABEL[L['stat']]}"


def nfl_candidates(markets, by, a):
    """NFL: Over + Over, and Under + Under, at main lines on each pair with r
    at least --min-r, most lift over independent legs first. Same shapes as
    candidates()."""
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
            for side in (1, -1) if a.unders else (1,):   # Under + Under at the same r
                if side < 0 and any(main[s]["line"] < 1 for s in (x, y) if s not in ("td", "ptd")):
                    continue   # U0.5 receptions is U any yards: one leg, not two
                la, lb = leg(x, main[x], side), leg(y, main[y], side)
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
# QB stat + his back's stat that go against each other (r by the back's
# carries): asked Over + Under and Under + Over.
STACK_AGAINST = (("att", "car"), ("pyds", "ryds"))
# Game lines a prop is asked with, and Novig's market type for each. "win" is
# the moneyline; the h1 ones are the first half's total, spread and moneyline.
LINE_TYPES = {"over": "TOTAL", "cover": "SPREAD", "win": "MONEY", "tt": "TEAM_TOTAL",
              "h1over": "TOTAL_1H", "h1cover": "SPREAD_1H", "h1win": "MONEY_1H"}


def role_r(table, vol, at=None, **match):
    """The role's r from nfl_stack_correlations.json: the row matching
    `match` whose volume bucket holds `vol` (targets or carries a game).
    Passing TDs are fitted at 2+ and again at 3+ (rows with `at` 1.5 and
    2.5): `at` is the passing-TD leg's own line, and the row fitted nearest
    it is used (2+ when no line is given). At 3+ the r with a receiver's TD
    is lower than at 2+ and the r with the team total higher."""
    rows = [e for e in table if all(e.get(k) == v for k, v in match.items())]
    if not rows:
        return None
    want = 1.5 if at is None else at
    near = min(abs(e.get("at", want) - want) for e in rows)
    rows = sorted((e for e in rows if abs(e.get("at", want) - want) == near), key=lambda e: e["min"])
    if rows[0]["by"] is None:
        return rows[0]["r"]
    if vol is None or vol < rows[0]["min"]:
        return None
    # Between the middles of two volume buckets the r is read off the straight
    # line through them, not the bucket's own: a receiver at 5.25 targets is
    # nearer the 3-5 bucket (PTD·TD 0.473) than the 5-7 one's middle (0.518).
    # The open top bucket's middle is taken half the bucket below's width up.
    mids = [(e["min"] + e["max"]) / 2 if e["max"] is not None else
            e["min"] + ((e["min"] - rows[i - 1]["min"]) / 2 if i else 0.0) for i, e in enumerate(rows)]
    return price.interp(list(zip(mids, (e["r"] for e in rows))), vol)


# Touchdowns a carry and a target are worth to a receiver (nflverse 2017-2026,
# WR 0.0385 / 0.0486, TE 0.0781 / 0.0547), and the share of a typical
# receiver's touchdowns that are rushing (3%: the role r's already carry it).
TD_PER = {"WR": (0.0385, 0.0486), "TE": (0.0781, 0.0547)}
RUSH_TYPICAL = 0.03


def rush_share(p, vol):
    """The share of a receiver's scoring that is on the ground beyond a
    typical receiver's, from his carries and targets a game (0 for one who is
    not handed the ball, or where the data has no carries for him)."""
    per = TD_PER.get(p.get("group"))
    car, tgt = vol(p, "car_mean"), vol(p, "tgt_mean")
    if not per or not car or not tgt:
        return 0.0
    s = car * per[0] / (car * per[0] + tgt * per[1])
    return max(0.0, (s - RUSH_TYPICAL) / (1 - RUSH_TYPICAL))


def rush_r(r, share, a=0.5, td=0.25):
    """A QB's passing leg with a receiver's anytime TD, for a receiver who
    also scores on the ground (Max, 11-22: Deebo Samuel isn't a traditional
    WR). The role r is a receiver's whose touchdowns are catches; a rushing
    touchdown is not a passing one, and a back's TD by carries has no r with
    his QB's passing TDs (0.00). So his TD is split into a receiving one, at
    r, and a rushing one, at none, and the r returned is the one that prices
    the two together (read at even money on the QB's leg and a 25% TD)."""
    if share < 0.02 or r is None:
        return r
    lam = -math.log(1 - td)
    rec, rush = 1 - math.exp(-(1 - share) * lam), 1 - math.exp(-share * lam)
    j = sgp.joint(r, a, rec)
    want = j + (a - j) * rush
    lo, hi = (0.0, r) if r > 0 else (r, 0.0)
    for _ in range(30):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if sgp.joint(mid, a, td) < want else (lo, mid)
    return (lo + hi) / 2


def stack_r(table, p, vol, qs, ts, at=None):
    """role_r for a QB's leg with his receiver's, by the receiver's targets;
    his TD's r comes down by how much of his scoring is on the ground."""
    r = role_r(table, vol(p, "tgt_mean"), at, qb=qs, stat=ts, pos=p["group"], by="tgt")
    return rush_r(r, rush_share(p, vol)) if ts == "td" else r


def ptd_at(stat, line):
    """`at` for role_r: the leg's line when it is passing TDs, else None."""
    return line if stat == "ptd" else None


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
        if getattr(a, "events", None) and eid not in a.events:
            continue   # --events: not one of the games asked for
        people.setdefault(eid, {}).setdefault(p["team_abbr"], []).append((p, main, starts))
    return S, events, people, vol


def prop_leg(p, s, main, who="", side=1):
    L = leg(s, main[s], side)
    L["text"] = f"{who}{leg_text(L)}"
    return L


SIDED = ("cover", "win", "h1cover", "h1win")   # lines whose r depends on who is favoured


def side_of(ev, team):
    """'dog', 'even' or 'fav': his team against today's spread (3.5 points
    either way), from Novig's main spread, else its moneyline (63.5% is
    about 3.5 points). None when neither has a tight book."""
    ms = ev["lines"].get("SPREAD", [])
    if ms:
        m = min(ms, key=lambda m: (abs(m["p"][0] - 0.5) + m["spread"], -m["volume"]))
        for n in m["names"]:
            who, _, pts = n.partition(" ")
            try:
                if who == team:   # "TEN +10.5": he gets points, so favoured by -10.5
                    return "dog" if float(pts) >= 3.5 else "fav" if float(pts) <= -3.5 else "even"
            except ValueError:
                pass
    for m in ev["lines"].get("MONEY", []):
        for n, q in zip(m["names"], m["p"]):
            if n.split()[0] == team:
                return "fav" if q >= 0.635 else "dog" if q <= 0.365 else "even"
    return None


def line_r(S, vol, p, s, line, side=None, at=None):
    """The role's r between his stat and a game line (`at`: a passing-TD
    leg's own line, see role_r). A back's rushing and
    his TD go by his carries, everything else by targets; a QB has one role.
    With the spread, the moneyline and their first-half versions the r is the
    one for his team's side of the spread (a QB's attempts go against his
    team covering at -0.44 as a favourite and -0.15 as an underdog)."""
    by_ = None if p["group"] == "QB" else "car" if p["group"] == "RB" and s in ("ryds", "car", "rry", "td") else "tgt"
    v = by_ and vol(p, by_ + "_mean")
    r = role_r(S["game"], v, at, line=line, stat=s, pos=p["group"], by=by_, side=side) if side and line in SIDED else None
    return r if r is not None else role_r(S["game"], v, at, line=line, stat=s, pos=p["group"], by=by_, side=None)


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
    total whatever the prop.
    Unders (unless --no-unders), with the same allowance again: each stack
    Under + Under, a QB's pass attempts or passing yards against his back's
    carries or rushing yards as Over + Under both ways (STACK_AGAINST), and
    each prop's Under with the line's other side. The r is the Overs': the
    copula r that gives how often both Overs hit gives both Unders too."""
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
                    mine, unders = [], []
                    for qs, ts in STACK_PAIRS + (STACK_MORE if a.scope == "all" else ()):
                        r = stack_r(S["stack"], p, vol, qs, ts, ptd_at(qs, qmain[qs]["line"]) if qs in qmain else None)
                        if qs in qmain and ts in main and r is not None and r >= a.min_r:
                            mine.append(row(p, starts, prop_leg(qb, qs, qmain, who), prop_leg(p, ts, main), r, "stack", 7))
                            unders.append(row(p, starts, prop_leg(qb, qs, qmain, who, -1), prop_leg(p, ts, main, side=-1), r, "stack", 7))
                    for qs, ts in STACK_AGAINST:   # one Over, the other Under
                        r = role_r(S["stack"], vol(p, "car_mean"), qb=qs, stat=ts, pos=p["group"], by="car")
                        if qs in qmain and ts in main and r is not None and -r >= a.min_r:
                            unders += [row(p, starts, prop_leg(qb, qs, qmain, who, q), prop_leg(p, ts, main, side=-q), -r, "stack", 7)
                                       for q in (1, -1)]
                    out += sorted(mine, key=lambda c: -c["r"])[:a.per]
                    if a.unders:   # his --per best with an Under in them, on top of the Overs
                        out += sorted(unders, key=lambda c: -c["r"])[:a.per]
                continue
            side = side_of(ev, team)
            for p, main, starts in ps:
                overs, unders = [], []
                for s in main:
                    for line in LINE_TYPES:
                        r = line_r(S, vol, p, s, line, side, ptd_at(s, main[s]["line"]))
                        if r is None or abs(r) < a.line_r:
                            continue
                        lb = line_leg(ev, p, team, line, r)   # his team's side when r > 0, the other when r < 0
                        if lb:
                            overs.append(row(p, starts, prop_leg(p, s, main), lb, abs(r), line, 8))
                        lb = a.unders and line_leg(ev, p, team, line, -r)   # his Under with the line's other side
                        if lb:
                            unders.append(row(p, starts, prop_leg(p, s, main, side=-1), lb, abs(r), line, 8))
                for mine in (overs, unders):   # the same allowance for each
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


# A QB prop + his receiver's prop + a game line hits less often than the
# three pair r's say: the pairs each reproduce their own history, the three
# together don't quite. Ten seasons, each game priced at the rates of that
# player-season's other games (11-15): 2+ pass TDs + WR TD + Over 1,699 hits
# against 1,802 modelled (0.94), with the team total 0.96, pass yards +
# receiving yards + Over 0.96, 3+ pass TDs 0.93, tight ends 0.96, pass yards
# + TD + Over 0.98. The slip's joint is scaled by this.
STACKLINE_FIX = 0.95


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
        fav = side_of(ev, team)
        for line in LINE_TYPES:
            ra = line_r(S, vol, pa, la["stat"], line, fav, ptd_at(la["stat"], la["line"]))
            rb = line_r(S, vol, pb, lb["stat"], line, fav, ptd_at(lb["stat"], lb["line"]))
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
                          for r in [stack_r(S["stack"], p, vol, qs, ts, ptd_at(qs, Q[qs]["line"]))]
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
                    if shape == "stackline":
                        j *= STACKLINE_FIX
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
# The major leagues only (Max, 11-16): the top five, which the correlations
# were measured on, and the Champions League. MLS and Liga MX added 11-20
# (Max), priced on the top five's correlations: measured alone on 4,871 and
# 3,365 matches, the top five's fair value is within one standard error of
# each league's counted hit rate for every shape at 50-60% and 60-70%
# favourites, and under it more often than over ("by_league" in
# soccer_corner_correlations.json). Left out: Europa League, UEFA Nations
# League, FIFA World Cup, FIFA Club World Cup.
SOCCER_LEAGUES = ("EPL", "Serie A", "La Liga", "Bundesliga", "Ligue 1", "Champions League", "MLS", "Liga MX")


SOCCER_CORNERS = os.path.join(HERE, "..", "..", "..", "public", "data", "soccer_corner_correlations.json")
try:
    SOCCER_R = json.load(open(SOCCER_CORNERS))
except (OSError, ValueError):
    SOCCER_R = {}
SOCCER_DOG_MIN = 0.26      # the mirror slip is asked in close games only (Max, 11-20: no big underdogs): the underdog is at least this to win, about +285


def soccer_candidates(a):
    """Favourite ML + goals Over + favourite corners Under + underdog corners
    Over, per match, against the unrelated-legs price. Every leg's fair value
    is Pinnacle's no-vig price on that line (pinnacle.py), never Novig's own
    book (Max, 11-20): a match Pinnacle doesn't list, or a leg on a line it
    doesn't price, is not asked."""
    out, failed, alts, seen_alt = [], [], [], set()
    try:
        import pinnacle
        pin = pinnacle.board()
    except Exception as e:
        raise SystemExit(f"Pinnacle didn't answer ({type(e).__name__}): soccer fair values are Pinnacle's only, so nothing was priced")
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
            if len(o) != 2:
                continue
            # Novig's own book on the market, where it has one on both sides.
            # A corners or goals market needs none (Max, 11-20): its fair
            # value is Pinnacle's, so a one-sided or empty book is no reason
            # to skip the line. The win markets still need theirs: it is how
            # the favourite is told from the underdog and the match checked
            # against Pinnacle's.
            p, width = None, None
            if all(x.get("bid") for x in o):
                b0, b1 = float(o[0]["bid"]["price"]), float(o[1]["bid"]["price"])
                if 0 < b0 < 1 - b1 < 1:
                    p, width = sgp.devig_worst(1 - b1, 1 - b0), 1 - b1 - b0
            if p is None and m["marketType"] == "MONEYLINE_3_WAY_WIN":
                continue
            ev.setdefault(m["eventId"], []).append(
                {"type": m["marketType"], "desc": m["description"], "strike": m.get("strike"), "starts": m["startsTs"],
                 "subj": o[0].get("subjectId"), "p": p, "width": width, "ids": (o[0]["outcomeId"], o[1]["outcomeId"])})
        for eid, ms in ev.items():
            wins = sorted((m for m in ms if m["type"] == "MONEYLINE_3_WAY_WIN" and m["width"] <= 0.08),
                          key=lambda m: -m["p"][0])
            if len(wins) < 2:
                continue
            fav, dog = (m["desc"].replace(" MONEYLINE_3_WAY_WIN", "") for m in wins[:2])
            subj = {fav: wins[0]["subj"], dog: wins[1]["subj"]}

            def his(m, team):
                """Is this corners market the team's? By Novig's id for the
                team, which the win market shares: the names differ too often
                (Man Utd / Manchester United FC, Inter Miami / Club
                Internacional de Futbol Miami, nearly all of Liga MX), and a
                match whose names differ was dropped without a word."""
                if m["type"] != "TEAM_TOTAL_CORNERS":
                    return False
                return m["subj"] == subj[team] if m["subj"] and subj[team] else m["desc"].startswith(team + " ")

            game, fside = pinnacle.match(pin, fav, dog, wins[0]["starts"] / 1000, wins[0]["p"][0])
            if not game:
                continue
            dside = "away" if fside == "home" else "home"

            def crn(m, side, way):
                return game["corners"].get((side, float(m["strike"])), {}).get(way)

            def corners(team, side):
                """The team's line nearest 50/50 among the lines Pinnacle prices (by its price)."""
                sharp = [m for m in ms if his(m, team) and crn(m, side, "over")]
                return min(sharp, key=lambda m: abs(crn(m, side, "over")[0] - 0.5)) if sharp else None
            fc, dc = corners(fav, fside), corners(dog, dside)
            if not fc or not dc:
                continue

            def L(m, i, stat, text, sharp=None):
                """sharp: Pinnacle's (fair chance, American price) on this leg:
                every leg has one. width and novig_p are None where Novig has
                no two-sided book on the market."""
                mine = m["p"][i] if m["p"] else None
                return {"stat": stat, "side": "under" if i else "over", "line": float(m["strike"] or 0), "p": sharp[0],
                        "fair": sgp.american(sharp[0]), "width": m["width"], "id": m["ids"][i], "text": text, "sharp": True,
                        "novig_p": mine, "books": f"Pinnacle {sharp[1]:+d}, " + (f"Novig's book says {sgp.american(mine):+d}" if mine
                                                                            else "Novig has no two-sided book")}
            base = [L(wins[0], 0, "ml", f"{fav} win", game["ml"][fside]),
                    L(fc, 1, "crn", f"{fav} U{fc['strike']} corners", crn(fc, fside, "under")),
                    L(dc, 0, "crn", f"{dog} O{dc['strike']} corners", crn(dc, dside, "over"))]
            band = next((b for b in SOCCER_R.get("by_fav", []) if b["fav"][0] <= base[0]["p"] < b["fav"][1] + 1e-9), None)

            def slip(shape, legs, goals=None, alt=None):
                """shape 'fav': favourite wins (+ goals Over) + his corners
                Under + the underdog's Over; 'dog': underdog wins + the
                favourite's corners Over + the underdog's Under. The joint
                is the Gaussian copula's at the measured pair r's for this
                strength of favourite, times the shape's scale (see
                scripts/soccer_corner_correlations.py); with no correlations
                file, the old lift at the main lines."""
                ps, unrelated = [x["p"] for x in legs], math.prod(x["p"] for x in legs)
                if band:
                    r, g = band["r"], f"o{goals.replace('.', '')}" if goals else None
                    if shape == "dog":
                        prs, name = {(0, 1): r["dw_fo"], (0, 2): r["dw_du"], (1, 2): r["fu_do"]}, "dog"
                    elif g:
                        prs, name = {(0, 1): r[f"fw_{g}"], (0, 2): r["fw_fu"], (0, 3): r["fw_do"], (1, 2): r[f"fu_{g}"],
                                     (1, 3): r[f"do_{g}"], (2, 3): r["fu_do"]}, f"fav_{g}"
                    else:
                        prs, name = {(0, 1): r["fw_fu"], (0, 2): r["fw_do"], (1, 2): r["fu_do"]}, "fav"
                    R = [[1.0 if i == k else prs[(min(i, k), max(i, k))] for k in range(len(ps))] for i in range(len(ps))]
                    j = (price.tri_joint(ps, R) if len(ps) == 3 else price.quad_joint(ps, R)) * band["check"][name]["scale"]
                    rs = [round(v, 2) for v in prs.values()]
                else:
                    if shape == "dog" or alt:
                        return None
                    j, rs = unrelated * next(v for top, v in SOCCER_LIFT[goals] if base[0]["p"] <= top), None
                j = min(j, 0.99, min(ps))
                c = {"key": ",".join(x["id"] for x in legs), "tier": 5, "player": f"{fav} v {dog}", "id": eid,
                     "team": lg, "starts": wins[0]["starts"], "legs": [dict(x) for x in legs], "label": " · ".join(x["text"] for x in legs),
                     "r": None, "j": j, "forced": False, "devig_r": None, "pair_rs": rs,
                     "lift": j / unrelated, "unrelated_x": 1 / unrelated, "sharp": sum(1 for x in legs if x.get("sharp")),
                     "rough": False}   # every leg is Pinnacle's price
                if alt:
                    c.update(alt=alt["key"], alt_of=alt["label"])
                return c

            def beside(team, side, m0, i, way):
                """The team's corner legs on the next line each way from m0
                (one easier, one harder), where Pinnacle prices that line."""
                v = []
                for m in ms:
                    if not his(m, team) or m["strike"] == m0["strike"]:
                        continue
                    sharp = crn(m, side, way)
                    if not sharp:
                        continue
                    leg = L(m, i, "crn", f"{team} {'O' if i == 0 else 'U'}{m['strike']} corners", sharp)
                    if ALT_P[0] <= leg["p"] <= ALT_P[1]:
                        v.append(leg)
                near = lambda xs: [min(xs, key=lambda x: abs(x["line"] - float(m0["strike"])))] if xs else []   # noqa: E731
                p0 = L(m0, i, "crn", "", crn(m0, side, way))["p"]
                return near([x for x in v if x["p"] > p0]) + near([x for x in v if x["p"] < p0])

            def moved(shape, legs, c, spots):
                """c with one corner leg moved a line: [(index in legs, team, Pinnacle side, market, outcome, way)]."""
                for k, team, side, m0, i, way in spots:
                    for x in beside(team, side, m0, i, way):
                        v = slip(shape, [x if n == k else y for n, y in enumerate(legs)], alt=c)
                        if v and v["key"] not in seen_alt:
                            seen_alt.add(v["key"])
                            alts.append(v)
            c = slip("fav", base)
            out.append(c)
            if a.alts and band:
                moved("fav", base, c, [(1, fav, fside, fc, 1, "under"), (2, dog, dside, dc, 0, "over")])
            for line in ("1.5", "2.5"):
                t = next((m for m in ms if m["type"] == "TOTAL" and m["strike"] == line), None)
                sharp = game["goals"].get(float(line), {}).get("over")
                if t and sharp:
                    out.append(slip("fav", [base[0], L(t, 0, "tot", f"Over {line}", sharp)] + base[1:], goals=line))
            # The mirror (Max, 11-16): a favourite who is behind piles up
            # corners. Close games only (Max, 11-20): no slip on a big
            # underdog to win.
            dw = L(wins[1], 0, "ml", f"{dog} win", game["ml"][dside])
            if band and dw["p"] >= SOCCER_DOG_MIN and wins[1]["width"] <= 0.08:
                mirror = [dw,
                          L(fc, 0, "crn", f"{fav} O{fc['strike']} corners", crn(fc, fside, "over")),
                          L(dc, 1, "crn", f"{dog} U{dc['strike']} corners", crn(dc, dside, "under"))]
                c = slip("dog", mirror)
                out.append(c)
                if a.alts:
                    moved("dog", mirror, c, [(1, fav, fside, fc, 0, "over"), (2, dog, dside, dc, 1, "under")])
    if failed and not out:
        raise SystemExit("Novig's catalog didn't answer for " + ", ".join(failed))
    out = out[:a.max] if a.max else out
    keys = {c["key"] for c in out}
    return out + [v for v in alts if v["alt"] in keys and v["key"] not in keys], {}


ALT_P = (0.25, 0.75)       # a leg moved a line keeps a fair chance inside this
CFB_KAPPA = 0.5            # corr(favourite's margin, total) = CFB_KAPPA x spread / total
# Per board: Novig's league, the margin and total sd where a game's ladder is
# too short to fit, and whether the underdog-moneyline slips are asked.
# pin: team-total and first-half legs take Pinnacle's no-vig price (Novig's
# books on those are too wide in college basketball), and the slips with them are asked.
# own: the same slips, and the first-half total's, on Novig's own team-total
# and first-half books (tight in college football).
LINE_BOARDS = {"cfb": {"league": "NCAAF", "sd": (14.6, 15.0), "dogml": True, "pin": False, "own": True},
               "cbb": {"league": "NCAAB", "sd": (12.0, 16.5), "dogml": False, "pin": True, "own": False}}
CBB_LINES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "public", "data", "cbb_line_correlations.json")
CFB_MIN_DOG = 0.10         # no underdog-moneyline slips on a longer shot than this


def cfb_fit(points, default_sd):
    """(line, P(X > line)) pairs -> (mean, sd) of a normal by least squares on
    z. Under four points, or a fitted sd outside 8 to 22, the sd is the
    default and the mean comes from the line nearest even money."""
    pts = [(x, sgp.nppf(p)) for x, p in points if 0.08 < p < 0.92]
    if len(pts) >= 4:
        n, sx, sz = len(pts), sum(x for x, _ in pts), sum(z for _, z in pts)
        sxx, sxz = sum(x * x for x, _ in pts), sum(x * z for x, z in pts)
        b = (n * sxz - sx * sz) / ((n * sxx - sx * sx) or 1e-9)   # z = a + b x = (mu - x) / sd
        if b < 0 and 8 <= -1 / b <= 22:
            return -(sz - b * sx) / n / b, -1 / b
    x, p = min(points, key=lambda q: abs(q[1] - 0.5))
    return x + default_sd * sgp.nppf(p), default_sd


def cbb_r(measured, shape, spread):
    """A CBB shape's measured r at this size of spread ({"r", "n"}), or None
    for a shape that wasn't measured. Its curve by spread where the curve is
    a real change (cbb_line_correlations.py: both team totals Under falls
    from +0.37 to +0.22 at a 33-point spread; DraftKings paid more than the
    one-r fair on those, 11-17), else the all-games r. Spread bands on their
    own were tried first: four bands missed the fall and nine were noise."""
    v = (measured.get("shapes") or {}).get(shape)
    if not v:
        return None
    c = v.get("curve")
    if not (c and c["used"]):
        return v["all"]
    x = min(max(spread, c["at"][0]), c["at"][-1])
    i = min(int(x - c["at"][0]), len(c["at"]) - 2)
    r = c["r"][i] + (c["r"][i + 1] - c["r"][i]) * (x - c["at"][i])
    return {"r": round(r, 3), "n": v["all"]["n"]}


def cfb_candidates(a, listed=None):
    """College football or basketball slips across one game's lines (see the module docstring).
    listed (scan_kalshi.py's college football board): called once a game with its name and
    Novig markets, it returns None to leave the game out, or a test a leg must pass to be put
    on a slip (the line is on the other site too). The model is still fitted to every line."""
    board = LINE_BOARDS[a.league]
    items = novig.catalog({"league": board["league"], "eventStatus": "OPEN_PREGAME",
                           "marketType": "MONEY,SPREAD,TOTAL" + (",TEAM_TOTAL" if board["dogml"] or board["pin"] else "")
                                         + (",SPREAD_1H" if board["pin"] or board["own"] else "")
                                         + (",TOTAL_1H" if board["own"] else "")})
    pin = []
    if board["pin"]:
        try:
            import pinnacle
            pin = pinnacle.lines(board["league"])
        except Exception as e:
            print(f"Pinnacle didn't answer ({type(e).__name__}): no team-total or first-half slips", file=sys.stderr)
    # Measured leg-pair correlations by shape and size of spread
    # (scripts/cbb_line_correlations.py); a shape not in it keeps the model's r.
    measured = {}
    if a.league == "cbb" and os.path.exists(CBB_LINES):
        measured = json.load(open(CBB_LINES))

    measured_r = lambda shape, spread: cbb_r(measured, shape, spread)   # noqa: E731
    games = {}
    for m in items:
        games.setdefault(m["eventId"], []).append(m)
    out, alts, seen_alt = [], [], set()
    for eid, ms in games.items():
        money = next((m for m in ms if m["marketType"] == "MONEY"), None)
        name = next((m["description"].rsplit(" t", 1)[0] for m in ms if m["marketType"] == "TOTAL" and " @ " in m["description"]), None)
        tw = money and two_way(money)
        if not name:
            continue
        on = listed(name, ms) if listed else None
        if listed and not on:
            continue
        if tw:
            f = 0 if tw["p"][0] >= 0.5 else 1
            fav, dog = tw["names"][f], tw["names"][1 - f]
        else:
            # No two-sided moneyline (a 30-point favourite): the favourite is
            # the side giving points on the spread nearest even money.
            sps = [t for t in (two_way(m) for m in ms if m["marketType"] == "SPREAD") if t]
            if not sps:
                continue
            t = min(sps, key=lambda t: abs(t["p"][0] - 0.5) + t["spread"])
            f = 0 if t["names"][0].rpartition(" ")[2].startswith("-") else 1
            fav, dog = (t["names"][i].rpartition(" ")[0] for i in (f, 1 - f))
        sub = {}   # Novig's subject id -> the team's short name, as the spread and moneyline spell it
        for m in ms:
            if m["marketType"] in ("MONEY", "SPREAD"):
                for o in m["outcomes"]:
                    sub[o.get("subjectId")] = o["name"] if m["marketType"] == "MONEY" else o["name"].rpartition(" ")[0]
        away, _, home = name.partition(" @ ")
        pg = None
        if pin:
            full = {m["outcomes"][0].get("subjectId"): m["description"].rsplit(" ", 2)[0] for m in ms if m["marketType"] == "TEAM_TOTAL"}
            ids = {v: k for k, v in sub.items()}
            both_names = lambda t: [t] + ([full[ids[t]]] if ids.get(t) in full else [])   # noqa: E731
            pg = pinnacle.college_match(pin, both_names(away), both_names(home), ms[0]["startsTs"] / 1000)
        legs = []   # every side of every line with a fair value: Novig's two-sided book, or Pinnacle's price
        for m in ms:
            t, typ = two_way(m), m["marketType"]
            half = typ.endswith("_1H")
            for i, o in enumerate(m["outcomes"]):
                L = {"id": o["outcomeId"], "line": float(m["strike"]), "side": "over", "half": half}
                if typ == "MONEY":
                    L.update(stat="ml", team=o["name"], text=f"{o['name']} ML")
                    key, des = (0, "moneyline", None, 0.0), "home" if o["name"] == home else "away"
                elif typ in ("SPREAD", "SPREAD_1H"):
                    tm, _, ln = o["name"].rpartition(" ")
                    L.update(stat="cover", team=tm, line=float(ln), text=("1H " if half else "") + o["name"])
                    des = "home" if tm == home else "away"
                    key = (1 if half else 0, "spread", None, float(ln) if des == "home" else -float(ln))
                elif typ in ("TOTAL", "TOTAL_1H"):
                    L.update(stat="tot", team=None, side="over" if i == 0 else "under",
                             text=f"{'1H ' if half else ''}{'Over' if i == 0 else 'Under'} {L['line']:g}")
                    key, des = (1 if half else 0, "total", None, L["line"]), L["side"]
                elif typ == "TEAM_TOTAL" and o.get("subjectId") in sub:
                    tm = sub[o["subjectId"]]
                    L.update(stat="tt", team=tm, side="over" if i == 0 else "under",
                             text=f"{tm} team total {'Over' if i == 0 else 'Under'} {L['line']:g}")
                    key, des = (0, "team_total", "home" if tm == home else "away", L["line"]), L["side"]
                else:
                    continue
                # Pinnacle prices the team totals and the first half; the game's
                # own spread, total and moneyline stay on Novig's (tight) book.
                sharp = ((pg["mk"].get(key) or {}).get(des) if pg and (half or L["stat"] == "tt") else None)
                if sharp:
                    L.update(p=sharp[0], fair=sgp.american(sharp[0]), sharp=True, width=t["spread"] if t else 1.0,
                             books=f"Pinnacle {sharp[1]:+d}" + (f", Novig's book says {sgp.american(t['p'][i]):+d}" if t else ""))
                elif t and not (board["pin"] and (half or L["stat"] == "tt")):
                    L.update(p=t["p"][i], fair=sgp.american(t["p"][i]), width=t["spread"])
                else:
                    continue
                legs.append(L)
        fit = [L for L in legs if L["width"] <= 0.05 + 1e-9 and not L["half"] and not L.get("sharp")]   # the ladders the model is fitted to
        sp = [(-L["line"], L["p"]) for L in fit if L["stat"] == "cover" and L["team"] == fav]
        to = [(L["line"], L["p"]) for L in fit if L["stat"] == "tot" and L["side"] == "over"]
        if not sp or not to:
            continue
        (mu_m, sd_m), (mu_t, sd_t) = cfb_fit(sp, board["sd"][0]), cfb_fit(to, board["sd"][1])
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
            # A first-half leg sees half the game: half the variance (the two
            # halves taken as unrelated), and only that half in common with a
            # full-game leg. A first-half spread with the game's spread is 0.71.
            hx, hy = (0.5 if L["half"] else 1.0 for L in (x, y))
            return cov(a1, b1, a2, b2) * min(hx, hy) / math.sqrt(cov(a1, b1, a1, b1) * hx * cov(a2, b2, a2, b2) * hy)

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

        def pick(stat, team=None, side="over", target=0.5, within=0.12, half=False):
            v = [L for L in legs if L["stat"] == stat and L["team"] == team and L["side"] == side and L["half"] == half
                 and (not on or on(L)) and (L.get("sharp") or L["width"] <= a.max_spread + 1e-9) and abs(L["p"] - target) <= within]
            return min(v, key=lambda L: abs(L["p"] - target) + (0 if L.get("sharp") else L["width"])) if v else None
        dog_ml = pick("ml", dog, within=0.5) if board["dogml"] else None
        if dog_ml and dog_ml["p"] < CFB_MIN_DOG:
            dog_ml = None
        under, under_alt = pick("tot", side="under"), pick("tot", side="under", target=0.30, within=0.08)
        dog_tt = pick("tt", dog)
        shapes = [("dogml", None, [dog_ml, under]), ("dogml", None, [dog_ml, under_alt]), ("dogml", None, [dog_ml, under, dog_tt]),
                  ("cover", "fav_cover+over", [pick("cover", fav), pick("tot")]), ("cover", "dog_cover+under", [pick("cover", dog), under])]
        if board["pin"] or board["own"]:
            fav_ttu, dog_ttu = pick("tt", fav, "under"), pick("tt", dog, "under")
            # The underdog covering with his own total Under: no game Under leg,
            # since those two all but force it (63.5 + 63.5 + 27.5 is under a 157.5 total).
            # Both team totals Under is asked before the underdog covering with his own total Under
            # (Max, 11-19: he likes the double Under more), so it is the one priced and alerted first.
            shapes += [("tt", "fav_tt_under+dog_tt_under", [fav_ttu, dog_ttu]), ("tt", "fav_tt_under+under", [fav_ttu, under]),
                       ("tt", "dog_cover+dog_tt_under", [pick("cover", dog), dog_ttu]),
                       ("half", "fav_1h_cover+fav_cover", [pick("cover", fav, half=True), pick("cover", fav)])]
        if board["own"]:
            shapes += [("half", "1h_under+under", [pick("tot", side="under", half=True), under])]
        def row(kind, shape, ls):
            R = [[1.0 if i == j else corr(x, y) for j, y in enumerate(ls)] for i, x in enumerate(ls)]
            seen = measured_r(shape, abs(mu_m)) if shape and len(ls) == 2 else None
            if seen:
                R[0][1] = R[1][0] = seen["r"]
            j = sgp.joint(R[0][1], ls[0]["p"], ls[1]["p"]) if len(ls) == 2 else both_scores(ls)
            return {"key": ",".join(L["id"] for L in ls), "tier": 9, "player": name, "id": eid, "team": board["league"],
                    "starts": ms[0]["startsTs"], "legs": [dict(L) for L in ls], "kind": kind, "shape": shape,
                    "label": " · ".join(L["text"] for L in ls), "forced": False,
                    "r": min(R[i][k] for i in range(len(ls)) for k in range(i)), "j": j,
                    "devig_r": sgp.devig_r(j, ls[0]["p"], ls[1]["p"]) if len(ls) == 2 else None,
                    "sharp": sum(1 for L in ls if L.get("sharp")), **({"games": seen["n"]} if seen else {}),
                    "rough": any(L["width"] > novig.MAX_SPREAD + 1e-9 for L in ls if not L.get("sharp"))}

        def beside(L):
            """The same leg on the next line each way (one easier, one
            harder), where that line has a fair value too."""
            v = [x for x in legs if x["id"] != L["id"] and all(x[k] == L[k] for k in ("stat", "team", "side", "half"))
                 and (x.get("sharp") or x["width"] <= a.max_spread + 1e-9) and ALT_P[0] <= x["p"] <= ALT_P[1]]
            near = lambda xs: [min(xs, key=lambda x: abs(x["line"] - L["line"]))] if xs else []   # noqa: E731
            return near([x for x in v if x["p"] > L["p"]]) + near([x for x in v if x["p"] < L["p"]])
        for kind, shape, ls in shapes:
            if any(L is None for L in ls) or len({L["id"] for L in ls}) < len(ls):
                continue
            c = row(kind, shape, ls)
            out.append(c)
            # The same slip with one leg moved a line (Max, 11-16: U88 + U74
            # paid +230 where U88 + U76 paid +225; Novig's price doesn't move
            # with the line the way the fair value does). Asked only when the
            # slip itself comes back near fair (--alt-gate), see scan().
            if board["pin"] and a.alts and len(ls) == 2:
                for i, L in enumerate(ls):
                    for x in beside(L):
                        v = row(kind, shape, [x if k == i else y for k, y in enumerate(ls)])
                        if v["key"] not in seen_alt:
                            seen_alt.add(v["key"])
                            alts.append(dict(v, alt=c["key"], alt_of=c["label"]))
    out.sort(key=lambda c: c["starts"])
    out = out[:a.max] if a.max else out
    keys = {c["key"] for c in out}
    return out + [v for v in alts if v["alt"] in keys and v["key"] not in keys], {}


NBA_LINES = os.path.join(HERE, "..", "..", "..", "public", "data", "nba_line_correlations.json")
NBA_TEAM = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}   # the data's (ESPN's) code -> Novig's
NBA_TEAM_STATS = ("pts", "reb", "ast", "tpm", "pra")
NBA_MIN_GAMES = 400        # a spread band with fewer games than this uses the all-games r
NBA_AGAINST_R = 0.15       # a prop that goes against his own team covering (a star on a big favourite) is asked from here,
NBA_AGAINST_SPREAD = 11.0  # and only when his team is favoured by this much: on held-out seasons those slips hit 28.8% at 11 to 14
#                            points and 27.4% beyond (unrelated legs: 24.2%, 20.3%), but 26.9% at 8 to 11 (unrelated 26.6%)
NBA_MIN_MINUTES = 20.0     # the prop + line r's are measured on players at 20+ minutes a game: nobody under it is asked
# Slips across one game's own lines: the six that came nearest fair of the 33
# asked on three games (11-13). (shape in the data, its legs.)
NBA_GAME_SHAPES = (("fav_tt_over+dog_tt_over", (("tt", "fav", "over"), ("tt", "dog", "over"))),
                   ("fav_tt_under+dog_tt_under", (("tt", "fav", "under"), ("tt", "dog", "under"))),
                   ("fav_tt_over+over", (("tt", "fav", "over"), ("tot", None, "over"))),
                   ("fav_tt_under+under", (("tt", "fav", "under"), ("tot", None, "under"))),
                   ("dog_ml+under", (("ml", "dog", "over"), ("tot", None, "under"))),
                   ("fav_1h_ml+fav_ml", (("h1ml", "fav", "over"), ("ml", "fav", "over"))))
# A player's prop with a game line: the line in the data -> (kind on the page, the leg, whose).
NBA_PROP_LINES = {"cover": ("cover", "cover", "mine"), "h1cover": ("h1cover", "h1cover", "mine"), "tt": ("tt", "tt", "mine"),
                  "opp_tt": ("tt", "tt", "theirs"), "over": ("over", "tot", None), "h1over": ("h1over", "h1tot", None)}


def nba_role(stat, row):
    """His expected count tonight, which picks his role in the data (roles
    there are season averages). Points and PRA: his main line + 0.5. The
    low counts (rebounds, assists, threes): the Poisson mean whose chance of
    clearing the line is the Over's fair value, since a 2.5 threes line at
    +150 is a 2.3-a-game shooter and one at -110 a 2.9."""
    if stat in ("pts", "pra"):
        return row["line"] + 0.5
    need, lo, hi = math.floor(row["line"]) + 1, 0.01, 60.0
    for _ in range(40):
        mu = (lo + hi) / 2
        term = cdf = math.exp(-mu)
        for k in range(1, need):
            term *= mu / k
            cdf += term
        lo, hi = (mu, hi) if 1 - cdf < row["fo"] else (lo, mu)
    return (lo + hi) / 2


def nba_prop_r(T, stat, avg, ev, my_spread):
    """(the fitted r, the r to price at, player-games behind it) between a
    player's Over at about his median and a game line going his team's way,
    for a player averaging `avg` on a team with this spread (negative:
    favoured): the role's straight-line fit of r on the spread, and that
    fit less one standard error (toward unrelated). (None, None, 0) with no
    such role."""
    for e in T["props"]:
        if e["stat"] == stat and e["ev"] == ev and e["min"] <= avg < e["max"]:
            f = e["fit"]
            x = max(f["lo"], min(f["hi"], my_spread))
            r = f["a"] + f["b"] * x
            se = math.hypot(f["a_se"], (x - f["x0"]) * f["b_se"])
            return r, math.copysign(max(abs(r) - se, 0.0), r), e["all"]["n"]
    return None, None, 0


def nba_team_candidates(d, by, a):
    """NBA Team board (--league nba --kind team): slips with a game line in
    them. Game lines are Novig's own books (spread, total, moneyline, the
    first half's); a team total is Novig's book where it is tight and
    Pinnacle's no-vig price on the same line where it is not.

    props: a player's main-line Over (points, rebounds, assists, threes,
    points + rebounds + assists) with a game line on the side that goes with
    it, and his Under with the other side: his team's spread, his team's
    total, the other team's total, the game total, the first half's spread
    and total. The r is league-wide for a player with that line on a team
    with tonight's spread (nba_line_correlations.json), asked where |r| is
    at least --line-r; each player gets his --per highest, Over and Under.

    game: NBA_GAME_SHAPES across each game's own lines, at each shape's
    measured r for the game's size of spread."""
    T = json.load(open(NBA_LINES))
    items = novig.catalog({"league": "NBA", "eventStatus": "OPEN_PREGAME",
                           "marketType": "MONEY,SPREAD,TOTAL,TEAM_TOTAL,SPREAD_1H,TOTAL_1H,MONEY_1H"})
    try:
        import pinnacle
        pin = pinnacle.lines("NBA")
    except Exception as e:
        pin = []
        print(f"Pinnacle didn't answer ({type(e).__name__}): team totals on Novig's own books only", file=sys.stderr)
    by_event = {}
    for m in items:
        by_event.setdefault(m["eventId"], []).append(m)
    games = {}   # event id -> {name, fav, dog, spread, starts, legs: {(stat, whose, side): [leg]}}
    for eid, ms in by_event.items():
        name = next((m["description"].rsplit(" t", 1)[0] for m in ms if m["marketType"] == "TOTAL" and " @ " in m["description"]), None)
        money = next((t for t in (two_way(m) for m in ms if m["marketType"] == "MONEY") if t), None)
        sps = [t for t in (two_way(m) for m in ms if m["marketType"] == "SPREAD") if t and t["spread"] <= a.max_spread + 1e-9]
        if not name or not money or not sps:
            continue
        f = 0 if money["p"][0] >= 0.5 else 1
        fav, dog = money["names"][f], money["names"][1 - f]
        main = min(sps, key=lambda t: (abs(t["p"][0] - 0.5) + t["spread"], -t["volume"]))
        spread = abs(main["strike"]) if main["p"][0] <= 0.75 else 0.0
        away, _, home = name.partition(" @ ")
        sub, full = {}, {}   # Novig's subject id -> the team's code; code -> full name
        for m in ms:
            if m["marketType"] == "MONEY":
                sub.update({o.get("subjectId"): o["name"] for o in m["outcomes"]})
        for m in ms:
            if m["marketType"] == "TEAM_TOTAL" and m["outcomes"][0].get("subjectId") in sub:
                full[sub[m["outcomes"][0]["subjectId"]]] = m["description"].rsplit(" ", 2)[0]
        pg = pinnacle.college_match(pin, [away] + [full[away]] * (away in full), [home] + [full[home]] * (home in full),
                                    ms[0]["startsTs"] / 1000) if pin else None
        legs = {}
        for m in ms:
            t, typ = two_way(m), m["marketType"]
            h1 = "h1" if typ.endswith("_1H") else ""
            for i, o in enumerate(m["outcomes"]):
                L = {"id": o["outcomeId"], "line": float(m["strike"]), "side": "over"}
                if typ.startswith("MONEY"):
                    k = (h1 + "ml", "fav" if o["name"] == fav else "dog", "over")
                    L.update(stat=h1 + "ml", text=f"{o['name']} {'1H ' if h1 else ''}moneyline")
                elif typ.startswith("SPREAD"):
                    tm, _, ln = o["name"].rpartition(" ")
                    k = (h1 + "cover", "fav" if tm == fav else "dog", "over")
                    L.update(stat=h1 + "cover", line=float(ln), text=o["name"] + (" 1H" if h1 else ""))
                elif typ.startswith("TOTAL"):
                    side = "over" if i == 0 else "under"
                    k = (h1 + "tot", None, side)
                    L.update(stat=h1 + "tot", side=side, text=f"{name}{' 1H' if h1 else ''} {side.capitalize()} {L['line']:g}")
                elif typ == "TEAM_TOTAL" and o.get("subjectId") in sub:
                    tm, side = sub[o["subjectId"]], "over" if i == 0 else "under"
                    k = ("tt", "fav" if tm == fav else "dog", side)
                    L.update(stat="tt", side=side, text=f"{tm} team total {side.capitalize()} {L['line']:g}")
                else:
                    continue
                sharp = None
                if typ == "TEAM_TOTAL" and pg and not (t and t["spread"] <= a.max_spread + 1e-9):
                    sharp = (pg["mk"].get((0, "team_total", "home" if tm == home else "away", L["line"])) or {}).get(side)
                if sharp:   # src: the page's refresh keeps this fair value instead of re-reading Novig's wide book
                    L.update(p=sharp[0], fair=sgp.american(sharp[0]), width=0.0, src="pinnacle",
                             books=f"Pinnacle {sharp[1]:+d}" + (f", Novig's book says {sgp.american(t['p'][i]):+d}" if t else ""))
                elif t and t["spread"] <= a.max_spread + 1e-9:
                    L.update(p=t["p"][i], fair=sgp.american(t["p"][i]), width=t["spread"])
                else:
                    continue
                legs.setdefault(k, []).append(L)
        games[eid] = {"name": name, "fav": fav, "dog": dog, "spread": spread, "starts": ms[0]["startsTs"], "legs": legs}

    def pick(g, k):
        """The leg of this kind nearest 50/50 (a moneyline: the only one), or None."""
        v = [L for L in g["legs"].get(k, []) if "ml" in k[0] or abs(L["p"] - 0.5) <= 0.13]
        return min(v, key=lambda L: abs(L["p"] - 0.5) + L["width"]) if v else None

    def row(g, eid, ls, r, n, kind, who, pid, **more):
        j = sgp.joint(r, ls[0]["p"], ls[1]["p"])
        return dict({"key": ",".join(L["id"] for L in ls), "tier": 2, "player": who, "id": pid, "team": "NBA", "starts": g["starts"],
                     "legs": [dict(L) for L in ls], "kind": kind, "label": " · ".join(L["text"] for L in ls), "r": r, "j": j,
                     "forced": False, "devig_r": sgp.devig_r(j, ls[0]["p"], ls[1]["p"]), "games": n,
                     "sharp": sum(1 for L in ls if L.get("src")),
                     "rough": any(L["width"] > novig.MAX_SPREAD + 1e-9 for L in ls)}, **more)

    out = []
    if a.team in ("all", "game"):
        for eid, g in games.items():
            band = next((i for i, (lo, hi) in enumerate(T["buckets"]) if lo <= g["spread"] < hi), None)
            for shape, ks in NBA_GAME_SHAPES:
                ls = [pick(g, k) for k in ks]
                v = T["shapes"].get(shape)
                if not v or any(L is None for L in ls) or (shape.startswith("dog_ml") and ls[0]["p"] < CFB_MIN_DOG):
                    continue
                m = v["by_spread"][band] if band is not None else None
                # A spread band's own r only where it is a real difference (see cfb_candidates).
                if not (m and m["n"] >= NBA_MIN_GAMES and not m["r_lo"] <= v["all"]["r"] <= m["r_hi"]):
                    m = v["all"]
                out.append(row(g, eid, ls, m["r"], m["n"], "game", g["name"], eid, shape=shape))
    if a.team in ("all", "props"):
        markets = novig.fetch("NBA", NBA_TEAM_STATS)
        key = {novig.norm(n): n for n in by}
        for nm in sorted({novig.player_name(m) for m in markets}):
            p = by.get(key.get(novig.norm(nm)))
            eid = next(m["eventId"] for m in markets if novig.player_name(m) == nm)
            g = games.get(eid)
            team = p and NBA_TEAM.get(p.get("team_abbr"), p.get("team_abbr"))
            if not g or team not in (g["fav"], g["dog"]):
                continue   # no lines for his game, or he has changed teams since the data was built
            now = (p.get("by_season") or {}).get(str(p.get("latest_season"))) or {}
            if ((now if now.get("games", 0) >= 5 else p).get("min_mean") or 0) < NBA_MIN_MINUTES:
                # A bench player's numbers go the other way in a blowout (he
                # plays the fourth quarter): Novig quoted Collier's PRA with
                # Utah +15.5 as if they moved apart, 11-13.
                continue
            me, them = ("fav", "dog") if team == g["fav"] else ("dog", "fav")
            my_spread = -g["spread"] if me == "fav" else g["spread"]
            _, rows = novig.ladder(markets, nm)
            kalshi_blend(nm, rows, a.max_spread)
            mine = []
            for s in NBA_TEAM_STATS:
                ok = [r for r in rows.get(s, []) if usable(r, a.max_spread)]
                if not ok:
                    continue
                main = main_line(ok)
                if abs(main["fo"] - 0.5) > 0.13:
                    continue
                for ev, (kind, stat, whose) in NBA_PROP_LINES.items():
                    if ev not in a.team_lines:
                        continue
                    fit, r, n = nba_prop_r(T, s, nba_role(s, main), ev, my_spread)
                    if fit is None:
                        continue
                    if fit < 0 and kind.endswith("cover"):   # goes against his own team covering
                        if fit > -NBA_AGAINST_R or my_spread > -NBA_AGAINST_SPREAD:
                            continue
                    elif abs(fit) < a.line_r:
                        continue
                    who = {"mine": me, "theirs": them}.get(whose)
                    for over in (1, -1):   # his Over with the side that goes with it, his Under with the other
                        way = over if r > 0 else -over
                        if stat in ("cover", "h1cover"):
                            k = (stat, who if way > 0 else {"fav": "dog", "dog": "fav"}[who], "over")
                        else:
                            k = (stat, who, "over" if way > 0 else "under")
                        lb = pick(g, k)
                        if not lb:
                            continue
                        la = leg(s, main, over)
                        la["text"] = leg_text(la)
                        mine.append(row(g, eid, [la, lb], abs(r), n, kind, p["name"], p["athlete_id"], team=team, role=True,
                                        line=ev, spread=my_spread, fit_r=abs(fit)))
            # His --per highest-r pairings (a stat with a line), each as its Over and its Under slip.
            best = sorted({(c["legs"][0]["stat"], c["line"]): c["r"] for c in mine}.items(), key=lambda kv: -kv[1])[:a.per]
            out += [c for c in mine if (c["legs"][0]["stat"], c["line"]) in dict(best)]
    out.sort(key=lambda c: (c["starts"], -c["j"] / (c["legs"][0]["p"] * c["legs"][1]["p"])))
    return out[:a.max] if a.max else out


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
        kalshi_blend(nm, rows, a.max_spread)
        tight = {s: [r for r in rows.get(s, []) if usable(r, a.max_spread)] for s in STATS}
        main = {s: main_line(v) for s, v in tight.items() if v}
        # A stat whose real main line has a wide book has no main line here:
        # the nearest tight line can be a far milestone (Grant, 11-19: 10.5
        # points 5.5c wide, so 20+ points at +856 was taken as his main line
        # and asked with his threes, a ladder slip on the NBA board).
        for s in list(main):
            two = [r for r in rows.get(s, []) if r.get("mid") is not None]
            if abs(main[s]["line"] - min(two, key=lambda r: abs(r["mid"] - 0.5))["line"]) > 1:
                del main[s]
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
        if a.tier == 1 and not a.pr:
            continue
        for x, y in PAIRS:
            if x not in main or y not in main:
                continue
            r = price.shrunk_r(d, by, p, x, y)[0]
            if a.pr and (x, y) == ("pts", "reb"):
                # Max, 11-19: Points + Rebounds is back on the NBA board, for
                # every player and not big men alone (Burries, a guard, 10+
                # points with 6+ rebounds on Kalshi: Novig paid the same for
                # that slip and this board never asked). Main lines, r at
                # --pr-r or better as on Kalshi NBA, and not held back by his
                # Points + Threes price (`pr`: the quoting loop's gate).
                # Each leg at --pr-leg or better, Kalshi NBA's floor: a "main
                # line" is the tight book nearest even money, and where only a
                # far line is tight that is a long shot (Burries the same
                # evening: 20+ points at 8%, the one tight book on his ladder).
                c = combo(2, r, leg(x, main[x], 1), leg(y, main[y], 1))
                if r >= a.pr_r and a.tier in (0, 1, 2) and min(L["p"] for L in c["legs"]) >= a.pr_leg - 1e-9:
                    rest.append(dict(c, pr=True))
                continue
            if a.tier == 1:
                continue
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


# Two teammates' points Overs. Measured unrelated across the league (+0.02, see
# nba_mate_candidates), but priced at -0.05 since 11-18 (Max's number): one pair can sit well
# off the league's number and its own history is too short to say (Maxey +
# Embiid: points r -0.14 on 47 games together, both 25+ in 34% of them against
# 39% as unrelated legs), and the slip's whole edge is this one number. -0.05
# is a margin for that, not a measurement.
NBA_MATE_R = -0.05
NBA_MATE_MIN = 14.5    # the second scorer's points line is at least this


def nba_mate_candidates(markets, ctx):
    """NBA teammates: each team's two highest points lines, Over + Over.
    Measured on four seasons of box scores (each player's line his median
    over his previous 15 games, 20+ minutes): a team's top two scorers both
    go Over as often as unrelated legs would, r +0.02 on 6,578 team-games
    (two-sigma range -0.03 to +0.06), the same at 20+ and 24+ points a game.
    Pairs don't differ from one another by more than chance (204 pairs with
    40+ games together: their r's spread 0.17, what 78 games each gives by
    itself), so every pair is priced at one number, NBA_MATE_R (the measured r
    less one standard error until 11-18; -0.05 since, see above). Novig prices many of them as if one scorer's night cost
    the other's: 11-16, 16 teams, its quotes implied r -0.05 at the median
    and -0.12 to -0.15 on Jokic + Murray, Davis + Young and Maxey + Brown,
    +6% to +10% against unrelated legs and the same on a second ask.
    Opposing stars it prices about right (8 slips, median -2.7%), and one
    player's Over + Under came back -6% to -30% (6 slips): neither is asked."""
    event = {}
    for m in markets:
        event.setdefault(novig.norm(novig.player_name(m)), m["eventId"])
    teams = {}   # (game, team): the data's team can be out of date, so two teammates must also be in the same game
    for p, main, starts in ctx.values():
        ev = event.get(novig.norm(p["name"]))
        if "pts" in main and p.get("team_abbr") and ev:
            teams.setdefault((ev, p["team_abbr"]), []).append((p, main["pts"], starts))
    out = []
    for (_, team), ps in teams.items():
        ps.sort(key=lambda x: -x[1]["line"])
        if len(ps) < 2 or ps[1][1]["line"] < NBA_MATE_MIN:
            continue
        (pa, ra, starts), (pb, rb, _) = ps[0], ps[1]
        la, lb = leg("pts", ra, 1), leg("pts", rb, 1)
        last = lambda p: p["name"].split(" ", 1)[-1]   # noqa: E731
        j = sgp.joint(NBA_MATE_R, la["p"], lb["p"])
        out.append({"key": f"{la['id']},{lb['id']}", "tier": 2, "player": f"{pa['name']} + {pb['name']}",
                    "id": f"{pa['athlete_id']}+{pb['athlete_id']}", "team": team, "starts": starts, "legs": [la, lb], "kind": "mates",
                    "label": f"{last(pa)} {leg_text(la)} · {last(pb)} {leg_text(lb)}", "r": NBA_MATE_R, "j": j, "forced": False,
                    "devig_r": sgp.devig_r(j, la["p"], lb["p"]),
                    "rough": max(la["width"], lb["width"]) > novig.MAX_SPREAD + 1e-9})
    return out


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
    # When Novig's quote for these legs expires (ms), for the alerts: a price
    # is good for about 30 seconds.
    c["expires"] = novig.EXPIRES.get(",".join(L["id"] for L in c["legs"]))
    return c


def catalog_leagues(league):
    """Novig's league names behind a board."""
    return {"nba": ("NBA",), "nfl": ("NFL",), "nhl": ("NHL",), "soccer": SOCCER_LEAGUES}.get(league) \
        or (LINE_BOARDS[league]["league"],)


def games(league):
    """Open pregame games for the page's game picker (--games): [{id, name,
    starts}], soonest first. The id is Novig's event id, which --events takes."""
    out = {}
    for lg in catalog_leagues(league):
        for m in novig.catalog({"league": lg, "eventStatus": "OPEN_PREGAME", "marketType": "TOTAL,MONEY"}):
            g = out.setdefault(m["eventId"], {"id": m["eventId"], "name": None, "starts": m["startsTs"]})
            if m["marketType"] == "TOTAL" and " @ " in m["description"]:
                g["name"] = m["description"].rsplit(" t", 1)[0]
            elif not g["name"] and len(m["outcomes"]) == 2:
                g["name"] = " v ".join(o["name"] for o in m["outcomes"])
    return sorted((g for g in out.values() if g["name"]), key=lambda g: (g["starts"], g["name"]))


def outcome_events(league):
    """{outcome id: event id} for every open pregame market on the board's
    league(s): which game a slip belongs to, whatever built it."""
    return {o["outcomeId"]: m["eventId"] for lg in catalog_leagues(league)
            for m in novig.catalog({"league": lg, "eventStatus": "OPEN_PREGAME"}) for o in m["outcomes"]}


def requote(c, league, max_spread, unit, kelly):
    """One slip again (the page's refresh button; --requote): (the row with
    today's leg prices, a new Novig quote and EV, None), or (None, why).
    NBA, NFL and NHL legs read off a book are re-read from Novig's catalog
    (one pull) and the fair value rebuilt with the same correlation: for two
    legs the r that gave the row's joint, for three legs with pair r's the
    same three-way joint, otherwise the joint scaled by the legs' move. A
    leg modelled from another line, or whose book has gone wider than it
    was (and than --max-spread), keeps its fair value. Soccer and college
    rows keep theirs too: only the quote is new."""
    if league in ("nba", "nfl", "nhl"):
        where = {o["outcomeId"]: (m, i) for m in novig.catalog({"league": league.upper(), "eventStatus": "OPEN_PREGAME"})
                 for i, o in enumerate(m["outcomes"])}
        if any(L["id"] not in where for L in c["legs"]):
            return None, "a leg is no longer open (the game has started or the line closed)"
        old = [L["p"] for L in c["legs"]]
        for L in c["legs"]:
            m, i = where[L["id"]]
            t = two_way(m) if L.get("from") is None and not L.get("src") else None
            if t and L.get("kal"):   # a line Kalshi lists too: both books again, by the same rule (two_books)
                import scan_kalshi
                st, d = scan_kalshi.call("GET", "/markets/" + L["kal"], signed=False)
                try:
                    kb, ka = float(d["market"]["yes_bid_dollars"]), float(d["market"]["yes_ask_dollars"])
                    kz = min(float(d["market"]["yes_bid_size_fp"]), float(d["market"]["yes_ask_size_fp"]))
                except (KeyError, TypeError, ValueError):
                    kb = ka = kz = None
                b = two_books({"spread": t["spread"], "fo": t["p"][0], "fu": t["p"][1], "bid": 0.001, "ask": 0.999}   # two_way checked the book
                              if t["spread"] <= max_spread + 1e-9 else None, kb, ka, max_spread, ksize=kz) if st == 200 else None
                if b:
                    t = dict(t, p=(b[0], b[1]), spread=b[2])
            if t and t["spread"] <= max(max_spread, L["width"]) + 1e-9:
                L.update(p=t["p"][i], fair=sgp.american(t["p"][i]), width=t["spread"])
        new = [L["p"] for L in c["legs"]]
        if new != old and not c.get("forced"):
            if len(new) == 2:
                lo, hi = -0.99, 0.99   # the r that gave this row's joint
                for _ in range(30):
                    mid = (lo + hi) / 2
                    lo, hi = (mid, hi) if sgp.joint(mid, *old) < c["j"] else (lo, mid)
                c["j"] = sgp.joint((lo + hi) / 2, *new)
                if c.get("devig_r") is not None:
                    c["devig_r"] = sgp.devig_r(c["j"], *new)
            elif len(new) == 3 and c.get("rs"):
                c["j"] = tri_safe(new, c["rs"])
            else:
                c["j"] = min(c["j"] * math.prod(new) / math.prod(old), min(new))
            c["rough"] = max(L["width"] for L in c["legs"]) > novig.MAX_SPREAD + 1e-9
    quote, why = novig.parlay([L["id"] for L in c["legs"]])
    if not quote:
        return None, why
    kalshi_set(c, {})   # Kalshi's price from the last look does not stay beside a new Novig one
    return finish(c, quote, unit, kelly), None


def scan(a, emit):
    """Quote every candidate; emit(event dict) as things happen. Returns the priced rows."""
    t0 = time.time()
    if a.league == "soccer":
        d = {"generated_at": time.strftime("%Y-%m-%d")}
        cands, ctx = soccer_candidates(a)
        stats, rfun, a.tri = (), None, 0
    elif a.league in LINE_BOARDS:
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
    elif a.kind == "team":
        d, by = sgp.load()
        cands, ctx = nba_team_candidates(d, by, a), {}
        stats, rfun, a.tri, a.stars = (), None, 0, False
    else:
        d, by = sgp.load()
        markets = novig.fetch()
        cands, ctx = candidates(markets, d, by, a)
        if a.scope != "ladder" and a.mates:   # not under --tier: the NBA board runs at --tier 1
            cands = cands + nba_mate_candidates(markets, ctx)
        stats, rfun = STATS, lambda p, x, y: price.shrunk_r(d, by, p, x, y)[0]
    # Everything else waits for the main-line Points + Threes quotes: a player
    # whose best one isn't above --gate (0%: above fair) gets nothing more
    # asked, no higher lines, other pairs, double-doubles or three-leg slips.
    # Every big play on the 11-10 boards came from a player whose main line
    # was already good, and each quote is an auction sent to every pricer.
    # A player with no Points + Threes price at all (a big with no threes
    # line) has no signal either way, so his few combos are still asked.
    # Each slip is tagged with its game (Novig's event id), and --events
    # keeps only the games picked on the page.
    try:
        where = outcome_events(a.league) if a.events or a.league != "soccer" else {}
    except OSError:
        if a.events:
            raise
        where = {}

    def mine(cs):
        # --max-fair: an NFL slip whose fair value is longer than +600 is not
        # asked at all (Max, 11-15: keep the NFL FVs we scan under +600).
        for c in cs:
            c["event"] = where.get(c["legs"][0]["id"])
        # --before: games starting later than that are left out (Auto-scan
        # prices today's games only).
        # --full-before: a game starting later than that keeps one slip
        # only, its QB's 2+ passing TDs with a teammate's TD (Max, 11-20:
        # Novig's NFL limits are too small until the day before).
        def early(c):
            ls = c["legs"]
            return (len(ls) == 2 and {x["stat"] for x in ls} == {"ptd", "td"} and all(x["side"] == "over" for x in ls)
                    and next(x for x in ls if x["stat"] == "ptd")["line"] == 1.5)
        return [c for c in cs if (not a.events or c["event"] in a.events)
                and (not a.before or not c.get("starts") or c["starts"] < a.before)
                and (not a.full_before or not c.get("starts") or c["starts"] < a.full_before or early(c))
                and (not a.max_fair or sgp.american(c["j"]) <= a.max_fair)]
    cands = mine(cands)
    moved = [c for c in cands if c.get("alt")]   # CBB: a slip with one leg moved a line, asked after its own slip
    cands = [c for c in cands if not c.get("alt")]
    ladder = [c for c in cands if c["tier"] == 6]
    cands = [c for c in cands if c["tier"] != 6]
    if BOOKS["ladders"] is not None:   # the NBA ladder's lazy pull
        import books as _b
        BOOKS["seen"] = dict({b: len(v) for b, v in BOOKS["ladders"].items()}, errors=dict(_b.ERRORS))
    emit({"type": "start", "total": len(cands), "players": len({c["id"] for c in cands}),
          "league": a.league, "data": d["generated_at"][:10], "at": t0, "books": BOOKS["seen"]})
    pace, rows, lock = Pace(), [], threading.Lock()

    # --first: the slips the last pass left at the top of the board, best
    # first. They are asked before the rest of their stage, so the rows being
    # looked at are minutes old early in a pass, not whenever a 50-minute NFL
    # pass reaches them (Max, 11-15: half the All tab was dimmed).
    lead = {}
    if a.first:
        try:
            lead = {k: i for i, k in enumerate(json.load(open(a.first)))}
        except (OSError, ValueError):
            lead = {}

    def soonest(cs):
        """The last pass's best rows first (--first), in that order; then the
        earliest game first, so a slate's early games are priced before they
        start; within a game the order the candidates came in."""
        return sorted(cs, key=lambda c: (lead.get(c["key"], len(lead)), c.get("starts") or float("inf")))

    # Every slip is asked once a pass (Max, 11-20). A slip above fair used to
    # be held and asked again 40 seconds later until two quotes agreed (11-14:
    # first quotes showed as plays and were gone on the slip). 11-20, WYO ML +
    # Under 37.5, 18 asks: the quote was 7.54x when the slip had been left
    # alone 90 seconds and 6.27x on about every other ask 36 seconds apart, so
    # the second ask was itself what found the worse price, and an ask from
    # the board shortly before the app's did the same to the app.
    # --kalshi (the Ladder boards): each slip Novig prices is then asked of Kalshi
    # as the same combo, one request at a time on its own thread, the best Novig
    # EV waiting first. The row goes out with Novig's price at once; Kalshi's
    # follows as a "kalshi" event that sets its kalshi_* fields.
    kq, kcv, kst = [], threading.Condition(), {"open": True, "n": 0, "asked": 0, "got": 0, "refused": 0, "off": None}

    def kalshi_worker():
        import scan_kalshi
        while True:
            with kcv:
                while not kq and kst["open"]:
                    kcv.wait()
                if not kq:
                    return
                _, _, c = heapq.heappop(kq)
            if kst["off"]:
                got = {"kalshi_why": "not asked: " + kst["off"], "kalshi_at": time.time()}
            elif c["ev"] * 100 < a.kalshi_ev:
                got = {"kalshi_why": f"not asked: Novig is more than {-a.kalshi_ev:g}% under fair (the row's refresh asks)", "kalshi_at": time.time()}
            elif kst["asked"] >= a.kalshi_max and kalshi_same(c, a.league)[0]:
                got = {"kalshi_why": f"not asked: this pass's {a.kalshi_max} Kalshi asks were used (the row's refresh asks)", "kalshi_at": time.time()}
            else:
                try:
                    got = kalshi_look(c, a.league, a.kalshi_stake, a.kelly)
                    if got.get("kalshi_quote") or got.get("kalshi_url"):   # a request went out
                        kst["asked"] += 1
                        kst["got"] += 1 if got.get("kalshi_quote") else 0
                        time.sleep(scan_kalshi.PACE_S)
                except scan_kalshi.Refused as e:
                    kst["refused"] += 1
                    got = {"kalshi_why": f"Kalshi refused the request: {e}", "kalshi_at": time.time()}
                    if not kst["got"] and kst["refused"] >= scan_kalshi.REFUSED_AFTER:
                        kst["off"] = f"Kalshi is refusing this key's requests: {e}{scan_kalshi.refused_fix(str(e))}"
                except SystemExit as e:   # no key on the server, or one that can't be read
                    kst["off"] = str(e)
                    got = {"kalshi_why": "not asked: " + kst["off"], "kalshi_at": time.time()}
                if kst["off"]:
                    emit({"type": "kalshi_off", "why": kst["off"]})
            with lock:
                kalshi_set(c, got)
                emit({"type": "kalshi", "key": c["key"], "set": got})

    kthread = threading.Thread(target=kalshi_worker, daemon=True) if a.kalshi else None
    if kthread:
        kthread.start()

    def one(c):
        pace.wait()
        quote, why = novig.parlay([L["id"] for L in c["legs"]])
        with lock:
            if quote:
                finish(c, quote, a.unit, a.kelly)
                rows.append(c)
                emit(dict(c, type="row"))
            else:
                emit({"type": "miss", "key": c["key"], "player": c["player"], "label": c["label"], "why": why})
        if quote and kthread:
            with kcv:
                kst["n"] += 1
                heapq.heappush(kq, (-c["ev"], kst["n"], c))
                kcv.notify()

    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        first = soonest(c for c in cands if c["tier"] == 1)
        list(pool.map(one, first))
        best, asked = {}, {c["id"] for c in first}
        for c in list(rows):
            best[c["id"]] = max(best.get(c["id"], -9.0), c["ev"])

        def go(c):
            return c.get("pr") or c["id"] not in asked or best.get(c["id"], -9.0) * 100 > a.gate
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
            more = mine([c for c in star_triples(ctx, rfun, a) if c["key"] not in asked_keys])
            if more:
                emit({"type": "more", "add": len(more)})
                cands = cands + more
                list(pool.map(one, soonest(more)))
        if moved:
            # Team-total and first-half slips: always asked. Novig's price on
            # those does not follow the line (11-16, ACU @ MOST: ACU +5.5 +
            # ACU Under 67.5 paid 4.04x, -39%, and ACU +6.5 + Under 67.5,
            # the easier slip, 5.95x, +10%), so the slip's own EV says nothing
            # about the line beside it. Spread + total slips track the model
            # (every one of 8 within 3% of its slip), so theirs are asked only
            # when the slip itself priced at --alt-gate or better.
            ev = {c["key"]: c["ev"] for c in rows}
            more = [c for c in moved if c.get("kind") != "cover" or ev.get(c["alt"], -9.0) * 100 >= a.alt_gate]
            if more:
                emit({"type": "more", "add": len(more)})
                cands = cands + more
                list(pool.map(one, soonest(more)))
        if a.tri and a.tier in (0, 4):
            more = mine(triples([c for c in rows if go(c)], ctx, stats, rfun, a))
            emit({"type": "more", "add": len(more)})
            cands = cands + more
            list(pool.map(one, soonest(more)))
    if kthread:   # Kalshi's answers for the slips still waiting, before the pass is done
        with kcv:
            kst["open"] = False
            kcv.notify()
        kthread.join()
    emit({"type": "done", "quoted": len(cands), "priced": len(rows), "seconds": time.time() - t0, "at": time.time()})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="nba", choices=("nba", "nfl", "nhl", "soccer", "cfb", "cbb"))
    ap.add_argument("--kind", default="all", choices=("all", "props", "stacks", "lines", "tri", "mates", "team"),
                    help="NFL: one kind of slip only (default: a player's own props, stacks, game lines, "
                         "then tri, the three-leg slips). "
                         "NHL: props (a skater's own goals + shots), mates (two teammates) or lines (points + a game line). "
                         "NBA: team (the NBA Team board: a player's prop with a game line, and slips across a game's own lines)")
    ap.add_argument("--team", default="all", choices=("all", "props", "game"),
                    help="NBA Team board: props (a player's prop + a game line) or game (a game's own lines) only")
    ap.add_argument("--team-lines", nargs="+", default=["cover"], choices=tuple(NBA_PROP_LINES),
                    help="NBA Team board: the game lines a prop is asked with (default: the spread; the first-half "
                         "spread, his team's total, the other team's, the game total and the first half's were all "
                         "3%% to 8%% under fair on 11-13)")
    ap.add_argument("--per", type=int, default=None,
                    help="NFL stacks / lines / three legs, NHL teammates: combos asked per player of each kind, highest r first "
                         "(3; NHL lines 4: moneyline, puck line, total and team total)")
    ap.add_argument("--line-r", type=float, default=None,
                    help="NFL / NHL lines, NBA Team: smallest |r| between a prop and a game line (0.25; NBA Team 0.42)")
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
    ap.add_argument("--max-fair", type=float, default=None,
                    help="ask only slips whose fair value is at most this in American odds "
                         "(NFL: 600, so its ladder band is 500 to 600; other leagues: no cap; 0 = no cap)")
    ap.add_argument("--gate", type=float, default=None,
                    help="ask a player's other combos only if his best main-line PTS+3PM EV%% is above this (-100 = everyone)")
    ap.add_argument("--no-books", action="store_true",
                    help="don't cap shifted legs at DK's and FanDuel's one-way prices")
    ap.add_argument("--no-stars", dest="stars", action="store_false",
                    help="NBA: skip the three-leg main-line slips always asked for the STARS list")
    ap.add_argument("--star-pts", type=float, default=26.5,
                    help="NBA: also ask those three-leg slips for anyone whose points main line is this high (0 = the list only)")
    ap.add_argument("--ladder-fix", action="store_true", help="scale higher-line joints by LADDER_FIX (off: plain model)")
    ap.add_argument("--alt-gate", type=float, default=-8.0,
                    help="CBB: a spread + total slip at this EV%% or better is asked again with each leg moved one line "
                         "either way (default -8); team-total and first-half slips always are")
    ap.add_argument("--no-mates", dest="mates", action="store_false", help="NBA: skip the teammates' points slips")
    ap.add_argument("--no-alts", dest="alts", action="store_false", help="CBB: skip the moved-line versions")
    ap.add_argument("--no-unders", dest="unders", action="store_false",
                    help="NFL: ask no player-prop Unders (Under + Under, the Over + Under stacks, a prop's Under + a game line)")
    ap.add_argument("--no-dd", dest="dd", action="store_false", help="skip the build-your-own double-doubles")
    ap.add_argument("--no-ladder", dest="ladder", action="store_false", help="skip the higher-line combos")
    ap.add_argument("--min-r", type=float, default=None,
                    help="smallest r for an Over + Over on the other pairs (0.15; NHL 0.10)")
    ap.add_argument("--no-pr", dest="pr", action="store_false",
                    help="NBA main scope: skip each player's main-line Points + Rebounds slip")
    ap.add_argument("--pr-r", type=float, default=0.25, help="NBA main scope: smallest r for that Points + Rebounds slip")
    ap.add_argument("--pr-leg", type=float, default=0.30, help="NBA main scope: each leg of that slip has a fair value of at least this")
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
    ap.add_argument("--requote", action="store_true",
                    help="price one slip again: a board row (JSON) on stdin, the row with today's leg prices and "
                         "a new quote on stdout, or {\"error\": why}")
    ap.add_argument("--events", nargs="+", default=None, metavar="ID",
                    help="only these games (Novig event ids, from --games): the page's game picker")
    ap.add_argument("--before", type=float, default=None, metavar="MS",
                    help="only games starting before this time (epoch ms): Auto-scan's end of today")
    ap.add_argument("--full-before", type=float, default=None, metavar="MS",
                    help="games starting at or after this time (epoch ms) keep only the QB 2+ passing TDs + teammate TD slip "
                         "(Auto-scan's NFL: everything else waits for the day before the game)")
    ap.add_argument("--first", default=None, metavar="FILE",
                    help="a JSON list of slip keys to ask before the rest, in that order (server.js: the last pass's best rows)")
    ap.add_argument("--games", action="store_true", help="list the league's open pregame games as JSON and stop")
    ap.add_argument("--kalshi", action="store_true",
                    help="--scope ladder, or --requote of a Ladder row: also ask Kalshi for the same slip, where it lists "
                         "every leg on the same line (needs KALSHI_KEY_ID / KALSHI_PRIVATE_KEY; one request for quote a slip, "
                         "nothing accepted)")
    ap.add_argument("--kalshi-ev", type=float, default=KALSHI_LOOK["ev"],
                    help="--kalshi: ask Kalshi only for slips Novig prices at this EV%% or better (default -100: all of them)")
    ap.add_argument("--kalshi-max", type=int, default=KALSHI_LOOK["max"], help="--kalshi: Kalshi asks a pass, best Novig EV first (default 150)")
    ap.add_argument("--kalshi-stake", type=float, default=KALSHI_LOOK["stake"], help="--kalshi: dollars each Kalshi request is sized at")
    a = ap.parse_args()
    a.events = set(a.events) if a.events else None
    if a.games:
        print(json.dumps(games(a.league)))
        return
    if a.requote:
        row, why = requote(json.load(sys.stdin), a.league, a.max_spread,
                           a.unit or (500.0 if a.league == "nhl" else 250.0), a.kelly)
        if row and a.kalshi:   # a Ladder row: Kalshi's price for the same slip, whatever Novig's EV
            try:
                kalshi_set(row, kalshi_look(row, a.league, a.kalshi_stake, a.kelly))
            except SystemExit as e:
                kalshi_set(row, {"kalshi_why": f"not asked: {e}", "kalshi_at": time.time()})
            except Exception as e:  # noqa: BLE001  scan_kalshi.Refused, or Kalshi unreachable: Novig's new price still stands
                kalshi_set(row, {"kalshi_why": f"{'Kalshi refused the request' if type(e).__name__ == 'Refused' else 'no answer from Kalshi'}: {e}",
                                 "kalshi_at": time.time()})
        print(json.dumps(row if row else {"error": why}))
        return
    BOOKS["on"] = not a.no_books
    if a.per is None:
        a.per = 4 if a.league == "nhl" and a.kind == "lines" else 3
    if a.unit is None:
        a.unit = 500.0 if a.league == "nhl" else 250.0
    if a.min_r is None:
        a.min_r = 0.10 if a.league == "nhl" else 0.15
    if a.line_r is None:
        # NBA Team, 11-13, priced at the fit less one standard error: prop +
        # spread slips at a fitted r of 0.42 or better were above fair on 33 of
        # 42 quotes (median +2.0%); at 0.30 to 0.42, 8 of 45 (median -4.0%).
        a.line_r = 0.42 if a.kind == "team" else 0.25
    if a.gate is None:
        # Ladder scope asks down to a main line 10% under fair: on the ungated
        # pass of 11-11, players at -10% to 0% held 46 of the 81 ladder slips
        # at +10% or better; those under -10% held 4 (of 74 asked).
        a.gate = -10.0 if a.scope == "ladder" else 0.0
    if a.max_fair is None:   # Max, 11-15: NFL only
        a.max_fair = 600.0 if a.league == "nfl" else 0.0
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
    if a.kind == "team" and (a.league != "nba" or a.scope == "ladder"):
        raise SystemExit("--kind team is NBA only (and not with --scope ladder)")
    if a.kind == "tri" and (a.league != "nfl" or a.scope == "ladder"):
        raise SystemExit("--kind tri is NFL only (and not with --scope ladder)")
    if a.scope == "ladder":
        if a.league in ("soccer", "cfb", "cbb"):
            raise SystemExit("--scope ladder is NBA and NFL only")
        if a.league == "nhl":
            raise SystemExit("--scope ladder is NBA and NFL only")
        a.tri, a.dd, a.ladder = 0, False, True
        if a.league == "nba":
            a.tier = 1
    if a.kalshi and a.scope != "ladder":
        raise SystemExit("--kalshi is for --scope ladder (and --requote of a Ladder row)")
    if a.scope == "main":
        # Max, 11-10: every quote is an auction the pricers see, and plays were
        # being repriced while the wider scans ran. One ask per player.
        a.tri, a.ladder, a.dd = 0, False, False
        if a.league == "nba":
            a.tier = 1
    # Points + Rebounds for every player is the NBA board's slip (main scope); --scope all keeps its own rule (big men).
    a.pr = a.pr and a.league == "nba" and a.scope == "main"

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
    print("| Player | Legs | Leg fairs | r | Fair | Novig | EV | QK | Wager |" + (" Kalshi |" if a.kalshi else ""))
    print("|---|---|---|---|---|---|---|---|---|" + ("---|" if a.kalshi else ""))
    for c in shown:
        legs = " / ".join(f"{L['fair']:+d}" for L in c["legs"])
        rtxt = "unrel." if c["r"] is None else f"{c['r']:+.2f}"
        print(f"| {c['player']} {c['team']} | {c['label']}{' *' if c.get('model') else ''}{' ~' if c['rough'] else ''} | {legs} | {rtxt} | "
              f"{c['fair']:+d} | {c['slip_x']:.2f}x | {c['ev']:+.1%} | {c['qk']:.2f}u | ${c['wager']:,.0f} |"
              + ((f" {c['kalshi_x']:.2f}x ({c['kalshi_ev']:+.1%}){' BETTER' if c['kalshi_x'] > c['slip_x'] else ''} |" if c.get("kalshi_x")
                  else f" {c.get('kalshi_why') or ''} |") if a.kalshi else ""))
    if any(c.get("model") for c in shown):
        print("* a higher line: fair value modelled from the main line, not read off a book")
    if any(c["rough"] for c in shown):
        print("~ a leg sits on a Novig book wider than 4c: rough fair value")


if __name__ == "__main__":
    main()
