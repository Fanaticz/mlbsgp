// Checks novigAlerts.js's rules and its Discord posting against a stand-in
// webhook (no network): node scripts/novig_alerts_check.js
const assert = require('assert');
const A = require('../novigAlerts.js');
let T = 1e12, posts = [], answers = [];
const fetchStub = async (url, o) => {
  posts.push(JSON.parse(o.body));
  const a = answers.shift() || { status: 200 };
  return { status: a.status, ok: a.status < 300, headers: { get: k => (a.headers || {})[k] || null }, json: async () => a.body || {} };
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
  assert.strictEqual(a.consider('cbb', row({ ev: 0.3 })), 'board not in ALERT_SPORTS');
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
  assert.ok(e.title.includes('Cam Spencer') && e.title.includes('+7.1%'));
  assert.ok(e.url.startsWith('https://novig.com/events/11111111-'));
  assert.strictEqual(e.fields.find(f => f.name.startsWith('Stake')).value, '$300 · 0.60u');   // 0.6u x $500
  assert.strictEqual(a.consider('nba', row({ ev: 0.085 })), 'already sent');
  assert.strictEqual(a.consider('nba', row({ ev: 0.50 })), 'already sent');
  // same player, another slip: not sent either
  assert.strictEqual(a.consider('nba', row({ key: 'a,c', ev: 0.50 })), 'another slip on this one already sent');
  // with ALERT_REALERT_STEP set, another slip on him goes at that many points better; the same slip still never
  const s2 = mk({ ALERT_REALERT_STEP: '2' });
  assert.strictEqual(s2.consider('nba', row({})), null);
  assert.strictEqual(s2.consider('nba', row({ ev: 0.50 })), 'already sent');
  assert.strictEqual(s2.consider('nba', row({ key: 'a,c', ev: 0.08 })), 'another slip on this one already sent');
  assert.strictEqual(s2.consider('nba', row({ key: 'a,c', ev: 0.095 })), null);
  await s2.flush();
  // two alerts a game: a second player goes, a third does not
  assert.strictEqual(a.consider('nba', row({ key: 'd,e', id: 78, player: 'B' })), null);
  assert.strictEqual(a.consider('nba', row({ key: 'f,g', id: 79, player: 'C', ev: 0.3 })), 'game has its alerts');
  assert.strictEqual(a.consider('nba', row({ key: 'f,g', id: 79, player: 'C', ev: 0.3, event: 'g2' })), null);
  await a.flush();
  // a game's own lines: the same shape one line over is the same subject
  a = mk({ ALERT_SPORTS: 'soccer' });
  const soc = o => row(Object.assign({ id: 'm1', event: undefined, player: 'Arsenal v Chelsea', ev: 0.2, label: 'Arsenal to win · Arsenal U5.5 corners · Chelsea O3.5 corners' }, o));
  assert.strictEqual(a.consider('soccer', soc({ key: 's1' })), null);
  assert.strictEqual(a.consider('soccer', soc({ key: 's2', label: 'Arsenal to win · Arsenal U6.5 corners · Chelsea O3.5 corners' })), 'another slip on this one already sent');
  assert.strictEqual(a.consider('soccer', soc({ key: 's3', label: 'Arsenal to win · Arsenal U5.5 corners · Chelsea O3.5 corners · O2.5 goals' })), null);
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
