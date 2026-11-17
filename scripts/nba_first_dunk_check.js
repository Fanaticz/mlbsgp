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
const gap = (a, b) => Object.keys(b).reduce((w, k) => Math.max(w, Math.abs((a[k] || 0) - b[k])), 0);

// a settled lineup
const out = FD.price(c.entries, c.m, c.gamma);
const sum = Object.values(out.probs).reduce((a, b) => a + b, 0);
ok(`game ${c.game}: ${c.entries.length} players match Python`, gap(out.probs, c.probs) < 1e-12, `largest gap ${gap(out.probs, c.probs).toExponential(2)}`);
ok('probabilities and the no-dunk chance sum to 1', Math.abs(sum + out.noDunk - 1) < 1e-12);
ok('no-dunk chance matches', Math.abs(out.noDunk - c.no_dunk) < 1e-15);
ok('each team\'s share matches', gap(out.team, c.team) < 1e-12);
ok('minutes to the first dunk match', Math.abs(out.tFirst - c.t_first) < 1e-9 && gap(out.tTeam, c.t_team) < 1e-9);

// two starters unsure (one 50%, one 15%): four lineups priced and added up
const mx = FD.mix(c.rows, (lineup) => Object.keys(lineup).map((id) => c.both[id + ':' + lineup[id]]), c.m, c.gamma);
ok(`unsure starters: ${mx.scenarios} lineups match Python`, mx.scenarios === c.mixed.scenarios && gap(mx.probs, c.mixed.probs) < 1e-12,
  `largest gap ${gap(mx.probs, c.mixed.probs).toExponential(2)}`);
ok('unsure starters: team shares and minutes match', gap(mx.team, c.mixed.team) < 1e-12 && Math.abs(mx.tFirst - c.mixed.t_first) < 1e-9);
const unsure = c.rows.filter((r) => r.play < 1).map((r) => r.id);
ok('a 50% starter is worth less than when he is sure to play', unsure.every((id) => mx.probs[id] < out.probs[id]));

// the page's own road: the model file's rounded numbers, a pre-game bench, one starter at 50%
const D = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'public', 'data', 'nba_first_dunk.json'), 'utf8'));
const pc = c.page;
if (pc.through !== D.through || pc.rows.some((r) => !D.players[r.id])) {
  console.log('skip the model file is newer than the fixture (or a player left his roster); rewrite it with --fixture');
} else {
  const cx = { [pc.away]: FD.context(D, pc.away, pc.home, 0), [pc.home]: FD.context(D, pc.home, pc.away, 1) };
  const by = {};
  pc.rows.forEach((r) => { by[r.id] = Object.assign({}, r, { app: r.tagged ? Math.max(D.players[r.id].app, 0.6) : D.players[r.id].app }); });
  const pm = FD.mix(pc.rows, (lu) => Object.keys(lu).map((id) => FD.entry(D, id, by[id].t, lu[id], cx[by[id].t], by[id].app)), D.m, D.params.gamma);
  const g1 = gap(pm.probs, pc.probs);
  ok(`page pricing of ${pc.away} at ${pc.home} from the model file matches Python (${pc.rows.length} candidates, ${pm.scenarios} lineups)`,
    g1 < 2e-3 && gap(pm.team, pc.team) < 2e-3, `largest gap ${(100 * g1).toFixed(3)} points`);
}

// Rotowire's page
const LU = require('../nbaLineups.js');
const li = (name, pos, cls, tag) => `<li class="lineup__player ${cls}" title="x"><div class="lineup__pos">${pos}</div><a title="${name}" href="#">x</a>${tag ? `<span class="lineup__inj">${tag}</span>` : ''}</li>`;
const list = (side, status, st, others) => `<ul class="lineup__list ${side}"><li class="lineup__status ${status}">x</li>${st.join('')}<li class="lineup__title is-middle">MAY NOT PLAY</li>${others.join('')}</ul>`;
const five = (p) => ['A', 'B', 'C', 'D', 'E'].map((x, i) => li(p + ' ' + x, 'PG', i === 4 ? 'is-pct-play-50 has-injury-status' : 'is-pct-play-100', i === 4 ? 'Ques' : ''));
const page = `<div class="page-title__secondary">Starting lineups for November 17, 2026</div><div class="lineup is-nba" data-lnum="1"><div class="lineup__time">7:30 PM ET</div>` +
  `<div class="lineup__abbr">NYK</div><div class="lineup__abbr">TOR</div>` +
  list('is-visit', 'is-expected', five('Knick'), [li('Knick F', 'C', 'is-pct-play-0 has-injury-status', 'Out'), li('Knick G', 'F', 'is-pct-play-100 has-injury-status', 'Doubt')]) +
  list('is-home', 'is-confirmed', five('Raptor'), []) + `</div>`;
const lg = LU.parse(page);
ok('lineups: one game, dated, Rotowire\'s NYK read as ESPN\'s NY', lg.length === 1 && lg[0].date === '20261117' && lg[0].away === 'NY' && lg[0].home === 'TOR');
const ny = lg[0].teams.NY, tor = lg[0].teams.TOR;
ok('lineups: five expected starters, the questionable one at 50%', ny.status === 'expected' && ny.starters.length === 5 && ny.starters[4].play === 0.5 && ny.starters[4].tag === 'ques');
ok('lineups: out is 0, doubtful is 15%', ny.others.length === 2 && ny.others[0].play === 0 && ny.others[1].play === 0.15);
ok('lineups: a confirmed five all play', tor.status === 'confirmed' && tor.starters.every((p) => p.play === 1));

ok('+650 is 7.5', FD.parsePrice('+650') === 7.5);
ok('-120 is 1.8333', Math.abs(FD.parsePrice('-120') - (1 + 100 / 120)) < 1e-12);
ok('650 reads as American', FD.parsePrice('650') === 7.5);
ok('7.5x reads as decimal', FD.parsePrice('7.5x') === 7.5);
ok('junk is null', FD.parsePrice('abc') === null && FD.parsePrice('') === null && FD.parsePrice('50') !== null);
ok('fair odds', FD.probToAmerican(0.2) === '+400' && FD.probToAmerican(0.6) === '-150');
ok('names', FD.normName('Wendell Carter Jr.') === 'wendell carter' && FD.normName("Ja'Kobe Walter") === 'jakobe walter'
  && FD.normName('Nikola Jokić') === 'nikola jokic' && FD.normName('Karl-Anthony Towns') === 'karl anthony towns');

process.exit(fail ? 1 : 0);
