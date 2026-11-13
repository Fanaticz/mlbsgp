---
name: nba-sgp-fv
description: Fair value of an NBA same-player SGP (2+ legs of points, rebounds, assists, threes) from a bet-slip screenshot (Novig, Pikkit, a book), with leg fair values pulled live from Novig's exchange, or taken from Vulture fair odds or a book's two-way price. Triggers on a slip screenshot with "FV?", "fair value", "price this", "calc FV", or "what r should I use". Reply with the four-line FV / EV% / Kelly Wager / QK block (quarter Kelly, $250 units).
---

# NBA same-player SGP fair value

## 1. Read the inputs

- **Slip:** player, legs and payout (no slip, legs only → `--payout novig`,
  see Related).
- **Pikkit's Novig price is not what Novig pays.** Pikkit shows Novig's raw
  parlay quote; the slip pays that after Novig's 10% parlay fee (+359 on
  Pikkit is 4.25x on the slip). For a Novig price read off Pikkit, add
  `--before-fee`. A Novig slip's own multiplier, and other books' prices on
  Pikkit, are used as shown. Novig milestones: "26+ Points · Yes" =
  Over 25.5, "10+ Assists · No" = Under 9.5. The payout (Novig "3.80x", or
  American) is the price for EV and Kelly.
- **Leg odds, in order of preference:**
  1. The user's instruction for a leg ("for 2.5, use DK FV") → that book's
     Over/Under pair at that line (Pikkit shows both sides).
  2. Vulture sheet: the **Fair** column of the Over row and the Under row at
     the slip's line (layout: Date, League, Game, Market, Bet, Book, Odds,
     Limit, Sharp "Avg (n)", Sharp odds, **Fair**, Hold, ...; older sheets
     called it `avg_fv`).
  3. No sheet, or the user says "novig" → `odds novig`: the script pulls
     Novig's exchange price at the slip's line (see "Novig" below).
  4. Slip line not posted → the nearest posted line's pair, shifted (`from`).
     Prefer a posted alt line when one exists. `odds novig` does this by
     itself when Novig's line is missing or too wide.

## 2. Price it

```bash
python3 .claude/skills/nba-sgp-fv/price.py "Victor Wembanyama" \
  "pts over 25.5 odds +114 -113" \
  "tpm over 2.5 odds +150 -197" \
  "reb over 9.5 from 11.5 odds +115 -114" \
  --payout 6.58
```

Leg: `<pts|reb|ast|tpm> <over|under> <line> [from <posted line>] odds <over> [<under>]`,
or `... odds novig` (just `novig` works) to pull the leg from Novig:

```bash
python3 .claude/skills/nba-sgp-fv/price.py "Deni Avdija" \
  "pts over 22.5 novig" "reb over 6.5 novig" --payout 3.20
```

A team or game total rides along as a score leg: `op` = the opponent's team
total (DK's "Team Total - IND" on a BKN player), `tm` = his team's total,
`tot` = the game total, e.g. `"op under 116.5 odds -107 -109"`. Vulture's
player sheet doesn't carry them: take Pinnacle's two-way price
(`python3 dk_api.py pinnacle-nba-props` prints each game's total and team
totals) and name it in the trailing line.

Odds are always the posted line's **Over then Under** price, whichever side
the leg takes. With both, each side is the **worst case** (lowest
probability) of the multiplicative, additive, power and Shin devigs, as
Vulture's Fair column does: a book's +132/−173 prices an Over at +153 and an
Under at −147, so the two don't mirror. A pair already at or under 100%
(Vulture's own Fair pair) is used as is. One side only is taken as fair: right for a Vulture Fair value (already devigged), wrong for a
raw one-way book price (alt overs like "4+ threes"). For those, shift from the
two-way main line with `from`, and use the one-way prices only as a check:
each book's implied % divided by (1 + that book's margin on the main two-way,
about 6.5–7.7% on props). Alts usually carry more margin than that, so the
check runs slightly high.

## Novig

`novig.py` reads Novig's public catalog (`GET /v3/public/catalog/markets`,
official API, no key, throttled per IP), open pregame NBA markets only.
The Over ask is 1 − the Under bid, so the two sides' asks are a two-way price
whose vig is the spread; each side's fair is its worst-case devig (above),
a hair under the mid on a tight book. The app
shows asks (Avdija O14.5 91% / U14.5 15% = 106%), so never read a fair
value off the app's percentages. Pregame game markets charge no taker fee.

- The price is only as good as the book: main lines run 0.5–2¢ wide, alts
  wider, and some are junk (Sabonis 18.5 pts 0.21/0.48, out of order with
  19.5). A line wider than 4¢ (`--novig-spread 0.04`) is never priced from:
  the leg shifts from the nearest tight line instead, and the script says so.
  Mention that leg in the trailing line, like any `from` leg.
- No tight line for a stat → the script stops. Look at the ladder and pass
  odds by hand:
  `python3 .claude/skills/nba-sgp-fv/novig.py "Domantas Sabonis" ast 9.5`
  (one row per line: bid, ask, mid, fair Over/Under American, spread, volume).
- Live games (`OPEN_INGAME`) are left out on purpose: those books move
  every possession and do carry a fee.

## 3. Reply: this block, every time

```
FV = +229
EV% = 15.5%
Kelly Wager = $692.03
QK=1.38u
```

- Send it in a code block so the four lines stay separate. Nothing else,
  except one short trailing line when a leg was estimated (`from` used, or
  one side only), naming the leg.
- **EV%** = p × decimal − 1, where p is the probability of the FV as shown,
  so the block checks by hand.
- **Kelly:** quarter Kelly at p, f = (p·b − (1−p))/b with b = decimal − 1.
  QK = max(f, 0)/4 × 100 units (1u = 1% of bankroll); Kelly Wager = QK × $250
  (Max's unit, same as his MLB skills; `--unit` overrides). Negative EV shows
  $0.00 and 0.00u.
- **No payout given:** `FV = +229` only, then ask for the payout.
- No book-by-book comparison, no verdict: the user does the book part.
- Always quote leg prices, fair values and comparisons as American odds
  (+113, -108), never as percentages. EV% is the only percentage.
- Check: Lillard O20.5 points (Fair +101/−101) + O3.5 threes from the 2.5
  Fair (−142) at 3.80x → +238 / 12.4% / $277.37 / 1.11u on the 11-11 data
  (r drifts a little with each daily refresh).
- For any number of legs (3-leg PTS·3PM·REB included), the script prints a
  `devig tool:` line: paste its Leg Odds into Leg Odds and its
  `<FV>=<legs>` string into the Correlation box. The tool derives its own r
  from that and returns our FV exactly. Give this when asked for a 3-leg r.
- If asked "what r?": give the **devig r** the script prints (2 legs). It is
  what goes in the devig tool's Correlation box, which scales r to the most
  overlap the legs allow: joint = pA·pB + r·(min(pA, pB) − pA·pB). The
  plug-in r is for the phi formula, joint = pA·pB + r·√(pA(1−pA)·pB(1−pB));
  typed into the devig tool it understates the joint (e.g. 0.443 there gives
  28.8% where the copula says 30.4%). The margin r is the copula input and
  goes in neither formula.

## Method (what the script does)

- **Correlation:** margin r between the stat lines over every game played
  (short-minute games count: the props are action in them), within-season
  centered and recency-weighted, then shrunk (empirical Bayes) toward
  rotation players in a similar role: minutes and rebound volume for PTS·REB
  (bigs run higher than guards at equal minutes), minutes for PTS·AST and
  REB·AST (all three move together mostly through minutes); 3PM or REB
  volume for the threes pairs. One player's r carries about 0.10 of sampling noise, as
  much as the real spread between players, so raw r's must not be used.
  Points pairs (PTS·REB, PTS·AST, PTS·3PM) and the score-REB pairs
  (TOT·REB, TM·REB, OPP·REB) come from `public/data/nba_correlations.json`
  (`<pair>.shrunk`); REB·AST, REB·3PM, AST·3PM and points, assists or threes
  against a score are computed from the game logs the same way (score pairs
  binned on minutes). An Over/Under mix flips the sign.
- **Joint:** Gaussian copula at each leg's probability. Two legs exact, three
  by integration (matches a 4M-draw simulation), four or more by Monte Carlo.
  Checked on PTS·3PM: across 254 player-seasons at book-style lines it
  predicted both overs 41.1% vs 41.05% actual.
- **Line shifts (`from`):** the leg is fitted through the posted line and
  read off at the slip's line. Above the posted line (a one-way milestone
  like 30+ against a 22.5 main) it is a negative binomial with the player's
  own dispersion; points keep a fifth of the normal fit. Below it, points
  use the normal with his within-season SD and rebounds, assists and threes
  average the two. Study of 11-11 (about 30k player-games a stat, prior games
  only): the normal alone gave 54% of the real hit rate on points at main +
  12 and 36% on threes at + 3, the count model 96-112%; both-legs rates on
  the ladder went from 52-80% of actual to 81-101%. DK's and FanDuel's
  one-way ladders agree (their price over this fair is their margin: 6% near
  the main, 30-45% on long shots). One player's shift still carries noise, so
  a shifted `novig` leg is held inside Novig's own ladder: no higher than the
  lowest ask at that line or below, no lower than the highest bid at that
  line or above (a one-way line gives one of the two; the note says when it
  bit). Score legs shift with the normal.
- **FanDuel ceiling (`books.py`):** every shifted box-stat leg is also
  checked against FanDuel's one-way Over on its exact line, pulled live
  (kept 4 minutes). The leg can't sit above that price with the least margin
  FanDuel charges taken out (measured against Novig's tight lines: 1.00 to
  1.02, 1.05 under 15%). The leg's line in the output ends with the price
  (`FD +600`) and says when it capped it. DraftKings is not asked for NBA:
  its pull never worked (removed 11-13); NFL still asks both books.
  On the 11-11 slate, with DK too, that bit on 230 of 1,106 shifted legs, cutting them a
  median 7%. `--no-books` turns it off; a book that can't be reached is left
  out. `python3 .claude/skills/nba-sgp-fv/books.py "Player" [stat [line]]`
  prints the ladder with "about" (usual margin out) and "no shorter than"
  (least margin out) fairs. One-way prices are never a fair value by
  themselves and never raise a leg.

## Data freshness

`price.py` prints the data date. The daily GitHub workflow
(`refresh-data.yml`, 11:00 UTC) rebuilds it and rebases before pushing. This
session's GitHub access can't trigger workflows (403), so to refresh by hand:
`python3 scripts/nba_fetch_correlations.py --workers 16` (about 25 minutes,
ESPN is reachable from the container), check `generated_at` and the player
count, then commit and push `public/data/nba_correlations.json` to `main`.

## Slate scan

**Default scope is main lines only** (Max, 11-10): NBA asks one slip a
player, his main-line Points + Threes, and NFL asks no three-leg slips. Every
quote is an auction every Novig pricer sees, and plays were being repriced
while the wider scans ran. Everything below about higher lines, other pairs,
double- and triple-doubles and three legs needs `--scope all`, which Max has
asked not to run on his board; use it only if he asks.

`--scope ladder` (the page's **Ladder** tab) is the one wider scan Max runs
(asked for 11-11): only shooters with PTS·3PM r at least 0.70 (43 on the
11-11 slate). The main-line slips are not asked or shown here (the NBA tab
has them; showing both was all overlap), so there is no gate: every higher
points line Novig lists to main + 15 with threes
at main to + 3, one-way lines included (`--ladder-pts`, `--ladder-3s`). Those
legs are shifted from the main line and capped by Novig's ask and by
FanDuel's one-way price (Method). Ungated pass of 11-11 (518 quotes, 10
minutes): 81 ladder slips at +10% or better, 31 on the 11 players whose main
line was above fair, 46 on the 21 at -10% to 0%, 4 on the 10 under -10%;
hence the -10% gate. The big ones are far lines (25+ points with 4+ to 6+
threes at 20x to 50x), which Novig prices close to unrelated legs.
Max (11-11) doesn't trust fairs that long: the scope now asks only ladder
slips whose fair is +500 to +800 (`--ladder-fair 500 800`; `0 0` asks every
slip). In that band the 11-11 pass had 61 slips, 8 above fair and 3 at +10%
or better (Pritchard 25+ / 3+ at 11.31x against +640, Curry 27+ / 7+ and
26+ / 7+); most of the +10% slips were at +1200 and longer.

**Star three-leg slips** (Max, 11-12) ride on every NBA pass except the
ladder: for `STARS` in scan.py (Doncic, Curry, Wembanyama, Gilgeous-Alexander,
Jerome, Tatum, Jokic) and anyone whose points main line is `--star-pts`
(26.5) or higher, every three of points, rebounds, assists and threes, all
Overs at main lines: four slips a player, 32 quotes on the 11-11 slate. Not
gated. `--no-stars` skips them; add a name to `STARS` to add a player.

`python3 .claude/skills/nba-sgp-fv/scan.py` prices every open pregame
player's same-player 2-leg combos (fair from Novig's legs, as `odds novig`)
against Novig's slip price and prints them best EV first: Points + Threes
Overs first, then Over + Over on the other pairs (r at least 0.15), then
(Points + Rebounds for big men only: centres and forwards averaging 9.5+
rebounds; Points + Assists is not asked at all and nothing is asked Over +
Under, Max's cuts of 11-10), then three legs: the best 12 two-leg
Over rows (-6% EV or better) with each other stat's main-line Over added
(`--tri 0` turns that off). `--tier 1` is Points + Threes only,
`--min-ev 3` trims the table, `--max-spread 0.08` lets in wide books (rows
marked ~, rough). About one quote a second. Under + Under is never asked:
Novig rejects it for one player. A row is a lead: quotes move a few percent
between asks, so reprice the slip (and check sharp odds) before a bet.
Higher lines ("the ladder", rows marked *): for shooters with r at least
0.70 the scan also asks every higher points line Novig lists (to main + 10)
with threes at main, +1 and +2. Those fairs are modelled: legs shifted from
the main line as `from` does, then the usual copula joint. Checked against
other books 11-10 on McCain: 14+ PTS / 3+ 3PM plain model +218 vs Fanatics
+195; 15+ / 3+ plain model +226 vs Fanatics +210, FD +207, DK +206, so the
model sits about 6% longer than the books, as a fair value should.
(Those were priced before 11-11, when shifted legs got the fatter upper
tail described under Method; ladder fairs are shorter since.)
`--ladder-fix` scales the joint by a game-log tail correction (`LADDER_FIX`,
x1.00 to x1.28) measured on the old shift; leave it off, the legs carry the
tail now.
The main-line Points + Threes quotes go first and gate the rest (`--gate`,
0%): a player whose best one isn't above fair gets nothing else asked, no
ladder, other pairs, double-doubles or three-leg slips, to keep the number
of auctions down. Players with no Points + Threes price are not gated. A shifted leg is capped at Novig's own ask on that line (a seller there means
the true chance is lower). Still model fairs: confirm a ladder play against other books' SGP price or
Vulture before sizing.

Triple-doubles (10+ REB · 10+ AST with points at the lowest line from 10+
and the next two up) are asked for players whose rebounds and assists main
lines are both 5.5+. Rebounds + Assists at main lines is not asked.
Build-your-own double-doubles (10+ with 10+ on points, rebounds, assists;
`--no-dd` skips them) ride at the end of the NBA pass, modelled like the
ladder. First test 11-10: 2 of 34 above fair, and Novig prices them in line
with its own DOUBLE_DOUBLE market, so expect little.

`--league nfl --scope ladder` (the page's **NFL Ladder** tab, 11-11): each
player's yards lines above his main line (receiving, rushing, passing;
one-way lines included) with anytime TD, receptions or passing TDs at its own
main line, kept to slips with a fair of +500 to +800 (about 195 on a
Wednesday board, 3 to 4 minutes). The yards leg is Novig's own book where
that line is tight, else shifted from the main line by `nfl_shift.py`: a
gamma through the main line at the spread DK's and FanDuel's own ladders
imply (CV 1.07 at an 8-yard receiving line down to 0.52 at 85; rushing 0.93
to 0.46; passing about 0.3), with 15% of the normal above the line. The main
line is Novig's when it has a tight one within 15 points of even money, else
DK's or FanDuel's two-way line (`books.py`, which also caps the leg at both
books' one-way price). Game logs: the normal gave 60-71% of the real hit
rate at twice the main line, the gamma 95-126%. Not gated, and r is the
player's shrunk copula r, fitted at median lines. No real pass had been run
when this was written: check the first plays against another book.

`--kind team` (NBA) is the NBA Team board: a player's main-line Over with
his game's spread on the side that goes with it (and his Under with the
other side), priced at the fitted r less one standard error, then six slips
across each game's own lines.
The r is league-wide for a player with that line on a team with tonight's
spread, from `public/data/nba_line_correlations.json`
(`scripts/nba_line_correlations.py`: four seasons of box scores against
closing lines). The plays are prop + spread in lopsided games; see scan.py's
docstring for what was tested.

`--league nfl` scans NFL instead: Over + Over on Receptions·Yards,
Receptions·TD and Yards·TD (TD = Novig's TOUCHDOWNS 0.5, any touchdown) for
the WRs, TEs and RBs in `public/data/nfl_correlations.json`, then the three
together. No rushing props (no r for them). NFL books are thin until late in
the week.
The same pass asks QB + receiver stacks and a prop with a game line (the
total, spread, moneyline, team total, and the first half's total, spread and
moneyline), from the role r's in `public/data/nfl_stack_correlations.json`.
It ends with three-leg slips (`--kind tri` asks those alone): three of a player's props, two with a game line, QB + receiver + a
game line, or three props across the two.
`--league cfb` asks college football slips across one game's lines (Novig
lists no college player props): underdog moneyline + Under, spread + total, team-total Unders, first half + game.
Fair values are modelled per game; see scan.py's docstring.
`--league cbb` is the same for college basketball: spread + total only.
`--league soccer` prices Max's corners shape (favourite 3-way win +
favourite corners Under + underdog corners Over, with and without goals Over
1.5 / 2.5) on every open match with team-corners books. Each leg's fair
value is Pinnacle's no-vig price on that line (`pinnacle.py`, two calls for
the whole board; `python3 pinnacle.py Albania` prints one match), or the
middle of Novig's own book where Pinnacle has no such line (row marked ~ if
that book is wide). Corner lines Pinnacle prices are preferred. Fair = the legs'
product x a measured lift (`SOCCER_LIFT` in scan.py: x1.25 to x1.61 from
17,934 top-five-league matches, football-data.co.uk). Checks: 11-06 Venezia
with Over 2.5 paid 17.24x on Novig (other books 8.2x to 9.9x) against about
13.9x fair for that kind of match; with Over 1.5 it paid 13.45x against
about 10.8x.
The dashboard's Scanner page (`public/nba_scan.html`, `/api/nba/novig-scan`
in `server.js`) runs the same script on the server, one pass each time
Fetch is pressed and never by itself: every quote is a live auction sent to
all of Novig's pricers, so repeated scans show them what is being watched.
**My bets** on the page: open a row, type the stake (the price defaults to
Novig's multiplier) and Save. The strip above the board lists each player
with his total, and rows carry a green badge. Kept on the server
(`/api/nba/novig-bets`, `novig_bets.json` beside the saved boards), so phone
and desktop match; a bet shows until about five hours after tip. "Hide my
bets" hides all of it on that device, for a screenshot.
It is private: the route needs the passcode in the server's `NOVIG_SCAN_KEY`
(no key set = scanner off), and the NOVIG SCAN tab only shows on a device
that has entered it (five taps on the EVC label opens the passcode box).

Teammate combos are not scanned, on purpose (checked 11-10, 40 live quotes):
Novig prices cross-player parlays 10 to 25% under fair in every direction
(assist Over + teammate scoring Over or Under, star points Under + teammate
points Over), more than our teammate correlations (shrunk phi at most 0.15)
can ever make back.

## Related

- `nba-ast-pts-sgp`: Vulture `/run` commands and the Assists × Points
  Discord card. Its `sgp.py` holds the copula math this script imports.
- Dashboard `public/nba.html`: shows the plug-in r and devig r and prices
  2-leg combos in each player's builder (Fetch FV fills Novig's leg fairs;
  the slip price is typed in: Novig's own prices live on the private Scanner).
- Novig's SGP price (the slip payout) can be pulled: `--payout novig` asks
  Novig's keyless parlay quote (`POST /rfq/v2/quote/unauthenticated`,
  docs.novig.com/affiliates/parlay-pricing) for the legs' own lines, takes
  Novig's parlay fee off it (fee = 0.10 × stake × (1 − quote), so slip x =
  1 / (quote × (1 + 0.10 × (1 − quote))); `novig.slip_multiplier`) and prints
  `Novig pays 2.56x (+156): its 2.75x quote after the 10% parlay fee` above
  the block. Checked 11-09 on Tatum U26.5 points + O7.5 assists: quote
  0.218, slip 4.25x. Player-stat legs posted
  on Novig only; a score leg, an unposted line or a 404 ("no price right
  now") stops with "pass the payout by hand". The quote lasts about 30
  seconds and the limit is a 10-request burst per IP, then 1 a second. A
  payout on the user's slip always wins over the quote.
