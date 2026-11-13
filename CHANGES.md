# Changes

## 2026-11-13 session

### Novig Scan: CBB board on measured correlations (three seasons)
The CBB board's correlations were modelled from each game's alt ladders. They are now measured: how often the two legs of each slip shape hit together, on 17,319 games.

- **Data** (`scripts/cbb_line_correlations.py --fetch 2024 2025 2026`; `public/data/cbb_game_lines.json`): every Division I final of 2023-24, 2024-25 and 2025-26 from ESPN's scoreboard, with halftime scores, and DraftKings' closing spread and total from ESPN's odds feed (one call a game; 17,342 of 18,835 games have a line). Posted team totals and first-half spreads aren't in the feed: a team's total is (total -/+ spread) / 2, the first-half spread 0.546 x the spread (the fitted slope).
- **What was measured** (`public/data/cbb_line_correlations.json`): for each shape, overall and in four spread bands (under 6, 6 to 12, 12 to 20, 20+), the share of games both legs hit and the Gaussian-copula r that reproduces it. The board (`cfb_candidates`, `--league cbb`) takes the r for the game's spread band (the all-games r under 400 games) and applies it to each leg's real price; the detail line shows the games behind it. A shape not in the file keeps the model's r, as does CFB.

| Shape | Both hit | r measured | r the model used |
|---|---|---|---|
| Underdog covers + his team total Under | 14.4% (± 0.3) | -0.61 (20+ spreads -0.55) | about -0.56 |
| Favourite's team total Under + game Under | 40.2% | +0.83 | about +0.80 |
| Both team totals Under | 30.1% | +0.37 (0.29 to 0.41 by band) | 0.22 to 0.38 |
| First-half spread + game spread | 35.1% | +0.63 | +0.71 |
| Spread + total, same way | 24.1% to 24.6% | -0.04 (20+ spreads +0.14) | 0.00 to 0.11 |

- **Effect**: the underdog shape's fair values get about 4% longer (two even-money legs: +586, where the model said about +560), and the first-half shape about 5% longer. On a 36-quote pass the underdog rows that had shown +13% to +27% came back +3% to +9%.
- **A mistake corrected**: the first cut of this (one season, 2,135 games) converted hit rates to r with `sgp.devig_r`, which is the devig tool's own scale, about two thirds of the copula r. It reported -0.43 for the underdog shape and +460 at even legs, and called the model conservative and the team total Under + Under shape 12% too generous. Both were wrong: on the right scale that season is -0.61 too, and Under + Under is +0.83. The script solves `sgp.joint` for r directly.
- Still not measured: posted team-total lines (the board's Pinnacle leg), and other books' closers.

### Novig Scan: CBB underdog slip is two legs
The three-leg slip (underdog's spread + Under + underdog's team total Under) had a leg that adds nothing: Tennessee State +27.5 with its team total Under 63.5 caps the game at 154, under the 157.5 total. DraftKings refuses the third leg for that reason, and Novig quoted it at its two-leg price. The board now asks the two legs alone. Its correlation is now measured: see the entry above.

### Novig Scan: CBB team totals and first half, priced off Pinnacle
- **Why**: the CBB board could not ask a team-total or first-half slip, because Novig's own books on those are 6c to 28c wide. Pinnacle posts both for college basketball (three team-total lines a team, a first-half spread and total ladder, first-half team totals and moneyline).
- **`pinnacle.lines(league)`** (new; `NCAAB` 493, `NCAAF` 880): every pregame game's two-way lines for the game and the first half, alt lines included, devigged worst case. Two calls a pass. `college_match` pairs a game with Novig's by tip time (10 min) and both names (Novig's short code or the full name from its team-total market): 50 of 55 games matched tonight.
- **The board now asks up to six slips a game** (296 on tonight's 55 games, about five minutes): the two spread + total slips as before, then the underdog's spread + Under + the underdog's team total Under, the favourite's team total Under + Under, both team totals Under, and the favourite's first-half spread + his spread. A team-total or first-half leg is priced only where Pinnacle has that exact line. Open a row to see "Pinnacle -114, Novig's book says -124".
- **Tested first on 106 quotes over four games** (Georgia at UNC, Georgetown at Clemson, Pitt at Butler, Tennessee State at Tennessee), 27 shapes: 5 above fair, median -9.5%. Four of the five were Under slips in Pitt at Butler, where Novig priced every Over pairing rich and every Under pairing cheap (its pricers had the total higher than its own book), so that is a line that moved, not a correlation Novig misprices. The four shapes kept are the best by median: -1.7% (underdog spread + Under + his team total Under), -5.9% (first-half spread + spread), -7.2% and -8.0%. A team's total Over with the other's Under ran -18% to -20%.
- **Model**: a first-half leg is half the game (half the variance, the halves unrelated), which gives 0.71 between a first-half spread and the game's; Novig's quotes implied 0.68 to 0.82. A team total with the game total is about 0.8, the two team totals 0.2 to 0.4 with each other.
- CFB is unchanged: Novig's own team-total books are tight there. Bookmaker was not tried: this session could not open its lines site.

### Novig Scan: pick the game or slate to fetch
A full NFL pass is about 1,480 slips and Novig allows one quote a second per IP, so it takes about 27 minutes however the quotes are sent. A picker beside Fetch (every board) now limits a pass to one game or one slate.

- **The picker**: All games (as before), then by day: all of that day's games, each kickoff window with two or more games ("6:00 PM slate · 7 games"), and each game. Games in the next eight days, from Novig's catalog (`/api/nba/novig-games`, kept two minutes).
- **Size**: one NFL game is 70 to 160 slips on today's board, 1.3 to 2.9 minutes; Sunday's seven-game early window about 16 minutes.
- **The board keeps the other games**: a picked pass replaces and drops rows of its own games only; the rest stay at their earlier prices, and the status line says the last pass was partial. Fetching a different game right after one finishes needs no minute's wait.
- **How** (`scan.py --games`, `--events ID ...`; `&events=` on `/api/nba/novig-scan`): every slip is tagged with its game (Novig's event id, looked up from its first leg in one catalog pull), whatever built it, so this works on every board. For NFL the stack, game-line and three-leg builders skip the other games before doing any work.
- **Checked** in a browser on live passes capped at four slips a kind: JAX @ TEN alone (13 rows, both teams only), then HOU @ CLE at once (25 rows, the first game's kept); phone width has no overflow.

### Novig Scan: CBB tab
A new board on the Novig Scan page (`scan.py --league cbb`), on the CFB board's code (`LINE_BOARDS` in `scan.py`).

- **What Novig lists** (league `NCAAB`): game lines only, like football. Spreads and totals have alt ladders (median book 5c, 44% inside 4c). Team totals and first-half lines are too wide to take a fair value from: none of 314 team totals and 1 of 86 first-half spreads inside 4c (medians 19c and 10.5c).
- **What it asks**, two a game: the favourite's spread + Over and the underdog's spread + Under, at the lines nearest even money. No underdog-moneyline slips: the margin is close to unrelated to the total in basketball (modelled r 0.01 in a close game, 0.10 at a 30-point spread), so there is nothing for the moneyline to add. A game with no two-sided moneyline (30-point favourites) takes its favourite from the spread.
- **Checked on 89 quotes over four games** (Pitt at Butler, Georgia at UNC, Georgetown at Clemson, Northern Arizona at Kentucky): none above fair, median -10.4%, best -3.2%. Novig charges a positive correlation on both pairings of a spread with a total (r about +0.1 on favourite + Under as well as favourite + Over), and +0.4 to +0.7 on two short-priced alt lines, so the wider shapes are worse than the two asked here.
- Same per-game model as CFB (the margin's and total's sd fitted to the alt ladders: about 12 and 16.5; the two scores come out 0.2 to 0.4 correlated), same `CFB_KAPPA` assumption.

### Novig Scan: refresh one slip
Every row has a small ↻ button beside its age (every board). It prices that one slip again without running a pass: one catalog pull and one quote.

- **What is new on the row**: Novig's quote, and on the NBA, NFL and NHL boards each leg's fair value re-read from Novig's book, with the fair value rebuilt on the same correlation. EV, stake and age follow.
- **What is kept**: a leg modelled from another line (the ladders), a leg whose book has gone wider than it was, and soccer and CFB fair values (Pinnacle, the fitted lift): for those only the quote is new.
- A leg that is no longer open (the game started, the line closed) says so under the status line and the row is left as it was. One refresh at a time; it can run while a pass is running.
- `scan.py --requote --league nfl` (a board row as JSON on stdin); `POST /api/nba/novig-requote { league, wide, key }`.
- Checked on a live 12-slip NFL pass in a browser, desktop and phone width: a two-leg row and a three-leg row re-priced in place, an unknown slip answers 404.

### NFL: spread and moneyline correlations by underdog / favourite
- **What was wrong**: Cam Ward 21+ CMP · 34+ PASS ATT · JAX -10.5 showed fair +306 and +22.5% at Novig's 4.97x, while Fanatics paid +335 and DK +320 on the same slip. The board used one r for a QB's attempts against his team covering (-0.39, all games). For underdogs it is far weaker: an underdog is already expected to trail, and its attempts line says so.
- **Measured** (ten seasons, each fitted within 3-point bands of the closing spread): QB attempts · his team covering -0.44 as a favourite of 3.5+, -0.39 within a field goal, -0.15 as an underdog of 3.5+; completions -0.29 / -0.19 / -0.02. A lead back's carries · covering go the other way: +0.22 as a favourite, +0.54 / +0.53 otherwise. Touchdown props and everything with a total show no split.
- **Three legs, checked on the games**: attempts Over + completions Over + the other team covering hit 78% as often as the old model said for underdogs of 7+ (459 games), 82% for underdogs of 3.5 to 6.5, 102% for favourites. With the per-side r's: 96% to 99% on every side.
- **Now** (`nfl_stack_correlations.py`: `side` dog / even / fav rows for the spread, moneyline and their first-half versions, 210 → 570 rows; `side_of` and `line_r` in `scan.py`): a slip with one of those four lines uses the r for his team's side of Novig's main spread (its moneyline when the spread book is wide). Totals and team totals are unchanged.
- **Ward's slip** reprices to +375 fair: +4.7% at Novig's 4.97x and -8% at Fanatics' +335. With attempts · cover at -0.15 it is under the 0.25 cut, so the board no longer asks it. Each per-side r carries about ±0.08, more than the all-games ones (±0.04).

### Novig Scan: three-leg NFL slips folded into the NFL tab
The NFL 3-Leg tab is gone (Max, 11-13): the NFL tab's one Fetch now also asks the three-leg slips, on the same board. The pair filter has "Three legs: all", the four shapes and the seven kinds of line, each marked "3:". `scan.py --league nfl --kind tri` still asks them alone.

- **Size**: on Friday's board with tight books the pass is 1,462 slips (397 own props, 226 stacks, 450 with a game line, 389 three-leg), about 27 minutes. Games are asked in order of start time and Stop keeps what has been priced. A pass is now killed at 45 minutes.
- Checked in a browser on a pass capped at 24 quotes; no full pass has been run.
### Novig Scan: CFB tab
A new board on the Novig Scan page (`scan.py --league cfb`).

- **No player props**: Novig's `NCAAF` league lists game lines only (`MONEY`, `SPREAD`, `TOTAL`, `TEAM_TOTAL`, and one or two first-half lines a game), so the slips are across one game's own lines.
- **What it asks**, up to five a game: the underdog's moneyline + the game Under (main line, and the Under nearest +230), those two with the underdog's team total Over, the favourite's spread + Over, the underdog's spread + Under. Underdogs under a 10% chance get no moneyline slips. 275 slips on a 59-game Saturday board, about five minutes.
- **Fair value**: each leg is Novig's own book. The correlation is from a two-score model fitted per game (`cfb_candidates`): the margin's and the total's sd from that game's alt spreads and alt totals (about 14.5 and 15), the two scores tied by what those imply, and the margin tied to the total by `CFB_KAPPA` (0.5) x spread / total. That last number is an assumption, not measured on college results. Three-leg slips are integrated over the two scores directly (their correlation matrix is singular, so `price.tri_joint` can't take it).
- **Why these shapes**: 182 quotes over four games (FSU at Pitt, Illinois at UCLA, Houston at Colorado, MTSU at Liberty) across spread, moneyline, total, team totals and first-half lines, two and three legs. Novig's quotes implied the same correlations as the model to within a few hundredths (first half with full game 0.71 to 0.78, team total with game total 0.68 to 0.82, spread with total 0.04 to 0.20 by size of spread), so nearly everything came back 4% to 12% under fair after the fee. The underdog's moneyline with the Under was the one shape priced as nearly unrelated (r 0.02 to 0.03 against the model's 0.10): -0.5% to -1%. With the underdog's team total Over added it showed +6%, +6% and -13% on three games, so that row leans on the model: a lead, not a bet.
- **Refused by Novig** ("Invalid parlay combination"): two lines of the same market in one slip (Pitt -1.5 with FSU +7.5, Over 45.5 with Under 57.5), and a moneyline with the other team's spread.
- **Page**: CFB button after Soccer, one card a game, filters for "Underdog ML + Under" and "Spread + total".

### Novig Scan: NFL 3-Leg board, moneyline and first-half lines
- **NFL tab, game lines**: a prop was asked with the game total, the spread and the team total only. It is now also asked with his team's **moneyline** and the **first half's total, spread and moneyline** (Novig's `MONEY`, `TOTAL_1H`, `SPREAD_1H`, `MONEY_1H`), on the side that goes with the prop. Each player gets his best prop with each kind of line (r 0.25 or better), plus what he was asked before. The pair filter has the four new kinds.
- **NFL 3-Leg** (first shipped as its own board, folded into the NFL tab the same day, above; `scan.py --league nfl --kind tri`): three legs at main lines, all pulling the same way. Four shapes: three of a player's own props (receptions + yards + TD); two of his props + a game line; his QB's passing Over + his Over + a game line; three props across him and his QB. The line is any of the seven above. Each player leads up to three slips, the ones with most lift over unrelated legs, at most two of a shape and one per kind of line. The filter picks a shape or a kind of line; an open row shows the three pair r's.
- **The numbers** (`scripts/nfl_stack_correlations.py`, same file, 90 → 210 prop + line rows): a prop moves with the moneyline as it does with the spread. Cut at a player's season win rate, a lead back's carries with a win reads 0.59, but that counts the spread itself (favourites run more); within games of the same closing spread it is 0.50, against 0.47 with covering. So the moneyline leg is priced off its own fair value with that r. First half: a lead back's carries 0.43 with the 1H spread (0.47 full game), rushing yards 0.39 (0.38); QB passing TDs 0.45 with the 1H total (0.62 full), passing yards 0.26 (0.41).
- **First-half data**: halftime scores for all 2,520 games from ESPN's scoreboard (finals match nflverse in every game). nflverse has no closing first-half lines, so the 1H total is cut at a straight-line fit on the closing total (0.28 + 0.50 x) and the 1H spread at 0.57 x the closing spread. The script leaves the file alone if ESPN gives no halftime scores.
- **Three-leg fair value**: the three-way Gaussian copula on the three pair r's: the player's own for two of his props, role r's across players and with lines. Role r's carry about ±0.05 each, so these fair values are rougher than two-leg ones, roughly ±5%.
- **Size**: on today's board (Friday, tight books) the NFL tab asks 445 prop + line slips where it asked 254, about 3.5 minutes more; NFL 3-Leg asks 394, about 8 minutes. A pass is now killed at 30 minutes, not 20.
- **Checked**: Novig priced all 20 test slips, every new kind (prop + moneyline, each first-half line, all four three-leg shapes). 3 came back above fair (Braelon Allen TD + rushing yards + NYJ 1H moneyline +12.5%), 17 below, most by 3% to 20%. Both boards fetched and rendered in a browser on passes capped at 14 and 42 quotes; no full pass has been run.

### Novig Scan: stop a pass
A pass could not be interrupted: with one running (up to 20 minutes), Fetch was greyed out on every board until it finished.

- **The button**: while this board's pass runs, Fetch reads **Stop**. On another board it reads **Stop NHL Lines and fetch** (whichever board is running): one press ends that pass and starts this board's.
- **A stopped board** keeps the rows the pass priced; rows it didn't reach stay at their earlier prices (the Age column says which). The status line reads "Stopped at 40 / 120 combos". Nothing is dropped as moved or closed, since the pass never got to ask.
- **Server** (`/api/nba/novig-scan?stop=1`, with `now=1` to start this board's pass in the same request): kills the scan process. A stopped board can be fetched again at once, without the one-minute wait.
- Checked against a stand-in scanner (server and the page in a browser); no real pass was run or stopped.

## 2026-11-12 session

### Novig Scan: soccer legs priced off Pinnacle
- **Why**: the soccer board took each leg's fair value from the middle of Novig's own book, and corner books there run 10c to 16c wide. Albania v Finland (Albania win + Albania U4.5 corners + Finland O3.5 corners, 8.06x on Novig) showed fair +618 and +12.2%. Pinnacle offered Albania Under 4.5 at +107 (48.3% before any margin) where Novig's middle said 49%; with Pinnacle's legs the slip is about +720 fair and -1%.
- **Now** (`pinnacle.py`, new; `soccer_candidates` in `scan.py`): each leg (3-way win, goals Over, both corner legs) is Pinnacle's no-vig price on the same line. Two-way lines use the same worst-case devig as everywhere else; the 3-way is devigged in proportion. Where Pinnacle has no such line the leg stays on Novig's book, and only those legs can mark a row ~. A team's corner line is the one nearest 50/50 among the lines Pinnacle prices, if any.
- **Matching**: same kickoff (10 min), both team names close ("Türkiye" / "Turkiye", "Republic of Ireland" / "Ireland"), and Pinnacle's 3-way price within 6 points of Novig's, else the match is left on Novig's books. On today's board 169 of 260 legs were on Pinnacle; the gaps are mostly Over 1.5 where Pinnacle lists no 1.5.
- **Cost**: two Pinnacle calls a pass (public guest API, standard library), nothing more asked of Novig. If Pinnacle doesn't answer the board is priced as before.
- **Page**: open a row to see each leg as "Pinnacle -141, Novig's book says +104". The footnote says where fair values come from.
- **The lift was re-measured** on 19,761 top-five-league matches (football-data.co.uk, 2015-16 to now): 1.29 to 1.41 for home favourites at 40-48%, and 1.38 using each match's own expected corners (team-season rates), so `SOCCER_LIFT` (1.33 there) is left as it is. Club matches, not internationals.

### Novig Scan: NHL Lines board, and a goal with a linemate's assist
- **NHL Lines** (a new board; `scan.py --league nhl --kind lines`): a skater's points at his main line with his team's moneyline, the puck line (-1.5 or +1.5, whichever his team has), the game total and his team's total, on the side that goes with his points, where r is 0.25 or better. Up to four slips a skater: 108 on a four-game board with tight books, so about 300 on a full night. It is its own board so the NHL tab's pass stays short. `--line-stats g ast sog` adds other legs.
- **The numbers** (`public/data/nhl_line_correlations.json`; the Game lines view on the NHL Correlations page): league-wide by position and ice time, not per skater. A forward with 16.8+ minutes: 1+ point with his team's total over 2.5 is 0.52, with a win 0.38, with -1.5 0.36, with the game over 5.5 0.32. Defencemen run about 0.10 lower. Shots on goal with any game line is 0.00 to 0.08.
- **Scores**: final scores for all 1,604 games in the history from ESPN's scoreboard (`scores` in `nhl_game_logs.json`; the nightly step adds each day's). Every score equals the team's skater goals, or one more (140 shootout wins). Results are the raw outcome (won, won by two, more than 5.5 goals), each measured against the skater's own season, not against a closing line.
- **Shots with a teammate's points, looked at again**: split by how tied the two skaters' points are. For linemates (176 forward pairs whose points move together) 3+ shots with the other's 1+ point is 0.06, and with his assist 0.08; for other teammates it is -0.02. That moves a fair price by about 3%, so those slips are still not asked.
- **What is there**: a goal with a linemate's assist, 0.41 for those forward pairs against 0.05 for other teammates. The NHL tab's teammates now ask a skater's goal with a teammate's 1+ assist (and assists with assists) on the same 0.20 cut: 16 more slips on the four-game board.
- Novig quotes a skater's points with all four game lines. Ten real quotes came back at -14% to -55% after the fee. No full pass has been run.

### Novig Scan: NHL teammates
The NHL tab now also asks slips across two teammates (`scan.py --league nhl`, or `--kind mates` for these alone), and the NHL Correlations page has a Teammates view.

- **What it asks**: one skater's points (or his goal) with a teammate's points in the same game, Yes + Yes at main lines, where their r is 0.20 or better (`--mate-r`), at most three slips led by one skater. 31 slips on a four-game board, so about 80 on a full night, after the goals + shots slips.
- **Shots with a teammate's points were asked for and are not on the board.** Across 4,205 pairs with 40+ games together, one skater's shots on goal with a teammate's points is 0.01 (forwards), and shots with shots 0.01; pairs don't differ beyond noise. Those slips would be priced as unrelated legs, so they fall under the cut. `--mate-r -1` asks them.
- **Two teammates' points**: 0.15 on average, more for skaters with more ice time (0.11 / 0.13 / 0.22 by thirds for two forwards), and pairs really differ (spread 0.11 beyond noise), which is linemates. A goal with a teammate's points is 0.10.
- **The data** (`public/data/nhl_teammate_correlations.json`, built by the same nightly script): the games both skaters played 10+ minutes for the same team, 40 needed, same hit-or-miss r as the skater file. Each pair is shrunk toward the average for the two positions at the pair's ice time; box scores don't say who skates together, so the pair's own games are what separate linemates. A pair without 40 games together gets that average. Only skaters on the same team today are kept.
- **How far to trust a pair's own number**: tested by fitting on every other game and predicting the rest (957 forward pairs). The pair's own r (0.73 for the top 3%) over-predicted both-hit games by 12%; the shrunk r (0.28) under-predicted by 8%; the average alone by 13%. A two-group fit (linemates and the rest) did no better than the plain shrink. The top pairs are the known lines: Connor + Scheifele 0.41 (own 0.83), Suzuki + Caufield 0.36, Hughes + Bratt 0.35.
- **Novig quotes them**: points + points, shots + points, shots + shots and a goal + points all priced for two teammates (and for opponents). Eight real points + points quotes came back at -10% to -20% after the fee. No full pass has been run.

### Novig Scan: NHL tab
A new board on the Novig Scan page (`scan.py --league nhl`) and an NHL page under Correlations (`public/nhl.html`, the NHL button in the sport bar).

- **What it asks**: for each skater, Yes + Yes on goals + shots on goal, each at its main line (the Novig line nearest even money), as "N+" legs. 1+ goal with 1+ shot is just the goal leg, so goals go with 2+ shots. About 50 slips on a ten-game slate with tight books, 75 with Wide books.
- **Goals + assists and assists + shots are not asked** (Max, 11-12): their r is about zero, so the slips are near-unrelated legs and each one is an auction. Novig does quote them; `--min-r -1` asks them.
- **Points and blocked shots are not on the board.** Novig refuses any slip with a skater's points and another of his stats ("Invalid parlay combination": tried with goals, assists and shots, Over and Under), and it lists no blocked-shots market for the NHL. Both are in the data and on the Correlations page; `--nhl-points` asks the points pairs if Novig ever opens them, and blocked shots are asked for (market type `BLOCKS`) the day they appear.
- **Novig's market types** (league `NHL`): `PLAYER_GOALS`, `ASSISTS`, `POINTS`, `SHOTS_ON_GOAL`. Also listed and not used: `POWER_PLAY_POINTS`, `SAVES`, `FIRST_GOAL_SCORER`.
- **History** (`scripts/nhl_fetch_correlations.py --moneypuck`): MoneyPuck's game-by-game skater files for 2025-26 and 2026-27, 57,723 skater-games, kept in `public/data/nhl_game_logs.json`. Only the all-situations rows, regular season. The files are on `peter-tanner.com` (the same path on `moneypuck.com` is a 404). Columns: `I_F_goals`, `I_F_primaryAssists` + `I_F_secondaryAssists`, `I_F_shotsOnGoal`, `shotsBlockedByPlayer`, `icetime` (seconds).
- **Nightly** (the daily refresh workflow, same script with no flag): ESPN box scores for games since the last day read, one row per skater per date, then the correlations rebuilt. Stats are read by key (`shotsTotal` is shots on goal; the label SOG is shootout goals).
- **Joining the two**: by name, and by forward / defence where two skaters share one (both Elias Petterssons are Canucks). MoneyPuck's files drop accented letters outright ("Tim Sttzle", "Juraj Slafkovsk"), so an ESPN name also matches a skater on the same team whose name is his with up to three letters missing, or who has the same surname and initial. Anyone still unmatched is added and printed.
- **Checked**: on the three days both sources cover (16 games, 576 skater rows) 571 rows are identical and 5 differ by one shot or one block; none was unmatched. Connor Bedard on 11-05 at Tampa Bay reads 0 G, 0 A, 4 SOG, 0 BLK, 18:05, and his last eight games match ESPN's game log stat for stat.
- **The correlation** is fitted to the two legs' hit-or-miss record at the exact lines (the Gaussian-copula r that gives the both-hit rate, which is what the scanner's joint formula takes; the same kind of r the NFL touchdown pairs carry), one r for each pair of lines, hits measured against the skater's own rate that season. Games of 10+ minutes only, 40 of them needed (606 skaters).
- **What the numbers say**: goals with shots on goal is 0.29 to 0.57 depending on the lines (1+ goal · 3+ shots: 0.41 forwards, 0.34 defencemen). Goals with assists is about -0.03 and assists with shots about 0.01, which is why those two pairs are left off the board. Skaters differ from each other by no more than their own samples' noise (spread 0.22, noise 0.22 on goals · shots), so each skater's r is shrunk almost all the way to his position's average. Predicted both-hit rates are within 0 to 5% of the actual ones across 46,000 skater-games.
- **First quotes** (16 real ones, goals + shots, 11-12): every slip came back under fair, -15% to -34% after the 10% fee. No full pass has been run.
- Fair value, EV and quarter Kelly are the scanner's existing code. Units are $500 on this board (`--unit`, 250 on the others).


### NFL Ladder: a fair value can't be shorter than DK's or FanDuel's one-way price
Max caught Amon-Ra St. Brown 130+ YDS · 8+ REC at a fair of +513 while DraftKings sold 130+ yards alone at +610. A slip can't be likelier than one of its legs, and a one-way price already has margin in it, so the fair value had to be longer than +610.

- **What went wrong**: the yards leg was meant to be capped by DK's price. Run from here the cap works (the same slip prices at +721). On the server the leg sat at Novig's own 17% ask, which means the DraftKings pull did not load there and nothing said so.
- **Now visible**: the ladder tabs' status line says in red when DraftKings or FanDuel prices did not load, with the reason, and that fair values are not capped by that book. The open row shows the book prices next to the capped leg ("DK +610").
- **Cap applies to every ladder leg**, including one priced off a tight Novig book.
- **Each player's own spread**: the yards shift used one spread for everyone at the same main line. It now fits the player's spread to the book's own ladder for him when there is one (St. Brown 0.46 against 0.53 for his line, which alone takes 130+ from 17.5% to 13.5%). Across 168 DK ladders the player's spread is 0.90 to 1.09 of the level curve.

### Novig Scan: three-leg slips for the big-stat players
The NBA tab now always asks three-leg slips for Luka Doncic, Stephen Curry, Victor Wembanyama, Shai Gilgeous-Alexander, Ty Jerome, Jayson Tatum and Nikola Jokic, plus anyone whose points main line is 26.5 or higher (Jalen Brunson on the 11-11 slate). Each gets every three of points, rebounds, assists and threes, all Overs at main lines: four slips a player, 32 extra quotes on that slate. They are asked whatever the player's two-leg price, and fold under his "more" chip. The list is `STARS` in `scan.py`; `--star-pts` moves the points cutoff and `--no-stars` turns them off. Checked with a dry run on stand-in prices; no real pass has been run.

## 2026-11-11 session

### Novig Scan: the hide button shows when bets are hidden
With bets hidden the button read "Show my bets" in the same grey as everything else, which looked like the bets had been lost. It now reads "Bets hidden · show" in amber while they are hidden. It says nothing about what the bets are, so a screenshot still gives nothing away.

### NBA Ladder: higher lines only
The NBA Ladder tab asked each shooter's main-line Points + Threes first and headed his card with it, so its top rows were the same slips as the NBA tab. It now asks and shows only the higher-line slips (fair value +500 to +800): about 60 quotes a pass instead of about 100, and none of them repeats an auction the NBA tab already ran. The main-line gate is gone with it; the fair-value band is what keeps the pass small.

### Novig Scan: My bets survive a redeploy
Bets vanished after a hard refresh. A refresh alone keeps them (checked in a browser); what loses them is the server restarting on a new deploy when its data folder is not on the mounted volume, and there were several deploys that evening. Each browser now keeps its own copy of the list, and when it sees the server's list has been reset it sends the missing bets back. A bet removed with the × stays removed. Bets entered before this change were only on the server and are not recoverable.

### NFL Ladder: higher yards lines, one-way lines included
A new board on the Novig Scan page (`scan.py --league nfl --scope ladder`), the NFL version of the NBA ladder. The NBA one is now labelled "NBA Ladder".

- **What it asks**: each player's yards lines above his main line with the partner leg at its own main line: receiving yards + anytime TD, receiving yards + receptions, rushing yards + anytime TD, passing yards + passing TDs. Only slips with a fair value of +500 to +800 (195 slips on 89 players on Wednesday's board; all lines would be 1,208).
- **Why it needed a model**: on Novig 500 of 1,376 receiving-yards lines were one-way and only 106 had a book within 4c (rushing 295 of 695, passing 108 of 306).
- **The yards leg** (`nfl_shift.py`): a gamma curve through the main line. Game logs (5,000 receiving and 1,400 rushing player-games, priced from prior games): at twice the main line a bell curve gave 60-71% of the real hit rate and at three times 29-38%; the gamma 95-126%. The spread comes from DK's and FanDuel's own ladders (4,000 one-way prices over 14 games): near the main line it depends on the line's level and little else (receiving 1.07 x the mean at an 8-yard line down to 0.52 at 85; rushing 0.93 to 0.46; passing about 0.3). With it the gamma sits under both books' prices by 0-25% across the whole ladder; the bell curve is off by 2x to 50x in the tail. A leg above the main keeps 15% bell curve, since the gamma ran slightly high beyond 1.8x.
- **The main line** is Novig's when it has a tight book within 15 points of even money; otherwise DK's or FanDuel's two-way line, devigged (101 of the 195 slips on Wednesday). The row's detail shows which ("from DK 37.5").
- **Guards**: a line Novig has a tight two-way book on is priced from that book, not the model. A shifted leg stays under Novig's ask, over its bid and under DK's / FanDuel's one-way price on that line (`books.py` now pulls NFL yards: 21 seconds for the week, kept 4 minutes).
- Checked on stand-in prices in a browser (desktop and phone); no real pass has been run.

### Novig Scan: Ladder kept to slips with a fair value of +500 to +800
Max's call: fair values of +2000 are modelled too far from the main line to trust. The Ladder tab now asks a ladder slip only when its fair value is between +500 and +800 (`scan.py --ladder-fair 500 800`; `0 0` asks every slip). On the 11-11 slate that is about 60 ladder slips after the 43 main-line asks, under two minutes, where the full ladder was 476. In that band the ungated pass had 8 slips above fair and 3 at +10% or better (Pritchard 25+ PTS · 3+ 3PM at 11.31x against a fair of +640; Curry 27+ and 26+ PTS · 7+ 3PM at +27% and +20%). Most of what priced at +10% or better was at +1200 and longer (59 of 81 slips).

### Novig Scan: Ladder asks players down to 10% under fair; remove a bet from the strip
- **Ladder gate**: a full pass with no gate (518 quotes, 43 shooters, 11-11) priced 476 ladder slips, 81 of them at +10% or better. 31 were on the 11 players whose main line was above fair, 46 on the 21 players between 10% under and fair, and 4 on the 10 players more than 10% under. The Ladder tab now asks a player's ladder unless his main line is more than 10% under fair (it was: only above fair). The NBA tab's rule is unchanged.
- **My bets**: each player's chip in the strip has an ×, which removes his bets after a confirm. It works even when the slip's row has left the board.

### Novig Scan: Ladder tab and My bets
- **Ladder tab** (`scan.py --scope ladder`): its own board, next to NBA. It asks only shooters whose Points and Threes move together (r 0.70 or better, 43 on the 11-11 slate): each one's main-line Points + Threes first, then, for those priced above fair, every higher points line Novig lists up to main + 15 with threes at main to + 3. One-way lines are included; their fair values are shifted from the main line and capped by Novig's ask and DK's / FanDuel's one-way price. Asking everyone's ladder would be about 490 slips; with the gate it is a few minutes. The NBA tab is unchanged (one main-line slip a player), which is why it still shows 97 combos.
- **My bets**: open a row, type the stake (the price defaults to Novig's multiplier) and press Save. A strip above the board lists each player with his total and the slip; a green badge sits by the player's name (his total) and by the slip you hold. Remove a bet with the × in the open row. The list is kept on the server, so the phone and the desktop show the same bets, and a bet stays until about five hours after tip.
- **Hide my bets** (button by Fetch) hides the strip, the badges and the stake box on that device, for a screenshot; press it again to show them.
- Checked in a browser on stand-in prices (no quotes sent to Novig): the Ladder board, saving two bets on desktop, seeing and removing them on a phone layout, and hiding. The first real Ladder pass is yours to run.

### NBA SGP fair value: DK and FanDuel one-way prices cap a shifted leg
A leg shifted from the main line is now checked live against DraftKings' and FanDuel's one-way Over on that exact line (`books.py`, used by `price.py` and the scanner's ladder).

- The leg's chance can't sit above the better book's price with the least margin that book charges taken out: DK 2% down to a 15% shot and 13% under it, FanDuel 0–2% and 5% (the low end of each book's margin against Novig's tight two-way lines on 11-11; the usual margins are 6% near the main and 30–45% on long shots).
- The output shows the prices on the leg's line (`DK +552 · FD +600`) and says when they capped it. A one-way price never raises a leg.
- On the 11-11 slate the cap bit on 230 of 1,106 shifted legs above the main line (after Novig's own ask had already cut 172), by a median 7%.
- Cost: about 4 seconds for one game, 15 for all ten, kept for 4 minutes. The scanner pulls only when it prices a shifted leg, so the default main-lines scan is unchanged. `--no-books` turns it off, and a book that can't be reached is skipped.
- `python3 .claude/skills/nba-sgp-fv/books.py "Payton Pritchard" pts` prints both books' ladders with an estimated fair for each line.

### NBA SGP fair value: legs on one-way and far lines
An SGP leg on a line Novig has no two-way book for (30+ points against a 22.5 main, 5+ threes) is priced by shifting the main line's fair value. That shift was a bell curve for points and half bell curve, half count model for the other stats, and it ran far short above the main line.

- **Study** (53k game logs, each game priced from prior games only): at main + 12 points the bell curve gave 54% of the real hit rate, at + 3 threes 36%, at + 4 rebounds 63%, at + 4 assists 45%. The count model gave 96–112%. Below the main line every method was within 3%.
- **Books**: DK's and FanDuel's one-way ladders for all ten games of 11-11 (3,200 and 2,400 prices) sit over the count-model fair by their margin, measured against Novig's tight two-way lines: 6% near the main, 5–13% on 15–40% shots, 30–45% on long shots. Over the bell curve they would be charging 160–570%.
- **Change** (`price.py`, used by the scanner's ladder too): above the posted line a leg is the count model (points: 80% count model, 20% bell curve, since it ran 12–28% high at + 12 to + 15). Below it nothing changes. Both-legs hit rates on the ladder (points + threes / rebounds / assists, up to main + 10 points and + 3) went from 52–80% of actual to 81–101%.
- **Guard**: a shifted `novig` leg stays inside Novig's own ladder, at most the lowest ask at that line or below and at least the highest bid at that line or above. A one-way line still gives the ceiling. One player's shift is noisy: Pritchard 25+ points shifted to 17.3% with Novig asking 14% there. The scanner's ladder already had the ceiling and gets the floor.
- `--ladder-fix` was measured on the old shift and should stay off.
- DK's SGP price can't be pulled from this container (403 on its bet calculator), so slips were checked against game logs and leg prices, not against DK's parlay price.

### Novig Scan: rows drop off when their game starts
The board kept the last pass until the next Fetch, so after tip-off it still listed slips on games already under way. A row now disappears once its game has started (the status line counts them: "12 hidden, game started"), and when every game on the board has started it says to press Fetch for the next slate. A Fetch already prices only games still to come, so after tonight's last tip it prices tomorrow's.

Checked and not built: adding the game's spread or total to an NBA Points + Threes slip. On 138 shooter-seasons (8,552 games) points + threes Over with his team beating its usual margin hits 1.13x as often as if the margin were unrelated; Novig's quote on six test slips charged 1.19x for the team's spread (1.13x to 1.41x) and 1.19x for the game Over. The third leg costs about 5% of EV plus the larger parlay fee.

### Novig Scan: QK instead of the dollar wager
The row shows the quarter-Kelly stake in units (QK) and no dollar amount, on desktop and phone: Fair · Novig · QK · Age. QK had been a desktop-only column and the phone showed the wager in dollars.

### Novig Scan: NFL rows are not grouped
On the NFL board every combo is its own row with the player's name, sorted by EV; nothing folds under a "+N more" chip. NBA and soccer keep one card per player / match.

### Novig Scan: one NFL tab
The separate Stacks and Lines boards are gone. The NFL tab's single Fetch now prices a player's own props, the QB + receiver stacks and the prop + game-line slips in one pass, on one board. The pair filter picks one kind (QB + his receiver, prop + game total / spread / team total). `scan.py --league nfl --kind props|stacks|lines` runs one kind from the command line. First pass, Wednesday, tight books: 102 combos (35 own props, 20 stacks, 47 with a game line).

### NFL: QB + receiver stacks and prop + game-line combos (nflverse)
Two more kinds of slip on the Novig Scan page's NFL board (first shipped as separate Stacks and Lines boards, merged into NFL the same day, above). Novig prices both kinds of slip (test quotes 11-11); neither was being looked at.

- **Data** (`scripts/nfl_stack_correlations.py` → `public/data/nfl_stack_correlations.json`, in the daily refresh): ten seasons of nflverse weekly player stats and closing spreads / totals (2017–2026, 5,038 team-games). These are league-wide r's by role, not per player: position plus that season's targets a game (3–5, 5–7, 7+) or carries a game (8–13, 13+). A QB and one receiver share a dozen games a season, too few to fit a pair on its own.
- **What r is**: the copula correlation that reproduces how often both legs hit, each stat cut at the group's median (anytime TD 1+, passing TDs 2+, the game lines at the closing number). Checked at lines the fit never saw (each stat's upper third): actual vs modelled 14.1% / 13.5% (QB yards + WR1 yards), 18.5% / 18.6% (QB yards + game Over), 19.0% / 19.1% (lead back's rushing yards + cover). Each r carries about ±0.04–0.07 of sampling error, which is roughly ±2–4% of EV on a slip.
- **Stacks**, QB with his own receiver: PASS YDS·REC YDS +0.34 / +0.42 / +0.51 for a WR at 3–5 / 5–7 / 7+ targets (TE +0.28 / +0.43, RB +0.34); PASS TD·anytime TD +0.52 to +0.62 for WRs and TEs (a back's: +0.12); CMP·REC +0.36 to +0.52; PASS YDS·TD about +0.24. The board asks those four per receiver, three highest r first.
- **Lines**: QB PASS YDS·game Over +0.41, PASS TD·game Over +0.62, PASS TD·team total Over +0.67, PASS ATT·his team covering −0.39 (asked as attempts Over + the other team). Lead back (13+ carries): CAR·cover +0.47, RUSH YDS·cover +0.38, TD·team total +0.51. WR at 7+ targets: TD·game Over +0.37, REC YDS·team total +0.26. Asked where |r| is 0.25 or more, three per player.
- Also in the file, not asked yet: the negative pairs for Over + Under slips (QB PASS ATT·his back's CAR −0.29, PASS YDS·RUSH YDS −0.15).
- First passes (Wednesday, tight books only): Stacks 20 combos, 3 above fair; Lines 47 combos, 3 above fair.

### NFL: rushing props in the correlation data and the Novig scanner
- **Data**: running backs now carry carries, rushing yards and rushing + receiving yards in their game logs, with five more copula r's shrunk toward the average of the 41 backs at 8+ carries a game: RUSH YDS·TD +0.49, RUSH+REC YDS·TD +0.51, CAR·TD +0.37, RUSH YDS·REC −0.03, RUSH YDS·REC YDS +0.01. QBs get RUSH YDS·TD +0.30 (his rushing TDs) and PASS YDS·RUSH YDS −0.03.
- On those backs' 1,439 games, both legs at his median line and 1+ TD hit as often as the copula says: 28.1% vs 27.9% (rush yards), 28.1% vs 28.4% (rush + rec yards), 24.8% vs 24.9% (carries); unrelated legs would be about 20%.
- **Scanner**: the NFL board also asks rushing yards, rushing + receiving yards and carries, each with anytime TD, for backs, and rushing yards + anytime TD for QBs. Novig refuses carries + rushing yards and rushing yards + rushing-and-receiving yards ("Invalid parlay combination"), so those aren't asked.
- **Fix**: the anytime-TD leg is the 0.5 line only. When that book was too wide the scanner fell back to 2+ TDs (a +1850 leg) and priced the slip off it.
- Novig test quotes, 11-11: it prices two-player parlays (QB passing yards + his receiver's yards) and a player prop with the game total, spread or team total.

### NFL: quarterbacks in the correlation data and the Novig scanner
- **Data** (`scripts/nfl_fetch_correlations.py` → `public/data/nfl_correlations.json`): QBs on current rosters are now in the file (60 of them, `group: "QB"`), with their game logs (attempts, completions, passing yards, passing TDs, interceptions, rushing yards) and six copula r's: `att_cmp`, `att_pyds`, `cmp_pyds`, `att_ptd`, `cmp_ptd`, `pyds_ptd`. Same method as the receivers; only games with 10+ pass attempts count, and each r is shrunk toward the average of the 28 QBs with 20+ games at 20+ attempts. The daily refresh picks them up.
- **Position averages**: ATT·CMP +0.88, CMP·PASS YDS +0.76, ATT·PASS YDS +0.67, PASS YDS·PASS TD +0.43, CMP·PASS TD +0.25, ATT·PASS TD +0.11. On those 28 QBs' 993 games, both legs Over at each QB's median lines (2+ pass TDs) hit as often as the copula says: 37.6% vs 37.8%, 35.6% vs 35.8%, 34.0% vs 34.5%, 31.8% vs 31.0%, 25.4% vs 26.1%, 24.3% vs 24.4%. The 0.02–0.05 hold on the between-player spread was tested out of sample for receivers only and is carried over, so every QB sits within about 0.01 of the average.
- **Scanner** (`scan.py --league nfl`, the Novig Scan page's NFL board): also asks each QB's Over + Over at main lines on those pairs (all but ATT·PASS TD, under the 0.15 minimum r). The pair filter has the five QB pairs. Novig quotes them: a wide-books pass priced 95 combos on 52 players, QBs included, none of the QB rows above fair.
- The NFL page itself is unchanged: QBs are in the data but not in its table (its columns and pricer are receptions / yards / TD).

### NFL page: Fetch FV takes Novig books up to 6¢ wide
The NFL page's Fetch FV priced a leg from Novig only when the book was at most 4¢ wide (bid to ask); the limit is now 6¢ (`NV_MAX_SPREAD` in `public/nfl.html`). Lines between 4¢ and 6¢ wide now fill in and are no longer dimmed as rough. The Novig scanner's NFL board and the NBA pages stay at 4¢.

## 2026-11-10 session

### Sport tabs: readable
The tab bar above every page had dim grey text on transparent pills, and on a phone the two-word tabs wrapped onto two lines. Inactive tabs are now light text on a filled pill with a visible border, the active tab is solid green with dark text, labels stay on one line, and on a phone the bar scrolls sideways (dots hidden to fit more). The NBA header no longer says "r at Pinnacle main lines (… 0 players)" when Pinnacle matched nobody.

### NBA dashboard: higher-contrast colors
The page was hard to read, mostly on a phone: grey labels on a near-black panel, boxes barely lighter than their background, and r values as tinted text on a faint tint.

- Secondary text is brighter (`--muted` #8b98a5 → #b3bfcc), borders are visible (#2a333d → #3d4a59), and input boxes, selects and buttons have their own lighter fill. Box stats and the builder's labels are full white. Placeholders are a clear step dimmer than real values.
- The table's r values are white numbers on a solid green or red pill (strength still relative to the players on screen, up to 85% solid at 2 SD) instead of colored text.
- Green, red and amber are brighter; the smallest type (10–11.5 px) is up about a point.

### NBA dashboard: scatter chart removed; − / + on the line boxes
- The prop builder's scatter chart (and its season legend and hover tooltip) is gone, after the hit-rate tiles. The panel is now the two stats and lines, the devig r, and the SGP pricer.
- Each line box (both legs and the 3rd leg) has − and + buttons that move the line a full point (17.5 → 18.5), and tapping the box selects its value so typing replaces it. Retyping a line on a phone meant clearing the box first, and each keystroke repriced on a half-typed number.

Checked in headless Chromium at 390 and 1500 px: + on PTS 17.5 gives 18.5 and reprices (+229 → +240), the 3rd-leg stepper works, Fetch FV / Novig SGP (mocked) still fill, no page errors.

### NBA dashboard: hit-rate tiles removed from the prop builder
The four over/under tiles under the chart (share of games in each quadrant, with a game-log fair price) are gone; they weren't used and crowded the panel. The scatter still shows the same games against the two lines. On a wide screen the SGP pricer now sits beside the chart.

### NBA dashboard: Fetch FV and Novig SGP say what they did
Pressing either button used to print a paragraph of muted text, which on an iPhone inside the dashboard's iframe was also blown up by iOS text inflation.

- Each press now leaves a boxed report with one line per leg or combo: a green check and "PTS 19.5 filled: over +102 / under −102 · 2.0¢ wide", or an amber ! and "PTS 17.5 not filled: Novig has no line at 17.5." The Fetch FV header counts it ("0 of 2 legs filled"). Bid/ask/mid detail moved to the tooltip.
- Under an unfilled leg: "Tap a Novig line to switch PTS to it" and the chips (`o19.5 +102`; wide books dashed with "44.0¢ wide"). The picked chip and the leg's line turn green.
- Boxes Novig filled (fair odds, SGP odds) get a green edge until edited. The buttons read "Fetching…" / "Asking…" while they work.
- Novig SGP with a line Novig doesn't have says what to do: "No SGP price filled. Novig has no line at PTS 17.5. Tap Fetch FV, pick one of Novig's lines, then tap Novig SGP again."
- The SGP odds box's placeholder was "4.14x", which read as a filled price; it is now "price".
- `text-size-adjust: 100%` stops iOS inflating the text.

Checked in headless Chromium at 390 and 1500 px with Novig's two endpoints mocked (no line, too-wide line, chip picks, parlay quote): no page errors. Not run against live Novig or on a real iPhone.

### NBA dashboard: cleaned up
The table was 16 columns with a line annotation beside every r. Now one number per cell.

- **Table**: the three game score·REB columns (TOT / TM / OPP) are off by default (Options → "Game score·REB columns", remembered; sorting on one from the phone's Sort menu shows them). nEff moved to the expanded row's caption. Only the sorted column spells out its lines (`~17.5/9.5`); the other columns keep them in the tooltip. A rule separates box stats from the r's, numbers are tabular, `-0.00` shows as `0.00`, and the "plays today" dot shows only under All players (under Playing today every row had it).
- **Controls**: Min games and the short-minute checkbox moved into an Options popover. The Sort menu shows on phones only (headers sort on a wide screen). The count reads "85 players".
- **Slate bar**: one chip per game with just the tip time (`MIL @ NY 7:30 PM`); one swipeable row on a phone instead of six lines.
- **Player panel**: the builder's stat and line controls sit on one row beside the devig r. The by-season table drops the `p=` text (underlined = p < 0.05, p in the tooltip) and the pooled row reads `0.43 ~17.5/9.5 margin 0.29 · own 0.41` (prior and p in the tooltip).

No pricing or data logic changed. Checked in headless Chromium at 1500 and 390 px: 85 rows, the panel opens, Options toggles the score columns and the sort falls back to PTS·REB when they are turned off, no page errors, no horizontal overflow. Pinnacle wasn't reachable from the test machine, so the `@` (Pinnacle line) labels weren't seen live.

## 2026-11-04 session (evening)

### NBA TEAMMATES tab: every stat pairing at tonight's lines, like last season's sheet
The tab is rebuilt around last season's `teammate_correlations` sheet: one row per teammate pair × stat pairing (PTS/REB/AST/3PM, all 16) × direction (O+O, O+U, U+O, U+U), at tonight's Pinnacle main lines (live from `/api/pinnacle/nba-props`; `~` marks this season's average where Pinnacle has no line).

- **Columns**: r (Pearson over their games together, within-season centered; sign flipped for mixed directions so positive means the legs hit together), shrunk r, games together, the combo's hit rate vs. independence, Pinnacle's devigged leg fairs, the combo's fair (Gaussian copula), no-correlation price, bet-if (fair + 3%), the direct assist-to note from play-by-play ("0.57 3PM/gm from Brunson → 24% of Anunoby's 3PM"), and both players' mpg last season → this season (orange when a role moved 5+ minutes).
- **Controls**: tonight's game, player and teammate search, stat pairing, directions (U+U off by default), min games (30), min |r| (0.20), direct assist-to only, tonight's lines only, and a raw/shrunk toggle for the r the fair price uses (raw by default, as last season's sheet was used). Sorted by r, high to low.
- **Assist network** view stays, now over both seasons and current rosters.
- **Data**: `scripts/nba_teammate_logs.py` writes `public/data/nba_teammate_logs.json` (628 KB, 163 KB gzipped): each current player's box line in every game for his current team, last season and this one, plus assist totals between current teammates. The page computes all correlations in the browser (about 0.8 s for 1,326 pairs). Added to the daily refresh workflow.
- Removed the xlsx sheet and `scripts/nba_teammate_sheet.py` from earlier today; the tab replaces them.

Verified in headless Chromium at 1500 and 390 px against the local server with live Pinnacle lines (523 props): 1,014 rows at the defaults, the Brunson filter gives 18 rows, the raw/shrunk toggle reprices (Brunson o7.5 AST + Anunoby o2.5 3PM: +330 raw, +422 shrunk), the assist network shows 6 Jokic links, the tab loads inside the dashboard iframe, no page errors, no horizontal overflow on a phone.

## 2026-11-04 session

### NBA teammate correlations + assist network (2025-26)
New page `public/nba_teammates.html` (linked as "Teammates →" from the NBA correlations header). Data comes from `scripts/nba_fetch_teammates.py`, which writes `public/data/nba_teammates.json` from ESPN game summaries: one request per game gives the box score and play-by-play. An assisted basket reads "X makes … (Y assists)" with participants [scorer, assister]. 2025-26: 1,235 games, 65,879 assists linked to a passer and scorer, 472 players, 5,400 ordered pairs with 20+ games together.

- **Views**: AST(A) → PTS(B), AST(A) → 3PM(B), REB·REB, and an assist network. The network shows A→B assists per game, 3PT assists per game, the share of A's assists going to B, and the share of B's FGM and 3PM that A set up. Filters: team, player A / passer, player B / scorer, min mpg (default 20), min games together, and "still teammates" (ESPN's current rosters).
- **Method**: raw r on the stats, plus φ on Over hits at a proxy line (floor(season mean) + 0.5). φ is shrunk in Fisher-z toward the league mean for the stat pair and role pairing (S/R/B by mpg; the role cell's mean is itself partially pooled toward the league). τ comes from the method of moments. r over games decided by 12 or fewer is shown so blowout-driven pairs can be spotted.
- **League φ**: AST→PTS +0.041, AST→3PM +0.036, REB·REB +0.005. Bench–bench pairs run highest everywhere (+0.08, +0.08, +0.06): garbage-time minutes move together. The between-pair spread is small (τ ≈ 0.04–0.055), so a single season shrinks individual pairs hard. The top rotation AST→PTS pairs land around +0.10–0.11 (raw φ 0.3–0.5).
- Not yet in the daily refresh: the 2025-26 season is final. Run `--season 2027` once the current season has enough games; a slim per-game cache goes to `.cache/` (gitignored), so reruns only fetch new games.

Verified in headless Chromium at 1400 and 390 px: all four views render with no page errors and no horizontal overflow. Jokic's network reads Braun 2.59/g (53% of Braun's FGM), Murray 2.33/g. Spot checks against known passing duos: Murray→Jokic 2.71/g, Maxey→Embiid 2.86/g, Draymond→Curry 2.33/g (1.23 of them threes).

## 2026-11-01 session

### NBA dashboard: no Pinnacle line → r at this season's average
A leg Pinnacle hasn't posted now uses the half-point line at this season's average, the same line the prop builder opens on (`halfLine` of the current-season mean). Its probability is the weighted share of his games over that line, as the pricer uses when a fair-odds box is empty. Previously such a leg fell back to the median. The check is per leg: Pinnacle PTS with no Pinnacle REB line prices PTS at Pinnacle and REB at the season average. The cell marks it `~5.5/1.5`, where `@` still means both legs are Pinnacle main lines. The tooltip names each leg's source: `REB 1.5 (this season's average 1.8; over in 61% of his games)`. The r's are cached per player and pair, and cleared when Pinnacle's lines land or the short-game toggle changes the games behind them. Sorting follows the r on screen, as before. The meta line reads `r at Pinnacle main lines (@, …), else this season's averages (~)`.

Verified in headless Chromium at 1600 and 390 px: the table's PTS·REB equals the builder's plug-in box on open in every case. Melton (both legs Pinnacle) 0.20 @12.5/3.5 = +0.203. Keon Ellis (Pinnacle PTS, average REB) 0.18 ~5.5/1.5 = +0.184. Sexton 0.15 ~9.5/1.5 = +0.151. Jokic (no lines; DEN off) 0.13 ~20.5/9.5 = +0.127. Edey 0.26 ~6.5/6.5 = +0.265. With short games unchecked Jokic re-prices and still matches. All players renders in about 0.3 s. No page errors, no horizontal overflow.

### NBA dashboard: r at today's Pinnacle main lines
The r columns are priced at each player's main line for the day, from Pinnacle, instead of at lines near his median. The prop builder opens on those lines with Pinnacle's prices in the fair-odds boxes.

- **`dk_api.py pinnacle-nba-props`**: Pinnacle's guest API (the same curl_cffi session and key as the World Cup pulls) in two league-wide calls. It returns every pregame player prop with both prices (Pinnacle hangs one line per prop: points, rebounds, assists, threes, PRA; 188 props on 54 players today) and each game's main total and team totals. **`server.js`** serves it at `GET /api/pinnacle/nba-props`, cached for two minutes.
- **`public/nba.html`**: after the first paint, the page loads those lines and matches names with the Novig key; all 54 of today's Pinnacle players match ESPN's. For each pair whose two legs both have a Pinnacle line, the r cell shows the plug-in at those lines, taking each leg's Over at Pinnacle's worst-case devigged price as the pricer does. A small `@23.5/2.5` gives the lines, and the tooltip gives both prices. TOT·REB, TM·REB and OPP·REB use the game total, his team's total and the opponent's total. Sorting follows the r on screen. Players without both lines keep the median value, with no `@`. The meta line reads `r at Pinnacle main lines (6:42 PM, 54 players)`.
- **Prop builder**: each leg defaults to the Pinnacle line with both prices filled, so the pricer and its plug-in box match the table at once. A note reads `Pinnacle main lines · 6:42 PM: PTS 23.5 o -108 / u -122 · REB 2.5 o -132 / u +100`. Switching a stat moves that leg to its Pinnacle line. Editing a line clears that leg's prices, as before. Fetch FV (Novig) still overwrites them. A builder opened before the lines arrive moves onto them unless it was edited.
- **How much it moves**: a main line sits near 50/50 by design, and the plug-in r depends only on the two legs' probabilities. So at main lines it stays close to the median value. Today PTS·REB moved by at most 0.004 across 44 players and PTS·AST by at most 0.002. PTS·3PM moved by up to 0.05 (Keon Ellis: a 3PM line at 37% Over with a 0.7 margin r). Far alt lines are where r really changes, and the builder prices those.

Verified: the endpoint returns 4 games and 188 props (0.75 s cold, cached after). In headless Chromium at 1600 and 390 px the page has no errors and no overflow. Darius Garland reads PTS·REB 0.08 @23.5/2.5 and PTS·AST 0.09 @23.5/7.5, and his builder opens on PTS 23.5 / REB 2.5 with −108/−122 and −132/+100 filled, its plug-in box +0.077. Switching to AST gives 7.5 at +102/−136 and +0.090. An independent scipy computation from the skill's `devig_worst` gives +0.0770 and +0.0905. The repo's NBA and TLS smoke scripts still pass.

### NBA PTS·REB: the role prior adds rebound volume, so bigs aren't under-priced
Follow-up to the entry below, after Zach Edey's PTS·REB r (0.23) looked low next to his scatter. A minutes-only prior gave a 22-mpg big the same prior as a 22-mpg guard. But a big's rebounds track his minutes more closely, so his PTS·REB r runs higher. Tested on held-out seasons, 20–28-mpg bigs' same-direction combos (O/O + U/U at median lines) hit 3.8 points more often than predicted. The PTS·REB prior is now a least-squares line in minutes and rebounds over rotation players (r ≈ 0.60 − 0.016·mpg + 0.021·reb; each stat clipped to the pool's range, so it is flat beyond it like the bins). PTS·AST keeps minutes bins: adding assist volume there fit worse.

- Out of sample (both folds), the log-loss gain over independence for rotation players goes 12.96 (this morning) → 13.35 (minutes bins) → 13.61. The same-direction gap at median lines goes from +3.8 to +1.7 points for 20–28-mpg bigs and from +1.4 to −0.1 for 28+-mpg bigs. Under-5-REB players move from +0.4 to +0.9.
- Plug-in r, this morning → first fix → now: Edey 0.18 → 0.23 → 0.28, Jokic 0.13 → 0.10 → 0.15, Sabonis 0.17 → 0.14 → 0.22, Gobert 0.19 → 0.16 → 0.20, Zubac 0.19 → 0.18 → 0.23, SGA 0.18 → 0.16 → 0.14. Bigs (7+ REB) average 0.207 (was 0.184 this morning); the rotation-wide average stays 0.171.
- Edey at the dashboard's 6.5/6.5 lines: plug-in +0.265 (was +0.217), pricer O/O 51.7% vs 56% in his games. At 8.5/7.5 it is 34.7% vs 34%. The low-line gap is his bad-game tail: 8 of his 9 short-minute games went Under/Under. An extra low-line link like that mostly doesn't repeat. Between seasons, players' Under/Under excess at 30th-percentile lines correlates only 0.12, and the top fifth's +4.9 points became +1.4 the next season. So the model doesn't chase it.
- `scripts/nba_fetch_correlations.py`: `SHRINK_COVARIATE` takes a tuple for a line prior (`_line_prior`, pure Python normal equations), one stat for bins (`_bin_prior`, unchanged output: every other pair's shrunk r is bit-identical). The payload's fit for `pts_reb` carries `covariates`, `coef` and `range` instead of `knots`; `--reshrink` prints either. Data regenerated (same game logs, 609 players).

### NBA correlations: short-minute games count again, small samples trusted less, role prior by minutes
Checked the PTS·REB r end to end after it looked low on the dashboard. The arithmetic is right: the stored r's reproduce from the game logs (to 5e-5), and the copula joint in `nba.html` and `sgp.py` matches scipy's bivariate normal to six decimals, with the plug-in r at median lines equal to (2/π)·asin(r). The problems were in the method:

- **Short-minute games were dropped** (under 60% of the player's median minutes that season: injury exits, blowouts, foul trouble; 7% of rotation players' games). A prop on a player who plays is action, and those are the games where every stat drops together, so leaving them out understated PTS·REB and PTS·AST. Out of sample (fit on 2024-25, scored on 2025-26 and the reverse, every game, lines at each player's median), rotation players' real Over/Over hit rates showed 1.21× the PTS·REB dependence the old r's predicted, and 20–26-mpg players 1.5–1.7×. Short games now count in every r and box mean. They stay flagged in the game log; the dashboard shows them by default and the checkbox hides them.
- **Small samples were over-trusted.** The shrinkage weight used each player's sampling noise at his own r, so a 6-game rookie whose r ran to 0.90 got 53% weight on it (Caleb Wilson, PTS·REB plug-in 0.41). The noise is now evaluated at the role prior, as the NFL script does; he is at 0.14.
- **The role prior is minutes, not REB or AST volume.** PTS·REB and PTS·AST move together mostly through minutes: a 34-mpg starter's PTS·REB margin r runs near 0.19, a 21-mpg reserve's near 0.36. Binned by rebounds, the short games would have pulled high-minute bigs up toward the bench bigs' r (bigs' dependence over-predicted by 10–20%). PTS·REB and PTS·AST in the data file, and REB·AST in `price.py`, now bin on minutes; PTS·3PM keeps 3PM volume and the game-score pairs keep REB.

Out of sample on rotation players, Over/Over at median lines is 29.6% actual vs 29.6% predicted (old r's: 28.9%), and the log-loss of the four over/under outcomes improves in both folds for PTS·REB, PTS·AST, REB·AST, REB·3PM and AST·3PM. PTS·3PM is a wash: slightly better in one fold, slightly worse in the other. One limit: dependence is stronger in the bad-game tail than the good-game tail, which one Gaussian-copula r can't match everywhere. At lines below or at the median the new r is right; with both legs at the 75th percentile it runs a little high (Over/Over 8.6% actual vs 9.1% predicted, where the old r's predicted 8.6%).

What moved: rotation players' PTS·REB plug-in r averages 0.171 (was 0.146). That is +0.05 for 20–26-mpg players and no change for 30+ mpg (0.136 → 0.133). Jokic goes from 0.130 to 0.102: his own r over 140 games is 0.11 (0.03 and 0.10 in the last two seasons). PTS·AST rises the same way (0.086 → 0.112). No high-assist scorer has a negative shrunk PTS·AST r any more (Booker, Jokic, SGA, Morant, Murray and Brunson were −0.024 to −0.003). For Morant, the old negative r came from leaving out his short games: his own r was −0.19 without them and −0.07 with them. At 50/50 lines, an AST Under + PTS Over combo's fair probability drops by 0.4–1.7 points (Morant 25.1% → 23.5%). PTS·3PM and the game-score pairs barely move (median change under 0.005).

- **`scripts/nba_fetch_correlations.py`**: every game played feeds the r's and means (`--short-min-frac` now only sets the flag); `add_shrinkage` evaluates the noise at the prior; `SHRINK_COVARIATE` uses `min_mean` for `pts_reb` and `pts_ast`. `public/data/nba_correlations.json` was regenerated: the same game logs as this morning's file, 609 players, short games included (51,850 game rows).
- **`public/nba.html`**: short-minute games are shown by default in the box stats and the prop builder (checked box; unchecking hides them), matching the r's. The per-season table reads `65 (2 short)` instead of `(−2)`. The tooltips say short games count.
- **Skills**: `price.py` computes its own pairs (REB·AST, REB·3PM, AST·3PM) over every game, with the noise at the prior and REB·AST binned on minutes. Its line-shift spread still leaves short games out. `sgp.py` uses the same noise rule in its fallback, and `players` prints a "no player under --max-r" line instead of empty Vulture commands. The SKILL.md method notes are updated. The Lillard check now reads +227 / 16.2% / $723.57 / 1.45u on today's data: it read +225 before this change, so the +229 recorded on 10-29 had already drifted with the daily refreshes.

Verified: the repo's NBA scripts pass (`nba_ev_formula_check`, `nba_null_ev_sort_check`, `nba_ocr_normalize_tests`, `nba_render_card_smoke` with jsdom, `nba_dk_match_tests`). In headless Chromium at 1600 and 390 px the page has no errors and no horizontal overflow. Short games are checked by default. Jokic's row reads PTS·REB 0.10 (margin 0.16, data 0.11) over 140 games, and his builder at the screenshot's PTS 20.5 / REB 9.5 shows a plug-in r of +0.085 (was +0.109). Unchecking the box hides his 2 short games.

### NFL tab: receptions, receiving yards and TD correlations for WRs, TEs and RBs
A new **NFL** button in the sport bar (`?sport=nfl`) opens `public/nfl.html`, built like the NBA tab: per-player REC·YDS, REC·TD and YDS·TD correlations shown as the plug-in r for a devig calculator, a this-week toggle, ESPN injury badges, and per player a prop builder (scatter + quadrant tiles), an SGP pricer and Novig's "Fetch FV". TD is receiving + rushing, i.e. the anytime-TD market (line 0.5).

- **`scripts/nfl_fetch_correlations.py`** — every WR / TE / RB / FB on a current ESPN roster (551 with 3+ games), regular-season game logs for ESPN's current season and the two before it (2024–2026, ESPN names an NFL season by the year it starts), recency weights 0.15 / 0.35 / 0.50. Game-log columns are read by ESPN's stat `names` (an RB's log lists rushing first). Writes `public/data/nfl_correlations.json` (2.2 MB, ~0.26 MB gzipped as served); ~11 s with 16 workers. Exits without writing if ESPN returns no rosters or logs.
- **The r is a Gaussian-copula correlation, not the Pearson r of the stat lines.** TDs are 0/1 most weeks and receptions are small counts, and a raw Pearson r understates the copula correlation, so the copula underpriced every combo against the actual hit rates (pooled WR/TE seasons: REC·TD 0.28 raw → 0.39, YDS·TD 0.36 → 0.44, REC·YDS 0.76 → 0.80). Per pair, the more continuous stat becomes normal scores within each season, the count stat is centered on its season mean, and their weighted r is scaled by the polyserial factor sd / Σφ(τ) from that season's count thresholds. On the pooled data this matches a full maximum-likelihood copula fit with discrete margins (0.797 / 0.443 / 0.387 vs 0.803 / 0.437 / 0.387), reproduces the pooled joint hit rates (YDS o / TD: 18.9% predicted vs 18.8% actual; REC o / TD: 21.4% vs 21.5%), and on simulated players with 17 + 17 + 7 games it is unbiased to within 0.01 with the noise its formula says.
- **Shrinkage toward the player's position, not a role covariate.** Out of sample (2023–24 games predicting each player's 2025 r), a player's own r predicted worse than his position's average for every pair (e.g. WR YDS·TD MSE 0.227 vs 0.126), and role covariates (yards per catch, targets, TD rate) showed nothing. So each r is shrunk toward the average of rotation players (20+ games, 3+ targets a game) at his position — WR REC·YDS 0.84 / REC·TD 0.41 / YDS·TD 0.47, TE 0.86 / 0.45 / 0.42, RB 0.75 / 0.00 / 0.18 (RB touchdowns are mostly rushing) — with each player's sampling noise evaluated at that average (at his own r, players whose sample r ran high would get the least noise and the most weight on it) and the between-player spread held to 0.02–0.05, the most that held up out of sample. Most players sit within a few hundredths of their position's r; the player's own r is shown beside it.
- **`public/nfl.html`** — table columns G, nEff, Tgt, Rec, Yds, TD% and the three r's. The table's plug-in r is the binary correlation at a median line; for the TD pairs, at the player's weighted 2024–26 anytime-TD rate (the binary correlation depends on it). Filters: position (WR + TE default, WR, TE, RB, All), min targets a game this season (default 3), min games. **This week** = teams whose game this week (ESPN's scoreboard, live in the browser, baked snapshot as fallback) hasn't gone final, so Thursday's teams drop off by Sunday; byes listed. Injury report: Q / D badges; OUT, IR, PUP, NFI, inactive and suspended players hidden. The builder's default lines are the half-point closest to a 50/50 split of the player's weighted games (about where a book hangs its main line), TD at 0.5; picking the other leg's stat swaps the legs. The pricer, devig, EV and Novig chips work as on the NBA page; Fetch FV reads Novig's NFL `RECEPTIONS`, `RECEIVING_YARDS` and `TOUCHDOWNS` markets (161 of 164 Novig receiving-prop names match ESPN's; aliases for Kenneth Gainwell → Kenny Gainwell and Kevin Concepcion → KC Concepcion).
- **Same conventions as today's NBA changes:** no explanatory paragraphs (the meta line reads `Box stats: 2026 season`, the builder is titled "Prop builder", the pricer's subtitle is just its r, the history table is "Per-season history"; the method lives in the column-header tooltips and here). The box columns (G, Tgt, Rec, Yds, TD%) and the min-targets filter use the current season only, and players with no games this season are hidden, so a player back from injury this week appears once he has played. The r's, the builder and the pricer still use 2024–26, weighted, and the table's TD-pair plug-in r uses the weighted 2024–26 TD rate (steadier than this season's handful of games; the tooltip says which rate).
- **`public/index.html`** — NFL button + lazily-sourced iframe page; **`.github/workflows/refresh-data.yml`** runs the NFL script daily after NBA (`continue-on-error`, so an ESPN hiccup there can't block the MLB/NBA commit).

Verified: ESPN's raw 2024 log for Brock Bowers matches the JSON game rows. In headless Chromium (ESPN's scoreboard and injury report served from curl copies, since this container's proxy blocks browser requests to ESPN; Novig live): `?sport=nfl` opens the tab and the NBA / MLB / default routes are unchanged; week 8 shows 103 WR/TE with 10 OUT/IR hidden (A.J. Brown out and Davante Adams on IR gone, George Pickens badged Q), byes listed, Thursday's game final. A FanDuel 2-leg slip, Bowers REC o6.5 + YDS o69.5 at +139 (DK +124), with Novig's fair odds at 6:29 AM CT (+129 / −107) and his REC·YDS copula r 0.863, prices at **+159** fair (38.7%), so FanDuel's +139 is **−7.6% EV** and DK's worse (Novig's 6.5 had moved to +126 on a rerun: +156, −6.7%); an independent scipy bivariate-normal computation gives the same joint (0.38674 → +159, −7.6% from the boxes' odds; 0.38735 from Novig's unrounded fair values: Fetch FV writes whole American odds into the boxes, the same as the NBA page). The table's plug-in r's (0.66 / 0.29 / 0.27) match scipy too. Sorting by YDS·TD opens builders on YDS × TD; Fetch FV fills the anytime-TD leg, skips a 7¢-wide yardage line and offers Novig's ladder as chips. No page errors; no horizontal page overflow at 1600 or 390 px. The repo's NBA regression scripts still pass.

## 2026-10-29 session

### Novig name matching: "P.J." meets "PJ"
Fetch FV said "P.J. Washington isn't on Novig's open pregame props" while Novig had him as "PJ Washington": the name key turned each period into a space ("p j washington" vs "pj washington"). The key (`nvNorm` in `nba.html`, `norm` in `novig.py`) now drops periods and apostrophes and ignores spaces, and a small alias table covers Novig's full first names (`Alexandre Sarr` → ESPN's `Alex Sarr`). Against the 10-30 pregame board, 147 of 148 Novig players match the data file (was 145); the one left, AJ Dybantsa, isn't in the data yet. Verified in headless Chromium: PJ Washington's Fetch FV now shows his ladder.

### NBA dashboard: the prop builder follows the sort
Sorted on a correlation (PTS·REB / PTS·AST / PTS·3PM / TOT·REB / TM·REB / OPP·REB r, from the Sort menu or a column header), an expanded player's builder opens on that pair: stat selects, default lines (blended means), scatter, tiles and pricer. Changing the sort to another pair moves every open builder onto it (fresh lines; fair odds and SGP prices cleared, since they belonged to the old pair); a builder already on the new pair, or a sort that isn't a pair (Points, Minutes, name), leaves it alone. Picking stats by hand in a builder still works as before.

Verified in headless Chromium: sort PTS·AST → opens PTS × AST; switch to PTS·3PM → the open builder moves to PTS × 3PM with its fair odds cleared; re-clicking PTS·3PM (direction flip) keeps an entered fair; OPP·REB header → Opp score × REB with the pricer priced; sort by Points leaves it; no page errors.

### Fair odds: worst-case devig per side, everywhere
Vulture's Fair column doesn't mirror (CJ McCollum 3PM 2.5: sharp +132/−173 → Fair +153 / −147): each side is the lowest probability of four devigs (multiplicative +147/−147, additive and Shin +151/−151, power +153/−153; Over takes power, Under multiplicative, summing to 99.05%). Every place that turns a two-way price into fair probabilities now does the same:

- **`sgp.py`** — new `devig_worst(po, pu)`; a pair at or under 100% (Vulture's own Fair pair) is kept. `sides()` uses it when both prices are given (was: each raw implied as is, so a book's pair kept its vig). Reproduces Vulture's +153 / −147 from +132 / −173 exactly.
- **`price.py`** — a leg with both prices takes its own side's worst case (was: the pair rescaled to 100%, which sits between the two). The SKILL.md check (Lillard, Fair +101/−101, already 100%) is unchanged at +229.
- **`novig.py` / Novig legs** — the two sides' asks are the two-way price (the spread is its vig): fair O / U is their worst-case devig, a hair under the mid on a tight book.
- **Dashboard pricer** — each leg gets an optional **Under fair** box. Both boxes → worst case per side; Over only → Under is its complement (as before); game-log fallback unchanged. Fetch FV and the Novig chips fill both boxes; the note reads `PTS 11.5: o -102 / u +102 (worst case; mid 50.5%, …)`.

Verified: the JS `devigWorst` and Python `devig_worst` both give +153 / −147 from +132 / −173 and keep +153 / −147; in headless Chromium an REB pair +132 / −173 put 39.5% on the Over leg and 59.5% on the Under leg of the combos, Fetch FV filled all four boxes; no page errors, no horizontal overflow at 390 px.

### NBA dashboard: Novig note follows a chip click
Clicking a Novig chip moved the line and filled the fair odds, but the note above kept describing the old line ("PTS o20.5: no Novig line at 20.5" with 17.5 in use). The clicked leg's line in the note now reads like an auto-filled one: `PTS o11.5: -103 (mid 50.8%, 50.0–51.5, 1.5¢ wide)`, plus "mid is rough" for a wide book. Also checked by hand on a PTS 17.5 (−113) × AST 5.5 (−129), r −0.016 screen: all four combos match an independent `sgp.py` computation (+237 / +394 / +327 / +275), sum to 100%, and O/O + O/U equals the PTS Over.

### NBA dashboard: OUT players hidden, ESPN injury status on the rest
The page loads ESPN's league injury report (`site.api.espn.com/.../nba/injuries`, called from the browser like the scoreboard; keyed by the athlete id in each entry's player-card link, the same id as the data file). Status follows ESPN's player page: its label is `details.fantasyStatus` (GTD / OUT / OFS), which is the current one; a player ruled out of last night's game keeps `status: "Out"` but shows GTD for the next game, so `status` is only a fallback. **OUT, OFS (out for the season) and suspended players are always hidden**, in both Playing today and All players; a muted "N OUT hidden" note says how many. Everyone else on the report gets ESPN's dot and label next to the name (yellow GTD), with ESPN's note and estimated return on hover. If the report can't load, nobody is hidden.

Verified in headless Chromium with the live report (served from a curl copy: this container's proxy 403s browser requests to ESPN, the same reason the scoreboard fails here): 91 entries, 6 OUT hidden from today's slate and 51 from all players with none of them in the table, GTD rows badged (Jordan Poole: yellow GTD, as on ESPN); no page errors, no horizontal overflow at 390 px.

### NBA dashboard: SGP pricer beside the tiles
The SGP pricer moved into the prop builder's chart row: on a wide screen (about 1550px and up) it fills the empty space right of the quadrant tiles; narrower, it wraps under the chart at full width as before. The player panel is now pinned to the visible width on every screen, not only phones: the table is ~1780px wide, so on a laptop the panel (and anything on its right, like the pricer) ran off the edge. `--vw` (page width without the scrollbar) is set from JS on load and resize.

Verified in headless Chromium at 1880 / 1500 / 1300 / 1000 / 390 px: the pricer sits beside the tiles at 1880 and below the chart otherwise, the panel's right edge stays inside the viewport at every width, no horizontal page scroll, no page errors; Fetch FV and the per-combo SGP odds still work.

### NBA dashboard: SGP odds per combo
The pricer's single Payout box is gone: each of the four combo rows (O/O, U/U, O/U, U/O) has its own **SGP odds** input and EV, since a book prices each combo separately (e.g. PTS·REB O/O, PTS·AST O/U and U/O, PTS·3PM O/O). Prices take decimal (`4.14`, `4.14x`) or American (`+314`). Typing updates only that row's EV, so the box keeps focus. A new line or stat clears the prices, like it clears the leg fair odds. SGP odds and EV sit right after Fair odds so they're on screen on a phone.

Verified in headless Chromium: four different prices on Avdija PTS 22.5 × REB 6.5 gave EVs matching an independent computation (+9.8 / −5.2 / −8.6 / −6.5%), focus stayed in the input, a line change cleared them; no page errors, no horizontal overflow at 390 px.

### NBA dashboard: "Fetch FV" pulls the pricer's fair odds from Novig
The SGP pricer gets a **Fetch FV** button. It pulls Novig's open pregame NBA props straight from the browser (public catalog, CORS open, one pull cached for a minute across players) and fills each leg's Over fair odds with the exchange mid at the builder's line, same rule as `novig.py`: books wider than 4¢ are not used. When a line is missing, one-sided or too wide, the note under the inputs says so and lists Novig's lines as chips; a chip moves the line there and fills its fair odds. Wide books (over 4¢) are chips too, dashed and dimmed with their spread, since one is sometimes the only line near the slip's (Avdija PTS 14.5, 4.5¢); Fetch FV itself never fills from one. Game total / team / opp score legs say Novig doesn't list them.

Verified in headless Chromium against the live slate: Avdija PTS 9.5 (no Novig line) showed chips 19.5 / 22.5 / 23.5 / 24.5, REB o6.5 filled −112; the 22.5 chip set the line and −109 and priced Over/Over at +211, the same as `price.py`. No new page errors; no horizontal overflow at 390 px.

### nba-sgp-fv: pull leg fair values from Novig
`price.py` legs can now say `odds novig` (or just `novig`) instead of typing prices: `"pts over 22.5 novig"`. New `.claude/skills/nba-sgp-fv/novig.py` reads Novig's official public catalog (`GET https://api.novig.com/v3/public/catalog/markets`, no key, open pregame NBA POINTS / REBOUNDS / ASSISTS / THREE_POINTERS_MADE), one call per run. The fair value is the exchange mid: Over bid and Over ask (= 1 − Under bid), averaged; no vig to strip, and pregame markets charge no taker fee. Books wider than 4¢ (`--novig-spread`) are never priced from: the leg shifts from the nearest tight line through the existing `from` model, and the note says which line and spread it used. `novig.py "<player>" [stat] [line]` prints the ladder (bid, ask, mid, American both sides, spread, volume) for checking by hand. Novig's app shows asks, not fair values (Avdija O/U 14.5 91% / 15% = 106%); the API matched the app's ladder (lowest points line 14.5). Parlay multipliers still can't be pulled (the API prices parlays only via RFQ for registered market makers).

Verified live on the 10-29 slate: Avdija PTS O22.5 + REB O6.5 both priced at the line (0.5¢ and 1.5¢ wide); Sabonis PTS O16.5 (8¢ wide) fell back to 17.5 and shifted; three-leg Novig combo runs. The SKILL.md check (Lillard, hand odds) still gives +229 / 15.5% / $692.03 / 1.38u.

## 2026-10-27 session

### NBA tab: box stats + prop builder use all three seasons
The prop builder and the left box-stat columns now use every pulled season (2025 + 2026 + 2027, i.e. the last two seasons plus this one), not just the last two, with the same recency weights (0.15 / 0.35 / 0.50). Tatum goes from 19 games to 91. `recent_games` / `recent_seasons` now cover all three seasons; the scatter colors 2027 orange, 2026 blue, 2025 grey. JSON regenerated (17.7 MB raw, ~1.5 MB gzipped).

### NBA tab: game total, team score and opponent score vs REB
For SGPs like game Under + player REB Over. The game logs already carry the final score, so no extra requests.

- **`scripts/nba_fetch_correlations.py`** — every game gets `tot` (both teams, incl. OT), `tm` (his team) and `op` (opponent). New per-player `tot_reb` / `tm_reb` / `op_reb` (pooled, unweighted + recency-weighted, same shape as `pts_reb`), `tot_mean` / `tm_mean` / `op_mean`, and the same three r values per season. Games without a score are skipped for these only.
- **`public/nba.html`** — TOT·REB, TM·REB and OPP·REB r columns (sortable, also in the Sort menu and the per-season table). The prop builder's 1st stat can be Points, Game total, Team score or Opp score; the 2nd stat gains Points. Tooltips show the final score.
- `public/data/nba_correlations.json` regenerated (586 players).

### NBA tab: box stats + prop builder blend last season and this season, weighted
Three games into 2026-27, the left box-stat columns (G, Min, Pts, Reb, Ast, 3PM) and the prop builder were running on each player's latest season alone, so SGA showed **3** games. Both now blend last season and this season (the two newest seasons in the data: 2026 + 2027 in ESPN's naming), each game weighted by its season with the same per-game recency weights as the pooled r (0.35 / 0.50, so a 2027 game counts 1.4× a 2026 game). Early in the season last year carries the sample (SGA: 68 + 3 games, this season 6% of the weight), and the tilt moves to this season as games pile up. The r columns are unchanged (all three seasons pooled, 0.15 / 0.35 / 0.50).

- **`scripts/nba_fetch_correlations.py`** — `latest_games` → **`recent_games`**: the date-ordered game log for the last two seasons, each game tagged `s` (season). The payload gains `recent_seasons` (`[2026, 2027]`). Nothing else in the JSON changes.
- **`public/nba.html`** — box stats are weighted means over `recent_games` (no games in either season → "—", which the default Min mpg 20 hides); default prop lines follow the blended means; quadrant tiles show weighted hit rates (counts stay raw games), with fair odds from the weighted rate. The scatter draws last season in slate under this season in orange (a slate ring around an orange dot = both seasons landed on that score), with a legend and a subtitle giving games per season, the weight ratio and this season's current share. Text in the expanded row now wraps: it inherited the table's `nowrap`, and the longer subtitle ran off-screen.
- `public/data/nba_correlations.json` regenerated (592 players, same 50,973 game rows as the 10-26 file; 27,271 recent-season game rows, 7.8 MB raw / ~0.56 MB gzipped as served).

Verified: SGA's blended row (G 71, 33.4 min, 30.9 pts, 4.3 reb, 6.4 ast, 1.7 3PM) and all four tiles for PTS 30.5 × REB 3.5 and × AST 5.5 match an independent Python computation from the JSON. For every player, the latest-season games inside `recent_games` are identical to the previous `latest_games`, and every other per-player field is unchanged apart from the day's `playing_today` snapshot. In headless Chromium the page loads with no page errors, the desktop layout has no horizontal overflow, and at phone width the open builder scrolls no wider than before (1080 px vs 1213 px).

## 2026-10-20 session

### WNBA correlations tab → NBA
The WNBA tab is now **NBA**, same data and page: per-player PTS·REB / PTS·AST / PTS·3PM correlations (pooled, recency-weighted, Kish effective-N p-values), per-season history and the this-season prop builder. `scripts/wnba_fetch_correlations.py` → `scripts/nba_fetch_correlations.py` (ESPN `nba` endpoints; seasons default to 2025/2026/2027 with weights 0.15/0.35/0.50 — ESPN names a season by the year it ends, so 2027 = 2026-27). NBA gamelogs order columns differently (`MIN, FG, FG%, 3PT, …, REB, AST, …, PTS`), so the script now reads stat positions from each payload's `labels` instead of hard-coded indices. `public/wnba.html` → `public/nba.html`, data `public/data/nba_correlations.json` (WNBA JSON removed). In `index.html` the sport button reads NBA and deep-links as `?sport=nbacorr` (`?sport=nba` stays reserved for the hidden +EV Finder). The daily refresh workflow runs the NBA script instead of WNBA.

## 2026-09-16 session

### `DK_PROXY` sticky sessions + the cookie mint rides the proxy: one exit for the cookie and the POST
The 09-15 probe left one fact standing: from a datacenter IP, `calculateBets` 403s with a *validated* cookie, and the only lever is a different exit. The plan is a residential/mobile proxy through the existing `DK_PROXY` hook — but as wired, that could never have priced: `_mint_cookies_with_browser()` launched Chromium through the ambient `HTTPS_PROXY`, not `DK_PROXY`, so with both set the cookie was minted on one IP and POSTed from another (Akamai binds `_abck` to the minting IP). And server.js spawns a fresh `dk_api.py` per request, so with a *rotating* pool every subprocess would draw a new exit — and re-mint (~30-50s) each time, since the mint cache was in-process.

- **`dk_api.py` — sticky sessions.** `DK_PROXY` may carry a `{session}` placeholder where the provider's sticky token goes (Bright Data `-session-{session}`, Oxylabs `-sessid-{session}`, Decodo `-session-{session}`, IPRoyal `_session-{session}`; table in `LOCAL_RUN.md`). It resolves to **one** 8-hex id per host, kept in `DK_STATE_DIR` (owner-only file; default under the system temp dir), reused by every subprocess, re-drawn after `DK_PROXY_SESSION_TTL` (600s, inside every provider's sticky window) or when the proxy host changes, and pinnable with `DK_PROXY_SESSION`. With no writable state dir it falls back to a per-host deterministic id (never rotates, still one exit). curl_cffi sessions and the browser mint both read the *resolved* URL. Credentials never reach a diag or a log — `_proxy_host()` is the only printable form.
- **`dk_api.py` — the mint goes through `DK_PROXY`** (credentials split into Playwright's `username`/`password` — Chromium rejects them inline), falling back to `HTTPS_PROXY` only when no `DK_PROXY` is set. Minted cookies are cached in `DK_STATE_DIR` for `DK_COOKIE_BROWSER_TTL`, **keyed to the exit** (`host|session`), so the per-request subprocesses share one mint and a new session id invalidates the old jar.
- **`dk_api.py` — mint engines.** `DK_COOKIE_BROWSER_ENGINE` = `auto` (patchright if installed, else playwright) / `patchright` / `playwright` / `uc` (SeleniumBase undetected-chromedriver; `DK_COOKIE_BROWSER_HEADLESS=0` + `xvfb-run` on a server). Headless Chromium's `HeadlessChrome/…` UA — which DK's edge denies outright — is rewritten to `Chrome/…` with platform and version left truthful. The mint now nudges the page (mouse/scroll: the sensor posts after input events, not a bare load) and, if `_abck` hasn't validated halfway through `DK_COOKIE_BROWSER_WAIT` (30s), clicks through to `DK_COOKIE_BROWSER_PATH` (MLB league page) and keeps polling. Driver missing/crashing degrades to the warmup path as before, and says why.
- **Diag.** `sgp_price_diag` gains `proxy {host, sticky, session}` (host only) and `mint {engine, source: fresh|disk|unavailable|failed:<Type>|empty, abck, error}`. The soccer status line and the MLB empty state now distinguish "blocked *through* DK_PROXY" — sticky → the exit is scored too, try another pool/session; not pinned → the cookie and the POST left from different IPs, add `{session}` — from the plain "set a proxy" case.
- **`scripts/probe_dk_price.py`** — prints `DK_PROXY` host + stickiness (never the credentials; the old version echoed the raw URL), the mint engine, and a new **`--mint-only`** mode that mints and compares the browser's egress IP with curl_cffi's without touching `calculateBets` — the two must match or the cookie is bound to the wrong address. The 403-with-validated-cookie verdict now says which proxy variable to change.
- **`LOCAL_RUN.md`** — "Residential / mobile proxy": the three conditions (sticky; mobile > residential; cookie minted on the same exit), provider URL formats, the engine table, and a mint-only → real-probe recipe. `TESTING.md` lists the new smoke.

Verified: new `scripts/smoke_dk_proxy_mint.py` (54 checks: session id reuse across a module reload, TTL/host-change re-draw, pin, no credential leaks, browser proxy kwarg, DK_PROXY-over-HTTPS_PROXY, engine selection, and a mint through a fake driver — proxy at launch, UA rewrite, second-page hop, disk cache reuse without a launch, exit-change re-mint, failure → None with the message in the diag); the breaker, TLS-rotation and soccer smokes still pass; frontend scripts parse. Live from this container (homepage loads only, no wager calls): patchright headless and SeleniumBase UC headed under Xvfb both load the sportsbook and cache a jar (14 and 20 cookies) with `_abck` **unvalidated** — the same result as the 09-15 plain-Playwright mint, which is the expected shape for a scored IP and the reason the exit, not the engine, is the variable. `probe_dk_price.py --mint-only` from here also caught a mismatch the old probe couldn't see: this container's egress is a NAT *pool* — the browser left from `.135`, curl_cffi from `.136` — so even a cookie that had validated here would have been presented from the wrong IP; the same trap a rotating proxy sets. The proxy path itself can't be exercised from here (egress is 443-only, provider ports aren't reachable) — run `probe_dk_price.py --mint-only` from Railway or a laptop with a real `DK_PROXY`.

Also for the record: open PR #89 (July) proposed the same shape — mint through `DK_PROXY`, sticky session — on a base that predates the `DK_PROXY` hook and the mint in `main`; this entry supersedes it.

## 2026-09-15 session

### `scripts/probe_dk_price.py`: a one-command yes/no for "can this VPN / proxy price DK SGPs?"
Trying to pull an MLB pitcher SGP from a cloud container reproduced the known shape exactly — `games` and `markets` fine (full 15-game slate, 265 pitcher props on LAD@CIN), every `calculateBets` POST `403 Access Denied` on every state host, `abck=unvalidated`. That combination is ambiguous by construction: an unvalidated cookie 403s on *any* IP, so the bare failure says nothing about whether a VPN would help, and the next question was "how do we test one?".

- **`scripts/probe_dk_price.py`** — runs one real 2-leg cross-stat pitcher SGP (K Over + ER Under on the first SGP-eligible starter, or a named one: `probe_dk_price.py Yamamoto`) through the same curl_cffi session as the app, so `DK_PROXY`, the TLS profile and the cookie sources all apply, and prints the egress IP as DK sees it, the cookie source actually used, the `_abck` state and a verdict: **PASS** (priced, or the endpoint answered with a combinability rejection), **FAIL (403, cookie validated)** — the IP is scored, only the egress can change it — or **FAIL (403, _abck unvalidated)** — not a verdict on the IP yet, with the paste-a-cookie-on-the-same-VPN steps. Exit 0 / 2 / 1.
- **`LOCAL_RUN.md`** — "Testing whether a VPN / proxy can price DK SGPs": the four-step recipe (VPN → bare probe → mint a validated cookie in a normal browser *on the same egress* → `DK_COOKIES=… probe`) and a verdict table.

Findings from this container, for the record: curl_cffi with the `chrome` profile gets `200` on the sportsbook HTML while the wager POST 403s; headless Chromium via Playwright is denied at the homepage outright with the default UA, and with a normal UA loads the page (13 cookies) but `_abck` never leaves `-1` — so `DK_COOKIE_BROWSER` cannot mint from a flagged IP and the probe now says so when that fallback happens. The container also only has direct egress on 443, so a residential `DK_PROXY` used *from here* has to listen on 443; a home machine on a VPN has no such limit.

### `scripts/dk_live_feed.py`: DK's live game-state socket, straight from the source
DK's event/live pages don't scrape scores — they hold a JSON-RPC 2.0 websocket to `wss://sportsbook-ws-us-<state>.draftkings.com/websocket` (the `SportsbookLeague` class in `@draftkings/dk-data-layer`), one `subscribe` per query (`entity: events`, `queryParams: {query: "$filter=leagueId eq '84240'", initialData, projection: "sportsbook", locale}`), then a stream of `update` messages with `add/change/remove` of events, markets and selections. It is the public sports-data socket, not the Akamai-gated wager endpoint: no cookie, no residential IP, no 403 from a cloud container.

- **`scripts/dk_live_feed.py`** — subscribes to a league (default MLB) or one `--event`, reconnects with backoff, and prints one JSON row per live-state change. Verified at first pitch on LAD@CIN: for MLB `eventStatus` stays null and the state rides on **`eventScore`** — `metadata {atBat, balls, strikes, outs, bases:"100", *CurrentBatter ids}`, per-inning `gamePartScores`, `mainScore` — which the script folds into a compact `state {inning, half, outs, balls, strikes, bases, score, batter}` per row (observed pitch-by-pitch, ~1 row per pitch). `--markets` adds `queryParams.includeMarkets` so the event's markets stream too, each with `statistics.live[] = {type:"MarketStat", prefix:"Current", value}` — the running per-prop stat (observed: `Rhett Lowder Strikeouts Thrown O/U → Current 1`). `--raw` dumps every message.

Also checked and ruled out for MLB: **Simplebet** (DK-owned play-by-play; a Phoenix socket at `api.simplebet.io/play-by-play` reachable with the public `api_key` in DK's page config — `get_matches` lists NFL and CFB only, no MLB) and **Sportradar** (the match-tracker widget; its `licensing` response is an encrypted blob the widget decrypts client-side — a licensed feed, left alone).

## 2026-09-03 session

### DK soccer lines: scraping works again on egress paths that reset the "chrome" TLS profile
Symptom: the soccer sweep — and every other DK call — died after ~30s with `curl: (35) Recv failure: Connection reset by peer`, even though DK itself was reachable: the games feed answered 200 the moment a different fingerprint was used. The root cause was in our retry layer, not at DK. `_IMPERSONATES` leads with the newest `chrome` profile (deliberately — Akamai 503s the pinned versions on some IPs), some intermediaries reset that ClientHello at the transport layer before any HTTP happens, and `_get_with_retry_inner` / `_post_with_retry` / `_pin_get` only rotated the fingerprint on a 403 *status*. A reset arrives as an *exception*, so every attempt re-sent on the same dead profile and the scrape could never reach the profiles that work.

- **`dk_api.py`** — a profile fault (curl 35/55/56, `ImpersonateError`) now **retires** that fingerprint for the process (`_dead_profiles`) and rotates immediately, without charging the attempt — so the sweep's per-league `attempts=2` still reaches a live profile. Retired profiles are skipped by every later rotation (403-driven ones and wrap-around included); if every profile dies the set clears so we cycle rather than deadlock. Timeouts, DNS and refused stay transient (same profile, normal backoff). Each session is tagged with its profile so a worker thread retires the one *it* failed on, not whichever is current when it reports back. The homepage cookie warmup retires a reset profile too, so the first market GET doesn't rediscover it. `_IMPERSONATES` order is unchanged — the Akamai rationale still holds and runtime retirement makes it safe on any network — and `DK_IMPERSONATE` still pins the list outright.
- **Diag** — `sgp_price_diag` now also carries `tls_profile` (what the shared session speaks) and `dead_profiles` (what this process gave up on), so an empty +EV state can be told apart from a cookie problem without shell access.

Verified: new `scripts/smoke_dk_tls_rotation.py` (fault classifier, no-attempt-cost retirement, wrap-around skipping, timeout-is-transient, all-dead termination, thread-race no-op, POST/Pinnacle/warmup parity, diag); the existing EPL + sweep smokes still pass; and live with the **default** config (no env pin) the previously failing EPL games call returns the full slate, with a multi-league sweep rendering the Pinnacle fair board and resolving DK legs. Also confirmed live in passing: all 13 league ids in the registry still resolve to the right DK competitions (SGP-tagged games in every one), the per-event market feed still parses every soccer kind, and Pinnacle's combo groups (BTTS×Total, BTTS×Winner, Winner×Total, Odd/Even×Total, HT/FT) all devig with 20/20 club names matching across books.

### calculateBets circuit breaker: a blocked IP fails fast and says so
With the transport fixed, real DK SGP prices came back (verified live: `BTTS Yes + Over 2.5` on Ipswich @ Liverpool priced at `−135`). But on a *flagged* IP every pricing POST 403s even with a validated cookie, and the sweep prices ~30 combos × 4 retries behind a 95s deadline — so it spent the whole budget re-POSTing into the block and then labelled the rows **`deadline`**, which reads as "slow, try again" when the truth is "this IP can't price, set `DK_PROXY`". Measured before: 27 of 29 calls 403, 103s elapsed, 87 rows marked `deadline`.

- **`dk_api.py`** — a breaker trips after `DK_PRICE_BREAKER_403S` (default 12, `0` disables) **consecutive** pricing 403s, after which `_price_combo` returns without a POST and `_post_with_retry` abandons its remaining attempts. Crucially **any served response clears the streak**, so an IP that is merely rate-limited — a couple through, then a burst of 403s — keeps pricing instead of being written off; that distinction is what stops the breaker from costing real prices. `_price_event_combos` skips building its thread pool when already tripped, and the sweep stops fetching further games' markets once it's clear nothing can price. Rows whose legs resolved but which DK refused to price now report **`pricing_blocked`** rather than `no_match` (a leg-matching failure) or `deadline` (a timing failure) — only `pricing_blocked` is the one a proxy fixes. Diag gains `breaker_tripped` + `skipped_blocked`.
- **Frontend** (`worldcupEvTab.js`) — the status line now distinguishes *partial* pricing (some combos priced, then 403s cut it short → amber, names the unpriced count) from a *hard* block, and notes that the scrape stopped early rather than grinding through every combo. Previously "priced 2 combo(s)" next to 116 rows implied the other 114 simply hadn't matched.

Verified: new `scripts/smoke_dk_price_breaker.py` (20 checks incl. the streak-reset case, non-pricing hosts not gated, breaker disabled via env, and an end-to-end hard-blocked sweep that keeps every Pinnacle fair line and reports `pricing_blocked`); all existing guards still pass.

### Run it locally: auto-detected Python interpreter + `LOCAL_RUN.md`
Running the app on a home machine sidesteps both DK obstacles at once — a residential IP isn't carrying the datacenter penalty, and the `_abck` cookie is presented from the same IP that earned it (pasting a browser cookie into a server in another state is itself a signal Akamai looks for). The soccer tab needs no local data files; it fetches Pinnacle and DK live per scrape.

- **`server.js`** — the Python helpers were spawned as a hard-coded `python3`. On Windows the launcher is normally `python`, and a bare `python3` can hit the Microsoft Store stub, which surfaced only as an opaque `dk_api.py exited with code 9009`. The interpreter is now resolved once at boot — `PYTHON` env wins, else platform-appropriate candidates (`python`,`python3`,`py` on Windows; `python3`,`python` elsewhere), probed with `--version` and requiring `status === 0` so the Store stub is rejected rather than selected — and logged on startup. Both spawn sites (`dkCall`, the NBA correlations parser) use it.
- **`LOCAL_RUN.md`** — setup, per-platform pip/interpreter gotchas, the cookie walkthrough, a status-line table, the env-var reference, and the no-auth security note.

Verified end-to-end on a real local boot (`npm ci && npm start`): interpreter resolved and logged, `/api/soccer/leagues` and `/api/soccer/scrape-all` both spawn correctly, and the no-cookie sweep now returns in **22s instead of 103s** with all 87 rows carrying Pinnacle fair lines and reporting `pricing_blocked` (8 pricing calls, 21 skipped by the breaker, vs 29 calls before).

**Unchanged, and worth restating:** `calculateBets` still sits behind Akamai's *validated* `_abck` gate — from a datacenter egress it 403s with `abck=unvalidated`, exactly as documented in the 2026-08 entries. So without a cookie the sweep shows Pinnacle fair lines with DK legs resolved but no combined DK SGP price; paste `DK_COOKIES` (soccer tab → DK cookie box) and real pricing layers in. Nothing in this change touches that gate.

## 2026-08-24 session

### Soccer: one-button "Scrape SGPs" sweep across all major leagues
Replaced the pick-a-league / load-slate / pick-a-game flow with a single **SCRAPE SGPS** button that sweeps every major soccer league at once and lists all combo SGPs (BTTS×Total, BTTS×Winner, Winner×Total, Odd/Even×Total, HT/FT) DK-vs-Pinnacle in one EV-ranked table. No league or game picking; World Cup / league selector / match dropdown / DK-league-id box all removed.

- **`dk_api.py`** — league registry expanded to the major leagues (EPL, La Liga, Serie A, Bundesliga, Ligue 1, UCL, Eredivisie, Primeira, Championship, MLS, Liga MX, Brasileirão, Saudi PL) with DK + Pinnacle ids (per-league env overrides `DK_LEAGUE_ID_<KEY>` / `PIN_LEAGUE_ID_<KEY>`; sweep set via `SOCCER_LEAGUES_SWEEP`). New `find_sgps_soccer_all()`: Phase 1 pull Pinnacle games per league (concurrent, upcoming within `window_hours`, capped at `max_games`), Phase 2 devig each game's combo specials into fair lines, Phase 3 best-effort DK match + real 2-leg SGP pricing under a shared deadline. The per-event match+price body was factored into `_price_event_combos()` shared with `find_sgps_worldcup`.
- **DK-block resilience** — DK games are fetched per league with a short retry budget; the first Akamai 403 with no prior success sets `dk_blocked` and skips DK for the rest, so a flagged IP fails fast and the **Pinnacle fair board still renders for every game** (DK column just stays empty). DK-bound GETs now also carry the `DK_COOKIES` jar (some IPs 403 the market GETs too, not just pricing). New `DK_IMPERSONATE` env pins the curl_cffi TLS profile list when an egress path rejects the newest "chrome" fingerprint.
- **`server.js`** — `POST /api/soccer/scrape-all` (cached 2 min; busted when the DK cookie changes).
- **Frontend** — the soccer tab is now one SCRAPE SGPS button + a flat table (Game/Market/Selection/PIN/FAIR/DK SGP/EV%/Kelly), combo-family filter chips, SGP-ONLY, DK-PRICED-ONLY (off by default), ≤+1000, plus the existing DK-cookie box and pricing status line.

Verified: `scripts/smoke_soccer_sweep.py` (aggregation, EV ranking, DK-up/down, dk_blocked degradation) and a live 3-league sweep (58 combos across 5 families, full Pinnacle fair board, graceful DK statuses). Existing MLB + EPL smokes still pass.

### Optional DK proxy (`DK_PROXY`) for IP-blocked deployments
When DK's Akamai edge scores a deployment's datacenter IP and 403s even with a valid cookie (observed on Railway — the market GETs 403 too, not just pricing), set `DK_PROXY` to a residential/rotating proxy URL (`http://user:pass@host:port`) and all DK/Pinnacle curl_cffi traffic routes through it. Empty (default) = direct, no behavior change. Plumbed through initial session creation and `_rotate_session` via a `_new_session()` helper; verified routing end-to-end.

## 2026-08-22 session

### Soccer SGP +EV: multi-league support (EPL added), DK vs Pinnacle
The soccer tab (previously World Cup–only) now works for any soccer league via a **league picker**. Added **English Premier League** — DK eventGroup **40253**, Pinnacle league **1980** — verified live against today's slate.

The whole soccer engine (DK combo grammar + Pinnacle devig) was already league-agnostic; only the league IDs and club naming differed. Changes:
- **`dk_api.py`** — new `SOCCER_LEAGUES` registry (`worldcup`, `epl`; env-overridable ids) + `_soccer_league()` resolver. `get_games_soccer` / `pinnacle_wc_games` / `find_sgps_worldcup` accept a `league` key. New `soccer-leagues` CLI command returns the registry. Added `_SOCCER_CLUB_ALIASES` so DK short forms match Pinnacle long forms (Man City↔Manchester City, Wolves↔Wolverhampton, Spurs↔Tottenham, …) — without it, e.g. Bournemouth @ Manchester City failed to match between books.
- **HT/FT prebuilt fix** — DK's EPL "Half Time / Full Time" selections leave `label` null and put the paired result ("Nottingham Forest/Leeds") only in the bet-slip line; the World Cup format put it in the label. `get_markets` now carries `betslipLine` on each prop and the `ht_ft` matcher falls back to it, so EPL HT/FT combos match DK's posted price **with no `calculateBets` call** (cookie-free).
- **`server.js`** — `/api/pinnacle/worldcup-games` takes `?league=<key>`/`?leagueId=<id>` and league-keys its cache; new `/api/soccer/leagues` serves the registry; `find-sgps-worldcup` cache key includes the league.
- **Frontend** — league `<select>` in the soccer tab (populated from `/api/soccer/leagues`), passed to both the Pinnacle slate pull and the DK scan. Tab relabeled World Cup → Soccer.

Verified offline via `scripts/smoke_soccer_epl.py` (+ trimmed fixture): registry resolution, club aliases, BTTS/Total leg resolution, and cookie-free HT/FT prebuilt matching against Pinnacle candidates.

**Caveat — the combined DK price for BTTS + Over 2.5:** unlike the World Cup, DK does **not** prebuild "BTTS & Total" / "Result & Total" combos for EPL (only HT/FT). Those combos' legs resolve fine, but the correlated combined DK price comes from `calculateBets`, which is behind the same Akamai validated-cookie gate as MLB pricing — so from a datacenter IP it needs `DK_COOKIES`. Without it, EPL shows Pinnacle fair lines + DK's prebuilt HT/FT combos + individual leg prices; with it, the full BTTS+O2.5 SGP is priced and compared.

### Soccer: SGP-only mode (default on) — real SGPs only, no prebuilt combos
For a DK SGP promo, only an *actual Same Game Parlay* qualifies — DK's prebuilt straight combo markets (BTTS & Total, HT/FT listed as one market) don't count even though they represent the same joint outcome. Added an **`sgp_only`** flag to `find_sgps_worldcup` (and an **SGP ONLY** toggle in the soccer tab, default on): when set, a combo counts as matched only if it priced as a real 2-leg SGP via `calculateBets`; the prebuilt-combo fallback is suppressed and such rows report why. Toggling it re-scans DK (it changes the server response, not just a client filter).

Consequence: in SGP-only mode the soccer tab needs DK's SGP pricing reachable — i.e. `DK_COOKIES` set (the same no-VPN path as MLB) — or it returns no priced combos. Turn SGP ONLY off to fall back to DK's prebuilt combos (useful for reference / World Cup knockout slates), but those won't satisfy an SGP promo.

### DK cookie set from the website + SGP pricing status line
Two additions so the DK SGP cookie can be managed without a Railway redeploy:
- **Status line** (soccer tab): reads the `sgp_price_diag` the scan already returns and shows, in plain English, whether DK SGP pricing is live (green: N combos priced), blocked (red: Akamai 403 + `_abck` missing/unvalidated → set/refresh the cookie), IP-flagged (amber: 403 despite a validated cookie → residential proxy needed), or leg-incompatible (info).
- **Paste-in cookie** (soccer tab): a collapsible "DK cookie" box. Paste `document.cookie` from draftkings.com, Save → `POST /api/dk/cookies`. The server holds it **in memory only** (never logged, never written to disk, never echoed back) and injects it into the `dk_api.py` pricing subprocess env, overriding the `DK_COOKIES` env var for that call. Saving busts the DK scan cache and re-prices loaded games; the box summary shows current cookie health (`validated` / `unvalidated` / not set) via `GET /api/dk/cookies`, and CLEAR (`DELETE /api/dk/cookies`) reverts to the env var. Re-paste after a container restart or when the cookie expires (a few hours). Verified end-to-end locally: POST/GET/DELETE behavior, `_abck` state parsing, and that an injected cookie reaches dk_api as `cookie_source=env, _abck=validated`.

Note: the app has no auth (same as all its routes), so only expose the deployment to people you'd trust with your DK session.


### DK API migration: games + markets restored after DK retired the nav/controldata endpoints
DK prices stopped resolving because DraftKings retired two of the three endpoints the tool depended on. The old games feed (`.../sportscontent/navigation/dkusnj/v1/nav/leagues/{id}`) and the per-subcategory market feed (`.../sportscontent/controldata/event/eventSubcategory/v1/markets`) now return **404**. The per-event SGP feed (`.../sportscontent/parlays/v1/sgp/events/{id}`) still serves **200**.

Fix (`dk_api.py`):
- **Games** now come from the sportscontent leagues route `.../sportscontent/<site>/v1/leagues/{id}` (`DK_LEAGUES`; `DK_SITE` env, default `dkusnj`). Event ids/start times moved fields (`eventId`→`id`, `startDate`→`startEventDate`); parsing accepts both via `_ev_id`/`_ev_start`. Bonus: MLB games now expose each starter's name (`homeStarter`/`awayStarter`) from participant metadata. All five game functions (MLB, NBA, tennis, World Cup) were on the dead endpoint and are repointed.
- **Markets** now come entirely from the still-live SGP feed, which embeds every SGP-eligible market's selections + odds inline. `get_markets()` filters that single response by subcategory in memory instead of fanning out ~100 parallel per-subcategory GETs to the retired controldata endpoint. One request per event is also far friendlier to Akamai's rate limiter. The `props` output shape is byte-for-byte unchanged, so leg-matching (`_match_leg_to_dk`), `find_sgps`, and the frontend are untouched. Dead `_fetch_subcategory` + `DK_MARKETS` removed.
- Verified offline against a live-captured feed fixture: `get_markets(pitcher_only=True)` returns both starters' complete Over/Under legs (K, ER, Hits Allowed, Outs, Walks) with valid `calculateBets` selection ids and decimal odds; milestone (X-or-Fewer) legs parse their thresholds; `_match_leg_to_dk` resolves all sample OCR legs to selection ids.

**Still pending, unchanged by this fix:** the combined correlated SGP price comes from `calculateBets`, which sits behind Akamai Bot Manager and requires a *validated* `_abck` cookie. From a datacenter IP that POST still 403s (documented at length in the 2026-07 entries below). The no-VPN path is the existing `DK_COOKIES` env — paste a fresh validated cookie string from a logged-out browser in a legal state — after which pricing resumes on top of the now-working market data. Per-leg DK prices themselves need no cookie and work again immediately.

## 2026-07-06 session

### MLB +EV finder: FV-only fallback when DK prices can't be pulled ("screenshot mode")
When every DK SGP price fails — calculateBets 403 storm, DK games endpoint down, or a network error — the pitcher +EV finder no longer dead-ends at a diagnostic empty state. It now computes the **fair value of each SGP straight from the uploaded screenshot**: per-leg `avg_fv` (already OCR'd) → implied probabilities → the same pairwise-Fréchet correlation correction the priced path uses (`evComputeCombo` with `dkDecimal=null`), rendered as FV-only cards **sorted by FV odds low → high** (biggest favorites first). Cards show FV CORR, FV INDEP, binary-phi R, per-leg/combined historical hit rates, and the blend-transparency line; EV%, Kelly, and DK-price columns are omitted because there is no DK price to beat — the FV is presented as the price to beat. Works in both 2-leg and 3-leg modes (3-leg cards add the shrunk empirical MODEL joint when the triplet exists in the aggregates), and re-resolves live on GLOBAL/BLENDED/PLAYER toggles.

Combo enumeration happens client-side since DK can't be asked: cross-stat combos are always legal (mirrors what `find_sgps` enumerates and DK accepts), same-stat combos only when they appear verbatim in `combo_spec.json` — which admits the Over-K-style ladders and rejects contradictory Over/Under of the same leg. The whitelist ships to the client via a new `GET /api/combo-spec` endpoint; if that fetch fails, same-stat ladders are conservatively dropped while all cross-stat combos still render. The fallback only engages when DK priced **zero** combos — if DK priced some and render filters hid them, the filters remain the message. Pure helpers (enumeration, legality, low→high sort) live in `public/utils/fvFallback.js` (UMD, Node-testable); guarded by `scripts/smoke_fv_fallback.js` (fixture = the 07/06 NYY@TB Schlittler/Jax sheet).

### WNBA prop builder: this-season two-stat scatter per player
Clicking a player on the WNBA page now opens a prop builder above the per-season history: set a PTS line and a second-stat line (REB by default; AST/3PM selectable) and get a scatter of **every game this season only** (one dot per game, dots grow when multiple games land on the same score), the two lines drawn in red, and four tiles showing how often each over/under combo hit (count, %, and the fair American odds that hit rate implies — TacoBot-style). Over = strictly greater; games landing exactly on an integer line count as pushes and are excluded (noted when present). Line inputs redraw just the chart, so typing keeps focus; per-player settings survive re-renders. Data side: `scripts/wnba_fetch_correlations.py` now emits `latest_games` per player — the full date-ordered current-season game log (date, opponent, home/away, W/L, min/pts/reb/ast/3pm) taken from the same ESPN gamelog payload — and `public/data/wnba_correlations.json` was regenerated (195 players through 2026-07-05, ~1.1 MB).

## 2026-07-05 session (later)

### calculateBets 403 root cause: unvalidated Akamai `_abck` + validated-cookie provider
Rounds 1–2 (retries, browser headers, homepage warmup, host override) didn't stop the 403 storm because they targeted the wrong layer. Reproduced end-to-end: market GETs on `sportsbook-nash` return 200 and legs match fine, but every `calculateBets` POST to `gaming-us-*` returns an **Akamai edge 403** ("AkamaiGHost / Access Denied") — instantly, on the first attempt, identically across all six state hosts. Root cause: the homepage warmup collects an **unvalidated** `_abck` cookie (its 2nd `~`-field is `-1`). Akamai Bot Manager only flips `_abck` to *validated* after its in-page sensor JS POSTs telemetry back — which curl_cffi can't run. The market GETs don't enforce validation (so they work); the wager POST does (so it 403s). No header/cookie/host/fingerprint permutation fixes this from a plain HTTP client.

Added a validated-cookie provider for the pricing POST (`dk_api.py`), tried highest-priority first:
1. `DK_COOKIES` env — a raw `name=value; name=value` string pasted from a logged-out browser (must include a validated `_abck`). Immediate stopgap; refresh when it expires.
2. `DK_COOKIE_BROWSER=1` — mint cookies with a headless browser that runs the sensor JS, cached with `DK_COOKIE_BROWSER_TTL` (default 600s) and re-minted when stale. Durable, but requires Playwright + a Chromium build in the image (point `DK_CHROMIUM_PATH` at the binary if needed); off by default and lazy-imported, so it's a no-op unless enabled.
3. homepage warmup (legacy) — unchanged, kept as the last-ditch fallback.

Injected cookies are `.draftkings.com`-scoped so they ride to the gaming-us host and survive `_rotate_session()`. The `_abck` validation state and the cookie source are now recorded on `sgp_price_diag`, and the +EV empty state reads them: on a 403 with an unvalidated `_abck` it now says the block is Akamai bot protection fixable via `DK_COOKIES`/`DK_COOKIE_BROWSER`, instead of the misleading "try again in a few minutes."

> Note: from a datacenter IP, even a validated `_abck` may not be enough if DK is also scoring the egress IP — if `DK_COOKIES` with a fresh validated cookie still 403s in prod, the next lever is a residential/rotating proxy for the pricing POST.

### calculateBets Akamai hardening (round 2 — prod diag showed HTTP 403 ×57)
The retry fix alone wasn't enough: prod diagnostics showed all 57 pricing POSTs 403-ing while market GETs (different host) worked. The pricing POST looked exactly like a bot to Akamai: no Origin/Referer, no `.draftkings.com` cookies (market traffic lives on `sportsbook-nash`, cookies are domain-scoped), and every fingerprint rotation discarded whatever cookies existed. Now: (1) calculateBets POSTs send browser headers (`Origin`/`Referer: sportsbook.draftkings.com`, Accept, Accept-Language); (2) a one-time best-effort GET of the sportsbook homepage collects Akamai clearance cookies into the shared jar before the first pricing call; (3) `_rotate_session()` carries the cookie jar into the new session; (4) `DK_PRICE_HOST` env var switches the state pricing host (e.g. `gaming-us-ny.draftkings.com`) from Railway without a code change — the NJ host being blocked doesn't mean the others are.

### MLB SGP pricing fix: calculateBets retries + diagnosable empty state
The +EV Finder showed "No SGPs could be priced" with legs matched fine — the 2026-07-04 calculateBets outage pattern. Root cause candidate: every DK **GET** goes through `_get_with_retry` (fingerprint rotation, cool-off, backoff), but the pricing **POSTs** in `_price_combo`/`get_price` were single bare `session.post()` calls — first Akamai 403 killed every price call while market fetches recovered by rotating. New `_post_with_retry` gives POSTs the same survival kit (retries only 403/429/5xx; 422/400 pass through so incompatible-leg semantics are unchanged; exhaustion returns the last response so `_PRICE_DIAG` status tallies still work). `find_sgps` (MLB) now returns `sgp_price_diag` like the World Cup path, and the frontend empty state renders the actual failure mode ("calculateBets rejected all 20 attempts (HTTP 403 ×18…)") instead of the generic guess list.

### Claude model bump
OCR/vision extraction endpoints (`server.js` ×4) moved `claude-opus-4-7` → `claude-opus-4-8` (same API surface, better vision/knowledge-work). The leg-normalization call already uses `claude-haiku-4-5-20251001`, which is the newest Haiku.

### WNBA correlations refreshed + daily auto-refresh workflow
`public/data/wnba_correlations.json` regenerated via `scripts/wnba_fetch_correlations.py` (was stale since 2026-06-22; now 195 players through 2026-07-04). New `.github/workflows/refresh-data.yml` runs daily at 11:00 UTC (after West Coast games go final) and on manual dispatch: ESPN pitcher fetch → `build_pitcher_data.py` (supplement merge + dedupe) → `build_aggregates.py` → WNBA correlations, then auto-commits `espn-2026-pitcher-supplement.json` + `public/data/*.json` only if something changed. Dedupe lives in the build script, so scheduled re-runs can never double-count a start.

### 2026 pitcher data refreshed through July 4 via ESPN (no double counting)
The 2026 xlsx feed ended 2026-05-15. New `scripts/fetch_espn_2026_pitchers.py` pulls every completed regular-season game from ESPN's public site API for a date window (default 2026-05-16 .. today) and writes starting-pitcher lines to `espn-2026-pitcher-supplement.json` in the same schema as `pitchers_YYYY.json`. `build_pitcher_data.py` merges the supplement into `pitchers_2026.json`, deduping by (pitcher name, date) with the xlsx winning on conflict, so re-running either script never double-counts a start. `pitchers_2026.json`: 1,337 → **2,663 starts** (2026-03-25 .. 2026-07-04); all per-year and pooled aggregates rebuilt.

**Validation.** On xlsx-covered dates (5/14–5/15) the ESPN extraction matched the feed 52/52 rows exactly on every shared field (IP, H, ER, BB, K, HR, W/L, QS, hand, venue, team names — ESPN names are accent-stripped to the feed's spelling, e.g. "Jesus Luzardo").

**ESPN traps encoded in the fetcher.** The boxscore `starter` flag marks anyone who *started the game*, including position players who mopped up blowouts (catcher Carson Kelly, SS Miguel Rojas) and sometimes random relievers; and the pitching list can mis-sort a position-player pitcher above the real starter (RF Carlos Cortes listed first in 401815762 — play-by-play shows Jeffrey Springs started). The starter is therefore the first entry in the pitching group whose `position` is an actual pitcher; openers (RP) genuinely start and are kept, matching the xlsx `STARTING PITCHER == YES` semantics.

**Field coverage.** `bf` / `gb` / `fb` aren't in ESPN box scores → null (nothing downstream reads them; correlations use only K/ER/BB/H-allowed/IP→outs). `pid` and throwing hand are reused from existing rows by name; new call-ups get the ESPN athlete id and the core-API `throws` hand. `qs` derived (outs ≥ 18 and ER ≤ 3), W/L from the `pitchingDecision` note, `gid` is `espn-<eventId>`.

## 2026-07-04 session

### World Cup combos: prebuilt fallback + knockout-slate fixes ("no match" everywhere)
Every combo market (Winner/Total, HT/FT, BTTS/Winner, BTTS/Total) showed `no match` on knockout-round matches. Three stacked causes, verified against the live Canada vs Morocco event (34339353):
1. **DK's `calculateBets` endpoint is failing for every request** (MLB pairs too, so it's not soccer-specific) — every combo whose SGP legs resolved died with `sgp_price_unavailable`.
2. **Knockout slates drop the SGP leg markets**: no regular-time `Both Teams to Score` (only the "Including Extra Time" variant, a different proposition) and no 1st-half Moneyline — so BTTS/Winner, BTTS/Total and HT/FT legs can't even be built.
3. The 2026-06 change made combos **hand-built SGPs only, no prebuilt fallback** — so when 1+2 hit, everything reported unmatched even though DK posts prebuilt `Half Time / Full Time` (9 sels) and `Moneyline / Both Teams to Score` (6 sels) on the same event.

**Fix (dk_api.py).** `find_sgps_worldcup` is SGP-first as before, but now falls back to the prebuilt combo market when a leg can't resolve or pricing fails (`via: "prebuilt"`, so the UI's SGP badge still only marks real tickets). Replayed against the live event dump: 55/97 → **72/97** matched with pricing down (HT/FT 9/9, BTTS/Winner 6/6 restored), 82/97 once `calculateBets` recovers (Winner/Total + Odd-Even/Total upgrade to `via: "sgp"`). Remaining misses are genuine DK absences on knockout slates (no regular-time BTTS or team-total-goals markets, unlisted lines/bands).

**Also fixed.**
- `_soccer_straight_kind`: alternate spread lines (±1.5, ±2.5) live under a subcat literally named `Spread`, not `Asian Handicap` — both now classify, restoring the alt-line spread rows.
- `_price_combo` now tallies outcomes (HTTP status counts, incompatible, no-bet, exceptions) into `_PRICE_DIAG`; `find_sgps_worldcup` returns the snapshot as `sgp_price_diag` so a pricing outage is diagnosable from the API response.
- `get_price` returns `{"error": "calculateBets HTTP <status>", "status", "body"}` instead of raising, and `dkCall` (server.js) surfaces the JSON error dk_api.py prints on exit 1 instead of the opaque `dk_api.py exited with code 1` — `/api/dk/price` now reports the real failure mode.

## 2026-06-11 session

### World Cup SGP +EV tab
New top-level sport (`WORLD CUP` in the `.sport-bar`) for soccer same-game-parlay combo markets at the FIFA World Cup. Unlike tennis/NBA there is **no correlation model**: Pinnacle prices each joint outcome directly, so the fair probability is a straight multiplicative devig of each combo market group (every group is a mutually exclusive, exhaustive partition).

**Markets.** `Both Teams To Score/Total Goals`, `Both Teams To Score/Winner`, `Winner/Total Goals` (the mains), plus `Half-Time/Full-Time` and `Odd/Even / Total Goals` as bonus combos. Correct-score / exact-total-style markets are ignored by design.

**Inputs (two paths, one client code path).**
- *Live pull (primary)* — `LOAD SLATE` hits Pinnacle's guest API (`guest.api.arcadia.pinnacle.com`, static guest key, via the same curl_cffi Chrome-TLS session that talks to DK) and lists all World Cup matches; picking one fetches its special markets live. League 2686, override via `PINNACLE_WC_LEAGUE_ID`.
- *PDF upload (fallback)* — print the Pinnacle match page to PDF and drop it on the tab. `POST /api/extract-worldcup-pdf` (multer + `pdf-parse`, new dep) extracts the text layer; `pinnacleSoccer.js` tokenizes it (American-odds tokens terminate selection names, icon-font PUA glyphs stripped) into the same `{home, away, kickoff, markets}` shape.

**DK side.** No SGP pricing engine needed — DK lists these combos as straight markets. `find_sgps_worldcup` (dk_api.py) resolves the league (env `DK_WORLDCUP_LEAGUE_ID`, else scrapes slug `world-cup-2026`; live id 209533), matches the event by team names either orientation, scans soccer subcats, and maps each candidate to a DK selection using the verified label grammar: `"Mexico Win and Over 2.5"`, `"Tie with Goals"` / `"Win to Zero"` (BTTS yes/no), `"Mexico/Tie"` (HT/FT). Two traps encoded: DK's `Both Teams to Score / Over 2.5 Goals` "No" is the *complement* of (Yes & Over), not Pinnacle's "No & Over", so only the Yes cell maps; and `Half Time / Full Time / Over/Under 2.5` shares HT/FT labels and must not shadow plain HT/FT. The response includes `available_markets` for renaming debuggability.

**Output.** Table ranked by `EV% = fair_prob × dk_decimal − 1`, with Pinnacle price, no-vig FV, fair %, DK price, and full-Kelly %. Filters: min-EV slider, per-market toggles, matched-only. Endpoints: `/api/pinnacle/worldcup-games`, `/api/pinnacle/worldcup-match/:id`, `/api/dk/find-sgps-worldcup`, `/api/dk/worldcup-games`, `/api/dk/worldcup-resolve-league`.


## 2026-05-26 session

### Tennis SGP +EV tab (French Open M)
New top-level sport (`TENNIS` next to MLB / NBA in the `.sport-bar`) targeting 1st-set-total × dog-game-handicap SGPs at the men's grand slam. Sport-wide correlations are hardcoded priors:

| 1st Set Total Over | r vs dog Game Handicap |
| --- | --- |
| 8.5  | 0.20 |
| 9.5  | 0.27 |
| 10.5 | 0.30 |
| 12.5 | 0.34 |

**Inputs.** Two FV-sheet uploads (one screenshot per market). OCR (`/api/extract-tennis`) auto-normalizes both layouts we've seen — the older `name / book_odds / fv` schema and the newer `bet_name / odds / avg_fv / tournament` schema — to a single `{game, market, bet_name, book_odds, fv, devig_odds, tournament}` row. Rows accumulate across uploads and merge by `game` key into SGP candidates. Favorite-side spread rows (`-X.5`) are dropped; only the dog side feeds the correlation.

**Fair-price source toggle.**
- `FV` (default) — uses the sheet's signed `fv` integer for each leg.
- `DK NO-VIG` — no-vigs DK's own two-sided `book_odds` pair (e.g. `-150/+100` → fair `-120`) for each leg.

Joint prob via `sgpMath.jointFrechet(pa, pb, r)`, same function the pitcher + teammate + NBA pipelines use. EV vs DK SGP price + Kelly + `evAttribution` rendered on each card.

**DK linkage.** `dk_api.py:get_games_tennis()` pulls events from `DK_TENNIS_LEAGUE_ID` (env-configurable; defaults to a placeholder for French Open M — set it explicitly to the live league ID). `find_sgps_tennis()` resolves each candidate to one event by player-name match, scans markets with the new `tennis_only=True` subcat filter, matches Set-1 Over/Under and per-player full-match Game Handicap legs by line + name, then prices each unique pair via `_price_combo` with the existing 110s soft deadline + Akamai-safe retry budget. Response cached server-side for 10 minutes per candidate-set fingerprint (mirrors the NBA pricing cache).

**Files.** `dk_api.py` (+ tennis league ID, get_games_tennis, find_sgps_tennis, tennis subcat filter), `server.js` (+ `/api/extract-tennis`, `/api/dk/find-sgps-tennis`, `/api/dk/tennis-games`, OCR prompt + parser), `public/index.html` (+ sport-btn, nav, header, page, sport switcher), `public/utils/tennisEvTab.js` (new tab module — upload merge, fair-mode toggle, scan, render).

## 2026-04-24 session

### AI Insights: structured context, r_DK attribution, correlation-gap-first prompt
2-leg cards now compute `r_DK` (inverting `jointFrechet` on the DK SGP price with our FV legs) and an EV attribution split (`evFromLegsPct` + `evFromCorrPct`). New `DK R` column on the card shows the gap directly. `sgpInsightPrompt.js` rewritten to hand the model a structured context object (FV legs, empirical hits J/N, P(A)·P(B), P(B|A), r_ours, r_DK, r_gap, attribution split) and enforce a correlation-gap-default thesis (pitcher leg markets are near-efficient, so for EV > ~8% the edge must live in the r_ours vs r_DK gap), correct-math (P(B|A) vs P(B) not vs P(A)·P(B); near-zero r_ours is not "no correlation edge" when r_gap is large), specific-risk, and honest-score rules. `sgpMath.js` gained `inverseJointFrechet` and `evAttribution` (unit-tested roundtrip + clamp).

## 2026-04-17 session

### 571e187 — Collapse duplicate `(pitcher, leg)` rows and canonicalize SGP leg ordering
Added a second-pass dedup in `server.js:normalizeRows` that collapses duplicate `(pitcher, leg)` entries coming out of OCR. Canonical row picked by `(books_count desc, L desc)` — no averaging. OCR prompt now requests `books_count` from column 12 so the collapse has a signal to rank on. In `dk_api.py`, combo index pairs are swapped after `combinations()` so the leg with the alphabetically earlier stat category (BB < ER < H < OUTS < SO) always comes first. Fixes the 4× duplicate Wacha cards observed when FV sheet or OCR emits multiple rows for the same leg.

### 8b11254 — Lower blend threshold to 5
`BLEND_MIN_STARTS` lowered from 10 to 5. The `n/(n+50)` shrinkage already self-degrades player influence at low samples (9% at n=5, 17% at n=10). Threshold of 10 was double-counting the small-sample penalty and disproportionately caught veterans with thin recent seasons (injury years, swing roles, late callups). Threshold of 5 keeps a sanity floor while letting the shrinkage math work on its own.

### 53633f1 — Pass 2: `n_eff` shrinkage + blended-mode UI + float-precision cleanup
`resolveR()` is now the single source of truth for correlation reads — uses `n_starts_eff` (year-weighted) for the shrinkage threshold and blend weights instead of raw `n_starts`, and exposes `{r, source, wPlayer, wGlobal, n, rPlayer, rGlobal}` so EV card labels, pitcher-page tooltips, and raw_corr displays reconstruct from the same data. Blended mode shrinks both the binary `r` and the raw-stat `r_margin` on the pitcher page. `avg_r` for 3-leg combos is the simple mean of the three shrunk pair r's. EV label reads source not mode, so low-sample blend fallbacks render as `(blended → global)`. Float precision cleaned up in `_blendCombosGeneric`: percentage fields rounded to 1 decimal, display-only correlation variants (`r_avg`, `r12a/13a/23a`, `avg_ra`) rounded to 4. Primary correlation fields left un-rounded (they feed math). `_warnMissingPair` and `_blendCombosGeneric`'s gap warning both gated behind the frontend `DEBUG` flag.

### 6d8574e — Pass 1: year-weighted blending for pitcher + global data
Replaced the 25 MB inline `var D = {…}` with a loader that fetches `public/data/aggregates_YYYY.json` for all four years and builds an equivalent-shape `D` object at page load. Dynamic weights key off each pitcher's own 2026 starts via `getDynamicWeights`. Globals blend via static `YEAR_WEIGHTS = {2023:0.15, 2024:0.20, 2025:0.30, 2026:0.35}`. `normalizeWeights` pins 2026 at its dynamic-table value so renormalization over missing years can't inflate it past its prescribed share. Badge and stats-row now render from runtime totals. Pitcher page shows `STARTS · EFF N`.

### e398835 — Per-year correlation aggregator + gzip middleware
Added `build_aggregates.py` reading `public/data/pitchers_YYYY.json` and emitting `public/data/aggregates_YYYY.json` — same shape as the legacy inline `D` (`global_2`, `global_3`, `pitchers` with `combos_2/combos_3/avg_*/raw_corr`) plus `global_raw_corr` for shrinkage-toward-global. IP converted via baseball rules (`5.2 IP → 17 outs`). Null-only combo rows dropped. `server.js` gained `compression` middleware so the 22 MB/year files ship at ~1.8 MB gzipped.

### 063e0fc, 20a2000 — Raw pitcher JSON builder
`build_pitcher_data.py` converts the four xlsx season feeds (2023–2026) to slim `public/data/pitchers_YYYY.json` + `manifest.json`. Idempotent — drop a refreshed 2026 xlsx and re-run.
