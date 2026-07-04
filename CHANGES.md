# Changes

## 2026-07-04 session

### World Cup combos: prebuilt fallback + knockout-slate fixes ("no match" everywhere)
Every combo market (Winner/Total, HT/FT, BTTS/Winner, BTTS/Total) showed `no match` on knockout-round matches. Three stacked causes, verified against the live Canada vs Morocco event (34339353):
1. **DK's `calculateBets` endpoint is failing for every request** (MLB pairs too, so it's not soccer-specific) — every combo whose SGP legs resolved died with `sgp_price_unavailable`.
2. **Knockout slates drop the SGP leg markets**: no regular-time `Both Teams to Score` (only the "Including Extra Time" variant, a different proposition) and no 1st-half Moneyline — so BTTS/Winner, BTTS/Total and HT/FT legs can't even be built.
3. The 2026-06 change made combos **hand-built SGPs only, no prebuilt fallback** — so when 1+2 hit, everything reported unmatched even though DK posts prebuilt `Half Time / Full Time` (9 sels) and `Moneyline / Both Teams to Score` (6 sels) on the same event.

**Fix (dk_api.py).** `find_sgps_worldcup` is SGP-first as before, but now falls back to the prebuilt combo market when a leg can't resolve or pricing fails (`via: "prebuilt"`, so the UI's SGP badge still only marks real tickets). Replayed against the live event dump: 55/97 → **72/97** matched with pricing down (HT/FT 9/9, BTTS/Winner 6/6 restored), 82/97 once `calculateBets` recovers (Winner/Total + Odd-Even/Total upgrade to `via: "sgp"`). Remaining misses are genuine DK absences on knockout slates (no regular-time BTTS or team-total-goals markets, unlisted lines/bands).

**Also fixed.**
- `_soccer_straight_kind`: alternate spread lines (±1.5, ±2.5) live under a subcat literally named `Spread`, not `Asian Handicap` — both now classify, restoring the alt-line spread rows.
- `_price_combo` now tallies outcomes (HTTP status counts, incompatible, no-bet, exceptions) into `_PRICE_DIAG`; `find_sgps_worldcup` returns the snapshot as `sgp_price_diag` so a pricing outage is diagnosable from the API response.
- `get_price` returns `{"error": "calculateBets HTTP <status>", "status", "body"}` instead of raising, and `dkCall` (server.js) surfaces the JSON error dk_api.py prints on exit 1 instead of the opaque `dk_api.py exited with code 1` — `/api/dk/price` now reports the real failure mode.

## 2026-06-11 session

### World Cup SGP +EV tab
New top-level sport (`WORLD CUP` in the `.sport-bar`) for soccer same-game-parlay combo markets at the FIFA World Cup. Unlike tennis/NBA there is **no correlation model**: Pinnacle prices each joint outcome directly, so the fair probability is a straight multiplicative devig of each combo market group (every group is a mutually exclusive, exhaustive partition).

**Markets.** `Both Teams To Score/Total Goals`, `Both Teams To Score/Winner`, `Winner/Total Goals` (the mains), plus `Half-Time/Full-Time` and `Odd/Even / Total Goals` as bonus combos. Correct-score / exact-total-style markets are ignored by design.

**Inputs (two paths, one client code path).**
- *Live pull (primary)* — `LOAD SLATE` hits Pinnacle's guest API (`guest.api.arcadia.pinnacle.com`, static guest key, via the same curl_cffi Chrome-TLS session that talks to DK) and lists all World Cup matches; picking one fetches its special markets live. League 2686, override via `PINNACLE_WC_LEAGUE_ID`.
- *PDF upload (fallback)* — print the Pinnacle match page to PDF and drop it on the tab. `POST /api/extract-worldcup-pdf` (multer + `pdf-parse`, new dep) extracts the text layer; `pinnacleSoccer.js` tokenizes it (American-odds tokens terminate selection names, icon-font PUA glyphs stripped) into the same `{home, away, kickoff, markets}` shape.

**DK side.** No SGP pricing engine needed — DK lists these combos as straight markets. `find_sgps_worldcup` (dk_api.py) resolves the league (env `DK_WORLDCUP_LEAGUE_ID`, else scrapes slug `world-cup-2026`; live id 209533), matches the event by team names either orientation, scans soccer subcats, and maps each candidate to a DK selection using the verified label grammar: `"Mexico Win and Over 2.5"`, `"Tie with Goals"` / `"Win to Zero"` (BTTS yes/no), `"Mexico/Tie"` (HT/FT). Two traps encoded: DK's `Both Teams to Score / Over 2.5 Goals` "No" is the *complement* of (Yes & Over), not Pinnacle's "No & Over", so only the Yes cell maps; and `Half Time / Full Time / Over/Under 2.5` shares HT/FT labels and must not shadow plain HT/FT. The response includes `available_markets` for renaming debuggability.

**Output.** Table ranked by `EV% = fair_prob × dk_decimal − 1`, with Pinnacle price, no-vig FV, fair %, DK price, and full-Kelly %. Filters: min-EV slider, per-market toggles, matched-only. Endpoints: `/api/pinnacle/worldcup-games`, `/api/pinnacle/worldcup-match/:id`, `/api/dk/find-sgps-worldcup`, `/api/dk/worldcup-games`, `/api/dk/worldcup-resolve-league`.


## 2026-05-26 session

### Tennis SGP +EV tab (French Open M)
New top-level sport (`TENNIS` next to MLB / NBA in the `.sport-bar`) targeting 1st-set-total × dog-game-handicap SGPs at the men's grand slam. Sport-wide correlations are hardcoded priors:

| 1st Set Total Over | r vs dog Game Handicap |
| --- | --- |
| 8.5  | 0.20 |
| 9.5  | 0.27 |
| 10.5 | 0.30 |
| 12.5 | 0.34 |

**Inputs.** Two FV-sheet uploads (one screenshot per market). OCR (`/api/extract-tennis`) auto-normalizes both layouts we've seen — the older `name / book_odds / fv` schema and the newer `bet_name / odds / avg_fv / tournament` schema — to a single `{game, market, bet_name, book_odds, fv, devig_odds, tournament}` row. Rows accumulate across uploads and merge by `game` key into SGP candidates. Favorite-side spread rows (`-X.5`) are dropped; only the dog side feeds the correlation.

**Fair-price source toggle.**
- `FV` (default) — uses the sheet's signed `fv` integer for each leg.
- `DK NO-VIG` — no-vigs DK's own two-sided `book_odds` pair (e.g. `-150/+100` → fair `-120`) for each leg.

Joint prob via `sgpMath.jointFrechet(pa, pb, r)`, same function the pitcher + teammate + NBA pipelines use. EV vs DK SGP price + Kelly + `evAttribution` rendered on each card.

**DK linkage.** `dk_api.py:get_games_tennis()` pulls events from `DK_TENNIS_LEAGUE_ID` (env-configurable; defaults to a placeholder for French Open M — set it explicitly to the live league ID). `find_sgps_tennis()` resolves each candidate to one event by player-name match, scans markets with the new `tennis_only=True` subcat filter, matches Set-1 Over/Under and per-player full-match Game Handicap legs by line + name, then prices each unique pair via `_price_combo` with the existing 110s soft deadline + Akamai-safe retry budget. Response cached server-side for 10 minutes per candidate-set fingerprint (mirrors the NBA pricing cache).

**Files.** `dk_api.py` (+ tennis league ID, get_games_tennis, find_sgps_tennis, tennis subcat filter), `server.js` (+ `/api/extract-tennis`, `/api/dk/find-sgps-tennis`, `/api/dk/tennis-games`, OCR prompt + parser), `public/index.html` (+ sport-btn, nav, header, page, sport switcher), `public/utils/tennisEvTab.js` (new tab module — upload merge, fair-mode toggle, scan, render).

## 2026-04-24 session

### AI Insights: structured context, r_DK attribution, correlation-gap-first prompt
2-leg cards now compute `r_DK` (inverting `jointFrechet` on the DK SGP price with our FV legs) and an EV attribution split (`evFromLegsPct` + `evFromCorrPct`). New `DK R` column on the card shows the gap directly. `sgpInsightPrompt.js` rewritten to hand the model a structured context object (FV legs, empirical hits J/N, P(A)·P(B), P(B|A), r_ours, r_DK, r_gap, attribution split) and enforce a correlation-gap-default thesis (pitcher leg markets are near-efficient, so for EV > ~8% the edge must live in the r_ours vs r_DK gap), correct-math (P(B|A) vs P(B) not vs P(A)·P(B); near-zero r_ours is not "no correlation edge" when r_gap is large), specific-risk, and honest-score rules. `sgpMath.js` gained `inverseJointFrechet` and `evAttribution` (unit-tested roundtrip + clamp).

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
