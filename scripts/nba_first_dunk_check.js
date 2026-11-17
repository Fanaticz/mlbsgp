#!/usr/bin/env node
// The page's first-dunk pricing (public/utils/firstDunk.js) against the
// Python model's (scripts/nba_first_dunk.py) on one real game.
//
//   python3 scripts/nba_first_dunk.py --fixture   # rewrite the case
//   node scripts/nba_first_dunk_check.js
const fs = require('fs');
const path = require('path');
const FD = require('../public/utils/firstDunk.js');

let fail = 0;
const ok = (name, cond, extra) => { if (!cond) fail++; console.log((cond ? 'ok   ' : 'FAIL ') + name + (extra ? '  ' + extra : '')); };

const c = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'first_dunk_case.json'), 'utf8'));
const data = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'public', 'data', 'nba_first_dunk.json'), 'utf8'));
const out = FD.price(c.entries, c.m, data.params.gamma);
let worst = 0, sum = 0;
for (const id of Object.keys(c.probs)) { worst = Math.max(worst, Math.abs(out.probs[id] - c.probs[id])); sum += out.probs[id]; }
ok(`game ${c.game}: ${c.entries.length} players match Python`, worst < 1e-9, `largest gap ${worst.toExponential(2)}`);
ok('probabilities sum to 1', Math.abs(sum - 1) < 1e-9);
ok('no-dunk chance matches', Math.abs(out.noDunk - c.no_dunk) < 1e-12);

ok('+650 is 7.5', FD.parsePrice('+650') === 7.5);
ok('-120 is 1.8333', Math.abs(FD.parsePrice('-120') - (1 + 100 / 120)) < 1e-12);
ok('650 reads as American', FD.parsePrice('650') === 7.5);
ok('7.5x reads as decimal', FD.parsePrice('7.5x') === 7.5);
ok('junk is null', FD.parsePrice('abc') === null && FD.parsePrice('') === null && FD.parsePrice('50') !== null);
ok('fair odds', FD.probToAmerican(0.2) === '+400' && FD.probToAmerican(0.6) === '-150');
ok('names', FD.normName('Wendell Carter Jr.') === 'wendell carter' && FD.normName("Ja'Kobe Walter") === 'jakobe walter'
  && FD.normName('Nikola Jokić') === 'nikola jokic' && FD.normName('Karl-Anthony Towns') === 'karl anthony towns');

process.exit(fail ? 1 : 0);
