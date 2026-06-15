# Long Ball Jackpot Model

An EV optimizer for Fanatics Sportsbook's **Daily $50K FanCash "Long Ball" Jackpot**.
Bet $5+ on an anytime-HR hitter; if your player hits the **single longest HR in MLB that
day**, you split $50,000 FanCash **equally** with everyone else who bet that same player.

```
payout_if_win = $50,000 / (entries on that player)
EV per $5 ticket = P(player hits the day's longest HR) × payout_if_win
```

Payout is entirely about how crowded your pick is. The public bets by **anytime-HR odds**
(who's most likely to homer), but the jackpot pays **distance**, not probability. The
structural edge:

> **High distance ceiling + LONG HR odds = a bat that can win the day that nobody is on.**

Short HR odds → popular → many entries → tiny payout even when they win (Soderstrom hit the
longest on 6/14 and paid just **$365** on 137 entries). Long HR odds → ignored → few entries
→ huge payout (Caballero, 5 entries, would've paid $10,000; Durán, 1 entry, the full $50k).

## Fully automated — no manual uploads

Every input is fetched programmatically (via `curl_cffi` browser impersonation, the same
Akamai/CDN bypass `dk_api.py` uses). Screenshots/CSVs are only a calibration archive.

| # | Input | Source | Module | Feeds |
|---|-------|--------|--------|-------|
| 1 | Per-HR distances → **top-5 ceiling** | Baseball Savant Statcast Search CSV | `savant.py` | `P(longest)` |
| 2 | Season **xHR** → P(HR) proxy | Savant HR leaderboard (embedded JSON) | `savant.py` | `P(HR)` fallback |
| 3 | Game **totals (O/U)** → park/weather carry | DraftKings | `totals.py` | environment (`PARKS`) |
| 4 | **DK anytime-HR odds** → real P(HR) + popularity | DraftKings | `dk_odds.py` | `P(HR)` + ownership |
| 5 | Live **entries** → true ownership | Fanatics board (manual, when posted) | `LIVE_ENTRIES` | payout split |

Input #4 is the sharpest: the de-vigged anytime-HR price is a better P(HR) than xHR, and
short odds are a pre-game popularity proxy (entries don't exist until games start).

## Run it

```bash
pip install -r requirements.txt
python3 run_today.py            # full ranked card + Under-Floor + Launchpad views
python3 run_today.py --refresh  # force a fresh Savant pull too
```

Individual fetchers also run standalone for debugging:

```bash
python3 savant.py        # refresh Savant distance + xHR caches (data/)
python3 dk_odds.py       # today's DK anytime-HR odds
python3 totals.py        # today's game totals -> per-team carry
```

## How the model works (`longball.py`)

- `load_distance_profile` → each hitter's `top5` / `max` HR distance from Statcast.
- `env_from_total(total)` → O/U into **carry feet** (`clamp((total-8.5)·1.8, ±9)`; gentled
  after a 13.5 total over-shot Sacramento on 6/13).
- `build_card(odds=…, parks=…, live_entries=…)` merges everything:
  - `ceil = top5 + park_carry`
  - **odds override**: when DK odds are present they replace the xHR-derived `P(HR)` with the
    de-vigged market probability and drive `est_entries` via the ownership curve.
  - `est_entries ≈ pool · k · implied_prob^α` (α>1 — the public over-concentrates on
    favorites). Live Fanatics entries override the estimate when known.
  - `payout_if_win = 50000 / entries`
  - `p_long = phr·w(ceil) / (field + Σ phr·w(ceil))`, `w(s)=exp((s-430)/τ)`
  - `EV = p_long · payout_if_win`
- `launchpad_stack(card)` → on outlier-environment days, the cheap high-ceiling bats in the
  single best game (basket the darts instead of sniping one bat).
- `under_floor(card)` → only bats whose split clears `MIN_PAYOUT_FLOOR` ($1000 → ≤50 entries).

Name joins across sources go through `names.norm_key` (accent-/suffix-/parenthetical-
insensitive), so DK's "Eugenio Suarez" / "Max Muncy (LAD)" match Savant's "Suárez, Eugenio".

## "Today's 3" button — Claude reasoning layer

`POST /api/pick3` (frontend at **`/longball.html`**) splits math from judgment:

- **The model does the math** (`pick3.py` → `build_card`): distances, P(HR), entries,
  payout, EV. Claude is never asked to compute these or recall stats.
- **Claude does the judgment** (`server.js`, model `claude-sonnet-4-6`): from the candidate
  pool (ceiling ≥445 AND clears the floor), it picks **3 players** — tie-breaking similar-EV
  bats, stacking a launchpad vs spreading darts, penalizing unconfirmed lineups — labels one
  `core` and the rest `dart`, and writes a one-line why + slate read.
- **Guardrails**: candidate data is sent as JSON ground truth; every returned name is
  verified against the pool (hallucinated names dropped, backfilled from top EV); a malformed
  Claude response falls back to the model's **top-3 by EV** so the button never dead-ends.
- The candidate pool is cached ~15 min so repeated clicks don't re-pull DK/Savant.

## Calibration (`calibration.json` + `boards/`)

`pool_size`, `entries_from_odds.{k,α}`, and the env params live in `calibration.json` and are
fit against real Fanatics boards (archived in `boards/`). Current anchors: Kurtz 435 entries
(6/12), Soderstrom 137 / Caballero 5 / Durán 1 (6/14). Refit as more boards land.

## Strategy rules the output encodes

1. **Ceiling gate** — only `top5 ≥ ~445` can realistically win a day (observed winning
   distances 6/8–6/14: 483, 446, 466, 445, 471, 454, 462 — median ~466; 470+ rarely required).
2. **Fade chalk even when it wins** — short-odds favorites pay ~$100–365. Skip them.
3. **$1K floor → ≤50 entries** — the default Under-Floor view.
4. **Target the intersection** — ceiling 445+ **AND** odds ~+350 to +700 (LIGHT/DART tiers).
5. **Stack outlier games** — when one total is extreme, the day's longest almost certainly
   comes from it but *which* bat is unknowable; spread several $5 darts across its cheap bats.
6. **Bet early** — entries climb through the day; lock while your guy is uncrowded.
7. **Stakes** — always the $5 minimum; more doesn't grow your share.

## Hard caveats

- **High-variance lottery, not a grinder.** A perfect pick wins single-digit % of days.
  Long dry stretches are variance, not a broken model.
- Payout is **FanCash**, not cash — discount accordingly.
- The model is strong at **right game / right distance band / dilution math** and inherently
  weak at predicting **which specific bat** squares one up (Soderstrom's 462 on 6/14 was a
  17-ft career outlier over his prior top-5 — unrankable). The fix is structural (stack +
  floor), not a better point pick.
- **Lineups are the #1 blind spot** — there is no lineup feed wired in; `lineup_confirmed` is
  `null` (unknown). Always confirm the bat is starting before betting.

## Files

```
longball.py        # the model: build_card, env, launchpad, floor (core)
savant.py          # Savant distances + xHR leaderboard -> data/ (cached daily)
dk_odds.py         # DraftKings anytime-HR odds {name: american}
totals.py          # DraftKings game O/U -> per-team carry (PARKS); team aliasing
names.py           # accent/suffix/paren-insensitive name matching
pick3.py           # candidate pool + slate context JSON for the button
run_today.py       # glue: fetch all -> print card + floor + stack
calibration.json   # pool size, ownership curve, env params, anchors
boards/            # archived Fanatics boards for calibration
public/longball.html  # "Today's 3" frontend
data/              # cached CSVs + JSON (gitignored, refreshed daily)
```
