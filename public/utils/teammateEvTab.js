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

  /* ---------------- placeholder renderer (full cards arrive in 5c) ---------------- */
  function render() {
    $('tmevFilterBar').style.display = 'flex';
    var filtered = applyFilters(S.candidatesFull);
    $('tmevCount').textContent =
      filtered.length + ' / ' + S.candidatesFull.length + ' match current filters' +
      ' · source: ' + (S.fvSource || 'none');
    var container = $('tmevResults');
    if (!filtered.length) {
      container.innerHTML = '<div class="empty" style="padding:20px;color:var(--mu);font-size:12px;text-align:center">' +
        'No candidates match the current filters. Try lowering MIN EV% or widening confidence.</div>';
      return;
    }
    /* 5c will replace this with proper cards. For now, show a dense
       table-like summary so the pipeline is demonstrably working end
       to end. Render top 30 to keep DOM cost bounded. */
    var rows = filtered.slice(0, 30).map(function (c) {
      var dk = (c.dk_american > 0 ? '+' : '') + c.dk_american;
      var fvC = (c.fv_corr_american > 0 ? '+' : '') + c.fv_corr_american;
      var conf = c.slot_match_confidence;
      var confColor = conf.level === 'high' ? 'var(--ac)' : conf.level === 'medium' ? 'var(--ac2)' : conf.level === 'low' ? 'var(--red)' : 'var(--mu)';
      return '<div style="display:grid;grid-template-columns:minmax(220px,1fr) 140px 120px 100px 100px 90px 80px;gap:10px;padding:8px 10px;border-bottom:1px solid var(--b1);font-family:Space Mono,monospace;font-size:11px;align-items:center">' +
        '<div style="color:var(--tx)"><strong>' + c.p1 + '</strong> × <strong>' + c.p2 + '</strong>' +
          '<div style="font-size:9px;color:var(--mu)">' + c.team + ' · ' + (c.game_label || '') + '</div></div>' +
        '<div style="color:var(--mu);font-size:10px">' + c.leg1_full + '<br>' + c.leg2_full + '</div>' +
        '<div style="color:var(--mu)">slots ' + c.tonight_slots[0] + '_' + c.tonight_slots[1] + '<br><span style="color:' + confColor + ';font-size:10px">' + conf.level + ' n=' + conf.n + '</span></div>' +
        '<div>r=' + (c.r_binary == null ? 'null' : c.r_binary.toFixed(3)) + '<br><span style="color:var(--mu);font-size:10px">w=' + (c.w_player || 0).toFixed(2) + '</span></div>' +
        '<div>DK ' + dk + '<br><span style="color:var(--mu);font-size:10px">FV ' + fvC + '</span></div>' +
        '<div style="color:' + (c.ev_pct >= 5 ? 'var(--ac)' : c.ev_pct >= 0 ? 'var(--ac2)' : 'var(--red)') + ';font-weight:700">' + c.ev_pct.toFixed(1) + '%</div>' +
        '<div style="color:var(--mu)">QK ' + c.qk_pct.toFixed(2) + 'u</div>' +
        '</div>';
    }).join('');
    container.innerHTML =
      '<div style="padding:10px;background:var(--s1);border-radius:8px;border:1px solid var(--b1);margin-top:10px">' +
        '<div style="font-size:10px;color:var(--mu);padding:4px 10px 8px;font-family:Space Mono,monospace">Preview — full card UI lands in chunk 5c</div>' +
        rows +
      '</div>';
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
    _state:          S,  // for debugging from the browser console
  };
})();
