/* teammatePairLookup.js — Phase-1 aggregator data access + shrinkage.
   UMD: works as <script> in browser (window.teammatePairLookup) or
   require() in Node. Depends on teammateMath.js (which depends on
   sgpMath.js).

   Scope (intentionally narrow):
     - findPair (handles both (a,b,team) and (b,a,team) key orderings)
     - comboView / baselineForCombo / slotUsage lookups
     - resolvePairR — Phase-2-ready shrinkage: player value blended
       toward slot-pair baseline at a weight of n_total / (n_total + k_pair)
       when n_total >= blend_min_games_pair, else fallback to baseline.
       Accepts tonightSlots so shrinkage targets the RIGHT slot-pair
       baseline, not pair.most_common_slots. This is the Phase-2 payoff.
     - slotMatchConfidence — classifies tonight's slots against the
       pair's slot_usage histogram into {high, medium, low, none}.

   No enumeration, no EV math, no orchestration — those live in
   teammateEv.js. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./teammateMath.js'));
  } else {
    root.teammatePairLookup = factory(root.teammateMath);
  }
}(typeof self !== 'undefined' ? self : this, function (tm) {

  if (!tm) {
    throw new Error('teammatePairLookup: teammateMath is required (load /utils/teammateMath.js first)');
  }

  /* ========== Pair lookup ==========
     TEAMMATE_DATA.pairs is keyed "<p1>||<p2>||<team>". The p1/p2
     ordering inside the key is NOT alphabetical (verified empirically:
     ~50/50 split). For a random (a, b) input from a lineup, we try
     both orderings before giving up. */
  function findPair(teammateData, playerA, playerB, team) {
    if (!teammateData || !teammateData.pairs) return null;
    var pairs = teammateData.pairs;
    var kAB = playerA + '||' + playerB + '||' + team;
    if (pairs[kAB]) return pairs[kAB];
    var kBA = playerB + '||' + playerA + '||' + team;
    if (pairs[kBA]) return pairs[kBA];
    return null;
  }

  /* Default shrinkage constants — match build_teammate_aggregates.py
     and index.html's resolvePairR. Overridable via teammateData metadata
     (_tmKPair / _tmBlendMin equivalents). */
  var K_PAIR_DEFAULT    = 80;
  var BLEND_MIN_DEFAULT = 30;

  function kPair(teammateData) {
    return (teammateData && teammateData.k_pair) || K_PAIR_DEFAULT;
  }
  function blendMin(teammateData) {
    return (teammateData && teammateData.blend_min_games_pair) || BLEND_MIN_DEFAULT;
  }

  /* ========== Combo view ==========
     pair.combos_2[idx] is a tuple [r_binary, r_margin, hit1, hit2, both]
     aligned to teammateData.combo_spec[idx] = [leg1_short, leg2_short].
     Null/skipped combos (filter didn't survive emission) return null. */
  function comboView(pair, idx, comboSpec) {
    var raw = pair && pair.combos_2 && pair.combos_2[idx];
    if (!raw) return null;
    var legs = (comboSpec && comboSpec[idx]) || [null, null];
    var p1 = tm.parseLeg(legs[0]);
    var p2 = tm.parseLeg(legs[1]);
    return {
      idx:      idx,
      leg1:     legs[0], leg2: legs[1],
      stat1:    p1 ? p1.stat : null,
      stat2:    p2 ? p2.stat : null,
      thresh1:  p1 ? p1.threshold : null,
      thresh2:  p2 ? p2.threshold : null,
      dir1:     p1 ? p1.direction : null,
      dir2:     p2 ? p2.direction : null,
      r_binary: raw[0],
      r_margin: raw[1],
      hit1:     raw[2],
      hit2:     raw[3],
      both:     raw[4],
    };
  }

  /* ========== Baseline lookup ==========
     slotBaselines.slot_pairs["{s1}_{s2}"].combos_2 is a list of
     { leg1, leg2, r_binary, r_margin, ... } objects. Match on exact
     (leg1, leg2) to the combo being resolved. */
  function baselineForCombo(slotBaselines, targetSlots, combo) {
    if (!slotBaselines || !targetSlots || !combo) return null;
    var key = targetSlots[0] + '_' + targetSlots[1];
    var sp = slotBaselines.slot_pairs && slotBaselines.slot_pairs[key];
    if (!sp || !sp.combos_2) return null;
    for (var i = 0; i < sp.combos_2.length; i++) {
      var c = sp.combos_2[i];
      if (c && c.leg1 === combo.leg1 && c.leg2 === combo.leg2) return c;
    }
    return null;
  }

  /* ========== Core resolver ==========
     Phase-2-ready: targetSlots is a first-class arg so the caller can
     pass tonight's actual (p1_slot, p2_slot) instead of falling back
     to pair.most_common_slots. mode ∈ {'player','global','blended'}.

     Returns { r_binary, r_margin, baseline, w_player, fallback,
               r_binary_player, r_binary_global, r_margin_player,
               r_margin_global }
       - r_binary / r_margin: resolved value under the active mode
       - baseline: slot-pair baseline combo used (null in player mode)
       - w_player: weight applied to specific-pair data (0..1)
       - fallback: true when blended collapsed to pure baseline because
                   n_total < blend_min or the baseline was missing
       - the *_player / *_global fields are kept on the response so
         EV cards + AI Insights can show provenance without a second
         lookup.

     Invariant mirrored from index.html:727-763 — same math, same
     constants (sourced from teammateData metadata when present). */
  function resolvePairR(pair, combo, opts) {
    opts = opts || {};
    var mode          = opts.mode || 'player';
    var slotBaselines = opts.slotBaselines || null;
    var teammateData  = opts.teammateData  || null;
    var targetSlots   = opts.targetSlots   || (pair && pair.most_common_slots) || null;

    if (!combo) {
      return { r_binary: null, r_margin: null, baseline: null,
               w_player: 0, fallback: false,
               r_binary_player: null, r_binary_global: null,
               r_margin_player: null, r_margin_global: null };
    }

    var rbPlayer = combo.r_binary;
    var rmPlayer = combo.r_margin;

    if (mode === 'player') {
      return { r_binary: rbPlayer, r_margin: rmPlayer,
               baseline: null, w_player: 1, fallback: false,
               r_binary_player: rbPlayer, r_binary_global: null,
               r_margin_player: rmPlayer, r_margin_global: null };
    }

    var base = baselineForCombo(slotBaselines, targetSlots, combo);
    var rbGlobal = base ? base.r_binary : null;
    var rmGlobal = base ? base.r_margin : null;

    if (mode === 'global') {
      return { r_binary: rbGlobal == null ? 0 : rbGlobal,
               r_margin: rmGlobal == null ? 0 : rmGlobal,
               baseline: base, w_player: 0, fallback: !base,
               r_binary_player: rbPlayer, r_binary_global: rbGlobal,
               r_margin_player: rmPlayer, r_margin_global: rmGlobal };
    }

    /* blended */
    var nTotal = (pair && pair.n_total) || 0;
    var minN   = blendMin(teammateData);
    if (!base || nTotal < minN) {
      return { r_binary: rbGlobal == null ? 0 : rbGlobal,
               r_margin: rmGlobal == null ? 0 : rmGlobal,
               baseline: base, w_player: 0, fallback: true,
               r_binary_player: rbPlayer, r_binary_global: rbGlobal,
               r_margin_player: rmPlayer, r_margin_global: rmGlobal };
    }
    var k = kPair(teammateData);
    var w = nTotal / (nTotal + k);
    function blend(a, b) {
      if (a == null && b == null) return null;
      if (a == null) return b;
      if (b == null) return a;
      return w * a + (1 - w) * b;
    }
    return {
      r_binary: blend(rbPlayer, rbGlobal),
      r_margin: blend(rmPlayer, rmGlobal),
      baseline: base, w_player: w, fallback: false,
      r_binary_player: rbPlayer, r_binary_global: rbGlobal,
      r_margin_player: rmPlayer, r_margin_global: rmGlobal,
    };
  }

  /* ========== Slot-match confidence ==========
     Per Phase 2 chunk 4 spec:
       high    n >= 20    (pair has meaningful history at these slots)
       medium  5 <= n < 20
       low     1 <= n < 5 (tonight's config unusual for this pair)
       none    key absent (pair has never batted at these slots together)

     Does NOT change EV math. Returned alongside each candidate so
     chunks 5/6 can surface the distinction on cards + AI Insights.
     tonightSlots is [p1_slot, p2_slot] in pair.p1/p2 ordering — the
     same ordering used by pair.slot_usage keys. */
  function slotMatchConfidence(pair, tonightSlots) {
    if (!pair || !pair.slot_usage || !tonightSlots || tonightSlots.length !== 2) {
      return { level: 'none', n: 0, key: null };
    }
    var key = tonightSlots[0] + '_' + tonightSlots[1];
    var n = pair.slot_usage[key] || 0;
    var level;
    if (n >= 20)      level = 'high';
    else if (n >= 5)  level = 'medium';
    else if (n >= 1)  level = 'low';
    else              level = 'none';
    return { level: level, n: n, key: key };
  }

  return {
    findPair:            findPair,
    comboView:           comboView,
    baselineForCombo:    baselineForCombo,
    resolvePairR:        resolvePairR,
    slotMatchConfidence: slotMatchConfidence,
    kPair:               kPair,
    blendMin:            blendMin,
    K_PAIR_DEFAULT:      K_PAIR_DEFAULT,
    BLEND_MIN_DEFAULT:   BLEND_MIN_DEFAULT,
  };
}));
