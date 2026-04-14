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

    const prompt = `You are extracting MLB pitcher prop bets from a screenshot. Return ONLY valid JSON, no prose.

For each row, extract: the pitcher name, the bet (Over/Under + line + stat), and the avg_fv value (American odds number, may be positive or negative, integer).

Normalize the bet to EXACTLY one of these canonical leg strings (match stat type):
- Strikeouts: "Over 4.5 Strikeouts", "Over 5.5 Strikeouts", "Over 6.5 Strikeouts", "Over 7.5 Strikeouts", "Under 4.5 Strikeouts", "Under 5.5 Strikeouts", "Under 6.5 Strikeouts", "Under 7.5 Strikeouts"
- Earned Runs: "Under 1.5 Earned Runs", "Under 2.5 Earned Runs", "Under 3.5 Earned Runs", "Over 1.5 Earned Runs", "Over 2.5 Earned Runs", "Over 3.5 Earned Runs"
- Walks: "Under 1.5 Walks", "Under 2.5 Walks", "Under 3.5 Walks"
- Hits Allowed: "Under 3.5 Hits Allowed", "Under 4.5 Hits Allowed", "Under 5.5 Hits Allowed", "Over 3.5 Hits Allowed", "Over 4.5 Hits Allowed", "Over 5.5 Hits Allowed"
- Outs Recorded (includes Pitching Outs): "Over 14.5 Outs Recorded", "Over 15.5 Outs Recorded", "Over 16.5 Outs Recorded", "Over 17.5 Outs Recorded", "Over 18.5 Outs Recorded", "Under 14.5 Outs Recorded", "Under 15.5 Outs Recorded", "Under 16.5 Outs Recorded", "Under 17.5 Outs Recorded", "Under 18.5 Outs Recorded"

The column "avg_fv" is the target number. It may show "+109" or "-145". Return as signed integer (109 or -145).

Return format:
{"rows":[{"pitcher":"Cole Ragans","leg":"Under 3.5 Hits Allowed","avg_fv":109}, ...]}`;

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
