#!/usr/bin/env python3
"""NFL teammates who are not a QB and his receiver: how two of one team's
players' props move together (two receivers' yards, a back's rushing yards
with a receiver's yards, two backs' rushing yards, two players' touchdowns).

  python3 scripts/nfl_mate_correlations.py              # last 10 seasons
  python3 scripts/nfl_mate_correlations.py --cache DIR  # keep the downloads

Same data and the same r as scripts/nfl_stack_correlations.py (nflverse
weekly stats; the Gaussian-copula r that reproduces how often both legs hit,
each stat cut at the group's median, anytime TD at 1+, solved on simulated
seasons). A group is one pair of teammates in one season, the games both
played (6 needed). League-wide by role, like the stacks: a pair shares a
dozen games a season, far too few for a number of its own.

Roles: a receiver (WR or TE) by his targets a game that season, R1 2 to 4,
R2 4 to 7, R3 7 or more; a back by his carries, B1 2 to 6, B2 6 to 13, B3 13
or more.

Each cell is fitted twice. `r` is on the games both have a line in the
weekly stats. A player with no catch, target or carry has no line that week,
though a prop on him would have lost. So `r_filled` adds those games: one he
took an offensive snap in (nflverse snap counts, matched by game, team and
name) with no line counts as a zero for him. Weeks he did not play are left
out, as a bet on him would have been void. The scanner prices at the lower of
the two less one standard error.

Measured 11-28 (2017-2026): nothing here is far from unrelated. Two
receivers' yards -0.10 to +0.04 (two 7-target receivers the lowest),
receptions +0.02 to +0.09, two receivers' touchdowns -0.10 to -0.02, a back's
rushing yards with a receiver's yards -0.09 to +0.01, their touchdowns -0.11
to +0.05, a lead back's rushing yards with the second back's +0.19 (two
backs sharing the carries +0.06). Counting the blank games moves no cell by
more than 0.05; taking the closing spread and team total out of each stat
first moved none of twelve cells by more than 0.03.
"""
import argparse
import collections
import csv
import datetime as dt
import io
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_stack_correlations as S  # noqa: E402

EDGES = {"R": (2.0, 4.0, 7.0), "B": (2.0, 6.0, 13.0)}   # targets a game, carries a game
# the pairings fitted, by the two roles' kinds (the first player's stat, the second's)
STATS = {"RR": (("yds", "yds"), ("rec", "rec"), ("td", "td")),
         "BR": (("ryds", "yds"), ("td", "td")),
         "BB": (("ryds", "ryds"), ("td", "td"))}
MIN_GAMES = 1000   # a cell with fewer games gets no row


def role_of(pos, tgt, car):
    """'R3', 'B1', ... or None: the role names used in the data file."""
    kind, v = ("R", tgt) if pos in ("WR", "TE") else ("B", car) if pos == "RB" else (None, None)
    if kind is None or v is None or v < EDGES[kind][0]:
        return None
    return kind + str(sum(v >= e for e in EDGES[kind]))


SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm(name):
    """'Aaron Jones Sr.' (weekly stats) and 'Aaron Jones' (snap counts) -> 'aaronjones'."""
    words = "".join(c if c.isalnum() or c == " " else "" for c in name.lower()).split()
    return "".join(w for w in words if w not in SUFFIXES)


def snaps(seasons, cache):
    """{(game id, team, name)}: everyone who took an offensive snap."""
    out = set()
    for yr in seasons:
        try:
            text = S.fetch(f"snap_counts/snap_counts_{yr}.csv", cache)
        except Exception as e:  # noqa: BLE001 - a season with no file adds no zeros
            print(f"  no snap counts for {yr}: {e}", file=sys.stderr)
            continue
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("game_type") == "REG" and S.num(r.get("offense_snaps")) > 0:
                out.add((r["game_id"], r["team"], norm(r["player"])))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="+", default=None, help="default: the last 10, through this one")
    ap.add_argument("--out", default=os.path.join("public", "data", "nfl_mate_correlations.json"))
    ap.add_argument("--cache", default=None, help="directory to keep the nflverse downloads in")
    a = ap.parse_args()
    today = dt.date.today()
    cur = today.year if today.month >= 9 else today.year - 1
    seasons = sorted(a.seasons or range(cur - 9, cur + 1))
    teams, _ = S.load(seasons, a.cache)
    if len(teams) < 500:
        sys.exit("Too few games from nflverse; refusing to overwrite the data file.")
    played = snaps(seasons, a.cache)
    tot, by_team, name = collections.defaultdict(lambda: [0, 0.0, 0.0]), collections.defaultdict(dict), {}
    for (gid, team), players in teams.items():
        by_team[(team, int(gid.split("_")[0]))][gid] = players
        for p in players:
            t = tot[(p["id"], p["season"])]
            t[0] += 1
            t[1] += p["tgt"]
            t[2] += p["car"]
            name[p["id"]] = norm(p["name"])
    zero = dict.fromkeys(S.COLS, 0.0)
    cells = {False: collections.defaultdict(lambda: collections.defaultdict(list)),
             True: collections.defaultdict(lambda: collections.defaultdict(list))}
    zeros = 0
    for (team, season), weeks in by_team.items():
        ids = {}
        for players in weeks.values():
            for p in players:
                t = tot[(p["id"], season)]
                r = role_of(p["pos"], t[1] / t[0], t[2] / t[0])
                if r:
                    ids[p["id"]] = r
        for (ia, ra), (ib, rb) in itertools.combinations(ids.items(), 2):
            if (ra[0] == rb[0] and (ra, ia) < (rb, ib)) or (ra[0], rb[0]) == ("R", "B"):
                ia, ib, ra, rb = ib, ia, rb, ra   # a back before a receiver, else the higher role first
            for gid, players in weeks.items():
                x = next((p for p in players if p["id"] == ia), None)
                y = next((p for p in players if p["id"] == ib), None)
                if x and y:
                    cells[False][(ra, rb)][(ia, ib, season)].append((x, y))
                x = x or ((gid, team, name[ia]) in played and zero)
                y = y or ((gid, team, name[ib]) in played and zero)
                if x and y and not (x is zero and y is zero):
                    zeros += x is zero or y is zero
                    cells[True][(ra, rb)][(ia, ib, season)].append((x, y))
    print(f"  {zeros} pair-games added where one of the two took a snap and has no line", file=sys.stderr)
    rows = []
    for ra, rb in sorted(cells[False], reverse=True):
        for sx, sy in STATS[ra[0] + rb[0]]:
            fits = {}
            for filled in (False, True):
                gs = [[(x[sx], y[sy]) for x, y in g] for g in cells[filled][(ra, rb)].values() if len(g) >= S.MIN_GROUP]
                fits[filled], _ = S.fit_groups([S.tally(g, sx, sy) for g in gs], S.fixed(sx), S.fixed(sy))
            f, g = fits[False], fits[True]
            if not f or not g or f["games"] < MIN_GAMES or f["se"] is None or g["se"] is None:
                continue
            rows.append({"a": ra, "b": rb, "sa": sx, "sb": sy, "r": f["r"], "se": f["se"], "games": f["games"],
                         "both": f["both"], "unrelated": f["unrelated"],
                         "r_filled": g["r"], "se_filled": g["se"], "games_filled": g["games"]})
            print(f"  {ra}·{rb} {sx + '·' + sy:<10}{f['r']:>+7.3f} ±{f['se']:.3f} {f['games']:>6} games   "
                  f"with his blank games as zeros {g['r']:>+7.3f} ±{g['se']:.3f} {g['games']:>6}")
    payload = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
               "source": "nflverse-data (stats_player_week, snap_counts)", "seasons": seasons, "team_games": len(teams),
               "roles": {"R": "WR or TE by targets a game", "B": "RB by carries a game", "edges": EDGES},
               "method": "Gaussian-copula r of both Overs at each pair-season's median lines (anytime TD at 1+), "
                         "solved on simulated seasons as in nfl_stack_correlations.py; r_filled also counts a game "
                         "a player took an offensive snap in with no line in the weekly stats, as a zero for him",
               "rows": rows}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Wrote {a.out}: {len(rows)} rows, {seasons[0]}-{seasons[-1]}, {len(teams)} team-games")


if __name__ == "__main__":
    main()
