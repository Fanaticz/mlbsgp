---
name: novig-tennis-scan
description: Scan Novig's tennis matches for +EV same-match parlays of the game spread with the total games (and the moneyline with the total), priced against a tennis score model fitted to Novig's own lines. Triggers on "tennis plays", "scan tennis", "any tennis on Novig", "check tennis".
---

# Novig tennis scan

Never place a bet. Build nothing in the app: the script asks Novig's keyless
quote and prints rows.

## Run it

    python3 .claude/skills/novig-tennis-scan/tennis.py              # every open match
    python3 .claude/skills/novig-tennis-scan/tennis.py Alcaraz      # one match
    python3 .claude/skills/novig-tennis-scan/tennis.py --all        # every row, not only above fair

About two minutes for a dozen matches. It reads Novig's catalog, fits the
model to each best-of-three singles match with tight books (4c or inside) on
the moneyline, a total and a game spread, asks the four main-line slips of
each match once, then the lines one either side for any match with a slip at
-3% or better (`--grid-ev`).

## What it asks

- Underdog + games with the Over; favourite - games with the Under.
- Favourite moneyline with the Under; underdog moneyline with the Over.

These legs nearly imply each other (a straight-sets match of 22+ games is
never won by five), so the fair value is far above the product of the legs.
Most of Novig's pricers price that correctly and the slip loses to the fee:
200 slips on 24 matches 11-20 had a median of -21%, and moneyline + total
slips sat at -4% to -9%. The play is the match where a pricer prices the
pair as loosely related. Seen once so far: Alcaraz v Cobolli (ATP Finals,
11-20), Cobolli +4.5 + Over 21.5 at 3.02x against a fair +159, with three
more slips of that match above fair. A second pass the same evening (11
Challenger matches, 68 slips) had none.

Not worth asking (11-20): anything with a sets market (set spread, total
sets: -10% to -60%), the "wrong way" pairs (underdog + games with the Under),
and UFC (moneyline + goes the distance pays less than Pinnacle's straight
"wins by decision" on every fight).

## Reading a row

Fair is the careful end of the model's range and "to" the other end; EV, QK
and Wager are on the careful end. QK is quarter Kelly, $250 a unit.

Before calling a row a play:
1. The match is best of three with tiebreak sets (the script skips a total
   of 30+ as best of five; it can't see a deciding match tiebreak).
2. Both legs' lines are still where the row has them.
3. Two slips of one match that share a leg are one bet: give the best.
4. The model was checked on 36,435 ATP tour matches (11-20,
   `scripts/tennis_model_check.py`, `public/data/tennis_model_check.json`):
   game spread + total slips within 3% of the counted hit rate on average,
   underdog moneyline + Over 5% to 8% too high against 70%+ favourites. The
   script already cuts the fair value where the model ran high. Not covered:
   Challengers and the WTA (most of what Novig lists), and the favourite in
   the check comes from an Elo rating, not a price. Say that with any play.

## Asking Novig

One ask a slip. On 11-20 a slip asked again inside about a minute often came
back lower (WYO ML + Under 37.5: 7.54x rested, 6.27x on a quick second ask),
and the scanner's ask does the same to the app. So: don't re-ask a row to
"confirm" it, and tell Max to leave the slip alone about 90 seconds after
the scan before building it. The quote is before the parlay fee;
`novig.slip_multiplier` (the nba-sgp-fv skill) turns it into what the slip pays.

## Reply

No plays: one line (matches, slips priced, best EV) and stop.

Plays: a table, best first,

    Match | Start (CT) | Legs | Novig | Fair | EV | QK $

then for the best row of each match the four-line block and its app link
(the script prints the link):

    FV = +159
    EV% = 16.7%
    Kelly Wager = $518
    QK=2.07u
