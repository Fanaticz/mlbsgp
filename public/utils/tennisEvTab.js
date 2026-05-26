/* tennisEvTab.js — Tennis SGP +EV tab (French Open men's, v1).
 *
 * SGP build target: 1st Set Total Over X.5 × Underdog full-match Game
 * Handicap. Correlations are hardcoded sport-wide priors:
 *   8.5 → 0.20 ; 9.5 → 0.27 ; 10.5 → 0.30 ; 12.5 → 0.34
 *
 * Two FV-sheet uploads (one per market). OCR rows merge by `game`
 * string; per-match we generate one candidate per (set1_total_line,
 * dog_match_handicap_line) combination from the uploaded rows.
 *
 * Fair-price source toggle:
 *   FV         — use the sheet's signed `fv` integer as the fair American
 *                for each leg (default).
 *   PIN NO-VIG — no-vig the sheet's `devig_odds` two-sided pair
 *                (the `sharp:Pinnacle` column from the FV source).
 *                Effectively "use Pinnacle no-vig as fair."
 *   DK NO-VIG  — no-vig the DK two-sided `book_odds` pair instead.
 *
 * Joint probability: jointFrechet(pa, pb, r) from sgpMath.js — same
 * function the pitcher / teammate / NBA pipelines use.
 *
 * Surfaces only the underdog side of Game Spread rows. Favorites have
 * the opposite-signed correlation; we drop those rows server-side
 * downstream by ignoring negative-line spread rows.
 */
(function () {
  'use strict';
  if (!window.sgpMath) {
    console.error('tennisEvTab: sgpMath missing — script load order broke');
    return;
  }
  var SGM = window.sgpMath;

  // Hardcoded sport priors. Keyed by 1st-set total line (Over side).
  // If the user wants per-event uploaded correlations later we can swap
  // this for a runtime-loaded map mirroring the NBA pattern.
  var CORR_BY_LINE = { 8.5: 0.20, 9.5: 0.27, 10.5: 0.30, 12.5: 0.34 };
  var SUPPORTED_LINES = [8.5, 9.5, 10.5, 12.5];

  // Tab state.
  //
  // Two parallel candidate sources, each consumed by a different fairMode:
  //   autoCands  — straight from DK /api/dk/tennis-autoscan (no FV sheets
  //                needed). Carries full DK two-sided + DK SGP price.
  //                Source for DK NO-VIG mode.
  //   sheetCands — built from OCR'd FV-sheet rows merged by game string.
  //                Carries fv + book_odds + devig_odds per leg. Source
  //                for FV and PIN NO-VIG modes.
  // dkResults still maps sheet-candidate id → DK pricing row (legacy
  // sheet pipeline path; lazy-priced via /api/dk/find-sgps-tennis).
  var state = {
    rowsTotal: [],         // parsed 1st-set-total leg rows (sheet)
    rowsSpread: [],        // parsed game-spread leg rows (sheet, dog side only)
    sheetCands: [],        // sheet-sourced candidate objects
    autoCands: [],         // DK-autoscan-sourced candidate objects
    dkResults: {},         // sheet candidate.id → DK price row
    fairMode: 'dk',        // 'fv' | 'pinnacle' | 'dk' (DK is the default now)
    enabledLines: { 8.5: true, 9.5: true, 10.5: true, 12.5: true },
    matchedOnly: true,
    minEv: 0,
    activated: false,
  };

  function $(id) { return document.getElementById(id); }
  function setStatus(msg, color) {
    var el = $('tnsStatus'); if (!el) return;
    el.textContent = msg || '';
    el.style.color = color || 'var(--mu)';
  }

  // American → implied prob, deferring to sgpMath for the actual math.
  function americanToProb(o) { return SGM.americanToProb(o); }
  function americanToDecimal(o) { return SGM.americanToDecimal(o); }

  // Parse DK's two-sided "X / Y" string. Returns [a, b] American integers
  // or null. Tolerates spaces and the unicode minus.
  function parseTwoSided(s) {
    if (!s) return null;
    var clean = String(s).replace(/−/g, '-');
    var m = clean.match(/([+-]?\d+)\s*\/\s*([+-]?\d+)/);
    if (!m) return null;
    return [Number(m[1]), Number(m[2])];
  }

  // No-vig a two-sided American pair. Returns the fair probability for
  // the FIRST side. e.g. "-150/+100" → 0.6/(0.6+0.5) = 0.5455.
  function noVigProbForSideA(twoSided) {
    if (!twoSided || twoSided.length !== 2) return null;
    var pa = americanToProb(twoSided[0]);
    var pb = americanToProb(twoSided[1]);
    if (pa == null || pb == null) return null;
    var sum = pa + pb;
    if (sum <= 0) return null;
    return pa / sum;
  }

  // Best-effort canonical match key for a game string. Strips
  // punctuation, lowercases, splits on "@" or "vs", sorts the two
  // player tokens so "A @ B" and "B @ A" hash equally.
  function gameKey(g) {
    if (!g) return '';
    var s = String(g).toLowerCase().replace(/[.,]/g, '').trim();
    var parts = s.split(/\s*(?:@|vs\.?)\s*/);
    if (parts.length !== 2) return s;
    var a = parts[0].trim();
    var b = parts[1].trim();
    return (a < b) ? a + '|' + b : b + '|' + a;
  }

  // Last-name extractor for matching a spread row's player to one of
  // the two `game` participants. Returns lowercased last name.
  function lastName(name) {
    if (!name) return '';
    var t = String(name).trim().split(/\s+/);
    return (t[t.length - 1] || '').toLowerCase();
  }

  // Index rows by game key. Returns { keyedTotals, keyedSpreads }.
  function indexByGame() {
    var T = {}, S = {};
    state.rowsTotal.forEach(function (r) {
      var k = gameKey(r.game);
      (T[k] = T[k] || []).push(r);
    });
    state.rowsSpread.forEach(function (r) {
      if (!r.isDog) return;  // dog side only — favorite has opposite corr
      var k = gameKey(r.game);
      (S[k] = S[k] || []).push(r);
    });
    return { T: T, S: S };
  }

  // Build SGP candidates from indexed rows. One candidate per
  // (game, total_line, dog_handicap_line).
  function rebuildCandidates() {
    var idx = indexByGame();
    var cands = [];
    Object.keys(idx.T).forEach(function (k) {
      var totals = idx.T[k];
      var spreads = idx.S[k] || [];
      if (!spreads.length) return;
      // Dedupe spreads by (player, line) — same row sometimes appears
      // twice across re-uploads.
      var sSeen = {};
      spreads = spreads.filter(function (s) {
        var key = lastName(s.player) + '|' + s.mag;
        if (sSeen[key]) return false;
        sSeen[key] = true;
        return true;
      });
      // Pick the Over-side total rows whose line is in our supported set.
      totals.forEach(function (t) {
        if (t.side !== 'Over') return;
        if (!CORR_BY_LINE.hasOwnProperty(t.line)) return;
        spreads.forEach(function (s) {
          cands.push({
            id: [k, t.line, lastName(s.player), s.mag].join('::'),
            game: t.game || s.game,
            player_dog: s.player,
            set1_total_line: t.line,
            set1_total_side: 'Over',
            match_handicap_line: s.mag,        // magnitude (always +)
            // Per-leg FV + book_odds, used by computeEv. We carry the
            // OCR rows directly so the renderer can show source data.
            legTotal: t,
            legSpread: s,
            r: CORR_BY_LINE[t.line],
          });
        });
      });
    });
    state.sheetCands = cands;
  }

  // Compute the fair probabilities + joint + EV for one candidate,
  // using the current fairMode. Returns null if any required input is
  // unavailable. `dkRow` is the DK pricing row (or null when unmatched).
  function computeEv(c, dkRow) {
    var pa = null, pb = null, paSrc = '', pbSrc = '';
    if (state.fairMode === 'dk' || state.fairMode === 'pinnacle') {
      // Both modes share the same no-vig math; only the source pair
      // differs. DK reads `book_odds` (the DK two-sided column);
      // Pinnacle reads `devig_odds` (the sharp.Pinnacle two-sided
      // column the FV sheet already carries). In both cases side-A of
      // the pair corresponds to the leg as named in `bet_name`:
      //   Total  row: "Over X.5"            ⇒ side-A is the Over price
      //   Spread row: "<player> +X.5"       ⇒ side-A is the dog's price
      var useDevig = state.fairMode === 'pinnacle';
      var totalPair  = parseTwoSided(useDevig ? c.legTotal.devig_odds  : c.legTotal.book_odds);
      var spreadPair = parseTwoSided(useDevig ? c.legSpread.devig_odds : c.legSpread.book_odds);
      var srcTag = useDevig ? 'PIN' : 'DK';
      if (totalPair) {
        pa = noVigProbForSideA(totalPair);
        paSrc = srcTag + ' ' + totalPair[0] + '/' + totalPair[1];
      }
      if (spreadPair) {
        pb = noVigProbForSideA(spreadPair);
        pbSrc = srcTag + ' ' + spreadPair[0] + '/' + spreadPair[1];
      }
    } else {
      // FV mode: use the sheet's signed `fv` integer for each leg.
      if (c.legTotal.fv != null) {
        pa = americanToProb(c.legTotal.fv);
        paSrc = 'FV ' + (c.legTotal.fv > 0 ? '+' : '') + c.legTotal.fv;
      }
      if (c.legSpread.fv != null) {
        pb = americanToProb(c.legSpread.fv);
        pbSrc = 'FV ' + (c.legSpread.fv > 0 ? '+' : '') + c.legSpread.fv;
      }
    }
    if (pa == null || pb == null) {
      return { ok: false, paSrc: paSrc, pbSrc: pbSrc, reason: 'fair_unavailable' };
    }
    var pJoint = SGM.jointFrechet(pa, pb, c.r);
    var fairAmerican = SGM.probToAmerican(pJoint);
    var dkDecimal = dkRow && dkRow.matched ? dkRow.dk_decimal : null;
    var dkOdds = dkRow && dkRow.matched ? dkRow.dk_odds : null;
    var evPct = null, kellyPct = null, attrib = null;
    if (dkDecimal) {
      evPct = (pJoint * dkDecimal - 1) * 100;
      kellyPct = (pJoint * dkDecimal - 1) / (dkDecimal - 1) * 100;
      attrib = SGM.evAttribution(pa, pb, c.r, dkDecimal);
    }
    return {
      ok: true,
      pa: pa, pb: pb, paSrc: paSrc, pbSrc: pbSrc,
      r: c.r, pJoint: pJoint,
      fairAmerican: fairAmerican,
      dkOdds: dkOdds, dkDecimal: dkDecimal,
      evPct: evPct, kellyPct: kellyPct, attrib: attrib,
    };
  }

  // ===== upload handling =====
  async function onUpload(event, marketKey) {
    var file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file) return;
    var statusEl = $('tnsStatus' + (marketKey === 'total' ? 'Total' : 'Spread'));
    if (statusEl) { statusEl.textContent = 'uploading…'; statusEl.style.color = 'var(--ac3)'; }
    try {
      var b64 = await fileToBase64(file);
      var r = await fetch('/api/extract-tennis', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ image: b64, mime: file.type || 'image/png' }),
      });
      var j = await r.json();
      if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
      // Bucket the rows into the slot the user dropped on. We trust the
      // upload zone the user picked rather than the per-row market, so
      // a sheet that mixes markets still flows to the right bucket.
      // BUT — we filter to the matching kind so an accidental wrong-sheet
      // drop doesn't poison the spread bucket with total rows or vice versa.
      var wantKind = marketKey === 'total' ? 'total' : 'spread';
      var keep = (wantKind === 'total' ? j.totals : j.spreads) || [];
      if (wantKind === 'total') {
        state.rowsTotal = keep;
      } else {
        state.rowsSpread = keep;
      }
      var nTot = state.rowsTotal.length, nSpr = state.rowsSpread.length;
      if (statusEl) {
        statusEl.style.color = 'var(--ac)';
        statusEl.textContent = keep.length + ' rows parsed' +
          (j.unmatched && j.unmatched.length ? ' (' + j.unmatched.length + ' skipped)' : '');
      }
      setStatus('Loaded ' + nTot + ' total rows · ' + nSpr + ' spread rows.', 'var(--mu)');
      rebuildCandidates();
      render();
      // Auto-price sheet candidates if both buckets are populated and
      // the user is on an FV/PIN mode. DK NO-VIG mode doesn't need this
      // — those candidates come from the autoscan path.
      if (state.sheetCands.length && state.fairMode !== 'dk') {
        runScan();
      }
    } catch (e) {
      if (statusEl) { statusEl.style.color = 'var(--red)'; statusEl.textContent = 'failed: ' + e.message; }
      setStatus('Upload failed: ' + e.message, 'var(--red)');
    }
  }

  function fileToBase64(file) {
    return new Promise(function (resolve, reject) {
      var fr = new FileReader();
      fr.onload = function () {
        var s = String(fr.result || '');
        var i = s.indexOf(',');
        resolve(i >= 0 ? s.slice(i + 1) : s);
      };
      fr.onerror = function () { reject(new Error('file read failed')); };
      fr.readAsDataURL(file);
    });
  }

  // ===== DK auto-scan (primary path; no FV sheet required) =====
  async function runAutoScan() {
    var btn = $('tnsAutoScanBtn'); if (btn) { btn.disabled = true; btn.style.opacity = '.5'; }
    setStatus('Scanning DK for tennis slate…', 'var(--ac3)');
    try {
      var params = { lines: Object.keys(state.enabledLines).filter(function (k) { return state.enabledLines[k]; }).map(Number) };
      var r = await fetch('/api/dk/tennis-autoscan', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(params),
      });
      var j = await r.json();
      if (!r.ok || (j.error && !j.candidates)) throw new Error(j.error || ('HTTP ' + r.status));
      // Shim auto-candidate rows into the same shape sheet-candidates use
      // (legTotal / legSpread objects carrying a synthesized book_odds
      // string). That lets computeEv / renderCard branch only on
      // fairMode, not on candidate source. `source:'auto'` marks the
      // candidate so render() can pick the DK price baked into the row
      // instead of looking up state.dkResults.
      state.autoCands = (j.candidates || []).map(function (c) {
        var totBookOdds = (c.leg_1_over_american != null && c.leg_1_under_american != null)
          ? (c.leg_1_over_american + ' / ' + c.leg_1_under_american)
          : '';
        var spdBookOdds = (c.leg_2_dog_american != null && c.leg_2_fav_american != null)
          ? (c.leg_2_dog_american + ' / ' + c.leg_2_fav_american)
          : '';
        return Object.assign({}, c, {
          source: 'auto',
          r: CORR_BY_LINE[c.set1_total_line] || 0,
          game: c.game_name || c.game,
          player_dog: c.dog_player,
          set1_total_side: 'Over',
          legTotal:  { book_odds: totBookOdds, fv: null, devig_odds: '' },
          legSpread: { book_odds: spdBookOdds, fv: null, devig_odds: '', isDog: true },
        });
      });
      var matched = state.autoCands.filter(function (c) { return c.matched; }).length;
      setStatus(state.autoCands.length + ' candidates across ' + (j.events_scanned || []).length + '/' +
        (j.events_total || '?') + ' events · ' + matched + ' priced' +
        (j.cached ? ' (cached ' + j.cache_age_s + 's)' : '') +
        (j.truncated ? ' · TRUNCATED' : ''),
        matched ? 'var(--ac)' : 'var(--ac2)');
      // If FV/PIN was the active mode but no sheet data is loaded, kick
      // back to DK mode so the user sees results immediately.
      if ((state.fairMode === 'fv' || state.fairMode === 'pinnacle') &&
          !state.sheetCands.length) {
        setFairMode('dk');
      }
      render();
    } catch (e) {
      setStatus('DK scan failed: ' + e.message, 'var(--red)');
    } finally {
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    }
  }

  // ===== DK scan (legacy sheet-driven path) =====
  // Called from the sheet pipeline after both FV uploads — prices the
  // sheet-merged candidate list via /api/dk/find-sgps-tennis. Still
  // wired so FV/PIN modes get DK prices without firing a full autoscan.
  async function runScan() {
    if (!state.sheetCands.length) {
      setStatus('No sheet candidates yet — upload both FV sheets first.', 'var(--ac2)');
      return;
    }
    setStatus('Pricing ' + state.sheetCands.length + ' sheet candidates via DK…', 'var(--ac3)');
    try {
      var body = {
        candidates: state.sheetCands.map(function (c) {
          return {
            id: c.id,
            player_dog: c.player_dog,
            event: c.game,
            set1_total_line: c.set1_total_line,
            set1_total_side: c.set1_total_side,
            match_handicap_line: c.match_handicap_line,
          };
        }),
      };
      var r = await fetch('/api/dk/find-sgps-tennis', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      var j = await r.json();
      if (!r.ok || (j.error && !j.results)) throw new Error(j.error || ('HTTP ' + r.status));
      state.dkResults = {};
      (j.results || []).forEach(function (row) { state.dkResults[row.id] = row; });
      var matched = (j.results || []).filter(function (r) { return r.matched; }).length;
      setStatus(matched + ' of ' + state.sheetCands.length + ' sheet candidates matched' +
        (j.cached ? ' (cached ' + j.cache_age_s + 's)' : '') +
        (j.truncated ? ' · TRUNCATED' : ''),
        matched ? 'var(--ac)' : 'var(--ac2)');
      render();
    } catch (e) {
      setStatus('DK scan failed: ' + e.message, 'var(--red)');
    } finally {
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    }
  }

  // ===== UI control handlers =====
  function setFairMode(mode) {
    if (mode !== 'fv' && mode !== 'dk' && mode !== 'pinnacle') return;
    state.fairMode = mode;
    var fv = $('tnsFairFv'), pin = $('tnsFairPin'), dk = $('tnsFairDk');
    function on(el) { el.style.background = 'rgba(34,197,94,.12)'; el.style.color = 'var(--ac)'; }
    function off(el) { el.style.background = 'transparent'; el.style.color = 'var(--mu)'; }
    if (fv)  (mode === 'fv'       ? on : off)(fv);
    if (pin) (mode === 'pinnacle' ? on : off)(pin);
    if (dk)  (mode === 'dk'       ? on : off)(dk);
    render();
  }
  function onLineBtn(btn) {
    var line = Number(btn.getAttribute('data-tns-line'));
    state.enabledLines[line] = !state.enabledLines[line];
    btn.classList.toggle('active', !!state.enabledLines[line]);
    render();
  }
  function onFilter() {
    var ev = $('tnsMinEv'); if (ev) {
      state.minEv = Number(ev.value);
      var lab = $('tnsMinEvV'); if (lab) lab.textContent = (state.minEv >= 0 ? '+' : '') + state.minEv + '%';
    }
    var mo = $('tnsMatchedOnly'); if (mo) state.matchedOnly = !!mo.checked;
    render();
  }

  // ===== rendering =====
  function fmtPct(p) {
    if (p == null || isNaN(p)) return '—';
    return (p * 100).toFixed(1) + '%';
  }
  function fmtAmerican(a) {
    if (a == null || isNaN(a)) return '—';
    return (a > 0 ? '+' : '') + a;
  }
  function fmtEv(ev) {
    if (ev == null || isNaN(ev)) return '—';
    return (ev >= 0 ? '+' : '') + ev.toFixed(2) + '%';
  }
  function evColor(ev) {
    if (ev == null || isNaN(ev)) return 'var(--mu)';
    if (ev >= 5) return 'var(--ac)';
    if (ev >= 0) return 'var(--ac3)';
    return 'var(--red)';
  }
  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function render() {
    var body = $('tnsBody'); if (!body) return;
    // Pick the candidate source for the active fair mode.
    //   DK NO-VIG → autoscan candidates (no sheet needed)
    //   FV / PIN  → sheet-merged candidates
    var src = (state.fairMode === 'dk') ? state.autoCands : state.sheetCands;
    if (!src.length) {
      var empty;
      if (state.fairMode === 'dk') {
        empty = 'Click SCAN DK to pull tonight\'s slate and price every supported SGP.';
      } else if (state.fairMode === 'pinnacle') {
        empty = 'PIN NO-VIG reads the sheet\'s devig_odds column — open the FV uploads panel and drop both sheets.';
      } else {
        empty = 'FV mode reads the sheet\'s fv column — open the FV uploads panel and drop both sheets.';
      }
      body.innerHTML = '<div class="empty" style="padding:30px;text-align:center;color:var(--mu);font-family:Space Mono,monospace;font-size:12px">' + escapeHtml(empty) + '</div>';
      var cnt = $('tnsCount'); if (cnt) cnt.textContent = '';
      return;
    }
    // Compute EV per candidate. For auto candidates, the DK price is
    // baked into the row. For sheet candidates, fall back to the
    // state.dkResults map (populated by the legacy runScan path).
    var rows = src.map(function (c) {
      var dk = (c.source === 'auto')
        ? {
            matched:   !!c.matched,
            dk_odds:    c.dk_odds,
            dk_decimal: c.dk_decimal,
            missing:    c.missing,
          }
        : (state.dkResults[c.id] || null);
      var ev = computeEv(c, dk);
      return { c: c, dk: dk, ev: ev };
    });
    // Apply filters.
    var filtered = rows.filter(function (r) {
      if (!state.enabledLines[r.c.set1_total_line]) return false;
      if (state.matchedOnly && !(r.dk && r.dk.matched)) return false;
      if (r.ev.ok && r.ev.evPct != null && r.ev.evPct < state.minEv) return false;
      return true;
    });
    // Sort by EV desc when DK is priced; un-priced rows sink to the bottom.
    filtered.sort(function (a, b) {
      var ea = (a.ev && a.ev.evPct != null) ? a.ev.evPct : -Infinity;
      var eb = (b.ev && b.ev.evPct != null) ? b.ev.evPct : -Infinity;
      return eb - ea;
    });
    var cnt = $('tnsCount');
    if (cnt) cnt.textContent = filtered.length + ' of ' + rows.length + ' candidates';
    if (!filtered.length) {
      body.innerHTML = '<div class="empty" style="padding:30px;text-align:center;color:var(--mu);font-family:Space Mono,monospace;font-size:12px">No candidates match the current filters.</div>';
      return;
    }
    body.innerHTML = filtered.map(renderCard).join('');
  }

  function renderCard(row) {
    var c = row.c, ev = row.ev, dk = row.dk;
    var evPct = ev.ok ? ev.evPct : null;
    var ec = evColor(evPct);
    var matchedLabel = '';
    if (dk && dk.matched) matchedLabel = '<span style="color:var(--ac);font-size:9px">DK MATCHED</span>';
    else if (dk && dk.missing) matchedLabel = '<span style="color:var(--ac2);font-size:9px" title="' + escapeHtml((dk.missing||[]).join(' · ')) + '">DK MISSING</span>';
    else matchedLabel = '<span style="color:var(--mu);font-size:9px">NOT PRICED YET</span>';
    var corrPct = (c.r * 100).toFixed(0);
    var legTotal = c.legTotal, legSpread = c.legSpread;
    var totalBookOdds = legTotal.book_odds || '—';
    var spreadBookOdds = legSpread.book_odds || '—';
    var fvTotal = legTotal.fv != null ? (legTotal.fv > 0 ? '+' : '') + legTotal.fv : '—';
    var fvSpread = legSpread.fv != null ? (legSpread.fv > 0 ? '+' : '') + legSpread.fv : '—';
    var paLabel = ev.ok ? fmtPct(ev.pa) : '—';
    var pbLabel = ev.ok ? fmtPct(ev.pb) : '—';
    var pJointLabel = ev.ok ? fmtPct(ev.pJoint) : '—';
    var fairLabel = ev.ok ? fmtAmerican(ev.fairAmerican) : '—';
    var rGapStr = '';
    if (ev.ok && ev.attrib && ev.attrib.rGap != null) {
      var rg = ev.attrib.rGap;
      rGapStr = ' · r gap ' + (rg >= 0 ? '+' : '') + rg.toFixed(3);
    }
    return '' +
      '<div class="card" style="margin:10px 0;border:1px solid var(--b1);border-radius:9px;padding:12px 14px;background:var(--s1)">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">' +
          '<div style="font-family:Inter,sans-serif;font-weight:700;font-size:13px;color:var(--tx)">' + escapeHtml(c.game) + '</div>' +
          '<div style="display:flex;gap:8px;align-items:center">' +
            matchedLabel +
            '<span style="font-family:Space Mono,monospace;font-size:11px;color:var(--mu)">r = ' + corrPct + '%</span>' +
          '</div>' +
        '</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;font-family:Space Mono,monospace;font-size:11px">' +
          '<div style="padding:8px;border:1px solid var(--b1);border-radius:6px;background:var(--s2)">' +
            '<div style="color:var(--cyan);font-weight:700;margin-bottom:4px">LEG 1 — Over ' + c.set1_total_line + ' 1st Set Total</div>' +
            '<div style="color:var(--mu)">DK two-sided: <span style="color:var(--tx)">' + escapeHtml(totalBookOdds) + '</span></div>' +
            '<div style="color:var(--mu)">FV (sheet): <span style="color:var(--tx)">' + fvTotal + '</span></div>' +
            '<div style="color:var(--mu)">pa = <span style="color:var(--ac)">' + paLabel + '</span> <span style="font-size:9px">(' + escapeHtml(ev.paSrc || '—') + ')</span></div>' +
          '</div>' +
          '<div style="padding:8px;border:1px solid var(--b1);border-radius:6px;background:var(--s2)">' +
            '<div style="color:var(--cyan);font-weight:700;margin-bottom:4px">LEG 2 — ' + escapeHtml(c.player_dog) + ' +' + c.match_handicap_line + ' Game Handicap</div>' +
            '<div style="color:var(--mu)">DK two-sided: <span style="color:var(--tx)">' + escapeHtml(spreadBookOdds) + '</span></div>' +
            '<div style="color:var(--mu)">FV (sheet): <span style="color:var(--tx)">' + fvSpread + '</span></div>' +
            '<div style="color:var(--mu)">pb = <span style="color:var(--ac)">' + pbLabel + '</span> <span style="font-size:9px">(' + escapeHtml(ev.pbSrc || '—') + ')</span></div>' +
          '</div>' +
        '</div>' +
        '<div style="margin-top:10px;display:grid;grid-template-columns:repeat(4,1fr);gap:10px;font-family:Space Mono,monospace;font-size:11px">' +
          '<div><div style="color:var(--mu);font-size:9px">FAIR JOINT</div><div style="color:var(--tx);font-weight:700">' + pJointLabel + '</div></div>' +
          '<div><div style="color:var(--mu);font-size:9px">FAIR ODDS</div><div style="color:var(--tx);font-weight:700">' + fairLabel + '</div></div>' +
          '<div><div style="color:var(--mu);font-size:9px">DK PRICE</div><div style="color:var(--tx);font-weight:700">' + escapeHtml(ev.dkOdds || '—') + '</div></div>' +
          '<div><div style="color:var(--mu);font-size:9px">EV%</div><div style="color:' + ec + ';font-weight:700">' + fmtEv(evPct) + '</div></div>' +
        '</div>' +
        '<div style="margin-top:6px;color:var(--mu);font-family:Space Mono,monospace;font-size:9px">' +
          'fair mode: ' + (
            state.fairMode === 'dk' ? 'DK no-vig' :
            state.fairMode === 'pinnacle' ? 'Pinnacle no-vig (sheet devig_odds)' :
            'FV sheet'
          ) + rGapStr +
        '</div>' +
      '</div>';
  }

  // ===== lifecycle =====
  function onActivate() {
    if (state.activated) return;
    state.activated = true;
    // Wire drop-zone click + drag/drop on the two upload boxes.
    [['tnsDropTotal', 'tnsFileTotal'], ['tnsDropSpread', 'tnsFileSpread']].forEach(function (pair) {
      var drop = $(pair[0]), file = $(pair[1]);
      if (!drop || !file) return;
      drop.addEventListener('click', function () { file.click(); });
      drop.addEventListener('dragover', function (e) {
        e.preventDefault(); drop.style.borderColor = 'var(--ac)';
      });
      drop.addEventListener('dragleave', function () { drop.style.borderColor = 'var(--b2)'; });
      drop.addEventListener('drop', function (e) {
        e.preventDefault(); drop.style.borderColor = 'var(--b2)';
        var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (!f) return;
        var dt = new DataTransfer(); dt.items.add(f); file.files = dt.files;
        file.dispatchEvent(new Event('change'));
      });
    });
    // Sync the fair-mode button highlighting to the runtime default
    // (DK NO-VIG). The HTML's static `background:rgba(...)` already
    // marks the DK button green; this catches any post-load drift.
    setFairMode(state.fairMode);
    render();
    // Kick the DK autoscan automatically on first activation. Cached
    // server-side for 10 min so the second activation is free.
    runAutoScan();
  }

  window.tennisTab = {
    onActivate: onActivate,
    onUpload: onUpload,
    runScan: runScan,
    runAutoScan: runAutoScan,
    setFairMode: setFairMode,
    onLineBtn: onLineBtn,
    onFilter: onFilter,
  };
}());
