#!/usr/bin/env node
/* Phase 3 EV-formula verification: p_joint vs 1/decimal(FV_CORR).
 *
 * The user's spec + the MLB bug context disagree about whether EV% at
 * the top of a card should be computed from model_joint (= p_joint from
 * the correlation xlsx Empirical_Prob column) or from the FV-derived
 * joint. MLB had a bug where EV used aggregates-derived joint; the fix
 * made EV use FV-derived joint with MODEL JOINT kept as a diagnostic.
 *
 * This harness constructs a candidate where the two quantities are
 * meaningfully different, runs it through the real buildCandidate, and
 * prints what EV% the renderer would display. Expected outcomes:
 *
 *   EV displayed ≈ +20.0%  →  bug present (EV uses p_joint)
 *   EV displayed ≈ −25.0%  →  fix in place (EV uses fv_corr_prob)
 *
 * Fixture (per user's verification spec):
 *   Leg 1 FV implied over 53.8%     (fv_american ≈ -116)
 *   Leg 2 FV implied over 52.7%     (fv_american ≈ -112)
 *   r_adj tuned so jointFromPhi → fv_corr_prob ≈ 0.25
 *   p_joint (entry) = 0.40
 *   dk_sgp_american = +200
 *
 * Run:
 *   NODE_PATH=/tmp/node_modules node scripts/nba_ev_formula_check.js
 */

const fs = require('fs');
const path = require('path');

/* Load the module in a stub-DOM global context so the IIFE runs without
   jsdom's paint cycle overhead. We only need the _math helpers. */
global.window = { addEventListener: () => {}, location: { href: 'file:///', search: '' } };
global.document = {
  addEventListener: () => {}, getElementById: () => null,
  querySelectorAll: () => ({ forEach: () => {} }), querySelector: () => null,
};
global.fetch = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
global.FormData = class {};
// eslint-disable-next-line no-eval
eval(fs.readFileSync(path.join(__dirname, '..', 'public', 'utils', 'nbaEvTab.js'), 'utf8'));

const nba = global.window.nbaTab._math;

/* Tune r_adj so fv_corr_prob comes out close to the user's +300 spec.
   jointFromPhi(r, 0.537, 0.528) = 0.25 →
     r × sqrt(0.537·0.463·0.528·0.472) = 0.25 − 0.537·0.528
     r × 0.249 = −0.0335
     r ≈ −0.135 */
const fixtureEntry = {
  player: 'Bug Check',
  leg1: { prop: 'Points', side: 'over', line: 24.5 },
  leg2: { prop: 'Rebounds', side: 'over', line: 4.5 },
  r_adj: -0.135,
  p_value: 0.05,
  n_games: 50,
  hit_rate_1: 0.537,
  hit_rate_2: 0.528,
  p_joint: 0.40,
  p_independent: 0.283,
  type: 'Same Player',
  dk_sgp_american: 200,  // +200 American = 3.00 decimal → implied 33.3%
};

const fvIndex = {
  'Bug Check': {
    player: 'Bug Check', team: 'BUG', game: 'BUG vs CHK',
    props: {
      'Points':   { 24.5: { stat: 'Points',   threshold: 24.5, over_fv: -116, under_fv: +106, over_dk_american: -150, under_dk_american: +130 } },
      'Rebounds': { 4.5:  { stat: 'Rebounds', threshold: 4.5,  over_fv: -112, under_fv: +102, over_dk_american: -120, under_dk_american: +100 } },
    },
  },
};

const correlations = { entries: [fixtureEntry], by_player: { 'Bug Check': [0] } };
const filters = {
  minEvPct: -100, minGames: 0, maxPValue: 1,
  props: { 'Points': true, 'Rebounds': true, 'Assists': true, '3-Pointers Made': true },
  confirmedOnly: false,
};

const cands = nba.enumerateCandidates(correlations, fvIndex, filters, null);
if (!cands.length) {
  console.error('FAIL: no candidate produced by enumerator');
  process.exit(1);
}
const c = cands[0];

const fmt = n => (n == null ? '(null)' : (n >= 0 ? '+' : '') + (n * 100).toFixed(1) + '%');
console.log('--- Bug-check fixture ---');
console.log('  p_joint (model):          ', (c.model_joint * 100).toFixed(1) + '%');
console.log('  fv_corr_prob (FV-derived):', (c.fv_corr_prob * 100).toFixed(1) + '%');
console.log('  fv_corr_american:         ', (c.fv_corr_american >= 0 ? '+' : '') + c.fv_corr_american);
console.log('  dk_sgp_decimal:           ', c.dk_sgp_decimal.toFixed(2));
console.log('  dk_implied:               ', (c.dk_implied * 100).toFixed(1) + '%');
console.log('');
console.log('--- What each formula WOULD produce ---');
const evFromPJoint = c.model_joint * c.dk_sgp_decimal - 1;
const evFromFvCorr = c.fv_corr_prob * c.dk_sgp_decimal - 1;
console.log('  EV if formula uses p_joint:       ', fmt(evFromPJoint), '(buggy per MLB context)');
console.log('  EV if formula uses fv_corr_prob:  ', fmt(evFromFvCorr), '(correct per MLB fix)');
console.log('');
console.log('--- Actually rendered by nbaEvTab buildCandidate ---');
console.log('  c.ev_pct =', fmt(c.ev_pct));
console.log('');
console.log('VERDICT:',
  Math.abs(c.ev_pct - evFromPJoint) < 1e-9 ? 'BUG PRESENT — EV uses p_joint' :
  Math.abs(c.ev_pct - evFromFvCorr) < 1e-9 ? 'CORRECT — EV uses fv_corr_prob' :
  'UNEXPECTED — c.ev_pct matches neither candidate formula'
);
