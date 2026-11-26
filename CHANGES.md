# Changes

## 2026-11-27 session

### Ladders: the DraftKings pull is taken out
Max, 11-27, a screenshot of NFL Ladder with a red line at the top (DraftKings prices did not load: DK request failed after 6 attempts, status 403): remove DK thing, doesn't work.

- **Change** (`load` in `books.py`): the Ladder boards no longer ask DraftKings for its prices. DraftKings refused every pull from the server, so each NFL pass spent six tries on it and then showed the red line. FanDuel alone caps a shifted leg and supplies the main line where Novig has no tight one, which is what was already happening whenever DraftKings refused. The NBA Ladder was FanDuel only already.
- **Page** (`public/nba_scan.html`): the red DraftKings line is gone, and the NFL and NBA Ladder notes name FanDuel only. A line still shows if FanDuel's prices fail to load.
- **Not changed**: fair values (DraftKings was not contributing), the DK code in `books.py` and `dk_api.py`, which is left in place and not called from the ladders.
- **Checked**: an NFL ladder slip list built with FanDuel alone (`books` reported as FanDuel only, no DraftKings request made or error given). **Not checked**: on Railway.

### Ladder tab: adaptive, each slip at whichever of Novig and Kalshi pays more
Max, 11-27: instead of saying better on Kalshi, show both odds and make the bet button for Kalshi if better on Kalshi and then link to Novig if better on Novig. Make ladders adaptive, not like either of the other 2 tabs.

Read as: the Novig tab is fixed to Novig and the Kalshi tab to Kalshi; the Ladder tab follows the better price slip by slip. This replaces the "Better on Kalshi" mark and the rules about which slips Kalshi is asked for in the entry below.

- **Both prices on every row** (`priceCell`, `kalLine` in `public/nba_scan.html`): the price column reads `NV 7.76x` over `KAL 8.15x`, each after its own fee, the better one green. `KAL —` where Kalshi has no market on those lines or no maker answered; the row's line says which.
- **The row stands at the better price** (`adapt`): its EV, QK and QK $ are at that book's price, with the book named under the EV. The list's order, Plays, Min EV and Rescan top 10 follow it. A slip under fair on Novig and above fair on Kalshi is now a play, where before it was a Novig row with a mark on it. Novig's price counts as better when Kalshi's is within half a cent a dollar of it.
- **One button a row** (`lbetLine`), on a row above fair at its better price:
  - Kalshi pays more: **Bet $241 at 8.15x on Kalshi**. One press buys the combo on Kalshi for the row's QK $ at Kalshi's price, less what is already on the slip, or for a stake typed in the opened row; beside it, what Novig pays. The bet is saved on the row, and Kalshi's own position shows there once it reads it.
  - Novig pays more, or Kalshi has no price: **Open on Novig at 8.36x**, the link that opens Novig with the legs on the slip; beside it, what Kalshi pays or why it has no price. The bet is placed in Novig, and noted in the opened row as before.
- **The Kalshi bet from a Ladder row** (`/api/nba/kalshi-bet` in `server.js`; `hold` in `scan_kalshi.reprice`): the same route and rules as the Kalshi tab's button: not placed if Kalshi's price is more than 1% worse than shown or the slip is no longer above fair, one bet at a time, the position read back after. Two differences. The fair value is the Ladder row's (Novig's books, or modelled from the main line), held under Kalshi's ask and over its bid on each leg where it has them, not re-read off Kalshi's books, which on far milestones are often one-sided. So the row must be fresh: a row or Kalshi price over 10 minutes old is refused and asks for its ↻ first (`NV_LBET_AGE_MS`).
- **Kalshi is asked for every slip Novig prices** (`KALSHI_LOOK` in `scan.py`): the "within 10% of fair on Novig" rule is gone, since a slip that is poor on Novig can be the play on Kalshi. Still the best Novig EV first and one request at a time; the limit is 150 a pass (was 120). A slip Novig gives no price for is still not asked of Kalshi.
- **Cost**: more Kalshi asks a pass than before. On the stand-in run below Kalshi was asked for 76 of 123 NFL slips (52 of 120 under the old rule), about 5 seconds each, and each is a new combo against Kalshi's 5,000 a week.
- **Not changed**: what the Ladder boards ask of Novig, the fair values, the Novig and Kalshi tabs, the lock behind the Kalshi passcode.
- **Checked** on a local server with stand-ins for both exchanges' quoting (the real NFL ladder slips and Kalshi's real market list; made-up prices; nothing asked of or bought on Novig or Kalshi). A Fetch to the end: 123 slips priced on Novig, 68 on both (38 better on Kalshi, 30 on Novig), the list in order of the better EV. At phone size and on a wide screen: both prices, the book under the EV, 25 Kalshi buttons and 36 Novig links, no script errors. The Kalshi button: a press bought the slip on the stand-in (one acceptance), the row then read "You bet $276 at 8.54x" and the button "QK $276 is on"; a row 10 minutes old was refused with the refresh message; without the Kalshi passcode the route answers locked. A refresh re-priced both books. The Novig and Kalshi pages load as before. **Not checked**: a real bet on Kalshi from this tab, real quotes, the NBA Ladder with Kalshi (no NBA props were listed), the server on Railway.

### Ladders: their own tab, priced on Novig and on Kalshi
Max, 11-27: remove ladders from the Novig tab, make another ladders tab, and when we do ladders look up Novig and Kalshi, to make sure a slip isn't better on Kalshi if I'm taking it on Novig.

- **New tab, LADDER SCAN** (`ladderscan` in `public/index.html`; `public/nba_scan.html?ladders=1`, `LPAGE`): between NOVIG SCAN and KALSHI SCAN. It holds the two Ladder boards, NBA Ladder and NFL Ladder, as they were: the same slips, fair values, Fetch, game picker, refresh and saved bets. No Auto-scan button (the Ladder boards were already Fetch only).
- **Off the Novig tab**: NBA Ladder and NFL Ladder are no longer tabs there, and their rows are no longer on its All tab (`NV_ALL_BOARDS` in `server.js`). A device last left on a Ladder board opens the Novig tab on NBA. A bet saved on a Ladder row shows on the Ladder tab.
- **Kalshi's price for the same slip** (`kalshi_same`, `kalshi_look` in `scan.py`, run with `--kalshi`; `NV_LADDERS` in `server.js`): a Ladder pass asks Novig as before. Each slip Novig prices within 10% of fair or better is then asked of Kalshi as the same combo: a request for quote for $100, read after 3 seconds and withdrawn, nothing bought. The best Novig EV is asked first, one at a time, up to 120 a pass (`--kalshi-ev`, `--kalshi-max`). The row shows at once with Novig's price; Kalshi's fills in a few seconds later.
- **On the row**: `KAL 8.15x` under Novig's price is what the slip pays on Kalshi after its taker fee. Where that is more than Novig pays, it is green and the row is marked **Better on Kalshi**. The line at the top counts them. The opened row gives Kalshi's EV at the row's fair value, how much more or less than Novig it pays, and a link to the game on Kalshi. The row's own EV, QK and ranking are still Novig's.
- **Only the same bet counts**: Kalshi is asked only where it lists every leg on the same line (Over 49.5 is its "50+"). Its milestones are 5 points or 10 yards apart and Novig's ladder has every line, so many ladder slips have no Kalshi market: the row shows `KAL —` and the opened row names the leg ("Kalshi does not list 42+ YDS"). On the stand-in run below, 52 of 86 NFL slips asked had a Kalshi market.
- **Refresh** (↻, and Rescan top 10) asks Novig and Kalshi again for that slip, whatever its EV.
- **Behind the Kalshi passcode** (Max, the same day: make it hidden behind the Kalshi PW). The LADDER SCAN button shows only on a device that holds the Kalshi passcode, as KALSHI SCAN does. The page opened without it shows "Locked" and asks for it. The server answers a Ladder board's scan and refresh only with both passcodes (423 without the Kalshi one, `NV_LADDERS` in `server.js`), so the Ladder boards cannot be read or fetched with the scanner's passcode alone. The Novig tab no longer mentions the Ladder boards.
- **Cost**: each Kalshi ask is a new combo against Kalshi's 5,000 a week, which the script still does not count, and adds about 5 seconds to the pass (the 120-slip run below: 4 minutes). A Ladder pass's Kalshi asks run beside a pass on the Kalshi tab, not in its queue.
- **Not changed**: what the Ladder boards ask of Novig and how their fair values are made; the Kalshi tab; Discord alerts (a Ladder row's alert, sent only with Auto-scan on, does not carry Kalshi's price). (The button for Kalshi came the same day: the entry above.)
- **Checked** on a local server with stand-ins for both exchanges' quotes (the real NFL ladder slips and Kalshi's real market list from tonight's books; made-up prices, no quote asked of Novig or Kalshi): an NFL Ladder pass priced 120 slips on Novig, 44 of them on Kalshi, 8 with no maker answering, 34 not asked for being more than 10% under fair, and the rest with the leg Kalshi does not list. In a browser at phone size: the three scan buttons, the Novig tab without the Ladder tabs, Fetch on NFL Ladder to the end, the KAL line, the Better on Kalshi mark and count, an opened row, a refresh, and the Kalshi tab's own tabs; no script errors. The lock: with the scanner's passcode alone the main page shows NOVIG SCAN only, the Ladder page says Locked, and the server answers 423 to a Ladder scan and refresh (no passcode or a wrong one); with both, the button, the board and its rows. With no Kalshi key on the server the top line says so and the pass still prices on Novig. **Not checked**: a pass against Novig's and Kalshi's real quoting, the NBA Ladder with Kalshi (Kalshi listed no NBA props when this was written), the server on Railway.

## 2026-11-26 session

### Kalshi NBA: one tab for the four NBA boards, and one Fetch that prices all four
Max, 11-26: should we combine the NBA tabs for Kalshi; I have a hard time trying to figure out which one to run.

- **New tab, Kalshi NBA** (`kalshinbaall` in `public/nba_scan.html`; `NV_KNBA` in `server.js`): the first tab on the Kalshi page, and the one a new device opens on. It lists the four NBA boards' slips at Min EV or better in one list, best first, each row tagged with its board, drawn as the All tab is. Rows keep their own refresh and Bet buttons.
- **Its Fetch** (`NV_KQUEUE`, `nvKNext` in `server.js`) prices all four, one after another on the one Kalshi slot: Kalshi Pts + 3s, then Pairs, 3-Leg and Lines. The line at the top says which board is scanning and which are next. Stop ends the board that is running and drops the ones still queued. A board that fails or times out does not hold up the ones behind it. With a pass on another Kalshi board running, the button reads "Stop … and fetch", as on the other tabs.
- **The four boards are not merged**: each keeps its own pass, cap and rules, and can still be fetched alone. The old Kalshi NBA board (other pairs and teammates) is now named **Kalshi NBA Pairs**.
- **Cost**: the same slips as fetching the four tabs in turn, so the same new combos against Kalshi's 5,000 a week, which the script still does not count. A full Fetch is the four passes end to end (about 20 minutes for 390 slips at Kalshi's pace).
- **One NBA tab** (Max, the same day, from a phone where ten tabs wrapped to three lines each: so do we one NBA tab): Kalshi Pts + 3s, Pairs, 3-Leg and Lines have no tab of their own now. Kalshi NBA is the only NBA tab, and a dropdown beside the name filter (`kboard`, `tabOf`, `go` in `public/nba_scan.html`) picks "All four boards" or one board alone, which shows as it did on its tab: its own Fetch, All combos, its footer. The strip is six tabs. A device last left on one of the four opens on Kalshi NBA with that board picked. Checked at phone size on the stand-in: the picker, a Fetch of all four, a board picked during the run, another tab and back, a reload.
- **Kalshi NFL the same** (Max, the same day: let's combine NFL too; `NV_KGROUPS` in `server.js`, `KGROUPS` in `public/nba_scan.html`): one Kalshi NFL tab over the three NFL boards, with the same list, Fetch, Stop and dropdown. Its Fetch runs Kalshi NFL Props, then NFL Lines, then NFL 3-Leg: up to 200 slips a board, 600 a Fetch, against the same 5,000 new combos a week the NBA boards draw on. The old Kalshi NFL board (a player's own props and the quarterback stacks) is now named **Kalshi NFL Props**. The strip is four tabs: Kalshi NBA, Kalshi NFL, Kalshi CBB, Kalshi CFB. An NBA run and an NFL run share the one Kalshi slot: with one running, the other tab's button reads "Stop … and fetch". Checked at phone size on the stand-in: a device last on NFL Lines opens on Kalshi NFL with Lines picked; a Fetch of all three ran in order to the end (468 priced, rows from all three boards); the NFL Fetch pressed during an NBA run stopped it and started; Stop.
- **Fetch empties the list first** (Max, 11-27, Kalshi NFL with Props scanning 0 / 200 and Lines rows 8 hours old still on it with their Bet buttons: old ones don't go away when you hit Fetch). Each board was emptied only when its own pass began, so the boards still queued kept their last rows. Now the press empties every board in the group (`server.js`, the group's `now=1`), and the list holds only what this Fetch has priced. A run stopped part-way leaves the boards it didn't reach empty; the line at the top still gives the time of their last full pass. A slip you have bet keeps its dimmed row, with no Bet button, until its board prices it again. Fetching one board alone from the dropdown empties that board only, as before. Checked on the stand-in: 371 NFL rows before the press, 0 right after, the first board's rows as it priced them, the other two still empty after Stop and after a server restart.
- **Your bets sit under the priced rows** (Max, 11-27, a screenshot after a Fetch: I have killed the tab and it hasn't changed). The Fetch had emptied the boards: every row with a Bet button was 20 minutes old. The rows 13 hours old were his own bets, kept on the page since 11-25 when the board has no such row, and ranked among the new plays by the EV they had when last priced. They now come after every priced row, on every tab, under a line reading "Your bets · not priced by the last Fetch" (`cards.sort`, `.kept` in `public/nba_scan.html`); a card with both a priced row and a kept one is headed by the priced one. Checked at phone size on the stand-in with two staged bets on NFL 3-Leg: live rows before the Fetch, both under the heading while Props ran, and back among the plays once 3-Leg priced them (one stayed under the heading: the stand-in gave it no price).
- **Not changed**: what each board asks, fair values, the Bet button, the Novig page's boards and its All tab (kept bet rows sort last there too). A single board's Fetch pressed while the four are queued stops them, as it stops any other board's pass.
- **Checked** on a local server with a stand-in for Kalshi's quotes (the real slip lists off tonight's books, made-up prices, no quote asked of Kalshi): the four passes ran in order (56, 49, 35 and 40 slips); Stop ended the run and cleared the queue; a board made to fail was passed over; a CBB pass in the way showed as running and was stopped by "Stop … and fetch"; without the Kalshi passcode the tab answers 423. In a browser: the tab, Fetch, Stop and a run to the end, rows from all four boards with their Bet buttons, no script errors. **Not checked**: a pass against Kalshi itself, the Bet button, the server on Railway.

## 2026-11-25 session

### A bet keeps its row on the page when the board no longer has it
Max, 11-25: is there any way for the bets to not go away after we do an update?

- **Why they went**: the bets themselves were never lost: they are kept in the browser, not on the server. But a bet shows only on its own row, and after an update the board can come back without that row: the server restarts, and its saved boards survive only where `/data` is a mounted volume; a new pass may not ask the slip again; on the All tab a row under Min EV is not sent. With no row, the bet had nowhere to show.
- **Change** (`keepRows`, `GHOSTS` in `public/nba_scan.html`): each bet now carries a copy of its row, taken when the bet is saved (Save, or the Kalshi Bet button) and refreshed every time the board shows that row. When the board has no such row, the page draws the copy: dimmed, marked "not on the board now", with the numbers from when it was last priced, on the bet's own tab and on All. It can be opened and the bet removed; it has no refresh or Bet button, and is left out of the counts and of Rescan top 10. It gives way to the real row as soon as the board has it again, and leaves when the game starts, as rows do.
- **Bets already saved** (Max, the same day: I meant my saved Novig bets go away) have no copy yet, so their row is made from the bet itself (`stubRow`): the game or player, the legs' text, the fair value and price as saved, the stake. Opened, it lists the bets with their × and nothing else. They take a full copy the next time their row is on the board on that device.
- **Not changed**: bets are still kept on each device only. Kalshi positions read from Kalshi (the "On Kalshi" line) still show only on a row the board has; a Kalshi bet made with the Bet button is also a saved bet, so it keeps its row like the others.
- **Checked** in a phone-sized browser with stand-in server answers: a bet saved through the page and one saved in the old form both stay on the CBB tab and the All tab after the board is emptied, not on another tab, and the real row takes over when the board is back; old-form bets alone on an empty board (two on one slip, one with no price or fair value, one whose game has started) draw one row a slip, dashes where nothing was saved, none for the started game, and can be removed. **Not checked**: on the live site across a real deploy; whether the live server's `/data` is a volume.
### Scan: a player's other rows say what is already on him
Max, 11-25 (Day'Ron Sharpe: $241.80 on 10+ points + 8+ rebounds, and his 10+ points + 10+ rebounds row above it showed only "Bet $205"): does a bad job of showing I already have a bet on that player.

- **Change** (`alsoLine` in `public/nba_scan.html`): each row of a player's card with nothing on it carries a grey line, "Already on Sharpe: **$241.80** on 10+ points · 8+ rebounds", for every other slip of his with money on it (Kalshi's figure or this device's note, whichever is larger). It shows with the card folded too, and for a slip of his that is under Min EV. A row with its own bet keeps its green line and shows only that.
- **Green edge**: a Kalshi row now gets it from Kalshi's position too, not only from a bet saved on this device.
- **This puts back, reworded,** the grey line taken off this morning ("a bet shows on its own row only"). Then it was on the player's first row only and named no amount per slip.
- **Not changed**: the Bet button's amount on those rows is still that row's own QK $; money on his other slips is not taken off it. Boards where every row is its own card (NFL, NBA Team) have no such line.
- **Checked**: the page's script parses. **Not checked**: in a browser.

### Kalshi scan: the Bet button stakes the QK $ less what is already on the slip
Max, 11-25 (Stafford 34+ attempts + 22+ completions, QK $446 with $135.55 already on): bet the recommended less what we have outstanding.

- **Change** (`kbetStake`, `kbetOn`, `kbetFull` in `public/nba_scan.html`): one press stakes the row's QK $ minus what is on that slip, and the button reads **Bet $305 more at 2.35x**. What is on is the larger of Kalshi's own figure for the position (dollars in) and this device's note of bets on the slip, so a bet Kalshi's list has not caught up with is not placed twice.
- **Once the QK $ is on**, the button reads "QK $446 is on · bet a typed stake" and a press places nothing unless a stake is typed in the opened row. A typed stake is bet as typed, as before.
- **Not counted**: a position on the No side of the combo, and bets on the player's other slips.
- **Checked**: the page's script parses, and the three functions on five cases (nothing on, Kalshi and the device both, Kalshi only, over the QK $, No side). **Not checked**: in a browser, and no bet was placed.

### A modelled leg outside its own book takes the book's fair value, not its edge
Max, 11-25 (Kalshi Pts + 3s, Yaxel Lendeborg): these FVs are really odd. 20+ points + 3+ threes * showed fair +225 (30.8%) while 3+ threes alone was 27 / 30 on Kalshi and 25.5 / 30.5 on Novig: a slip likelier than its harder leg.

- **Cause**: a starred leg is shifted from Novig's main line by the Ladder's model, then held under the line's ask and over its bid. The model put 3+ threes at 0.349 from his 2+ line (56%), above the whole book, so it was held at the ask: the most optimistic value the book allows.
- **Change** (`inside` in `scan.py`, used by `shifted` there and `shift_leg` in `scan_kalshi.py`): where the line has both a bid and an ask and the model falls outside them, the leg takes that book's own fair value (worst-case devig), 0.282 here. A model inside the book stands, and a one-sided book is still only a ceiling or a floor. Applies to every starred row: the Kalshi NBA boards and the Novig NBA Ladder.
- **Effect here**: 20+ points + 3+ threes at 20+ 62% goes from about +225 to +282, so 3.29x reads about -14%, not +1%.
- **Checked**: the helper on eight book shapes (outside above, outside below, inside, one-sided, no book, crossed); a Kalshi Pts + 3s pass with no prices asked still lists its 12 modelled slips. **Not checked**: a priced pass, the Ladder board live. Rows on the boards keep their old fair values until their next pass.
- **Not changed**: the first row (25+ points + 2+ threes, +222) is right as arithmetic; its points leg is Kalshi's own untraded 5c book (the ~).

### Novig scan: a bet shows on its own row only
Max, 11-25: remove from Novig too (after the Kalshi strip).

- **Change** (`betLine` in `public/nba_scan.html`): the grey line on a player's other row ("$159 on another slip of his: 3+ receptions · 25+ receiving yards") is gone. It was the one place the Novig page showed a bet off its own row; the strip above the board went on 11-18. The green "✓ You bet" line on the bet's own row is unchanged.
- **Checked** in a phone-sized browser: the page loads and draws its rows with no error. **Not checked**: with a saved bet on the page.

### Kalshi scan: the "On Kalshi" strip above the board is gone
Max, 11-25 (screenshot, the strip of twelve combos circled): always hide this; bets should show in their own row only.

- **Change** (`public/nba_scan.html`): the strip listing every combo held on Kalshi is removed. A held combo still shows on its own row ("On Kalshi: $171.29 in, pays $475"), read from Kalshi once a minute and after a bet, as before.
- **What no longer shows anywhere**: a combo you hold whose row is not on the board (not fetched yet, another tab, or its game has started), the total staked, and the "could not be read" message when Kalshi's positions fail to load.
- **Checked** in a phone-sized browser with stand-in positions: no strip, the held row carries its line, a held combo with no row shows nothing.

### Novig scan: a Rescan top 10 button
Max, 11-25: a lot of weird pings (Sam LaPorta U4.5 receptions + U44.5 yards on the board at 2.91x, 7 seconds old, and 2.17x on Novig's slip); add a rescan top 10 button.

- **What the pings were**: Novig's quote on that slip, asked 30 times over 90 seconds, sat at 0.44 (2.17x), then 0.328 (2.89x) for about 30 seconds, then 0.44 again. Two prices take turns, a quote's 30 seconds each; a pass shows whichever it caught. ARIZ -5.5 + Over 156.5 at 10.36x (fair +340, right on Novig's own books) is likely the same: its four corners summed to 0.73.
- **Change** (`requoteTop` in `public/nba_scan.html`): **Rescan top 10**, beside Auto-scan, prices the ten best rows on screen again one after another (each row's own refresh, in turn), on any tab and with the filters as set. The button counts them off and stops when pressed again. The ten are the ones on screen when it is pressed.
- **Also**: a row's refresh button now spins on the All tab while it is priced (it compared two different keys there).
- **Checked** in a desktop and a phone-sized browser with stand-in server answers and 18 real CBB rows marked above fair for the test: ten asked in screen order, one refused row does not stop the rest, a second press stops it. **Not checked**: against the live server.

### Kalshi scan refused with 401: the page now says which variable is wrong
Max, 11-25: a screenshot of the Kalshi page, "Scan failed: Kalshi is refusing this key's requests: 401 authentication_error We could not authenticate your request".

- **Cause**: on Kalshi's side or in Railway's variables, not in the code. Kalshi's answer carries a `details` field with its reason, which the scanner dropped.
- **Change** (`call` and `refused_fix` in `scan_kalshi.py`): the reason is kept in the message, with the fix for the two it names: `NOT_FOUND` (Kalshi has no key with the id in `KALSHI_KEY_ID`) and a signature mismatch (`KALSHI_PRIVATE_KEY` is not that key's private key).
- **The "On Kalshi" strip** keeps the last list it read when a read fails, so the positions in the screenshot do not show the key working.
- **Checked**: `--check` with a made-up key id and a fresh RSA key prints `... (NOT_FOUND)`; Kalshi's exchange status is up. **Not checked**: the real key (it is only on Railway); the wording Kalshi uses for a wrong signature (`SIGNATURE` is matched from its documented `INCORRECT_API_KEY_SIGNATURE`).

## 2026-11-24 session

### NBA teammates' assists and rebounds, measured again on games to date: still not added
Max, 11-24: look at teammate correlation again (this player gets 2 assists a game from that one; one gets 7 rebounds and one gets 4, and Novig adds too much negative correlation). Update games to date.

- **Games to date**: `public/data/nba_teammate_logs.json` rebuilt through tonight (1,494 games, 2025-26 and 2026-27; the NBA TEAMMATES tab reads it).
- **Measured** (`scripts/nba_mate_research.py`, new; research only, no board reads it): every pair of teammates in every game both played 20+ minutes, each leg "Over his median of his previous 15 games", r the copula correlation of both hitting, ± one standard error.
  - **A's assists + B's points**: +0.07 for any pair. By how many assists A fed B a game in their earlier games together: under 1, +0.06; 1 to 2, +0.08 ± 0.015; 2 or more, +0.12 ± 0.035 (707 pair-games). This season alone: +0.07, and +0.10 ± 0.03 at 1 to 2.
  - **A's assists + B's threes**: +0.07; +0.10 ± 0.02 at 0.75+ three-point assists a game.
  - **Rebounds + rebounds**: 0.00 (+0.006 ± 0.006 on 32,590 pair-games). A line of 6 to 9 with one of 3.5 to 5.5 (the 7 with the 4): -0.01 ± 0.014. Two starters, starter + bench, by position: all within 0.03 of zero.
  - **A pair's own r does not carry over.** For pairs with 40+ games together, r on their odd games against r on their even games correlates -0.07 to +0.07 (150 to 190 pairs a pairing). A pair showing +0.3 on 50 games is what chance gives around the pairing's average.
- **Novig**, three reads tonight on the 8 teams with books open for 11-25 (`--novig`; legs on books to 8c wide): rebounds + rebounds, 61 to 64 slips a read, its price implies r +0.04 to +0.055 at the median (-0.09 to +0.11); assists + a fed teammate's points, 17 to 18 slips, +0.10 to +0.115. It is not pricing these as pulling against each other: it is at the measured number or a little over. After the parlay fee the medians are -11% to -12%. Four slips of about 240 came back above fair (best +3.2%); none did on the next read.
- **What it would take**: the fee is about 7% on a +270 slip, so a slip is +3% only where Novig's r is about 0.15 under the real one. None was.
- **Teammates' points, the slip already on the board**: 8 teams, implied r +0.03 at the median (-0.05 to +0.07), best -5.7%. The -0.12 to -0.15 of 11-16 was not there tonight.
- **The NBA TEAMMATES tab** prices off each pair's raw r by default and lists pairs at |r| 0.20 or more. By the odd-against-even check those rows are mostly chance, so its fair prices for them run long, and Novig looks too low beside them. Not changed (raw was Max's choice, 11-04); the shrunk toggle is the nearer one.
- **Not changed**: any board, any price. **Not checked**: a game-day read (books are tighter and more teams are open); steals and blocks.

### Scanner: one unit is $200
Max, 11-24: let's change units to $200.

- **Change**: the QK $ column on every scanner tab (`UNIT` in `public/nba_scan.html`), the stake in a Discord alert (`ALERT_UNIT` in `novigAlerts.js`) and `--unit` in `scan_kalshi.py` are at $200 a unit; all three were $100. The QK column in units is unchanged: 1.24u is now $248, was $124.
- **The Bet button stakes twice as much.** One press on a Kalshi row stakes the row's QK $, so every press doubles, up to the $250 cap on one bet (`KALSHI_BET_MAX`), which is not changed: any row at 1.25u or more is now bet at $250.
- **Not changed**: the skills' own sizing ($250 a unit in `price.py`, the daily Points + Threes run and tennis; `scan.py`'s `wager` field). If `ALERT_UNIT` is set on Railway, alerts keep that value.
- **Checked**: `scripts/novig_alerts_check.js` passes with the stake line at $120 for 0.60u. **Not checked**: the page in a browser; a press of the Bet button.

### Kalshi Bet button: no $250 cap
Max, 11-24: don't cap at $250.

- **Change** (`NV_KBET_MAX` in `server.js`; `kbetStake` in `public/nba_scan.html`): one press stakes the row's full QK $, or the stake typed, whatever its size. The server's $250 limit on one bet and the page's matching one are gone. The entry above was written with the cap still on.
- **`KALSHI_BET_MAX`** still caps a bet if it is set on Railway: a press over it is refused, not cut down. Unset it for no cap.
- **Still stops a bet**: the price more than 1% worse than the row showed; the slip no longer above fair; no Kalshi passcode; another bet in flight.
- **Checked**: `node --check server.js`; the page's script parses. **Not checked**: a press over $250 on the real exchange.

## 2026-11-23 session

### Kalshi NFL 3-Leg: a new board for three-leg NFL slips
Max, 11-23: can we add 3 leg Kalshi. (Kalshi NBA 3-Leg has been up since 11-21, so this was read as the NFL one.)

- **New tab** (Kalshi NFL 3-Leg, after Kalshi NFL Lines; `kalshinfltri` in `server.js` and `public/nba_scan.html`, `--league nfltri` in `scan_kalshi.py`). Fetch only, behind the Kalshi passcode, with the refresh and Bet buttons, on the All tab.
- **The slips** (`nfltri_candidates`): the NFL tab's three-leg slips (`scan.nfl_tri_candidates`) built on Kalshi's markets. Every prop is a Yes on the milestone beside the player's main line; all three legs pull the same way. Four shapes, each a choice in the tab's filter: three of one player's props (receptions + receiving yards + touchdown; a QB's completions + passing yards + passing TDs); two of his props + a game line; a QB's passing leg + his receiver's + a game line; a QB with one receiver across three props.
- **The game line**: the total, the team's spread, moneyline or team total, or the first half's, on the side that goes with both props (each at r 0.10 or better with it, one at 0.30). The other team covering and an Under are No legs, as on Kalshi NFL Lines.
- **Fair value**: the three-way joint from the three pair r's (`scan.tri_safe`): the player's own r for two of his props, the league-wide role r's across a QB and his receiver or with a line. A QB + receiver + line slip is times 0.95 (`scan.STACKLINE_FIX`, measured 11-15 for the NFL tab). The other three shapes have no such cut, as on the NFL tab; none has been measured for them.
- **Which are asked**: each player leads his three best by lift over unrelated legs (`--per`), at most two of a shape and one of each kind of line; pairs at r 0.25 or better (`--min-r`). 200 slips a pass, the next day of games first, most lift first. No prop Unders. Not asked: a slip where one leg decides another (`nfl_forced`).
- **Refresh and Bet** (`reprice`): a three-leg row is rebuilt from its own three pair r's and its own cut (`tri_fix` on the row; an NBA three-leg row keeps 0.96).
- **Moved, not changed**: the game-line code of `nflline_candidates` is now `nfl_games` and `nfl_line_leg`, shared by both boards. Kalshi NFL Lines builds 180 slips on tonight's books, as it does with the code before the move.
- **Tonight**, built from the live books: 161 slips on 66 players (58 QB + receiver + line, 35 own props, 35 two props + line, 33 QB + receiver on three props), about 13 minutes a pass.
- **Checked**: dry run on the live books; the re-price run on one row of each shape (Kalshi's public book); `node --check server.js`; the tab opened in a browser on a local server with those 161 slips and made-up Kalshi prices: rows, filter and game picker show, no page errors.
- **Not checked**: anything that needs the Kalshi key. No three-leg NFL slip has been asked of Kalshi, so which shapes it will combine is not known (a refused slip shows as a miss with Kalshi's reason). The Bet button was not pressed on one.

### Scanner passcodes: no built-in Kalshi passcode, and a lockout on wrong ones
Max, 11-23 (an email from Kalshi: new sign-in, Mac, Chrome, Louisville KY, 3:37 PM ET): I think we need to up the security on the scanner.

- **The email is not the scanner.** It reports a sign-in to kalshi.com in a browser, with the account's email and password. The scanner never has those: it signs each call with the API key (`KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY`), which makes no sign-in. Nothing below would have stopped or caused it; that is settled on Kalshi (password, two-factor, a new API key).
- **What was weak here**: the Kalshi boards and the Bet button answered to `yyy` whenever `KALSHI_TAB_KEY` was not set, and `yyy` is written in this repo. Wrong passcodes cost 0.8 s each and nothing else, so either passcode could be guessed at about 100,000 tries a day per connection.
- **No built-in Kalshi passcode** (`NV_KALSHI_ON` in `server.js`): with no `KALSHI_TAB_KEY`, one under 8 characters, or the scanner's own, the Kalshi boards, the positions read, the refresh and the Bet button are off for everyone (423, and the page says why instead of asking for a passcode). **Set `KALSHI_TAB_KEY` in Railway or the Kalshi page stays off.**
- **Lockout** (`nvCheck`): 5 wrong passcodes in 15 minutes from one address and that address is refused for 15 minutes, right passcode or not (429). Counted apart for the scanner's passcode and the Kalshi one, on every route that takes them. A request with no passcode is not a guess. Passcodes are compared in constant time. The address is the one Railway's edge reports (`trust proxy`), not the caller's own `X-Forwarded-For`.
- **No limit on a day's bets** (Max, 11-23: don't add a cap). One was added with this change and taken out the same day; $250 a bet (`KALSHI_BET_MAX`) is the only cap. The bet's log line now carries the caller's address.
- **Page** (`public/nba_scan.html`): both refusals show as a message; the passcode on that device is forgotten.
- **Checked** against the local server: the right passcodes; seven requests with none (no lockout); five wrong then 429 with the right one, for each passcode; the Novig boards still open while the Kalshi passcode is locked out; `yyy` refused with no `KALSHI_TAB_KEY` and with `KALSHI_TAB_KEY=yyy`, on the board and the bet route; the page's three states in a browser. **Not checked**: on Railway. If its edge is more than one hop, every caller shares one address and five wrong guesses by anyone lock everyone out for 15 minutes: the `[passcode]` log line names the address it counted.
- **Not changed**: the rest of the app has no passcode (the DraftKings cookie routes, the screenshot readers that spend the Anthropic key, the correlations upload and rollback). Passcodes are still kept in the browser's storage on each device.

## 2026-11-22 session

### A receiver who is handed the ball: his TD moves less with his QB's passing
Max, 11-22 (the same slip, after the fix below put it at +472): Deebo isn't a traditional WR.

- **What it was**: the role r knew position and targets only. Samuel has 2.0 carries a game this season on 3.8 targets; a rushing touchdown is not a passing one (a back's TD by carries has r 0.00 with his QB's passing TDs), so his anytime TD moves less with Purdy's than a WR's whose touchdowns are all catches.
- **Change** (`rush_share`, `rush_r`, `stack_r` in `scan.py`; all three stack call sites, Novig's NFL board, its three-leg slips and `scan_kalshi.py`): a receiver's rushing share of scoring is his carries and targets a game at the league's touchdowns per carry and per target (WR 0.0385 / 0.0486, TE 0.0781 / 0.0547, nflverse 2017-2026), less the 3% a typical receiver has. His TD is split into a receiving one at the role r and a rushing one at none, and the r used is the one that prices the two together. Passing TDs + TD and passing yards + TD. Under 2% is left alone.
- **Data** (`_box` in `scripts/nfl_fetch_correlations.py`; `public/data/nfl_correlations.json` refetched): WRs and TEs now carry `car_mean`, overall and by season.
- **Who moves**: 57 of 402 receivers, most by little. With a stack r today: Savion Williams 0.47 → 0.37, Samuel 0.47 → 0.37, Barner 0.44 → 0.38, Reed 0.47 → 0.43, Freiermuth 0.45 → 0.41, Malik Washington 0.51 → 0.47.
- **This slip**: r 0.37, 0.162, **+516** (DraftKings +525): about +1.5% at 6.25x, not a play.
- **Not changed**: a TD with a game line (a rushing TD moves with the team total as much as a receiving one). The split is read at even money on the QB's leg and a 25% TD, not at each slip's own prices. Not checked against results: receivers with a carry a game are too few to fit (30 seasons of them, r 0.54 ± 0.19 by the old fit).

### NFL role r's with a touchdown leg were about 0.1 too high
Max, 11-22 (Kalshi NFL: Samuel anytime TD + Purdy 2+ passing TDs, fair +430, +17.9% at 6.25x; DraftKings had the slip +525, Fanatics +465): this FV seems wrong?

- **The legs were right.** Kalshi's own books at the time: Samuel's TD 22 / 23 with 19,000 contracts bid and 250,000 traded, Purdy 2+ 52 / 53. 0.225 and 0.525 at r 0.569 is 0.186, the +430 on the card.
- **The r was not.** `fit` solved r from each group's own hit rates (one receiver with one QB in one season, about 12 games), as if those were the true rates. A touchdown rate read off 12 games is 1 in 12, 2 in 12 or none, and the joint's excess over a x b is curved in the rates, so the equation needs a higher r on noisy rates to reach the same count of games both hit. On made-up seasons with a known r it returned 0.43 for 0.35, 0.55 for 0.45 and 0.68 for 0.57. Legs cut at the group's median are not affected (the rate is one half by construction).
- **Ruled out first**: his carries (WRs with a carry a game fit 0.46 to 0.54, too few games to tell apart) and the matchup already being in both legs' prices (fitted within games of like implied team total, r is no lower).
- **Change** (`fit_groups`, `Seasons`, `rates`, `tally` in `scripts/nfl_stack_correlations.py`; `check` reads off the same simulated seasons): r is solved by simulation. Seasons of the real groups' lengths are drawn at a trial r, a counted leg's true rate from the spread of rates the bucket's groups show beyond chance, a median leg cut at each made-up season's own median, groups dropped by the same rule; r is the one whose made-up seasons show the real groups' games both hit beyond n a b. On made-up seasons it returns the r put in (0.30 / 0.45 / 0.60 came back 0.28 to 0.32 / 0.45 / 0.59 to 0.60). Lines fitted in bands of the spread (moneyline, sides) pool 50+ games a cell and keep the equation.
- **What moves** (`public/data/nfl_stack_correlations.json`, regenerated): passing TDs + a receiver's TD, WR by targets 0.57 / 0.60 / 0.63 → 0.47 / 0.52 / 0.55 (at 3+: 0.45 / 0.54 / 0.54 → 0.37 / 0.47 / 0.48), TE 0.52 / 0.58 → 0.44 / 0.50. Passing yards + his TD 0.23 → 0.20. Passing TDs with the team total 0.68 → 0.60 (3+: 0.82 → 0.71), with the Over 0.62 → 0.55. A TD with a game line 0.24 → 0.20 on average. Yardage, reception and carry pairs 0.01 to 0.02. The fit takes about two minutes, from seconds.
- **This slip**: r 0.473, 0.175, **+472**; at 6.25x that is +9%, not +18%.
- **Not changed**: `STACKLINE_FIX` (x0.95 on a QB prop + receiver prop + game line) was measured against the old r's and not measured again; with lower pair r's it now errs toward a longer fair. A player's own pairs (`nfl_fetch_correlations.py`, receptions + TD and the like) are fitted another way and were not looked at.

### A thin Kalshi book can't price a leg outside Novig's bid and ask
Max, 11-22 (Kalshi NBA: Stirtz 15+ points + 4+ assists, fair +487, +79.9% at 10.56x; the books had each leg +233 and the slip +535 to +975): FV doesn't seem right.

- **What it was**: both legs were read too high off Kalshi books minutes old. His props opened late (points 3:47 PM, assists 4:27 PM). About 4:37 the 15+ points book stood 38 / 41 on a few contracts, so the leg read 0.39 (Novig's 14.5 was wider than 4c, so it had no say); 4,900 contracts then traded and it settled at 27 / 28. The 4+ assists leg was modelled from Novig's 2.5 (0.254) and raised to 0.30 by one contract bid at 30 on Kalshi. At r +0.28 that is about 0.17; off the books at 4:55 (0.274, 0.278) it is 0.109, +815.
- **Change 1** (`two_books` in `scan.py`; `pick_leg` in `scan_kalshi.py` passes Novig's row whatever its width): a Kalshi book under 500 contracts that prices a line alone is held inside Novig's own bid and ask on that line, however wide. Both sets of NBA boards.
- **Change 2** (`shift_leg` in `scan_kalshi.py`): Kalshi's bid and ask bound a modelled leg (*) only with 500 contracts on them, or where Novig has neither on the line.
- **Checked**: the 4:55 books with Kalshi's 4:37 prices put back read +538 before and +842 after, with both legs under 30%, so the slip is not asked. Live dry runs: 144 slips on Kalshi NBA, 111 on Pts + 3s, 61 on 3-Leg; the alert checks pass. Novig's book at 4:37 was not saved, so the row's exact +487 was not reproduced.
- **Not changed**: the refresh and Bet buttons on a Kalshi row still re-read the legs off Kalshi's book alone (`reprice`), thin or not. A row from a book that has since moved is still stale until refreshed; this one was 11 minutes old.

### Kalshi's book counts beside Novig's only with real size on it
Max, 11-22: which one is better? Can you see liquidity on them?

- **Both show size.** Novig's catalog gives the size on each side's best bid and the market's volume; Kalshi's market list gives the size on its best bid and ask (`yes_bid_size_fp`, `yes_ask_size_fp`) and its volume, and its order book every level, without a key.
- **What it shows**: Klay 15+ points on Kalshi was 50 / 51 with 7 contracts ($3.50) on the bid, the next bids 47 at 49 and 119 at 48, and 150 contracts traded. Novig's 14.5 had 9,500 on the Over bid, 57,000 on the Under bid and 87,000 traded. Over the slate, lines near even money with a tight book: Kalshi's thinner side a median 23 contracts (320 of 351 under 200) and 36 traded; Novig's a median 3,700 and 43,000 traded. Kalshi's books are a cent wide because of a few contracts, so "the tighter book" (11-16) was reading the smaller market.
- **Change** (`two_books` in `scan.py`, `KALSHI["size"]`; `kalshi_props` in `scan_kalshi.py` carries the size): Kalshi's book is weighed against Novig's (tighter wins, averaged within a cent) only with 500 contracts or more on the thinner side of its best bid and ask. Under that, Novig's book is the fair value where Novig has a tight one. A line Novig has no tight book on is still priced off Kalshi's, thin or not, as before. One rule, both sets of boards, and the refresh.
- **What moves**: Kalshi-board NBA rows whose legs came off Kalshi's book go back to Novig's; today 141 legs on Novig, 98 on Kalshi (lines Novig has no tight book on), 3 averaged, and the same number of slips. Klay reads +132 on both.
- **Not changed**: NFL and the game-line boards on the Kalshi side (their own copies of the 11-16 rule, no size test). 500 is a judgement, not fitted.
- **Checked** live: `scan_kalshi.py --dry --league nba3` and `scan.py --tier 1` both give Klay 0.49 / 0.52 off Novig; the alert checks pass.

### One fair value for a slip on the Novig and Kalshi NBA boards
Max, 11-22 (Klay Thompson 15+ points + 4+ threes: +132 on the Novig board, +125 on the Kalshi one): how do we prevent this?

- **What it was**: the two boards read the legs off different books. The Kalshi boards take the tighter of Novig's book and Kalshi's own on each line, averaged where they are within a cent in width (11-16). The Novig boards read Novig's book alone. Klay's 15+ points was 0.492 on Novig (2.5c wide) and 0.505 on Kalshi (1c wide), his 4+ threes 0.522 and 0.535: the same r (+0.89) gives +132 and +125.
- **Change** (`two_books`, `kalshi_blend` in `scan.py`; `pick_leg` in `scan_kalshi.py` now calls the same `two_books`): the Novig NBA, NBA Ladder and NBA Team boards read Kalshi's open props once a pass (no key needed) and price every line Kalshi also lists by the Kalshi boards' rule. A line Kalshi does not list (18.5, 11.5) stays on Novig's book. The refresh button re-reads both books for such a leg.
- **What moves**: Novig-board fair values on round-number lines, by a point or so of probability a leg where the two books disagree; near tip most such legs now come off Kalshi's 1c book. A Novig line wider than 4c that Kalshi has tight is now priced, where it had no fair value before.
- **Still different**: the two boards scan at different times, so a row 8 minutes old and one 2 minutes old can differ by whatever the legs moved. Refresh brings either to now.
- **Not changed**: NFL (the Kalshi NFL board has the same two-book rule, the Novig NFL board is still Novig's alone), and the price.py slip pricer.
- **If Kalshi can't be read**, the pass says so on stderr and prices off Novig alone, as before.
- **Checked** live: Klay's row from `scan.py --tier 1` reads +125, the same as `scan_kalshi.py --dry --league nba3`; a 33-quote pass finished; `--requote` on a row with Kalshi-priced legs returned a row. Not looked at in the browser.

### Novig's parlay fee: the app has moved to the new one
Max, 11-22 (two slips a little above their rows: Herbert 2.91x beside 2.89x, Lawrence 2.86x beside 2.84x): see if they changed their fees.

- **What the slips say**: Lawrence U30.5 attempts + U19.5 completions was quoted 0.330 on the board four minutes before the slip and 0.330 again when asked just after it. At 0.330 the old fee is 2.840x and the new one 2.857x; the slip showed 2.86x. Herbert U18.5 completions + U200.5 passing yards: a 0.324 quote 47 seconds old, old fee 2.891x, new 2.907x, slip 2.91x.
- **Change** (`FEE_RULE`, `FEE_RULES` in `novig.py`): the new fee. It is now written as the fee page has it, 0.038 x -log2(price) x stake; the 0.055 x -ln(price) used on 11-18 was a rounding of that and read $12.66 on $100 at 0.10 where the page says $12.62.
- **What moves**: slips shorter than about +270 pay a little more than the boards said (about 0.6% here), longer ones less (a 0.133 quote: 6.77x, not 6.92x).
- **Not known**: when between 11-19 and today the app switched. Long slips on the boards were over-read since then.
- **Checked**: the rule gives the page's three examples ($3.80, $7.60, $12.62). $100 on the Lawrence slip paid $285.67, the new fee at a 0.330 quote to the cent (285.6675); the old fee at 0.330 is $284.00 and at 0.328, the nearest it comes, $285.68.
- **Rows already on the boards** keep the old fee's numbers until their next pass or refresh.

## 2026-11-21 session

### Kalshi boards: slips that got no price are counted, with the reason
Max, 11-21: am I out of scans???

- **Not known from here**: there is no Kalshi key in this session, so the account's use of its 5,000 new combos a week can't be read, and the script still does not count them.
- **Cause of not being able to tell** (`startNovigScan` in `server.js`): a slip Kalshi gave no price for was dropped along with Kalshi's reason, so a pass where every ask failed looked like an empty slate.
- **Change**: the server counts each pass's misses by reason and the page prints them under the status line ("No price for 91 of 91 asked: 91 × ..."), the three most common. A Kalshi board where every slip missed says so in place of "no player has two Novig books tight enough". A used-up weekly limit, a refused request for quote, a combination Kalshi won't make and "no maker answered" each read differently there.
- **Checked**: `node --check server.js`; the page's script parses. Not opened in a browser, not run against Kalshi.

### NBA boards empty: today's data refresh wrote a file with no players
Max, 11-21 (screenshot, 12:33 PM: Kalshi Pts + 3s, "Saved from 12:33 PM · 0 combos", "Nothing to price right now"): why not working.

- **Cause**: the daily data refresh ran at 12:10 PM CT (commit `213a7ea`) and ESPN gave it no players, so it wrote `public/data/nba_correlations.json` with 0 players over yesterday's 626. Every board that reads a player's numbers from that file (the Kalshi NBA boards, the Novig NBA tab, the NBA correlations page) then had nobody to price. Not the three-leg change.
- **Fix now**: yesterday's file (11-20, 626 players) is put back. It lacks last night's games; tomorrow's refresh adds them.
- **So it can't recur** (`scripts/nba_fetch_correlations.py`): a full run that finds under half the players the file already has, or under 100, stops and leaves the file as it is. The workflow step is marked `continue-on-error`, like the other refresh steps, so the rest of the day's data is still committed.
- **An empty pass says why** (`scan_kalshi.py`): an NBA props pass with no slip to ask now stops with the counts (players with open Kalshi props, how many are in the data, Novig's prop markets), shown as "Scan failed: ..." in place of the Novig tab's "no player has two Novig books tight enough". A failed read of a Kalshi series (`kalshi_props`, `_markets`) stops the pass with Kalshi's answer; it was taken as "no markets".
- **Checked**: with the file restored, dry runs on the live books build 91 slips on Kalshi Pts + 3s, 68 on NBA 3-Leg, 106 on Kalshi NBA, 60 on NBA Lines; with the empty file they built 0. A run against a wrong Kalshi address stops with the reason. The fetch script compiles; its new stop was not exercised against ESPN. Not run on the server.

### Kalshi NBA 3-Leg: a new board for three legs on the high scorers
Max, 11-21: can we add 3 leg NBA for high usage guys where everything correlates, like Wemby and Luka; for Kalshi.

- **New tab** (Kalshi NBA 3-Leg, after Kalshi NBA; `kalshinbatri` in `server.js` and `public/nba_scan.html`, `--league nbatri` in `scan_kalshi.py`). Fetch only, behind the Kalshi passcode, with the refresh and Bet buttons, on the All tab.
- **Who**: every player whose main points line is 19.5 or higher (`--tri-pts`; Novig's main line, or Kalshi's milestone nearest even money). The data has no usage rate, so the points line stands in for it.
- **The slips**: his points with two of rebounds, assists and threes, Yes + Yes + Yes on the milestones beside his main lines, where all three pair r's are above 0.03 (`--tri-r`). Each is also asked with the points leg on the milestone the other side of his line. Not asked: a threes leg that forces the points leg, any leg under 30%, and rebounds + assists + threes without points (lift over unrelated legs about 1.2).
- **Fair value**: the three-way joint from the three pair r's (`scan.tri_safe`), times 0.96 (`TRI_FIX`). Measured today on 56 players averaging 19+ points, three seasons, each season cut at his own median lines: points + rebounds + assists hit 672 times against 708 modelled (0.95), points + rebounds + threes 811 against 821 (0.99), points + assists + threes 755 against 787 (0.96). The Novig NBA tab's star three-leg slips do not have this cut.
- **How related the legs are**: points with threes is 0.5 to 0.8; every other pair is 0.05 to 0.3. A slip with threes hits about 1.6 times as often as unrelated legs, points + rebounds + assists about 1.3.
- **Refresh and Bet** (`reprice`): a three-leg row is rebuilt from its three pair r's and the same cut.
- **Tonight**, built from the live books: 77 slips on 17 players (48 at the first milestones), about 7 minutes a pass.
- **Novig's price on nine of them** (keyless quotes, before the 4% cut): one above fair (Maxey 25+ points, 4+ rebounds, 6+ assists, +9.5%, about +5% after the cut), two at about zero, six at -1% to -14%. The run was stopped there; it says nothing about Kalshi's makers.
- **Checked**: `node --check server.js`, the page's script parses, dry runs of the new board and of Kalshi NBA on the live books.
- **Not checked**: anything that needs the Kalshi key. No three-leg slip has been asked of Kalshi, so whether it will combine three props of one player is not known (a refused slip shows as a miss with Kalshi's reason). The tab was not opened in a browser. Refresh and Bet were not run on a three-leg row.

### Tennis scan: Pinnacle is the sharp price
Max, 11-21: for tennis, use pinny as sharp.

- **Change** (`tennis.py` in the novig-tennis-scan skill; new `pinnacle.tennis()`): every leg's fair value is Pinnacle's no-vig price: the moneyline from its match, the total and game spread from its "(Games)" child match, half-game lines only. Novig's own books are no longer read for a fair value, and a Novig market needs no book to be asked. A match Pinnacle doesn't list, or a line it doesn't price, is left out and named.
- **The fit is per slip**: the model is fitted to Pinnacle's moneyline and to the slip's own total and spread, where before it was fitted once at the match's main lines and read off for the others. The model now only says how the two legs go together.
- **Pairing a match with Pinnacle's**: both players by first initial and surname, starts within six hours (tennis start times drift), and where Novig has a moneyline book, Pinnacle's price within 8 points of it.
- **This morning** (7:03 AM CT): 14 of Novig's 31 singles matches are on Pinnacle; the 17 left out are qualifying rounds. 82 slips priced, one above fair: Alcaraz v Shelton, Shelton +3.5 games + Over 22.5 at 2.55x against a fair +128, +11.9%. Median -9.4%.
- **Alcaraz -3.5 + Under 22.5** (Max's slip at 7:00, 2.80x in the app): fair +151 on Pinnacle's prices (+148 on Novig's books a few minutes earlier). The scan's own ask of it at 7:04 came back 2.32x, -7.7%.
- **Checked**: the lint; every match's pairing read by eye; the pass above. The results check (`tennis_model_check.json`) is unchanged and still feeds the cut.

## 2026-11-20 session

### Kalshi NFL: Unders, QB + teammate stacks, and a new Kalshi NFL Lines board
Max, 11-20: also let's expand NFL. (Taken as the Kalshi NFL board, which asked only one player's own pairs, Yes + Yes.)

- **Kalshi NFL** (`nfl_candidates` in `scan_kalshi.py`) now asks what the Novig NFL tab asks of one team's players:
  - **Unders**: each own pair again as Under + Under (No on the same two markets), at the same correlation. Not where a leg is under 1 reception or the like (that leg decides the other).
  - **Stacks**: a quarterback's passing leg with one of his receivers' (passing yards + receiving yards, passing TDs + his TD, completions + receptions, passing yards + his TD), at the league-wide correlation for a receiver with his targets a game, 0.25 or better, each receiver's two strongest, as Overs and as Unders. And the quarterback's attempts or passing yards against his back's carries or rushing yards: one Over with the other's Under, both ways.
  - A touchdown leg is the anytime one only (a 2+ touchdowns milestone could be taken before, where the anytime one had no book).
- **Kalshi NFL Lines** (new tab; `nflline_candidates`, `--league nflline`): a player's prop with a game line on the side that goes with it, and his Under with the other side. The lines: game total, his team's spread, moneyline and team total, first-half total, spread and winner. Kalshi lists all of them for the NFL. The correlations are the Novig NFL tab's (`scan.line_r`: by position and targets or carries, and by his team's side of today's spread), asked at 0.30 or better: his two strongest over the total, spread and team total, and his best with each kind of line.
  - The other team covering and an Under are No legs; the other team winning is Yes on its own market. A line leg is priced off the tighter of Novig's book on that line and Kalshi's own. A first-half winner leg is Kalshi's book alone: Kalshi's loses on a tie at the half.
- **This week**, built from the live books: Kalshi NFL 1,262 slips on 160 players in 12 games (467 own Overs as before, 461 own Unders, 160 stack Overs, 174 with a stack Under); Kalshi NFL Lines 624 slips on 97 players. A pass still asks 200, and now takes the next day of games first and, within it, the strongest correlation first (it was earliest kickoff first); `--max 0` asks all, `--no-unders` leaves the Unders out.
- **Teams**: Kalshi writes JAC and WAS where Novig and the data write JAX and WSH. A player whose Kalshi ticker is not his team's in the data gets no stack and no line slip.
- **The page**: both tabs have a filter for Unders and for each kind of slip, and a card is headed by its best row.
- **Checked**: the lint, `node --check server.js`, the page's script parses. Dry runs of both boards on the live books, one slip of every kind read through: the right market, the right Yes or No, the right team (a quarterback's attempts with the other team covering, a back's carries with his own). Both tabs opened in a browser against a local server with Kalshi's answers replaced by made-up prices: rows, filters, open rows, no script errors. Those passes asked Novig for a real quote on about 90 slips.
- **Not checked**: anything that needs the Kalshi key. No new slip has been asked of Kalshi: whether it will combine a prop with each kind of line, or a No leg with a No leg, is not known (a refused slip shows as a miss with Kalshi's reason). The Bet button has not been pressed on a row with a No leg on these boards. Kalshi NBA Lines' code was not touched.

### Kalshi CFB: a new board on the Kalshi page
Max, 11-20: can you add CFB to Kalshi.

- **New tab** (Kalshi CFB, after Kalshi CBB; `kalshicfb` in `server.js` and `public/nba_scan.html`, `--league cfb` in `scan_kalshi.py`): the CFB tab's slips asked as Kalshi combos. Fetch only, behind the Kalshi passcode, with the Bet button, like the other Kalshi boards.
- **The slips** are the Novig CFB board's, up to ten a game: underdog's moneyline + Under (main line and the Under nearest +230), those with the underdog's team total Over, favourite's spread + Over, underdog's spread + Under, underdog's spread + his team total Under, favourite's team total Under + Under, both team totals Under, favourite's first-half spread + his spread, first-half Under + Under. Kalshi lists all of these for college football (winner, spread, total, team total, first-half spread and total).
- **Fair value** is the CFB tab's: each leg is Novig's own book on that line, the correlation from the same two-score model (`scan.cfb_candidates`, now called with a test for which lines may be used). A leg is only put on a line Kalshi lists too, so a slip sits on the line nearest even money that both have (Kalshi's are all half points). Kalshi's own books are not used for fair value. They could be on game day: on tonight's lines near even money for Saturday's games the median Kalshi book is 1 cent wide and 84% are inside 5 cents (next week's are 10 to 30 cents).
- **Yes and No**: a favourite's spread, an Over, a moneyline are Yes legs; the underdog's spread is No on the favourite's "wins by over", an Under is No on the Over.
- **Matching a game**: by the day in Kalshi's ticker and both teams, by code or by name; a look-alike counts for less than an exact code or name ("South Carolina St." scored 0.9 against "North Carolina State" letter for letter), and a game is left out when a second Kalshi game comes close. Kalshi's start times were not usable (off from Novig's by anything from 4.5 hours early to 6 hours late).
- **Tonight**, built from the live books: 536 slips on 59 games, every game on the Novig CFB board matched to its Kalshi game, all 59 read through by eye. A pass asks 200 slips, soonest games first (about 15 minutes); `--max 0` asks all.
- **Refresh and Bet** on a row ask Kalshi again at the fair value from the last Fetch, as on Kalshi CBB (the legs are priced off Novig and are not re-read): press Fetch before betting.
- **Checked**: the lint, `node --check server.js`, the page's script parses. The page opened in a browser against a local server on the new tab, with Kalshi's answers replaced by made-up prices (66 rows; the kind filter, the open row, the Novig price beside each row, no script errors). That pass asked Novig for a real quote on each of those 66 slips.
- **Not checked**: anything that needs the Kalshi key (there is none here). No slip has been asked of Kalshi, so it is not known that Kalshi will combine every pairing (two legs on one team's total and the spread, or a first-half leg with a game leg, may be refused; a refused slip shows as a miss with Kalshi's reason), or what its makers pay. The Bet button has not been pressed on this board.

### Kalshi NBA Lines, Kalshi CBB: a card is headed by its best row
Max, 11-20: why is this one hidden under the bad one (Naz Reid 30+ PRA · CHA +7.5 at +3.5%, folded under his -3.0% row).

- The card's head was picked as on the Points + Threes boards: the tier-1 row whose second leg is nearest 50%. On these two boards every row is tier 1, so that was an arbitrary row, and the card sorted by its EV. Now the head is the player's (or game's) best row, so the card sorts by its best price (`public/nba_scan.html`).

### Tennis model checked against 36,435 real matches; the data is saved
Max, 11-20: check vs real results. Save data.

- **Data** (`public/data/tennis_matches.json`, 0.9 MB): every completed best-of-three ATP tour match from 2005 to this week, 36,435 of them, each with its set scores, surface, year and the favourite's chance to win. Source: TennisMyLife's TML-Database on GitHub (ATP results; its terms allow non-commercial use only). It has no odds, so the favourite and his chance come from an Elo rating run forward from 1990 that never sees the match it rates. Left out: retirements, walkovers, Davis Cup, matches with a deciding match tiebreak, players' first 20 matches.
- **The check** (`scripts/tennis_model_check.py`; results in `public/data/tennis_model_check.json`): matches grouped by the favourite's chance (eight groups, 3,000 to 6,200 matches each). In each group the model is fitted as the scan fits a match, to how often the favourite won, went over the middle total and covered the middle game spread; then its joint for each of the scan's slips, on those lines and the ones either side, is set against the share of matches where both legs hit.
- **Game spread + total slips** (the ones that were plays): the model's fair value is within 3% of the count on average in every group. Underdog + games with the Over: -5.0% to +3.0% by group, the worst single line +6.0%. Favourite - games with the Under: -4.1% to +2.4%, worst -7.6% (a minus is the model under the count). Standard error about 2 points a line.
- **Moneyline + total**: favourite + Under -4.1% to +3.1%. Underdog + Over runs too high against strong favourites: +5.8%, +4.7%, +7.8%, +7.7% in the four groups from 70% up.
- **Three-setters**: the model is within 2.4 points of the count in six groups of eight (the 50-55% group 43% against 39%, 55-60% 34% against 37.5%).
- **Change** (`trim` in `tennis.py`): where the model ran high for a kind of slip at that strength of favourite, the scan divides its fair value by that much; where it ran low nothing is added. At an 81% favourite: 3.0% off underdog + games with the Over, 2.1% off favourite - games with the Under, 7.8% off underdog moneyline with the Over. Under 70% the cut is nothing or close to it.
- **This morning's Alcaraz v Cobolli slips with the cut**, at the prices Novig paid then: Cobolli +4.5 + Over 21.5 fair +166, +13.3% (was +159, +16.7%); Alcaraz -4.5 + Under 21.5 +6.2%; Cobolli +4.5 + Over 20.5 +6.0%; Alcaraz -4.5 + Under 20.5 +4.0%. All four still above fair.
- **What the check is not**: a group mixes many players of different serve strength, which one match's fit never has, and its favourite is an Elo rating, not a market price. Hard and clay apart give the same picture with wider errors (in the file); grass has too few matches for a group. Tour matches only: no Challengers and no WTA, which are most of what Novig lists.
- **Not downloaded**: tennis-data.co.uk (odds with scores) refuses the request, and Jeff Sackmann's repositories could not be reached from here.

### Tennis scan saved as a skill; no tennis plays this evening
Max, 11-20: can you see if there are any more tennis plays? Save skill.

- **New skill** (`.claude/skills/novig-tennis-scan/`: `tennis.py`, `SKILL.md`): the tennis look from this morning as one script. It fits a score model (points won on serve, with a match-to-match swing in the gap between the players) to each best-of-three singles match's moneyline, main total and main game spread on Novig, and asks game spread + total and moneyline + total slips against it, once each.
- **This evening** (3:01 PM CT, 11 Challenger and WTA matches with tight books, 68 slips): none above fair, best -2.3% (Gorzny -1.5 games + Under 23.5), median -15%.
- **Not on the dashboard**: it is a script and a skill, not a board.
- **Checked**: the lint; the fit on this morning's Alcaraz v Cobolli prices (3 sets 28% to 31% across the kept fits, the table sums to 1); the pass above. The model is still not checked against results.

### Kalshi Scan: a board clears when Fetch is pressed
Max, 11-20: for Kalshi, I want the board to clear when I hit Fetch.

- **Change** (`startNovigScan` in `server.js`): a pass on a Kalshi board empties that board as it starts, and the rows come back as Kalshi answers. Before, the last pass's rows stayed at their old prices until the new pass reached each one, and one it no longer asked went only when the pass finished.
- **A stopped pass**: the rows it reached are on the board; the rest are gone, where they used to stay at their earlier prices. A pass that fails to start clears nothing.
- **Unchanged**: the Novig boards, and the other Kalshi boards while one is fetched.
- **Checked**: `node --check server.js`. Not run against Kalshi (no key here).

### Novig soccer: a corners or goals leg needs no Novig book
Max, 11-20 (from the check below: a line Pinnacle prices was skipped where Novig's book was one-sided): fix soccer. No need for both sides.

- **Change** (`soccer_candidates` in `scan.py`): a corners or goals market is used whether or not Novig has a bid on both sides of it. Its fair value was already Pinnacle's; Novig's book was only a condition for looking at the line.
- **Still needed**: a two-sided Novig book on each team's win market. That is how the favourite is told from the underdog and how the match is checked against Pinnacle's (same kickoff, names, and a win price within 6 points).
- **Today**, built from the live books: 137 slips on 54 matches, 21 of them (8 matches) with a leg Novig has no two-sided book on. Those were not asked before.
- **Novig prices them**: six such slips asked, all quoted. Bournemouth v Nottm Forest's three +0.2% to +2.4%; Liverpool v Man Utd -59% and -34%; Brighton v Hull -24%.
- **The page**: a row's books line says "none" for such a leg, and the leg's note reads "Novig has no two-sided book" beside Pinnacle's price. No soccer row is marked rough: every leg is Pinnacle's price.
- **Checked**: the lint, the alert checks, the page's script parses. A full pass was not run and the page was not opened on such a row.

### A check of tonight's changes for bugs
Max, 11-20: can you check for any bugs.

- **No bug found in what runs.** Fixed: three notes that still described the old behaviour (the skill's soccer paragraph, two comments on when alerts are sent) and one dead line on the page (a row's "settled over N asks").
- **Checked**: `scan.py` and the correlations script lint clean. A real soccer pass, stopped at 48 of 119 slips: every leg on Pinnacle's price, none marked rough, no underdog-to-win slip under 26%, rows from six leagues. Pinnacle made to fail: the pass stops with the message, which the server shows as the board's error. `--fetch-americas`, not run before, run for 2026: 510 MLS and 311 Liga MX matches, every row identical to the committed files. The page opened in a browser against a local server on the Soccer, CFB and All tabs: no script errors, the new notes show, nothing about Discord.
- **Not bugs, but they follow from tonight's rules**:
  - Auto-scan switched on with **Wide books** ticked sends no Discord alerts at all: wide passes never alert, and Auto-scan is now the only way alerts go out.
  - Anyone with the scanner's passcode can switch Auto-scan, and so the Discord alerts, on or off.
  - A soccer leg needs a two-sided Novig book as well as Pinnacle's price; a line Pinnacle prices where Novig's book is one-sided is still skipped.
- **Not checked**: the live server; a real webhook; a phone.

### One button for the page and for Discord
Max, 11-20: yes. One button for dashboard and Discord. Should be the same.

- **Change** (`nvAlert` in `server.js`): Discord alerts are sent only while Auto-scan is on. With it off nothing is sent, the rows of a Fetch or of a row's refresh included (after the entry below, those still alerted).
- **So**: Auto-scan on, the server prices the boards and Discord gets the plays; off, neither happens. A Fetch with it off fills the page only.
- **Unchanged**: wide-book passes and the Kalshi and DK boards never alert; NBA Ladder and NFL Ladder are Fetch only, so their rows alert when fetched with Auto-scan on.
- **The page**: the button's hover text says the server prices nothing by itself with it off. It still says nothing of Discord.
- **Checked** on a local server, alerts in dry run with the bar at 0%: a CFB Fetch with Auto-scan off priced 133 rows, 32 above fair, and logged no alert; rows priced after Auto-scan was switched on were logged within 10 seconds. The alert checks pass.
- **Not checked**: on the live server, or with a real webhook.

### Auto-scan is the only thing that starts passes
Max, 11-20 (the page at 2:00 AM, Auto-scan off, "soccer scanning 25 / 111"): auto scanner isn't on but it keeps pulling lines. Then: make the Auto-scan button the only thing that starts passes.

- **What it was**: the Discord alert job. Since 11-19, with alerts on and Auto-scan off, the server priced the alert boards in turn by itself so there was something to alert on. Nothing on the page said so (Discord is kept off the page).
- **Change** (`nvCyc` in `server.js`; `novigAlerts.js`): that cycle is removed. A pass starts from Auto-scan or a Fetch and from nothing else. The alerts read whatever passes run, so with Auto-scan off there are alerts only for boards someone fetches. `ALERT_SCAN_SPORTS` is gone (read by nothing); `ALERTS_ENABLED` now only sends.
- **Why it matters beyond the page**: a background pass asks Novig for the slips about to be built in the app, which can cost the better quote (see the re-ask entry below).
- **Auto-scan's state is saved**, as before: on stays on across a restart, off stays off.
- **Checked** on a local server with alerts on (dry run): the old code started a pass within 50 seconds with Auto-scan off; the new code started none in 60 seconds, started one within 50 seconds of Auto-scan being switched on, and none in 45 seconds after it was switched off. The alert checks pass. The first run of this test caught a start-up crash (a log line still read the removed list), fixed before the commit.
- **Not checked**: on the live server, or with a real webhook.

### Novig Scan: each slip is asked once a pass; the re-ask is gone
Max, 11-20 (the board's WYO ML + Under 37.5 at 7.54x, 31 seconds old, beside the app's slip for it at 6.27x: not matching; then: we don't double ask, right? drop the re-ask, let's test it).

- **What the mismatch was**: not the fee. Novig's quote on that slip depends on when it was last asked. 18 asks over 13 minutes: 36 seconds apart it was 7.54x and 6.27x on about every other ask (4 and 5 of 9); 90 seconds apart, 7.54x, 7.30x, 7.54x, 7.54x after one 6.27x. The board had asked 31 seconds before the app did.
- **The re-ask did the same thing to the board**: since 11-14 a slip above fair was held and asked again 40 seconds later until two quotes agreed (up to four asks, then the worse of the last two). Only plays were asked more than once, at a gap inside that minute.
- **Change** (`scan()` in `scan.py`): every slip is asked once a pass and its row is that quote. `SETTLE_S`, `SETTLE_TOL`, `SETTLE_MAX`, the held list and `first_x` / `asks` on a row are gone. Later passes and a row's refresh button still ask the slip again.
- **The page**: the note on quotes says one ask a pass, and to leave a row alone about 90 seconds (no refresh) before building it in the app.
- **Tested**, tonight's CFB games, 57 slips: the pass took 68 seconds. Its 10 slips above fair, each asked again after 100 seconds or more: all 10 the same price as the pass. Asked once more 36 seconds after that: 8 the same, 2 lower, both two-leg slips of UNM @ WYO (WYO ML + Under 37.5 7.54x to 7.36x; WYO +7.5 + Under 37.5 3.80x to 3.25x). So the drop on a quick second ask is some slips, not all.
- **Not known**: why. It reads like one of Novig's pricers not quoting a slip again straight after quoting it, from two slips of one game. The 11-14 cases that led to the re-ask (Goff 4.14x then 2.32x on every ask after) may have been this, or may have been first quotes that never came back; not re-tested.
- **Watch for**: a row whose price is not on the slip after a 90-second rest. That would be the 11-14 problem back.
- **Not checked**: against the app (only the keyless quote); the page was not opened; Discord alerts now fire on a single quote.

### Novig Scan: soccer adds MLS and Liga MX, every leg's fair value is Pinnacle's, and teams are matched by Novig's id
Max, 11-20: let's add those 2 soccer leagues. And always use pinny=sharp to calc FV. Calc a separate MLS correlation to make sure it still holds.

- **Leagues** (`SOCCER_LEAGUES` in `scan.py`): MLS and Liga MX join the top five and the Champions League.
- **Pinnacle only** (`soccer_candidates`): every leg's fair value is Pinnacle's no-vig price on that line. The middle of Novig's own book is no longer a fallback: a match Pinnacle doesn't list, a corner or goals line it doesn't price, and a moved line it doesn't price are not asked, and if Pinnacle doesn't answer the pass stops with that message. Soccer only; the other boards are as they were. Pinnacle posts one corner line a team, about a day before kickoff, so that is when a match appears.
- **The correlation check** (`scripts/soccer_corner_correlations.py`, new `--fetch-americas`, `measure`, `holds`; `by_league` in `soccer_corner_correlations.json`): 4,871 MLS and 3,365 Liga MX matches, 2016 to 2026 (results and closing odds from football-data.co.uk, Pinnacle's where it has them; corners from ESPN, paired by date, score and names). Each league measured alone, then the top five's fair value set against each league's counted hit rate:
  - MLS, favourite under 50% (2,546 matches): favourite slip -7.0%, mirror -6.7%, with Over 1.5 -4.2%, with Over 2.5 +0.5%. 50-60% (1,503): -3.3%, -1.2%, -4.8%, -3.6%. 60-70% (678): -3.1%, -4.9%, -5.2%, -5.9%. Minus means the board's fair value is under what happened, so it understates a slip. All inside one and a half standard errors (5 to 16 points).
  - Liga MX, under 50% (2,078): -1.5%, -12.1%, +1.0%, +0.9%. 50-60% (759): +4.3%, -3.6%, -2.0%, -2.9%. 60-70% (419): -1.3%, -3.9%, -4.2%, -13.4%. All inside one standard error (6 to 21 points) but the mirror under 50%, which the board understates by 12% (1.8 standard errors).
  - The pair r's are close to the top five's (MLS 50-60%: favourite win with his corners Under 0.20 against 0.19, underdog win with the favourite's corners Over 0.24 against 0.28, the two corner legs 0.20 against 0.17).
- **So** both leagues are priced on the top five's correlations (19,761 matches), not their own: the league samples are too small to beat them and show no sign they differ. The top five's numbers in the file are unchanged.
- **Not measured**: favourites of 70% or more. MLS has 144 such matches and Liga MX 109, too few; a favourite that strong in either league is priced on the top five's 70%+ numbers untested.
- **Found on the way: matches were being dropped.** A team's corner market was found by its name starting with the win market's name. Novig's names differ (Man Utd / Manchester United FC, Man City / Manchester City FC, Inter Miami / Club Internacional de Futbol Miami, nearly every Liga MX team), and such a match was left out without a message. Now matched by Novig's id for the team (`subjectId`, which both markets carry). Today's board, built without quoting: 54 matches and 139 slips, 6 of the matches from the new leagues (Inter Miami v Columbus, Dallas v Portland, Philadelphia v New England; Tijuana v Atlante, Puebla v San Luis, Atlas v Juarez).
- **Cost**: more quotes a soccer pass, from the new leagues and the matches no longer dropped; not counted against the old matching.
- **The page**: the soccer note names the leagues and says Pinnacle only.
- **Checked**: candidates built from the live books, every leg on Pinnacle's price; a quoted pass on the two new matches (7 slips priced; Atlante win + Tijuana O5.5 corners + Atlante U4.5 at 15.76x against a fair +1366, +7.5%; Inter Miami's three -19% to -68%); the alert checks.
- **Merged with** this morning's change (no underdog-to-win slip under 26%, the 50% match filter taken back), which landed while this was being built: its rules are kept.
- **Not checked**: `--fetch-americas` as committed was not run end to end; the two match files were built by the same steps in separate scripts. A full quoted pass of all 139 slips was not run and the page was not opened.

### Auto-scan: the NFL waits for the day before, but for one slip
Max, 11-20: remove NFL until day before, limits too small; maybe except the QB 2+ TD with a player TD.

- **Change** (`NV_CYCLE_DAY_BEFORE` in `server.js`; `--full-before` in `scan.py`): Auto-scan prices an NFL game in full only from the day before it (a game starting before tomorrow's midnight, by the time zone Auto-scan was switched on with). A game further off gets one slip a receiver: his QB's 2+ passing TDs with his TD. The alert job's own passes follow the same rule.
- **Fetch** on the NFL tab still prices everything, any day. NFL Ladder was Fetch only already.
- **Today** (Friday, Sunday's games): 1,552 slips become 22, read from the start of a pass each way.
- **On the page**: the other NFL rows go at the end of the next Auto-scan NFL pass, and come back on Saturday for Sunday's games (Sunday for Monday night's).
- **Not checked**: no whole Auto-scan pass was run, and the page was not opened.

### Novig Scan: soccer has no slips on a big underdog to win
Max, 11-20 (the soccer board, underdog-to-win slips on top: Leeds, Sunderland, Udinese, Ipswich): I only want the favorites or close games priced. Don't want big dogs.

- **Change** (`SOCCER_DOG_MIN`, `soccer_candidates` in `scan.py`): the mirror slip (underdog to win + favourite's corners Over + underdog's corners Under) is asked only in a close game, where the underdog is at least 26% to win (about +285 or shorter; Pinnacle's no-vig price, Novig's book where Pinnacle has none). The favourite-to-win slips are asked on every match, as before. It replaces the rule that asked the mirror wherever the favourite was under 70%.
- **Why 26%**: today's underdogs fall in two groups, 15% to 24% (Leeds 24%, Valencia 23%) and 28% to 35% (Everton, Elche, Lyon, Sevilla, Crystal Palace); the line is between them. It is one number.
- **First try, taken back the same morning**: the request was first read as matches with a clear favourite only, and matches whose favourite was under 50% were dropped (`SOCCER_FAV_MIN`, 221bad6). That removed the close games and kept the big underdogs. It is gone; every match is back.
- **Today's board**, listed without quoting: 13 matches; the mirror on 5 (Brentford v Everton, Levante v Elche, Lille v Lyon, Real Betis v Sevilla, Coventry v Crystal Palace), no longer on Chelsea v Leeds, Aston Villa v Sunderland, Bologna v Udinese, Tottenham v Ipswich, Arsenal v Newcastle, Brighton v Hull, Rayo Vallecano v Valencia.
- **On the page**: the big underdogs' rows go at the end of the next soccer pass.
- **Not checked**: no pass was quoted and the page was not opened.

## 2026-11-19 session

### Novig account read taken out: the API does not list parlays
Max, 11-19 (Novig's developer team, by email): "No. The v3 API has no route that lists the parlays you placed in the app or their legs. The v3 RFQ routes serve makers only."

- **So**: open parlay bets can't be read from Novig, with any key. The look built for it this morning is removed: `novigAccount.js`, `GET /api/nba/novig-account-probe`, the **Check Novig bets** button on the Kalshi page, and its signing vectors. `NOVIG_KEY_ID` and `NOVIG_PRIVATE_KEY` are read by nothing; no key needs making.
- **Their note on the "Key Not Created" error**, for the record: an account must finish identity verification before it can create a key, and a VPN, iCloud Private Relay, WARP or a proxy gets the request refused.
- **What is left for not alerting a bet already held**: Max marking it. Not built yet.
- **Checked**: the server file loads, the alert checks pass, no mention of the button is left in the page.
### Novig's parlay fee: back to the old one, which the app still charges
Max, 11-19 (an alert at 6.77x beside the app's slip for the same legs at 6.92x, $100 paying $691.89): prices aren't matching exactly.

- **What it was**: last night's change moved the scanner to Novig's new parlay fee (0.055 x -ln(price) x stake) on the date its fee page gives, 11-19, without a slip to check it against. At 9:48 AM CT the app was still charging the old one (0.10 x (1 - price) x stake): $691.89 on $100 is the old fee at a 0.133 quote to the cent, and the new fee at that quote is 6.77x, the alert's number.
- **Change** (`FEE_RULE`, `FEE_RULES`, `slip_multiplier` in `novig.py`): the old fee again. Both are kept; `FEE_RULE = "new"` is the switch for when the app moves.
- **What moves**: slips longer than about +270 pay more than the boards said (this one 6.92x, not 6.77x: +12.8% where the alert said +10.4%), and shorter ones a little less (a 0.50 quote: 1.905x, not 1.927x, 1.2% of EV; a +178 Points + Threes slip about 0.6%).
- **Since last night** the boards and alerts under-read long slips and over-read short ones by those amounts.
- **Not known**: when Novig switches. The fee page still says 11-19; the quote's answer carries no fee to read. A slip in the app that pays less than its row on a long slip is the sign.
- **Checked**: the old rule gives 4.25x at 0.218 and 6.919x at 0.133; the new rule still gives the docs' three examples. One slip is the evidence for the app's fee.

### Discord alerts: Novig's price is in the heading
Max, 11-19 (a message headed "Strus: 10+ PTS, 2+ 3PM · +5.2%"): add the multiplier in the title; it gets lost in the message.

- **Change** (`embed` in `novigAlerts.js`): the heading carries Novig's slip price between the legs and the EV: "Strus: 10+ PTS, 2+ 3PM · 2.78x · +5.2%". An edited message (MOVED UP) shows the new price.
- **Checked**: the alert checks.

### Discord alerts: the heading says who and what
Max, 11-19 (a message headed "Emari Demercado (HOU) · +11.9%"): make the heading "Demercado: 25+ Rush, 1+ TD". Not just the name.

- **Change** (`heading` in `novigAlerts.js`): a message's heading is the player's last name and the legs, then the EV: "Demercado: 22+ Rush, 1+ TD · +11.9%". It is the line a phone's notification shows. The team is no longer in it (the game is on the next line).
- **Stat words** are shortened in the heading only: RUSH YDS is Rush, YDS is Rec Yds, PASS YDS is Pass Yds, CAR is Carries, PTS+REB+AST is PRA. The legs list underneath is as it was.
- **Two players**: the first one's last name, then the legs ("Stroud: 230+ Pass Yds, Collins 70+ Rec Yds"); NBA teammates' legs already name both.
- **A game's own lines** (CBB, CFB, soccer, NBA Team's game slips): the legs alone, which name the teams.
- **Checked**: the alert checks, with these headings added.

### Novig NBA: Points + Rebounds is back, for every player
Max, 11-19 (a Kalshi NBA row, Burries 10+ points with 6+ rebounds at +5.8%, Novig paying the same 3.75x for it: plays like this don't come up on NV, just Kalshi): let's add points and rebounds back.

- **Why it was missing**: the NBA board asked one slip a player, Points + Threes (11-10), and before that Points + Rebounds for big men only.
- **Change** (`candidates` in `scan.py`; the NBA tab's note in `public/nba_scan.html`): the NBA board also asks each player's main-line Points + Rebounds, Over + Over, where his shrunk r is 0.25 or better (`--pr-r`, Kalshi NBA's bar) and each leg's fair value is 30% or better (`--pr-leg`, Kalshi NBA's floor). `--no-pr` drops it. NBA Ladder, NBA Team and `--scope all` are unchanged.
- **Not gated**: the slip is asked whatever his Points + Threes priced at. The gate would have dropped most of them, and one pair's price says little about the other's.
- **Lines**: Novig's main lines, which are not Kalshi's milestones (Burries: 12+ and 5+ on Novig against Kalshi's 10+ and 6+), so the same player can be a play on one board and not the other.
- **The 30% floor**: a main line is the tight book nearest even money. The first dry run had Burries at 20+ points (8%), the only tight book left on his ladder.
- **Cost**: 17 more slips on tonight's five games (28 before, 45 now), each an auction Novig's pricers see.
- **The page**: in Plays, a card whose Points + Threes row is under Min EV is now headed by its best row that clears it; it was headed, and sorted, by the Points + Threes row.
- **Alerts**: a Points + Rebounds slip alerts at the general bar (`ALERT_MIN_EV`), not Points + Threes' lower one.
- **Checked**: candidates built from tonight's live books with the slip on and off (no quote asked): the other 28 slips are the same. A pass with quotes was not run.

### Discord alerts, CBB: one message a game for each type of slip
Max, 11-19: actually for CBB, one bet per type. I don't need 3 notifications for unders. I like double unders more than +4.5 and same team under 55.

- **Change** (`typeOf` in `novigAlerts.js`): on CBB a game gets one message per type of slip, where this morning's rule was one per game. A type is the slip's shape (spread + total, a team total Under + the game Under, both team totals Under, ...), so the same slip with a leg moved a line, which is where the three Unders messages came from, is not sent again. `ALERT_ONE_PER_TYPE` (cbb) names the boards.
- **The double Under first**: both team totals Under and the underdog covering with his own total Under share a leg and count as one type, with the double Under ahead. Once it has gone the other is not sent; if the other went first, the double Under still goes.
- **`scan.py`**: a college row carries its shape's name (`shape`), which the rule reads (a row priced before this is typed by its label with the numbers out). The double Under is now asked before the underdog-covers slip in each game. No fair value or price changes.
- **Which line of a type**: the first to clear the bar, the main line before the moved ones.
- **Checked**: the alert checks. `scan.py` loads; a CBB pass was not run.

### Discord alerts: every slip is sent; one message a game is CBB's rule only
Max, 11-19: I don't care about 1 message per game for anything but probably CBB.

- **Change** (`novigAlerts.js`): the rule that held a player's second slip back (and a game-line slip one line over) is gone. Every slip over its bar is sent, once each: Hutchinson's three-leg slip and Collins's passing yards + receiving yards, held back this morning, now go. On CBB a game gets one message, the first slip of it to clear the bar (`ALERT_ONE_PER_GAME`, cbb; other boards can be added).
- **Unchanged**: a slip is never sent twice. `ALERT_REALERT_STEP` is gone with the rule it tuned.
- **Checked**: the alert checks (a player's second slip sent; CBB's second slip of a game not, another game's sent; two soccer slips a line apart both sent).

### Discord alerts: a sent message is edited only for a move up
Max, 11-19: no. I don't want a push notification if no longer a play or moved down. I'd have probably already taken the play.

- **Change** (`update` in `novigAlerts.js`): a sent slip's message is edited only when its EV is 2 points above the best the message has shown (MOVED UP). A slip that moved down, fell under its bar, or whose player is now out leaves its message as it was. MOVED DOWN and PLAYER OUT are gone.
- **About the notification**: I had said Discord doesn't notify for an edit. Max got one, or something like it; not looked into. `ALERT_UPDATE_STEP=0` stops every edit, the move up included.
- **Checked**: the alert checks.

### Discord alerts: no limit a game, and every Novig tab alerts
Max, 11-19 (the All tab beside the channel: seven plays at 10% or better, two in Discord): also not sending every play.

- **What held them back**: two rules of mine. Two alerts a game at most: IND @ HOU was the only NFL game, so its first two slips over the bar (Hutchinson, Collins) went and Jonathan Taylor at +22.9% and Tyler Warren at +22.2% did not. And only five tabs alerted: NBA Team (LAC @ SAS, +32.0%) and CBB (COFC @ DRKE, +10.7%) were not among them.
- **Change** (`novigAlerts.js`): no limit a game (`ALERT_MAX_PER_GAME`, 0; a number brings it back). `ALERT_SPORTS` is every Novig tab on the page: NBA, NBA Ladder, NBA Team, NFL, NFL Ladder, soccer, CFB, CBB. With Auto-scan off the alert job prices all of those but NBA Ladder, which is Auto-scan's own list.
- **Still one message a player a game**: Hutchinson's three-leg slip (+15.7%) and Collins's passing yards + receiving yards (+10.7%) are second slips on players already sent, and stay unsent. Still one message per game-line slip shape, none for a rough fair value, a started game or a player listed out.
- **The plays held back** go out the next time a pass prices them, if they are still over the bar.
- **Checked**: the alert checks (six players of one game all sent; the limit when set).

### Discord alerts: no more NO LONGER A PLAY
Max, 11-19 (screenshot: "NO LONGER A PLAY · Xavier Hutchinson · +7.2%"): don't send this.

- **What it was**: a sent slip whose EV fell under its bar (10% here) had its message greyed and titled NO LONGER A PLAY, at any EV, +7.2% included.
- **Change** (`update` in `novigAlerts.js`): falling under the bar is no longer an event. A sent slip's message is edited only when its EV is 2 points off what the message last said, titled MOVED UP or MOVED DOWN; that one would have read MOVED DOWN, +10.0% → +7.2%. The grey title is kept for one case, a player ESPN now lists as out, and reads PLAYER OUT.
- **Messages already titled NO LONGER A PLAY** stay as they are unless their slip moves 2 points again.
- **No edits at all**: `ALERT_UPDATE_STEP=0`.
- **Checked**: the alert checks.

### Novig Scan and Kalshi Scan are the first two tabs
Max, 11-19: make the scanner tab and Kalshi all the way to the left.

- **Change** (`index.html`): the NOVIG SCAN and KALSHI SCAN buttons come first in the tab bar, before NBA. They still show only on a device that has opened them; the tab the app opens on is unchanged.
- **Checked**: in a phone-sized browser with both tabs switched on, the bar reads NOVIG SCAN, KALSHI SCAN, NBA, NBA TEAMMATES, ...

### Novig Scan: nothing about Discord on the page
Max, 11-19 (screenshot of the status line): hide discord stuff.

- **Change**: the green line "Discord alerts are on and keep ... priced" is gone. Other people use this page. With the test button already off, the page says nothing of the alerts; they run as before.
- **Left**: while the alert job is pricing a board, the page still says a pass is running on it, as it does for any pass.
- **Checked**: no mention of Discord is left in the page; not opened in a browser.

### Send test alert button removed; Check Novig bets is on the Kalshi page only
Max, 11-19: remove the test button. Is everyone going to see my bets now?

- **Send test alert** is off the page. Its route is still on the server.
- **Check Novig bets** was on the Novig page, where everyone with the scanner's passcode saw the button (not the bets: those needed the second passcode). It is now on the Kalshi page only (`?kalshi`), and uses that page's passcode.
- **The built-in second passcode** (`yyy`, when `KALSHI_TAB_KEY` is not set) is written in the code, so it is no lock. The account read is off unless `KALSHI_TAB_KEY` is set on the server.
- **Checked**: the page loads in a browser without errors on both pages; the button is absent on the Novig page and present on the Kalshi one; the route's three refusals.

### Novig account: a read-only look at what bets the API shows
Max, 11-19: how do we not send bets I already have; can we build it from my open bets API? Try the key.

- **Why a look first**: Novig's docs let a key read the account's positions, fills and ledger, the app's own wallet included (under a management key), but describe a position as one market and one outcome. Nothing says a parlay bought in the app appears there, or with its legs. One read answers it.
- **`novigAccount.js`**: signs GET requests the way Novig asks (NOVIG-V3; Ed25519 or P-256) with `NOVIG_KEY_ID` and `NOVIG_PRIVATE_KEY` (the downloaded .pem's contents). GETs only: it cannot place, cancel or move anything. Neither value is logged or sent to the page.
- **`GET /api/nba/novig-account-probe`** and a **Check Novig bets** button on the page: each account read's status, how many rows per wallet, the field names, and the first rows with their markets named from the public catalog. It needs the second passcode (the Kalshi page's) as well, since other people have the scanner's.
- **Nothing uses it yet**: the alerts don't read the account. That waits on what the look shows.
- **Checked**: the string signed matches all 30 of Novig's published vectors (in `scripts/novig_alerts_check.js`), and the signatures matched its two test keys. One live call with the published test key: Novig answered 401 "api key not found" on every route, as its docs say an unknown key gets. Not run with a real key; the button was not pressed in a browser.

### Discord alerts: the phone's link opens the app without asking
Max, 11-19: the 2nd link works.

- **Change** (`embed` in `novigAlerts.js`): an alert's title and its first link, **Open in the Novig app**, are `https://novig.onelink.me/JHQQ/events/<outcome ids>`, the link that was on trial below. The second link, **on a computer**, is the old one (`/n/<outcome ids>`, which goes to novig.com); the app link is a dead page in a computer's browser.
- **`/n/` on a phone** (`server.js`): its "Open in the Novig app" button is that same address, and the page no longer opens `novigapp://` by itself, which is what made Safari ask. The scanner page's own rows on a phone are unchanged (`novigapp://`).
- **Checked**: the alert checks; `/n/` answers. Not seen on a phone.

### Discord alerts: a second link on trial, to open the app without iOS asking
Max, 11-19 (iPhone screenshot: "Open this page in Novig?"): any way to not make links do this?

- **Why it asks**: the `/n/` page opens the app by its `novigapp://` name, and Safari asks before it follows any such address. A page can't switch that off.
- **What doesn't ask**: a universal link, an ordinary https address the app has claimed. Apple's list has none for novig.com; Novig's one is `novig.onelink.me/JHQQ/*` (its association file, read 11-19), which the app's own router also lists as a link prefix (11-16).
- **Change**: each alert has a second link, **App, no prompt (trial)**, to `https://novig.onelink.me/JHQQ/events/<outcome ids>`. The first link is unchanged.
- **Not known**: whether the app puts the legs on the slip from that address, or only opens. It can't be tried from here: in a browser it is a 404, so it is no use on a computer or without the app. If it fills the slip on the phone it becomes the phone's link; if not it comes out.

### Discord alerts: an "Open in Novig" link in the message
Max, 11-19: add a link to Novig to the Discord message.

- **Change** (`embed` in `novigAlerts.js`): the message's second line is **Open in Novig ↗**, the same address the title already linked to (`/n/<outcome ids>` on this app: the Novig app on a phone, novig.com on a computer, legs on the slip). The title's link was easy to miss. A test alert sent while no board has a row links to novig.com; it had no link at all.
- **Checked**: the alert checks. Not seen in Discord.

### Novig tabs and alerts: $100 a unit, as on the Kalshi page
Max, 11-19: switch my units to the same units as Kalshi.

- **Change**: the QK $ column on the Novig tabs (`UNIT` in `nba_scan.html`) and the stake in a Discord alert (`ALERT_UNIT` in `novigAlerts.js`) are at $100 a unit; both were $500. The QK column in units is unchanged: 0.60u is now $60, was $300. `ALERT_UNIT` on the server sets the alerts' unit to something else.
- **Not changed**: `scan.py`'s own `wager` field ($250 a unit, $500 for the NHL), which only its command-line table prints.
- **Checked**: the alert checks, with the stake line at the new unit. The page was not opened.

### Novig's parlay fee is the new one
Max, 11-19: yes, update the fee.

- **Change** (`novig.slip_multiplier`): the fee on a parlay is 0.055 x -ln(price) x stake, Novig's from 11-19 (docs.novig.com/fees, "RFQ trades"; its changelog of 11-16). It was 0.10 x (1 - price) x stake. Every Novig board's slip price, EV and stake come through this one function, and so do the alerts and the Kalshi boards' Novig comparison.
- **What moves**: slips shorter than about +270 pay a little more than the page said (a 0.50 quote: 1.927x, was 1.905x) and longer ones less (0.20: 4.59x, was 4.63x; 0.10: 8.88x, was 9.17x, 3.2% of EV). The Ladder tabs are the longest slips.
- **Rows already on the boards** keep the old fee's numbers until their next pass or refresh.
- **Checked**: the docs' three examples ($100 at 0.50 is $3.81, at 0.25 $7.62, at 0.10 $12.66). The page's and the skill's text no longer says 10%.
- **Not checked**: a slip in the app. Put one on and compare its multiplier with the row's.

### Novig Scan: Discord alerts
Max, 11-19: a background job that finds +EV parlays and posts them to my Discord channel. 5% for Points + Threes, 10% for the rest; not the same kind of bet over and over.

- **What sends** (`novigAlerts.js`, called from `server.js` for every row a pass or a row's refresh prices): a slip at 10% EV or better, 5% for an NBA main-line Points + Threes slip, whose game hasn't started, whose player ESPN doesn't list as out, whose fair value isn't rough (a wide book), and whose Novig quote has 10 seconds or more left. Nothing is priced there: fair value, EV and quarter Kelly are the row's own (`scan.py`'s `finish`). The stake is the row's QK at $500 a unit, the page's QK $. Wide-book passes and the Kalshi boards don't alert.
- **Not repeating**: a slip is sent once and never again, whatever its price does (Max, 11-19: a second message is a second bet). A player's other slips in the same game count as that slip and are not sent either; nor is a slip across a game's own lines one line over. `ALERT_REALERT_STEP` (0: never) lets a different slip on the same player through at that many EV points better, marked "better than the last"; the same slip still never. Two alerts a game at most. What was sent is kept in `novig_alerts.json` beside the boards, so a redeploy doesn't send it again (where `/data` is the volume).
- **A sent slip that moves** (Max, 11-19: could it show it moved, or the FV moved down?): its message is edited where it stands, never sent again, so there is no second message to bet from. When the slip's EV is 2 points (`ALERT_UPDATE_STEP`) off what the message last said, the title becomes MOVED UP or MOVED DOWN and the message says what changed since it was sent: Novig 3.75x → 3.92x, Fair +250 → +270 (longer: less likely to hit), EV +7.1% → +12.0%. A slip that falls under its bar, or whose player is now out, is greyed and titled NO LONGER A PLAY. Discord sends no notification for an edit. Not marked: a slip Novig stops pricing altogether.
- **The job**: with `ALERTS_ENABLED=1` and Auto-scan off, the Auto-scan cycle prices the alert boards on its own (NBA, NFL, NFL Ladder, soccer; each board's next day of games, tight books). NBA Ladder alerts only when it is fetched. With Auto-scan on, its passes are what the alerts read. A pass is one quote a second, so a slip alerts when the pass reaches it.
- **The quote's expiry**: Novig's answer carries `expiresAt` (30 seconds after the quote, seen 11-19); `novig.parlay` keeps it and each row now has `expires`. The message shows it as a countdown.
- **The message**: player and game, each leg with its fair price, Novig's slip price, fair, EV, stake, expiry, tab. The title links to `/n/<outcome ids>` on this app (`PUBLIC_URL`, or Railway's domain), which opens Novig with the legs on the slip. A stake on the slip needs a Novig partner id (affiliates@novig.co), which we don't have.
- **Discord's limits**: one message at a time; a 429 waits `retry_after` and sends again. A message that can't be sent before its quote expires is dropped and the slip can alert next pass. The webhook address is never logged or sent to the page.
- **Page**: a **Send test alert** button (one message marked TEST, with the best alert-board row's numbers; asks Novig nothing), and a status line when the alert job is pricing boards.
- **Settings**: `DISCORD_WEBHOOK_URL`, `ALERTS_ENABLED`, `ALERTS_DRY_RUN` (prints would-be alerts to the log, posts nothing), `ALERT_SPORTS`, `ALERT_SCAN_SPORTS`, `ALERT_MIN_EV` (10), `ALERT_MIN_EV_PTS3` (5), `ALERT_REALERT_STEP` (0), `ALERT_UPDATE_STEP` (2), `ALERT_MAX_PER_GAME` (2), `ALERT_MIN_TTL_S` (10), `ALERT_UNIT` (500), `ALERT_ROUGH`, `PUBLIC_URL`. `node novigAlerts.js --dry` prints what the saved boards would alert on.
- **Checked**: `node scripts/novig_alerts_check.js` (the two EV bars, expiry, the repeat rules, a 429, a failed post, dry run, the webhook in no log). Run here against a stand-in webhook with the bar dropped to -3%: the job started an NFL pass by itself, IND @ HOU sent two alerts and then (with the step then at 2) one better slip for each of those two players, the first post was answered 429 and re-sent, and the message for Daniel Jones U32.5 pass attempts + U19.5 completions carried the board row's numbers (quote 0.422, 2.24x, fair +121, EV +1.4%, 0.28u, $138). The button was pressed in a browser. On the NBA board nothing was asked: no tight books at 11pm ET.
- **Not checked**: a real Discord channel, and the deployed app.

## 2026-11-18 session

### Auto-scan leaves NBA Ladder out again
Max, 11-18: turn off NBA ladders on auto.

- **Change** (`NV_CYCLE_BOARDS` in `server.js`): NBA Ladder is out of the Auto-scan cycle, which is now NBA, NBA Team, NFL, NFL Ladder, CBB, CFB, soccer. NFL Ladder stays in. The NBA Ladder tab and its Fetch button are unchanged; its rows stay on the board and the All tab until they start.
- **Checked**: syntax only.

### Kalshi Pts + 3s and Kalshi NBA: every leg at 30% or better, in place of the +300 limit
Max, 11-18: do the leg floor instead.

- **Why**: the +300 limit on a slip's fair value was a stand-in for the real worry, a leg stranded on a far milestone. It also cut slips of two legs beside the player's own lines (Zubac 15+ points with 10+ rebounds, fair +392, legs about 36% and 42%) and needed teammates exempt.
- **Change** (`--leg-min` in `scan_kalshi.py`, default 0.30, read in `candidates`; `nvLong` in `server.js`): a slip is asked and shown only where every leg's fair value is 30% or better, teammates slips included. `--max-fair` stays as an option, off by default. A row already on the board with a leg under 30% is hidden, as is one a refresh moves under it.
- **Tonight**, no quote asked of Kalshi: Pts + 3s 243 slips (30 of them longer than +300, the longest +455); Kalshi NBA 337 (71 teammates; 103 longer than +300), so its 300 cap cuts 37 slips on other milestones.
- **Not changed**: Kalshi NBA Lines, NFL and CBB.
- **Not checked** on a live pass or in a browser.

### Kalshi +300 limit: teammates slips exempt, and long rows already on the board are hidden
Max, 11-18 (screenshot: Zubac 15+ points · 10+ rebounds, fair +392, still on Kalshi NBA): teammate ones are fine, but not ones like this.

- **Teammates** (`candidates` in `scan_kalshi.py`): the +300 limit no longer applies to a teammates slip.
- **Rows already there** (`nvLong` in `server.js`): the limit only stopped new asks, so a row from a pass before it stayed. The server now leaves a one-player row with a fair value over +300 off Kalshi Pts + 3s, Kalshi NBA and the All tab, including a row a refresh moves past +300.
- **Tonight**, no quote asked of Kalshi: Kalshi NBA lists 290 slips (92 teammates), inside its 300 cap; Pts + 3s is unchanged at 226.
- **Not checked** on a live pass or in a browser.

### Kalshi Pts + 3s and Kalshi NBA: no slip with a fair value longer than +300
Max, 11-18: keep FV under 300 on both; more comfortable with smaller lines since Kalshi does the 20 / 25 / 30 milestones.

- **Change** (`--max-fair` in `scan_kalshi.py`, default 300, read in `candidates`): a slip whose fair value is longer than +300 (under a 25% chance) is not asked, on Kalshi Pts + 3s and Kalshi NBA, teammates slips included. `--max-fair 0` lifts it. Kalshi NBA Lines, NFL and CBB are unchanged.
- **Tonight**, no quote asked of Kalshi: Pts + 3s 390 slips to 226, Kalshi NBA 503 to 226 (33 of them teammates), so both now fit under their caps and a pass is about 12 minutes.
- **Not limited**: ↻ and Bet on a row already on the board. A row whose fair value drifts past +300 on a refresh stays until the next pass.
- **Not checked** on a live pass or in a browser: both boards listed with `--dry`, the page's script parsed for syntax.

### Kalshi NBA is two tabs: Kalshi Pts + 3s, and Kalshi NBA for the rest
Max, 11-18: a Kalshi 3s and points and then another one; the 3s look good, they keep popping up.

- **New tab, Kalshi Pts + 3s** (`kalshinba3` in `server.js` and `public/nba_scan.html`; `--league nba3` in `scan_kalshi.py`): one player's Points + Threes alone, every player with open Kalshi props, up to four slips a player (the milestone each side of his main line on both stats). At most 400 slips a pass. It is the first tab and the one a new device opens on.
- **Kalshi NBA** keeps the other pairs (r 0.25 or better) and the teammates slips, at most 300 a pass, and no longer asks Points + Threes. A device last left on Kalshi NBA still opens there.
- **Same rules on both**: pricing, the ↻ and Bet buttons, the second passcode, Fetch only. Both share the one Kalshi slot, so one runs at a time. Both show on the All tab.
- **Tonight**, no quote asked of Kalshi: Pts + 3s has 390 slips (108 first slips, 113 players), all inside the 400; Kalshi NBA has 503 (136 first slips), of which a pass asks 300. Before the split one 300-slip pass asked 33 of the extra Points + Threes slips.
- **Cost**: a 390-slip pass is about 20 minutes. Fetching both tabs every night is up to 4,900 new combos a week against Kalshi's 5,000; the script still does not count them.
- **Not checked** on a live pass or in a browser: both boards were listed with `--dry`, and `server.js` and the page's script were parsed for syntax.

### Teammates' points slips are priced at r -0.05, not 0
Max, 11-18: less confident in the teammate plays than in a player's own Points + Threes; which fix?

- **Why**: the league-wide measurement stands (+0.02 on 6,578 team-games), but a slip is one pair, and one pair's history is too short to place it. Maxey + Embiid, 47 games together at 20+ minutes over two seasons: points r -0.14 (two-sigma ± 0.29), both at 25+ in 16 of 47 (34%) against 39% as unrelated legs. Their slip at 4.73x is +16% at r 0, +8.5% at -0.10, break-even at -0.21.
- **Change** (`NBA_MATE_R` in `scan.py`, read by the Novig NBA, Kalshi NBA and DK boards): 0.0 to -0.05 (first set to -0.10; Max chose -0.05 the same evening). A margin, not a measurement. A teammates slip's fair price is about 3.5% longer, so its EV is about 4 points lower and its stake smaller; fewer show as plays.
- **Not done**: a pair's own r from its games together, shrunk toward the league's. Rows on the boards keep their old fair values until their next pass.
- **Checked**: syntax only.

### Kalshi boards ask more: 300 slips a pass on NBA (200 on the others), and both milestones beside the main line
Max, 11-18: up the Kalshi scans, missing a lot.

- **Cap** (`--max` in `scan_kalshi.py`): a pass asked at most 60 slips. Now 300 on Kalshi NBA and 200 on Kalshi NBA Lines, NFL and CBB.
- **Second milestone** (Kalshi NBA; `pick_leg(skip=)`, `candidates`): each stat now has two legs where both can be priced, the milestones just under and just over the main line, each off its own tight book or shifted from Novig's main line. A pair is asked on up to four slips (Jokic: 25+ and 20+ points with 2+ and 3+ threes), teammates too. A player's stat with no tight book on any milestone now gets a shifted leg as well (it had none).
- **Order**: every pair's first slip (teammates, Points + Threes, the rest), then the other milestones' slips in the same order, so the cap cuts the extra teammates' slips last and the other pairs' extras first.
- **Tonight**, no quote asked of Kalshi, read about two hours before the first tip: 743 slips could be asked (209 first slips, 534 on other milestones; 125 with a shifted leg). A pass asks the 209, the 58 extra teammate slips and 33 of the extra Points + Threes.
- **Cost**: a pass at 300 is about 15 minutes where 60 took three or four. Kalshi allows an account 5,000 new combos a week and charges more rate-limit tokens to accounts that ask often and rarely accept: the NBA board every night at 300 is 2,100 of the 5,000 by itself. The script does not count the week's combos.
- **Not checked** on a live pass.

### Kalshi NBA: a milestone with no tight book is priced from Novig's main line
Max, 11-18: can we use Novig for help on the main line?

- **Change** (`shift_leg` in `scan_kalshi.py`, called from `pick_leg` on the Kalshi NBA board): where neither milestone beside a player's main line has a tight book but Novig's main line does (4 cents or tighter), the nearer milestone gets a fair value shifted from that main line with the Ladder's model (`price.leg_prob`: normal and count model), held under the lowest ask and over the highest bid that Kalshi and Novig show on the milestone itself. The leg carries the line it came from ("from Novig 22.5" in the opened row) and the slip is marked * (modelled). A milestone with its own tight book is still read off that book.
- **Tonight**, no quote asked of Kalshi: 56 slips become 72, 11 of them with a shifted leg; teammate slips 1 to 4. Murray 25+ comes out at 36.5% from Novig's 22.5 (45%), inside Kalshi's 33 / 42. Jokic 25+ with Murray 25+ is fair 5.54x; Kalshi's app showed 5.28x for it at 4:15, so under fair.
- **↻ and Bet on such a row** (`reprice`, fixed the same evening): they refused it ("no tight book on Kalshi right now"), because a row is re-priced off Kalshi's own book and a shifted leg has none. A shifted leg now keeps its fair value, held inside Kalshi's bid and ask as they are at that moment; Novig's main line is not read again until the next Fetch.
- **Not shifted**: the Kalshi NBA Lines and NFL boards (a leg there still needs a tight book on one of the two milestones beside the main line). FanDuel's one-way price, a ceiling on the Ladder boards, is not read here: the shift is one milestone at most and both exchanges' asks cap it.
- **Not checked** on a live pass or in a browser.

### Kalshi boards: a leg sits beside the player's main line, or there is no leg
Max, 11-18: Jokic 25+ with Murray 30+; why jump to 30?

- **Cause** (`pick_leg` in `scan_kalshi.py`): a leg went on the nearest milestone that had a tight book. Murray's main line is 22.5; Kalshi's 20+ was 60 / 67 and its 25+ 33 / 42 (7 and 9 cents wide, over the 5 allowed), Novig's books on those lines were 10 and 13 cents wide, and only 30+ (19 / 21) was tight. 16 of tonight's 48 points legs were more than 3 points from the main line.
- **Change**: the main line is read off every Novig line with a price (tight or not), and a leg may only sit on the Kalshi milestone just under or just over it. Neither has a book: no leg, and no slip that needs it. Where Novig lists nothing for the stat, the milestone nearest even money, as before. Applies to every stat on the Kalshi NBA, NBA Lines and NFL boards.
- **Cost**: fewer slips. Tonight, with no quote asked of Kalshi: 82 slips to 56, teammate slips 7 to 1 (Acuff 25+ with LaVine 20+).
- **The Murray 30+ leg itself** was priced off a real 2-cent book, so its own fair value stands. What is unmeasured is the teammates' r of 0.0 that far from a main line: it was measured at each scorer's median line.

### Kalshi NBA: the teammates slip is the team's real top two, or not asked
Max, 11-18: why is Kalshi showing Klay + Giannis to score together? He's not the #2.

- **Cause** (`candidates` in `scan_kalshi.py`): teammates were ranked among the players who had a priced points leg. Adebayo (Novig main line 17.5) had none: Kalshi's milestones for him are 10+, 15+, 20+ and 25+, Novig's books on those lines were 13 to 18 cents wide and Kalshi's own were over 5, so he was dropped and Thompson (15+) moved up beside Antetokounmpo. The "unrelated legs" measurement is for a team's top two scorers only.
- **Change**: each team is ranked by every listed player's main points line (Novig's, tight book or not; else Kalshi's milestone nearest even money), and the slip is asked only when both of the top two have a priced leg. The next man no longer steps in. The second scorer's main line must still be 14.5 or more.
- **Checked** on tonight's board without asking Kalshi for a quote: 82 slips, 7 teammate slips, none for Miami. Rows already on the board stay until its next pass.
- **Not changed**: the Novig NBA board ranks teammates by tight main lines, so the same thing can happen there when a second scorer has no tight points book at all (rarer: Novig's main line is usually tight). A leg can also sit well off the player's main line where only that milestone has a tight book (tonight: Murray 30+, Coward 10+).

### Novig Scan: Ladders in Auto-scan, DK NBA tab removed, no My bets strip, a saved bet folds its row
Max, 11-18: add ladder for NFL and NBA to auto; remove the DK NBA tab; hide the bets shown above the board; when a bet is entered and the phone's check is hit, collapse the row.

- **Auto-scan** (`NV_CYCLE_BOARDS` in `server.js`): NBA Ladder and NFL Ladder are in the cycle, each after its own main board (NBA, NBA Ladder, NBA Team, NFL, NFL Ladder, CBB, CFB, soccer). Same rules as the others: the board's next day of games only, no board more often than every ten minutes. A full turn of the cycle is longer by the two Ladder passes.
- **DK NBA** (`public/nba_scan.html`; `NV_ALL_BOARDS` in `server.js`): the tab is gone and its rows no longer show on the All tab. A page that was last left on DK NBA opens on NBA. The board's code on the server and `scan_dk.py` are left in place.
- **My bets strip** (`betStrip`): the list of bets above the board is gone. A bet still shows on its own row (the green line and edge), and the opened row still has the stake box and each bet's × to remove it. Hide my bets works as before. A bet whose row is no longer on the board can't be removed by hand any more; it leaves by itself as before. The Kalshi positions strip is unchanged.
- **Saving a bet folds the row**: on Save, Enter, or leaving the stake box (the iPhone keyboard's check mark), the opened row closes.
- **Not checked** in a browser or on a live pass: `server.js` and the page's script were parsed for syntax only.

### Kalshi Scan: the Bet button stakes the row's QK $
Max, 11-18: change $25 to QK for Kalshi.

- **Change** (`kbetStake` in `public/nba_scan.html`; `NV_KBET_MAX` in `server.js`): one press of the Bet button stakes the row's QK $ (quarter Kelly at $100 a unit, the number in the QK $ column, rounded to the dollar) where it staked a flat $25. The button's label shows the amount. A typed stake still replaces it.
- **Cap**: the server's limit on one bet goes from $25 back to $250, and a row whose QK $ is over $250 is bet at $250. `KALSHI_BET_MAX` on the server overrides the server's limit; if it is set on Railway, presses over it are refused until it is changed.
- **Not checked**: no bet was placed. The page's scripts and `server.js` were parsed for syntax only.

## 2026-11-17 session

### CBB correlations follow a curve by size of spread; more bands tested worse
Max, 11-17: another slip where DraftKings pays more than the fair (Xavier Under 95.5 + Cleveland State Under 62.5: fair +190, DK +216); is this wrong anywhere else, and would more bands make it better?

- **More bands, tested** (each season held out in turn, the other two fitted; scored on how well the fitted r predicts which legs hit): nine spread bands each on its own r predicted the held-out season **worse** than one number for six of seven shapes (a 30+ band is about 370 games and its r swings by season). A smooth curve through the nine bands predicted better than one number and better than four bands for both team totals Under, the underdog's team total with the game total, and the spread with the total. Splitting 20+ into 20 to 30 and 30+ was also tried on the board's own rule and sent a 33-point game back to +0.36.
- **Change** (`curve` in `scripts/cbb_line_correlations.py`; `cbb_r` in `scan.py`, read by the Novig and Kalshi CBB boards; `public/data/cbb_line_correlations.json` rebuilt, about two and a half minutes): each shape gets a quadratic by spread through nine bands, flat past the top band's average spread, with a jackknife range. The board reads the curve where its change from a 5- to a 30-point spread is over three standard errors, and one r at every spread otherwise. The four-band rule is gone.
- **What the board uses now**: both team totals Under +0.37 to a 10-point spread, +0.35 at 15, +0.33 at 20, +0.29 at 25, +0.25 at 30, +0.20 at 35 (was +0.36, and +0.25 at 20 and up). Spread + total -0.04 to 10 points, +0.01 at 20, +0.12 at 30 (was -0.03, +0.14 at 20 and up). One r at every spread: underdog covers + his team total Under -0.60, the favourite's team total Under + Under +0.83, first-half spread + spread +0.63 (its +0.69 at 20 and up is gone: the curve's rise is two standard errors, not three).
- **The two slips**: Xavier + Cleveland State (33 points) r +0.22, fair +213 against DraftKings' +216, Novig's 3.50x +11.8% (the board showed +20.8%). Ole Miss + Nicholls (29 points) r +0.26, fair +231 against DK's +232, Novig's 3.54x +6.9%.
- **Anywhere else**: the NBA game-line slips use the same four-band rule, so the same test was run on their 4,133 games: no curve, line or set of bands beat one number on held-out seasons (NBA spreads stop near 15 points, where college's fall has barely started). Left as it is. Not tested: college football's game-line slips (a model fitted to each game's own ladders, with no history in the repo to test against), soccer corners (already by strength of favourite), NHL lines and the NFL's line slips (three spread groups).
- **Checked**: each shape's r read back through `cbb_r` at spreads of 0 to 45, an unmeasured shape, and both slips' fair values. No live pass was run; rows on the board keep their old fair values until their next pass.

### CBB correlations: measured more steadily, and both team totals Under drops to +0.25 in lopsided games
Max, 11-17: DraftKings pays +232 on Ole Miss Under 85.5 + Nicholls Under 56.5 where the board's fair is +212, and Gordon Bombay saw fair below DK on a few CBB slips; research it and update the correlation if needed.

- **Found** (same 17,319 games): how much the two teams' scores move together falls as the spread grows. The scores' point misses against their lines correlate +0.39 under 12 points, +0.32 at 12 to 20, +0.26 at 20 to 30 and +0.14 at 30 and up (the margin's spread of results widens from 11 to 15 points there; the total's does not). The board's hit / miss number at 20+ read +0.29 with a range of +0.13 to +0.44, too wide to tell from the all-games +0.37, so +0.37 was used on every game.
- **Change** (`measure` in `scripts/cbb_line_correlations.py`; `public/data/cbb_line_correlations.json` rebuilt): each correlation is now the hit / miss copula r averaged over each leg's line and the lines 2 and 4 points either side (25 pairs of lines), with a two-sigma range from a 20-block jackknife. Ranges are about half as wide. The line-alone number is kept as `r_line`. The scanner's rule is unchanged: a spread band's own r where the all-games r is outside that band's range.
- **What the board uses now**: both team totals Under +0.36 (was +0.37), +0.39 at 6 to 12 points, **+0.25 at 20 and up** (range +0.20 to +0.31). First-half spread + spread +0.69 at 20 and up (was +0.63). Underdog covers + his team total Under -0.60 at every spread (was -0.61; its 20+ band, -0.55, is still inside its range). Team total Under + Under +0.83 and spread + total (-0.03; +0.14 at 20 and up) as before. The Kalshi CBB board reads the same file.
- **The Ole Miss slip**: fair +212 becomes +232, the same as DraftKings' price; Novig's 3.54x goes from +13.5% to +6.8%.
- **Checked**: the before and after r for each of the six shapes at spreads of 3, 9, 15 and 25 through the scanner's own rule, and that slip's fair value. No live pass was run: rows already on the board keep their old fair values until their next pass.
- **Still soft**: team-total lines in the history are worked out from the closing spread and total, not posted ones. By season the 20+ point-miss number was +0.17, +0.12 and +0.33, so +0.25 is an average of seasons that differ.

### First Dunk: a review of the model, and five things fixed
Max, 11-17: review the model again, check for bugs.

- **Fixed: the page priced the whole bench as if every man would play.** The backtest knew who got into each game (21.5 players a game); the page cannot, and priced everyone who had played lately (26.8). Priced that way, "Other" came out at 15.7% against the 12.6% that happened, so the Other EVs shown against DK's first prices were too high. A man off the bench is now weighted by the share of his team's last ten games he got into (`app`; shown on his row as "gets in 70%"), and the bench multiplier was refitted to 0.75 under those conditions. Priced the way the page prices it, Other is now 12.6% against 12.6% (`--backtest` prints both versions; 2,664 games). Against tonight's DK prices that moved Other from +112% to +90% in POR at MIN, +46% to +27% in CHA at LAL, +33% to +18% in UTAH at LAC.
- **Fixed: eight All-Star games were in the data.** ESPN files them as regular season (East/West, the 2025 and 2026 mini-tournaments). One had 44 dunks, all credited to the players the model most cares about. Only the 30 clubs are kept now (3,898 games).
- **Fixed: a man coming back from injury was held out.** A player with no game in his team's last three stayed at 0% even when Rotowire listed him probable or questionable. Rotowire's chance now stands.
- **Fixed: a hole in ESPN's play-by-play went unnoticed.** One game in a sample of 60 was missing five made baskets. Each game's made baskets are now counted against the box score and a game short by more than two is left out of the backtest and the on-floor patterns (1 game; 6 more are short by one or two).
- **Fixed in `price_game`**: a starter just traded in (his last game was for another team) was dropped from his new team; the date cut-off is ESPN's UTC day, now said in its notes.
- **Checked and found sound**: dunk detection against the raw play-by-play of 60 random games (607 dunk plays; every missed or blocked dunk left out, none hidden under another play type; the shooter matched the box score for 1,322 of 1,327 player-games, the other five being the game with the hole). Each team's possessions within 1.1 of the other's on average; players' on-floor possessions add to five times the team's. The fitted season weights still win in the first 20 games of a season (785 games), where we are now. Bench players and players running hot both land on their priced rates.
- **Known and left**: favourites priced 40% and up made it 39.8% (241 of them, priced 45.2%), and starting guards made it 8% less often than priced. The page's pricing now runs through `FD.context` / `FD.entry` and is checked end to end against Python on a real game from the model file (within 0.002 points; 20 checks).
- **Backtest after the fixes**, knowing who played: log loss 2.177 (the first dunker priced at 11.3%, against 9.3% and 6.2% for the two baselines), top pick 29.1%, top three 60.7%. Monte Carlo within 0.18 points on the same rotation.
- **Checked**: the page in a browser against the local server with live Rotowire lineups and live DK prices, all five games.

### First Dunk: DraftKings' market is found (Quick Hits, "1st Dunk Scorer")
Max, 11-17: first dunk is now on DK (a screenshot of NY at TOR: ten starters and Other).

- **Why it was not found**: DK files the market in a subcategory of its own under Quick Hits. It is in neither the SGP feed nor a game's own market list, which is where `nba_named_markets` looked.
- **Fix** (`dk_api.py`): the reader now takes the league's subcategories whose name matches ("1st Dunk Scorer") and reads each one: two requests for the whole slate where it was one a game.
- **Read live**: all five of tonight's games, eleven selections each (ten starters and Other), prices adding to 116 to 117%. NY at TOR matched the screenshot price for price.
- **A new note on the page**: DK names its own ten starters. Where they differ from the lineup the page used, the page says who, because Other's price hangs on it. Tonight: POR at MIN (DK names Terrence Shannon Jr.; Rotowire has Jonathan Kuminga starting, questionable) and CHA at LAL (DK names Grayson Allen; Rotowire has Sion James).
- **Checked**: the page in a browser against the local server with live Rotowire lineups and live DK prices, all five games.
- **Not checked**: how DK settles a named player who does not start.
### Novig Scan: a long bet chip no longer pushes the page sideways
Max, 11-17: the page is getting off-centre (screenshot: the board scrolled left, a My bets chip running past the right edge).

- **Cause**: a My bets chip is one unbroken line, and one with two long team-total legs ("SMU team total Under 92.5 · Oral Roberts team total Under 65.5 · 3.35x") is wider than a phone, so the whole page could be dragged sideways.
- **Change** (`.chip` in `public/nba_scan.html`): a chip is at most the width of the screen; the slip's text is cut short with "…" and the name, stake and × stay. The full text is still in the chip's title.
- **Checked** in a 390px browser with stand-in chips of that length: the page is exactly as wide as the screen. Not looked at on the live board.

### Novig Scan: the All tab folds a slip's other lines under it
Max, 11-17: do the "+3 more" when the lines are like that (XAV Under 96.5 + CLEV Under 62.5, then Under 97.5 + Under 62.5 as its own row); it clogs the feed.

- **Change** (`shape`, `cardOf` in `render`, `public/nba_scan.html`): on the All tab, rows of one board that are the same slip at different lines (same game or player, same legs and sides) are one card. Its head is the best of them by EV; the rest sit under a "+N more" chip. A different slip on the same game (CLEV +34.5 + CLEV Under 62.5) keeps its own row. The other tabs are as they were.
- **Checked** in a phone-sized browser on stand-in rows of the screenshot's two games: three cards from six rows, the chip opening and closing its own card only. Not looked at on the live board.

### First Dunk: rebuilt on possessions, with lineups and statuses set automatically and DraftKings' "Other" line
Max, 11-17: a spec for the model (possession rates, pace, opponent, tip, rotation, closed form and Monte Carlo, `price_game`, walk-forward validation), then: pull prices from DK, pull starting lineups from somewhere, DK lists the ten starters and then Other, and the tool should set starting / bench / out itself and adjust for a doubtful starter. This replaces the per-minute model of the entry below.

- **Data** (`public/data/nba_dunk_games.json`, 3,906 games: 2023-24, 2024-25, 2025-26 and this season through 11-16): ESPN's play-by-play, with every made dunk (time, player, team), the substitutions followed through all four quarters and overtime, each team's possessions, each player's possessions on the floor, live-ball turnovers, and who won the opening tip. The on-floor minutes rebuilt this way are within 0.26 of the box score's a player a game.
- **Player rate**: made dunks per 100 possessions on the floor, this season at full weight and last season at 0.3, with 100 possessions of his position's average mixed in. The suggested weights (1.0 / 0.6 / 0.3) scored a little worse; two seasons back added nothing.
- **Game adjustments**: the matchup's pace (both teams' possessions a game against the league's), the other team's dunks allowed per possession, and the home team's rates up 6% (the visitors' down 6%; home teams made 52.9% of first dunks). A man off the bench is priced at 0.8 of his rate, which is what makes "Other" come out right.
- **Built, tested and left off** because each made the backtest slightly worse: the other team's live-ball turnover rate, the team's dunks over what its players' rates expect (team dunk strength beyond its players), the team's dunks in its opening six minutes over expected (speed of its first dunk), and a bump for the team likelier to win the tip. The team that won the tip made the first dunk 52.1% of the time (3,885 games); which team will win it is not predictable enough beforehand to use. All four are settings in `PARAMS`.
- **Rotation**: one-minute stints. Each man's share of each of the first 24 minutes on the floor comes from his own games as a starter and off the bench, with 8 games of the league's pattern for his role and minutes mixed in.
- **The price**: per minute with total rate L, P(first dunk in it) = P(none before) × (1 − e^−L), and a player's share is his rate over L, leaned toward the bigger dunkers (power 1.1). What is left over is the no-dunk chance (about 0.03% a game; none of the 3,906 games went without one). The page also shows the expected minute of the first dunk and of each team's own first.
- **Monte Carlo** (`--mc`, 200,000 runs a game): within 0.15 points of the closed form for every player on the same rotation, and within 1.5 points when each man's rotation is drawn from his own past games instead of averaged.
- **Backtest** (`--backtest`, 2,672 games over three seasons, each priced only from the games before it, that night's starters known): the first dunker was priced at 11.4% (geometric average; log loss 2.175), against 9.3% pricing the starters by dunks a game and 6.2% pricing the ten evenly. He was the top pick 29.1% of the time and in the top three 60.7%. Priced 20 to 30%: made it 25.1% (priced 24.4%). 30% and up: 35.4% (priced 36.5%). 2 to 5%: 3.1% (priced 3.3%). "Other" (anyone but the ten starters): priced 12.4%, happened 12.5%. Minutes to the first dunk: priced 5.2, happened 5.1.
- **The settings were fitted on those same games** (`--tune`, each setting over its grid in turn, twice round), so the numbers flatter the model a little. At the starting settings the log loss was 2.187.
- **Lineups and statuses** (`nbaLineups.js`, `/api/nba/lineups`): Rotowire's lineups page for today and tomorrow: each team's five, confirmed or expected, and its "may not play" list with each man's tag and Rotowire's own chance that he plays. Until Rotowire posts a game the page uses the team's last five and ESPN's injury list (out, or game-time decision at 50%). A man who has not played in his team's last three games is out unless he is listed to start.
- **An unsure starter** (`mix`): every way the unsure players can turn out is priced with its chance and the results added up (up to 8 unsure players, 256 lineups). When a starter sits, the team's next man up starts (most recent starts, then minutes).
- **DraftKings' "Other"**: the page adds a row for everyone DK does not name (before DK lists the game: everyone but the ten starters), reads DK's price for a selection called Other or Field, and shows its EV.
- **Refresh**: lineups, injuries and DK prices are asked for again every three minutes while the page is on screen and a game has yet to start.
- **Hot and cold**: a player whose last ten games are more than 25% off his full rate is listed at the foot of the page (128 of them tonight), and marked on his row, with the price he would get on those ten, when that moves his chance by more than 25%.
- **`price_game(home_starters, away_starters, date)`** in `scripts/nba_first_dunk.py` returns the table (player, probability, fair odds, sorted), Other, and the no-dunk chance; `status=` takes out / doubt / ques / prob and `odds=` adds EV. `--price NY TOR` prints it from the last fives on file.
- **Checked**: the page's pricing and its unsure-starter mixing against Python on a real game, and the Rotowire reader on a made-up page (`node scripts/nba_first_dunk_check.js`, 19 checks). The Rotowire reader on its live page for 11-16 (8 games, all confirmed). The page in a desktop and a phone-sized browser against the local server: tonight's five games on the fallback lineups, then with a made-up Rotowire lineup (a questionable starter, a doubtful bench man) and a made-up DK market of ten starters and Other.
- **Not checked**: Rotowire had not posted 11-17's games when this was built, so tonight's games have only been priced from the fallback. No dunk market was on DraftKings (New Jersey) either; with ten starters and Other it is probably posted once the fives are known, close to the tip. Whether Rotowire answers Railway's servers the way it answered this machine.

### First Dunk: a model for who makes each NBA game's first dunk (new FIRST DUNK tab)
Max, 11-17: could we make a first dunk model? Might be fun. DK has lines.

- **The model** (`scripts/nba_first_dunk.py`): a race. While he is on the floor a player dunks at his own rate: his dunks per minute this season and last (last season counts three quarters), with 100 minutes of his position's average mixed in. That rate is scaled by the dunks the other team allows and by the league's rate in that minute of the game. The first dunk is his in a given minute with the chance of no dunk before it, times the chance of one in it, times his share of that minute's rates (leaned a little toward the biggest dunkers, power 1.15). When he is on the floor comes from his own games as a starter or off the bench, minute by minute for the first half.
- **The data** (`public/data/nba_dunk_games.json`, 2,674 games, 2024-25 through 11-16): ESPN's play-by-play for every final: each made dunk with its time, the starters, and who was on the floor in each of the first 24 minutes (followed through the substitutions). The league makes about 9.5 dunks a game; half of first dunks come within 3.3 minutes and 90% in the first quarter, so who starts matters most.
- **Backtest** (`--backtest`): 1,439 games since the start of last season, each priced only from the games before it, with that night's starters known. The man who made the first dunk was priced at 11.1% (geometric average; log loss 2.197), against 9.1% pricing the starters by their dunks a game and 6.1% pricing the ten starters evenly. The top pick made it 30.2% of the time. Players priced 20 to 30% made it 24.3% (priced 24.4%); 30% and up made it 38.8% (priced 36.6%); 2 to 5% made it 2.9% (priced 3.3%). The bench is priced a little high as a group (14.2% against 12.9%).
- **The settings were fitted on those same games** (`--tune`): the prior's 100 minutes, last season's weight and the 1.15 were picked by this backtest, so its numbers flatter the model a little. Before the fit the log loss was 2.215.
- **The page** (`public/nba_dunk.html`, `?sport=nbadunk`): each game of the day with every player's fair chance and fair odds, and each team's share. Start / Bench / Out is set from the team's last game and ESPN's injury list and can be changed on the row; the odds reprice at once and the change is kept for the day. Late at night it opens on the next day's games.
- **DraftKings**: `nba_named_markets` in `dk_api.py` (`/api/dk/nba-first-dunk`) reads every NBA market with "dunk" in its name, one request a game, and the page puts each price beside the fair odds with the EV. A price can also be typed in (+650, or 7.5).
- **Daily refresh**: a step in the data workflow pulls new finals and rebuilds the rates.
- **Checked**: the page's pricing against the Python model on a real game (`node scripts/nba_first_dunk_check.js`, equal to 1e-16); the page in a desktop and a phone-sized browser against the local server, for tonight's five games: role changes, typed prices, a reload, the tab inside the main page. The DK reader on DK's live "1st Points Scorer" market, and the page's matching on a made-up dunk market.
- **Not checked**: no dunk market was on DraftKings (New Jersey) for tonight's games when this was built, so a real one has not been read; if its name has no "dunk" in it, it won't be found. How DK settles it (a listed player who sits, a game with no dunk) was not looked up.
- **Not in the model**: the spread and total, matchups, and a new starter's actual minutes.

### Novig Scan: Auto-scan moves on to each board's next day of games
Max, 11-17: no games are left; NFL pick up Thursday, NBA do tomorrow, soccer until its next games.

- **Change** (`nvCycleTick` in `server.js`): Auto-scan priced games starting before tonight's midnight, so a board whose games had all started had nothing to price until the next day. Each board now takes the games starting before the midnight that follows its soonest open game: today's while there are any, then the next day that has some (the NBA's tomorrow, the NFL's Thursday, soccer's next match day). Days after that are still Fetch only.
- **A board with no open game at all** rests ten minutes and is asked again, like one just priced. If Novig's game list can't be read, the pass is today's games, as before.
- **The page** says "each board's next day of games" where it said "today's games", and names the day the last pass ran through.
- **Checked**: both files load; Novig's live game lists read for NBA, NFL and soccer (soonest: tonight, Thursday, Friday). **Not checked**: no auto-scan pass was run here (no passcode or cycle on this machine), and the page was not opened.

### Novig Scan: the Bet button on Novig rows is gone
Max, 11-17: remove the Novig button.

- **Change**: the button, its "Placed it?" question and the stake on the `/n` link are all taken out; the page and `/n` are as they were before the entry below. A row's Novig price is still the link into Novig, and a bet is still noted in the opened row.
- **Checked**: nothing of the button is left in the page or the server, and the server file loads. Not opened in a browser.

### Novig Scan: a Bet button on Novig rows (opens Novig with the slip and stake filled in)
Max, 11-17: can we make something where Novig will bet itself? (Asked which he meant: a Bet button on Novig rows.)

- **Why it is not the Kalshi button**: Novig's API (docs.novig.com, read 11-17) signs straight orders and lets a maker price parlays, but has no call that buys a parlay from an account. The server can't place one. The only other way is the app's own private calls with a login, which is not built here.
- **The button** (`nbetLine` in `nba_scan.html`): a Novig row above fair shows **Bet $107 at 8.30x** on the row. One press opens Novig with the legs and the row's QK $ already on the slip; the bet is confirmed in Novig. Novig's link takes a stake after a partner id (`events/<outcome ids>/<partner>/<amount>`, docs.novig.com/affiliates/deeplinking); the partner id sent is `evc`. On a phone it opens the app (`novigapp://`), on a computer `/n/<ids>?amt=107` on this server, which goes to novig.com.
- **After the press** the row asks "Placed it?": **Save $107 at 8.30x** puts it under My bets in one press, **No** clears it. A different stake is still typed in the opened row.
- **Checked** in a desktop and a phone-sized browser against the local server, on a real CBB row marked above fair for the test: the link each one opens, the question on the row, the saved bet. `/n` with and without `amt`.
- **Not checked**: that Novig fills the stake in. novig.com answered this machine with a bot check, and the docs show the amount for the web link only, not for `novigapp://`. If the app opens the slip without the stake, or not at all, the partner id or the amount is what to take off.

## 2026-11-16 session

### Kalshi Scan: a Kalshi NBA Lines board (a player's prop with a game line)
Max, 11-16: any other NBA combos we can do on Kalshi? Yes, test it out.

- **The board** (`nbaline_candidates` in `scan_kalshi.py`, `--league nbaline`; the `kalshinbaline` board; a **Kalshi NBA Lines** tab on the Kalshi page): a player's milestone (points, rebounds, assists, threes, or points + rebounds + assists) with the side of a game line that goes with it, and his Under (No on the same milestone) with the other side. The lines: his team covering, his team's total, the other team's total, the game total, the first half's spread and total. The other team covering and an Under are No legs on Kalshi's "wins by over" and "Over" markets.
- **The r** is the Novig NBA Team board's (`nba_line_correlations.json`: league-wide for a player with that line on a team with tonight's spread, less one standard error). Asked where the fitted r is 0.30 or better (`--line-r`; the Novig board uses 0.42 and the spread only), each player's two strongest pairings (`--per`), 60 slips a pass, earliest game first.
- **Fair values**: every leg within 13 points of 50%, priced like a prop leg: the tighter of Novig's book on the same line and Kalshi's own.
- **Refresh and Bet on a No leg**: `reprice` read every leg as its Yes side; a No leg now takes the other side of the same book. (College rows were never re-read, so nothing was wrong before.)
- **Checked** on the one game not yet started (PHX at DEN): 16 slips built from live lines; with Kalshi's signed calls faked, each went out with the right Yes / No sides, and Novig's own price for the same 16 slips came in between 7% under and 5% over this board's fair values.
- **Not checked**: no real Kalshi price has been seen on this board (no key on this machine), and the tab was not opened in a browser.

### Kalshi Scan: bets are $25 for tonight
Max, 11-16: limit it to $25 for tonight.

- **Change**: one press of the Bet button stakes $25 (it was $100), and the server refuses any bet over $25 (it was $250), so a typed stake can't go higher either. `KBET_STAKE` in the page, `NV_KBET_MAX` in `server.js`.
- **QK $ on the Kalshi page is at $100 a unit** (`UNIT` in the page; it was the Novig page's $500). The earlier "1u = $100" change was made in the script, but the page works the column out itself, so it had not shown.
- **To undo after tonight**: put both back (or set `KALSHI_BET_MAX` in Railway for the cap alone). Nothing does it by itself.
- **Checked**: both files load.

### Kalshi Scan: the Bet button's first real bet landed on the right side
Max, 11-16: "Placed" (Lendeborg 25+ points with Podziemski 20+ points, the $2 test).

- **What Kalshi shows**: $1.88 in, pays $13.86, on the Yes side. With the fee that is $2 for $13.86, 6.93x, against the 6.69x the row showed. So the side the button accepts is right, the Trade-only key may accept a quote, and the price came in a little better than quoted.
- **The $2 test is gone** (`NV_KBET.ok` starts true in `server.js`): a redeploy forgot that the test had passed and would have asked for it again. The position is still read back after every bet, and a bet on the No side still turns the button off.
- **Not checked**: a full $100 press on the real exchange.

### Kalshi Scan: the Bet button is on the row
Max, 11-16: "I don't see it" (the button was inside the opened row; his rows were closed).

- **Change**: a Kalshi row above fair shows **Bet $100 at 6.69x** on the row itself, open or not, so a play is one press. What happened shows beside it. A stake typed in the opened row still overrides the $100.
- **Checked** in a phone-sized browser against the stand-in: the button on a closed row, one press, the bought message.

### Kalshi Scan: the Bet button stakes a flat $100
Max, 11-16: just do $100 for the Kalshi bets.

- **Change**: one press of the button stakes $100, not the row's quarter-Kelly amount; the button reads "Bet $100 on Kalshi at 2.91x". A number typed in the stake box still overrides it. The row's QK $ stays on the row as a guide.
- **The first press**: until one bet from the button has been seen on the Yes side, a press stakes $2 whatever was asked (it was refused outright before, which a flat $100 would have hit every time). The row then says it was the $2 test and that the next press bets the full amount.
- **Checked**: both files load. Not run against the stand-in again.

### Kalshi Scan: one unit is $100
Max, 11-16: 1u = $100; a click and it bets; most prices match the app.

- **Unit**: the Kalshi boards size stakes at $100 a unit (`--unit` in `scan_kalshi.py`; it was $250). A row's QK $ is its quarter-Kelly units times $100, and that is what one press of the Bet button stakes when the stake box is empty. The Novig boards are unchanged.
- **Price allowance back to 1%**: "must match" was a typo for "most match" (Max: the board's prices mostly match the app's on the bets he has placed). The exact-price rule added on that misreading was taken out again the same hour: a bet goes in if Kalshi's new answer is within 1% of the row's price and the slip is still above fair.
- **The price check**: Max reports most rows matching the app. That is his report; no pair of numbers was recorded here.
- **Still in place**: the first bet from the button is $2 at most, until one is seen on the Yes side. Bets placed by hand in Kalshi's app don't test which side the button's call buys.
- **Checked**: both files load. Rows priced before this keep their $250-unit stakes until the next Fetch.

### Kalshi Scan: a Bet button, and what is already held on Kalshi
Max, 11-16: can we have a one click bet button? And could it show what we have already bet?

- **Bet button** (`place` in `scan_kalshi.py`, run as `--bet`; `POST /api/nba/kalshi-bet`; the opened row on the Kalshi page): on a Kalshi row above fair, **Bet on Kalshi at 2.91x** buys the slip in one press, for the stake typed in the row's stake box or the row's quarter-Kelly stake when the box is empty. The legs are re-priced, a new request goes out for that stake, and the best answer is accepted. The row then reads "Bought: $2 at 2.91x (6.10 contracts)" and the bet goes on this device's bets list.
- **What stops a bet**: the price more than 1% worse than the row showed; the slip no longer above today's fair value; a stake over $250 (`KALSHI_BET_MAX`); no Kalshi passcode; another bet in flight.
- **The first bet is $2 at most.** Buying the combo's Yes means accepting a maker's bid for No (side "no" in Kalshi's call). That is my reading of Kalshi's docs and it has never met the real exchange, so after every bet the account's position in the combo is read back: positive is Yes. Until one bet has been seen on the Yes side the cap is $2; a bet seen on the No side turns the button off and says so.
- **On Kalshi** (`--positions`; `GET /api/nba/kalshi-positions`): the Kalshi page shows a strip of the account's open combo positions (dollars in, what each pays), read from Kalshi once a minute and after a bet, and a row whose legs match a held combo says "On Kalshi: $2 in, pays $6.10". Read only. It shows bets placed in the app too, not just from this page.
- **Checked** against a stand-in for Kalshi, through the server and a phone-sized browser: the $2 first-bet cap, the price floor, a bought bet, the $250 cap, the refusal without the passcode, the shut-off after a position on the No side, the button pressed on the page, the strip and the row line.
- **Not checked: no bet has been placed on the real Kalshi.** Unknowns until the first $2 bet: whether "no" is the right side to accept; whether the Trade-only key may accept a quote; whether the position shows within the nine seconds the script waits (if not the row says to look at Kalshi before betting again).

### Kalshi Scan: Novig's price for the same slip beside Kalshi's
Max, 11-16: to double check the Kalshi prices, show the fair value and Novig's price too.

- **Added** (`novig_price` in `scan_kalshi.py`; the row and its opened line on the page): each priced Kalshi row also asks Novig for the same slip, where Novig lists every leg on the same line (25+ points is its Over 24.5; the underdog covering and the Under are its own outcomes). The row shows `NV 2.89x` under Kalshi's price; opened, "Novig pays 2.89x for the same slip" with its EV at the row's fair value. The fair value was on the row already. A refresh asks Novig again.
- **What it tells you**: Kalshi far above both the fair value and Novig is the row to doubt first.
- **Cost**: one more Novig quote for each priced row, on top of what Novig's own boards ask from this server.
- **Checked** with real Novig quotes on six live slips (two each NBA, NFL, CBB): fair 5.70x against Novig 5.63x, 3.00x / 2.89x, 2.58x / 2.59x, 2.45x / 2.43x, 3.74x / 3.32x, 4.12x / 4.07x. The page was not opened to look at it.

### Kalshi Scan: a refresh no longer keeps an old fair value
Max, 11-16: Tristan da Silva 15+ points · 3+ threes at +12.5% (fair +225, Kalshi 3.66x) looks weird; every book has his 15+ points alone at +228 to +270.

- **What was wrong**: fair +225 is 31%, more than his 15+ points leg alone (about 27%: Kalshi 26 / 29, Novig 25 / 29), which can't be. The row's points leg was still carrying about 36%, from before his line fell (Novig's 12.5, once his main line, is now 40%). The refresh added an hour earlier re-read a leg only where Kalshi's book was no wider than the book it was first priced from; Kalshi's 15+ book was wider, so the old fair value stayed under a new price.
- **Fix** (`requote` in `scan_kalshi.py`): a refresh re-reads every NBA and NFL leg off Kalshi's book (5c wide at most). A leg with no such book fails the refresh with a message; nothing keeps an old fair value.
- **The slip now**: legs 27% and 47.5% at r 0.82 give fair about +300 (4.0x); at Kalshi's 3.66x that is about -8%.
- **Not checked**: that the stale leg came from an earlier pass is worked out from the numbers (which leg price gives +225), not seen in the server's saved rows. The fix was not run against a real Kalshi quote.

### Kalshi Scan: a row's refresh button works; requests are sized at $100
Max, 11-16: the refresh button doesn't work (and the Kalshi app showed Henry 80+ rushing yards + touchdown at 2.58x for $150 when the board said 2.77x, three minutes old).

- **Refresh** (`scan_kalshi.py --requote`; `nvRequote` in `server.js`): the button on a Kalshi row re-asks that one slip. An NBA or NFL leg is re-read off Kalshi's own book where that book is no wider than the one it was priced from, and the fair value rebuilt at the same r; college legs keep their fair value. It was refused outright before.
- **Request size**: each ask was for $25; it is now $100 (`--stake`), nearer what is bet. A maker can answer a small request better than a large one, which is one possible reason for the 2.77x against the app's 2.58x at $150; the other is three minutes on a moving leg. Which it was is not known: compare a refreshed row with the app at once.
- **Checked**: the refresh on one live NFL slip with Kalshi's signed calls faked (legs re-read, joint rebuilt, new EV). The button was not pressed in a browser.

### Kalshi Scan: a leg is priced off the tighter book, Novig's or Kalshi's
Max, 11-16: where does Davis 25+ points' fair value come from? (Then: yes, use the tighter book.)

- **What it was**: Novig's book on Over 24.5 whenever it was inside 4c. For Davis that is a thin alt line (41.5 / 45.0, 3.5c wide, 17,000 traded; his main line is 23.5) while Kalshi's own 25+ book was 43 / 44.
- **Now** (`pick_leg` in `scan_kalshi.py`, NBA and NFL): each leg takes the tighter of the two books on its line; where they are within a cent of each other in width, the average of their two fair values. A row is marked ~ when a leg's book is wider than 4c, whichever book it is. CBB is unchanged (Novig only: Kalshi's college books are 8 to 10 cents wide).
- **Checked** on tonight's live lines with `--dry`: Davis 25+ at 0.43 off Kalshi's book. Close to tip Kalshi's star props are a cent wide, so most NBA legs now come off Kalshi's own book or the average.

### Kalshi Scan: its own page and its own slot on the server
Max, 11-16: a separate Kalshi tab, so the two scanners can run at the same time.

- **Its own page**: the Kalshi boards moved off the Novig scan page to a page of their own (`nba_scan.html?kalshi=1`: Kalshi NBA, Kalshi NFL, Kalshi CBB, no Auto-scan). In the main app it is a **KALSHI SCAN** tab (`?sport=kalshiscan`). The Novig page no longer shows any Kalshi tab, and Kalshi rows are no longer on its All tab.
- **Its own slot** (`NV_KRUN` in `server.js`): a Kalshi pass no longer waits for a Novig pass or holds one up. Novig's Auto-scan keeps going while Kalshi is fetched. Still one Kalshi board at a time.
- **Getting in**: with the Novig scanner open, tap the EVC label five more times; the Kalshi page opens and asks for its passcode once. After that the KALSHI SCAN button stays on that device. The earlier ways in (`#kalshi`, typing kalshi in the filter, three clicks on the Novig title) are gone; three clicks on the Kalshi page's title ask again after a wrong passcode.
- **Kalshi links** (Max: possible to add Kalshi links?): a row's price links to its game's page on Kalshi (`kalshi.com/markets/kxnbagame/game/kxnbagame-<game>`, and the NFL and college equivalents), where the combo is built by hand. No link that fills the slip in was found. The address follows Kalshi's usual pattern but was not opened from here: Kalshi's site turns this machine away.
- **Checked** in a browser against the local server with a stand-in for Kalshi: the Novig page's tabs (no Kalshi), the Kalshi page's three tabs after the passcode, a Kalshi CBB pass running while the Novig NBA board showed free, and the app opening the Kalshi page at `?sport=kalshiscan`. The five taps on the label were not clicked through.

### Novig Scan: a Kalshi NFL board, and the Kalshi passcode typed into the name filter
Max, 11-16: price NBA, NFL and CBB on Kalshi tonight; and nothing asks for the passcode when the scanner is opened from the app.

- **Kalshi NFL** (`scan_kalshi.py --league nfl`; the `kalshinfl` board; a hidden **Kalshi NFL** tab): one player's own props, both legs Yes, every pair the Novig NFL board prices (receptions, receiving yards and a touchdown; a quarterback's attempts, completions, yards and passing TDs; rushing yards, carries or rush + receiving yards with a touchdown) at r 0.25 or better. Legs, fair value, price, fee and the 60-slip cap as on Kalshi NBA. 54 slips on tonight's game and Thursday's; 46 with both legs on Novig's book (Novig lists the round-number yards lines Kalshi uses).
- **Not on it yet**: quarterback + receiver stacks, props with game lines, three legs, Unders.
- **The passcode**: the prompt only came up with `#kalshi` on the address, which a link from the app doesn't carry. Typing `kalshi` in the "Filter by name" box now asks for it too. So do three quick clicks on the scanner's own title (the scanner opens inside the main app, where the address can't be changed); with the passcode already in, the same clicks offer to hide the tabs again.
- **Kalshi CBB** (`--league cbb`; the `kalshicbb` board; a hidden **Kalshi CBB** tab), added after the NFL board: a game's spread with its total, the two pairings that go together in `cbb_line_correlations.json` (favourite + Under and underdog + Over at r 0.04; favourite + Over and underdog + Under at 0.14 on spreads of 20+). The underdog covering and the Under are No legs on Kalshi's "wins by over" and "Over" markets. Fair values are Novig's books on the same lines (Kalshi's own college books are 8 to 10 cents wide); each game is matched to Novig's by start time and team code, and a game Novig doesn't list is left out. 42 slips on 21 games tonight. With r this small a slip is above fair only where Kalshi's makers price it under two unrelated legs by more than the fee; the tape earlier showed them pricing spread + total as unrelated, so expect few.
- **Start times fixed on all three Kalshi boards**: Kalshi's `occurrence_datetime` is about three hours after the start, so rows showed a start three hours late and a game already under way could still be asked. The start is now Novig's where the player or game is on Novig, else Kalshi's time less three hours.
- **Checked**: the 54 NFL slips built from live lines; the passcode typed into the filter and the NFL tab opened in a browser against the local server. The CBB slips' legs and sides (Yes / No) checked against a stand-in. No real Kalshi price has been seen on the NFL or CBB board.

### Novig Scan: the Kalshi NBA tab is hidden behind its own passcode
Max, 11-16: hide the Kalshi tab, password yyy, since it asks with my API key. (The board's first real pass priced: Davis 25+ with Young 20+ at 5.46x, +14.8%.)

- **Server** (`server.js`): the Kalshi board answers only to a second passcode (`X-Kalshi-Key`; `yyy`, or `KALSHI_TAB_KEY` on the server). Without it the board can't be read or started (423), its rows stay off the All tab, and a pass on it shows to others as "another" board.
- **Page**: the tab is hidden until the passcode is on the device. Open the scanner with `#kalshi` on the end of the address and type it once; it is kept on that device. A wrong one is forgotten at the first refusal and the tab goes away again.
- **Also**: the price column's heading follows the board (Kalshi, DK, Novig); it said Novig on every tab.
- **Checked** in a browser against the local server: no tab without the passcode, a wrong passcode refused and dropped with the main passcode kept, the right one showing the tab on that visit and the next. The passcode sits in the repo's code; anyone who can read the repo can read it, so set `KALSHI_TAB_KEY` in Railway if the repo is shared.

### Novig Scan: a Kalshi NBA board (the NBA slips asked as Kalshi combos)
Max, 11-16: the Kalshi key is saved in Railway (`KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY`; made with Read all data + Trade only).

- **Added** (`.claude/skills/nba-sgp-fv/scan_kalshi.py`; the `kalshinba` board in `server.js`; a **Kalshi NBA** tab on the page; `cryptography` in `requirements.txt` for the signing). Per player with open Kalshi props on a game not yet started: each team's two highest points lines together (r 0.0, asked first), Points + Threes, and his other pairs at r 0.25 or better. Every leg is a Yes on a Kalshi milestone (25+ points is Over 24.5), on the one nearest Novig's main line.
- **Fair value**: each leg is Novig's book on the same line where it is tight, else Kalshi's own bid and ask, 5c wide at most (marked ~). Legs between 15% and 85% only.
- **Price**: for each slip the script creates the combo, sends a $25 request for quote, waits 3 seconds, reads the makers' answers and deletes the request. Buying Yes costs 1 less the best No bid; Kalshi's fee (7% x price x (1 - price)) goes on top. The script has no call that accepts a quote or places an order.
- **Fetch only, 60 slips a pass**: Auto-scan leaves the board out and one row can't be refreshed by itself. Each ask is a real auction on the account; Kalshi makes asking dearer for accounts that ask often and never accept, and allows 5,000 new combos a week.
- **Checked**: 60 slips built from Kalshi's and Novig's live lines (58 with both legs on Novig's book). The whole pass through the server and the page (phone-sized browser, the tab, an opened row) with Kalshi's signed calls answered by a stand-in that verifies the signature; the key read both pasted on one line and with `\n` breaks.
- **First real pass, same day**: the Trade-only key was accepted, and the combo and the request for quote went through. Kalshi refused the read of the answers (403: it must be marked as the account's own requests); the read now sends `rfq_user_filter=self`.
- **Not checked: no real Kalshi price has been seen.** The key is on the server only. Three things are assumptions until the first real pass: that a key with Trade (not Full access) may create combos and requests for quote (if not, the board says so and names the fix); that same-game NBA combos are made in `KXMVECROSSCATEGORY-R` (the collection on today's tape; the script tries a second one); and that makers answer a $25 request inside 3 seconds. `python3 scan_kalshi.py --check` on the server tests the key alone and asks nothing.

### Kalshi and Polymarket looked at for the same scan (nothing built yet: a live price needs an account key)
Max, 11-16: can the Novig logic be done on Kalshi or another exchange?

- **Kalshi has the slips**: its combos take two or more legs from one game: player points, rebounds, assists, threes, NFL yards, receptions and touchdowns, spreads, totals, moneylines. Its public API reads from here with no key: every leg's book, every combo market and every trade.
- **What it lacks is Novig's keyless quote.** A combo price on Kalshi is an auction (create the combo, send a request for quote, read the makers' answers), and each of those calls must be signed with an account's API key. Polymarket's combos work the same way and need its account credentials. So a live board is possible, but only with a key on the server.
- **Fee**: Kalshi charges the taker 7% x price x (1 - price) a contract (its fee schedule; the combo series is on the standard rate). Novig's parlay fee is the same shape at 10%.
- **A first read without a key, from the public trade tape** (two pulls about 30 minutes apart, 2 and 14 minutes of trades; about 3,000 combo trades a minute, most of them 3+ legs or across games). 170 two-leg same-game combos a taker bought had both legs on books 4c wide or less; 121 of those had both legs between 15% and 85%, where a whole-cent book is a usable fair value. Legs were priced off Kalshi's own books, worst-case devig, and joined at this repo's r.
  - NFL, one player's rushing yards + touchdown (7): Kalshi's implied r +0.42 against our +0.49; after the fee, median -1.9%, range -7% to +6%, 3 of 7 above fair.
  - NBA teammates' points, both Yes (3): implied r -0.01 against our 0.00; median -4.2%, one at +8.5% (Davis 20+ with Young 25+, implied r -0.20, a $1 trade).
  - NBA, one player's pairs (4): implied r +0.49 against our +0.42; median -3.6%.
  - Shapes with no r of ours applied: moneyline + total and spread + total priced as unrelated (implied r about 0), opposing players' touchdowns +0.01, teammates' touchdowns -0.12.
- **What that says**: on these few trades Kalshi's makers price the correlation close to this repo's numbers, so the price lands near fair less the fee. Nothing like Novig's NBA teammates discount showed up, but three trades can't rule it out. The sample is small and it is what other people chose to buy, not the scanner's slips; the NBA games were three hours off.
- **To build the board**: a Kalshi API key (key id + private key) set on the server. Then the scanner's own slips can be asked directly. Two costs to know first: Kalshi raises the price of asking for accounts that ask often and rarely accept, and an account may create 5,000 new combos a week.
- **ProphetX, looked at the same day** (Max: check ProphetX too). It is the closest to Novig: one call takes a slip's legs and answers with a parlay price in about two seconds (`POST cash.api.prophetx.co/parlay/api/v1/affiliate/quotes`, 2 to 12 legs, American odds back, or nothing when no maker answers). But the call needs a token ProphetX issues on request (hello@prophetexchange.com, "Affiliate Parlay Quotes"), and reading its lines needs a second one (Market Data API, also on request). Without a token the quote call answers 401 from here. The price it returns has no fee in it, and ProphetX's docs give no fee rate (it is set per account), so what the slip pays would have to be checked against the app. Nothing was priced.
- **Not looked at**: Sporttrade.

### NHL looked at again (still nothing above fair; the boards stay hidden)
Max, 11-16: EV plays in every league but the NHL.

- **Two players, both Yes** (28 slips, six games with tight books, two days before the games): Novig prices every pairing as positively related, opponents included. Its implied r: teammates' shots + shots +0.21, teammates' goal + goal +0.18, opposing skaters' shots +0.19, goals +0.19, points +0.16, teammates' points +0.47.
- **What two seasons of game logs say** (3,177 team-games; each skater's hits centred on his own season rate): a team's top two shooters' shots +0.03, top two scorers' goals +0.01, opposing top shooters' shots -0.01, opposing scorers' goals -0.02, opposing scorers' points 0.00 (all within 0.05 of zero); teammates' top two scorers' points +0.30. So every Yes + Yes slip is far under fair.
- **The other way round is no better**: one Yes with the other's No (38 slips, a second ask on none because none came back above fair), priced at the measured r: teammates' shots -20% at the median (best -16%), opposing shots -22%, teammates' goals -26%, opposing goals -24%, opposing points -15%. Novig is not wrong about the direction; it takes a far bigger margin on NHL player parlays than on the NBA's. Draisaitl and McDavid's goals: Yes + Yes at 4.33x and Yes + No at 3.05x add up to 56% for an event (Draisaitl scores) its own book has at 42%.
- **Game lines only** (moneyline, puck line either way, with the total Over and Under; 40 slips on four games): 0 above fair, medians -8% to -11% by shape. Measured r of a result with the total is about zero except win-by-two with Over 5.5 (+0.17), and Novig charges more than that too.
- **Caveat**: all of it two days before the games, when few books are tight. Worth one more look on a game day before calling the NHL closed.

### Novig Scan: a DK NBA board (the NBA slips priced on DraftKings)
Max, 11-16: can a scan like this be done for DraftKings? Try anything to get it to work.

- **What was there already**: `dk_api.py` reads DraftKings' slate and every line, and prices a same-game parlay with DraftKings' own `calculateBets` call (`_price_combo`), the path the main app's DK pricing uses.
- **Added** (`.claude/skills/nba-sgp-fv/scan_dk.py`; the `dknba` board in `server.js`; a **DK NBA** tab on the page): per player on tonight's DraftKings slate, Points + Threes Over at DraftKings' own O/U lines, his other Over + Over pairs at r 0.25 or better, and each team's two highest points lines together (r 0.0). 172 slips on tonight's slate. Each leg's fair value is Novig's exchange book on the same line where it has a tight one, else DraftKings' own Over / Under with the margin taken out (53 of the 172 have such a leg; marked ~). The row shows DraftKings' parlay price, EV, stake, and what its two legs multiplied would pay.
- **Fetch only**: Auto-scan leaves the board out (each price is a request DraftKings sees), one row can't be refreshed by itself, and the rows appear on the All tab tagged DK NBA.
- **The catch**: DraftKings answers the price call only from a connection it trusts. From the machine this was built on it refused (403, its bot protection; the slate and the lines read fine), and nothing was done to get around that. So **no real DraftKings parlay price has been seen by this board**. On the server it will price if the main app's DK pricing is working there (a fresh DK cookie, or `DK_PROXY`); if DraftKings refuses, the pass stops after four refusals and the board says so.
- **The pasted cookie reaches it** (fixed the same day): the board's pass is started with the DK cookie saved in the main app (Soccer tab, "DK cookie"), as the app's own DK pricing is. The first version started it without.
- **Checked**: the 172 slips built from DraftKings' and Novig's live lines; the whole pass through the server and the page (phone-sized browser, the tab, an opened row, the All tab) with DraftKings' price call replaced by a stand-in; and the real call from here ending with the refusal message on the board.

### Novig Scan: the status line says when Auto-scan is resting
Max, 11-16: "doesn't seem to be scanning" (every board priced 3 to 7 minutes ago, "next: NBA", nothing moving).

- **What it was**: nothing wrong. With today's games only, a round of all six boards takes a few minutes, and then every board is inside its ten minutes' rest (no board more often than every ten minutes), so nothing runs until the first one is due.
- **Change** (`nvCycleState` in `server.js`, `autoLine` on the page): between passes the line reads "resting (no board more often than every ten minutes) · next: NBA in 3 min".
- The ten minutes is unchanged. Halving it would double the asks Novig's pricers see from this server.
- **Checked** with a stand-in scanner that ends at once: the board and the time to it came back right between passes. The page was not opened.

### Novig Scan: doubtful NBA players are hidden, questionable ones carry a Q
Max, 11-16: Jaylon Tyson headed the All tab at +22% an hour after he was downgraded to doubtful.

- **What was wrong**: the board hides players ESPN lists as Out, Injured Reserve, Suspension or Doubtful, but ESPN's NBA report has no Doubtful (or Questionable) status. Both are "Day-To-Day", with the word in the note ("Tyson (ankle) has been downgraded to doubtful for Monday's game against the Bulls"). So no doubtful NBA player was ever hidden. The NFL report does use Doubtful and Questionable.
- **Fix** (`nvOutRefresh`, `nvFlag` in `server.js`): a Day-To-Day note about today's game (the weekday it names, Eastern) is read. Doubtful, ruled out, out, won't play: the player is hidden like any other out. Questionable: his rows stay and carry a **Q** beside his name (hover or hold for the note), on his board and on All. A note about another day's game is ignored: it says nothing about tonight. NFL Questionable players get the Q too.
- **Still true**: the report is read every ten minutes and ESPN's note can trail the news (Tyson's was posted about an hour before the screenshot). A big number on a role player is worth a look at the news before betting.
- **Checked** against ESPN's live report with a stand-in board: Tyson and Larsson (doubtful) hidden, Watson and Embiid (questionable, Embiid on a two-player slip) flagged, Mitchell untouched, VanVleet ("ruled out for Sunday's game", yesterday) untouched. The page was not opened to look at the Q.

### Novig Scan: NBA teammates' points, Over + Over
Max, 11-16: Points + Threes are dead; what else for the NBA? (Then: yes, build it.)

- **Added** (`nba_mate_candidates` in `scan.py`; `--no-mates`): on the NBA board, each team's two highest points lines, Over + Over, as one slip under both names. One ask a team, not gated by the Points + Threes quote. Priced as unrelated legs (`NBA_MATE_R` 0.0).
- **Why unrelated**: on four seasons of box scores (each player's line his median over his previous 15 games, 20+ minutes) a team's top two scorers both go Over at r +0.02 on 6,578 team-games (two-sigma range -0.03 to +0.06), the same at 20+ and 24+ points a game; 0.0 is that less one standard error. Pairs don't differ from one another by more than chance (204 pairs with 40+ games together), so no pair has its own number.
- **Why it can pay**: Novig often prices the two as if one's night cost the other's. 11-16, 16 teams: its quotes implied r -0.05 at the median, and -0.12 to -0.15 on Jokic + Murray, Davis + Young and Maxey + Brown (+6% to +10% against r +0.02; 8 of 16 above fair, median +0.4%).
- **Probed the same day and not added**: one player's Over + Under (Novig quotes it; points Over + assists Under on six stars -6% to -30%); opposing stars' points Over + Over (measured r +0.06, Novig about the same: 8 slips, median -2.7%); teammates' rebounds, opposing rebounders and opposing passers (unrelated in the data, -0.03 to +0.03). Rebounds Over + game Under is 0.06 to 0.12 and + the opponent's team total Under 0.09 to 0.16 in `nba_line_correlations.json`: under the 10% fee.
- **Teammates' assists and rebounds, researched and not added** (Max, 11-16: do the same with assists and rebounds, research first). Box scores, same method: top two passers' assists Over + Over r -0.04 to -0.02; top two rebounders' rebounds 0.00 to -0.03; the top passer's assists with a teammate's points +0.08 (+0.03 to +0.13) and with a teammate's threes +0.10 to +0.12; a rebounder's rebounds with a teammate's points or assists 0.00 to +0.02. Novig, 61 slips on 16 teams with a second ask: assists + assists 0 of 15 above fair (median -2.5%; its implied r -0.07 is close to the measured one); rebounds + rebounds 2 of 15 (median -6.0%); assists + a teammate's points 6 of 15 but none over +2.6% (median -2.3%); assists + a teammate's threes 4 of 16, best +4.5% (median -2.9%). Nothing like the points pairs, where Novig's implied r was -0.12 to -0.15 against a measured +0.02.
- **More NBA slips looked at and not added** (Max, 11-16: keep looking). All on tonight's 16 teams, with a second ask on anything above fair.
  - Teammates' combined stats, both Over, measured as unrelated (PRA + PRA r +0.01 to +0.04, points + assists pairs +0.03, points + rebounds pairs +0.02, two shooters' threes about 0, a scorer's points with a teammate's PRA +0.02): PRA + PRA 3 of 16 above fair (median -3.4%, best +4.7%), points + assists pairs 3 of 7 (best +1.0%), points + rebounds pairs 1 of 8, threes + threes 1 of 16 (median -6.9%), points + a teammate's PRA 3 of 16 (best +3.5%). Jokic + Murray, +8% on points, is +0.7% on PRA: the discount is on points.
  - Three scorers' points, all Over (0.93 times unrelated in the data): 2 of 13 above fair, median -9.6%. The two were PHI (+9.3%) and BOS (+5.0%).
  - A team's third and fourth scorers with the top two: r -0.03 to -0.07, about what Novig charges, so the teammates slip stays at the top two.
  - One player's combined line with one of its own parts (points + PRA, rebounds + points-and-rebounds, assists + rebounds-and-assists): Novig refuses these ("Invalid parlay combination"). Two combined lines together (points-and-assists + PRA) it takes and prices at r 0.85 to 1.00 against a measured 0.78 to 0.82: -15% to -22%. Threes + PRA for real shooters -10%.
  - Not looked at: steals and blocks (Novig lists them; the box scores on disk hold minutes, points, rebounds, assists and threes only).
- **The line beside, tried on NBA game lines and not added**: the CBB slips and their moved-line versions run on three NBA games with NBA r's (65 quotes, team totals and first-half legs on Pinnacle's price). Every moved-line version came back within about 3% of its own slip (MEM @ WAS -2% to -11% throughout, ORL @ BOS -4% to -13%), so on the NBA Novig's price does follow the line and the extra asks would find nothing the slip doesn't. CHI @ CLE was above fair on nearly every spread slip, moved or not (+2% to +8%): that game, not the line.
- **Checked** end to end on PHX @ DEN: Jokic 26+ + Murray 25+ fair +322, Novig 4.56x, +8.1%, the same on a second ask; Booker + Brooks -10.6%. The row was opened on the page in a browser. One slate only.

### Novig Scan: my bets are kept on each device only
Max, 11-16: other people look at the scanner too; hide the bets and keep them local.

- **Change**: the bets list lives in the browser (`nbaScanMyBets`) and nothing about a bet is sent to the server. The `/api/nba/novig-bets` routes are gone, and the server's saved list is set aside at start (`novig_bets.old.json`, not deleted). Another person with the passcode sees the boards and none of your bets.
- **What you lose**: the phone and the computer no longer share one list. A bet shows on the device it was entered on.
- **Bets already entered**: each device starts from the copy it had kept of the old shared list, so a device that had the page open before still shows them (anyone else's that did, too, until those games are three days old).
- **Checked** in a browser on a stand-in board: the old copy came over, a new bet was added and was still there after a reload, no request about bets went to the server, a second browser with the same passcode showed no bets, and the old route answers 404.

### Novig Scan: soccer priced by measured correlations, with the line beside and the mirror slip
Max, 11-16: build it (after the research below).

- **Fair value** (`slip` in `soccer_candidates`; `price.quad_joint`; `public/data/soccer_corner_correlations.json`): a Gaussian copula's joint at the legs' own prices, with each pair of legs' r measured on 19,761 top-five-league matches by strength of favourite, times a scale per shape so it matches the counted hit rate on average. It replaces one fixed lift per favourite strength, which was right only at the 50/50 corner lines. At those lines the two agree (Slovenia: x1.24 against x1.26; with Over 2.5 x1.45 against x1.40).
- **How good**: at the main corner lines and one corner either side (nine combinations per favourite strength), the scaled joint is within 5% of the counted hit rate for every shape the board asks.
- **The mirror**: underdog to win + favourite's corners Over + underdog's corners Under, where the favourite is under 70% to win (`SOCCER_DOG_MAX`; above that the fit is up to 11% out on few matches).
- **The line beside**: each three-leg slip is asked again with a corner leg moved one line, where that line has Pinnacle's price or a Novig book inside 10c. On today's Nations League board that was 4 extra slips over 13 matches: few corner lines have a usable second price.
- **Data** (`scripts/soccer_corner_correlations.py --fetch 2016 2026`): downloads the seasons from football-data.co.uk into `public/data/soccer_matches.json` and rebuilds the correlations with their checks.
- **Checked live** on Slovenia v North Macedonia with the league list pointed at the Nations League for the test (6 slips, all priced): the three favourite slips -9% to -11%, the mirror 26.8x against a fair +2161 (+19%, the same on a second ask), its moved-line version +11%. **Not checked on a major-league match**: Novig has no corner books on one today. The page was not opened on the soccer tab.

### Soccer SGPs researched further (nothing changed on the board)
Max, 11-16: research more on soccer SGPs.

- **Game-line slips in the major leagues: no.** On two EPL matches every way of betting a draw with a total or BTTS (nine slips a match) came back -13% to -60% against Pinnacle's own combo price, its correct scores and a goals model; Man City v Fulham's thirteen win / total / BTTS / spread slips were -8% to -24%. The long shots Novig overpaid on the Nations League matches earlier today are not there on the EPL.
- **A goals model against history** (two Poisson means and a low-score term fitted to each match's closing home, draw and Over 2.5 prices; 19,763 top-five-league matches): right within 2% on win & total and on BTTS & win. Off on draws: 2-2 or higher happened 15% more often than the model, 0-0 13% less, a win by two or more 7% less. Novig's draw slips are far enough under fair that this doesn't rescue them.
- **Corners are the one loose spot, and the board's fair value there is coarse.** It uses one lift per favourite strength; measured by line, the favourite win + his corners Under + underdog's corners Over hits x1.15 to x1.61 as often as unrelated legs (higher with a harder corner line, lower with an easier one). So a row on a line a corner off 50/50 can be up to 15% out, either way.
- **A fix that holds at every line**: one correlation per pair of legs (result with the favourite's corners 0.22, result with the underdog's 0.09, the two corner legs 0.17, by favourite strength) through the three-leg joint the other boards use gives the counted hit rate within 5% on all 36 line combinations. That would also let the board ask the corner line beside, as CBB now does.
- **The mirror** (underdog wins + favourite's corners Over + underdog's Under): x1.3 to x1.9 by line. The same joint is within 6% of the count where the favourite is under 60%, and 10% to 25% too high above that (few games), so it would be for even matches only.
- **Not checked live**: Novig has no corner books on a top-five-league match today (they open nearer kick-off).

### Novig Scan: CBB slips are asked again with a leg moved one line
Max, 11-16: after the Pinnacle lines are found, check the line beside too (U88 + U74 paid +230 where U88 + U76 paid +225).

- **Change** (`beside`, `row` in `cfb_candidates`; the `moved` stage in `scan()`; `--alt-gate`, `--no-alts`): each two-leg CBB slip also gets versions with one leg moved to the next line, one easier and one harder, where that line has a fair value (Pinnacle's on team totals and the first half, Novig's own tight book on the game's spread and total) and its chance stays between 25% and 75%. They are asked after the slips themselves and show as ordinary rows under the game.
- **When they are asked**: always for slips with a team-total or first-half leg; for spread + total slips only when the slip itself priced within 8% of fair.
- **Why not gate them all**: live on ACU @ MOST (21 slips, all priced), ACU +5.5 + ACU Under 67.5 paid 4.04x (-39%) and ACU +6.5 + Under 67.5, the easier slip, paid 5.95x (+10%). Both team totals Under: -26% at 72.5 / 67.5, +7% at 72.5 / 66.5, +3% at 73.5 / 67.5. Novig's price on these does not follow the line, so a slip's own EV says nothing about the line beside it. The eight spread + total versions all came back within 3% of their slip (-7% to -13%).
- **Cost**: about three times the asks on team-total games. Today's slate: 104 slips and 353 moved-line versions over 22 games (180 always asked, 173 gated), counted without quoting.
- **Checked**: that one game end to end against Novig, slips above fair settled over two asks as usual. A whole pass was not timed and the page was not opened.

### Novig Scan: soccer is the major leagues only
Max, 11-16. `SOCCER_LEAGUES` is the top five (EPL, Serie A, La Liga, Bundesliga, Ligue 1), which the lifts were measured on, and the Champions League. Dropped: Europa League, MLS, Liga MX, UEFA Nations League, FIFA World Cup, FIFA Club World Cup.

### Soccer explored (nothing changed on the board)
Max, 11-16: explore other soccer; check BTTS and Novig's SGPs against Pinnacle, prebuilt combos included.

- **Leagues**: Novig lists soccer in eight leagues (66 matches), all of them already asked.
- **BTTS against Pinnacle**: on 43 matches with both, Novig's Yes and No offers sit either side of Pinnacle's no-vig price; taking the better offer is -4% to +1%.
- **Novig's parlays against Pinnacle's prebuilt combos** (result & total goals, BTTS & result, BTTS & total goals; fair = Pinnacle's combo market with its 6% to 8% margin taken out in proportion; eight Nations League matches, 128 quotes): median -8% to -9% for each kind. 17 quotes above fair, nearly all long shots with the draw or the underdog (Draw & Over, No & Draw, underdog & either total), and Novig paid more than Pinnacle's own price, margin included, on many of them (Germany v Netherlands No & Draw 27.6x against Pinnacle's +2053, the same when asked again). Taking the margin out in proportion flatters long shots, so those EVs are high; paying more than Pinnacle's price is not affected by that. Not checked on a major-league match, and Pinnacle's limit on these is $150.
- **Goalscorer + his team to win**: priced above the goalscorer's own chance. Nothing there.
- **Other corner shapes**, measured on 19,761 top-five-league matches (football-data.co.uk, 2015-16 on; the same method gives the board's existing lifts): underdog wins + favourite's corners Over + underdog's corners Under hits x1.37 to x1.62 as often as unrelated legs would; underdog wins + favourite's corners Over x1.16 to x1.37; favourite -1.5 + his corners Under + underdog's Over x1.25 to x1.47. Total corners with total goals, and BTTS with corners: unrelated (x0.95 to x1.06). On two even Nations League matches Novig priced the first shape at about 14x where x1.22 was needed, twice running; on lopsided matches it was far under fair. Corner legs there were Novig's own 5c to 8c books, not Pinnacle's. Novig refuses "favourite doesn't win" in a parlay.

### Novig Scan: swipe a row right to hide it; Unhide brings them back
Max, 11-16.

- **Swipe** a row to the right (finger, or a mouse drag) past about a third of its width and it leaves the board; a shorter drag, or one to the left, puts it back. Up and down still scrolls. The drag starts on the row itself, not on its buttons, the Novig link, the bet form or the opened details.
- **Unhide N** appears beside Hide my bets while any open row is hidden, and brings them all back.
- **What is hidden**: that one slip, on its own board and on All, on this device only (`nbaScanHidden` in the browser), until its game starts (then it is forgotten) or Unhide. A new pass does not bring it back. The player's other slips stay.
- **Checked** in a phone-sized browser with touch drags on a stand-in board: a long right swipe hid the row and showed "Unhide 1", a short swipe and a left swipe did nothing, the row stayed hidden after a reload, Unhide brought it back. Not tried on a real phone.

### Novig Scan: a row's Novig price is a link that opens the slip in Novig
Max, 11-16: make the plays links (and, next, Discord alerts that carry them).

- **Novig's link format**, read from its own web app's code (novig.com's script bundle, 11-16; not documented anywhere public): `/events/<outcome id>,<outcome id>,...` opens the board with those legs put on the slip. The app's router has it as `events/:orderslip_outcomes?/:partner_id?/:amount?`, its "share parlay" builds the same path, and the phone app answers to `novigapp://` and `https://novig.onelink.me/JHQQ`.
- **`GET /n/<outcome ids>`** on this server (`server.js`; no passcode, it only redirects and takes nothing but outcome ids): a computer is sent to `https://novig.com/events/<ids>`; a phone gets a page that opens `novigapp://events/<ids>` at once, with buttons for the app and for novig.com if it doesn't open.
- **Page**: each row's Novig multiplier is that link (new tab). Pressing it doesn't open the row.
- **Not confirmed that the slip fills.** Novig's bot check stopped a browser from here at the link, and a signed-out phone browser is sent to sign-up, so the slip was never seen with the legs on it. Tap one on the phone and on the computer (signed in) to see. Checked here: the route's two answers and its 404 for anything but outcome ids, and the link on a stand-in row in a browser.
- **Works** (Max, 11-16, iPhone): the app opened with both legs on the slip as a 2 Leg Parlay (Cam Spencer 13+ PTS · 3+ 3PM). Not yet tried on a computer.
- **A phone opens the app straight from the row** (same day): the first version sent the phone to the `/n/` page, and the home-screen app has no back button to leave it. The row's link on a phone is now `novigapp://events/<ids>` itself, opened from the top window, so the scanner stays put. The `/n/` page (still what a computer and any link sent off the page use) has a "Back to the scanner" button.
- **Amount**: the path's third part is a stake, but it comes after a partner id Novig's affiliates use; not sent.

### Novig Scan: Auto-scan prices today's games only
Max, 11-16: have the auto scanner focus on the games of that day.

- **Change**: an Auto-scan pass leaves out every game starting after the next midnight (`nvDayEnd` in `server.js`; `scan.py --before MS`, applied in `scan()`'s `mine`). Midnight is in the time zone of the page that switched Auto-scan on (the page sends it; Eastern if none, and for a cycle already on from before this change until it is switched off and on again).
- **Later days' games** are priced with Fetch only (the whole board, or the game picker). Their rows stay on the board at their earlier prices: an Auto-scan pass removes only today's rows it did not price.
- **A board with no game today** gets a pass that reads the board and asks nothing, then the cycle moves on.
- **Page**: the status line says "today's games only", and a board whose last pass was Auto-scan's says so.
- **Checked** on the live boards without asking for a quote (candidates counted at the start of a pass): NFL 247 slips to 225 (LAC @ BAL tonight; the rest are Thursday's and Sunday's), NBA 65 to 65 (all tonight), CFB 0. Not run end to end through the server, and the page was not opened.

## 2026-11-15 session

### Novig Scan: passing-TD correlations fitted at 3+ as well as 2+
Max, 11-15: fix the 3 TD correlation (Purdy 3+ PASS TD · Samuel 1+ TD · SF team total Over 30.5, fair +497, with three books paying +486 to +575).

- **What was wrong**: a good offence's main passing-TD line is 2.5, not 1.5 (Purdy: 3+ at 35%, 2+ at 65%), and every role r with passing TDs was fitted at 2+ only.
- **Fix** (`PTD_AT`, `ptd_lines` in `scripts/nfl_stack_correlations.py`; `role_r(..., at)`, `ptd_at` in `scan.py`): each pairing with passing TDs is fitted twice, at 2+ and at 3+ (rows with `at` 1.5 and 2.5 in `nfl_stack_correlations.json`, rebuilt today), and the scanner uses the row nearest the passing-TD leg's own line. The 2+ rows are the same numbers as before.
- **What 3+ changes**: with a receiver's anytime TD the r is lower (WR 3 to 5 targets 0.57 to 0.45, 5 to 7 0.61 to 0.54, 7+ 0.62 to 0.54; TE 5+ 0.58 to 0.47); with the scoring lines it is higher (team total 0.67 to 0.82, game total 0.62 to 0.68, covering 0.31 to 0.41).
- **On Max's slip the two cancel**: fair +497 at the 2+ rows, +501 at the 3+ rows. So the 3+ fit was not why the books paid more than fair.
- **The three-leg joint checked against ten seasons** (QB passing TDs + his WR's TD + team total, each QB-receiver season at its own hit rates): at 3+ all three hit in 9.1% of 2,476 games for 3-to-5-target receivers against the model's 9.2%, 12.2% against 12.0% at 5 to 7, 15.6% against 15.9% at 7+. With the game total in place of the team total the 3-to-5 bucket runs 9% high (7.7% against 8.4%); the others are within 2%. This is the same data the r's were fitted on, pair by pair; the three-way count was not fitted.
- Not run end to end against Novig; candidates were built on today's board without error (552 slips, 97 three-leg).
### Novig Scan: a pass prices its board's best rows first
Max, 11-15: half the All tab was dimmed. Those were NFL rows the running pass hadn't reached (about 2,750 slips, 50 minutes at a quote a second, asked in game order) and rows over an hour old.

- **Change**: when a pass starts, the server lists that board's rows at -2% EV or better from last time, best first, 400 at most (`NV_LEAD_EV`, `NV_LEAD_MAX`; written to `novig_first_<board>.json` beside the saved boards) and `scan.py --first FILE` asks those before the rest of their stage. The rest follows in game order as before. No more quotes than before.
- **What to expect**: the top of a board is re-priced in the first minutes of its pass, not up to 50 minutes in. A board is still priced once per Auto-scan round, so an NFL row can still pass an hour (and dim) while the other five boards take their turn.
- **NBA**: the main-line Points + Threes slips still go first (they decide which players get more asked); the listed rows lead each stage after that.
- **Checked** live on CAR @ NO stacks (8 slips, twice): the three slips listed were asked first, in order; one came back above fair and was held 40 seconds to settle, so its row landed last. The server was started on a saved board and passed the scanner the right five keys, best EV first. A full pass was not timed and the page was not opened.

### Novig Scan: NFL Unders
Max, 11-15: "I don't ever see NFL unders" (the NFL board built every player prop as an Over); Unders are fair play.

- **Asked now** (`scan.py --league nfl`; `--no-unders` leaves them out):
  - a player's **Under + Under** on each of his own pairs (`nfl_candidates`), at the same r as the Over + Over;
  - a stack's **Under + Under** (QB passing Under + his receiver's Under);
  - **Over + Under across a QB and his back**, both ways (`STACK_AGAINST`): pass attempts against carries (-0.29 for a lead back, -0.20 at 8 to 13 carries) and passing yards against rushing yards (-0.15, lead backs only). These were in `nfl_stack_correlations.json` and not asked;
  - a prop's **Under + the game line's other side** (a back's rushing yards Under + the other team covering).
  Stacks and lines get each player's allowance (`--per`) again for the Unders, so they don't push his Overs out. Three-leg slips are still all Overs.
- **The r** is the Overs': a copula r fitted to how often both Overs hit gives how often both Unders hit as well, and its negative gives one Over with the other Under.
- **Novig prices them.** One NFL player's Under + Under is quoted (St. Brown U7.5 REC + U81.5 YDS; Addison the same), unlike the NBA's, which it refuses. Sixteen probe slips of the eight shapes on DET and MIN all came back with a price.
- **Not asked**: an Under + Under where a leg is U0.5 of anything but a touchdown (U0.5 receptions is U any yards: one leg, not two).
- **Page**: the NFL filter has "Unders: any slip with a prop Under"; the note under the board says what is asked.
- **A pass is twice as long**: 1,488 slips to 2,996 on the 11-15 slate (counted without asking for quotes), about 50 minutes at a quote a second, so the server's limit on one pass goes from 45 to 90 minutes (`NV_SCAN_MAX_MS`).
- **Checked**: `--kind stacks` on NE @ DET end to end against Novig, 60-odd rows, Unders and Over + Under among them, none above fair (best -2.1%). The props and lines Unders were counted and spot-read, not quoted in bulk; the page was not opened in a browser and a full pass was not timed.

### Novig Scan: NFL slips with a fair value longer than +600 are not asked
Max, 11-15: keep the FVs we scan under +600 (the NFL board was headed by 70x slips at +2209 and +2311); NFL only.

- **Change** (`--max-fair` in `scan.py`, 600 for `--league nfl` and no cap for the other leagues; applied in `scan()`'s `mine`): an NFL slip whose fair value is longer than +600 is dropped before it is sent to Novig, so it costs no quote. Three-leg slips built later in a pass go through the same check. `--max-fair 0` removes the cap.
- **NFL Ladder**: its band was +500 to +800 (`--ladder-fair`), so it now holds +500 to +600 only. The NBA ladder and every other board are unchanged.
- **Rows already on an NFL board** above +600 go when that board's next full pass finishes (a pass removes rows it did not price).
- **Checked** without asking Novig for a quote (candidates counted at the start of a pass, 11-15 slate): NFL 1,827 slips to 1,438; NFL Ladder 420 to 173. For NHL and NBA the cap reads as off, but only one NHL slip and no NBA slips were open to count. Not run end to end against Novig, and the page was not opened.
- First pushed as a cap on every board; narrowed to NFL the same day.

## 2026-11-14 session

### Novig Scan: Auto-scan is a plain on/off switch
Max, 11-14: turn it on and off at any time; no time rules. Gone: the 10 PM to 8 AM pause, the one-week limit and the "are you sure" prompt. The button switches it on at once, at any hour, and it runs until the button is pressed again (it still comes back on after a redeploy if it was on). A minute between passes and ten minutes before the same board is asked again are unchanged. Checked with a stand-in scanner: on started a pass at once, off stopped it, on again after a restart.

### Novig Scan: the five-minute re-pricing of the top eight is removed
Max, 11-14: with slips above fair now asked again until they settle, the separate re-pricing of the eight best plays every five minutes is not needed. `nvTopTick` and its status text are gone (about 100 fewer quotes an hour); the row refresh button is unchanged. The injury report is now refreshed from the auto-scan tick. A row's price is as old as its board's last pass (its Age), so press the row's refresh before betting an old one.

### Novig Scan: a slip above fair is asked again until its price settles
Max, 11-14: the top plays are "fake"; on the slip the odds are lower before he has put money in.

- **What was found** (asked from here, 11-14): Novig's first quote on a slip it hasn't been asked lately is often not its price. Goff 36+ pass attempts + 269+ yards quoted 4.14x, then 2.32x on every ask after; Herbert's 1.73x, 2.83x, then 2.33x; three other quarterbacks' slips gave the same price five times running. Mahomes 33+ attempts + 241+ yards, +25% on the board at 3.34x, quoted 2.65x (fair, +167) six times a few minutes later. The board showed each slip's first quote, and sorting 1,500 of them by EV put the wrong ones on top.
- **Fix** (`settle` in `scan.py`'s `scan()`; `SETTLE_S`, `SETTLE_TOL`, `SETTLE_MAX`): a slip whose quote comes back above fair is held back and asked again 40 seconds later, until two quotes in a row agree within 2% (three more asks at most, then the worse of the last two). Its row is sent only then, at the settled price. Slips at or under fair are sent on the first quote as before. An opened row shows "first quote 4.14x, settled over 2 asks".
- **Live check** (SEA @ LV, 116 slips, all priced, 190 seconds): 15 came back above fair on the first quote. Asked again, 10 fell under fair (14.75x to 8.91x, 18.26x to 13.07x, 4.05x to 2.58x, 9.36x to 6.82x, ...) and 5 gave the same price, at +0.5% to +3.3%. So expect far fewer plays and far smaller EVs than before: the big numbers were first quotes.
- **Cost**: one or two more quotes for each slip above fair; a pass's plays appear 40 seconds or more after they are first priced.
- **Not known**: whether the first quote can be bet by someone who asks first on the slip (asking may be what moves it), and whether a slip quoted low at first would settle above fair (those are not asked again).

### Novig Scan: players who are out are left off
Max, 11-14: T.J. Hockenson headed the All tab at +15.9% five hours after he was ruled out; Novig still had his props open.

- The server reads ESPN's NFL and NBA injury reports (`site.api.espn.com/.../injuries`, every ten minutes while the page is open or Auto-scan is on; `nvOutRefresh`, `nvOut` in `server.js`). A row is left off every tab, and out of the five-minute top-plays re-pricing, when its player is listed Out, Injured Reserve, Suspension or Doubtful: the row's player, either player of a two-player slip, or a quarterback one of its legs names (matched on last name and team).
- Matching is by name. A row stays in the saved board and returns if the report changes. The status line counts them ("3 hidden, player out"). A full pass still asks Novig about them: this hides rows, it does not yet skip them in `scan.py`.
- Not covered: Questionable and game-time decisions (they stay), and college or soccer players (those boards have no player props).
- Checked against ESPN's live report with a stand-in board: Hockenson's row and a slip with an out quarterback's leg were hidden, a healthy player's row and a game-line row were not.

### Novig Scan: Auto-scan stays on through a redeploy
Every push to `main` redeploys the server, which switched Auto-scan off each time (its state was in memory). It is now written to `novig_cycle.json` beside the saved boards and read back at start, so it carries on after a restart, on the same Wide books setting and time zone, and still ends a week after it was switched on. This holds where that directory is a volume (`NBA_DATA_DIR` or `/data/nba`), the same condition as for the saved boards and bets. Checked: switched on, server killed and started again, it was still on and started a pass; switched off, restarted, it stayed off.

### Novig Scan: the top plays are re-priced every five minutes
Max, 11-14: by the time he looks at a top play its price is often well down. A full pass returns to a board only every half hour or more, so the best rows were the stalest where it matters most.

- While Auto-scan is on (and not paused for the night), every five minutes the eight best slips across all boards (EV above zero, game not started) are priced again, one after another, with the single-slip re-quote behind a row's refresh button (`nvTopTick`, `NV_TOP_N`, `NV_TOP_EVERY_MS` in `server.js`; the route's body is now `nvRequote`). It runs beside a full pass. A slip whose price dropped falls down the list and the next round takes the new top eight. A slip Novig no longer prices keeps its old row and Age.
- The status line says when the top eight were last re-priced. A press of a row's refresh button during a round waits for the gap between two slips instead of failing.
- Cost: about 100 more quotes an hour.
- Checked with a stand-in for `scan.py`: a round re-priced the eight best rows across two boards and left the rest; off stopped it. Not run against Novig from here.

## 2026-11-13 session

### Novig Scan: QK in dollars
A "QK $" column beside QK on every board (Max, 11-13): the quarter-Kelly stake at $500 a unit, to the dollar (0.84u is $420); a dash where QK is zero. `UNIT` in `public/nba_scan.html` sets the unit.

### Novig Scan: one line for a bet on a row, instead of two badges
Max, 11-13 (phone screenshot): a row he had bet showed the same amount twice, once after the tip time (the player's total) and once after the legs (this slip), crowding both lines. A bet row now has a green left edge and one line of its own under the numbers: "✓ You bet $200 at 6.23x" (each bet listed when there are several). A player's first row shows a grey line instead when the money is on another of his slips. Neither badge is drawn any more. "Hide my bets" hides the line and the edge. Checked in a phone-sized and a desktop browser with a stand-in board.

### Novig Scan: a typed stake saves when the keyboard is closed
Max, 11-13 (iPhone): typed a stake under "I bet this", pressed the keyboard's check mark, nothing saved. The check mark only closes the keyboard; it sends no Enter, and the row was then redrawn without the stake. Leaving the bet form with a stake above zero now saves it (moving between the stake and price boxes does not; Save and Enter save once, as before). Checked in a phone-sized browser: closing the keyboard saved one bet, Save saved one, Enter saved one, an empty stake saved nothing.

### Novig Scan: Auto-scan and an All tab
Max, 11-13: have it scan by itself, cycling NBA, NFL, CBB and CFB, with one tab for every board's good slips.

- **Auto-scan** (button on the scanner page; `nvCycleTick` in `server.js`): while on, the server runs whole-board passes of NBA, NBA Team (the board added today, under three minutes a pass), NFL, CBB, CFB and soccer in turn (every board but the two Ladders; Max, 11-13), with the page open or closed. Still one pass at a time; a pass started with Fetch runs first and the cycle carries on after it. A minute between passes, no board more often than every ten minutes, no pass starts between 10 PM and 8 AM (Max, 11-13; by the time zone of the browser that switched it on, `NV_CYCLE_QUIET`; a pass running at 10 finishes), and it switches itself off after a week (`NV_CYCLE_*`; it was 12 hours before the night pause, which would have ended it before a full day). It uses the Wide books setting it was switched on with. Switching it off stops the pass it started. A redeploy switches it off (the state is in memory).
- **All tab** (`?league=all&min=`): every board's rows at Min EV or better for games that haven't started, best first, each tagged with its board (the two Ladder boards included, from their last Fetch). The status line shows how old each board's last pass is; rows over an hour old are dimmed. The refresh button and "I bet this" work from the row. No Fetch, game picker or pair filter there.
- **Changed**: this is the first thing that quotes Novig without Fetch being pressed. It is off until switched on, and asks to confirm.
- **Checked** with a stand-in for `scan.py` (three rows a board): the cycle went NBA then NFL a minute later, the All tab listed both boards' rows above Min EV, off stopped it. Not run against Novig from here.

### NBA Team: the prop + spread correlations checked, and priced one standard error down
Max, 11-13: is the correlation on Wembanyama 28+ PTS with GSW +12.5 right (board +10.3%; DraftKings pays +232 on the 28.5 version)? Checked three ways, then every prop + spread r on the board.

- **A rolling line changes nothing.** Each leg re-measured as "over the median of his previous 15 games" instead of his season median: every role and spread band within noise of before (25-point scorers on a 10+ favourite: -0.27 both ways; 20-to-25 on a 10.5+ underdog: +0.47 both ways).
- **Held-out seasons.** The fit made on three seasons, tested on the fourth, each in turn: the share of slips where both legs hit.

| Slips (Over + the side the fit says) | Player-games | Hit | The fit said | Fit less 1 SE | Unrelated legs |
|---|---|---|---|---|---|
| Fitted r 0.42+ | 3,113 | 30.5% | 31.5% | 30.3% | 23.6% |
| 0.30 to 0.42 | 8,243 | 29.7% | 29.8% | 28.8% | 24.2% |
| 0.15 to 0.30 | 79,864 | 28.0% | 27.9% | 27.3% | 24.8% |
| Against his own team covering (r -0.15 or lower) | 1,692 | 27.9% | 28.0% | 26.6% | 24.4% |

- **So the star-on-a-big-favourite r is real**, not half as I had guessed from DraftKings' price: at 11 to 14 points those slips hit 28.8% (unrelated 24.2%), beyond 14 27.4% (20.3%). But at 8 to 11 points they hit 26.9% against 26.6% unrelated: nothing there, and the straight-line fit said 29.7%.
- **Three changes** (`scan.py`):
  1. Every prop + line fair value uses the fitted r less one standard error of the fit at that spread (`nba_prop_r`; the file now carries `x0` and `a_se`). That matches the top group on held-out seasons and is 2.5% to 5% conservative in the others. Wembanyama at -12.5: -0.26 fitted, -0.19 used; a 22-point scorer at +12.5: +0.51 fitted, +0.44 used. The open row shows both.
  2. A prop against his own team covering is asked only on a favourite of 11 or more.
  3. A player's role comes from his line and its price, not the line alone (`nba_role`): a 2.5 threes line at +150 is a 2.3-a-game shooter (r +0.16 with an 8.5-point underdog covering), not a 2.9 one (+0.27). 26 of 83 players' threes, 11 of 96 rebounds and 9 of 84 assists were in the wrong role; points and PRA are unchanged.
- **Tonight's quotes at the new numbers**: fitted r 0.42+, 33 of 42 above fair, median +2.0% (was 35 of 38, +4.8%); a star against his own team covering on a favourite of 11+, 5 of 6, median +5.3%; 0.30 to 0.42, 8 of 45, median -4.0%; with the first-half spread, 3 of 16, median -3.6%. So the board now asks from 0.42 (`--line-r`) and the full-game spread only (`--team-lines cover h1cover` brings the first half back): about a third as many prop slips. The Wembanyama row goes from +10.3% to about +5.7%.
- Not settled: DraftKings and Fanatics price that pairing near unrelated, and their SGP margin is a guess on my part (10% to 20%), so their own r is somewhere from 0 to +0.10 where the history says 0.19 to 0.26. Wembanyama's own games as a favourite of 8+ (33) lean the same way but are too few to count.

### Novig Scan: NBA Team tab (a prop with the spread, and a game's own lines)
Max, 11-13: the Points + Threes edge looks gone; expand NBA to team props. A new board, **NBA Team**, on the scanner page (`scan.py --league nba --kind team`; `nbateam` in `server.js`).

- **What was tested first** (nine games, about 700 quotes):

| Kind of slip | Quotes | Median EV | Above fair | At +3% or better |
|---|---|---|---|---|
| Game lines only (33 shapes, three games) | 99 | -5% to -12% by shape | 4 | 1 |
| Prop + his team's total | 206 | -6.4% | 11 | 0 |
| Prop + game total | 18 | -4.6% | 0 | 0 |
| Prop + the other team's total | 10 | -3.8% | 1 | 0 |
| Prop + spread, r 0.42 or better | 38 | **+4.8%** | **35** | 26 |
| Prop + spread, r 0.30 to 0.42 | 68 | about -1% | 29 | 13 |
| Prop + spread, r under 0.30 | 54 | about -4% | 12 | 9 |

- **Team props alone are priced right.** Novig's quote before its fee sits on the measured correlation (favourite covers + his team total Over: 0.62 quoted, 0.58 measured; team total Over + game Over: 0.77 against 0.84; spread + total: 0.03 against 0.02), so the 10% fee puts them about 5% under fair. The same with a player's prop and a team total or game total.
- **A prop with the spread is the exception**, because the true correlation turns on who is favoured and Novig's barely does. A 20-to-25-point scorer's Over with his team covering: +0.46 as an underdog of 6.5 to 10.5 (807 player-games), +0.21 in a close game, -0.13 as a favourite of 10+ (the starters sit the fourth quarter of a blowout). A 25-point scorer on a 10+ favourite: -0.27 (627 player-games). Novig quoted Wembanyama's points with San Antonio -12.5 at -0.10 where the data says -0.26, and Lendeborg's with Golden State +12.5 at +0.16 where it says +0.5. The plays are a main scorer's Over with his underdog team covering (or his Under with the favourite covering), and a star's Under with his big-favourite team covering (or his Over with the underdog covering). They repeated on a second pass 15 minutes later: Lendeborg +12.7% then +11.6%, Acuff +11.2% then +10.5%, Wembanyama +15.2% then +9.4%, Siakam +5.8% then +6.5%.
- **The board asks**: each player's three strongest pairings of a main-line prop (points, rebounds, assists, threes, points + rebounds + assists) with the spread or first-half spread, Over and Under, where |r| is 0.30 or better (`--line-r`; 0.15 where the prop goes against his own team covering, the star on a big favourite); players at 20+ minutes a game only (a bench player's numbers go the other way in a blowout: Novig priced Collier's PRA with Utah +15.5 as moving apart). Then six slips across each game's own lines, the ones nearest fair of the 33: both team totals Over, both Under, the favourite's team total with the game total (Over, Under), the underdog's moneyline + Under, the favourite's first-half moneyline + his moneyline. About 140 slips on a nine-game night, under three minutes; the game picker narrows it. `--team-lines tt opp_tt over h1over` adds the lines that did not pay.
- **Data** (`scripts/nba_line_correlations.py`; daily refresh step added): `public/data/nba_game_lines.json`, 4,115 finals of 2023-24 to now with quarter scores and DraftKings' closing spread and total from ESPN; `public/data/nba_game_boxes.json`, every player's line in those games; `public/data/nba_line_correlations.json`, 46 game-line shapes by size of spread (copula r, as the CBB file), and for each prop and role (his average of the stat) its r with six game lines in seven bands of his team's spread plus a straight-line fit, which the board reads at tonight's spread. A player's line isn't in any feed, so the leg is "over his own median that season" (745 player-seasons of 20+ games at 20+ minutes). Team totals and first-half lines are derived from the closing spread and total (first half: 0.600 x the spread, 0.502 x the total).
- **Team-total legs** take Novig's own book where it is inside 4c and Pinnacle's no-vig price on the same line where it is not (`pinnacle.lines("NBA")`; most NBA team-total books on Novig are 4c to 6c wide). Novig also lists points + rebounds + assists (`novig.EXTRA_TYPES`).
- **Watch for**: the underdog's moneyline + Under came back +34% and +40% on two games (Novig quoting well under the unrelated price) and at -2% for the same legs on the other pass. Those are one pricer's quote, not a correlation; re-check on the slip. The prop + spread r is a league-wide role number, not the player's own, and the underdog bands for 25-point scorers are thin (211 to 337 player-games), so the fit is held to the spreads it was measured on.
- Checked: `scan.py --kind team` end to end on tonight's slate twice (345 and 161 slips priced, no refusals: Novig takes every pairing); the page in a browser (below).
### Novig Scan: CFB team-total and first-half slips
The CFB board asked five slips a game in two families (underdog moneyline + Under, spread + total) and left Novig's team-total and first-half books unused (Max, 11-13: "not many CFB markets").

- **Five more shapes a game**, ten at most (`LINE_BOARDS["cfb"]["own"]` in `scan.py`): the underdog's spread + his team total Under, the favourite's team total Under + Under, both team totals Under, the favourite's first-half spread + his spread, the first-half Under + Under. The first four are the CBB board's shapes; the first-half total is new (`TOTAL_1H`).
- **Fair value**: every leg is Novig's own book, 4c wide or less, not Pinnacle (the CBB board uses Pinnacle because Novig's college basketball team-total books are wide; in football they are tight). Correlations are the same per-game model: first half with full game 0.71, a team total with the game total about 0.75, underdog covering with his own total Under about -0.65. Modelled, not measured on college football results.
- **Size**: 560 slips on 61 games tonight (was about 290), so a full Saturday scan is about ten minutes. Of 134 open games, about half have only a tight moneyline and are skipped.
- **Page**: two more CFB filters, "With a team total" and "First half + game".
- **Checked**: a 30-quote pass priced every new shape. The new ones came back -2.9% to -7.5% (the three above fair were all underdog moneyline slips), in line with the 11-13 test that left them out: expect more rows, few above fair.

### NBA Ladder: DraftKings no longer asked
The DraftKings pull for NBA never worked (Max, 11-13), so `books.py` no longer tries it: NBA shifted legs (the Ladder tab and `price.py`) are capped by Novig's ask and FanDuel's one-way price only. The Ladder tab's red "DraftKings prices did not load" note is gone with it; it still warns when FanDuel fails. NFL Ladder is unchanged and still asks both books.

### Novig Scan: NHL and NHL Lines tabs hidden
The two NHL buttons are hidden on the scanner page (Max, 11-13); a browser that last had one open lands on NBA. The boards, the script's `--league nhl` and the NHL Correlations page are untouched: remove `hidden` from the two buttons in `public/nba_scan.html` to bring them back.

- **Why**: about 800 test slips on NYR @ VAN and NSH @ VGK (11-13), fair values from two seasons of game logs and scores. 435 two-leg slips across every pairing Novig lists (same skater, teammates, opponents, props with each game line, lines with each other, Overs and Unders): none above fair, best -5%, typically -12% to -25%. 306 three-leg slips: one above fair (+16.7%, a skater's no goal + his team's total Under + the other team -1.5), which did not repeat on about 65 more slips of that shape (-13% to -25%).
- Novig charges correlation on every NHL pairing, including unrelated ones (two opposing skaters' props: measured 0.00, priced about -15%), and prices real ones above the measured r (a point with his team's moneyline: 0.36 measured, about 0.64 charged).

### Novig Scan: CBB big underdogs no longer float to the top
Max, 11-13: the plays were all large spreads with the underdog's own total Under. The 20+ spread band had its own r for that shape, -0.55 on 1,271 games, where every other band is -0.61 to -0.62. That gap is inside the band's noise (two-sigma range -0.65 to -0.43; spreads of 30+ alone read -0.65; by season -0.50, -0.56, -0.57), and it made a big underdog's slip look about 6% better than a small one's at the same prices. A spread band's r is now used only when the all-games r is outside the band's two-sigma range; otherwise the all-games r. On today's file that leaves one band on its own number: spread + total at 20+ points (+0.14 against -0.04).

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
