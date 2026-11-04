#!/usr/bin/env python3
"""Game logs + assist links for the NBA TEAMMATES tab.

Writes public/data/nba_teammate_logs.json: for every player on a current
roster, his box line in each game he played for that team (last season and
this one), plus play-by-play assist totals between current teammates. The
page computes every teammate stat correlation from these logs in the
browser, at tonight's Pinnacle lines.

  python3 scripts/nba_teammate_logs.py                  # seasons 2026 2027
  python3 scripts/nba_teammate_logs.py --seasons 2027

Game summaries are cached in .cache/nba_games_<season>.json by
scripts/nba_fetch_teammates.py's fetch_games, so reruns only fetch new games.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from nba_fetch_correlations import make_session, team_roster_map  # noqa: E402
from nba_fetch_teammates import fetch_games  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="+", default=[2026, 2027])
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default=os.path.join(ROOT, "public", "data", "nba_teammate_logs.json"))
    args = ap.parse_args()

    games = []
    for s in sorted(args.seasons):
        for g in fetch_games(s, args.workers, os.path.join(ROOT, ".cache", f"nba_games_{s}.json")):
            g["season"] = s
            games.append(g)
    if not games:
        sys.exit("No games fetched; leaving the data file alone.")
    roster = team_roster_map(make_session())
    if not roster:
        sys.exit("No rosters from ESPN; leaving the data file alone.")

    names: dict[str, str] = {}
    for g in games:
        names.update(g["names"])
    games.sort(key=lambda g: (g["d"], g["id"]))
    gidx = {g["id"]: i for i, g in enumerate(games)}

    # log only the games each player played for his current team
    logs: dict[str, list] = defaultdict(list)
    for g in games:
        for aid, ln in g["p"].items():
            cur = roster.get(aid)
            if cur and g["abbr"].get(ln["t"]) == cur["team_abbr"]:
                logs[aid].append([gidx[g["id"]], g["season"], int(ln["min"]), ln["pts"], ln["reb"],
                                  ln["ast"], ln["tpm"], ln["fgm"]])
    # assist totals between current teammates, over games both played for that team
    assists: dict[str, list] = defaultdict(lambda: [0, 0])
    for g in games:
        for key, (two, three) in g["ae"].items():
            a, b = key.split(">")
            ca, cb = roster.get(a), roster.get(b)
            if not ca or not cb or ca["team_abbr"] != cb["team_abbr"]:
                continue
            if g["abbr"].get(g["p"][a]["t"]) != ca["team_abbr"]:
                continue
            e = assists[key]
            e[0] += two
            e[1] += three

    players = [{"id": aid, "name": names.get(aid, aid), "team": roster[aid]["team_abbr"],
                "team_name": roster[aid]["team_name"]} for aid in logs]
    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "ESPN NBA game summaries (box score + play-by-play), current rosters",
        "seasons": sorted(args.seasons),
        "season_labels": {s: f"{s - 1}-{str(s)[2:]}" for s in args.seasons},
        "games": [g["d"] for g in games],
        "log_fields": ["game", "season", "min", "pts", "reb", "ast", "tpm", "fgm"],
        "players": players,
        "logs": logs,
        "assists": {k: v for k, v in assists.items() if v[0] or v[1]},
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"Wrote {args.out}: {len(players)} players, {len(games)} games, {len(out['assists'])} assist links")


if __name__ == "__main__":
    main()
