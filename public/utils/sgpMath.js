/* sgpMath.js — odds + joint-probability helpers shared by pitcher and
   teammate EV pipelines. UMD: works as <script> in browser (window.sgpMath)
   or require() in Node. Single source of truth — index.html and
   teammateEv.js both consume from here. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.sgpMath = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {

  /* American → implied probability. Returns null on bad input.
     +120 → 100/(120+100) = 0.4545 ; -150 → 150/(150+100) = 0.6 */
  function americanToProb(o) {
    o = parseFloat(o);
    if (!o || isNaN(o)) return null;
    return o > 0 ? 100 / (o + 100) : -o / (-o + 100);
  }

  /* Probability → American odds (rounded to integer). Null on out-of-range.
     Inverse of americanToProb modulo rounding. */
  function probToAmerican(p) {
    if (p == null || isNaN(p) || p <= 0 || p >= 1) return null;
    return p >= 0.5 ? Math.round(-p / (1 - p) * 100) : Math.round((1 - p) / p * 100);
  }

  /* American → decimal odds. +120 → 2.20 ; -150 → 1.667 */
  function americanToDecimal(o) {
    o = parseFloat(o);
    if (!o || isNaN(o)) return null;
    return o > 0 ? 1 + o / 100 : 1 + 100 / -o;
  }

  /* Decimal → American odds (rounded). 2.20 → +120 ; 1.667 → -150 */
  function decimalToAmerican(d) {
    d = parseFloat(d);
    if (!d || isNaN(d) || d <= 1) return null;
    return d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1));
  }

  /* jointFrechet: Fréchet bound-interpolated joint probability.
     For r >= 0: linear blend between independence (r=0 → pa*pb) and Fréchet
     upper bound (r=1 → min(pa,pb)).
     For r <  0: linear blend between independence and Fréchet lower bound
     (r=-1 → max(0, pa+pb-1)).
     The pitcher EV pipeline has used this since Phase 1; the teammate
     pipeline reuses the SAME function so bet-quality intuition stays
     calibrated across both tabs.
       jointFrechet(0.5, 0.5,  0.4) = 0.25 + 0.4*(0.5-0.25) = 0.35
       jointFrechet(0.5, 0.5,  0.0) = 0.25
       jointFrechet(0.5, 0.5, -0.4) = 0.25 + (-0.4)*(0.25-0) = 0.15 */
  function jointFrechet(pa, pb, r) {
    if (r === null || r === undefined || isNaN(r)) r = 0;
    var pab = pa * pb;
    if (r >= 0) {
      return pab + r * (Math.min(pa, pb) - pab);
    }
    return pab + r * (pab - Math.max(0, pa + pb - 1));
  }

  /* inverseJointFrechet: given fair leg probabilities pa, pb and an observed
     joint probability pjoint, return the r that would produce pjoint under
     jointFrechet(pa, pb, r). Piecewise-linear inversion:
       pjoint = pa*pb + r*(min(pa,pb) - pa*pb)       [r >= 0]
       pjoint = pa*pb + r*(pa*pb - max(0, pa+pb-1))  [r <  0]
     Returns { r, clamp } where clamp is 'ceiling' when pjoint > upper Fréchet
     bound, 'floor' when < lower bound, or null. r is clamped to [-1, 1].
     Degenerate legs (pa or pb at 0/1) collapse the interpolation interval to
     zero on one or both sides; we fall back to r=0 and flag 'degenerate'. */
  function inverseJointFrechet(pa, pb, pjoint) {
    if (pa == null || pb == null || pjoint == null ||
        isNaN(pa) || isNaN(pb) || isNaN(pjoint)) return { r: null, clamp: null };
    var indep = pa * pb;
    var lo = Math.max(0, pa + pb - 1);
    var hi = Math.min(pa, pb);
    if (hi - lo <= 1e-12) return { r: 0, clamp: 'degenerate' };
    if (pjoint >= hi) return { r: 1, clamp: pjoint > hi + 1e-9 ? 'ceiling' : null };
    if (pjoint <= lo) return { r: -1, clamp: pjoint < lo - 1e-9 ? 'floor' : null };
    if (pjoint > indep) {
      var denomUp = hi - indep;
      if (denomUp <= 1e-12) return { r: 0, clamp: 'degenerate' };
      return { r: (pjoint - indep) / denomUp, clamp: null };
    }
    if (pjoint < indep) {
      var denomDn = indep - lo;
      if (denomDn <= 1e-12) return { r: 0, clamp: 'degenerate' };
      return { r: (pjoint - indep) / denomDn, clamp: null };
    }
    return { r: 0, clamp: null };
  }

  /* evAttribution: split total 2-leg SGP EV into leg vs correlation pieces
     using independence as the shared reference point:

       pIndep      = pa * pb                             — "no-corr" baseline
       pJointOurs  = jointFrechet(pa, pb, rOurs)         — our fair joint
       pJointDK    = 1 / dkDecimal                       — DK implied joint
       rDK         = inverseJointFrechet(pa, pb, pJointDK).r

     Then total EV factors cleanly:
       evTotalPct     = (pJointOurs * dkDecimal - 1) * 100
                      = evFromLegsPct + evFromCorrPct
       evFromLegsPct  = (pIndep     * dkDecimal - 1) * 100
       evFromCorrPct  = (pJointOurs - pIndep) * dkDecimal * 100

     Interpretation:
       - evFromLegsPct is the EV you'd see if the two legs were uncorrelated
         — i.e. how much our marginal fair probabilities beat DK's combined
         implied probability on their own.
       - evFromCorrPct is the additional EV (positive or negative) that our
         correlation contributes on top of independence.

     rDK is computed alongside (same pa, pb) so the narrative can reference
     "the r DK's SGP price implies, given our marginals." rGap = rOurs - rDK
     is positive when DK has priced in more negative correlation than our
     data supports, negative when DK has priced in more positive correlation
     than our data supports.

     Returns null if required inputs are missing/invalid. */
  function evAttribution(pa, pb, rOurs, dkDecimal) {
    if (pa == null || pb == null || !dkDecimal || dkDecimal <= 1 ||
        isNaN(pa) || isNaN(pb) || isNaN(dkDecimal)) return null;
    if (rOurs == null || isNaN(rOurs)) rOurs = 0;
    var pIndep = pa * pb;
    var pJointOurs = jointFrechet(pa, pb, rOurs);
    var pJointDK = 1 / dkDecimal;
    var inv = inverseJointFrechet(pa, pb, pJointDK);
    var rDK = inv.r;
    var evTotalPct = (pJointOurs * dkDecimal - 1) * 100;
    var evFromLegsPct = (pIndep * dkDecimal - 1) * 100;
    var evFromCorrPct = (pJointOurs - pIndep) * dkDecimal * 100;
    return {
      pIndep: pIndep,
      pJointOurs: pJointOurs,
      pJointDK: pJointDK,
      rOurs: rOurs,
      rDK: rDK,
      rGap: (rDK == null) ? null : (rOurs - rDK),
      evTotalPct: evTotalPct,
      evFromLegsPct: evFromLegsPct,
      evFromCorrPct: evFromCorrPct,
      clamp: inv.clamp,
    };
  }

  return {
    americanToProb: americanToProb,
    probToAmerican: probToAmerican,
    americanToDecimal: americanToDecimal,
    decimalToAmerican: decimalToAmerican,
    jointFrechet: jointFrechet,
    inverseJointFrechet: inverseJointFrechet,
    evAttribution: evAttribution,
  };
}));
