# Novig PTS + 3PM SGP kit

Finds +EV same-player "Points Over + Threes Over" parlays on Novig. Fair
values come from Novig's own single-leg markets; the correlation (r) comes
from each player's game logs. Chrome only has to build slips and read the
multiplier.

## Files

| File | What it is |
|---|---|
| `scan.py` | Pulls Novig's live NBA prop books and prints the fair table. Python 3, no installs. |
| `pts3_r.json` | Each player's PTS-3PM correlation (margin r, shrunk), plus season PTS/3PM/MIN. |
| `SKILL.md` | The procedure for Claude in Chrome. |
| `fair_table.md` | Written by `scan.py` each run. |

## Setup (once)

1. Put this folder anywhere, e.g. `~/novig-kit`.
2. Open Claude (desktop app / Claude Code) in that folder with Claude in Chrome connected.
3. Optional: copy `SKILL.md` into `~/.claude/skills/novig-sgp-scan/SKILL.md` so
   "run novig-sgp-scan" works from anywhere.

## Each day

Say: **"run novig-sgp-scan"** (or paste SKILL.md). It will:

1. Read the dummy leg's fair win prob from Novig (Gonzaga / Alabama ML, whatever you name).
2. Run `python3 scan.py --min-tpm 2 --dummy <that prob>`.
3. Build each slip in Chrome, read the Parlays multiplier, keep the ones above `+5% x`.

## Keeping r fresh

`pts3_r.json` moves slowly (a few games change it a little). Refresh it about
weekly: download the latest from the `mlbsgp` repo (`novig-kit/pts3_r.json` on
`main`), or ask the cloud session to rebuild it.

## Notes

- Legs whose Novig book is wider than 4c are skipped, not guessed
  (`--max-spread 0.06` loosens it).
- `--alts` also prices one line up on each leg (PTS +1, 3PM +1).
- A 3PM line that forces the PTS line (3 threes = 9 points vs PTS 8.5) prices
  as just the 3PM leg; the table shows Devig r +1.000 for those.
- Devig r is what to type into the devig tool's Correlation box if you check
  one by hand.
