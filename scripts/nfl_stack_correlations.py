#!/usr/bin/env python3
"""NFL correlations between two different bets in one game, from nflverse:

  stack  a quarterback's passing with one of his own receivers or backs
         (passing yards + his WR's receiving yards, passing TDs + anytime TD)
  game   a player's prop with the game's closing total, his team's closing
         spread, his team's implied total, his team winning, or the first
         half's total, spread and leader (QB passing yards + game Over, RB
         rushing yards + his team covering)

scripts/nfl_fetch_correlations.py covers one player's own props, per player.
These are league-wide numbers by role instead: a QB-receiver pair shares a
dozen games a season, far too few to estimate one pair on its own, and that
script already found a player's own r predicts worse than his position's
average. The role is the position and the player's volume that season
(targets a game for the receiving stats, carries a game for rushing).

What r is
---------
The Gaussian-copula correlation that reproduces how often both legs hit.
Within each group of games (one QB + one receiver in one season, or one
player's season against the lines), each stat is cut at that group's median
(anytime TD at 1+, passing TDs at 2+ and, in a row of their own, at 3+; the
game lines at the closing number: Over, cover, team total Over). r solves

    sum over groups [ n a b + (n - 1) (J(r; a, b) - a b) ] = games both hit

where a and b are the group's own hit rates and J the bivariate-normal joint.
The n - 1 is the usual loss of one game to the group's own averages. So a
slip of two legs near their main lines, priced with this r, hits as often as
it did over these seasons; `check` in the output is the same comparison at
harder lines (each stat's upper third), which the fit never saw.

That equation is only right when a and b are the group's true rates. They are
not: a receiver's touchdown rate is read off a dozen games (2 in 12, or none),
and the joint's excess over a b is curved in a and b, so on rates that noisy
the equation needs a higher r to reach the same count. On made-up seasons
with a known r of 0.45 it returned 0.55 (passing TDs + a receiver's TD), and
the slips priced with it showed fair values the books were nowhere near
(Samuel's TD with Purdy 2+, 11-22: +430 here, +525 at DraftKings). So r is
solved by simulation instead (fit_groups): seasons of the same lengths are
drawn at a trial r, a counted leg's true rate from the spread of rates the
bucket really has, a median leg cut at each made-up season's own median, the
same groups dropped; r is the one whose made-up seasons show the excess the
real ones did. Legs cut at a median are barely touched (the rate is one half
by construction); anything with a touchdown leg comes down about 0.1. Lines
fitted in bands of the spread pool hundreds of games a cell and keep the
equation.

Winning (the moneyline) has no closing number to cut at: a favourite wins
more often, and a favourite's back also carries more, so cutting "won" at a
player's season average counts the spread itself as correlation (a lead
back's carries: 0.59 that way, 0.47 with his team covering). It is fitted
within games of about the same closing spread instead (3-point bands), the
stat still cut at the player's own season median, which gives the r a slip
priced off the moneyline's own fair value needs. It lands on the cover r
(0.50), as it should: winning and covering are one margin cut at two
places. The first half's leader is fitted the same way (ties left out).

Underdogs and favourites: with the spread, the moneyline and their first-
half versions, a volume prop's r depends on which side his team is. A QB's
pass attempts against his team covering: -0.44 as a favourite of 3.5+,
-0.39 within a field goal, -0.15 as an underdog of 3.5+ (an underdog is
already expected to trail, and its attempts line says so). A lead back's
carries with covering: +0.22 as a favourite, +0.54 otherwise. So each of
those four lines also gets one fit per side (`side`: dog, even, fav), fitted
within 3-point bands of the closing spread like the moneyline. Totals show
no such split and keep one r.

First halves: halftime scores are ESPN's (its scoreboard's line scores, one
call a week, joined on the ESPN game id nflverse carries). There are no
closing first-half lines in nflverse, so the first-half total is cut at the
straight-line fit of first-half points on the closing total (about half of
it) and the first-half spread at the same fit of the halftime margin on the
closing spread (about 0.57 of it).

Sources (nflverse-data releases, public):
  stats_player/stats_player_week_{season}.csv   weekly player stats
  schedules/games.csv                           results, closing spread / total
  site.api.espn.com .../nfl/scoreboard          halftime scores

Usage:
  python3 scripts/nfl_stack_correlations.py              # last 10 seasons
  python3 scripts/nfl_stack_correlations.py --seasons 2021 2022 2023 2024 2025
  python3 scripts/nfl_stack_correlations.py --cache DIR   # keep the downloads
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import csv
import datetime as dt
import io
import json
import math
import random
import os
import statistics
import sys
import time
import urllib.request
from statistics import NormalDist

HALF = {}   # what load() found for the first halves, for the output file
REL = "https://github.com/nflverse/nflverse-data/releases/download"
ND = NormalDist()

MIN_GROUP = 6        # games a group needs
QB_MIN_ATT = 15      # pass attempts for a QB's game to count (the team's most that day)
EDGES = {"tgt": (3.0, 5.0, 7.0, 9.0), "car": (8.0, 13.0, 18.0)}  # role buckets: per-game volume from
MIN_GAMES = 1500     # a bucket with fewer games is merged into the one below it
SIM_GAMES = 100_000  # made-up games a fit is solved on (fit_groups)
KEEP = (0.08, 0.92)  # a group counts when each leg hit in this share of its games

# stat -> nflverse column(s)
COLS = {"att": ("attempts",), "cmp": ("completions",), "pyds": ("passing_yards",), "ptd": ("passing_tds",),
        "car": ("carries",), "ryds": ("rushing_yards",), "rec": ("receptions",), "tgt": ("targets",),
        "yds": ("receiving_yards",), "td": ("rushing_tds", "receiving_tds"),
        "rry": ("rushing_yards", "receiving_yards")}
# A leg's line inside a group: a fixed count, or the group's median.
FIXED = {"td": 0.5, "ptd": 1.5, "over": 0.0, "cover": 0.0, "tt": 0.0,
         "win": 0.0, "h1over": 0.0, "h1cover": 0.0, "h1win": 0.0}
# Passing TDs are also fitted at 3+. A good offence's main line is 2.5 (Purdy
# 3+ at 35% against 2+ at 65%, 11-15), and the r fitted at 2+ said such a slip
# hit more often than it did: every pairing with passing TDs gets one more
# row, `at` 2.5, beside the 2+ row (`at` 1.5).
PTD_AT = (1.5, 2.5)

# (QB stat, teammate's stat, teammate positions, role volume)
STACKS = (("pyds", "yds", ("WR", "TE", "RB"), "tgt"), ("pyds", "rec", ("WR", "TE", "RB"), "tgt"),
          ("cmp", "rec", ("WR", "TE", "RB"), "tgt"), ("ptd", "td", ("WR", "TE", "RB"), "tgt"),
          ("pyds", "td", ("WR", "TE"), "tgt"), ("ptd", "yds", ("WR", "TE"), "tgt"),
          ("pyds", "ryds", ("RB",), "car"), ("att", "car", ("RB",), "car"), ("ptd", "td", ("RB",), "car"))
# (stat, positions, role volume or None for the starting QB)
GAME = (("pyds", ("QB",), None), ("ptd", ("QB",), None), ("att", ("QB",), None), ("cmp", ("QB",), None),
        ("ryds", ("QB",), None),
        ("yds", ("WR", "TE", "RB"), "tgt"), ("rec", ("WR", "TE", "RB"), "tgt"), ("td", ("WR", "TE"), "tgt"),
        ("ryds", ("RB",), "car"), ("car", ("RB",), "car"), ("rry", ("RB",), "car"), ("td", ("RB",), "car"))
LINES = ("over", "cover", "tt", "win", "h1over", "h1cover", "h1win")
BANDED = ("win", "h1win")   # no closing number to cut at: fitted within bands of the closing spread
# Lines whose r depends on whether his team is the underdog: one more fit per
# side of the closing spread (points his team is favoured by).
SIDED = ("cover", "win", "h1cover", "h1win")
SIDES = {"dog": lambda sp: sp <= -3.5, "even": lambda sp: -3.5 < sp < 3.5, "fav": lambda sp: sp >= 3.5}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


def fetch(path: str, cache: str | None) -> str:
    name = path.replace("/", "_")
    if cache and os.path.exists(os.path.join(cache, name)):
        return open(os.path.join(cache, name), encoding="utf-8").read()
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"{REL}/{path}", headers={"User-Agent": "nfl-stack-correlations"})
            with urllib.request.urlopen(req, timeout=120) as r:
                text = r.read().decode("utf-8")
            break
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    if cache:
        os.makedirs(cache, exist_ok=True)
        open(os.path.join(cache, name), "w", encoding="utf-8").write(text)
    return text


def num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def halves(seasons: list[int], cache: str | None) -> dict:
    """{ESPN game id: (home, away) points at halftime} for finished regular-
    season games. A week ESPN doesn't answer for is left out."""
    name = os.path.join(cache, "espn_halves.json") if cache else None
    if name and os.path.exists(name):
        return json.load(open(name, encoding="utf-8"))

    def week(yw):
        url = f"{ESPN}?dates={yw[0]}&seasontype=2&week={yw[1]}"
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "nfl-stack-correlations"})
                with urllib.request.urlopen(req, timeout=40) as r:
                    return json.load(r).get("events", [])
            except Exception:  # noqa: BLE001
                time.sleep(2 * (attempt + 1))
        print(f"  no ESPN scoreboard for {yw[0]} week {yw[1]}", file=sys.stderr)
        return []

    out = {}
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        for events in pool.map(week, [(y, w) for y in seasons for w in range(1, 19)]):
            for e in events:
                c = e["competitions"][0]
                if not c["status"]["type"]["completed"]:
                    continue
                q = {t["homeAway"]: [x["value"] for x in t.get("linescores", [])] for t in c["competitors"]}
                if len(q.get("home", [])) >= 4 and len(q.get("away", [])) >= 4:
                    out[e["id"]] = (sum(q["home"][:2]), sum(q["away"][:2]))
    if name:
        os.makedirs(cache, exist_ok=True)
        json.dump(out, open(name, "w", encoding="utf-8"))
    return out


def ols(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """(intercept, slope) of the straight-line fit of ys on xs."""
    mx, my = statistics.mean(xs), statistics.mean(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my - b * mx, b


def load(seasons: list[int], cache: str | None):
    """(team-games, lines): team-games[(game_id, team)] = that team's players,
    each {id, name, pos, season, stats...}; lines[(game_id, team)] = how the
    game landed against the closing numbers, from that team's side."""
    lines, games = {}, []
    for g in csv.DictReader(io.StringIO(fetch("schedules/games.csv", cache))):
        try:
            res, tot, sp, tl = float(g["result"]), float(g["total"]), float(g["spread_line"]), float(g["total_line"])
            hs, as_ = float(g["home_score"]), float(g["away_score"])
        except (KeyError, ValueError):
            continue
        if g.get("game_type") != "REG":
            continue
        # result = home - away; spread_line = points the home team is favoured by.
        # "sp" is the closing spread from the team's side, for the banded fits.
        lines[(g["game_id"], g["home_team"])] = {"over": tot - tl, "cover": res - sp, "tt": hs - (tl + sp) / 2,
                                                 "win": res, "sp": sp}
        lines[(g["game_id"], g["away_team"])] = {"over": tot - tl, "cover": sp - res, "tt": as_ - (tl - sp) / 2,
                                                 "win": -res, "sp": -sp}
        if int(g["season"]) in seasons:
            games.append((g, sp, tl))
    # First halves, cut at stand-ins for the closing first-half lines.
    half = halves(seasons, cache)
    have = [(g, sp, tl, half[g["espn"]]) for g, sp, tl in games if g.get("espn") in half]
    if len(have) >= 500:
        t0, t1 = ols([tl for _, _, tl, _ in have], [h + a for _, _, _, (h, a) in have])
        _, s1 = ols([sp for _, sp, _, _ in have], [h - a for _, _, _, (h, a) in have])
        for g, sp, tl, (h, a) in have:
            lines[(g["game_id"], g["home_team"])].update(h1over=h + a - (t0 + t1 * tl), h1cover=h - a - s1 * sp, h1win=h - a)
            lines[(g["game_id"], g["away_team"])].update(h1over=h + a - (t0 + t1 * tl), h1cover=s1 * sp - (h - a), h1win=a - h)
        HALF.update(games=len(have), of=len(games), total=(round(t0, 2), round(t1, 3)), spread=round(s1, 3))
    else:
        print(f"  halftime scores for only {len(have)} of {len(games)} games: no first-half lines", file=sys.stderr)
    teams = collections.defaultdict(list)
    for yr in seasons:
        try:
            text = fetch(f"stats_player/stats_player_week_{yr}.csv", cache)
        except Exception as e:  # noqa: BLE001 - a season not published yet
            print(f"  no weekly stats for {yr}: {e}", file=sys.stderr)
            continue
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("season_type") != "REG" or r.get("position") not in ("QB", "WR", "TE", "RB", "FB"):
                continue
            p = {"id": r["player_id"], "name": r["player_display_name"], "season": yr,
                 "pos": "RB" if r["position"] == "FB" else r["position"]}
            for k, cols in COLS.items():
                p[k] = sum(num(r.get(c)) for c in cols)
            teams[(r["game_id"], r["team"])].append(p)
    return teams, lines


def groups_of(teams, lines):
    """Player-seasons with their games, each game carrying the team's starting
    QB's line and the game's lines: {(id, season): [row, ...]}."""
    seasons = collections.defaultdict(list)
    for key, players in teams.items():
        qbs = [p for p in players if p["pos"] == "QB" and p["att"] >= QB_MIN_ATT]
        qb = max(qbs, key=lambda p: p["att"]) if qbs else None
        ln = lines.get(key)
        for p in players:
            if p["pos"] == "QB" and p is not qb:
                continue
            seasons[(p["id"], p["season"])].append({"p": p, "qb": qb, "ln": ln})
    return seasons


def joint(r: float, x: float, y: float, ab: float) -> float:
    """P(both) for normal quantiles x, y at copula correlation r (Plackett, Simpson)."""
    n = 40
    h = r / n
    tot = 0.0
    for i in range(n + 1):
        rho = i * h
        q = 1 - rho * rho
        tot += math.exp(-(x * x - 2 * rho * x * y + y * y) / (2 * q)) / (2 * math.pi * math.sqrt(q)) \
            * (1 if i in (0, n) else 4 if i % 2 else 2)
    return ab + tot * h / 3


def line_of(vals: list[float], stat: str, q: float = 0.5, at: dict | None = None) -> float:
    if at and stat in at:
        return at[stat]
    if stat in FIXED:
        return FIXED[stat]
    s = sorted(vals)
    return statistics.median(s) if q == 0.5 else s[min(len(s) - 1, int(q * len(s)))]


def fixed(stat: str, at: dict | None = None) -> bool:
    """Is this leg a count against a set line (a rate to estimate), not a cut at the group's own median?"""
    return bool(at and stat in at) or stat in FIXED


def tally(pairs: list[tuple[float, float]], sx: str, sy: str, q: float = 0.5, at: dict | None = None):
    """(n, games x hit, games y hit, games both hit) for one group at its lines.
    `at` fixes a stat's line ({"ptd": 2.5}) in place of FIXED's."""
    lx, ly = line_of([x for x, _ in pairs], sx, q, at), line_of([y for _, y in pairs], sy, q, at)
    return (len(pairs), sum(x > lx for x, _ in pairs), sum(y > ly for _, y in pairs),
            sum(x > lx and y > ly for x, y in pairs))


def kept(n: int, kx: int, ky: int) -> bool:
    return KEEP[0] <= kx / n <= KEEP[1] and KEEP[0] <= ky / n <= KEEP[1]


def banded(groups: list[list[tuple]], sy: str, at: dict | None = None) -> list[tuple]:
    """Cuts for a line with no closing number (won, led at the half): one per
    3-point band of the closing spread, across every group. The stat is cut
    at each group's own median; ties on the line are left out."""
    cells = collections.defaultdict(lambda: [0, 0, 0, 0])
    for g in groups:
        ly = line_of([y for _, y, _ in g], sy, at=at)
        for x, y, sp in g:
            if x == 0:
                continue
            c = cells[max(-4, min(4, round(sp / 3)))]
            c[0] += 1
            c[1] += x > 0
            c[2] += y > ly
            c[3] += x > 0 and y > ly
    return [(n, a / n, b / n, both) for n, a, b, both in cells.values()
            if n >= 50 and 0.05 <= a / n <= 0.95 and 0.05 <= b / n <= 0.95]


def fit(cuts: list[tuple]) -> dict | None:
    """The r that reproduces the games both legs hit, with a rough standard
    error, by the equation: for cells of many games each (banded), whose rates
    are near enough the true ones. Small groups go through fit_groups."""
    if not cuts:
        return None
    both = sum(c[3] for c in cuts)
    cells = collections.Counter((n, a, b) for n, a, b, _ in cuts)
    terms = [(k, n, a * b, ND.inv_cdf(a), ND.inv_cdf(b)) for (n, a, b), k in cells.items()]

    def expected(r: float) -> float:
        return sum(k * (n * ab + (n - 1) * (joint(r, x, y, ab) - ab)) for k, n, ab, x, y in terms)

    lo, hi = -0.95, 0.95
    for _ in range(16):
        mid = (lo + hi) / 2
        if expected(mid) < both:
            lo = mid
        else:
            hi = mid
    r = (lo + hi) / 2
    slope = (expected(r + 0.01) - expected(r - 0.01)) / 0.02
    var = sum(k * n * j * (1 - j) for k, n, ab, x, y in terms for j in [joint(r, x, y, ab)])
    games = sum(c[0] for c in cuts)
    return {"r": round(r, 3), "se": round(math.sqrt(var) / slope, 3) if slope > 0 else None,
            "games": games, "groups": len(cuts), "both": round(both / games, 4),
            "unrelated": round(sum(n * a * b for n, a, b, _ in cuts) / games, 4)}


def rates(ks: list[int], ns: list[int]):
    """The true rates behind a bucket's groups, as a draw: a Beta with the
    bucket's mean and the spread its groups show beyond what their few games
    would alone (one fixed rate when they show none)."""
    m = sum(ks) / sum(ns)
    extra = statistics.fmean((k / n - m) ** 2 for k, n in zip(ks, ns)) - m * (1 - m) * statistics.fmean(1 / n for n in ns)
    if extra <= 1e-4 or not 0 < m < 1:
        return lambda rng: m
    c = max(m * (1 - m) / extra - 1, 2.0)
    return lambda rng: rng.betavariate(m * c, (1 - m) * c)


class Seasons:
    """Made-up seasons for one bucket's groups (tallies), to be read at any r.
    A counted leg (fx / fy true) hits when its normal passes the line its drawn
    rate sets; a median leg hits in as many games as it did in the real group,
    the top ones. The draws are made once: every r is read off the same ones."""

    def __init__(self, tallies: list[tuple], fx: bool, fy: bool, seed: int = 7):
        rng = random.Random(seed)
        ts = [t for t in tallies if (fx or KEEP[0] <= t[1] / t[0] <= KEEP[1]) and (fy or KEEP[0] <= t[2] / t[0] <= KEEP[1])]
        self.reps, self.rows = 0, []
        if not ts:
            return
        ax, ay = rates([t[1] for t in ts], [t[0] for t in ts]), rates([t[2] for t in ts], [t[0] for t in ts])
        self.reps = max(4, round(SIM_GAMES / sum(t[0] for t in ts)))
        for rep in range(self.reps):
            for n, kx, ky, _ in ts:
                z = [rng.gauss(0, 1) for _ in range(n)]
                e = [rng.gauss(0, 1) for _ in range(n)]
                if fx:
                    lx = ND.inv_cdf(1 - min(max(ax(rng), 1e-4), 1 - 1e-4))
                    hx = [v > lx for v in z]
                else:
                    top = sorted(z)[n - kx] if kx else math.inf
                    hx = [v >= top for v in z]
                ly = ND.inv_cdf(1 - min(max(ay(rng), 1e-4), 1 - 1e-4)) if fy else None
                self.rows.append((rep, n, sum(hx), hx, z, e, ly, ky))

    def read(self, r: float) -> list[tuple[float, float, int]]:
        """Per made-up bucket: (games both hit beyond n a b, games both hit, games), over the groups kept."""
        out, s = [[0.0, 0.0, 0] for _ in range(self.reps)], math.sqrt(1 - r * r)
        for rep, n, kx, hx, z, e, ly, ky in self.rows:
            w = [r * a + s * b for a, b in zip(z, e)]
            if ly is None:
                ly = sorted(w)[n - ky] - 1e-12 if ky else math.inf
            hy = [v > ly for v in w]
            k = sum(hy)
            if not kept(n, kx, k):
                continue
            both = sum(a and b for a, b in zip(hx, hy))
            o = out[rep]
            o[0] += both - kx * k / n
            o[1] += both
            o[2] += n
        return [tuple(o) for o in out]


def fit_groups(tallies: list[tuple], fx: bool, fy: bool) -> tuple[dict | None, Seasons | None]:
    """The r whose made-up seasons show the games both legs hit, beyond n a b,
    that the real groups do (the module docstring's "What r is"), with a rough
    standard error; and the seasons, for check."""
    real = [t for t in tallies if kept(*t[:3])]
    if not real:
        return None, None
    games = sum(t[0] for t in real)
    want = sum(t[3] - t[1] * t[2] / t[0] for t in real)
    sim = Seasons(tallies, fx, fy)

    def excess(r: float) -> float:
        return statistics.fmean(o[0] for o in sim.read(r))

    lo, hi = -0.95, 0.95
    for _ in range(11):
        mid = (lo + hi) / 2
        if excess(mid) < want:
            lo = mid
        else:
            hi = mid
    r = (lo + hi) / 2
    slope = (excess(min(r + 0.03, 0.97)) - excess(max(r - 0.03, -0.97))) / 0.06
    sd = statistics.pstdev(o[0] for o in sim.read(r))
    return {"r": round(r, 3), "se": round(sd / slope, 3) if slope > 0 else None,
            "games": games, "groups": len(real), "both": round(sum(t[3] for t in real) / games, 4),
            "unrelated": round(sum(t[1] * t[2] / t[0] for t in real) / games, 4)}, sim


def check(groups: list[list[tuple[float, float]]], sx: str, sy: str, r: float, at: dict | None = None) -> dict | None:
    """Out of the fit's sight: both legs at each group's upper-third lines
    (counts with a fixed line keep it), actual vs what r says (made-up seasons
    at r, cut the same way)."""
    if fixed(sx, at) and fixed(sy, at):   # both lines fixed: nothing the fit didn't see
        return None
    tallies = [tally(g, sx, sy, 2 / 3, at) for g in groups]
    real = [t for t in tallies if kept(*t[:3])]
    if not real:
        return None
    sim = Seasons(tallies, fixed(sx, at), fixed(sy, at), seed=11).read(r)
    n = sum(o[2] for o in sim)
    if not n:
        return None
    return {"actual": round(sum(t[3] for t in real) / sum(t[0] for t in real), 4),
            "model": round(sum(o[1] for o in sim) / n, 4)}


def buckets(rows: list[tuple[float, list]], edges: tuple, sx: str, sy: str, bands: bool = False,
            at: dict | None = None) -> list[dict]:
    """rows = (volume, group's pairs). One fit per volume bucket, thin buckets
    merged downward (the top bucket into the one below it). `at` fixes a
    stat's line in place of FIXED's."""
    bins = [[lo, None, []] for lo in edges]
    for vol, pairs in rows:
        i = max((i for i, lo in enumerate(edges) if vol >= lo), default=None)
        if i is not None:
            bins[i][2].append(pairs)
    for i in range(len(bins) - 1):
        bins[i][1] = bins[i + 1][0]
    i = len(bins) - 1
    while i > 0:
        if sum(len(g) for g in bins[i][2]) < MIN_GAMES:
            bins[i - 1][1] = bins[i][1]
            bins[i - 1][2] += bins[i][2]
            del bins[i]
        i -= 1
    out = []
    for lo, hi, groups in bins:
        if bands or sx in BANDED:
            f = fit(banded(groups, sy, at))
            if f:
                out.append({"min": lo, "max": hi, **f, "groups": len(groups), "check": None})
            continue
        f, _ = fit_groups([tally(g, sx, sy, at=at) for g in groups], fixed(sx, at), fixed(sy, at))
        if f:
            out.append({"min": lo, "max": hi, **f, "check": check(groups, sx, sy, f["r"], at)})
    return out


def ptd_lines(*stats):
    """The passing-TD lines a pairing is fitted at: [(extra row keys, `at`)].
    One plain fit for a pairing with no passing TDs."""
    return [({"at": L}, {"ptd": L}) for L in PTD_AT] if "ptd" in stats else [({}, None)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="+", default=None, help="default: the last 10, through this one")
    ap.add_argument("--out", default=os.path.join("public", "data", "nfl_stack_correlations.json"))
    ap.add_argument("--cache", default=None, help="directory to keep the nflverse downloads in")
    args = ap.parse_args()
    today = dt.date.today()
    cur = today.year if today.month >= 9 else today.year - 1
    seasons = sorted(args.seasons or range(cur - 9, cur + 1))
    print(f"Loading nflverse weekly stats {seasons[0]}-{seasons[-1]} ...", file=sys.stderr)
    teams, lines = load(seasons, args.cache)
    if len(teams) < 500:
        sys.exit("Too few games from nflverse; refusing to overwrite the data file.")
    if not HALF and os.path.exists(args.out) and json.load(open(args.out, encoding="utf-8")).get("halves"):
        sys.exit("No halftime scores from ESPN; refusing to drop the first-half lines from the data file.")
    ps = groups_of(teams, lines)
    vol = {k: {v: sum(g["p"][v] for g in rows) / len(rows) for v in EDGES} for k, rows in ps.items()}

    stack = []
    for sx, sy, positions, by in STACKS:
        for pos in positions:
            rows = []
            for key, games in ps.items():
                if games[0]["p"]["pos"] != pos:
                    continue
                duo = collections.defaultdict(list)   # one group per QB he played with
                for g in games:
                    if g["qb"]:
                        duo[g["qb"]["id"]].append((g["qb"][sx], g["p"][sy]))
                rows += [(vol[key][by], d) for d in duo.values() if len(d) >= MIN_GROUP]
            for extra, at in ptd_lines(sx, sy):
                for b in buckets(rows, EDGES[by], sx, sy, at=at):
                    stack.append({"qb": sx, "stat": sy, "pos": pos, "by": by, **extra, **b})

    game = []
    for sy, positions, by in GAME:
        for pos in positions:
            for line in LINES:
                rows = []
                for key, games in ps.items():
                    if games[0]["p"]["pos"] != pos:
                        continue
                    d = [(g["ln"][line], g["p"][sy]) + ((g["ln"]["sp"],) if line in BANDED else ())
                         for g in games if g["ln"] and line in g["ln"]]
                    if len(d) >= MIN_GROUP:
                        rows.append((vol[key][by] if by else 1.0, d))
                for extra, at in ptd_lines(sy):
                    for b in buckets(rows, EDGES[by] if by else (0.0,), line, sy, at=at):
                        game.append({"line": line, "stat": sy, "pos": pos, "by": by, "side": None, **extra, **b})
                if line not in SIDED:
                    continue
                for side, on in SIDES.items():
                    rows = []
                    for key, games in ps.items():
                        if games[0]["p"]["pos"] != pos:
                            continue
                        # (line, stat, spread) for his whole season, so the stat is cut at his
                        # season median; games on the other sides carry line 0 and are left out.
                        d = [(g["ln"][line] if on(g["ln"]["sp"]) else 0.0, g["p"][sy], g["ln"]["sp"])
                             for g in games if g["ln"] and line in g["ln"]]
                        if len(d) >= MIN_GROUP:
                            rows.append((vol[key][by] if by else 1.0, d))
                    for extra, at in ptd_lines(sy):
                        for b in buckets(rows, EDGES[by] if by else (0.0,), line, sy, bands=True, at=at):
                            game.append({"line": line, "stat": sy, "pos": pos, "by": by, "side": side, **extra, **b})

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "nflverse-data (stats_player_week, schedules); halftime scores from ESPN's scoreboard",
        "halves": HALF,
        "seasons": seasons,
        "team_games": len(teams),
        "method": "Gaussian-copula r that reproduces how often both legs hit at each group's median lines, "
                  "solved on simulated seasons so a rate read off a dozen games does not inflate it "
                  "(anytime TD 1+, game lines at the closing number; passing TDs at 2+ and again at 3+, "
                  "one row each, `at` 1.5 and 2.5); role = position and "
                  "that season's targets or carries a game; check = the same at upper-third lines. "
                  "win and h1win are fitted within 3-point bands of the closing spread; rows with a side "
                  "(dog: underdog of 3.5+, fav: favourite of 3.5+, even: between) are the spread and "
                  "moneyline lines fitted on those games alone, the same way; the first-half "
                  "total and spread are cut at straight-line fits on the closing total and spread",
        "lines": {"over": "game total Over the closing total", "cover": "his team covers the closing spread",
                  "tt": "his team Over its implied total, (total -/+ spread) / 2",
                  "win": "his team wins (the moneyline)",
                  "h1over": "first-half points Over the first-half total",
                  "h1cover": "his team covers the first-half spread",
                  "h1win": "his team leads at the half (ties left out)"},
        "stack": stack,
        "game": game,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))

    def rng(b):
        return f"{b['min']:g}+" if b["max"] is None else f"{b['min']:g}-{b['max']:g}"

    def show(b, what):
        c = b["check"] or {}
        print(f"  {what:<34}{b['r']:>+7.3f} ±{b['se'] or 0:.3f}{b['games']:>8}  both {b['both']:.3f} vs "
              f"{b['unrelated']:.3f} unrelated   upper third {c.get('actual', float('nan')):.3f} / {c.get('model', float('nan')):.3f}")

    print(f"NFL stack + game-line correlations, {seasons[0]}-{seasons[-1]}, {len(teams)} team-games")
    print("QB with a teammate (r, games, how often both hit; check: actual / model)")
    for b in stack:
        show(b, f"{b['qb']}{'@%g' % b['at'] if 'at' in b else ''}·{b['stat']} {b['pos']} {rng(b)} {b['by']}/g")
    print("Prop with a game line")
    for b in game:
        show(b, f"{b['stat']}{'@%g' % b['at'] if 'at' in b else ''}·{b['line']} {b['pos']}" + (f" {rng(b)} {b['by']}/g" if b["by"] else "") + (f" {b['side']}" if b["side"] else ""))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
