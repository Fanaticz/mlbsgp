---
name: nba-sgp-fv
description: Fair value of an NBA same-player SGP (2+ legs of points, rebounds, assists, threes) from a bet-slip screenshot (Novig, Pikkit, a book) plus Vulture fair odds or a book's two-way price. Triggers on a slip screenshot with "FV?", "fair value", "price this", "calc FV", or "what r should I use". Reply with the four-line FV / EV% / Kelly Wager / QK block (quarter Kelly, $500 units).
---

# NBA same-player SGP fair value

## 1. Read the inputs

- **Slip:** player, legs and payout. Novig milestones: "26+ Points · Yes" =
  Over 25.5, "10+ Assists · No" = Under 9.5. The payout (Novig "3.80x", or
  American) is the price for EV and Kelly.
- **Leg odds, in order of preference:**
  1. The user's instruction for a leg ("for 2.5, use DK FV") → that book's
     Over/Under pair at that line (Pikkit shows both sides).
  2. Vulture sheet: the **Fair** column of the Over row and the Under row at
     the slip's line (layout: Date, League, Game, Market, Bet, Book, Odds,
     Limit, Sharp "Avg (n)", Sharp odds, **Fair**, Hold, ...; older sheets
     called it `avg_fv`).
  3. Slip line not posted → the nearest posted line's pair, shifted (`from`).
     Prefer a posted alt line when one exists.

## 2. Price it

```bash
python3 .claude/skills/nba-sgp-fv/price.py "Victor Wembanyama" \
  "pts over 25.5 odds +114 -113" \
  "tpm over 2.5 odds +150 -197" \
  "reb over 9.5 from 11.5 odds +115 -114" \
  --payout 6.58
```

Leg: `<pts|reb|ast|tpm> <over|under> <line> [from <posted line>] odds <over> [<under>]`.
Odds are always the posted line's **Over then Under** price, whichever side
the leg takes; the pair is normalized (strips a book's vig). One side only is
taken as fair: right for a Vulture Fair value (already devigged), wrong for a
raw one-way book price (alt overs like "4+ threes"). For those, shift from the
two-way main line with `from`, and use the one-way prices only as a check:
each book's implied % divided by (1 + that book's margin on the main two-way,
about 6.5–7.7% on props). Alts usually carry more margin than that, so the
check runs slightly high.

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
  QK = max(f, 0)/4 × 100 units (1u = 1% of bankroll); Kelly Wager = QK × $500
  (Max's unit, same as his MLB skills; `--unit` overrides). Negative EV shows
  $0.00 and 0.00u.
- **No payout given:** `FV = +229` only, then ask for the payout.
- No book-by-book comparison, no verdict: the user does the book part.
- Check: Lillard O20.5 points (Fair +101/−101) + O3.5 threes from the 2.5
  Fair (−142) at 3.80x → +229 / 15.5% / $692.03 / 1.38u.
- If asked "what r?": the plug-in r the script prints (2 legs) is what goes
  in a devig calculator (joint = pA·pB + r·√(pA(1−pA)·pB(1−pB))); the margin r
  is the copula input. Never put a margin r into that formula: it overstates
  the correlation by about 1.5x near the median.

## Method (what the script does)

- **Correlation:** margin r between the stat lines, within-season centered
  and recency-weighted, then shrunk (empirical Bayes) toward rotation players
  in a similar role. One player's r carries about 0.10 of sampling noise, as
  much as the real spread between players, so raw r's must not be used.
  Points pairs (PTS·REB, PTS·AST, PTS·3PM) come from
  `public/data/nba_correlations.json` (`<pair>.shrunk`); REB·AST, REB·3PM and
  AST·3PM are computed from the game logs the same way. An Over/Under mix
  flips the sign.
- **Joint:** Gaussian copula at each leg's probability. Two legs exact, three
  by integration (matches a 4M-draw simulation), four or more by Monte Carlo.
  Checked on PTS·3PM: across 254 player-seasons at book-style lines it
  predicted both overs 41.1% vs 41.05% actual.
- **Line shifts (`from`):** a normal fit through the posted line with the
  player's within-season SD. Rebounds, assists and threes average that with a
  negative binomial using the player's own dispersion (they diverge on small
  counts).

## Data freshness

`price.py` prints the data date. The daily GitHub workflow
(`refresh-data.yml`, 11:00 UTC) rebuilds it and rebases before pushing. This
session's GitHub access can't trigger workflows (403), so to refresh by hand:
`python3 scripts/nba_fetch_correlations.py --workers 16` (about 25 minutes,
ESPN is reachable from the container), check `generated_at` and the player
count, then commit and push `public/data/nba_correlations.json` to `main`.

## Related

- `nba-ast-pts-sgp`: Vulture `/run` commands and the Assists × Points
  Discord card. Its `sgp.py` holds the copula math this script imports.
- Dashboard `public/nba.html`: shows the plug-in r and prices 2-leg combos in
  each player's builder.
- Novig SGP multipliers can't be pulled automatically: the official API
  (docs.novig.com) has no parlays, and reverse-engineering the app is off the
  table.
