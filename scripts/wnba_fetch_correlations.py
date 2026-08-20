#!/usr/bin/env python3
"""Pull WNBA per-game logs from ESPN and compute per-player correlations
between PTS-REB, PTS-AST and PTS-3PM over the last three seasons.

Correlations are reported two ways per player: unweighted (every game equal)
and recency-weighted, where each game carries a per-season weight (default
2024=0.15, 2025=0.35, 2026=0.50 — only the ratios matter). The weighted
significance test uses the Kish effective sample size so leaning on recent
games is reflected honestly in the p-value.

Data source (public ESPN endpoints, no key required):
  - Season athlete index:
      https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/seasons/{Y}/athletes?limit=1000
  - Athlete bio (name/position):
      https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/seasons/{Y}/athletes/{id}
  - Per-game log:
      https://site.web.api.espn.com/apis/common/v3/sports/basketball/wnba/athletes/{id}/gamelog?season={Y}

For each athlete we collect (PTS, REB, AST) for every regular-season game in the
requested seasons, pool the games, and compute the Pearson correlation for the
two prop pairs. A two-sided p-value is computed from the t-distribution via the
regularized incomplete beta function (no scipy dependency).

ESPN's gamelog files the All-Star Game and the Commissioner's Cup Championship
under "Regular Season" even though neither counts toward season stats, so both
are dropped (Commissioner's Cup group-play games do count and are kept). Every
player-season is then reconciled against ESPN's own season totals; disagreements
are reported at the end of the run and in the JSON's `espn_totals_check`.

Outputs:
  - JSON: public/data/wnba_correlations.json  (or --out)
  - A human-readable summary table to stdout.

Usage:
  python3 scripts/wnba_fetch_correlations.py                 # seasons 2024,2025,2026
  python3 scripts/wnba_fetch_correlations.py --seasons 2024 2025
  python3 scripts/wnba_fetch_correlations.py --min-games 25 --workers 8
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import re
import sys
import time
from typing import Any

import requests

CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba"
SITE = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/wnba"
# site.web.api serves the same /apis/site/v2 paths as site.api.espn.com, which
# started returning 403 to datacenter IPs (get_json swallows that as None, so
# rosters and the slate came back empty instead of erroring).
SITE_API = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/wnba"

# Column positions inside each gamelog event's `stats` array. The order is
# fixed by the league-level `names` array returned alongside the events:
#   ['MIN','PTS','REB','AST','STL','BLK','TO','FG','FG%','3PT','3P%', ...]
# The 3PT cell is a "made-attempted" string like "3-5"; we take the made part.
MIN_IDX, PTS_IDX, REB_IDX, AST_IDX, TPM_IDX = 0, 1, 2, 3, 9

ID_RE = re.compile(r"/athletes/(\d+)")

# ESPN files a few exhibitions inside the gamelog's "Regular Season" bucket even
# though the league does not count them toward season stats, so a naive read of
# the log runs ahead of the GP on ESPN's own stats page (Chelsea Gray's 2026 log
# has 37 events against ESPN's 36 GP). Two kinds show up, both tagged in the
# event metadata by `eventNote`:
#   - "AT&T WNBA All-Star Game"              (also flagged via team.isAllStar)
#   - "WNBA Commissioner's Cup Championship"
# Commissioner's Cup *group-play* games carry the note "WNBA Commissioner's Cup"
# and ARE ordinary regular-season games — they must not be filtered. Verified by
# reconciling every kept game against ESPN's own Regular Season totals for all
# 447 player-seasons in 2024-2026 (see espn_season_totals below).
ALLSTAR_NOTE_RE = re.compile(r"all[-\s]?star", re.I)
CUP_FINAL_NOTE_RE = re.compile(r"commissioner.*(championship|final)", re.I)


def is_exhibition(meta: dict) -> bool:
    """True for gamelog events the league excludes from regular-season stats."""
    note = meta.get("eventNote") or ""
    if ALLSTAR_NOTE_RE.search(note) or CUP_FINAL_NOTE_RE.search(note):
        return True
    # All-Star entries also set an explicit flag on both team blocks.
    for side in ("team", "opponent"):
        if (meta.get(side) or {}).get("isAllStar"):
            return True
    return False


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (wnba-correlations/1.0)"})
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
    """Today's WNBA slate from the public scoreboard. Returns the date used,
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


def espn_season_totals(data: dict) -> dict | None:
    """ESPN's own Regular Season totals row from a gamelog payload.

    This is the number the stats page is built from, so it is the ground truth
    for 'which games count'. Only PTS/REB/AST/3PM are read: ESPN's totals row
    drifts a unit or two from the sum of its own gamelog on MIN and on the
    attempt columns for a handful of players, but the counting stats reconcile
    exactly once the exhibitions are dropped.
    """
    for st in data.get("seasonTypes") or []:
        if "Regular Season" not in (st.get("displayName") or ""):
            continue
        for block in ((st.get("summary") or {}).get("stats") or []):
            if block.get("type") != "total":
                continue
            s = block.get("stats") or []
            if len(s) <= TPM_IDX:
                return None
            vals = {"pts": _num(s[PTS_IDX]), "reb": _num(s[REB_IDX]),
                    "ast": _num(s[AST_IDX]), "tpm": _made(s[TPM_IDX])}
            return None if any(v is None for v in vals.values()) else vals
    return None


def regular_season_games(
    sess: requests.Session, aid: str, season: int
) -> tuple[list[dict], dict | None]:
    """Return one dict per regular-season game -- box stats plus game metadata
    (date, opponent, home/away, result) pulled from the payload's events map --
    alongside ESPN's own season totals for cross-checking.

    Categories within a season type are monthly partitions; we dedupe on
    eventId so any overlap can't double-count a game. Exhibitions ESPN files
    under Regular Season but leaves out of its season stats (All-Star Game,
    Commissioner's Cup Championship) are dropped -- see is_exhibition.
    """
    url = f"{SITE}/athletes/{aid}/gamelog?season={season}"
    data = get_json(sess, url)
    if not data:
        return [], None
    ev_meta = data.get("events") or {}
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
                m = ev_meta.get(eid) or {}
                if is_exhibition(m):
                    continue
                stats = ev.get("stats") or []
                if len(stats) <= TPM_IDX:
                    continue
                pts = _num(stats[PTS_IDX])
                reb = _num(stats[REB_IDX])
                ast = _num(stats[AST_IDX])
                tpm = _made(stats[TPM_IDX])
                mins = _num(stats[MIN_IDX])
                if pts is None or reb is None or ast is None or tpm is None:
                    continue
                if eid:
                    seen.add(eid)
                out.append({
                    "pts": pts, "reb": reb, "ast": ast, "tpm": tpm,
                    "min": 0.0 if mins is None else mins,
                    "date": (m.get("gameDate") or "")[:10],
                    "opp": (m.get("opponent") or {}).get("abbreviation") or "",
                    "loc": m.get("atVs") or "",
                    "res": m.get("gameResult") or "",
                })
    out.sort(key=lambda g: g["date"])
    return out, espn_season_totals(data)


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
    }


def _totals_mismatch(games: list[dict], espn: dict | None) -> dict | None:
    """Our kept games vs ESPN's official season totals; None when they agree.

    A disagreement means ESPN counts a different set of games than we do -- a
    new kind of exhibition slipping through is_exhibition, most likely -- so it
    is surfaced in the run summary rather than silently shifting every stat.
    """
    if not espn:
        return None
    ours = {k: sum(g[k] for g in games) for k in ("pts", "reb", "ast", "tpm")}
    off = {k: round(ours[k] - espn[k], 3) for k in ours if abs(ours[k] - espn[k]) > 1e-9}
    return None if not off else {"games": len(games), "ours": ours,
                                 "espn": espn, "diff": off}


def process_player(
    sess: requests.Session, aid: str, seasons: list[int], weights: dict[int, float],
    min_mpg: float, team_map: dict[str, dict]
) -> dict | None:
    by_year: dict[int, list[dict]] = {}
    pts: list[float] = []
    reb: list[float] = []
    ast: list[float] = []
    tpm: list[float] = []
    mins: list[float] = []
    ws: list[float] = []
    per_season: dict[str, int] = {}
    checks: dict[str, dict] = {}
    for yr in seasons:
        g, espn_totals = regular_season_games(sess, aid, yr)
        if not g:
            continue
        bad = _totals_mismatch(g, espn_totals)
        if bad:
            checks[str(yr)] = bad
        by_year[yr] = g
        per_season[str(yr)] = len(g)
        w = weights.get(yr, 0.0)
        for gm in g:
            pts.append(gm["pts"]); reb.append(gm["reb"]); ast.append(gm["ast"])
            tpm.append(gm["tpm"]); mins.append(gm["min"]); ws.append(w)
    n = len(pts)
    if n < 3:
        return None

    # Substantial-player gate: drop garbage-time / deep-bench players whose
    # minutes are too low for their box-score correlations to be meaningful.
    mpg = sum(mins) / n
    if mpg < min_mpg:
        return None

    name, pos = athlete_name(sess, max(seasons), aid)

    # Unweighted (pooled, every game equal) for reference/comparison.
    r_pr, r_pa, r_p3 = pearson(pts, reb), pearson(pts, ast), pearson(pts, tpm)
    # Recency-weighted: each game carries its season weight.
    wpr = weighted_pearson(pts, reb, ws)
    wpa = weighted_pearson(pts, ast, ws)
    wp3 = weighted_pearson(pts, tpm, ws)
    n_eff = wpr[1] if wpr else (wpa[1] if wpa else None)

    # Weighted scoring means, to show what role the recency tilt emphasizes.
    W = sum(ws) or 1.0
    team = team_map.get(aid, {})
    # Per-season breakdown (only seasons with >=3 games get correlations).
    by_season = {str(yr): _season_stats(by_year[yr])
                 for yr in sorted(by_year) if len(by_year[yr]) >= 3}
    latest = max(by_year) if by_year else None
    # Full game-by-game log for the latest (current) season, date-ordered.
    # Powers the prop-builder scatter in the viewer, which is deliberately
    # this-season-only. Ints stored as ints to keep the JSON compact.
    def _i(v: float) -> int | float:
        return int(v) if float(v).is_integer() else v
    latest_games = [] if latest is None else [
        {"d": gm["date"], "opp": gm["opp"], "loc": gm["loc"], "res": gm["res"],
         "min": _i(gm["min"]), "pts": _i(gm["pts"]), "reb": _i(gm["reb"]),
         "ast": _i(gm["ast"]), "tpm": _i(gm["tpm"])}
        for gm in by_year[latest]
    ]
    return {
        "athlete_id": aid,
        "name": name,
        "position": pos,
        "team_id": team.get("team_id", ""),
        "team_abbr": team.get("team_abbr", ""),
        "team_name": team.get("team_name", ""),
        "n_games": n,
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
            "unweighted": _pair(r_pr, n),
            "weighted": _pair(wpr[0] if wpr else None, n_eff),
        },
        "pts_ast": {
            "unweighted": _pair(r_pa, n),
            "weighted": _pair(wpa[0] if wpa else None, n_eff),
        },
        "pts_3pm": {
            "unweighted": _pair(r_p3, n),
            "weighted": _pair(wp3[0] if wp3 else None, n_eff),
        },
        "by_season": by_season,
        "latest_games": latest_games,
        "_totals_check": checks,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025, 2026],
                    help="Seasons to pool (default: 2024 2025 2026; 2026 in progress).")
    ap.add_argument("--weights", default="2024=0.15,2025=0.35,2026=0.50",
                    help="Per-game recency weights as season=weight pairs. Only "
                         "the ratios matter (weighted Pearson is scale-free in "
                         "weights). Seasons absent here default to weight 0.")
    ap.add_argument("--min-games", type=int, default=20,
                    help="Min pooled games for a player to count as 'reportable'.")
    ap.add_argument("--min-mpg", type=float, default=0.0,
                    help="Optional min average minutes/game to include a player "
                         "(0 = keep everyone; filtering is done in the viewer).")
    ap.add_argument("--workers", type=int, default=8,
                    help="Concurrent HTTP workers.")
    ap.add_argument("--out", default=os.path.join("public", "data", "wnba_correlations.json"))
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap players processed (0 = all). For quick test runs.")
    args = ap.parse_args()

    weights: dict[int, float] = {}
    for tok in args.weights.split(","):
        tok = tok.strip()
        if not tok:
            continue
        k, _, v = tok.partition("=")
        weights[int(k)] = float(v)

    sess = make_session()

    print("Building team roster map + today's schedule ...", file=sys.stderr)
    team_map = team_roster_map(sess)
    sched = schedule_today(sess)
    today_ids = set(sched["team_ids"])
    print(f"  rosters: {len(team_map)} players mapped to teams; "
          f"{len(sched['games'])} games today ({sched['date']})", file=sys.stderr)

    print(f"Fetching WNBA athlete index for seasons {args.seasons} ...",
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
                      args.seasons, weights, args.min_mpg, team_map): aid
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

    # Cross-check against ESPN's own season totals. Every kept game should be a
    # game ESPN counts, so a non-empty list here means the exhibition filter has
    # fallen behind ESPN's data (a new note wording, a new non-counting event).
    totals_mismatches = [
        {"athlete_id": p["athlete_id"], "name": p["name"], "season": yr, **info}
        for p in players for yr, info in sorted(p.pop("_totals_check", {}).items())
    ]

    reportable = [p for p in players if p["n_games"] >= args.min_games]
    total_games = sum(p["n_games"] for p in players)

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc)
            .isoformat().replace("+00:00", "Z"),
        "source": "ESPN WNBA public API",
        "seasons": args.seasons,
        "scope": "regular-season games (All-Star Game and Commissioner's Cup "
                 "Championship excluded, as ESPN's season stats do), pooled "
                 "across seasons; correlations per player",
        "weighting": {
            "scheme": "per-game season weights (recency tilt); weighted Pearson, "
                      "Kish effective-N used for significance",
            "per_game_season_weights": {str(k): v for k, v in sorted(weights.items())},
        },
        "min_games_reportable": args.min_games,
        "min_mpg_included": args.min_mpg,
        "espn_totals_check": {
            "note": "Kept games reconciled against ESPN's own Regular Season "
                    "totals (PTS/REB/AST/3PM). Non-empty 'mismatches' means our "
                    "game set has drifted from ESPN's.",
            "n_mismatched_player_seasons": len(totals_mismatches),
            "mismatches": totals_mismatches[:25],
        },
        "schedule_today": sched,
        "n_players": len(players),
        "n_players_reportable": len(reportable),
        "total_game_rows": total_games,
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
    print(f"WNBA PTS correlations — seasons {args.seasons}, recency-weighted "
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
    if totals_mismatches:
        print(f"WARNING: {len(totals_mismatches)} player-season(s) disagree with "
              f"ESPN's own regular-season totals — the exhibition filter may be "
              f"out of date. First few:")
        for mm in totals_mismatches[:5]:
            print(f"  {mm['name']} {mm['season']}: {mm['games']} games kept, "
                  f"diff {mm['diff']}")
    else:
        print("ESPN totals cross-check: all player-seasons reconcile.")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
