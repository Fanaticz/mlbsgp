# boards/ — Fanatics leaderboard archive (calibration)

Drop dated Fanatics jackpot-board screenshots or CSVs here (e.g. `2026-06-14.png`,
`2026-06-14.csv`) recording **actual entries per player** once a board posts.

These are the ground truth for calibrating the ownership-from-odds curve in
`calibration.json` (`pool_size`, `entries_from_odds.k`, `entries_from_odds.alpha`).
Back out each player's pre-game anytime-HR odds, pair it with the observed entry count,
and refit `est_entries = pool_size · k · implied_prob^alpha`.

Known anchors already in `calibration.json`:

| Date  | Player           | Entries | Won | Notes                       |
|-------|------------------|---------|-----|-----------------------------|
| 6/12  | Nick Kurtz       | 435     | ✓   | longest 471 ft, paid ~$115  |
| 6/14  | Tyler Soderstrom | 137     | ✓   | longest 462 ft, paid ~$365  |
| 6/14  | Hunter Goodman   | 198     |     |                             |
| 6/14  | Noelvi Marte     | 15      |     |                             |
| 6/14  | José Caballero   | 5       |     | would've paid $10,000       |
| 6/14  | Rodolfo Durán    | 1       |     | would've paid the full $50k |

Files in this folder are archived inputs, not code — commit them so the calibration
history travels with the repo.
