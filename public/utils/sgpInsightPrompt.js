/* buildSGPInsightPrompt(sgp) — constructs the Claude prompt for an SGP
   insight card. Two variants: 2-leg (the common case; fed a fully
   structured numeric context object so the model never re-derives values)
   and 3-leg (empirical 3-way joint path).

   Rule-of-thumb for edits:
     1) Every number on the card must be in the structured context.
        If the model needs a value that isn't in the context, the context
        is incomplete — add it; do NOT let the model guess.
     2) One thesis per card. Title, body, Edge, and Risk must all stay
        consistent with a single thesis sentence.
     3) Math comparisons must be correct. To argue correlation exists,
        compare P(B|A) vs P(B), NOT P(B|A) vs P(A)*P(B).
     4) Risks must reference a specific number from the context.
     5) Confidence is justified by a specific data point, not handed out.

   sgp shape (2-leg):
     size         2
     pitcher      string
     game         string                       "Mets @ Dodgers" etc.
     inDB         bool
     legs         [{label, fv, fvProb}]
     dkSGP        number   American odds (e.g. +320)
     dkDecimal    number   decimal odds
     fvCorr       number   American odds, corr-adjusted FV
     fvIndep      number   American odds at independence
     evPct        number   % (e.g. 19.6)
     kellyPct     number
     qkUnits      number
     fvP          number   0–1 correlation-adjusted joint
     pIndep       number   0–1 independence product of FV legs
     correlation  { pairs[], missingPairs, usedPairs, starts, nEff, nRaw }
     hitRates     { leg1, leg2, both, givenLeg1toLeg2 } | null   (%)
     hits         { leg1Count, leg2Count, bothCount, n,
                    leg1Pct, leg2Pct, bothPct, givenLeg1toLeg2Pct }
     probs        { pA_fv, pB_fv, pA_emp, pB_emp, pA_times_pB_emp,
                    pAB_emp, pBgivenA_emp }
     rOurs        number   pair binary phi (shrunk)
     rMargin      number   pair margin r (shrunk)
     rSource      string   resolved source (blended, global, player, …)
     rPlayer      number | null
     rGlobal      number | null
     wPlayer      number | null
     wGlobal      number | null
     rDK          number | null   inverted from DK SGP price + FV legs
     rGap         number | null   rOurs - rDK
     rDKClamp     string | null   'ceiling' | 'floor' | 'degenerate' | null
     evFromLegsPct number | null  attribution split
     evFromCorrPct number | null  attribution split
*/
function buildSGPInsightPrompt(sgp) {
  var size = sgp.size || (sgp.legs && sgp.legs.length) || 2;
  if (size === 3) return _buildSGP3InsightPrompt(sgp);
  return _buildSGP2InsightPrompt(sgp);
}

function _fmtAm(v) {
  if (v === null || v === undefined || isNaN(v)) return 'n/a';
  return (v >= 0 ? '+' : '') + v;
}
function _fmtPct(v, digits) {
  if (v === null || v === undefined || isNaN(v)) return 'n/a';
  return v.toFixed(digits == null ? 1 : digits) + '%';
}
function _fmtR(v, digits) {
  if (v === null || v === undefined || isNaN(v)) return 'n/a';
  return (v >= 0 ? '+' : '') + v.toFixed(digits == null ? 3 : digits);
}

function _buildSGP2InsightPrompt(sgp) {
  var lines = [];
  var hits = sgp.hits || {};
  var probs = sgp.probs || {};
  var corr = sgp.correlation || {};
  var n = hits.n || corr.starts || null;

  lines.push('You are a sharp MLB pitcher-prop SGP analyst. Your output appears inside a small card that already shows the verdict badge, score, price, EV%, and correlation numbers. The user has the numbers — your job is to narrate them sharply and correctly. Respond ONLY with valid JSON (no markdown, no backticks, no prose).');
  lines.push('');

  /* All numeric context. Pre-derived. Do not ask the model to recompute. */
  lines.push('=== CONTEXT (every number on the card) ===');
  lines.push('pitcher: ' + sgp.pitcher);
  lines.push('game: ' + (sgp.game || 'n/a'));
  lines.push('pitcher_in_db: ' + (sgp.inDB ? 'yes' : 'no'));
  lines.push('');

  lines.push('legs:');
  (sgp.legs || []).forEach(function (l, i) {
    var fvp = (l.fvProb != null) ? (' / FV prob ' + _fmtPct(l.fvProb * 100)) : '';
    lines.push('  leg' + (i + 1) + ': "' + l.label + '"  FV ' + _fmtAm(l.fv) + fvp);
  });
  lines.push('');

  lines.push('pricing:');
  lines.push('  DK SGP: ' + _fmtAm(sgp.dkSGP) + ' (decimal ' + (sgp.dkDecimal != null ? sgp.dkDecimal.toFixed(3) : 'n/a') + ', implied ' + (sgp.dkDecimal ? _fmtPct(100 / sgp.dkDecimal) : 'n/a') + ')');
  lines.push('  FV correlation-adjusted: ' + _fmtAm(sgp.fvCorr) + ' (joint prob ' + (sgp.fvP != null ? _fmtPct(sgp.fvP * 100) : 'n/a') + ')');
  lines.push('  FV independence: ' + _fmtAm(sgp.fvIndep) + ' (joint prob ' + (sgp.pIndep != null ? _fmtPct(sgp.pIndep * 100) : 'n/a') + ')');
  lines.push('  EV%: ' + (sgp.evPct != null ? _fmtPct(sgp.evPct) : 'n/a'));
  lines.push('  Kelly: ' + (sgp.kellyPct != null ? sgp.kellyPct.toFixed(2) + '%' : 'n/a') + '   1/4 Kelly: ' + (sgp.qkUnits != null ? sgp.qkUnits.toFixed(2) + 'u' : 'n/a'));
  lines.push('');

  lines.push('historical hits (empirical, over ' + (n != null ? n : '?') + ' starts):');
  lines.push('  leg1: ' + (hits.leg1Count != null && n ? (hits.leg1Count + '/' + n) : 'n/a') +
             '   ' + _fmtPct(hits.leg1Pct));
  lines.push('  leg2: ' + (hits.leg2Count != null && n ? (hits.leg2Count + '/' + n) : 'n/a') +
             '   ' + _fmtPct(hits.leg2Pct));
  lines.push('  combined: ' + (hits.bothCount != null && n ? (hits.bothCount + '/' + n) : 'n/a') +
             '   ' + _fmtPct(hits.bothPct));
  lines.push('  P(leg2 | leg1): ' + _fmtPct(hits.givenLeg1toLeg2Pct));
  lines.push('');

  lines.push('probabilities (decimals):');
  lines.push('  P(A) empirical = ' + (probs.pA_emp != null ? probs.pA_emp.toFixed(4) : 'n/a'));
  lines.push('  P(B) empirical = ' + (probs.pB_emp != null ? probs.pB_emp.toFixed(4) : 'n/a'));
  lines.push('  P(A)*P(B) independence = ' + (probs.pA_times_pB_emp != null ? probs.pA_times_pB_emp.toFixed(4) : 'n/a'));
  lines.push('  P(A ∩ B) observed = ' + (probs.pAB_emp != null ? probs.pAB_emp.toFixed(4) : 'n/a'));
  lines.push('  P(B|A) observed = ' + (probs.pBgivenA_emp != null ? probs.pBgivenA_emp.toFixed(4) : 'n/a'));
  lines.push('  -> correlation-exists test: compare P(B|A)=' + (probs.pBgivenA_emp != null ? probs.pBgivenA_emp.toFixed(4) : 'n/a') +
             ' to P(B)=' + (probs.pB_emp != null ? probs.pB_emp.toFixed(4) : 'n/a') +
             '.  DO NOT compare P(B|A) to P(A)*P(B) — that comparison is almost always true and proves nothing.');
  lines.push('');

  lines.push('correlation:');
  lines.push('  r_ours (binary phi, shrunk): ' + _fmtR(sgp.rOurs));
  lines.push('  r_margin (continuous, shrunk): ' + _fmtR(sgp.rMargin));
  lines.push('  r_source: ' + (sgp.rSource || 'n/a'));
  if (sgp.rPlayer != null || sgp.rGlobal != null) {
    lines.push('  r_player=' + _fmtR(sgp.rPlayer) + '  r_global=' + _fmtR(sgp.rGlobal) +
               '   shrinkage weights: ' + Math.round((sgp.wPlayer || 0) * 100) + '% player / ' +
               Math.round((sgp.wGlobal || 0) * 100) + '% global');
  }
  lines.push('  r_DK (implied by DK SGP price + our FV legs): ' + _fmtR(sgp.rDK) +
             (sgp.rDKClamp ? ' [clamped: ' + sgp.rDKClamp + ']' : ''));
  lines.push('  r_gap = r_ours - r_DK = ' + _fmtR(sgp.rGap));
  lines.push('  n_eff: ' + (corr.nEff != null ? corr.nEff.toFixed(1) : 'n/a') +
             '   n_raw: ' + (corr.nRaw != null ? corr.nRaw : 'n/a'));
  lines.push('');

  lines.push('EV attribution (sums to total EV%):');
  lines.push('  EV from legs (independence × DK − 1): ' + (sgp.evFromLegsPct != null ? _fmtPct(sgp.evFromLegsPct) : 'n/a'));
  lines.push('  EV from correlation (our r above independence × DK): ' + (sgp.evFromCorrPct != null ? _fmtPct(sgp.evFromCorrPct) : 'n/a'));
  lines.push('  Total EV%: ' + (sgp.evPct != null ? _fmtPct(sgp.evPct) : 'n/a'));
  lines.push('');

  /* Reasoning rules. The model does not see the card layout — it only sees
     the JSON it emits, rendered into badges and lines. So the rules must
     be about CONTENT discipline, not layout.

     Core framing: DK's standalone pitcher leg markets are near-efficient
     (per-leg fair edge typically within +/-3%). When an SGP card shows
     meaningful EV (>~8%), the math forces the edge to come from DK's
     correlation prior disagreeing with our per-pitcher correlation
     measurement — not from leg mispricing. Leg mispricing is not a
     structurally repeatable edge on pitcher props; correlation
     mispricing IS, because DK applies a generic prior while we measure
     per pitcher. The prompt teaches this framing implicitly through
     the default thesis. */
  lines.push('=== BACKGROUND (read before choosing a thesis) ===');
  lines.push('DK\'s standalone pitcher leg markets are near-efficient: a single leg\'s fair-value edge is almost always within -2% to +3%. This means when an SGP card shows meaningful EV, the math simply does not allow leg mispricing to be the dominant driver. The only place a large edge can come from is DK\'s correlation prior disagreeing with our per-pitcher correlation measurement.');
  lines.push('Leg mispricing is not a structurally repeatable edge on pitcher props — DK prices those markets tightly and adjusts quickly. Correlation mispricing IS structurally repeatable, because DK applies a generic correlation prior across pitchers while we measure per-pitcher correlations from start history.');
  lines.push('');
  lines.push('=== RULES ===');
  lines.push('1. THESIS-FIRST. Pick ONE thesis and stick with it across headline, explanation, edge, and risk. Contradictions (e.g. headline says "weak correlation", edge says "DK underprices correlation") are forbidden.');
  lines.push('   The three theses:');
  lines.push('     (a) CORRELATION GAP — DK prices in a different correlation than our data supports (r_gap is the story). DEFAULT for any card with EV > 8%.');
  lines.push('     (b) LEG MISPRICING — a leg\'s fair value genuinely differs from DK\'s implied. RARE on pitcher props. Only pick (b) when EV is small AND |r_gap| < 0.05 AND evFromLegsPct carries most of the EV.');
  lines.push('     (c) MARGINAL — EV < 3% and |r_gap| < 0.05. Not a structural edge; card is a wash.');
  lines.push('   Use the EV-size decision table:');
  lines.push('     EV > ~8%   -> correlation-gap thesis (a) is the default. Leg mispricing is a secondary clause at most, not the thesis.');
  lines.push('     EV 3-8%    -> check attribution. Whichever of evFromLegsPct / evFromCorrPct is larger leads; the smaller is a supporting clause.');
  lines.push('     EV < 3%    -> likely (c); call it marginal unless there is a specific structural reason to play.');
  lines.push('');
  lines.push('2. CORRECT MATH.');
  lines.push('   - To argue correlation exists IN OUR SAMPLE, compare P(B|A) vs P(B). If P(B|A) > P(B), positive; if <, negative; within a couple of pp, effectively zero. NEVER argue that P(B|A) > P(A)*P(B) proves correlation — that comparison is almost always true and proves nothing.');
  lines.push('   - IMPORTANT: a near-zero r_ours does NOT mean "no correlation edge." It means OUR SAMPLE shows no correlation. The correlation edge lives in r_gap = r_ours - r_DK. A r_ours of +0.02 with a r_DK of -0.14 is a large correlation edge (DK is pricing in negative correlation that our data does not support) even though our r is near zero.');
  lines.push('');
  lines.push('3. USE r_DK.');
  lines.push('   - r_DK is what DK is pricing; r_ours is what our data shows. Always cite both when the correlation thesis is in play: "DK implies r≈X; our N-start sample shows r≈Y, a gap of Z."');
  lines.push('   - Directional rules:');
  lines.push('       r_gap > +0.05  -> DK prices in more negative correlation than our data supports. SGP is underpriced. This is the structural edge we hunt — lead with it.');
  lines.push('       r_gap < -0.05  -> DK prices in more positive correlation than our data supports. SGP is overpriced on correlation. Any +EV must overcome that; the score should reflect skepticism.');
  lines.push('       |r_gap| < 0.05 -> we agree with DK\'s correlation. If EV is meaningful (>5%) yet r_gap is tiny, flag it as unusual — something in the attribution or a near-efficient leg market accident. If EV < 3%, mark marginal (thesis c).');
  lines.push('   - When citing "worth X% of EV on its own", quote the attribution numbers directly (evFromCorrPct and evFromLegsPct). Do NOT recompute.');
  lines.push('   - Teach the user implicitly: frame the correlation edge as "DK applies a generic prior for this stat pair; this pitcher\'s history does not match." Do not belabor the point — one clause is enough.');
  lines.push('');
  lines.push('4. SPECIFIC RISK. risk must reference at least one number or fact from the context above (sample size, a specific leg hit rate, n_eff, blend %, r_gap magnitude, r_DK clamp, specific opponent/park from the game string). Never write a generic "usage pattern or injury history could shift baseline" line.');
  lines.push('');
  lines.push('5. HONEST SCORE. confidence must be tied to one specific data point. Defaults (7/10) are not allowed. Anchors:');
  lines.push('     confidence 8-9: EV% >= 10 AND n_raw >= 40 AND r_gap aligned with the thesis (positive r_gap for a play) AND no rDK clamp.');
  lines.push('     confidence 5-7: EV% 3-10, or n_raw 15-40, or r_gap modest and attribution ambiguous.');
  lines.push('     confidence 1-4: EV% < 3, n_raw < 15, rDK clamped, missingPairs>0, or thesis requires a negative-r_gap play.');
  lines.push('   If the only justification is generic, drop the score by 2.');
  lines.push('');
  lines.push('6. VALUES. Quote context numbers directly. Do NOT invent, round away, or re-derive. If a value is n/a, say so — never substitute.');
  lines.push('');
  lines.push('=== OUTPUT (JSON only; no markdown) ===');
  lines.push('{"verdict":"PLAY","headline":"one-line thesis, max 14 words","explanation":"2-3 sentences, grounded in context numbers","edge":"1 sentence; must agree with headline thesis","risk":"1 sentence; must cite a specific number from context","confidence":8}');
  lines.push('');
  lines.push('Example (deGrom, Over 3.5 Hits Allowed + Over 16.5 Outs, EV +19.6%, r_ours=+0.02, r_DK=-0.14):');
  lines.push('  headline: "DK\'s negative-correlation prior doesn\'t fit deGrom — correlation gap drives the edge"');
  lines.push('  explanation: "DK\'s SGP price implies r ≈ -0.14 — the standard \'hit around, pulled early\' prior. Our 42-start sample shows r ≈ +0.02: deGrom works through traffic rather than getting yanked. That 0.16 gap accounts for the bulk of the 19.6% EV; leg pricing contributes only a few points on top."');
  lines.push('  edge: "DK applies a generic negative-correlation prior for Hits × Outs that doesn\'t match this pitcher\'s history; that mismatch is the whole game, leg pricing a minor bonus."');
  lines.push('  risk: "42-start sample with n_eff 29.2; shrinkage pulls our r halfway toward the global baseline, so true correlation could still be modestly negative."');
  lines.push('');
  lines.push('verdict rules:');
  lines.push('  PLAY     = EV% > 5 AND the chosen thesis is structurally supported (correlation gap aligned, OR small-EV leg edge with |r_gap|<0.05).');
  lines.push('  MARGINAL = EV% 0-5, data thin (n_eff < 15, missingPairs>0, rDKClamp set), or r_gap negative and EV relying on correlation surviving.');
  lines.push('  SKIP     = EV% < 0, OR r_gap strongly negative and EV small enough that overcoming DK\'s correlation price is implausible.');

  return lines.join('\n');
}

/* 3-leg variant. Preserved from prior spec (empirical 3-way joint as the
   model ground truth). Prompt updated to carry the same thesis-first,
   specific-risk, and honest-score rules as the 2-leg variant. r_DK
   inversion is 2-leg-specific (pairwise Fréchet) and is not applied
   here. Reads directly from the _build3LegSgpData shape emitted by
   index.html (top-level pairDetails, all3 decimal-prob object,
   per-leg baseRate on legs[]). */
function _buildSGP3InsightPrompt(sgp) {
  var lines = [];

  lines.push('You are a sharp MLB pitcher-prop 3-leg SGP analyst. Respond ONLY with valid JSON — no markdown, no backticks, no prose.');
  lines.push('');
  lines.push('=== CONTEXT (3-LEG) ===');
  lines.push('pitcher: ' + sgp.pitcher);
  lines.push('game: ' + sgp.game);
  lines.push('');
  lines.push('legs:');
  (sgp.legs || []).forEach(function (leg, i) {
    var base = (leg.baseRate != null) ? (' / base ' + _fmtPct(leg.baseRate)) : '';
    lines.push('  leg' + (i + 1) + ': "' + leg.label + '"  FV ' + _fmtAm(leg.fv) + base);
  });
  lines.push('');
  lines.push('pricing:');
  lines.push('  DK SGP: ' + _fmtAm(sgp.dkSGP));
  lines.push('  FV correlation-adjusted (pairwise Fréchet): ' + _fmtAm(sgp.fvCorr));
  lines.push('  Primary EV% (vs FV): ' + (sgp.evPct != null ? _fmtPct(sgp.evPct) : 'n/a') + '  — decision number');
  if (sgp.evPctModel != null) {
    lines.push('  Secondary EV% (vs aggregates model): ' + _fmtPct(sgp.evPctModel) + '  — diagnostic');
  }
  lines.push('  FV-correlated joint probability: ' + (sgp.fvP != null ? _fmtPct(sgp.fvP * 100) : 'n/a'));
  if (sgp.pModel != null) {
    lines.push('  Aggregates blended 3-way joint: ' + _fmtPct(sgp.pModel * 100));
  }
  if (sgp.dkHoldPct != null) {
    lines.push('  DK correlation premium vs indep product of DK legs: ' + _fmtPct(sgp.dkHoldPct));
  }
  lines.push('');

  lines.push('pairwise correlations:');
  var pairs = sgp.pairDetails || (sgp.correlation && sgp.correlation.pairs) || [];
  if (pairs.length) {
    pairs.forEach(function (p) {
      lines.push('  ' + p.a + ' × ' + p.b + ': r=' + _fmtR(p.r));
    });
  } else {
    lines.push('  (none available)');
  }
  lines.push('');

  lines.push('empirical 3-way joint:');
  var all3 = sgp.all3 || {};
  if (all3.pPlayer != null) lines.push('  player all-3-hit: ' + _fmtPct(all3.pPlayer * 100));
  if (all3.pGlobal != null) lines.push('  global all-3-hit: ' + _fmtPct(all3.pGlobal * 100));
  if (all3.pBlend != null) lines.push('  blended: ' + _fmtPct(all3.pBlend * 100));
  if (all3.nEff != null) {
    lines.push('  shrinkage: ' + Math.round((all3.wPlayer || 0) * 100) + '% player / ' +
               Math.round((all3.wGlobal || 0) * 100) + '% global, n_eff=' + all3.nEff.toFixed(1) +
               (all3.nRaw != null ? ' (raw ' + all3.nRaw + ')' : ''));
  }
  lines.push('');

  lines.push('=== RULES ===');
  lines.push('1. THESIS-FIRST. Pick ONE thesis: (a) all-3-hit rate beats DK implied, (b) DK correlation premium disagrees with our pairwise structure, (c) both. Keep headline, explanation, edge, and risk consistent with the chosen thesis.');
  lines.push('2. PITCHER-QUALITY CONFOUND. An ace has a high all-3-hit rate because they are good; DK\'s per-leg prices already capture that. When n_eff < 25 OR edge > 15pp, flag this explicitly.');
  lines.push('3. FV vs AGGREGATES DIVERGENCE. When primary and secondary EV differ by > 15pp, call it out — FV and aggregates disagree about this combo.');
  lines.push('4. SPECIFIC RISK. risk must reference a specific number: n_eff, a leg hit rate, DK corr premium magnitude, edge size, or shrinkage weight. No generic "usage/injury" lines.');
  lines.push('5. HONEST SCORE. Tie confidence to one specific data point. Cap at 6 when n_eff < 20; cap at 8 when any pair r is missing; further cap at 8 when DK correlation premium already absorbs > 10% and the model\'s claimed edge is pure correlation.');
  lines.push('6. VALUES. Quote context numbers directly; do not invent, re-derive, or round them away.');
  lines.push('');
  lines.push('=== OUTPUT (JSON only) ===');
  lines.push('{"verdict":"PLAY","headline":"one-line thesis, max 14 words","explanation":"2-3 sentences, grounded in context","edge":"1 sentence; must agree with headline","risk":"1 sentence; must cite a specific number","confidence":8}');
  lines.push('');
  lines.push('verdict rules:');
  lines.push('  PLAY     = primary EV% > 10 AND n_eff >= 20 AND primary vs secondary EV agree in sign.');
  lines.push('  MARGINAL = thin EV, borderline sample, or FV/aggregates disagree materially.');
  lines.push('  SKIP     = primary EV% < 0 OR edge is plausibly pitcher-quality-confounding at small n_eff.');

  return lines.join('\n');
}

/* UMD-ish export so the prompt builder is importable in the Node smoke
   scripts while the script-tag call in index.html keeps working. */
if (typeof module === 'object' && module.exports) {
  module.exports = { buildSGPInsightPrompt: buildSGPInsightPrompt };
}
