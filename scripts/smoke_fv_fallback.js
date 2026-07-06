#!/usr/bin/env node
/* FV-only fallback ("screenshot mode") smoke check.
 *
 * When DK's calculateBets pricing is unreachable (Akamai 403 storm, DK
 * outage, network failure) the pitcher +EV finder now computes each
 * combo's correlated fair value straight from the screenshot's per-leg
 * FVs and renders FV-only cards sorted by fair-value odds low → high.
 * This guard covers the Node-testable pieces of that path:
 *
 *   1. fvFallback.enumerate: groups OCR rows by pitcher, emits only
 *      legal same-pitcher combos, never cross-pitcher
 *   2. fvFallback.isLegalCombo: distinct-stat combos always legal (both
 *      directions — combo_spec only enumerates the Over-K-side legs, but
 *      the screenshots carry both sides); same-stat combos only when
 *      verbatim whitelisted, so contradictory Over × Under of the same
 *      leg is rejected while spec ladders pass
 *   3. sgpMath-based FV compute with dkDecimal=null: joint prob and FV
 *      odds are produced; EV/Kelly stay null (no DK price to beat)
 *   4. fvFallback.sortByFvOddsAscending: ascending American FV odds ==
 *      descending joint probability, favorites first
 *
 * Fixture: the 2026-07-06 NYY@TB sheet legs (Cam Schlittler / Griffin
 * Jax) that motivated the feature.
 *
 * Run:
 *   node scripts/smoke_fv_fallback.js
 */

const fs = require('fs');
const path = require('path');

const fvFallback = require(path.join(__dirname, '..', 'public', 'utils', 'fvFallback.js'));
const sgpMath = require(path.join(__dirname, '..', 'public', 'utils', 'sgpMath.js'));
const spec = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'combo_spec.json'), 'utf8'));

let failures = 0;
function check(name, cond, detail) {
  if (cond) { console.log('  ✓ ' + name); }
  else { failures++; console.error('  ✗ ' + name + (detail ? ' — ' + detail : '')); }
}

/* OCR-shaped rows from the 07/06 screenshot (subset, avg_fv per leg). */
const rows = [
  { pitcher: 'Cam Schlittler', leg: 'Under 4.5 Hits Allowed',  avg_fv: 134 },
  { pitcher: 'Cam Schlittler', leg: 'Over 1.5 Walks',          avg_fv: 117 },
  { pitcher: 'Cam Schlittler', leg: 'Over 5.5 Strikeouts',     avg_fv: -126 },
  { pitcher: 'Cam Schlittler', leg: 'Under 5.5 Strikeouts',    avg_fv: 130 },
  { pitcher: 'Griffin Jax',    leg: 'Under 5.5 Strikeouts',    avg_fv: -111 },
  { pitcher: 'Griffin Jax',    leg: 'Over 4.5 Hits Allowed',   avg_fv: 135 },
  { pitcher: 'Griffin Jax',    leg: 'Under 1.5 Earned Runs',   avg_fv: 128 },
];

console.log('1. legality semantics');
const sets = fvFallback.buildSpecSets(spec);
check('pairs_2 map built', !!sets[2] && Object.keys(sets[2]).length === spec.pairs_2.length);
check('triples_3 map built', !!sets[3] && Object.keys(sets[3]).length === spec.triples_3.length);
check('known pair whitelisted (order-insensitive)',
  fvFallback.isWhitelisted(sets, 2, ['Under 1.5 Earned Runs', 'Over 4.5 Strikeouts']) === true &&
  fvFallback.isWhitelisted(sets, 2, ['Over 4.5 Strikeouts', 'Under 1.5 Earned Runs']) === true);
check('null when whitelist missing', fvFallback.isWhitelisted({ 2: null }, 2, ['a', 'b']) === null);
check('cross-stat legal even off-spec (bad-outing side)',
  fvFallback.isLegalCombo(sets, 2, ['Under 5.5 Strikeouts', 'Over 4.5 Hits Allowed']) === true);
check('contradictory Over/Under same leg ILLEGAL',
  fvFallback.isLegalCombo(sets, 2, ['Over 5.5 Strikeouts', 'Under 5.5 Strikeouts']) === false);
check('same-stat spec ladder legal',
  fvFallback.isLegalCombo(sets, 2, ['Over 4.5 Strikeouts', 'Over 5.5 Strikeouts']) === true);
check('same-stat unlisted shape illegal',
  fvFallback.isLegalCombo(sets, 2, ['Under 4.5 Strikeouts', 'Under 5.5 Strikeouts']) === false);
check('same-stat with spec missing → conservative reject, cross-stat still legal',
  fvFallback.isLegalCombo({ 2: null, 3: null }, 2, ['Over 4.5 Strikeouts', 'Over 5.5 Strikeouts']) === false &&
  fvFallback.isLegalCombo({ 2: null, 3: null }, 2, ['Over 4.5 Strikeouts', 'Under 1.5 Earned Runs']) === true);

console.log('2. enumeration');
const validFn = (legs) => fvFallback.isLegalCombo(sets, 2, legs);
const combos = fvFallback.enumerate(rows, 2, validFn, fvFallback.statCatOf);
check('emits combos', combos.length > 0, 'got ' + combos.length);
check('same-pitcher only', combos.every(c => c.rows.every(r => r.pitcher === c.pitcher)));
check('no contradictory K Over/Under pair', !combos.some(c => {
  const legs = c.rows.map(r => r.leg).sort();
  return legs[0] === 'Over 5.5 Strikeouts' && legs[1] === 'Under 5.5 Strikeouts';
}));
check('every emitted combo is legal', combos.every(c => validFn(c.rows.map(r => r.leg))));
const jaxCombos = combos.filter(c => c.pitcher === 'Griffin Jax');
check('Jax H×ER / K×H / K×ER pairs present (3 legs, 3 distinct stats)', jaxCombos.length === 3,
  'got ' + jaxCombos.length);
/* Schlittler: H, BB, K-over, K-under → C(4,2)=6 minus the contradictory
   K-over×K-under pair = 5 legal. */
const schlCombos = combos.filter(c => c.pitcher === 'Cam Schlittler');
check('Schlittler 5 of 6 pairs legal (contradiction dropped)', schlCombos.length === 5,
  'got ' + schlCombos.length);

console.log('3. FV compute with no DK price (mirrors evComputeCombo dkDecimal=null)');
/* Global-correlation stand-in: r=0.20 for every pair — the smoke test
   validates the null-DK contract, not the correlation resolution (which
   needs the browser-loaded aggregates). */
function computeFV(combo, r) {
  const legs = combo.rows.map(m => ({ leg: m.leg, fv: m.avg_fv, p: sgpMath.americanToProb(m.avg_fv) }));
  if (legs.some(l => l.p === null)) return null;
  let logIndep = 0; legs.forEach(x => { logIndep += Math.log(x.p); });
  let corrSum = 0;
  for (let i = 0; i < legs.length; i++) for (let j = i + 1; j < legs.length; j++) {
    const pab = Math.max(1e-6, Math.min(0.999999, sgpMath.jointFrechet(legs[i].p, legs[j].p, r)));
    corrSum += Math.log(pab) - Math.log(legs[i].p * legs[j].p);
  }
  const pJoint = Math.max(1e-6, Math.min(0.999999, Math.exp(logIndep + corrSum)));
  const dkDecimal = null;
  const hasDK = (dkDecimal != null && isFinite(dkDecimal) && dkDecimal > 1);
  return {
    pJoint,
    fvCorrOdds: sgpMath.probToAmerican(pJoint),
    evPct: hasDK ? (pJoint * dkDecimal - 1) * 100 : null,
    kellyPct: hasDK ? 0 : null,
  };
}
const withCalc = combos.map(c => Object.assign({ calc: computeFV(c, 0.20) }, c)).filter(c => c.calc);
check('all combos computed', withCalc.length === combos.length);
check('FV odds produced', withCalc.every(c => Number.isFinite(c.calc.fvCorrOdds)));
check('EV null without DK price', withCalc.every(c => c.calc.evPct === null && c.calc.kellyPct === null));
check('joint prob in (0,1)', withCalc.every(c => c.calc.pJoint > 0 && c.calc.pJoint < 1));

console.log('4. sort: low odds → high odds');
const sorted = fvFallback.sortByFvOddsAscending(withCalc, c => c.calc.pJoint);
check('probabilities descending', sorted.every((c, i) =>
  i === 0 || sorted[i - 1].calc.pJoint >= c.calc.pJoint));
/* American odds comparison needs the favorite-ordering, not raw numeric:
   -120 (p=.545) comes before +110 (p=.476); among negatives, more-negative
   first; among positives, smaller first. Verify via implied probability. */
check('American FV odds ascending (favorites first)', sorted.every((c, i) =>
  i === 0 || sgpMath.americanToProb(sorted[i - 1].calc.fvCorrOdds) >= sgpMath.americanToProb(c.calc.fvCorrOdds) - 1e-9));
check('sort is non-mutating', fvFallback.sortByFvOddsAscending(withCalc, c => c.calc.pJoint) !== withCalc);

console.log(failures ? '\nFAILED: ' + failures + ' check(s)' : '\nAll FV-fallback smoke checks passed.');
process.exit(failures ? 1 : 0);
