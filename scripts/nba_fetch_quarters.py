#!/usr/bin/env python3
"""Pull NBA quarter-by-quarter line scores from ESPN's public scoreboard.

One row per final regular-season game: date, home/away team and each side's
points in Q1..Q4 (plus any OT periods). The quarter-splits page
(public/nba_quarters.html) aggregates these per team in the browser, so the
viewer can slice by season, last-N games and home/away.

Seasons use ESPN's convention (2027 = the 2026-27 season). A finished season
already in the output file is kept as is; only the current season is refetched.

Data source (no key required):
  https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD

Usage:
  python3 scripts/nba_fetch_quarters.py                  # seasons 2026, 2027
  python3 scripts/nba_fetch_quarters.py --seasons 2025 2026 2027 --workers 16
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import sys
import time
import urllib.request

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
OUT = os.path.join(os.path.dirname(__file__), "..", "public", "data", "nba_quarters.json")


def get_json(url: str, tries: int = 4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                print(f"  ! {url}: {e}", file=sys.stderr)
                return None
            time.sleep(1.5 * (i + 1))


def season_window(season: int):
    """(start, end) dates of a season per ESPN's calendar."""
    # Ask a mid-season date for the league's season block.
    d = get_json(f"{SCOREBOARD}?dates={season}0115")
    if d and d.get("leagues"):
        s = d["leagues"][0].get("season", {})
        if s.get("year") == season:
            start = dt.date.fromisoformat(s["startDate"][:10])
            end = dt.date.fromisoformat(s["endDate"][:10])
            return start, end
    return dt.date(season - 1, 10, 1), dt.date(season, 6, 30)


def fetch_day(day: dt.date, season: int):
    d = get_json(f"{SCOREBOARD}?dates={day:%Y%m%d}")
    rows = []
    for e in (d or {}).get("events", []):
        se = e.get("season", {})
        if se.get("year") != season or se.get("type") != 2:  # regular season only
            continue
        c = e["competitions"][0]
        if not c.get("status", {}).get("type", {}).get("completed"):
            continue
        side = {}
        for t in c["competitors"]:
            ls = [int(round(float(x.get("value", 0)))) for x in t.get("linescores", [])]
            side[t["homeAway"]] = (t["team"]["abbreviation"], ls)
        if "home" not in side or "away" not in side:
            continue
        (h, hq), (a, aq) = side["home"], side["away"]
        if len(hq) < 4 or len(aq) < 4:
            continue
        rows.append({"id": e["id"], "d": e["date"][:10], "s": season,
                     "h": h, "a": a, "hq": hq, "aq": aq})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+", default=[2026, 2027])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    today = dt.datetime.now(dt.timezone.utc).date()
    old = {}
    if os.path.exists(args.out):
        with open(args.out) as f:
            old = json.load(f)
    old_games = old.get("games", [])
    done_seasons = set(old.get("complete_seasons", []))

    games, complete = [], []
    for season in args.seasons:
        start, end = season_window(season)
        if season in done_seasons:
            kept = [g for g in old_games if g["s"] == season]
            if kept:
                print(f"{season}: keeping {len(kept)} cached games (season complete)")
                games += kept
                complete.append(season)
                continue
        last = min(end, today)
        days = [start + dt.timedelta(n) for n in range((last - start).days + 1)]
        print(f"{season}: fetching {len(days)} days {start}..{last}")
        got = []
        with cf.ThreadPoolExecutor(args.workers) as ex:
            for rows in ex.map(lambda x: fetch_day(x, season), days):
                got += rows
        print(f"  {len(got)} final games")
        games += got
        if end < today and got:
            complete.append(season)

    # A fetch that came back empty shouldn't wipe out existing data.
    if not games:
        print("No games fetched — leaving existing file untouched.", file=sys.stderr)
        sys.exit(1)

    dedup = {g["id"]: g for g in games}
    games = sorted(dedup.values(), key=lambda g: (g["d"], g["id"]))
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "seasons": sorted(args.seasons), "complete_seasons": sorted(complete),
           "games": games}
    with open(args.out, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"Wrote {len(games)} games -> {args.out}")


if __name__ == "__main__":
    main()
