#!/usr/bin/env python3
"""Pull WNBA per-game logs from ESPN and compute per-player correlations
between PTS-REB and PTS-AST, pooled over the last two seasons.

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

Outputs:
  - JSON: public/data/wnba_correlations.json  (or --out)
  - A human-readable summary table to stdout.

Usage:
  python3 scripts/wnba_fetch_correlations.py                 # seasons 2024,2025
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

# Column positions inside each gamelog event's `stats` array. The order is
# fixed by the league-level `names` array returned alongside the events:
#   ['minutes','points','totalRebounds','assists','steals','blocks', ...]
PTS_IDX, REB_IDX, AST_IDX = 1, 2, 3

ID_RE = re.compile(r"/athletes/(\d+)")


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


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def regular_season_games(
    sess: requests.Session, aid: str, season: int
) -> list[tuple[float, float, float]]:
    """Return list of (pts, reb, ast) for each regular-season game in `season`.

    Categories within a season type are monthly partitions; we dedupe on
    eventId so any overlap can't double-count a game.
    """
    url = f"{SITE}/athletes/{aid}/gamelog?season={season}"
    data = get_json(sess, url)
    if not data:
        return []
    out: list[tuple[float, float, float]] = []
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
                if len(stats) <= AST_IDX:
                    continue
                pts = _num(stats[PTS_IDX])
                reb = _num(stats[REB_IDX])
                ast = _num(stats[AST_IDX])
                if pts is None or reb is None or ast is None:
                    continue
                if eid:
                    seen.add(eid)
                out.append((pts, reb, ast))
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

def process_player(
    sess: requests.Session, aid: str, seasons: list[int]
) -> dict | None:
    games: list[tuple[float, float, float]] = []
    per_season: dict[str, int] = {}
    for yr in seasons:
        g = regular_season_games(sess, aid, yr)
        if g:
            per_season[str(yr)] = len(g)
            games.extend(g)
    if len(games) < 3:
        return None
    name, pos = athlete_name(sess, max(seasons), aid)
    pts = [g[0] for g in games]
    reb = [g[1] for g in games]
    ast = [g[2] for g in games]
    n = len(games)
    r_pr = pearson(pts, reb)
    r_pa = pearson(pts, ast)
    return {
        "athlete_id": aid,
        "name": name,
        "position": pos,
        "n_games": n,
        "games_by_season": per_season,
        "pts_mean": round(sum(pts) / n, 2),
        "reb_mean": round(sum(reb) / n, 2),
        "ast_mean": round(sum(ast) / n, 2),
        "pts_reb": {
            "r": None if r_pr is None else round(r_pr, 4),
            "p_value": None if r_pr is None else round(pearson_pvalue(r_pr, n), 5),
        },
        "pts_ast": {
            "r": None if r_pa is None else round(r_pa, 4),
            "p_value": None if r_pa is None else round(pearson_pvalue(r_pa, n), 5),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025],
                    help="Seasons to pool (default: 2024 2025).")
    ap.add_argument("--min-games", type=int, default=20,
                    help="Min pooled games for a player to count as 'reportable'.")
    ap.add_argument("--workers", type=int, default=8,
                    help="Concurrent HTTP workers.")
    ap.add_argument("--out", default=os.path.join("public", "data", "wnba_correlations.json"))
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap players processed (0 = all). For quick test runs.")
    args = ap.parse_args()

    sess = make_session()

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
            ex.submit(process_player, sessions[i % args.workers], aid, args.seasons): aid
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

    players.sort(key=lambda p: p["name"].lower())

    reportable = [p for p in players if p["n_games"] >= args.min_games]
    total_games = sum(p["n_games"] for p in players)

    # League summary: games-weighted mean of per-player r's over reportable
    # players — a stable, interpretable aggregate that avoids letting
    # cross-player scoring-level differences inflate a naive pooled correlation.
    def wmean(key: str) -> float | None:
        num = den = 0.0
        for p in reportable:
            r = p[key]["r"]
            if r is None:
                continue
            w = p["n_games"]
            num += r * w
            den += w
        return round(num / den, 4) if den else None

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc)
            .isoformat().replace("+00:00", "Z"),
        "source": "ESPN WNBA public API",
        "seasons": args.seasons,
        "scope": "regular-season games, pooled across seasons; correlations per player",
        "min_games_reportable": args.min_games,
        "n_players": len(players),
        "n_players_reportable": len(reportable),
        "total_game_rows": total_games,
        "league_weighted_mean_r": {
            "pts_reb": wmean("pts_reb"),
            "pts_ast": wmean("pts_ast"),
        },
        "players": players,
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    # --- stdout summary ---
    print()
    print(f"WNBA PTS correlations — seasons {args.seasons} (regular season, pooled)")
    print(f"Players with >= {args.min_games} games: {len(reportable)} "
          f"(of {len(players)} with any games); {total_games} total game rows")
    print(f"League games-weighted mean r:  "
          f"PTS-REB={payload['league_weighted_mean_r']['pts_reb']}   "
          f"PTS-AST={payload['league_weighted_mean_r']['pts_ast']}")
    print()
    hdr = f"{'Player':<24}{'Pos':<4}{'G':>4}  {'PTS':>5}{'REB':>5}{'AST':>5}  " \
          f"{'r(P-R)':>7}{'p':>8}  {'r(P-A)':>7}{'p':>8}"
    print(hdr)
    print("-" * len(hdr))
    for p in sorted(reportable, key=lambda x: (x["pts_reb"]["r"] is None,
                                               -(x["pts_reb"]["r"] or 0))):
        pr = p["pts_reb"]; pa = p["pts_ast"]
        print(f"{p['name'][:23]:<24}{p['position']:<4}{p['n_games']:>4}  "
              f"{p['pts_mean']:>5}{p['reb_mean']:>5}{p['ast_mean']:>5}  "
              f"{(pr['r'] if pr['r'] is not None else float('nan')):>7.3f}"
              f"{(pr['p_value'] if pr['p_value'] is not None else float('nan')):>8.4f}  "
              f"{(pa['r'] if pa['r'] is not None else float('nan')):>7.3f}"
              f"{(pa['p_value'] if pa['p_value'] is not None else float('nan')):>8.4f}")

    print()
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
