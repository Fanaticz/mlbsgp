#!/usr/bin/env node
/* Chunk 4 smoke-test driver for the teammate EV pipeline.
 *
 * Pure Node-side validation — no browser, no UI. Does the following:
 *   1. Loads TEAMMATE_DATA + SLOT_BASELINES from public/data/
 *   2. Fetches tonight's lineups from a running server's /api/lineups
 *   3. Builds synthetic FV data (flat per-stat placeholders so the
 *      enumeration produces results even with OCR deferred)
 *   4. Calls teammateEv.enumerateCandidates for 3-5 games
 *   5. Batches the candidate list (top N by |r_binary|) to
 *      /api/dk/find-sgps-teammate for real DK SGP prices
 *   6. Runs teammateEv.finalizeCandidate on each priced candidate
 *   7. Reports top 10 by EV% with full provenance
 *   8. Hand-verifies Fréchet joint math on one high-EV candidate
 *
 * Requirements:
 *   - Server running with /api/lineups and /api/dk/find-sgps-teammate
 *     (no ANTHROPIC_API_KEY needed for this smoke — OCR not exercised)
 *
 * Usage:
 *   node scripts/smoke_teammate_ev.js [baseUrl] [date] [maxGames]
 *     baseUrl    default http://127.0.0.1:3300
 *     date       default today (YYYY-MM-DD)
 *     maxGames   default 4
 */

const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:3300';
const DATE = process.argv[3] || new Date().toISOString().slice(0, 10);
const MAX_GAMES = parseInt(process.argv[4] || '4', 10);

const tm = require(path.join(__dirname, '..', 'public', 'utils', 'teammateMath.js'));
const te = require(path.join(__dirname, '..', 'public', 'utils', 'teammateEv.js'));
const sgpMath = require(path.join(__dirname, '..', 'public', 'utils', 'sgpMath.js'));

/* Synthetic per-stat FV bank. Chosen as realistic-ish baseline implied
   probabilities so EV comparisons surface signal — not just flat +100. */
const SYNTH_FV = {
  'Hits':         { 0.5:  110, 1.5: 260, 2.5:  700 },
  'Runs':         { 0.5:  180, 1.5: 500 },
  'RBIs':         { 0.5:  175, 1.5: 480 },
  'Home Runs':    { 0.5:  400 },
  'Total Bases':  { 1.5:  180, 2.5: 400, 3.5: 800 },
  'Walks':        { 0.5:  250 },
  'Stolen Bases': { 0.5:  400 },
  'Singles':      { 0.5:  120 },
  'Doubles':      { 0.5:  320 },
  'Triples':      { 0.5: 1600 },
};
function synthUnderFor(overAmerican) {
  /* Round-trip: implied prob → 1-prob → back to American, with a mild
     juice (multiply decimal by 0.95) so Under isn't a perfect mirror. */
  var p = sgpMath.americanToProb(overAmerican);
  if (p == null) return null;
  var q = 1 - p;
  return sgpMath.probToAmerican(q) || -120;
}

function buildSyntheticFvByPlayer(lineups) {
  var fv = {};
  var names = new Set();
  for (var g of lineups) {
    for (var p of (g.home_lineup || [])) names.add(p.player);
    for (var p of (g.away_lineup || [])) names.add(p.player);
  }
  for (var name of names) {
    fv[name] = {};
    for (var stat of Object.keys(SYNTH_FV)) {
      fv[name][stat] = {};
      for (var thresh of Object.keys(SYNTH_FV[stat])) {
        var over = SYNTH_FV[stat][thresh];
        fv[name][stat][thresh] = {
          over_fv: over,
          under_fv: synthUnderFor(over),
          over_avg_odds: null,
          under_avg_odds: null,
        };
      }
    }
  }
  return fv;
}

async function fetchJson(url, init) {
  var r = await fetch(url, init || {});
  if (!r.ok) throw new Error(url + ' → HTTP ' + r.status);
  return await r.json();
}

async function main() {
  console.log('=== Chunk 4 smoke test — teammate EV pipeline ===');
  console.log('base=' + BASE + '  date=' + DATE + '  maxGames=' + MAX_GAMES);
  console.log('');

  // ---- 1. Load dataset files ----
  var t0 = Date.now();
  var TD = require(path.join(__dirname, '..', 'public', 'data', 'teammate_aggregates_pooled_static.json'));
  var SB = require(path.join(__dirname, '..', 'public', 'data', 'slot_pair_baselines.json'));
  console.log('[1] loaded TEAMMATE_DATA (pairs=' + Object.keys(TD.pairs).length +
              ', combo_spec=' + TD.combo_spec.length + ') + SLOT_BASELINES (' +
              ((Date.now() - t0) / 1000).toFixed(1) + 's)');

  // ---- 2. Lineups ----
  var lineupsResp = await fetchJson(BASE + '/api/lineups?date=' + DATE);
  var allGames = lineupsResp.games || [];
  var games = allGames.filter(function (g) { return g.status !== 'awaiting'; }).slice(0, MAX_GAMES);
  console.log('[2] lineups: ' + allGames.length + ' total, ' + games.length + ' used (after status filter + cap)');
  for (var g of games) {
    console.log('     ' + (g.away_team_abbr || '?') + ' @ ' + (g.home_team_abbr || '?') + '  [' + g.status + ']');
  }
  console.log('');

  // ---- 3. Synthetic FV ----
  var fv = buildSyntheticFvByPlayer(games);
  console.log('[3] synthetic FV built for ' + Object.keys(fv).length + ' players ('
              + Object.keys(SYNTH_FV).length + ' stats × mixed thresholds)');
  console.log('');

  // ---- 4. Enumerate ----
  t0 = Date.now();
  var enumRes = te.enumerateCandidates({
    lineups: games, fvByPlayer: fv,
    teammateData: TD, slotBaselines: SB,
    mode: 'blended', minPairGames: 30,
  });
  console.log('[4] enumerated ' + enumRes.candidates.length + ' candidates (' +
              ((Date.now() - t0) / 1000).toFixed(1) + 's)');
  console.log('    diagnostics:');
  for (var k of Object.keys(enumRes.diagnostics)) {
    console.log('      ' + k.padEnd(25) + ' ' + enumRes.diagnostics[k]);
  }
  console.log('');

  if (!enumRes.candidates.length) {
    console.log('no candidates — bailing out');
    process.exit(0);
  }

  // ---- 5. DK pricing (batched, top-by-|r| to stay under deadline) ----
  /* We cap the DK batch because pricing 1000s of candidates would blow
     past the 110s deadline in dk_api.py. Rank by |r_binary| so the
     batch emphasizes candidates with the most correlation signal —
     that's where EV edges (positive OR negative) live. */
  var ranked = enumRes.candidates.slice().sort(function (a, b) {
    var ra = Math.abs(a.r_binary || 0), rb = Math.abs(b.r_binary || 0);
    return rb - ra;
  });
  var DK_BATCH_CAP = 60;
  var batch = ranked.slice(0, DK_BATCH_CAP);
  var dkPayload = batch.map(function (c, i) {
    return {
      id: 'c' + i,
      team: c.team,
      player_a: c.p1, leg_a: c.leg1_full,
      player_b: c.p2, leg_b: c.leg2_full,
    };
  });
  console.log('[5] DK pricing ' + batch.length + ' candidates (capped to top ' + DK_BATCH_CAP + ' by |r|) ...');
  t0 = Date.now();
  var dkResp = await fetchJson(BASE + '/api/dk/find-sgps-teammate', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ candidates: dkPayload }),
  });
  console.log('    DK call completed in ' + ((Date.now() - t0) / 1000).toFixed(1) + 's; truncated=' + !!dkResp.truncated);
  var priceByCid = {};
  var matchedDk = 0, unmatchedDk = 0;
  for (var r of (dkResp.results || [])) {
    if (r.matched) { priceByCid[r.id] = r; matchedDk++; }
    else { unmatchedDk++; }
  }
  console.log('    matched=' + matchedDk + ' / unmatched=' + unmatchedDk);
  console.log('');

  // ---- 6. Finalize ----
  var finalized = [];
  for (var i = 0; i < batch.length; i++) {
    var cand = batch[i];
    var dk = priceByCid['c' + i];
    if (!dk) continue;
    /* DK returns American odds as a string like "+325" or "-120". Strip
       the leading + for Number() — browser fetch already does this for
       most cases but be defensive. */
    var dkAm = Number(String(dk.dk_odds).replace(/^\+/, ''));
    if (!isFinite(dkAm)) continue;
    finalized.push(te.finalizeCandidate(cand, dkAm));
  }
  console.log('[6] finalized ' + finalized.length + ' candidates with DK price');

  // ---- 7. Rank + report top 10 ----
  var MIN_EV = -100; /* smoke report: show top 10 regardless of threshold
                       so we can eyeball the tail. Real UI default 3%. */
  var top10 = te.rankAndFilter(finalized, { minEvPct: MIN_EV }).slice(0, 10);
  console.log('[7] top 10 by EV%:');
  console.log('');
  for (var i = 0; i < top10.length; i++) {
    var c = top10[i];
    console.log(('#' + (i + 1)).padEnd(4) + c.p1 + ' × ' + c.p2 + '   [' + c.team + ']');
    console.log('      slots ' + c.tonight_slots[0] + '_' + c.tonight_slots[1] +
                '  most_common=' + JSON.stringify(c.most_common_slots) +
                '  confidence=' + c.slot_match_confidence.level + ' (n=' + c.slot_match_confidence.n + ')');
    console.log('      combo#' + c.combo_idx + ': ' + c.leg1_full + '  +  ' + c.leg2_full);
    console.log('      FV:   p1=' + (c.fv_p1 > 0 ? '+' : '') + c.fv_p1 +
                '  p2=' + (c.fv_p2 > 0 ? '+' : '') + c.fv_p2 +
                '  (p1=' + c.p_leg1.toFixed(4) + ', p2=' + c.p_leg2.toFixed(4) + ')');
    console.log('      r_binary=' + c.r_binary.toFixed(4) +
                '  (player=' + (c.r_binary_player == null ? 'null' : c.r_binary_player.toFixed(4)) +
                ', global=' + (c.r_binary_global == null ? 'null' : c.r_binary_global.toFixed(4)) +
                ', w_player=' + c.w_player.toFixed(3) + ')');
    console.log('      DK: ' + (c.dk_american > 0 ? '+' : '') + c.dk_american +
                '  FVcorr: ' + (c.fv_corr_american > 0 ? '+' : '') + c.fv_corr_american +
                '  pJoint=' + c.p_joint.toFixed(4) +
                '  EV%=' + c.ev_pct.toFixed(2) +
                '  QK=' + c.qk_pct.toFixed(2) + 'u');
    console.log('');
  }

  // ---- 8. Math spot-check on #1 ----
  if (top10.length) {
    var c = top10[0];
    console.log('[8] math spot-check on #1 (Fréchet joint, hand-computed):');
    var pab_indep = c.p_leg1 * c.p_leg2;
    var maxBound  = Math.min(c.p_leg1, c.p_leg2);
    var handJoint = c.r_binary >= 0
      ? pab_indep + c.r_binary * (maxBound - pab_indep)
      : pab_indep + c.r_binary * (pab_indep - Math.max(0, c.p_leg1 + c.p_leg2 - 1));
    var dkDec = sgpMath.americanToDecimal(c.dk_american);
    var handEv = (handJoint * dkDec - 1) * 100;
    console.log('    p1=' + c.p_leg1.toFixed(6) + ' p2=' + c.p_leg2.toFixed(6) + ' r=' + c.r_binary.toFixed(6));
    console.log('    pab_indep = p1·p2             = ' + pab_indep.toFixed(6));
    console.log('    upper     = min(p1,p2)         = ' + maxBound.toFixed(6));
    console.log('    jointFr   = pab + r·(upper-pab) = ' + handJoint.toFixed(6));
    console.log('    module    pJoint              = ' + c.p_joint.toFixed(6));
    console.log('    diff      abs(module-hand)    = ' + Math.abs(handJoint - c.p_joint).toExponential(3));
    console.log('');
    console.log('    DK dec   = ' + dkDec.toFixed(6));
    console.log('    hand EV% = (pJoint·dkDec − 1)·100 = ' + handEv.toFixed(4));
    console.log('    module EV%                        = ' + c.ev_pct.toFixed(4));
    console.log('    diff                              = ' + Math.abs(handEv - c.ev_pct).toExponential(3));
    var mathOk = Math.abs(handJoint - c.p_joint) < 1e-9 && Math.abs(handEv - c.ev_pct) < 1e-6;
    console.log('');
    console.log(mathOk
      ? '    ✅ Fréchet joint + EV% reconstruct from inputs exactly.'
      : '    ❌ MISMATCH — investigate');
  }

  console.log('');
  console.log('=== smoke done ===');
}

main().catch(function (e) { console.error('FATAL:', e); process.exit(1); });
