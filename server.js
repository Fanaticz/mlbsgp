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

    const prompt = `You are extracting MLB pitcher prop bets from a screenshot of a spreadsheet. Return ONLY valid JSON, no prose.

The table has these columns in this order:
league | date | time | game | market | bet_name | book | L | M | odds | limit | books_count | avg_odds | avg_fv | avg_hold | fbc | ev | qk

CRITICAL: You must extract the value from the "avg_fv" column ONLY.

Column distinctions (do NOT confuse these):
- "odds" column contains TWO numbers separated by " / " (e.g. "-120 / -111") — this is the book's over/under price pair. IGNORE.
- "avg_odds" column contains TWO numbers separated by " / " (e.g. "-128 / -105") — this is the market consensus over/under price pair. IGNORE.
- "avg_fv" column contains ONE SINGLE signed integer (e.g. "-110" or "+152" or "+109"). THIS is the number you extract.

For each row, extract:
- pitcher: the pitcher's name from bet_name (e.g. "Cole Ragans" from "Cole Ragans Over 6.5")
- leg: the bet direction + line + market, normalized (see list below)
- avg_fv: the ONE signed integer from the avg_fv column

Normalize the leg to EXACTLY one of these canonical strings (preserve Over/Under exactly as shown in bet_name):
- Strikeouts: "Over 4.5 Strikeouts", "Over 5.5 Strikeouts", "Over 6.5 Strikeouts", "Over 7.5 Strikeouts", "Under 4.5 Strikeouts", "Under 5.5 Strikeouts", "Under 6.5 Strikeouts", "Under 7.5 Strikeouts"
- Earned Runs: "Under 1.5 Earned Runs", "Under 2.5 Earned Runs", "Under 3.5 Earned Runs", "Over 1.5 Earned Runs", "Over 2.5 Earned Runs", "Over 3.5 Earned Runs"
- Walks: "Under 1.5 Walks", "Under 2.5 Walks", "Under 3.5 Walks"
- Hits Allowed: "Under 3.5 Hits Allowed", "Under 4.5 Hits Allowed", "Under 5.5 Hits Allowed", "Over 3.5 Hits Allowed", "Over 4.5 Hits Allowed", "Over 5.5 Hits Allowed"
- Outs Recorded (market may say "Player Pitching Outs"): "Over 14.5 Outs Recorded", "Over 15.5 Outs Recorded", "Over 16.5 Outs Recorded", "Over 17.5 Outs Recorded", "Over 18.5 Outs Recorded", "Under 14.5 Outs Recorded", "Under 15.5 Outs Recorded", "Under 16.5 Outs Recorded", "Under 17.5 Outs Recorded", "Under 18.5 Outs Recorded"

Example: if bet_name is "Cole Ragans Over 15.5" and the market is "Player Pitching Outs" and the avg_fv column shows "+152", return {"pitcher":"Cole Ragans","leg":"Over 15.5 Outs Recorded","avg_fv":152}. Do NOT return -176 or any number from the odds/avg_odds pair columns.

Return this exact format:
{"rows":[{"pitcher":"Cole Ragans","leg":"Over 15.5 Outs Recorded","avg_fv":152}, ...]}`;

    const body = {
      model: 'claude-sonnet-4-5-20250929',
      max_tokens: 2000,
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
