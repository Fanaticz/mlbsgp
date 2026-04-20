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

  return {
    americanToProb: americanToProb,
    probToAmerican: probToAmerican,
    americanToDecimal: americanToDecimal,
    decimalToAmerican: decimalToAmerican,
    jointFrechet: jointFrechet,
  };
}));
