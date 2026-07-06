/* fvFallback.js — FV-only ("screenshot mode") fallback helpers for the
   pitcher +EV finder. When DraftKings SGP pricing is unreachable (Akamai
   403 storm, DK outage, network failure) the frontend can't rank combos by
   EV%, but the uploaded FV sheet still carries everything needed to compute
   each combo's correlated fair value: per-leg avg_fv + the correlation
   aggregates already loaded in the page. These helpers cover the pure,
   Node-testable parts of that path — combo enumeration against the
   combo_spec whitelist and the "low odds → high odds" ordering — so the
   math can be smoke-tested without a browser. UMD: works as <script> in
   browser (window.fvFallback) or require() in Node. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.fvFallback = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {

  /* Order-insensitive combo identity. combo_spec.json stores each pair/
     triple once in canonical stat-category order; OCR rows arrive in sheet
     order — sorting the leg strings before joining makes lookup robust to
     both. '||' can't occur inside a leg string ("Over 4.5 Strikeouts"). */
  function comboKey(legs) {
    return legs.slice().sort().join('||');
  }

  /* combo_spec.json → { 2: {key:true,...}, 3: {...} } lookup maps.
     Plain objects rather than Set to match the ES5 style of the rest of
     the frontend bundle. Missing/malformed spec yields nulls — callers
     treat a null map as "whitelist unavailable" and apply their own
     validity rule. */
  function buildSpecSets(spec) {
    function toMap(list) {
      if (!Array.isArray(list) || !list.length) return null;
      var m = {};
      for (var i = 0; i < list.length; i++) {
        if (Array.isArray(list[i])) m[comboKey(list[i])] = true;
      }
      return m;
    }
    return {
      2: spec ? toMap(spec.pairs_2) : null,
      3: spec ? toMap(spec.triples_3) : null,
    };
  }

  function isWhitelisted(specSets, size, legs) {
    var m = specSets && specSets[size];
    if (!m) return null; /* unknown — no whitelist available */
    return !!m[comboKey(legs)];
  }

  /* Stat category of a canonical leg string. Mirrors index.html's statCat
     (order matters: 'Strikeouts' must not match the 'Out' check — it
     doesn't, the checks are case-sensitive). */
  function statCatOf(leg) {
    if (leg.indexOf('Strikeout') >= 0) return 'SO';
    if (leg.indexOf('Earned Run') >= 0) return 'ER';
    if (leg.indexOf('Walk') >= 0) return 'BB';
    if (leg.indexOf('Hit') >= 0) return 'H';
    if (leg.indexOf('Out') >= 0) return 'OUTS';
    return '';
  }

  /* Combo legality without DK to ask. The server-side find_sgps enumerates
     every same-pitcher combo unfiltered and lets DK's calculateBets reject
     incompatible ones — with DK unreachable we approximate that judgment:
       - All legs on DISTINCT stat categories → legal. Cross-stat pitcher
         props always parlay in a DK SGP; this covers both directions of
         every stat, including the "bad outing" side (Over Walks, Under
         Strikeouts, ...) that combo_spec never enumerates.
       - Any shared stat category → legal only if the combo appears
         VERBATIM in the combo_spec whitelist (the Over-K-style ladders).
         This also rejects contradictory Over/Under of the same leg, and
         conservatively drops unlisted same-stat shapes rather than
         guessing what DK would allow. */
  function isLegalCombo(specSets, size, legs) {
    var seen = {};
    var distinct = true;
    for (var i = 0; i < legs.length; i++) {
      var c = statCatOf(legs[i]);
      if (!c || seen[c]) { distinct = false; break; }
      seen[c] = 1;
    }
    if (distinct) return true;
    return isWhitelisted(specSets, size, legs) === true;
  }

  /* C(n, size) index combinations in lexicographic order. size is 2 or 3
     in practice; written generically anyway. */
  function _combinations(n, size) {
    var out = [];
    function rec(start, acc) {
      if (acc.length === size) { out.push(acc.slice()); return; }
      for (var i = start; i < n; i++) { acc.push(i); rec(i + 1, acc); acc.pop(); }
    }
    rec(0, []);
    return out;
  }

  /* enumerate(rows, size, validFn, sortKey) — group OCR'd legs by pitcher
     and emit every valid same-pitcher combo of the requested size.
       rows:    [{pitcher, leg, avg_fv, _fv_suspicious}, ...] (OCR output)
       size:    2 or 3
       validFn: (legStrings[]) => bool — combo validity (whitelist or rule)
       sortKey: optional (legString) => string — orders each combo's legs
                (stat-category sort, mirroring dk_api.find_sgps' stable
                orientation) so cards render consistently across sheets.
     Returns [{pitcher, rows:[legRow,...]}]. Pitchers with fewer than
     `size` usable legs contribute nothing. */
  function enumerate(rows, size, validFn, sortKey) {
    var byPitcher = {};
    var order = [];
    (rows || []).forEach(function (r) {
      if (!r || !r.pitcher || !r.leg) return;
      if (!byPitcher[r.pitcher]) { byPitcher[r.pitcher] = []; order.push(r.pitcher); }
      byPitcher[r.pitcher].push(r);
    });
    var out = [];
    order.forEach(function (p) {
      var legs = byPitcher[p];
      if (legs.length < size) return;
      _combinations(legs.length, size).forEach(function (idx) {
        var comboRows = idx.map(function (i) { return legs[i]; });
        if (validFn && !validFn(comboRows.map(function (r) { return r.leg; }))) return;
        if (sortKey) {
          comboRows = comboRows.slice().sort(function (a, b) {
            var ka = sortKey(a.leg) || '', kb = sortKey(b.leg) || '';
            return ka < kb ? -1 : ka > kb ? 1 : 0;
          });
        }
        out.push({ pitcher: p, rows: comboRows });
      });
    });
    return out;
  }

  /* "Low odds → high odds": ascending American fair-value odds, which is
     exactly descending joint probability (a -300 FV is a higher-probability
     combo than a +250 FV). Sorting on the probability instead of the
     rounded American integer avoids rounding ties flipping order. Ties
     break by pitcher then leg strings so renders are deterministic. */
  function sortByFvOddsAscending(combos, getProb) {
    return combos.slice().sort(function (a, b) {
      var pa = getProb(a), pb = getProb(b);
      var va = (pa == null || isNaN(pa)) ? -1 : pa;
      var vb = (pb == null || isNaN(pb)) ? -1 : pb;
      if (vb !== va) return vb - va;
      if (a.pitcher !== b.pitcher) return a.pitcher < b.pitcher ? -1 : 1;
      var la = a.rows.map(function (r) { return r.leg; }).join('||');
      var lb = b.rows.map(function (r) { return r.leg; }).join('||');
      return la < lb ? -1 : la > lb ? 1 : 0;
    });
  }

  return {
    comboKey: comboKey,
    buildSpecSets: buildSpecSets,
    isWhitelisted: isWhitelisted,
    statCatOf: statCatOf,
    isLegalCombo: isLegalCombo,
    enumerate: enumerate,
    sortByFvOddsAscending: sortByFvOddsAscending,
  };
}));
