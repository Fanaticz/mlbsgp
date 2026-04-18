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
      _L: L,
      _books: Number.isFinite(booksCount) ? booksCount : 0,
    });
  });
  return collapseLegDupes(firstPass).map(function(x) {
    return { pitcher: x.pitcher, leg: x.leg, avg_fv: x.avg_fv };
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

The table header row contains these 18 columns in this left-to-right order:
1=league  2=date  3=time  4=game  5=market  6=bet_name  7=book  8=L  9=M  10=odds  11=limit  12=books_count  13=avg_odds  14=avg_fv  15=avg_hold  16=fbc  17=ev  18=qk

YOUR TASK: For each data row, return ONE JSON object with raw cell values copied verbatim from that single row. Do NOT normalize, do NOT combine columns, do NOT infer values from other rows. Each row of JSON must come from exactly ONE row of the table. Emit one object per row — do NOT skip rows, do NOT merge rows.

═══ FIELDS TO RETURN (raw, per row) ═══
- L: the integer in column 8 ("L"), the small per-row index (1, 2, 3, ...). Required — this anchors the row.
- pitcher: the player name (everything in bet_name BEFORE the word "Over" or "Under")
- market: the EXACT text from column 5 ("market"), verbatim. Examples: "Player Pitching Strikeouts", "Player Pitching Earned Runs Allowed", "Player Pitching Walks", "Player Pitching Hits Allowed", "Player Pitching Outs"
- bet_name: the EXACT text from column 6 ("bet_name"), verbatim. Examples: "Emerson Hancock Over 15.5", "Clay Holmes Under 2.5"
- direction: the word "Over" or "Under" — read it letter-by-letter from this row's bet_name cell. Do NOT copy from a neighbouring row.
- line: the numeric line value from this row's bet_name (4.5, 14.5, 16.5, etc.) as a number, not a string.
- avg_fv: the SIGNED INTEGER from column 14 ("avg_fv")
- books_count: the UNSIGNED INTEGER from column 12 ("books_count"), a small count like 2, 3, 5, 7, 8 that tells us how many sportsbooks contributed to the averaged lines. If the cell is empty or non-numeric, return 0.

═══ ROW DISCIPLINE — THE #1 SOURCE OF BUGS ═══
The market, bet_name, direction, and avg_fv MUST come from the SAME row. Use L (column 8) as a positional anchor. Before emitting JSON for a row, ask:
- "Am I reading market, bet_name, direction, line, AND avg_fv all from the row whose L = X?"
If you cannot answer YES with the same X, you have crossed rows — re-align before emitting.

DO NOT cross rows. DO NOT pair the market from one row with the bet_name from another. The most common mistake is taking bet_name "Over 4.5" from a Strikeouts row and pairing it with "Earned Runs Allowed" market from a different row, or vice versa.

═══ CRITICAL COLUMN DISAMBIGUATION FOR avg_fv ═══
Three adjacent columns contain American odds. You MUST distinguish them:

Column 10 "odds": a PAIR like "+109 / -145" or "-120 / -111" — IGNORE THIS COLUMN
Column 13 "avg_odds": a PAIR like "-103 / -132" or "+128 / -183" — IGNORE THIS COLUMN
Column 14 "avg_fv": a SINGLE signed integer like "+114" or "-110" or "+158" — EXTRACT THIS VALUE

The first two columns have a "/" character. The avg_fv column has NO slash. If you see a value containing "/", you are reading the wrong column.

The avg_hold column (15) is a percentage like "7.0%" or "6.5%" — it is immediately to the right of avg_fv. Use that as a positional anchor: the signed integer IMMEDIATELY LEFT of the percentage column IS avg_fv.

═══ OVER vs UNDER — CRITICAL — READ THE LETTER, NOT THE PATTERN ═══
The same pitcher will often appear in MULTIPLE rows of the sheet, with DIFFERENT directions and lines (e.g. row 3 might be "Braxton Ashcraft Under 4.5" Strikeouts and row 13 might be "Braxton Ashcraft Over 4.5" Strikeouts — those are two SEPARATE rows for two SEPARATE bets). For EACH row independently:
1. Locate the bet_name cell for the row whose L = X.
2. Read the literal letters after the player name. The next word is either "Over" (starts with O) or "Under" (starts with U). Do NOT guess from context, do NOT infer from the avg_fv sign, do NOT infer from a similar pitcher row elsewhere.
3. Copy that exact word into the "direction" field AND keep it inside the verbatim "bet_name" field. They MUST agree.

If the same pitcher has two rows with the same line+stat (e.g., two "Ashcraft 4.5 Strikeouts" rows), one MUST be Over and the other MUST be Under. Never label both with the same direction.

═══ WORKED EXAMPLES ═══
Table row: L=15, market="Player Pitching Outs", bet_name="Emerson Hancock Over 15.5", odds="-352 / +267", books_count=7, avg_odds="-436 / +287", avg_fv="-298", avg_hold="7.9%"
  RIGHT: {"L":15,"pitcher":"Emerson Hancock","market":"Player Pitching Outs","bet_name":"Emerson Hancock Over 15.5","direction":"Over","line":15.5,"avg_fv":-298,"books_count":7}
  WRONG: {"L":15,"pitcher":"Emerson Hancock","market":"Player Pitching Earned Runs Allowed","bet_name":"Emerson Hancock Over 2.5","direction":"Over","line":2.5,"avg_fv":-298,"books_count":7}  (market and bet_name pulled from a DIFFERENT row)

Table row: L=24, market="Player Pitching Earned Runs Allowed", bet_name="Emerson Hancock Over 4.5", odds="+168 / nan", books_count=4, avg_odds="+150 / -209", avg_fv="+181", avg_hold="7.1%"
  RIGHT: {"L":24,"pitcher":"Emerson Hancock","market":"Player Pitching Earned Runs Allowed","bet_name":"Emerson Hancock Over 4.5","direction":"Over","line":4.5,"avg_fv":181,"books_count":4}

Table row: L=3, market="Player Pitching Strikeouts", bet_name="Braxton Ashcraft Under 4.5", odds="+109 / -139", books_count=8, avg_odds="+100 / -132", avg_fv="+115", avg_hold="6.5%"
  RIGHT: {"L":3,"pitcher":"Braxton Ashcraft","market":"Player Pitching Strikeouts","bet_name":"Braxton Ashcraft Under 4.5","direction":"Under","line":4.5,"avg_fv":115,"books_count":8}
  WRONG: {"L":3,"pitcher":"Braxton Ashcraft","market":"Player Pitching Strikeouts","bet_name":"Braxton Ashcraft Over 4.5","direction":"Over","line":4.5,"avg_fv":115,"books_count":8}  (direction flipped — the bet_name cell says "Under", not "Over")

═══ OUTPUT ═══
Return exactly this JSON shape, nothing else:
{"rows":[{"L":1,"pitcher":"...","market":"...","bet_name":"...","direction":"Over","line":4.5,"avg_fv":123,"books_count":7}, ...]}`;

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

app.get('/healthz', (_req, res) => res.send('ok'));

app.listen(PORT, '0.0.0.0', () => console.log('Listening on 0.0.0.0:' + PORT));
