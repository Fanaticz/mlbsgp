---
name: novig-sgp-scan
description: Scan Novig for +EV NBA same-player Points Over + Threes Over parlays. Runs scan.py for fair values (Novig legs + player PTS-3PM correlation), then builds each slip in Chrome and compares the Parlays multiplier. Triggers on "run novig-sgp-scan", "scan novig SGPs", "find points threes plays".
---

# Novig PTS + 3PM SGP scan

Never place a bet or type an amount. Only build slips and read multipliers.

## 1. Dummy leg

Use the dummy the user names (default: a heavy college-basketball ML such
as Gonzaga or Alabama). On Novig's game page read both moneyline asks
(e.g. 97% / 4%). pD = Fav / (Fav + Dog). Re-read every 15 minutes.
Add the dummy to the slip once and keep it there for every combo. It must
stay in every slip: the Fair x / +5% x columns already include it, so a slip
without it would be compared against the wrong breakeven.

## 2. Fair table

From the kit folder:

    python3 scan.py --min-tpm 2 --dummy <pD>

It writes `fair_table.md`. Players can have two rows: threes at the
milestone just under even money (3+ at -130) and the next one up (4+ at +140).
Check both. A "~6c" after the legs means that threes line comes from a wider
Novig book: still a play if it clears +5% x, but say "rough" in the report.
Each row: Player, Legs (e.g. 21+ PTS / 3+ 3PM),
leg fairs, Fair odds (NBA legs only), Fair x and +5% x (already divided by pD,
so compare straight to the slip's multiplier), Devig r.

## 3. Build and compare (top to bottom)

For each row:
1. Type the player's name into Novig's search bar (much faster than opening
   the game page), then add "<N>+ Points · Yes" and "<M>+ Three Pointers
   Made · Yes" from his props.
2. Read the multiplier M on the Order Slip, Parlays tab (it includes the dummy).
3. M >= +5% x -> play. Fair x <= M < +5% x -> thin, list it. Below Fair x -> pass.
4. Remove only the two NBA legs (keep the dummy) and go to the next row.
Skip games that have started.

## 4. Math for plays

    P   = 1 / Fair x                       (win prob of the whole slip incl. dummy)
    EV% = (M x P - 1) x 100
    b   = M - 1
    QK  = max(0, (P*b - (1-P)) / b) / 4 x 100   units (quarter Kelly)
    $   = QK x 250
    FV  = fair American odds of P

## 5. Report

Table, highest EV first, prices as American odds (never percentages except EV%):

    Player | Legs | M | Fair x | EV% | QK u | $

Then, for each row with EV >= 5%, the four-line block:

    FV = +xxx
    EV% = x.x%
    Kelly Wager = $x
    QK=x.xxu

Then list anything new you learned about Novig's UI, and add it to the
"UI notes" section below so the next run is faster.

## UI notes

- Fastest route: search bar > player name > his props. Fallback: NBA > game > Player Props; Points and Three Pointers Made are separate sections.
- "25+ Points · Yes" = Over 24.5; "3+ Three Pointers Made · Yes" = Over 2.5.
- The multiplier ("3.83x") is top right of the Parlays tab.
