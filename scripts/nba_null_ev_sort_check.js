#!/usr/bin/env node
/* Null-EV sort + filter + pagination regression check.
 *
 * DO NOT DELETE — locked in by Phase 3 rider 1 after the a5b5442 fix.
 *
 * When fv_corr_prob is null (missing r_adj, degenerate FV marginals),
 * buildCandidate now emits ev_pct = null. This guard verifies the three
 * downstream paths handle that correctly without crashing:
 *
 *   1. sortCandidates: null EVs sort to the bottom (treated as -Infinity)
 *   2. applyEvFilter:  null EVs are excluded at any MIN EV% setting —
 *      missing FV doesn't silently count as "clears threshold"
 *   3. Pagination:     null EVs never occupy top-30 ahead of real ±EV
 *
 * Fixture: three candidates — +5%, -2%, null.
 *
 * Run:
 *   node scripts/nba_null_ev_sort_check.js
 */

const fs = require('fs');
const path = require('path');

global.window = { addEventListener: () => {}, location: { href: 'file:///', search: '' } };
global.document = {
  addEventListener: () => {}, getElementById: () => null,
  querySelectorAll: () => ({ forEach: () => {} }), querySelector: () => null,
};
global.fetch = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
global.FormData = class {};
eval(fs.readFileSync(path.join(__dirname, '..', 'public', 'utils', 'nbaEvTab.js'), 'utf8'));

const nba = global.window.nbaTab;

/* Three hand-built candidates. Skip enumerateCandidates — we're testing
   the post-enumerator paths. Entry stub only carries p_value for the
   sort tiebreak, which is orthogonal to the null-EV behavior. */
const cands = [
  { id: 'pos5', player: 'P5',  ev_pct:  0.05, entry: { p_value: 0.04, n_games: 50 } },
  { id: 'neg2', player: 'N2',  ev_pct: -0.02, entry: { p_value: 0.06, n_games: 50 } },
  { id: 'null', player: 'NUL', ev_pct:  null, entry: { p_value: 0.05, n_games: 50 } },
];

const sorted = nba._sortCandidates(cands);
console.log('sort(desc):', sorted.map(c => c.id + ' ev=' + (c.ev_pct == null ? 'null' : (c.ev_pct * 100).toFixed(1) + '%')).join(' | '));

function check(label, arr, wantIds) {
  const gotIds = arr.map(c => c.id).join(',');
  const ok = gotIds === wantIds.join(',');
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + label + '  → ' + (gotIds || '(empty)') + (ok ? '' : '   want ' + wantIds.join(',')));
  if (!ok) process.exitCode = 1;
}

check('sort order (ev desc, nulls last)', sorted, ['pos5', 'neg2', 'null']);
check('filter MIN EV% = +3 (only +5% passes)', nba._math.applyEvFilter(cands, 3), ['pos5']);
check('filter MIN EV% = -5 (pos5, neg2; null excluded)', nba._math.applyEvFilter(cands, -5), ['pos5', 'neg2']);
check('filter MIN EV% = -100 (null still excluded)', nba._math.applyEvFilter(cands, -100), ['pos5', 'neg2']);

/* Pagination is deterministic: slice(0, pageShown) over the sorted+
   filtered list. With two candidates passing filter, page 1 (30) shows
   both in EV-desc order and the null card never appears. */
const filtered = nba._math.applyEvFilter(cands, -100);
const page = nba._sortCandidates(filtered).slice(0, 30);
check('pagination: null never in top-30', page, ['pos5', 'neg2']);

if (!process.exitCode) console.log('\nALL NULL-EV GUARDS PASS');
