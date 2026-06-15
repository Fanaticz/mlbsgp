#!/usr/bin/env python3
"""
savant.py  -  automated Baseball Savant pulls for the Long Ball model.

Two inputs, both fetched programmatically (no manual CSV downloads):

  1. PER-HR DISTANCES  (feeds the top-5 / max distance ceiling)
     Statcast Search CSV endpoint, filtered to home runs for the given seasons.
     -> data/savant_event.csv   columns include player_name, game_date, bbdist (= hit_distance_sc)

  2. xHR LEADERBOARD   (feeds the P(HR) fallback + the slate team_abbrev)
     The /leaderboard/home-runs page embeds the full table as `var data = [...]`.
     -> data/savant_lb.csv      columns: player, year, team_abbrev, hr_total, xhr, xhr_diff, no_doubter_per

Both are cached in data/ and only re-fetched once per day (distance profiles barely move
day to day). Pass force=True to bypass the cache.

CLI:
  python3 savant.py            # refresh both caches if stale, print a summary
  python3 savant.py --force    # force re-fetch
"""

import datetime as dt
import io
import json
import os
import re
import sys

import pandas as pd
from curl_cffi import requests as cffi_requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

EVENT_CSV = os.path.join(DATA, "savant_event.csv")
LB_CSV    = os.path.join(DATA, "savant_lb.csv")

STATCAST_CSV = "https://baseballsavant.mlb.com/statcast_search/csv"
HR_LEADERBOARD = "https://baseballsavant.mlb.com/leaderboard/home-runs"

# curl_cffi impersonates a real Chrome TLS fingerprint -- plain urllib/requests get
# blocked by Savant's CDN the same way DK's Akamai blocks them.
_IMPERSONATE = "chrome"


def _default_seasons():
    """Current season + prior season, e.g. on a 2026 date -> ['2026', '2025']."""
    y = dt.date.today().year
    return [str(y), str(y - 1)]


def _is_fresh(path, max_age_hours=20):
    if not os.path.exists(path):
        return False
    age = (dt.datetime.now().timestamp() - os.path.getmtime(path)) / 3600.0
    return age < max_age_hours


def _get(url, params=None, timeout=90):
    r = cffi_requests.get(url, params=params, impersonate=_IMPERSONATE, timeout=timeout)
    r.raise_for_status()
    return r


# ------------------------------------------------------------------------------------
# 1. Per-HR distances  (Statcast Search CSV)
# ------------------------------------------------------------------------------------

def fetch_distances(seasons=None, force=False) -> pd.DataFrame:
    """Pull every home run's batted-ball distance for `seasons` and cache to EVENT_CSV.

    Savant's Statcast Search 'details' CSV is the same data behind the search page, but
    downloaded directly instead of scraping the rendered table. The `hfAB=home\\.\\.run|`
    filter scopes to home runs; `hfSea` is a pipe-joined list of years."""
    seasons = seasons or _default_seasons()
    if not force and _is_fresh(EVENT_CSV):
        return pd.read_csv(EVENT_CSV, low_memory=False)

    params = {
        "all": "true",
        "type": "details",
        "player_type": "batter",
        "hfAB": r"home\.\.run|",
        "hfSea": "|".join(seasons) + "|",
        "min_results": "0",
    }
    txt = _get(STATCAST_CSV, params=params).text
    df = pd.read_csv(io.StringIO(txt), low_memory=False)
    # keep just what the model needs; alias hit_distance_sc -> bbdist for longball.py
    cols = ["player_name", "game_date", "hit_distance_sc", "launch_speed", "events"]
    df = df[[c for c in cols if c in df.columns]].copy()
    df = df.rename(columns={"hit_distance_sc": "bbdist"})
    df = df.dropna(subset=["bbdist"])
    os.makedirs(DATA, exist_ok=True)
    df.to_csv(EVENT_CSV, index=False)
    return df


# ------------------------------------------------------------------------------------
# 2. xHR leaderboard  (embedded JSON on the HR leaderboard page)
# ------------------------------------------------------------------------------------

def fetch_leaderboard(force=False) -> pd.DataFrame:
    """Pull the season HR leaderboard (xHR, no-doubter%, team) and cache to LB_CSV.

    The page ships the table inline as `var data = [ {...}, ... ]`; we parse that JSON
    rather than the rendered HTML. Output columns match longball.load_hr_rate()."""
    if not force and _is_fresh(LB_CSV):
        return pd.read_csv(LB_CSV)

    html = _get(HR_LEADERBOARD).text
    m = re.search(r"var\s+data\s*=\s*(\[\{.*?\}\]);", html, re.S)
    if not m:
        raise RuntimeError("savant.py: could not find `var data` on the HR leaderboard page")
    rows = json.loads(m.group(1))
    df = pd.DataFrame(rows)
    keep = {
        "player": "player", "year": "year", "team_abbrev": "team_abbrev",
        "hr_total": "hr_total", "xhr": "xhr", "xhr_diff": "xhr_diff",
        "no_doubter_per": "no_doubter_per",
    }
    out = pd.DataFrame({dst: df[src] for src, dst in keep.items() if src in df.columns})
    for c in ("hr_total", "xhr", "xhr_diff", "no_doubter_per"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    os.makedirs(DATA, exist_ok=True)
    out.to_csv(LB_CSV, index=False)
    return out


def refresh(force=False):
    """Fetch both inputs; return (distance_df, leaderboard_df)."""
    dist = fetch_distances(force=force)
    lb = fetch_leaderboard(force=force)
    return dist, lb


def main():
    force = "--force" in sys.argv
    dist, lb = refresh(force=force)
    n_players = dist["player_name"].nunique()
    print(f"savant: distances  {len(dist):>6} HRs across {n_players} hitters "
          f"-> {os.path.relpath(EVENT_CSV, HERE)}")
    print(f"savant: leaderboard {len(lb):>5} batters (xHR) "
          f"-> {os.path.relpath(LB_CSV, HERE)}")


if __name__ == "__main__":
    main()
