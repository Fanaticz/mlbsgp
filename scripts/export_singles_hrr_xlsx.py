#!/usr/bin/env python3
"""Export public/data/singles_hrr_corr.json to an xlsx for human review.

One row per player, sorted by name. The first sheet ("players") has the
per-player records; the second sheet ("meta") has the build header
(scheme, weights, lines, generated_at).

Usage:
  python3 scripts/export_singles_hrr_xlsx.py
  python3 scripts/export_singles_hrr_xlsx.py --out custom/path.xlsx
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IN = ROOT / "public" / "data" / "singles_hrr_corr.json"
DEFAULT_OUT = ROOT / "public" / "data" / "singles_hrr_corr.xlsx"

YEARS = [2023, 2024, 2025, 2026]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, default=DEFAULT_IN)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"error: {args.input} not found — run build_singles_hrr_corr.py first")

    with args.input.open("r", encoding="utf-8") as f:
        db = json.load(f)

    rows = []
    for name in sorted(db["players"].keys()):
        e = db["players"][name]
        sby = e.get("starts_by_year", {})
        nw = e.get("norm_weights", {})
        rows.append({
            "player":      name,
            "n":           e["n"],
            "n_eff":       e["n_eff"],
            "date_min":    e["date_min"],
            "date_max":    e["date_max"],
            **{f"starts_{y}": int(sby.get(str(y), 0)) for y in YEARS},
            "avg_singles": e["avg_singles"],
            "avg_hrr":     e["avg_hrr"],
            "pearson":     e["pearson"],
            "phi":         e["phi"],
            "tetrachoric": e["tetrachoric"],
            "p_s":         e["p_s"],
            "p_h":         e["p_h"],
            "p_both":      e["p_both"],
            **{f"w_{y}": nw.get(str(y)) for y in YEARS},
        })
    df = pd.DataFrame(rows)

    meta = pd.DataFrame([
        ("scheme",       db.get("scheme")),
        ("pin_current",  db.get("pin_current")),
        ("current_year", db.get("current_year")),
        ("singles_gte",  db.get("lines", {}).get("singles_gte")),
        ("hrr_gte",      db.get("lines", {}).get("hrr_gte")),
        ("min_games",    db.get("min_games")),
        ("n_players",    db.get("n_players")),
        ("generated_at", db.get("generated_at")),
        *[(f"weight_{y}", db.get("weights", {}).get(str(y))) for y in YEARS],
    ], columns=["key", "value"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="players", index=False)
        meta.to_excel(writer, sheet_name="meta", index=False)

    size_kb = args.out.stat().st_size / 1024
    print(f"wrote {len(df):,} players -> {args.out.relative_to(ROOT).as_posix()}  ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
