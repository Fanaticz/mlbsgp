#!/usr/bin/env python3
"""Pull NFL per-game logs from ESPN and compute, for every rostered WR, TE and
RB, the correlations between receptions (REC), receiving yards (YDS) and
touchdowns (TD = receiving + rushing TDs, i.e. the anytime-TD market) over the
last three seasons.

ESPN names an NFL season by the year it starts, so 2026 = the 2026-27 season.
By default the seasons are this one and the two before it, read off ESPN's
scoreboard, with per-game recency weights 0.15 / 0.35 / 0.50 (oldest first;
only the ratios matter).

What the r values are
---------------------
A same-game parlay only cares whether each leg clears its line, so every r here
is the correlation of a Gaussian copula: the one number that, put through a
bivariate normal at the two legs' probabilities, gives the joint probability.
That is not the Pearson r of the raw stat lines. TDs are 0/1 most weeks and
receptions are small counts, and a Pearson r on such data understates the
copula correlation (pooled over WR/TE seasons: REC-TD 0.28 raw vs 0.39 in the
copula, YDS-TD 0.36 vs 0.44, REC-YDS 0.76 vs 0.80; with the raw values the
copula underprices every one of those combos against the actual hit rates).

Per player and pair, the more continuous stat (YDS, or REC against TD) becomes
normal scores within each season (rank -> standard normal quantile), the more
discrete one (REC or TD) is kept as its count, centered on its season mean.
Their recency-weighted Pearson r is then scaled by the polyserial factor
sd(count) / sum_j phi(tau_j) (Olsson, Drasgow & Dorans 1982), where tau_j are
that season's thresholds between consecutive counts. On the pooled data this
matches a full maximum-likelihood fit of the copula with discrete margins
(0.797 / 0.443 / 0.387 vs 0.803 / 0.437 / 0.387), and on simulated players
with 17 + 17 + 7 games it is unbiased to within 0.01.

Ranks within each season do what the NBA script's within-season centering
does: a season where a player's role moved every stat together can't pass for
a same-game correlation.

Shrinkage
---------
With ~40 games a player, one player's r carries 0.08 (REC-YDS) to 0.25 (the TD
pairs) of sampling noise, and out of sample (2023-24 games predicting 2025) a
player's own r predicts worse than his position's average for every pair. So
each r is shrunk toward the average r of rotation players at his position (WR,
TE, RB), empirical-Bayes style, with the sampling noise evaluated at that
average (evaluating it at the player's own r hands the most weight to players
whose sample r happens to be high). The between-player spread tau is the
method-of-moments estimate held to 0.02-0.05: the most that held up out of
sample was about 0.04 (WR REC-YDS); larger estimates were noise.

Data source (public ESPN endpoints, no key required):
  - Teams + rosters:
      https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/teams[/{id}/roster]
  - Per-game log:
      https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{id}/gamelog?season={Y}
  - This week's slate:
      https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard

Regular-season games only, every game the player appeared in (ESPN lists games
with zero targets too, so a quiet game or an early injury exit stays in: a
prop stands once the player takes a snap).

Outputs:
  - JSON: public/data/nfl_correlations.json  (or --out)
  - A human-readable summary table to stdout.

Usage:
  python3 scripts/nfl_fetch_correlations.py                 # this season + the two before
  python3 scripts/nfl_fetch_correlations.py --seasons 2024 2025 2026
  python3 scripts/nfl_fetch_correlations.py --workers 16 --limit 40
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import statistics
import sys
from statistics import NormalDist

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Shared pure-python helpers (HTTP with backoff, weighted Pearson + Kish nEff,
# Student-t p-value).
from nba_fetch_correlations import get_json, pearson_pvalue, weighted_pearson  # noqa: E402

SITE = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl"
SITE_API = "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl"

POSITIONS = {"WR": "WR", "TE": "TE", "RB": "RB", "FB": "RB"}  # roster position -> group

# Game-log columns by ESPN's stat `names` (column order differs by position:
# an RB's log lists rushing first).
COLS = {"rec": "receptions", "tgt": "receivingTargets", "yds": "receivingYards",
        "rec_td": "receivingTouchdowns", "rush_td": "rushingTouchdowns"}

# The three pairs: (key, continuous stat -> normal scores, count stat -> polyserial).
PAIRS = (("rec_yds", "yds", "rec"), ("rec_td", "rec", "td"), ("yds_td", "yds", "td"))

SHRINK_POOL = {"min_games": 20, "min_tgt": 3.0}
SHRINK_TAU = (0.02, 0.05)  # floor, cap
RHO_CLAMP = 0.99

ND = NormalDist()


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (nfl-correlations/1.0)"})
    return s


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


# --- ESPN ----------------------------------------------------------------------

def roster_players(sess: requests.Session) -> dict[str, dict]:
    """athlete_id -> {name, position, group, team_id, team_abbr, team_name} for
    every WR / TE / RB / FB on a current roster (active, reserve lists and
    practice squad alike; the viewer filters by volume)."""
    data = get_json(sess, f"{SITE_API}/teams")
    out: dict[str, dict] = {}
    try:
        teams = data["sports"][0]["leagues"][0]["teams"]
    except (TypeError, KeyError, IndexError):
        return out
    for t in teams:
        tm = t.get("team") or {}
        tid = str(tm.get("id") or "")
        rd = get_json(sess, f"{SITE_API}/teams/{tid}/roster")
        if not rd:
            continue
        for grp in rd.get("athletes") or []:
            for a in grp.get("items") or []:
                pos = (a.get("position") or {}).get("abbreviation") or ""
                aid = str(a.get("id") or "")
                if pos not in POSITIONS or not aid:
                    continue
                out[aid] = {"name": a.get("displayName") or f"athlete-{aid}", "position": pos,
                            "group": POSITIONS[pos], "team_id": tid,
                            "team_abbr": tm.get("abbreviation") or "",
                            "team_name": tm.get("displayName") or ""}
    return out


def schedule_week(sess: requests.Session) -> dict:
    """This week's slate from the public scoreboard (ESPN's current week)."""
    data = get_json(sess, f"{SITE_API}/scoreboard") or {}
    games: list[dict] = []
    for e in data.get("events") or []:
        try:
            comp = e["competitions"][0]["competitors"]
        except (KeyError, IndexError):
            continue
        # away first, like "LV @ NYJ"
        comp = sorted(comp, key=lambda c: c.get("homeAway") != "away")
        st = (e.get("status") or {}).get("type") or {}
        games.append({
            "start": e.get("date"),
            "state": st.get("state"),
            "detail": st.get("shortDetail") or "",
            "matchup": " @ ".join(c["team"]["abbreviation"] for c in comp),
            "team_ids": [str(c["team"]["id"]) for c in comp],
        })
    season = data.get("season") or {}
    return {"season": season.get("year"), "season_type": season.get("type"),
            "week": (data.get("week") or {}).get("number"),
            "byes": [t.get("abbreviation") for t in (data.get("week") or {}).get("teamsOnBye") or []],
            "games": games}


def _scores(meta: dict) -> tuple[float | None, float | None]:
    """(his team's score, opponent's score) from a game-log event."""
    hs, aws = _num(meta.get("homeTeamScore")), _num(meta.get("awayTeamScore"))
    if hs is None or aws is None:
        return None, None
    tid = str((meta.get("team") or {}).get("id") or "")
    home = tid == str(meta.get("homeTeamId") or "") if tid else meta.get("atVs") != "@"
    return (hs, aws) if home else (aws, hs)


def regular_season_games(sess: requests.Session, aid: str, season: int) -> list[dict]:
    """One dict per regular-season game the player appeared in."""
    data = get_json(sess, f"{SITE}/athletes/{aid}/gamelog?season={season}")
    if not data:
        return []
    names = data.get("names") or []
    idx = {k: names.index(v) for k, v in COLS.items() if v in names}
    if not all(k in idx for k in ("rec", "yds", "rec_td")):
        return []
    meta_all = data.get("events") or {}
    out: list[dict] = []
    seen: set[str] = set()
    for st in data.get("seasonTypes") or []:
        if "Regular Season" not in (st.get("displayName") or ""):
            continue
        for cat in st.get("categories") or []:
            for ev in cat.get("events") or []:
                eid = str(ev.get("eventId") or "")
                if eid and eid in seen:
                    continue
                stats = ev.get("stats") or []
                val = lambda k: _num(stats[idx[k]]) if k in idx and idx[k] < len(stats) else None  # noqa: E731
                rec, yds = val("rec"), val("yds")
                if rec is None or yds is None:
                    continue
                if eid:
                    seen.add(eid)
                m = meta_all.get(eid) or {}
                tm, op = _scores(m)
                rush_td = val("rush_td") or 0.0
                out.append({
                    "rec": rec, "yds": yds, "tgt": val("tgt") or 0.0,
                    "td": (val("rec_td") or 0.0) + rush_td, "rush_td": rush_td,
                    "week": m.get("week"),
                    "date": (m.get("gameDate") or "")[:10],
                    "opp": (m.get("opponent") or {}).get("abbreviation") or "",
                    "loc": m.get("atVs") or "",
                    "res": m.get("gameResult") or "",
                    "tm": tm, "op": op,
                })
    out.sort(key=lambda g: g["date"])
    return out


# --- copula correlation ----------------------------------------------------------

def normal_scores(v: list[float]) -> list[float]:
    """Rank -> standard normal quantile, ties sharing their mid-rank."""
    n = len(v)
    order = sorted(range(n), key=lambda i: v[i])
    rank = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            rank[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return [ND.inv_cdf(r / (n + 1)) for r in rank]


def threshold_density(ys: list[float]) -> float:
    """sum_j phi(tau_j) * gap_j over the cuts between consecutive observed
    counts, tau_j = Phi^-1(share of games at or below the lower count). For a
    count cut out of a normal Z with corr rho to X: cov(X, count) = rho * this."""
    n = len(ys)
    cats = sorted(set(ys))
    cum = tot = 0.0
    for a, b in zip(cats, cats[1:]):
        cum += sum(1 for y in ys if y == a) / n
        tot += ND.pdf(ND.inv_cdf(cum)) * (b - a)
    return tot


def copula_r(by_season: dict[int, list[dict]], kx: str, ky: str,
             weights: dict[int, float] | None) -> dict | None:
    """Copula correlation of (kx, ky) pooled over seasons: normal scores of kx
    and season-centered ky within each season, weighted Pearson r over all
    games, times sd(ky) / mean threshold density. weights=None -> unweighted.

    Returns {rho, r, f, neff, dfx}: rho = the copula r (clamped), r = the
    normal-score Pearson behind it, f = the polyserial factor, neff = Kish
    effective n, dfx = extra seasons (one df spent per season mean)."""
    zx: list[float] = []
    yc: list[float] = []
    ws: list[float] = []
    dens = wsum = 0.0
    used = 0
    for yr, gs in by_season.items():
        if len(gs) < 2:
            continue
        w = 1.0 if weights is None else weights.get(yr, 0.0)
        if w <= 0:
            continue
        ys = [g[ky] for g in gs]
        my = sum(ys) / len(ys)
        zx += normal_scores([g[kx] for g in gs])
        yc += [y - my for y in ys]
        ws += [w] * len(gs)
        dens += w * len(gs) * threshold_density(ys)
        wsum += w * len(gs)
        used += 1
    if len(zx) < 3 or dens <= 0:
        return None
    wp = weighted_pearson(zx, yc, ws)
    if wp is None:
        return None
    r, neff = wp
    sd_y = math.sqrt(sum(w * y * y for w, y in zip(ws, yc)) / sum(ws))
    f = sd_y / (dens / wsum)
    rho = max(-RHO_CLAMP, min(RHO_CLAMP, r * f))
    return {"rho": rho, "r": r, "f": f, "neff": neff, "dfx": used - 1}


def _pair(est: dict | None) -> dict:
    """Copula r + two-sided p-value (tested on the normal-score r, which is
    zero exactly when the copula r is)."""
    if est is None:
        return {"r": None, "p_value": None}
    p = pearson_pvalue(est["r"], est["neff"] - est["dfx"])
    return {"r": round(est["rho"], 4), "p_value": None if p is None else round(p, 5)}


# --- driver -------------------------------------------------------------------

SEASON_MIN_GAMES_R = 8  # fewer games in a season: box stats only, no r (5 games can land on 0.99)


def _season_stats(games: list[dict]) -> dict:
    n = len(games)
    one = {0: games}
    return {
        "games": n,
        "tgt_mean": round(sum(g["tgt"] for g in games) / n, 2),
        "rec_mean": round(sum(g["rec"] for g in games) / n, 2),
        "yds_mean": round(sum(g["yds"] for g in games) / n, 1),
        "td_rate": round(sum(1 for g in games if g["td"] >= 1) / n, 3),
        **{key: _pair(copula_r(one, kx, ky, None) if n >= SEASON_MIN_GAMES_R else None)
           for key, kx, ky in PAIRS},
    }


def process_player(sess: requests.Session, aid: str, info: dict, seasons: list[int],
                   weights: dict[int, float]) -> dict | None:
    by_year: dict[int, list[dict]] = {}
    for yr in seasons:
        g = regular_season_games(sess, aid, yr)
        if g:
            by_year[yr] = g
    allg = [g for yr in sorted(by_year) for g in by_year[yr]]
    n = len(allg)
    if n < 3:
        return None
    W = sum(weights.get(g_yr, 0.0) for g_yr in by_year for _ in by_year[g_yr]) or 1.0

    def wmean(f) -> float:
        return sum(weights.get(yr, 0.0) * f(g) for yr in by_year for g in by_year[yr]) / W

    pairs: dict[str, dict] = {}
    est: dict[str, dict | None] = {}
    for key, kx, ky in PAIRS:
        e = copula_r(by_year, kx, ky, weights)
        est[key] = e
        pairs[key] = {"unweighted": _pair(copula_r(by_year, kx, ky, None)),
                      "weighted": _pair(e)}
    n_eff = next((e["neff"] for e in est.values() if e), None)

    def _i(v: float | None):
        if v is None:
            return None
        return int(v) if float(v).is_integer() else v

    games = []
    for yr in sorted(by_year):
        for g in by_year[yr]:
            row = {"s": yr, "wk": g["week"], "d": g["date"], "opp": g["opp"], "loc": g["loc"],
                   "res": g["res"], "tgt": _i(g["tgt"]), "rec": _i(g["rec"]),
                   "yds": _i(g["yds"]), "td": _i(g["td"])}
            if g["rush_td"]:
                row["rtd"] = _i(g["rush_td"])
            if g["tm"] is not None:
                row["tm"], row["op"] = _i(g["tm"]), _i(g["op"])
            games.append(row)

    return {
        "athlete_id": aid,
        "name": info["name"],
        "position": info["position"],
        "group": info["group"],
        "team_id": info["team_id"],
        "team_abbr": info["team_abbr"],
        "team_name": info["team_name"],
        "n_games": n,
        "effective_n": None if n_eff is None else round(n_eff, 1),
        "games_by_season": {str(yr): len(g) for yr, g in sorted(by_year.items())},
        "tgt_mean": round(sum(g["tgt"] for g in allg) / n, 2),
        "rec_mean": round(sum(g["rec"] for g in allg) / n, 2),
        "yds_mean": round(sum(g["yds"] for g in allg) / n, 1),
        "td_rate": round(sum(1 for g in allg if g["td"] >= 1) / n, 3),
        "td_rate_weighted": round(wmean(lambda g: 1.0 if g["td"] >= 1 else 0.0), 3),
        **pairs,
        "by_season": {str(yr): _season_stats(g) for yr, g in sorted(by_year.items()) if len(g) >= 3},
        "games": games,
        # Shrinkage inputs, dropped before writing.
        "_est": est,
    }


def add_shrinkage(players: list[dict]) -> dict:
    """Empirical-Bayes shrink of each player's weighted copula r toward the
    average of rotation players at his position, written to
    p[pair]["shrunk"] = {"r", "prior", "w"}.

    Sampling variance of a copula r: f^2 (1 - r_obs^2)^2 / nEff, with r_obs the
    normal-score r the prior implies (prior / f). Evaluated at the prior, not at
    the player's own r: the own-r version gives the players whose sample r
    happens to run high the smallest noise and so the most weight on it.
    tau^2 = spread of the pool's r around the prior minus their average noise
    (method of moments), held to SHRINK_TAU. Players with no r of their own
    (e.g. no TD in any game) get the prior."""
    def noise(e: dict, prior: float) -> float:
        r0 = min(RHO_CLAMP, abs(prior) / e["f"])
        return e["f"] ** 2 * (1 - r0 * r0) ** 2 / e["neff"]

    def in_pool(p: dict, key: str) -> bool:
        return bool(p["_est"][key]) and p["n_games"] >= SHRINK_POOL["min_games"] \
            and p["tgt_mean"] >= SHRINK_POOL["min_tgt"]

    def fit(pool: list[dict]) -> tuple[float, float]:
        m = statistics.mean(e["rho"] for e in pool)
        tau2 = SHRINK_TAU[0] ** 2
        for _ in range(50):
            v = [noise(e, m) for e in pool]
            spread = statistics.mean((e["rho"] - m) ** 2 for e in pool)
            tau2 = min(max(spread - statistics.mean(v), SHRINK_TAU[0] ** 2), SHRINK_TAU[1] ** 2)
            wts = [1 / (tau2 + x) for x in v]
            m_new = sum(w * e["rho"] for w, e in zip(wts, pool)) / sum(wts)
            if abs(m_new - m) < 1e-7:
                break
            m = m_new
        return m, tau2

    fits: dict[str, dict] = {}
    for group in sorted({p["group"] for p in players}):
        members = [p for p in players if p["group"] == group]
        for key, _, _ in PAIRS:
            pool = [p["_est"][key] for p in members if in_pool(p, key)]
            src = group
            if len(pool) < 5:  # too few rotation players: every position's pool
                pool = [p["_est"][key] for p in players if in_pool(p, key)]
                src = "ALL"
            if len(pool) < 5:
                continue
            m, tau2 = fit(pool)
            for p in members:
                e = p["_est"][key]
                if e is None:
                    p[key]["shrunk"] = {"r": round(m, 4), "prior": round(m, 4), "w": 0.0}
                    continue
                w = tau2 / (tau2 + noise(e, m))
                p[key]["shrunk"] = {"r": round(w * e["rho"] + (1 - w) * m, 4),
                                    "prior": round(m, 4), "w": round(w, 3)}
            fits[f"{group}.{key}"] = {"prior": round(m, 4), "tau": round(math.sqrt(tau2), 4),
                                      "pool_n": len(pool), "pool": src}
    return {"method": "empirical Bayes: weighted copula r shrunk toward rotation players at the "
                      "same position; noise evaluated at the prior; tau held to "
                      f"{SHRINK_TAU[0]}-{SHRINK_TAU[1]}",
            "pool": SHRINK_POOL, "fits": fits}


def default_seasons(sched: dict) -> list[int]:
    cur = sched.get("season")
    if not cur:
        today = dt.date.today()
        cur = today.year if today.month >= 9 else today.year - 1
    return [cur - 2, cur - 1, cur]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="+", default=None,
                    help="Seasons to pool (default: ESPN's current season and the two before it).")
    ap.add_argument("--weights", type=float, nargs="+", default=[0.15, 0.35, 0.50],
                    help="Per-game recency weights, oldest season first (only the ratios matter).")
    ap.add_argument("--min-games", type=int, default=20,
                    help="Min pooled games for a player to count as 'reportable' in the summary.")
    ap.add_argument("--workers", type=int, default=8, help="Concurrent HTTP workers.")
    ap.add_argument("--out", default=os.path.join("public", "data", "nfl_correlations.json"))
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap players processed (0 = all). For quick test runs.")
    args = ap.parse_args()

    sess = make_session()
    print("Building rosters + this week's slate ...", file=sys.stderr)
    sched = schedule_week(sess)
    seasons = sorted(args.seasons or default_seasons(sched))
    if len(args.weights) != len(seasons):
        sys.exit(f"--weights needs one weight per season ({len(seasons)}), got {len(args.weights)}")
    weights = dict(zip(seasons, args.weights))
    roster = roster_players(sess)
    if not roster:
        sys.exit("No rosters from ESPN; refusing to overwrite the data file.")
    print(f"  {len(roster)} WR/TE/RB on rosters; week {sched.get('week')} of {sched.get('season')}: "
          f"{len(sched['games'])} games", file=sys.stderr)

    ids = sorted(roster, key=int)
    if args.limit:
        ids = ids[: args.limit]
    print(f"Pulling game logs for seasons {seasons} ...", file=sys.stderr)
    players: list[dict] = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        sessions = [make_session() for _ in range(args.workers)]
        futs = {ex.submit(process_player, sessions[i % args.workers], aid, roster[aid],
                          seasons, weights): aid for i, aid in enumerate(ids)}
        for fut in cf.as_completed(futs):
            done += 1
            if done % 100 == 0:
                print(f"  ...{done}/{len(ids)}", file=sys.stderr)
            try:
                res = fut.result()
            except Exception as e:  # noqa: BLE001 - one bad player shouldn't kill the run
                print(f"  warn: athlete {futs[fut]} failed: {e}", file=sys.stderr)
                res = None
            if res:
                players.append(res)
    if not players:
        sys.exit("No game logs from ESPN; refusing to overwrite the data file.")

    players.sort(key=lambda p: p["name"].lower())
    shrinkage = add_shrinkage(players)
    for p in players:
        del p["_est"]
    reportable = [p for p in players if p["n_games"] >= args.min_games]

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "ESPN NFL public API",
        "seasons": seasons,
        "scope": "regular-season games, WR / TE / RB on current rosters; TD = receiving + rushing",
        "weighting": {
            "scheme": "per-game season weights (recency tilt); weighted Pearson, Kish "
                      "effective-N used for significance",
            "per_game_season_weights": {str(k): v for k, v in sorted(weights.items())},
            "copula": "r = Gaussian-copula correlation: normal scores of the continuous stat "
                      "within each season x polyserial factor for the count stat",
        },
        "schedule_week": sched,
        "n_players": len(players),
        "total_game_rows": sum(p["n_games"] for p in players),
        "shrinkage": shrinkage,
        "players": players,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))

    # --- stdout summary ---
    def cell(v, w: int, prec: int) -> str:
        return f"{(v if v is not None else float('nan')):>{w}.{prec}f}"

    print()
    print(f"NFL receiving correlations (copula r, shrunk) - seasons {seasons}, weights "
          + " ".join(f"{k}={v}" for k, v in sorted(weights.items())))
    for k, fit in shrinkage["fits"].items():
        print(f"  prior {k:11} {fit['prior']:+.3f}  tau {fit['tau']:.3f}  pool {fit['pool_n']}")
    print(f"{len(reportable)} players with >= {args.min_games} games (of {len(players)}); "
          f"{payload['total_game_rows']} game rows")
    hdr = (f"{'Player':<24}{'Pos':<4}{'Tm':<5}{'G':>4}{'nEff':>6}{'Tgt':>6}{'Rec':>6}{'Yds':>7}"
           f"{'TD%':>6}  {'REC-YDS':>8}{'own':>7}  {'REC-TD':>8}{'own':>7}  {'YDS-TD':>8}{'own':>7}")
    print(hdr)
    print("-" * len(hdr))
    top = sorted((p for p in reportable if p["tgt_mean"] >= 4), key=lambda p: -p["yds_mean"])[:40]
    for p in top:
        cells = "".join(f"  {cell(p[k]['shrunk']['r'] if 'shrunk' in p[k] else None, 8, 3)}"
                        f"{cell(p[k]['weighted']['r'], 7, 3)}" for k, _, _ in PAIRS)
        print(f"{p['name'][:23]:<24}{p['position']:<4}{p['team_abbr']:<5}{p['n_games']:>4}"
              f"{cell(p['effective_n'], 6, 1)}{p['tgt_mean']:>6.1f}{p['rec_mean']:>6.1f}"
              f"{p['yds_mean']:>7.1f}{100 * p['td_rate']:>5.0f}%{cells}")
    print()
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
