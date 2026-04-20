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
      /* foldedKey is computed once at index time so the enumeration
         hot path doesn't re-fold on every FV player read. Keys are
         whatever the FV source (OCR or synthetic) emitted raw — foldedKey
         is the normalized form used to join against correlations. */
      idx[p.player] = { player: p.player, foldedKey: foldKey(p.player), team: p.team || null, game: p.game || null, props: propMap };
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

  /* Canonical fold-key for player-name joins. Reuses the shared
     nameNormalize.foldKey (NFKD decomposition + strip combining marks +
     lowercase + strip non-alphanumerics). Same helper MLB uses to
     resolve Giménez/O'Hoppe-class mismatches. Defensive fallback just
     lowercases if the script isn't loaded for some reason. */
  function foldKey(name) {
    if (window.nameNormalize && typeof window.nameNormalize.foldKey === 'function') {
      return window.nameNormalize.foldKey(name);
    }
    return String(name == null ? '' : name).toLowerCase();
  }

  /* Build correlations.foldedByPlayer: foldedKey → [entry indices].
     Idempotent (safe to call on every reload). Collisions are merged
     by concat so a single folded key can point to entries from
     multiple original-name variants (e.g. "Luka Doncic" + "Luka Dončić"
     both folding to "luka doncic"). */
  function buildFoldedIndex(correlations) {
    if (!correlations || !correlations.by_player) return;
    var folded = {};
    Object.keys(correlations.by_player).forEach(function (rawName) {
      var key = foldKey(rawName);
      folded[key] = (folded[key] || []).concat(correlations.by_player[rawName]);
    });
    correlations.foldedByPlayer = folded;
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
    /* Prefer the folded index if present. Built lazily in runPipeline +
       populated on correlation-load so the hot path here stays branch-free.
       Raw-name lookup is kept as a fallback so pre-Phase-4 regression tests
       (which build fixtures with correlations.by_player only) still work. */
    var foldedIdx = correlations.foldedByPlayer || null;
    var players = Object.keys(fvIndex);
    for (var i = 0; i < players.length; i++) {
      var player = players[i];
      var fvP = fvIndex[player];
      var fk = (fvP && fvP.foldedKey) ? fvP.foldedKey : foldKey(player);
      var idxs = (foldedIdx && foldedIdx[fk]) || (correlations.by_player && correlations.by_player[player]) || [];
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
    /* CRITICAL: EV% at the top of the card reflects the FV-DERIVED joint,
       NOT the correlation-data p_joint. This mirrors the MLB fix:
       scoring a bet as "+EV" means our best estimate of the true
       probability (FV marginals + correlation) beats DK's implied price.
       p_joint stays visible on the card in the MODEL JOINT / EDGE row
       as diagnostic context ("what does the historical correlation data
       say?"), but the headline EV% is what tells the user to bet or skip.
       DO NOT revert to evPct = modelJoint * dkSgpDec − 1 — that is the
       bug that was just fixed on the MLB side. If fv_corr_prob is null
       (r_adj missing, degenerate FV), EV% is null and the card renders
       as '--' rather than silently falling back to the model path. */
    var evPct = (dkSgpDec != null && fvCorrProb != null) ? (fvCorrProb * dkSgpDec - 1) : null;
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

  /* ---------- Card renderer (Edit 6) ---------- */

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function fmtPct(p, digits) {
    if (p == null || !isFinite(p)) return '--';
    return (p * 100).toFixed(digits == null ? 1 : digits) + '%';
  }
  function fmtAm(a) {
    if (a == null || !isFinite(a)) return '--';
    return (a > 0 ? '+' : '') + Math.round(a);
  }
  function fmtEvSigned(ev) {
    if (ev == null || !isFinite(ev)) return '--';
    var pct = ev * 100;
    var sign = pct >= 0 ? '+' : '';
    return sign + pct.toFixed(1) + '%';
  }
  function sideLabel(side) { return side === 'over' ? 'Over' : side === 'under' ? 'Under' : side; }

  /* Render a single leg row inside a card. FV price, DK pair, base rate
     from correlation data. DK pair is informational — the sgp price is
     what drives EV. Missing DK single-leg prices render as "--" to keep
     alignment. */
  function renderLegRow(leg) {
    var dkPair = '';
    if (leg.dk_over_american != null || leg.dk_under_american != null) {
      dkPair = '[DK O' + fmtAm(leg.dk_over_american) + ' U' + fmtAm(leg.dk_under_american) + ']';
    } else {
      dkPair = '[DK --]';
    }
    return '<div class="nc-leg">' +
      '<span class="nc-lbl">' + esc(sideLabel(leg.side)) + ' ' + esc(leg.line) + ' ' + esc(leg.prop) + '</span>' +
      '<span class="nc-fv">FV ' + fmtAm(leg.fv_american) + '</span>' +
      '<span class="nc-dk">' + esc(dkPair) + '</span>' +
      '<span class="nc-base">' + fmtPct(leg.base_rate, 1) + '</span>' +
      '</div>';
  }

  function renderJointRow(c) {
    return '<div class="nc-joint">' +
      '<div class="nc-cell"><div class="nc-cval">' + fmtPct(c.model_joint, 1) + '</div><div class="nc-clbl">MODEL JOINT</div></div>' +
      '<div class="nc-cell"><div class="nc-cval">' + fmtPct(c.dk_implied, 1) + '</div><div class="nc-clbl">DK IMPLIED</div></div>' +
      '<div class="nc-cell"><div class="nc-cval" style="color:' + (c.edge_pp != null && c.edge_pp >= 0 ? 'var(--ac)' : 'var(--red)') + '">' + (c.edge_pp == null ? '--' : ((c.edge_pp >= 0 ? '+' : '') + c.edge_pp.toFixed(1) + 'pp')) + '</div><div class="nc-clbl">EDGE</div></div>' +
      '</div>';
  }

  function renderPricesRow(c) {
    return '<div class="nc-prices">' +
      '<span>DK SGP <span class="nc-pv">' + fmtAm(c.dk_sgp_american) + '</span></span>' +
      '<span>FV CORR <span class="nc-pv">' + fmtAm(c.fv_corr_american) + '</span></span>' +
      '</div>';
  }

  function renderStatsLine(c) {
    var e = c.entry || {};
    var parts = [];
    if (e.r_adj != null) parts.push('r ' + (e.r_adj >= 0 ? '+' : '') + e.r_adj.toFixed(2) + ' (adj)');
    if (e.p_value != null) parts.push('p=' + e.p_value.toFixed(2));
    if (e.n_games != null) parts.push('n=' + e.n_games);
    /* Surface the muted "rest-context" caveat from the NBA v1 hazards list
       once per card so the user carries the caveat into their bet decision. */
    var ctx = parts.join(' · ');
    return '<div class="nc-stats">' + esc(ctx) + '  <span style="color:var(--b2)">&middot; n=' + (e.n_games || '?') + ' doesn\'t distinguish rest contexts</span></div>';
  }

  function renderCard(c) {
    var ctx = [];
    if (c.team) ctx.push(c.team);
    if (c.game) ctx.push(c.game);
    var ctxLine = ctx.length ? ctx.join(' &middot; ') : '';
    var evColor = c.ev_pct != null && c.ev_pct >= 0 ? 'var(--ac)' : 'var(--red)';
    return '<div class="nba-card" id="nba-card-' + esc(c.id) + '">' +
      '<div class="nc-head">' +
        '<div><div class="nc-player">' + esc(c.player) + '</div><div class="nc-ctx">' + ctxLine + '</div></div>' +
        '<div class="nc-ev"><div class="v" style="color:' + evColor + '">' + fmtEvSigned(c.ev_pct) + '</div><div class="l">EV%</div></div>' +
      '</div>' +
      renderLegRow(c.leg1) +
      renderLegRow(c.leg2) +
      renderJointRow(c) +
      renderPricesRow(c) +
      renderStatsLine(c) +
      '<div class="nc-badges" data-nba-badges="' + esc(c.id) + '"></div>' +
      '</div>';
  }

  /* ---------- Badges (Edit 7) ---------- */
  /* Five spec-defined badges:
       [NBA]              info — always present, sport clarity
       [LOW p-val]        danger — p_value > 0.10
       [SMALL n]          warn — n_games < 25
       [OUTLIER]          danger — EV% > 100%
       [IMPLAUSIBLE GAP]  danger — |p_joint - p_independent| > 0.20
     (Phase 5 will add [QUESTIONABLE] / [OUT] when injury reports load.) */
  function computeBadges(c) {
    var out = [{ cls: 'info', text: 'NBA' }];
    var e = c.entry || {};
    if (e.p_value != null && e.p_value > 0.10) out.push({ cls: 'danger', text: 'LOW p-val' });
    if (e.n_games != null && e.n_games < 25) out.push({ cls: 'warn', text: 'SMALL n' });
    if (c.ev_pct != null && c.ev_pct > 1.0) out.push({ cls: 'danger', text: 'OUTLIER' });
    if (e.p_joint != null && e.p_independent != null && Math.abs(e.p_joint - e.p_independent) > 0.20) {
      out.push({ cls: 'danger', text: 'IMPLAUSIBLE GAP' });
    }
    return out;
  }

  function renderBadges(c) {
    return computeBadges(c).map(function (b) {
      return '<span class="nc-bdg ' + b.cls + '">' + esc(b.text) + '</span>';
    }).join('');
  }

  /* ---------- Sort + pagination (Edit 7) ---------- */
  /* Spec: EV% desc, tiebreak by p_value asc (lower p_value = higher
     confidence). Candidates without an EV% (missing DK SGP) sort last. */
  function sortCandidates(cands) {
    return cands.slice().sort(function (a, b) {
      var aEv = a.ev_pct == null ? -Infinity : a.ev_pct;
      var bEv = b.ev_pct == null ? -Infinity : b.ev_pct;
      if (aEv !== bEv) return bEv - aEv;
      var aP = (a.entry && a.entry.p_value) != null ? a.entry.p_value : 1;
      var bP = (b.entry && b.entry.p_value) != null ? b.entry.p_value : 1;
      return aP - bP;
    });
  }

  /* Load 30 cards at a time. "Load more" button appends the next batch
     without re-enumerating — cheap since enumeration already produced
     the full sorted list. */
  state.pageSize = 30;
  state.pageShown = 30;

  function onLoadMore() {
    state.pageShown += state.pageSize;
    renderResults();
  }

  function renderResults() {
    var body = document.getElementById('nbaBody');
    var count = document.getElementById('nbaCandCount');
    if (!body) return;
    var cands = sortCandidates(state.candidates || []);
    state.candidates = cands;
    if (count) count.textContent = cands.length + ' candidate' + (cands.length === 1 ? '' : 's');
    if (!state.correlations || state.correlations.status === 'empty') {
      body.innerHTML = '<div class="nba-empty">No NBA correlations data uploaded yet. Drop your xlsx above to begin.</div>';
      return;
    }
    if (!state.fv) {
      body.innerHTML = '<div class="nba-empty">Correlations loaded &middot; ' + (state.correlations.entries.length) + ' entries, ' + Object.keys(state.correlations.by_player).length + ' players.<br>Upload an NBA FV sheet above to see candidates.</div>';
      return;
    }
    if (!cands.length) {
      body.innerHTML = '<div class="nba-empty">No candidates matched the current filters. Loosen MIN EV%, MIN GAMES, or MAX P_VALUE to see more.</div>';
      return;
    }
    var shown = Math.min(state.pageShown, cands.length);
    var visible = cands.slice(0, shown);
    var html = '<div class="nba-cards">' + visible.map(function (c) {
      var cardHtml = renderCard(c);
      /* Inject badges after the placeholder div renderCard emitted. We
         render badges separately so card HTML stays a pure data->HTML
         transform without badge-computation dependencies. */
      var badgesHtml = renderBadges(c);
      return cardHtml.replace('<div class="nc-badges" data-nba-badges="' + esc(c.id) + '"></div>',
                              '<div class="nc-badges">' + badgesHtml + '</div>');
    }).join('') + '</div>';
    if (shown < cands.length) {
      html += '<div style="text-align:center;margin:16px 0"><button type="button" onclick="window.nbaTab.onLoadMore()" style="padding:8px 18px;font-family:Space Mono,monospace;font-size:11px;font-weight:600;border:1px solid var(--b2);background:var(--s2);color:var(--tx);border-radius:6px;cursor:pointer">LOAD MORE (' + (cands.length - shown) + ' remaining)</button></div>';
    }
    body.innerHTML = html;
  }

  /* Main pipeline entry. Rebuilds state.candidates from the current inputs.
     Cheap enough to call on every filter change — the FV + DK fetches are
     the expensive legs and those happen at upload time, not here. */
  /* FIRST-LOOK MODE: all filters are stripped. Every enumerated pair
     renders so we can see exactly what the pipeline produces without
     a filter-defaults argument over what's "really there". MIN EV%,
     MIN GAMES, MAX P_VALUE, prop multi-select, and confirmed-starter
     gates are all bypassed. Pagination still caps the render at 30
     cards — rendering 500+ cards at once would lag the tab.
     Restore filter gating once we see the distribution of actual edges
     on a real FV upload and know what defaults make sense. */
  var PERMISSIVE_FILTERS = {
    props: { 'Points': true, 'Rebounds': true, 'Assists': true, '3-Pointers Made': true },
    minGames: 0,
    maxPValue: 1.0,
    confirmedOnly: false,
  };

  /* Walk the FV index → correlations join once, record who matched and
     who didn't (for the diagnostic panel). Separate from enumeration so
     this count includes players whose entries don't happen to pass the
     FV leg-lookup in enumerateCandidates — i.e., we know the player is
     in correlations even if none of their entries produced a card. */
  function computeFunnel(correlations, fvIndex) {
    var foldedIdx = correlations && correlations.foldedByPlayer;
    var matched = [], unmatched = [];
    Object.keys(fvIndex || {}).forEach(function (rawName) {
      var fvP = fvIndex[rawName];
      var fk = (fvP && fvP.foldedKey) ? fvP.foldedKey : foldKey(rawName);
      var idxs = (foldedIdx && foldedIdx[fk]) || (correlations && correlations.by_player && correlations.by_player[rawName]) || [];
      if (idxs.length) matched.push(rawName); else unmatched.push(rawName);
    });
    return { fv_count: Object.keys(fvIndex || {}).length, matched: matched, unmatched: unmatched, enumerated: 0, dk_priced: 0 };
  }

  function runPipeline(opts) {
    state.pageShown = state.pageSize;
    if (!state.correlations || !state.fv) {
      state.candidates = []; state.candidatesAll = [];
      state.funnel = { fv_count: 0, matched: [], unmatched: [], enumerated: 0, dk_priced: 0 };
      if (typeof renderResults === 'function') renderResults();
      return;
    }
    /* Build the folded-player index once per correlations-load. runPipeline
       may fire many times (filter changes — now no-op, FV uploads, dev sim)
       and we don't want to rebuild it on each call. */
    if (!state.correlations.foldedByPlayer) buildFoldedIndex(state.correlations);
    var funnel = computeFunnel(state.correlations, state.fv);
    var all = enumerateCandidates(state.correlations, state.fv, PERMISSIVE_FILTERS, null);
    funnel.enumerated = all.length;
    funnel.dk_priced = all.filter(function (c) { return c.dk_sgp_american != null; }).length;
    state.funnel = funnel;
    state.candidatesAll = all;
    /* FIRST-LOOK MODE: no applyEvFilter — render everything. Sort + page
       limits happen in renderResults. */
    state.candidates = all;
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

  /* ---------- Dev synthetic harness (Edit 8) ----------
     Gated behind ?nbaDev=1 so it doesn't clutter the production UI. When
     clicked, invents FV prices for every (player, prop, line) mentioned
     in the uploaded correlations data + attaches a DK SGP American price
     to every correlation entry using a deterministic bump from model
     joint so the cards render with coherent numbers (edge_pp in a
     plausible −5pp…+15pp band). Used to produce the Phase 3 screenshot
     and to verify the render pipeline end-to-end before Phase 4 OCR +
     real DK wiring land. */
  function _devFvForPlayer(player, entries) {
    var props = {};
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      [e.leg1, e.leg2].forEach(function (leg) {
        if (!props[leg.prop]) props[leg.prop] = {};
        if (props[leg.prop][leg.line]) return;
        /* Synthesize symmetric FV around the base rate: if empirical hit
           rate ≈ 50%, FV should be near +100/-100. Skew slightly to keep
           numbers interesting. */
        var hr = leg === e.leg1 ? e.hit_rate_1 : e.hit_rate_2;
        var p = (hr == null) ? 0.5 : Math.max(0.1, Math.min(0.9, hr));
        var pOver = leg.side === 'over' ? p : 1 - p;
        var overAm = Math.round(pOver >= 0.5 ? -100 * pOver / (1 - pOver) : 100 * (1 - pOver) / pOver);
        var underAm = Math.round((1 - pOver) >= 0.5 ? -100 * (1 - pOver) / pOver : 100 * pOver / (1 - pOver));
        /* DK shades ~5% off FV on each side to model vig. */
        var shade = function (a, pct) { return a > 0 ? Math.round(a * (1 - pct)) : Math.round(a * (1 + pct)); };
        props[leg.prop][leg.line] = {
          stat: leg.prop,
          threshold: leg.line,
          over_fv: overAm,
          under_fv: underAm,
          over_dk_american: shade(overAm, 0.05),
          under_dk_american: shade(underAm, 0.05),
        };
      });
    }
    return { player: player, team: 'DEV', game: 'DEV vs SYN', props: props };
  }
  function _devBuildFvIndex(corr) {
    var idx = {};
    Object.keys(corr.by_player).forEach(function (player) {
      var entryIdxs = corr.by_player[player];
      var entries = entryIdxs.map(function (i) { return corr.entries[i]; });
      var p = _devFvForPlayer(player, entries);
      /* indexFvPlayers expects p.props as a nested map already — our
         _devFvForPlayer already emits the right shape, so pass it
         through the indexer to stay consistent with the OCR path. */
      idx[player] = { player: player, team: p.team, game: p.game, props: p.props };
    });
    return idx;
  }
  function _devAttachDkToEntries(corr) {
    corr.entries.forEach(function (e) {
      /* Set DK SGP ~5% worse than what model joint would price fairly,
         with some per-entry jitter so not every card shows identical
         edge. Scale by entry index hash to keep it deterministic. */
      if (!e.p_joint || e.p_joint <= 0) return;
      var fair = 1 / e.p_joint;
      var hash = 0;
      for (var i = 0; i < e.player.length; i++) hash = (hash * 31 + e.player.charCodeAt(i)) | 0;
      var jitter = ((hash & 0xff) / 255 - 0.5) * 0.15;  // ±7.5%
      var dkDec = fair * (1 + 0.06 + jitter);  // ~6% vig + jitter
      e.dk_sgp_american = decToAm(dkDec);
    });
  }
  function devSimulate() {
    if (!state.correlations || !state.correlations.entries || !state.correlations.entries.length) {
      setStatus('<span style="color:var(--red)">DEV: upload correlations xlsx first</span>');
      return;
    }
    _devAttachDkToEntries(state.correlations);
    state.fv = _devBuildFvIndex(state.correlations);
    setFvStatus('<span style="color:var(--ac2)">DEV: synthesized FV + DK for ' + Object.keys(state.fv).length + ' players</span>');
    runPipeline();
  }

  function onActivate() {
    wireDom();
    renderHeaderStats();
    renderCorrMeta();
    renderFilterLabels();
    /* Reveal the DEV harness button when the URL flag is set. Idempotent. */
    try {
      var u = new URL(window.location.href);
      if (u.searchParams.get('nbaDev') === '1') {
        var b = document.getElementById('nbaDevSimBtn'); if (b) b.style.display = '';
      }
    } catch (_) {}
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
    _renderCard: renderCard,
    _renderBadges: renderBadges,
    _computeBadges: computeBadges,
    _sortCandidates: sortCandidates,
    onLoadMore: onLoadMore,
    devSimulate: devSimulate,
    _state: state,
  };
})();
