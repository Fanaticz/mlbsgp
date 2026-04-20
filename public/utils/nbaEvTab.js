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

  /* Drag/drop wiring for the correlations drop zone. Idempotent via the
     _wired flag — onActivate may fire many times but we only bind once. */
  var _wired = false;
  function wireDom() {
    if (_wired) return;
    var dz = document.getElementById('nbaCorrDrop');
    if (!dz) return;
    dz.addEventListener('click', function () { var i = document.getElementById('nbaCorrFile'); if (i) i.click(); });
    dz.addEventListener('dragover', function (e) { e.preventDefault(); dz.style.borderColor = 'var(--cyan)'; dz.style.background = 'rgba(34,211,238,.08)'; });
    dz.addEventListener('dragleave', function () { dz.style.borderColor = 'var(--b2)'; dz.style.background = 'var(--s2)'; });
    dz.addEventListener('drop', function (e) {
      e.preventDefault();
      dz.style.borderColor = 'var(--b2)';
      dz.style.background = 'var(--s2)';
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) postCorrFile(f);
    });
    _wired = true;
  }

  function onActivate() {
    wireDom();
    renderHeaderStats();
    renderCorrMeta();
    if (!state._activated) { state._activated = true; reload().then(renderCorrMeta); return; }
    reload().then(renderCorrMeta);
  }

  window.nbaTab = {
    onActivate: onActivate,
    reload: function () { return reload().then(renderCorrMeta); },
    onCorrUpload: onCorrUpload,
    onRollback: onRollback,
    _state: state,
  };
})();
