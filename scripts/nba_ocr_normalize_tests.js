#!/usr/bin/env node
/* NBA OCR normalization synthetic test suite.
 *
 * DO NOT DELETE — regression guard for NBA OCR normalizer + grouper.
 *
 * Covers matchNbaMarket, normalizeNbaRows, and groupNbaPlayers against
 * synthetic row fixtures that mirror what /api/extract-nba would get
 * back from Claude Vision. No live Vision call — exercises only the
 * pure transforms. Phase 4 Edit 4 per the NBA build plan.
 *
 * Runs without jsdom, a server, or npm test:
 *   node scripts/nba_ocr_normalize_tests.js
 *
 * Exit 0 = all pass, 1 = at least one fail.
 *
 * If any test fails after a prompt/normalizer edit, investigate before
 * shipping — the normalizer is what stands between a raw Vision
 * response and the candidate enumerator in nbaEvTab.js.
 */

const fs = require('fs');
const path = require('path');

/* Pull the pure functions out of server.js by slicing between markers.
   Same pattern nba_ev_formula_check.js uses to eval nbaEvTab.js without
   a full DOM. Fragile only if someone moves the NBA OCR block — keep
   the === NBA FV sheet OCR === marker intact if you refactor server.js. */
const src = fs.readFileSync(path.join(__dirname, '..', 'server.js'), 'utf8');

function slice(fromMarker, toMarker) {
  const i = src.indexOf(fromMarker);
  const j = src.indexOf(toMarker, i + fromMarker.length);
  if (i < 0 || j < 0) throw new Error('slice markers missing: ' + fromMarker + ' ... ' + toMarker);
  return src.slice(i, j);
}

/* Block 1: parseBetNameDirection + canonDirection (shared helpers used
   by normalizeNbaRows for the bet_name → direction+line fallback). */
const helpersSrc = slice('function parseBetNameDirection', 'function normalizeLeg');

/* Block 2: NBA-specific pure functions, all grouped under the same
   header comment in server.js. */
const nbaSrc = slice('/* NBA canonical prop vocabulary', 'app.post(\'/api/extract-nba');

// eslint-disable-next-line no-eval
eval(helpersSrc + '\n' + nbaSrc);

let passes = 0, failures = 0;
function check(label, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { passes++; console.log('PASS  ' + label); return; }
  failures++;
  console.log('FAIL  ' + label);
  console.log('      got : ' + g);
  console.log('      want: ' + w);
}
function checkTruthy(label, got) {
  if (got) { passes++; console.log('PASS  ' + label); return; }
  failures++;
  console.log('FAIL  ' + label + '  (got falsy: ' + got + ')');
}

/* --- matchNbaMarket --- */
check('market: Player Points',       matchNbaMarket('Player Points'),            { stat: 'Points', supported: true });
check('market: Player Rebounds',     matchNbaMarket('Player Rebounds'),          { stat: 'Rebounds', supported: true });
check('market: Player Assists',      matchNbaMarket('Player Assists'),           { stat: 'Assists', supported: true });
check('market: 3-Pointers Made',     matchNbaMarket('Player 3-Pointers Made'),   { stat: '3-Pointers Made', supported: true });
check('market: 3-Pt Made',           matchNbaMarket('Player 3-Pt Made'),         { stat: '3-Pointers Made', supported: true });
check('market: Threes Made',         matchNbaMarket('Player Threes Made'),       { stat: '3-Pointers Made', supported: true });
check('market: Steals',              matchNbaMarket('Player Steals'),            { stat: 'Steals', supported: false });
check('market: PRA combo',           matchNbaMarket('Player Points + Rebounds + Assists'), { stat: 'PRA', supported: false });
check('market: PR combo',            matchNbaMarket('Player Points + Rebounds'), { stat: 'PR', supported: false });
check('market: Double-Double',       matchNbaMarket('Player Double-Double'),     { stat: 'Double-Double', supported: false });
check('market: unknown returns null', matchNbaMarket('Player Total Bases'),      null);

/* --- normalizeNbaRows: supported, unsupported, schema-drift, dedup --- */
const raw = [
  { L: 1, player: 'Donovan Mitchell', team: 'CLE', game: 'CLE@BOS', market: 'Player Points', bet_name: 'Donovan Mitchell Over 27.5', direction: 'Over', line: 27.5, avg_odds: '+135 / -170', avg_fv: 120, books_count: 7 },
  { L: 2, player: 'Donovan Mitchell', team: 'CLE', game: 'CLE@BOS', market: 'Player Points', bet_name: 'Donovan Mitchell Under 27.5', direction: 'Under', line: 27.5, avg_odds: '+135 / -170', avg_fv: -150, books_count: 7 },
  { L: 3, player: 'Donovan Mitchell', team: 'CLE', game: 'CLE@BOS', market: 'Player Rebounds', bet_name: 'Donovan Mitchell Over 4.5', direction: 'Over', line: 4.5, avg_odds: '-145 / +125', avg_fv: -140, books_count: 5 },
  { L: 4, player: 'Jayson Tatum', team: 'BOS', game: 'CLE@BOS', market: 'Player Steals', bet_name: 'Jayson Tatum Over 1.5', direction: 'Over', line: 1.5, avg_odds: '+110 / -130', avg_fv: 108, books_count: 4 },  // unsupported
  { L: 5, player: 'Jayson Tatum', team: 'BOS', game: 'CLE@BOS', market: 'Player Points + Rebounds + Assists', bet_name: 'Jayson Tatum Over 40.5', direction: 'Over', line: 40.5, avg_odds: '-115 / -105', avg_fv: -108, books_count: 6 },  // unsupported
  { L: 6, player: 'Jayson Tatum', team: 'BOS', game: 'CLE@BOS', market: 'Player Assists', bet_name: 'Jayson Tatum Over 5.5', direction: 'Over', line: 5.5, avg_odds: '+115 / -135', avg_fv: -135, books_count: 6 },  // _fv_suspicious (fv=-135 matches odds pair)
  { L: 7, player: 'Jayson Tatum', team: '', game: '', market: 'Player Assists', bet_name: 'Jayson Tatum Over 5.5', direction: 'Over', line: 5.5, avg_odds: '+115 / -135', avg_fv: 102, books_count: 8 },  // dup (player,leg) — keep books_count=8
  { L: 8, player: 'Unknown Guy', team: 'UTA', game: 'UTA@DEN', market: 'Player 3-Pt Made', bet_name: 'Unknown Guy Over 2.5', direction: 'Over', line: 2.5, avg_odds: '+160 / -200', avg_fv: 180, books_count: 3 },
  { L: 9, player: '', team: '', game: '', market: 'Player Points', bet_name: 'Over 20.5', direction: 'Over', line: 20.5, avg_odds: '-110 / -110', avg_fv: 100, books_count: 2 },  // missing player
];

const { rows: normRows, unmatched } = normalizeNbaRows(raw);

/* Surviving rows after normalize + collapse:
     L=1 Mitchell Points Over, L=2 Mitchell Points Under, L=3 Mitchell Rebounds Over,
     L=7 Tatum Assists Over (wins collapse over L=6 via higher books_count),
     L=8 Unknown Guy 3-Pt Over.
   Dropped: L=4 Steals (unsupported), L=5 PRA (unsupported), L=9 no-player. */
check('normRows.length = 5 (after dedupe + unsupported drops)', normRows.length, 5);
check('unmatched.length = 3 (Steals, PRA, no-player)', unmatched.length, 3);

const tatumAst = normRows.find(r => r.player === 'Jayson Tatum' && r.stat === 'Assists');
checkTruthy('Tatum Assists leg kept', tatumAst);
check('  dup-leg tiebreak: higher books_count wins', tatumAst ? tatumAst._books : null, 8);
check('  dup-leg tiebreak: kept L=7', tatumAst ? tatumAst._L : null, 7);

const mitchellPts = normRows.find(r => r.player === 'Donovan Mitchell' && r.stat === 'Points' && r.direction === 'Over');
check('  stat canonicalized correctly', mitchellPts ? mitchellPts.stat : null, 'Points');
check('  leg string canonical', mitchellPts ? mitchellPts.leg : null, 'Over 27.5 Points');

const unknownThrees = normRows.find(r => r.player === 'Unknown Guy');
check('  3-Pt Made normalizes to "3-Pointers Made"', unknownThrees ? unknownThrees.stat : null, '3-Pointers Made');

const steals = unmatched.find(u => u.market === 'Player Steals');
check('  Steals flagged unsupported_prop', steals ? steals.reason.indexOf('unsupported_prop') : -1, 0);
const pra = unmatched.find(u => u.market === 'Player Points + Rebounds + Assists');
check('  PRA flagged unsupported_prop', pra ? pra.reason.indexOf('unsupported_prop') : -1, 0);

/* --- groupNbaPlayers --- */
const grouped = groupNbaPlayers(normRows);
check('grouped: 3 players', grouped.length, 3);
const mitchellG = grouped.find(p => p.player === 'Donovan Mitchell');
checkTruthy('mitchell props exist', mitchellG);
check('  mitchell Points has over + under merged',
  mitchellG ? (mitchellG.props.find(p => p.stat === 'Points').over_fv + ',' + mitchellG.props.find(p => p.stat === 'Points').under_fv) : null,
  '120,-150');
check('  mitchell Rebounds has only Over (sparse side OK)',
  mitchellG ? (mitchellG.props.find(p => p.stat === 'Rebounds').under_fv) : '???',
  null);

/* --- Suspicious FV flag + unsupported-prop reason string preserved --- */
const mitchellPtsOver = mitchellG.props.find(p => p.stat === 'Points');
check('  _fv_suspicious propagated via over_fv_suspicious (Points over is clean)',
  mitchellPtsOver.over_fv_suspicious, false);

console.log('\n' + passes + ' pass, ' + failures + ' fail');
if (failures) process.exit(1);
console.log('ALL NBA OCR NORMALIZE TESTS PASS');
