# Tomorrow's smoke test

Run through this once tomorrow's slate loads. Stop and investigate at the first step that doesn't match the expected output.

## Regression guards (run any time the NBA EV pipeline is touched)

These two standalone scripts are load-bearing. Do NOT delete them. They
exist because past bugs are cheaper to catch at commit time than after a
deploy.

```bash
# Verify buildCandidate uses fv_corr_prob for EV% (not p_joint).
# Fixed in a5b5442. Expected final line: "VERDICT: CORRECT — EV uses fv_corr_prob"
node scripts/nba_ev_formula_check.js

# Verify null-EV candidates sort/filter/paginate correctly. Locked in
# by Phase 3 rider 1. Expected final line: "ALL NULL-EV GUARDS PASS"
node scripts/nba_null_ev_sort_check.js
```

Neither needs jsdom or a running server — both eval the NBA module in a
stub-DOM context and exercise the pure math/sort/filter paths.

## 0. Boot

```bash
npm install            # only if not already done
npm start              # node server.js on :3000 (or $PORT)
```

Open `http://localhost:3000/` (or your deployed URL).

## 1. Upload + OCR

- Drag-and-drop or paste a fresh FV sheet screenshot onto the +EV Finder.
- Open DevTools → Network tab **before** the fetch fires.

### Verify `/api/extract` response

- Expand the response body. Every `rows[]` entry should include a `books_count` field (integer, usually 2–10).
- If any row is missing `books_count` or has it as `null`: the Vision prompt is dropping the field on that row. Note which rows; the collapse will fall back to L-only tiebreak for those pitchers, still correct but less robust.

## 2. Blocking-visible dedup check (no DEBUG needed)

- Find a pitcher with a known duplicate row pair in the sheet — e.g. any pitcher whose ER line or Outs line appears on two L values.
- Before the fix: that pitcher's SGP cards for the duplicated combo showed up 2× or 4×.
- After the fix: should show exactly 1 card per unique `(leg1, leg2)` combo.
- **Wacha-style test**: if your sheet has a pitcher with 2 ER rows × 2 Outs rows, they should collapse to 1 card, not 4.

## 3. Turn on DEBUG for the collapse log

Edit `public/index.html` line 237:
```js
var DEBUG=false;  →  var DEBUG=true;
```

For the server-side `[collapse]` log, relaunch with `DEBUG=true npm start`.

Reload the page, re-upload the sheet. In the server console, expect lines like:
```
[collapse] Michael Wacha|Over 2.5 Earned Runs — 2 rows → winner L=7 books=5 avg_fv=129; dropped: L=19 books=3 avg_fv=153
```

- No `[collapse]` output on a sheet with no duplicates is fine — means your sheet is clean.
- Any `[collapse]` line with a losing row whose `books_count` equals the winner's → tiebreak fell through to L (newer row won). That's the intended fallback.

## 4. Leg ordering consistency

Pick any 2-leg SGP card. Reload the page. The leg order should be stable across reloads (e.g. always "Over 2.5 ER × Over 17.5 Outs", never flipped to "Outs × ER"). Alphabetical stat category: BB < ER < H < OUTS < SO.

## 5. Top-5 EV sanity check

- With mode toggle on `BLENDED`:
  - A veteran with `n_eff ≥ 20` (check the pitcher page's "STARTS · EFF N" display) should show an EV that lands between their PLAYER and GLOBAL toggle values.
  - A pitcher with `n_eff < 5` should show `(blended → global)` on the EV card label and a tooltip saying `0% player / 100% global`.
- Click the three-mode toggle and verify the EV numbers change as expected: PLAYER uses raw pitcher r, GLOBAL uses league baseline, BLENDED sits between for medium-sample pitchers.

## 6. Close out

Flip `DEBUG` back to `false` in `public/index.html`. If you relaunched the server with `DEBUG=true`, restart it plain (`npm start`).

```bash
git diff public/index.html     # confirm DEBUG is back to false
git add -p                     # if you want to commit the flip, or nothing if it was never true
```

Commit only if DEBUG was left true or if you want to land an intentional change.

## Known-unverified going into tomorrow

- The Outs-side duplication root cause (sheet vs OCR). Irrelevant to the fix — it collapses either case — but worth noting if the collapse log shows OCR rows whose L values don't appear in the sheet.
- `books_count` consistency across Vision runs. If the OCR occasionally returns `0` or drops the field, watch for collapse winners that don't match your gut call.
- Live browser interaction with year-blended EV math on real DK prices (wasn't available during the refactor because slate was locked).
