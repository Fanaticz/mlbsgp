/* worldcupEvTab.js — World Cup (soccer) SGP +EV tab.
   Flow: pull live Pinnacle odds for one or more matches → server devigs each
   combo market group (straight multiplicative no-vig: the groups are
   mutually exclusive + exhaustive partitions, so normalizing the implied
   probabilities removes the hold) → scan DK for each match's posted combo
   markets → EV% = fairProb × dkDecimal − 1, ranked descending across games.
   No correlation model needed: Pinnacle prices the joint outcome directly. */
(function () {
  'use strict';
  var M = window.sgpMath;

  var CATS = ['combos', 'gamelines', 'team', 'corners', 'cards', 'players'];

  var state = {
    games: [],           // [{ id, label, parsed, candidates, dkById, dkMeta, loading, scanning, error }]
    matchedOnly: true,
    maxOddsCap: true,    // hide longshots priced above +1000
    enabledCats: { combos: true, gamelines: true, team: true, corners: true, cards: true, players: true },
    leagues: [],         // [{ key, label, dk_id, dk_slug, pin_id }]
    leagueKey: 'worldcup',
  };

  function currentLeague() {
    for (var i = 0; i < state.leagues.length; i++)
      if (state.leagues[i].key === state.leagueKey) return state.leagues[i];
    return null;
  }
  function leagueLabel() {
    var l = currentLeague();
    return l ? l.label : 'soccer';
  }

  var MARKET_LABELS = {
    btts_total: 'BTTS / Total Goals',
    btts_winner: 'BTTS / Winner',
    winner_total: 'Winner / Total Goals',
    ht_ft: 'HT / FT',
    oddeven_total: 'Odd-Even / Total',
  };

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
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* Live Pinnacle pulls arrive with server-computed groups (fair_prob +
     structured fields included). */
  function buildCandidates(parsed) {
    var out = [];
    (parsed.groups || []).forEach(function (g) {
      g.sels.forEach(function (s, i) {
        if (s.fair_prob == null) return;
        out.push({
          id: g.key + ':' + i,
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

  /* ---- live pull from Pinnacle ---- */

  /* Populate the league picker from the server registry (World Cup, EPL, …).
     Falls back to a built-in list if the endpoint is unavailable so the tab
     still works. */
  function loadLeagues() {
    var pick = $('wcLeague');
    function apply(j) {
      state.leagues = (j && j.leagues) || [];
      if (!state.leagues.length) {
        state.leagues = [
          { key: 'worldcup', label: 'FIFA World Cup' },
          { key: 'epl', label: 'English Premier League' },
        ];
      }
      var stored = '';
      try { stored = localStorage.getItem('wcLeagueKey') || ''; } catch (_) {}
      var def = stored || (j && j.default) || state.leagues[0].key;
      if (!currentLeagueIn(def)) def = state.leagues[0].key;
      state.leagueKey = def;
      if (pick) {
        pick.innerHTML = state.leagues.map(function (l) {
          return '<option value="' + esc(l.key) + '"' + (l.key === def ? ' selected' : '') + '>' + esc(l.label) + '</option>';
        }).join('');
      }
    }
    function currentLeagueIn(key) {
      for (var i = 0; i < state.leagues.length; i++) if (state.leagues[i].key === key) return true;
      return false;
    }
    fetch('/api/soccer/leagues')
      .then(function (r) { return r.json(); })
      .then(apply)
      .catch(function () { apply(null); });
  }

  /* Switching league invalidates the loaded slate + any added matches. */
  function onLeagueChange() {
    var pick = $('wcLeague');
    if (!pick) return;
    state.leagueKey = pick.value;
    try { localStorage.setItem('wcLeagueKey', state.leagueKey); } catch (_) {}
    state.games = [];
    var sel = $('wcPinMatch');
    if (sel) { sel.innerHTML = ''; sel.style.display = 'none'; }
    renderGames();
    render();
    setStatus('League set to ' + leagueLabel() + '. Load the slate to begin.');
  }

  function loadPinnySlate() {
    var sel = $('wcPinMatch');
    var btn = $('wcPinLoad');
    if (btn) { btn.disabled = true; btn.textContent = 'LOADING…'; }
    var q = state.leagueKey ? ('?league=' + encodeURIComponent(state.leagueKey)) : '';
    fetch('/api/pinnacle/worldcup-games' + q)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (btn) { btn.disabled = false; btn.textContent = '↻ LOAD SLATE'; }
        if (j.error) { setStatus('Pinnacle slate: ' + j.error, true); return; }
        var matches = j.matches || [];
        if (!sel) return;
        sel.innerHTML = '<option value="">— add a match (' + matches.length + ') —</option>' +
          matches.map(function (m) {
            var d = m.startTime ? m.startTime.replace('T', ' ').replace(':00Z', 'Z') : '';
            return '<option value="' + m.id + '">' + esc(m.home + ' vs ' + m.away) + (d ? ' · ' + d : '') + '</option>';
          }).join('');
        sel.style.display = '';
        setStatus('Pinnacle slate loaded — ' + matches.length + ' ' + leagueLabel() + ' matches. Pick one or more.');
      })
      .catch(function (e) {
        if (btn) { btn.disabled = false; btn.textContent = '↻ LOAD SLATE'; }
        setStatus('Pinnacle slate failed: ' + e.message, true);
      });
  }

  function findGame(mid) {
    for (var i = 0; i < state.games.length; i++) if (state.games[i].id === mid) return state.games[i];
    return null;
  }

  function onPinMatchPick() {
    var sel = $('wcPinMatch');
    var mid = sel && sel.value;
    if (!mid) return;
    var label = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : mid;
    sel.value = '';                     // reset so another match can be added
    if (findGame(mid)) { setStatus(label + ' is already loaded.'); return; }
    var game = { id: mid, label: label, parsed: null, candidates: [], dkById: {}, dkMeta: null, loading: true, scanning: false, error: null };
    state.games.push(game);
    renderGames();
    setStatus('Pulling live Pinnacle odds for ' + label + '…');
    fetch('/api/pinnacle/worldcup-match/' + mid)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        game.loading = false;
        if (j.error) { game.error = j.error; setStatus('Pinnacle pull: ' + j.error, true); renderGames(); render(); return; }
        game.parsed = j;
        game.candidates = buildCandidates(j);
        game.label = j.home + ' vs ' + j.away;
        setStatus(j.home + ' vs ' + j.away + ' — ' + game.candidates.length +
          ' selections across ' + (j.sgp_markets_found || []).length + ' combo markets. Scanning DK…');
        renderGames();
        render();
        scanGame(game);
      })
      .catch(function (e) {
        game.loading = false;
        game.error = e.message;
        setStatus('Pinnacle pull failed: ' + e.message, true);
        renderGames();
      });
  }

  function removeGame(mid) {
    state.games = state.games.filter(function (g) { return g.id !== mid; });
    renderGames();
    render();
  }

  /* ---- DK scan ---- */

  function scanGame(game) {
    if (!game.parsed || game.scanning) return;
    var cands = game.candidates.filter(function (c) { return c.fields; });
    if (!cands.length) { game.error = 'no parseable SGP candidates'; renderGames(); return; }
    game.scanning = true;
    game.error = null;
    renderGames();
    syncScanBtn();
    var body = {
      home: game.parsed.home,
      away: game.parsed.away,
      candidates: cands.map(function (c) {
        return Object.assign({ id: c.id, market_key: c.market_key }, c.fields);
      }),
    };
    if (state.leagueKey) body.league = state.leagueKey;
    var lid = ($('wcLeagueId') && $('wcLeagueId').value || '').trim();
    if (/^\d+$/.test(lid)) body.league_id = lid;  // manual DK id wins over key
    fetch('/api/dk/find-sgps-worldcup', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        game.scanning = false;
        syncScanBtn();
        if (j.error) {
          game.error = 'DK: ' + j.error;
          setStatus('DK scan (' + game.label + '): ' + j.error + (j.dk_events ? ' · slate: ' + j.dk_events : ''), true);
          renderGames();
          render();
          return;
        }
        game.dkById = {};
        (j.results || []).forEach(function (r) { game.dkById[r.id] = r; });
        game.dkMeta = j;
        var matched = (j.results || []).filter(function (r) { return r.matched; }).length;
        setStatus('DK event: ' + (j.event_name || (j.away + ' @ ' + j.home)) +
          ' — matched ' + matched + '/' + (j.results || []).length + ' selections' +
          (j.cached ? ' (cached ' + j.cache_age_s + 's)' : ''));
        renderGames();
        render();
      })
      .catch(function (e) {
        game.scanning = false;
        syncScanBtn();
        game.error = 'DK scan failed: ' + e.message;
        setStatus('DK scan failed (' + game.label + '): ' + e.message, true);
        renderGames();
      });
  }

  function runScan() {
    var loaded = state.games.filter(function (g) { return g.parsed; });
    if (!loaded.length) { setStatus('Load the slate and pick a match first.', true); return; }
    loaded.forEach(scanGame);
  }

  function syncScanBtn() {
    var btn = $('wcScanBtn');
    if (!btn) return;
    var busy = state.games.some(function (g) { return g.scanning; });
    btn.disabled = busy;
    btn.textContent = busy ? 'SCANNING…' : '✨ SCAN DK';
  }

  /* ---- EV + render ---- */

  /* Numeric American price of the DK side (DK strings use unicode minus). */
  function dkAmericanNum(dk, ev) {
    if (!dk) return null;
    var s = String(dk.dk_american || '').replace(/−/g, '-').replace(/[^0-9+-]/g, '');
    var n = parseInt(s, 10);
    if (!isNaN(n) && n !== 0) return n;
    return ev ? M.decimalToAmerican(ev.dec) : null;
  }

  function evFor(game, cand) {
    var dk = game.dkById[cand.id];
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

  function renderGames() {
    var el = $('wcGames');
    if (!el) return;
    if (!state.games.length) { el.innerHTML = ''; el.style.display = 'none'; return; }
    el.style.display = 'flex';
    el.innerHTML = state.games.map(function (g) {
      var stat;
      if (g.loading) stat = 'pulling…';
      else if (g.scanning) stat = 'scanning DK…';
      else if (g.error) stat = '⚠ ' + g.error;
      else if (g.dkMeta) {
        var matched = (g.dkMeta.results || []).filter(function (r) { return r.matched; }).length;
        stat = matched + '/' + (g.dkMeta.results || []).length + ' matched';
      } else stat = g.candidates.length + ' sels';
      return '<span style="display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border:1px solid ' +
        (g.error ? 'var(--red, #f87171)' : 'var(--b1)') + ';border-radius:5px;background:var(--s1);font-size:10px;font-family:Space Mono,monospace">' +
        '<span style="color:var(--tx)">' + esc(g.label) + '</span>' +
        '<span style="color:' + (g.error ? 'var(--red, #f87171)' : 'var(--mu)') + '" title="' + esc(g.error || '') + '">' + esc(stat) + '</span>' +
        '<button type="button" onclick="window.worldcupTab.removeGame(\'' + esc(g.id) + '\')" style="border:none;background:none;color:var(--mu);cursor:pointer;font-size:11px;padding:0" title="Remove this match">✕</button>' +
        '</span>';
    }).join('');
    var badge = $('wcHdrBadge');
    if (badge) {
      var loaded = state.games.filter(function (g) { return g.parsed; });
      badge.textContent = loaded.length ? loaded.map(function (g) { return g.label; }).join(' · ')
        : 'Load the Pinnacle slate and pick matches';
    }
  }

  function render() {
    var bodyEl = $('wcBody');
    if (!bodyEl) return;
    var loaded = state.games.filter(function (g) { return g.parsed; });
    if (!loaded.length) {
      bodyEl.innerHTML = '<div class="empty">Load the Pinnacle slate and pick one or more matches to begin.</div>';
      var cnt0 = $('wcCount');
      if (cnt0) cnt0.textContent = '';
      return;
    }
    var multi = loaded.length > 1;
    var rows = [];
    loaded.forEach(function (g) {
      g.candidates
        .filter(function (c) { return state.enabledCats[KIND_CATS[c.market_key] || 'team'] !== false; })
        .forEach(function (c) {
          rows.push({ g: g, c: c, dk: g.dkById[c.id], ev: evFor(g, c) });
        });
    });
    rows = rows
      .filter(function (r) {
        if (state.matchedOnly && !r.ev) return false;
        if (state.maxOddsCap) {
          var am = r.ev ? dkAmericanNum(r.dk, r.ev) : r.c.pin_odds;
          if (am != null && am > 1000) return false;
        }
        return true;
      })
      .sort(function (a, b) {
        var ea = a.ev ? a.ev.evPct : -1e9, eb = b.ev ? b.ev.evPct : -1e9;
        return eb - ea;
      });

    // Always the top 20 of whatever passes the filters — changing a filter
    // recomputes a fresh top 20.
    var total = rows.length;
    rows = rows.slice(0, 20);

    var cnt = $('wcCount');
    if (cnt) cnt.textContent = total > rows.length ?
      ('top ' + rows.length + ' of ' + total) : (rows.length + ' rows');

    if (!rows.length) {
      bodyEl.innerHTML = '<div class="empty">No selections pass the current filters.</div>';
      return;
    }

    var html = '<table style="width:100%;border-collapse:collapse;font-family:Space Mono,monospace;font-size:12px">' +
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
      html += '<tr style="border-top:1px solid var(--b1)">' +
        (multi ? '<td style="padding:7px 10px;color:var(--mu);white-space:nowrap">' + esc(r.g.parsed.home + ' v ' + r.g.parsed.away) + '</td>' : '') +
        '<td style="padding:7px 10px;color:var(--cyan);white-space:nowrap">' + (c.group_label || MARKET_LABELS[c.market_key] || c.market_key) +
          (dk && dk.via === 'sgp' ? ' <span style="font-size:9px;color:var(--ac);border:1px solid var(--ac);border-radius:3px;padding:0 3px" title="Priced as a real 2-leg SGP via DK calculateBets — boost-eligible. Legs: ' + String(dk.dk_market || '').replace(/"/g, '&quot;') + '">SGP</span>' : '') + '</td>' +
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

    loaded.forEach(function (g) {
      if (g.dkMeta && g.dkMeta.available_markets && g.dkMeta.available_markets.length) {
        html += '<details style="margin-top:6px;font-size:10px;color:var(--mu);font-family:Space Mono,monospace">' +
          '<summary style="cursor:pointer">DK markets seen on ' + esc(g.label) + ' (' + g.dkMeta.available_markets.length + ')</summary>' +
          '<div style="margin-top:4px;line-height:1.7">' + g.dkMeta.available_markets.join(' · ') + '</div></details>';
      }
    });
    bodyEl.innerHTML = html;
  }

  /* ---- controls ---- */

  function onFilter() {
    var mo = $('wcMatchedOnly');
    if (mo) state.matchedOnly = !!mo.checked;
    var cap = $('wcMaxOdds');
    if (cap) state.maxOddsCap = !!cap.checked;
    render();
  }

  /* Click selects ONLY that category. Clicking the lone active category
     again restores all categories. */
  function onMarketBtn(btn) {
    var key = btn.getAttribute('data-wc-cat');
    if (!key) return;
    var active = CATS.filter(function (k) { return state.enabledCats[k]; });
    var soloAlready = active.length === 1 && active[0] === key;
    CATS.forEach(function (k) { state.enabledCats[k] = soloAlready ? true : (k === key); });
    document.querySelectorAll('[data-wc-cat]').forEach(function (b) {
      b.classList.toggle('active', !!state.enabledCats[b.getAttribute('data-wc-cat')]);
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
    loadLeagues();
    render();
  }

  window.worldcupTab = {
    onActivate: onActivate,
    loadLeagues: loadLeagues,
    onLeagueChange: onLeagueChange,
    loadPinnySlate: loadPinnySlate,
    onPinMatchPick: onPinMatchPick,
    removeGame: removeGame,
    runScan: runScan,
    onFilter: onFilter,
    onMarketBtn: onMarketBtn,
    onLeagueIdChange: onLeagueIdChange,
  };
})();
