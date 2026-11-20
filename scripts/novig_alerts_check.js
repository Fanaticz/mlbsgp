// Checks novigAlerts.js's rules and its Discord posting against a stand-in
// webhook (no network): node scripts/novig_alerts_check.js
const assert = require('assert');
const A = require('../novigAlerts.js');
let T = 1e12, posts = [], answers = [], calls = [];
const fetchStub = async (url, o) => {
  calls.push(o.method + ' ' + url.replace(/^.*SECRET/, ''));
  if (o.method === 'PATCH') { calls.push(JSON.parse(o.body).embeds[0]); return { status: 200, ok: true, headers: { get: () => null }, json: async () => ({ id: 'm1' }) }; }
  posts.push(JSON.parse(o.body));
  const a = answers.shift() || { status: 200 };
  return { status: a.status, ok: a.status < 300, headers: { get: k => (a.headers || {})[k] || null }, json: async () => a.body || { id: 'm1' } };
};
const logs = [];
const mk = env => A.create({ env: Object.assign({ ALERTS_ENABLED: '1', DISCORD_WEBHOOK_URL: 'https://discord.invalid/api/webhooks/1/SECRET' }, env), fetch: fetchStub, now: () => T, log: m => logs.push(m) });
const row = (o) => Object.assign({ key: 'a,b', player: 'Cam Spencer', id: 77, team: 'MEM', event: 'g1', label: '13+ PTS · 3+ 3PM', starts: T + 3600e3,
  legs: [{ id: '11111111-1111-1111-1111-111111111111', stat: 'pts', fair: -110 }, { id: '22222222-2222-2222-2222-222222222222', stat: 'tpm', fair: 140 }],
  fair: 250, fair_x: 3.5, slip_x: 3.75, ev: 0.071, qk: 0.6, at: T / 1000, expires: T + 28000 }, o);
(async () => {
  let a = mk({});
  // the two EV bars
  assert.strictEqual(a.consider('nba', row({ ev: 0.049 })), 'under the EV bar');
  assert.strictEqual(a.consider('nfl', row({ ev: 0.071, legs: [{ id: 'x', stat: 'rec' }, { id: 'y', stat: 'yds' }] })), 'under the EV bar');
  assert.strictEqual(a.consider('ladder', row({ ev: 0.071, model: true })), 'under the EV bar');   // modelled: the 10% bar
  assert.strictEqual(a.consider('nhl', row({ ev: 0.3 })), 'board not in ALERT_SPORTS');
  assert.deepStrictEqual(a.S.sports, ['nba', 'ladder', 'nbateam', 'nfl', 'nflladder', 'soccer', 'cfb', 'cbb']);
  // expiry, start, out, rough
  assert.strictEqual(a.consider('nba', row({ expires: T + 5000 })), 'quote expired or about to');
  assert.strictEqual(a.consider('nba', row({ expires: null })), 'no expiry on the quote');
  assert.strictEqual(a.consider('nba', row({ starts: T - 1 })), 'game started');
  assert.strictEqual(a.consider('nba', row({}), { out: true }), 'player out');
  assert.strictEqual(a.consider('nba', row({ rough: true })), 'rough fair value');
  assert.strictEqual(posts.length, 0);
  // sent once, and never again whatever its price does
  assert.strictEqual(a.consider('nba', row({}), { game: 'MEM @ DAL' }), null);
  await a.flush();
  assert.strictEqual(posts.length, 1);
  const e = posts[0].embeds[0];
  assert.strictEqual(e.title, 'Spencer: 13+ PTS, 3+ 3PM · 3.75x · +7.1%');   // the heading: who and what, not just the name
  assert.strictEqual(a.heading({ player: 'Emari Demercado', label: '22+ RUSH YDS · 1+ TD' }), 'Demercado: 22+ Rush, 1+ TD');
  assert.strictEqual(a.heading({ player: 'Terrence Shannon Jr.', label: '60+ YDS · 5+ REC' }), 'Shannon Jr.: 60+ Rec Yds, 5+ Rec');
  assert.strictEqual(a.heading({ player: 'Nikola Jokic + Jamal Murray', label: 'Jokic 27+ PTS · Murray 22+ PTS' }), 'Jokic 27+ PTS, Murray 22+ PTS');
  assert.strictEqual(a.heading({ player: 'C.J. Stroud + Nico Collins', label: '230+ PASS YDS · Collins 70+ YDS' }), 'Stroud: 230+ Pass Yds, Collins 70+ Rec Yds');
  assert.strictEqual(a.heading({ player: 'TA&M @ TCU (NCAAB)', label: 'TA&M team total Under 80.5 · TCU team total Under 81.5' }), 'TA&M team total Under 80.5, TCU team total Under 81.5');
  const two = '11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222';
  assert.strictEqual(e.url, 'https://novig.onelink.me/JHQQ/events/' + two);   // the title: the phone's link
  assert.ok(e.description.includes(`[Open in the Novig app ↗](https://novig.onelink.me/JHQQ/events/${two})** · [on a computer ↗](https://novig.com/events/${two})`));
  assert.ok(A.embed(A.settings({ PUBLIC_URL: 'https://app.example/' }), 'nba', row({})).description.includes('[on a computer ↗](https://app.example/n/11111111-'));
  assert.strictEqual(e.fields.find(f => f.name.startsWith('Stake')).value, '$60 · 0.60u');   // 0.6u x $100
  assert.strictEqual(a.consider('nba', row({ ev: 0.085 })), 'already sent');   // under 2 points: nothing
  // moved 2+ points: the message is edited where it stands, no new message
  calls = [];
  assert.strictEqual(a.consider('nba', row({ ev: 0.12, slip_x: 3.92 })), 'message edited');
  await a.flush();
  assert.strictEqual(posts.length, 1);
  assert.strictEqual(calls[0], 'PATCH /messages/m1');
  assert.ok(calls[1].title.startsWith('MOVED UP · ') && calls[1].description.includes('Novig 3.75x → 3.92x') && calls[1].description.includes('EV +7.1% → +12.0%'));
  assert.strictEqual(a.consider('nba', row({ ev: 0.125, slip_x: 3.93 })), 'already sent');   // under 2 points from what it now says
  // moved down, under its bar, or his player out: the message is left alone
  calls = [];
  assert.strictEqual(a.consider('nba', row({ ev: 0.01, fair: 270, fair_x: 3.7, expires: null })), 'already sent');
  assert.strictEqual(a.consider('nba', row({ ev: 0.50 }), { out: true }), 'already sent');
  assert.strictEqual(a.consider('nba', row({ ev: 0.13 })), 'already sent');   // back up, but under 2 points over the best it has shown (12%)
  await a.flush();
  assert.strictEqual(calls.length, 0);
  assert.strictEqual(a.consider('nba', row({ ev: 0.50 })), 'message edited');   // far better: edited, still no new message
  await a.flush();
  assert.ok(calls[1].title.startsWith('MOVED UP · '));
  assert.strictEqual(posts.length, 1);
  // same player, another slip: sent, once
  assert.strictEqual(a.consider('nba', row({ key: 'a,c', ev: 0.08 })), null);
  await a.flush();
  assert.strictEqual(a.consider('nba', row({ key: 'a,c', ev: 0.08 })), 'already sent');
  // every other player in the game goes: no limit a game
  for (let i = 0; i < 6; i++) assert.strictEqual(a.consider('nba', row({ key: 'p' + i, id: 100 + i, player: 'P' + i })), null);
  await a.flush();
  // with ALERT_MAX_PER_GAME=2: a second player goes, a third does not
  const cap = mk({ ALERT_MAX_PER_GAME: '2' });
  assert.strictEqual(cap.consider('nba', row({})), null);
  assert.strictEqual(cap.consider('nba', row({ key: 'd,e', id: 78, player: 'B' })), null);
  assert.strictEqual(cap.consider('nba', row({ key: 'f,g', id: 79, player: 'C', ev: 0.3 })), 'game has its alerts');
  assert.strictEqual(cap.consider('nba', row({ key: 'f,g', id: 79, player: 'C', ev: 0.3, event: 'g2' })), null);
  assert.strictEqual(cap.verdict('cbb', row({ key: 'zz', event: 'g1', ev: 0.3 })), 'game has its alerts');
  await cap.flush();
  // CBB: one message a game for each type of slip; soccer and the rest: every slip
  a = mk({});
  const cbb = o => row(Object.assign({ id: 'g7', event: 'g7', player: 'COFC @ DRKE', ev: 0.2, shape: 'fav_tt_under+under', label: 'DRKE team total Under 79.5 · Under 150.5' }, o));
  assert.strictEqual(a.consider('cbb', cbb({ key: 'c1' })), null);
  assert.strictEqual(a.consider('cbb', cbb({ key: 'c2', label: 'DRKE team total Under 78.5 · Under 150.5', ev: 0.4 })), 'this type already sent for the game');   // a line over
  assert.strictEqual(a.consider('cbb', cbb({ key: 'c3', shape: 'fav_cover+over', label: 'DRKE -6.5 · Over 150.5' })), null);   // another type
  assert.strictEqual(a.consider('cbb', cbb({ key: 'c4', id: 'g8', event: 'g8' })), null);   // another game
  // the underdog covering + his total Under, then the double Under: the double Under still goes; not the other way round
  assert.strictEqual(a.consider('cbb', cbb({ key: 'c5', shape: 'dog_cover+dog_tt_under', label: 'COFC +4.5 · COFC team total Under 55.5' })), null);
  assert.strictEqual(a.consider('cbb', cbb({ key: 'c6', shape: 'fav_tt_under+dog_tt_under', label: 'DRKE team total Under 79.5 · COFC team total Under 55.5' })), null);
  assert.strictEqual(a.consider('cbb', cbb({ key: 'c7', shape: 'dog_cover+dog_tt_under', label: 'COFC +5.5 · COFC team total Under 55.5', ev: 0.5 })), 'this type already sent for the game');
  assert.strictEqual(a.consider('cbb', cbb({ key: 'c8', shape: 'fav_tt_under+dog_tt_under', label: 'DRKE team total Under 78.5 · COFC team total Under 55.5', ev: 0.5 })), 'this type already sent for the game');
  // a row from before rows carried a shape: its label with the numbers out
  assert.strictEqual(a.consider('cbb', cbb({ key: 'c9', id: 'g9', event: 'g9', shape: undefined })), null);
  assert.strictEqual(a.consider('cbb', cbb({ key: 'c10', id: 'g9', event: 'g9', shape: undefined, label: 'DRKE team total Under 77.5 · Under 151.5' })), 'this type already sent for the game');
  const soc = o => row(Object.assign({ id: 'm1', event: undefined, player: 'Arsenal v Chelsea', ev: 0.2, label: 'Arsenal to win · Arsenal U5.5 corners · Chelsea O3.5 corners' }, o));
  assert.strictEqual(a.consider('soccer', soc({ key: 's1' })), null);
  assert.strictEqual(a.consider('soccer', soc({ key: 's2', label: 'Arsenal to win · Arsenal U6.5 corners · Chelsea O3.5 corners' })), null);
  await a.flush();
  // Discord 429: waits retry_after, sends again
  a = mk({}); posts = []; answers = [{ status: 429, body: { retry_after: 0.6 }, headers: { 'retry-after': '1' } }];
  const t0 = Date.now();
  a.consider('nba', row({ key: 'z,z' })); await a.flush();
  assert.strictEqual(posts.length, 2); assert.ok(Date.now() - t0 >= 600);
  assert.strictEqual(a.status().sent, 1);
  // a post that fails takes the mark off, so the slip can go next pass
  answers = [{ status: 404 }];
  a.consider('nba', row({ key: 'q,q', id: 90, event: 'g9' })); await a.flush();
  assert.strictEqual(a.status().lastError, 'Discord answered 404');
  assert.strictEqual(a.verdict('nba', row({ key: 'q,q', id: 90, event: 'g9' })), null);
  // dry run posts nothing; off sends nothing; the webhook is in no log line or status
  posts = [];
  a = mk({ ALERTS_DRY_RUN: '1' }); assert.strictEqual(a.consider('nba', row({})), null); await a.flush();
  assert.strictEqual(posts.length, 0); assert.ok(logs.some(l => l.startsWith('[novig-alert dry] NBA | Cam Spencer')));
  assert.strictEqual(mk({ ALERTS_ENABLED: '' }).consider('nba', row({})), 'alerts off');
  assert.ok(!JSON.stringify([logs, a.status()]).includes('SECRET'));
  console.log('novig alerts: all checks passed');
})().catch(e => { console.error(e); process.exit(1); });
