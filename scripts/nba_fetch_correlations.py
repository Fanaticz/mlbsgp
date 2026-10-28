#!/usr/bin/env python3
"""Pull NBA per-game logs from ESPN and compute per-player correlations
between PTS-REB, PTS-AST and PTS-3PM over the last three seasons.

Seasons use ESPN's convention of naming a season by the year it ends, so
2027 = the 2026-27 season.

Correlations are reported two ways per player: unweighted (every game equal)
and recency-weighted, where each game carries a per-season weight (default
2025=0.15, 2026=0.35, 2027=0.50 — only the ratios matter). The weighted
significance test uses the Kish effective sample size so leaning on recent
games is reflected honestly in the p-value.

Pooled correlations are within-season: each stat is centered on that season's
mean before the seasons are pooled. Otherwise a season where a player's role
moved every stat together (fewer minutes -> fewer points AND fewer assists)
shows up as a positive correlation even when every single season is flat or
negative. Only the game-to-game swings a same-game parlay depends on remain.

Data source (public ESPN endpoints, no key required):
  - Season athlete index:
      https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{Y}/athletes?limit=1000
  - Athlete bio (name/position):
      https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{Y}/athletes/{id}
  - Per-game log:
      https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{id}/gamelog?season={Y}

For each athlete we collect (PTS, REB, AST) for every regular-season game in the
requested seasons, pool the games, and compute the Pearson correlation for the
prop pairs, plus the game's scoring (game total, the player's team score,
the opponent's score) vs the player's REB. Short-minute games (under 60% of the player's median minutes
that season; --short-min-frac) are left out of the correlations. A two-sided p-value is computed from the t-distribution via the
regularized incomplete beta function (no scipy dependency).

Outputs:
  - JSON: public/data/nba_correlations.json  (or --out)
  - A human-readable summary table to stdout.

Usage:
  python3 scripts/nba_fetch_correlations.py                 # seasons 2025,2026,2027
  python3 scripts/nba_fetch_correlations.py --seasons 2025 2026
  python3 scripts/nba_fetch_correlations.py --min-games 25 --workers 8
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import re
import statistics
import sys
import time
from typing import Any

import requests

CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
SITE = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"
# site.web.api serves the same /apis/site/v2 paths as site.api.espn.com, which
# started returning 403 to datacenter IPs (get_json swallows that as None, so
# rosters and the slate came back empty instead of erroring).
SITE_API = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba"

# Column positions inside each gamelog event's `stats` array. The order is
# fixed by the `labels` array returned alongside the events; for the NBA:
#   ['MIN','FG','FG%','3PT','3P%','FT','FT%','REB','AST','BLK','STL','PF','TO','PTS']
# These are the defaults; gamelog_columns() re-reads them from each payload's
# labels in case ESPN reorders. The 3PT cell is a "made-attempted" string like
# "3-5"; we take the made part.
DEFAULT_COLS = {"MIN": 0, "PTS": 13, "REB": 7, "AST": 8, "3PT": 3}

# Game-scoring stats correlated against the player's REB: final game total
# (both teams, incl. OT), his team's score, and the opponent's score.
SCORE_KEYS = ("tot", "tm", "op")

# Shrinkage: one player's r carries ~0.10 of sampling noise, about as much as
# the real spread between players, so the raw r's overstate how players
# differ. Each r is pulled toward the typical r of rotation players in a
# similar role, the role set by the box stat below (high-assist guards run a
# lower PTS-AST r than low-usage wings; PTS-3PM depends on 3PM volume).
SHRINK_COVARIATE = {"pts_reb": "reb_mean", "pts_ast": "ast_mean", "pts_3pm": "tpm_mean",
                    "tot_reb": "reb_mean", "tm_reb": "reb_mean", "op_reb": "reb_mean"}
SHRINK_POOL = {"min_mpg": 20.0, "min_games": 40}
SHRINK_BINS = 5
SHRINK_TAU2_FLOOR = 0.02 ** 2

ID_RE = re.compile(r"/athletes/(\d+)")


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (nba-correlations/1.0)"})
    return s


def get_json(sess: requests.Session, url: str, retries: int = 4) -> dict | None:
    """GET with exponential backoff. Returns parsed JSON or None on failure."""
    delay = 1.0
    for attempt in range(retries):
        try:
            r = sess.get(url, timeout=30)
            if r.status_code == 200:
                return r.json()
            # 404 means the athlete has no log for that season — not retryable.
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        if attempt < retries - 1:
            time.sleep(delay)
            delay *= 2
    return None


def season_athlete_ids(sess: requests.Session, season: int) -> set[str]:
    url = f"{CORE}/seasons/{season}/athletes?limit=1000"
    data = get_json(sess, url)
    if not data:
        return set()
    ids: set[str] = set()
    for it in data.get("items", []):
        m = ID_RE.search(it.get("$ref", ""))
        if m:
            ids.add(m.group(1))
    return ids


def athlete_name(sess: requests.Session, season: int, aid: str) -> tuple[str, str]:
    url = f"{CORE}/seasons/{season}/athletes/{aid}?lang=en&region=us"
    data = get_json(sess, url)
    if not data:
        return (f"athlete-{aid}", "")
    name = data.get("displayName") or data.get("fullName") or f"athlete-{aid}"
    pos = (data.get("position") or {}).get("abbreviation") or ""
    return (name, pos)


def team_roster_map(sess: requests.Session) -> dict[str, dict]:
    """Map athlete_id -> {team_id, team_abbr, team_name} from current rosters.

    Teams are stable day-to-day, so the current roster is the right source for
    'which team does this player suit up for today'.
    """
    data = get_json(sess, f"{SITE_API}/teams")
    out: dict[str, dict] = {}
    if not data:
        return out
    try:
        teams = data["sports"][0]["leagues"][0]["teams"]
    except (KeyError, IndexError):
        return out
    for t in teams:
        tm = t.get("team") or {}
        tid = str(tm.get("id") or "")
        rd = get_json(sess, f"{SITE_API}/teams/{tid}/roster")
        if not rd:
            continue
        info = {
            "team_id": tid,
            "team_abbr": tm.get("abbreviation") or "",
            "team_name": tm.get("displayName") or "",
        }
        for a in rd.get("athletes", []):
            aid = str(a.get("id") or "")
            if aid:
                out[aid] = info
    return out


def schedule_today(sess: requests.Session) -> dict:
    """Today's NBA slate from the public scoreboard. Returns the date used,
    the set of team_ids playing, and a compact per-game list."""
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    data = get_json(sess, f"{SITE_API}/scoreboard?dates={day}")
    team_ids: list[str] = []
    games: list[dict] = []
    if data:
        for e in data.get("events", []):
            try:
                comp = e["competitions"][0]["competitors"]
            except (KeyError, IndexError):
                continue
            pair = [(str(c["team"]["id"]), c["team"]["abbreviation"]) for c in comp]
            for tid, _ in pair:
                team_ids.append(tid)
            games.append({
                "start": e.get("date"),
                "state": (e.get("status") or {}).get("type", {}).get("state"),
                "matchup": " @ ".join(ab for _, ab in reversed(pair)),
                "team_abbrs": [ab for _, ab in pair],
            })
    return {"date": day, "team_ids": sorted(set(team_ids)), "games": games}


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _made(v: Any) -> float | None:
    """Parse the 'made' side of a 'made-attempted' cell like '3-5' -> 3."""
    if v is None:
        return None
    return _num(str(v).split("-")[0])


def gamelog_columns(data: dict) -> dict[str, int]:
    labels = data.get("labels") or []
    cols = {k: labels.index(k) for k in DEFAULT_COLS if k in labels}
    return cols if len(cols) == len(DEFAULT_COLS) else DEFAULT_COLS


def _exhibition(meta: dict) -> bool:
    """ESPN files the All-Star game(s) and the NBA Cup final under "Regular
    Season", but neither counts toward official regular-season stats (and an
    untimed 5-minute All-Star stint is a big outlier). Both carry an eventNote."""
    note = (meta.get("eventNote") or "").lower()
    if "all-star" in note:
        return True
    return ("cup" in note or "in-season tournament" in note) and "championship" in note


def _scores(meta: dict) -> dict:
    """Final score from a gamelog event: game total, the player's team score,
    the opponent's score. All None if ESPN didn't return a score."""
    hs, aws = _num(meta.get("homeTeamScore")), _num(meta.get("awayTeamScore"))
    if hs is None or aws is None:
        return {k: None for k in SCORE_KEYS}
    opp_id = str((meta.get("opponent") or {}).get("id") or "")
    home = opp_id != str(meta.get("homeTeamId") or "") if opp_id else meta.get("atVs") != "@"
    tm, op = (hs, aws) if home else (aws, hs)
    return {"tot": hs + aws, "tm": tm, "op": op}


def regular_season_games(
    sess: requests.Session, aid: str, season: int
) -> list[dict]:
    """Return one dict per regular-season game: box stats plus game metadata
    (date, opponent, home/away, result) pulled from the payload's events map.

    Categories within a season type are monthly partitions; we dedupe on
    eventId so any overlap can't double-count a game.
    """
    url = f"{SITE}/athletes/{aid}/gamelog?season={season}"
    data = get_json(sess, url)
    if not data:
        return []
    ev_meta = data.get("events") or {}
    cols = gamelog_columns(data)
    last_idx = max(cols.values())
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
                if _exhibition(ev_meta.get(eid) or {}):
                    continue
                stats = ev.get("stats") or []
                if len(stats) <= last_idx:
                    continue
                pts = _num(stats[cols["PTS"]])
                reb = _num(stats[cols["REB"]])
                ast = _num(stats[cols["AST"]])
                tpm = _made(stats[cols["3PT"]])
                mins = _num(stats[cols["MIN"]])
                if pts is None or reb is None or ast is None or tpm is None:
                    continue
                if eid:
                    seen.add(eid)
                m = ev_meta.get(eid) or {}
                sc = _scores(m)
                out.append({
                    "pts": pts, "reb": reb, "ast": ast, "tpm": tpm,
                    "min": 0.0 if mins is None else mins,
                    "date": (m.get("gameDate") or "")[:10],
                    "opp": (m.get("opponent") or {}).get("abbreviation") or "",
                    "loc": m.get("atVs") or "",
                    "res": m.get("gameResult") or "",
                    **sc,
                })
    out.sort(key=lambda g: g["date"])
    return out


# --- statistics (pure python, no numpy/scipy) ---------------------------------

def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def weighted_pearson(
    xs: list[float], ys: list[float], ws: list[float]
) -> tuple[float, float] | None:
    """Weighted Pearson r and Kish effective sample size.

    Weighted means/(co)variances; only weight *ratios* matter, so per-game
    season weights like 0.15/0.35/0.50 act as a 3:7:10 recency tilt. The
    effective n = (Σw)² / Σw² (Kish) shrinks as weight concentrates on fewer
    games, and is what we feed the significance test so heavy recency weighting
    is honestly reflected in the p-value.
    """
    if len(xs) < 3:
        return None
    W = sum(ws)
    if W <= 0:
        return None
    mx = sum(w * x for w, x in zip(ws, xs)) / W
    my = sum(w * y for w, y in zip(ws, ys)) / W
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs))
    syy = sum(w * (y - my) ** 2 for w, y in zip(ws, ys))
    sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
    if sxx <= 0 or syy <= 0:
        return None
    r = sxy / math.sqrt(sxx * syy)
    n_eff = (W * W) / sum(w * w for w in ws)
    return r, n_eff


def _betacf(a: float, b: float, x: float) -> float:
    MAXIT, EPS, FPMIN = 200, 3.0e-12, 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a,b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def pearson_pvalue(r: float, n: int) -> float | None:
    """Two-sided p-value for a Pearson r under H0: rho=0, via Student-t."""
    if n < 3:
        return None
    if abs(r) >= 1.0:
        return 0.0
    df = n - 2
    t2 = (r * r) * df / (1.0 - r * r)
    # p = I_{df/(df+t^2)}(df/2, 1/2)
    return _betai(df / 2.0, 0.5, df / (df + t2))


# --- driver -------------------------------------------------------------------

def _pair(r: float | None, n: float | None) -> dict:
    if r is None or n is None:
        return {"r": None, "p_value": None}
    p = pearson_pvalue(r, n)
    return {"r": round(r, 4), "p_value": None if p is None else round(p, 5)}


def _season_stats(games: list[dict]) -> dict:
    """Box-score means + within-season correlations for one season's games.
    Single-season, so weighting is moot (every game shares one weight)."""
    n = len(games)
    pts = [g["pts"] for g in games]; reb = [g["reb"] for g in games]
    ast = [g["ast"] for g in games]; tpm = [g["tpm"] for g in games]
    mins = [g["min"] for g in games]
    return {
        "games": n,
        "min_mean": round(sum(mins) / n, 1),
        "pts_mean": round(sum(pts) / n, 2),
        "reb_mean": round(sum(reb) / n, 2),
        "ast_mean": round(sum(ast) / n, 2),
        "tpm_mean": round(sum(tpm) / n, 2),
        "pts_reb": _pair(pearson(pts, reb), n),
        "pts_ast": _pair(pearson(pts, ast), n),
        "pts_3pm": _pair(pearson(pts, tpm), n),
        **{f"{k}_reb": _pair(*_score_reb(games, k)) for k in SCORE_KEYS},
    }


def _centered(vals: list[float], seasons: list[int]) -> list[float]:
    """Each value minus its own season's mean. Pooling these keeps only the
    game-to-game swings within a season, so a season where a player's role
    (minutes, team) moved every stat up or down together can't pass for a
    same-game correlation (Simpson's paradox)."""
    tot: dict[int, list[float]] = {}
    for v, s in zip(vals, seasons):
        t = tot.setdefault(s, [0.0, 0])
        t[0] += v
        t[1] += 1
    return [v - tot[s][0] / tot[s][1] for v, s in zip(vals, seasons)]


def _score_reb(games: list[dict], key: str) -> tuple[float | None, int]:
    """Unweighted r between a game-score stat and the player's REB, over games
    with a known final score."""
    gs = [g for g in games if g[key] is not None]
    return pearson([g[key] for g in gs], [g["reb"] for g in gs]), len(gs)


def _interp(knots: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear through (x, y) knots, flat beyond the ends."""
    if x <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return knots[-1][1]


def add_shrinkage(players: list[dict]) -> dict:
    """Empirical-Bayes shrink of each player's weighted r, written to
    p[pair]["shrunk"] = {"r", "prior", "w"}.

    Prior: the mean r of rotation players in the same role, from equal-count
    bins of the pair's covariate (SHRINK_COVARIATE), joined piecewise-linearly.
    tau^2 (real between-player spread) = variance of the pool's r around that
    prior minus their average sampling variance (1 - r^2)^2 / nEff. Each
    player's weight on his own r is tau^2 / (tau^2 + his sampling variance).
    Returns the per-pair fit for the payload."""
    fits = {}
    for pair, cov in SHRINK_COVARIATE.items():
        def usable(p: dict) -> bool:
            return p[pair]["weighted"]["r"] is not None and bool(p["effective_n"])
        pool = sorted((p for p in players if usable(p)
                       and p["min_mean"] >= SHRINK_POOL["min_mpg"]
                       and p["n_games"] >= SHRINK_POOL["min_games"]),
                      key=lambda p: p[cov])
        if len(pool) < 2 * SHRINK_BINS:
            continue
        knots = []
        for i in range(SHRINK_BINS):
            b = pool[i * len(pool) // SHRINK_BINS:(i + 1) * len(pool) // SHRINK_BINS]
            knots.append((statistics.median(p[cov] for p in b),
                          sum(p[pair]["weighted"]["r"] for p in b) / len(b)))

        def noise(p: dict) -> float:
            r = p[pair]["weighted"]["r"]
            return (1 - r * r) ** 2 / p["effective_n"]
        resid = [p[pair]["weighted"]["r"] - _interp(knots, p[cov]) for p in pool]
        tau2 = max(sum(x * x for x in resid) / len(resid)
                   - sum(noise(p) for p in pool) / len(pool), SHRINK_TAU2_FLOOR)
        for p in players:
            if not usable(p):
                continue
            prior = _interp(knots, p[cov])
            w = tau2 / (tau2 + noise(p))
            p[pair]["shrunk"] = {"r": round(w * p[pair]["weighted"]["r"] + (1 - w) * prior, 4),
                                 "prior": round(prior, 4), "w": round(w, 3)}
        fits[pair] = {"covariate": cov, "tau": round(math.sqrt(tau2), 4), "pool_n": len(pool),
                      "knots": [[round(x, 2), round(y, 4)] for x, y in knots]}
    return {"method": "empirical Bayes: weighted r shrunk toward rotation players "
                      "with a similar covariate value",
            "pool": SHRINK_POOL, "pairs": fits}


def mark_short_games(games: list[dict], frac: float) -> float:
    """Flag games where the player logged under `frac` x his median minutes for
    that season (injury exits, blowout rest, minutes restrictions). Those games
    drag every stat down together and manufacture positive correlation, so they
    are left out of the correlations and the box means. Returns the cutoff."""
    if frac <= 0 or not games:
        for gm in games:
            gm["short"] = False
        return 0.0
    cut = frac * statistics.median(gm["min"] for gm in games)
    for gm in games:
        gm["short"] = gm["min"] < cut
    return cut


def process_player(
    sess: requests.Session, aid: str, seasons: list[int], weights: dict[int, float],
    min_mpg: float, team_map: dict[str, dict], recent: list[int], short_frac: float
) -> dict | None:
    by_year: dict[int, list[dict]] = {}
    pts: list[float] = []
    reb: list[float] = []
    ast: list[float] = []
    tpm: list[float] = []
    mins: list[float] = []
    ws: list[float] = []
    yrs: list[int] = []         # each game's season, for within-season centering
    scored: list[dict] = []     # games with a known final score
    scored_ws: list[float] = []
    scored_yrs: list[int] = []
    per_season: dict[str, int] = {}
    all_by_year: dict[int, list[dict]] = {}
    n_short = 0
    for yr in seasons:
        g_all = regular_season_games(sess, aid, yr)
        mark_short_games(g_all, short_frac)
        g = [gm for gm in g_all if not gm["short"]]
        if not g:
            continue
        all_by_year[yr] = g_all
        by_year[yr] = g
        per_season[str(yr)] = len(g)
        n_short += len(g_all) - len(g)
        w = weights.get(yr, 0.0)
        for gm in g:
            pts.append(gm["pts"]); reb.append(gm["reb"]); ast.append(gm["ast"])
            tpm.append(gm["tpm"]); mins.append(gm["min"]); ws.append(w)
            yrs.append(yr)
            if gm["tot"] is not None:
                scored.append(gm); scored_ws.append(w); scored_yrs.append(yr)
    n = len(pts)
    if n < 3:
        return None

    # Substantial-player gate: drop garbage-time / deep-bench players whose
    # minutes are too low for their box-score correlations to be meaningful.
    mpg = sum(mins) / n
    if mpg < min_mpg:
        return None

    name, pos = athlete_name(sess, max(seasons), aid)

    # Pooled r's are within-season: every stat is centered on its season mean
    # first (_centered). Each season mean spends one degree of freedom, so the
    # significance tests drop one n per extra season.
    c_pts, c_reb = _centered(pts, yrs), _centered(reb, yrs)
    c_ast, c_tpm = _centered(ast, yrs), _centered(tpm, yrs)
    dfx = len(set(yrs)) - 1
    # Unweighted (pooled, every game equal) for reference/comparison.
    r_pr, r_pa, r_p3 = pearson(c_pts, c_reb), pearson(c_pts, c_ast), pearson(c_pts, c_tpm)
    # Recency-weighted: each game carries its season weight.
    wpr = weighted_pearson(c_pts, c_reb, ws)
    wpa = weighted_pearson(c_pts, c_ast, ws)
    wp3 = weighted_pearson(c_pts, c_tpm, ws)
    n_eff = wpr[1] if wpr else (wpa[1] if wpa else None)
    n_test = None if n_eff is None else n_eff - dfx

    # Game scoring vs REB (pooled within-season; unweighted + recency-weighted).
    s_dfx = len(set(scored_yrs)) - 1
    s_reb = _centered([g["reb"] for g in scored], scored_yrs)
    score_corr = {}
    for k in SCORE_KEYS:
        xs = [g[k] for g in scored]
        cx = _centered(xs, scored_yrs)
        wk = weighted_pearson(cx, s_reb, scored_ws)
        score_corr[f"{k}_reb"] = {
            "unweighted": _pair(pearson(cx, s_reb), len(xs) - s_dfx),
            "weighted": _pair(wk[0] if wk else None, wk[1] - s_dfx if wk else None),
        }
        score_corr[f"{k}_mean"] = round(sum(xs) / len(xs), 1) if xs else None

    # Weighted scoring means, to show what role the recency tilt emphasizes.
    W = sum(ws) or 1.0
    team = team_map.get(aid, {})
    # Per-season breakdown (only seasons with >=3 games get correlations).
    by_season = {str(yr): {**_season_stats(by_year[yr]),
                           "short_games": len(all_by_year[yr]) - len(by_year[yr])}
                 for yr in sorted(by_year) if len(by_year[yr]) >= 3}
    latest = max(by_year) if by_year else None
    # Full game-by-game log for every pulled season,
    # date-ordered, each game tagged with its season `s`. Powers the viewer's
    # prop-builder scatter and box-stat columns, which blend these seasons
    # using the per-game recency weights. Ints stored as ints to keep the
    # JSON compact. Short-minute games stay in the log, flagged `short: 1`, so
    # the viewer can show them (or not); they never feed the r values.
    def _i(v: float) -> int | float:
        return int(v) if float(v).is_integer() else v
    recent_games = [
        {"s": yr, "d": gm["date"], "opp": gm["opp"], "loc": gm["loc"],
         "res": gm["res"], "min": _i(gm["min"]), "pts": _i(gm["pts"]),
         "reb": _i(gm["reb"]), "ast": _i(gm["ast"]), "tpm": _i(gm["tpm"]),
         **{k: _i(gm[k]) for k in SCORE_KEYS if gm[k] is not None},
         **({"short": 1} if gm["short"] else {})}
        for yr in recent for gm in all_by_year.get(yr, [])
    ]
    return {
        "athlete_id": aid,
        "name": name,
        "position": pos,
        "team_id": team.get("team_id", ""),
        "team_abbr": team.get("team_abbr", ""),
        "team_name": team.get("team_name", ""),
        "n_games": n,
        "n_short_games": n_short,
        "effective_n": None if n_eff is None else round(n_eff, 1),
        "min_mean": round(mpg, 1),
        "games_by_season": per_season,
        "latest_season": None if latest is None else str(latest),
        "pts_mean": round(sum(pts) / n, 2),
        "reb_mean": round(sum(reb) / n, 2),
        "ast_mean": round(sum(ast) / n, 2),
        "tpm_mean": round(sum(tpm) / n, 2),
        "pts_mean_weighted": round(sum(w * x for w, x in zip(ws, pts)) / W, 2),
        "pts_reb": {
            "unweighted": _pair(r_pr, n - dfx),
            "weighted": _pair(wpr[0] if wpr else None, n_test),
        },
        "pts_ast": {
            "unweighted": _pair(r_pa, n - dfx),
            "weighted": _pair(wpa[0] if wpa else None, n_test),
        },
        "pts_3pm": {
            "unweighted": _pair(r_p3, n - dfx),
            "weighted": _pair(wp3[0] if wp3 else None, n_test),
        },
        **score_corr,
        "by_season": by_season,
        "recent_games": recent_games,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", type=int, nargs="+", default=[2025, 2026, 2027],
                    help="Seasons to pool (default: 2025 2026 2027; 2027 = 2026-27, in progress).")
    ap.add_argument("--weights", default="2025=0.15,2026=0.35,2027=0.50",
                    help="Per-game recency weights as season=weight pairs. Only "
                         "the ratios matter (weighted Pearson is scale-free in "
                         "weights). Seasons absent here default to weight 0.")
    ap.add_argument("--min-games", type=int, default=20,
                    help="Min pooled games for a player to count as 'reportable'.")
    ap.add_argument("--min-mpg", type=float, default=0.0,
                    help="Optional min average minutes/game to include a player "
                         "(0 = keep everyone; filtering is done in the viewer).")
    ap.add_argument("--short-min-frac", type=float, default=0.6,
                    help="Drop games where the player played under this fraction "
                         "of his median minutes that season from correlations and "
                         "box means (0 = keep every game).")
    ap.add_argument("--workers", type=int, default=8,
                    help="Concurrent HTTP workers.")
    ap.add_argument("--out", default=os.path.join("public", "data", "nba_correlations.json"))
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap players processed (0 = all). For quick test runs.")
    ap.add_argument("--reshrink", action="store_true",
                    help="Only recompute the shrunk r's in the existing --out file "
                         "(no fetching).")
    args = ap.parse_args()

    if args.reshrink:
        with open(args.out, encoding="utf-8") as f:
            payload = json.load(f)
        payload["shrinkage"] = add_shrinkage(payload["players"])
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        for pair, fit in payload["shrinkage"]["pairs"].items():
            print(f"{pair:8} tau {fit['tau']:.3f}  pool {fit['pool_n']}  prior by "
                  f"{fit['covariate']}: " + "  ".join(f"{x:g}->{y:+.3f}" for x, y in fit["knots"]))
        print(f"Wrote {args.out}")
        return

    weights: dict[int, float] = {}
    for tok in args.weights.split(","):
        tok = tok.strip()
        if not tok:
            continue
        k, _, v = tok.partition("=")
        weights[int(k)] = float(v)

    # Every pulled season (last two + this one by default): the per-game logs the viewer's prop builder and
    # box-stat columns blend.
    recent = sorted(args.seasons)

    sess = make_session()

    print("Building team roster map + today's schedule ...", file=sys.stderr)
    team_map = team_roster_map(sess)
    sched = schedule_today(sess)
    today_ids = set(sched["team_ids"])
    print(f"  rosters: {len(team_map)} players mapped to teams; "
          f"{len(sched['games'])} games today ({sched['date']})", file=sys.stderr)

    print(f"Fetching NBA athlete index for seasons {args.seasons} ...",
          file=sys.stderr)
    ids: set[str] = set()
    for yr in args.seasons:
        s = season_athlete_ids(sess, yr)
        print(f"  {yr}: {len(s)} athletes", file=sys.stderr)
        ids |= s
    id_list = sorted(ids, key=int)
    if args.limit:
        id_list = id_list[: args.limit]
    print(f"Total unique athletes: {len(id_list)}. Pulling game logs ...",
          file=sys.stderr)

    players: list[dict] = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        # Each worker needs its own session for thread safety.
        sessions = [make_session() for _ in range(args.workers)]
        futs = {
            ex.submit(process_player, sessions[i % args.workers], aid,
                      args.seasons, weights, args.min_mpg, team_map, recent,
                      args.short_min_frac): aid
            for i, aid in enumerate(id_list)
        }
        for fut in cf.as_completed(futs):
            done += 1
            if done % 25 == 0:
                print(f"  ...{done}/{len(id_list)}", file=sys.stderr)
            try:
                res = fut.result()
            except Exception as e:  # noqa: BLE001 - one bad player shouldn't kill run
                print(f"  warn: athlete {futs[fut]} failed: {e}", file=sys.stderr)
                res = None
            if res:
                players.append(res)

    # Tag who plays today (generation-day snapshot; the web viewer refreshes
    # this live so the toggle stays correct on later days).
    for p in players:
        p["playing_today"] = bool(p["team_id"]) and p["team_id"] in today_ids

    players.sort(key=lambda p: p["name"].lower())
    shrinkage = add_shrinkage(players)

    reportable = [p for p in players if p["n_games"] >= args.min_games]
    total_games = sum(p["n_games"] for p in players)

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc)
            .isoformat().replace("+00:00", "Z"),
        "source": "ESPN NBA public API",
        "seasons": args.seasons,
        "scope": "regular-season games, pooled across seasons; correlations per player",
        "weighting": {
            "scheme": "per-game season weights (recency tilt); weighted Pearson, "
                      "Kish effective-N used for significance",
            "per_game_season_weights": {str(k): v for k, v in sorted(weights.items())},
            "centering": "pooled r's are within-season: each stat is centered on "
                         "its season mean before pooling",
        },
        "recent_seasons": recent,
        "min_games_reportable": args.min_games,
        "min_mpg_included": args.min_mpg,
        "short_game_rule": {
            "min_frac_of_season_median": args.short_min_frac,
            "note": "games under this fraction of the player's median minutes "
                    "that season are excluded from r values and box means",
        },
        "schedule_today": sched,
        "n_players": len(players),
        "n_players_reportable": len(reportable),
        "total_game_rows": total_games,
        "shrinkage": shrinkage,
        "players": players,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    # --- stdout summary ---
    def cell(v: float | None, w: int, prec: int) -> str:
        return f"{(v if v is not None else float('nan')):>{w}.{prec}f}"

    wtxt = " ".join(f"{k}={v}" for k, v in sorted(weights.items()))
    print()
    print(f"NBA PTS correlations — seasons {args.seasons}, recency-weighted "
          f"(per-game weights {wtxt})")
    print(f"Players with >= {args.min_games} games and >= {args.min_mpg} mpg: "
          f"{len(reportable)} (of {len(players)} included); {total_games} game rows")
    print("rw = recency-weighted r (headline); r = unweighted; nEff = effective "
          "sample size after weighting")
    print()
    hdr = (f"{'Player':<24}{'Pos':<4}{'G':>4}{'nEff':>6}{'MIN':>6}  "
           f"{'PTS':>5}{'REB':>5}{'AST':>5}{'3PM':>5}  "
           f"{'rwP-R':>7}{'p':>8}{'rP-R':>7}  "
           f"{'rwP-A':>7}{'p':>8}{'rP-A':>7}  "
           f"{'rwP-3':>7}{'p':>8}{'rP-3':>7}")
    print(hdr)
    print("-" * len(hdr))
    for p in sorted(reportable, key=lambda x: (x["pts_reb"]["weighted"]["r"] is None,
                                               -(x["pts_reb"]["weighted"]["r"] or 0))):
        pr, pa, p3 = p["pts_reb"], p["pts_ast"], p["pts_3pm"]
        print(f"{p['name'][:23]:<24}{p['position']:<4}{p['n_games']:>4}"
              f"{cell(p['effective_n'], 6, 1)}{cell(p['min_mean'], 6, 1)}  "
              f"{p['pts_mean']:>5}{p['reb_mean']:>5}{p['ast_mean']:>5}{p['tpm_mean']:>5}  "
              f"{cell(pr['weighted']['r'], 7, 3)}{cell(pr['weighted']['p_value'], 8, 4)}"
              f"{cell(pr['unweighted']['r'], 7, 3)}  "
              f"{cell(pa['weighted']['r'], 7, 3)}{cell(pa['weighted']['p_value'], 8, 4)}"
              f"{cell(pa['unweighted']['r'], 7, 3)}  "
              f"{cell(p3['weighted']['r'], 7, 3)}{cell(p3['weighted']['p_value'], 8, 4)}"
              f"{cell(p3['unweighted']['r'], 7, 3)}")

    print()
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
