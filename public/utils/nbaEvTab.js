/* nbaEvTab.js — NBA +EV Finder tab wiring.
 *
 * Phase 3 module split (built incrementally across commits):
 *   - Edit 1: scaffold + correlations fetch + header stats population
 *   - Edit 2: correlations xlsx upload card + rollback
 *   - Edit 3: FV sheet upload card + POST to /api/extract-nba (Phase 4)
 *   - Edit 4: filter controls (MIN EV%, MIN GAMES, MAX P_VALUE, props)
 *   - Edit 5: candidate enumeration + EV math
 *   - Edit 6: card renderer
 *   - Edit 7: badges + sort + pagination
 *   - Edit 8: dev synthetic harness (for screenshots before OCR/DK wiring)
 *
 * Self-contained: no dependency on the MLB teammateEv* modules. Reads only
 * from /api/nba/* endpoints (landed in Phase 1) and the DOM elements inside
 * #page-nba-evfinder (populated in later edits of Phase 3).
 *
 * Attached to window.nbaTab so setSport('nba') can call .onActivate().
 */
(function () {
  'use strict';

  /* Activation is cheap — we lazy-fetch correlations + meta on first open
     and on every subsequent activation (to pick up a just-uploaded file
     without a page reload). Concurrent calls dedupe via the _busy flag. */
  var state = {
    correlations: null,   // { schema_version, status, season, entries, by_player }
    meta: null,           // { status, uploaded_at, season, row_count, ... }
    _busy: false,
    _activated: false,
  };

  function fmtInt(n) {
    if (n == null || !isFinite(n)) return '--';
    return Number(n).toLocaleString('en-US');
  }

  function fmtTimestamp(iso) {
    if (!iso) return '';
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      /* 24-hour local time + YYYY-MM-DD so it reads the same on every
         viewer's clock region. Matches the spec's "2026-04-21 09:14 AM"
         shape, swapped to 24h for unambiguity. */
      var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
      return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
        ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    } catch (_) { return iso; }
  }

  /* Wire the header stats row (#nbaHdrEntries / #nbaHdrPlayers / #nbaHdrSeason
     + #nbaHdrBadge). Defensive: any missing id is a no-op so this survives
     partial DOM states (e.g. if Phase 3 edits later restructure the header). */
  function renderHeaderStats() {
    var m = state.meta || {};
    var setText = function (id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
    if (m.status === 'ok') {
      setText('nbaHdrEntries', fmtInt(m.row_count));
      setText('nbaHdrPlayers', fmtInt(m.distinct_players));
      setText('nbaHdrSeason', m.season || '--');
      setText('nbaHdrBadge', 'Last upload: ' + fmtTimestamp(m.uploaded_at));
    } else {
      setText('nbaHdrEntries', '--');
      setText('nbaHdrPlayers', '--');
      setText('nbaHdrSeason', '--');
      setText('nbaHdrBadge', 'No NBA correlations data uploaded yet');
    }
  }

  function fetchJson(url, init) {
    return fetch(url, init).then(function (r) {
      if (!r.ok) {
        return r.json().then(function (j) { throw new Error(j.error || ('HTTP ' + r.status)); },
                             function ()  { throw new Error('HTTP ' + r.status); });
      }
      return r.json();
    });
  }

  /* Public: fetch /meta + /correlations and repaint header stats. Returns
     a promise the caller can chain (Edit 2 will trigger this after an
     upload completes). */
  function reload() {
    if (state._busy) return Promise.resolve();
    state._busy = true;
    return Promise.all([
      fetchJson('/api/nba/correlations/meta').catch(function () { return { status: 'empty' }; }),
      fetchJson('/api/nba/correlations').catch(function () { return { status: 'empty', entries: [], by_player: {} }; }),
    ]).then(function (parts) {
      state.meta = parts[0];
      state.correlations = parts[1];
      renderHeaderStats();
    }).finally(function () { state._busy = false; });
  }

  /* Render the per-tab "Last updated: … · N entries · M players · season …"
     line and toggle the ROLL BACK button based on history availability.
     Called after every reload() so uploads are immediately visible. */
  function renderCorrMeta() {
    var m = state.meta || {};
    var line = document.getElementById('nbaCorrMetaLine');
    var rb = document.getElementById('nbaCorrRollback');
    if (!line) return;
    if (m.status === 'ok') {
      line.innerHTML =
        'Last updated: <span style="color:var(--tx)">' + fmtTimestamp(m.uploaded_at) + '</span>' +
        '  &middot;  ' + fmtInt(m.row_count) + ' entries' +
        '  &middot;  ' + fmtInt(m.distinct_players) + ' players' +
        '  &middot;  season ' + (m.season || '--') +
        (m.rejected_rows ? '  &middot;  <span style="color:var(--ac2)">' + fmtInt(m.rejected_rows) + ' rejected</span>' : '');
    } else {
      line.innerHTML = '<span style="color:var(--mu)">No correlations data uploaded yet &mdash; drop your xlsx above to get started.</span>';
    }
    /* ROLL BACK is always visible; the server-side endpoint returns a
       400 with "No history entries" when the archive is empty, which
       onRollback surfaces as a clean error instead of a silent no-op. */
    if (rb) rb.style.opacity = (m.status === 'ok') ? '1' : '0.5';
  }

  function setStatus(html) {
    var el = document.getElementById('nbaCorrStatus');
    if (el) el.innerHTML = html;
  }

  function postCorrFile(file) {
    if (!file) return;
    if (!/\.xlsx$/i.test(file.name)) {
      setStatus('<span style="color:var(--red)">File must be .xlsx (got ' + file.name + ')</span>');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setStatus('<span style="color:var(--red)">File too large: ' + (file.size / 1024 / 1024).toFixed(1) + ' MB (max 10)</span>');
      return;
    }
    setStatus('<span style="color:var(--ac2)">Uploading + parsing ' + file.name + '...</span>');
    var fd = new FormData();
    fd.append('file', file, file.name);
    fetch('/api/nba/upload-correlations', { method: 'POST', body: fd })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        var j = res.body || {};
        if (!j.ok) {
          setStatus('<span style="color:var(--red)">Upload failed: ' + (j.error || ('HTTP ' + res.status)) + '</span>');
          return;
        }
        var rejNote = j.rejected_rows ? ' &middot; ' + fmtInt(j.rejected_rows) + ' rejected' : '';
        setStatus('<span style="color:var(--ac)">&#10003; Uploaded ' + fmtInt(j.row_count) + ' entries, ' + fmtInt(j.distinct_players) + ' players' + rejNote + '</span>');
        state._activated = true; // force reload to see new data
        return reload();
      })
      .catch(function (e) {
        setStatus('<span style="color:var(--red)">Upload error: ' + (e.message || e) + '</span>');
      });
  }

  function onCorrUpload(ev) {
    var f = ev.target.files && ev.target.files[0];
    if (f) postCorrFile(f);
    ev.target.value = ''; // allow re-uploading the same filename
  }

  function onRollback() {
    if (!confirm('Restore the previous correlations snapshot? Current data will be replaced with the most recent archived version.')) return;
    setStatus('<span style="color:var(--ac2)">Rolling back...</span>');
    fetch('/api/nba/correlations/rollback', { method: 'POST' })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        var j = res.body || {};
        if (!j.ok) { setStatus('<span style="color:var(--red)">Rollback failed: ' + (j.error || ('HTTP ' + res.status)) + '</span>'); return; }
        setStatus('<span style="color:var(--ac)">&#10003; Rolled back to ' + (j.restored_from || 'previous snapshot') + '</span>');
        state._activated = true;
        return reload();
      })
      .catch(function (e) { setStatus('<span style="color:var(--red)">Rollback error: ' + (e.message || e) + '</span>'); });
  }

  /* ---------- FV sheet upload (POSTs to /api/extract-nba, Phase 4) ---------- */

  /* FV rows, keyed by player → array of props. Structure mirrors what the
     batter-FV OCR returns in MLB:
       { "Player Name": [ {stat, threshold, over_fv, under_fv, ...}, ... ] }
     Populated on successful /api/extract-nba response. Until Phase 4 ships
     the endpoint, this stays null and a clear status message tells the user
     "OCR not deployed yet". */
  state.fv = null;

  function setFvStatus(html) {
    var el = document.getElementById('nbaFvStatus');
    if (el) el.innerHTML = html;
  }

  function handleFvImage(file) {
    if (!file) return;
    if (file.type && file.type.indexOf('image/') !== 0) {
      setFvStatus('<span style="color:var(--red)">File must be an image (got ' + (file.type || 'unknown') + ')</span>');
      return;
    }
    setFvStatus('<span style="color:var(--ac2)">OCR &middot; extracting NBA prop legs...</span>');
    var img = new Image();
    img.onload = function () {
      var MAX = 2000, w = img.width, h = img.height;
      if (w > MAX || h > MAX) { var s = MAX / Math.max(w, h); w = Math.round(w * s); h = Math.round(h * s); }
      var c = document.createElement('canvas'); c.width = w; c.height = h;
      c.getContext('2d').drawImage(img, 0, 0, w, h);
      var dataUrl = c.toDataURL('image/jpeg', 0.85);
      postFvImage(dataUrl.split(',')[1], 'image/jpeg');
    };
    img.onerror = function () {
      var reader = new FileReader();
      reader.onload = function (e) { postFvImage(e.target.result.split(',')[1], file.type || 'image/png'); };
      reader.readAsDataURL(file);
    };
    img.src = URL.createObjectURL(file);
  }

  function postFvImage(b64, mime) {
    fetch('/api/extract-nba', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ image: b64, mime: mime }),
    }).then(function (r) {
      if (r.status === 404) {
        setFvStatus('<span style="color:var(--ac2)">NBA OCR endpoint not yet deployed (lands in Phase 4). Use DEV button below for synthetic smoke testing.</span>');
        return null;
      }
      return r.json().then(function (j) { return { status: r.status, body: j }; });
    }).then(function (res) {
      if (!res) return;
      var j = res.body || {};
      if (!j.players || !j.players.length) {
        setFvStatus('<span style="color:var(--red)">OCR extracted no NBA props: ' + (j.error || 'empty response') + '</span>');
        return;
      }
      state.fv = indexFvPlayers(j.players);
      setFvStatus('<span style="color:var(--ac)">&#10003; FV: ' + j.players.length + ' players parsed' + (j.unmatched_markets && j.unmatched_markets.length ? ' &middot; ' + j.unmatched_markets.length + ' unsupported-prop rows' : '') + '</span>');
      if (typeof runPipeline === 'function') runPipeline();
    }).catch(function (e) { setFvStatus('<span style="color:var(--red)">OCR error: ' + (e.message || e) + '</span>'); });
  }

  /* Build { player -> { stat -> { threshold -> { over_fv, under_fv, … } } } }
     for O(1) lookups in the enumerator. Matches what batter OCR already
     emits in the MLB flow so Phase 4's NBA OCR can reuse the same shape. */
  function indexFvPlayers(players) {
    var idx = {};
    for (var i = 0; i < players.length; i++) {
      var p = players[i];
      var propMap = {};
      for (var k = 0; k < (p.props || []).length; k++) {
        var pr = p.props[k];
        if (!propMap[pr.stat]) propMap[pr.stat] = {};
        propMap[pr.stat][pr.threshold] = pr;
      }
      idx[p.player] = { player: p.player, team: p.team || null, game: p.game || null, props: propMap };
    }
    return idx;
  }

  /* Idempotent wiring of both drop zones (correlations + FV). */
  var _wired = false;
  function wireDom() {
    if (_wired) return;
    var bindDrop = function (zoneId, fileId, handler, accept) {
      var dz = document.getElementById(zoneId);
      if (!dz) return;
      dz.addEventListener('click', function () { var i = document.getElementById(fileId); if (i) i.click(); });
      dz.addEventListener('dragover', function (e) { e.preventDefault(); dz.style.borderColor = 'var(--cyan)'; dz.style.background = 'rgba(34,211,238,.08)'; });
      dz.addEventListener('dragleave', function () { dz.style.borderColor = 'var(--b2)'; dz.style.background = 'var(--s2)'; });
      dz.addEventListener('drop', function (e) {
        e.preventDefault();
        dz.style.borderColor = 'var(--b2)';
        dz.style.background = 'var(--s2)';
        var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (!f) return;
        if (accept === 'image' && f.type && f.type.indexOf('image/') !== 0) return;
        handler(f);
      });
    };
    bindDrop('nbaCorrDrop', 'nbaCorrFile', postCorrFile, 'xlsx');
    bindDrop('nbaFvDrop', 'nbaFvFile', handleFvImage, 'image');
    /* Paste-from-clipboard support (NBA tab only). */
    document.addEventListener('paste', function (e) {
      var pageEl = document.getElementById('page-nba-evfinder');
      if (!pageEl || !pageEl.classList.contains('active')) return;
      var items = e.clipboardData && e.clipboardData.items;
      if (!items) return;
      for (var i = 0; i < items.length; i++) {
        if (items[i].type && items[i].type.indexOf('image/') === 0) {
          var f = items[i].getAsFile();
          if (f) { handleFvImage(f); e.preventDefault(); return; }
        }
      }
    });
    _wired = true;
  }

  function onFvUpload(ev) {
    var f = ev.target.files && ev.target.files[0];
    if (f) handleFvImage(f);
    ev.target.value = '';
  }

  /* ---------- EV math (Edit 5) ---------- */

  /* American odds → decimal. Handles both signs. */
  function amToDec(a) {
    a = Number(a); if (!isFinite(a) || a === 0) return null;
    return a > 0 ? 1 + a / 100 : 1 + 100 / (-a);
  }
  /* Decimal → American (rounded). */
  function decToAm(d) {
    d = Number(d); if (!isFinite(d) || d <= 1) return null;
    return d >= 2 ? Math.round((d - 1) * 100) : -Math.round(100 / (d - 1));
  }
  /* Binary-phi reconstruction of joint probability from correlation + marginals.
     Clamped to keep sqrt stable at extremes. Used for the FV CORR display
     (what the SGP should price at if you trust FV marginals + the data's r). */
  function jointFromPhi(r, p1, p2) {
    if (r == null || !isFinite(r) || !isFinite(p1) || !isFinite(p2)) return null;
    var a = Math.max(0.001, Math.min(0.999, p1));
    var b = Math.max(0.001, Math.min(0.999, p2));
    var j = r * Math.sqrt(a * (1 - a) * b * (1 - b)) + a * b;
    return Math.max(0.001, Math.min(0.999, j));
  }

  /* Return the FV row from state.fv for a (player, prop, line) triple, or
     null if no match. Line matching is exact (0.5 / 1.5 etc). Side stored
     as 'over'/'under' per Phase 1 normalization. */
  function findFv(fvIndex, player, prop, line, side) {
    if (!fvIndex || !fvIndex[player]) return null;
    var byStat = fvIndex[player].props[prop];
    if (!byStat) return null;
    var row = byStat[line];
    if (!row) return null;
    return {
      fv_american: side === 'over' ? row.over_fv : row.under_fv,
      dk_over_american: row.over_dk_american || null,
      dk_under_american: row.under_dk_american || null,
    };
  }

  /* Pure: build candidates from (correlations, fvIndex, filters, confirmedSet).
     Each correlation entry becomes 0 or 1 candidate depending on whether
     both legs have FV + pass leg-level filters. DK prices are expected to
     already be attached to fvIndex rows (dk_over_american, dk_under_american)
     and to the candidate's dk_sgp_american by the caller (harness or Phase 4
     OCR+DK path). Candidates missing DK SGP are still emitted but flagged
     so the renderer can show them in a muted state. */
  function enumerateCandidates(correlations, fvIndex, filters, confirmedSet) {
    var out = [];
    if (!correlations || !correlations.entries || !fvIndex) return out;
    var players = Object.keys(fvIndex);
    for (var i = 0; i < players.length; i++) {
      var player = players[i];
      var idxs = (correlations.by_player && correlations.by_player[player]) || [];
      for (var k = 0; k < idxs.length; k++) {
        var e = correlations.entries[idxs[k]];
        if (!e) continue;
        if (!filters.props[e.leg1.prop] || !filters.props[e.leg2.prop]) continue;
        if (e.n_games < filters.minGames) continue;
        if (e.p_value > filters.maxPValue) continue;
        /* Phase 5 will populate confirmedSet from /api/nba/games. Until
           then, confirmedOnly silently gates nothing (treat all players
           as confirmed). A non-null confirmedSet flips it on. */
        if (filters.confirmedOnly && confirmedSet && !confirmedSet.has(player)) continue;
        var fv1 = findFv(fvIndex, player, e.leg1.prop, e.leg1.line, e.leg1.side);
        var fv2 = findFv(fvIndex, player, e.leg2.prop, e.leg2.line, e.leg2.side);
        if (!fv1 || !fv2 || fv1.fv_american == null || fv2.fv_american == null) continue;
        out.push(buildCandidate(player, fvIndex[player], e, fv1, fv2));
      }
    }
    return out;
  }

  function buildCandidate(player, fvPlayer, entry, fv1, fv2) {
    var fvDec1 = amToDec(fv1.fv_american);
    var fvDec2 = amToDec(fv2.fv_american);
    var p1 = fvDec1 ? 1 / fvDec1 : null;
    var p2 = fvDec2 ? 1 / fvDec2 : null;
    var fvCorrProb = jointFromPhi(entry.r_adj, p1, p2);
    var modelJoint = entry.p_joint;
    var dkSgpAm = entry.dk_sgp_american != null ? entry.dk_sgp_american : null;
    var dkSgpDec = dkSgpAm != null ? amToDec(dkSgpAm) : null;
    var dkImplied = dkSgpDec ? 1 / dkSgpDec : null;
    var evPct = (dkSgpDec != null) ? (modelJoint * dkSgpDec - 1) : null;
    var edgePp = (dkImplied != null) ? (modelJoint - dkImplied) * 100 : null;
    return {
      id: player + '|' + entry.leg1.prop + entry.leg1.line + entry.leg1.side + '|' + entry.leg2.prop + entry.leg2.line + entry.leg2.side,
      player: player,
      team: fvPlayer.team,
      game: fvPlayer.game,
      leg1: Object.assign({}, entry.leg1, { fv_american: fv1.fv_american, dk_over_american: fv1.dk_over_american, dk_under_american: fv1.dk_under_american, base_rate: entry.hit_rate_1 }),
      leg2: Object.assign({}, entry.leg2, { fv_american: fv2.fv_american, dk_over_american: fv2.dk_over_american, dk_under_american: fv2.dk_under_american, base_rate: entry.hit_rate_2 }),
      entry: entry,
      dk_sgp_american: dkSgpAm,
      dk_sgp_decimal: dkSgpDec,
      dk_implied: dkImplied,
      fv_corr_prob: fvCorrProb,
      fv_corr_american: fvCorrProb ? decToAm(1 / fvCorrProb) : null,
      model_joint: modelJoint,
      edge_pp: edgePp,
      ev_pct: evPct,
    };
  }

  function applyEvFilter(cands, minEvPct) {
    var min = minEvPct / 100;
    return cands.filter(function (c) { return c.ev_pct != null && c.ev_pct >= min; });
  }

  /* Forward-declared renderer; defined in Edit 6. */
  var renderResults;

  /* Main pipeline entry. Rebuilds state.candidates from the current inputs.
     Cheap enough to call on every filter change — the FV + DK fetches are
     the expensive legs and those happen at upload time, not here. */
  function runPipeline(opts) {
    if (!state.correlations || !state.fv) { state.candidates = []; if (typeof renderResults === 'function') renderResults(); return; }
    var all = enumerateCandidates(state.correlations, state.fv, state.filters, state.confirmedSet);
    state.candidatesAll = all;
    state.candidates = applyEvFilter(all, state.filters.minEvPct);
    if (typeof renderResults === 'function') renderResults();
  }

  /* ---------- Filters (Edit 4) ---------- */

  /* Live filter state. Kept in sync with the DOM on every control event.
     Defaults match the v1 spec: aggressive enough to keep noise out of
     a first scan (MIN_GAMES 30, MAX_P_VALUE 0.10) but not so aggressive
     they'd suppress moderately-sampled signals. Prop multi-select is
     initialized with all 4 supported NBA props on. */
  state.filters = {
    minEvPct: 3,       // percent, e.g. 3 => EV% >= +3%
    minGames: 30,
    maxPValue: 0.10,
    props: { 'Points': true, 'Rebounds': true, 'Assists': true, '3-Pointers Made': true },
    confirmedOnly: true,
  };

  function readFilterDom() {
    var f = state.filters;
    var el;
    if ((el = document.getElementById('nbaMinEv')))       f.minEvPct = Number(el.value);
    if ((el = document.getElementById('nbaMinGames')))    f.minGames = Number(el.value);
    if ((el = document.getElementById('nbaMaxP')))        f.maxPValue = Number(el.value) / 100;
    if ((el = document.getElementById('nbaConfirmedOnly'))) f.confirmedOnly = !!el.checked;
    /* Prop buttons: the .active class on the <button> is the source of
       truth. readFilterDom reads it back so programmatic toggles via
       onPropBtn stay in sync. */
    var btns = document.querySelectorAll('#nbaPropBtns [data-nba-prop]');
    f.props = {};
    btns.forEach(function (b) { f.props[b.getAttribute('data-nba-prop')] = b.classList.contains('active'); });
    return f;
  }

  function renderFilterLabels() {
    var f = state.filters;
    var set = function (id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
    set('nbaMinEvV', (f.minEvPct >= 0 ? '+' : '') + f.minEvPct + '%');
    set('nbaMinGamesV', String(f.minGames));
    set('nbaMaxPV', f.maxPValue.toFixed(2));
  }

  function onFilter() {
    readFilterDom();
    renderFilterLabels();
    if (typeof runPipeline === 'function') runPipeline({ filtersOnly: true });
  }

  function onPropBtn(btn) {
    if (!btn) return;
    btn.classList.toggle('active');
    /* Refuse to let the user disable every prop — an empty prop filter
       silently kills all candidates, which reads as "nothing found" when
       it's really "nothing allowed". Reactivate the clicked button if
       it was the last one on. */
    var anyOn = false;
    document.querySelectorAll('#nbaPropBtns [data-nba-prop]').forEach(function (b) { if (b.classList.contains('active')) anyOn = true; });
    if (!anyOn) btn.classList.add('active');
    onFilter();
  }

  function onActivate() {
    wireDom();
    renderHeaderStats();
    renderCorrMeta();
    renderFilterLabels();
    if (!state._activated) { state._activated = true; reload().then(renderCorrMeta); return; }
    reload().then(renderCorrMeta);
  }

  window.nbaTab = {
    onActivate: onActivate,
    reload: function () { return reload().then(renderCorrMeta); },
    onCorrUpload: onCorrUpload,
    onRollback: onRollback,
    onFvUpload: onFvUpload,
    onFilter: onFilter,
    onPropBtn: onPropBtn,
    /* Exposed for the dev harness (Edit 8) + ad-hoc testing from DevTools. */
    _math: { amToDec: amToDec, decToAm: decToAm, jointFromPhi: jointFromPhi, enumerateCandidates: enumerateCandidates, applyEvFilter: applyEvFilter },
    _runPipeline: runPipeline,
    _state: state,
  };
})();
