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
slate with >= 5 AST, >= 17 PTS, n >= 20, and weighted PTS-AST r < 0, sorted
most negative first. Give the user the names comma-separated, and the
command in exactly this form (user's Vulture command, DraftKings only):

```
command_name:twa markets:player assist, player points bet_names:Nikola Jokic, Shai Gilgeous-Alexander, Jalen Brunson, Donovan Mitchell, Jamal Murray, Cade Cunningham, Stephen Curry, Trae Young, James Harden, Luka Doncic, Dejounte Murray books:dk
```

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

Math: correlation for both opposite combos = -(weighted PTS-AST r).
Joint = r*sqrt(a(1-a)b(1-b)) + a*b (binary phi, same as `jointFromPhi` in
`public/utils/nbaEvTab.js`). Fair multiplier = 1/joint; EV of a slip =
payout x joint - 1.

## Output

One table, both directions side by side per player (combo, FV, fair
multiplier, r). If the user gave a slip (e.g. Novig 4.14x), state its EV.
List any player missing a points or assists FV so they can send it.
None of these r's are individually significant — mention that briefly.
