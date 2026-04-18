#!/usr/bin/env python3
"""Build correlation aggregates from raw pitcher game logs.

Reads public/data/pitchers_YYYY.json (produced by build_pitcher_data.py) and
writes two kinds of output into public/data/:

  * aggregates_YYYY.json — per-year files, one per season. Still used by the
    frontend for global_2 / global_3 / global_raw_corr blending and for the
    per-year display on the pitcher profile (n_starts per year, etc).
  * aggregates_pooled_<scheme>.json — one file per weight scheme, carrying
    per-pitcher combos_2 / combos_3 / raw_corr / avg stats computed via
    pool-and-weight: pool every pitcher start across years, weight each start
    by its year's scheme weight (renormalized with a 2026 pin so missing
    years redistribute only across earlier years), compute ONE weighted
    Pearson per combo. Replaces the old per-year r blend, which
    under-attenuated noisy low-sample seasons.

Notes worth keeping in mind:
  * IP is baseball notation: X.Y means X innings + Y outs (Y in {0,1,2}).
    outs = floor(ip)*3 + round((ip - floor(ip))*10).
  * Pearson r is translation-invariant, so per-pitcher "r_margin" for any leg
    pair equals raw Pearson of the two raw stats for that pitcher's starts.
    Same stat pair (SO x SO) would be trivially 1.0 — those are filtered out
    of per-pitcher combos_2 to match the existing UI, but kept in global_2.
  * Global "r_avg" / triple "_a" variants: each pitcher contributes one point
    (their season-mean hit rate for the leg) to a cross-pitcher Pearson.
  * Correlations require variance on both sides; we emit null otherwise.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "public" / "data"
COMBO_SPEC_PATH = ROOT / "combo_spec.json"

YEARS = [2023, 2024, 2025, 2026]
CURRENT_YEAR = 2026

# Pool-and-weight schemes. Keys mirror the frontend dynamic buckets so the
# UI can pick aggregates_pooled_<scheme>.json based on each pitcher's 2026
# sample size. "static" is the manual fallback when the dynamic toggle is
# off; "unweighted" is a diagnostic (every start weighted equally).
WEIGHT_SCHEMES: dict[str, dict[int, float]] = {
    "dyn_1_3":    {2023: 0.20, 2024: 0.25, 2025: 0.40, 2026: 0.15},
    "dyn_4_8":    {2023: 0.15, 2024: 0.20, 2025: 0.35, 2026: 0.30},
    "dyn_9_15":   {2023: 0.10, 2024: 0.15, 2025: 0.30, 2026: 0.45},
    "dyn_16plus": {2023: 0.08, 2024: 0.12, 2025: 0.25, 2026: 0.55},
    "static":     {2023: 0.15, 2024: 0.20, 2025: 0.30, 2026: 0.35},
    "unweighted": {2023: 1.00, 2024: 1.00, 2025: 1.00, 2026: 1.00},
}

STAT_COL = {
    "Strikeouts":    "k",
    "Earned Runs":   "er",
    "Walks":         "bb",
    "Hits Allowed":  "h_allowed",
    "Outs Recorded": "outs",
}
STAT_SHORT = {
    "Strikeouts":    "SO",
    "Earned Runs":   "ER",
    "Walks":         "BB",
    "Hits Allowed":  "H",
    "Outs Recorded": "OUTS",
}
# Order used for raw_corr keys, matches today's baked D.
RAW_ORDER = ["SO", "ER", "BB", "H", "OUTS"]
RAW_COL = {"SO": "k", "ER": "er", "BB": "bb", "H": "h_allowed", "OUTS": "outs"}
RAW_PAIRS = [(RAW_ORDER[i], RAW_ORDER[j])
             for i in range(len(RAW_ORDER))
             for j in range(i + 1, len(RAW_ORDER))]


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #

def ip_to_outs(ip: float | None) -> int | None:
    """Convert baseball-notation IP to whole outs. 5.2 -> 17, 0.2 -> 2."""
    if ip is None:
        return None
    try:
        f = float(ip)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    whole = int(math.floor(f))
    frac = round((f - whole) * 10)
    if frac < 0 or frac > 2:
        # Defensive: unexpected decimal, fall back to naive conversion.
        return int(round(f * 3))
    return whole * 3 + frac


def parse_leg(leg: str) -> tuple[str, float, str, str]:
    """'Over 4.5 Strikeouts' -> ('Over', 4.5, 'Strikeouts', 'k')."""
    direction, rest = leg.split(" ", 1)
    thresh_str, stat = rest.split(" ", 1)
    return direction, float(thresh_str), stat, STAT_COL[stat]


def hit_vector(rows_col_values: np.ndarray, direction: str, thresh: float) -> np.ndarray:
    """Return 0/1 numpy array of leg hits given raw stat values."""
    if direction == "Over":
        return (rows_col_values > thresh).astype(np.float64)
    return (rows_col_values < thresh).astype(np.float64)


def pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    """Pearson r; None if degenerate (n<2 or zero variance on either side)."""
    if x.size < 2 or y.size < 2 or x.size != y.size:
        return None
    xv = float(np.var(x))
    yv = float(np.var(y))
    if xv == 0.0 or yv == 0.0:
        return None
    xm = x - x.mean()
    ym = y - y.mean()
    num = float((xm * ym).sum())
    den = math.sqrt(float((xm * xm).sum()) * float((ym * ym).sum()))
    if den == 0.0:
        return None
    r = num / den
    # Clamp to guard against tiny FP drift outside [-1, 1].
    if r > 1.0:
        r = 1.0
    elif r < -1.0:
        r = -1.0
    return round(r, 4)


def weighted_pearson(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> float | None:
    """Weighted Pearson correlation. x,y,w are equal-length 1D arrays.

    Drops entries where either x or y is not finite (matching the unweighted
    pearson()'s finite-mask handling done upstream). Returns None for
    degenerate samples (total weight 0, <2 effective rows, zero variance on
    either side). For binary 0/1 inputs this is the weighted phi coefficient;
    for continuous inputs it's the weighted generalization of Pearson's r.
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
    w_sum = float(w.sum())
    if w_sum <= 0.0:
        return None
    mx = float((w * x).sum() / w_sum)
    my = float((w * y).sum() / w_sum)
    dx = x - mx
    dy = y - my
    vx = float((w * dx * dx).sum() / w_sum)
    vy = float((w * dy * dy).sum() / w_sum)
    if vx <= 0.0 or vy <= 0.0:
        return None
    cov = float((w * dx * dy).sum() / w_sum)
    den = math.sqrt(vx * vy)
    if den == 0.0:
        return None
    r = cov / den
    if r > 1.0:
        r = 1.0
    elif r < -1.0:
        r = -1.0
    return round(r, 4)


def pct(numerator_mask: np.ndarray) -> float:
    """Hit rate as percent, rounded to 1 decimal (matches existing baked D)."""
    return round(float(numerator_mask.mean()) * 100, 1)


def weighted_pct(values: np.ndarray, w: np.ndarray) -> float | None:
    """Weighted mean (of 0/1 or arbitrary) expressed as a percent, rounded to
    1 decimal. Returns None if no weight mass.
    """
    w = np.asarray(w, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    m = np.isfinite(values) & np.isfinite(w) & (w > 0)
    if not m.any():
        return None
    w = w[m]
    values = values[m]
    ws = float(w.sum())
    if ws <= 0.0:
        return None
    return round(float((w * values).sum() / ws) * 100, 1)


def weighted_mean(values: np.ndarray, w: np.ndarray) -> float | None:
    """Weighted mean for raw continuous values (e.g. K, ER, OUTS). Returns
    None if no finite-and-positive-weight entries remain.
    """
    w = np.asarray(w, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    m = np.isfinite(values) & np.isfinite(w) & (w > 0)
    if not m.any():
        return None
    w = w[m]
    values = values[m]
    ws = float(w.sum())
    if ws <= 0.0:
        return None
    return float((w * values).sum() / ws)


def clean_round(val, digits=4):
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    return round(float(val), digits)


# --------------------------------------------------------------------------- #
# per-year aggregation                                                        #
# --------------------------------------------------------------------------- #

def load_year(year: int) -> list[dict]:
    path = DATA_DIR / f"pitchers_{year}.json"
    with path.open("r", encoding="utf-8") as f:
        rows = json.load(f)
    for r in rows:
        r["outs"] = ip_to_outs(r.get("ip"))
    return rows


def group_by_pitcher(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        name = r.get("p")
        if name is None:
            continue
        out.setdefault(name, []).append(r)
    return out


def stat_array(rows: list[dict], key: str) -> np.ndarray:
    """Pull a numeric column from rows as float array, NaN for nulls."""
    arr = np.empty(len(rows), dtype=np.float64)
    for i, r in enumerate(rows):
        v = r.get(key)
        arr[i] = float(v) if v is not None else float("nan")
    return arr


def compute_raw_stats(rows: list[dict]) -> dict[str, np.ndarray]:
    return {s: stat_array(rows, RAW_COL[s]) for s in RAW_ORDER}


def mask_finite(arrs: list[np.ndarray]) -> np.ndarray:
    m = np.ones(arrs[0].size, dtype=bool)
    for a in arrs:
        m &= np.isfinite(a)
    return m


def compute_raw_corr(raw: dict[str, np.ndarray]) -> dict[str, float | None]:
    """Pairwise Pearson on raw stats; nulls out pairs with missing values."""
    out = {}
    for a, b in RAW_PAIRS:
        m = mask_finite([raw[a], raw[b]])
        out[f"{a}_{b}"] = pearson(raw[a][m], raw[b][m])
    return out


def hit_dict(rows: list[dict], legs: list[str]) -> dict[str, np.ndarray]:
    """Return {leg: binary 0/1 hit array} aligned to rows."""
    raw_cache: dict[str, np.ndarray] = {}
    out = {}
    for leg in legs:
        direction, thresh, stat, col = parse_leg(leg)
        if col not in raw_cache:
            raw_cache[col] = stat_array(rows, col)
        vals = raw_cache[col]
        # For rows where the stat is missing (NaN), treat as miss (0) — these
        # should be rare; raw data is typically complete for pitcher starts.
        hit = np.where(np.isfinite(vals),
                       hit_vector(np.where(np.isfinite(vals), vals, 0.0), direction, thresh),
                       0.0)
        out[leg] = hit
    return out


def build_pitcher_combos_2(pairs, hits, raw_corr) -> list[dict]:
    """Diff-cat pairs only (per existing UI). Emits r (binary), r_margin (=raw
    stat corr, translation-invariant), hit rates.

    Skips rows where both r and r_margin are null — no useful signal for the
    blend or the UI.
    """
    out = []
    for leg1, leg2 in pairs:
        _, _, stat1, _ = parse_leg(leg1)
        _, _, stat2, _ = parse_leg(leg2)
        s1, s2 = STAT_SHORT[stat1], STAT_SHORT[stat2]
        if s1 == s2:
            continue
        h1, h2 = hits[leg1], hits[leg2]
        r = pearson(h1, h2)
        key = f"{s1}_{s2}" if f"{s1}_{s2}" in raw_corr else f"{s2}_{s1}"
        r_margin = raw_corr.get(key)
        if r is None and r_margin is None:
            continue
        hit1 = pct(h1)
        hit2 = pct(h2)
        both = pct(h1 * h2)
        given1 = round(both / hit1 * 100, 1) if hit1 > 0 else None
        out.append({
            "leg1": leg1, "leg2": leg2,
            "r": r, "r_margin": r_margin,
            "hit1": hit1, "hit2": hit2,
            "both": both,
            "given1": given1,
        })
    return out


def build_pitcher_combos_3(triples, hits) -> list[dict]:
    """Skips triples where all three pairwise r's are null."""
    out = []
    for leg1, leg2, leg3 in triples:
        h1, h2, h3 = hits[leg1], hits[leg2], hits[leg3]
        r12 = pearson(h1, h2)
        r13 = pearson(h1, h3)
        r23 = pearson(h2, h3)
        if r12 is None and r13 is None and r23 is None:
            continue
        valid = [v for v in (r12, r13, r23) if v is not None]
        avg_r = round(sum(valid) / len(valid), 4) if valid else None
        all3 = pct(h1 * h2 * h3)
        out.append({
            "leg1": leg1, "leg2": leg2, "leg3": leg3,
            "r12": r12, "r13": r13, "r23": r23,
            "avg_r": avg_r,
            "hit1": pct(h1), "hit2": pct(h2), "hit3": pct(h3),
            "all3": all3,
        })
    return out


def build_global_2(pairs, all_hits, per_pitcher_mean_hits) -> list[dict]:
    out = []
    for leg1, leg2 in pairs:
        h1 = all_hits[leg1]
        h2 = all_hits[leg2]
        hit1 = pct(h1); hit2 = pct(h2)
        both = pct(h1 * h2)
        neither = round(100 - hit1 - hit2 + both, 1)
        given1 = round(both / hit1 * 100, 1) if hit1 > 0 else None
        given2 = round(both / hit2 * 100, 1) if hit2 > 0 else None
        r = pearson(h1, h2)
        m1 = per_pitcher_mean_hits[leg1]
        m2 = per_pitcher_mean_hits[leg2]
        r_avg = pearson(m1, m2)
        out.append({
            "leg1": leg1, "leg2": leg2,
            "r": r, "r_avg": r_avg,
            "hit1": hit1, "hit2": hit2,
            "both": both, "neither": neither,
            "given1": given1, "given2": given2,
        })
    return out


def build_global_3(triples, all_hits, per_pitcher_mean_hits) -> list[dict]:
    out = []
    for leg1, leg2, leg3 in triples:
        h1 = all_hits[leg1]; h2 = all_hits[leg2]; h3 = all_hits[leg3]
        r12 = pearson(h1, h2)
        r13 = pearson(h1, h3)
        r23 = pearson(h2, h3)
        valid = [v for v in (r12, r13, r23) if v is not None]
        avg_r = round(sum(valid) / len(valid), 4) if valid else None
        m1 = per_pitcher_mean_hits[leg1]
        m2 = per_pitcher_mean_hits[leg2]
        m3 = per_pitcher_mean_hits[leg3]
        r12a = pearson(m1, m2)
        r13a = pearson(m1, m3)
        r23a = pearson(m2, m3)
        valida = [v for v in (r12a, r13a, r23a) if v is not None]
        avg_ra = round(sum(valida) / len(valida), 4) if valida else None
        hit1 = pct(h1); hit2 = pct(h2); hit3 = pct(h3)
        all3 = pct(h1 * h2 * h3)
        none_mask = (1 - h1) * (1 - h2) * (1 - h3)
        neither = pct(none_mask)
        out.append({
            "leg1": leg1, "leg2": leg2, "leg3": leg3,
            "r12": r12, "r13": r13, "r23": r23, "avg_r": avg_r,
            "r12a": r12a, "r13a": r13a, "r23a": r23a, "avg_ra": avg_ra,
            "hit1": hit1, "hit2": hit2, "hit3": hit3,
            "all3": all3, "neither": neither,
        })
    return out


# --------------------------------------------------------------------------- #
# pool-and-weight aggregation                                                 #
# --------------------------------------------------------------------------- #

def normalize_scheme_weights(
    scheme_weights: dict[int, float],
    available_years: list[int],
    pin_current: bool,
) -> dict[int, float]:
    """Renormalize scheme weights across a pitcher's available years.

    With pin_current=True and the current year present, the current year's
    weight is pinned at its scheme value; freed mass from missing pre-current
    years is redistributed only across the OTHER available pre-current years
    (proportional to their scheme values). If the current year is missing,
    or pin_current is False, do plain proportional renormalization.

    Mirrors the frontend's normalizeWeights() cap-aware rule so pool-and-weight
    and the old per-year blend agree on weight distributions.
    """
    avail = [y for y in YEARS if y in available_years]
    if not avail:
        return {}
    if pin_current and CURRENT_YEAR in avail:
        pin = float(scheme_weights.get(CURRENT_YEAR, 0.0))
        others = [y for y in avail if y != CURRENT_YEAR]
        if not others:
            return {CURRENT_YEAR: 1.0}
        other_total = sum(float(scheme_weights.get(y, 0.0)) for y in others)
        remaining = 1.0 - pin
        out: dict[int, float] = {CURRENT_YEAR: pin}
        if other_total <= 0.0:
            for y in others:
                out[y] = remaining / len(others)
        else:
            scale = remaining / other_total
            for y in others:
                out[y] = float(scheme_weights.get(y, 0.0)) * scale
        return out
    total = sum(float(scheme_weights.get(y, 0.0)) for y in avail)
    if total <= 0.0:
        return {y: 1.0 / len(avail) for y in avail}
    return {y: float(scheme_weights.get(y, 0.0)) / total for y in avail}


def _pitcher_pooled_inputs(
    prows_by_year: dict[int, list[dict]],
    legs_sorted: list[str],
    scheme_weights: dict[int, float],
    pin_current: bool,
) -> tuple[list[dict], np.ndarray, dict[str, np.ndarray], dict[str, np.ndarray], dict[int, float]]:
    """Pool one pitcher's starts across years. Returns:
      * all_rows:    flattened rows in year order (asc)
      * per_start_w: np.ndarray of per-start weights
      * raw:         {SO/ER/BB/H/OUTS: per-row continuous array}
      * hits:        {leg: per-row 0/1 array}
      * norm_w:      {year: normalized weight} actually used
    Each start in year Y gets weight norm_w[Y] — literally the year's
    (cap-aware-renormalized) scheme weight. A pitcher with 29 starts in 2023
    and 3 in 2026 contributes 29 × w_2023 units of mass from 2023 vs 3 ×
    w_2026 from 2026, so high-sample years naturally carry more influence
    per pitcher while the scheme's across-year weights shape the relative
    emphasis. For the "unweighted" scheme this reduces to equal weight on
    every start, matching the unweighted career Pearson.
    """
    available = [y for y in YEARS if y in prows_by_year and prows_by_year[y]]
    norm_w = normalize_scheme_weights(scheme_weights, available, pin_current)
    all_rows: list[dict] = []
    w_list: list[float] = []
    for y in sorted(available):
        rows = prows_by_year[y]
        per = float(norm_w.get(y, 0.0))
        for r in rows:
            all_rows.append(r)
            w_list.append(per)
    per_start_w = np.asarray(w_list, dtype=np.float64)
    raw = compute_raw_stats(all_rows)
    hits = hit_dict(all_rows, legs_sorted)
    return all_rows, per_start_w, raw, hits, norm_w


def _pooled_raw_corr(raw: dict[str, np.ndarray], w: np.ndarray) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for a, b in RAW_PAIRS:
        xa = raw[a]; xb = raw[b]
        m = np.isfinite(xa) & np.isfinite(xb) & np.isfinite(w) & (w > 0)
        if m.sum() < 2:
            out[f"{a}_{b}"] = None
            continue
        out[f"{a}_{b}"] = weighted_pearson(xa[m], xb[m], w[m])
    return out


def _pooled_combos_2(pairs, hits, raw_corr, w) -> list[dict]:
    out = []
    for leg1, leg2 in pairs:
        _, _, stat1, _ = parse_leg(leg1)
        _, _, stat2, _ = parse_leg(leg2)
        s1, s2 = STAT_SHORT[stat1], STAT_SHORT[stat2]
        if s1 == s2:
            continue
        h1 = hits[leg1]; h2 = hits[leg2]
        r = weighted_pearson(h1, h2, w)
        key = f"{s1}_{s2}" if f"{s1}_{s2}" in raw_corr else f"{s2}_{s1}"
        r_margin = raw_corr.get(key)
        if r is None and r_margin is None:
            continue
        hit1 = weighted_pct(h1, w)
        hit2 = weighted_pct(h2, w)
        both = weighted_pct(h1 * h2, w)
        given1 = round(both / hit1 * 100, 1) if (hit1 and hit1 > 0 and both is not None) else None
        out.append({
            "leg1": leg1, "leg2": leg2,
            "r": r, "r_margin": r_margin,
            "hit1": hit1, "hit2": hit2,
            "both": both,
            "given1": given1,
        })
    return out


def _pooled_combos_3(triples, hits, w) -> list[dict]:
    out = []
    for leg1, leg2, leg3 in triples:
        h1 = hits[leg1]; h2 = hits[leg2]; h3 = hits[leg3]
        r12 = weighted_pearson(h1, h2, w)
        r13 = weighted_pearson(h1, h3, w)
        r23 = weighted_pearson(h2, h3, w)
        if r12 is None and r13 is None and r23 is None:
            continue
        valid = [v for v in (r12, r13, r23) if v is not None]
        avg_r = round(sum(valid) / len(valid), 4) if valid else None
        out.append({
            "leg1": leg1, "leg2": leg2, "leg3": leg3,
            "r12": r12, "r13": r13, "r23": r23,
            "avg_r": avg_r,
            "hit1": weighted_pct(h1, w),
            "hit2": weighted_pct(h2, w),
            "hit3": weighted_pct(h3, w),
            "all3": weighted_pct(h1 * h2 * h3, w),
        })
    return out


def aggregate_pooled(
    scheme_name: str,
    scheme_weights: dict[int, float],
    by_pitcher_by_year: dict[int, dict[str, list[dict]]],
    pairs,
    triples,
    legs_sorted: list[str],
) -> dict:
    """Build one pooled file: per-pitcher combos_2 / combos_3 / raw_corr /
    avg stats computed by weighted Pearson on pooled starts with this
    scheme's weights. Pitchers with zero career starts are skipped.

    pin_current applies to every scheme EXCEPT "unweighted" (where pinning
    2026 at 1.0 would collapse all other years to zero weight).
    """
    pin_current = scheme_name != "unweighted"

    pitcher_names = set()
    for y in YEARS:
        for name in (by_pitcher_by_year.get(y) or {}):
            pitcher_names.add(name)

    pitchers_out: dict[str, dict] = {}
    for name in sorted(pitcher_names):
        prows_by_year: dict[int, list[dict]] = {}
        for y in YEARS:
            rows = (by_pitcher_by_year.get(y) or {}).get(name) or []
            if rows:
                prows_by_year[y] = rows
        if not prows_by_year:
            continue

        all_rows, w, raw, hits, norm_w = _pitcher_pooled_inputs(
            prows_by_year, legs_sorted, scheme_weights, pin_current
        )
        if not all_rows:
            continue

        starts_by_year = {str(y): len(prows_by_year[y]) for y in sorted(prows_by_year)}
        n_starts_raw = sum(len(v) for v in prows_by_year.values())
        # n_starts_eff mirrors the frontend's existing sum(w_year * n_year).
        n_starts_eff = float(sum(norm_w.get(y, 0.0) * len(prows_by_year[y])
                                 for y in prows_by_year))

        avg_by_stat: dict[str, float | None] = {}
        for s in RAW_ORDER:
            mu = weighted_mean(raw[s], w)
            avg_by_stat[s] = round(float(mu), 2) if mu is not None else None

        raw_corr = _pooled_raw_corr(raw, w)
        combos_2 = _pooled_combos_2(pairs, hits, raw_corr, w)
        combos_3 = _pooled_combos_3(triples, hits, w)

        pitchers_out[name] = {
            "n_starts":      n_starts_raw,
            "n_starts_raw":  n_starts_raw,
            "n_starts_eff":  round(n_starts_eff, 3),
            "starts_2026":   len(prows_by_year.get(CURRENT_YEAR, [])),
            "starts_by_year": starts_by_year,
            "years":         sorted(prows_by_year.keys()),
            "norm_weights":  {str(y): round(float(norm_w.get(y, 0.0)), 4)
                              for y in sorted(prows_by_year)},
            "avg_SO":        avg_by_stat["SO"],
            "avg_ER":        avg_by_stat["ER"],
            "avg_BB":        avg_by_stat["BB"],
            "avg_H":         avg_by_stat["H"],
            "avg_OUTS":      avg_by_stat["OUTS"],
            "raw_corr":      raw_corr,
            "combos_2":      combos_2,
            "combos_3":      combos_3,
        }

    return {
        "scheme":       scheme_name,
        "weights":      {str(y): float(scheme_weights.get(y, 0.0)) for y in YEARS},
        "pin_current":  pin_current,
        "current_year": CURRENT_YEAR,
        "n_pitchers":   len(pitchers_out),
        "pitchers":     pitchers_out,
    }


def aggregate_year_from_rows(
    year: int,
    rows: list[dict],
    by_pitcher: dict[str, list[dict]],
    pairs,
    triples,
    legs_set,
) -> dict:
    # Global: hit vectors pooled across all starts, plus per-pitcher mean-hit
    # rate (one point per pitcher) for the _a / r_avg variants.
    all_hits = hit_dict(rows, sorted(legs_set))
    mean_hits_list = {leg: [] for leg in legs_set}
    pitcher_names_sorted = sorted(by_pitcher.keys())

    # Global raw_corr: pool continuous stats across all rows.
    global_raw = compute_raw_stats(rows)
    global_raw_corr = compute_raw_corr(global_raw)

    pitchers_out: dict[str, dict] = {}

    for name in pitcher_names_sorted:
        prows = by_pitcher[name]
        n_starts = len(prows)
        raw = compute_raw_stats(prows)

        avg_by_stat = {}
        for s in RAW_ORDER:
            vals = raw[s][np.isfinite(raw[s])]
            avg_by_stat[s] = round(float(vals.mean()), 2) if vals.size else None

        raw_corr = compute_raw_corr(raw)
        p_hits = hit_dict(prows, sorted(legs_set))

        # Contribute this pitcher's season mean-hit-rate to the global _avg / _a pools.
        for leg in legs_set:
            mean_hits_list[leg].append(float(p_hits[leg].mean()))

        combos_2 = build_pitcher_combos_2(pairs, p_hits, raw_corr)
        combos_3 = build_pitcher_combos_3(triples, p_hits)

        pitchers_out[name] = {
            "n_starts": n_starts,
            "avg_SO":   avg_by_stat["SO"],
            "avg_ER":   avg_by_stat["ER"],
            "avg_BB":   avg_by_stat["BB"],
            "avg_H":    avg_by_stat["H"],
            "avg_OUTS": avg_by_stat["OUTS"],
            "raw_corr": raw_corr,
            "combos_2": combos_2,
            "combos_3": combos_3,
        }

    per_pitcher_mean_hits = {leg: np.asarray(v, dtype=np.float64)
                             for leg, v in mean_hits_list.items()}

    global_2 = build_global_2(pairs, all_hits, per_pitcher_mean_hits)
    global_3 = build_global_3(triples, all_hits, per_pitcher_mean_hits)

    return {
        "year":        year,
        "n_starts":    len(rows),
        "n_pitchers":  len(by_pitcher),
        "global_2":    global_2,
        "global_3":    global_3,
        "global_raw_corr": global_raw_corr,
        "pitchers":    pitchers_out,
    }


def main() -> int:
    with COMBO_SPEC_PATH.open("r", encoding="utf-8") as f:
        spec = json.load(f)
    pairs = [tuple(p) for p in spec["pairs_2"]]
    triples = [tuple(t) for t in spec["triples_3"]]

    legs_set = set()
    for a, b in pairs:
        legs_set.add(a); legs_set.add(b)
    for a, b, c in triples:
        legs_set.add(a); legs_set.add(b); legs_set.add(c)

    summary = []
    # Load each year once so we can reuse the pitcher-indexed rows for the
    # pool-and-weight pass below.
    rows_by_year: dict[int, list[dict]] = {}
    by_pitcher_by_year: dict[int, dict[str, list[dict]]] = {}
    for year in YEARS:
        rows_by_year[year] = load_year(year)
        by_pitcher_by_year[year] = group_by_pitcher(rows_by_year[year])

    legs_sorted = sorted(legs_set)

    for year in YEARS:
        agg = aggregate_year_from_rows(
            year, rows_by_year[year], by_pitcher_by_year[year],
            pairs, triples, legs_set,
        )
        out = DATA_DIR / f"aggregates_{year}.json"
        with out.open("w", encoding="utf-8") as f:
            json.dump(agg, f, ensure_ascii=False, separators=(",", ":"))
        size = out.stat().st_size / (1024 * 1024)
        summary.append((year, agg["n_starts"], agg["n_pitchers"], size, out))

    print("Aggregate build summary (per-year)")
    print("-" * 64)
    for year, n_starts, n_pitchers, size, path in summary:
        print(f"  {year}: {n_starts:>5} starts  {n_pitchers:>3} pitchers  "
              f"{size:5.2f} MB  -> {path.relative_to(ROOT).as_posix()}")

    # Pool-and-weight pass: one file per scheme.
    pooled_summary = []
    for scheme_name, weights in WEIGHT_SCHEMES.items():
        pooled = aggregate_pooled(
            scheme_name, weights, by_pitcher_by_year,
            pairs, triples, legs_sorted,
        )
        out = DATA_DIR / f"aggregates_pooled_{scheme_name}.json"
        with out.open("w", encoding="utf-8") as f:
            json.dump(pooled, f, ensure_ascii=False, separators=(",", ":"))
        size = out.stat().st_size / (1024 * 1024)
        pooled_summary.append((scheme_name, pooled["n_pitchers"], size, out))

    print()
    print("Aggregate build summary (pool-and-weight)")
    print("-" * 64)
    for name, n_pitchers, size, path in pooled_summary:
        print(f"  {name:>11}: {n_pitchers:>3} pitchers  "
              f"{size:5.2f} MB  -> {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
