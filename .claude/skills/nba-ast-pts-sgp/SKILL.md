---
name: nba-ast-pts-sgp
description: NBA Assists x Points SGP workflow. Build the Vulture "twa" command for today's high-assist players with negative PTS-AST correlation, then price both opposite-direction combos (Ast Under + Pts Over, Ast Over + Pts Under) from the Vulture avg_fv screenshot. Triggers on "high assist players today", "vulture command", "calc SGP FVs" for NBA assists/points.
---

# NBA Assists x Points SGP

## 1. Pick players + Vulture command

```bash
python3 .claude/skills/nba-ast-pts-sgp/sgp.py players
```

Reads `public/data/nba_correlations.json` (refreshed daily; check
`generated_at` / `schedule_today.date` is today). Keeps players on today's
slate with >= 5 AST, >= 17 PTS, n >= 20, and shrunk PTS-AST margin r < 0,
sorted most negative first. Give the user two commands, one per market,
always starting with `/run` so they paste straight into Discord
(DraftKings only; splitting keeps Vulture's EV cutoff from dropping the
points lines):

```
/run command_name:twa markets:player assist bet_names:Nikola Jokic, Shai Gilgeous-Alexander, Jalen Brunson books:dk
```

```
/run command_name:twa markets:player points bet_names:Nikola Jokic, Shai Gilgeous-Alexander, Jalen Brunson books:dk
```

When re-pulling FVs for players already on the card, use the card's full
player list rather than re-running the picker.

## 2. Price the SGPs from the Vulture screenshot

The user pastes a table (columns: bet_name, odds, avg_odds, **avg_fv**, fbc,
ev ...). Use `avg_fv` for each side. Write a legs JSON in the scratchpad:

```json
{"Cade Cunningham": {"ast": {"line": 9.5, "over": 128, "under": -125},
                     "pts": {"line": 24.5, "over": 104, "under": -104}}}
```

Omit a side if the sheet doesn't show it (script uses the complement — say
so). Then:

```bash
python3 .claude/skills/nba-ast-pts-sgp/sgp.py fv <legs.json>
```

Math (`margin_r` / `joint` in sgp.py):
- **Margin r** = recency-weighted, season-centered Pearson PTS-AST r, shrunk
  (empirical Bayes) toward high-assist starters (>=4 AST, >=24 MPG, >=60 g;
  avg ~ +0.075). Per-player sampling noise (~0.10) is larger than the real
  spread between players (~0.08), so raw r's must not be used directly.
  Players picked for a negative raw r regress toward zero.
- Opposite-side combos use corr(AST, -PTS) = -margin r.
- **Joint** = Gaussian copula at the two legs' quantiles (Plackett integral).
  This is line-aware: the implied binary corr shrinks as lines move away
  from the median. Don't plug margin r into the phi formula
  (`r*sqrt(a(1-a)b(1-b)) + a*b`); that formula wants binary corr and
  overstates it ~1.5x near the median.
- Fair multiplier = 1/joint; EV of a slip = payout x joint - 1.

If Vulture has no DK points line (DK hanging an alt number), devig the
other books' main line (multiplicative, averaged) from the user's
Pikkit screenshots and mark it on the card.

## Output

One table, both directions side by side per player (combo, FV, fair
multiplier, r). If the user gave a slip (e.g. Novig 4.14x), state its EV.
List any player missing a points or assists FV so they can send it.
Show margin r and combo binary corr columns. Deliver as a PNG card (HTML + playwright screenshot) for Discord.
