#!/usr/bin/env python3
"""Build teammate-pair correlation aggregates from raw batter game logs.

Reads the four xlsx files (2023, 2024, 2025, 2026), filters to batter rows
with PA > 0 AND BO# populated (starting lineup only; pinch hitters and late
subs whose BO# is null are dropped), indexes per (game, team, lineup slot),
and produces two families of correlation output in public/data/:

  * teammate_aggregates_pooled_<scheme>.json — one file per year-weighting
    scheme. Each file carries per-(p1, p2, team) pair data: n_by_year,
    slot_gap, adjacency, most_common_slots, and combos_2 (r_binary weighted
    phi, r_margin weighted Pearson, hit rates, conditional probs). Pair key
    is (p1_name, p2_name, team) so traded players are segmented correctly
    (Torres-Yankees 2024 vs Torres-Tigers 2025 are separate pairs).

  * slot_pair_baselines.json — league-wide slot-pair correlations for ordered
    slot pairs (1,2), (1,3), ... (9,8), pooling all player dyads playing in
    those exact slots. Used as the Bayesian prior for blended mode — specific
    pair correlations are shrunk toward their lineup slot's baseline, not
    toward zero, since slot position carries real causal-order information
    (leadoff R → cleanup RBI flow, etc).

  This file only carries the skeleton / config / load + index logic. Slot
  baselines and pair aggregation are added in follow-up commits.

Notes on the data shape:
  * One row per (game, team, BO#) for starters; 59 known cases in 2025 where
    a double-switch moves two players through the same slot, both with
    partial PA — both kept and both get teammate credit for that game.
  * GAME-ID already disambiguates doubleheaders via the trailing -1 / -2
    suffix, so no special handling is needed there.
  * DH is naturally covered — the xlsx has a row for the designated hitter
    with BO# populated just like any other starter.
  * HRR composite = H + R + RBI, computed at row-load time.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "public" / "data"

# year -> (xlsx filename, sheet name) — mirrors build_pitcher_data.py
SOURCES = {
    2023: ("MLB-2023-Player-BoxScore-Dataset.xlsx", "2023-MLB-PLAYER"),
    2024: ("MLB-2024-Player-BoxScore-Dataset.xlsx", "2024-MLB-PLAYER"),
    2025: ("MLB-2025-Player-BoxScore-Dataset.xlsx", "2025-MLB-PLAYER"),
    2026: ("04-16-2026-mlb-season-player-feed.xlsx", "MLB-2026-PLAYER"),
}

YEARS = [2023, 2024, 2025, 2026]
CURRENT_YEAR = 2026

# Per-game batter stats we track. HRR ("hits + runs + RBI") is a composite;
# the other eight are raw xlsx columns renamed to short keys.
STATS = ["H", "R", "RBI", "HR", "TB", "BB", "SB", "SO", "HRR"]

# Column map: xlsx source header -> short key used throughout this script.
# PA and BO# drive the filter only; they aren't carried into correlation math.
BATTER_COLS = {
    "GAME-ID":   "gid",
    "DATE":      "d",
    "PLAYER-ID": "pid",
    "PLAYER":    "p",
    "TEAM":      "t",
    "BO#":       "bo",
    "PA":        "pa",
    "H":         "H",
    "R":         "R",
    "RBI":       "RBI",
    "HR":        "HR",
    "TB":        "TB",
    "BB":        "BB",
    "SB":        "SB",
    "SO":        "SO",
}

# Threshold lines used to dichotomize each stat for binary phi. HRR uses
# composite-scale thresholds (1.5/2.5/3.5) because 0.5 is near-trivial for
# any starting batter.
THRESHOLDS: dict[str, list[float]] = {
    "H":   [0.5, 1.5, 2.5],
    "R":   [0.5, 1.5],
    "RBI": [0.5, 1.5, 2.5],
    "HR":  [0.5],
    "TB":  [0.5, 1.5, 2.5, 3.5],
    "BB":  [0.5, 1.5],
    "SB":  [0.5],
    "SO":  [0.5, 1.5, 2.5],
    "HRR": [1.5, 2.5, 3.5],
}

# Year-weighting schemes keyed on each PAIR's 2026 sample size. Teammate
# pairs need more sample to stabilize than pitcher starts, so 2026 weights
# are lower than pitcher buckets and bucket boundaries are higher (10/25/60
# vs pitcher's 3/8/15). Static is the manual fallback; unweighted is
# diagnostic-only (every game weighted equally).
WEIGHT_SCHEMES: dict[str, dict[int, float]] = {
    "dyn_1_10":    {2023: 0.20, 2024: 0.25, 2025: 0.45, 2026: 0.10},
    "dyn_11_25":   {2023: 0.15, 2024: 0.20, 2025: 0.35, 2026: 0.30},
    "dyn_26_60":   {2023: 0.10, 2024: 0.15, 2025: 0.30, 2026: 0.45},
    "dyn_61plus":  {2023: 0.08, 2024: 0.12, 2025: 0.25, 2026: 0.55},
    "static":      {2023: 0.15, 2024: 0.20, 2025: 0.30, 2026: 0.35},
    "unweighted":  {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
}

# Slot-pair baselines use static weights only — the league-wide sample at
# each (slot_i, slot_j) is large enough that dynamic buckets add noise, not
# signal.
SLOT_BASELINE_SCHEME = "static"


def bucket_for_2026(n_2026: int) -> str:
    """Pick a dynamic scheme key from a pair's 2026 game count."""
    if n_2026 <= 10:
        return "dyn_1_10"
    if n_2026 <= 25:
        return "dyn_11_25"
    if n_2026 <= 60:
        return "dyn_26_60"
    return "dyn_61plus"


# Pair emission threshold: keep a pair if it has meaningful total sample,
# with a lower bar when the pair has real 2026 presence (tonight-bettable).
PAIR_MIN_TOTAL_COLD  = 30  # n_2026 <  PAIR_WARM_2026 → need 30+ lifetime games
PAIR_MIN_TOTAL_WARM  = 20  # n_2026 >= PAIR_WARM_2026 → 20 lifetime games is OK
PAIR_WARM_2026       = 10

# Per-combo emission threshold: emit only combos with enough sample for a
# meaningful weighted phi. All combos in a pair share n_total, so this
# effectively redundant with PAIR_MIN_TOTAL_* today — kept as an explicit
# knob for future variance-dependent filtering.
COMBO_MIN_N = 20

# Shrinkage config used by the UI. Committed here as documentation; the
# frontend applies shrinkage at render time against the slot baseline.
K_PAIR = 80              # pseudo-games — prior weight in r_blended formula
BLEND_MIN_GAMES_PAIR = 30  # under this, blended mode falls back to pure baseline


# --------------------------------------------------------------------------- #
# combo spec                                                                  #
# --------------------------------------------------------------------------- #

def _over(thresh: float, stat: str) -> str:
    return f"Over {thresh} {stat}"

def _under(thresh: float, stat: str) -> str:
    return f"Under {thresh} {stat}"


def build_combo_spec() -> list[tuple[str, str]]:
    """Return the full ordered list of (leg1, leg2) combos.

    Leg strings use the same "Direction Thresh Stat" convention as the
    pitcher side so the UI can reuse leg-parsing helpers.
    """
    combos: list[tuple[str, str]] = []

    # Run-scoring flow — p1 drives p2's line or vice versa.
    for x in (0.5, 1.5):
        for y in (0.5, 1.5):
            combos.append((_over(x, "R"), _over(y, "RBI")))
    for x in (0.5, 1.5, 2.5):
        for y in (0.5, 1.5):
            combos.append((_over(x, "RBI"), _over(y, "R")))
    for x in (0.5, 1.5, 2.5):
        for y in (0.5, 1.5):
            combos.append((_over(x, "H"), _over(y, "R")))
    for x in (0.5, 1.5):
        for y in (0.5, 1.5):
            combos.append((_over(x, "BB"), _over(y, "R")))
    for x in (0.5, 1.5, 2.5):
        for y in (0.5, 1.5, 2.5):
            combos.append((_over(x, "H"), _over(y, "RBI")))

    # Same-stat both-players — offensive inning co-occurrence.
    for x in (0.5, 1.5, 2.5):
        combos.append((_over(x, "H"), _over(x, "H")))
    for x in (0.5, 1.5, 2.5, 3.5):
        combos.append((_over(x, "TB"), _over(x, "TB")))
    for x in (0.5, 1.5):
        combos.append((_over(x, "R"), _over(x, "R")))
    for x in (0.5, 1.5, 2.5):
        combos.append((_over(x, "RBI"), _over(x, "RBI")))
    for x in (1.5, 2.5, 3.5):
        combos.append((_over(x, "HRR"), _over(x, "HRR")))
    for x in (0.5, 1.5):
        combos.append((_over(x, "BB"), _over(x, "BB")))

    # Power flow — p1 HRs feed p2's run/rbi/tb.
    for y in (0.5, 1.5):
        combos.append((_over(0.5, "HR"), _over(y, "R")))
    for y in (0.5, 1.5):
        combos.append((_over(0.5, "HR"), _over(y, "RBI")))
    for y in (1.5, 2.5):
        combos.append((_over(0.5, "HR"), _over(y, "TB")))

    # TB cross-flow.
    for x in (1.5, 2.5):
        for y in (0.5, 1.5):
            combos.append((_over(x, "TB"), _over(y, "R")))
    for x in (1.5, 2.5):
        for y in (0.5, 1.5, 2.5):
            combos.append((_over(x, "TB"), _over(y, "RBI")))
    for x in (1.5, 2.5):
        for y in (0.5, 1.5):
            combos.append((_over(x, "TB"), _over(y, "H")))

    # HRR composite.
    for x in (1.5, 2.5):
        for y in (0.5, 1.5):
            combos.append((_over(x, "HRR"), _over(y, "R")))
    for x in (1.5, 2.5):
        for y in (0.5, 1.5):
            combos.append((_over(x, "HRR"), _over(y, "RBI")))

    # Negative / bust — one leg flipped direction.
    for x in (0.5, 1.5):
        combos.append((_over(x, "SO"), _under(0.5, "R")))
    for y in (0.5, 1.5):
        combos.append((_under(0.5, "H"), _over(y, "R")))

    return combos


COMBO_SPEC: list[tuple[str, str]] = build_combo_spec()


def parse_leg(leg: str) -> tuple[str, float, str]:
    """'Over 1.5 RBI' -> ('Over', 1.5, 'RBI'). Stat is any STATS key."""
    direction, rest = leg.split(" ", 1)
    thresh_str, stat = rest.split(" ", 1)
    return direction, float(thresh_str), stat


# --------------------------------------------------------------------------- #
# data loading + game indexing                                                #
# --------------------------------------------------------------------------- #

def _clean_int(v) -> int:
    """Coerce a pandas/numpy scalar to int. NaN/None -> 0 (batters with PA>0
    have complete stat coverage in these xlsx files; defensive fallback)."""
    if v is None:
        return 0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    if math.isnan(f):
        return 0
    return int(f)


def load_batters_year(year: int, filename: str, sheet: str) -> list[dict]:
    """Read one xlsx file, filter to starting-lineup batter rows, return
    a list of dicts keyed by the short names in BATTER_COLS.

    Filter: PA > 0 AND BO# populated (pinch hitters / late subs with null
    BO# are dropped, matching the spec).
    """
    path = ROOT / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing source file for {year}: {path}")

    df = pd.read_excel(path, sheet_name=sheet, header=1)

    missing = [c for c in BATTER_COLS if c not in df.columns]
    if missing:
        raise KeyError(f"{year}: expected columns missing: {missing}")

    mask = df["PA"].notna() & (df["PA"] > 0) & df["BO#"].notna()
    # Regression guard: about half of all xlsx rows are batters; the other
    # half are pitchers / DH overlap with null BO#. If the filter silently
    # returns 0 rows or >60% of rows, something's broken upstream.
    total = len(df)
    kept = int(mask.sum())
    assert 0 < kept < total * 0.70, (
        f"{year}: batter filter produced {kept}/{total} rows "
        f"({kept / max(total, 1):.0%}); expected 30-60%. "
        "Starter filter or column schema likely broken."
    )
    batters = df.loc[mask, list(BATTER_COLS.keys())].rename(columns=BATTER_COLS)

    rows: list[dict] = []
    for row in batters.itertuples(index=False):
        r = {}
        for key, val in zip(batters.columns, row):
            if key in ("gid", "d", "p", "t"):
                r[key] = None if (val is None or (isinstance(val, float) and math.isnan(val))) else str(val) if key != "d" else val
            elif key == "pid":
                r[key] = _clean_int(val)
            elif key == "bo":
                r[key] = _clean_int(val)
            elif key == "pa":
                r[key] = _clean_int(val)
            else:
                r[key] = _clean_int(val)
        # Composite: hits + runs + RBI. Used for HRR threshold combos.
        r["HRR"] = r["H"] + r["R"] + r["RBI"]
        r["year"] = year
        rows.append(r)
    return rows


def index_games(
    rows_by_year: dict[int, list[dict]],
) -> dict[int, dict[str, dict[str, list[dict]]]]:
    """Group batter rows by (year, game_id, team) into lineup lists.

    Returns: games_by_year[year][gid][team] = [row, row, ...]
    The inner list holds every batter row tagged with that (game, team),
    typically 9 rows (one per slot) plus occasional double-switch extras.
    Lineup lists are NOT sorted by BO# — downstream code that needs slot
    ordering must sort explicitly on row["bo"].
    """
    games_by_year: dict[int, dict[str, dict[str, list[dict]]]] = {}
    for year, rows in rows_by_year.items():
        by_game: dict[str, dict[str, list[dict]]] = {}
        for r in rows:
            gid = r.get("gid")
            team = r.get("t")
            if not gid or not team:
                continue
            by_game.setdefault(gid, {}).setdefault(team, []).append(r)
        games_by_year[year] = by_game
    return games_by_year


# --------------------------------------------------------------------------- #
# slot baselines + pair aggregation — added in follow-up commits              #
# --------------------------------------------------------------------------- #

def compute_slot_baselines(
    games_by_year: dict[int, dict[str, dict[str, list[dict]]]],
) -> dict:
    """TODO (step 2.2): league-wide slot-pair correlations."""
    raise NotImplementedError("slot baseline aggregation lands in step 2.2")


def compute_pair_aggregates(
    games_by_year: dict[int, dict[str, dict[str, list[dict]]]],
    scheme_name: str,
    scheme_weights: dict[int, float],
) -> dict:
    """TODO (step 2.3): per-(p1, p2, team) pair aggregation with weighted
    phi + weighted Pearson for each combo in COMBO_SPEC."""
    raise NotImplementedError("pair aggregation lands in step 2.3")


# --------------------------------------------------------------------------- #
# main — skeleton: loads, indexes, prints summary. JSON output comes later.   #
# --------------------------------------------------------------------------- #

def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    rows_by_year: dict[int, list[dict]] = {}
    for year, (filename, sheet) in SOURCES.items():
        rows_by_year[year] = load_batters_year(year, filename, sheet)

    games_by_year = index_games(rows_by_year)

    print("Teammate dataset — skeleton load summary")
    print("-" * 64)
    for year in YEARS:
        rows = rows_by_year[year]
        gbg = games_by_year[year]
        team_games = sum(len(team_map) for team_map in gbg.values())
        print(
            f"  {year}: {len(rows):>6} batter rows  "
            f"{len(gbg):>5} games  "
            f"{team_games:>5} team-lineups"
        )
    print("-" * 64)
    print(f"  stats tracked:       {STATS}")
    print(f"  combos per pair:     {len(COMBO_SPEC)}")
    print(f"  weighting schemes:   {sorted(WEIGHT_SCHEMES.keys())}")
    print(f"  K_PAIR:              {K_PAIR} (prior strength in shrinkage blend)")
    print(f"  pair min n (cold):   {PAIR_MIN_TOTAL_COLD}")
    print(f"  pair min n (warm):   {PAIR_MIN_TOTAL_WARM} when n_2026 >= {PAIR_WARM_2026}")
    print()
    print("Slot baselines and pair aggregates land in follow-up commits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
