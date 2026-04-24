# Changes

## 2026-04-24 session

### AI Insights: structured context, r_DK attribution, thesis-first prompt
2-leg cards now compute `r_DK` (inverting `jointFrechet` on the DK SGP price with our FV legs) and an EV attribution split (`evFromLegsPct` + `evFromCorrPct`). New `DK R` column on the card shows the gap directly. `sgpInsightPrompt.js` rewritten to hand the model a structured context object (FV legs, empirical hits J/N, P(A)·P(B), P(B|A), r_ours, r_DK, r_gap, attribution split) and enforce thesis-first / correct-math (P(B|A) vs P(B), not vs P(A)·P(B)) / specific-risk / honest-score rules. `sgpMath.js` gained `inverseJointFrechet` and `evAttribution` (unit-tested roundtrip + clamp).

## 2026-04-17 session

### 571e187 — Collapse duplicate `(pitcher, leg)` rows and canonicalize SGP leg ordering
Added a second-pass dedup in `server.js:normalizeRows` that collapses duplicate `(pitcher, leg)` entries coming out of OCR. Canonical row picked by `(books_count desc, L desc)` — no averaging. OCR prompt now requests `books_count` from column 12 so the collapse has a signal to rank on. In `dk_api.py`, combo index pairs are swapped after `combinations()` so the leg with the alphabetically earlier stat category (BB < ER < H < OUTS < SO) always comes first. Fixes the 4× duplicate Wacha cards observed when FV sheet or OCR emits multiple rows for the same leg.

### 8b11254 — Lower blend threshold to 5
`BLEND_MIN_STARTS` lowered from 10 to 5. The `n/(n+50)` shrinkage already self-degrades player influence at low samples (9% at n=5, 17% at n=10). Threshold of 10 was double-counting the small-sample penalty and disproportionately caught veterans with thin recent seasons (injury years, swing roles, late callups). Threshold of 5 keeps a sanity floor while letting the shrinkage math work on its own.

### 53633f1 — Pass 2: `n_eff` shrinkage + blended-mode UI + float-precision cleanup
`resolveR()` is now the single source of truth for correlation reads — uses `n_starts_eff` (year-weighted) for the shrinkage threshold and blend weights instead of raw `n_starts`, and exposes `{r, source, wPlayer, wGlobal, n, rPlayer, rGlobal}` so EV card labels, pitcher-page tooltips, and raw_corr displays reconstruct from the same data. Blended mode shrinks both the binary `r` and the raw-stat `r_margin` on the pitcher page. `avg_r` for 3-leg combos is the simple mean of the three shrunk pair r's. EV label reads source not mode, so low-sample blend fallbacks render as `(blended → global)`. Float precision cleaned up in `_blendCombosGeneric`: percentage fields rounded to 1 decimal, display-only correlation variants (`r_avg`, `r12a/13a/23a`, `avg_ra`) rounded to 4. Primary correlation fields left un-rounded (they feed math). `_warnMissingPair` and `_blendCombosGeneric`'s gap warning both gated behind the frontend `DEBUG` flag.

### 6d8574e — Pass 1: year-weighted blending for pitcher + global data
Replaced the 25 MB inline `var D = {…}` with a loader that fetches `public/data/aggregates_YYYY.json` for all four years and builds an equivalent-shape `D` object at page load. Dynamic weights key off each pitcher's own 2026 starts via `getDynamicWeights`. Globals blend via static `YEAR_WEIGHTS = {2023:0.15, 2024:0.20, 2025:0.30, 2026:0.35}`. `normalizeWeights` pins 2026 at its dynamic-table value so renormalization over missing years can't inflate it past its prescribed share. Badge and stats-row now render from runtime totals. Pitcher page shows `STARTS · EFF N`.

### e398835 — Per-year correlation aggregator + gzip middleware
Added `build_aggregates.py` reading `public/data/pitchers_YYYY.json` and emitting `public/data/aggregates_YYYY.json` — same shape as the legacy inline `D` (`global_2`, `global_3`, `pitchers` with `combos_2/combos_3/avg_*/raw_corr`) plus `global_raw_corr` for shrinkage-toward-global. IP converted via baseball rules (`5.2 IP → 17 outs`). Null-only combo rows dropped. `server.js` gained `compression` middleware so the 22 MB/year files ship at ~1.8 MB gzipped.

### 063e0fc, 20a2000 — Raw pitcher JSON builder
`build_pitcher_data.py` converts the four xlsx season feeds (2023–2026) to slim `public/data/pitchers_YYYY.json` + `manifest.json`. Idempotent — drop a refreshed 2026 xlsx and re-run.
