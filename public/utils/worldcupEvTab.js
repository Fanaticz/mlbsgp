/* worldcupEvTab.js — World Cup (soccer) SGP +EV tab.
   Flow: LOAD SLATE pulls the World Cup match list from Pinnacle's guest
   API → check one or more matches → PULL & SCAN fetches each match's
   markets live (server devigs every exhaustive group to fair probs) and
   prices the same selections on DK (combos as real 2-leg SGPs via DK's
   calculateBets, straights off the listed odds). One merged table across
   all selected games, ranked by EV% = fairProb × dkDecimal − 1. */
(function () {
  'use strict';
  var M = window.sgpMath;

  var state = {
    slate: [],           // [{id, home, away, startTime}] from pinnacle
    games: [],           // pulled games: {mid, label, parsed, candidates, dkById, dkMeta, error}
    scanning: false,
    minEv: -10,          // slider floor == "ALL" (no EV cutoff)
    matchedOnly: true,
    enabledCats: { combos: true, gamelines: true, team: true, corners: true, cards: true, players: true },
  };

  var ALL_CATS = ['combos', 'gamelines', 'team', 'corners', 'cards', 'players'];

  /* Filter category per market kind. Combos = the joint SGP markets; the
     rest are straight Pinnacle partitions paired with DK's listed markets. */
  var KIND_CATS = {
    btts_total: 'combos', btts_winner: 'combos', winner_total: 'combos',
    ht_ft: 'combos', oddeven_total: 'combos',
    moneyline: 'gamelines', total_goals: 'gamelines', spread: 'gamelines',
    double_chance: 'gamelines', draw_no_bet: 'gamelines', btts: 'gamelines',
    team_goals: 'team', team_to_score: 'team', winning_margin: 'team',
    total_goals_range: 'team', first_team_to_score: 'team',
    corners_total: 'corners', team_corners: 'corners',
    cards_total: 'cards', team_cards: 'cards',
    player_to_score: 'players',
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

  /* ---- candidates from the server-devigged groups ---- */

  function buildCandidates(mid, parsed) {
    var out = [];
    (parsed.groups || []).forEach(function (g) {
      g.sels.forEach(function (s, i) {
        if (s.fair_prob == null) return;
        out.push({
          id: mid + '|' + g.key + ':' + i,
          market_key: g.kind,
          group_label: g.label,
          name: s.name,
          pin_odds: s.odds,
          fair_prob: s.fair_prob,
          fair_american: s.fair_american != null ? s.fair_american : M.probToAmerican(s.fair_prob),
          fields: s.fields || null,
        });
      });
    });
    return out;
  }

  /* ---- slate load + multi-game pull ---- */

  function loadPinnySlate() {
    var btn = $('wcPinLoad');
    if (btn) { btn.disabled = true; btn.textContent = 'LOADING…'; }
    fetch('/api/pinnacle/worldcup-games')
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (btn) { btn.disabled = false; btn.textContent = '↻ LOAD SLATE'; }
        if (j.error) { setStatus('Pinnacle slate: ' + j.error, true); return; }
        state.slate = j.matches || [];
        renderSlatePicker();
        setStatus('Pinnacle slate loaded — ' + state.slate.length + ' World Cup matches. Check the games you want, then PULL & SCAN.');
      })
      .catch(function (e) {
        if (btn) { btn.disabled = false; btn.textContent = '↻ LOAD SLATE'; }
        setStatus('Pinnacle slate failed: ' + e.message, true);
      });
  }

  function renderSlatePicker() {
    var box = $('wcPinMatches');
    if (!box) return;
    if (!state.slate.length) { box.style.display = 'none'; return; }
    box.style.display = '';
    box.innerHTML = state.slate.map(function (m) {
      var d = m.startTime ? m.startTime.replace('T', ' ').replace(':00Z', 'Z') : '';
      return '<label style="display:flex;gap:8px;align-items:center;padding:3px 6px;cursor:pointer;white-space:nowrap">' +
        '<input type="checkbox" value="' + m.id + '" style="accent-color:var(--ac)">' +
        '<span style="color:var(--tx)">' + m.home + ' vs ' + m.away + '</span>' +
        '<span style="color:var(--mu);font-size:10px">' + d + '</span></label>';
    }).join('');
    var pull = $('wcPullBtn');
    if (pull) pull.style.display = '';
  }

  function selectedMatchIds() {
    var box = $('wcPinMatches');
    if (!box) return [];
    return Array.prototype.slice.call(box.querySelectorAll('input:checked'))
      .map(function (cb) { return cb.value; });
  }

  function pullSelected() {
    var mids = selectedMatchIds();
    if (!mids.length) { setStatus('Check at least one match first.', true); return; }
    if (state.scanning) return;
    state.scanning = true;
    var pull = $('wcPullBtn');
    if (pull) { pull.disabled = true; pull.textContent = 'WORKING…'; }
    state.games = [];

    var idx = 0;
    function step() {
      if (idx >= mids.length) {
        state.scanning = false;
        if (pull) { pull.disabled = false; pull.textContent = '⚡ PULL & SCAN'; }
        var nOk = state.games.filter(function (g) { return !g.error; }).length;
        setStatus('Done — ' + nOk + '/' + mids.length + ' games priced.');
        updateBadge();
        render();
        return;
      }
      var mid = mids[idx];
      var slateEntry = state.slate.filter(function (m) { return String(m.id) === String(mid); })[0] || {};
      var game = { mid: mid, label: (slateEntry.home || '?') + ' vs ' + (slateEntry.away || '?'),
                   parsed: null, candidates: [], dkById: {}, dkMeta: null, error: null };
      state.games.push(game);
      setStatus('(' + (idx + 1) + '/' + mids.length + ') Pulling Pinnacle — ' + game.label + '…');
      fetch('/api/pinnacle/worldcup-match/' + mid)
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.error) throw new Error('pinnacle: ' + j.error);
          game.parsed = j;
          game.label = j.home + ' vs ' + j.away;
          game.candidates = buildCandidates(mid, j);
          render();
          setStatus('(' + (idx + 1) + '/' + mids.length + ') Scanning DK — ' + game.label + '…');
          return scanGame(game);
        })
        .catch(function (e) { game.error = e.message; })
        .then(function () { idx++; render(); step(); });
    }
    step();
  }

  function scanGame(game) {
    var cands = game.candidates.filter(function (c) { return c.fields; });
    if (!cands.length || !game.parsed) return Promise.resolve();
    var body = {
      home: game.parsed.home,
      away: game.parsed.away,
      candidates: cands.map(function (c) {
        return Object.assign({ id: c.id, market_key: c.market_key }, c.fields);
      }),
    };
    var lid = ($('wcLeagueId') && $('wcLeagueId').value || '').trim();
    if (/^\d+$/.test(lid)) body.league_id = lid;
    return fetch('/api/dk/find-sgps-worldcup', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.error) {
          game.error = 'DK: ' + j.error + (j.dk_events ? ' · slate: ' + j.dk_events : '');
          return;
        }
        (j.results || []).forEach(function (r) { game.dkById[r.id] = r; });
        game.dkMeta = j;
      })
      .catch(function (e) { game.error = 'DK scan failed: ' + e.message; });
  }

  /* Re-run the DK scan for already-pulled games (prices move). */
  function runScan() {
    if (!state.games.length) { setStatus('Pull at least one game first.', true); return; }
    if (state.scanning) return;
    state.scanning = true;
    var btn = $('wcScanBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'SCANNING…'; }
    var chain = Promise.resolve();
    state.games.forEach(function (g, i) {
      chain = chain.then(function () {
        setStatus('(' + (i + 1) + '/' + state.games.length + ') Re-scanning DK — ' + g.label + '…');
        g.error = null;
        return scanGame(g);
      });
    });
    chain.then(function () {
      state.scanning = false;
      if (btn) { btn.disabled = false; btn.textContent = '✨ RESCAN DK'; }
      setStatus('Re-scan complete.');
      render();
    });
  }

  function updateBadge() {
    var badge = $('wcHdrBadge');
    if (!badge) return;
    var n = state.games.filter(function (g) { return !g.error; }).length;
    var sels = state.games.reduce(function (a, g) { return a + g.candidates.length; }, 0);
    badge.textContent = n ? (n + ' game' + (n > 1 ? 's' : '') + ' · ' + sels + ' selections') :
      'Load the slate and pick matches';
  }

  /* ---- EV + render ---- */

  function evFor(cand, dk) {
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
    if (!state.games.length) {
      bodyEl.innerHTML = '<div class="empty">Load the Pinnacle slate, check one or more matches, then PULL &amp; SCAN.</div>';
      return;
    }
    var multi = state.games.length > 1;
    var noEvFloor = state.minEv <= -10;
    var rows = [];
    state.games.forEach(function (g) {
      g.candidates.forEach(function (c) {
        if (state.enabledCats[KIND_CATS[c.market_key] || 'team'] === false) return;
        var dk = g.dkById[c.id];
        var ev = evFor(c, dk);
        if (state.matchedOnly && !ev) return;
        if (ev && !noEvFloor && ev.evPct < state.minEv) return;
        rows.push({ g: g, c: c, dk: dk, ev: ev });
      });
    });
    rows.sort(function (a, b) {
      var ea = a.ev ? a.ev.evPct : -1e9, eb = b.ev ? b.ev.evPct : -1e9;
      return eb - ea;
    });

    var cnt = $('wcCount');
    if (cnt) cnt.textContent = rows.length + ' rows';

    var html = '';
    var gameErrs = state.games.filter(function (g) { return g.error; });
    if (gameErrs.length) {
      html += gameErrs.map(function (g) {
        return '<div style="margin:6px 0;font-size:11px;color:var(--red,#f87171);font-family:Space Mono,monospace">' +
          g.label + ' — ' + g.error + '</div>';
      }).join('');
    }

    if (!rows.length) {
      bodyEl.innerHTML = html + '<div class="empty">No selections pass the current filters.</div>';
      return;
    }

    html += '<table style="width:100%;border-collapse:collapse;font-family:Space Mono,monospace;font-size:12px">' +
      '<thead><tr style="color:var(--mu);font-size:10px;letter-spacing:.5px;text-align:left">' +
      (multi ? '<th style="padding:8px 10px">GAME</th>' : '') +
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
      var sgpTag = dk && dk.via === 'sgp'
        ? ' <span style="font-size:9px;color:var(--ac);border:1px solid var(--ac);border-radius:3px;padding:0 3px" title="Priced as a real 2-leg SGP via DK calculateBets — boost-eligible. Legs: ' + String(dk.dk_market || '').replace(/"/g, '&quot;') + '">SGP</span>'
        : '';
      html += '<tr style="border-top:1px solid var(--b1)">' +
        (multi ? '<td style="padding:7px 10px;color:var(--mu);white-space:nowrap;font-size:11px">' + r.g.label + '</td>' : '') +
        '<td style="padding:7px 10px;color:var(--cyan);white-space:nowrap">' + (c.group_label || c.market_key) + sgpTag + '</td>' +
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

    state.games.forEach(function (g) {
      if (g.dkMeta && g.dkMeta.available_markets && g.dkMeta.available_markets.length) {
        html += '<details style="margin-top:6px;font-size:10px;color:var(--mu);font-family:Space Mono,monospace">' +
          '<summary style="cursor:pointer">DK markets — ' + g.label + ' (' + g.dkMeta.available_markets.length + ')</summary>' +
          '<div style="margin-top:4px;line-height:1.7">' + g.dkMeta.available_markets.join(' · ') + '</div></details>';
      }
    });
    bodyEl.innerHTML = html;
  }

  /* ---- controls ---- */

  function onFilter() {
    var s = $('wcMinEv');
    if (s) {
      state.minEv = parseInt(s.value, 10) || 0;
      var v = $('wcMinEvV');
      if (v) v.textContent = state.minEv <= -10 ? 'ALL' : (state.minEv >= 0 ? '+' : '') + state.minEv + '%';
    }
    var mo = $('wcMatchedOnly');
    if (mo) state.matchedOnly = !!mo.checked;
    render();
  }

  /* Category buttons act as an isolate-then-toggle filter: with everything
     enabled (default "all shown"), clicking one shows ONLY that family;
     further clicks add/remove families; emptying the set resets to all. */
  function onMarketBtn(btn) {
    var key = btn.getAttribute('data-wc-cat');
    if (!key) return;
    var allOn = ALL_CATS.every(function (k) { return state.enabledCats[k]; });
    if (allOn) {
      ALL_CATS.forEach(function (k) { state.enabledCats[k] = (k === key); });
    } else {
      state.enabledCats[key] = !state.enabledCats[key];
      if (!ALL_CATS.some(function (k) { return state.enabledCats[k]; })) {
        ALL_CATS.forEach(function (k) { state.enabledCats[k] = true; });
      }
    }
    ALL_CATS.forEach(function (k) {
      var b = document.querySelector('[data-wc-cat="' + k + '"]');
      if (b) b.classList.toggle('active', !!state.enabledCats[k]);
    });
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
    onFilter();
    render();
  }

  window.worldcupTab = {
    onActivate: onActivate,
    loadPinnySlate: loadPinnySlate,
    pullSelected: pullSelected,
    runScan: runScan,
    onFilter: onFilter,
    onMarketBtn: onMarketBtn,
    onLeagueIdChange: onLeagueIdChange,
  };
})();
