/* teammateInsightPrompt.js — Claude prompt builder for the Teammate +EV
   tab's AI Insights feature. Mirrors the pitcher-side sgpInsightPrompt.js
   pattern so verdict/headline/explanation/edge/risk/confidence round-trip
   JSON and the inline panel renderer can be reused.

   Differences from pitcher prompt:
     - Two players (pair) instead of one pitcher + multi-leg
     - Single combo (always 2 legs — one per player)
     - Tonight's slot pair vs the pair's historical default slots — surfaces
       LINEUP CHANGE as a first-class interpretation hook
     - slot_match_confidence (high/medium/low/none) — replaces "sample size"
       as the primary confidence anchor
     - Shrinkage provenance (player r × w + slot-baseline r × (1−w))
       exposed so the model can calibrate how much to trust the pair-
       specific signal vs the cross-config baseline

   sgp shape passed in:
     p1, p2          string
     team            string
     gameLabel       string          "BAL @ KC"
     mode            string          "player" | "blended" | "global"
     fallback        boolean         true when blended collapsed to global
     leg1Full        string          canonical "Over 0.5 Runs"
     leg2Full        string          canonical "Over 0.5 RBIs"
     fv1, fv2        number          American odds per leg (FV)
     pLeg1, pLeg2    number          0..1 implied probabilities
     dkAmerican      number          DK SGP American odds
     fvCorrAmerican  number          FV correlation-adjusted American
     pJoint          number          0..1 Fréchet-joint probability
     evPct           number          EV% (may be an OUTLIER — treat as data flag)
     qkPct           number          Quality Kelly units (1/4-Kelly)
     rBinary         number|null     resolved binary r
     rMargin         number|null     resolved margin r (display signal)
     rBinaryPlayer   number|null     pair-specific r_binary, pre-shrinkage
     rBinaryGlobal   number|null     slot-baseline r_binary
     wPlayer         number          0..1 blend weight on pair data
     hit1, hit2      number|null     0..1 historical per-leg hit rates
     bothHit         number|null     0..1 historical both-hit rate
     nTotal          number          pair.n_total (games together)
     tonightSlots    [s1, s2]        p1_slot, p2_slot tonight
     historicalSlots [s1, s2]|null   pair.most_common_slots
     slotMatchConfidence { level, n, key }
*/
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.buildTeammateInsightPrompt = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {

  function fmtNum(n, d) {
    if (n == null || isNaN(n)) return 'n/a';
    return Number(n).toFixed(d == null ? 4 : d);
  }
  function fmtSigned(n) {
    if (n == null || isNaN(n)) return 'n/a';
    return (n > 0 ? '+' : '') + n;
  }
  function fmtPctRaw(x) {
    if (x == null || isNaN(x)) return 'n/a';
    return (Number(x) * 100).toFixed(1) + '%';
  }

  /* Classify the shift from historical slots to tonight's slots. The model
     uses this to decide how much to discount the pair-specific correlation
     when betting tonight.
       same        slots identical (or swapped identical pair)
       tighter     the slot gap is smaller tonight (p1+p2 slot numbers closer)
       wider       the slot gap is larger tonight
       different   historical is null or the overlap is zero
     "tighter" is flagged because MLB run-scoring correlation tends to
     strengthen when teammates bat nearer each other (runner/driver role
     alignment). The model isn't told to apply a magnitude — just to
     acknowledge the direction when relevant. */
  function describeSlotShift(tonight, historical) {
    if (!tonight || tonight.length !== 2) return { kind: 'unknown', detail: 'no tonight slots' };
    if (!historical || historical.length !== 2) {
      return { kind: 'different', detail: 'pair has no historical default slots recorded' };
    }
    var tGap = Math.abs(tonight[0] - tonight[1]);
    var hGap = Math.abs(historical[0] - historical[1]);
    var sameSet = (tonight[0] === historical[0] && tonight[1] === historical[1]) ||
                  (tonight[0] === historical[1] && tonight[1] === historical[0]);
    if (sameSet) {
      return { kind: 'same',
               detail: 'tonight ' + tonight[0] + '-' + tonight[1] +
                       ' matches pair historical default' };
    }
    if (tGap < hGap) {
      return { kind: 'tighter',
               detail: 'tonight ' + tonight[0] + '-' + tonight[1] +
                       ' is tighter than historical ' + historical[0] + '-' + historical[1] +
                       ' (gap ' + tGap + ' vs ' + hGap + ')' };
    }
    if (tGap > hGap) {
      return { kind: 'wider',
               detail: 'tonight ' + tonight[0] + '-' + tonight[1] +
                       ' is wider than historical ' + historical[0] + '-' + historical[1] +
                       ' (gap ' + tGap + ' vs ' + hGap + ')' };
    }
    return { kind: 'different',
             detail: 'tonight ' + tonight[0] + '-' + tonight[1] +
                     ' differs from historical ' + historical[0] + '-' + historical[1] +
                     ' at same gap' };
  }

  function buildTeammateInsightPrompt(sgp) {
    var L = [];

    L.push('You are a sharp sports betting analyst specializing in MLB batter teammate-pair Same Game Parlays.');
    L.push('Analyze the following 2-leg teammate SGP and respond ONLY with valid JSON — no markdown, no backticks, no prose before or after the JSON.');
    L.push('');

    L.push('=== PAIR ===');
    L.push('Team:        ' + (sgp.team || 'n/a'));
    L.push('Game:        ' + (sgp.gameLabel || 'n/a'));
    L.push('Player 1:    ' + sgp.p1 + '   (batting slot ' + (sgp.tonightSlots ? sgp.tonightSlots[0] : '?') + ' tonight)');
    L.push('Player 2:    ' + sgp.p2 + '   (batting slot ' + (sgp.tonightSlots ? sgp.tonightSlots[1] : '?') + ' tonight)');
    L.push('Games together (all seasons): ' + (sgp.nTotal || 0));
    L.push('');

    L.push('=== LINEUP CONTEXT ===');
    var shift = describeSlotShift(sgp.tonightSlots, sgp.historicalSlots);
    L.push('Tonight slots:          ' + (sgp.tonightSlots ? sgp.tonightSlots.join('-') : 'n/a'));
    L.push('Historical default:     ' + (sgp.historicalSlots ? sgp.historicalSlots.join('-') : 'none'));
    L.push('Slot shift:             ' + shift.kind + ' (' + shift.detail + ')');
    var conf = sgp.slotMatchConfidence || { level: 'none', n: 0 };
    L.push('Slot-match confidence:  ' + conf.level + '  (' + conf.n + ' historical games at tonight\'s exact slot config)');
    L.push('');

    L.push('=== LEGS ===');
    L.push('Leg 1:  ' + (sgp.leg1Full || '?') + '  (' + sgp.p1 + ')   FV ' + fmtSigned(sgp.fv1) +
           '   implied ' + fmtPctRaw(sgp.pLeg1));
    L.push('Leg 2:  ' + (sgp.leg2Full || '?') + '  (' + sgp.p2 + ')   FV ' + fmtSigned(sgp.fv2) +
           '   implied ' + fmtPctRaw(sgp.pLeg2));
    L.push('');

    L.push('=== PRICING ===');
    L.push('DK SGP price:                 ' + fmtSigned(sgp.dkAmerican));
    L.push('FV correlation-adjusted:      ' + fmtSigned(sgp.fvCorrAmerican));
    L.push('FV joint probability:         ' + fmtPctRaw(sgp.pJoint));
    L.push('EV%:                          ' + (sgp.evPct == null ? 'n/a' : sgp.evPct.toFixed(1) + '%'));
    L.push('Quality Kelly (1/4-Kelly):    ' + (sgp.qkPct == null ? 'n/a' : sgp.qkPct.toFixed(2) + 'u'));
    if (sgp.evPct != null && sgp.evPct > 100) {
      L.push('');
      L.push('FLAG: EV% > 100% — this is likely a DK mispricing or a long-tail same-stat parlay boost.');
      L.push('      Treat as an outlier worth verifying on DK before any strong recommendation.');
    }
    L.push('');

    L.push('=== CORRELATION ===');
    L.push('Mode:                ' + (sgp.mode || 'blended').toUpperCase() +
           (sgp.fallback ? '  (blended collapsed to slot-baseline — pair sample was below blend threshold)' : ''));
    L.push('Binary r (resolved): ' + fmtNum(sgp.rBinary));
    L.push('Margin r (display):  ' + fmtNum(sgp.rMargin));
    if (sgp.rBinaryPlayer != null || sgp.rBinaryGlobal != null) {
      var wp = sgp.wPlayer == null ? 0 : sgp.wPlayer;
      var wpPct = Math.round(wp * 100);
      L.push('Shrinkage split:     player r = ' + fmtNum(sgp.rBinaryPlayer) +
             '  ×  ' + wpPct + '%   +   slot-baseline r = ' + fmtNum(sgp.rBinaryGlobal) +
             '  ×  ' + (100 - wpPct) + '%   →  ' + fmtNum(sgp.rBinary));
      L.push('                     (slot-baseline above is for tonight\'s ' +
             (sgp.tonightSlots ? sgp.tonightSlots.join('-') : '?') +
             ' config, NOT the pair\'s historical default)');
    }
    L.push('');
    L.push('Interpret binary r vs margin r:');
    L.push('  - Same sign, similar magnitude      stable relationship, high correlation confidence');
    L.push('  - Same sign, margin >> binary       underlying stats move together but the specific line');
    L.push('                                       thresholds don\'t carve the edge — EV may be weaker');
    L.push('                                       than binary suggests');
    L.push('  - Opposite signs                    the specific thresholds fight the underlying');
    L.push('                                       relationship — usually a weak or negative edge');
    L.push('  - Both near zero                    legs effectively independent — EV comes from');
    L.push('                                       pricing, not correlation arbitrage');
    L.push('');

    L.push('=== HISTORICAL HIT RATES ===');
    L.push('Leg 1 hit rate:            ' + fmtPctRaw(sgp.hit1));
    L.push('Leg 2 hit rate:            ' + fmtPctRaw(sgp.hit2));
    L.push('Both-legs hit rate:        ' + fmtPctRaw(sgp.bothHit) +
           (sgp.bothHit != null && sgp.nTotal ? '  (' + Math.round(sgp.bothHit * sgp.nTotal) + ' / ' + sgp.nTotal + ' games)' : ''));
    L.push('');

    L.push('=== INTERPRETATION GUIDANCE ===');
    L.push('Weight these factors when forming your verdict:');
    L.push('');
    L.push('  1. Slot-match confidence is the PRIMARY data-quality anchor here, not raw games-together.');
    L.push('     - HIGH   (>= 20 games at tonight\'s exact slot config): trust the pair-specific r strongly.');
    L.push('     - MEDIUM (5-19 games): pair-specific signal is real but noisy at this slot config — slight discount.');
    L.push('     - LOW    (< 5 games):  tonight\'s config is unusual for this pair; the blended r is mostly');
    L.push('                            cross-config extrapolation — strong caveat.');
    L.push('     - NONE   (0 games):    the pair has NEVER batted at tonight\'s exact slots together;');
    L.push('                            the blended r is pure extrapolation — strongest caveat, flag explicitly.');
    L.push('');
    L.push('  2. Slot shift from historical default matters even when the confidence level is high.');
    L.push('     - SAME: tonight matches the pair\'s historical lineup — no adjustment.');
    L.push('     - TIGHTER: teammates batting closer together tonight typically sees SLIGHTLY STRONGER');
    L.push('                run-scoring correlation (runner/driver role alignment) — correlation may run');
    L.push('                a touch above the slot-baseline used in shrinkage.');
    L.push('     - WIDER:   teammates batting farther apart — correlation may run a touch BELOW.');
    L.push('     - DIFFERENT: a genuine lineup change from the pair\'s default — name the shift explicitly');
    L.push('                  (e.g. "Witt-Perez historically bat 2-4, tonight they\'re batting 1-3").');
    L.push('');
    L.push('  3. Margin vs binary r disagreement: covered above. Work it into the commentary when relevant,');
    L.push('     don\'t restate numbers.');
    L.push('');
    L.push('  4. EV > 100% outlier flag (if present): the user has already been warned visually. Your job is');
    L.push('     to judge whether the DK price is plausibly legit or plausibly a mispricing they should avoid.');
    L.push('');
    L.push('Keep the commentary concise. Don\'t lecture — interpret.');
    L.push('');

    L.push('Respond with ONLY this JSON (no markdown, no backticks):');
    L.push('{"verdict":"PLAY","headline":"Short takeaway here","explanation":"2-3 sentences.","edge":"1 sentence on what gives this value.","risk":"1 sentence on the main risk.","confidence":8}');
    L.push('');
    L.push('Rules:');
    L.push('- verdict: "PLAY" (EV% > 5 and correlation + lineup context are supportive),');
    L.push('           "MARGINAL" (thin EV, low slot-match confidence, binary/margin disagreement, or');
    L.push('           an EV>100% outlier that looks more like a DK anomaly than a real edge),');
    L.push('           "SKIP" (negative EV or correlation undermines the parlay)');
    L.push('- headline: max 12 words, punchy, captures the key signal');
    L.push('- explanation: 2-3 sentences covering EV, correlation strength, slot-match confidence, and any');
    L.push('  notable slot shift or binary/margin disagreement');
    L.push('- edge: 1 sentence — what specifically makes this worth playing (or not)');
    L.push('- risk: 1 sentence — biggest concern or caveat (lineup status, slot mismatch, sample size, etc.)');
    L.push('- confidence: integer 1-10 based on data quality, slot-match confidence, sample size, and conviction');

    return L.join('\n');
  }

  return buildTeammateInsightPrompt;
}));
