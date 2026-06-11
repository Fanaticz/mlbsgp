/* worldcupEvTab.js — World Cup (soccer) SGP +EV tab.
   Flow: upload a Pinnacle match-page PDF → server parses the combo market
   groups (BTTS/Total, BTTS/Winner, Winner/Total, HT/FT, Odd-Even/Total) →
   client devigs each group (straight multiplicative no-vig: the groups are
   mutually exclusive + exhaustive partitions, so normalizing the implied
   probabilities removes the hold) → scan DK for the match's posted combo
   markets → EV% = fairProb × dkDecimal − 1, ranked descending.
   No correlation model needed: Pinnacle prices the joint outcome directly. */
(function () {
  'use strict';
  var M = window.sgpMath;

  var state = {
    parsed: null,        // /api/extract-worldcup-pdf response
    candidates: [],      // devigged Pinnacle combo selections
    dkById: {},          // candidate id -> DK match result
    dkMeta: null,        // event/league info from the DK scan
    scanning: false,
    minEv: 0,
    matchedOnly: true,
    enabledMarkets: { btts_total: true, btts_winner: true, winner_total: true, ht_ft: true, oddeven_total: true },
  };

  var MARKET_LABELS = {
    btts_total: 'BTTS / Total Goals',
    btts_winner: 'BTTS / Winner',
    winner_total: 'Winner / Total Goals',
    ht_ft: 'HT / FT',
    oddeven_total: 'Odd-Even / Total',
  };

  function $(id) { return document.getElementById(id); }
  function setStatus(msg, isErr) {
    var el = $('wcStatus');
    if (el) { el.textContent = msg || ''; el.style.color = isErr ? 'var(--red, #f87171)' : 'var(--mu)'; }
  }
  function fmtAm(o) {
    if (o == null || isNaN(o)) return '—';
    return (o > 0 ? '+' : '') + Math.round(o);
  }

  /* ---- Pinnacle selection-name parsing into structured fields ---- */

  function resultToken(token, home, away) {
    var t = (token || '').trim().toLowerCase();
    if (!t) return null;
    if (t.indexOf('draw') >= 0) return 'draw';
    var h = (home || '').toLowerCase(), a = (away || '').toLowerCase();
    if (h && (t === h || t.indexOf(h) >= 0 || h.indexOf(t) >= 0)) return 'home';
    if (a && (t === a || t.indexOf(a) >= 0 || a.indexOf(t) >= 0)) return 'away';
    return null;
  }

  function parseTotal(s) {
    var side = /\bover\b/i.test(s) ? 'Over' : (/\bunder\b/i.test(s) ? 'Under' : null);
    var m = s.match(/(\d+(?:\.\d+)?)/);
    return { side: side, line: m ? parseFloat(m[1]) : null };
  }

  /* Turn one Pinnacle selection name into the structured candidate fields
     dk_api.py's matcher expects. Returns null when the name doesn't parse —
     that selection is dropped (and reported) rather than mismatched. */
  function structureSelection(key, name, home, away) {
    var parts = name.split('&').map(function (s) { return s.trim(); });
    if (key === 'btts_total') {
      if (parts.length !== 2) return null;
      var t = parseTotal(parts[1]);
      if (!/^(yes|no)$/i.test(parts[0]) || !t.side) return null;
      return { btts: parts[0].charAt(0).toUpperCase() === 'Y' ? 'Yes' : 'No', total_side: t.side, total_line: t.line };
    }
    if (key === 'btts_winner') {
      if (parts.length !== 2) return null;
      var r = resultToken(parts[1], home, away);
      if (!/^(yes|no)$/i.test(parts[0]) || !r) return null;
      return { btts: parts[0].charAt(0).toUpperCase() === 'Y' ? 'Yes' : 'No', result: r };
    }
    if (key === 'winner_total') {
      if (parts.length !== 2) return null;
      var r2 = resultToken(parts[0], home, away);
      var t2 = parseTotal(parts[1]);
      if (!r2 || !t2.side) return null;
      return { result: r2, total_side: t2.side, total_line: t2.line };
    }
    if (key === 'oddeven_total') {
      if (parts.length !== 2) return null;
      var t3 = parseTotal(parts[1]);
      if (!/^(odd|even)$/i.test(parts[0]) || !t3.side) return null;
      return { odd_even: /^odd$/i.test(parts[0]) ? 'Odd' : 'Even', total_side: t3.side, total_line: t3.line };
    }
    if (key === 'ht_ft') {
      var seg = name.split(/\s+-\s+/);
      if (seg.length !== 2) return null;
      var ht = resultToken(seg[0], home, away), ft = resultToken(seg[1], home, away);
      if (!ht || !ft) return null;
      return { ht: ht, ft: ft };
    }
    return null;
  }

  /* Devig one market group (multiplicative): fair_i = implied_i / Σ implied. */
  function buildCandidates(parsed) {
    var out = [];
    var keys = Object.keys(MARKET_LABELS);
    keys.forEach(function (key) {
      var sels = (parsed.markets || {})[key] || [];
      if (sels.length < 2) return;
      var implied = sels.map(function (s) { return M.americanToProb(s.odds); });
      if (implied.some(function (p) { return p == null; })) return;
      var sum = implied.reduce(function (a, b) { return a + b; }, 0);
      if (sum <= 0) return;
      sels.forEach(function (s, i) {
        var fields = structureSelection(key, s.name, parsed.home, parsed.away);
        var fairProb = implied[i] / sum;
        out.push({
          id: key + ':' + i,
          market_key: key,
          name: s.name,
          pin_odds: s.odds,
          fair_prob: fairProb,
          fair_american: M.probToAmerican(fairProb),
          group_hold_pct: (sum - 1) * 100,
          fields: fields,            // null → can't be matched on DK
        });
      });
    });
    return out;
  }

  /* ---- live pull from Pinnacle ---- */

  function applyParsed(j, sourceLabel) {
    state.parsed = j;
    state.candidates = buildCandidates(j);
    state.dkById = {};
    state.dkMeta = null;
    var badge = $('wcHdrBadge');
    if (badge) badge.textContent = j.home + ' vs ' + j.away + (j.kickoff ? ' · ' + j.kickoff : '');
    setStatus(j.home + ' vs ' + j.away + ' (' + sourceLabel + ') — ' + state.candidates.length +
      ' SGP selections across ' + (j.sgp_markets_found || []).length + ' combo markets. Scanning DK…');
    render();
    runScan();
  }

  function loadPinnySlate() {
    var sel = $('wcPinMatch');
    var btn = $('wcPinLoad');
    if (btn) { btn.disabled = true; btn.textContent = 'LOADING…'; }
    fetch('/api/pinnacle/worldcup-games')
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (btn) { btn.disabled = false; btn.textContent = '↻ LOAD SLATE'; }
        if (j.error) { setStatus('Pinnacle slate: ' + j.error, true); return; }
        var matches = j.matches || [];
        if (!sel) return;
        sel.innerHTML = '<option value="">— pick a match (' + matches.length + ') —</option>' +
          matches.map(function (m) {
            var d = m.startTime ? m.startTime.replace('T', ' ').replace(':00Z', 'Z') : '';
            return '<option value="' + m.id + '">' + m.home + ' vs ' + m.away + (d ? ' · ' + d : '') + '</option>';
          }).join('');
        sel.style.display = '';
        setStatus('Pinnacle slate loaded — ' + matches.length + ' World Cup matches. Pick one.');
      })
      .catch(function (e) {
        if (btn) { btn.disabled = false; btn.textContent = '↻ LOAD SLATE'; }
        setStatus('Pinnacle slate failed: ' + e.message, true);
      });
  }

  function onPinMatchPick() {
    var sel = $('wcPinMatch');
    var mid = sel && sel.value;
    if (!mid) return;
    setStatus('Pulling live Pinnacle odds…');
    fetch('/api/pinnacle/worldcup-match/' + mid)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error) { setStatus('Pinnacle pull: ' + j.error, true); return; }
        applyParsed(j, 'live pinny');
      })
      .catch(function (e) { setStatus('Pinnacle pull failed: ' + e.message, true); });
  }

  /* ---- upload ---- */

  function onUpload(ev) {
    var file = ev && ev.target && ev.target.files && ev.target.files[0];
    if (!file) return;
    ev.target.value = '';
    var fd = new FormData();
    fd.append('file', file);
    setStatus('Parsing PDF…');
    fetch('/api/extract-worldcup-pdf', { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error) { setStatus(j.error, true); return; }
        applyParsed(j, 'pdf');
      })
      .catch(function (e) { setStatus('Upload failed: ' + e.message, true); });
  }

  /* ---- DK scan ---- */

  function runScan() {
    if (!state.parsed) { setStatus('Upload a Pinnacle PDF first.', true); return; }
    if (state.scanning) return;
    var cands = state.candidates.filter(function (c) { return c.fields; });
    if (!cands.length) { setStatus('No parseable SGP candidates in this PDF.', true); return; }
    state.scanning = true;
    var btn = $('wcScanBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'SCANNING…'; }
    var body = {
      home: state.parsed.home,
      away: state.parsed.away,
      candidates: cands.map(function (c) {
        return Object.assign({ id: c.id, market_key: c.market_key }, c.fields);
      }),
    };
    var lid = ($('wcLeagueId') && $('wcLeagueId').value || '').trim();
    if (/^\d+$/.test(lid)) body.league_id = lid;
    fetch('/api/dk/find-sgps-worldcup', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        state.scanning = false;
        if (btn) { btn.disabled = false; btn.textContent = '✨ SCAN DK'; }
        if (j.error) {
          setStatus('DK scan: ' + j.error + (j.dk_events ? ' · slate: ' + j.dk_events : ''), true);
          render();
          return;
        }
        state.dkById = {};
        (j.results || []).forEach(function (r) { state.dkById[r.id] = r; });
        state.dkMeta = j;
        var matched = (j.results || []).filter(function (r) { return r.matched; }).length;
        setStatus('DK event: ' + (j.event_name || (j.away + ' @ ' + j.home)) +
          ' — matched ' + matched + '/' + (j.results || []).length + ' selections' +
          (j.cached ? ' (cached ' + j.cache_age_s + 's)' : ''));
        render();
      })
      .catch(function (e) {
        state.scanning = false;
        if (btn) { btn.disabled = false; btn.textContent = '✨ SCAN DK'; }
        setStatus('DK scan failed: ' + e.message, true);
      });
  }

  /* ---- EV + render ---- */

  function evFor(cand) {
    var dk = state.dkById[cand.id];
    if (!dk || !dk.matched) return null;
    var dec = dk.dk_decimal != null ? parseFloat(dk.dk_decimal) : null;
    if (!dec || isNaN(dec) || dec <= 1) dec = M.americanToDecimal(dk.dk_american);
    if (!dec) return null;
    return {
      dec: dec,
      american: dk.dk_american,
      evPct: (cand.fair_prob * dec - 1) * 100,
      kellyPct: (cand.fair_prob * dec - 1) / (dec - 1) * 100,
    };
  }

  function render() {
    var bodyEl = $('wcBody');
    if (!bodyEl) return;
    if (!state.parsed) {
      bodyEl.innerHTML = '<div class="empty">Upload a Pinnacle World Cup match PDF to begin.</div>';
      return;
    }
    var rows = state.candidates
      .filter(function (c) { return state.enabledMarkets[c.market_key]; })
      .map(function (c) {
        var dk = state.dkById[c.id];
        return { c: c, dk: dk, ev: evFor(c) };
      })
      .filter(function (r) {
        if (state.matchedOnly && !r.ev) return false;
        if (r.ev && r.ev.evPct < state.minEv) return false;
        return true;
      })
      .sort(function (a, b) {
        var ea = a.ev ? a.ev.evPct : -1e9, eb = b.ev ? b.ev.evPct : -1e9;
        return eb - ea;
      });

    var cnt = $('wcCount');
    if (cnt) cnt.textContent = rows.length + ' rows';

    if (!rows.length) {
      bodyEl.innerHTML = '<div class="empty">No selections pass the current filters.</div>';
      return;
    }

    var html = '<table style="width:100%;border-collapse:collapse;font-family:Space Mono,monospace;font-size:12px">' +
      '<thead><tr style="color:var(--mu);font-size:10px;letter-spacing:.5px;text-align:left">' +
      '<th style="padding:8px 10px">MARKET</th><th style="padding:8px 10px">SELECTION</th>' +
      '<th style="padding:8px 10px;text-align:right">PIN</th>' +
      '<th style="padding:8px 10px;text-align:right" title="No-vig fair price from the devigged Pinnacle group">FV</th>' +
      '<th style="padding:8px 10px;text-align:right">FAIR %</th>' +
      '<th style="padding:8px 10px;text-align:right">DK</th>' +
      '<th style="padding:8px 10px;text-align:right">EV %</th>' +
      '<th style="padding:8px 10px;text-align:right" title="Full Kelly stake as % of bankroll">KELLY %</th>' +
      '</tr></thead><tbody>';

    rows.forEach(function (r) {
      var c = r.c, ev = r.ev, dk = r.dk;
      var evTxt, evCol, dkTxt;
      if (ev) {
        evTxt = (ev.evPct >= 0 ? '+' : '') + ev.evPct.toFixed(1) + '%';
        evCol = ev.evPct >= 3 ? 'var(--ac)' : (ev.evPct >= 0 ? 'var(--tx)' : 'var(--red, #f87171)');
        dkTxt = String(dk.dk_american || fmtAm(M.decimalToAmerican(ev.dec)));
      } else {
        evTxt = '—';
        evCol = 'var(--mu)';
        dkTxt = dk && dk.missing ? 'no match' : (c.fields ? '—' : 'unparsed');
      }
      var missTitle = dk && dk.missing ? String(dk.missing) : '';
      html += '<tr style="border-top:1px solid var(--b1)">' +
        '<td style="padding:7px 10px;color:var(--cyan);white-space:nowrap">' + (MARKET_LABELS[c.market_key] || c.market_key) + '</td>' +
        '<td style="padding:7px 10px;color:var(--tx)">' + c.name + '</td>' +
        '<td style="padding:7px 10px;text-align:right;color:var(--mu)">' + fmtAm(c.pin_odds) + '</td>' +
        '<td style="padding:7px 10px;text-align:right;color:var(--tx)">' + fmtAm(c.fair_american) + '</td>' +
        '<td style="padding:7px 10px;text-align:right;color:var(--mu)">' + (c.fair_prob * 100).toFixed(1) + '%</td>' +
        '<td style="padding:7px 10px;text-align:right;color:var(--tx)" title="' + missTitle.replace(/"/g, '&quot;') + '">' + dkTxt + '</td>' +
        '<td style="padding:7px 10px;text-align:right;font-weight:700;color:' + evCol + '">' + evTxt + '</td>' +
        '<td style="padding:7px 10px;text-align:right;color:var(--mu)">' + (ev && ev.evPct > 0 ? ev.kellyPct.toFixed(1) + '%' : '—') + '</td>' +
        '</tr>';
    });
    html += '</tbody></table>';

    // Group-hold footnote + DK debug: which market names DK actually lists.
    var holds = {};
    state.candidates.forEach(function (c) { holds[c.market_key] = c.group_hold_pct; });
    var holdTxt = Object.keys(holds).map(function (k) {
      return (MARKET_LABELS[k] || k) + ' ' + holds[k].toFixed(1) + '%';
    }).join(' · ');
    html += '<div style="margin-top:10px;font-size:10px;color:var(--mu);font-family:Space Mono,monospace">Pinnacle hold removed per group: ' + holdTxt + '</div>';
    if (state.dkMeta && state.dkMeta.available_markets && state.dkMeta.available_markets.length) {
      html += '<details style="margin-top:6px;font-size:10px;color:var(--mu);font-family:Space Mono,monospace">' +
        '<summary style="cursor:pointer">DK markets seen on this event (' + state.dkMeta.available_markets.length + ')</summary>' +
        '<div style="margin-top:4px;line-height:1.7">' + state.dkMeta.available_markets.join(' · ') + '</div></details>';
    }
    bodyEl.innerHTML = html;
  }

  /* ---- controls ---- */

  function onFilter() {
    var s = $('wcMinEv');
    if (s) {
      state.minEv = parseInt(s.value, 10) || 0;
      var v = $('wcMinEvV');
      if (v) v.textContent = (state.minEv >= 0 ? '+' : '') + state.minEv + '%';
    }
    var mo = $('wcMatchedOnly');
    if (mo) state.matchedOnly = !!mo.checked;
    render();
  }

  function onMarketBtn(btn) {
    var key = btn.getAttribute('data-wc-mkt');
    if (!key) return;
    state.enabledMarkets[key] = !state.enabledMarkets[key];
    btn.classList.toggle('active', state.enabledMarkets[key]);
    render();
  }

  function onLeagueIdChange() {
    var el = $('wcLeagueId');
    if (el) try { localStorage.setItem('wcLeagueId', el.value.trim()); } catch (_) {}
  }

  var activated = false;
  function onActivate() {
    if (activated) return;
    activated = true;
    var el = $('wcLeagueId');
    if (el) try { el.value = localStorage.getItem('wcLeagueId') || ''; } catch (_) {}
    var drop = $('wcDrop');
    if (drop) {
      ['dragover', 'dragenter'].forEach(function (evn) {
        drop.addEventListener(evn, function (e) { e.preventDefault(); drop.style.borderColor = 'var(--ac)'; });
      });
      ['dragleave', 'drop'].forEach(function (evn) {
        drop.addEventListener(evn, function (e) { e.preventDefault(); drop.style.borderColor = 'var(--b2)'; });
      });
      drop.addEventListener('drop', function (e) {
        var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) onUpload({ target: { files: [f], value: '' } });
      });
      drop.addEventListener('click', function () { var fi = $('wcFile'); if (fi) fi.click(); });
    }
    render();
  }

  window.worldcupTab = {
    onActivate: onActivate,
    onUpload: onUpload,
    loadPinnySlate: loadPinnySlate,
    onPinMatchPick: onPinMatchPick,
    runScan: runScan,
    onFilter: onFilter,
    onMarketBtn: onMarketBtn,
    onLeagueIdChange: onLeagueIdChange,
  };
})();
