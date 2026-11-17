// First-dunk pricing: who makes the first dunk of an NBA game.
//
// The same arithmetic as hazards() / price() / mix() in
// scripts/nba_first_dunk.py, which builds the data this reads
// (public/data/nba_first_dunk.json) and backtests it;
// scripts/nba_first_dunk_check.js holds the two together.
//
// A race, minute by minute. While he is on the floor a player dunks at his
// own rate; the first dunk goes to him in minute k with probability
//   (no dunk before k) x (a dunk in k) x (his share of the rates in k).
(function (root) {
  'use strict';
  var CURVE_MIN = 24, GAME_MIN = 48, EARLY_MIN = 6;

  // entries: [{id, t, rate, early, tip, curve[24], after}]; m: [48]; gamma:
  // how far a minute's dunks lean toward its biggest dunkers (1 = by rate).
  // Returns { probs: {id: p} (they sum to 1 - noDunk), noDunk, team: {t: p},
  //           tFirst (expected minute of the first dunk), tTeam: {t: minute of its own first} }.
  function price(entries, m, gamma) {
    var g = gamma == null ? 1 : gamma;
    var n = entries.length, p = new Array(n), alive = 1, tFirst = 0, i, k, t;
    var teams = [], tAlive = {}, tTime = {};
    for (i = 0; i < n; i++) {
      p[i] = 0;
      if (teams.indexOf(entries[i].t) < 0) { teams.push(entries[i].t); tAlive[entries[i].t] = 1; tTime[entries[i].t] = 0; }
    }
    for (k = 0; k < GAME_MIN; k++) {
      var h = new Array(n), tot = 0;
      for (i = 0; i < n; i++) {
        var e = entries[i];
        var x = e.rate * m[k] * (k < CURVE_MIN ? e.curve[k] : e.after);
        if (k < EARLY_MIN && e.early != null) x *= e.early;
        if (k === 0 && e.tip != null) x *= e.tip;
        h[i] = x; tot += x;
      }
      if (tot > 0 && g !== 1) {
        var z = 0;
        for (i = 0; i < n; i++) z += Math.pow(h[i], g);
        for (i = 0; i < n; i++) h[i] = tot * Math.pow(h[i], g) / z;
      }
      if (tot > 0) {
        var q = alive * (1 - Math.exp(-tot));
        for (i = 0; i < n; i++) p[i] += q * h[i] / tot;
        tFirst += q * (k + 0.5);
        alive *= Math.exp(-tot);
      }
      for (var ti = 0; ti < teams.length; ti++) {
        t = teams[ti];
        var lt = 0;
        for (i = 0; i < n; i++) if (entries[i].t === t) lt += h[i];
        if (lt > 0) { tTime[t] += tAlive[t] * (1 - Math.exp(-lt)) * (k + 0.5); tAlive[t] *= Math.exp(-lt); }
      }
    }
    var probs = {}, team = {}, tTeam = {};
    for (i = 0; i < n; i++) { probs[entries[i].id] = p[i]; team[entries[i].t] = (team[entries[i].t] || 0) + p[i]; }
    teams.forEach(function (tt) { tTeam[tt] = tAlive[tt] < 1 ? tTime[tt] / (1 - tAlive[tt]) : null; });
    return { probs: probs, noDunk: alive, team: team, tFirst: alive < 1 ? tFirst / (1 - alive) : null, tTeam: tTeam };
  }

  // A game whose lineup is not settled. rows: [{id, t, st (listed to start),
  // play (chance he plays), sub (order to step in for a starter who sits)}].
  // Every way the unsure players can turn out is priced with its chance and
  // added up; a team short of five starters takes its next men up.
  // makeEntries(lineup {id: 0|1}) -> pricing rows.
  function mix(rows, makeEntries, m, gamma, maxUnsure) {
    var cap = maxUnsure == null ? 8 : maxUnsure;
    var unsure = rows.filter(function (r) { return r.play > 0 && r.play < 1; })
      .map(function (r, i) { return { r: r, i: i }; })
      .sort(function (a, b) { return (Math.abs(0.5 - b.r.play) - Math.abs(0.5 - a.r.play)) || (a.i - b.i); })
      .map(function (x) { return x.r; });
    var nFixed = Math.max(0, unsure.length - cap);
    var fixedExtra = unsure.slice(0, nFixed);
    unsure = unsure.slice(nFixed);
    var plays = {};
    rows.forEach(function (r) { plays[r.id] = fixedExtra.indexOf(r) >= 0 ? r.play >= 0.5 : r.play >= 1; });
    var teams = [];
    rows.forEach(function (r) { if (teams.indexOf(r.t) < 0) teams.push(r.t); });
    teams.sort();
    var out = { probs: {}, noDunk: 0, team: {}, tFirst: 0, tTeam: {}, scenarios: 1 << unsure.length };
    for (var mask = 0; mask < (1 << unsure.length); mask++) {
      var w = 1;
      for (var b = 0; b < unsure.length; b++) {
        var inn = !!((mask >> b) & 1);
        plays[unsure[b].id] = inn;
        w *= inn ? unsure[b].play : 1 - unsure[b].play;
      }
      if (w <= 0) continue;
      var lineup = {};
      teams.forEach(function (t) {
        var act = rows.filter(function (r) { return r.t === t && plays[r.id]; });
        var st = act.filter(function (r) { return r.st; });
        var bench = act.filter(function (r) { return !r.st; })
          .map(function (r, i) { return { r: r, i: i }; })
          .sort(function (a, c) { return (a.r.sub - c.r.sub) || (a.i - c.i); })
          .map(function (x) { return x.r; });
        while (st.length < 5 && bench.length) st.push(bench.shift());
        act.forEach(function (r) { lineup[r.id] = st.indexOf(r) >= 0 ? 1 : 0; });
      });
      var res = price(makeEntries(lineup), m, gamma);
      for (var id in res.probs) out.probs[id] = (out.probs[id] || 0) + w * res.probs[id];
      out.noDunk += w * res.noDunk;
      out.tFirst += w * (res.tFirst || 0);
      teams.forEach(function (t) {
        out.team[t] = (out.team[t] || 0) + w * (res.team[t] || 0);
        out.tTeam[t] = (out.tTeam[t] || 0) + w * (res.tTeam[t] || 0);
      });
    }
    return out;
  }

  // One team's side of a matchup, from the model file D (public/data/nba_first_dunk.json):
  // possessions a minute and the multipliers on its players' rates. State.team_ctx in Python.
  function context(D, abbr, opp, home) {
    var P = D.params, t = D.teams[abbr], o = D.teams[opp], avg = D.league.ppg;
    var mult = o.d;
    if (P.to_pow) mult *= Math.pow(o.to, P.to_pow);
    if (P.off_pow) mult *= Math.pow(t.o, P.off_pow);
    if (P.home) mult *= home ? 1 + P.home : 1 - P.home;
    var tipP = Math.min(0.9, Math.max(0.1, 0.5 + (t.tip - o.tip)));
    return { pace: avg * (t.pace / avg) * (o.pace / avg) / GAME_MIN, mult: mult,
             early: P.early_pow ? Math.pow(t.e, P.early_pow) : 1,
             tip: P.tip_pow ? 1 + P.tip_pow * (2 * tipP - 1) : 1 };
  }

  // One player's pricing row. st: starts (1) or comes off the bench (0). app: for a bench
  // man, his chance of getting into the game at all. lam: his rate, if not the model file's.
  // State.entry in Python.
  function entry(D, id, team, st, ctx, app, lam) {
    var p = D.players[id];
    var rate = (lam == null ? p.lam : lam) * ctx.pace * ctx.mult * (st ? 1 : D.params.bench * (app == null ? 1 : app));
    return { id: id, t: team, rate: rate, early: ctx.early, tip: ctx.tip,
             curve: st ? p.cs : p.cb, after: st ? p.as : p.ab };
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

  var api = { price: price, mix: mix, context: context, entry: entry, probToAmerican: probToAmerican, parsePrice: parsePrice, normName: normName,
              CURVE_MIN: CURVE_MIN, GAME_MIN: GAME_MIN, EARLY_MIN: EARLY_MIN };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FirstDunk = api;
})(typeof window !== 'undefined' ? window : this);
