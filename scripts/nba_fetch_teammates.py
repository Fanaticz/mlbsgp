#!/usr/bin/env python3
"""NBA teammate correlations + assist network for one regular season.

For every pair of teammates (A, B) who played in the same games, computes:

  * AST(A) x PTS(B)   - does A having a big assist night go with B scoring?
  * AST(A) x 3PM(B)   - ... with B hitting threes?
  * REB(A) x REB(B)   - do they share the glass (negative) or rise together?

and, from play-by-play, the direct assist link A -> B: how many of B's
baskets A set up per game, what share of A's assists go to B, and what share
of B's made field goals / threes came off A's passes.

Seasons use ESPN's convention (2026 = the 2025-26 season). One request per
game: ESPN's game summary carries both the box score and play-by-play, where
an assisted basket reads "X makes ... (Y assists)" with participants
[scorer, assister].

Correlation details
  * r       Pearson on the raw per-game stats over the games both played.
  * phi     Pearson on Over/Under hit indicators at a proxy prop line for each
            player (floor(season mean) + 0.5). This is the number the SGP math
            uses (binary phi), since bets settle on lines, not raw stats.
  * shrunk  Empirical-Bayes shrinkage of phi in Fisher-z space toward the
            league mean for that stat pair and role pairing (starter /
            rotation / bench by mpg). Individual teammate pairs are noisy;
            role carries most of the real signal (blowouts push bench players'
            minutes and stats up together while starters sit).

Outputs public/data/nba_teammates.json.

Usage:
  python3 scripts/nba_fetch_teammates.py                 # season 2026
  python3 scripts/nba_fetch_teammates.py --season 2027 --min-games 10
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
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nba_fetch_correlations import (  # noqa: E402
    SITE_API, get_json, make_session, team_roster_map,
)

SUMMARY = f"{SITE_API}/summary?event={{}}"
SCOREBOARD = f"{SITE_API}/scoreboard?dates={{}}&limit=1000"
STATS = ("pts", "reb", "ast", "tpm")
PAIRS = {             # key -> (A stat, B stat, symmetric?)
    "ast_pts": ("ast", "pts", False),
    "ast_3pm": ("ast", "tpm", False),
    "reb_reb": ("reb", "reb", True),
}
ASSIST_RE = re.compile(r"\(([^()]+?) assists?\)")


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------
def season_event_ids(sess, season: int) -> list[str]:
    """Final regular-season game ids. Season Y runs Oct (Y-1) to Jun Y."""
    ids: list[str] = []
    for y, m in [(season - 1, mm) for mm in (10, 11, 12)] + [(season, mm) for mm in range(1, 7)]:
        data = get_json(sess, SCOREBOARD.format(f"{y}{m:02d}")) or {}
        for e in data.get("events", []):
            s = e.get("season") or {}
            st = ((e.get("status") or {}).get("type") or {})
            if s.get("year") == season and s.get("type") == 2 and st.get("completed"):
                ids.append(str(e["id"]))
    return sorted(set(ids))


def _mins(v) -> float:
    try:
        return float(str(v).split(":")[0])
    except (TypeError, ValueError):
        return 0.0


def _made(v) -> int:
    try:
        return int(str(v).split("-")[0])
    except (TypeError, ValueError):
        return 0


def parse_game(eid: str, data: dict) -> dict | None:
    """Slim one game: per-player box lines + assist edges."""
    try:
        comp = data["header"]["competitions"][0]
    except (KeyError, IndexError, TypeError):
        return None
    score = {str(c["team"]["id"]): int(float(c.get("score") or 0)) for c in comp["competitors"]}
    abbr = {str(c["team"]["id"]): c["team"].get("abbreviation", "") for c in comp["competitors"]}
    players: dict[str, dict] = {}
    names: dict[str, str] = {}
    for tblock in (data.get("boxscore") or {}).get("players", []):
        tid = str(tblock["team"]["id"])
        for sb in tblock.get("statistics", []):
            keys = sb.get("keys") or []
            ix = {k: i for i, k in enumerate(keys)}
            for a in sb.get("athletes", []):
                st = a.get("stats") or []
                if a.get("didNotPlay") or not st:
                    continue
                mn = _mins(st[ix["minutes"]]) if "minutes" in ix else 0.0
                if mn <= 0:
                    continue
                aid = str(a["athlete"]["id"])
                names[aid] = a["athlete"].get("displayName", aid)
                g = lambda k: st[ix[k]] if k in ix else 0  # noqa: E731
                players[aid] = {
                    "t": tid, "min": mn, "st": 1 if a.get("starter") else 0,
                    "pts": int(float(g("points") or 0)),
                    "reb": int(float(g("rebounds") or 0)),
                    "ast": int(float(g("assists") or 0)),
                    "tpm": _made(g("threePointFieldGoalsMade-threePointFieldGoalsAttempted")),
                    "fgm": _made(g("fieldGoalsMade-fieldGoalsAttempted")),
                }
    if not players:
        return None
    # assist edges: assister -> scorer, split 2s and 3s
    edges: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for p in data.get("plays", []) or []:
        if not (p.get("scoringPlay") and p.get("shootingPlay")):
            continue
        if "assist" not in (p.get("text") or ""):
            continue
        parts = [str((x.get("athlete") or {}).get("id") or "") for x in p.get("participants") or []]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        scorer, passer = parts[0], parts[1]
        if scorer not in players or passer not in players:
            continue
        e = edges[f"{passer}>{scorer}"]
        if int(p.get("scoreValue") or 0) == 3:
            e[1] += 1
        else:
            e[0] += 1
    return {"id": eid, "d": (data["header"]["competitions"][0].get("date") or "")[:10],
            "score": score, "abbr": abbr, "p": players, "names": names,
            "ae": {k: v for k, v in edges.items()}}


def fetch_games(season: int, workers: int, cache_path: str) -> list[dict]:
    cache: dict[str, dict] = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path) as fh:
            cache = {g["id"]: g for g in json.load(fh)}
    sess = make_session()
    ids = season_event_ids(sess, season)
    todo = [i for i in ids if i not in cache]
    print(f"season {season}: {len(ids)} final games, {len(todo)} to fetch", file=sys.stderr)

    def one(eid):
        data = get_json(make_session(), SUMMARY.format(eid))
        return parse_game(eid, data) if data else None

    done = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for g in ex.map(one, todo):
            done += 1
            if g:
                cache[g["id"]] = g
            if done % 100 == 0:
                print(f"  {done}/{len(todo)}", file=sys.stderr)
    games = [cache[i] for i in ids if i in cache]
    if cache_path:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w") as fh:
            json.dump(games, fh, separators=(",", ":"))
    return games


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------
def pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def fz(r: float) -> float:
    return math.atanh(max(min(r, 0.999), -0.999))


def role_of(mpg: float) -> str:
    return "S" if mpg >= 28 else ("R" if mpg >= 18 else "B")


def build(games: list[dict], min_games: int, roster: dict) -> dict:
    # per (team, player) game rows
    rows: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    names: dict[str, str] = {}
    team_abbr: dict[str, str] = {}
    margin: dict[tuple[str, str], int] = {}
    for g in games:
        names.update(g["names"])
        team_abbr.update(g["abbr"])
        tids = list(g["score"])
        for aid, line in g["p"].items():
            rows[(line["t"], aid)][g["id"]] = line
        for t in tids:
            o = [x for x in tids if x != t]
            margin[(g["id"], t)] = g["score"][t] - (g["score"][o[0]] if o else 0)
    edges = {g["id"]: g["ae"] for g in games}

    # player season summaries (per team stint)
    players = {}
    for (tid, aid), gl in rows.items():
        n = len(gl)
        mean = {k: sum(r[k] for r in gl.values()) / n for k in STATS + ("min",)}
        players[(tid, aid)] = {
            "athlete_id": aid, "name": names.get(aid, aid), "team_id": tid,
            "team_abbr": team_abbr.get(tid, ""), "games": n,
            "starts": sum(r["st"] for r in gl.values()),
            "mpg": round(mean["min"], 1), "role": role_of(mean["min"]),
            **{f"{k}_mean": round(mean[k], 2) for k in STATS},
            # proxy prop line: nearest x.5 at or below the season mean
            "lines": {k: math.floor(mean[k]) + 0.5 for k in STATS},
        }

    by_team: dict[str, list[str]] = defaultdict(list)
    for (tid, aid), p in players.items():
        if p["games"] >= min_games:
            by_team[tid].append(aid)

    pairs = []
    for tid, aids in by_team.items():
        for a in aids:
            for b in aids:
                if a == b:
                    continue
                ga, gb = rows[(tid, a)], rows[(tid, b)]
                shared = sorted(set(ga) & set(gb))
                n = len(shared)
                if n < min_games:
                    continue
                pa, pb = players[(tid, a)], players[(tid, b)]
                rec = {"team_id": tid, "a": a, "b": b, "n": n}
                close = [gid for gid in shared if abs(margin[(gid, tid)]) <= 12]
                for key, (sa, sb, sym) in PAIRS.items():
                    if sym and a > b:
                        continue
                    xa = [ga[gid][sa] for gid in shared]
                    xb = [gb[gid][sb] for gid in shared]
                    la, lb = pa["lines"][sa], pb["lines"][sb]
                    ha = [1.0 if v > la else 0.0 for v in xa]
                    hb = [1.0 if v > lb else 0.0 for v in xb]
                    both = sum(1 for u, v in zip(ha, hb) if u and v) / n
                    r = pearson(xa, xb)
                    phi = pearson(ha, hb)
                    rc = pearson([ga[gid][sa] for gid in close], [gb[gid][sb] for gid in close]) \
                        if len(close) >= 15 else None
                    rec[key] = {
                        "r": None if r is None else round(r, 4),
                        "phi": None if phi is None else round(phi, 4),
                        "r_close": None if rc is None else round(rc, 4),
                        "n_close": len(close),
                        "line_a": la, "line_b": lb,
                        "hit_a": round(sum(ha) / n, 3), "hit_b": round(sum(hb) / n, 3),
                        "hit_both": round(both, 3),
                    }
                # direct assists A -> B over the shared games
                a2 = a3 = 0
                for gid in shared:
                    e = edges[gid].get(f"{a}>{b}")
                    if e:
                        a2 += e[0]
                        a3 += e[1]
                a_ast = sum(ga[gid]["ast"] for gid in shared)
                b_fgm = sum(gb[gid]["fgm"] for gid in shared)
                b_tpm = sum(gb[gid]["tpm"] for gid in shared)
                per_game = [sum((edges[gid].get(f"{a}>{b}") or [0, 0])) for gid in shared]
                rec["assists"] = {
                    "per_game": round((a2 + a3) / n, 2),
                    "threes_per_game": round(a3 / n, 2),
                    "share_of_a_ast": round((a2 + a3) / a_ast, 3) if a_ast else None,
                    "share_of_b_fgm": round((a2 + a3) / b_fgm, 3) if b_fgm else None,
                    "share_of_b_3pm": round(a3 / b_tpm, 3) if b_tpm else None,
                    "r_direct_b_pts": (lambda v: None if v is None else round(v, 4))(
                        pearson(per_game, [gb[gid]["pts"] for gid in shared])),
                    "max_game": max(per_game) if per_game else 0,
                }
                pairs.append(rec)

    # ---- empirical-Bayes shrinkage of phi ---------------------------------
    role = {(p["team_id"], p["athlete_id"]): p["role"] for p in players.values()}
    priors = {}
    for key in PAIRS:
        recs = [p for p in pairs if key in p and p[key]["phi"] is not None]
        if not recs:
            continue
        z = [fz(p[key]["phi"]) for p in recs]
        se2 = [1 / max(p["n"] - 3, 1) for p in recs]
        wts = [1 / s for s in se2]
        mu_all = sum(w * v for w, v in zip(wts, z)) / sum(wts)
        var = sum((v - mu_all) ** 2 for v in z) / len(z)
        tau2 = max(var - sum(se2) / len(se2), 0.0003)
        cells: dict[str, list] = defaultdict(list)
        for p, v, w in zip(recs, z, wts):
            cells[role[(p["team_id"], p["a"])] + role[(p["team_id"], p["b"])]].append((v, w))
        cell_mu = {}
        for c, vs in cells.items():
            if key == "reb_reb":  # symmetric: SB and BS are the same cell
                pass
            # partial pooling of the cell mean toward the overall mean
            sw = sum(w for _, w in vs)
            m = sum(v * w for v, w in vs) / sw
            k = len(vs) / (len(vs) + 15)
            cell_mu[c] = k * m + (1 - k) * mu_all
        if key == "reb_reb":
            for c in list(cell_mu):
                rc = c[::-1]
                if rc in cell_mu and rc != c:
                    nc, nrc = len(cells[c]), len(cells[rc])
                    avg = (cell_mu[c] * nc + cell_mu[rc] * nrc) / (nc + nrc)
                    cell_mu[c] = cell_mu[rc] = avg
        for p, v, s in zip(recs, z, se2):
            c = role[(p["team_id"], p["a"])] + role[(p["team_id"], p["b"])]
            w = tau2 / (tau2 + s)
            p[key]["prior"] = round(math.tanh(cell_mu[c]), 4)
            p[key]["w"] = round(w, 3)
            p[key]["shrunk"] = round(math.tanh(w * v + (1 - w) * cell_mu[c]), 4)
        priors[key] = {
            "league_phi": round(math.tanh(mu_all), 4), "tau": round(math.sqrt(tau2), 4),
            "league_r": round(sum(p[key]["r"] for p in recs if p[key]["r"] is not None) / len(recs), 4),
            "by_role": {c: {"phi": round(math.tanh(m), 4), "pairs": len(cells[c])}
                        for c, m in sorted(cell_mu.items())},
        }

    pl_out = [p for p in players.values() if p["games"] >= min_games]
    for p in pl_out:
        cur = roster.get(p["athlete_id"]) or {}
        p["current_team"] = cur.get("team_abbr", "")
    return {"players": pl_out, "pairs": pairs, "priors": priors}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=2026, help="ESPN season year (2026 = 2025-26)")
    ap.add_argument("--min-games", type=int, default=20, help="min games together for a pair")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--cache", default=None,
                    help="slim per-game cache (default .cache/nba_games_<season>.json)")
    ap.add_argument("--out", default=os.path.join("public", "data", "nba_teammates.json"))
    args = ap.parse_args()
    cache = args.cache or os.path.join(".cache", f"nba_games_{args.season}.json")

    games = fetch_games(args.season, args.workers, cache)
    if not games:
        sys.exit("No games fetched; leaving the data file alone.")
    roster = team_roster_map(make_session())
    res = build(games, args.min_games, roster)
    n_ast = sum(sum(sum(v) for v in g["ae"].values()) for g in games)
    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "ESPN NBA game summaries (box score + play-by-play)",
        "season": args.season,
        "season_label": f"{args.season - 1}-{str(args.season)[2:]}",
        "n_games": len(games),
        "n_assists_linked": n_ast,
        "min_games_together": args.min_games,
        "roles": {"S": "starter-level, 28+ mpg", "R": "rotation, 18-28 mpg", "B": "bench, under 18 mpg"},
        "method": {
            "r": "Pearson on raw per-game stats over games both played",
            "phi": "Pearson on Over/Under hits at proxy lines (floor(season mean) + 0.5)",
            "shrunk": "phi shrunk in Fisher-z toward the league mean for the stat pair and role pairing",
            "r_close": "r over games decided by 12 or fewer",
        },
        "priors": res["priors"],
        "players": res["players"],
        "pairs": res["pairs"],
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"Wrote {args.out}: {len(games)} games, {len(res['players'])} players, "
          f"{len(res['pairs'])} ordered pairs, {n_ast} linked assists")
    for k, v in res["priors"].items():
        print(f"  {k}: league phi {v['league_phi']:+.3f}  r {v['league_r']:+.3f}  tau {v['tau']:.3f}  "
              + "  ".join(f"{c}:{d['phi']:+.3f}" for c, d in v["by_role"].items()))


if __name__ == "__main__":
    main()
