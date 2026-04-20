/* teammateMath.js — pure math helpers for the teammate EV pipeline.
   UMD: works as <script> in browser (window.teammateMath) or require()
   in Node. Depends only on sgpMath.js (single source of truth for
   Fréchet joint + odds conversions — shared with pitcher EV pipeline).

   No schema knowledge here — everything takes primitives as args. The
   enumeration + resolvePairR wrapper + slotMatchConfidence logic lives
   in teammateEv.js (file 2). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./sgpMath.js'));
  } else {
    root.teammateMath = factory(root.sgpMath);
  }
}(typeof self !== 'undefined' ? self : this, function (sgpMath) {

  if (!sgpMath) {
    throw new Error('teammateMath: sgpMath is required (load /utils/sgpMath.js first)');
  }

  /* ========== Stat label translation ==========
     Phase 1 combo_spec uses abbreviated stat labels ("Over 0.5 R", "Over
     0.5 RBI"). Chunk 2's DK matcher and chunk 3's FV OCR use the full
     canonical labels ("Over 0.5 Runs", "Over 0.5 RBIs"). This table
     bridges them.

     Intentional skips:
       SO   — batter strikeouts; Phase 1 has correlations, chunk 2 vocab
              does not (decision: revisit if batter-K props become a
              priority). Combos with SO are dropped in enumeration.
       HRR  — multi-stat (Hits + Runs + RBIs) combo prop. No single-stat
              DK market matches it. Also dropped.

     Forward-compat in the OTHER direction: chunk 2 vocab includes
     Singles/Doubles/Triples/Stolen Bases, but Phase 1 combo_spec has
     no correlations for them. Those simply yield zero candidates from
     enumeration — not a bug, expected. */
  var STAT_SHORT_TO_FULL = {
    'H':   'Hits',
    'R':   'Runs',
    'RBI': 'RBIs',
    'HR':  'Home Runs',
    'TB':  'Total Bases',
    'BB':  'Walks',
    'SB':  'Stolen Bases',
  };
  /* Stats deliberately not translatable (see comment above). Checked
     explicitly so enumeration can emit a targeted diagnostic rather
     than a generic "unknown stat" error. */
  var STAT_SHORT_SKIP = { 'SO': 'batter strikeouts not in chunk 2 vocab',
                          'HRR': 'multi-stat combo prop (no DK single-leg match)' };

  /* Reverse table for the FV → Phase-1 direction. Same keys inverted;
     chunk 2 vocab-only stats (1B, 2B, 3B) are absent on purpose. */
  var STAT_FULL_TO_SHORT = {};
  Object.keys(STAT_SHORT_TO_FULL).forEach(function (k) {
    STAT_FULL_TO_SHORT[STAT_SHORT_TO_FULL[k]] = k;
  });

  /* Parse a canonical leg string like "Over 0.5 RBI" or "Over 0.5 Total Bases"
     → { direction, threshold, stat }. Stat is returned verbatim (no
     translation). Returns null on malformed input. */
  function parseLeg(s) {
    if (!s || typeof s !== 'string') return null;
    var parts = s.trim().split(/\s+/);
    if (parts.length < 3) return null;
    var t = parseFloat(parts[1]);
    if (isNaN(t)) return null;
    return { direction: parts[0], threshold: t, stat: parts.slice(2).join(' ') };
  }

  /* Translate a Phase-1 leg ("Over 0.5 R") → canonical leg ("Over 0.5 Runs").
     Returns { leg, skipped, reason }. On skipped stats (SO, HRR), leg is
     null and reason carries the diagnostic. */
  function shortLegToFull(s) {
    var p = parseLeg(s);
    if (!p) return { leg: null, skipped: true, reason: 'malformed leg' };
    if (STAT_SHORT_SKIP[p.stat]) return { leg: null, skipped: true, reason: STAT_SHORT_SKIP[p.stat] };
    var full = STAT_SHORT_TO_FULL[p.stat];
    if (!full) return { leg: null, skipped: true, reason: 'unknown short stat: ' + p.stat };
    return { leg: p.direction + ' ' + p.threshold + ' ' + full,
             skipped: false, direction: p.direction, threshold: p.threshold,
             statFull: full, statShort: p.stat };
  }

  /* ========== Joint probability + EV math ========== */

  /* Thin re-exports so callers can import everything from one module. */
  var jointFrechet      = sgpMath.jointFrechet;
  var americanToProb    = sgpMath.americanToProb;
  var probToAmerican    = sgpMath.probToAmerican;
  var americanToDecimal = sgpMath.americanToDecimal;
  var decimalToAmerican = sgpMath.decimalToAmerican;

  /* EV% given fair joint probability + DK decimal odds. Matches the
     pitcher pipeline's evPct calculation (index.html:1429).
       ev_pct = (pJoint * dk_decimal - 1) * 100 */
  function evPct(pJoint, dkDecimal) {
    if (pJoint == null || dkDecimal == null || isNaN(pJoint) || isNaN(dkDecimal)) return null;
    return (pJoint * dkDecimal - 1) * 100;
  }

  /* Full Kelly fraction for one bet at pJoint true prob, dk_decimal odds.
     kelly = (p*d - 1) / (d - 1). Matches index.html:1430. */
  function fullKelly(pJoint, dkDecimal) {
    if (pJoint == null || dkDecimal == null || dkDecimal <= 1) return null;
    return (pJoint * dkDecimal - 1) / (dkDecimal - 1);
  }

  /* Quality Kelly = 0.25 × full Kelly, clamped non-negative, expressed as
     percentage-of-bankroll units. Matches index.html:1438-1439.
     Returns null when inputs are bad. */
  function qualityKelly(pJoint, dkDecimal) {
    var k = fullKelly(pJoint, dkDecimal);
    if (k == null) return null;
    return Math.max(0, k * 0.25) * 100;
  }

  /* Convenience: everything-from-one-call. Given leg probs and r, return
     the full bundle of derived numbers a card / row would display.
     Clamped to (1e-6, 0.999999) to keep probToAmerican from exploding.

     p1, p2: 0..1 implied probs from each leg's FV
     r:      resolved binary correlation (blended/player/global)
     dkDec:  DK decimal odds for the joint SGP
     Returns { pJoint, fvCorrAmerican, evPct, kellyPct, qkPct }.
     All fields null when dkDec is absent so callers can still display
     correlation-adjusted FV without a DK price. */
  function ivBundle(p1, p2, r, dkDec) {
    if (p1 == null || p2 == null) return null;
    var raw = jointFrechet(p1, p2, r);
    var pJoint = Math.max(1e-6, Math.min(0.999999, raw));
    var fvCorrAmerican = probToAmerican(pJoint);
    if (dkDec == null || isNaN(dkDec)) {
      return { pJoint: pJoint, fvCorrAmerican: fvCorrAmerican,
               evPct: null, kellyPct: null, qkPct: null };
    }
    var full = fullKelly(pJoint, dkDec);
    return {
      pJoint: pJoint,
      fvCorrAmerican: fvCorrAmerican,
      evPct: evPct(pJoint, dkDec),
      kellyPct: full == null ? null : Math.max(0, full) * 100,
      qkPct: qualityKelly(pJoint, dkDec),
    };
  }

  return {
    // Translation
    STAT_SHORT_TO_FULL: STAT_SHORT_TO_FULL,
    STAT_FULL_TO_SHORT: STAT_FULL_TO_SHORT,
    STAT_SHORT_SKIP:    STAT_SHORT_SKIP,
    parseLeg:     parseLeg,
    shortLegToFull: shortLegToFull,
    // Re-exports from sgpMath
    jointFrechet:      jointFrechet,
    americanToProb:    americanToProb,
    probToAmerican:    probToAmerican,
    americanToDecimal: americanToDecimal,
    decimalToAmerican: decimalToAmerican,
    // EV / Kelly
    evPct:        evPct,
    fullKelly:    fullKelly,
    qualityKelly: qualityKelly,
    ivBundle:     ivBundle,
  };
}));
