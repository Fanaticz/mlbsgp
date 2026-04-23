# MLB SGP — Project Overview

Single-page reference for the MLB (+ NBA) Same-Game-Parlay +EV finder. Written to be pasted into a Claude Chat project as background context.

---

## 1. Overview

**What it is.** A correlations-based SGP +EV tool. It ingests DraftKings SGP markets plus historical pitcher/batter box-score data, computes joint probabilities under empirical correlation, and ranks combos by expected value vs. DK's offered price.

**Two product surfaces (MLB):**
- **Pitcher SGP +EV Finder** — primary, mature. 2-leg and 3-leg combos over a single pitcher's stats (K, ER, BB, H, Outs, etc.).
- **Teammate SGP +EV** — Phase 2. Pairs of batters on the same team, using slot-pair correlations with Bayesian shrinkage.

**Phase 3 — NBA.** Same EV pipeline (Fréchet bounds + shrinkage), but correlations are **uploaded at runtime** and persisted to a Railway Volume instead of baked into the repo.

**Stack & deployment.**
- Express (Node 20) host — `node server.js`, default `PORT=3000`.
- Python 3.11 subprocess for DK calls (`dk_api.py`) using `curl_cffi` to impersonate a browser through Akamai.
- Railway deploy via `nixpacks.toml`; compression middleware ships the ~30 MB aggregate JSONs as ~1.8 MB gzipped.
- Frontend is a single bundled `public/index.html` that lazy-loads aggregate JSONs at startup.

**Key files at the repo root.**
| File | Role |
| --- | --- |
| `server.js` | Express host, OCR `/api/extract`, leg normalization, static serving with cache-busting (`server.js:23–46`). |
| `dk_api.py` | DK client — `games`, `markets`, `featured`, `price`; Akamai bypass via `curl_cffi`. |
| `build_pitcher_data.py` | xlsx → slim `public/data/pitchers_YYYY.json` + `manifest.json`. |
| `build_aggregates.py` | Per-pitcher weighted-Pearson combo correlations + pooled schemes. |
| `build_teammate_aggregates.py` | Per-(p1,p2,team) slot-pair correlations + league-wide slot baselines. |
| `combo_spec.json` | Whitelist of valid SGP 2-leg pairs (166) and 3-leg triples (690). |
| `CHANGES.md` / `TESTING.md` / `NBA_DEPLOY.md` | Changelog, smoke-test checklist, NBA volume/rollback config. |

**`public/`** — `index.html` (all-in-one frontend), `data/*.json` (read-only aggregates), `utils/` (`sgpMath.js`, `teammateMath.js`, `nbaEvTab.js`, `nameNormalize.js`, `sgpInsightPrompt.js`).

---

## 2. Data Pipeline

### Inputs
- `MLB-2023-Player-BoxScore-Dataset.xlsx`, `MLB-2024-…`, `MLB-2025-…` — historical per-game rows.
- `04-16-2026-mlb-season-player-feed.xlsx` — current-season feed, same schema.
- Columns include: player, team, opponent, hand, IP, H, ER, BB, K, W/L, HR, QS, BF, GB, FB.

### Build steps (offline, idempotent)

**`build_pitcher_data.py`** (`build_pitcher_data.py:1–32`)
- Reads all four xlsx files; filters `STARTING PITCHER == YES AND IP > 0`.
- Emits `public/data/pitchers_YYYY.json` (~1.2–1.3 MB/year) with slim keys (`gid, d, pid, p, t, o, v, h, ip, h_allowed, er, bb, k, w, l, hra, qs, bf, gb, fb`) plus `manifest.json`.

**`build_aggregates.py`** (`build_aggregates.py:1–137`)
- Inputs: all `pitchers_YYYY.json`.
- Converts IP → outs (e.g. `5.2 → 17`, `build_aggregates.py:85–100`).
- For each `(Over/Under, threshold)` leg, builds a binary 0/1 hit vector, then computes weighted Pearson on pairs (`combos_2`) and triples (`combos_3`) — `weighted_pearson` at `build_aggregates.py:117–137`.
- Pooling schemes (`build_aggregates.py:50–57`): `dyn_1_3`, `dyn_4_8`, `dyn_9_15`, `dyn_16plus`, plus `static` and `unweighted`. The dynamic schemes pin 2026 weight per-pitcher based on current-season sample size.
- Outputs:
  - `public/data/aggregates_YYYY.json` — per-year: `global_2`, `global_3`, `pitchers.{combos_2, combos_3, avg_*, raw_corr, n_starts_eff}`.
  - `public/data/aggregates_pooled_<scheme>.json` — blended across years.
- `raw_corr` carries unweighted cross-stat Pearson (SO, ER, BB, H, OUTS pairs) for the display-only "Margin" column.

**`build_teammate_aggregates.py`** (`build_teammate_aggregates.py:1–55`)
- Inputs: the same xlsx files, filtered to starters (`PA > 0 AND BO# populated`).
- Per-(p1, p2, team) stats: `n_by_year`, `slot_gap`, `adjacency`, `combos_2` containing both binary phi and continuous r_margin, hit rates, conditional probs. HRR composite = H + R + RBI.
- Outputs: `teammate_aggregates_pooled_<scheme>.json` and `slot_pair_baselines.json` (league-wide slot-pair priors for Bayesian shrinkage).

### Runtime consumption
- `server.js:23–46` serves `public/data/*.json` with a 1 h cache; `index.html`/`utils/*.js` served `no-cache` for cache-busting on deploy.
- `index.html` startup (`buildBlendedD`, ~lines 2816–2817) merges `aggregates_YYYY.json` into `window.D`.
- Pitcher page → `D.pitchers[name]` → `combos_2`, `combos_3`, `n_starts_eff`, `raw_corr`.
- `dk_api.py._price_combo()` posts selection IDs to DK's `calculateBets` endpoint and returns the true SGP price.

### `combo_spec.json`
Precomputed whitelist so we don't query DK for invalid SGP combos.
- `pairs_2`: 166 legal 2-leg combos (e.g. `Over 4.5 K × Under 1.5 ER`).
- `triples_3`: 690 legal 3-leg combos.

---

## 3. Pricing / Math

The EV computation is a correlation-adjusted joint probability, compared to the DK-priced decimal odds.

### Correlation input: binary phi (not r_margin)

As of commit `3dbec52` — *"Route pitcher EV math through binary phi; stop using r_margin as correlation input"* — all EV math reads binary phi (Pearson on 0/1 leg-hit indicators), not the continuous raw-stat correlation.

- `index.html:1391–1408` — `resolveR()` → `_findRBinaryIn(...)`.
- `resolveRMargin()` (`index.html:1456+`) and `resolveRBinary()` (`index.html:1489+`) still exist, but are display-only (pitcher tooltip, Margin column).
- Rationale: binary phi is the correct input for a joint-probability bound on binary leg outcomes. r_margin (raw-stat correlation) was a leaky proxy.

### Joint probability via Fréchet blend

`sgpMath.js:42–60`, called at `index.html:1763`:

```
jointFrechet(pa, pb, r):
  pab = pa * pb                                 # independence
  if r >= 0: return pab + r * (min(pa,pb) - pab)       # blend toward upper Fréchet
  else:      return pab + r * (pab - max(0, pa+pb-1))  # blend toward lower Fréchet
```

Linear interpolation between independence and the Fréchet bounds, parameterized by binary phi.

### Bayesian shrinkage on `r`

`resolveR()` at `index.html:1420–1454`:

- `n_eff` = year-weighted effective start count (`n_starts_eff`).
- `BLEND_MIN_STARTS = 5` (`index.html:1316–1319`; lowered from 10 in commit `8b11254`).
- Shrinkage weights in `_blendWeights()` at `index.html:1260–1267`:
  - 2-way: `w_player = n / (n + K)` with `K = 50`.
  - 3-way: `K = 80`.
- Modes:
  - `player` — raw pitcher r (noisy for n < 10).
  - `global` — league baseline pooled across all pitchers.
  - `blended` (default) — if `n_eff < BLEND_MIN_STARTS`, fall back to global; otherwise `w_player · r_player + w_global · r_global`.
- Dynamic year weighting: the per-pitcher pooling scheme (`dyn_1_3` … `dyn_16plus`) is chosen by current-season sample, so a pitcher with 2 starts in 2026 blends differently than one with 20.

### 3-way combos

`resolveAll3()` at `index.html:1991+`:
- Uses the empirical all-3 hit rate from `aggregates_pooled_<scheme>.combos_3`.
- Shrinks toward the global 3-way baseline with `K_3WAY = 80`, with a floor at `n_eff = 15`.

### EV calculation

`evComputeCombo()` at `index.html:1760–1800`:

```
pa, pb        = leg marginal probs (from DK or modeled)
r             = resolveR(...)                 # binary phi, shrunk
pab           = jointFrechet(pa, pb, r)

logIndep      = log(pa) + log(pb)
corrSum       = Σ over pairs [ log(pab) − log(pa · pb) ]   # log-likelihood ratio
pJoint        = exp(logIndep + corrSum)                    # correlation-adjusted joint

fvCorrOdds    = probToAmerican(pJoint)
evPct         = (pJoint · dkDecimal − 1) · 100
kellyPct      = (pJoint · dkDecimal − 1) / (dkDecimal − 1) · 100
```

### NBA pricing

- Same Fréchet + shrinkage pipeline via `public/utils/nbaEvTab.js`.
- Correlations are user-uploaded and stored to `/data/nba/correlations_current.json.gz` on the Railway Volume (see `NBA_DEPLOY.md`).
- DK leg matching: `dk_api.py:753+` (`_match_leg_to_dk_batter`) maps `(player, stat, direction, line)` → DK selection ID; game matching uses full team name / game string.

---

## Quick map

- **Rebuild data:** `python build_pitcher_data.py && python build_aggregates.py && python build_teammate_aggregates.py`
- **Run locally:** `node server.js`
- **Smoke tests:** `TESTING.md` checklist; regression scripts under `scripts/`.
- **Deploy:** push to main → Railway (nixpacks). NBA correlations are uploaded at runtime, not committed.
