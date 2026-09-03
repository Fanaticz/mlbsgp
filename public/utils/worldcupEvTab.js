/* worldcupEvTab.js — Soccer SGP +EV, one-button "scrape all" model.
   Flow: POST /api/soccer/scrape-all → server sweeps every major-league game's
   Pinnacle combo fair lines (devigged) vs DK's real 2-leg SGP price → one flat
   EV-ranked list. No league/game picking. */
(function () {
  'use strict';

  var FAMS = ['btts_total', 'btts_winner', 'winner_total', 'oddeven_total', 'ht_ft'];
  var FAM_LABEL = {
    btts_total: 'BTTS×Total', btts_winner: 'BTTS×Winner',
    winner_total: 'Winner×Total', oddeven_total: 'Odd/Even×Total', ht_ft: 'HT/FT',
  };
  var MAX_ROWS = 100;

  var state = {
    rows: [], summary: null, scanning: false,
    enabledFams: { btts_total: true, btts_winner: true, winner_total: true, oddeven_total: true, ht_ft: true },
    matchedOnly: false,   // DK is often blocked; default to showing the Pinnacle board
    maxOddsCap: true,
    sgpOnly: true,
  };

  function $(id) { return document.getElementById(id); }
  function setStatus(msg, isErr) {
    var el = $('wcStatus');
    if (el) { el.textContent = msg || ''; el.style.color = isErr ? 'var(--red, #f87171)' : 'var(--mu)'; }
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function fmtAm(o) {
    if (o == null || o === '') return '—';
    var n = (typeof o === 'number') ? o : parseInt(String(o).replace(/−/g, '-').replace(/[^0-9+-]/g, ''), 10);
    if (isNaN(n)) return esc(String(o));
    return (n > 0 ? '+' : '') + n;
  }
  function amNum(o) {
    if (o == null || o === '') return null;
    var n = (typeof o === 'number') ? o : parseInt(String(o).replace(/−/g, '-').replace(/[^0-9+-]/g, ''), 10);
    return isNaN(n) ? null : n;
  }

  /* ---- the one button ---- */

  function scrapeAll() {
    if (state.scanning) return;
    state.scanning = true;
    var btn = $('wcScrapeBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'SCRAPING…'; }
    setStatus('Scraping all major-league soccer SGPs (Pinnacle fair lines + DK) — this can take up to ~2 min…');
    fetch('/api/soccer/scrape-all', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ sgp_only: state.sgpOnly }),
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        state.scanning = false;
        if (btn) { btn.disabled = false; btn.textContent = '↻ SCRAPE SGPS'; }
        if (j.error) { setStatus('Scrape failed: ' + j.error, true); return; }
        state.rows = j.rows || [];
        state.summary = j.summary || null;
        var s = state.summary || {};
        setStatus('Swept ' + (s.leagues_swept || 0) + ' leagues · ' + (s.games_with_candidates || 0) +
          ' games · ' + (s.rows || 0) + ' combos' + (j.cached ? ' (cached ' + j.cache_age_s + 's)' : '') + '.');
        render();
      })
      .catch(function (e) {
        state.scanning = false;
        if (btn) { btn.disabled = false; btn.textContent = '↻ SCRAPE SGPS'; }
        setStatus('Scrape failed: ' + e.message, true);
      });
  }

  /* ---- DK pricing status (from the sweep summary) ---- */

  function renderDiag() {
    var el = $('wcDiag');
    if (!el) return;
    var s = state.summary;
    if (!s) { el.style.display = 'none'; el.textContent = ''; return; }
    var diag = s.sgp_price_diag || {};
    var http = diag.http || {};
    var n403 = (http['403'] || 0) + (http['429'] || 0);
    var level, msg;
    var skipped = diag.skipped_blocked || 0;
    if (s.dk_priced_any) {
      level = 'ok';
      msg = '✅ DK SGP pricing live — priced ' + (diag.ok || 0) + ' combo(s). EV% is DK vs Pinnacle fair.';
      // Partial pricing: a few got through, then Akamai started 403ing and the
      // breaker stopped the rest. Say so, or "priced 2 combo(s)" out of a
      // hundred rows looks like the other 98 simply didn't match.
      if (diag.breaker_tripped || skipped > 0) {
        level = 'warn';
        msg += ' Then DK started refusing (Akamai 403) and pricing stopped early, so ' + skipped +
          ' combo(s) went unpriced — this IP is rate-limited. A residential proxy (DK_PROXY) prices the full board.';
      }
    } else if (s.dk_blocked || n403 > 0 || skipped > 0) {
      var abck = diag.abck || 'absent';
      if (abck === 'validated') {
        level = 'warn';
        msg = '⚠ DK blocked this server\'s IP (Akamai 403) despite a validated cookie — showing Pinnacle fair lines only. ' +
          'A residential proxy for DK is the remaining lever.';
        if (diag.breaker_tripped) {
          msg += ' (Stopped after ' + n403 + ' refused price call(s) instead of retrying every combo, so the scrape returns fast.)';
        }
      } else {
        level = 'err';
        msg = '⛔ DK unreachable (Akamai 403, _abck ' + abck + ') — showing Pinnacle fair lines only. ' +
          'Set/refresh the DK cookie below (copy(document.cookie) on draftkings.com), then Scrape again.';
      }
    } else {
      level = 'ok';
      msg = 'ℹ Pinnacle fair board loaded. Turn off SGP-ONLY or set a DK cookie to fill the DK column.';
    }
    var colors = {
      ok: { bg: 'rgba(34,197,94,.10)', bd: 'var(--ac)', fg: 'var(--ac)' },
      warn: { bg: 'rgba(234,179,8,.10)', bd: '#eab308', fg: '#eab308' },
      err: { bg: 'rgba(248,113,113,.10)', bd: 'var(--red, #f87171)', fg: 'var(--red, #f87171)' },
    }[level];
    el.style.display = '';
    el.style.background = colors.bg;
    el.style.border = '1px solid ' + colors.bd;
    el.style.color = colors.fg;
    el.textContent = msg;
  }

  /* ---- render the flat table ---- */

  function render() {
    renderDiag();
    var bodyEl = $('wcBody');
    if (!bodyEl) return;
    if (!state.rows.length) {
      bodyEl.innerHTML = '<div class="empty">Hit <b>SCRAPE SGPS</b> to pull every major-league soccer SGP — Pinnacle fair lines vs DK.</div>';
      var c0 = $('wcCount'); if (c0) c0.textContent = '';
      return;
    }
    var rows = state.rows.filter(function (r) {
      if (!state.enabledFams[r.market_key]) return false;
      if (state.matchedOnly && r.ev_pct == null) return false;
      if (state.maxOddsCap) {
        var am = r.dk_american != null ? amNum(r.dk_american) : amNum(r.fair_american);
        if (am != null && am > 1000) return false;
      }
      return true;
    });
    var total = rows.length;
    rows = rows.slice(0, MAX_ROWS);
    var cnt = $('wcCount');
    if (cnt) cnt.textContent = total > rows.length ? ('top ' + rows.length + ' of ' + total) : (rows.length + ' rows');
    if (!rows.length) { bodyEl.innerHTML = '<div class="empty">No combos pass the current filters.</div>'; return; }

    var html = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-family:Space Mono,monospace;font-size:12px">' +
      '<thead><tr style="color:var(--mu);font-size:10px;letter-spacing:.5px;text-align:left">' +
      '<th style="padding:8px 10px">GAME</th><th style="padding:8px 10px">MARKET</th>' +
      '<th style="padding:8px 10px">SELECTION</th>' +
      '<th style="padding:8px 10px;text-align:right">PIN</th>' +
      '<th style="padding:8px 10px;text-align:right" title="No-vig fair price from the devigged Pinnacle group">FAIR</th>' +
      '<th style="padding:8px 10px;text-align:right">DK SGP</th>' +
      '<th style="padding:8px 10px;text-align:right">EV %</th>' +
      '<th style="padding:8px 10px;text-align:right" title="Full Kelly stake as % of bankroll">KELLY %</th>' +
      '</tr></thead><tbody>';
    rows.forEach(function (r) {
      var evTxt = '—', evCol = 'var(--mu)';
      if (r.ev_pct != null) {
        evTxt = (r.ev_pct >= 0 ? '+' : '') + r.ev_pct.toFixed(1) + '%';
        evCol = r.ev_pct >= 3 ? 'var(--ac)' : (r.ev_pct >= 0 ? 'var(--tx)' : 'var(--red, #f87171)');
      }
      var dkTxt = r.dk_american != null ? fmtAm(r.dk_american)
        : (r.dk_status && r.dk_status !== 'priced' ? '—' : '—');
      html += '<tr style="border-top:1px solid var(--b1)">' +
        '<td style="padding:7px 10px;color:var(--mu);white-space:nowrap">' + esc(r.game) +
          '<div style="font-size:9px;color:var(--b2,#64748b)">' + esc(r.league) + '</div></td>' +
        '<td style="padding:7px 10px;color:var(--cyan);white-space:nowrap">' + esc(FAM_LABEL[r.market_key] || r.market_key) +
          (r.via === 'sgp' ? ' <span style="font-size:9px;color:var(--ac);border:1px solid var(--ac);border-radius:3px;padding:0 3px">SGP</span>' : '') + '</td>' +
        '<td style="padding:7px 10px;color:var(--tx)">' + esc(r.selection) + '</td>' +
        '<td style="padding:7px 10px;text-align:right;color:var(--mu)">' + fmtAm(r.pin_american) + '</td>' +
        '<td style="padding:7px 10px;text-align:right;color:var(--tx)">' + fmtAm(r.fair_american) + '</td>' +
        '<td style="padding:7px 10px;text-align:right;color:var(--tx)">' + dkTxt + '</td>' +
        '<td style="padding:7px 10px;text-align:right;font-weight:700;color:' + evCol + '">' + evTxt + '</td>' +
        '<td style="padding:7px 10px;text-align:right;color:var(--mu)">' + (r.kelly_pct != null && r.ev_pct > 0 ? r.kelly_pct.toFixed(1) + '%' : '—') + '</td>' +
        '</tr>';
    });
    html += '</tbody></table></div>';
    bodyEl.innerHTML = html;
  }

  /* ---- filters ---- */

  function onFilter() {
    var mo = $('wcMatchedOnly'); if (mo) state.matchedOnly = !!mo.checked;
    var cap = $('wcMaxOdds'); if (cap) state.maxOddsCap = !!cap.checked;
    render();
  }

  function onSgpOnlyChange() {
    var el = $('wcSgpOnly'); if (el) state.sgpOnly = !!el.checked;
    // sgp_only changes what the server returns — re-scrape if we already have data.
    if (state.rows.length) scrapeAll();
  }

  /* Click a family to isolate it; click the lone active one to restore all. */
  function onMarketBtn(btn) {
    var key = btn.getAttribute('data-wc-fam');
    if (!key) return;
    var active = FAMS.filter(function (k) { return state.enabledFams[k]; });
    var solo = active.length === 1 && active[0] === key;
    FAMS.forEach(function (k) { state.enabledFams[k] = solo ? true : (k === key); });
    document.querySelectorAll('[data-wc-fam]').forEach(function (b) {
      b.classList.toggle('active', !!state.enabledFams[b.getAttribute('data-wc-fam')]);
    });
    render();
  }

  /* ---- DK cookie (set from the site, held in server memory) ---- */

  function setCookieState(txt, color) {
    var el = $('wcCookieState');
    if (el) { el.textContent = txt; el.style.color = color || 'var(--mu)'; }
  }
  function refreshCookieState() {
    fetch('/api/dk/cookies').then(function (r) { return r.json(); }).then(function (j) {
      if (!j.set) { setCookieState(j.envFallback ? 'using env cookie' : 'not set — DK SGP pricing will 403', j.envFallback ? 'var(--mu)' : 'var(--red, #f87171)'); return; }
      var age = j.ageSec != null ? Math.round(j.ageSec / 60) + 'm ago' : '';
      if (j.abck === 'validated') setCookieState('set ✓ validated · ' + age, 'var(--ac)');
      else setCookieState('set but _abck ' + j.abck + ' · ' + age, '#eab308');
    }).catch(function () { setCookieState('', 'var(--mu)'); });
  }
  function saveCookie() {
    var ta = $('wcCookieInput'), msg = $('wcCookieMsg');
    var val = (ta && ta.value || '').trim();
    if (!val) { if (msg) { msg.textContent = 'paste the cookie string first'; msg.style.color = 'var(--red, #f87171)'; } return; }
    if (msg) { msg.textContent = 'saving…'; msg.style.color = 'var(--mu)'; }
    fetch('/api/dk/cookies', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ cookies: val }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error) { if (msg) { msg.textContent = j.error; msg.style.color = 'var(--red, #f87171)'; } return; }
        if (ta) ta.value = '';
        if (msg) {
          if (j.warning) { msg.textContent = '⚠ ' + j.warning; msg.style.color = '#eab308'; }
          else { msg.textContent = '✓ saved (' + j.cookieCount + ' cookies, _abck ' + j.abck + ') — Scrape again to price DK'; msg.style.color = 'var(--ac)'; }
        }
        refreshCookieState();
      })
      .catch(function (e) { if (msg) { msg.textContent = 'save failed: ' + e.message; msg.style.color = 'var(--red, #f87171)'; } });
  }
  function clearCookie() {
    fetch('/api/dk/cookies', { method: 'DELETE' }).then(function (r) { return r.json(); })
      .then(function () { var msg = $('wcCookieMsg'); if (msg) { msg.textContent = 'cleared'; msg.style.color = 'var(--mu)'; } refreshCookieState(); })
      .catch(function () {});
  }

  var activated = false;
  function onActivate() {
    if (activated) return;
    activated = true;
    refreshCookieState();
    render();
  }

  window.worldcupTab = {
    onActivate: onActivate,
    scrapeAll: scrapeAll,
    onFilter: onFilter,
    onSgpOnlyChange: onSgpOnlyChange,
    onMarketBtn: onMarketBtn,
    saveCookie: saveCookie,
    clearCookie: clearCookie,
  };
})();
