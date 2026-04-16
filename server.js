// Minimal Express server: serves /public and proxies image OCR to Anthropic.
// Keeps your API key server-side. Set ANTHROPIC_API_KEY in Railway's env vars.

const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json({ limit: '25mb' }));
app.use(express.static(path.join(__dirname, 'public'), { maxAge: '1h' }));

// ===== Deterministic leg normalization =====
// The model returns raw cells (market, bet_name, avg_fv). We build the canonical
// leg string here so the model can't mis-pair stat-type with line value.
const STAT_FROM_MARKET = [
  // order matters: check more specific first
  { re: /strikeout/i,             stat: 'Strikeouts',    valid: [4.5, 5.5, 6.5, 7.5] },
  { re: /earned\s*run/i,          stat: 'Earned Runs',   valid: [1.5, 2.5, 3.5] },
  { re: /walk/i,                  stat: 'Walks',         valid: [1.5, 2.5, 3.5] },
  { re: /hits?\s*allowed|hits?$/i,stat: 'Hits Allowed',  valid: [3.5, 4.5, 5.5] },
  { re: /out/i,                   stat: 'Outs Recorded', valid: [14.5, 15.5, 16.5, 17.5, 18.5] },
];

function normalizeLeg(market, betName) {
  if (!market || !betName) return null;
  const m = String(betName).match(/\b(Over|Under)\s+(\d+(?:\.\d+)?)/i);
  if (!m) return null;
  const direction = m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
  const line = parseFloat(m[2]);
  if (!isFinite(line)) return null;
  const hit = STAT_FROM_MARKET.find(s => s.re.test(market));
  if (!hit) return null;
  // Drop legs whose line value can't possibly belong to this stat type —
  // those are almost always a cross-row OCR mistake.
  if (!hit.valid.includes(line)) return null;
  return `${direction} ${line} ${hit.stat}`;
}

function complementFV(fv) {
  const f = Number(fv);
  if (!isFinite(f) || f === 0) return null;
  const p = f > 0 ? 100 / (f + 100) : -f / (-f + 100);
  const q = 1 - p;
  if (q <= 0 || q >= 1) return null;
  return q >= 0.5 ? -Math.round(q / (1 - q) * 100) : Math.round((1 - q) / q * 100);
}

// For every (pitcher, stat, line) that only has ONE direction, auto-add the other
// direction so correlations can be found in both orientations.
function addComplementLegs(rows) {
  const groups = Object.create(null);
  for (const r of rows) {
    const m = r.leg.match(/^(Over|Under)\s+([\d.]+)\s+(.+)$/i);
    if (!m) continue;
    const [, dir, line, stat] = m;
    const key = r.pitcher + '|' + stat + '|' + line;
    if (!groups[key]) groups[key] = {};
    groups[key][dir] = r;
  }
  const extras = [];
  for (const g of Object.values(groups)) {
    if (g.Over && !g.Under) {
      const fv = complementFV(g.Over.avg_fv);
      if (fv !== null)
        extras.push({ pitcher: g.Over.pitcher, leg: 'Under ' + g.Over.leg.slice(5), avg_fv: fv });
    } else if (g.Under && !g.Over) {
      const fv = complementFV(g.Under.avg_fv);
      if (fv !== null)
        extras.push({ pitcher: g.Under.pitcher, leg: 'Over ' + g.Under.leg.slice(6), avg_fv: fv });
    }
  }
  return [...rows, ...extras];
}

function normalizeRows(rows) {
  if (!Array.isArray(rows)) return [];
  const out = [];
  const seen = new Set();
  for (const r of rows) {
    if (!r || typeof r !== 'object') continue;
    // Backwards-compat: if the model still returned a pre-normalized "leg",
    // accept it as-is when no market/bet_name is present.
    let leg = null;
    if (r.market && r.bet_name) {
      leg = normalizeLeg(r.market, r.bet_name);
    } else if (typeof r.leg === 'string') {
      leg = r.leg;
    }
    if (!leg) continue;
    const pitcher = (r.pitcher || '').trim();
    if (!pitcher) continue;
    const fv = Number(r.avg_fv);
    if (!isFinite(fv)) continue;
    const key = pitcher + '|' + leg;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ pitcher, leg, avg_fv: fv });
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

YOUR TASK: For each data row, return ONE JSON object with FOUR raw cell values copied verbatim from that single row. Do NOT normalize, do NOT combine columns, do NOT infer values from other rows. Each row of JSON must come from exactly ONE row of the table.

═══ FIELDS TO RETURN (raw, per row) ═══
- pitcher: the player name (everything in bet_name BEFORE the word "Over" or "Under")
- market: the EXACT text from column 5 ("market"), verbatim. Examples: "Player Pitching Strikeouts", "Player Pitching Earned Runs Allowed", "Player Pitching Walks", "Player Pitching Hits Allowed", "Player Pitching Outs"
- bet_name: the EXACT text from column 6 ("bet_name"), verbatim. Examples: "Emerson Hancock Over 15.5", "Clay Holmes Under 2.5"
- avg_fv: the SIGNED INTEGER from column 14 ("avg_fv")

═══ ROW DISCIPLINE — THE #1 SOURCE OF BUGS ═══
The market and bet_name MUST come from the SAME row as the avg_fv. Use the row number (column 8 "L", a small integer like 1,2,3,...) as a positional anchor. Before emitting JSON for a row, ask:
- "Am I reading market, bet_name, and avg_fv all from the row whose L = X?"
If you cannot answer YES with the same X, you have crossed rows — re-align before emitting.

DO NOT cross rows. DO NOT pair the market from one row with the bet_name from another. The most common mistake is taking bet_name "Over 4.5" from a Strikeouts row and pairing it with "Earned Runs Allowed" market from a different row, or vice versa.

═══ CRITICAL COLUMN DISAMBIGUATION FOR avg_fv ═══
Three adjacent columns contain American odds. You MUST distinguish them:

Column 10 "odds": a PAIR like "+109 / -145" or "-120 / -111" — IGNORE THIS COLUMN
Column 13 "avg_odds": a PAIR like "-103 / -132" or "+128 / -183" — IGNORE THIS COLUMN
Column 14 "avg_fv": a SINGLE signed integer like "+114" or "-110" or "+158" — EXTRACT THIS VALUE

The first two columns have a "/" character. The avg_fv column has NO slash. If you see a value containing "/", you are reading the wrong column.

The avg_hold column (15) is a percentage like "7.0%" or "6.5%" — it is immediately to the right of avg_fv. Use that as a positional anchor: the signed integer IMMEDIATELY LEFT of the percentage column IS avg_fv.

═══ OVER vs UNDER — CRITICAL ═══
Each pitcher will often have BOTH an Over row and an Under row for the same line (e.g., "Jesus Luzardo Over 2.5" and "Jesus Luzardo Under 2.5"). These are TWO different bets with TWO different L numbers and TWO different avg_fv values. They may appear far apart in the table (e.g., L=3 is Under 4.5 Strikeouts and L=13 is Over 4.5 Strikeouts). Return BOTH as separate JSON objects. Read the word "Over" or "Under" directly from the bet_name column for each row independently and read avg_fv from THAT SAME ROW. Never carry forward an avg_fv value you saw on a different row, even if the pitcher, stat, and line look identical — the direction is different and so is the avg_fv. The Over and Under of the same stat+line WILL have different avg_fv values.

═══ WORKED EXAMPLES ═══
Table row: L=15, market="Player Pitching Outs", bet_name="Emerson Hancock Over 15.5", odds="-352 / +267", avg_odds="-436 / +287", avg_fv="-298", avg_hold="7.9%"
  RIGHT: {"pitcher":"Emerson Hancock","market":"Player Pitching Outs","bet_name":"Emerson Hancock Over 15.5","avg_fv":-298}
  WRONG: {"pitcher":"Emerson Hancock","market":"Player Pitching Earned Runs Allowed","bet_name":"Emerson Hancock Over 2.5","avg_fv":-298}  (market and bet_name pulled from a DIFFERENT row)

Table row: L=24, market="Player Pitching Earned Runs Allowed", bet_name="Emerson Hancock Over 4.5", odds="+168 / nan", avg_odds="+150 / -209", avg_fv="+181", avg_hold="7.1%"
  RIGHT: {"pitcher":"Emerson Hancock","market":"Player Pitching Earned Runs Allowed","bet_name":"Emerson Hancock Over 4.5","avg_fv":181}
  WRONG: {"pitcher":"Emerson Hancock","market":"Player Pitching Strikeouts","bet_name":"Emerson Hancock Over 4.5","avg_fv":181}  (market crossed from a different row)

═══ OUTPUT ═══
Return exactly this JSON shape, nothing else:
{"rows":[{"pitcher":"...","market":"...","bet_name":"...","avg_fv":123}, ...]}`;

    const body = {
      model: 'claude-opus-4-5',
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
      const rows = addComplementLegs(normalizeRows(parsed.rows));
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
      timeout: 60000,
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
