#!/usr/bin/env python3
"""Build per-batter Singles ↔ Hits+Runs+RBI correlation database.

Outputs public/data/singles_hrr_corr.json — one entry per batter with
weighted Pearson R (continuous), weighted phi (binary at default lines),
and weighted tetrachoric R (latent-normal). Used by the SGP devig
pipeline to convert Singles + HRR pairs into joint hit probabilities.

Pool-and-weight scheme (mirrors build_aggregates.py architecture):
  * Pool every PA>0 game across all available years.
  * Each game gets weight = its year's normalized scheme weight.
  * Compute ONE weighted statistic per player on the pooled sample.

Year weights:
  {2023: 0.10, 2024: 0.15, 2025: 0.30, 2026: 0.45}, pin_current=True

Rationale (vs the pitcher static {.15, .20, .30, .35}): batters
accumulate ~5x more games per season than pitcher starts, so 2026 mid-
season already carries meaningful sample. Lineup spot and team turn
over fast, and lineup spot drives RBI opportunities — the dominant
mechanism in the singles-vs-HRR correlation — so recent role matters
more than 3-year-old data. 2023 retained at 10% so career hitters with
stable approaches still contribute some history.

Uses normalize_scheme_weights() from build_aggregates.py so a player
missing 2023+2024 (rookie) gets that mass redistributed across their
available pre-2026 years rather than collapsing 2026's pin.

Filters:
  * PA > 0 (player actually batted)
  * n_raw >= MIN_GAMES total across all years (default 30)

Idempotent: rerunning overwrites public/data/singles_hrr_corr.json.

Usage:
  python3 build_singles_hrr_corr.py
  python3 build_singles_hrr_corr.py --l1 1 --l2 2 --min-games 30
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import brentq

# Reuse the existing pool-and-weight helpers so we stay byte-compatible
# with how pitcher and teammate aggregates handle missing-year redistribution.
from build_aggregates import (
    YEARS,
    CURRENT_YEAR,
    normalize_scheme_weights,
    weighted_pearson,
    weighted_pct,
    weighted_mean,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "public" / "data"

# Mirrors SOURCES in build_pitcher_data.py.
SOURCES = {
    2023: ("MLB-2023-Player-BoxScore-Dataset.xlsx", "2023-MLB-PLAYER"),
    2024: ("MLB-2024-Player-BoxScore-Dataset.xlsx", "2024-MLB-PLAYER"),
    2025: ("MLB-2025-Player-BoxScore-Dataset.xlsx", "2025-MLB-PLAYER"),
    2026: ("04-16-2026-mlb-season-player-feed.xlsx", "MLB-2026-PLAYER"),
}

# Positional column indices in the xlsx (header row 1, 0-indexed).
# H/R/BB/SO collide with the pitching block, so index by position not name.
COL_DATE = 2
COL_PLAYER = 4
COL_R = 12
COL_H = 13
COL_RBI = 14
COL_1B = 16
COL_PA = 24

SCHEME_WEIGHTS = {2023: 0.10, 2024: 0.15, 2025: 0.30, 2026: 0.45}
SCHEME_NAME = "batter_recent_weighted"
PIN_CURRENT = True
DEFAULT_L1 = 1.0   # Singles >= 1
DEFAULT_L2 = 2.0   # HRR >= 2
DEFAULT_MIN_GAMES = 30


def load_year(year: int) -> pd.DataFrame | None:
    fname, sheet = SOURCES[year]
    path = ROOT / fname
    if not path.exists():
        print(f"warn: missing {path.name}, skipping {year}", file=sys.stderr)
        return None
    df = pd.read_excel(path, sheet_name=sheet, header=1)
    sub = pd.DataFrame({
        "date": pd.to_datetime(df.iloc[:, COL_DATE], errors="coerce"),
        "player": df.iloc[:, COL_PLAYER].astype(str).str.strip(),
        "pa": pd.to_numeric(df.iloc[:, COL_PA], errors="coerce"),
        "singles": pd.to_numeric(df.iloc[:, COL_1B], errors="coerce"),
        "h": pd.to_numeric(df.iloc[:, COL_H], errors="coerce"),
        "r": pd.to_numeric(df.iloc[:, COL_R], errors="coerce"),
        "rbi": pd.to_numeric(df.iloc[:, COL_RBI], errors="coerce"),
    })
    sub = sub[sub["pa"].fillna(0) > 0].copy()
    sub["hrr"] = sub[["h", "r", "rbi"]].sum(axis=1)
    sub["year"] = year
    return sub


def tetrachoric_weighted(p11: float, p10: float, p01: float, p00: float) -> float | None:
    """Tetrachoric R via root-find on bivariate normal CDF.

    Inputs are the four cell probabilities (already weighted means). Returns
    None if any cell is empty or marginals are degenerate.
    """
    if min(p11, p10, p01, p00) <= 0:
        return None
    px = p11 + p10
    py = p11 + p01
    if not (0 < px < 1) or not (0 < py < 1):
        return None
    tau_x = stats.norm.ppf(1 - px)
    tau_y = stats.norm.ppf(1 - py)

    def bvn_upper(rho: float) -> float:
        cov = [[1.0, rho], [rho, 1.0]]
        cdf_xy = stats.multivariate_normal.cdf([tau_x, tau_y], mean=[0, 0], cov=cov)
        return 1 - stats.norm.cdf(tau_x) - stats.norm.cdf(tau_y) + cdf_xy

    f = lambda rho: bvn_upper(rho) - p11
    lo, hi = -0.9999, 0.9999
    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        return float(np.sign(f_hi))
    try:
        return round(float(brentq(f, lo, hi, xtol=1e-6)), 4)
    except Exception:
        return None


def build_player_entry(g: pd.DataFrame, l1: float, l2: float) -> dict:
    """Compute the per-player record for one player's pooled games. g must
    already have the per-game weight column 'w' set."""
    g = g.sort_values("date").reset_index(drop=True)
    s = g["singles"].to_numpy(dtype=float)
    h = g["hrr"].to_numpy(dtype=float)
    w = g["w"].to_numpy(dtype=float)

    pearson = weighted_pearson(s, h, w)

    bs = (s >= l1).astype(float)
    bh = (h >= l2).astype(float)
    p_s = weighted_pct(bs, w)         # percent (rounded 1dp)
    p_h = weighted_pct(bh, w)
    p_both = weighted_pct(bs * bh, w)
    phi = weighted_pearson(bs, bh, w)

    tet = None
    if p_s is not None and p_h is not None and p_both is not None:
        # weighted_pct returns percent; convert to probabilities for tetrachoric.
        p11 = p_both / 100.0
        p10 = p_s / 100.0 - p11
        p01 = p_h / 100.0 - p11
        p00 = 1 - p11 - p10 - p01
        tet = tetrachoric_weighted(p11, p10, p01, p00)

    starts_by_year = (
        g.groupby("year").size().to_dict()
    )
    starts_by_year = {str(int(y)): int(n) for y, n in sorted(starts_by_year.items())}

    avg_singles = weighted_mean(s, w)
    avg_hrr = weighted_mean(h, w)

    return {
        "n":           int(len(g)),
        "n_eff":       round(float(w.sum()), 3),
        "starts_by_year": starts_by_year,
        "date_min":    g["date"].min().strftime("%Y-%m-%d") if pd.notna(g["date"].min()) else None,
        "date_max":    g["date"].max().strftime("%Y-%m-%d") if pd.notna(g["date"].max()) else None,
        "avg_singles": round(float(avg_singles), 3) if avg_singles is not None else None,
        "avg_hrr":     round(float(avg_hrr), 3) if avg_hrr is not None else None,
        "pearson":     pearson,
        "phi":         phi,
        "tetrachoric": tet,
        "p_s":         round(p_s / 100.0, 4) if p_s is not None else None,
        "p_h":         round(p_h / 100.0, 4) if p_h is not None else None,
        "p_both":      round(p_both / 100.0, 4) if p_both is not None else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--l1", type=float, default=DEFAULT_L1, help=f"singles line (default {DEFAULT_L1})")
    ap.add_argument("--l2", type=float, default=DEFAULT_L2, help=f"HRR line (default {DEFAULT_L2})")
    ap.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES,
                    help=f"skip players with fewer than this many raw games (default {DEFAULT_MIN_GAMES})")
    args = ap.parse_args()

    frames = []
    for yr in YEARS:
        f = load_year(yr)
        if f is not None:
            frames.append(f)
    if not frames:
        sys.exit("error: no source xlsx files could be loaded")
    games = pd.concat(frames, ignore_index=True)

    n_players_total = games["player"].nunique()
    print(f"Loaded {len(games):,} batter-games across {n_players_total:,} players")

    skipped_small = 0
    players_out: dict[str, dict] = {}

    for name, g in games.groupby("player", sort=True):
        if len(g) < args.min_games:
            skipped_small += 1
            continue
        available = sorted(g["year"].unique().tolist())
        norm_w = normalize_scheme_weights(SCHEME_WEIGHTS, available, PIN_CURRENT)
        if not norm_w:
            continue
        g = g.assign(w=g["year"].map(lambda y: float(norm_w.get(int(y), 0.0))))
        if g["w"].sum() <= 0:
            continue
        entry = build_player_entry(g, args.l1, args.l2)
        entry["years"] = [int(y) for y in available]
        entry["norm_weights"] = {str(int(y)): round(float(norm_w.get(int(y), 0.0)), 4)
                                 for y in available}
        players_out[name] = entry

    out = {
        "scheme":       SCHEME_NAME,
        "weights":      {str(y): float(SCHEME_WEIGHTS.get(y, 0.0)) for y in YEARS},
        "pin_current":  PIN_CURRENT,
        "current_year": CURRENT_YEAR,
        "lines":        {"singles_gte": args.l1, "hrr_gte": args.l2},
        "min_games":    args.min_games,
        "n_players":    len(players_out),
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "players":      players_out,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "singles_hrr_corr.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    size_mb = out_path.stat().st_size / (1024 * 1024)

    print()
    print("Singles ↔ HRR correlation build summary")
    print("-" * 64)
    print(f"  scheme:       {SCHEME_NAME}")
    print(f"  weights:      {SCHEME_WEIGHTS}  (pin_current={PIN_CURRENT})")
    print(f"  lines:        S>={args.l1:g}, HRR>={args.l2:g}")
    print(f"  min_games:    {args.min_games}")
    print(f"  players in:   {len(players_out):,} (skipped {skipped_small:,} below min)")
    print(f"  output:       {out_path.relative_to(ROOT).as_posix()}  ({size_mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
