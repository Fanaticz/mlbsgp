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

  function onActivate() {
    /* Always repaint header stats from cached state so the user sees
       something immediate, then kick off a background refresh. */
    renderHeaderStats();
    if (!state._activated) { state._activated = true; reload(); return; }
    reload();
  }

  window.nbaTab = { onActivate: onActivate, reload: reload, _state: state };
})();
