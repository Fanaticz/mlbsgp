#!/usr/bin/env python3
"""NFL correlations between two different bets in one game, from nflverse:

  stack  a quarterback's passing with one of his own receivers or backs
         (passing yards + his WR's receiving yards, passing TDs + anytime TD)
  game   a player's prop with the game's closing total, his team's closing
         spread, or his team's implied total (QB passing yards + game Over,
         RB rushing yards + his team covering)

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
(anytime TD at 1+, passing TDs at 2+, the game lines at the closing number:
Over, cover, team total Over). r solves

    sum over groups [ n a b + (n - 1) (J(r; a, b) - a b) ] = games both hit

where a and b are the group's own hit rates and J the bivariate-normal joint.
The n - 1 is the usual loss of one game to the group's own averages. So a
slip of two legs near their main lines, priced with this r, hits as often as
it did over these seasons; `check` in the output is the same comparison at
harder lines (each stat's upper third), which the fit never saw.

Sources (nflverse-data releases, public):
  stats_player/stats_player_week_{season}.csv   weekly player stats
  schedules/games.csv                           results, closing spread / total

Usage:
  python3 scripts/nfl_stack_correlations.py              # last 10 seasons
  python3 scripts/nfl_stack_correlations.py --seasons 2021 2022 2023 2024 2025
  python3 scripts/nfl_stack_correlations.py --cache DIR   # keep the downloads
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import json
import math
import os
import statistics
import sys
import time
import urllib.request
from statistics import NormalDist

REL = "https://github.com/nflverse/nflverse-data/releases/download"
ND = NormalDist()

MIN_GROUP = 6        # games a group needs
QB_MIN_ATT = 15      # pass attempts for a QB's game to count (the team's most that day)
EDGES = {"tgt": (3.0, 5.0, 7.0, 9.0), "car": (8.0, 13.0, 18.0)}  # role buckets: per-game volume from
MIN_GAMES = 1500     # a bucket with fewer games is merged into the one below it

# stat -> nflverse column(s)
COLS = {"att": ("attempts",), "cmp": ("completions",), "pyds": ("passing_yards",), "ptd": ("passing_tds",),
        "car": ("carries",), "ryds": ("rushing_yards",), "rec": ("receptions",), "tgt": ("targets",),
        "yds": ("receiving_yards",), "td": ("rushing_tds", "receiving_tds"),
        "rry": ("rushing_yards", "receiving_yards")}
# A leg's line inside a group: a fixed count, or the group's median.
FIXED = {"td": 0.5, "ptd": 1.5, "over": 0.0, "cover": 0.0, "tt": 0.0}

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
LINES = ("over", "cover", "tt")


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


def load(seasons: list[int], cache: str | None):
    """(team-games, lines): team-games[(game_id, team)] = that team's players,
    each {id, name, pos, season, stats...}; lines[(game_id, team)] = how the
    game landed against the closing numbers, from that team's side."""
    lines = {}
    for g in csv.DictReader(io.StringIO(fetch("schedules/games.csv", cache))):
        try:
            res, tot, sp, tl = float(g["result"]), float(g["total"]), float(g["spread_line"]), float(g["total_line"])
            hs, as_ = float(g["home_score"]), float(g["away_score"])
        except (KeyError, ValueError):
            continue
        if g.get("game_type") != "REG":
            continue
        # result = home - away; spread_line = points the home team is favoured by.
        lines[(g["game_id"], g["home_team"])] = {"over": tot - tl, "cover": res - sp, "tt": hs - (tl + sp) / 2}
        lines[(g["game_id"], g["away_team"])] = {"over": tot - tl, "cover": sp - res, "tt": as_ - (tl - sp) / 2}
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


def line_of(vals: list[float], stat: str, q: float = 0.5) -> float:
    if stat in FIXED:
        return FIXED[stat]
    s = sorted(vals)
    return statistics.median(s) if q == 0.5 else s[min(len(s) - 1, int(q * len(s)))]


def cut(pairs: list[tuple[float, float]], sx: str, sy: str, q: float = 0.5):
    """(n, a, b, both) for one group at its lines, or None if a leg never / always hits."""
    n = len(pairs)
    lx, ly = line_of([x for x, _ in pairs], sx, q), line_of([y for _, y in pairs], sy, q)
    a = sum(x > lx for x, _ in pairs) / n
    b = sum(y > ly for _, y in pairs) / n
    if not (0.08 <= a <= 0.92 and 0.08 <= b <= 0.92):
        return None
    return n, a, b, sum(x > lx and y > ly for x, y in pairs)


def fit(cuts: list[tuple]) -> dict | None:
    """The r that reproduces the games both legs hit, with a rough standard error."""
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


def check(groups: list[list[tuple[float, float]]], sx: str, sy: str, r: float) -> dict | None:
    """Out of the fit's sight: both legs at each group's upper-third lines
    (counts with a fixed line keep it), actual vs what r says."""
    cuts = [c for g in groups for c in [cut(g, sx, sy, 2 / 3)] if c]
    if not cuts or (sx in FIXED and sy in FIXED):   # both lines fixed: nothing the fit didn't see
        return None
    games = sum(c[0] for c in cuts)
    model = sum(n * a * b + (n - 1) * (joint(r, ND.inv_cdf(a), ND.inv_cdf(b), a * b) - a * b) for n, a, b, _ in cuts)
    return {"actual": round(sum(c[3] for c in cuts) / games, 4), "model": round(model / games, 4)}


def buckets(rows: list[tuple[float, list]], edges: tuple, sx: str, sy: str) -> list[dict]:
    """rows = (volume, group's pairs). One fit per volume bucket, thin buckets
    merged downward (the top bucket into the one below it)."""
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
        f = fit([c for g in groups for c in [cut(g, sx, sy)] if c])
        if f:
            out.append({"min": lo, "max": hi, **f, "check": check(groups, sx, sy, f["r"])})
    return out


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
            for b in buckets(rows, EDGES[by], sx, sy):
                stack.append({"qb": sx, "stat": sy, "pos": pos, "by": by, **b})

    game = []
    for sy, positions, by in GAME:
        for pos in positions:
            for line in LINES:
                rows = []
                for key, games in ps.items():
                    if games[0]["p"]["pos"] != pos:
                        continue
                    d = [(g["ln"][line], g["p"][sy]) for g in games if g["ln"]]
                    if len(d) >= MIN_GROUP:
                        rows.append((vol[key][by] if by else 1.0, d))
                for b in buckets(rows, EDGES[by] if by else (0.0,), line, sy):
                    game.append({"line": line, "stat": sy, "pos": pos, "by": by, **b})

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "nflverse-data (stats_player_week, schedules)",
        "seasons": seasons,
        "team_games": len(teams),
        "method": "Gaussian-copula r that reproduces how often both legs hit at each group's median lines "
                  "(anytime TD 1+, passing TDs 2+, game lines at the closing number); role = position and "
                  "that season's targets or carries a game; check = the same at upper-third lines",
        "lines": {"over": "game total Over the closing total", "cover": "his team covers the closing spread",
                  "tt": "his team Over its implied total, (total -/+ spread) / 2"},
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
        show(b, f"{b['qb']}·{b['stat']} {b['pos']} {rng(b)} {b['by']}/g")
    print("Prop with a game line")
    for b in game:
        show(b, f"{b['stat']}·{b['line']} {b['pos']}" + (f" {rng(b)} {b['by']}/g" if b["by"] else ""))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
