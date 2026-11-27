// Minimal Express server: serves /public and proxies image OCR to Anthropic.
// Keeps your API key server-side. Set ANTHROPIC_API_KEY in Railway's env vars.

const express = require('express');
const compression = require('compression');
const path = require('path');
/* foldAscii: NFKD-fold + strip combining marks. Used to normalize player
   names at every boundary so the FV-sheet OCR (ASCII), MLB Stats API
   lineup hydrate (diacritic), and TEAMMATE_DATA aggregates (ASCII) all
   join cleanly. See public/utils/nameNormalize.js for the canonical impl. */
const { foldAscii } = require('./public/utils/nameNormalize.js');

const app = express();
const PORT = process.env.PORT || 3000;
// Railway's edge is the one proxy in front: req.ip is the caller's address as the edge saw it,
// not what the caller wrote in X-Forwarded-For. The passcode lockout below counts by it.
app.set('trust proxy', 1);

/* Server-side diagnostic flag. Mirrors the DEBUG flag in public/index.html
   but lives in this process. Set DEBUG=true in env to see dedup collapses,
   OCR gaps, and other post-ingest diagnostics. No-op in production. */
const DEBUG = process.env.DEBUG === 'true';

app.use(compression());
app.use(express.json({ limit: '25mb' }));
app.use(express.static(path.join(__dirname, 'public'), {
  /* Default per-file cache window. Keeps the big public/data/*.json
     aggregates (~30 MB) cacheable for an hour — they only change on
     aggregator rebuilds and aren't iteration-sensitive. */
  maxAge: '1h',
  /* Override for the three iteration-sensitive asset classes.
     Motivating case (2026-04-20): PR #37 merged to main + deployed
     to Railway, but iPhone Safari kept serving the pre-PR bundle for
     ~an hour because index.html + /utils/*.js were cached under the
     blanket 1h maxAge. User saw old UI, stale diagnostic-panel rows,
     and the "Logan O'Hoppe team=(none)" bug that PR #37 had already
     fixed — until the cache expired.
     Switching these to `no-cache` means every page load revalidates
     against the server via ETag/Last-Modified. If the file hasn't
     changed, Express returns 304 and the client uses its local copy
     (fast). If it has, the new bytes go out immediately (correct).
     Small files (index.html ~133 KB, each utils/*.js ~2-20 KB) so
     the revalidate cost is negligible vs the stale-bundle confusion
     it prevents. */
  setHeaders(res, filePath) {
    if (filePath.endsWith('.html') || filePath.endsWith('.js') || filePath.endsWith('.css')) {
      res.setHeader('Cache-Control', 'no-cache');
    }
  },
}));

// ===== Deterministic leg normalization =====
// The model returns raw cells. We build the canonical leg string here so the
// model can't mis-pair stat-type with line value.
const STAT_FROM_MARKET = [
  // order matters: check more specific first
  { re: /strikeout/i,             stat: 'Strikeouts',    valid: [3.5, 4.5, 5.5, 6.5, 7.5] },
  { re: /earned\s*run/i,          stat: 'Earned Runs',   valid: [1.5, 2.5, 3.5] },
  { re: /walk/i,                  stat: 'Walks',         valid: [1.5, 2.5, 3.5] },
  { re: /hits?\s*allowed|hits?$/i,stat: 'Hits Allowed',  valid: [3.5, 4.5, 5.5] },
  { re: /out/i,                   stat: 'Outs Recorded', valid: [14.5, 15.5, 16.5, 17.5, 18.5] },
];

/* Strip invalid leading "+" from JSON number literals in the model's
   response. Vision occasionally echoes American odds like "+185" verbatim
   into a number context (e.g. `"avg_fv": +185`), which JSON.parse rejects
   with "Unexpected token '+'". Only touches "+" that appears at a value
   position (after `:`, `,`, or `[`) immediately before a digit, so quoted
   strings like `"avg_odds": "+204 / -309"` are left intact. */
function sanitizeModelJson(s) {
  return s.replace(/([:\[,]\s*)\+(?=\d)/g, '$1');
}

function parseBetNameDirection(betName) {
  if (!betName) return null;
  const m = String(betName).match(/^(.*?)\s+(Over|Under)\s+(\d+(?:\.\d+)?)/i);
  if (!m) return null;
  return {
    pitcher: m[1].trim(),
    direction: m[2][0].toUpperCase() + m[2].slice(1).toLowerCase(),
    line: parseFloat(m[3]),
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

    /* bet_name is authoritative for direction + line. The 2026-04-30 trace
       showed the model emitting bet_name="Bryce Elder Over 3.5" with
       line:5.5 — a misread of the digit. Trusting the explicit `line`
       field then mislabels the row as Over 5.5 Strikeouts and drags the
       wrong row's avg_fv into a real leg. bet_name has more redundancy
       (letters + digits + name), so it's the safer source of truth. */
    const fromBetName = parseBetNameDirection(r.bet_name);
    const explicitDir = canonDirection(r.direction);
    const explicitLine = (r.line !== undefined && r.line !== null && r.line !== '')
      ? Number(r.line) : NaN;
    let direction, line;
    if (fromBetName) {
      direction = fromBetName.direction;
      line = fromBetName.line;
      if ((explicitDir && explicitDir !== direction) ||
          (isFinite(explicitLine) && explicitLine !== line)) {
        console.warn('[bet_name_disagree] L=' + (r.L != null ? r.L : '?') +
          ' bet_name=' + JSON.stringify(r.bet_name) +
          ' → ' + direction + ' ' + line +
          ' but explicit fields say ' + explicitDir + ' ' + explicitLine +
          ' — using bet_name');
      }
    } else {
      direction = explicitDir;
      line = explicitLine;
    }

    let leg = null;
    if (r.market && direction && isFinite(line)) {
      leg = normalizeLeg(r.market, direction, line);
    } else if (typeof r.leg === 'string') {
      leg = r.leg;
    }
    if (!leg) return;

    /* Pitcher name: same authority rule as direction/line. The 2026-04-30
       trace showed the model emitting pitcher="Chris Bassitt" with
       bet_name="Peter Lambert Over 5.5" — a row-level player swap that
       silently put Lambert's Over 5.5 K (+177) on Bassitt's card. Pull
       the name from bet_name when we can; warn when the explicit field
       disagrees. */
    const explicitPitcher = (r.pitcher || '').trim();
    let pitcher = (fromBetName && fromBetName.pitcher) || explicitPitcher;
    if (fromBetName && fromBetName.pitcher && explicitPitcher &&
        fromBetName.pitcher.toLowerCase() !== explicitPitcher.toLowerCase()) {
      console.warn('[pitcher_disagree] L=' + (r.L != null ? r.L : '?') +
        ' bet_name pitcher=' + JSON.stringify(fromBetName.pitcher) +
        ' but explicit pitcher=' + JSON.stringify(explicitPitcher) +
        ' — using bet_name');
    }
    pitcher = pitcher.trim();
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
     2. Lowest L             (first occurrence in sheet — the model reads top-to-bottom
                              and later rows are more likely to be direction misreads.
                              e.g. row 6 "Over 4.5 K" wins over row 18 "Over 4.5 K"
                              when row 18 was actually "Under 4.5 K" misread as Over.)
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
      return a._L - b._L;
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

═══ HOW TO READ THE TABLE — ROW BY ROW, LEFT TO RIGHT ═══
You will read the table the same way a human reads a spreadsheet:

1. Find row L=1. Place your eye on the leftmost cell of that row.
2. Slide your eye RIGHT across that single row, reading each cell in order: league → date → time → game → market → bet_name → book → L → M → odds → limit → books_count → avg_odds → avg_fv → avg_hold → fbc → ev → qk.
3. Emit the JSON object for that row.
4. Move down to row L=2. Repeat from step 2.
5. Continue until every row of the table has been emitted.

DO NOT scan a single column top-to-bottom and then jump to the next column. DO NOT collect avg_fv values down a column and then try to pair them with bet_names. Process ONE COMPLETE ROW at a time. Every field for row L=N must come from the SAME horizontal row of pixels.

═══ FIELDS TO RETURN (per row) ═══
- L: the integer in the "L" column, the small per-row index (1, 2, 3, ...). Required — anchors the row.
- pitcher: the player name (everything in bet_name BEFORE the word "Over" or "Under")
- market: the EXACT text from the "market" column. Examples: "Player Pitching Strikeouts", "Player Pitching Earned Runs Allowed", "Player Pitching Walks", "Player Pitching Hits Allowed", "Player Pitching Outs"
- bet_name: the EXACT text from the "bet_name" column. Examples: "Emerson Hancock Over 15.5", "Clay Holmes Under 2.5"
- direction: the word "Over" or "Under" — read the first letter ("O" or "U") of the word that appears after the player name in this row's bet_name
- line: the numeric line from this row's bet_name (4.5, 14.5, 16.5, etc.) as a number
- avg_odds: the EXACT text in the avg_odds cell of this row, as a STRING. Always a PAIR of signed integers separated by "/". Preserve verbatim: "+204 / -309", "-101 / -136". If empty, return "".
- avg_fv: the SINGLE SIGNED INTEGER in the avg_fv cell of this row. ONE number, not a pair. Examples: 261, -298, 117, -110.
- books_count: the UNSIGNED INTEGER in the books_count cell. Small count: 2, 3, 5, 7, 8. If empty/non-numeric, return 0.

═══ ANTI-COLUMN-DRIFT CHECK (per row, before emitting) ═══
After reading a row, verify these three properties of THIS row's values:

(a) avg_fv is a SINGLE signed integer. NO "/" in it. NO second number.
(b) avg_fv is NOT numerically equal to either half of this row's own avg_odds pair.
    If avg_odds is "+204 / -309" and you wrote avg_fv = -309, you read the wrong column for THIS row. Re-read avg_fv from the cell directly to the RIGHT of the avg_odds cell on this same row.
(c) pitcher in your JSON object equals the name in bet_name on THIS row. If bet_name says "Peter Lambert Over 5.5" and you wrote pitcher="Chris Bassitt", you carried the name from a previous row — re-read the bet_name cell on THIS row.

If any check fails, fix the offending field on THIS row before moving to row L=N+1.

═══ OVER vs UNDER (per row) ═══
The same pitcher appears in MULTIPLE rows with different directions/lines. For EACH row independently:
1. Look at the bet_name cell on this row.
2. The word right after the player name is "Over" or "Under". The only difference is the FIRST letter: O vs U.
3. Whatever first letter you see, write that exact word into BOTH the bet_name field (verbatim) AND the direction field. They MUST agree.

If the same pitcher has two rows with the same stat+line, one MUST be Over and the other MUST be Under. Never label both rows with the same direction.

═══ FINAL TABLE-LEVEL CHECK BEFORE EMITTING JSON ═══
After processing every row, scan the assembled list once more:

(1) Look for any (pitcher, line, stat) that appears with the SAME direction twice. Impossible — one must be Under. Re-read that later row's bet_name letter-by-letter and correct.
(2) Look for any row where the pitcher field doesn't match the player name in its own bet_name. Re-read that row's bet_name and fix the pitcher field.
(3) Look for any row where avg_fv equals one half of that row's own avg_odds pair. That row's avg_fv was copied from the wrong column — re-read it from one cell to the right of avg_odds.

═══ WORKED EXAMPLES ═══
CORRECT (read row 15 left-to-right): bet_name="Emerson Hancock Over 15.5" → pitcher="Emerson Hancock", direction="Over", line=15.5; avg_odds cell shows "-436 / +287"; avg_fv cell (next right) shows "-298".
{"L":15,"pitcher":"Emerson Hancock","market":"Player Pitching Outs","bet_name":"Emerson Hancock Over 15.5","direction":"Over","line":15.5,"avg_odds":"-436 / +287","avg_fv":-298,"books_count":7}

WRONG — avg_fv copied from avg_odds pair (column drift):
{"L":2,"pitcher":"Dean Kremer","bet_name":"Dean Kremer Over 5.5","avg_odds":"+204 / -309","avg_fv":-309,"books_count":2}
  — -309 is the right half of avg_odds. The real avg_fv lives ONE CELL FURTHER RIGHT on the same row.

WRONG — pitcher carried over from previous row:
{"L":7,"pitcher":"Chris Bassitt","bet_name":"Peter Lambert Over 4.5",...}
  — bet_name says Peter Lambert; pitcher must say Peter Lambert too.

WRONG — direction flipped:
{"L":3,"bet_name":"Braxton Ashcraft Under 4.5","direction":"Over",...}
  — bet_name says Under; direction must say Under.

═══ OUTPUT ═══
Return exactly this JSON shape, nothing else:
{"rows":[{"L":1,"pitcher":"...","market":"...","bet_name":"...","direction":"Over","line":4.5,"avg_odds":"+X / -Y","avg_fv":123,"books_count":7}, ...]}`;

    const body = {
      model: 'claude-opus-4-8',
      max_tokens: 8000,
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

    const cleaned = sanitizeModelJson(m[0]);
    try {
      const parsed = JSON.parse(cleaned);
      const rawRows = Array.isArray(parsed.rows) ? parsed.rows : [];
      const rows = normalizeRows(rawRows);
      /* Echo a sample of raw OCR rows so the client can show what Vision
         actually emitted. Mirrors the batter endpoint at line 720 — fastest
         way to spot bet_name/line/avg_fv misalignment without re-uploading. */
      return res.json({ rows, raw_rows: rawRows, raw_row_count: rawRows.length });
    } catch (e) {
      return res.status(500).json({ error: 'JSON parse error: ' + e.message, raw: cleaned });
    }
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
});

// ===== Batter FV-sheet OCR =====
// Mirrors the pitcher /api/extract pipeline for batter prop sheets.
// Output shape is per-(player, team, game) with Over+Under merged into a
// single record per (stat, threshold) — matches Phase-2 chunk-0 spec and is
// what the Teammate +EV pipeline (chunk 4) consumes.

// Canonical batter stat vocabulary, kept in lockstep with the chunk 2
// matcher (_stat_matches_batter_market in dk_api.py). Order matters: more
// specific names first so "Total Bases" doesn't collide with "Bases" inside
// "Stolen Bases", and "Home Runs" doesn't collide with plain "Runs".
const BATTER_STAT_FROM_MARKET = [
  // Multi-stat combo markets (Hits + Runs + RBIs, Runs + RBIs) get dropped —
  // we only care about single-stat props for teammate-pair correlations.
  { re: /hits?\s*\+\s*runs?\s*\+\s*rbi/i,    drop: true },
  { re: /runs?\s*\+\s*rbi/i,                  drop: true },
  // Single-stat batter markets
  { re: /total\s*bases/i,                     stat: 'Total Bases',   valid: [1.5, 2.5, 3.5] },
  { re: /home\s*runs?/i,                      stat: 'Home Runs',     valid: [0.5] },
  { re: /stolen\s*bases?/i,                   stat: 'Stolen Bases',  valid: [0.5] },
  { re: /singles?/i,                          stat: 'Singles',       valid: [0.5] },
  { re: /doubles?/i,                          stat: 'Doubles',       valid: [0.5] },
  { re: /triples?/i,                          stat: 'Triples',       valid: [0.5] },
  { re: /\brbi/i,                             stat: 'RBIs',          valid: [0.5, 1.5] },
  { re: /walks?/i,                            stat: 'Walks',         valid: [0.5] },
  { re: /\bruns?\b(?!\s*\+)/i,                stat: 'Runs',          valid: [0.5, 1.5] },
  { re: /\bhits?\b/i,                         stat: 'Hits',          valid: [0.5, 1.5, 2.5] },
];

function normalizeBatterLeg(market, direction, line) {
  if (!market || !direction || !isFinite(line)) return { drop: true, reason: 'missing fields' };
  const hit = BATTER_STAT_FROM_MARKET.find(s => s.re.test(market));
  if (!hit) return { drop: true, reason: 'unknown market' };
  if (hit.drop) return { drop: true, reason: 'multi-stat combo (skipped)' };
  if (!hit.valid.includes(line)) return { drop: true, reason: 'line ' + line + ' not valid for ' + hit.stat };
  return { drop: false, stat: hit.stat, leg: direction + ' ' + line + ' ' + hit.stat };
}

/* normalizeBatterRows: same per-row discipline as normalizeRows (pitcher).
   Outputs flat per-direction rows with canonical stat labels. groupBatterPlayers
   then merges Over+Under into one prop record per (player, stat, threshold). */
function normalizeBatterRows(rows) {
  if (!Array.isArray(rows)) return { rows: [], unmatched: [] };
  const out = [];
  const unmatched = [];   // diagnostic: rows we dropped + why
  const seen = new Set(); // first-pass dedupe by (batter, L) — see pitcher comment
  rows.forEach((r, idx) => {
    if (!r || typeof r !== 'object') return;

    // Direction + line: prefer explicit fields, fall back to bet_name parse.
    let direction = canonDirection(r.direction);
    let line = (r.line !== undefined && r.line !== null && r.line !== '') ? Number(r.line) : NaN;
    if (!direction || !isFinite(line)) {
      const parsed = parseBetNameDirection(r.bet_name);
      if (parsed) {
        if (!direction) direction = parsed.direction;
        if (!isFinite(line)) line = parsed.line;
      }
    }

    /* OCR sometimes returns names with stray accents the user's sheet
       didn't actually have, and even when it doesn't, downstream joins
       happen against TEAMMATE_DATA (ASCII) and the lineup endpoint
       (which we also ASCII-fold). Fold here so the join key is canonical
       for the entire pipeline. */
    const batterRaw = (r.batter || r.player || r.pitcher || '').trim();
    const batter = foldAscii(batterRaw);
    if (!batter) {
      unmatched.push({ L: r.L, bet_name: r.bet_name, market: r.market, reason: 'no batter name' });
      return;
    }

    const market = (r.market || '').trim();
    const norm = normalizeBatterLeg(market, direction, line);
    if (norm.drop) {
      unmatched.push({ L: r.L, batter, bet_name: r.bet_name, market, reason: norm.reason });
      return;
    }

    const fv = Number(r.avg_fv);
    if (!isFinite(fv)) {
      unmatched.push({ L: r.L, batter, bet_name: r.bet_name, market, reason: 'avg_fv not numeric' });
      return;
    }

    // Same avg_fv vs avg_odds pair-collision check the pitcher path uses to
    // catch the Kremer −309 column-confusion bug — see normalizeRows comment.
    const avgOddsRaw = String(r.avg_odds == null ? '' : r.avg_odds);
    const oddsPair = avgOddsRaw.match(/([+-]?\d+)\s*\/\s*([+-]?\d+)/);
    let fvSuspicious = false;
    if (oddsPair) {
      const oddsOver = Number(oddsPair[1]);
      const oddsUnder = Number(oddsPair[2]);
      if (fv === oddsOver || fv === oddsUnder) {
        fvSuspicious = true;
        console.warn('[batter suspicious_fv] L=' + (r.L != null ? r.L : '?') +
          ' ' + (r.bet_name || batter + ' ' + norm.leg) +
          ': avg_fv=' + fv + ' matches avg_odds pair (' +
          oddsOver + '/' + oddsUnder + ')');
      }
    }

    if (DEBUG) {
      console.log('[batter ocr_raw]', r.L, r.bet_name, {
        team: r.team, game: r.game, avg_fv: r.avg_fv, avg_odds: r.avg_odds,
        books_count: r.books_count, _fv_suspicious: fvSuspicious,
      });
    }

    const rowIdRaw = (r.L !== undefined && r.L !== null && r.L !== '') ? r.L : ('idx' + idx);
    const rowIdKey = String(rowIdRaw);
    const key = batter + '|' + rowIdKey;
    if (seen.has(key)) return;
    seen.add(key);

    const L = Number.isFinite(Number(rowIdRaw)) ? Number(rowIdRaw) : -1;
    const booksCount = Number(r.books_count);

    out.push({
      batter,
      team: (r.team || '').trim() || null,
      game: (r.game || '').trim() || null,
      stat: norm.stat,
      threshold: line,
      direction,
      leg: norm.leg,
      avg_fv: fv,
      avg_odds: avgOddsRaw || null,
      _fv_suspicious: fvSuspicious,
      _L: L,
      _books: Number.isFinite(booksCount) ? booksCount : 0,
    });
  });

  // Per-direction collapse on (batter, leg). Same tiebreak as pitcher:
  // (books_count desc, L desc).
  const groups = new Map();
  for (const r of out) {
    const k = r.batter + '|' + r.leg;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  }
  const collapsed = [];
  for (const [, rows2] of groups) {
    if (rows2.length === 1) { collapsed.push(rows2[0]); continue; }
    rows2.sort((a, b) => (b._books - a._books) || (b._L - a._L));
    if (DEBUG) {
      console.log('[batter collapse] ' + rows2[0].batter + '|' + rows2[0].leg +
        ' — kept L=' + rows2[0]._L + ' books=' + rows2[0]._books +
        ', dropped: ' + rows2.slice(1).map(r => 'L=' + r._L + ' books=' + r._books).join(', '));
    }
    collapsed.push(rows2[0]);
  }
  return { rows: collapsed, unmatched };
}

/* groupBatterPlayers: merges Over and Under rows for the same (batter, stat,
   threshold) into one prop record, then nests by player. Sparse OK — if only
   Over (or only Under) exists for a (player, stat, threshold), the other
   side's fields are null. team and game come from whichever direction's row
   had them set first.

   Per-player ordering: stable on first-seen leg order. Per-prop ordering:
   stat alphabetical, threshold ascending. */
function groupBatterPlayers(normRows) {
  const players = new Map();   // batter -> { player, team, game, propsByKey: Map }
  for (const r of normRows) {
    if (!players.has(r.batter)) {
      players.set(r.batter, {
        player: r.batter,
        team: r.team || null,
        game: r.game || null,
        propsByKey: new Map(),
      });
    }
    const p = players.get(r.batter);
    if (!p.team && r.team) p.team = r.team;
    if (!p.game && r.game) p.game = r.game;

    const propKey = r.stat + '|' + r.threshold;
    if (!p.propsByKey.has(propKey)) {
      p.propsByKey.set(propKey, {
        stat: r.stat,
        threshold: r.threshold,
        over_fv: null,    over_avg_odds: null, over_books_count: null, over_L: null, over_fv_suspicious: false,
        under_fv: null,   under_avg_odds: null, under_books_count: null, under_L: null, under_fv_suspicious: false,
      });
    }
    const prop = p.propsByKey.get(propKey);
    const side = r.direction === 'Over' ? 'over' : 'under';
    prop[side + '_fv'] = r.avg_fv;
    prop[side + '_avg_odds'] = r.avg_odds;
    prop[side + '_books_count'] = r._books;
    prop[side + '_L'] = r._L;
    prop[side + '_fv_suspicious'] = r._fv_suspicious;
  }
  // Materialize, sort props within each player.
  const out = [];
  for (const p of players.values()) {
    const props = [...p.propsByKey.values()].sort((a, b) => {
      if (a.stat !== b.stat) return a.stat < b.stat ? -1 : 1;
      return a.threshold - b.threshold;
    });
    out.push({ player: p.player, team: p.team, game: p.game, props });
  }
  // Stable player ordering: alphabetical by player name (frontend can re-sort).
  out.sort((a, b) => a.player.localeCompare(b.player));
  return out;
}

const BATTER_OCR_PROMPT = `You are extracting MLB BATTER prop bets from a screenshot of a spreadsheet. Return ONLY valid JSON, no prose, no markdown fences.

The table header row contains these column names (left to right): league, date, time, game, market, bet_name, L/U, book, L, M, odds, limit, books_count, avg_odds, avg_fv, avg_hold, fbc, ev, qk.

Optional columns that may also appear: "team" (short code like "KC", "BOS") between game and market.

═══ CRITICAL SCHEMA NOTE — the L/U column ═══
Between "bet_name" and "book" there is a narrow column labeled "L/U" whose cells contain a single letter — either "L" or "U" — often on a colored background. DO NOT confuse "L/U" with the later "L" column (which is a small integer row index). Do NOT treat "DraftKings" in the "book" column as if it were an L/U value. Use the column HEADERS to orient yourself, not cell counts from neighbors.

The presence of "L/U" means EVERY column to its right is shifted one position compared to sheets that lack it. You MUST read values by column HEADER TEXT, never by counting positions from the left edge.

═══ HOW TO READ THE TABLE — ROW BY ROW, LEFT TO RIGHT ═══
Read the table the same way a human reads a spreadsheet:

1. Find row L=1. Place your eye on the leftmost cell of that row.
2. Slide your eye RIGHT across that single row, reading each cell in header order.
3. Emit the JSON object for that row.
4. Move down to row L=2. Repeat.
5. Continue until every row of the table has been emitted.

DO NOT scan a single column top-to-bottom and then jump to the next column. DO NOT collect avg_fv values down a column and then try to pair them with bet_names. Process ONE COMPLETE ROW at a time. Every field for row L=N must come from the SAME horizontal row of pixels.

YOUR TASK: For each data row, return ONE JSON object with cell values from that single row. Do NOT normalize, do NOT combine columns, do NOT infer values from other rows. Each row of JSON must come from exactly ONE row of the table. Emit one object per row — do NOT skip rows, do NOT merge rows.

═══ FIELDS TO RETURN (per row) ═══
- L: the integer in the "L" column, the small per-row index (1, 2, 3, ...). Required — anchors the row.
- batter: the player name (everything in bet_name BEFORE the word "Over" or "Under")
- team: the EXACT text under the "team" column if present (short code like "KC", "BOS", "NYY"). If no team column exists, return "".
- game: the EXACT text under the "game" column (e.g., "TEX@KC", "BAL @ KC"). If no game column exists, return "".
- market: the EXACT text from the "market" column. Examples: "Player Hits", "Player Total Bases", "Player RBIs", "Player Home Runs", "Player Singles", "Player Doubles", "Player Triples", "Player Walks", "Player Stolen Bases", "Player Runs", "Player Hits + Runs + RBIs". DO NOT shorten "RBIs" to "RBI" if the sheet says "RBIs"; copy verbatim.
- bet_name: the EXACT text from the "bet_name" column. Examples: "Bobby Witt Jr. Over 0.5", "Salvador Perez Under 1.5"
- direction: the word "Over" or "Under" — read it letter-by-letter from this row's bet_name cell
- line: the numeric line from this row's bet_name (0.5, 1.5, 2.5, 3.5, etc.) as a number
- avg_odds: the EXACT text under the "avg_odds" header for this row, as a STRING. This cell always contains a PAIR of signed integers separated by "/". Preserve the format verbatim: "-280 / +220", "+135 / -155", "-110 / -110". If the cell is genuinely empty, return "".
- avg_fv: the SINGLE SIGNED INTEGER under the "avg_fv" header for this row. ONE number, not a pair. Examples: -260, +250, +135, -155.
- books_count: the UNSIGNED INTEGER under the "books_count" header. A small count like 2, 3, 5, 7, 8. If empty or non-numeric, return 0.

═══ HOW TO IDENTIFY THE avg_fv COLUMN — READ THIS CAREFULLY ═══
Do NOT count columns. Do NOT infer column position from neighbors. Do NOT use adjacent columns as positional anchors. Instead:

1. Locate the HEADER ROW at the top of the table. Visually find the text "avg_fv".
2. Read values straight DOWN from that specific header cell. For each data row, the avg_fv value is the cell directly under the "avg_fv" header.
3. The "avg_odds" header sits immediately to the LEFT of "avg_fv". Its cells contain TWO numbers separated by "/". That column is NOT avg_fv. Never substitute one for the other.

═══ MANDATORY SELF-CHECK BEFORE EMITTING EACH ROW ═══
For every row, verify these FIVE conditions. If ANY fail, you are reading the wrong column — re-locate the "avg_fv" header and re-read.

(a) avg_fv is a SINGLE signed INTEGER (e.g. +120, -180, +225). It contains NO "/" character and NO space-separated second number.
(b) avg_fv is NOT numerically equal to either half of this row's avg_odds pair.
    If avg_odds is "-280 / +220" and you think avg_fv is +220, that's impossible — you copied from the wrong column.
    If avg_odds is "+135 / -155" and you think avg_fv is -155, that's impossible — same mistake.
(c) avg_fv is the value directly under the "avg_fv" header text, not under "avg_odds" or "avg_hold".
(d) avg_fv is NEVER a word like "DraftKings" or "FanDuel". If you're about to emit a word instead of a number for avg_fv, you are reading the BOOK column instead of avg_fv — go back to the header row and recount columns from "avg_fv" directly.
(e) avg_fv is NEVER a letter like "L" or "U" or "L/U" on a colored background. That's the L/U column located BETWEEN bet_name and book — it is NOT avg_fv.

═══ ROW DISCIPLINE ═══
market, bet_name, direction, avg_odds, and avg_fv MUST all come from the SAME row. Use L as a positional anchor. Before emitting JSON for a row, ask: "Am I reading every field from the row whose L = X?" If not, re-align.

DO NOT cross rows. DO NOT pair the market from one row with the bet_name from another.

A SINGLE BATTER WILL HAVE MANY ROWS — one for each (stat, threshold, direction) triple. For Bobby Witt Jr. you might see:
  L=1  Bobby Witt Jr. Over 0.5  Player Hits           direction=Over
  L=2  Bobby Witt Jr. Under 0.5 Player Hits           direction=Under
  L=3  Bobby Witt Jr. Over 1.5  Player Total Bases    direction=Over
  L=4  Bobby Witt Jr. Under 1.5 Player Total Bases    direction=Under
Each is a SEPARATE row in your output. Do not merge the two "Hits" rows; do not skip any row because the player name is the same.

═══ OVER vs UNDER ═══
The same batter often appears in MULTIPLE rows with different directions, lines, and stats. For EACH row independently:
1. Locate the bet_name cell in the row whose L = X.
2. Read the literal letters after the player name — "Over" (O) or "Under" (U). Do NOT guess from context, do NOT infer from avg_fv sign.
3. Copy that exact word into "direction" AND keep it in the verbatim "bet_name". They MUST agree.

If the same batter has two rows with the same line+stat, one MUST be Over and the other MUST be Under. Never label both with the same direction.

═══ WORKED EXAMPLES ═══
CORRECT:
{"L":1,"batter":"Bobby Witt Jr.","team":"KC","game":"BAL@KC","market":"Player Hits","bet_name":"Bobby Witt Jr. Over 0.5","direction":"Over","line":0.5,"avg_odds":"-280 / +220","avg_fv":-260,"books_count":7}

CORRECT:
{"L":2,"batter":"Bobby Witt Jr.","team":"KC","game":"BAL@KC","market":"Player Hits","bet_name":"Bobby Witt Jr. Under 0.5","direction":"Under","line":0.5,"avg_odds":"-280 / +220","avg_fv":250,"books_count":7}

CORRECT:
{"L":15,"batter":"Salvador Perez","team":"KC","game":"BAL@KC","market":"Player Total Bases","bet_name":"Salvador Perez Over 1.5","direction":"Over","line":1.5,"avg_odds":"+150 / -180","avg_fv":135,"books_count":5}

WRONG — the exact bug this prompt guards against:
{"L":1,"batter":"Bobby Witt Jr.","bet_name":"Bobby Witt Jr. Over 0.5","avg_odds":"-280 / +220","avg_fv":+220,"books_count":7}
  — avg_fv was copied from the avg_odds pair. ALWAYS WRONG. The real avg_fv (-260) lives in the NEXT column to the right.

WRONG — direction flipped:
{"L":3,"bet_name":"Bobby Witt Jr. Under 0.5","direction":"Over",...}
  — bet_name says "Under" but direction says "Over". They MUST agree.

WRONG — merged rows:
{"L":1,"batter":"Bobby Witt Jr.","market":"Player Hits","bet_name":"Bobby Witt Jr. Over 0.5","direction":"Over","line":0.5,"avg_fv":-260,"under_fv":250}
  — Each row is one direction. Do NOT collapse Over and Under into one object. Emit two separate rows.

═══ OUTPUT ═══
Return exactly this JSON shape, nothing else:
{"rows":[{"L":1,"batter":"...","team":"...","game":"...","market":"...","bet_name":"...","direction":"Over","line":0.5,"avg_odds":"+X / -Y","avg_fv":123,"books_count":7}, ...]}`;

app.post('/api/extract-batter', async (req, res) => {
  try {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) return res.status(500).json({ error: 'ANTHROPIC_API_KEY not set on server' });

    const { image, mime } = req.body || {};
    if (!image) return res.status(400).json({ error: 'Missing image (base64) in body' });

    const body = {
      model: 'claude-opus-4-8',
      max_tokens: 8000,
      messages: [{
        role: 'user',
        content: [
          { type: 'image', source: { type: 'base64', media_type: mime || 'image/png', data: image } },
          { type: 'text', text: BATTER_OCR_PROMPT }
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

    const cleaned = sanitizeModelJson(m[0]);
    try {
      const parsed = JSON.parse(cleaned);
      const rawRowCount = Array.isArray(parsed.rows) ? parsed.rows.length : 0;
      const { rows: normRows, unmatched } = normalizeBatterRows(parsed.rows);

      /* Schema-drift guard: the 2026-04-20 real-sheet test surfaced a
         Vision column-shift bug (L/U column between bet_name and book
         wasn't in the prompt schema; every avg_fv was read from the
         book column and came back as the string "DraftKings"). The
         numeric-avg_fv guard inside normalizeBatterRows already
         catches each bad row individually, but if MOST of the sheet
         is bad we should refuse the result entirely rather than
         surface a dozen phantom candidates with garbage FV values. */
      const badFvCount = unmatched.filter(u => u.reason === 'avg_fv not numeric').length;
      const badFvPct = rawRowCount > 0 ? badFvCount / rawRowCount : 0;
      if (rawRowCount >= 10 && badFvPct > 0.20) {
        /* Sample a few specific rows so the client can show the user
           exactly what the OCR thought avg_fv was. Helps distinguish
           "column shift" (avg_fv = "DraftKings") from "genuinely blank
           column in the source sheet" (avg_fv = ""). */
        const samples = unmatched
          .filter(u => u.reason === 'avg_fv not numeric')
          .slice(0, 5)
          .map(u => ({ L: u.L, batter: u.batter, bet_name: u.bet_name, market: u.market }));
        return res.status(422).json({
          error: 'OCR misread the sheet column layout — ' + badFvCount +
                 ' of ' + rawRowCount + ' rows (' + (badFvPct * 100).toFixed(0) +
                 '%) had non-numeric avg_fv values. This usually means your sheet has a column the prompt does not know about. Check the FV column position and compare to the schema in server.js:BATTER_OCR_PROMPT.',
          bad_fv_count: badFvCount,
          total_row_count: rawRowCount,
          bad_fv_pct: badFvPct,
          sample_bad_rows: samples,
        });
      }

      const players = groupBatterPlayers(normRows);
      /* Sample raw OCR rows for the client-side diagnostic panel.
         Pass through verbatim (no normalization) so the user can
         eyeball exactly what Vision emitted for avg_fv, avg_odds,
         market, bet_name, etc. — the fastest way to spot column-drift
         bugs that slip past the 20% abort gate. */
      const sampleRows = (Array.isArray(parsed.rows) ? parsed.rows : []).slice(0, 3);
      return res.json({
        players,
        unmatched_markets: unmatched,
        /* Always echo validation stats so the client can log them via
           TMEV_DIAG checkpoint 1 without making a separate call. */
        ocr_stats: {
          raw_row_count: rawRowCount,
          bad_fv_count: badFvCount,
          normalized_row_count: normRows.length,
        },
        sample_rows: sampleRows,
      });
    } catch (e) {
      return res.status(500).json({ error: 'JSON parse error: ' + e.message, raw: cleaned });
    }
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
});

// ===== NBA FV sheet OCR =====
// Mirrors /api/extract-batter. Client sends { image: base64, mime } and
// gets back { players, unmatched_markets, ocr_stats, sample_rows } — same
// shape nbaEvTab.js already expects. Supported props (from the Phase 1
// correlations data): Points, Rebounds, Assists, 3-Pointers Made. The
// other NBA prop markets (Steals, Blocks, Turnovers, PRA, PR, PA,
// Double-Double, Triple-Double) are extracted but flagged as
// "no correlation data" so the user knows why they don't produce cards.
//
// Edit 1 (this commit): endpoint shell + Anthropic Vision call. Prompt
// and NBA market table land in Edit 2; normalization/grouping in Edit 3;
// synthetic tests in Edit 4. Until Edit 2 ships a real prompt, the
// endpoint will return the Vision model's raw rows without NBA-specific
// validation — enough to unblock the client's 404 and let us iterate
// the prompt on real sheets.

/* NBA canonical prop vocabulary. Order matters — combo markets are
   listed FIRST so patterns like "Points + Rebounds + Assists" don't
   collide with a later single-stat "Points" regex. Unsupported markets
   (Steals / Blocks / Turnovers / combos) are extracted and flagged with
   supported:false so the UI can show the user which FV-sheet rows
   weren't usable for correlation enumeration. Supported set is strictly
   the 4 props with correlation data per the Phase 1 NBA v1 schema. */
const NBA_STAT_FROM_MARKET = [
  /* Combo markets first — "Triple-Double" / "Double-Double" / "PRA" /
     "PR" / "PA" / "RA". These are tracked for diagnostic visibility
     (user knows they uploaded them) but produce no candidates. */
  { re: /triple[-\s]*double/i,                                   stat: 'Triple-Double', supported: false },
  { re: /double[-\s]*double/i,                                   stat: 'Double-Double', supported: false },
  { re: /points?\s*\+\s*rebounds?\s*\+\s*assists?|\bpra\b/i,     stat: 'PRA',           supported: false },
  { re: /points?\s*\+\s*rebounds?/i,                             stat: 'PR',            supported: false },
  { re: /points?\s*\+\s*assists?/i,                              stat: 'PA',            supported: false },
  { re: /rebounds?\s*\+\s*assists?/i,                            stat: 'RA',            supported: false },
  /* Supported single-stat markets (have correlation data). */
  { re: /(3[-\s]?(?:pointers?|pts?)\s*made|threes?\s*made|\b3pm\b)/i, stat: '3-Pointers Made', supported: true },
  { re: /\brebounds?\b/i,                                         stat: 'Rebounds',       supported: true },
  { re: /\bassists?\b/i,                                          stat: 'Assists',        supported: true },
  { re: /\bpoints?\b/i,                                           stat: 'Points',         supported: true },
  /* Unsupported singles — no correlation data. */
  { re: /\bsteals?\b/i,                                           stat: 'Steals',         supported: false },
  { re: /\bblocks?\b/i,                                           stat: 'Blocks',         supported: false },
  { re: /\bturnovers?\b/i,                                        stat: 'Turnovers',      supported: false },
];

/* Normalize a raw market string to { stat, supported } or null if
   unrecognized. Shared by the OCR normalizer and the unit tests in
   Edit 4 — keep this pure, no DOM/network. */
function matchNbaMarket(market) {
  if (!market) return null;
  const s = String(market);
  for (const m of NBA_STAT_FROM_MARKET) {
    if (m.re.test(s)) return { stat: m.stat, supported: m.supported };
  }
  return null;
}

const NBA_FV_PROMPT = `You are extracting NBA player prop bets from a screenshot of a spreadsheet. Return ONLY valid JSON, no prose, no markdown fences.

The table header row contains columns like: league, date, time, game, team, market, bet_name, L/U, book, L, M, odds, limit, books_count, avg_odds, avg_fv, avg_hold, fbc, ev, qk.

The "L/U" narrow column (single letter L or U, often colored) sits between bet_name and book. EVERY column to its right is shifted one slot, so you MUST read by header text, not by counting positions from the left edge.

═══ HOW TO READ THE TABLE — ROW BY ROW, LEFT TO RIGHT ═══
Read the table the same way a human reads a spreadsheet:
1. Find row L=1. Slide your eye RIGHT across that single row, reading each cell in header order.
2. Emit the JSON object for that row.
3. Move down to row L=2. Repeat.
DO NOT scan a single column top-to-bottom and then jump to the next column. Process ONE COMPLETE ROW at a time. Every field for row L=N must come from the SAME horizontal row of pixels.

YOUR TASK: For each data row, return ONE JSON object with cell values from that single row. Do NOT normalize, do NOT combine columns, do NOT infer from other rows.

═══ FIELDS TO RETURN (per row) ═══
- L: integer in the "L" column (the small row index)
- player: player name (everything in bet_name BEFORE the word "Over"/"Under")
- team: short code from the "team" column (e.g. "BOS", "LAL"). If no team column, return ""
- game: text from the "game" column (e.g. "CLE@BOS"). If no game column, return ""
- market: EXACT "market" column text. Examples: "Player Points", "Player Rebounds", "Player Assists", "Player 3-Pointers Made", "Player 3-Pt Made", "Player Steals", "Player Blocks", "Player Turnovers", "Player Points + Rebounds + Assists", "Player PRA", "Player Double-Double", "Player Triple-Double"
- bet_name: EXACT "bet_name" column text. Examples: "Donovan Mitchell Over 27.5", "Jayson Tatum Under 8.5"
- direction: "Over" or "Under" — read literally from this row's bet_name
- line: numeric line from bet_name (e.g. 27.5, 8.5, 1.5) as a number
- avg_odds: EXACT "avg_odds" text as a STRING, a signed pair like "+135 / -170", "-140 / +120". Empty → ""
- avg_fv: SINGLE signed integer under "avg_fv". ONE number, not a pair.
- books_count: unsigned integer under "books_count". 0 if empty/non-numeric.

═══ MANDATORY SELF-CHECK BEFORE EMITTING EACH ROW ═══
(a) avg_fv is a SINGLE integer — NO "/" character, NO second number.
(b) avg_fv is NOT equal to either half of avg_odds for this row.
(c) avg_fv is NEVER a word like "DraftKings"/"FanDuel" (that's the book column).
(d) avg_fv is NEVER "L"/"U" (that's the L/U column).
(e) market, bet_name, direction, avg_odds, avg_fv all come from the SAME row as L.

═══ OVER vs UNDER ═══
For each row independently, read the exact word after the player name in bet_name. Do NOT infer from avg_fv sign. The same player often has many rows — one for each (stat, threshold, direction).

═══ WORKED EXAMPLES ═══
CORRECT:
{"L":1,"player":"Donovan Mitchell","team":"CLE","game":"CLE@BOS","market":"Player Points","bet_name":"Donovan Mitchell Over 27.5","direction":"Over","line":27.5,"avg_odds":"+135 / -170","avg_fv":120,"books_count":7}

CORRECT (combo market, extracted but flagged downstream):
{"L":14,"player":"Jayson Tatum","team":"BOS","game":"CLE@BOS","market":"Player Points + Rebounds + Assists","bet_name":"Jayson Tatum Over 40.5","direction":"Over","line":40.5,"avg_odds":"-115 / -105","avg_fv":-108,"books_count":6}

WRONG — avg_fv copied from avg_odds pair:
{"L":1,"player":"Donovan Mitchell","bet_name":"Donovan Mitchell Over 27.5","avg_odds":"+135 / -170","avg_fv":-170,"books_count":7}
  — avg_fv was the second half of avg_odds. ALWAYS WRONG.

═══ OUTPUT ═══
Return exactly this JSON shape, nothing else:
{"rows":[{"L":1,"player":"...","team":"...","game":"...","market":"...","bet_name":"...","direction":"Over","line":27.5,"avg_odds":"+X / -Y","avg_fv":123,"books_count":7}, ...]}`;

/* normalizeNbaRows: takes the raw OCR rows array, validates each row,
   canonicalizes the market via matchNbaMarket, and returns the
   collapsed per-(player, leg) list + an unmatched diagnostic array.
   Mirrors normalizeBatterRows in structure so the Edit 1 handler can
   swap between the two without shape changes. Fallthrough logic:
     - missing player/market/direction/line/avg_fv → drop, counted reason
     - unsupported market (Steals, PRA, etc.) → drop, reason=unsupported_prop
     - avg_fv equals either half of avg_odds pair → flagged as suspicious
       but kept (user sees a warning on the card)
     - duplicate (player, L) → second occurrence dropped
     - duplicate (player, leg) after first-pass → collapsed by
       (books_count desc, L desc), same tiebreak as pitcher/batter paths. */
function normalizeNbaRows(rows) {
  if (!Array.isArray(rows)) return { rows: [], unmatched: [] };
  const out = [];
  const unmatched = [];
  const seen = new Set();
  rows.forEach((r, idx) => {
    if (!r || typeof r !== 'object') return;
    let direction = canonDirection(r.direction);
    let line = (r.line !== undefined && r.line !== null && r.line !== '') ? Number(r.line) : NaN;
    if (!direction || !isFinite(line)) {
      const parsed = parseBetNameDirection(r.bet_name);
      if (parsed) {
        if (!direction) direction = parsed.direction;
        if (!isFinite(line)) line = parsed.line;
      }
    }
    const player = (r.player || r.batter || r.pitcher || '').trim();
    if (!player) { unmatched.push({ L: r.L, bet_name: r.bet_name, market: r.market, reason: 'no player name' }); return; }
    const market = (r.market || '').trim();
    const cls = matchNbaMarket(market);
    if (!cls) { unmatched.push({ L: r.L, player, bet_name: r.bet_name, market, reason: 'unknown NBA market' }); return; }
    if (!cls.supported) { unmatched.push({ L: r.L, player, bet_name: r.bet_name, market, stat: cls.stat, reason: 'unsupported_prop (no correlation data)' }); return; }
    if (!direction || !isFinite(line)) { unmatched.push({ L: r.L, player, bet_name: r.bet_name, market, reason: 'missing direction/line' }); return; }
    const fv = Number(r.avg_fv);
    if (!isFinite(fv)) { unmatched.push({ L: r.L, player, bet_name: r.bet_name, market, reason: 'avg_fv not numeric' }); return; }
    /* Column-drift guard: avg_fv shouldn't equal either half of
       avg_odds. Same check the batter path uses to catch the
       "DraftKings" / -309 bugs. */
    const avgOddsRaw = String(r.avg_odds == null ? '' : r.avg_odds);
    const oddsPair = avgOddsRaw.match(/([+-]?\d+)\s*\/\s*([+-]?\d+)/);
    let fvSuspicious = false;
    if (oddsPair) {
      const oa = Number(oddsPair[1]); const ob = Number(oddsPair[2]);
      if (fv === oa || fv === ob) {
        fvSuspicious = true;
        console.warn('[nba suspicious_fv] L=' + (r.L != null ? r.L : '?') + ' ' + (r.bet_name || player) + ': avg_fv=' + fv + ' matches avg_odds pair (' + oa + '/' + ob + ')');
      }
    }
    const rowIdRaw = (r.L !== undefined && r.L !== null && r.L !== '') ? r.L : ('idx' + idx);
    const key = player + '|' + String(rowIdRaw);
    if (seen.has(key)) return;
    seen.add(key);
    const L = Number.isFinite(Number(rowIdRaw)) ? Number(rowIdRaw) : -1;
    const booksCount = Number(r.books_count);
    out.push({
      player,
      team: (r.team || '').trim() || null,
      game: (r.game || '').trim() || null,
      stat: cls.stat,
      threshold: line,
      direction,
      leg: direction + ' ' + line + ' ' + cls.stat,
      avg_fv: fv,
      avg_odds: avgOddsRaw || null,
      _fv_suspicious: fvSuspicious,
      _L: L,
      _books: Number.isFinite(booksCount) ? booksCount : 0,
    });
  });
  /* Collapse duplicate (player, leg) by (books desc, L desc) — prefer
     the row with more books (sharper FV) and newer L (sheet usually
     appended). Averaging would mix potentially-wrong values; pick one. */
  const groups = new Map();
  for (const r of out) {
    const k = r.player + '|' + r.leg;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  }
  const collapsed = [];
  for (const [, rs] of groups) {
    if (rs.length === 1) { collapsed.push(rs[0]); continue; }
    rs.sort((a, b) => (b._books - a._books) || (b._L - a._L));
    collapsed.push(rs[0]);
  }
  return { rows: collapsed, unmatched };
}

/* groupNbaPlayers: merge Over+Under rows for the same (player, stat,
   threshold) into one prop record, nest by player. Same output shape
   as groupBatterPlayers so nbaEvTab.js's indexFvPlayers handles it
   without a sport-specific branch. Sparse sides are OK — if only Over
   is on the sheet, Under fields stay null. */
function groupNbaPlayers(normRows) {
  const players = new Map();
  for (const r of normRows) {
    if (!players.has(r.player)) {
      players.set(r.player, { player: r.player, team: r.team || null, game: r.game || null, propsByKey: new Map() });
    }
    const p = players.get(r.player);
    if (!p.team && r.team) p.team = r.team;
    if (!p.game && r.game) p.game = r.game;
    const propKey = r.stat + '|' + r.threshold;
    if (!p.propsByKey.has(propKey)) {
      p.propsByKey.set(propKey, {
        stat: r.stat, threshold: r.threshold,
        over_fv: null, over_avg_odds: null, over_books_count: null, over_L: null, over_fv_suspicious: false,
        under_fv: null, under_avg_odds: null, under_books_count: null, under_L: null, under_fv_suspicious: false,
      });
    }
    const prop = p.propsByKey.get(propKey);
    const side = r.direction === 'Over' ? 'over' : 'under';
    prop[side + '_fv'] = r.avg_fv;
    prop[side + '_avg_odds'] = r.avg_odds;
    prop[side + '_books_count'] = r._books;
    prop[side + '_L'] = r._L;
    prop[side + '_fv_suspicious'] = r._fv_suspicious;
  }
  const out = [];
  for (const p of players.values()) {
    const props = [...p.propsByKey.values()].sort((a, b) => (a.stat < b.stat ? -1 : a.stat > b.stat ? 1 : a.threshold - b.threshold));
    out.push({ player: p.player, team: p.team, game: p.game, props });
  }
  out.sort((a, b) => a.player.localeCompare(b.player));
  return out;
}

app.post('/api/extract-nba', async (req, res) => {
  try {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) return res.status(500).json({ error: 'ANTHROPIC_API_KEY not set on server' });

    const { image, mime } = req.body || {};
    if (!image) return res.status(400).json({ error: 'Missing image (base64) in body' });

    const body = {
      model: 'claude-opus-4-8',
      max_tokens: 8000,
      messages: [{
        role: 'user',
        content: [
          { type: 'image', source: { type: 'base64', media_type: mime || 'image/png', data: image } },
          { type: 'text', text: NBA_FV_PROMPT }
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

    const cleaned = sanitizeModelJson(m[0]);
    try {
      const parsed = JSON.parse(cleaned);
      const rawRowCount = Array.isArray(parsed.rows) ? parsed.rows.length : 0;
      const { rows: normRows, unmatched } = normalizeNbaRows(parsed.rows);
      /* Schema-drift guard: if >20% of rows had non-numeric avg_fv the
         OCR probably misread the column layout (same bug class the
         batter endpoint guards against). Refuse to return a poisoned
         set; surface a sample for client-side diagnosis. */
      const badFvCount = unmatched.filter(u => u.reason === 'avg_fv not numeric').length;
      const badFvPct = rawRowCount > 0 ? badFvCount / rawRowCount : 0;
      if (rawRowCount >= 10 && badFvPct > 0.20) {
        return res.status(422).json({
          error: 'OCR misread the NBA sheet column layout — ' + badFvCount +
                 ' of ' + rawRowCount + ' rows (' + (badFvPct * 100).toFixed(0) +
                 '%) had non-numeric avg_fv. Check the FV column position vs NBA_FV_PROMPT.',
          bad_fv_count: badFvCount,
          total_row_count: rawRowCount,
          sample_bad_rows: unmatched.filter(u => u.reason === 'avg_fv not numeric').slice(0, 5),
        });
      }
      const players = groupNbaPlayers(normRows);
      return res.json({
        players,
        unmatched_markets: unmatched,
        ocr_stats: {
          raw_row_count: rawRowCount,
          normalized_row_count: normRows.length,
          bad_fv_count: badFvCount,
          unsupported_prop_count: unmatched.filter(u => u.reason && u.reason.indexOf('unsupported_prop') === 0).length,
        },
        sample_rows: (parsed.rows || []).slice(0, 3),
      });
    } catch (e) {
      return res.status(500).json({ error: 'JSON parse error: ' + e.message, raw: cleaned });
    }
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
});

// ===== Tennis FV OCR =====
//
// One endpoint handles BOTH market sheets the user uploads — the prompt
// extracts whatever rows the model finds, and we auto-detect per-row
// whether it's a "1st Set Total Games" row or a "Game Spread" row by
// inspecting the `market` cell. The client accumulates rows across
// multiple uploads (one per market) before running the SGP pipeline.
//
// We extract `book_odds` as a STRING (two-sided pair like "-150 / +100"),
// the signed `fv` integer, and the row identifiers (game, name, market).
// `book_odds` is needed so the client's "DK lines as fair" mode can
// no-vig DK's own two-sided price instead of relying on the sharp FV.
const TENNIS_FV_PROMPT = `You are extracting tennis prop bets from a screenshot of a spreadsheet. Return ONLY valid JSON, no prose, no markdown fences.

The screenshot's columns may vary across sheets. Map source columns to these OUTPUT field names regardless of what the header says:

  OUTPUT FIELD       <-  SOURCE COLUMN ALIASES (any one)
  game               <-  game
  tournament         <-  tournament                          (optional; "" if absent)
  market             <-  market
  bet_name           <-  bet_name OR name
  book               <-  book
  book_odds          <-  odds OR book_odds                   (DK's two-sided pair, e.g. "-150 / +100")
  fv                 <-  avg_fv OR fv                        (single signed integer, sharp/consensus FV)
  devig_odds         <-  devig_odds                          (optional; "" if absent)

The "L" / "M" / "L/U" narrow indicator columns sit just before "book" or just after "bet_name" depending on the sheet. EVERY column to the right of those indicators is shifted one slot — so you MUST read by header text, not by counting positions from the left edge.

═══ HOW TO READ THE TABLE — ROW BY ROW, LEFT TO RIGHT ═══
1. Find the first data row. Slide your eye RIGHT across it, reading each cell in the order the headers appear.
2. Map the cell under each header to the OUTPUT field via the alias table above.
3. Emit one JSON object for that row. Move to the next row.
DO NOT scan a single column top-to-bottom and jump to the next column — process ONE COMPLETE ROW at a time.

═══ FIELD SEMANTICS ═══
- game: STRING containing BOTH players with " @ " between them. e.g. "Quentin Halys @ Ugo Humbert". Preserve exactly.
- tournament: STRING. e.g. "ATP French Open - Paris - France". Empty string if no such column.
- market: STRING copied EXACTLY. Expected: "1st Set Total Games" OR "Game Spread". Other markets are allowed but the downstream pipeline will ignore them.
- bet_name: STRING copied EXACTLY.
    * For 1st-Set-Total rows: "Over X.5" or "Under X.5" (X.5 a numeric line)
    * For Game-Spread rows: "<Full Player Name> +X.5" or "<Full Player Name> -X.5"
- book_odds: STRING. The DK two-sided pair like "-150 / +100" or "-110 / -135". Keep both sides and the separator. This is the "odds" column (the DK book column) — NOT the avg_odds / consensus column.
- fv: SINGLE signed integer copied from the avg_fv (or fv) column. ONE number, never a pair.

═══ MANDATORY SELF-CHECK BEFORE EMITTING EACH ROW ═══
(a) fv is a SINGLE integer, NO "/" character, NO second number.
(b) fv MUST NOT equal either half of book_odds or devig_odds for this row.
(c) fv MUST NOT be the literal word "DraftKings" / "Pinnacle" / "L" / "M" — those are different columns.
(d) book_odds contains a "/" between two signed numbers (DK's two-sided market).
(e) game contains "@" between two player names.
(f) market is the EXACT cell text under "market" — do NOT infer from bet_name.

═══ WORKED EXAMPLES ═══
1st-set-total row (older layout, "name" column):
{"game":"Quentin Halys @ Ugo Humbert","tournament":"","market":"1st Set Total Games","bet_name":"Over 8.5","book":"DraftKings","book_odds":"-525 / +300","fv":-578,"devig_odds":"-684 / +490"}

1st-set-total row (newer layout, "bet_name" + "tournament" columns):
{"game":"Yibing Wu @ Flavio Cobolli","tournament":"ATP French Open - Paris - France","market":"1st Set Total Games","bet_name":"Over 8.5","book":"DraftKings","book_odds":"-110 / -135","fv":-108,"devig_odds":""}

Game-spread row (newer layout):
{"game":"Alexander Zverev @ Tomas Machac","tournament":"ATP French Open - Paris - France","market":"Game Spread","bet_name":"Tomas Machac +6.5","book":"DraftKings","book_odds":"+100 / -140","fv":100,"devig_odds":""}

WRONG — fv copied from a half of book_odds:
{"bet_name":"Over 8.5","book_odds":"-525 / +300","fv":-525}
  — fv was the first half of the DK pair. NEVER do this.

═══ OUTPUT ═══
Return exactly this JSON shape, nothing else:
{"rows":[ <one normalized object per data row>, ... ]}`;

/* Parse an OCR row into a canonicalized tennis-leg record.
   Returns { kind: 'total'|'spread', ... } or { kind: null, reason } when
   the row can't be classified. */
function parseTennisRow(r) {
  if (!r || typeof r !== 'object') return { kind: null, reason: 'bad row' };
  const game = (r.game || '').trim();
  if (!game || game.indexOf('@') < 0) return { kind: null, reason: 'no game' };
  const market = (r.market || '').toLowerCase();
  // Accept either the new ("bet_name", "avg_fv", "odds") or the old
  // ("name", "fv", "book_odds") schema — the OCR prompt normalizes them
  // but we fall back per-key just in case.
  const name = (r.bet_name || r.name || '').trim();
  const fv = Number(r.fv != null && r.fv !== '' ? r.fv : r.avg_fv);
  const bookOdds = String(
    r.book_odds != null && r.book_odds !== '' ? r.book_odds
    : (r.odds != null ? r.odds : '')
  ).trim();
  const tournament = (r.tournament || '').trim();
  const players = game.split('@').map(s => s.trim());
  const [pA, pB] = [players[0] || '', players[1] || ''];

  if (market.indexOf('1st set total') >= 0 || market.indexOf('first set total') >= 0) {
    // name: "Over 8.5" / "Under 8.5"
    const m = name.match(/^(Over|Under)\s+(\d+(?:\.\d+)?)$/i);
    if (!m) return { kind: null, reason: 'unparseable 1st-set name: ' + name };
    return {
      kind: 'total',
      game, pA, pB, tournament,
      side: m[1][0].toUpperCase() + m[1].slice(1).toLowerCase(), // Over | Under
      line: Number(m[2]),
      fv: Number.isFinite(fv) ? fv : null,
      book_odds: bookOdds,
      devig_odds: String(r.devig_odds || ''),
    };
  }

  if (market.indexOf('game spread') >= 0 || market.indexOf('game handicap') >= 0) {
    // name: "Tomas Machac +7.5" or "Rafael Jodar -8.5"
    const m = name.match(/^(.+?)\s+([+-])\s*(\d+(?:\.\d+)?)$/);
    if (!m) return { kind: null, reason: 'unparseable spread name: ' + name };
    const player = m[1].trim();
    const sign = m[2];
    const mag = Number(m[3]);
    return {
      kind: 'spread',
      game, pA, pB, tournament,
      player,
      sign,                       // "+" → dog ; "-" → favorite
      line: sign === '+' ? mag : -mag,   // signed line
      mag,
      isDog: sign === '+',
      fv: Number.isFinite(fv) ? fv : null,
      book_odds: bookOdds,
      devig_odds: String(r.devig_odds || ''),
    };
  }

  return { kind: null, reason: 'unknown market: ' + r.market };
}

app.post('/api/extract-tennis', async (req, res) => {
  try {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) return res.status(500).json({ error: 'ANTHROPIC_API_KEY not set on server' });

    const { image, mime } = req.body || {};
    if (!image) return res.status(400).json({ error: 'Missing image (base64) in body' });

    const body = {
      model: 'claude-opus-4-8',
      max_tokens: 8000,
      messages: [{
        role: 'user',
        content: [
          { type: 'image', source: { type: 'base64', media_type: mime || 'image/png', data: image } },
          { type: 'text', text: TENNIS_FV_PROMPT }
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

    const cleaned = sanitizeModelJson(m[0]);
    let parsed;
    try {
      parsed = JSON.parse(cleaned);
    } catch (e) {
      return res.status(500).json({ error: 'JSON parse error: ' + e.message, raw: cleaned });
    }

    const rawRows = Array.isArray(parsed.rows) ? parsed.rows : [];
    const totals  = [];
    const spreads = [];
    const unmatched = [];
    rawRows.forEach((row) => {
      const parsedRow = parseTennisRow(row);
      if (parsedRow.kind === 'total')  return totals.push(parsedRow);
      if (parsedRow.kind === 'spread') return spreads.push(parsedRow);
      unmatched.push({ row, reason: parsedRow.reason });
    });

    return res.json({
      totals,
      spreads,
      unmatched,
      ocr_stats: { raw_row_count: rawRows.length, totals: totals.length, spreads: spreads.length },
      sample_rows: rawRows.slice(0, 3),
    });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
});

// POST /api/dk/find-sgps-tennis — price a batch of tennis 2-leg SGPs.
// Request body: { candidates: [{ id, player_dog, event, set1_total_line, set1_total_side, match_handicap_line }] }
const TENNIS_DK_CACHE = new Map();
const TENNIS_DK_CACHE_TTL_MS = 10 * 60 * 1000;

function _tennisCacheKey(candidates) {
  var parts = candidates.map(function (c) {
    return [c.id, c.player_dog, c.set1_total_line, c.set1_total_side, c.match_handicap_line].join('|');
  }).slice().sort();
  return parts.join('\n');
}

app.post('/api/dk/find-sgps-tennis', async (req, res) => {
  try {
    const { candidates } = req.body || {};
    if (!Array.isArray(candidates) || !candidates.length) {
      return res.status(400).json({ error: 'candidates array required' });
    }
    const key = _tennisCacheKey(candidates);
    const hit = TENNIS_DK_CACHE.get(key);
    if (hit && Date.now() - hit.ts < TENNIS_DK_CACHE_TTL_MS) {
      return res.json(Object.assign({}, hit.body, { cached: true, cache_age_s: Math.round((Date.now() - hit.ts) / 1000) }));
    }
    const result = await dkCall(['find-sgps-tennis'], JSON.stringify({ candidates }));
    if (result.error && !result.results) return res.json(result);
    if (!result.error) TENNIS_DK_CACHE.set(key, { ts: Date.now(), body: result });
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK find-sgps-tennis failed: ' + e.message });
  }
});

// GET /api/dk/tennis-resolve-league?slug=<slug>
// Server-side resolution of a DK public slug to the numeric league ID.
// DK's public URLs switched to slug routing; the backend still uses
// numeric IDs. Scrapes the public page via dk_api.py's curl_cffi
// session (which already bypasses Akamai) and extracts the embedded
// league ID. Cached 30 min per slug — IDs don't change mid-tournament.
// Default slug=french-open-men so the bare call resolves the current
// French Open M ID.
const TENNIS_LEAGUE_RESOLVE_CACHE = new Map();
const TENNIS_LEAGUE_RESOLVE_TTL_MS = 30 * 60 * 1000;

app.get('/api/dk/tennis-resolve-league', async (req, res) => {
  try {
    const slug = String(req.query.slug || 'french-open-men').trim();
    if (!/^[a-z0-9-]+$/i.test(slug)) {
      return res.status(400).json({ error: 'slug must be alphanumeric with dashes only' });
    }
    const hit = TENNIS_LEAGUE_RESOLVE_CACHE.get(slug);
    if (hit && Date.now() - hit.ts < TENNIS_LEAGUE_RESOLVE_TTL_MS) {
      return res.json(Object.assign({}, hit.body, {
        cached: true, cache_age_s: Math.round((Date.now() - hit.ts) / 1000),
      }));
    }
    const result = await dkCall(['resolve-tennis-league', slug]);
    if (!result.error && result.league_id) {
      TENNIS_LEAGUE_RESOLVE_CACHE.set(slug, { ts: Date.now(), body: result });
    }
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK league resolve failed: ' + e.message });
  }
});

// GET /api/dk/tennis-games — DK tennis events for the current league
// (defaults to French Open men's via DK_TENNIS_LEAGUE_ID env var).
app.get('/api/dk/tennis-games', async (_req, res) => {
  try {
    const result = await dkCall(['games-tennis']);
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK tennis games failed: ' + e.message });
  }
});

// POST /api/dk/tennis-autoscan — auto-enumerate the full SGP candidate
// set straight from DK. No FV-sheet upload required. Returns priced
// candidates with two-sided per-leg DK odds + DK SGP price; the client
// no-vigs to derive pa/pb, applies the hardcoded set-1 correlation,
// and computes EV. Cached server-side for 10 minutes keyed by the
// {lines, max_handicap} request fingerprint.
const TENNIS_AUTOSCAN_CACHE = new Map();
const TENNIS_AUTOSCAN_TTL_MS = 10 * 60 * 1000;

app.post('/api/dk/tennis-autoscan', async (req, res) => {
  try {
    const params = req.body || {};
    const key = JSON.stringify({
      lines: Array.isArray(params.lines) ? params.lines.slice().sort() : null,
      max_handicap: params.max_handicap != null ? Number(params.max_handicap) : null,
      league_id: params.league_id != null ? String(params.league_id) : null,
    });
    const hit = TENNIS_AUTOSCAN_CACHE.get(key);
    if (hit && Date.now() - hit.ts < TENNIS_AUTOSCAN_TTL_MS) {
      return res.json(Object.assign({}, hit.body, {
        cached: true, cache_age_s: Math.round((Date.now() - hit.ts) / 1000)
      }));
    }
    const result = await dkCall(['enumerate-sgps-tennis'], JSON.stringify(params));
    if (result.error && !result.candidates) return res.json(result);
    if (!result.error) TENNIS_AUTOSCAN_CACHE.set(key, { ts: Date.now(), body: result });
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK tennis autoscan failed: ' + e.message });
  }
});

// ===== World Cup (soccer) =====
// Flow: user prints the Pinnacle match page to PDF and uploads it here.
// We extract the text layer (pdf-parse), parse the combo market groups
// (pinnacleSoccer.js), and return them raw — the client devigs each group
// (they're exhaustive partitions) and computes EV against DK's posted
// combo-market odds from /api/dk/find-sgps-worldcup.
const { parsePinnacleSoccerText, MARKET_DEFS: WC_MARKET_DEFS } = require('./pinnacleSoccer');

const WC_PDF_MAX_BYTES = 20 * 1024 * 1024;
const wcPdfUpload = (() => {
  const multer = require('multer');
  return multer({
    storage: multer.memoryStorage(),
    limits: { fileSize: WC_PDF_MAX_BYTES, files: 1, fields: 4 },
  });
})();

app.post('/api/extract-worldcup-pdf', (req, res) => {
  wcPdfUpload.single('file')(req, res, async function (err) {
    if (err) {
      const status = err.code === 'LIMIT_FILE_SIZE' ? 413 : 400;
      return res.status(status).json({ error: 'Upload rejected: ' + err.message });
    }
    try {
      if (!req.file || !req.file.buffer) {
        return res.status(400).json({ error: 'No PDF file in request (field name: file)' });
      }
      if (!/^%PDF/.test(req.file.buffer.slice(0, 5).toString('latin1'))) {
        return res.status(400).json({ error: 'File is not a PDF' });
      }
      const pdfParse = require('pdf-parse');
      const data = await pdfParse(req.file.buffer);
      const parsed = parsePinnacleSoccerText(data.text || '');
      if (!parsed.home || !parsed.away) {
        return res.status(422).json({
          error: 'Could not find the two team names in this PDF — is it a Pinnacle soccer match page?',
          pages: data.numpages,
        });
      }
      const sgpKeys = WC_MARKET_DEFS.filter(d => d.sgp).map(d => d.key);
      const foundSgp = sgpKeys.filter(k => (parsed.markets[k] || []).length >= 2);
      return res.json({
        ok: true,
        pages: data.numpages,
        home: parsed.home,
        away: parsed.away,
        league: parsed.league,
        kickoff: parsed.kickoff,
        markets: parsed.markets,
        market_defs: WC_MARKET_DEFS.map(d => ({ key: d.key, label: d.label, sgp: !!d.sgp })),
        sgp_markets_found: foundSgp,
      });
    } catch (e) {
      return res.status(500).json({ error: 'PDF parse failed: ' + e.message });
    }
  });
});

// Soccer league registry (World Cup, EPL, …). Lets the client populate a
// league picker without hardcoding ids. Cached — the registry is static.
const SOCCER_LEAGUES_CACHE = { ts: 0, body: null };
const SOCCER_LEAGUES_TTL_MS = 60 * 60 * 1000;

app.get('/api/soccer/leagues', async (_req, res) => {
  try {
    if (SOCCER_LEAGUES_CACHE.body && Date.now() - SOCCER_LEAGUES_CACHE.ts < SOCCER_LEAGUES_TTL_MS) {
      return res.json(Object.assign({}, SOCCER_LEAGUES_CACHE.body, { cached: true }));
    }
    const result = await dkCall(['soccer-leagues']);
    if (!result.error) { SOCCER_LEAGUES_CACHE.ts = Date.now(); SOCCER_LEAGUES_CACHE.body = result; }
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'soccer leagues failed: ' + e.message });
  }
});

// Live pull from Pinnacle's guest API — no PDF required. Same output shape
// as /api/extract-worldcup-pdf so the client reuses one code path. Accepts an
// optional ?league=<key> (worldcup|epl|…) or ?leagueId=<pinnacle numeric id>;
// blank = the server default (World Cup). Cache is keyed per league so
// switching leagues doesn't serve a stale slate.
const PIN_WC_GAMES_CACHE = new Map();
const PIN_WC_GAMES_TTL_MS = 5 * 60 * 1000;

app.get('/api/pinnacle/worldcup-games', async (req, res) => {
  try {
    const league = String(req.query.league || '').trim().toLowerCase();
    const leagueId = String(req.query.leagueId || '').trim();
    // Prefer an explicit numeric Pinnacle id; else a registry key; else default.
    const arg = /^\d+$/.test(leagueId) ? leagueId
      : (/^[a-z0-9_-]+$/.test(league) ? league : '');
    const cacheKey = arg || '__default__';
    const hit = PIN_WC_GAMES_CACHE.get(cacheKey);
    if (hit && Date.now() - hit.ts < PIN_WC_GAMES_TTL_MS) {
      return res.json(Object.assign({}, hit.body, { cached: true }));
    }
    const args = ['pinnacle-wc-games'];
    if (arg) args.push(arg);
    const result = await dkCall(args);
    if (!result.error) PIN_WC_GAMES_CACHE.set(cacheKey, { ts: Date.now(), body: result });
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'Pinnacle games failed: ' + e.message });
  }
});

const PIN_WC_MATCH_CACHE = new Map();
const PIN_WC_MATCH_TTL_MS = 2 * 60 * 1000;

app.get('/api/pinnacle/worldcup-match/:matchupId', async (req, res) => {
  try {
    const mid = String(req.params.matchupId || '');
    if (!/^\d+$/.test(mid)) return res.status(400).json({ error: 'numeric matchupId required' });
    const hit = PIN_WC_MATCH_CACHE.get(mid);
    if (hit && Date.now() - hit.ts < PIN_WC_MATCH_TTL_MS) {
      return res.json(Object.assign({}, hit.body, { cached: true }));
    }
    const result = await dkCall(['pinnacle-wc-specials', mid]);
    if (!result.error) PIN_WC_MATCH_CACHE.set(mid, { ts: Date.now(), body: result });
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'Pinnacle match fetch failed: ' + e.message });
  }
});

// GET /api/pinnacle/nba-props — today's NBA main lines from Pinnacle (player
// props with both prices, game and team totals). The NBA dashboard prices its
// plug-in r at these lines and opens the prop builder on them. Two league-wide
// calls through dk_api.py's curl_cffi session; cached two minutes.
let PIN_NBA_CACHE = null;
const PIN_NBA_TTL_MS = 2 * 60 * 1000;

app.get('/api/pinnacle/nba-props', async (req, res) => {
  try {
    if (PIN_NBA_CACHE && Date.now() - PIN_NBA_CACHE.ts < PIN_NBA_TTL_MS) {
      return res.json(Object.assign({}, PIN_NBA_CACHE.body, { cached: true }));
    }
    const result = await dkCall(['pinnacle-nba-props']);
    if (!result.error) PIN_NBA_CACHE = { ts: Date.now(), body: result };
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'Pinnacle NBA props failed: ' + e.message });
  }
});

// GET /api/dk/worldcup-resolve-league?slug=world-cup-2026
const WC_LEAGUE_RESOLVE_CACHE = new Map();
const WC_LEAGUE_RESOLVE_TTL_MS = 30 * 60 * 1000;

app.get('/api/dk/worldcup-resolve-league', async (req, res) => {
  try {
    const slug = String(req.query.slug || 'world-cup-2026').trim();
    if (!/^[a-z0-9-]+$/i.test(slug)) {
      return res.status(400).json({ error: 'slug must be alphanumeric with dashes only' });
    }
    const hit = WC_LEAGUE_RESOLVE_CACHE.get(slug);
    if (hit && Date.now() - hit.ts < WC_LEAGUE_RESOLVE_TTL_MS) {
      return res.json(Object.assign({}, hit.body, {
        cached: true, cache_age_s: Math.round((Date.now() - hit.ts) / 1000),
      }));
    }
    const result = await dkCall(['resolve-worldcup-league', slug]);
    if (!result.error && result.league_id) {
      WC_LEAGUE_RESOLVE_CACHE.set(slug, { ts: Date.now(), body: result });
    }
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK league resolve failed: ' + e.message });
  }
});

// GET /api/dk/worldcup-games — DK World Cup slate (league via env or slug resolve)
app.get('/api/dk/worldcup-games', async (req, res) => {
  try {
    const args = ['games-worldcup'];
    if (req.query.league_id && /^\d+$/.test(String(req.query.league_id))) {
      args.push(String(req.query.league_id));
    }
    const result = await dkCall(args);
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK worldcup games failed: ' + e.message });
  }
});

// POST /api/dk/find-sgps-worldcup — match Pinnacle combo candidates to DK's
// posted combo markets for one match, return DK odds per candidate.
const WC_DK_CACHE = new Map();
const WC_DK_CACHE_TTL_MS = 5 * 60 * 1000;

app.post('/api/dk/find-sgps-worldcup', async (req, res) => {
  try {
    const body = req.body || {};
    const { candidates, home, away } = body;
    if (!Array.isArray(candidates) || !candidates.length) {
      return res.status(400).json({ error: 'candidates array required' });
    }
    if (!home || !away) {
      return res.status(400).json({ error: 'home and away required' });
    }
    const key = JSON.stringify([home, away, body.league || '', body.league_id || '',
      body.league_slug || '', candidates.map(c => c.id).sort()]);
    const hit = WC_DK_CACHE.get(key);
    if (hit && Date.now() - hit.ts < WC_DK_CACHE_TTL_MS) {
      return res.json(Object.assign({}, hit.body, { cached: true, cache_age_s: Math.round((Date.now() - hit.ts) / 1000) }));
    }
    const result = await dkCall(['find-sgps-worldcup'], JSON.stringify(body));
    if (!result.error) WC_DK_CACHE.set(key, { ts: Date.now(), body: result });
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK find-sgps-worldcup failed: ' + e.message });
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

// Which interpreter runs the Python helpers. On Linux/macOS (and the Railway
// image) `python3` is right; on Windows the launcher is usually `python` and
// `python3` either doesn't exist or is the Store stub that opens a web page —
// which surfaced as an opaque "dk_api.py exited with code 9009". Resolve it
// once at boot: PYTHON env wins, else the platform default, and fall back to
// whichever of python3/python actually answers --version.
const PYTHON = (function resolvePython() {
  const explicit = (process.env.PYTHON || '').trim();
  if (explicit) return explicit;
  const candidates = process.platform === 'win32'
    ? ['python', 'python3', 'py']
    : ['python3', 'python'];
  for (const cmd of candidates) {
    try {
      const probe = require('child_process').spawnSync(cmd, ['--version'], { timeout: 5000 });
      // A Windows Store stub exits non-zero (or errors) instead of printing a
      // version, so status===0 is the real check, not merely "no error".
      if (!probe.error && probe.status === 0) return cmd;
    } catch (_) { /* try the next candidate */ }
  }
  return candidates[0];   // nothing answered; let the spawn fail loudly
})();
console.log('Python interpreter: ' + PYTHON + ' (override with PYTHON=...)');

// Runtime DK cookie set from the website (POST /api/dk/cookies) instead of the
// DK_COOKIES env var — lets you paste a fresh cookie from your phone without a
// Railway redeploy. Held in memory only (never logged, never written to disk,
// never echoed back); re-paste after a container restart or when it expires.
// When set, it is injected into the dk_api.py subprocess env and OVERRIDES the
// DK_COOKIES env var for that call.
let DK_RUNTIME_COOKIES = '';
let DK_RUNTIME_COOKIES_TS = 0;

// _abck carries its Akamai validation state in the 2nd '~'-delimited field:
// -1 = unvalidated (won't clear the wager endpoint), anything else = validated.
function abckState(cookieStr) {
  const m = /(?:^|;\s*)_abck=([^;]+)/.exec(cookieStr || '');
  if (!m) return 'absent';
  const parts = decodeURIComponent(m[1]).split('~');
  return (parts.length > 1 && parts[1] !== '-1') ? 'validated' : 'unvalidated';
}

function dkCall(args, stdinData) {
  return new Promise((resolve, reject) => {
    const childEnv = DK_RUNTIME_COOKIES
      ? Object.assign({}, process.env, { DK_COOKIES: DK_RUNTIME_COOKIES })
      : process.env;
    const proc = require('child_process').spawn(PYTHON, [DK_PY, ...args], {
      maxBuffer: 50 * 1024 * 1024,
      timeout: 130000,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: childEnv,
    });
    let stdout = '', stderr = '';
    proc.stdout.on('data', d => stdout += d);
    proc.stderr.on('data', d => stderr += d);
    proc.on('close', code => {
      if (code !== 0) {
        // dk_api.py prints {"error": ...} to stdout before exiting 1 — that
        // message (e.g. "calculateBets HTTP 403") is the actual diagnosis;
        // only fall back to stderr / the opaque exit code when there is none.
        try {
          const parsed = JSON.parse(stdout);
          if (parsed && parsed.error) return reject(new Error(parsed.error));
        } catch (_) { /* not JSON — fall through */ }
        return reject(new Error(stderr || 'dk_api.py exited with code ' + code));
      }
      try { resolve(JSON.parse(stdout)); }
      catch (e) { reject(new Error('Failed to parse dk_api.py output: ' + stdout.slice(0, 200))); }
    });
    if (stdinData) { proc.stdin.write(stdinData); }
    proc.stdin.end();
  });
}

// POST /api/soccer/scrape-all — one-button sweep of the major soccer leagues:
// every upcoming game's Pinnacle combo fair lines vs DK's real 2-leg SGP price,
// one flat EV-ranked list. Body (all optional): { sgp_only, max_games,
// window_hours, leagues, deadline_s }. Cached briefly since it's expensive.
const SOCCER_SWEEP_CACHE = new Map();
const SOCCER_SWEEP_TTL_MS = 2 * 60 * 1000;

app.post('/api/soccer/scrape-all', async (req, res) => {
  try {
    const body = req.body || {};
    const key = JSON.stringify([!!body.sgp_only, body.max_games || '', body.window_hours || '',
      (body.leagues || []).join(',')]);
    const hit = SOCCER_SWEEP_CACHE.get(key);
    if (hit && Date.now() - hit.ts < SOCCER_SWEEP_TTL_MS) {
      return res.json(Object.assign({}, hit.body, { cached: true, cache_age_s: Math.round((Date.now() - hit.ts) / 1000) }));
    }
    const result = await dkCall(['find-sgps-soccer-all'], JSON.stringify(body));
    if (!result.error) SOCCER_SWEEP_CACHE.set(key, { ts: Date.now(), body: result });
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'soccer scrape failed: ' + e.message });
  }
});

// ===== DK cookie, set from the website (no Railway redeploy needed) =====
// POST a cookie string here instead of editing the DK_COOKIES env var. It's
// held in server memory only — never logged, never written to disk, never
// returned in a response — and injected into the dk_api.py pricing subprocess,
// overriding DK_COOKIES for the call. Re-paste after a restart or when the
// cookie expires. The app has no auth (same as every other route here), so
// only expose the deployment to people you'd trust with your DK session.
app.post('/api/dk/cookies', (req, res) => {
  try {
    const raw = String((req.body && req.body.cookies) || '').trim();
    if (!raw || raw.indexOf('=') === -1) {
      return res.status(400).json({ error: 'Paste the DK cookie string (name=value; name=value; …).' });
    }
    DK_RUNTIME_COOKIES = raw;
    DK_RUNTIME_COOKIES_TS = Date.now();
    // A fresh cookie should re-price everything — drop cached DK scan results
    // so the next scan actually re-calls calculateBets with the new session.
    try { WC_DK_CACHE.clear(); } catch (_) {}
    try { SOCCER_SWEEP_CACHE.clear(); } catch (_) {}
    const state = abckState(raw);
    let warning = null;
    if (state === 'absent') {
      warning = 'No _abck cookie found — copy the full document.cookie from draftkings.com.';
    } else if (state === 'unvalidated') {
      warning = 'The _abck cookie is not validated yet (its 2nd "~" field is -1). ' +
        'On draftkings.com, click into a game / add legs to a bet slip, then copy again.';
    }
    return res.json({
      ok: true,
      abck: state,                 // validated | unvalidated | absent
      warning: warning,
      cookieCount: raw.split(';').filter(s => s.indexOf('=') > -1).length,
    });
  } catch (e) {
    return res.status(500).json({ error: 'Set DK cookies failed: ' + e.message });
  }
});

// GET current cookie status (never returns the value itself).
app.get('/api/dk/cookies', (_req, res) => {
  if (!DK_RUNTIME_COOKIES) {
    return res.json({ set: false, envFallback: !!process.env.DK_COOKIES });
  }
  return res.json({
    set: true,
    abck: abckState(DK_RUNTIME_COOKIES),
    ageSec: Math.round((Date.now() - DK_RUNTIME_COOKIES_TS) / 1000),
    cookieCount: DK_RUNTIME_COOKIES.split(';').filter(s => s.indexOf('=') > -1).length,
  });
});

// Clear the runtime cookie (falls back to the DK_COOKIES env var, if any).
app.delete('/api/dk/cookies', (_req, res) => {
  DK_RUNTIME_COOKIES = '';
  DK_RUNTIME_COOKIES_TS = 0;
  try { WC_DK_CACHE.clear(); } catch (_) {}
  try { SOCCER_SWEEP_CACHE.clear(); } catch (_) {}
  return res.json({ ok: true, set: false });
});

// GET /api/combo-spec — DK-legal SGP combo whitelist (repo-root combo_spec.json).
// Consumed by the frontend's FV-only fallback: when DK pricing is unreachable
// the client enumerates combos from the OCR'd screenshot legs itself, and it
// needs the same pair/triple validity rules find-sgps would have applied.
// require() caches the parsed JSON for the process lifetime — the spec only
// changes with a deploy.
app.get('/api/combo-spec', (_req, res) => {
  try {
    const spec = require('./combo_spec.json');
    res.setHeader('Cache-Control', 'public, max-age=3600');
    return res.json(spec);
  } catch (e) {
    return res.status(500).json({ error: 'combo_spec.json unavailable: ' + e.message });
  }
});

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
// Body: { legs: [...], enumSize?: 2|3 }. enumSize defaults to 2 for back-compat;
// clients that opt into 3-leg must send enumSize:3. DK pricing is N-leg native,
// but C(k,3) price calls cost time, so the extra budget is only paid on demand.
app.post('/api/dk/find-sgps', async (req, res) => {
  try {
    const { legs, enumSize } = req.body || {};
    if (!Array.isArray(legs) || !legs.length) return res.status(400).json({ error: 'legs array required' });
    const size = enumSize === 3 ? 3 : 2;
    const payload = size === 3 ? { legs, enumSize: 3 } : legs;
    const result = await dkCall(['find-sgps'], JSON.stringify(payload));
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

// POST /api/dk/find-sgps-nba — same-player NBA 2-leg SGP pricing.
// Request body: { candidates: [{ id, player, game, prop1, side1, line1, prop2, side2, line2 }] }
// Response: { results: [{ id, matched, dk_odds, dk_decimal, missing? }], events_scanned, cached?, truncated? }
//
// Cache: 10-minute TTL keyed by a stable hash of the sorted candidate
// handles + their (player, prop, side, line) fingerprint. Selections
// rarely move intraday, and a user re-scan on the same slate is the
// common case — serving cached here avoids burning ~20 calculateBets
// calls + a fresh subcat scan per reload.
const NBA_DK_CACHE = new Map();
const NBA_DK_CACHE_TTL_MS = 10 * 60 * 1000;

function _nbaCacheKey(candidates) {
  var parts = candidates.map(function (c) {
    return [c.id, c.player, c.prop1, c.side1, c.line1, c.prop2, c.side2, c.line2].join('|');
  }).slice().sort();
  return parts.join('\n');
}

app.post('/api/dk/find-sgps-nba', async (req, res) => {
  try {
    const { candidates } = req.body || {};
    if (!Array.isArray(candidates) || !candidates.length) {
      return res.status(400).json({ error: 'candidates array required' });
    }
    const key = _nbaCacheKey(candidates);
    const hit = NBA_DK_CACHE.get(key);
    if (hit && Date.now() - hit.ts < NBA_DK_CACHE_TTL_MS) {
      return res.json(Object.assign({}, hit.body, { cached: true, cache_age_s: Math.round((Date.now() - hit.ts) / 1000) }));
    }
    const result = await dkCall(['find-sgps-nba'], JSON.stringify({ candidates }));
    if (result.error && !result.results) return res.json(result);
    /* Only cache successful responses. A single transient Akamai 503
       shouldn't lock in a broken response for 10 minutes. */
    if (!result.error) NBA_DK_CACHE.set(key, { ts: Date.now(), body: result });
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK find-sgps-nba failed: ' + e.message });
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
  /* MLB Stats API returns names with diacritics (e.g. "Andrés Giménez").
     We preserve that on `displayName` for the UI but fold `player` to
     ASCII so the join key matches the ASCII forms used in TEAMMATE_DATA
     and in FV-sheet OCR output. */
  const raw = p.fullName || (p.person && p.person.fullName) || meta.fullName || null;
  return {
    player: foldAscii(raw),
    displayName: raw,
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
    /* Same display/canonical split as normalizeHydratePlayer above. */
    const fullName = p.person && p.person.fullName;
    starters.push({
      slot: bo / 100,
      player: foldAscii(fullName),
      displayName: fullName,
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

// ===== NBA correlations: daily xlsx upload + persistence =====
// Railway Volume is mounted at /data; our bucket is /data/nba/. The dir
// is created on first upload if missing. For local dev the path is
// overridable via NBA_DATA_DIR so tests/CI don't need /data access.
//
// Cold start (empty volume): /api/nba/correlations and /meta return a
// placeholder with status='empty' + a 200 code so the UI can render a
// "no data yet" card without pretending there's an error. We refuse to
// bundle a default xlsx — staleness ambiguity is worse than an empty state.
//
// Upload path runs the Python parser as a subprocess. It receives the
// xlsx bytes on stdin, validates the 18-column schema, rejects non-same-
// player rows, and writes both the parsed JSON and a meta sidecar. Same
// subprocess pattern as dk_api.py; reuse the python3 invocation style.

const multer = require('multer');
const fs = require('fs');
const NBA_DATA_DIR = process.env.NBA_DATA_DIR || '/data/nba';
const NBA_PARSE_PY = path.join(__dirname, 'scripts', 'nba_parse_correlations.py');
const NBA_CURRENT_FILE = 'correlations_current.json.gz';
const NBA_META_FILE = 'correlations_meta.json';
/* 10 MB cap is for the upload bytes on the wire. matches the spec + the
   Python-side MAX_BYTES guard. Raising this would require bumping the
   Python guard in lockstep. */
const NBA_UPLOAD_MAX_BYTES = 10 * 1024 * 1024;

/* Multer memoryStorage: keeps the xlsx bytes in-process so we can pipe them
   to the Python parser on stdin. No temp file on disk, no race with
   concurrent uploads. We never accept more than one file per request and
   reject any request whose declared multipart field isn't named 'file'. */
const nbaUpload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: NBA_UPLOAD_MAX_BYTES, files: 1, fields: 4 },
});

function nbaRunPython(args, stdinBuf) {
  return new Promise((resolve, reject) => {
    const proc = require('child_process').spawn(PYTHON, [NBA_PARSE_PY, ...args], {
      timeout: 60000,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, NBA_DATA_DIR },
    });
    let stdout = '', stderr = '';
    proc.stdout.on('data', d => { stdout += d; });
    proc.stderr.on('data', d => { stderr += d; });
    proc.on('error', err => reject(err));
    proc.on('close', code => {
      if (code !== 0) {
        return reject(new Error(stderr || ('nba_parse_correlations.py exited ' + code)));
      }
      const line = stdout.trim().split('\n').pop() || '';
      try { resolve(JSON.parse(line)); }
      catch (e) { reject(new Error('parser emitted unparseable JSON: ' + line.slice(0, 300))); }
    });
    if (stdinBuf) proc.stdin.write(stdinBuf);
    proc.stdin.end();
  });
}

function nbaEmptyMeta() {
  return {
    status: 'empty',
    uploaded_at: null,
    season: null,
    source_filename: null,
    row_count: 0,
    distinct_players: 0,
  };
}

/* POST /api/nba/upload-correlations
   Body: multipart/form-data with field `file` (xlsx, <=10MB).
   On success: 200 { ok:true, uploaded_at, row_count, distinct_players, ... }
   On client error (bad file / schema / size): 400 { ok:false, error }
   On server error (python fails hard): 500 { error }. Existing data stays
   untouched because the parser only writes after validation passes. */
app.post('/api/nba/upload-correlations', (req, res, next) => {
  nbaUpload.single('file')(req, res, function (err) {
    if (err) {
      const status = err.code === 'LIMIT_FILE_SIZE' ? 413 : 400;
      return res.status(status).json({ ok: false, error: 'Upload rejected: ' + err.message });
    }
    next();
  });
}, async (req, res) => {
  try {
    if (!req.file || !req.file.buffer || !req.file.buffer.length) {
      return res.status(400).json({ ok: false, error: 'No file received (expected multipart field name "file")' });
    }
    const fname = req.file.originalname || 'uploaded.xlsx';
    if (!fname.toLowerCase().endsWith('.xlsx')) {
      return res.status(400).json({ ok: false, error: 'File must be .xlsx (got ' + fname + ')' });
    }
    const result = await nbaRunPython(
      ['--out-dir', NBA_DATA_DIR, '--source-filename', fname],
      req.file.buffer,
    );
    if (!result.ok) {
      return res.status(422).json(result);
    }
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'nba upload failed: ' + e.message });
  }
});

/* GET /api/nba/correlations
   Serves the gzipped parsed dataset. Sets Content-Encoding:gzip so the
   browser inflates transparently. On cold-start (no file yet) responds
   200 with {status:'empty', entries:[], by_player:{}} — UI renders an
   "upload your xlsx" card rather than an error. */
app.get('/api/nba/correlations', (req, res) => {
  const p = path.join(NBA_DATA_DIR, NBA_CURRENT_FILE);
  fs.stat(p, (err, st) => {
    if (err || !st.isFile()) {
      return res.json({
        schema_version: 1,
        status: 'empty',
        season: null,
        uploaded_at: null,
        entries: [],
        by_player: {},
      });
    }
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('Content-Encoding', 'gzip');
    res.setHeader('Cache-Control', 'private, max-age=60');
    fs.createReadStream(p).pipe(res);
  });
});

/* GET /api/nba/correlations/meta
   Serves the sidecar meta (small, uncompressed JSON). Cold start returns
   a placeholder with status='empty'. UI binds to this for the "Last
   updated" line above the upload card. */
app.get('/api/nba/correlations/meta', (req, res) => {
  const p = path.join(NBA_DATA_DIR, NBA_META_FILE);
  fs.readFile(p, 'utf8', (err, buf) => {
    if (err) return res.json(nbaEmptyMeta());
    try {
      const meta = JSON.parse(buf);
      meta.status = 'ok';
      return res.json(meta);
    } catch (_) {
      return res.json(nbaEmptyMeta());
    }
  });
});

/* POST /api/nba/correlations/rollback
   Restores the most recent file from correlations_history/. The UI wraps
   this in a confirmation prompt — no additional guard here. */
app.post('/api/nba/correlations/rollback', async (_req, res) => {
  try {
    const result = await nbaRunPython(['--action', 'rollback', '--out-dir', NBA_DATA_DIR]);
    if (!result.ok) return res.status(400).json(result);
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'nba rollback failed: ' + e.message });
  }
});

// GET /api/nba/scoreboard?dates=YYYYMMDD — ESPN's NBA scoreboard, relayed for
// browsers that can't reach ESPN themselves (nba.html tries ESPN first).
const NBA_SB_CACHE = new Map();  // dates -> { ts, body }
app.get('/api/nba/scoreboard', async (req, res) => {
  const dates = String(req.query.dates || '');
  if (!/^\d{8}$/.test(dates)) return res.status(400).json({ error: 'dates=YYYYMMDD' });
  const hit = NBA_SB_CACHE.get(dates);
  if (hit && Date.now() - hit.ts < 60 * 1000) return res.json(hit.body);
  try {
    const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=${dates}`);
    if (!r.ok) return res.status(502).json({ error: `ESPN answered ${r.status}` });
    const body = await r.json();
    if (NBA_SB_CACHE.size > 20) NBA_SB_CACHE.clear();
    NBA_SB_CACHE.set(dates, { ts: Date.now(), body });
    return res.json(body);
  } catch (e) {
    return res.status(502).json({ error: 'ESPN scoreboard failed: ' + e.message });
  }
});

// ---- NBA: first dunk (public/nba_dunk.html) --------------------------------
// GET /api/nba/injuries — ESPN's league injury list, slimmed to
// { players: { <ESPN athlete id>: { status, note } } }. Cached five minutes.
let NBA_INJ_CACHE = null;
app.get('/api/nba/injuries', async (_req, res) => {
  if (NBA_INJ_CACHE && Date.now() - NBA_INJ_CACHE.ts < 5 * 60 * 1000) return res.json(NBA_INJ_CACHE.body);
  try {
    const r = await fetch('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries');
    if (!r.ok) return res.status(502).json({ error: `ESPN answered ${r.status}` });
    const j = await r.json();
    const players = {};
    for (const t of j.injuries || []) {
      for (const i of t.injuries || []) {
        const a = i.athlete || {};
        const href = ((a.links || [])[0] || {}).href || '';
        const id = String(a.id || (href.match(/\/id\/(\d+)/) || [])[1] || '');
        if (!id) continue;
        const fs = ((i.details || {}).fantasyStatus || {}).abbreviation || '';
        players[id] = {
          name: a.displayName || '',
          status: (fs === 'OUT' || fs === 'OFS' || /^out/i.test(i.status || '')) && fs !== 'GTD' ? 'out' : 'gtd',
          note: i.shortComment || '',
        };
      }
    }
    const body = { players };
    NBA_INJ_CACHE = { ts: Date.now(), body };
    return res.json(body);
  } catch (e) {
    return res.status(502).json({ error: 'ESPN injuries failed: ' + e.message });
  }
});

// GET /api/nba/lineups — starting fives and injury statuses for today's and
// tomorrow's games, from Rotowire's lineups page (nbaLineups.js). Each game
// carries the date it is for. Cached three minutes; an old answer is served,
// marked stale, when Rotowire stops answering.
let NBA_LU_CACHE = null;
app.get('/api/nba/lineups', async (req, res) => {
  if (!req.query.fresh && NBA_LU_CACHE && Date.now() - NBA_LU_CACHE.ts < 3 * 60 * 1000) return res.json(NBA_LU_CACHE.body);
  try {
    const body = await require('./nbaLineups.js').fetchLineups();
    body.fetched = new Date().toISOString();
    NBA_LU_CACHE = { ts: Date.now(), body };
    return res.json(body);
  } catch (e) {
    if (NBA_LU_CACHE) return res.json(Object.assign({}, NBA_LU_CACHE.body, { stale: true }));
    return res.status(502).json({ error: 'Rotowire lineups failed: ' + e.message });
  }
});

// GET /api/dk/nba-first-dunk — DraftKings' markets with "dunk" in the name for
// tonight's NBA games, each selection with its price (dk_api.py
// nba_named_markets; one request a game). Cached two minutes.
let DK_DUNK_CACHE = null;
app.get('/api/dk/nba-first-dunk', async (req, res) => {
  try {
    if (!req.query.fresh && DK_DUNK_CACHE && Date.now() - DK_DUNK_CACHE.ts < 2 * 60 * 1000) {
      return res.json(Object.assign({}, DK_DUNK_CACHE.body, { cached: true }));
    }
    const result = await dkCall(['nba-named-markets', 'dunk']);
    if (!result.error) DK_DUNK_CACHE = { ts: Date.now(), body: result };
    return res.json(result);
  } catch (e) {
    return res.status(500).json({ error: 'DK first dunk failed: ' + e.message });
  }
});

// ---- NBA: Novig SGP scanner (public/nba_scan.html) -------------------------
// .claude/skills/nba-sgp-fv/scan.py quotes every same-player combo worth
// asking Novig about and streams one JSON event per line. Novig's quote limit
// is per IP (one a second), so one pass runs at a time, here on the server.
// The page polls this route for the board. A pass starts when the Fetch
// button is pressed, or from the auto-scan cycle below while it is switched on.
const NV_SCAN_PY = path.join(__dirname, '.claude', 'skills', 'nba-sgp-fv', 'scan.py');
// Every quote is a live auction sent to all of Novig's parlay pricers, so
// nothing here scans on its own unless auto-scan is on: a pass runs when the
// page's Fetch button asks for one (?now=1), at most once a minute for the
// same board.
const NV_SCAN_NOW_MS = 60 * 1000;
const NV_SCAN_MAX_MS = 90 * 60 * 1000;   // a pass stuck this long is killed (the NFL tab on a full board, Unders included, runs about 50 minutes)
// One board per league and book width ("nba:0", "nfl:1", ...). The last pass
// of each is kept, in memory and on disk, until the next Fetch replaces it:
// leaving the page, switching league or a redeploy doesn't lose it (the disk
// copy survives a redeploy only where NBA_DATA_DIR / /data is a volume).
const NV_BOARDS = new Map();
// A pass asks first the rows its board's last pass left at this EV or better
// (a little under fair: those are the ones that cross it), best first.
const NV_LEAD_EV = -0.02, NV_LEAD_MAX = 400;
let NV_RUN = null;   // { proc, key, stop, auto } while a pass is running
let NV_KRUN = null;  // the same for a Kalshi board: its own slot, so it runs beside a Novig pass
// The Kalshi NBA tab's Fetch (Max, 11-26: hard to tell which board to run): the four NBA boards
// priced one after another in the order listed, on the one Kalshi slot. NV_KQUEUE holds the ones still to
// come, as { league, wide }. A pass that fails or times out moves on to the next; Stop ends the lot.
// The Kalshi NFL tab is the same over its three boards (Max, 11-26: let's combine NFL too).
const NV_KGROUPS = { kalshinbaall: ['kalshinba3', 'kalshinba', 'kalshinbatri', 'kalshinbaline'],
                     kalshinflall: ['kalshinfl', 'kalshinflline', 'kalshinfltri'] };
let NV_KQUEUE = [];
function nvKNext() { while (!NV_KRUN && NV_KQUEUE.length) { const q = NV_KQUEUE.shift(); startNovigScan(q.league, q.wide); } }
let NV_LAST_END = 0; // when the last pass ended, however it ended
const NV_SCAN_FILE = (() => {
  const fsx = require('fs'), os = require('os');
  for (const dir of [process.env.NBA_DATA_DIR, '/data/nba', os.tmpdir()]) {
    if (!dir) continue;
    try { fsx.mkdirSync(dir, { recursive: true }); fsx.accessSync(dir, fsx.constants.W_OK); return path.join(dir, 'novig_scan_boards.json'); } catch (_) { /* next */ }
  }
  return null;
})();
function nvBoard(key) {
  if (!NV_BOARDS.has(key)) {
    NV_BOARDS.set(key, { started: 0, finished: 0, total: 0, done: 0, players: 0, data: null, seconds: 0,
                         error: null, rows: new Map(), seen: new Set() });
  }
  return NV_BOARDS.get(key);
}
function nvSaveBoards() {
  if (!NV_SCAN_FILE) return;
  const out = {};
  for (const [k, b] of NV_BOARDS) out[k] = Object.assign({}, b, { rows: [...b.rows.values()], seen: undefined });
  require('fs').writeFile(NV_SCAN_FILE, JSON.stringify(out), () => {});
}
try {
  const saved = JSON.parse(require('fs').readFileSync(NV_SCAN_FILE, 'utf8'));
  for (const [k, b] of Object.entries(saved)) {
    NV_BOARDS.set(k, Object.assign(b, { rows: new Map((b.rows || []).map(r => [r.key, r])), seen: new Set() }));
  }
} catch (_) { /* no saved boards yet */ }

const NV_PY_LEAGUE = league => ({ ladder: 'nba', nbateam: 'nba', dknba: 'nba', kalshinba: 'nba', kalshinba3: 'nba', kalshinbatri: 'nba', kalshinbaline: 'nba', kalshinfl: 'nfl', kalshinflline: 'nfl', kalshinfltri: 'nfl', kalshicbb: 'cbb', kalshicfb: 'cfb', nflladder: 'nfl', nhllines: 'nhl' }[league] || league);
// The DK NBA board: the NBA slips priced on DraftKings (scan_dk.py). Its own script; same events.
const NV_DK_PY = path.join(__dirname, '.claude', 'skills', 'nba-sgp-fv', 'scan_dk.py');
// Every board but 'nba' (the default). 'nbateam' is the NBA Team board:
// scan.py --league nba --kind team.
// The Kalshi boards: slips asked as Kalshi combos (scan_kalshi.py; 'kalshinba3' is Points + Threes
// alone, 'kalshinba' the other pairs and teammates: split 11-18; 'kalshinbatri' three legs on the
// high scorers, 11-21; 'kalshinfltri' the NFL three-leg slips, 11-23), signed with
// KALSHI_KEY_ID / KALSHI_PRIVATE_KEY. Fetch only, like the DK board.
const NV_KALSHI_PY = path.join(__dirname, '.claude', 'skills', 'nba-sgp-fv', 'scan_kalshi.py');
const NV_OWN_SCRIPT = { dknba: NV_DK_PY, kalshinba: NV_KALSHI_PY, kalshinba3: NV_KALSHI_PY, kalshinbatri: NV_KALSHI_PY, kalshinbaline: NV_KALSHI_PY, kalshinfl: NV_KALSHI_PY, kalshinflline: NV_KALSHI_PY, kalshinfltri: NV_KALSHI_PY, kalshicbb: NV_KALSHI_PY, kalshicfb: NV_KALSHI_PY };
const nvKalshi = league => String(league).startsWith('kalshi');
// The Ladder boards (Max, 11-27: their own tab, off the Novig one; and look up Novig and Kalshi,
// to see a slip taken on Novig isn't better on Kalshi). A pass on one asks Novig as before, then
// Kalshi for the same slip where it lists every leg on the same line (scan.py --kalshi). The
// Kalshi asks are signed with the owner's key, so the Ladder boards answer only to a request that
// carries the Kalshi passcode as well as the scanner's (423 without it, as the Kalshi boards).
const NV_LADDERS = ['ladder', 'nflladder'];
const NV_LEAGUES = ['nfl', 'nhl', 'nhllines', 'soccer', 'cfb', 'cbb', 'ladder', 'nflladder', 'nbateam', 'dknba', 'kalshinba3', 'kalshinba', 'kalshinbatri', 'kalshinbaline', 'kalshinfl', 'kalshinflline', 'kalshinfltri', 'kalshicbb', 'kalshicfb'];
// GET /api/nba/novig-games?league= — the league's open pregame games for the
// page's game picker: [{ id, name, starts }]. One catalog read, kept 2 minutes.
const NV_GAMES = new Map();   // python league -> { at, games }
app.get('/api/nba/novig-games', (req, res) => {
  if (!nvBetsAuth(req, res)) return;
  const lg = NV_PY_LEAGUE(NV_LEAGUES.includes(req.query.league) ? req.query.league : 'nba');
  nvGames(lg, games => (games ? res.json({ games }) : res.status(502).json({ error: 'could not read Novig\'s games' })));
});
// The league's open pregame games, soonest first (null if Novig couldn't be read).
function nvGames(lg, cb) {
  const hit = NV_GAMES.get(lg);
  if (hit && Date.now() - hit.at < 120000) return cb(hit.games);
  require('child_process').execFile(PYTHON, [NV_SCAN_PY, '--games', '--league', lg], { timeout: 60000, maxBuffer: 4e6 }, (e, out) => {
    let games = null;
    try { games = JSON.parse(String(out).trim().split('\n').pop()); } catch (_) { /* not JSON */ }
    if (e || !Array.isArray(games)) return cb(null);
    NV_GAMES.set(lg, { at: Date.now(), games });
    cb(games);
  });
}

// events: Novig event ids picked on the page (the game picker); empty = the whole board.
// before: only games starting before this time (ms); Auto-scan's end of today.
// full: games starting at or after this time (ms) get one slip only (scan.py --full-before).
// kalshi: a Ladder board's pass also asks Kalshi for each slip (the request carried the Kalshi passcode).
function startNovigScan(league, wide, events, auto, before, full, kalshi) {
  const onKalshi = String(league).startsWith('kalshi');
  if (onKalshi ? NV_KRUN : NV_RUN) return;
  events = events || [];
  const key = `${league}:${wide ? 1 : 0}`, B = nvBoard(key);
  // wide: also price legs on books up to 8c (10c for the second threes
  // milestone); the page flags those rows as rough.
  // "ladder" is its own NBA board: the shooters' higher lines (one-way lines
  // included), fair values shifted from the main line (scan.py --scope ladder).
  const args = NV_OWN_SCRIPT[league] ? [NV_OWN_SCRIPT[league], '--json'].concat(nvKalshi(league) ? ['--league', league.slice(6)] : []).concat(before ? ['--before', String(before)] : []) : [NV_SCAN_PY, '--json'].concat(league === 'ladder' ? ['--league', 'nba', '--scope', 'ladder'] :
    league === 'nflladder' ? ['--league', 'nfl', '--scope', 'ladder'] :
    league === 'nhllines' ? ['--league', 'nhl', '--kind', 'lines'] :
    league === 'nbateam' ? ['--league', 'nba', '--kind', 'team'] : ['--league', league]).concat(wide ? ['--max-spread', '0.08', '--alt-spread', '0.10'] : [])
    .concat(events.length ? ['--events', ...events] : []).concat(before ? ['--before', String(before)] : [])
    .concat(full ? ['--full-before', String(full)] : []);
  kalshi = !!kalshi && NV_LADDERS.includes(league);
  if (kalshi) args.push('--kalshi');
  // The last pass's best rows are asked first (scan.py --first), so the top
  // of the board is fresh minutes into a pass instead of whenever the pass
  // reaches each row (an NFL pass is about 50 minutes).
  const lead = [...B.rows.values()].filter(r => r.ev >= NV_LEAD_EV).sort((x, y) => y.ev - x.ev).slice(0, NV_LEAD_MAX).map(r => r.key);
  if (lead.length && NV_SCAN_FILE && !NV_OWN_SCRIPT[league]) {
    const f = path.join(path.dirname(NV_SCAN_FILE), `novig_first_${league}_${wide ? 1 : 0}.json`);
    try { require('fs').writeFileSync(f, JSON.stringify(lead)); args.push('--first', f); } catch (_) { /* the pass runs in its usual order */ }
  }
  let proc;
  try {
    // The DK board prices with the cookie pasted in the main app (Soccer tab,
    // "DK cookie"), as the app's own DK pricing does.
    const env = league === 'dknba' && DK_RUNTIME_COOKIES ? Object.assign({}, process.env, { DK_COOKIES: DK_RUNTIME_COOKIES }) : process.env;
    proc = require('child_process').spawn(PYTHON, args, { stdio: ['ignore', 'pipe', 'pipe'], env });
  } catch (e) {
    B.error = 'scan could not start: ' + e.message;
    return;
  }
  let live = true;   // false once the pass has ended or been stopped
  Object.assign(B, { started: Date.now(), total: 0, done: 0, error: null, stopped: 0, seen: new Set(), events, before: before || 0, why: {}, kalshi, knote: null });
  // A Kalshi board starts each pass empty (Max, 11-20): only what this
  // Fetch priced is on it. A pass stopped part-way keeps the rows it reached.
  if (onKalshi) B.rows.clear();
  const timer = setTimeout(() => { const R = onKalshi ? NV_KRUN : NV_RUN; if (R && R.proc === proc) proc.kill(); }, NV_SCAN_MAX_MS);
  let buf = '', err = '', ok = false;
  const onEvent = e => {
    if (!live) return;
    if (e.type === 'start') { B.total = e.total; B.players = e.players; B.data = e.data; B.books = e.books || null; }
    else if (e.type === 'more') { B.total += e.add; if (e.players) B.players = e.players; }
    else if (e.type === 'row') { B.done++; B.seen.add(e.key); B.rows.set(e.key, e); nvAlert(league, wide, e); }
    // why a slip got no price, counted for the page (Max, 11-21: am I out of scans?)
    else if (e.type === 'miss') { B.done++; B.rows.delete(e.key); const w = String(e.why || 'no reason given').slice(0, 120); B.why = B.why || {}; B.why[w] = (B.why[w] || 0) + 1; }
    // A Ladder row's Kalshi price, after its Novig one (scan.py --kalshi): set on the row it belongs to.
    else if (e.type === 'kalshi') { const r = B.rows.get(e.key); if (r && e.set) { for (const k of Object.keys(r)) if (k.startsWith('kalshi_')) delete r[k]; Object.assign(r, e.set); } }
    else if (e.type === 'kalshi_off') { B.knote = String(e.why || '').slice(0, 300); }
    else if (e.type === 'done') { ok = true; B.seconds = e.seconds; }
  };
  proc.stdout.on('data', chunk => {
    buf += chunk;
    for (let i; (i = buf.indexOf('\n')) >= 0; buf = buf.slice(i + 1)) {
      try { onEvent(JSON.parse(buf.slice(0, i))); } catch (_) { /* not an event line */ }
    }
  });
  proc.stderr.on('data', c => { err = (err + c).slice(-4000); });
  const end = (why, stopped) => {
    if (!live) return;
    live = false;
    clearTimeout(timer);
    if (onKalshi) NV_KRUN = null; else { NV_RUN = null; NV_LAST_END = Date.now(); }
    if (onKalshi && stopped) NV_KQUEUE = [];   // Stop ends the boards still queued behind this one
    if (stopped && !ok) {
      // Stopped from the page: rows it priced are kept, and rows it didn't
      // reach stay at their earlier prices (each row carries its own age).
      B.stopped = Date.now();
    } else if (ok) {
      B.finished = Date.now();
      // A combo this pass didn't price is gone: its line moved or closed.
      // A pass of picked games says nothing about the other games' rows.
      // Nor does a pass of today's games about later days' rows.
      for (const [k, r] of [...B.rows]) {
        if (!B.seen.has(k) && (!events.length || events.includes(r.event)) && (!before || !r.starts || r.starts < before)) B.rows.delete(k);
      }
    } else {
      B.error = (why || err.trim().split('\n').pop() || 'scan stopped early').slice(0, 500);
    }
    nvSaveBoards();
    if (onKalshi) nvKNext();
  };
  proc.on('error', e => end('scan could not start: ' + e.message));
  proc.on('close', () => end(''));
  // Frees the scanner at once, so another pass can start in the same request.
  const run = { proc, key, auto: !!auto, stop: () => { end('', true); proc.kill(); } };
  if (onKalshi) NV_KRUN = run; else NV_RUN = run;
}

// A Kalshi tab's Fetch (Max, 11-27: it looks like we do 3s first, then other plays; do everything at
// the same time): one pass over every board of the group (scan_kalshi.py --league nbaall / nflall),
// asked player by player, so a player's slips on all its boards are priced seconds apart. Each event
// names its board and is filed under that board, which is read and bet on as before. It holds the one
// Kalshi slot; run.keys are the boards it is pricing.
function startKalshiGroup(name, wide) {
  if (NV_KRUN) return;
  const leagues = NV_KGROUPS[name], keyOf = l => `${l}:${wide ? 1 : 0}`;
  const Bs = new Map(leagues.map(l => [l, nvBoard(keyOf(l))]));
  let proc;
  try {
    proc = require('child_process').spawn(PYTHON, [NV_KALSHI_PY, '--json', '--league', name.slice(6)], { stdio: ['ignore', 'pipe', 'pipe'] });
  } catch (e) {
    for (const B of Bs.values()) B.error = 'scan could not start: ' + e.message;
    return;
  }
  let live = true, buf = '', err = '', ok = false;
  for (const B of Bs.values()) {
    Object.assign(B, { started: Date.now(), total: 0, done: 0, error: null, stopped: 0, seen: new Set(), events: [], before: 0, why: {}, kalshi: false, knote: null });
    B.rows.clear();
  }
  const timer = setTimeout(() => { if (NV_KRUN && NV_KRUN.proc === proc) proc.kill(); }, NV_SCAN_MAX_MS);
  const onEvent = e => {
    if (!live) return;
    const B = Bs.get(e.board);
    if (!B) { if (e.type === 'done') ok = true; return; }
    if (e.type === 'start') { B.total = e.total; B.players = e.players; B.data = e.data; B.books = null; }
    else if (e.type === 'row') {
      // filed without its board: a board's own rows carry none (the page keys a row by it only on a tab of several boards)
      const row = Object.assign({}, e); delete row.board;
      B.done++; B.seen.add(row.key); B.rows.set(row.key, row); nvAlert(e.board, wide, row);
    }
    else if (e.type === 'miss') { B.done++; B.rows.delete(e.key); const w = String(e.why || 'no reason given').slice(0, 120); B.why[w] = (B.why[w] || 0) + 1; }
    else if (e.type === 'done') { B.seconds = e.seconds; }
  };
  proc.stdout.on('data', chunk => {
    buf += chunk;
    for (let i; (i = buf.indexOf('\n')) >= 0; buf = buf.slice(i + 1)) {
      try { onEvent(JSON.parse(buf.slice(0, i))); } catch (_) { /* not an event line */ }
    }
  });
  proc.stderr.on('data', c => { err = (err + c).slice(-4000); });
  const end = (why, stopped) => {
    if (!live) return;
    live = false;
    clearTimeout(timer);
    NV_KRUN = null;
    if (stopped) NV_KQUEUE = [];
    for (const B of Bs.values()) {
      if (stopped && !ok) B.stopped = Date.now();   // the rows it reached are kept
      else if (ok) B.finished = Date.now();
      else B.error = (why || err.trim().split('\n').pop() || 'scan stopped early').slice(0, 500);
    }
    nvSaveBoards();
    nvKNext();
  };
  proc.on('error', e => end('scan could not start: ' + e.message));
  proc.on('close', () => end(''));
  NV_KRUN = { proc, key: `${name}:${wide ? 1 : 0}`, keys: leagues.map(keyOf), auto: false, stop: () => { end('', true); proc.kill(); } };
}

// Players who are out: ESPN's injury report for the NFL and the NBA, read
// again every ten minutes while the boards are being looked at or auto-scan
// is on. Novig keeps a ruled-out player's props open for hours (11-14: T.J.
// Hockenson, out since Friday afternoon, still headed the board that night),
// so his rows are left off the page. They
// stay in the saved board and come back if the report changes.
// Out = ESPN's Out, Injured Reserve, Suspension or Doubtful.
const NV_OUT = { nfl: { at: 0, names: new Map(), last: new Map(), maybe: new Map() }, nba: { at: 0, names: new Map(), last: new Map(), maybe: new Map() } };
const NV_OUT_EVERY_MS = 10 * 60 * 1000;
const nvName = n => String(n || '').toLowerCase().normalize('NFD').replace(/[^a-z ]/g, '').replace(/ (jr|sr|ii|iii|iv|v)$/, '').replace(/\s+/g, ' ').trim();
let NV_OUT_BUSY = false;
async function nvOutRefresh() {
  if (NV_OUT_BUSY) return;
  NV_OUT_BUSY = true;
  for (const [lg, sport] of [['nfl', 'football/nfl'], ['nba', 'basketball/nba']]) {
    if (Date.now() - NV_OUT[lg].at < NV_OUT_EVERY_MS) continue;
    NV_OUT[lg].at = Date.now();   // a failed read waits its ten minutes too; the last good list stays
    try {
      const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/${sport}/injuries`, { signal: AbortSignal.timeout(30000) });
      if (!r.ok) throw new Error('ESPN answered ' + r.status);
      const names = new Map(), last = new Map(), maybe = new Map();
      // ESPN's NBA report has no Doubtful or Questionable status: both are
      // "Day-To-Day", and the word is in the note ("Tyson (ankle) has been
      // downgraded to doubtful for Monday's game", 11-16: he headed the board
      // at +22% an hour after that). So a Day-To-Day note about today's game
      // is read: doubtful or out hides the player.
      const today = new Intl.DateTimeFormat('en-US', { timeZone: NV_TZ, weekday: 'long' }).format(Date.now());
      for (const t of (await r.json()).injuries || []) {
        for (const i of t.injuries || []) {
          let status = i.status || '';
          const note = String(i.shortComment || '');
          if (/^day-to-day$/i.test(status)) {
            const day = (note.match(/\b(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)'s\b/) || [])[1];
            // Any other Day-To-Day player is a game-time decision and is
            // flagged, whatever day his note is about (11-17: Kuminga left
            // Monday's game hurt, the note only described Monday, and he
            // headed Tuesday's board unflagged).
            if (day === today && /\b(doubtful|ruled out|is out|out for|won't play|will not play|will miss|will sit)\b/i.test(note) && !/\bupgraded\b/i.test(note)) status = 'Doubtful';
            else status = 'Questionable';
          }
          if (/^questionable$/i.test(status)) { maybe.set(nvName((i.athlete || {}).displayName), note || 'Questionable'); continue; }
          if (!/^(out|injured reserve|suspension|doubtful)$/i.test(status)) continue;
          const a = i.athlete || {}, team = String((a.team || {}).abbreviation || '').toUpperCase();
          names.set(nvName(a.displayName), status);
          const l = nvName(a.lastName);   // "Stroud 21+ CMP": a leg on another player names him by last name
          if (l) last.set(l, (last.get(l) || []).concat(team));
        }
      }
      NV_OUT[lg].names = names; NV_OUT[lg].last = last; NV_OUT[lg].maybe = maybe;
    } catch (e) { console.warn(`Novig scan: could not read ESPN's ${lg.toUpperCase()} injury report: ${e.message}`); }
    if (lg === 'nba') {
      try { NV_OUT.nba.league = await nvNbaReport(); }
      catch (e) { console.warn(`Novig scan: could not read the NBA's injury report: ${e.message}`); }
    }
  }
  NV_OUT_BUSY = false;
}
// The NBA's own injury report (Max, 11-27: Dean Wade, downgraded to questionable at noon, headed the
// board at +31% ninety minutes later with no tag; ESPN's report and Rotowire's page still had no line
// on him). The league posts it as a PDF every half hour (ak-static.cms.nba.com/referee/injury/
// Injury-Report_2026-11-27_02_30PM.pdf, Eastern time), and it is where the news accounts read a
// downgrade from. Read beside ESPN's: Out or Doubtful hides a player, Questionable flags him.
// Its text has no spaces ("Wade,DeanQuestionable", "Philadelphia76ersBrown,JaylenOut"), so players
// are keyed by their names with the spaces out.
const NV_NBA_TEAMS = ['AtlantaHawks', 'BostonCeltics', 'BrooklynNets', 'CharlotteHornets', 'ChicagoBulls', 'ClevelandCavaliers', 'DallasMavericks', 'DenverNuggets',
  'DetroitPistons', 'GoldenStateWarriors', 'HoustonRockets', 'IndianaPacers', 'LAClippers', 'LosAngelesClippers', 'LosAngelesLakers', 'MemphisGrizzlies', 'MiamiHeat',
  'MilwaukeeBucks', 'MinnesotaTimberwolves', 'NewOrleansPelicans', 'NewYorkKnicks', 'OklahomaCityThunder', 'OrlandoMagic', 'Philadelphia76ers', 'PhoenixSuns',
  'PortlandTrailBlazers', 'SacramentoKings', 'SanAntonioSpurs', 'TorontoRaptors', 'UtahJazz', 'WashingtonWizards'];
const nvKeyX = n => nvName(n).replace(/ /g, '');
// { out: Map(key -> status), maybe: Map(key -> note), stamp } from the report's text
function nvNbaReportParse(text, stamp) {
  const out = new Map(), maybe = new Map();
  const teamRe = new RegExp('^.*?(?:' + NV_NBA_TEAMS.join('|') + ')');
  for (const raw of String(text || '').split('\n')) {
    const line = raw.trim().replace(teamRe, '');
    const m = line.match(/^([A-Za-z'.\- ]+?),([A-Za-z'.\- ]+?)(Out|Questionable|Doubtful|Probable|Available)(.*)$/);
    if (!m) continue;
    const key = nvKeyX(m[2] + ' ' + m[1].replace(/(Jr\.?|Sr\.?|III|II|IV)$/, ''));
    if (!key || out.has(key) || maybe.has(key)) continue;   // the first line on a player is his next game
    const why = m[4].replace(/^Injury\/Illness-/, '').replace(/([a-z])([A-Z])/g, '$1 $2').trim();
    if (m[3] === 'Out' || m[3] === 'Doubtful') out.set(key, m[3]);
    else if (m[3] === 'Questionable') maybe.set(key, `Questionable${why ? ': ' + why : ''} (NBA injury report, ${stamp} ET)`);
  }
  return { out, maybe, stamp };
}
async function nvNbaReport() {
  // the newest report: this half hour's, or the one before it, back three hours
  for (let back = 0; back < 7; back++) {
    const t = new Date(Math.floor(Date.now() / 1800000) * 1800000 - back * 1800000);
    const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: true }).formatToParts(t).map(x => [x.type, x.value]));
    const url = `https://ak-static.cms.nba.com/referee/injury/Injury-Report_${p.year}-${p.month}-${p.day}_${p.hour}_${p.minute}${p.dayPeriod.toUpperCase()}.pdf`;
    const r = await fetch(url, { signal: AbortSignal.timeout(20000) });
    if (!r.ok) continue;   // not posted yet (403 until it is)
    const data = await require('pdf-parse')(Buffer.from(await r.arrayBuffer()));
    const got = nvNbaReportParse(data.text, `${Number(p.hour)}:${p.minute} ${p.dayPeriod.toUpperCase()}`);
    if (got.out.size + got.maybe.size === 0) throw new Error('no player line read in ' + url);
    return got;
  }
  throw new Error('no report posted in the last three hours');
}
// Is this row's player (either one of a two-player slip, or a quarterback a
// leg names) out?
// Kalshi Pts + 3s, Kalshi NBA and Kalshi NBA 3-Leg show no slip with a leg under 30% (Max, 11-18; scan_kalshi.py
// --leg-min stops asking them, this hides rows from older passes and rows a refresh moved under it).
const nvLong = (league, row) => (league === 'kalshinba' || league === 'kalshinba3' || league === 'kalshinbatri') && (row.legs || []).some(L => L.p < 0.30 - 1e-9);
function nvOut(league, row) {
  const O = NV_OUT[NV_PY_LEAGUE(league)];
  if (O && O.league && String(row.player || '').split(' + ').some(n => O.league.out.has(nvKeyX(n)))) return true;   // the NBA's own report
  if (!O || !O.names.size) return false;
  if (String(row.player || '').split(' + ').some(n => O.names.has(nvName(n)))) return true;
  const team = String(row.team || '').toUpperCase();
  return (row.legs || []).some(L => {
    const teams = L.text && O.last.get(nvName(String(L.text).split(' ')[0]));
    return !!teams && teams.includes(team) && /^[A-Z][a-z'.-]+ \d/.test(L.text);
  });
}

// A row whose player is questionable goes out with the report's note on it
// (gtd), for the page to flag: he may sit, and the price may know it.
function nvFlag(league, row) {
  const O = NV_OUT[NV_PY_LEAGUE(league)];
  if (!O || !(O.maybe.size || O.league)) return row;
  const note = String(row.player || '').split(' + ').map(n => (O.league && O.league.maybe.get(nvKeyX(n))) || O.maybe.get(nvName(n))).find(Boolean);
  return note ? Object.assign({}, row, { gtd: note }) : row;
}

// Discord alerts (novigAlerts.js): while Auto-scan is on, every row a pass or
// a refresh prices is offered to it, and it sends the ones worth a message. Nothing is priced
// there and nothing is ever bet: a row carries its own fair value, EV and stake.
// Wide-book passes and the Kalshi and DK boards don't alert.
const NV_ALERTS = require('./novigAlerts.js').create({ dir: NV_SCAN_FILE ? path.dirname(NV_SCAN_FILE) : null });
// One button for the page and for Discord (Max, 11-20): alerts go out only
// while Auto-scan is on. With it off nothing is sent, a Fetch's or a
// refresh's rows included.
function nvAlert(league, wide, row) {
  if (!NV_CYCLE || wide || NV_OWN_SCRIPT[league]) return;
  try {
    const g = (NV_GAMES.get(NV_PY_LEAGUE(league)) || {}).games || [];
    const game = (g.find(x => x.id === (row.event || row.id)) || {}).name || '';
    NV_ALERTS.consider(league, nvFlag(league, row), { out: nvLong(league, row) || nvOut(league, row), game });
  } catch (e) { console.warn('Novig alert: ' + e.message); }
}
{
  const a = NV_ALERTS.status();
  if (a.enabled) console.log(`Novig alerts: on${a.dry ? ' (dry run: nothing is posted)' : a.webhook ? '' : ' but DISCORD_WEBHOOK_URL is not set'}; boards ${a.sports.join(', ')}; sent only while Auto-scan is on`);
}
// POST /api/nba/novig-alert-test — one message marked TEST (the page's button
// for it was taken off 11-19; the route is kept for a check by hand), with the numbers of the best row on the alert boards
// when there is one. GET /api/nba/novig-alerts — the settings in force (never the webhook).
app.get('/api/nba/novig-alerts', (req, res) => { if (nvBetsAuth(req, res)) res.json(NV_ALERTS.status()); });
app.post('/api/nba/novig-alert-test', async (req, res) => {
  if (!nvBetsAuth(req, res)) return;
  let best = null, board = null;
  for (const lg of NV_ALERTS.S.sports) {
    for (const r of ((NV_BOARDS.get(lg + ':0') || {}).rows || new Map()).values()) {
      if ((!r.starts || r.starts > Date.now()) && (!best || r.ev > best.ev)) { best = r; board = lg; }
    }
  }
  try {
    const g = best ? ((NV_GAMES.get(NV_PY_LEAGUE(board)) || {}).games || []).find(x => x.id === (best.event || best.id)) : null;
    res.json(await NV_ALERTS.test(board, best, g ? g.name : ''));
  } catch (e) { res.status(502).json({ error: e.message }); }
});

// Auto-scan: while switched on (the page's Auto-scan button), the server runs
// whole-board passes of NBA, NBA Team, NFL, CBB, CFB and soccer one after another, with or
// without the page open. Still one pass at a time: a pass asked for with
// Fetch runs first and the cycle carries on after it.
// It prices each board's next day of games only (Max, 11-16: today's games;
// 11-17: once today's are gone, the next ones, e.g. the NBA's tomorrow and
// the NFL's Thursday): the games starting before the midnight that follows
// the board's soonest open game, in the time zone of the page that switched
// it on (Eastern if the page sent none). Later games are priced with Fetch.
// Football runs through its main day (Max, 11-19: the NFL's full Sunday, not
// just the Thursday game, and CFB's Saturday): from the soonest open game to
// the end of that Sunday (NFL) or Saturday (CFB), when it is at most
// NV_CYCLE_REACH days on. A Monday night game is still priced alone.
// Soccer runs through the weekend the same way (Max, 11-19): to the end of
// Sunday, from Thursday on.
// Novig's CFB board is off (Max, 11-27: turn off CFB until I tell you, they aren't very good): out of Auto-scan
// and the All tab, and its tab is hidden on the page. To bring it back: 'cfb' after 'cbb' here, in NV_ALL_BOARDS
// below, and the CFB button's `hidden` in nba_scan.html. The Kalshi CFB board is not touched.
const NV_CYCLE_BOARDS = ['nba', 'nbateam', 'nfl', 'cbb', 'soccer'];   // NFL Ladder 11-18, out again 11-19 (Max: Fetch only, like NBA Ladder), to leave the time to the NFL's Sunday
const NV_CYCLE_THROUGH = { nfl: 0, cfb: 6, soccer: 0 };   // board -> the weekday its window runs through (0 = Sunday)
const NV_CYCLE_REACH_DAYS = { soccer: 3 }, NV_CYCLE_REACH = 4;   // soccer: a midweek match day is priced alone
// Boards priced in full only from the day before a game (Max, 11-20: Novig's
// NFL limits are too small earlier): a game starting after tomorrow's
// midnight gets its QB 2+ passing TDs + teammate TD slip and nothing else.
// Fetch still prices everything.
const NV_CYCLE_DAY_BEFORE = ['nfl'];
const NV_CYCLE_GAP_MS = 60 * 1000;             // pause between two passes
const NV_CYCLE_REST_MS = 10 * 60 * 1000;       // a board is not asked again sooner than this after its last pass began or ended
// It runs until it is switched off: no time limit and no hours it rests (Max, 11-14).
let NV_CYCLE_ASK = false;   // true while the tick is reading a board's games
let NV_CYCLE = null;   // { since, wide, tz, i } while on; i = the next board in NV_CYCLE_BOARDS
const NV_TZ = 'America/New_York';
const nvTz = tz => { try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); return String(tz); } catch (_) { return NV_TZ; } };
// The next midnight in that time zone, in ms (an hour out on the two nights the clocks change).
function nvDayEnd(tz, now) {
  const p = {};
  for (const x of new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', hour: 'numeric', minute: 'numeric', second: 'numeric' }).formatToParts(now)) p[x.type] = Number(x.value);
  return Math.floor(now / 1000) * 1000 + (86400 - (p.hour * 3600 + p.minute * 60 + p.second)) * 1000;
}
// Where a board's auto-scan pass ends: the midnight after its soonest game's
// day, or after its main day (NV_CYCLE_THROUGH) when that is near enough.
function nvCycleEnd(league, tz, t) {
  const end = nvDayEnd(tz, t), through = NV_CYCLE_THROUGH[league];
  if (through === undefined) return end;
  const day = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(new Intl.DateTimeFormat('en-US', { timeZone: tz, weekday: 'short' }).format(t));
  const on = (through - day + 7) % 7;
  return on <= (NV_CYCLE_REACH_DAYS[league] || NV_CYCLE_REACH) ? end + on * 86400000 : end;
}
// Kept on disk beside the boards, so a redeploy or restart doesn't switch
// auto-scan off (where that directory is a volume; elsewhere it is lost with
// the disk, as the boards are).
const NV_CYCLE_FILE = NV_SCAN_FILE ? path.join(path.dirname(NV_SCAN_FILE), 'novig_cycle.json') : null;
function nvSaveCycle() {
  if (NV_CYCLE_FILE) require('fs').writeFile(NV_CYCLE_FILE, JSON.stringify(NV_CYCLE), () => {});
}
try {
  const c = JSON.parse(require('fs').readFileSync(NV_CYCLE_FILE, 'utf8'));
  if (c && Number(c.since) > 0) {
    NV_CYCLE = { since: Number(c.since), wide: !!c.wide, tz: nvTz(c.tz || NV_TZ), i: 0 };
    console.log('Novig auto-scan: still on from before the restart');
  }
} catch (_) { /* it was off */ }
// The Auto-scan button is the only thing that starts passes by itself (Max,
// 11-20). The alert job used to keep its boards priced with Auto-scan off
// (11-19): the page showed boards scanning with the button off, and those
// passes asked Novig for the slips Max was about to build in the app. Alerts
// go out only while Auto-scan is on (nvAlert).
const nvCyc = () => NV_CYCLE;
function nvCycleTick(first) {
  const C = nvCyc();
  if (!C) return;
  const boards = NV_CYCLE_BOARDS;
  nvOutRefresh();   // the injury report, kept current while auto-scan runs
  const now = Date.now();
  if (NV_RUN || NV_CYCLE_ASK || (!first && now - NV_LAST_END < NV_CYCLE_GAP_MS)) return;
  for (let n = 0; n < boards.length; n++) {
    const at = (C.i + n) % boards.length, league = boards[at];
    const B = nvBoard(`${league}:${C.wide ? 1 : 0}`);
    if (now - Math.max(B.started, B.finished, B.stopped || 0, B.idle || 0) < NV_CYCLE_REST_MS) continue;
    C.i = (at + 1) % boards.length;
    NV_CYCLE_ASK = true;
    nvGames(NV_PY_LEAGUE(league), games => {
      NV_CYCLE_ASK = false;
      if (nvCyc() !== C || NV_RUN) return;
      // No open game at all: the board rests like one just priced. Novig not
      // read: today's games, as before.
      if (games && !games.length) { B.idle = Date.now(); return; }
      const first = games ? games.find(g => g.starts > Date.now()) || games[0] : null;
      startNovigScan(league, C.wide, [], true, nvCycleEnd(league, C.tz, Math.max(Date.now(), first ? first.starts : 0)),
        NV_CYCLE_DAY_BEFORE.includes(league) ? nvDayEnd(C.tz, Date.now()) + 86400000 : 0);
    });
    return;
  }
}
setInterval(nvCycleTick, 15000).unref();
// next: the board the cycle will price next and how long until then (ms; 0
// while a pass runs). Between rounds every board can be inside its ten
// minutes' rest, and the page said "next: NBA" with nothing to show it was waiting.
function nvCycleState() {
  if (!NV_CYCLE) return { on: false, boards: NV_CYCLE_BOARDS };
  const now = Date.now();
  let next = NV_CYCLE_BOARDS[NV_CYCLE.i], wait = Infinity;
  for (let n = 0; n < NV_CYCLE_BOARDS.length; n++) {
    const league = NV_CYCLE_BOARDS[(NV_CYCLE.i + n) % NV_CYCLE_BOARDS.length];
    const B = NV_BOARDS.get(`${league}:${NV_CYCLE.wide ? 1 : 0}`) || {};
    const due = Math.max(Math.max(B.started || 0, B.finished || 0, B.stopped || 0, B.idle || 0) + NV_CYCLE_REST_MS, NV_LAST_END + NV_CYCLE_GAP_MS) - now;
    if (due < wait - 1000) { wait = due; next = league; }
    if (due <= 0) break;   // the tick takes the first board that is due, in order
  }
  return { on: true, wide: NV_CYCLE.wide, tz: NV_CYCLE.tz, boards: NV_CYCLE_BOARDS, next, wait: NV_RUN ? 0 : Math.max(0, wait), since: NV_CYCLE.since };
}

// GET /api/nba/novig-scan?league=nba|ladder|nbateam|nfl|nflladder|nhl|nhllines|soccer|cfb|cbb[&wide=1][&now=1][&stop=1][&events=id,id] — that
// board's last pass (or the one running), and what else is running.
// ladder and nflladder: with the Kalshi passcode on the request (X-Kalshi-Key), a pass started here also asks Kalshi for each slip.
// stop=1 ends the pass that is running, whichever board it is on; with now=1
// this board's pass then starts in its place.
// Private: the scanner answers only to the passcode in NOVIG_SCAN_KEY (sent
// as X-Scan-Key; the page asks for it once and keeps it on that device).
// With no NOVIG_SCAN_KEY set, the scanner is off for everyone.
const NV_SCAN_KEY = (process.env.NOVIG_SCAN_KEY || '').trim();
// The Kalshi boards' own passcode: KALSHI_TAB_KEY on the server. It stands in front of the Bet
// button, so there is no built-in one (it was 'yyy' until 11-23, readable in this file): with
// none set, one under 8 characters, or the scanner's own, the Kalshi boards are off for everyone.
const NV_KALSHI_KEY = (process.env.KALSHI_TAB_KEY || '').trim();
const NV_KALSHI_ON = NV_KALSHI_KEY.length >= 8 && NV_KALSHI_KEY !== NV_SCAN_KEY;
if (!NV_KALSHI_ON) console.log('[kalshi] boards off: ' + (NV_KALSHI_KEY ? 'KALSHI_TAB_KEY must be 8 characters or more and not the scanner\'s passcode' : 'no KALSHI_TAB_KEY set'));
// Wrong passcodes are counted per caller address and per passcode: after 5 in 15 minutes that
// address is refused for 15 minutes, right passcode or not (429). A request with no passcode
// on it is not a guess. The 0.8 s wait on a wrong answer stays.
const NV_GUESS = new Map(), NV_GUESS_MAX = 5, NV_GUESS_MS = 15 * 60 * 1000;   // 'scan:ip' -> { n, since, until }
const nvSame = (a, b) => { const h = x => require('crypto').createHash('sha256').update(String(x)).digest(); return require('crypto').timingSafeEqual(h(a), h(b)); };
// { ok: true } or { ok: false, code, body, slow } for the scanner's passcode ('scan') or the Kalshi one ('kalshi').
function nvCheck(req, kind) {
  const want = kind === 'kalshi' ? NV_KALSHI_KEY : NV_SCAN_KEY, got = String(req.get(kind === 'kalshi' ? 'X-Kalshi-Key' : 'X-Scan-Key') || '');
  const no = kind === 'kalshi' ? { code: 423, body: { error: 'locked' } } : { code: 403, body: { error: 'wrong passcode' } };
  if (kind === 'kalshi' && !NV_KALSHI_ON) return { ok: false, code: 423, body: { error: 'the Kalshi boards are off on the server (no KALSHI_TAB_KEY set)', off: true } };
  const k = kind + ':' + (req.ip || ''), now = Date.now(), g = NV_GUESS.get(k);
  if (g && g.until > now) return { ok: false, code: 429, body: { error: 'too many wrong passcodes: try again in ' + Math.ceil((g.until - now) / 60000) + ' min', kind, wait: g.until - now } };
  if (!got) return Object.assign({ ok: false }, no);
  if (nvSame(got, want)) { NV_GUESS.delete(k); return { ok: true }; }
  const n = g && now - g.since < NV_GUESS_MS ? g : { n: 0, since: now, until: 0 };
  if (++n.n >= NV_GUESS_MAX) { n.until = now + NV_GUESS_MS; n.n = 0; n.since = now; console.log('[passcode] ' + kind + ': ' + NV_GUESS_MAX + ' wrong from ' + req.ip + ', refused for 15 min'); }
  if (NV_GUESS.size > 5000) for (const [x, v] of NV_GUESS) if (v.until < now && now - v.since > NV_GUESS_MS) NV_GUESS.delete(x);
  NV_GUESS.set(k, n);
  return Object.assign({ ok: false, slow: true }, no);
}
const nvDeny = (res, c) => { const go = () => res.status(c.code).json(c.body); if (c.slow) setTimeout(go, 800); else go(); return false; };
const nvKalshiAuth = (req, res) => { const c = nvCheck(req, 'kalshi'); return c.ok || nvDeny(res, c); };
app.get('/api/nba/novig-scan', (req, res) => {
  res.set('Cache-Control', 'no-store');
  if (!NV_SCAN_KEY) return res.status(503).json({ error: 'scanner off' });
  const sc = nvCheck(req, 'scan');
  if (!sc.ok) return nvDeny(res, sc);
  const wide = req.query.wide === '1';
  const league = NV_LEAGUES.includes(req.query.league) ? req.query.league : 'nba';
  const now = Date.now();
  // The Kalshi board asks with the owner's own Kalshi key, so it has a second
  // passcode (X-Kalshi-Key). Without it the board can't be read or started,
  // its rows stay off the All tab, and a pass on it shows as no board's.
  const kc = nvCheck(req, 'kalshi'), kalshiOk = kc.ok;
  if (nvKalshi(league) && !kalshiOk) return nvDeny(res, kc);
  // The Ladder boards are behind the Kalshi passcode too (Max, 11-27: make it hidden behind the Kalshi PW).
  if (NV_LADDERS.includes(league) && !kalshiOk) return nvDeny(res, kc);
  // A Kalshi board looks at the Kalshi slot, every other board at Novig's.
  // league=kalshinbaall or kalshinflall: the Kalshi NBA or NFL tab, its boards as one list with one Fetch.
  const group = Object.prototype.hasOwnProperty.call(NV_KGROUPS, req.query.league) ? NV_KGROUPS[req.query.league] : null;
  if (group && !kalshiOk) return nvDeny(res, kc);
  const RUN = group || (nvKalshi(league) && req.query.league !== 'all') ? NV_KRUN : NV_RUN;
  const busyName = () => (RUN ? RUN.key.split(':')[0] : null);
  // One pass at a time (Novig's limit is per IP), and only when asked.
  if (req.query.stop === '1' && RUN) RUN.stop();
  nvOutRefresh();
  // league=all[&min=EV%]: the page's All tab. Every board's rows at that EV
  // or better whose game hasn't started, each tagged with its board, and
  // where each board's last pass stands. Never starts a pass.
  if (req.query.league === 'all' || group) {
    // A Kalshi NBA or NFL tab does start passes: all its boards, queued. It waits for a pass on
    // another Kalshi board unless that one was stopped just above.
    // Every board in it is emptied at the press, not when its turn comes (Max, 11-27: old ones
    // don't go away when you hit Fetch): the list holds only what this Fetch has priced.
    if (group && req.query.now === '1' && !NV_KRUN) {
      for (const league of group) nvBoard(`${league}:${wide ? 1 : 0}`).rows.clear();
      nvSaveBoards();
      startKalshiGroup(req.query.league, wide);   // one pass over all of them, player by player (it was one board after another)
    }
    const floor = Number.isFinite(parseFloat(req.query.min)) ? parseFloat(req.query.min) / 100 : 0;
    const boards = [], rows = [];
    let out = 0;
    for (const league of group || NV_ALL_BOARDS) {
      if (nvKalshi(league) && !kalshiOk) continue;
      const k = `${league}:${wide ? 1 : 0}`, B = NV_BOARDS.get(k) || {};
      let priced = 0;
      for (const r of (B.rows ? B.rows.values() : [])) {
        if (r.starts && r.starts <= now) continue;
        if (nvLong(league, r)) continue;
        if (nvOut(league, r)) { out++; continue; }
        priced++;
        if (r.ev >= floor) rows.push(Object.assign({}, nvFlag(league, r), { board: league }));
      }
      const R = nvKalshi(league) ? NV_KRUN : NV_RUN;
      boards.push({ league, scanning: !!R && (R.key === k || (R.keys || []).includes(k)), started: B.started || 0, finished: B.finished || 0,
                    stopped: B.stopped || 0, total: B.total || 0, done: B.done || 0, error: B.error || null, priced,
                    queued: !!group && NV_KQUEUE.some(q => q.league === league && q.wide === wide) });
    }
    if (group) {
      const mine = boards.some(b => b.scanning || b.queued);
      return res.json({ now, league: req.query.league, wide, scanning: mine, busy: NV_KRUN && !mine ? NV_KRUN.key.split(':')[0] : null,
                        boards, rows, out, cycle: nvCycleState() });
    }
    return res.json({ now, league: 'all', wide, scanning: false, busy: busyName(),
                      boards, rows, out, cycle: nvCycleState() });
  }
  // events=id,id: only those games (the page's game picker).
  const events = String(req.query.events || '').split(',').filter(x => /^[0-9a-f-]{16,40}$/i.test(x)).slice(0, 40);
  const key = `${league}:${wide ? 1 : 0}`, B = nvBoard(key);
  const other = events.join() !== (B.events || []).join();   // other games than the last pass: no minute's wait
  const ladder = NV_LADDERS.includes(league);
  if (req.query.now === '1' && !RUN && (B.stopped || other || now - Math.max(B.finished, B.started) > NV_SCAN_NOW_MS)) startNovigScan(league, wide, events, false, 0, 0, ladder && kalshiOk);
  const mine = !!RUN && (RUN.key === key || (RUN.keys || []).includes(key));
  const shown = [...B.rows.values()].filter(r => !nvLong(league, r) && !nvOut(league, r)).map(r => nvFlag(league, r));
  res.json({
    now, league, wide, scanning: mine, busy: RUN && !mine ? busyName() : null,
    started: B.started, finished: B.finished, stopped: B.stopped || 0, total: B.total, done: B.done, players: B.players, data: B.data,
    seconds: B.seconds, error: B.error, books: B.books || null, events: B.events || [], before: B.before || 0, rows: shown,
    out: B.rows.size - shown.length, cycle: nvCycleState(), why: B.why || {},
    // A Ladder board: did its last pass ask Kalshi too, and why not if it could not.
    ...(ladder ? { kalshi: !!B.kalshi, knote: B.knote || null } : {}),
  });
});
// The boards the All tab gathers (the hidden NHL boards are left out; the Ladder boards have their own tab since 11-27).
const NV_ALL_BOARDS = ['nba', 'nbateam', 'nfl', 'soccer', 'cbb', 'kalshinba3', 'kalshinba', 'kalshinbatri', 'kalshinbaline', 'kalshinfl', 'kalshinflline', 'kalshinfltri', 'kalshicbb', 'kalshicfb'];   // DK NBA's tab was removed 11-18

// GET /n/<outcome id,outcome id,...> — a slip's link into Novig, for the
// scanner's rows (and for alerts sent off the page). Novig's own app routes
// /events/<outcome ids> to the board with those legs on the slip (read from
// its web bundle 11-16: path 'events/:orderslip_outcomes?/:partner_id?/:amount?',
// link prefixes novigapp:// and novig.onelink.me/JHQQ). A computer goes
// straight to novig.com. A phone gets a page with a button to the app, by
// Novig's universal-link address (novig.onelink.me/JHQQ/events/...: iOS opens
// the app on the tap without asking, Max 11-19), and one to novig.com. The
// page no longer opens novigapp:// by itself: that is what made Safari ask
// "Open this page in Novig?". Nothing here needs the
// passcode: the page only redirects, and takes nothing but outcome ids.
app.get('/n/:ids', (req, res) => {
  const ids = String(req.params.ids).split(',');
  if (ids.length > 8 || !ids.every(i => /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(i))) return res.status(404).send('not a slip');
  const tail = 'events/' + ids.join(','), web = 'https://novig.com/' + tail;
  res.set('Cache-Control', 'no-store');
  if (!/iphone|ipad|ipod|android/i.test(req.get('User-Agent') || '')) return res.redirect(302, web);
  res.type('html').send(`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Open in Novig</title>
<style>body{margin:0;background:#0b0d10;color:#e8eaed;font:16px -apple-system,system-ui,sans-serif;display:flex;flex-direction:column;gap:14px;align-items:center;justify-content:center;height:100vh}
a{display:block;width:240px;text-align:center;padding:14px 0;border-radius:10px;text-decoration:none;font-weight:600}
.a{background:#179be7;color:#fff}.w{border:1px solid #3a3f47;color:#e8eaed}</style>
<a class="a" href="https://novig.onelink.me/JHQQ/${tail}">Open in the Novig app</a><a class="w" href="${web}">Open on novig.com</a><a class="w" href="/">Back to the scanner</a>`);
});

// POST /api/nba/novig-cycle { on, wide, tz } — switch auto-scan on or off. On: the
// first board starts at once (if nothing is running). Off: a pass the cycle
// started is stopped too; one started with Fetch runs on.
app.post('/api/nba/novig-cycle', (req, res) => {
  if (!nvBetsAuth(req, res)) return;
  const { on, wide, tz } = req.body || {};
  if (on) {
    if (!NV_CYCLE || NV_CYCLE.wide !== !!wide) NV_CYCLE = { since: Date.now(), wide: !!wide, i: 0 };
    NV_CYCLE.tz = nvTz(tz || NV_TZ);
    nvSaveCycle();
    nvCycleTick(true);
  } else {
    NV_CYCLE = null;
    nvSaveCycle();
    if (NV_RUN && NV_RUN.auto) NV_RUN.stop();
  }
  res.json({ cycle: nvCycleState() });
});

// My bets on the scanner page are kept in each browser only (Max, 11-16:
// other people look at the scanner too). They used to be saved here and
// shown to every device with the passcode; that file is set aside at start.
// (renamed, not deleted, so the old list can be read back by hand if a device lost its copy)
if (NV_SCAN_FILE) require('fs').rename(path.join(path.dirname(NV_SCAN_FILE), 'novig_bets.json'), path.join(path.dirname(NV_SCAN_FILE), 'novig_bets.old.json'), () => {});
function nvBetsAuth(req, res) {
  res.set('Cache-Control', 'no-store');
  if (!NV_SCAN_KEY) { res.status(503).json({ error: 'scanner off' }); return false; }
  const c = nvCheck(req, 'scan');
  return c.ok || nvDeny(res, c);
}
// POST /api/nba/novig-requote { league, wide, key } — price one row of a
// board again (the refresh button on a row): scan.py --requote re-reads the
// legs' books and asks Novig for a new quote on that one slip. One at a time;
// it may run beside a pass (one more quote inside Novig's per-IP limit).
let NV_REQUOTE = false;
// cb(error text or null, the new row, http status for the error)
// kalshi: a Ladder row is also asked of Kalshi (the request carried the Kalshi passcode).
function nvRequote(league, wide, key, cb, kalshi) {
  const B = NV_BOARDS.get(`${league}:${wide ? 1 : 0}`), row = B && B.rows.get(String(key));
  if (!row) return cb('that slip is no longer on the board', null, 404);
  const onKalshi = nvKalshi(league);
  if (NV_OWN_SCRIPT[league] && !onKalshi) return cb('one slip can\'t be re-priced on this board: press Fetch', null, 400);
  if (NV_REQUOTE) return cb('another slip is being refreshed', null, 429);
  NV_REQUOTE = true;
  const lg = NV_PY_LEAGUE(league);
  const args = [onKalshi ? NV_KALSHI_PY : NV_SCAN_PY, '--requote', '--league', lg].concat(wide ? ['--max-spread', '0.08'] : [])
    .concat(kalshi && NV_LADDERS.includes(league) ? ['--kalshi'] : []);
  let out = '', err = '', done = false, timer = null;
  const finish = (why, r, code) => { if (done) return; done = true; NV_REQUOTE = false; clearTimeout(timer); cb(why, r, code); };
  let proc;
  try { proc = require('child_process').spawn(PYTHON, args, { stdio: ['pipe', 'pipe', 'pipe'] }); }
  catch (e) { return finish('could not start: ' + e.message, null, 502); }
  timer = setTimeout(() => { proc.kill(); finish((onKalshi ? 'Kalshi' : 'Novig') + ' did not answer', null, 504); }, 90 * 1000);
  proc.stdout.on('data', c => { out += c; });
  proc.stderr.on('data', c => { err = (err + c).slice(-2000); });
  proc.on('error', e => finish('could not start: ' + e.message, null, 502));
  proc.on('close', () => {
    let r = null;
    try { r = JSON.parse(out.trim().split('\n').pop()); } catch (_) { /* not JSON */ }
    if (!r || r.error || !r.key) return finish((r && r.error) || err.trim().split('\n').pop() || 'no answer', null, 502);
    r.type = 'row';
    if (B.rows.has(r.key)) { B.rows.set(r.key, r); B.seen.add(r.key); nvSaveBoards(); }
    nvAlert(league, wide, r);
    finish(null, r);
  });
  proc.stdin.on('error', () => {});
  proc.stdin.end(JSON.stringify(row));
}
// POST /api/nba/kalshi-bet { league, wide, key, stake, x } — the Bet button on
// a Kalshi row (and on a Ladder row that pays more on Kalshi, x being its kalshi_x): scan_kalshi.py --bet re-prices the legs, asks Kalshi for
// `stake` dollars and accepts the best answer if the slip still pays within
// 1% of x (the price on the row) and is not under today's fair value. Needs
// both passcodes. One bet at a time. There is no cap on a stake unless
// KALSHI_BET_MAX is set; it is $2 until one bet has been seen to land on the Yes side of
// the combo (the account's position is read after every bet); a bet seen on
// the No side turns the button off until the server is told otherwise.
// No cap on one bet (Max, 11-24: don't cap at $250): the page stakes a row's QK $. KALSHI_BET_MAX on the server, if set, is still a cap.
const NV_LBET_AGE_MS = 10 * 60 * 1000;   // a Ladder row older than this is not bet on Kalshi without a refresh
const NV_KBET_MAX = parseFloat(process.env.KALSHI_BET_MAX) >= 1 ? parseFloat(process.env.KALSHI_BET_MAX) : Infinity;
const NV_KBET_FILE = NV_SCAN_FILE ? path.join(path.dirname(NV_SCAN_FILE), 'kalshi_bet_state.json') : null;
// ok: the button's side was seen right on the real exchange 11-16 (a $2 bet, $1.88 in, on the Yes side),
// so no $2 test is asked for any more. The position is still read after every bet.
let NV_KBET = { ok: true, off: '' }, NV_KBET_BUSY = false;
try { if (NV_KBET_FILE) NV_KBET = Object.assign(NV_KBET, JSON.parse(require('fs').readFileSync(NV_KBET_FILE, 'utf8'))); } catch (_) { /* no bet placed yet */ }
const nvKbetSave = () => { if (NV_KBET_FILE) require('fs').writeFile(NV_KBET_FILE, JSON.stringify(NV_KBET), () => {}); };
app.post('/api/nba/kalshi-bet', (req, res) => {
  if (!nvBetsAuth(req, res)) return;
  const { league, wide, key } = req.body || {};
  let stake = Math.round(Number((req.body || {}).stake) * 100) / 100;
  const x = Number((req.body || {}).x);
  const ladder = NV_LADDERS.includes(league);
  if (!nvKalshi(league) && !ladder) return res.status(423).json({ error: 'locked' });
  if (!nvKalshiAuth(req, res)) return;
  if (NV_KBET.off) return res.status(409).json({ error: 'Betting is off: ' + NV_KBET.off });
  const B = NV_BOARDS.get(`${league}:${wide ? 1 : 0}`), row = B && B.rows.get(String(key));
  if (!row) return res.status(404).json({ error: 'that slip is no longer on the board' });
  // A Ladder row (Max, 11-27: the bet button for Kalshi if better on Kalshi): the same slip bought on
  // Kalshi, on the markets its last Kalshi look found (kalshi_legs). Its fair value is the Novig
  // scanner's, not re-read off Kalshi's books as a Kalshi row's is, so the row must be newly priced:
  // one more than NV_LBET_AGE_MS old is refused and wants its refresh first.
  let betRow = row;
  if (ladder) {
    const kl = row.kalshi_legs;
    if (!Array.isArray(kl) || kl.length !== (row.legs || []).length || !(row.kalshi_x > 1)) return res.status(409).json({ error: 'Kalshi has no price for this slip: press its refresh' });
    const age = Date.now() - Math.min(row.at || 0, row.kalshi_at || 0) * 1000;
    if (age > NV_LBET_AGE_MS) return res.status(409).json({ error: `this row was priced ${Math.round(age / 60000)} min ago: press its refresh, then bet` });
    betRow = { key: row.key, hold: true, player: row.player, label: row.label, j: row.j, r: row.r, devig_r: row.devig_r, starts: row.starts,
               legs: row.legs.map((L, i) => ({ id: kl[i].id, event: kl[i].event, yes: true, side: 'over', stat: L.stat, line: L.line, p: L.p, fair: L.fair, width: L.width || 0 })) };
  }
  if (!(stake >= 1) || !(x > 1)) return res.status(400).json({ error: 'a stake of $1 or more and the row\'s price are needed' });
  // Until one bet has been seen on the Yes side, a press stakes $2 whatever was asked for.
  const first = !NV_KBET.ok;
  if (first) stake = Math.min(stake, 2);
  if (stake > NV_KBET_MAX) return res.status(400).json({ error: `the most one bet can be is $${NV_KBET_MAX}` });
  if (NV_KBET_BUSY) return res.status(429).json({ error: 'another bet is being placed' });
  NV_KBET_BUSY = true;
  let out = '', err = '', done = false, timer = null, proc;
  const finish = (code, body) => { if (done) return; done = true; NV_KBET_BUSY = false; clearTimeout(timer); res.status(code).json(body); };
  try { proc = require('child_process').spawn(PYTHON, [NV_KALSHI_PY, '--bet', '--league', NV_PY_LEAGUE(league)], { stdio: ['pipe', 'pipe', 'pipe'] }); }
  catch (e) { return finish(502, { error: 'could not start: ' + e.message }); }
  timer = setTimeout(() => { proc.kill(); finish(504, { error: 'No answer in 60 seconds. The bet may or may not have gone in: look at your Kalshi positions before trying again.' }); }, 60 * 1000);
  proc.stdout.on('data', c => { out += c; });
  proc.stderr.on('data', c => { err = (err + c).slice(-2000); });
  proc.on('error', e => finish(502, { error: 'could not start: ' + e.message }));
  proc.on('close', () => {
    let r = null;
    try { r = JSON.parse(out.trim().split('\n').pop()); } catch (_) { /* not JSON */ }
    if (!r || r.error || !r.bet) return finish(502, { error: (r && r.error) || err.trim().split('\n').pop() || 'no answer' });
    if (r.bet.side === 'yes') NV_KBET.ok = true;
    else if (r.bet.side === 'no') NV_KBET.off = 'the last bet landed on the No side of the combo. Close that position on Kalshi; the button stays off until this is fixed in the code.';
    nvKbetSave();
    NV_KPOS.at = 0;   // the next read of positions is fresh
    console.log('[kalshi-bet]', JSON.stringify({ label: row.label, player: row.player, bet: r.bet, from: req.ip }));
    if (ladder) {
      // The Ladder row stays Novig's row: only Kalshi's price on it is new (what the bet was taken at).
      if (r.bet.x > 1 && row.fair_x > 1) {
        const p = 1 / row.fair_x, x = r.bet.x;
        Object.assign(row, { kalshi_x: x, kalshi_quote: r.bet.yes, kalshi_ev: x * p - 1, kalshi_qk: Math.max(0, (p * (x - 1) - (1 - p)) / (x - 1)) * 25, kalshi_at: Date.now() / 1000 });
        delete row.kalshi_why;
        nvSaveBoards();
      }
      return finish(200, { bet: r.bet, row, first, off: NV_KBET.off, now: Date.now() });
    }
    if (r.row && B.rows.has(r.row.key)) { r.row.type = 'row'; B.rows.set(r.row.key, r.row); nvSaveBoards(); }
    finish(200, { bet: r.bet, row: r.row, first, off: NV_KBET.off, now: Date.now() });
  });
  proc.stdin.on('error', () => {});
  proc.stdin.end(JSON.stringify({ row: betRow, stake, min_x: x * 0.99, min_ev: 0 }));
});
// GET /api/nba/kalshi-positions — the account's open combo positions on
// Kalshi (scan_kalshi.py --positions), for the Kalshi page's "On Kalshi"
// strip and row lines. Both passcodes. Read once a minute at most; a bet
// clears the copy so the next read is fresh.
let NV_KPOS = { at: 0, list: [], error: null, busy: null };
app.get('/api/nba/kalshi-positions', (req, res) => {
  if (!nvBetsAuth(req, res)) return;
  if (!nvKalshiAuth(req, res)) return;
  const send = () => res.json({ positions: NV_KPOS.list, error: NV_KPOS.error, at: NV_KPOS.at, now: Date.now() });
  if (Date.now() - NV_KPOS.at < 60 * 1000) return send();
  if (!NV_KPOS.busy) {
    NV_KPOS.busy = new Promise(done => {
      require('child_process').execFile(PYTHON, [NV_KALSHI_PY, '--positions'], { timeout: 45 * 1000, maxBuffer: 4 << 20 }, (e, out, err) => {
        let list = null;
        try { list = JSON.parse(String(out).trim().split('\n').pop()); } catch (_) { /* not JSON */ }
        if (Array.isArray(list)) NV_KPOS = { at: Date.now(), list, error: null, busy: null };
        else NV_KPOS = { at: Date.now(), list: NV_KPOS.list, error: String(err || (e && e.message) || 'no answer').trim().split('\n').pop().slice(0, 200), busy: null };
        done();
      });
    });
  }
  NV_KPOS.busy.then(send);
});
app.post('/api/nba/novig-requote', (req, res) => {
  if (!nvBetsAuth(req, res)) return;
  const { league, wide, key } = req.body || {};
  if (nvKalshi(league) && !nvKalshiAuth(req, res)) return;
  // A Ladder row is behind the Kalshi passcode, and its refresh asks Kalshi too.
  const kalshi = NV_LADDERS.includes(league);
  if (kalshi && !nvKalshiAuth(req, res)) return;
  nvRequote(league, wide, key, (why, row, code) => why ? res.status(code).json({ error: why }) : res.json({ row, now: Date.now() }), kalshi);
});



app.get('/healthz', (_req, res) => res.send('ok'));

app.listen(PORT, '0.0.0.0', () => console.log('Listening on 0.0.0.0:' + PORT));
