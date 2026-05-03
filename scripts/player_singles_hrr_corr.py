#!/usr/bin/env python3
"""Singles vs Hits+Runs+RBI correlation lookup for SGP devigging.

Given a batter name, computes three correlation flavors across that
player's game logs:

  1. Continuous Pearson R          corr(singles, HRR)
  2. Binary phi                    corr(1{S>=L1}, 1{HRR>=L2})
  3. Tetrachoric R                 latent-normal correlation matching
                                   the same 2x2 marginals as phi

HRR = H + R + RBI. Games are filtered to PA > 0 (i.e. the batter
actually came to the plate).

Default season window is the most recent full season (2025) plus the
current 2026 season to date. Override with --seasons.

Usage:
  python3 scripts/player_singles_hrr_corr.py "Aaron Judge"
  python3 scripts/player_singles_hrr_corr.py "Judge" --l1 1 --l2 2
  python3 scripts/player_singles_hrr_corr.py "Soto" --seasons 2024 2025 2026
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent

# year -> (xlsx filename, sheet name). Mirrors build_pitcher_data.py SOURCES.
SOURCES = {
    2023: ("MLB-2023-Player-BoxScore-Dataset.xlsx", "2023-MLB-PLAYER"),
    2024: ("MLB-2024-Player-BoxScore-Dataset.xlsx", "2024-MLB-PLAYER"),
    2025: ("MLB-2025-Player-BoxScore-Dataset.xlsx", "2025-MLB-PLAYER"),
    2026: ("04-16-2026-mlb-season-player-feed.xlsx", "MLB-2026-PLAYER"),
}
DEFAULT_SEASONS = (2025, 2026)

# Positional column indices in the xlsx (header row 1, 0-indexed).
# The first row is a section banner; pandas' header=1 makes row 1 the header,
# but H/R/BB/SO repeat in the pitching block so we index by position to be safe.
COL_DATE = 2
COL_PLAYER = 4
COL_R = 12
COL_H = 13
COL_RBI = 14
COL_1B = 16
COL_PA = 24


def load_batter_games(seasons: list[int]) -> pd.DataFrame:
    frames = []
    for yr in seasons:
        if yr not in SOURCES:
            print(f"warn: no source xlsx for season {yr}, skipping", file=sys.stderr)
            continue
        fname, sheet = SOURCES[yr]
        path = ROOT / fname
        if not path.exists():
            print(f"warn: missing {path}, skipping", file=sys.stderr)
            continue
        # header=1 takes the second row as headers; we then re-key by position.
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
        sub["season"] = yr
        frames.append(sub)
    if not frames:
        sys.exit("error: no source xlsx files could be loaded")
    out = pd.concat(frames, ignore_index=True)
    # PA > 0 means the player actually batted (drops pitcher-only rows and DNPs).
    out = out[out["pa"].fillna(0) > 0].copy()
    out["hrr"] = out[["h", "r", "rbi"]].sum(axis=1)
    return out


def find_player(df: pd.DataFrame, query: str) -> tuple[str, list[str]]:
    """Return (resolved_name, suggestions). resolved_name='' on miss."""
    names = df["player"].dropna().unique().tolist()
    q = query.strip().lower()
    exact = [n for n in names if n.lower() == q]
    if exact:
        return exact[0], []
    contains = [n for n in names if q in n.lower()]
    if len(contains) == 1:
        return contains[0], []
    if contains:
        return "", sorted(contains)[:8]
    # Fall back to fuzzy match against full names AND last-token only,
    # since short typos like "Jude" -> "Judge" don't clear difflib's
    # default cutoff against the full "Aaron Judge" string.
    last_tokens = {n.split()[-1]: n for n in names if n.split()}
    close_full = difflib.get_close_matches(query, names, n=8, cutoff=0.5)
    close_last = difflib.get_close_matches(query, list(last_tokens.keys()), n=8, cutoff=0.6)
    merged = list(dict.fromkeys(close_full + [last_tokens[t] for t in close_last]))
    return "", merged[:8]


def tetrachoric(p11: float, p10: float, p01: float, p00: float) -> float | None:
    """Tetrachoric correlation via root-find on the bivariate normal CDF.

    Solves for rho in BVN_sf(tau_x, tau_y, rho) = p11, where tau_x and
    tau_y are the latent-normal cutpoints implied by the marginals.
    Returns None if any cell is empty (boundary case where rho is +/-1
    and the standard estimator is undefined).
    """
    if min(p11, p10, p01, p00) <= 0:
        return None
    px = p11 + p10  # P(X=1)
    py = p11 + p01  # P(Y=1)
    if not (0 < px < 1) or not (0 < py < 1):
        return None
    tau_x = stats.norm.ppf(1 - px)
    tau_y = stats.norm.ppf(1 - py)

    def bvn_upper(rho: float) -> float:
        # P(X > tau_x, Y > tau_y) under standard BVN with correlation rho.
        cov = [[1.0, rho], [rho, 1.0]]
        # mvn.cdf gives P(X<=a, Y<=b); convert via inclusion-exclusion.
        cdf_xy = stats.multivariate_normal.cdf([tau_x, tau_y], mean=[0, 0], cov=cov)
        return 1 - stats.norm.cdf(tau_x) - stats.norm.cdf(tau_y) + cdf_xy

    f = lambda rho: bvn_upper(rho) - p11
    lo, hi = -0.9999, 0.9999
    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        return float(np.sign(f_hi))  # saturated
    try:
        from scipy.optimize import brentq
        return float(brentq(f, lo, hi, xtol=1e-6))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("player", help="player name (partial / case-insensitive ok)")
    ap.add_argument("--l1", type=float, default=1.0, help="singles line (default 1)")
    ap.add_argument("--l2", type=float, default=2.0, help="HRR line (default 2)")
    ap.add_argument("--seasons", type=int, nargs="+", default=list(DEFAULT_SEASONS),
                    help=f"seasons to include (default {' '.join(map(str, DEFAULT_SEASONS))})")
    args = ap.parse_args()

    games = load_batter_games(args.seasons)
    name, suggestions = find_player(games, args.player)
    if not name:
        print(f"player not found: {args.player!r}")
        if suggestions:
            print("did you mean:")
            for s in suggestions:
                print(f"  - {s}")
        return 1

    g = games[games["player"] == name].sort_values("date").reset_index(drop=True)
    n = len(g)
    if n == 0:
        print(f"no games found for {name} in seasons {args.seasons}")
        return 1

    s = g["singles"].to_numpy(dtype=float)
    h = g["hrr"].to_numpy(dtype=float)

    # Continuous Pearson. Undefined if either series has zero variance.
    if s.std() == 0 or h.std() == 0:
        pearson = float("nan")
    else:
        pearson = float(np.corrcoef(s, h)[0, 1])

    bs = (s >= args.l1).astype(int)
    bh = (h >= args.l2).astype(int)
    p_s = float(bs.mean())
    p_h = float(bh.mean())
    p_both = float(((bs == 1) & (bh == 1)).mean())

    if bs.std() == 0 or bh.std() == 0:
        phi = float("nan")
    else:
        phi = float(np.corrcoef(bs, bh)[0, 1])

    p11 = p_both
    p10 = p_s - p_both
    p01 = p_h - p_both
    p00 = 1 - p11 - p10 - p01
    tet = tetrachoric(p11, p10, p01, p00)

    date_min = g["date"].min()
    date_max = g["date"].max()
    fmt = lambda x: x.strftime("%Y-%m-%d") if pd.notna(x) else "n/a"

    def fnum(x):
        return f"{x:+.3f}" if isinstance(x, float) and not np.isnan(x) else "n/a"

    print(f"Player: {name}")
    print(f"Games (n): {n}")
    print(f"Date range: {fmt(date_min)} – {fmt(date_max)}")
    print(f"Singles mean / HRR mean: {s.mean():.2f} / {h.mean():.2f}")
    print()
    print(f"Continuous R:        {fnum(pearson)}")
    print(f"Binary phi (L1, L2): {fnum(phi)}   [lines used: S>={args.l1:g}, HRR>={args.l2:g}]")
    print(f"Tetrachoric R:       {fnum(tet) if tet is not None else 'n/a (degenerate 2x2)'}")
    print()
    print("Marginals (for sanity check):")
    print(f"  P(singles >= {args.l1:g}) = {p_s:.3f}")
    print(f"  P(HRR >= {args.l2:g})     = {p_h:.3f}")
    print(f"  P(both)         = {p_both:.3f}   (empirical)")

    warnings = []
    if n < 50:
        warnings.append(f"n={n} < 50 — small sample, treat all R values as noisy")
    for label, p in (("singles", p_s), ("HRR", p_h)):
        if p < 0.05 or p > 0.95:
            warnings.append(f"{label} marginal = {p:.3f} (outside 5–95%) — phi unstable, prefer tetrachoric")
    if warnings:
        print()
        print("Warnings:")
        for w in warnings:
            print(f"  ! {w}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
