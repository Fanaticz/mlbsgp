#!/usr/bin/env python3
"""NHL skater game logs and same-player milestone correlations for the Novig
scanner's NHL tab (scan.py --league nhl) and the NHL correlations page.

Two files:
  public/data/nhl_game_logs.json     the history: one row per skater per game
  public/data/nhl_correlations.json  built from it: each skater's correlation
                                     for every pair of milestone legs

Where the games come from
-------------------------
History: MoneyPuck's bulk game-by-game skater files, one zip per season
(https://moneypuck.com/data.htm; free for non-commercial use, credit
MoneyPuck.com). Each game has one row per situation; only `situation == all`
is read, regular season only (gameId digits 5-6 == 02). Columns used:
I_F_goals, I_F_primaryAssists + I_F_secondaryAssists, I_F_shotsOnGoal,
shotsBlockedByPlayer, icetime (seconds).

  python3 scripts/nhl_fetch_correlations.py --moneypuck            # 2025-26 and 2026-27
  python3 scripts/nhl_fetch_correlations.py --moneypuck 2026       # one season

Nightly: ESPN box scores for games since the last run (the default, no flag).
The scoreboard for each day gives the completed regular-season events; each
event's summary gives every skater's line. Stats are read by ESPN's `keys`,
never by label: shots on goal is `shotsTotal` (label S); the label SOG is
shootout goals. Goalies, rows with no stats and 0:00 of ice time are skipped,
and a skater listed twice in one game is taken once.

  python3 scripts/nhl_fetch_correlations.py                        # new games, then rebuild
  python3 scripts/nhl_fetch_correlations.py --no-fetch             # rebuild from the history as it is

Joining the two
---------------
MoneyPuck carries NHL player ids, ESPN its own, so skaters are joined on name
(accents, periods and suffixes dropped) and, where two skaters share a name,
on forward / defence. An ESPN name with no match is tried against the skaters
last seen on that team with the same surname, initial and position ("Mitchell
Marner" meets "Mitch Marner"), and the alias is kept. Anyone still unmatched
is added as a new skater and printed, never dropped. A game is one row per
skater per date: a game both sources have is counted once (MoneyPuck's row
stays) and any stat the two disagree on is printed.

What the r values are
---------------------
Goals and assists are 0 most nights, so a correlation of the raw counts says
little about whether two milestone legs hit together. Each r here is fitted
to the legs themselves: for a pair of lines (1+ goal with 3+ shots on goal)
it is the Gaussian-copula correlation that reproduces how often the skater
hit both, given how often he hit each (the tetrachoric correlation of the two
hit / miss indicators). That is the number the scanner's joint formula takes
(sgp.joint), the same kind of r the NFL file carries for its touchdown pairs.
One r per pair of lines, for every line Novig lists.

Hits are compared with the skater's own rate that season, so a season in
which his role grew (more of everything) can't pass for a same-game
correlation. Games count with per-game weights by season (this season 1.0,
last season 0.7). Only games with at least 10 minutes of ice time count, and
a skater needs 40 of them.

Shrinkage: with 40-100 games one skater's r carries 0.10-0.25 of sampling
noise, so each is shrunk toward the average r of skaters at his position
(forwards, defencemen) for that pair of lines, empirical-Bayes style, with
the noise evaluated at that average, as the NFL script does.

Nested legs are left out: a goal is a point and a shot on goal, an assist is
a point, so 1+ goal with 1+ point (or with 1+ shot) is just the goal leg.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import os
import statistics
import sys
import unicodedata
import zipfile
from statistics import NormalDist
from zoneinfo import ZoneInfo

import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nba_fetch_correlations import get_json  # noqa: E402  GET with backoff

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "public", "data")
LOGS = os.path.join(DATA, "nhl_game_logs.json")
OUT = os.path.join(DATA, "nhl_correlations.json")

MONEYPUCK = "https://peter-tanner.com/moneypuck/downloads/seasonPlayersSummary/skaters/{season}.zip"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
ET = ZoneInfo("America/New_York")

# One code per team, whichever source it came from.
TEAM = {"LAK": "LA", "NJD": "NJ", "SJS": "SJ", "TBL": "TB", "UTAH": "UTA", "L.A": "LA", "N.J": "NJ",
        "S.J": "SJ", "T.B": "TB"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
# A game row: [date YYYYMMDD, team, goals, assists, shots on goal, blocked shots, ice time (s), source m/e]
D, TM, G, A, S, B, TOI, SRC = range(8)

MIN_TOI = 600        # seconds: a game counts with 10+ minutes of ice time
MIN_GAMES = 40       # such games a skater needs
SEASON_WEIGHT = {0: 1.0, 1: 0.7}   # seasons back -> per-game weight (older: 0.5)
MARGIN = (0.04, 0.96)              # a leg he hits less or more often than this has no r of his own
STATS = ("g", "ast", "pts", "sog", "blk")
# Over lines Novig lists (2.5 goals or assists is a longshot no skater's log can speak to).
LINES = {"g": (0.5, 1.5), "ast": (0.5, 1.5), "pts": (0.5, 1.5, 2.5),
         "sog": (0.5, 1.5, 2.5, 3.5, 4.5, 5.5), "blk": (0.5, 1.5, 2.5, 3.5)}
PAIRS = [(x, y) for i, x in enumerate(STATS) for y in STATS[i + 1:]]
# stat -> the stats it is part of: n goals are n points and n shots on goal.
PART_OF = {"g": ("pts", "sog"), "ast": ("pts",)}
SHRINK_TAU = (0.02, 0.12)   # floor, cap on the real spread between skaters
POOL_MIN = 15               # skaters a position needs for its own average
RHO_CLAMP = 0.98
ND = NormalDist()


def norm(name: str) -> str:
    """'Tim Stützle' / 'J.T. Miller' / 'Martin Fehérváry' -> 'timstutzle' / 'jtmiller' / 'martinfehervary'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = "".join(c if c.isalnum() or c == " " else " " for c in s.replace("'", "").replace(".", "")).split()
    return "".join(w for w in words if w not in SUFFIXES)


def surname(name: str) -> str:
    words = [w for w in norm_words(name) if w not in SUFFIXES]
    return words[-1] if words else ""


def norm_words(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return "".join(c if c.isalnum() or c == " " else " " for c in s.replace("'", "").replace(".", "")).split()


def nested(x: str, lx: float, y: str, ly: float) -> bool:
    """One leg forces the other: n+ goals with n+ (or fewer) points or shots."""
    return (y in PART_OF.get(x, ()) and ly <= lx) or (x in PART_OF.get(y, ()) and lx <= ly)


def season_of(date: int) -> int:
    """20261105 -> 2026 (the 2026-27 season), 20260411 -> 2025."""
    return date // 10000 if (date // 100) % 100 >= 8 else date // 10000 - 1


def group(pos: str) -> str:
    return "D" if pos.upper().startswith("D") else "F"


# --- the history file ----------------------------------------------------------

def load_logs() -> dict:
    if os.path.exists(LOGS):
        with open(LOGS, encoding="utf-8") as f:
            return json.load(f)
    return {"players": {}, "aliases": {}, "espn_events": [], "espn_through": None}


def save_logs(logs: dict) -> None:
    for p in logs["players"].values():
        p["games"].sort(key=lambda g: g[D])
    logs["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    logs["rows"] = "[date, team, goals, assists, shots on goal, blocked shots, ice time (s), source m=MoneyPuck e=ESPN]"
    logs["credit"] = "History: MoneyPuck.com. New games: ESPN box scores."
    os.makedirs(DATA, exist_ok=True)
    with open(LOGS, "w", encoding="utf-8") as f:
        json.dump(logs, f, separators=(",", ":"), sort_keys=True)


def by_name(logs: dict) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for key, p in logs["players"].items():
        idx.setdefault(key.split("|")[0], []).append(key)
    return idx


def put(p: dict, row: list) -> str:
    """Add a game to a skater, one row per date. MoneyPuck's row replaces
    ESPN's; an ESPN row never replaces anything. Returns 'new', 'same',
    'replaced' or 'differs: ...' (both sources have the game and disagree)."""
    for i, g in enumerate(p["games"]):
        if g[D] != row[D]:
            continue
        diff = [f"{n} {g[k]} vs {row[k]}" for k, n in ((G, "G"), (A, "A"), (S, "SOG"), (B, "BLK")) if g[k] != row[k]]
        if abs(g[TOI] - row[TOI]) > 5:
            diff.append(f"TOI {g[TOI]}s vs {row[TOI]}s")
        if row[SRC] == "m" and g[SRC] != "m":
            p["games"][i] = row
            return "differs: " + ", ".join(diff) if diff else "replaced"
        return "differs: " + ", ".join(diff) if diff and g[SRC] != row[SRC] else "same"
    p["games"].append(row)
    return "new"


# --- MoneyPuck -----------------------------------------------------------------

def moneypuck(logs: dict, seasons: list[int]) -> None:
    sess = requests.Session()
    sess.headers.update({"User-Agent": "mlbsgp-nhl-correlations (personal, non-commercial)"})
    idx = by_name(logs)
    for season in seasons:
        url = MONEYPUCK.format(season=season)
        print(f"MoneyPuck {season}: {url}", file=sys.stderr)
        r = sess.get(url, timeout=300)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        rows = new = 0
        with z.open(name) as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                if row["situation"] != "all" or row["gameId"][4:6] != "02":
                    continue
                toi = int(float(row["icetime"]))
                if toi <= 0:
                    continue
                key = f"{norm(row['name'])}|{group(row['position'])}"
                p = logs["players"].get(key)
                if p is None:
                    p = logs["players"][key] = {"name": row["name"], "pos": row["position"], "grp": group(row["position"]),
                                                "mp_id": row["playerId"], "espn_id": None, "espn_name": None, "games": []}
                    idx.setdefault(key.split("|")[0], []).append(key)
                elif p.get("mp_id") not in (None, row["playerId"]):
                    print(f"  two MoneyPuck skaters share {key}: ids {p['mp_id']} and {row['playerId']} (kept as one)",
                          file=sys.stderr)
                p["mp_id"], p["name"], p["pos"] = row["playerId"], row["name"], row["position"]
                game = [int(row["gameDate"]), TEAM.get(row["playerTeam"], row["playerTeam"]),
                        int(float(row["I_F_goals"])),
                        int(float(row["I_F_primaryAssists"])) + int(float(row["I_F_secondaryAssists"])),
                        int(float(row["I_F_shotsOnGoal"])), int(float(row["shotsBlockedByPlayer"])), toi, "m"]
                res = put(p, game)
                rows += 1
                new += res == "new"
                if res.startswith("differs"):
                    print(f"  {p['name']} {game[D]}: MoneyPuck replaces ESPN, {res}", file=sys.stderr)
        print(f"  {rows} skater-games read, {new} new", file=sys.stderr)
    logs.setdefault("moneypuck", {})["seasons"] = sorted(set(logs.get("moneypuck", {}).get("seasons", [])) | set(seasons))
    logs["moneypuck"]["through"] = max((g[D] for p in logs["players"].values() for g in p["games"] if g[SRC] == "m"),
                                       default=None)


# --- ESPN ----------------------------------------------------------------------

def seconds(text: str) -> int:
    try:
        m, s = text.split(":")
        return int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return 0


def box_rows(summary: dict) -> list[dict]:
    """Every skater's line in one ESPN summary: {id, name, pos, team, g, a,
    sog, blk, toi}. Indexed by `keys`; goalies, empty rows and 0:00 skipped;
    a skater listed in two groups is taken once."""
    out, seen = [], set()
    for team in (summary.get("boxscore") or {}).get("players") or []:
        abbr = (team.get("team") or {}).get("abbreviation") or ""
        abbr = TEAM.get(abbr, abbr)
        for grp in team.get("statistics") or []:
            if grp.get("name") == "goalies":
                continue
            keys = grp.get("keys") or []
            try:
                ix = {k: keys.index(k) for k in ("goals", "assists", "shotsTotal", "blockedShots", "timeOnIce")}
            except ValueError:
                continue
            for a in grp.get("athletes") or []:
                ath, stats = a.get("athlete") or {}, a.get("stats") or []
                aid = str(ath.get("id") or "")
                if not aid or aid in seen or len(stats) <= max(ix.values()):
                    continue
                toi = seconds(stats[ix["timeOnIce"]])
                if toi <= 0:
                    continue
                try:
                    vals = [int(stats[ix[k]]) for k in ("goals", "assists", "shotsTotal", "blockedShots")]
                except ValueError:
                    continue
                seen.add(aid)
                out.append({"id": aid, "name": ath.get("displayName") or f"athlete-{aid}",
                            "pos": (ath.get("position") or {}).get("abbreviation") or "F", "team": abbr,
                            "g": vals[0], "a": vals[1], "sog": vals[2], "blk": vals[3], "toi": toi})
    return out


def subseq(short: str, long: str) -> bool:
    it = iter(long)
    return all(c in it for c in short)


def match(logs: dict, idx: dict, by_espn: dict, row: dict, report: dict, create: bool = True) -> dict | None:
    """The history's skater for an ESPN row {id, name, pos, team}; a skater
    nobody matches is made (and reported) unless create is False."""
    if row["id"] in by_espn:
        return logs["players"][by_espn[row["id"]]]
    n, grp = norm(row["name"]), group(row["pos"])
    n = logs["aliases"].get(f"{n}|{grp}", n)
    keys = [k for k in idx.get(n, []) if logs["players"][k].get("espn_id") in (None, row["id"])]
    if len(keys) > 1:
        keys = [k for k in keys if k.endswith("|" + grp)]
    if not keys:
        # Same team and position under another spelling. MoneyPuck's files drop
        # accented letters outright ("Tim Sttzle", "Juraj Slafkovsk"), so first
        # a name that is ESPN's with up to three letters missing; then the same
        # surname and first initial ("Mitchell Marner" for "Mitch Marner").
        full = norm(row["name"])
        first = (norm_words(row["name"]) or [""])[0][:1]
        team = [k for k, p in logs["players"].items()
                if p.get("espn_id") is None and p["grp"] == grp and p["games"] and p["games"][-1][TM] == row["team"]]
        keys = [k for k in team if 0 < len(full) - len(k.split("|")[0]) <= 3 and k[:1] == full[:1]
                and subseq(k.split("|")[0], full)]
        if len(keys) != 1:
            keys = [k for k in team if surname(logs["players"][k]["name"]) == surname(row["name"])
                    and (norm_words(logs["players"][k]["name"]) or [""])[0][:1] == first]
        if len(keys) == 1:
            logs["aliases"][f"{full}|{grp}"] = keys[0].split("|")[0]
            report["alias"].append(f"{row['name']} ({row['team']}) = {logs['players'][keys[0]]['name']}")
        else:
            keys = []
    if len(keys) == 1:
        p = logs["players"][keys[0]]
        if create and p["games"] and p["games"][-1][TM] != row["team"] and p.get("espn_id") is None:
            report["moved"].append(f"{row['name']}: {p['games'][-1][TM]} in the history, {row['team']} on ESPN")
    elif not create:
        return None
    else:
        key = f"{norm(row['name'])}|{grp}"
        while key in logs["players"]:   # a second skater of that name and position
            key = key.replace("|", "2|", 1) if "2|" not in key else key.replace("2|", "3|", 1)
        p = logs["players"][key] = {"name": row["name"], "pos": row["pos"], "grp": grp, "mp_id": None,
                                    "espn_id": None, "espn_name": None, "games": []}
        idx.setdefault(key.split("|")[0], []).append(key)
        keys = [key]
        report["unmatched"].append(f"{row['name']} ({row['pos']}, {row['team']}, ESPN id {row['id']})")
    p["espn_id"], p["espn_name"] = row["id"], row["name"]
    by_espn[row["id"]] = keys[0]
    return p


def rosters(sess: requests.Session, logs: dict, idx: dict, by_espn: dict, report: dict) -> None:
    """Today's rosters: ESPN's id and spelling for skaters already in the
    history (so Novig's names find them before their next game), and each
    skater's current team."""
    data = get_json(sess, f"{ESPN}/teams?limit=50") or {}
    try:
        teams = data["sports"][0]["leagues"][0]["teams"]
    except (KeyError, IndexError, TypeError):
        return
    for t in teams:
        tm = t.get("team") or {}
        abbr = TEAM.get(tm.get("abbreviation") or "", tm.get("abbreviation") or "")
        logs.setdefault("teams", {})[abbr] = tm.get("displayName") or abbr
        rd = get_json(sess, f"{ESPN}/teams/{tm.get('id')}/roster") or {}
        for grp in rd.get("athletes") or []:
            for a in grp.get("items") or []:
                pos = (a.get("position") or {}).get("abbreviation") or ""
                aid = str(a.get("id") or "")
                if not aid or not pos or pos == "G":
                    continue
                p = match(logs, idx, by_espn, {"id": aid, "name": a.get("displayName") or "", "pos": pos, "team": abbr},
                          report, create=False)
                if p is not None:
                    p["team"] = abbr


def note_scores(logs: dict, events: list) -> int:
    """Final scores of completed games into logs['scores'][date][team] =
    [goals for, goals against] (a shootout win counts one goal, as totals
    are settled). Dates are US Eastern, teams in the history's codes."""
    n = 0
    for e in events:
        if not ((e.get("status") or {}).get("type") or {}).get("completed"):
            continue
        try:
            comp = e["competitions"][0]["competitors"]
            (ta, sa), (tb, sb) = ((TEAM.get(c["team"]["abbreviation"], c["team"]["abbreviation"]), int(c["score"]))
                                  for c in comp)
        except (KeyError, IndexError, ValueError, TypeError):
            continue
        date = dt.datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(ET).strftime("%Y%m%d")
        day = logs.setdefault("scores", {}).setdefault(date, {})
        n += ta not in day
        day[ta], day[tb] = [sa, sb], [sb, sa]
    return n


def backfill_scores(logs: dict) -> None:
    """Scores for every game date in the history that has none yet (one
    scoreboard request a date; a first run reads about 230)."""
    import concurrent.futures as cf
    have = logs.get("scores") or {}
    want = sorted({str(g[D]) for p in logs["players"].values() for g in p["games"]} - set(have))
    if not want:
        return
    sess = requests.Session()
    sess.headers.update({"User-Agent": "mlbsgp-nhl-correlations"})
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        boards = list(ex.map(lambda ds: get_json(sess, f"{ESPN}/scoreboard?dates={ds}&limit=100"), want))
    n = sum(note_scores(logs, [e for e in (sb or {}).get("events") or [] if (e.get("season") or {}).get("type") == 2])
            for sb in boards)
    print(f"Scores: {n} games on {len(want)} dates ({sum(b is None for b in boards)} dates failed)", file=sys.stderr)


def espn(logs: dict, since: str | None, until: str | None) -> dict:
    """Add every completed regular-season game from `since` to `until`
    (YYYYMMDD, US Eastern dates) that the history hasn't read yet."""
    sess = requests.Session()
    sess.headers.update({"User-Agent": "mlbsgp-nhl-correlations"})
    today = dt.datetime.now(ET).date()
    if since:
        start = dt.datetime.strptime(since, "%Y%m%d").date()
    elif logs.get("espn_through"):
        start = dt.datetime.strptime(str(logs["espn_through"]), "%Y%m%d").date() - dt.timedelta(days=2)
    else:
        # First run after a MoneyPuck seed: start three days inside it, so the
        # two sources are checked against each other on the overlap.
        last = max((g[D] for p in logs["players"].values() for g in p["games"]), default=None)
        if last is None:
            sys.exit("No history yet: run with --moneypuck first.")
        start = dt.datetime.strptime(str(last), "%Y%m%d").date() - dt.timedelta(days=2)
    end = dt.datetime.strptime(until, "%Y%m%d").date() if until else today
    done = set(logs.get("espn_events") or [])
    idx = by_name(logs)
    by_espn = {p["espn_id"]: k for k, p in logs["players"].items() if p.get("espn_id")}
    report = {"games": 0, "rows": 0, "new": 0, "same": 0, "differs": [], "alias": [], "moved": [], "unmatched": [],
              "failed": []}
    rosters(sess, logs, idx, by_espn, report)
    day, through = start, logs.get("espn_through")
    while day <= end:
        ds = day.strftime("%Y%m%d")
        sb = get_json(sess, f"{ESPN}/scoreboard?dates={ds}&limit=100")
        if sb is None:
            report["failed"].append(f"scoreboard {ds}")
            break   # stop here: the next run starts from the last day read
        events = [e for e in sb.get("events") or [] if (e.get("season") or {}).get("type") == 2]
        note_scores(logs, events)
        pending = False
        for e in events:
            if not ((e.get("status") or {}).get("type") or {}).get("completed"):
                pending = True
                continue
            eid = str(e["id"])
            if eid in done:
                continue
            summary = get_json(sess, f"{ESPN}/summary?event={eid}")
            rows = box_rows(summary or {})
            if not rows:
                report["failed"].append(f"event {eid} ({e.get('shortName')})")
                pending = True
                continue
            when = dt.datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(ET)
            date = int(when.strftime("%Y%m%d"))
            for row in rows:
                p = match(logs, idx, by_espn, row, report)
                res = put(p, [date, row["team"], row["g"], row["a"], row["sog"], row["blk"], row["toi"], "e"])
                report["rows"] += 1
                report["new"] += res == "new"
                report["same"] += res == "same"
                if res.startswith("differs"):
                    report["differs"].append(f"{row['name']} {date} ({row['team']}): history vs ESPN, {res[9:]}")
            done.add(eid)
            report["games"] += 1
        # A day is finished once every game on it is read; today never is.
        if not pending and day < today:
            through = int(ds)
        elif pending:
            report["pending"] = ds
        day += dt.timedelta(days=1)
    logs["espn_events"] = sorted(done)
    logs["espn_through"] = through
    return report


# --- correlations --------------------------------------------------------------

_GL_X, _GL_W = np.polynomial.legendre.leggauss(32)


def phi2(h, k, rho):
    """Bivariate normal density at (h, k)."""
    q = 1 - rho * rho
    return np.exp(-(h * h - 2 * rho * h * k + k * k) / (2 * q)) / (2 * np.pi * np.sqrt(q))


def both(p1, p2, rho):
    """P(both legs hit) under a Gaussian copula: p1 p2 + the integral of the
    bivariate density from 0 to rho (Plackett), as sgp.joint does."""
    h, k = (np.array([ND.inv_cdf(float(x)) for x in np.ravel(p)]).reshape(np.shape(p)) for p in (p1, p2))
    return _both(h, k, np.asarray(p1), np.asarray(p2), np.asarray(rho))


def _both(h, k, p1, p2, rho):
    t = 0.5 * rho[..., None] * (_GL_X + 1)
    return p1 * p2 + (phi2(h[..., None], k[..., None], t) * _GL_W).sum(-1) * 0.5 * rho


def tetrachoric(p1, p2, p11):
    """The copula r that gives P(both) = p11 at hit rates p1, p2 (arrays)."""
    p1, p2, p11 = (np.asarray(x, dtype=float) for x in (p1, p2, p11))
    h = np.array([ND.inv_cdf(x) for x in p1])
    k = np.array([ND.inv_cdf(x) for x in p2])
    lo, hi = np.full(p1.shape, -RHO_CLAMP), np.full(p1.shape, RHO_CLAMP)
    for _ in range(40):
        mid = (lo + hi) / 2
        low = _both(h, k, p1, p2, mid) < p11
        lo, hi = np.where(low, mid, lo), np.where(low, hi, mid)
    return (lo + hi) / 2


def noise(p1: float, p2: float, rho: float, neff: float) -> float:
    """Sampling variance of a tetrachoric r from neff games, at copula r `rho`:
    the variance of the both-hit share with the two hit rates held (1 / (n x
    the sum of the four cells' reciprocals)) over the density squared."""
    h, k = ND.inv_cdf(p1), ND.inv_cdf(p2)
    p11 = float(_both(np.array(h), np.array(k), np.array(p1), np.array(p2), np.array(rho)))
    cells = [max(c, 1e-6) for c in (p11, p1 - p11, p2 - p11, 1 - p1 - p2 + p11)]
    return 1 / (neff * sum(1 / c for c in cells)) / float(phi2(h, k, rho)) ** 2


def estimates(games: list[list], this_season: int) -> tuple[dict, float]:
    """{(x, y, lx, ly): (p1, p2, r)} for one skater's qualifying games, and
    his Kish effective n. Hits are centred on his own rate that season."""
    w = np.array([SEASON_WEIGHT.get(this_season - season_of(g[D]), 0.5) for g in games])
    seasons = np.array([season_of(g[D]) for g in games])
    cols = {"g": np.array([g[G] for g in games]), "ast": np.array([g[A] for g in games]),
            "sog": np.array([g[S] for g in games]), "blk": np.array([g[B] for g in games])}
    cols["pts"] = cols["g"] + cols["ast"]
    hit, rate, cen = {}, {}, {}
    for s in STATS:
        for line in LINES[s]:
            x = (cols[s] > line).astype(float)
            hit[s, line] = x
            rate[s, line] = float((w * x).sum() / w.sum())
            c = x.copy()
            for yr in set(seasons.tolist()):
                m = seasons == yr
                c[m] -= x[m].mean()
            cen[s, line] = c
    keys, p1s, p2s, p11s = [], [], [], []
    for x, y in PAIRS:
        for lx in LINES[x]:
            for ly in LINES[y]:
                p1, p2 = rate[x, lx], rate[y, ly]
                if nested(x, lx, y, ly) or not (MARGIN[0] <= p1 <= MARGIN[1] and MARGIN[0] <= p2 <= MARGIN[1]):
                    continue
                p11 = p1 * p2 + float((w * cen[x, lx] * cen[y, ly]).sum() / w.sum())
                lo, hi = max(0.0, p1 + p2 - 1), min(p1, p2)
                eps = 0.25 / len(games)   # never both / always both: a quarter of a game, not a certainty
                keys.append((x, y, lx, ly))
                p1s.append(p1); p2s.append(p2); p11s.append(min(max(p11, lo + eps), hi - eps))
    if not keys:
        return {}, 0.0
    rs = tetrachoric(p1s, p2s, p11s)
    return ({k: (a, b, float(r)) for k, a, b, r in zip(keys, p1s, p2s, rs)},
            float(w.sum() ** 2 / (w * w).sum()))


def shrink(players: list[dict]) -> dict:
    """Empirical-Bayes shrink of each skater's r toward the average of his
    position for that pair of lines; fills p['pairs'] and returns the priors."""
    priors: dict = {}
    combos = sorted({k for p in players for k in p["_est"]})
    for grp in ("F", "D"):
        members = [p for p in players if p["grp"] == grp]
        for key in combos:
            pool = [(p["_est"][key], p["_neff"]) for p in members if key in p["_est"]]
            src = grp
            if len(pool) < POOL_MIN:
                pool = [(p["_est"][key], p["_neff"]) for p in players if key in p["_est"]]
                src = "ALL"
            if len(pool) < POOL_MIN:
                continue
            m = statistics.mean(e[2] for e, _ in pool)
            tau2 = SHRINK_TAU[0] ** 2
            for _ in range(30):
                v = [noise(e[0], e[1], m, n) for e, n in pool]
                spread = statistics.mean((e[2] - m) ** 2 for e, _ in pool)
                tau2 = min(max(spread - statistics.mean(v), SHRINK_TAU[0] ** 2), SHRINK_TAU[1] ** 2)
                wts = [1 / (tau2 + x) for x in v]
                m_new = sum(wt * e[2] for wt, (e, _) in zip(wts, pool)) / sum(wts)
                if abs(m_new - m) < 1e-6:
                    break
                m = m_new
            x, y, lx, ly = key
            priors.setdefault(grp, {}).setdefault(f"{x}_{y}", {})[f"{lx}|{ly}"] = {
                "r": round(m, 4), "tau": round(math.sqrt(tau2), 4), "pool_n": len(pool), "pool": src}
            for p in members:
                if key not in p["_est"]:
                    continue
                p1, p2, r = p["_est"][key]
                wt = tau2 / (tau2 + noise(p1, p2, m, p["_neff"]))
                # [shrunk r, his own r, weight on his own, his hit rate on each leg]
                p["pairs"].setdefault(f"{x}_{y}", {})[f"{lx}|{ly}"] = [
                    round(wt * r + (1 - wt) * m, 4), round(r, 3), round(wt, 3), round(p1, 3), round(p2, 3)]
    return priors


def build(logs: dict) -> dict:
    last = max((g[D] for p in logs["players"].values() for g in p["games"]), default=None)
    if last is None:
        sys.exit("No games in the history; refusing to overwrite the data file.")
    this_season = season_of(last)
    players = []
    for key, p in logs["players"].items():
        games = [g for g in p["games"] if g[TOI] >= MIN_TOI]
        if len(games) < MIN_GAMES:
            continue
        est, neff = estimates(games, this_season)
        n = len(games)
        by_season: dict[str, int] = {}
        for g in games:
            by_season[str(season_of(g[D]))] = by_season.get(str(season_of(g[D])), 0) + 1
        players.append({
            "athlete_id": p.get("espn_id") or f"mp{p.get('mp_id')}", "key": key,
            # ESPN's spelling when there is one: MoneyPuck's files drop accented letters.
            "name": p.get("espn_name") or p["name"], "position": p["pos"], "grp": p["grp"],
            "team_abbr": p.get("team") or p["games"][-1][TM], "last_game": p["games"][-1][D],
            "n_games": n, "effective_n": round(neff, 1), "games_by_season": by_season,
            "toi_mean": round(sum(g[TOI] for g in games) / n / 60, 1),
            "g_mean": round(sum(g[G] for g in games) / n, 3), "ast_mean": round(sum(g[A] for g in games) / n, 3),
            "pts_mean": round(sum(g[G] + g[A] for g in games) / n, 3),
            "sog_mean": round(sum(g[S] for g in games) / n, 2), "blk_mean": round(sum(g[B] for g in games) / n, 2),
            "pairs": {}, "_est": est, "_neff": neff})
    if not players:
        sys.exit(f"No skater with {MIN_GAMES} games; refusing to overwrite the data file.")
    priors = shrink(players)
    for p in players:
        del p["_est"], p["_neff"]
    players.sort(key=lambda p: p["name"].lower())
    seasons = sorted({season_of(g[D]) for p in logs["players"].values() for g in p["games"]})
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "MoneyPuck.com game-by-game skater files; ESPN box scores for new games",
        "credit": "Data: MoneyPuck.com",
        "seasons": seasons, "through": last,
        "scope": f"regular-season games with {MIN_TOI // 60}+ minutes of ice time; skaters with {MIN_GAMES}+ of them",
        "weighting": {"per_game_season_weights": {str(this_season - back): wt for back, wt in SEASON_WEIGHT.items()},
                      "r": "Gaussian-copula (tetrachoric) correlation of the two legs' hit / miss indicators at "
                           "those exact lines, hits centred on the skater's own rate each season",
                      "pair_values": "[shrunk r, own r, weight on own, hit rate leg 1, hit rate leg 2]"},
        "lines": {s: list(v) for s, v in LINES.items()},
        "shrinkage": {"method": "empirical Bayes toward the position's average r for the same pair of lines; "
                                f"noise evaluated at that average; tau held to {SHRINK_TAU[0]}-{SHRINK_TAU[1]}",
                      "priors": priors},
        "n_players": len(players),
        "total_game_rows": sum(p["n_games"] for p in players),
        "players": players,
    }


# --- teammates -----------------------------------------------------------------

MATE_OUT = os.path.join(DATA, "nhl_teammate_correlations.json")
# (first skater's stat, his teammate's stat): the lines read for each.
MATE_KINDS = (("pts", "pts"), ("g", "pts"), ("g", "ast"), ("ast", "ast"), ("sog", "pts"), ("sog", "ast"), ("sog", "sog"))
MATE_LINES = {"pts": (0.5, 1.5), "g": (0.5,), "ast": (0.5,), "sog": (1.5, 2.5, 3.5)}
MATE_OWN = {"pts_pts", "g_pts", "g_ast", "ast_ast"}     # kinds where pairs really differ; the shots kinds are the average for everyone
MATE_MARGIN = (0.10, 0.90)
MATE_TAU = (0.02, 0.15)
MATE_BINS = 3


def _interp(knots: list, x: float) -> float:
    if x <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return knots[-1][1]


def build_teammates(logs: dict, this_season: int) -> dict:
    """Two teammates' legs in the same game: skater A's points, goal or shots
    with skater B's points or shots. Same r as build(): the copula correlation
    of the two legs' hit / miss record at exact lines, over the games both
    played 10+ minutes for the same team, hits centred on each skater's rate
    that season. Shrunk toward the average for the two positions at the
    pair's ice time (the lower of the two averages: first-line skaters share
    more of the same goals), since box scores don't say who skates together.
    Pairs on the same team today with 40+ shared games get their own r."""
    by_game: dict = {}
    for key, p in logs["players"].items():
        for g in p["games"]:
            if g[TOI] >= MIN_TOI:
                by_game.setdefault((g[D], g[TM]), []).append((key, g))
    shared: dict = {}
    for rows in by_game.values():
        for ka, ga in rows:
            for kb, gb in rows:
                if ka != kb:
                    shared.setdefault((ka, kb), []).append((ga, gb))
    P = logs["players"]
    now = {k: p.get("team") or p["games"][-1][TM] for k, p in P.items() if p["games"]}

    def val(g, s):
        return g[G] + g[A] if s == "pts" else g[S] if s == "sog" else g[A] if s == "ast" else g[G]

    est: dict = {}   # (kind, lines, groups) -> [(pair, p1, p2, r, neff, cov)]
    for (ka, kb), v in shared.items():
        if len(v) < MIN_GAMES:
            continue
        w = np.array([SEASON_WEIGHT.get(this_season - season_of(ga[D]), 0.5) for ga, _ in v])
        yrs = np.array([season_of(ga[D]) for ga, _ in v])
        neff = float(w.sum() ** 2 / (w * w).sum())
        cov = min(sum(ga[TOI] for ga, _ in v), sum(gb[TOI] for _, gb in v)) / len(v) / 60
        cache: dict = {}

        def leg(i, s, line):
            if (i, s, line) not in cache:
                x = np.array([val(r[i], s) > line for r in v], dtype=float)
                c = x.copy()
                for yr in set(yrs.tolist()):
                    m = yrs == yr
                    c[m] -= x[m].mean()
                cache[i, s, line] = (float((w * x).sum() / w.sum()), c)
            return cache[i, s, line]
        for x, y in MATE_KINDS:
            for lx in MATE_LINES[x]:
                for ly in MATE_LINES[y]:
                    (p1, c1), (p2, c2) = leg(0, x, lx), leg(1, y, ly)
                    if not (MATE_MARGIN[0] <= p1 <= MATE_MARGIN[1] and MATE_MARGIN[0] <= p2 <= MATE_MARGIN[1]):
                        continue
                    p11 = p1 * p2 + float((w * c1 * c2).sum() / w.sum())
                    eps = 0.25 / len(v)
                    p11 = min(max(p11, max(0.0, p1 + p2 - 1) + eps), min(p1, p2) - eps)
                    est.setdefault((f"{x}_{y}", f"{lx}|{ly}", P[ka]["grp"] + P[kb]["grp"]), []).append(
                        [(ka, kb), p1, p2, p11, neff, cov, len(v)])
    priors: dict = {}
    pairs: dict = {}
    for (kind, lines, grps), pool in sorted(est.items()):
        if len(pool) < 3 * POOL_MIN:
            continue
        rs = tetrachoric([e[1] for e in pool], [e[2] for e in pool], [e[3] for e in pool])
        for e, r in zip(pool, rs):
            e[3] = float(r)
        pool.sort(key=lambda e: e[5])
        knots = []
        for i in range(MATE_BINS):
            b = pool[i * len(pool) // MATE_BINS:(i + 1) * len(pool) // MATE_BINS]
            knots.append((round(b[len(b) // 2][5], 2), round(statistics.mean(e[3] for e in b), 4)))
        v = [noise(e[1], e[2], _interp(knots, e[5]), e[4]) for e in pool]
        spread = statistics.mean((e[3] - _interp(knots, e[5])) ** 2 for e in pool)
        tau2 = min(max(spread - statistics.mean(v), MATE_TAU[0] ** 2), MATE_TAU[1] ** 2)
        priors.setdefault(grps, {}).setdefault(kind, {})[lines] = {
            "knots": knots, "tau": round(math.sqrt(tau2), 4), "pool_n": len(pool)}
        if kind not in MATE_OWN:
            continue
        for e, nz in zip(pool, v):
            ka, kb = e[0]
            if now.get(ka) != now.get(kb):
                continue   # no longer teammates
            m = _interp(knots, e[5])
            wt = tau2 / (tau2 + nz)
            # [shrunk r, own r, weight on own, hit rate leg 1, hit rate leg 2]
            pairs.setdefault(f"{ka}>{kb}", {"n": e[6], "toi": round(e[5], 1)}).setdefault(kind, {})[lines] = [
                round(wt * e[3] + (1 - wt) * m, 4), round(e[3], 3), round(wt, 3), round(e[1], 3), round(e[2], 3)]
    names = {k: {"name": P[k].get("espn_name") or P[k]["name"], "team": now[k], "grp": P[k]["grp"], "pos": P[k]["pos"]}
             for pk in pairs for k in pk.split(">")}
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "credit": "Data: MoneyPuck.com",
        "scope": f"two skaters on the same team today, {MIN_GAMES}+ games together of {MIN_TOI // 60}+ minutes each",
        "kinds": {"pts_pts": "A's points with B's points", "g_pts": "A's goal with B's points",
                  "g_ast": "A's goal with B's assists", "ast_ast": "A's assists with B's",
                  "sog_ast": "A's shots on goal with B's assists",
                  "sog_pts": "A's shots on goal with B's points", "sog_sog": "A's shots on goal with B's"},
        "pair_values": "[shrunk r, own r, weight on own, hit rate leg 1, hit rate leg 2]; key 'A>B', lines 'A's|B's'",
        "priors": {"by": "the two positions (A's then B's), then the lower of the two skaters' average ice time "
                         "(minutes): knots are (ice time, r)", "values": priors},
        "skaters": names, "n_pairs": len(pairs), "pairs": pairs,
    }


# --- game lines ----------------------------------------------------------------

LINE_OUT = os.path.join(DATA, "nhl_line_correlations.json")
LINE_STATS = {"pts": (0.5, 1.5), "g": (0.5,), "ast": (0.5,), "sog": (1.5, 2.5, 3.5)}
# A game-line outcome, from his team's side: win (overtime and shootout
# included, as the moneyline is), the puck line both ways, the game total and
# his team's total.
LINE_EVENTS = ([("win", None, lambda f, a: f > a), ("m15", None, lambda f, a: f - a >= 2),
                ("p15", None, lambda f, a: f - a >= -1)]
               + [("over", L, (lambda L: lambda f, a: f + a > L)(L)) for L in (4.5, 5.5, 6.5, 7.5)]
               + [("tt", L, (lambda L: lambda f, a: f > L)(L)) for L in (1.5, 2.5, 3.5, 4.5)])
LINE_MIN_GAMES = 20
LINE_BINS = 3


def build_lines(logs: dict) -> dict:
    """A skater's leg with a game line: league-wide r by role (forwards and
    defencemen, each in thirds by average ice time), as the NFL file does by
    position and volume. Every game of 10+ minutes with a final score; the
    leg's hit and the line's outcome are each centred on that skater's rate
    that season (his team's, for the line), so a good team's season of wins
    and points can't pass for a same-game correlation. Thresholds are the raw
    result (won, won by 2+, more than 5.5 goals), not against a closing line."""
    scores = logs.get("scores") or {}
    roles: dict = {"F": [], "D": []}
    for p in logs["players"].values():
        games = [(g, scores.get(str(g[D]), {}).get(g[TM])) for g in p["games"] if g[TOI] >= MIN_TOI]
        games = [(g, sc) for g, sc in games if sc]
        if len(games) >= LINE_MIN_GAMES:
            roles[p["grp"]].append((sum(g[TOI] for g, _ in games) / len(games) / 60, games))
    table = []
    for grp, members in roles.items():
        members.sort(key=lambda m: m[0])
        for b in range(LINE_BINS):
            part = members[b * len(members) // LINE_BINS:(b + 1) * len(members) // LINE_BINS]
            if not part:
                continue
            lo = part[0][0] if b else 0.0
            hi = members[(b + 1) * len(members) // LINE_BINS][0] if b < LINE_BINS - 1 else None
            cols: dict = {}
            for _, games in part:
                yrs = np.array([season_of(g[D]) for g, _ in games])
                f = np.array([sc[0] for _, sc in games]); a = np.array([sc[1] for _, sc in games])
                vals = {"g": np.array([g[G] for g, _ in games]), "ast": np.array([g[A] for g, _ in games]),
                        "sog": np.array([g[S] for g, _ in games])}
                vals["pts"] = vals["g"] + vals["ast"]

                def cen(x):
                    c = x.astype(float)
                    for yr in set(yrs.tolist()):
                        m = yrs == yr
                        c[m] -= c[m].mean()
                    return c
                legs = {(s, ln): vals[s] > ln for s, lns in LINE_STATS.items() for ln in lns}
                evs = {(n, L): fn(f, a) for n, L, fn in LINE_EVENTS}
                cl = {k: cen(v) for k, v in legs.items()}
                ce = {k: cen(v) for k, v in evs.items()}
                for lk in legs:
                    for ek in evs:
                        c = cols.setdefault((lk, ek), [0.0, 0.0, 0.0, 0])
                        c[0] += legs[lk].sum(); c[1] += evs[ek].sum(); c[2] += float((cl[lk] * ce[ek]).sum()); c[3] += len(games)
            for ((s, ln), (ev, L)), (h1, h2, cov, n) in cols.items():
                p1, p2 = h1 / n, h2 / n
                if not (0.03 <= p1 <= 0.97 and 0.03 <= p2 <= 0.97):
                    continue
                r = float(tetrachoric([p1], [p2], [p1 * p2 + cov / n])[0])
                table.append({"grp": grp, "min": round(lo, 2), "max": None if hi is None else round(hi, 2),
                              "stat": s, "line": ln, "ev": ev, "strike": L, "r": round(r, 4), "n": n,
                              "p_leg": round(p1, 3), "p_ev": round(p2, 3)})
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "credit": "Data: MoneyPuck.com; scores from ESPN",
        "scope": f"games of {MIN_TOI // 60}+ minutes with a final score, skaters with {LINE_MIN_GAMES}+ of them; "
                 "league-wide by position and ice time (minutes, min <= his average < max)",
        "events": {"win": "his team wins (overtime and shootout included)", "m15": "his team wins by 2 or more (-1.5)",
                   "p15": "his team wins or loses by 1 (+1.5)", "over": "game total over the strike",
                   "tt": "his team's goals over the strike"},
        "teams": logs.get("teams") or {},
        "game": table,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--moneypuck", type=int, nargs="*", default=None, metavar="SEASON",
                    help="load MoneyPuck's season files into the history (default seasons: 2025 2026) "
                         "instead of reading ESPN")
    ap.add_argument("--no-fetch", action="store_true", help="rebuild the correlations from the history as it is")
    ap.add_argument("--since", help="ESPN: first date to read, YYYYMMDD (default: two days before the last day read)")
    ap.add_argument("--until", help="ESPN: last date to read, YYYYMMDD (default: today)")
    ap.add_argument("--check", metavar="NAME", help="print this skater's game log from the history and stop")
    a = ap.parse_args()

    logs = load_logs()
    if a.check:
        want = norm(a.check)
        for key, p in logs["players"].items():
            if want in key.split("|")[0]:
                print(f"{p['name']} ({p['pos']}) · MoneyPuck {p.get('mp_id')} · ESPN {p.get('espn_id')} {p.get('espn_name') or ''}")
                for g in p["games"][-25:]:
                    print(f"  {g[D]} {g[TM]:<4} G {g[G]} A {g[A]} SOG {g[S]} BLK {g[B]} TOI {g[TOI] // 60}:{g[TOI] % 60:02d} {g[SRC]}")
        return
    if a.moneypuck is not None:
        moneypuck(logs, a.moneypuck or [2025, 2026])
        save_logs(logs)
    elif not a.no_fetch:
        rep = espn(logs, a.since, a.until)
        backfill_scores(logs)
        save_logs(logs)
        print(f"ESPN: {rep['games']} games, {rep['rows']} skater rows: {rep['new']} new, {rep['same']} already in the "
              f"history and equal, {len(rep['differs'])} that differ", file=sys.stderr)
        for label, k in (("differs", "differs"), ("matched under another name", "alias"),
                         ("changed team", "moved"), ("UNMATCHED, added as new", "unmatched"), ("failed", "failed")):
            for line in rep[k]:
                print(f"  {label}: {line}", file=sys.stderr)
    out = build(logs)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    lines = build_lines(logs)
    with open(LINE_OUT, "w", encoding="utf-8") as f:
        json.dump(lines, f, separators=(",", ":"))
    print(f"NHL game lines: {len(lines['game'])} role r's")
    for grp in ("F", "D"):
        top = [e for e in lines["game"] if e["grp"] == grp and e["max"] is None and e["stat"] == "pts" and e["line"] == 0.5]
        print(f"  {grp}, most ice time, 1+ point: " + "  ".join(
            f"{e['ev']}{'' if e['strike'] is None else ' ' + format(e['strike'], 'g')} {e['r']:+.2f}" for e in top))
    mates = build_teammates(logs, season_of(out["through"]))
    with open(MATE_OUT, "w", encoding="utf-8") as f:
        json.dump(mates, f, separators=(",", ":"))
    mp = mates["priors"]["values"]
    print(f"NHL teammates: {mates['n_pairs']} ordered pairs with their own r")
    for grps in ("FF", "FD", "DF", "DD"):
        print(f"  {grps}: " + "  ".join(
            f"{k} {ln} " + "/".join(f"{r:+.2f}" for _, r in mp[grps][k][ln]["knots"]) + f" (tau {mp[grps][k][ln]['tau']:.2f})"
            for k, ln in (("pts_pts", "0.5|0.5"), ("g_ast", "0.5|0.5"), ("ast_ast", "0.5|0.5"), ("sog_pts", "2.5|0.5"))
            if ln in mp.get(grps, {}).get(k, {})))
    pri = out["shrinkage"]["priors"]
    print(f"NHL correlations: {out['n_players']} skaters with {MIN_GAMES}+ games, through {out['through']}")
    show = (("g_sog", "0.5|2.5"), ("g_ast", "0.5|0.5"), ("g_pts", "0.5|1.5"), ("ast_pts", "0.5|1.5"),
            ("ast_sog", "0.5|2.5"), ("pts_sog", "0.5|2.5"), ("g_blk", "0.5|0.5"), ("sog_blk", "2.5|0.5"))
    for grp in ("F", "D"):
        print(f"  {grp}: " + "  ".join(f"{k} {ln} {pri[grp][k][ln]['r']:+.2f} (tau {pri[grp][k][ln]['tau']:.2f})"
                                       for k, ln in show if ln in pri.get(grp, {}).get(k, {})))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
