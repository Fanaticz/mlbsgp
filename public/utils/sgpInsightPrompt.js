/* buildSGPInsightPrompt(sgp) — constructs the Claude prompt for an SGP insight.
   sgp shape:
     size       2 | 3  (defaults to legs.length when absent — 2-leg back-compat)
     pitcher    string
     game       string
     legs       [{label, fv}]
     dkSGP      number  (American odds)
     fvCorr     number  (American odds, corr-adjusted FV)
     evPct      number  (e.g. 7.3)
     fvP        number  (0–1 decimal probability)
     correlation {
       pairs:[{a,b,r,rMargin,rMarginSource,source,...}],
       missingPairs, usedPairs, starts,
       // 3-leg only:
       empirical3Way: { hitRatePlayer, hitRateGlobal, hitRateBlended, wPlayer, wGlobal, nEff, nRaw }
     }
     hitRates   { leg1, leg2, both, givenLeg1toLeg2 } | null      // 2-leg shape
     hitRates3  { leg1, leg2, leg3, all3, all3Blended } | null    // 3-leg shape
     dkHoldPct  number | null                                       // 3-leg only
*/
function buildSGPInsightPrompt(sgp) {
  var size = sgp.size || (sgp.legs && sgp.legs.length) || 2;
  if (size === 3) return _buildSGP3InsightPrompt(sgp);
  return _buildSGP2InsightPrompt(sgp);
}

function _buildSGP2InsightPrompt(sgp) {
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

/* 3-leg variant. The primary model probability is the EMPIRICAL 3-way joint
   hit rate from the aggregates (blended with the global 3-way baseline under
   shrinkage), not a pairwise-derived estimate — it captures higher-order
   structure that the pairwise correction misses. The prompt tells the model
   to treat the empirical 3-way rate as the ground truth for model joint. */
function _buildSGP3InsightPrompt(sgp) {
  var lines = [];
  var am = function(v){ return (v >= 0 ? '+' : '') + v; };

  lines.push('You are a sharp sports betting analyst specializing in MLB pitcher prop 3-leg SGPs.');
  lines.push('Analyze the following Same Game Parlay and respond ONLY with valid JSON — no markdown, no backticks, no prose before or after the JSON.');
  lines.push('');
  lines.push('=== SGP DATA (3-LEG) ===');
  lines.push('Pitcher: ' + sgp.pitcher);
  lines.push('Game: ' + sgp.game);
  lines.push('');
  lines.push('Legs:');
  sgp.legs.forEach(function(leg, i) {
    lines.push('  Leg ' + (i + 1) + ': ' + leg.label + '  (FV odds: ' + am(leg.fv) + ')');
  });
  lines.push('');
  lines.push('=== PRICING ===');
  lines.push('DK SGP price: ' + am(sgp.dkSGP));
  lines.push('Fair Value (FV-correlated joint, pairwise Fréchet): ' + am(sgp.fvCorr));
  lines.push('Primary EV% (vs FV): ' + sgp.evPct.toFixed(1) + '%   — this is the decision number; computed from user-supplied FV × DK decimal');
  if (sgp.evPctModel !== null && sgp.evPctModel !== undefined) {
    lines.push('Secondary EV% (vs aggregates model): ' + sgp.evPctModel.toFixed(1) + '%   — computed from the blended empirical 3-way joint × DK decimal');
  }
  lines.push('FV-correlated joint probability (pairwise Fréchet on FV marginals): ' + (sgp.fvP * 100).toFixed(1) + '%');
  if (sgp.pModel !== null && sgp.pModel !== undefined) {
    lines.push('Aggregates blended 3-way joint (what MODEL JOINT on the card shows): ' + (sgp.pModel * 100).toFixed(1) + '%');
  }
  if (sgp.dkHoldPct !== null && sgp.dkHoldPct !== undefined) {
    lines.push('DK correlation premium vs independent-product: ' + sgp.dkHoldPct.toFixed(1) + '%' +
               '   (positive means DK prices the SGP SHORTER than the product of its own vigged per-leg prices — i.e. DK models the legs as positively correlated)');
  }
  lines.push('');

  lines.push('=== PAIRWISE CORRELATIONS ===');
  var corr = sgp.correlation || {};
  if (corr.pairs && corr.pairs.length) {
    corr.pairs.forEach(function(p) {
      var rStr = (p.r !== null && p.r !== undefined) ? p.r.toFixed(4) : 'missing (treated as 0)';
      lines.push('  ' + p.a + '  \u2194  ' + p.b + ':  binary r = ' + rStr);
    });
  } else {
    lines.push('  No pair correlations available');
  }
  if (corr.missingPairs) {
    lines.push('  Missing pairs (r=0 fallback): ' + corr.missingPairs);
  }
  lines.push('');

  lines.push('=== EMPIRICAL 3-WAY JOINT ===');
  var e3 = corr.empirical3Way || {};
  if (e3.hitRatePlayer !== null && e3.hitRatePlayer !== undefined) {
    lines.push('  Player empirical all-3-hit rate: ' + e3.hitRatePlayer.toFixed(1) + '%');
  }
  if (e3.hitRateGlobal !== null && e3.hitRateGlobal !== undefined) {
    lines.push('  Global (league) empirical all-3-hit rate: ' + e3.hitRateGlobal.toFixed(1) + '%');
  }
  if (e3.hitRateBlended !== null && e3.hitRateBlended !== undefined) {
    lines.push('  Blended (shrunk) 3-way joint used in EV: ' + e3.hitRateBlended.toFixed(1) + '%');
  }
  if (e3.nEff !== null && e3.nEff !== undefined) {
    lines.push('  Shrinkage: ' + Math.round((e3.wPlayer || 0) * 100) + '% player / ' +
               Math.round((e3.wGlobal || 0) * 100) + '% global,  n_eff=' + e3.nEff.toFixed(1) +
               (e3.nRaw != null ? '  (raw starts=' + e3.nRaw + ')' : ''));
  }
  if (sgp.hitRates3) {
    var h3 = sgp.hitRates3;
    if (h3.leg1 != null) lines.push('  Leg 1 marginal hit: ' + h3.leg1.toFixed(1) + '%');
    if (h3.leg2 != null) lines.push('  Leg 2 marginal hit: ' + h3.leg2.toFixed(1) + '%');
    if (h3.leg3 != null) lines.push('  Leg 3 marginal hit: ' + h3.leg3.toFixed(1) + '%');
  }
  lines.push('');

  lines.push('=== INSTRUCTIONS ===');
  lines.push('Primary EV% for the play decision is the FV-based number. The user supplied FV because they believe their fair-value sheet is sharper than pure aggregate history; a model-based EV that disagrees with FV-based EV is a useful divergence signal, not a substitute.');
  lines.push('The aggregates-based EV (secondary) is the "what the history-only model would think if FV were absent" view. When the two EVs disagree materially (> 15pp), call that out — it indicates FV and aggregates see this combo differently, and the user should weigh whether their FV already priced in what the aggregates are seeing.');
  lines.push('Key risks specific to 3-leg:');
  lines.push('  - Pitcher-quality confounding: an ace has a high all-3-hit rate because the pitcher is good, not necessarily because of intrinsic correlation between the specific thresholds. DK\'s per-leg prices already reflect pitcher quality, so part of the apparent edge may be double-counted. Heavier shrinkage toward global mitigates but does not eliminate this.');
  lines.push('  - Empirical 3-way rates from 15-40 effective starts have high variance. A 10pp edge on n_eff=20 is noisy; the same edge on n_eff=40 is meaningful.');
  lines.push('  - If DK\'s correlation premium is already large (dkHoldPct > 10%), DK agrees the legs are positively correlated and is pricing accordingly — the model needs a markedly different joint to create a real edge.');
  lines.push('Evaluate EV%, pairwise r structure, sample size (n_eff matters more than raw starts), and DK\'s own correlation premium.');
  lines.push('');
  lines.push('Respond with ONLY this JSON (no markdown, no backticks):');
  lines.push('{"verdict":"PLAY","headline":"Short takeaway","explanation":"2-3 sentences.","edge":"1 sentence on what gives this value.","risk":"1 sentence on the main risk.","confidence":8}');
  lines.push('');
  lines.push('Rules:');
  lines.push('- verdict reads from the PRIMARY (FV-based) EV%: "PLAY" (primary EV% > 10 AND n_eff >= 20 AND model EV agrees at least in sign), "MARGINAL" (thin primary EV, borderline sample, or the two EVs disagree materially), "SKIP" (primary EV% is negative or the edge is plausibly pitcher-quality-confounding)');
  lines.push('- headline: max 12 words');
  lines.push('- explanation: 2-3 sentences — cover EV, empirical vs DK implied, sample size, and any red flag');
  lines.push('- edge: 1 sentence — what specifically makes this worth playing (or not)');
  lines.push('- risk: 1 sentence — biggest concern; mention pitcher-quality confounding when n_eff < 25 or edge > 15pp');
  lines.push('- confidence: integer 1-10; cap at 6 when n_eff < 20 and at 8 when any pair has missing r');

  return lines.join('\n');
}
