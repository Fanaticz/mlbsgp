// Discord alerts for the Novig SGP scanner (public/nba_scan.html).
//
// server.js hands every row a pass prices to consider(). Nothing is priced
// here: a row arrives with its fair value, Novig's slip price, EV and quarter
// Kelly already on it (scan.py's finish()). This file decides whether the row
// is worth a message, keeps what it has already sent, and posts to the webhook.
// Alerts only: nothing here, or anywhere in the app, places a Novig bet.
//
// Settings (all from the environment):
//   DISCORD_WEBHOOK_URL   the channel's webhook. Never logged or sent to the page.
//   ALERTS_ENABLED        1 to send alerts (and keep the alert boards priced). Default off.
//   ALERTS_DRY_RUN        1 to print would-be alerts to the log and post nothing.
//   ALERT_SPORTS          boards that may alert: nba,ladder,nfl,nflladder,soccer
//   ALERT_SCAN_SPORTS     boards the job prices on its own: ALERT_SPORTS without
//                         ladder (NBA Ladder is Fetch only; its rows alert when fetched).
//   ALERT_MIN_EV          EV% a slip needs: 10
//   ALERT_MIN_EV_PTS3     EV% for NBA main-line Points + Threes: 5
//   ALERT_REALERT_STEP    A slip is sent once, ever (Max, 11-19: a second message
//                         is a second bet on it). So is a player in a game. Set this
//                         to let a DIFFERENT slip on the same player through when it
//                         beats the one sent by this many EV points: 0 (never)
//   ALERT_UPDATE_STEP     A slip already sent is not sent again, but its message is
//                         edited in place (no new message, no ping) when its EV has
//                         moved this many points either way since the message last
//                         said, or has fallen under its bar: 2 (0: never edited)
//   ALERT_MAX_PER_GAME    alerts for one game: 2
//   ALERT_MIN_TTL_S       a quote with less than this left is not sent: 10
//   ALERT_UNIT            dollars a unit for the stake: 100 (the page's QK $)
//   ALERT_ROUGH           1 to alert on rows whose fair value is rough (a wide book)
//   PUBLIC_URL            this app's address, for the slip link (else Railway's domain)
//
//   node novigAlerts.js --dry [boards.json]   what the saved boards would alert on now
const fs = require('fs');
const path = require('path');

const num = (v, d) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : d);
const on = v => /^(1|true|yes|on)$/i.test(String(v || '').trim());
const list = (v, d) => (String(v || '').trim() ? String(v).split(',').map(s => s.trim().toLowerCase()).filter(Boolean) : d);

const BOARD_NAME = { nba: 'NBA', ladder: 'NBA Ladder', nbateam: 'NBA Team', nfl: 'NFL', nflladder: 'NFL Ladder',
                     nhl: 'NHL', nhllines: 'NHL Lines', soccer: 'Soccer', cfb: 'CFB', cbb: 'CBB' };

function settings(env) {
  const sports = list(env.ALERT_SPORTS, ['nba', 'ladder', 'nfl', 'nflladder', 'soccer']).filter(b => BOARD_NAME[b]);
  return {
    webhook: String(env.DISCORD_WEBHOOK_URL || '').trim(),
    enabled: on(env.ALERTS_ENABLED),
    dry: on(env.ALERTS_DRY_RUN),
    sports,
    scan: list(env.ALERT_SCAN_SPORTS, sports.filter(b => b !== 'ladder')).filter(b => BOARD_NAME[b]),
    minEv: num(env.ALERT_MIN_EV, 10),
    minEvPts3: num(env.ALERT_MIN_EV_PTS3, 5),
    step: Math.max(0, num(env.ALERT_REALERT_STEP, 0)),
    update: Math.max(0, num(env.ALERT_UPDATE_STEP, 2)),
    perGame: Math.max(1, Math.round(num(env.ALERT_MAX_PER_GAME, 2))),
    minTtl: num(env.ALERT_MIN_TTL_S, 10),
    unit: num(env.ALERT_UNIT, 100),
    rough: on(env.ALERT_ROUGH),
    base: String(env.PUBLIC_URL || (env.RAILWAY_PUBLIC_DOMAIN ? 'https://' + env.RAILWAY_PUBLIC_DOMAIN : '')).trim().replace(/\/+$/, ''),
  };
}

// NBA main-line Points + Threes: the slip the lower EV bar is for.
const isPts3 = (board, row) => board === 'nba' && (row.legs || []).length === 2 && !row.model &&
  (row.legs || []).map(L => L.stat).sort().join() === 'pts,tpm' && String(row.player || '').indexOf(' + ') < 0;
const minEv = (S, board, row) => (isPts3(board, row) ? S.minEvPts3 : S.minEv);

// Which game a slip is on, and what it repeats. A player's slips are one
// subject whatever the legs (25+ and 26+ points with 3+ threes are the same
// bet twice); a slip across a game's own lines is its shape, the label with
// the numbers out, so the same slip one line over is the same subject.
const gameOf = row => String(row.event || row.id || row.player || '');
function subjectOf(board, row) {
  const game = gameOf(row);
  if (String(row.id) === game || !row.id) return `${game}|${board}|${String(row.label || '').replace(/[0-9.+-]+/g, '#')}`;
  return `${game}|${row.id}`;
}

const american = x => (x >= 2 ? '+' + Math.round((x - 1) * 100) : String(Math.round(-100 / (x - 1))));
const pct = v => (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';

// The Discord message for a row. extra: { game, test, better }.
function embed(S, board, row, extra) {
  extra = extra || {};
  const ids = (row.legs || []).map(L => L.id);
  const okIds = ids.length && ids.every(i => /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(String(i)));
  // Two links. The phone's (the title, and the first link): Novig's own
  // universal-link address, which iOS hands straight to the app with the legs
  // on the slip and no "Open this page in Novig?" question (Max, 11-19: works).
  // It is a dead page in a computer's browser, so the second link is for a
  // computer: /n/<ids> on this app, which goes to novig.com (novig.com itself
  // without this app's address). A row with no real outcome ids (the test
  // button's stand-in) links to novig.com.
  const tail = ids.join(',');
  const url = okIds ? `https://novig.onelink.me/JHQQ/events/${tail}` : 'https://novig.com';
  const web = S.base ? `${S.base}/n/${tail}` : `https://novig.com/events/${tail}`;
  const texts = String(row.label || '').split(' · ');
  const legs = (row.legs || []).map((L, i) => {
    const t = L.text || (texts.length === row.legs.length ? texts[i] : `${L.side || ''} ${L.line != null ? L.line : ''} ${L.stat || ''}`.trim());
    return `${t} (${L.fair > 0 ? '+' : ''}${L.fair})`;
  });
  const stake = Math.round((row.qk || 0) * S.unit);
  const when = row.starts ? `<t:${Math.floor(row.starts / 1000)}:t>` : '';
  // An edited message: what it said when it was sent, and what moved since.
  const was = extra.was, moved = [];
  if (was) {
    if (Math.abs(row.slip_x - was.slip_x) >= 0.005) moved.push(`Novig ${was.slip_x.toFixed(2)}x → ${row.slip_x.toFixed(2)}x`);
    if (row.fair !== was.fair) moved.push(`Fair ${was.fair > 0 ? '+' : ''}${was.fair} → ${row.fair > 0 ? '+' : ''}${row.fair} (${row.fair > was.fair ? 'longer: less likely to hit' : 'shorter: more likely to hit'})`);
    moved.push(`EV ${pct(was.ev)} → ${pct(row.ev)}`);
  }
  const head = extra.test ? 'TEST · ' : !was ? '' : extra.gone ? 'NO LONGER A PLAY · ' : row.ev > was.ev ? 'MOVED UP · ' : 'MOVED DOWN · ';
  const notes = [
    was ? `Same slip as sent <t:${Math.floor(was.at / 1000)}:R>, not a new one. ` + moved.join(' · ') : '',
    extra.better ? 'Better than the last alert on this one.' : '',
    row.model ? 'Fair value modelled from the main line, not read off a book.' : '',
    row.rough ? 'A leg sits on a wide book: rough fair value.' : '',
    row.gtd ? `Game-time decision: ${row.gtd}` : '',
  ].filter(Boolean);
  return {
    title: `${head}${row.player}${row.team && !/ v | \+ /.test(row.player) ? ' (' + row.team + ')' : ''} · ${pct(row.ev)}`.slice(0, 250),
    url,
    color: extra.test || extra.gone ? 0x8a8f98 : row.ev >= 0.10 ? 0x2ecc71 : 0xf1c40f,
    // The title is the phone's link too; this line is the one that looks like a link.
    description: [[extra.game, when].filter(Boolean).join(' · '),
      okIds ? `**[Open in the Novig app ↗](${url})** · [on a computer ↗](${web})` : `**[Open Novig ↗](${url})**`, ...notes]
      .filter(Boolean).join('\n').slice(0, 1000) || undefined,
    fields: [
      { name: legs.length > 1 ? `${legs.length} legs` : 'Leg', value: legs.join('\n').slice(0, 1000) || String(row.label || '-') },
      { name: 'Novig', value: `${row.slip_x.toFixed(2)}x (${american(row.slip_x)})`, inline: true },
      { name: 'Fair', value: `${row.fair > 0 ? '+' : ''}${row.fair} (${row.fair_x.toFixed(2)}x)`, inline: true },
      { name: 'EV', value: pct(row.ev), inline: true },
      { name: 'Stake (quarter Kelly)', value: stake > 0 ? `$${stake.toLocaleString('en-US')} · ${row.qk.toFixed(2)}u` : '-', inline: true },
      { name: 'Quote expires', value: row.expires ? `<t:${Math.floor(row.expires / 1000)}:R>` : 'unknown', inline: true },
      { name: 'Tab', value: BOARD_NAME[board] || board, inline: true },
    ],
    footer: { text: 'Novig Scan · the price is a new auction when you open the slip' },
    timestamp: new Date(row.at ? row.at * 1000 : Date.now()).toISOString(),
  };
}

const line = (board, row, game) => `${BOARD_NAME[board] || board} | ${row.player} | ${row.label}${game ? ' | ' + game : ''} | Novig ${row.slip_x.toFixed(2)}x | fair ${row.fair > 0 ? '+' : ''}${row.fair} | EV ${pct(row.ev)} | QK ${(row.qk || 0).toFixed(2)}u`;

// opts: { env, dir (where the sent list is kept), log, fetch, now }
function create(opts) {
  opts = opts || {};
  const S = settings(opts.env || process.env);
  const log = opts.log || console.log, doFetch = opts.fetch || fetch, now = opts.now || Date.now;
  // A dry run keeps its own list, so trying it out doesn't use up real alerts.
  const file = opts.dir ? path.join(opts.dir, S.dry ? 'novig_alerts_dry.json' : 'novig_alerts.json') : null;
  let M = { slips: {}, subjects: {}, games: {} }, sent = 0, lastError = null;
  try { if (file) M = Object.assign(M, JSON.parse(fs.readFileSync(file, 'utf8'))); } catch (_) { /* nothing sent yet */ }
  const save = () => { if (file) fs.writeFile(file, JSON.stringify(M), () => {}); };
  // A game's entries go six hours after it starts (or a day after they were made).
  function prune() {
    const t = now();
    for (const m of [M.slips, M.subjects, M.games]) {
      for (const [k, v] of Object.entries(m)) if ((v.starts ? v.starts + 6 * 3600e3 : (v.at || 0) + 24 * 3600e3) < t) delete m[k];
    }
  }

  // Why a row is not sent, or null when it should be. Reads only.
  function verdict(board, row, o) {
    o = o || {};
    const t = now();
    if (!S.sports.includes(board)) return 'board not in ALERT_SPORTS';
    if (!row || !(row.slip_x > 1) || !Number.isFinite(row.ev)) return 'no price';
    if (row.ev * 100 < minEv(S, board, row) - 1e-9) return 'under the EV bar';
    if (row.starts && row.starts <= t) return 'game started';
    if (row.rough && !S.rough) return 'rough fair value';
    if (o.out) return 'player out';
    if (!o.anyAge) {
      if (!row.expires) return 'no expiry on the quote';
      if (row.expires - t < S.minTtl * 1000) return 'quote expired or about to';
    }
    const step = S.step / 100, key = String(row.key), sub = subjectOf(board, row), game = gameOf(row);
    const a = M.slips[key], b = M.subjects[sub];
    if (a) return 'already sent';
    if (b && (!(step > 0) || row.ev < b.ev + step - 1e-9)) return 'another slip on this one already sent';
    if (!a && !b && M.games[game] && M.games[game].n >= S.perGame) return 'game has its alerts';
    return null;
  }

  // One message at a time; Discord's limits are per webhook.
  let chain = Promise.resolve();
  const wait = ms => new Promise(r => setTimeout(r, ms));
  async function post(body, deadline, editId) {
    if (!S.webhook) throw new Error('DISCORD_WEBHOOK_URL is not set');
    for (let n = 0; n < 4; n++) {
      if (deadline && now() > deadline) throw new Error('quote expired before Discord took the message');
      let r;
      try {
        const [u, q] = S.webhook.split('?');
        r = await doFetch(editId ? `${u}/messages/${editId}${q ? '?' + q : ''}` : `${u}?${q ? q + '&' : ''}wait=true`, {
          method: editId ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(15000) });
      } catch (e) {
        // The address is the secret: an error is named by kind, never by its text.
        if (n === 3) throw new Error('Discord could not be reached (' + (e && e.name || 'error') + ')');
        await wait(1000 * (n + 1));
        continue;
      }
      if (r.status === 429) {
        let s = parseFloat(r.headers.get('retry-after'));
        try { const j = await r.json(); if (Number.isFinite(j.retry_after)) s = j.retry_after; } catch (_) { /* header only */ }
        await wait(Math.min(60, Math.max(0.5, Number.isFinite(s) ? s : 2)) * 1000 + 100);
        continue;
      }
      if (r.status >= 500) { await wait(1000 * (n + 1)); continue; }
      if (!r.ok) throw new Error('Discord answered ' + r.status);
      // The bucket is empty: the next message waits for it to refill.
      if (r.headers.get('x-ratelimit-remaining') === '0') {
        const s = parseFloat(r.headers.get('x-ratelimit-reset-after'));
        if (Number.isFinite(s)) await wait(Math.min(10, s) * 1000);
      }
      try { return (await r.json()).id || null; } catch (_) { return null; }
    }
    throw new Error('Discord kept refusing the message (rate limit)');
  }

  // A slip already sent, priced again: its message is edited where it stands
  // when the EV has moved S.update points since the message last said, or the
  // slip is no longer a play (under its bar, or his player now out). Never a
  // new message. Returns what it did, or null for a slip not sent before.
  function update(board, row, o) {
    const a = M.slips[String(row.key)];
    if (!a || !row || !(row.slip_x > 1) || !Number.isFinite(row.ev)) return null;
    if (!a.first || !(S.update > 0) || (row.starts && row.starts <= now())) return 'already sent';
    const gone = !!o.out || row.ev * 100 < minEv(S, board, row) - 1e-9;
    if (Math.abs(row.ev - a.shown) < S.update / 100 - 1e-9 && gone === !!a.gone) return 'already sent';
    if (!S.dry && !a.id) return 'already sent';   // its message is still on the way (or was sent before ids were kept)
    const prev = { shown: a.shown, gone: a.gone };
    a.shown = row.ev; a.gone = gone;
    save();
    const text = `${gone ? 'no longer a play' : row.ev > a.first.ev ? 'moved up' : 'moved down'}: ` + line(board, row, o.game) + ` | was ${pct(a.first.ev)} at ${a.first.slip_x.toFixed(2)}x, fair ${a.first.fair}`;
    if (S.dry) { log('[novig-alert dry] ' + text); return 'message edited'; }
    const body = { embeds: [embed(S, board, row, { game: o.game, was: a.first, gone })] };
    chain = chain.then(() => post(body, null, a.id)).then(() => log('[novig-alert] ' + text))
      .catch(e => { lastError = e.message; log('[novig-alert] message not edited: ' + e.message); a.shown = prev.shown; a.gone = prev.gone; save(); });
    return 'message edited';
  }

  // A row a pass has just priced. o: { out, game }. Returns why it was not
  // sent, or null. The row is marked sent before the post, so the same pass
  // can't queue it twice; a post that fails takes the mark off again.
  function consider(board, row, o) {
    o = o || {};
    if (!S.enabled) return 'alerts off';
    if (!S.dry && !S.webhook) return 'no webhook';
    prune();
    const moved = update(board, row, o);
    if (moved) return moved;
    const why = verdict(board, row, o);
    if (why) return why;
    const key = String(row.key), sub = subjectOf(board, row), game = gameOf(row);
    const before = { slip: M.slips[key], sub: M.subjects[sub], game: M.games[game] && Object.assign({}, M.games[game]) };
    const better = !!(before.slip || before.sub);
    const mark = { ev: row.ev, at: now(), starts: row.starts || 0, shown: row.ev, first: { ev: row.ev, slip_x: row.slip_x, fair: row.fair, at: now() } };
    M.slips[key] = mark;
    M.subjects[sub] = Object.assign({ key }, mark);
    if (!better) M.games[game] = { n: ((M.games[game] || {}).n || 0) + 1, at: now(), starts: row.starts || 0 };
    save();
    if (S.dry) { sent++; log('[novig-alert dry] ' + line(board, row, o.game) + (better ? ' | better than the last' : '')); return null; }
    const body = { username: 'Novig Scan', embeds: [embed(S, board, row, { game: o.game, better })], allowed_mentions: { parse: [] } };
    chain = chain.then(() => post(body, row.expires)).then(id => { if (M.slips[key] === mark) { mark.id = id; save(); } sent++; lastError = null; log('[novig-alert] sent ' + line(board, row, o.game)); })
      .catch(e => {
        lastError = e.message;
        log('[novig-alert] not sent: ' + e.message);
        if (before.slip) M.slips[key] = before.slip; else delete M.slips[key];
        if (before.sub) M.subjects[sub] = before.sub; else delete M.subjects[sub];
        if (before.game) M.games[game] = before.game; else if (!better) delete M.games[game];
        save();
      });
    return null;
  }

  // The page's "Send test alert" button: one message, marked TEST, with a real
  // row's numbers when a board has one. Works whether or not alerts are on.
  async function test(board, row, game) {
    const stand = { key: 'test', player: 'Test Player', team: 'TST', label: '20+ PTS · 3+ 3PM', starts: now() + 3600e3,
                    legs: [{ id: 'x', fair: -120 }, { id: 'y', fair: 150 }], fair: 220, fair_x: 3.2, slip_x: 3.45, ev: 0.078, qk: 0.8,
                    at: now() / 1000, expires: now() + 30000 };
    const r = row || stand, b = row ? board : 'nba';
    if (S.dry) { log('[novig-alert dry] TEST ' + line(b, r, game)); return { ok: true, dry: true }; }
    await post({ username: 'Novig Scan', embeds: [embed(S, b, r, { game, test: true })], allowed_mentions: { parse: [] } });
    return { ok: true, dry: false };
  }

  const status = () => ({ enabled: S.enabled, dry: S.dry, webhook: !!S.webhook, sports: S.sports, scan: S.scan, minEv: S.minEv,
                          minEvPts3: S.minEvPts3, step: S.step, update: S.update, perGame: S.perGame, sent, lastError });
  return { S, consider, verdict, test, status, embed: (b, r, x) => embed(S, b, r, x), flush: () => chain };
}

module.exports = { create, settings, isPts3, subjectOf, gameOf, embed, BOARD_NAME };

// node novigAlerts.js --dry [boards.json]: the saved boards' rows that would
// alert now, whatever their age (a saved quote has long expired). Posts nothing.
if (require.main === module) {
  const args = process.argv.slice(2);
  if (!args.includes('--dry')) { console.log('usage: node novigAlerts.js --dry [novig_scan_boards.json]'); process.exit(1); }
  const f = args.find(a => !a.startsWith('--')) || path.join(process.env.NBA_DATA_DIR || '/data/nba', 'novig_scan_boards.json');
  const boards = JSON.parse(fs.readFileSync(f, 'utf8'));
  const A = create({ env: Object.assign({}, process.env, { ALERTS_ENABLED: '1', ALERTS_DRY_RUN: '1' }) });
  let n = 0, would = 0;
  for (const [k, b] of Object.entries(boards)) {
    const [board, wide] = k.split(':');
    if (wide === '1') continue;
    for (const row of (b.rows || []).slice().sort((x, y) => y.ev - x.ev)) {
      n++;
      const why = A.verdict(board, row, { anyAge: true });
      if (!why) { would++; A.S.enabled = true; row.expires = Date.now() + 30000; A.consider(board, row, {}); }
    }
  }
  console.log(`${would} of ${n} saved rows would alert (EV ${A.S.minEv}%, Points + Threes ${A.S.minEvPts3}%)`);
}
