// Minimal Express server: serves /public and proxies image OCR to Anthropic.
// Keeps your API key server-side. Set ANTHROPIC_API_KEY in Railway's env vars.

const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json({ limit: '25mb' }));
app.use(express.static(path.join(__dirname, 'public'), { maxAge: '1h' }));

app.post('/api/extract', async (req, res) => {
  try {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) return res.status(500).json({ error: 'ANTHROPIC_API_KEY not set on server' });

    const { image, mime } = req.body || {};
    if (!image) return res.status(400).json({ error: 'Missing image (base64) in body' });

    const prompt = `You are extracting MLB pitcher prop bets from a screenshot of a spreadsheet. Return ONLY valid JSON, no prose, no markdown fences.

The table header row contains these 18 columns in this left-to-right order:
1=league  2=date  3=time  4=game  5=market  6=bet_name  7=book  8=L  9=M  10=odds  11=limit  12=books_count  13=avg_odds  14=avg_fv  15=avg_hold  16=fbc  17=ev  18=qk

YOUR TASK: For each data row, return ONE JSON object with the pitcher, the normalized leg, and the value from column 14 (avg_fv) ONLY.

═══ CRITICAL COLUMN DISAMBIGUATION ═══
Three adjacent columns contain American odds. You MUST distinguish them:

Column 10 "odds": a PAIR like "+109 / -145" or "-120 / -111" — IGNORE THIS COLUMN
Column 13 "avg_odds": a PAIR like "-103 / -132" or "+128 / -183" — IGNORE THIS COLUMN
Column 14 "avg_fv": a SINGLE signed integer like "+114" or "-110" or "+158" — EXTRACT THIS VALUE

The first two columns have a "/" character. The avg_fv column has NO slash. If you see a value containing "/", you are reading the wrong column.

The avg_hold column (15) is a percentage like "7.0%" or "6.5%" — it is immediately to the right of avg_fv. Use that as a positional anchor: the signed integer IMMEDIATELY LEFT of the percentage column IS avg_fv.

═══ ROW-BY-ROW REASONING ═══
For each row, before emitting JSON, mentally verify:
- Does the value I'm about to return have a "/" in it? If yes, STOP — I'm reading a pair column. Move one column right.
- Does the value I'm about to return have a "%" in it? If yes, STOP — that's avg_hold. Move one column left.
- The correct avg_fv should be a single signed integer with no slash, no percent.

═══ EXTRACTION FIELDS ═══
- pitcher: the player name from bet_name column (e.g., "Cole Ragans" from "Cole Ragans Over 6.5")
- leg: normalized to canonical string (see list below) — the Over/Under comes ONLY from the bet_name column (column 6), never from the market column. The market column (column 5) always says things like "Player Pitching Strikeouts" with no direction — ignore it for direction. Read "Over" or "Under" verbatim from the bet_name text.
- avg_fv: the signed integer from column 14

═══ OVER vs UNDER — CRITICAL ═══
Each pitcher will often have BOTH an Over row and an Under row for the same line (e.g., "Jesus Luzardo Over 2.5" and "Jesus Luzardo Under 2.5"). These are TWO different bets. Read the word "Over" or "Under" directly from the bet_name column for each row independently. Never infer direction from the avg_fv sign or from a neighbouring row.

═══ CANONICAL LEG STRINGS ═══
- Strikeouts: "Over 4.5 Strikeouts", "Over 5.5 Strikeouts", "Over 6.5 Strikeouts", "Over 7.5 Strikeouts", "Under 4.5 Strikeouts", "Under 5.5 Strikeouts", "Under 6.5 Strikeouts", "Under 7.5 Strikeouts"
- Earned Runs: "Over 1.5 Earned Runs", "Over 2.5 Earned Runs", "Over 3.5 Earned Runs", "Under 1.5 Earned Runs", "Under 2.5 Earned Runs", "Under 3.5 Earned Runs"
- Walks: "Over 1.5 Walks", "Over 2.5 Walks", "Over 3.5 Walks", "Under 1.5 Walks", "Under 2.5 Walks", "Under 3.5 Walks"
- Hits Allowed: "Over 3.5 Hits Allowed", "Over 4.5 Hits Allowed", "Over 5.5 Hits Allowed", "Under 3.5 Hits Allowed", "Under 4.5 Hits Allowed", "Under 5.5 Hits Allowed"
- Outs Recorded (market may read "Player Pitching Outs"): "Over 14.5 Outs Recorded", "Over 15.5 Outs Recorded", "Over 16.5 Outs Recorded", "Over 17.5 Outs Recorded", "Over 18.5 Outs Recorded", "Under 14.5 Outs Recorded", "Under 15.5 Outs Recorded", "Under 16.5 Outs Recorded", "Under 17.5 Outs Recorded", "Under 18.5 Outs Recorded"

═══ WORKED EXAMPLES (WRONG vs RIGHT) ═══
Row: market="Player Pitching Outs", bet_name="Yoshinobu Yamamoto Over 18.5", odds="+136 / -182", avg_odds="+132 / -183", avg_fv="+158", avg_hold="7.2%"
  WRONG: avg_fv=-182  (that came from odds column)
  WRONG: avg_fv=-183  (that came from avg_odds column)
  WRONG: avg_fv=-127  (that belongs to a different row entirely)
  RIGHT: {"pitcher":"Yoshinobu Yamamoto","leg":"Over 18.5 Outs Recorded","avg_fv":158}

Row: market="Player Pitching Strikeouts", bet_name="Yoshinobu Yamamoto Over 6.5", odds="-108 / -118", avg_odds="-112 / -116", avg_fv="-102", avg_hold="6.8%"
  WRONG: avg_fv=-118  (odds column pair, second value)
  WRONG: avg_fv=-116  (avg_odds column pair, second value)
  RIGHT: {"pitcher":"Yoshinobu Yamamoto","leg":"Over 6.5 Strikeouts","avg_fv":-102}

═══ OUTPUT ═══
Return exactly this JSON shape, nothing else:
{"rows":[{"pitcher":"...","leg":"...","avg_fv":123}, ...]}`;

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
      return res.json(parsed);
    } catch (e) {
      return res.status(500).json({ error: 'JSON parse error: ' + e.message, raw: m[0] });
    }
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
});

app.get('/healthz', (_req, res) => res.send('ok'));

app.listen(PORT, '0.0.0.0', () => console.log('Listening on 0.0.0.0:' + PORT));
