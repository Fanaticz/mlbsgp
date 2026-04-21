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
      /* After enumeration produces state.candidatesAll, kick off the
         async DK pricing request. fetchDkPricing merges prices back
         into the existing candidates (no re-enumeration) and triggers
         a second render. Synthetic dev path (devSimulate) skips this
         since it pre-attaches dk_sgp_american on every entry. */
      fetchDkPricing();
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
    /* FIRST-LOOK MODE: hide the filter bar entirely. Dead controls
       would just confuse. Restoring is a one-line removal once defaults
       are tuned from the first-upload distribution. */
    var fb = document.getElementById('nbaFilterBar'); if (fb) fb.style.display = 'none';
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
  /* Canonical key for a (prop, side) leg pair, order-invariant. Correlation
     is symmetric between leg1/leg2, so ('Points','over','Rebounds','over')
     and ('Rebounds','over','Points','over') must produce the same key —
     otherwise the pair-index would need two lookups per query. */
  function _legKey(prop, side) { return prop + '|' + side; }
  function pairKey(propA, sideA, propB, sideB) {
    var a = _legKey(propA, sideA), b = _legKey(propB, sideB);
    return a < b ? a + '||' + b : b + '||' + a;
  }

  /* Build a line-ignorant lookup: `foldedPlayer###pairKey` →
     [entry indices]. Each bucket holds every correlation entry that
     shares that (prop, side) pair for that player, regardless of line.
     Called lazily from enumerateCandidates so pre-existing fixtures
     that only populate by_player still work without modification. */
  function buildPairIndex(correlations) {
    if (!correlations || !correlations.entries) return;
    var idx = {};
    correlations.entries.forEach(function (e, i) {
      if (!e || !e.leg1 || !e.leg2 || !e.player) return;
      var fk = foldKey(e.player);
      var key = fk + '###' + pairKey(e.leg1.prop, e.leg1.side, e.leg2.prop, e.leg2.side);
      (idx[key] = idx[key] || []).push(i);
    });
    correlations.pairIndex = idx;
  }

  /* Flatten a FV player's props map into a list of per-side legs:
     [{ stat, threshold, side, fv_american, dk_over/under_american }, ...].
     Sides with null fv_american are dropped. */
  function _flattenFvLegs(fvP) {
    var legs = [];
    var props = (fvP && fvP.props) || {};
    Object.keys(props).forEach(function (stat) {
      Object.keys(props[stat]).forEach(function (thresh) {
        var row = props[stat][thresh];
        var th = Number(thresh);
        if (row.over_fv != null) legs.push({ stat: stat, threshold: th, side: 'over', fv_american: row.over_fv, dk_over_american: row.over_dk_american || null, dk_under_american: row.under_dk_american || null });
        if (row.under_fv != null) legs.push({ stat: stat, threshold: th, side: 'under', fv_american: row.under_fv, dk_over_american: row.over_dk_american || null, dk_under_american: row.under_dk_american || null });
      });
    });
    return legs;
  }

  /* From a list of candidate correlation entries sharing the same
     (prop, side) pair for this player, pick the one whose lines are
     closest to (fvA.threshold, fvB.threshold). Sum-of-absolute-line-
     differences. Tiebreak: highest n_games. Returns { entry, exact,
     corrA_line, corrB_line } or null. */
  function pickBestEntry(entries, idxs, fvA, fvB) {
    var best = null, bestDrift = Infinity, bestN = -1;
    for (var i = 0; i < idxs.length; i++) {
      var e = entries[idxs[i]];
      if (!e) continue;
      /* The entry's leg1/leg2 order is not guaranteed to match fvA/fvB.
         Resolve which entry leg corresponds to fvA vs fvB by prop+side. */
      var corrA, corrB;
      if (e.leg1.prop === fvA.stat && e.leg1.side === fvA.side) { corrA = e.leg1; corrB = e.leg2; }
      else if (e.leg2.prop === fvA.stat && e.leg2.side === fvA.side) { corrA = e.leg2; corrB = e.leg1; }
      else continue; // defensive — pair-index shouldn't emit mismatches
      var drift = Math.abs(corrA.line - fvA.threshold) + Math.abs(corrB.line - fvB.threshold);
      var n = e.n_games || 0;
      if (drift < bestDrift || (drift === bestDrift && n > bestN)) {
        bestDrift = drift; bestN = n;
        best = { entry: e, exact: drift === 0, corrA_line: corrA.line, corrB_line: corrB.line };
      }
    }
    return best;
  }

  /* Line-ignorant enumeration. For each FV player, iterate all unordered
     pairs of FV legs with different stats (6 × 4 = 24 combos when all 4
     supported props are on the sheet). For each pair, look up matching
     correlation entries via the pair index, pick the closest-line entry,
     build a candidate that carries the FV lines (what the user bets)
     plus the correlation lines (for the LINE DRIFT display).

     Filter semantics unchanged — filters apply AFTER entry selection so
     the closest-line pick isn't distorted by n_games/p_value gates. */
  function enumerateCandidates(correlations, fvIndex, filters, confirmedSet) {
    var out = [];
    if (!correlations || !correlations.entries || !fvIndex) return out;
    if (!correlations.pairIndex) buildPairIndex(correlations);
    var pairIdx = correlations.pairIndex || {};
    Object.keys(fvIndex).forEach(function (rawName) {
      var fvP = fvIndex[rawName];
      var foldedPlayer = fvP.foldedKey || foldKey(rawName);
      var legs = _flattenFvLegs(fvP);
      for (var i = 0; i < legs.length; i++) {
        for (var j = i + 1; j < legs.length; j++) {
          var a = legs[i], b = legs[j];
          if (a.stat === b.stat) continue; // same-stat pairs aren't useful
          if (!filters.props[a.stat] || !filters.props[b.stat]) continue;
          var key = foldedPlayer + '###' + pairKey(a.stat, a.side, b.stat, b.side);
          var idxs = pairIdx[key];
          if (!idxs || !idxs.length) continue;
          var picked = pickBestEntry(correlations.entries, idxs, a, b);
          if (!picked) continue;
          var e = picked.entry;
          if (e.n_games < filters.minGames) continue;
          if (e.p_value > filters.maxPValue) continue;
          if (filters.confirmedOnly && confirmedSet && !confirmedSet.has(rawName)) continue;
          out.push(buildCandidate(rawName, fvP, e, a, b, picked));
        }
      }
    });
    return out;
  }

  function buildCandidate(player, fvPlayer, entry, fvA, fvB, picked) {
    var fvDec1 = amToDec(fvA.fv_american);
    var fvDec2 = amToDec(fvB.fv_american);
    var p1 = fvDec1 ? 1 / fvDec1 : null;
    var p2 = fvDec2 ? 1 / fvDec2 : null;
    var fvCorrProb = jointFromPhi(entry.r_adj, p1, p2);
    var modelJoint = entry.p_joint;
    var dkSgpAm = entry.dk_sgp_american != null ? entry.dk_sgp_american : null;
    var dkSgpDec = dkSgpAm != null ? amToDec(dkSgpAm) : null;
    var dkImplied = dkSgpDec ? 1 / dkSgpDec : null;
    /* CRITICAL (regression-guarded by nba_ev_formula_check.js): EV% at
       the top of the card reflects the FV-DERIVED joint, NOT the
       correlation-data p_joint. DO NOT change to modelJoint * dkSgpDec
       - 1 — that's the bug fixed in a5b5442.  The line-ignorant matching
       change affects what we DISPLAY (MODEL JOINT / EDGE / corr lines),
       not how EV is computed. EV remains FV-based, so cards with the
       [LINE DRIFT] badge still have a trustworthy EV% headline. */
    var evPct = (dkSgpDec != null && fvCorrProb != null) ? (fvCorrProb * dkSgpDec - 1) : null;
    var edgePp = (dkImplied != null) ? (modelJoint - dkImplied) * 100 : null;
    /* Figure out which correlation leg matches fvA vs fvB so we can
       attribute hit rates correctly. Same resolution pickBestEntry
       did, repeated here because we don't pass the matched-leg objects
       through — just the lines. */
    var corrHr1 = (entry.leg1.prop === fvA.stat && entry.leg1.side === fvA.side) ? entry.hit_rate_1 : entry.hit_rate_2;
    var corrHr2 = (entry.leg1.prop === fvA.stat && entry.leg1.side === fvA.side) ? entry.hit_rate_2 : entry.hit_rate_1;
    var corrLineA = (picked && picked.corrA_line != null) ? picked.corrA_line : null;
    var corrLineB = (picked && picked.corrB_line != null) ? picked.corrB_line : null;
    var exactMatch = !!(picked && picked.exact);
    return {
      id: player + '|' + fvA.stat + fvA.threshold + fvA.side + '|' + fvB.stat + fvB.threshold + fvB.side,
      player: player,
      team: fvPlayer.team,
      game: fvPlayer.game,
      leg1: { prop: fvA.stat, side: fvA.side, line: fvA.threshold, fv_american: fvA.fv_american, dk_over_american: fvA.dk_over_american, dk_under_american: fvA.dk_under_american, base_rate: corrHr1 },
      leg2: { prop: fvB.stat, side: fvB.side, line: fvB.threshold, fv_american: fvB.fv_american, dk_over_american: fvB.dk_over_american, dk_under_american: fvB.dk_under_american, base_rate: corrHr2 },
      entry: entry,
      dk_sgp_american: dkSgpAm,
      dk_sgp_decimal: dkSgpDec,
      dk_implied: dkImplied,
      fv_corr_prob: fvCorrProb,
      fv_corr_american: fvCorrProb ? decToAm(1 / fvCorrProb) : null,
      model_joint: modelJoint,
      edge_pp: edgePp,
      ev_pct: evPct,
      /* Line-drift metadata. Exact match when corr lines == FV lines.
         Approx match otherwise — UI surfaces with a LINE DRIFT badge. */
      corr_line1: corrLineA,
      corr_line2: corrLineB,
      exact_line_match: exactMatch,
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
  /* Convert a probability (0 < p < 1) to American odds. Used for
     MODEL JOINT / DK IMPLIED / Both-hit-row displays where we were
     previously rendering "42.0%" — American is the native unit for
     bettors comparing against DK's posted prices. Returns "--" on
     degenerate inputs (null, out-of-range) so the render keeps its
     placeholder instead of throwing. */
  function fmtAmFromProb(p) {
    if (p == null || !isFinite(p) || p <= 0 || p >= 1) return '--';
    var dec = 1 / p;
    if (dec >= 2) return '+' + Math.round((dec - 1) * 100);
    return '-' + Math.round(100 / (dec - 1));
  }
  function fmtEvSigned(ev) {
    if (ev == null || !isFinite(ev)) return '--';
    var pct = ev * 100;
    var sign = pct >= 0 ? '+' : '';
    return sign + pct.toFixed(1) + '%';
  }
  function sideLabel(side) { return side === 'over' ? 'Over' : side === 'under' ? 'Under' : side; }

  /* Render a single leg row inside a card. FV price + DK pair, no
     per-leg base rate column. Base rate used to show the correlation
     entry's hit_rate for this leg, but with line-ignorant matching the
     correlation leg's line may differ from the FV line — rendering
     "Over 22.5 Points ... 55.4%" would mislead the user (the 55.4%
     was measured at a different line). Drift context lives on the
     "Both hit" row instead. */
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
      '</div>';
  }

  /* "Both hit" summary line between the leg rows and the DK-SGP/FV-CORR
     price line. When lines drift (exact_line_match === false), shows
     "Both hit (corr at 21.5/5.5, n=28)" so the user can see the
     correlation lines the model joint was measured against vs the FV
     lines they're actually betting. On exact matches, drops the
     "corr at ..." clause so it reads "Both hit (n=28)". Right-side
     value is MODEL JOINT — same number as the bottom diagnostic grid,
     surfaced here for in-context readability. */
  function renderBothHitLine(c) {
    var e = c.entry || {};
    var inner = [];
    if (c.exact_line_match === false && c.corr_line1 != null && c.corr_line2 != null) {
      inner.push('corr at ' + c.corr_line1 + '/' + c.corr_line2);
    }
    if (e.n_games != null) inner.push('n=' + e.n_games);
    var label = 'Both hit' + (inner.length ? ' (' + inner.join(', ') + ')' : '');
    return '<div class="nc-both">' +
      '<span class="nc-both-lbl">' + esc(label) + '</span>' +
      '<span class="nc-both-val">' + fmtAmFromProb(c.model_joint) + ' <span style="color:var(--mu);font-size:10px;letter-spacing:.4px">MODEL</span></span>' +
      '</div>';
  }

  function renderJointRow(c) {
    return '<div class="nc-joint">' +
      '<div class="nc-cell"><div class="nc-cval">' + fmtAmFromProb(c.model_joint) + '</div><div class="nc-clbl">MODEL JOINT</div></div>' +
      '<div class="nc-cell"><div class="nc-cval">' + fmtAmFromProb(c.dk_implied) + '</div><div class="nc-clbl">DK IMPLIED</div></div>' +
      '<div class="nc-cell"><div class="nc-cval" style="color:' + (c.edge_pp != null && c.edge_pp >= 0 ? 'var(--ac)' : 'var(--red)') + '">' + (c.edge_pp == null ? '--' : ((c.edge_pp >= 0 ? '+' : '') + c.edge_pp.toFixed(1) + 'pp')) + '</div><div class="nc-clbl">EDGE</div></div>' +
      '</div>';
  }

  function renderPricesRow(c) {
    /* Surface DK-pricing failure inline so the card reads as a "has data
       but no DK" cell instead of ambiguous "--" that could also mean no
       FV_CORR. Missing reason comes from the server's `missing[]` list
       (first element is usually enough context). */
    var dkLine = '<span>DK SGP <span class="nc-pv">' + fmtAm(c.dk_sgp_american) + '</span></span>';
    if (c.dk_sgp_american == null && c.dk_missing) {
      var reason = Array.isArray(c.dk_missing) && c.dk_missing.length ? c.dk_missing[0] : 'DK price unavailable';
      dkLine = '<span style="color:var(--mu)">DK SGP <span class="nc-pv" style="color:var(--mu)">--</span> <span style="font-size:10px">' + esc(reason) + '</span></span>';
    }
    return '<div class="nc-prices">' +
      dkLine +
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
      renderBothHitLine(c) +
      renderPricesRow(c) +
      renderStatsLine(c) +
      '<div class="nc-badges" data-nba-badges="' + esc(c.id) + '"></div>' +
      /* MODEL JOINT / DK IMPLIED / EDGE diagnostic grid lives at the
         bottom of the card so the "Both hit" line up top is the
         prominent model-joint surface and this strip is explicitly
         "supporting detail". Keeps the top half focused on the FV-based
         decision (EV% headline + FV prices + model context). */
      renderJointRow(c) +
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
    /* Line-drift flag — fires when the selected correlation entry's
       lines differ from the FV lines the user is actually betting. EV%
       is still FV-based (trustworthy), but MODEL JOINT / EDGE use the
       entry as a line-approximation — surface that caveat explicitly. */
    if (c.exact_line_match === false && c.corr_line1 != null && c.corr_line2 != null) {
      var fvLines = c.leg1.line + '/' + c.leg2.line;
      var corrLines = c.corr_line1 + '/' + c.corr_line2;
      out.push({
        cls: 'warn',
        text: 'LINE DRIFT',
        title: 'Correlation entry measured at lines ' + corrLines +
               '. Tonight\'s bet is at ' + fvLines +
               '. MODEL JOINT and EDGE use the historical correlation as approximation — treat as informational, not ground truth. EV% is computed from your FV directly and remains accurate.'
      });
    }
    return out;
  }

  function renderBadges(c) {
    return computeBadges(c).map(function (b) {
      /* esc() handles the quote-escape needed for title attributes
         (replaces " with &quot;). Tooltip visible in all major browsers
         via the native title-attr hover behavior. */
      var title = b.title ? ' title="' + esc(b.title) + '"' : '';
      return '<span class="nc-bdg ' + b.cls + '"' + title + '>' + esc(b.text) + '</span>';
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

  /* Pipeline funnel diagnostic (first-look mode companion). Renders
     FV parse count, FV ∩ correlations match count + unmatched player
     list, pairs enumerated, pairs DK-priced, pairs rendered. Collapsed
     by default when no FV has been uploaded — nothing meaningful to
     show. Matches #tmevDiagPanel s1/b1 visual vocabulary. */
  function renderDiagnostics() {
    var panel = document.getElementById('nbaDiag');
    if (!panel) return;
    var f = state.funnel;
    if (!f || !state.fv) { panel.style.display = 'none'; panel.innerHTML = ''; return; }
    panel.style.display = '';
    var unmatchedList = '';
    if (f.unmatched.length) {
      var shown = f.unmatched.slice(0, 10);
      var more = f.unmatched.length > shown.length ? '<li style="color:var(--b2)">…and ' + (f.unmatched.length - shown.length) + ' more</li>' : '';
      unmatchedList =
        '<div style="margin-top:10px"><div style="font-size:10px;color:var(--ac2);letter-spacing:.6px;margin-bottom:4px">UNMATCHED FV PLAYERS (' + f.unmatched.length + ')</div>' +
        '<ul style="margin:0 0 0 16px;padding:0;font-size:11px;color:var(--tx);line-height:1.7">' +
        shown.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + more + '</ul></div>';
    }
    /* Flag zero DK pricing separately. The Phase 3 dev harness attaches
       DK on demand; Phase 4 OCR + Phase 5 DK wiring populate on real
       uploads. Distinguishing "pairs enumerated but never priced" from
       "pairs never enumerated" is the whole point of this funnel. */
    var dkHint = (f.enumerated > 0 && f.dk_priced === 0)
      ? ' <span style="color:var(--red)">← DK not wired (run DEV:SIM or wait for live pipeline)</span>' : '';
    var rendered = Math.min(state.pageShown || state.pageSize || 30, (state.candidates || []).length);
    /* Exact/approx split surfaced inline so the user sees how much
       candidate volume comes from line approximation vs exact match.
       In exact-only mode, the "Rendered" denominator switches to
       exact_match (since approx are post-filtered out). */
    var exactN = (f.exact_match != null) ? f.exact_match : 0;
    var approxN = (f.approx_match != null) ? f.approx_match : 0;
    var renderedDenom = state.exactLineOnly ? exactN : f.enumerated;
    var checked = state.exactLineOnly ? ' checked' : '';
    panel.innerHTML =
      '<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:10px">' +
        '<span style="font-size:11px;color:var(--cyan);font-weight:700;letter-spacing:.5px">PIPELINE FUNNEL</span>' +
        '<span style="font-size:10px;color:var(--ac2)">FIRST-LOOK MODE · filters stripped</span>' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:auto 1fr;gap:4px 16px;font-size:11px;color:var(--tx)">' +
        '<div style="color:var(--mu)">FV players parsed</div><div>' + f.fv_count + '</div>' +
        '<div style="color:var(--mu)">FV ∩ Correlations match</div><div>' + f.matched.length + ' <span style="color:var(--b2)">/ ' + f.fv_count + '</span></div>' +
        '<div style="color:var(--mu)">Pairs enumerated</div><div>' + f.enumerated + '</div>' +
        '<div style="color:var(--mu);padding-left:14px">&middot; Exact line match</div><div>' + exactN + '</div>' +
        '<div style="color:var(--mu);padding-left:14px">&middot; Approximate line match</div><div>' + approxN + '</div>' +
        '<div style="color:var(--mu)">DK priced</div><div>' + f.dk_priced + dkHint + '</div>' +
        (f.dk_failures ? '<div style="color:var(--mu);padding-left:14px">&middot; DK pricing failures</div><div style="color:var(--ac2)">' + f.dk_failures + '</div>' : '') +
        '<div style="color:var(--mu)">Rendered</div><div>' + rendered + ' <span style="color:var(--b2)">/ ' + renderedDenom + (state.exactLineOnly ? ' exact' : ' enumerated') + '</span></div>' +
      '</div>' +
      '<label style="display:inline-flex;align-items:center;gap:8px;margin-top:12px;font-size:11px;color:var(--tx);cursor:pointer">' +
        '<input type="checkbox" id="nbaExactLineOnly"' + checked + ' onchange="window.nbaTab&amp;&amp;window.nbaTab.onExactLineToggle(this.checked)" style="cursor:pointer">' +
        '<span>Exact line match only <span style="color:var(--mu)">(hide ' + approxN + ' approximate-match candidate' + (approxN === 1 ? '' : 's') + ')</span></span>' +
      '</label>' +
      unmatchedList;
  }

  function renderResults() {
    var body = document.getElementById('nbaBody');
    var count = document.getElementById('nbaCandCount');
    if (!body) return;
    var cands = sortCandidates(state.candidates || []);
    state.candidates = cands;
    /* Count banner shown on the (now-hidden) filter bar AND in the
       top-right of the card list. Renders "Showing X of Y" so the user
       sees both the paginated-render count and the total enumerated set. */
    var rendered = Math.min(state.pageShown || state.pageSize || 30, cands.length);
    if (count) count.textContent = 'Showing ' + rendered + ' of ' + cands.length + ' enumerated';
    renderDiagnostics();
    if (!state.correlations || state.correlations.status === 'empty') {
      body.innerHTML = '<div class="nba-empty">No NBA correlations data uploaded yet. Drop your xlsx above to begin.</div>';
      return;
    }
    if (!state.fv) {
      body.innerHTML = '<div class="nba-empty">Correlations loaded &middot; ' + (state.correlations.entries.length) + ' entries, ' + Object.keys(state.correlations.by_player).length + ' players.<br>Upload an NBA FV sheet above to see candidates.</div>';
      return;
    }
    if (!cands.length) {
      /* FIRST-LOOK MODE: filters are stripped, so zero candidates means
         the pipeline itself produced nothing — not a too-tight filter.
         Point the user at the diagnostic funnel instead of suggesting
         they loosen sliders that don't exist in this mode. */
      body.innerHTML = '<div class="nba-empty">No pairs enumerated from the current FV × correlations join. See the PIPELINE FUNNEL above for where the pipeline dropped out.</div>';
      return;
    }
    var shown = Math.min(state.pageShown, cands.length);
    var visible = cands.slice(0, shown);
    /* Count banner at the top of the card grid — visible replacement for
       the filter-bar count which is hidden in first-look mode. */
    var countBanner =
      '<div style="display:flex;align-items:baseline;gap:8px;margin:4px 0 10px;font-family:Space Mono,monospace;font-size:11px">' +
        '<span style="color:var(--cyan);font-weight:700;letter-spacing:.4px">SHOWING ' + shown + ' OF ' + cands.length + '</span>' +
        '<span style="color:var(--mu)">enumerated candidates &middot; sorted by EV% desc</span>' +
      '</div>';
    var html = countBanner + '<div class="nba-cards">' + visible.map(function (c) {
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
    /* Split enumerated count by line-match quality so the diagnostic
       panel can show "exact vs approximate" without another pass. */
    funnel.exact_match = all.filter(function (c) { return c.exact_line_match === true; }).length;
    funnel.approx_match = all.length - funnel.exact_match;
    state.funnel = funnel;
    state.candidatesAll = all;
    /* FIRST-LOOK MODE: no applyEvFilter — render every enumerated pair
       (sort + page limits happen in renderResults). The exact-line-only
       toggle post-filters candidatesAll without re-enumerating; onExact-
       LineToggle short-circuits runPipeline for cheap re-renders. */
    state.candidates = state.exactLineOnly
      ? all.filter(function (c) { return c.exact_line_match === true; })
      : all;
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
  /* Exact-line-match post-filter. Orthogonal to state.filters — those are
     bypassed entirely in first-look mode, but this toggle is always
     meaningful (even in first-look) because it's about match quality,
     not edge/volume tuning. Default OFF so all enumerated pairs render. */
  state.exactLineOnly = false;

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

  /* ---------- DK pricing (async, merges into state.candidatesAll) ----------
     fetchDkPricing POSTs the enumerated candidate list to the NBA SGP
     pricing endpoint. Response comes back with per-candidate dk_odds +
     per-leg over/under American prices, which mergeDkPrices writes
     into the existing candidate objects and recomputes ev_pct/edge_pp.
     Not called from runPipeline — filter changes shouldn't re-hit DK. */
  function _parseAmerican(s) {
    if (s == null) return null;
    var m = String(s).replace(/−/g, '-').match(/([+-]?\d+)/);
    if (!m) return null;
    var n = parseInt(m[1], 10);
    return isFinite(n) ? n : null;
  }

  function mergeDkPrices(dkJson) {
    var byId = {};
    (dkJson.results || []).forEach(function (r) { byId[r.id] = r; });
    (state.candidatesAll || []).forEach(function (c) {
      var r = byId[c.id];
      if (!r) return;
      if (!r.matched) {
        c.dk_missing = r.missing || ['dk:unmatched'];
        return;
      }
      c.dk_missing = null;
      c.dk_sgp_american = _parseAmerican(r.dk_odds);
      c.dk_sgp_decimal = r.dk_decimal;
      c.dk_implied = (c.dk_sgp_decimal && c.dk_sgp_decimal > 0) ? 1 / c.dk_sgp_decimal : null;
      if (r.leg_1_over_american  != null) c.leg1.dk_over_american  = r.leg_1_over_american;
      if (r.leg_1_under_american != null) c.leg1.dk_under_american = r.leg_1_under_american;
      if (r.leg_2_over_american  != null) c.leg2.dk_over_american  = r.leg_2_over_american;
      if (r.leg_2_under_american != null) c.leg2.dk_under_american = r.leg_2_under_american;
      /* Recompute EV% + EDGE now that we have a real dk_sgp_decimal.
         EV% stays FV-based per the a5b5442 fix — fv_corr_prob × dkSgpDec
         - 1, NOT model_joint × dkSgpDec - 1. */
      c.ev_pct  = (c.dk_sgp_decimal != null && c.fv_corr_prob != null)
        ? (c.fv_corr_prob * c.dk_sgp_decimal - 1) : null;
      c.edge_pp = (c.dk_implied != null && c.model_joint != null)
        ? (c.model_joint - c.dk_implied) * 100 : null;
    });
    /* Refresh funnel stats so the diagnostic panel reflects the new
       priced/failed split without requiring a full re-enumeration. */
    if (state.funnel) {
      var priced = (state.candidatesAll || []).filter(function (c) { return c.dk_sgp_american != null; }).length;
      state.funnel.dk_priced = priced;
      state.funnel.dk_failures = (state.funnel.enumerated || 0) - priced;
    }
  }

  function fetchDkPricing() {
    if (!state.candidatesAll || !state.candidatesAll.length) return;
    setFvStatus('<span style="color:var(--ac2)">Pricing ' + state.candidatesAll.length + ' candidates against DraftKings...</span>');
    var payload = { candidates: state.candidatesAll.map(function (c) {
      return {
        id: c.id, player: c.player, team: c.team, game: c.game,
        prop1: c.leg1.prop, side1: c.leg1.side, line1: c.leg1.line,
        prop2: c.leg2.prop, side2: c.leg2.side, line2: c.leg2.line,
      };
    }) };
    fetch('/api/dk/find-sgps-nba', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload),
    }).then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error && !j.results) {
          setFvStatus('<span style="color:var(--red)">DK pricing error: ' + j.error + '</span>');
          return;
        }
        mergeDkPrices(j);
        var priced = (state.funnel && state.funnel.dk_priced) || 0;
        var total  = state.candidatesAll.length;
        var cached = j.cached ? ' <span style="color:var(--mu)">(cached ' + (j.cache_age_s || 0) + 's)</span>' : '';
        var trunc  = j.truncated ? ' <span style="color:var(--ac2)">(pricing truncated)</span>' : '';
        setFvStatus('<span style="color:var(--ac)">&#10003; DK priced ' + priced + '/' + total + ' candidates</span>' + cached + trunc);
        if (typeof renderResults === 'function') renderResults();
      })
      .catch(function (e) { setFvStatus('<span style="color:var(--red)">DK pricing failed: ' + (e.message || e) + '</span>'); });
  }

  /* Exact-line-only toggle. Fires from the checkbox inside #nbaDiag.
     Post-filters state.candidatesAll without re-running enumeration
     (enumeration already produced per-candidate exact_line_match
     flags). Resets pagination so toggling doesn't leave stale pages. */
  function onExactLineToggle(checked) {
    state.exactLineOnly = !!checked;
    var all = state.candidatesAll || [];
    state.candidates = state.exactLineOnly
      ? all.filter(function (c) { return c.exact_line_match === true; })
      : all;
    state.pageShown = state.pageSize;
    if (typeof renderResults === 'function') renderResults();
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
    onExactLineToggle: onExactLineToggle,
    devSimulate: devSimulate,
    _state: state,
  };
})();
