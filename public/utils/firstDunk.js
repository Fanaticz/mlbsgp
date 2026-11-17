// First-dunk pricing: who makes the first dunk of an NBA game.
//
// The same arithmetic as price() in scripts/nba_first_dunk.py, which builds
// the data this reads (public/data/nba_first_dunk.json) and backtests it;
// scripts/nba_first_dunk_check.js holds the two together.
//
// A race, minute by minute. While he is on the floor a player dunks at his
// own rate; the first dunk goes to him in minute k with probability
//   (no dunk before k) x (a dunk in k) x (his share of the rates in k).
(function (root) {
  'use strict';
  var CURVE_MIN = 24, GAME_MIN = 48;

  // entries: [{id, lam, d, curve[24], after}]; m: [48]; gamma: how far a
  // minute's dunks lean toward its biggest dunkers (1 = by rate).
  // Returns { probs: {id: p}, noDunk }.
  function price(entries, m, gamma) {
    var g = gamma == null ? 1 : gamma;
    var p = {}, alive = 1, i, k;
    for (i = 0; i < entries.length; i++) p[entries[i].id] = 0;
    for (k = 0; k < GAME_MIN; k++) {
      var h = [], tot = 0;
      for (i = 0; i < entries.length; i++) {
        var e = entries[i];
        var x = e.lam * e.d * m[k] * (k < CURVE_MIN ? e.curve[k] : e.after);
        h.push(x); tot += x;
      }
      if (tot <= 0) continue;
      if (g !== 1) {
        var z = 0;
        for (i = 0; i < h.length; i++) z += Math.pow(h[i], g);
        for (i = 0; i < h.length; i++) h[i] = tot * Math.pow(h[i], g) / z;
      }
      var q = alive * (1 - Math.exp(-tot));
      for (i = 0; i < entries.length; i++) p[entries[i].id] += q * h[i] / tot;
      alive *= Math.exp(-tot);
    }
    var s = 0, id;
    for (id in p) s += p[id];
    if (s > 0) for (id in p) p[id] /= s;
    return { probs: p, noDunk: alive };
  }

  function probToAmerican(p) {
    if (!(p > 0) || !(p < 1)) return '';
    return p >= 0.5 ? '-' + Math.round(100 * p / (1 - p)) : '+' + Math.round(100 * (1 - p) / p);
  }

  // "+650", "-120", "650" (American) or "7.5" / "7.5x" (decimal) -> decimal odds, or null.
  function parsePrice(str) {
    var s = String(str == null ? '' : str).trim().replace(/−/g, '-').replace(/x$/i, '');
    if (!s) return null;
    var v = Number(s);
    if (!isFinite(v)) return null;
    if (/^[+-]/.test(s) || Math.abs(v) >= 100) {
      if (Math.abs(v) < 100) return null;
      return v > 0 ? 1 + v / 100 : 1 + 100 / -v;
    }
    return v > 1 ? v : null;
  }

  // "Wendell Carter Jr." and "wendell carter" are the same man.
  function normName(n) {
    return String(n || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/[.'’`]/g, '').replace(/-/g, ' ')
      .replace(/\s+(jr|sr|ii|iii|iv|v)$/g, '').replace(/\s+/g, ' ').trim();
  }

  var api = { price: price, probToAmerican: probToAmerican, parsePrice: parsePrice, normName: normName,
              CURVE_MIN: CURVE_MIN, GAME_MIN: GAME_MIN };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FirstDunk = api;
})(typeof window !== 'undefined' ? window : this);
