/* teammateEvTab.js — Teammate +EV tab wiring (chunk 5b).
   Scope for this file so far:
     - tab state (lineups, FV data, candidates, filter values, mode)
     - lineup load + status bar render
     - FV sheet upload → /api/extract-batter → fvIndex
     - synthetic-FV fallback (for smoke testing while OCR is deferred)
     - pipeline invocation (enumerate → DK price → finalize)
     - filter/mode stubs (handlers exist but render is a placeholder
       that dumps candidate count + top 3 until chunk 5c lands the
       card renderer)

   Depends on the already-loaded utils: teammateMath, teammatePairLookup,
   teammateEv, sgpMath — all exposed on window by their UMD shims. */
(function () {
  'use strict';

  if (!window.teammateEv || !window.teammatePairLookup || !window.teammateMath) {
    console.error('teammateEvTab: module dependencies not loaded');
    return;
  }
  var TE = window.teammateEv;
  var TP = window.teammatePairLookup;
  var TM = window.teammateMath;

  /* ---------------- state ---------------- */
  var S = {
    activated:      false,   // onActivate has fired at least once
    lineups:        null,    // /api/lineups response
    fvIndex:        null,    // { player: { stat: { thresh: {over_fv,under_fv,...} } } }
    fvSource:       null,    // "ocr" | "synthetic" | null
    candidatesRaw:  [],      // output of enumerateCandidates (pre-DK)
    candidatesFull: [],      // after finalizeCandidate with DK prices
    dkMissing:      [],      // candidate ids that didn't get a DK match
    mode:           'blended',
    filters: {
      minEvPct: 3,
      minN:     30,
      conf:     'all',       // 'all' | 'med' | 'high'
      team:     '',
      game:     '',
      confirmedOnly: false,
    },
  };

  /* Synthetic per-stat FV bank — same shape used by scripts/smoke_teammate_ev.js.
     Lets users exercise the pipeline while chunk 3 OCR is deferred. */
  var SYNTH_FV = {
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

  /* ---------------- DOM helpers ---------------- */
  function $(id) { return document.getElementById(id); }
  function setStatus(text, kind) {
    var el = $('tmevStatus');
    if (!el) return;
    var color = kind === 'err' ? 'var(--red)' : kind === 'ok' ? 'var(--ac)' : 'var(--ac2)';
    el.innerHTML = text == null ? '' : '<span style="color:' + color + '">' + text + '</span>';
  }

  /* ---------------- lineup load + status bar ---------------- */
  function fmtDateYMD(d) { return d.toISOString().slice(0, 10); }

  function renderLineupStatus() {
    var bar = $('tmevLineupStatus');
    var stamp = $('tmevLineupStamp');
    if (!bar || !stamp) return;
    if (!S.lineups) {
      bar.textContent = 'Loading tonight\'s lineups...';
      stamp.textContent = '';
      return;
    }
    var counts = { confirmed: 0, projected: 0, awaiting: 0 };
    (S.lineups.games || []).forEach(function (g) {
      if (counts[g.status] != null) counts[g.status]++;
    });
    bar.innerHTML =
      '<span style="color:var(--ac);font-weight:600">' + counts.confirmed + ' confirmed</span>' +
      ' &nbsp;·&nbsp; <span style="color:var(--ac2)">' + counts.projected + ' projected</span>' +
      ' &nbsp;·&nbsp; <span style="color:var(--mu)">' + counts.awaiting + ' awaiting</span>' +
      ' &nbsp;·&nbsp; <span style="color:var(--mu)">' + (S.lineups.games || []).length + ' games</span>';
    var ts = S.lineups.lineups_confirmed_at ? new Date(S.lineups.lineups_confirmed_at).toLocaleTimeString() : '';
    stamp.textContent = ts ? ' stamped ' + ts : '';
  }

  function populateGameAndTeamFilters() {
    var teamSel = $('tmevTeam'), gameSel = $('tmevGame');
    if (!teamSel || !gameSel || !S.lineups) return;
    var teams = new Set(), games = [];
    (S.lineups.games || []).forEach(function (g) {
      if (g.home_team) teams.add(g.home_team);
      if (g.away_team) teams.add(g.away_team);
      games.push({ id: g.game_id, label: (g.away_team_abbr || '?') + ' @ ' + (g.home_team_abbr || '?') });
    });
    teamSel.innerHTML = '<option value="">All teams</option>' +
      [...teams].sort().map(function (t) { return '<option value="' + t + '">' + t + '</option>'; }).join('');
    gameSel.innerHTML = '<option value="">All games</option>' +
      games.map(function (g) { return '<option value="' + g.id + '">' + g.label + '</option>'; }).join('');
  }

  async function loadLineups() {
    try {
      var date = fmtDateYMD(new Date());
      var r = await fetch('/api/lineups?date=' + date);
      var j = await r.json();
      if (j.error) {
        setStatus('Lineup load failed: ' + j.error, 'err');
        return;
      }
      S.lineups = j;
      renderLineupStatus();
      populateGameAndTeamFilters();
    } catch (e) {
      setStatus('Lineup load failed: ' + e.message, 'err');
    }
  }

  function refreshLineups() {
    S.lineups = null;
    renderLineupStatus();
    loadLineups();
  }

  /* ---------------- FV sheet ingestion ---------------- */
  function buildSyntheticFvForLineups(lineups) {
    /* Same shape the OCR extractor would produce, but every batter gets
       every stat at every threshold at the SYNTH_FV baseline. Under
       odds round-tripped via probability complement with a mild juice. */
    var idx = {};
    var names = new Set();
    (lineups.games || []).forEach(function (g) {
      (g.home_lineup || []).forEach(function (p) { if (p && p.player) names.add(p.player); });
      (g.away_lineup || []).forEach(function (p) { if (p && p.player) names.add(p.player); });
    });
    names.forEach(function (name) {
      idx[name] = {};
      Object.keys(SYNTH_FV).forEach(function (stat) {
        idx[name][stat] = {};
        Object.keys(SYNTH_FV[stat]).forEach(function (threshStr) {
          var thresh = Number(threshStr);
          var over = SYNTH_FV[stat][threshStr];
          var pOver = TM.americanToProb(over);
          var under = pOver == null ? null : TM.probToAmerican(1 - pOver);
          idx[name][stat][thresh] = {
            over_fv: over, under_fv: under,
            over_avg_odds: null, under_avg_odds: null,
          };
        });
      });
    });
    return idx;
  }

  function handleUpload(ev) {
    var f = ev && ev.target && ev.target.files && ev.target.files[0];
    if (!f) return;
    ingestImage(f);
  }

  function handleDroppedFile(f) {
    if (f && f.type && f.type.indexOf('image/') === 0) ingestImage(f);
  }

  function ingestImage(f) {
    var img = new Image();
    img.onload = function () {
      var MAX = 2000, w = img.width, h = img.height;
      if (w > MAX || h > MAX) { var s = MAX / Math.max(w, h); w = Math.round(w * s); h = Math.round(h * s); }
      var c = document.createElement('canvas');
      c.width = w; c.height = h;
      c.getContext('2d').drawImage(img, 0, 0, w, h);
      var dataUrl = c.toDataURL('image/jpeg', 0.85);
      callExtractBatter(dataUrl.split(',')[1], 'image/jpeg');
    };
    img.onerror = function () {
      var reader = new FileReader();
      reader.onload = function (e) { callExtractBatter(e.target.result.split(',')[1], f.type || 'image/png'); };
      reader.readAsDataURL(f);
    };
    img.src = URL.createObjectURL(f);
  }

  function callExtractBatter(b64, mime) {
    setStatus('Step 1/2 · Extracting batter props from the sheet via Claude Vision...');
    fetch('/api/extract-batter', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ image: b64, mime: mime }),
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error) { setStatus('Extract error: ' + j.error, 'err'); return; }
        var players = j.players || [];
        if (!players.length) { setStatus('No batter props extracted from image', 'err'); return; }
        S.fvIndex = TE.fvIndexFromExtractor(players);
        S.fvSource = 'ocr';
        var propCount = players.reduce(function (a, p) { return a + (p.props ? p.props.length : 0); }, 0);
        setStatus('Extracted ' + players.length + ' players / ' + propCount + ' props. Enumerating candidates...', 'ok');
        runPipeline();
      })
      .catch(function (e) { setStatus('Network error: ' + e.message, 'err'); });
  }

  function useSyntheticFv() {
    if (!S.lineups) { setStatus('Need lineups before synthetic FV can seed — try Refresh', 'err'); return; }
    S.fvIndex = buildSyntheticFvForLineups(S.lineups);
    S.fvSource = 'synthetic';
    setStatus('Synthetic FV seeded for ' + Object.keys(S.fvIndex).length + ' players. Enumerating candidates...', 'ok');
    runPipeline();
  }

  /* ---------------- pipeline orchestration ---------------- */
  async function runPipeline() {
    if (!window.TEAMMATE_DATA || !window.SLOT_BASELINES) {
      setStatus('Teammate data still loading — give it a moment and the pipeline will auto-run.');
      // Retry once data arrives. teammateLazyLoad sets window.TEAMMATE_LOADED.
      var waitStart = Date.now();
      var iv = setInterval(function () {
        if (window.TEAMMATE_DATA && window.SLOT_BASELINES) { clearInterval(iv); runPipeline(); }
        else if (Date.now() - waitStart > 60000) { clearInterval(iv); setStatus('Teammate data load timeout', 'err'); }
      }, 300);
      return;
    }
    if (!S.lineups) { setStatus('Lineups not loaded yet — retry in a moment', 'err'); return; }
    if (!S.fvIndex)  { setStatus('No FV data — upload a sheet or use synthetic FV', 'err'); return; }

    var enumRes = TE.enumerateCandidates({
      lineups:      S.lineups.games || [],
      fvByPlayer:   S.fvIndex,
      teammateData: window.TEAMMATE_DATA,
      slotBaselines: window.SLOT_BASELINES,
      mode:         S.mode,
      minPairGames: S.filters.minN,
    });
    S.candidatesRaw = enumRes.candidates;
    setStatus('Enumerated ' + enumRes.candidates.length + ' candidates (' + enumRes.diagnostics.combos_emitted +
      ' combos emitted, ' + enumRes.diagnostics.pairs_no_data + ' pairs without Phase-1 data). DK pricing top-|r|...', 'ok');

    /* DK batch: |r|-rank and cap to keep under the 110s deadline.
       Real edges (positive or negative) live at the high-|r| tail. */
    var ranked = enumRes.candidates.slice().sort(function (a, b) {
      return Math.abs(b.r_binary || 0) - Math.abs(a.r_binary || 0);
    });
    var DK_CAP = 120;
    var batch = ranked.slice(0, DK_CAP);
    var payload = batch.map(function (c, i) {
      return {
        id: 'c' + i, team: c.team,
        player_a: c.p1, leg_a: c.leg1_full,
        player_b: c.p2, leg_b: c.leg2_full,
      };
    });

    try {
      var dkResp = await (await fetch('/api/dk/find-sgps-teammate', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ candidates: payload }),
      })).json();
      var priceByCid = {};
      (dkResp.results || []).forEach(function (r) { if (r.matched) priceByCid[r.id] = r; });
      S.dkMissing = (dkResp.results || []).filter(function (r) { return !r.matched; });

      var finalized = [];
      for (var i = 0; i < batch.length; i++) {
        var cand = batch[i], dk = priceByCid['c' + i];
        if (!dk) continue;
        var dkAm = Number(String(dk.dk_odds).replace(/^\+/, ''));
        if (!isFinite(dkAm)) continue;
        finalized.push(TE.finalizeCandidate(cand, dkAm));
      }
      S.candidatesFull = finalized;
      setStatus('Priced ' + finalized.length + ' / ' + batch.length + ' candidates.' +
        (dkResp.truncated ? ' DK deadline hit — partial results.' : ''), 'ok');
      render();
    } catch (e) {
      setStatus('DK pricing error: ' + e.message, 'err');
    }
  }

  /* ---------------- filter application ---------------- */
  function applyFilters(fullList) {
    var f = S.filters;
    var out = fullList.filter(function (c) {
      if (c.ev_pct == null || isNaN(c.ev_pct)) return false;
      if (c.ev_pct < f.minEvPct) return false;
      if ((c.n_total || 0) < f.minN) return false;
      var lvl = c.slot_match_confidence && c.slot_match_confidence.level;
      if (f.conf === 'high' && lvl !== 'high') return false;
      if (f.conf === 'med'  && lvl !== 'high' && lvl !== 'medium') return false;
      if (f.team && c.team !== f.team) return false;
      if (f.game && c.game_id !== f.game) return false;
      if (f.confirmedOnly && c.lineup_status !== 'confirmed') return false;
      return true;
    });
    out.sort(function (a, b) { return b.ev_pct - a.ev_pct; });
    return out;
  }

  /* ---------------- card renderer ---------------- */
  function fmtAm(n) { if (n == null || isNaN(n)) return '--'; return (n > 0 ? '+' : '') + n; }
  /* fmtPct accepts a 0..1 decimal probability and renders "34.2%" — or a
     dash when the value is missing / non-numeric. Callers should pass the
     raw Phase-1 stored value (hit1, hit2, both_hit) which may legitimately
     be null for sparse combos. Previously rendered as "NaN%"; now stays
     visually clean so users don't read it as a broken card. */
  function fmtPct(x) {
    if (x == null || x === '' || isNaN(Number(x))) return '--';
    return (Number(x) * 100).toFixed(1) + '%';
  }
  function confColor(level) {
    return level === 'high'   ? 'var(--ac)'
         : level === 'medium' ? 'var(--ac2)'
         : level === 'low'    ? 'var(--red)'
         : 'var(--mu)';
  }
  function evColor(ev) { return ev >= 5 ? 'var(--ac)' : ev >= 0 ? 'var(--ac2)' : 'var(--red)'; }
  function evCls(ev)   { return ev >= 5 ? 'str'        : ev >= 0 ? 'mod'        : 'neg'; }
  function legSideCls(leg) { return /^Over/.test(leg) ? 'ov' : 'un'; }
  function rColorFor(r) {
    if (r == null || isNaN(r)) return 'var(--mu)';
    return r >= 0.3 ? 'var(--ac)' : r < 0 ? 'var(--red)' : 'var(--ac2)';
  }

  /* Outlier threshold: above 100% EV, DK's returned SGP price has almost
     certainly diverged from a sane FV-implied joint. Common causes:
       - DK mispriced a long-tail same-stat parlay (e.g. O 2.5 H x O 2.5 H)
       - DK applied a promotional correlation boost we can't distinguish from
         their base price
       - Our FV sheet's implied probs are off (OCR mis-read, stale line)
     In every one of those cases the right user action is "go verify on DK
     before betting" — badge nudges that behavior without touching the math. */
  var EV_OUTLIER_THRESHOLD = 100;
  function isOutlier(ev) { return ev != null && !isNaN(ev) && ev > EV_OUTLIER_THRESHOLD; }

  function _pct(x) { return x == null || isNaN(x) ? '--' : (x * 100).toFixed(1) + '%'; }

  /* Build a shrinkage-provenance tooltip string for one candidate. Used
     on the R BINARY pill so users can hover to see the player/global
     split + weights that produced the blended r. */
  function shrinkageProv(c) {
    if (c.mode === 'player' || c.w_player === 1) {
      return 'player r = ' + (c.r_binary_player == null ? 'null' : c.r_binary_player.toFixed(4)) +
             ' (n=' + c.n_total + ', no shrinkage)';
    }
    if (c.mode === 'global' || c.w_player === 0) {
      return 'slot-baseline r = ' + (c.r_binary_global == null ? 'null' : c.r_binary_global.toFixed(4)) +
             ' at slots ' + c.tonight_slots[0] + '_' + c.tonight_slots[1];
    }
    var wp = Math.round(c.w_player * 100), wg = 100 - wp;
    return 'player ' + (c.r_binary_player == null ? 'null' : c.r_binary_player.toFixed(4)) +
           ' × ' + wp + '%  +  slot-baseline ' + (c.r_binary_global == null ? 'null' : c.r_binary_global.toFixed(4)) +
           ' × ' + wg + '%  →  blended ' + (c.r_binary == null ? 'null' : c.r_binary.toFixed(4)) +
           '   (n=' + c.n_total + ' at slots ' + c.tonight_slots[0] + '_' + c.tonight_slots[1] + ')';
  }

  function cardHtml(c, idx) {
    /* Mirrors the pitcher EV card (index.html:card2pitcher + the
       evfinder ranked-card block) so the visual language is uniform
       across tabs. Teammate-specific additions: slot-match confidence
       badge, tonight-vs-historical slot row. */
    var dkStr  = fmtAm(c.dk_american);
    var fvStr  = fmtAm(c.fv_corr_american);
    var hr1 = fmtPct(c.hit1);
    var hr2 = fmtPct(c.hit2);
    /* Both-hit row appears only when we have a real numeric value. Sparse
       Phase-1 combos (null `both`) hide the row entirely rather than
       printing a dash — the row's purpose is to quantify joint historical
       performance, and a dash there would look like a broken stat. */
    var bothHasVal = c.both_hit != null && !isNaN(Number(c.both_hit));
    var bothHr = bothHasVal ? fmtPct(c.both_hit) : null;
    var n = c.n_total;
    var outlier = isOutlier(c.ev_pct);
    var conf = c.slot_match_confidence || { level: 'none', n: 0 };
    var slotStr = c.tonight_slots[0] + '_' + c.tonight_slots[1];
    var histStr = c.most_common_slots ? c.most_common_slots.join('_') : '?';
    var modeBadge = c.mode ? c.mode.toUpperCase() : 'BLENDED';
    var fallbackNote = c.fallback ? ' <span style="color:var(--ac2);font-size:9px">(blended→global)</span>' : '';
    var rmColor = rColorFor(c.r_margin);
    var rmText  = c.r_margin == null ? null : ((c.r_margin >= 0 ? '+' : '') + c.r_margin.toFixed(2));

    var rProv = shrinkageProv(c).replace(/"/g, '&quot;');

    var h = '';
    /* Outlier cards override their border color (inline style wins over
       the class-level border) so they're distinguishable at a glance even
       when the grid is scrolled past — the +1483% Raleigh × Young kind of
       case would otherwise sit visually next to a legit +28% card. */
    var cardStyle = outlier
      ? ' style="border:1px solid var(--ac2);border-left:4px solid var(--ac2);box-shadow:0 0 0 1px rgba(245,158,11,.25) inset"'
      : '';
    h += '<div class="card ' + evCls(c.ev_pct) + '" id="tmev-card-' + idx + '"' + cardStyle + '>';
    /* Outlier banner — above the header so it reads first. Orange (--ac2)
       rather than red so it doesn't scream "BAD"; the candidate MAY be
       a genuine edge, the badge just says "go check DK first". */
    if (outlier) {
      h += '<div style="margin:-14px -14px 8px;padding:5px 10px;background:rgba(245,158,11,.14);border-bottom:1px solid var(--ac2);font-family:Space Mono,monospace;font-size:10px;color:var(--ac2);font-weight:600;letter-spacing:.3px">' +
             '&#9888; OUTLIER &middot; EV > 100% &middot; verify DK price before betting' +
           '</div>';
    }
    /* Header: pair × EV% */
    h += '<div style="display:flex;justify-content:space-between;align-items:start;gap:8px;margin-bottom:8px">';
    h += '<div>' +
           '<div style="font-size:12px;font-weight:700">' + c.p1 + ' &times; ' + c.p2 + '</div>' +
           '<div style="font-size:9px;color:var(--mu);font-family:Space Mono,monospace">' +
             (c.team || '?') + ' &middot; ' + (c.game_label || '?') +
             ' &middot; <span style="color:' + (c.lineup_status === 'confirmed' ? 'var(--ac)' : 'var(--ac2)') + '">' + c.lineup_status + '</span>' +
             ' &middot; ' + modeBadge + fallbackNote +
           '</div>' +
         '</div>';
    h += '<div style="text-align:right">' +
           '<div style="font-size:20px;font-weight:800;font-family:Space Mono,monospace;color:' + evColor(c.ev_pct) + '">' +
             (c.ev_pct >= 0 ? '+' : '') + c.ev_pct.toFixed(1) + '%</div>' +
           '<div style="font-size:8px;color:var(--mu);font-family:Space Mono,monospace">EV</div>' +
         '</div>';
    h += '</div>';

    /* Legs box: two teammate legs + combined hit rate. */
    h += '<div style="background:var(--s2);border-radius:6px;padding:7px 9px;margin-bottom:8px">';
    h += '<div style="display:flex;justify-content:space-between;align-items:center;padding:2px 0">' +
           '<span class="leg ' + legSideCls(c.leg1_full) + '" style="font-size:10px">' + c.leg1_full + ' &middot; ' + c.p1 + '</span>' +
           '<div style="display:flex;align-items:center;gap:6px">' +
             '<span style="font-size:10px;font-family:Space Mono,monospace;color:var(--mu)">FV ' + fmtAm(c.fv_p1) + '</span>' +
             '<span style="font-size:9px;font-family:Space Mono,monospace;color:var(--ac2)">' + hr1 + '</span>' +
           '</div>' +
         '</div>';
    h += '<div style="display:flex;justify-content:space-between;align-items:center;padding:2px 0">' +
           '<span class="leg ' + legSideCls(c.leg2_full) + '" style="font-size:10px">' + c.leg2_full + ' &middot; ' + c.p2 + '</span>' +
           '<div style="display:flex;align-items:center;gap:6px">' +
             '<span style="font-size:10px;font-family:Space Mono,monospace;color:var(--mu)">FV ' + fmtAm(c.fv_p2) + '</span>' +
             '<span style="font-size:9px;font-family:Space Mono,monospace;color:var(--ac2)">' + hr2 + '</span>' +
           '</div>' +
         '</div>';
    if (bothHr != null) {
      h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:5px;padding-top:5px;border-top:1px solid rgba(255,255,255,0.07)">' +
             '<span style="font-size:9px;color:var(--mu);font-family:Space Mono,monospace">Both hit (' + n + ' games together)</span>' +
             '<span style="font-size:9px;font-family:Space Mono,monospace;color:var(--ac)">' + bothHr + '</span>' +
           '</div>';
    }
    h += '</div>';

    /* Metric row: DK, FVcorr, R binary, R margin, QK (5 pills). */
    h += '<div class="hr4" style="grid-template-columns:repeat(5,1fr)">';
    h += '<div class="hi"><div class="hv" style="color:var(--cyan);font-size:15px">' + dkStr + '</div><div class="hl">DK SGP</div></div>';
    h += '<div class="hi"><div class="hv" style="color:var(--ac);font-size:15px">' + fvStr + '</div><div class="hl">FV CORR</div></div>';
    h += '<div class="hi" title="' + rProv + '"><div class="hv" style="color:' + rColorFor(c.r_binary) + ';font-size:15px">' +
         (c.r_binary == null ? 'N/A' : ((c.r_binary >= 0 ? '+' : '') + c.r_binary.toFixed(2))) +
         '</div><div class="hl">R BINARY</div></div>';
    h += '<div class="hi"><div class="hv" style="color:' + rmColor + ';font-size:15px">' +
         (rmText == null ? 'N/A' : rmText) + '</div><div class="hl">MARGIN</div></div>';
    h += '<div class="hi"><div class="hv" style="color:var(--mu);font-size:13px">' + c.qk_pct.toFixed(2) + 'u</div><div class="hl">QK</div></div>';
    h += '</div>';

    /* Slot-match confidence row + shrinkage provenance + AI Insights button */
    h += '<div style="display:flex;align-items:center;gap:8px;margin-top:8px;flex-wrap:wrap">';
    h += '<div style="font-size:9px;font-family:Space Mono,monospace;color:var(--mu)">' +
           'tonight <span style="color:var(--tx)">' + slotStr + '</span>' +
           ' &nbsp;vs hist <span style="color:var(--tx)">' + histStr + '</span>' +
         '</div>';
    h += '<div style="font-size:9px;font-family:Space Mono,monospace;padding:2px 8px;border-radius:10px;background:rgba(0,0,0,.2);color:' + confColor(conf.level) + ';border:1px solid ' + confColor(conf.level) + '">' +
           conf.level.toUpperCase() + ' · n=' + conf.n +
         '</div>';
    h += '<button class="tmev-insight-btn" onclick="window.teammateEvTab._aiInsight(' + idx + ')" title="Fetch AI analysis of this candidate" style="margin-left:auto;padding:4px 10px;font-size:10px;border:1px solid var(--ac3);background:transparent;color:var(--ac3);border-radius:5px;cursor:pointer;font-family:Space Mono,monospace">&#10022; AI INSIGHTS</button>';
    h += '</div>';
    /* Shrinkage provenance line (always visible, matches what the
       tooltip on R BINARY would have shown so keyboard/mobile users
       aren't locked out of that information). */
    h += '<div style="margin-top:6px;font-size:9px;color:var(--mu);font-family:Space Mono,monospace;line-height:1.4;word-break:break-word">' +
         shrinkageProv(c) + '</div>';
    /* Insight panel mount point — populated when the AI INSIGHTS button
       fires. Same pattern as the pitcher EV card (class names match so
       the pitcher side's CSS for .ins-panel / .ins-vbadge / verdict
       variants just works here too). */
    h += '<div class="tmev-insight-wrap"></div>';

    h += '</div>';
    return h;
  }

  /* Project a candidate record (chunk 4 enumerator output) into the sgp
     shape buildTeammateInsightPrompt expects. Names kept compact so the
     prompt itself reads cleanly — the raw candidate has 45+ fields. */
  function projectCandidateForInsight(c) {
    return {
      p1: c.p1, p2: c.p2,
      team: c.team, gameLabel: c.game_label,
      mode: c.mode, fallback: c.fallback,
      leg1Full: c.leg1_full, leg2Full: c.leg2_full,
      fv1: c.fv_p1, fv2: c.fv_p2,
      pLeg1: c.p_leg1, pLeg2: c.p_leg2,
      dkAmerican: c.dk_american, fvCorrAmerican: c.fv_corr_american,
      pJoint: c.p_joint, evPct: c.ev_pct, qkPct: c.qk_pct,
      rBinary: c.r_binary, rMargin: c.r_margin,
      rBinaryPlayer: c.r_binary_player, rBinaryGlobal: c.r_binary_global,
      wPlayer: c.w_player,
      hit1: c.hit1, hit2: c.hit2, bothHit: c.both_hit, nTotal: c.n_total,
      tonightSlots: c.tonight_slots, historicalSlots: c.most_common_slots,
      slotMatchConfidence: c.slot_match_confidence,
    };
  }

  /* Render one insight panel inline under the card's metric row. HTML
     structure + class names match the pitcher-side .ins-panel pattern
     so the existing index.html CSS applies without a new rule set. */
  function renderInsightPanel(wrap, ins) {
    var vc = ins.verdict === 'PLAY' ? 'play' : ins.verdict === 'MARGINAL' ? 'marginal' : 'skip';
    var conf = parseInt(ins.confidence, 10) || 0;
    var h = '<div class="ins-panel ' + vc + '" style="margin-top:8px;padding:10px;border-radius:6px;border:1px solid var(--b1);background:var(--s2)">';
    h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
    h += '<span class="ins-vbadge ' + vc + '" style="font-family:Space Mono,monospace;font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;background:' +
         (vc === 'play' ? 'rgba(74,222,128,.2);color:var(--ac)'
        : vc === 'marginal' ? 'rgba(245,158,11,.2);color:var(--ac2)'
        : 'rgba(248,113,113,.2);color:var(--red)') + '">' + ins.verdict + '</span>';
    h += '<span style="display:flex;align-items:center;gap:10px">';
    h += '<span style="font-size:10px;font-family:Space Mono,monospace;color:var(--mu)">' + conf + '/10</span>';
    h += '</span></div>';
    h += '<div style="font-size:12px;font-weight:600;margin-bottom:6px;line-height:1.4">' + ins.headline + '</div>';
    h += '<div style="font-size:11px;color:var(--tx);line-height:1.55;margin-bottom:8px">' + ins.explanation + '</div>';
    h += '<div style="font-size:10px;color:var(--ac);font-family:Space Mono,monospace;margin-bottom:4px">EDGE &nbsp; ' + ins.edge + '</div>';
    h += '<div style="font-size:10px;color:var(--red);font-family:Space Mono,monospace">RISK &nbsp; ' + ins.risk + '</div>';
    h += '</div>';
    wrap.innerHTML = h;
  }

  function loadAiInsight(idx) {
    var card = document.getElementById('tmev-card-' + idx);
    if (!card) return;
    var btn  = card.querySelector('.tmev-insight-btn');
    var wrap = card.querySelector('.tmev-insight-wrap');
    if (!btn || !wrap) return;
    var c = (S.candidatesFull && S.candidatesFull[idx]) || null;
    /* Candidates rendered in the filtered view map to post-sort indices
       that don't align to S.candidatesFull's insertion order. Look up by
       pair_key/combo_idx instead when we can't assume positional identity. */
    if (!c) {
      /* Fallback: find via the id embedded in the card — idx is the
         post-filter render position, so use the filtered list. */
      var filtered = applyFilters(S.candidatesFull);
      c = filtered[idx];
    }
    if (!c) {
      wrap.innerHTML = '<div style="margin-top:8px;font-size:11px;color:var(--red);font-family:Space Mono,monospace">No candidate data for idx=' + idx + '</div>';
      return;
    }

    btn.disabled = true;
    btn.textContent = '⟳ Analyzing…';
    wrap.innerHTML = '';

    var builder = window.buildTeammateInsightPrompt;
    if (typeof builder !== 'function') {
      wrap.innerHTML = '<div style="margin-top:8px;font-size:11px;color:var(--red);font-family:Space Mono,monospace">teammateInsightPrompt.js not loaded</div>';
      btn.disabled = false; btn.textContent = '✦ AI INSIGHTS';
      return;
    }
    var prompt = builder(projectCandidateForInsight(c));

    fetch('/api/sgp-insight', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ prompt: prompt }),
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        btn.disabled = false; btn.textContent = '✦ AI INSIGHTS';
        if (j.error) {
          wrap.innerHTML = '<div style="margin-top:8px;font-size:11px;color:var(--red);font-family:Space Mono,monospace">' + j.error + '</div>';
          return;
        }
        /* Claude sometimes wraps JSON in ```json fences despite the "no
           markdown" instruction. Strip them defensively — matches the
           pitcher side's approach at index.html:1339. */
        var txt = (j.text || '').replace(/```json\s*/g, '').replace(/```/g, '').trim();
        try {
          var ins = JSON.parse(txt);
          renderInsightPanel(wrap, ins);
        } catch (e) {
          wrap.innerHTML = '<div style="margin-top:8px;font-size:11px;color:var(--red);font-family:Space Mono,monospace">Parse error: ' +
            e.message + '<br><span style="color:var(--mu);font-size:10px">Raw: ' +
            txt.slice(0, 200).replace(/</g, '&lt;') + '…</span></div>';
        }
      })
      .catch(function (e) {
        btn.disabled = false; btn.textContent = '✦ AI INSIGHTS';
        wrap.innerHTML = '<div style="margin-top:8px;font-size:11px;color:var(--red);font-family:Space Mono,monospace">Network error: ' + e.message + '</div>';
      });
  }

  function render() {
    $('tmevFilterBar').style.display = 'flex';
    var filtered = applyFilters(S.candidatesFull);
    $('tmevCount').textContent =
      filtered.length + ' / ' + S.candidatesFull.length + ' match current filters' +
      ' · source: ' + (S.fvSource || 'none');
    var container = $('tmevResults');
    if (!filtered.length) {
      container.innerHTML = '<div class="empty" style="padding:20px;color:var(--mu);font-size:12px;text-align:center;margin-top:10px">' +
        'No candidates match the current filters. Try lowering MIN EV%, widening confidence, or checking other teams.</div>';
      return;
    }
    /* Cap to top 60 — at 60 cards × ~8 DOM elements each we stay under
       500 nodes. UI can grow this later with a "load more" button. */
    var cap = Math.min(filtered.length, 60);
    var cardsHtml = '';
    for (var i = 0; i < cap; i++) cardsHtml += cardHtml(filtered[i], i);
    container.innerHTML =
      '<div class="grid" style="margin-top:10px;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:10px">' +
        cardsHtml +
      '</div>' +
      (filtered.length > cap
         ? '<div style="text-align:center;margin-top:10px;font-size:10px;color:var(--mu);font-family:Space Mono,monospace">Showing top ' + cap + ' of ' + filtered.length + ' — refine filters to see more</div>'
         : '');
  }

  /* ---------------- filter/mode handlers ---------------- */
  function setMode(m) {
    S.mode = m;
    ['tmevModePlayer', 'tmevModeBlended', 'tmevModeGlobal'].forEach(function (id) {
      var el = $(id); if (!el) return;
      var on = id.toLowerCase().indexOf(m) >= 0;
      el.style.background = on ? 'rgba(34,197,94,.12)' : 'transparent';
      el.style.color = on ? 'var(--ac)' : 'var(--mu)';
    });
    if (S.fvIndex) runPipeline();
  }

  function readFiltersFromDom() {
    var minEvEl = $('tmevMinEv'); if (minEvEl) S.filters.minEvPct = Number(minEvEl.value);
    var minNEl  = $('tmevMinN');  if (minNEl)  S.filters.minN     = Number(minNEl.value);
    var confEl  = $('tmevConf');  if (confEl)  S.filters.conf     = confEl.value;
    var teamEl  = $('tmevTeam');  if (teamEl)  S.filters.team     = teamEl.value;
    var gameEl  = $('tmevGame');  if (gameEl)  S.filters.game     = gameEl.value;
    var coEl    = $('tmevConfirmedOnly'); if (coEl) S.filters.confirmedOnly = !!coEl.checked;
    var minEvV = $('tmevMinEvV'); if (minEvV) minEvV.textContent = (S.filters.minEvPct >= 0 ? '+' : '') + S.filters.minEvPct + '%';
    var minNV  = $('tmevMinNV');  if (minNV)  minNV.textContent  = S.filters.minN;
  }

  function onFilter() {
    readFiltersFromDom();
    if (S.candidatesFull.length) render();
  }

  /* ---------------- init ---------------- */
  function onActivate() {
    if (S.activated) return;
    S.activated = true;

    /* Drop + paste handlers. Modeled on the pitcher EV Finder tab's
       pattern (index.html:evDrop wiring). */
    var dz = $('tmevDrop');
    if (dz) {
      dz.onclick = function () { var f = $('tmevFile'); if (f) f.click(); };
      dz.ondragover = function (e) { e.preventDefault(); dz.style.borderColor = 'var(--ac3)'; dz.style.background = 'var(--s1)'; };
      dz.ondragleave = function () { dz.style.borderColor = 'var(--b2)'; dz.style.background = 'var(--s2)'; };
      dz.ondrop = function (e) {
        e.preventDefault();
        dz.style.borderColor = 'var(--b2)'; dz.style.background = 'var(--s2)';
        var f = e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) handleDroppedFile(f);
      };
    }
    document.addEventListener('paste', function (e) {
      if (!document.getElementById('page-tmev').classList.contains('active')) return;
      var items = e.clipboardData && e.clipboardData.items; if (!items) return;
      for (var i = 0; i < items.length; i++) {
        if (items[i].type.indexOf('image/') === 0) {
          var f = items[i].getAsFile();
          if (f) { handleDroppedFile(f); e.preventDefault(); return; }
        }
      }
    });
    var synth = $('tmevSynthLink');
    if (synth) synth.onclick = function (e) { e.preventDefault(); useSyntheticFv(); };

    loadLineups();
  }

  window.teammateEvTab = {
    onActivate:      onActivate,
    refreshLineups:  refreshLineups,
    handleUpload:    handleUpload,
    setMode:         setMode,
    onFilter:        onFilter,
    useSyntheticFv:  useSyntheticFv,
    _aiInsight:      loadAiInsight,
    _projectForInsight: projectCandidateForInsight,
    _render:         render,
    _cardHtml:       cardHtml,
    _state:          S,  // for debugging from the browser console
  };
})();
