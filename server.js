// Minimal Express server: serves /public and proxies image OCR to Anthropic.
// Keeps your API key server-side. Set ANTHROPIC_API_KEY in Railway's env vars.

const express = require('express');
const compression = require('compression');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

/* Server-side diagnostic flag. Mirrors the DEBUG flag in public/index.html
   but lives in this process. Set DEBUG=true in env to see dedup collapses,
   OCR gaps, and other post-ingest diagnostics. No-op in production. */
const DEBUG = process.env.DEBUG === 'true';

app.use(compression());
app.use(express.json({ limit: '25mb' }));
app.use(express.static(path.join(__dirname, 'public'), { maxAge: '1h' }));

// ===== Deterministic leg normalization =====
// The model returns raw cells. We build the canonical leg string here so the
// model can't mis-pair stat-type with line value.
const STAT_FROM_MARKET = [
  // order matters: check more specific first
  { re: /strikeout/i,             stat: 'Strikeouts',    valid: [4.5, 5.5, 6.5, 7.5] },
  { re: /earned\s*run/i,          stat: 'Earned Runs',   valid: [1.5, 2.5, 3.5] },
  { re: /walk/i,                  stat: 'Walks',         valid: [1.5, 2.5, 3.5] },
  { re: /hits?\s*allowed|hits?$/i,stat: 'Hits Allowed',  valid: [3.5, 4.5, 5.5] },
  { re: /out/i,                   stat: 'Outs Recorded', valid: [14.5, 15.5, 16.5, 17.5, 18.5] },
];

function parseBetNameDirection(betName) {
  if (!betName) return null;
  const m = String(betName).match(/\b(Over|Under)\s+(\d+(?:\.\d+)?)/i);
  if (!m) return null;
  return {
    direction: m[1][0].toUpperCase() + m[1].slice(1).toLowerCase(),
    line: parseFloat(m[2]),
  };
}

function canonDirection(d) {
  if (!d) return null;
  const s = String(d).trim().toLowerCase();
  if (s === 'over' || s === 'o') return 'Over';
  if (s === 'under' || s === 'u') return 'Under';
  return null;
}

function normalizeLeg(market, direction, line) {
  if (!market || !direction || !isFinite(line)) return null;
  const hit = STAT_FROM_MARKET.find(s => s.re.test(market));
  if (!hit) return null;
  // Drop legs whose line value can't possibly belong to this stat type —
  // those are almost always a cross-row OCR mistake.
  if (!hit.valid.includes(line)) return null;
  return `${direction} ${line} ${hit.stat}`;
}

function normalizeRows(rows) {
  if (!Array.isArray(rows)) return [];
  const firstPass = [];
  const seen = new Set();
  rows.forEach((r, idx) => {
    if (!r || typeof r !== 'object') return;

    // Prefer the explicit direction/line fields when the model returned them
    // (asking for them as separate fields forces a more careful read of the
    // U/O letter than parsing it back out of the bet_name string).
    let direction = canonDirection(r.direction);
    let line = (r.line !== undefined && r.line !== null && r.line !== '') ? Number(r.line) : NaN;
    if (!direction || !isFinite(line)) {
      const parsed = parseBetNameDirection(r.bet_name);
      if (parsed) {
        if (!direction) direction = parsed.direction;
        if (!isFinite(line)) line = parsed.line;
      }
    }

    let leg = null;
    if (r.market && direction && isFinite(line)) {
      leg = normalizeLeg(r.market, direction, line);
    } else if (typeof r.leg === 'string') {
      leg = r.leg;
    }
    if (!leg) return;

    const pitcher = (r.pitcher || '').trim();
    if (!pitcher) return;
    const fv = Number(r.avg_fv);
    if (!isFinite(fv)) return;

    // Defense against OCR column-confusion: when the model picks a number from
    // the avg_odds pair ("+204 / -309") and returns it as avg_fv, it will
    // exactly match one half of that pair. Flag but don't drop — the user
    // sees a warning on the card and decides.
    const avgOddsRaw = String(r.avg_odds == null ? '' : r.avg_odds);
    const oddsPair = avgOddsRaw.match(/([+-]?\d+)\s*\/\s*([+-]?\d+)/);
    let fvSuspicious = false;
    if (oddsPair) {
      const oddsOver = Number(oddsPair[1]);
      const oddsUnder = Number(oddsPair[2]);
      if (fv === oddsOver || fv === oddsUnder) {
        fvSuspicious = true;
        console.warn('[suspicious_fv] L=' + (r.L != null ? r.L : '?') +
          ' ' + (r.bet_name || pitcher + ' ' + leg) +
          ': avg_fv=' + fv + ' matches avg_odds pair (' +
          oddsOver + '/' + oddsUnder + ') — OCR likely picked wrong column');
      }
    }

    if (DEBUG) {
      console.log('[ocr_raw]', r.L, r.bet_name, {
        avg_fv: r.avg_fv,
        avg_odds: r.avg_odds,
        fbc: r.fbc,
        _fv_suspicious: fvSuspicious,
      });
    }

    // First-pass dedupe by row number (L) — prevents two distinct sheet rows
    // from being collapsed when an OCR direction misread makes their
    // canonical leg strings collide. (Previously dedupe by pitcher|leg
    // silently dropped the second row, e.g. a Strikeouts Under row whose
    // direction was misread to Over collided with the real Over row.)
    const rowIdRaw = (r.L !== undefined && r.L !== null && r.L !== '') ? r.L : ('idx' + idx);
    const rowIdKey = String(rowIdRaw);
    const key = pitcher + '|' + rowIdKey;
    if (seen.has(key)) return;
    seen.add(key);

    // Carry L and books_count forward so collapseLegDupes can pick a
    // canonical row when the sheet (or OCR) emits multiple entries for the
    // same (pitcher, leg). Both fields are stripped from the final output.
    const L = Number.isFinite(Number(rowIdRaw)) ? Number(rowIdRaw) : -1;
    const booksCount = Number(r.books_count);
    firstPass.push({
      pitcher,
      leg,
      avg_fv: fv,
      _fv_suspicious: fvSuspicious,
      _L: L,
      _books: Number.isFinite(booksCount) ? booksCount : 0,
    });
  });
  return collapseLegDupes(firstPass).map(function(x) {
    return { pitcher: x.pitcher, leg: x.leg, avg_fv: x.avg_fv, _fv_suspicious: !!x._fv_suspicious };
  });
}

/* Second-pass collapse: group by (pitcher, leg), pick one canonical row.
   Preference order:
     1. Highest books_count  (more books = more robust FV, less OCR-artifact-y)
     2. Highest L            (newer row; assumes sheets are appended to)
   No averaging — we pick one row and use it whole so avg_fv stays
   self-consistent with whatever other fields of that row matter downstream. */
function collapseLegDupes(legs) {
  const groups = new Map();
  for (const l of legs) {
    const key = l.pitcher + '|' + l.leg;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(l);
  }
  const out = [];
  for (const [key, rows] of groups) {
    if (rows.length === 1) { out.push(rows[0]); continue; }
    rows.sort(function(a, b) {
      if (b._books !== a._books) return b._books - a._books;
      return b._L - a._L;
    });
    const winner = rows[0];
    if (DEBUG) {
      const losers = rows.slice(1).map(function(r) {
        return 'L=' + r._L + ' books=' + r._books + ' avg_fv=' + r.avg_fv;
      }).join(', ');
      console.log('[collapse] ' + key + ' — ' + rows.length + ' rows → winner L=' +
                  winner._L + ' books=' + winner._books + ' avg_fv=' + winner.avg_fv +
                  '; dropped: ' + losers);
    }
    out.push(winner);
  }
  return out;
}

app.post('/api/extract', async (req, res) => {
  try {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) return res.status(500).json({ error: 'ANTHROPIC_API_KEY not set on server' });

    const { image, mime } = req.body || {};
    if (!image) return res.status(400).json({ error: 'Missing image (base64) in body' });

    const prompt = `You are extracting MLB pitcher prop bets from a screenshot of a spreadsheet. Return ONLY valid JSON, no prose, no markdown fences.

The table header row contains these column names (left to right): league, date, time, game, market, bet_name, book, L, M, odds, limit, books_count, avg_odds, avg_fv, avg_hold, fbc, ev, qk.

YOUR TASK: For each data row, return ONE JSON object with cell values from that single row. Do NOT normalize, do NOT combine columns, do NOT infer values from other rows. Each row of JSON must come from exactly ONE row of the table. Emit one object per row — do NOT skip rows, do NOT merge rows.

═══ FIELDS TO RETURN (per row) ═══
- L: the integer in the "L" column, the small per-row index (1, 2, 3, ...). Required — anchors the row.
- pitcher: the player name (everything in bet_name BEFORE the word "Over" or "Under")
- market: the EXACT text from the "market" column. Examples: "Player Pitching Strikeouts", "Player Pitching Earned Runs Allowed", "Player Pitching Walks", "Player Pitching Hits Allowed", "Player Pitching Outs"
- bet_name: the EXACT text from the "bet_name" column. Examples: "Emerson Hancock Over 15.5", "Clay Holmes Under 2.5"
- direction: the word "Over" or "Under" — read it letter-by-letter from this row's bet_name cell
- line: the numeric line from this row's bet_name (4.5, 14.5, 16.5, etc.) as a number
- avg_odds: the EXACT text under the "avg_odds" header for this row, as a STRING. This cell always contains a PAIR of signed integers separated by "/". Preserve the format verbatim: "+204 / -309", "-101 / -136", "+150 / -209". If the cell is genuinely empty, return "".
- avg_fv: the SINGLE SIGNED INTEGER under the "avg_fv" header for this row. ONE number, not a pair. Examples: 261, -298, 117, -110.
- books_count: the UNSIGNED INTEGER under the "books_count" header. A small count like 2, 3, 5, 7, 8. If empty or non-numeric, return 0.

═══ HOW TO IDENTIFY THE avg_fv COLUMN — READ THIS CAREFULLY ═══
Do NOT count columns. Do NOT infer column position from neighbors. Do NOT use adjacent columns as positional anchors. Instead:

1. Locate the HEADER ROW at the top of the table. Visually find the text "avg_fv".
2. Read values straight DOWN from that specific header cell. For each data row, the avg_fv value is the cell directly under the "avg_fv" header.
3. The "avg_odds" header sits immediately to the LEFT of "avg_fv". Its cells contain TWO numbers separated by "/". That column is NOT avg_fv. Never substitute one for the other.

═══ MANDATORY SELF-CHECK BEFORE EMITTING EACH ROW ═══
For every row, verify these three conditions. If ANY fail, you are reading the wrong column — re-locate the "avg_fv" header and re-read.

(a) avg_fv is a SINGLE integer. It contains NO "/" character and NO space-separated second number.
(b) avg_fv is NOT numerically equal to either half of this row's avg_odds pair.
    If avg_odds is "+204 / -309" and you think avg_fv is -309, that's impossible — you copied from the wrong column.
    If avg_odds is "-101 / -136" and you think avg_fv is -101, that's impossible — same mistake.
(c) avg_fv is the value directly under the "avg_fv" header text, not under "avg_odds" or "avg_hold".

═══ ROW DISCIPLINE ═══
market, bet_name, direction, avg_odds, and avg_fv MUST all come from the SAME row. Use L as a positional anchor. Before emitting JSON for a row, ask: "Am I reading every field from the row whose L = X?" If not, re-align.

DO NOT cross rows. DO NOT pair the market from one row with the bet_name from another.

═══ OVER vs UNDER ═══
The same pitcher often appears in MULTIPLE rows with different directions and lines. For EACH row independently:
1. Locate the bet_name cell in the row whose L = X.
2. Read the literal letters after the player name — "Over" (O) or "Under" (U). Do NOT guess from context, do NOT infer from avg_fv sign.
3. Copy that exact word into "direction" AND keep it in the verbatim "bet_name". They MUST agree.

If the same pitcher has two rows with the same line+stat, one MUST be Over and the other MUST be Under. Never label both with the same direction.

═══ WORKED EXAMPLES ═══
CORRECT:
{"L":15,"pitcher":"Emerson Hancock","market":"Player Pitching Outs","bet_name":"Emerson Hancock Over 15.5","direction":"Over","line":15.5,"avg_odds":"-436 / +287","avg_fv":-298,"books_count":7}

CORRECT:
{"L":2,"pitcher":"Dean Kremer","market":"Player Pitching Strikeouts","bet_name":"Dean Kremer Over 5.5","direction":"Over","line":5.5,"avg_odds":"+204 / -309","avg_fv":261,"books_count":2}

CORRECT:
{"L":6,"pitcher":"Dean Kremer","market":"Player Pitching Outs","bet_name":"Dean Kremer Over 15.5","direction":"Over","line":15.5,"avg_odds":"-101 / -136","avg_fv":117,"books_count":4}

WRONG — the exact bug this prompt guards against:
{"L":2,"pitcher":"Dean Kremer","bet_name":"Dean Kremer Over 5.5","avg_odds":"+204 / -309","avg_fv":-309,"books_count":2}
  — avg_fv was copied from the avg_odds pair. ALWAYS WRONG. The real avg_fv (261) lives in the NEXT column to the right.

WRONG — direction flipped:
{"L":3,"bet_name":"Braxton Ashcraft Under 4.5","direction":"Over",...}
  — bet_name says "Under" but direction says "Over". They MUST agree.

═══ OUTPUT ═══
Return exactly this JSON shape, nothing else:
{"rows":[{"L":1,"pitcher":"...","market":"...","bet_name":"...","direction":"Over","line":4.5,"avg_odds":"+X / -Y","avg_fv":123,"books_count":7}, ...]}`;

    const body = {
      model: 'claude-opus-4-6',
      max_tokens: 4000,
      messages: [{
        role: 'user',
        content: [
          { type: 'image', source: { type: 'base64', media_type: mime || 'image/png', data: image } },
          { type: 'text', text: prompt }
        ]
      }]
    };

    const r = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify(body)
    });

    const j = await r.json();
    if (j.error) return res.status(500).json({ error: j.error.message || 'Anthropic API error', detail: j.error });

    const txt = j.content && j.content[0] && j.content[0].text || '';
    const m = txt.match(/\{[\s\S]*\}/);
    if (!m) return res.status(500).json({ error: 'Could not parse JSON from model output', raw: txt });

    try {
      const parsed = JSON.parse(m[0]);
      const rows = normalizeRows(parsed.rows);
      return res.json({ rows });
    } catch (e) {
      return res.status(500).json({ error: 'JSON parse error: ' + e.message, raw: m[0] });
    }
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
});

// ===== SGP AI Insight =====
app.post('/api/sgp-insight', async (req, res) => {
  try {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) return res.status(500).json({ error: 'ANTHROPIC_API_KEY not set on server' });

    const { prompt } = req.body || {};
    if (!prompt) return res.status(400).json({ error: 'Missing prompt in body' });

    const r = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 512,
        messages: [{ role: 'user', content: prompt }]
      })
    });

    const j = await r.json();
    if (j.error) return res.status(500).json({ error: j.error.message || 'Anthropic API error' });

    const text = (j.content && j.content[0] && j.content[0].text) || '';
    return res.json({ text });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
});

// ===== DraftKings SGP API proxy =====
// Uses a Python helper (dk_api.py) with curl_cffi for Chrome TLS impersonation
// to bypass DraftKings Akamai bot protection. Node.js fetch gets 403'd.
const { execFile } = require('child_process');
const DK_PY = path.join(__dirname, 'dk_api.py');

function dkCall(args, stdinData) {
  return new Promise((resolve, reject) => {
    const proc = require('child_process').spawn('python3', [DK_PY, ...args], {
      maxBuffer: 50 * 1024 * 1024,
      timeout: 130000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let stdout = '', stderr = '';
    proc.stdout.on('data', d => stdout += d);
    proc.stderr.on('data', d => stderr += d);
    proc.on('close', code => {
      if (code !== 0) return reject(new Error(stderr || 'dk_api.py exited with code ' + code));
      try { resolve(JSON.parse(stdout)); }
      catch (e) { reject(new Error('Failed to parse dk_api.py output: ' + stdout.slice(0, 200))); }
    });
    if (stdinData) { proc.stdin.write(stdinData); }
    proc.stdin.end();
  });
}

// GET /api/dk/games — today's MLB games from DraftKings
app.get('/api/dk/games', async (_req, res) => {
  try {
    const result = await dkCall(['games']);
    if (result.error) return res.status(500).json(result);
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK games fetch failed: ' + e.message });
  }
});

// GET /api/dk/markets/:eventId — all markets + selections for a game
app.get('/api/dk/markets/:eventId', async (req, res) => {
  try {
    const result = await dkCall(['markets', req.params.eventId]);
    if (result.error) return res.status(500).json(result);
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK markets fetch failed: ' + e.message });
  }
});

// GET /api/dk/featured/:eventId — auto-built and pre-priced SGPs for a game
app.get('/api/dk/featured/:eventId', async (req, res) => {
  try {
    const result = await dkCall(['featured', req.params.eventId]);
    if (result.error) return res.status(500).json(result);
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK featured fetch failed: ' + e.message });
  }
});

// POST /api/dk/find-sgps — unified: take OCR'd legs, match to DK, enumerate + price combos
app.post('/api/dk/find-sgps', async (req, res) => {
  try {
    const { legs } = req.body || {};
    if (!Array.isArray(legs) || !legs.length) return res.status(400).json({ error: 'legs array required' });
    const result = await dkCall(['find-sgps'], JSON.stringify(legs));
    if (result.error && !result.pitchers) return res.json(result);
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK find-sgps failed: ' + e.message });
  }
});

// POST /api/dk/find-sgps-teammate — batter teammate-pair SGP pricing.
// Request body: { candidates: [{ id, team, player_a, leg_a, player_b, leg_b }] }
// Response: { results: [{ id, matched, dk_odds, dk_decimal, missing? }], events_scanned, truncated? }
// Same Akamai-throttling story as find-sgps; per-call deadline ~110s.
app.post('/api/dk/find-sgps-teammate', async (req, res) => {
  try {
    const { candidates } = req.body || {};
    if (!Array.isArray(candidates) || !candidates.length) {
      return res.status(400).json({ error: 'candidates array required' });
    }
    const result = await dkCall(['find-sgps-teammate'], JSON.stringify({ candidates }));
    if (result.error && !result.results) return res.json(result);
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK find-sgps-teammate failed: ' + e.message });
  }
});

// POST /api/dk/price — get correlated SGP price from DraftKings
app.post('/api/dk/price', async (req, res) => {
  try {
    const { selections } = req.body;
    if (!Array.isArray(selections) || selections.length < 2)
      return res.status(400).json({ error: 'Need at least 2 selection IDs' });
    // Pass selection IDs via stdin to avoid shell escaping issues with # chars
    const result = await dkCall(['price'], JSON.stringify(selections));
    if (result.error) return res.json(result);
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK price fetch failed: ' + e.message });
  }
});

// ===== MLB Lineups =====
// GET /api/lineups?date=YYYY-MM-DD
// Pulls tonight's slate + batting orders from the free MLB Stats API.
//
// Endpoints used:
//   https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=<DATE>&hydrate=probablePitcher,lineups,team
//   https://statsapi.mlb.com/api/v1/game/<gamePk>/boxscore
//   https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=<ID>&startDate=<D-3>&endDate=<D-1>
//     (used to locate a projected-lineup source when tonight's lineup isn't posted yet)
//
// Status values returned:
//   confirmed  — MLB has posted both full 9-batter orders in the schedule hydrate
//   projected  — hydrate was empty, so we fell back to the team's most recent played
//                game's batting order as a guess
//   awaiting   — no hydrate lineup and no recent played game found (early in season
//                or for a team that just returned from an off-day)
//
// Cache: per-date, 10-minute TTL. Long enough to absorb refresh clicks, short
// enough that a confirmed lineup shows up quickly after MLB posts it.

const LINEUP_CACHE = new Map();          // key: date, val: { ts, body }
const LINEUP_CACHE_TTL_MS = 10 * 60 * 1000;
const BOXSCORE_CACHE = new Map();        // key: gamePk, val: { ts, data }
const BOXSCORE_CACHE_TTL_MS = 60 * 60 * 1000;
const PERSON_CACHE = new Map();          // key: personId, val: { batSide, primaryPosition, fullName }

async function mlbApi(pathAndQuery) {
  const url = 'https://statsapi.mlb.com' + pathAndQuery;
  const r = await fetch(url);
  if (!r.ok) throw new Error('MLB Stats API ' + r.status + ' on ' + pathAndQuery);
  return r.json();
}

async function getBoxscore(gamePk) {
  const hit = BOXSCORE_CACHE.get(gamePk);
  if (hit && Date.now() - hit.ts < BOXSCORE_CACHE_TTL_MS) return hit.data;
  const j = await mlbApi('/api/v1/game/' + gamePk + '/boxscore');
  BOXSCORE_CACHE.set(gamePk, { ts: Date.now(), data: j });
  return j;
}

// Batched person lookup. Boxscore person records are stripped down (no
// batSide) and hitting /api/v1/people/<id> 180 times per slate is abusive,
// so we cache per-ID forever and fetch missing IDs in chunks of 100.
async function enrichPeople(personIds) {
  const missing = [];
  for (const id of personIds) { if (id != null && !PERSON_CACHE.has(id)) missing.push(id); }
  if (!missing.length) return;
  const CHUNK = 100;
  for (let i = 0; i < missing.length; i += CHUNK) {
    const ids = missing.slice(i, i + CHUNK);
    try {
      const j = await mlbApi('/api/v1/people?personIds=' + ids.join(','));
      for (const p of (j.people || [])) {
        PERSON_CACHE.set(p.id, {
          batSide: (p.batSide && p.batSide.code) || null,
          primaryPosition: (p.primaryPosition && p.primaryPosition.abbreviation) || null,
          fullName: p.fullName || null,
        });
      }
    } catch (e) {
      if (DEBUG) console.warn('[lineups] person enrich failed for', ids.length, 'ids:', e.message);
    }
  }
}

// Build a { personId -> { position, hand } } lookup for a game from its
// boxscore. batSide lives on the nested `person` object; the top-level
// `position` is this player's position in THIS game.
function extractPlayerMetaFromBoxscore(box, side) {
  const out = {};
  const team = box && box.teams && box.teams[side];
  if (!team || !team.players) return out;
  for (const key of Object.keys(team.players)) {
    const p = team.players[key];
    if (!p || !p.person) continue;
    const person = p.person;
    out[person.id] = {
      fullName: person.fullName || null,
      position: (p.position && p.position.abbreviation) || null,
      hand: (person.batSide && person.batSide.code) || null,
      battingOrder: p.battingOrder ? parseInt(p.battingOrder, 10) : null,
    };
  }
  return out;
}

function normalizeHydratePlayer(p, slot, metaById) {
  if (!p) return null;
  const id = p.id || (p.person && p.person.id) || null;
  const meta = id != null ? (metaById[id] || {}) : {};
  return {
    player: p.fullName || (p.person && p.person.fullName) || meta.fullName || null,
    slot,
    position: (p.primaryPosition && p.primaryPosition.abbreviation) || meta.position || null,
    hand: (p.batSide && p.batSide.code) || meta.hand || null,
    mlbam_id: id,
  };
}

// Pre-game lineup from a boxscore (projected-lineup fallback). battingOrder in
// boxscore is "100"/"200"/.../"900" for slots 1-9, starter vs. substitute
// encoded in the trailing two digits. We only keep starters (orderPos ending
// in "00") and take the first 9 by ascending order.
function lineupFromBoxscore(box, side) {
  const team = box && box.teams && box.teams[side];
  if (!team || !team.players) return [];
  const starters = [];
  for (const key of Object.keys(team.players)) {
    const p = team.players[key];
    if (!p || !p.battingOrder) continue;
    const bo = parseInt(p.battingOrder, 10);
    if (!Number.isFinite(bo) || bo % 100 !== 0) continue; // keep slot-100 starters only
    starters.push({
      slot: bo / 100,
      player: p.person && p.person.fullName,
      position: (p.position && p.position.abbreviation) || null,
      hand: (p.person && p.person.batSide && p.person.batSide.code) || null,
      mlbam_id: p.person && p.person.id,
    });
  }
  starters.sort((a, b) => a.slot - b.slot);
  return starters.slice(0, 9);
}

function shiftDateYmd(dateStr, days) {
  const d = new Date(dateStr + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

// Look back up to 3 days for a team's most recent completed game; return its
// gamePk or null. We go day-by-day (rather than one 3-day range call) so the
// most-recent game wins even when MLB returns dates in ascending order.
async function findRecentGameForTeam(teamId, beforeDate) {
  for (let back = 1; back <= 3; back++) {
    const d = shiftDateYmd(beforeDate, -back);
    try {
      const j = await mlbApi(
        '/api/v1/schedule?sportId=1&teamId=' + teamId + '&date=' + d
      );
      const dates = j.dates || [];
      for (const dd of dates) {
        for (const g of (dd.games || [])) {
          const state = g.status && g.status.abstractGameState;
          // Only "Final" games have a batting order we can trust as the most
          // recent posted lineup. "Postponed" or "Cancelled" won't.
          if (state === 'Final') return g.gamePk;
        }
      }
    } catch (_) { /* swallow and try the next day back */ }
  }
  return null;
}

async function buildGameEntry(g) {
  const homeTeam = g.teams.home.team || {};
  const awayTeam = g.teams.away.team || {};
  const homeTeamId = homeTeam.id;
  const awayTeamId = awayTeam.id;
  const hydrateHome = (g.lineups && g.lineups.homePlayers) || [];
  const hydrateAway = (g.lineups && g.lineups.awayPlayers) || [];

  // Pull a boxscore for position/hand enrichment when lineups ARE posted —
  // hydrate player shapes vary and often omit batSide. We also reuse the
  // boxscore for projected-lineup fallback below if hydrate is empty.
  let box = null;
  try { box = await getBoxscore(g.gamePk); } catch (_) { box = null; }
  const homeMeta = box ? extractPlayerMetaFromBoxscore(box, 'home') : {};
  const awayMeta = box ? extractPlayerMetaFromBoxscore(box, 'away') : {};

  let homeLineup = hydrateHome.map((p, i) => normalizeHydratePlayer(p, i + 1, homeMeta)).filter(Boolean);
  let awayLineup = hydrateAway.map((p, i) => normalizeHydratePlayer(p, i + 1, awayMeta)).filter(Boolean);

  let status = 'awaiting';
  if (homeLineup.length === 9 && awayLineup.length === 9) {
    status = 'confirmed';
  } else {
    // Projected fallback: replace whichever side is empty with that team's
    // most recent completed game's lineup. Each side is handled independently
    // because a split-squad scenario (or just late-posting home team) can
    // leave one side confirmed while the other isn't.
    const needs = [];
    if (homeLineup.length !== 9 && homeTeamId != null) needs.push({ side: 'home', teamId: homeTeamId });
    if (awayLineup.length !== 9 && awayTeamId != null) needs.push({ side: 'away', teamId: awayTeamId });
    let anyProjected = false;
    for (const n of needs) {
      const recentPk = await findRecentGameForTeam(n.teamId, String(g.gameDate || '').slice(0, 10) || null);
      if (!recentPk) continue;
      let recentBox;
      try { recentBox = await getBoxscore(recentPk); } catch (_) { continue; }
      const lineup = lineupFromBoxscore(recentBox, n.side);
      if (lineup.length === 9) {
        if (n.side === 'home') homeLineup = lineup; else awayLineup = lineup;
        anyProjected = true;
      }
    }
    if (homeLineup.length === 9 && awayLineup.length === 9 && anyProjected) status = 'projected';
  }

  return {
    game_id: String(g.gamePk),
    home_team: homeTeam.name || null,
    away_team: awayTeam.name || null,
    home_team_abbr: homeTeam.abbreviation || null,
    away_team_abbr: awayTeam.abbreviation || null,
    game_time: g.gameDate || null,
    home_lineup: homeLineup,
    away_lineup: awayLineup,
    home_sp: (g.teams.home.probablePitcher && g.teams.home.probablePitcher.fullName) || null,
    away_sp: (g.teams.away.probablePitcher && g.teams.away.probablePitcher.fullName) || null,
    status,
  };
}

async function buildLineupsForDate(date) {
  const sched = await mlbApi(
    '/api/v1/schedule?sportId=1&date=' + encodeURIComponent(date) +
    '&hydrate=probablePitcher,lineups,team'
  );
  const games = [];
  for (const d of (sched.dates || [])) {
    for (const g of (d.games || [])) {
      // Skip obvious non-regular-game rows (spring training, exhibition, all-star).
      // gameType 'R' = regular, 'P' = postseason, 'F'/'D'/'L'/'W' = wildcard/division/league/world series.
      // We accept all of those; skip only 'S' (spring) and 'E' (exhibition).
      if (g.gameType === 'S' || g.gameType === 'E') continue;
      try {
        games.push(await buildGameEntry(g));
      } catch (e) {
        if (DEBUG) console.warn('[lineups] skipped game', g.gamePk, e.message);
      }
    }
  }

  // Second pass: enrich any player whose batSide wasn't set (projected
  // lineups come from boxscore.person which is stripped down — the real
  // batSide only lives on /api/v1/people). One batched call covers every
  // batter across the slate.
  const idsNeeded = [];
  for (const gm of games) {
    for (const side of ['home_lineup', 'away_lineup']) {
      for (const p of gm[side]) {
        if (p.mlbam_id != null && (p.hand == null || p.position == null)) {
          idsNeeded.push(p.mlbam_id);
        }
      }
    }
  }
  if (idsNeeded.length) {
    await enrichPeople(idsNeeded);
    for (const gm of games) {
      for (const side of ['home_lineup', 'away_lineup']) {
        for (const p of gm[side]) {
          const meta = p.mlbam_id != null ? PERSON_CACHE.get(p.mlbam_id) : null;
          if (!meta) continue;
          if (p.hand == null) p.hand = meta.batSide;
          if (p.position == null) p.position = meta.primaryPosition;
        }
      }
    }
  }

  return {
    date,
    lineups_confirmed_at: new Date().toISOString(),
    games,
  };
}

app.get('/api/lineups', async (req, res) => {
  const date = (String(req.query.date || '').trim()) ||
               new Date().toISOString().slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return res.status(400).json({ error: 'date must be YYYY-MM-DD' });
  }
  const cached = LINEUP_CACHE.get(date);
  if (cached && Date.now() - cached.ts < LINEUP_CACHE_TTL_MS) {
    return res.json(cached.body);
  }
  try {
    const body = await buildLineupsForDate(date);
    LINEUP_CACHE.set(date, { ts: Date.now(), body });
    return res.json(body);
  } catch (e) {
    return res.status(500).json({ error: 'lineups fetch failed: ' + e.message });
  }
});

app.get('/healthz', (_req, res) => res.send('ok'));

app.listen(PORT, '0.0.0.0', () => console.log('Listening on 0.0.0.0:' + PORT));
