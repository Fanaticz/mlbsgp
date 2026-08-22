# Changes

## 2026-08-22 session

### Soccer SGP +EV: multi-league support (EPL added), DK vs Pinnacle
The soccer tab (previously World Cup–only) now works for any soccer league via a **league picker**. Added **English Premier League** — DK eventGroup **40253**, Pinnacle league **1980** — verified live against today's slate.

The whole soccer engine (DK combo grammar + Pinnacle devig) was already league-agnostic; only the league IDs and club naming differed. Changes:
- **`dk_api.py`** — new `SOCCER_LEAGUES` registry (`worldcup`, `epl`; env-overridable ids) + `_soccer_league()` resolver. `get_games_soccer` / `pinnacle_wc_games` / `find_sgps_worldcup` accept a `league` key. New `soccer-leagues` CLI command returns the registry. Added `_SOCCER_CLUB_ALIASES` so DK short forms match Pinnacle long forms (Man City↔Manchester City, Wolves↔Wolverhampton, Spurs↔Tottenham, …) — without it, e.g. Bournemouth @ Manchester City failed to match between books.
- **HT/FT prebuilt fix** — DK's EPL "Half Time / Full Time" selections leave `label` null and put the paired result ("Nottingham Forest/Leeds") only in the bet-slip line; the World Cup format put it in the label. `get_markets` now carries `betslipLine` on each prop and the `ht_ft` matcher falls back to it, so EPL HT/FT combos match DK's posted price **with no `calculateBets` call** (cookie-free).
- **`server.js`** — `/api/pinnacle/worldcup-games` takes `?league=<key>`/`?leagueId=<id>` and league-keys its cache; new `/api/soccer/leagues` serves the registry; `find-sgps-worldcup` cache key includes the league.
- **Frontend** — league `<select>` in the soccer tab (populated from `/api/soccer/leagues`), passed to both the Pinnacle slate pull and the DK scan. Tab relabeled World Cup → Soccer.

Verified offline via `scripts/smoke_soccer_epl.py` (+ trimmed fixture): registry resolution, club aliases, BTTS/Total leg resolution, and cookie-free HT/FT prebuilt matching against Pinnacle candidates.

**Caveat — the combined DK price for BTTS + Over 2.5:** unlike the World Cup, DK does **not** prebuild "BTTS & Total" / "Result & Total" combos for EPL (only HT/FT). Those combos' legs resolve fine, but the correlated combined DK price comes from `calculateBets`, which is behind the same Akamai validated-cookie gate as MLB pricing — so from a datacenter IP it needs `DK_COOKIES`. Without it, EPL shows Pinnacle fair lines + DK's prebuilt HT/FT combos + individual leg prices; with it, the full BTTS+O2.5 SGP is priced and compared.


### DK API migration: games + markets restored after DK retired the nav/controldata endpoints
DK prices stopped resolving because DraftKings retired two of the three endpoints the tool depended on. The old games feed (`.../sportscontent/navigation/dkusnj/v1/nav/leagues/{id}`) and the per-subcategory market feed (`.../sportscontent/controldata/event/eventSubcategory/v1/markets`) now return **404**. The per-event SGP feed (`.../sportscontent/parlays/v1/sgp/events/{id}`) still serves **200**.

Fix (`dk_api.py`):
- **Games** now come from the sportscontent leagues route `.../sportscontent/<site>/v1/leagues/{id}` (`DK_LEAGUES`; `DK_SITE` env, default `dkusnj`). Event ids/start times moved fields (`eventId`→`id`, `startDate`→`startEventDate`); parsing accepts both via `_ev_id`/`_ev_start`. Bonus: MLB games now expose each starter's name (`homeStarter`/`awayStarter`) from participant metadata. All five game functions (MLB, NBA, tennis, World Cup) were on the dead endpoint and are repointed.
- **Markets** now come entirely from the still-live SGP feed, which embeds every SGP-eligible market's selections + odds inline. `get_markets()` filters that single response by subcategory in memory instead of fanning out ~100 parallel per-subcategory GETs to the retired controldata endpoint. One request per event is also far friendlier to Akamai's rate limiter. The `props` output shape is byte-for-byte unchanged, so leg-matching (`_match_leg_to_dk`), `find_sgps`, and the frontend are untouched. Dead `_fetch_subcategory` + `DK_MARKETS` removed.
- Verified offline against a live-captured feed fixture: `get_markets(pitcher_only=True)` returns both starters' complete Over/Under legs (K, ER, Hits Allowed, Outs, Walks) with valid `calculateBets` selection ids and decimal odds; milestone (X-or-Fewer) legs parse their thresholds; `_match_leg_to_dk` resolves all sample OCR legs to selection ids.

**Still pending, unchanged by this fix:** the combined correlated SGP price comes from `calculateBets`, which sits behind Akamai Bot Manager and requires a *validated* `_abck` cookie. From a datacenter IP that POST still 403s (documented at length in the 2026-07 entries below). The no-VPN path is the existing `DK_COOKIES` env — paste a fresh validated cookie string from a logged-out browser in a legal state — after which pricing resumes on top of the now-working market data. Per-leg DK prices themselves need no cookie and work again immediately.

## 2026-07-06 session

### MLB +EV finder: FV-only fallback when DK prices can't be pulled ("screenshot mode")
When every DK SGP price fails — calculateBets 403 storm, DK games endpoint down, or a network error — the pitcher +EV finder no longer dead-ends at a diagnostic empty state. It now computes the **fair value of each SGP straight from the uploaded screenshot**: per-leg `avg_fv` (already OCR'd) → implied probabilities → the same pairwise-Fréchet correlation correction the priced path uses (`evComputeCombo` with `dkDecimal=null`), rendered as FV-only cards **sorted by FV odds low → high** (biggest favorites first). Cards show FV CORR, FV INDEP, binary-phi R, per-leg/combined historical hit rates, and the blend-transparency line; EV%, Kelly, and DK-price columns are omitted because there is no DK price to beat — the FV is presented as the price to beat. Works in both 2-leg and 3-leg modes (3-leg cards add the shrunk empirical MODEL joint when the triplet exists in the aggregates), and re-resolves live on GLOBAL/BLENDED/PLAYER toggles.

Combo enumeration happens client-side since DK can't be asked: cross-stat combos are always legal (mirrors what `find_sgps` enumerates and DK accepts), same-stat combos only when they appear verbatim in `combo_spec.json` — which admits the Over-K-style ladders and rejects contradictory Over/Under of the same leg. The whitelist ships to the client via a new `GET /api/combo-spec` endpoint; if that fetch fails, same-stat ladders are conservatively dropped while all cross-stat combos still render. The fallback only engages when DK priced **zero** combos — if DK priced some and render filters hid them, the filters remain the message. Pure helpers (enumeration, legality, low→high sort) live in `public/utils/fvFallback.js` (UMD, Node-testable); guarded by `scripts/smoke_fv_fallback.js` (fixture = the 07/06 NYY@TB Schlittler/Jax sheet).

### WNBA prop builder: this-season two-stat scatter per player
Clicking a player on the WNBA page now opens a prop builder above the per-season history: set a PTS line and a second-stat line (REB by default; AST/3PM selectable) and get a scatter of **every game this season only** (one dot per game, dots grow when multiple games land on the same score), the two lines drawn in red, and four tiles showing how often each over/under combo hit (count, %, and the fair American odds that hit rate implies — TacoBot-style). Over = strictly greater; games landing exactly on an integer line count as pushes and are excluded (noted when present). Line inputs redraw just the chart, so typing keeps focus; per-player settings survive re-renders. Data side: `scripts/wnba_fetch_correlations.py` now emits `latest_games` per player — the full date-ordered current-season game log (date, opponent, home/away, W/L, min/pts/reb/ast/3pm) taken from the same ESPN gamelog payload — and `public/data/wnba_correlations.json` was regenerated (195 players through 2026-07-05, ~1.1 MB).

## 2026-07-05 session (later)

### calculateBets 403 root cause: unvalidated Akamai `_abck` + validated-cookie provider
Rounds 1–2 (retries, browser headers, homepage warmup, host override) didn't stop the 403 storm because they targeted the wrong layer. Reproduced end-to-end: market GETs on `sportsbook-nash` return 200 and legs match fine, but every `calculateBets` POST to `gaming-us-*` returns an **Akamai edge 403** ("AkamaiGHost / Access Denied") — instantly, on the first attempt, identically across all six state hosts. Root cause: the homepage warmup collects an **unvalidated** `_abck` cookie (its 2nd `~`-field is `-1`). Akamai Bot Manager only flips `_abck` to *validated* after its in-page sensor JS POSTs telemetry back — which curl_cffi can't run. The market GETs don't enforce validation (so they work); the wager POST does (so it 403s). No header/cookie/host/fingerprint permutation fixes this from a plain HTTP client.

Added a validated-cookie provider for the pricing POST (`dk_api.py`), tried highest-priority first:
1. `DK_COOKIES` env — a raw `name=value; name=value` string pasted from a logged-out browser (must include a validated `_abck`). Immediate stopgap; refresh when it expires.
2. `DK_COOKIE_BROWSER=1` — mint cookies with a headless browser that runs the sensor JS, cached with `DK_COOKIE_BROWSER_TTL` (default 600s) and re-minted when stale. Durable, but requires Playwright + a Chromium build in the image (point `DK_CHROMIUM_PATH` at the binary if needed); off by default and lazy-imported, so it's a no-op unless enabled.
3. homepage warmup (legacy) — unchanged, kept as the last-ditch fallback.

Injected cookies are `.draftkings.com`-scoped so they ride to the gaming-us host and survive `_rotate_session()`. The `_abck` validation state and the cookie source are now recorded on `sgp_price_diag`, and the +EV empty state reads them: on a 403 with an unvalidated `_abck` it now says the block is Akamai bot protection fixable via `DK_COOKIES`/`DK_COOKIE_BROWSER`, instead of the misleading "try again in a few minutes."

> Note: from a datacenter IP, even a validated `_abck` may not be enough if DK is also scoring the egress IP — if `DK_COOKIES` with a fresh validated cookie still 403s in prod, the next lever is a residential/rotating proxy for the pricing POST.

### calculateBets Akamai hardening (round 2 — prod diag showed HTTP 403 ×57)
The retry fix alone wasn't enough: prod diagnostics showed all 57 pricing POSTs 403-ing while market GETs (different host) worked. The pricing POST looked exactly like a bot to Akamai: no Origin/Referer, no `.draftkings.com` cookies (market traffic lives on `sportsbook-nash`, cookies are domain-scoped), and every fingerprint rotation discarded whatever cookies existed. Now: (1) calculateBets POSTs send browser headers (`Origin`/`Referer: sportsbook.draftkings.com`, Accept, Accept-Language); (2) a one-time best-effort GET of the sportsbook homepage collects Akamai clearance cookies into the shared jar before the first pricing call; (3) `_rotate_session()` carries the cookie jar into the new session; (4) `DK_PRICE_HOST` env var switches the state pricing host (e.g. `gaming-us-ny.draftkings.com`) from Railway without a code change — the NJ host being blocked doesn't mean the others are.

### MLB SGP pricing fix: calculateBets retries + diagnosable empty state
The +EV Finder showed "No SGPs could be priced" with legs matched fine — the 2026-07-04 calculateBets outage pattern. Root cause candidate: every DK **GET** goes through `_get_with_retry` (fingerprint rotation, cool-off, backoff), but the pricing **POSTs** in `_price_combo`/`get_price` were single bare `session.post()` calls — first Akamai 403 killed every price call while market fetches recovered by rotating. New `_post_with_retry` gives POSTs the same survival kit (retries only 403/429/5xx; 422/400 pass through so incompatible-leg semantics are unchanged; exhaustion returns the last response so `_PRICE_DIAG` status tallies still work). `find_sgps` (MLB) now returns `sgp_price_diag` like the World Cup path, and the frontend empty state renders the actual failure mode ("calculateBets rejected all 20 attempts (HTTP 403 ×18…)") instead of the generic guess list.

### Claude model bump
OCR/vision extraction endpoints (`server.js` ×4) moved `claude-opus-4-7` → `claude-opus-4-8` (same API surface, better vision/knowledge-work). The leg-normalization call already uses `claude-haiku-4-5-20251001`, which is the newest Haiku.

### WNBA correlations refreshed + daily auto-refresh workflow
`public/data/wnba_correlations.json` regenerated via `scripts/wnba_fetch_correlations.py` (was stale since 2026-06-22; now 195 players through 2026-07-04). New `.github/workflows/refresh-data.yml` runs daily at 11:00 UTC (after West Coast games go final) and on manual dispatch: ESPN pitcher fetch → `build_pitcher_data.py` (supplement merge + dedupe) → `build_aggregates.py` → WNBA correlations, then auto-commits `espn-2026-pitcher-supplement.json` + `public/data/*.json` only if something changed. Dedupe lives in the build script, so scheduled re-runs can never double-count a start.

### 2026 pitcher data refreshed through July 4 via ESPN (no double counting)
The 2026 xlsx feed ended 2026-05-15. New `scripts/fetch_espn_2026_pitchers.py` pulls every completed regular-season game from ESPN's public site API for a date window (default 2026-05-16 .. today) and writes starting-pitcher lines to `espn-2026-pitcher-supplement.json` in the same schema as `pitchers_YYYY.json`. `build_pitcher_data.py` merges the supplement into `pitchers_2026.json`, deduping by (pitcher name, date) with the xlsx winning on conflict, so re-running either script never double-counts a start. `pitchers_2026.json`: 1,337 → **2,663 starts** (2026-03-25 .. 2026-07-04); all per-year and pooled aggregates rebuilt.

**Validation.** On xlsx-covered dates (5/14–5/15) the ESPN extraction matched the feed 52/52 rows exactly on every shared field (IP, H, ER, BB, K, HR, W/L, QS, hand, venue, team names — ESPN names are accent-stripped to the feed's spelling, e.g. "Jesus Luzardo").

**ESPN traps encoded in the fetcher.** The boxscore `starter` flag marks anyone who *started the game*, including position players who mopped up blowouts (catcher Carson Kelly, SS Miguel Rojas) and sometimes random relievers; and the pitching list can mis-sort a position-player pitcher above the real starter (RF Carlos Cortes listed first in 401815762 — play-by-play shows Jeffrey Springs started). The starter is therefore the first entry in the pitching group whose `position` is an actual pitcher; openers (RP) genuinely start and are kept, matching the xlsx `STARTING PITCHER == YES` semantics.

**Field coverage.** `bf` / `gb` / `fb` aren't in ESPN box scores → null (nothing downstream reads them; correlations use only K/ER/BB/H-allowed/IP→outs). `pid` and throwing hand are reused from existing rows by name; new call-ups get the ESPN athlete id and the core-API `throws` hand. `qs` derived (outs ≥ 18 and ER ≤ 3), W/L from the `pitchingDecision` note, `gid` is `espn-<eventId>`.

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
