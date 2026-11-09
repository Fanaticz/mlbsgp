---
name: nba-pts3-daily
description: Daily Novig NBA Points + Threes SGP run. Step 1 gives Vulture /run commands for today's best PTS-3PM shooters; step 2 turns the Vulture sheet screenshots (plus a dummy-leg screenshot) into a Claude-in-Chrome handoff with Fair x / +5% x breakevens; step 3 prices the plays Chrome reports. Triggers on "run today", "today's slate", "points threes today", "round 2", or Vulture sheet screenshots of player points / made threes.
---

# Daily NBA Points + Threes run (Novig)

Same-player "Points Over + Threes Over" parlays on Novig. Fair values come
from the Vulture sheet's legs plus each player's shrunk PTS-3PM correlation;
Claude in Chrome builds the slips and reads Novig's multipliers.

Script: `.claude/skills/nba-pts3-daily/daily.py` (uses `nba-sgp-fv/price.py`
and `public/data/nba_correlations.json`; refresh notes are in `nba-sgp-fv`).

## Step 1: "run today" -> Vulture commands

```bash
python3 .claude/skills/nba-pts3-daily/daily.py slate
```

It lists every player with an open pregame NBA prop on Novig, averaging
1.8+ threes, ranked by PTS-3PM r, and prints the top 25 as `/run` commands
(13 names each, Overs only, `markets:player points, player made threes`,
`books:dk,fd`). Reply with the commands in code blocks and the ranked list.
Also ask for a screenshot of the dummy leg (a heavy college moneyline on
Novig, e.g. St. John's 99% / Iona 2%).

## Step 2: Vulture screenshots -> Chrome handoff

From each sheet, for every player take the **main line** of each market
(the line marked M by DK/FD) and its **Sharp odds** pair, Over then Under.
When a player has two main lines in a market (DK and FD mark different
lines), use both: one legs-file row per line, same player name repeated.
Never shift lines. If a market is missing from the sheet, use Novig's own main
line for it: `python3 .claude/skills/nba-sgp-fv/novig.py "<player>" <pts|tpm> <line>`
shows the ladder; pick the tight line (<= 4c) nearest 50/50 and write it with
`novig`. Skip a player if neither the sheet nor a tight Novig line has the leg.

Write a legs file in the scratchpad, one player per line:

```
Cade Cunningham | pts 24.5 -120 -109 | tpm 2.5 +109 -145
Davion Mitchell | pts 12.5 novig     | tpm 1.5 -145 +109
```

Dummy: pD = favorite % / (favorite % + dog %) from Novig's moneyline asks
(99 / (99 + 2) = 0.980).

```bash
python3 .claude/skills/nba-pts3-daily/daily.py handoff legs.txt \
  --dummy 0.980 --dummy-name "St. John's ML (vs Iona, CBB, 11 AM)"
```

Send the printed code block as is: it is the full handoff for Claude in
Chrome (search players by name, keep the dummy, table, grading, one play per
player, quarter-Kelly math at $250 units, report format). Under it, list the
script's Notes and any skipped players.

The script also prices every row from Novig's own legs at the same lines (one
catalog pull) and puts the higher Fair x of the two in the table, so a leg the
sheet has too rich can't make a play by itself. The Notes name each row Novig
lowered, each row with no tight Novig book to check against, each leg given
one price only (taken as fair: add the Under if it is a raw book price), and
each row skipped for a missing leg or an unreadable price. `--no-novig` turns
the check off.

## Step 3: Chrome's report

- For each PLAY, give the four-line block (FV / EV% / Kelly Wager / QK) in a
  code block. FV includes the dummy: P = 1 / Fair x.
- The table already carries the lower of the sheet's and Novig's fair, as of
  the handoff. If a play comes back above 20% EV long after the handoff, run
  the handoff again first: Novig's legs move, and the multiplier follows them.
- One play per player: two rows of one player win and lose together, so only
  the higher-EV one is bet.
- Sizing: quarter Kelly, 1u = $250, no cap.
- Round 2 (if round 1 hit often): `daily.py slate --round 2`, then step 2
  again.
- Share card: on request, render a PNG (Player · Legs · Fair · Novig · EV ·
  QK · Wager, total row) with Playwright into `share/nba-sgps-<date>.png`.

## Rules

- Prices are American odds or x multipliers, never percentages; EV% is the
  only percentage.
- Main lines only (both when DK and FD differ); no shifted lines.
- A slip without the dummy leg is compared to Fair x times pD.
- A heavier NBA moneyline is not a better dummy: Novig's vig on it costs more
  than the boost (Celtics -541 turned a 29.6% EV slip into 22.7%).
