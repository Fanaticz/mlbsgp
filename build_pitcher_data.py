#!/usr/bin/env python3
"""Convert MLB player box score xlsx files into slim pitcher JSON files.

Reads the four xlsx files (2023, 2024, 2025, 2026), filters to STARTING
pitcher rows (STARTING\\nPITCHER == "YES" AND IP > 0), renames columns to
short keys, and writes compact JSON files to data/pitchers_YYYY.json plus
a data/manifest.json summary.

Idempotent: rerunning overwrites outputs cleanly.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "public" / "data"

# year -> (xlsx filename, sheet name)
SOURCES = {
    2023: ("MLB-2023-Player-BoxScore-Dataset.xlsx", "2023-MLB-PLAYER"),
    2024: ("MLB-2024-Player-BoxScore-Dataset.xlsx", "2024-MLB-PLAYER"),
    2025: ("MLB-2025-Player-BoxScore-Dataset.xlsx", "2025-MLB-PLAYER"),
    2026: ("04-16-2026-mlb-season-player-feed.xlsx", "MLB-2026-PLAYER"),
}

# Source column name -> short output key.
# Pitching columns that collide with batting ones are auto-suffixed .1 by pandas.
COLUMN_MAP = {
    "GAME-ID":   "gid",
    "DATE":      "d",
    "PLAYER-ID": "pid",
    "PLAYER":    "p",
    "TEAM":      "t",
    "OPPONENT":  "o",
    "VENUE":     "v",
    "HAND.1":    "h",
    "IP":        "ip",
    "H.1":       "h_allowed",
    "ER":        "er",
    "BB.1":      "bb",
    "SO.1":      "k",
    "W":         "w",
    "L":         "l",
    "HR.1":      "hra",
    "QS":        "qs",
    "BF":        "bf",
    "GB":        "gb",
    "FB":        "fb",
}


def _clean(value):
    """Convert pandas/numpy scalars to JSON-safe primitives, NaN -> None."""
    if value is None:
        return None
    if isinstance(value, float):
        return None if math.isnan(value) else value
    try:
        import numpy as np
        if isinstance(value, np.floating):
            f = float(value)
            return None if math.isnan(f) else f
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.bool_):
            return bool(value)
    except ImportError:
        pass
    if pd.isna(value):
        return None
    return value


def _format_date(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        # Already a string — try to normalize to YYYY-MM-DD.
        try:
            return pd.to_datetime(value).strftime("%Y-%m-%d")
        except Exception:
            return value
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return str(value)


def build_year(year: int, filename: str, sheet: str) -> tuple[list[dict], dict]:
    path = ROOT / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing source file for {year}: {path}")

    df = pd.read_excel(path, sheet_name=sheet, header=1)

    missing = [c for c in COLUMN_MAP if c not in df.columns]
    if missing:
        raise KeyError(f"{year}: expected columns missing: {missing}")

    # Filter to STARTING pitcher rows only. The xlsx has one row per
    # (game, player) for every pitcher who recorded an out, so IP > 0 alone
    # would pull relief appearances (openers, long relief, closers). The
    # starter aggregates and correlations assume full-game starts; mixing
    # relievers in would compress SO/ER/OUTS distributions and break the
    # existing correlation baselines. The "STARTING\nPITCHER" column is
    # "YES" for the starting pitcher of each side, blank otherwise.
    sp_col = "STARTING\nPITCHER"
    if sp_col not in df.columns:
        raise KeyError(f"{year}: missing required column {sp_col!r}")
    sp_mask = df[sp_col].notna() & (df[sp_col].astype(str).str.strip().str.upper() == "YES")
    mask = sp_mask & df["IP"].notna() & (df["IP"] > 0)
    # Regression guard: starter rows should be roughly 2 per game, ~25-30%
    # of IP>0 rows (the rest are relievers). If a future edit drops this
    # filter, the starter share jumps to 100% and this assertion trips.
    ip_rows = int((df["IP"].notna() & (df["IP"] > 0)).sum())
    starter_rows = int(mask.sum())
    assert starter_rows < ip_rows * 0.35, (
        f"{year}: starter filter looks broken — {starter_rows} starter rows "
        f"out of {ip_rows} IP>0 rows ({starter_rows / max(ip_rows, 1):.0%}); "
        f"expected <35% (starters are ~2 per game, relievers fill the rest)."
    )
    pitchers = df.loc[mask, list(COLUMN_MAP.keys())].copy()
    pitchers = pitchers.rename(columns=COLUMN_MAP)

    # Normalize dates up front so the manifest matches the output.
    pitchers["d"] = pitchers["d"].map(_format_date)

    records: list[dict] = []
    for row in pitchers.itertuples(index=False):
        record = {}
        for key, val in zip(pitchers.columns, row):
            record[key] = _clean(val)
        records.append(record)

    dates = sorted(r["d"] for r in records if r.get("d"))
    date_range = {
        "first": dates[0] if dates else None,
        "last":  dates[-1] if dates else None,
    }
    return records, date_range


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    summaries = []
    row_counts = {}
    date_ranges = {}

    for year, (filename, sheet) in SOURCES.items():
        records, drange = build_year(year, filename, sheet)
        out_path = DATA_DIR / f"pitchers_{year}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, separators=(",", ":"))
        size = out_path.stat().st_size
        row_counts[str(year)] = len(records)
        date_ranges[str(year)] = drange
        summaries.append((year, out_path, len(records), size, drange))

    manifest = {
        "years": list(SOURCES.keys()),
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "row_counts": row_counts,
        "date_ranges": date_ranges,
    }
    manifest_path = DATA_DIR / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("Pitcher dataset build summary")
    print("-" * 64)
    for year, path, n_rows, size, drange in summaries:
        size_mb = size / (1024 * 1024)
        print(
            f"  {year}: {n_rows:>5} rows  "
            f"{size_mb:6.2f} MB  "
            f"{drange['first']} .. {drange['last']}  "
            f"-> {path.relative_to(ROOT).as_posix()}"
        )
    print("-" * 64)
    print(f"  manifest -> {manifest_path.relative_to(ROOT).as_posix()}")
    print(f"  last_updated: {manifest['last_updated']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
