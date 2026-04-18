/* buildSGPInsightPrompt(sgp) — constructs the Claude prompt for an SGP insight.
   sgp shape:
     pitcher    string
     game       string
     legs       [{label, fv}]
     dkSGP      number  (American odds)
     fvCorr     number  (American odds, corr-adjusted FV)
     evPct      number  (e.g. 7.3)
     fvP        number  (0–1 decimal probability)
     correlation { pairs:[{a,b,r,rMargin,rMarginSource,source,...}], missingPairs, usedPairs, starts }
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
      var rStr = (p.r !== null && p.r !== undefined) ? p.r.toFixed(4) : 'missing (treated as 0)';
      var hasMargin = (p.rMargin !== null && p.rMargin !== undefined && !isNaN(p.rMargin));
      var mStr = hasMargin ? p.rMargin.toFixed(4) : 'n/a';
      lines.push('  ' + p.a + '  \u2194  ' + p.b + ':  binary r = ' + rStr + ',  margin r = ' + mStr);
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
  lines.push('For each leg pair, you have two correlation measures:');
  lines.push('  - R (binary phi): how often the two leg outcomes co-occur at their specific thresholds (the actual parlay lines).');
  lines.push('  - Margin (continuous): how the underlying raw stats move together, independent of the chosen thresholds.');
  lines.push('Interpret divergence between them:');
  lines.push('  - Same sign, similar magnitude: stable relationship, high confidence in the correlation signal.');
  lines.push('  - Same sign, margin much stronger than binary: the raw-stat relationship is real but the specific line thresholds don\u2019t capture it well \u2014 edge may be weaker than binary suggests.');
  lines.push('  - Opposite signs: the line thresholds are carving the data differently than the underlying relationship \u2014 the parlay at these specific lines fights the pitcher\u2019s actual tendencies (usually a weak or negative edge).');
  lines.push('  - Both near zero: outcomes are effectively independent; any EV is coming from leg pricing errors, not correlation arbitrage.');
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
  lines.push('Evaluate this SGP using EV%, the correlation between legs (both binary r and margin r), sample size, and historical hit rates.');
  lines.push('A positive correlation means the legs tend to hit together \u2014 this boosts real fair value above the independent product.');
  lines.push('Missing correlations or small samples increase uncertainty.');
  lines.push('Compare binary r vs margin r for each pair and work the interpretation into the commentary:');
  lines.push('  - When binary and margin agree directionally (same sign, similar magnitude), say so briefly \u2014 it reinforces confidence in the edge.');
  lines.push('  - When they disagree (opposite signs, or same sign with very different magnitudes), flag it and explain what the disagreement suggests about this specific pitcher + these specific line thresholds.');
  lines.push('  - Do not simply restate both numbers. Interpret the relationship for the specific pitcher and combo (e.g. an all-or-nothing pitcher whose raw stats trend together but whose line thresholds carve the outcomes oppositely).');
  lines.push('Keep the correlation discussion concise \u2014 one paragraph mentioning the r/margin behavior is enough; do not turn every insight into a statistics lecture.');
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
