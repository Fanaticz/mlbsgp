/* buildSGPInsightPrompt(sgp) — constructs the Claude prompt for an SGP insight.
   sgp shape:
     pitcher    string
     game       string
     legs       [{label, fv}]
     dkSGP      number  (American odds)
     fvCorr     number  (American odds, corr-adjusted FV)
     evPct      number  (e.g. 7.3)
     fvP        number  (0–1 decimal probability)
     correlation { pairs:[{a,b,r}], missingPairs, usedPairs, starts }
     hitRates   { leg1, leg2, both, givenLeg1toLeg2 } | null
*/
function buildSGPInsightPrompt(sgp) {
  var lines = [];

  lines.push('You are a sharp sports betting analyst specializing in MLB pitcher prop SGPs.');
  lines.push('Analyze the following Same Game Parlay and respond ONLY with valid JSON — no markdown, no backticks, no prose before or after the JSON.');
  lines.push('');
  lines.push('=== SGP DATA ===');
  lines.push('Pitcher: ' + sgp.pitcher);
  lines.push('Game: ' + sgp.game);
  lines.push('');
  lines.push('Legs:');
  sgp.legs.forEach(function(leg, i) {
    lines.push('  Leg ' + (i + 1) + ': ' + leg.label + '  (FV odds: ' + (leg.fv > 0 ? '+' : '') + leg.fv + ')');
  });
  lines.push('');
  lines.push('=== PRICING ===');
  lines.push('DK SGP price: ' + (sgp.dkSGP > 0 ? '+' : '') + sgp.dkSGP);
  lines.push('Fair Value (correlation-adjusted): ' + (sgp.fvCorr > 0 ? '+' : '') + sgp.fvCorr);
  lines.push('EV%: ' + sgp.evPct.toFixed(1) + '%');
  lines.push('Fair Value probability: ' + (sgp.fvP * 100).toFixed(1) + '%');
  lines.push('');

  lines.push('=== CORRELATION ===');
  var corr = sgp.correlation || {};
  if (corr.pairs && corr.pairs.length) {
    corr.pairs.forEach(function(p) {
      if (p.r !== null && p.r !== undefined) {
        lines.push('  ' + p.a + '  ↔  ' + p.b + ':  r = ' + p.r.toFixed(4));
      } else {
        lines.push('  ' + p.a + '  ↔  ' + p.b + ':  r = missing (treated as 0)');
      }
    });
  } else {
    lines.push('  No pair correlations available');
  }
  if (corr.missingPairs) {
    lines.push('  Missing pairs (r=0 fallback): ' + corr.missingPairs);
  }
  if (corr.starts !== null && corr.starts !== undefined) {
    lines.push('  Sample size: ' + corr.starts + ' pitcher starts');
  }
  lines.push('');

  lines.push('=== HISTORICAL HIT RATES ===');
  var hr = sgp.hitRates;
  if (hr) {
    if (hr.leg1 !== null && hr.leg1 !== undefined) lines.push('  Leg 1 hit rate: ' + hr.leg1.toFixed(1) + '%');
    if (hr.leg2 !== null && hr.leg2 !== undefined) lines.push('  Leg 2 hit rate: ' + hr.leg2.toFixed(1) + '%');
    if (hr.both !== null && hr.both !== undefined) lines.push('  Both legs hit rate: ' + hr.both.toFixed(1) + '%');
    if (hr.givenLeg1toLeg2 !== null && hr.givenLeg1toLeg2 !== undefined) {
      lines.push('  P(Leg 2 hits | Leg 1 hits): ' + hr.givenLeg1toLeg2.toFixed(1) + '%');
    }
  } else {
    lines.push('  No historical hit rate data available');
  }
  lines.push('');

  lines.push('=== INSTRUCTIONS ===');
  lines.push('Evaluate this SGP using EV%, the correlation between legs, sample size, and historical hit rates.');
  lines.push('A positive correlation means the legs tend to hit together — this boosts real fair value above the independent product.');
  lines.push('Missing correlations or small samples increase uncertainty.');
  lines.push('');
  lines.push('Respond with ONLY this JSON (no markdown, no backticks):');
  lines.push('{"verdict":"PLAY","headline":"Short takeaway here","explanation":"2-3 sentences.","edge":"1 sentence on what gives this value.","risk":"1 sentence on the main risk.","confidence":8}');
  lines.push('');
  lines.push('Rules:');
  lines.push('- verdict: "PLAY" (EV% > 5 and correlation is supportive), "MARGINAL" (EV is thin, data is weak, or uncertainty is high), "SKIP" (negative EV or correlation undermines the parlay)');
  lines.push('- headline: max 12 words, punchy, captures the key signal');
  lines.push('- explanation: 2-3 sentences covering EV, correlation strength, and hit rate context');
  lines.push('- edge: 1 sentence — what specifically makes this worth playing (or not)');
  lines.push('- risk: 1 sentence — biggest concern or caveat');
  lines.push('- confidence: integer 1-10 based on data quality, sample size, and conviction in the verdict');

  return lines.join('\n');
}
