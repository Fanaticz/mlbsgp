// Read-only calls to the owner's Novig account (docs.novig.com), signed with
// his API key. Used to see what bets he already holds, so the alerts can leave
// those out. Nothing here places, cancels or moves anything: every call is a GET.
//
//   NOVIG_KEY_ID        the key's id (shown beside the key on novig.com: Profile, Settings, Novig API)
//   NOVIG_PRIVATE_KEY   the key's private half: the contents of the .pem file it downloaded
//                       (pasted whole; "\n" written out and a base64 of the file are read too)
// Neither is ever logged or sent to the page.
const crypto = require('crypto');

const HOST = (process.env.NOVIG_HOST || 'https://api.novig.com').replace(/\/+$/, '');

// Line 5 of the string to sign: each pair decoded and re-encoded (everything
// but A-Z a-z 0-9 - . _ ~ as %XX, uppercase), sorted by name then value.
function canonicalQuery(raw) {
  const enc = s => {
    let dec;
    try { dec = decodeURIComponent(s); } catch (_) { dec = s; }
    return Array.from(Buffer.from(dec, 'utf8')).map(b => (/[A-Za-z0-9\-._~]/.test(String.fromCharCode(b)) ? String.fromCharCode(b) : '%' + b.toString(16).toUpperCase().padStart(2, '0'))).join('');
  };
  const cmp = (a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b));
  return String(raw || '').split('&').filter(Boolean).map(p => { const i = p.indexOf('='); return i < 0 ? [enc(p), ''] : [enc(p.slice(0, i)), enc(p.slice(i + 1))]; })
    .sort((a, b) => cmp(a[0], b[0]) || cmp(a[1], b[1])).map(([k, v]) => `${k}=${v}`).join('&');
}
// The six NOVIG-V3 lines.
const stringToSign = (ts, method, path, query, body) => ['NOVIG-V3', String(ts), String(method).toUpperCase(), path, canonicalQuery(query),
  crypto.createHash('sha256').update(body || '').digest('hex')].join('\n');

function loadKey(text) {
  let pem = String(text || '').trim().replace(/\\n/g, '\n');
  if (pem && !pem.includes('BEGIN')) { try { pem = Buffer.from(pem, 'base64').toString('utf8'); } catch (_) { /* not base64 */ } }
  if (!pem.includes('BEGIN')) return null;
  try { return crypto.createPrivateKey(pem); } catch (_) { return null; }
}
// Ed25519 signs the string itself; P-256 is ECDSA over its SHA-256, DER-encoded (Node's default).
const sign = (key, text) => crypto.sign(key.asymmetricKeyType === 'ed25519' ? null : 'sha256', Buffer.from(text, 'utf8'), key).toString('base64');

function create(env, doFetch) {
  env = env || process.env; doFetch = doFetch || fetch;
  const id = String(env.NOVIG_KEY_ID || '').trim(), key = loadKey(env.NOVIG_PRIVATE_KEY);
  const ready = !!(id && key);
  // GET only. Returns { status, body } (body parsed when it is JSON).
  async function get(pathAndQuery) {
    if (!ready) throw new Error(!id ? 'NOVIG_KEY_ID is not set' : 'NOVIG_PRIVATE_KEY is not set or is not a private key file');
    const [path, query] = pathAndQuery.split('?');
    const ts = Date.now();
    const r = await doFetch(HOST + pathAndQuery, { method: 'GET', signal: AbortSignal.timeout(20000),
      headers: { Accept: 'application/json', 'Novig-Key-Id': id, 'Novig-Timestamp': String(ts), 'Novig-Signature': sign(key, stringToSign(ts, 'GET', path, query || '', '')) } });
    const text = await r.text();
    let body = text.slice(0, 300);
    try { body = JSON.parse(text); } catch (_) { /* the edge answers a refusal with a page */ }
    return { status: r.status, body };
  }

  // What the account's reads look like, for deciding whether parlay bets can
  // be read at all (11-19: the docs describe a position as one market and one
  // outcome, and say nothing of a parlay on the bettor's side). Each route's
  // status, how many rows per wallet, the field names, and the first rows with
  // their markets named from the public catalog. Wallet ids are cut short.
  async function probe() {
    const out = { at: Date.now(), host: HOST, routes: [] };
    const name = new Map();
    const market = async mid => {
      if (!mid || name.has(mid)) return name.get(mid);
      let d = null;
      try { const r = await doFetch(`${HOST}/v3/public/catalog/markets/${mid}`, { signal: AbortSignal.timeout(15000) }); d = r.ok ? await r.json() : { missing: r.status }; } catch (_) { d = { missing: 'no answer' }; }
      name.set(mid, d);
      return d;
    };
    for (const p of ['/v3/time', '/v3/account/geolocation', '/v3/portfolio/positions', '/v3/account/positions', '/v3/history/positions?limit=25', '/v3/portfolio/fills?limit=25', '/v3/account/transactions?limit=25']) {
      const row = { route: p };
      try {
        const r = await get(p);
        row.status = r.status;
        if (r.status !== 200) { row.answer = typeof r.body === 'string' ? r.body.slice(0, 160) : r.body; out.routes.push(row); continue; }
        // A management key's answer is { wallet key id: rows }; a paged one is { items }.
        const wallets = Array.isArray(r.body) ? { own: r.body } : r.body && Array.isArray(r.body.items) ? { own: r.body.items }
          : r.body && typeof r.body === 'object' && Object.values(r.body).every(v => Array.isArray(v) || (v && Array.isArray(v.items))) && Object.keys(r.body).length
            ? Object.fromEntries(Object.entries(r.body).map(([k, v]) => [k.slice(0, 8), Array.isArray(v) ? v : v.items])) : null;
        if (!wallets) { row.answer = r.body; out.routes.push(row); continue; }
        row.wallets = {};
        for (const [w, rows] of Object.entries(wallets)) {
          const first = [];
          for (const x of rows.slice(0, 12)) {
            const y = Object.assign({}, x);
            if (x.marketId) {
              const m = await market(x.marketId);
              y.market = m && m.missing ? `not in the public catalog (${m.missing})` : m ? `${m.marketType}: ${m.description}` : undefined;
              const o = m && (m.outcomes || []).find(o => o.outcomeId === x.outcomeId);
              if (o) y.outcome = o.name;
            }
            first.push(y);
          }
          row.wallets[w] = { rows: rows.length, fields: [...new Set(rows.flatMap(x => Object.keys(x)))], first };
        }
      } catch (e) { row.error = e.name === 'TimeoutError' ? 'no answer' : e.message; }
      out.routes.push(row);
    }
    return out;
  }
  return { ready, get, probe };
}

module.exports = { create, canonicalQuery, stringToSign, loadKey, sign };
