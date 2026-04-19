#!/usr/bin/env python3
# Methodology note — read before changing how correlations are computed:
#
# The slot-pair and specific-pair correlations emitted here include BOTH
# causal flow (e.g., slot 2 scores when slot 3 drives him in) AND game-level
# common variance (high-scoring team-days elevate every slot's R and RBI
# hit rates together). This is INTENTIONAL for the betting use case.
#
# DraftKings prices teammate SGP legs as independent events and multiplies
# them. That independence assumption ignores BOTH components, so the full
# empirical correlation captures the full DK mispricing — not just the
# causal part. Partialing out game-level variance here would produce
# "cleaner" causal numbers but would systematically UNDERESTIMATE the joint
# probability DK is actually paying off at, and therefore underestimate EV
# for correlated SGPs.
#
# The `combo_game_variance_floors` field in slot_pair_baselines.json lets
# the UI distinguish "this correlation is purely game variance" from "this
# correlation has causal lift above the game-variance floor" as a diagnostic
# overlay — but the primary r values stay as the full empirical correlation
# that the betting math downstream needs.
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
from datetime import datetime, timezone
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
# correlation helpers (weighted phi / Pearson / mean)                         #
# --------------------------------------------------------------------------- #

def weighted_pearson(
    x: np.ndarray, y: np.ndarray, w: np.ndarray
) -> float | None:
    """Weighted Pearson r on equal-length 1D arrays. Returns None for
    degenerate samples (fewer than 2 positive-weight rows or zero variance
    on either side). For binary 0/1 inputs this is the weighted phi.

    Mirrors build_aggregates.py's helper so teammate and pitcher sides
    share the same numeric convention (including the [-1, 1] FP clamp and
    4-decimal rounding done by the caller).
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    w = np.asarray(w, dtype=np.float64)
    if x.size != y.size or x.size != w.size:
        return None
    m = np.isfinite(x) & np.isfinite(y) & np.isfinite(w) & (w > 0)
    if m.sum() < 2:
        return None
    x, y, w = x[m], y[m], w[m]
    ws = float(w.sum())
    if ws <= 0.0:
        return None
    mx = float((w * x).sum() / ws)
    my = float((w * y).sum() / ws)
    dx = x - mx
    dy = y - my
    vx = float((w * dx * dx).sum() / ws)
    vy = float((w * dy * dy).sum() / ws)
    if vx <= 0.0 or vy <= 0.0:
        return None
    cov = float((w * dx * dy).sum() / ws)
    den = math.sqrt(vx * vy)
    if den == 0.0:
        return None
    r = cov / den
    if r > 1.0:
        r = 1.0
    elif r < -1.0:
        r = -1.0
    return r


def weighted_mean(values: np.ndarray, w: np.ndarray) -> float | None:
    """Weighted mean; None if no positive weight mass. Used for hit rates
    (on 0/1 arrays) and for continuous stat means."""
    values = np.asarray(values, dtype=np.float64)
    w = np.asarray(w, dtype=np.float64)
    m = np.isfinite(values) & np.isfinite(w) & (w > 0)
    if not m.any():
        return None
    values, w = values[m], w[m]
    ws = float(w.sum())
    if ws <= 0.0:
        return None
    return float((w * values).sum() / ws)


def _round_r(v: float | None) -> float | None:
    if v is None:
        return None
    return round(float(v), 4)


def _round_p(v: float | None) -> float | None:
    if v is None:
        return None
    return round(float(v), 3)


# --------------------------------------------------------------------------- #
# slot-stat aggregation per team-game                                         #
# --------------------------------------------------------------------------- #

def _slot_stats_for_team_game(team_rows: list[dict]) -> dict[int, dict[str, int]]:
    """For one team's roster in one game, return {slot: {stat: sum_value}}.

    When two players share a BO# (double-switch / in-game lineup shuffle,
    ~60 cases per season), their stats are summed into the slot's totals.
    This matches what the slot itself did offensively that game — which is
    the right unit for slot-level baselines, since identity of the player
    in the slot is immaterial for slot-to-slot correlations.
    """
    by_slot: dict[int, dict[str, int]] = {}
    for r in team_rows:
        slot = r.get("bo")
        if slot is None or slot < 1 or slot > 9:
            continue
        d = by_slot.setdefault(slot, {s: 0 for s in STATS})
        for s in STATS:
            d[s] += int(r.get(s, 0) or 0)
    return by_slot


# --------------------------------------------------------------------------- #
# slot-pair baselines                                                         #
# --------------------------------------------------------------------------- #

def _compute_combo_game_variance_floors(
    team_game_obs: list[tuple[dict[int, dict[str, int]], float]],
) -> dict[str, dict]:
    """Per-combo "typical slot pair" floor — pooled across ALL 72 ordered
    slot pairs in every team-game.

    For each team-game, each ordered slot pair (i, j) with i != j and both
    slots present contributes one observation: (slot_i's stat1, slot_j's
    stat2). Pooling across all ordered pairs and all team-games gives the
    correlation a RANDOM ordered slot pair would exhibit for this combo —
    a genuine floor for comparing specific slot pairs against.

    Interpretation:
      * Specific slot-pair r_binary ≈ floor: pair is unremarkable, r is
        driven by the same within-game co-occurrence every slot pair
        experiences (good offensive day lifts all slots together).
      * Specific slot-pair r_binary >> floor: causal lift above the
        typical slot pair — e.g., slot 2 R × slot 3 RBI picks up direct
        same-inning flow on top of the shared-game-context baseline.
      * Specific slot-pair r_binary << floor: anti-correlation specific
        to this pair beyond the typical lift.

    Returned dict is keyed on "leg1||leg2" so the UI can do an O(1)
    lookup per combo without re-scanning the per-slot-pair list.
    """
    # Pre-size the pooled arrays. For each team-game with P present slots,
    # we emit P*(P-1) ordered pairs. In practice P=9 → 72 per team-game.
    n_pool = 0
    for by_slot, _w in team_game_obs:
        p = len(by_slot)
        if p >= 2:
            n_pool += p * (p - 1)

    # One parallel (p1, p2) pair of arrays per stat, filled by one pass
    # through team-games. Memory: 9 stats × 2 sides × 8B × ~1.1M ≈ 160MB
    # peak — well within the aggregator's budget.
    p1_stats = {s: np.empty(n_pool, dtype=np.float64) for s in STATS}
    p2_stats = {s: np.empty(n_pool, dtype=np.float64) for s in STATS}
    w_pool = np.empty(n_pool, dtype=np.float64)

    idx = 0
    for by_slot, w in team_game_obs:
        slots_present = [s for s in range(1, 10) if s in by_slot]
        if len(slots_present) < 2:
            continue
        for i in slots_present:
            si = by_slot[i]
            for j in slots_present:
                if i == j:
                    continue
                sj = by_slot[j]
                for s in STATS:
                    p1_stats[s][idx] = si[s]
                    p2_stats[s][idx] = sj[s]
                w_pool[idx] = w
                idx += 1
    assert idx == n_pool, f"pool size mismatch: {idx} vs {n_pool}"

    out: dict[str, dict] = {}
    for leg1, leg2 in COMBO_SPEC:
        d1, t1, stat1 = parse_leg(leg1)
        d2, t2, stat2 = parse_leg(leg2)
        v1 = p1_stats[stat1]
        v2 = p2_stats[stat2]
        h1 = (v1 > t1).astype(np.float64) if d1 == "Over" else (v1 < t1).astype(np.float64)
        h2 = (v2 > t2).astype(np.float64) if d2 == "Over" else (v2 < t2).astype(np.float64)
        r_floor_binary = weighted_pearson(h1, h2, w_pool)
        r_floor_margin = weighted_pearson(v1, v2, w_pool)
        key = f"{leg1}||{leg2}"
        out[key] = {
            "leg1":            leg1,
            "leg2":            leg2,
            "r_floor_binary":  _round_r(r_floor_binary),
            "r_floor_margin":  _round_r(r_floor_margin),
            "n_pool":          n_pool,
        }
    return out


def compute_slot_baselines(
    games_by_year: dict[int, dict[str, dict[str, list[dict]]]],
) -> dict:
    """League-wide baseline correlations per ordered (slot_i, slot_j).

    For each team-game we collapse the lineup to {slot: stats}. Then for
    every ordered slot pair (i, j) with i != j we emit one observation
    per team-game where both slots have entries. Weighted Pearson across
    all observations, with each year weighted by SLOT_BASELINE_SCHEME.

    Output mirrors the per-pair combos_2 structure so the UI can shrink
    specific pairs toward the matching slot baseline without re-shaping.
    """
    scheme_weights = WEIGHT_SCHEMES[SLOT_BASELINE_SCHEME]

    # Materialize team-game observations once. Each carries every slot's
    # summed stats plus the year weight we'll apply when building arrays.
    team_game_obs: list[tuple[dict[int, dict[str, int]], float]] = []
    for year in YEARS:
        year_w = float(scheme_weights.get(year, 0.0))
        if year_w <= 0.0:
            continue
        for gid, by_team in games_by_year[year].items():
            for _team, rows in by_team.items():
                by_slot = _slot_stats_for_team_game(rows)
                if len(by_slot) < 2:
                    continue
                team_game_obs.append((by_slot, year_w))

    total_games_sampled = len(team_game_obs)

    slot_pairs_out: dict[str, dict] = {}
    for i in range(1, 10):
        for j in range(1, 10):
            if i == j:
                continue

            # Collect parallel stat arrays + weight vector across every
            # team-game where both slots had entries.
            p1_arrs: dict[str, list[int]] = {s: [] for s in STATS}
            p2_arrs: dict[str, list[int]] = {s: [] for s in STATS}
            w_list: list[float] = []
            for by_slot, w in team_game_obs:
                si = by_slot.get(i)
                sj = by_slot.get(j)
                if si is None or sj is None:
                    continue
                for s in STATS:
                    p1_arrs[s].append(si[s])
                    p2_arrs[s].append(sj[s])
                w_list.append(w)

            n_dyad = len(w_list)
            if n_dyad < 2:
                slot_pairs_out[f"{i}_{j}"] = {
                    "n_dyad_games_total": n_dyad,
                    "combos_2": [],
                }
                continue

            p1_np = {s: np.asarray(p1_arrs[s], dtype=np.float64) for s in STATS}
            p2_np = {s: np.asarray(p2_arrs[s], dtype=np.float64) for s in STATS}
            w_np = np.asarray(w_list, dtype=np.float64)

            combos_out: list[dict] = []
            for leg1, leg2 in COMBO_SPEC:
                d1, t1, stat1 = parse_leg(leg1)
                d2, t2, stat2 = parse_leg(leg2)
                v1 = p1_np[stat1]
                v2 = p2_np[stat2]
                h1 = (v1 > t1).astype(np.float64) if d1 == "Over" else (v1 < t1).astype(np.float64)
                h2 = (v2 > t2).astype(np.float64) if d2 == "Over" else (v2 < t2).astype(np.float64)

                r_binary = weighted_pearson(h1, h2, w_np)
                # r_margin is direction-invariant: weighted Pearson on the
                # raw stat columns, regardless of how legs are dichotomized.
                r_margin = weighted_pearson(v1, v2, w_np)
                if r_binary is None and r_margin is None:
                    continue

                hit1 = weighted_mean(h1, w_np)
                hit2 = weighted_mean(h2, w_np)
                both = weighted_mean(h1 * h2, w_np)
                neither = weighted_mean((1.0 - h1) * (1.0 - h2), w_np)

                combos_out.append({
                    "leg1":         leg1,
                    "leg2":         leg2,
                    "stat1":        stat1,
                    "stat2":        stat2,
                    "thresh1":      t1,
                    "thresh2":      t2,
                    "r_binary":     _round_r(r_binary),
                    "r_margin":     _round_r(r_margin),
                    "n_this_combo": n_dyad,
                    "hit1_rate":    _round_p(hit1),
                    "hit2_rate":    _round_p(hit2),
                    "both_rate":    _round_p(both),
                    "neither_rate": _round_p(neither),
                })

            slot_pairs_out[f"{i}_{j}"] = {
                "n_dyad_games_total": n_dyad,
                "combos_2": combos_out,
            }

    combo_floors = _compute_combo_game_variance_floors(team_game_obs)

    return {
        "generated":           datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scheme":              SLOT_BASELINE_SCHEME,
        "weights":             {str(y): scheme_weights[y] for y in YEARS},
        "total_games_sampled": total_games_sampled,
        # Per-combo game-variance floor: correlation of team-level hit-
        # fractions (leg1 vs leg2) across all team-games. Keyed on
        # "leg1||leg2". Compare any slot_pair's combo r_binary against the
        # matching combo_floor to gauge causal lift above game variance.
        "combo_game_variance_floors": combo_floors,
        "slot_pairs":          slot_pairs_out,
    }


def _materialize_pair_observations(
    games_by_year: dict[int, dict[str, dict[str, list[dict]]]],
) -> dict[tuple, list[dict]]:
    """Walk every team-game, emit one observation per ORDERED pair of
    batters on the same team in the same game. Returns pairs keyed on
    (p1_name, p2_name, team_name) — ordered so (A, B) and (B, A) are
    distinct. Traded players get separate pair entries by team (Torres
    on NYY and Torres on DET are distinct teammates from other players'
    perspective).

    Each observation holds year, both slots, and both players' raw stat
    values for the 9 tracked stats. One-time materialization — all five
    weight schemes can iterate this structure without re-walking the
    xlsx-derived rows.
    """
    pairs: dict[tuple, list[dict]] = {}
    for year in YEARS:
        for _gid, by_team in games_by_year[year].items():
            for team, rows in by_team.items():
                # Keep only rows with a slot — pinch hitters with null
                # BO# were already dropped upstream, but be defensive.
                valid = [r for r in rows if r.get("bo")]
                n = len(valid)
                if n < 2:
                    continue
                for i in range(n):
                    r1 = valid[i]
                    for j in range(n):
                        if i == j:
                            continue
                        r2 = valid[j]
                        key = (r1["p"], r2["p"], team)
                        obs = {
                            "year":  year,
                            "slot1": r1["bo"],
                            "slot2": r2["bo"],
                        }
                        for s in STATS:
                            obs[f"{s}_1"] = r1[s]
                            obs[f"{s}_2"] = r2[s]
                        pairs.setdefault(key, []).append(obs)
    return pairs


def _pair_metadata(games: list[dict]) -> dict:
    """Compute the once-per-pair metadata fields (slot_usage histogram,
    slot_gap stats, adjacency, most_common_slots) shared across all
    schemes. n_by_year / n_total are also included here."""
    from collections import Counter

    year_counts: Counter = Counter(g["year"] for g in games)
    n_total = len(games)

    slot_pair_counts: Counter = Counter(
        (g["slot1"], g["slot2"]) for g in games
    )
    slot_usage = {f"{s1}_{s2}": cnt for (s1, s2), cnt in slot_pair_counts.items()}
    top_slot_pair, top_slot_pair_n = slot_pair_counts.most_common(1)[0]

    gaps = [abs(g["slot1"] - g["slot2"]) for g in games]
    slot_gap_mean = sum(gaps) / n_total
    slot_gap_mode = Counter(gaps).most_common(1)[0][0]
    adjacency = sum(1 for gp in gaps if gp == 1) / n_total

    p1_slot_counts: Counter = Counter(g["slot1"] for g in games)
    p2_slot_counts: Counter = Counter(g["slot2"] for g in games)
    most_common_slots = [
        p1_slot_counts.most_common(1)[0][0],
        p2_slot_counts.most_common(1)[0][0],
    ]

    return {
        "n_by_year":        {str(y): year_counts.get(y, 0) for y in YEARS},
        "n_total":          n_total,
        "n_2026":           year_counts.get(CURRENT_YEAR, 0),
        "slot_gap_mean":    round(slot_gap_mean, 2),
        "slot_gap_mode":    int(slot_gap_mode),
        "adjacency":        round(adjacency, 3),
        "most_common_slots": most_common_slots,
        "slot_usage":       slot_usage,
        "_top_slot_pair":   f"{top_slot_pair[0]}_{top_slot_pair[1]}",
        "_top_slot_pair_n": top_slot_pair_n,
    }


def _passes_pair_threshold(n_total: int, n_2026: int) -> bool:
    """Emission rule: pair survives if n_total >= 30, OR n_total >= 20
    when the pair has meaningful 2026 presence (n_2026 >= 10)."""
    if n_2026 >= PAIR_WARM_2026:
        return n_total >= PAIR_MIN_TOTAL_WARM
    return n_total >= PAIR_MIN_TOTAL_COLD


def compute_pair_aggregates(
    games_by_year: dict[int, dict[str, dict[str, list[dict]]]],
    scheme_name: str,
    scheme_weights: dict[int, float],
    pairs_raw: dict[tuple, list[dict]] | None = None,
) -> dict:
    """Per-(p1, p2, team) pair aggregation with weighted phi / weighted
    Pearson for every combo in COMBO_SPEC.

    pairs_raw (optional) is the output of _materialize_pair_observations
    — passed in to avoid re-walking team-games for each of the 5 schemes.
    """
    if pairs_raw is None:
        pairs_raw = _materialize_pair_observations(games_by_year)

    pairs_out: dict[str, dict] = {}

    for (p1, p2, team), games in pairs_raw.items():
        meta = _pair_metadata(games)
        if not _passes_pair_threshold(meta["n_total"], meta["n_2026"]):
            continue

        years = np.asarray([g["year"] for g in games], dtype=np.int64)
        weights = np.asarray(
            [float(scheme_weights.get(int(y), 0.0)) for y in years],
            dtype=np.float64,
        )
        p1_arrs = {
            s: np.asarray([g[f"{s}_1"] for g in games], dtype=np.float64)
            for s in STATS
        }
        p2_arrs = {
            s: np.asarray([g[f"{s}_2"] for g in games], dtype=np.float64)
            for s in STATS
        }

        # Each combo entry is a positional 5-tuple [rb, rm, h1, h2, b]
        # indexed by COMBO_SPEC position. Drops redundant fields that UI
        # can derive (neither = 1-h1-h2+b, given1 = b/h1, given2 = b/h2)
        # or that are constant within a pair (n_this_combo = pair.n_total,
        # most_common_slot_pair_for_this_combo = pair.top_slot_pair).
        # Output file shrinks from ~240MB to ~25MB; still sub-5MB gzipped.
        combos_arr: list[list] = []
        any_valid = False
        for leg1, leg2 in COMBO_SPEC:
            d1, t1, stat1 = parse_leg(leg1)
            d2, t2, stat2 = parse_leg(leg2)
            v1 = p1_arrs[stat1]
            v2 = p2_arrs[stat2]
            h1 = (v1 > t1).astype(np.float64) if d1 == "Over" else (v1 < t1).astype(np.float64)
            h2 = (v2 > t2).astype(np.float64) if d2 == "Over" else (v2 < t2).astype(np.float64)

            r_binary = weighted_pearson(h1, h2, weights)
            r_margin = weighted_pearson(v1, v2, weights)

            if (r_binary is None and r_margin is None) or meta["n_total"] < COMBO_MIN_N:
                combos_arr.append(None)
                continue

            any_valid = True
            hit1 = weighted_mean(h1, weights)
            hit2 = weighted_mean(h2, weights)
            both = weighted_mean(h1 * h2, weights)
            combos_arr.append([
                _round_r(r_binary),
                _round_r(r_margin),
                _round_p(hit1),
                _round_p(hit2),
                _round_p(both),
            ])

        if not any_valid:
            continue

        key_str = f"{p1}||{p2}||{team}"
        pairs_out[key_str] = {
            "p1":               p1,
            "p2":               p2,
            "t":                team,
            "n_by_year":        meta["n_by_year"],
            "n_total":          meta["n_total"],
            "slot_gap_mean":    meta["slot_gap_mean"],
            "slot_gap_mode":    meta["slot_gap_mode"],
            "adjacency":        meta["adjacency"],
            "most_common_slots": meta["most_common_slots"],
            "slot_usage":       meta["slot_usage"],
            # Pair-level shortcut: the (slot1, slot2) config this pair
            # batted together at most often. Phase 2 uses this to decide
            # whether tonight's actual slots match history or trigger a
            # slot-baseline re-blend. Same value used to be duplicated on
            # every combo entry; moved here to save ~60 bytes × 78 combos
            # × 10k pairs = ~47 MB per scheme file.
            "top_slot_pair":    meta["_top_slot_pair"],
            "top_slot_pair_n":  meta["_top_slot_pair_n"],
            "combos_2":         combos_arr,
        }

    # combo_spec is emitted once at the top of each file — per-pair
    # combos_2 arrays are positional over this list so UI can read
    # combo_spec[i] for legs while combos_2[i] carries the values. Keeps
    # per-pair output compact without losing self-description.
    combo_spec_out = [list(c) for c in COMBO_SPEC]

    return {
        "scheme":       scheme_name,
        "weights":      {str(y): float(scheme_weights.get(y, 0.0)) for y in YEARS},
        "current_year": CURRENT_YEAR,
        "k_pair":       K_PAIR,
        "blend_min_games_pair": BLEND_MIN_GAMES_PAIR,
        "pair_min_total_cold":  PAIR_MIN_TOTAL_COLD,
        "pair_min_total_warm":  PAIR_MIN_TOTAL_WARM,
        "pair_warm_2026":       PAIR_WARM_2026,
        # Shape of each combos_2[i] entry (positional):
        #   [r_binary, r_margin, hit1, hit2, both]
        # r_* rounded to 4 decimals; hit rates to 3 decimals; null entry
        # means that combo was skipped (zero variance or below COMBO_MIN_N).
        "combos_2_schema": ["r_binary", "r_margin", "hit1", "hit2", "both"],
        "combo_spec":   combo_spec_out,
        "n_pairs":      len(pairs_out),
        "pairs":        pairs_out,
    }


# --------------------------------------------------------------------------- #
# main — skeleton: loads, indexes, prints summary. JSON output comes later.   #
# --------------------------------------------------------------------------- #

def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    rows_by_year: dict[int, list[dict]] = {}
    for year, (filename, sheet) in SOURCES.items():
        rows_by_year[year] = load_batters_year(year, filename, sheet)

    games_by_year = index_games(rows_by_year)

    print("Teammate dataset — load summary")
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

    # Slot-pair baselines — league-wide, static weights, always large sample.
    slot_baselines = compute_slot_baselines(games_by_year)
    out_path = DATA_DIR / "slot_pair_baselines.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(slot_baselines, f, ensure_ascii=False, separators=(",", ":"))
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print("-" * 64)
    print(
        f"  slot baselines: {len(slot_baselines['slot_pairs'])} ordered pairs, "
        f"{slot_baselines['total_games_sampled']} team-games sampled, "
        f"{size_mb:.2f} MB  -> {out_path.relative_to(ROOT).as_posix()}"
    )

    # Materialize pair-observation dict once, re-use across all schemes.
    print()
    print("Materializing pair observations ...")
    pairs_raw = _materialize_pair_observations(games_by_year)
    print(f"  {len(pairs_raw):,} raw (p1, p2, team) groups before threshold")

    print()
    print("Pair aggregate build summary (pool-and-weight, one file per scheme)")
    print("-" * 64)
    for scheme_name, scheme_weights in WEIGHT_SCHEMES.items():
        agg = compute_pair_aggregates(
            games_by_year, scheme_name, scheme_weights, pairs_raw=pairs_raw,
        )
        fname = f"teammate_aggregates_pooled_{scheme_name}.json"
        path = DATA_DIR / fname
        with path.open("w", encoding="utf-8") as f:
            json.dump(agg, f, ensure_ascii=False, separators=(",", ":"))
        size_mb = path.stat().st_size / (1024 * 1024)
        print(
            f"  {scheme_name:>11}: {agg['n_pairs']:>5} pairs  "
            f"{size_mb:6.2f} MB  -> {path.relative_to(ROOT).as_posix()}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
