/* teammateEv.js — candidate enumeration + EV finalization orchestrator.
   UMD: works as <script> in browser (window.teammateEv) or require() in
   Node. Depends on teammateMath.js + teammatePairLookup.js. No math,
   no data access — just glue between Phase-1 aggregates, tonight's
   lineups, FV data, and DK pricing.

   Flow:
     1. enumerateCandidates(args) returns { candidates, diagnostics }.
        Pure — no network. DK pricing happens OUT-OF-BAND; the caller
        batches the candidate list to /api/dk/find-sgps-teammate.
     2. For each DK-priced candidate, finalizeCandidate(cand, dkAm)
        returns the same record enriched with pJoint / fvCorr /
        evPct / kellyPct / qkPct via teammateMath.ivBundle.
     3. rankAndFilter(finalizedCandidates, {minEvPct}) sorts and
        threshold-filters for UI consumption.

   FV data shape (matches chunk 3 groupBatterPlayers output, re-indexed
   for fast lookup):
     fvByPlayer[playerName][statFull][threshold] = {
       over_fv: <American odds number|null>,
       under_fv: <American odds number|null>,
       over_avg_odds: <"+120 / -140" string|null>,
       under_avg_odds: <same|null>,
     }
*/
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./teammateMath.js'),
                             require('./teammatePairLookup.js'));
  } else {
    root.teammateEv = factory(root.teammateMath, root.teammatePairLookup);
  }
}(typeof self !== 'undefined' ? self : this, function (tm, tp) {

  if (!tm || !tp) {
    throw new Error('teammateEv: requires teammateMath + teammatePairLookup loaded first');
  }

  /* Convert chunk-3 groupBatterPlayers output to a fast lookup index
     keyed by player → stat → threshold. Callers with a different FV
     source can pass a pre-built index directly to enumerateCandidates. */
  function fvIndexFromExtractor(players) {
    var idx = {};
    if (!Array.isArray(players)) return idx;
    for (var i = 0; i < players.length; i++) {
      var p = players[i];
      if (!p || !p.player) continue;
      idx[p.player] = idx[p.player] || {};
      var props = p.props || [];
      for (var j = 0; j < props.length; j++) {
        var pr = props[j];
        idx[p.player][pr.stat] = idx[p.player][pr.stat] || {};
        idx[p.player][pr.stat][pr.threshold] = {
          over_fv: pr.over_fv, under_fv: pr.under_fv,
          over_avg_odds: pr.over_avg_odds, under_avg_odds: pr.under_avg_odds,
        };
      }
    }
    return idx;
  }

  /* Look up FV odds for one (player, canonical_stat, threshold, direction).
     Returns the American odds (number) or null if absent.

     Defensive ASCII-fold on the player key. Server-side OCR
     normalization in server.js already folds, but folding here too
     handles direct-call usage (smoke drivers, future code paths) and
     stays idempotent on already-folded input. The fvByPlayer index
     itself is also assumed-folded — built by fvIndexFromExtractor
     which keys off players[i].player, which the chunk-3 server-side
     normalizeBatterRows now folds. */
  function lookupFv(fvByPlayer, player, statFull, threshold, direction) {
    if (!fvByPlayer) return null;
    var fold = (typeof window !== 'undefined' && window.nameNormalize && window.nameNormalize.foldAscii) ||
               (typeof require === 'function' ? require('./nameNormalize.js').foldAscii : null);
    var key = fold ? fold(player) : (player || '');
    var pRec = fvByPlayer[key] || fvByPlayer[player];
    if (!pRec) return null;
    var sRec = pRec[statFull];
    if (!sRec) return null;
    var tRec = sRec[threshold];
    if (!tRec) return null;
    var fvKey = (direction === 'Over') ? 'over_fv' : 'under_fv';
    var v = tRec[fvKey];
    return (v == null || isNaN(v)) ? null : Number(v);
  }

  /* Enumerate every valid (pair × combo × lineup-slot) candidate from
     tonight's slate. Pure — no network calls, no mutation of inputs.

     args = {
       lineups:        [{ home_team, away_team, home_lineup: [{player, slot}],
                          away_lineup: [{player, slot}], status, game_id, ... }, ...]
                       (shape from /api/lineups)
       fvByPlayer:     {playerName: {statFull: {threshold: {over_fv, under_fv,...}}}}
       teammateData:   loaded public/data/teammate_aggregates_pooled_static.json
       slotBaselines:  loaded public/data/slot_pair_baselines.json
       mode:           'player' | 'global' | 'blended'  (default 'blended')
       minPairGames:   pair.n_total >= this  (default 30 — pair_min_total_cold)
       skipStatuses:   set of lineup statuses to skip (default {'awaiting'})
     }

     Returns { candidates, diagnostics } where diagnostics is a count
     bucket keyed by skip reason. */
  function enumerateCandidates(args) {
    var lineups       = (args && args.lineups) || [];
    var fvByPlayer    = (args && args.fvByPlayer) || {};
    var teammateData  = args && args.teammateData;
    var slotBaselines = args && args.slotBaselines;
    var mode          = (args && args.mode) || 'blended';
    var minPairGames  = args && args.minPairGames != null ? args.minPairGames : 30;
    var skipStatuses  = (args && args.skipStatuses) || { awaiting: 1 };

    if (!teammateData || !teammateData.pairs) {
      throw new Error('enumerateCandidates: teammateData.pairs required');
    }
    var comboSpec = teammateData.combo_spec || [];

    var candidates = [];
    var diag = {
      games_considered:    0,
      games_skipped_status: 0,
      pairs_considered:    0,
      pairs_no_data:       0,
      pairs_below_threshold: 0,
      /* Pairs that passed BOTH pair-existence and min-games checks — i.e.
         pairs that entered combo-level enumeration. Reconciles the
         funnel:
           pairs_considered
             = pairs_no_data + pairs_below_threshold + pairs_with_phase1_data
         Before this counter existed, the diag panel showed "Pairs with
         historical data: 0" whenever combos_emitted = 0, which was
         misleading: pairs HAD Phase-1 data, they just lost downstream at
         leg-FV checks. */
      pairs_with_phase1_data: 0,
      combos_considered:   0,
      combos_null:         0,
      combos_so_skip:      0,
      combos_hrr_skip:     0,
      combos_other_skip:   0,
      /* Hybrid-mode counter split.
           combos_no_fv_both — both legs missing FV → skipped (cannot
             compute any edge; no anchor on either side).
           combos_emitted_full_fv — both legs had FV → full-FV candidate
             emitted; edge claim is marginal + correlation.
           combos_hybrid_p1_missing / _p2_missing — exactly one side
             missing FV → hybrid candidate emitted; the missing side's
             probability is derived from DK no-vig at finalize time; edge
             claim is correlation-only.
         Pre-hybrid counters combos_no_fv_leg1 / combos_no_fv_leg2 are
         intentionally retired — they used to mean "dropped because" and
         would be misleading now that those combos actually emit. */
      combos_no_fv_both:          0,
      combos_emitted_full_fv:     0,
      combos_hybrid_p1_missing:   0,
      combos_hybrid_p2_missing:   0,
      combos_emitted:      0,
    };

    for (var gi = 0; gi < lineups.length; gi++) {
      var game = lineups[gi];
      if (!game) continue;
      if (skipStatuses[game.status]) { diag.games_skipped_status++; continue; }
      diag.games_considered++;

      var sides = [
        { team: game.home_team, lineup: game.home_lineup || [] },
        { team: game.away_team, lineup: game.away_lineup || [] },
      ];

      for (var si = 0; si < sides.length; si++) {
        var team = sides[si].team, lineup = sides[si].lineup;
        if (!team || lineup.length < 2) continue;

        // Unique unordered pairs of batters in this lineup
        for (var i = 0; i < lineup.length; i++) {
          for (var j = i + 1; j < lineup.length; j++) {
            var a = lineup[i], b = lineup[j];
            if (!a || !b || !a.player || !b.player) continue;
            diag.pairs_considered++;

            var pair = tp.findPair(teammateData, a.player, b.player, team);
            if (!pair) { diag.pairs_no_data++; continue; }
            if ((pair.n_total || 0) < minPairGames) { diag.pairs_below_threshold++; continue; }
            diag.pairs_with_phase1_data++;

            // Order tonight's slots to match pair.p1/p2.
            // Both sides are ASCII-folded: pair.p1/p2 were folded at
            // dataset build time; a.player/b.player are folded at the
            // lineup endpoint boundary (server.js). The displayName
            // fields preserve the original diacritic form for UI.
            var p1 = pair.p1, p2 = pair.p2;
            var slotP1, slotP2, p1Display, p2Display;
            if (a.player === p1 && b.player === p2) {
              slotP1 = a.slot; slotP2 = b.slot;
              p1Display = a.displayName || a.player;
              p2Display = b.displayName || b.player;
            } else if (a.player === p2 && b.player === p1) {
              slotP1 = b.slot; slotP2 = a.slot;
              p1Display = b.displayName || b.player;
              p2Display = a.displayName || a.player;
            } else {
              continue;  // post-fold this should essentially never fire
            }
            var tonightSlots = [slotP1, slotP2];
            var conf = tp.slotMatchConfidence(pair, tonightSlots);

            for (var ci = 0; ci < comboSpec.length; ci++) {
              diag.combos_considered++;
              var combo = tp.comboView(pair, ci, comboSpec);
              if (!combo) { diag.combos_null++; continue; }

              var t1 = tm.shortLegToFull(combo.leg1);
              var t2 = tm.shortLegToFull(combo.leg2);
              if (t1.skipped || t2.skipped) {
                var reason = (t1.reason || t2.reason || '').toLowerCase();
                if (reason.indexOf('strikeout') >= 0) diag.combos_so_skip++;
                else if (reason.indexOf('multi-stat') >= 0) diag.combos_hrr_skip++;
                else diag.combos_other_skip++;
                continue;
              }

              var fv1 = lookupFv(fvByPlayer, p1, t1.statFull, t1.threshold, t1.direction);
              var fv2 = lookupFv(fvByPlayer, p2, t2.statFull, t2.threshold, t2.direction);

              /* Hybrid mode (see commits A-C on claude/teammate-hybrid-plus-fixes).
                 If BOTH legs have FV: full-FV candidate (unchanged
                 behavior). If exactly ONE leg has FV: hybrid candidate —
                 the missing side gets DK no-vig fair computed at
                 finalizeCandidate time once per-leg DK prices are in
                 hand. If neither has FV: no anchor, skip. */
              if (fv1 == null && fv2 == null) {
                diag.combos_no_fv_both++;
                continue;
              }

              var candType, missingLeg;
              if (fv1 != null && fv2 != null) {
                candType = 'full_fv';
                missingLeg = null;
                diag.combos_emitted_full_fv++;
              } else if (fv1 == null) {
                candType = 'hybrid';
                missingLeg = 'p1';
                diag.combos_hybrid_p1_missing++;
              } else {
                candType = 'hybrid';
                missingLeg = 'p2';
                diag.combos_hybrid_p2_missing++;
              }

              var res = tp.resolvePairR(pair, combo, {
                mode: mode,
                targetSlots: tonightSlots,
                slotBaselines: slotBaselines,
                teammateData: teammateData,
              });

              candidates.push({
                // Identity
                pair_key: p1 + '||' + p2 + '||' + team,
                team: team,
                game_id: game.game_id,
                game_label: (game.away_team_abbr || '?') + ' @ ' + (game.home_team_abbr || '?'),
                lineup_status: game.status,
                // Players + slots
                // p1 / p2 are ASCII canonical (used as join keys for
                // any downstream re-lookup); p1_display / p2_display
                // preserve the original diacritic forms for UI render.
                p1: p1, p2: p2,
                p1_display: p1Display, p2_display: p2Display,
                p1_slot: slotP1, p2_slot: slotP2,
                tonight_slots: tonightSlots,
                most_common_slots: pair.most_common_slots || null,
                n_total: pair.n_total || 0,
                // Combo
                combo_idx: ci,
                leg1_short: combo.leg1, leg2_short: combo.leg2,
                leg1_full:  t1.leg,     leg2_full:  t2.leg,
                direction1: t1.direction, direction2: t2.direction,
                stat1_full: t1.statFull, stat2_full: t2.statFull,
                thresh1:    t1.threshold, thresh2:   t2.threshold,
                // Hit rates from Phase 1
                hit1: combo.hit1, hit2: combo.hit2, both_hit: combo.both,
                // FV (null entries indicate the leg needs no-vig at finalize)
                fv_p1: fv1, fv_p2: fv2,
                p_leg1: fv1 != null ? tm.americanToProb(fv1) : null,
                p_leg2: fv2 != null ? tm.americanToProb(fv2) : null,
                // Hybrid fields — populated downstream in finalizeCandidate
                type: candType,
                missing_leg: missingLeg,  // null | 'p1' | 'p2'
                novig_source: null,       // populated by finalize when type='hybrid'
                // Correlation (mode-resolved)
                mode: mode,
                r_binary: res.r_binary,
                r_margin: res.r_margin,
                r_binary_player: res.r_binary_player,
                r_binary_global: res.r_binary_global,
                r_margin_player: res.r_margin_player,
                r_margin_global: res.r_margin_global,
                w_player: res.w_player,
                fallback: res.fallback,
                // Confidence
                slot_match_confidence: conf,
              });
              diag.combos_emitted++;
            }
          }
        }
      }
    }

    return { candidates: candidates, diagnostics: diag };
  }

  /* Given a candidate + a DK SGP price (American odds number, e.g. +250 or
     -120), produce the EV-finalized record via teammateMath.ivBundle.
     Returns a NEW object (shallow-copied from cand + bundle fields).
     If dkAmericanOdds is null/undefined, bundle fields are FV-only
     (no EV%, no Kelly). */
  /* DK two-way no-vig fair probability for one leg. Returns null when
     no-vig can't be computed (one side missing on DK, implausible
     round-trip bounds, etc.) — caller's hybrid path should skip the
     candidate in that case. */
  function computeNoVigFair(americanOver, americanUnder, direction) {
    if (americanOver == null || americanUnder == null) return null;
    var pOver  = tm.americanToProb(americanOver);
    var pUnder = tm.americanToProb(americanUnder);
    if (pOver == null || pUnder == null) return null;
    var total = pOver + pUnder;
    if (!isFinite(total) || total <= 0) return null;
    var pOverFair = pOver / total;
    /* Sanity bounds: DK occasionally quotes extreme long-tails (e.g.
       Over 2.5 Hits at +3300) where the over/under pair's no-vig
       doesn't reflect a real market-consensus probability. Drop those
       rather than propagate a number we don't trust into jointFrechet. */
    if (pOverFair < 0.02 || pOverFair > 0.98) return null;
    return (direction === 'Over') ? pOverFair : (1 - pOverFair);
  }

  function finalizeCandidate(cand, dkAmericanOdds, dkLegPrices) {
    /* Two entry modes:
       1. Full-FV candidate (cand.type === 'full_fv'): both p_leg1 and
          p_leg2 are already populated from the FV sheet. Existing
          path — no-vig is ignored even if dkLegPrices is provided.
       2. Hybrid candidate (cand.type === 'hybrid'): exactly one of
          p_leg1 / p_leg2 is null. Compute no-vig on the missing side
          from DK's Over/Under pair on that leg. If no-vig fails (no
          opposite-direction DK price, or implausible bounds), return
          null so the caller can skip the candidate. */
    var p_leg1 = cand.p_leg1;
    var p_leg2 = cand.p_leg2;
    var novig_source = null;

    if (cand.type === 'hybrid') {
      if (!dkLegPrices) return null;
      var missing = cand.missing_leg;  // 'p1' or 'p2'
      var side = (missing === 'p1') ? 'a' : 'b';
      var over  = dkLegPrices['leg_' + side + '_over_american'];
      var under = dkLegPrices['leg_' + side + '_under_american'];
      var dir   = (missing === 'p1') ? cand.direction1 : cand.direction2;
      var pFair = computeNoVigFair(over, under, dir);
      if (pFair == null) return null;
      if (missing === 'p1') p_leg1 = pFair; else p_leg2 = pFair;
      novig_source = {
        missing:      missing,
        leg_over_american:  over,
        leg_under_american: under,
        direction:    dir,
        novig_fair_prob: pFair,
      };
    }

    var dkDec = (dkAmericanOdds == null) ? null : tm.americanToDecimal(dkAmericanOdds);
    var bundle = tm.ivBundle(p_leg1, p_leg2, cand.r_binary, dkDec);
    var out = {};
    for (var k in cand) if (Object.prototype.hasOwnProperty.call(cand, k)) out[k] = cand[k];
    out.dk_american = (dkAmericanOdds == null) ? null : Number(dkAmericanOdds);
    out.dk_decimal  = dkDec;
    out.novig_source = novig_source;
    /* For hybrid, surface the no-vig-filled probability back onto
       p_leg1 / p_leg2 so downstream consumers (card renderer, AI
       Insights prompt) see the actual probability the Fréchet join
       used, not the original null. The raw FV American odds
       (cand.fv_p1 / cand.fv_p2) stay null on the missing side so the
       card can render "—" for FV and "X%" for the no-vig. */
    out.p_leg1 = p_leg1;
    out.p_leg2 = p_leg2;
    if (bundle) {
      out.p_joint         = bundle.pJoint;
      out.fv_corr_american = bundle.fvCorrAmerican;
      out.ev_pct          = bundle.evPct;
      out.kelly_pct       = bundle.kellyPct;
      out.qk_pct          = bundle.qkPct;
    } else {
      out.p_joint = null; out.fv_corr_american = null;
      out.ev_pct = null;  out.kelly_pct = null; out.qk_pct = null;
    }
    return out;
  }

  /* Sort by ev_pct descending, keep only ev_pct >= minEvPct. Candidates
     whose ev_pct is null (no DK price) are excluded regardless of
     threshold — callers that want "show all" should skip this filter. */
  function rankAndFilter(finalizedCandidates, opts) {
    opts = opts || {};
    var minEv = opts.minEvPct != null ? opts.minEvPct : 3;
    var out = [];
    for (var i = 0; i < finalizedCandidates.length; i++) {
      var c = finalizedCandidates[i];
      if (c.ev_pct == null || isNaN(c.ev_pct)) continue;
      if (c.ev_pct < minEv) continue;
      out.push(c);
    }
    out.sort(function (a, b) { return b.ev_pct - a.ev_pct; });
    return out;
  }

  return {
    fvIndexFromExtractor: fvIndexFromExtractor,
    lookupFv:             lookupFv,
    enumerateCandidates:  enumerateCandidates,
    finalizeCandidate:    finalizeCandidate,
    rankAndFilter:        rankAndFilter,
  };
}));
