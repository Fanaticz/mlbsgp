#!/usr/bin/env python3
"""First-dunk model for the NBA (who makes the first dunk of a game).

Two files in public/data/:

  nba_dunk_games.json   one slim row per final regular-season game, from
                        ESPN's play-by-play: who started, who played how long,
                        every made dunk with its time, and who was on the
                        floor in each of the first 24 minutes.
  nba_first_dunk.json   what the page (public/nba_dunk.html) prices from:
                        each player's dunks per minute, when he is usually on
                        the floor as a starter and off the bench, each team's
                        dunks allowed, and how the league's dunk rate moves
                        through a game.

The model is a race. While he is on the floor a player dunks at his own rate
(made dunks per 100 of his team's possessions with him on the floor, recent
seasons weighted most, shrunk toward his position's average), times the
matchup's pace, scaled by how many dunks the other team allows and by the
league's rate at that point of the game. The first dunk goes to player i in minute k with probability

    (no dunk before k) x (a dunk in k) x (i's share of the rates in k)

summed over the game. FirstDunk.price in public/utils/firstDunk.js is the
same arithmetic as price() here; scripts/nba_first_dunk_check.js holds the
two together.

  python3 scripts/nba_first_dunk.py --fetch          # new finals, then rebuild
  python3 scripts/nba_first_dunk.py                  # rebuild from the games file
  python3 scripts/nba_first_dunk.py --backtest       # walk-forward check
  python3 scripts/nba_first_dunk.py --tune           # grid search on log loss
  python3 scripts/nba_first_dunk.py --mc             # Monte Carlo against the closed form
  python3 scripts/nba_first_dunk.py --price NY TOR   # tonight's table for one game
  python3 scripts/nba_first_dunk.py --fixture        # scripts/fixtures/first_dunk_case.json

Seasons use ESPN's convention (2027 = the 2026-27 season).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAMES = os.path.join(ROOT, "public", "data", "nba_dunk_games.json")
OUT = os.path.join(ROOT, "public", "data", "nba_first_dunk.json")
FIXTURE = os.path.join(HERE, "fixtures", "first_dunk_case.json")
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={}"

CURVE_MIN = 24        # minutes of the game with a per-minute on-floor curve
GAME_MIN = 48
EARLY_MIN = 6         # the opening stretch the starters play (team early-speed factor)
# Fitted on the walk-forward backtest (--tune); see CHANGES.md.
PARAMS = {
    "prior_poss": 100.0,  # possessions of his position's average rate mixed into a player's
    "w1": 0.3,            # weight of last season
    "w2": 0.0,            # weight of the season before
    "curve_k": 8.0,       # games of the league's on-floor curve mixed into a player's
    "team_k": 40.0,       # games of league average mixed into a team's pace, dunks allowed, turnovers
    "gamma": 1.1,         # >1 leans a minute's dunks toward its biggest dunkers
    "to_pow": 0.0,        # power on the other team's live-ball turnover rate
    "off_pow": 0.0,       # power on the team's dunks over what its players' rates expect
    "early_pow": 0.0,     # power on the team's opening-six-minutes dunks over expected
    "tip_pow": 0.0,       # opening-minute bump for the team likelier to win the tip
    "home": 0.06,         # the home team's rates up by this share, the visitors' down by it
    "bench": 0.8,         # multiplier on the rate of a man who comes off the bench
}
PLAY_P = {"out": 0.0, "ofs": 0.0, "doubt": 0.15, "ques": 0.5, "gtd": 0.5, "prob": 0.85}
POS_GROUP = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C"}


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------
def _clock(v) -> float:
    s = str(v or "0")
    try:
        if ":" in s:
            m, sec = s.split(":")[:2]
            return int(m) * 60 + float(sec)
        return float(s)
    except ValueError:
        return 0.0


def _elapsed(period: int, clock: float) -> float:
    """Seconds since the opening tip."""
    if period <= 4:
        return (period - 1) * 720 + (720 - clock)
    return 2880 + (period - 5) * 300 + (300 - clock)


def _mins(v) -> float:
    try:
        return float(str(v).split(":")[0])
    except (TypeError, ValueError):
        return 0.0


NOT_ON_FLOOR = ("technical", "eject", "timeout", "review", "challenge", "delay", "end ", "substitution")
LAST_FT = ("free throw - 2 of 2", "free throw - 3 of 3")
GAMES_V = 2   # bump when parse_game's row changes; older rows are pulled again


def parse_game(eid: str, data: dict, season: int) -> dict | None:
    """One game, slim. Per player: name, team, position, started, minutes,
    made dunks, the share of each of the first 24 minutes he was on the
    floor, and his team's possessions while he was on it. Per team: its
    possessions and its live-ball turnovers (steals against it). Every made
    dunk with its time, and who won the opening tip."""
    try:
        comp = data["header"]["competitions"][0]
    except (KeyError, IndexError, TypeError):
        return None
    teams = {}
    for c in comp["competitors"]:
        teams[str(c["team"]["id"])] = {"a": c["team"].get("abbreviation", ""),
                                       "h": 1 if c.get("homeAway") == "home" else 0, "poss": 0, "lto": 0}
    if len(teams) != 2:
        return None
    tids = list(teams)
    other = {tids[0]: tids[1], tids[1]: tids[0]}
    players: dict[str, dict] = {}
    for tblock in (data.get("boxscore") or {}).get("players", []):
        tid = str(tblock["team"]["id"])
        for sb in tblock.get("statistics", []):
            ix = {k: i for i, k in enumerate(sb.get("keys") or [])}
            for a in sb.get("athletes", []):
                st = a.get("stats") or []
                if a.get("didNotPlay") or not st or "minutes" not in ix:
                    continue
                mn = _mins(st[ix["minutes"]])
                if mn <= 0:
                    continue
                ath = a["athlete"]
                players[str(ath["id"])] = {
                    "n": ath.get("displayName", ""), "t": tid, "min": mn,
                    "st": 1 if a.get("starter") else 0,
                    "pos": ((ath.get("position") or {}).get("abbreviation") or ""),
                    "dk": 0, "poss": 0, "sec": 0.0,
                }
    plays = data.get("plays") or []
    if not players or not plays:
        return None

    # Who is on the floor. Start from the starters, follow the substitutions,
    # and at the start of each later period (ESPN lists no substitutions
    # between periods) take whoever acts in the period before he is sent in.
    on = {aid for aid, p in players.items() if p["st"]}
    on_ok = len(on) == 10 and sum(1 for a in on if players[a]["t"] == tids[0]) == 5
    secs = {aid: [0.0] * CURVE_MIN for aid in players}
    horizon = CURVE_MIN * 60

    def credit(t0: float, t1: float) -> None:
        if t1 <= t0:
            return
        for aid in on:
            players[aid]["sec"] += t1 - t0
        t0, t1 = max(0.0, t0), min(float(horizon), t1)
        k = int(t0 // 60)
        while k < CURVE_MIN and k * 60 < t1:
            ov = min(t1, (k + 1) * 60) - max(t0, k * 60)
            if ov > 0:
                for aid in on:
                    secs[aid][k] += ov
            k += 1

    def possession(tid: str) -> None:
        if tid not in teams:
            return
        teams[tid]["poss"] += 1
        for aid in on:
            if players[aid]["t"] == tid:
                players[aid]["poss"] += 1

    by_period: dict[int, list] = defaultdict(list)
    for p in plays:
        by_period[int((p.get("period") or {}).get("number") or 0)].append(p)

    dunks = []
    tip = None
    last_t = 0.0
    for per in sorted(by_period):
        if per < 1:
            continue
        pp = by_period[per]
        if per > 1:
            sent_in, seen = set(), []
            for p in pp:
                typ = ((p.get("type") or {}).get("text") or "").lower()
                parts = [str((x.get("athlete") or {}).get("id") or "") for x in p.get("participants") or []]
                if typ == "substitution":
                    if parts:
                        sent_in.add(parts[0])
                    if len(parts) > 1 and parts[1] not in sent_in and parts[1] not in seen:
                        seen.append(parts[1])     # the man coming off was on
                    continue
                if any(w in typ for w in NOT_ON_FLOOR):
                    continue
                for a in parts:
                    if a in players and a not in sent_in and a not in seen:
                        seen.append(a)
            new_on = set()
            for tid in tids:
                five = [a for a in seen if a in players and players[a]["t"] == tid][:5]
                if len(five) < 5:
                    # men who played the whole period without a recorded play
                    for a in on:
                        if len(five) >= 5:
                            break
                        if players[a]["t"] == tid and a not in five and a not in sent_in:
                            five.append(a)
                new_on.update(five)
            last_t = _elapsed(per, 720 if per <= 4 else 300)
            on = new_on
        for p in pp:
            t = _elapsed(per, _clock((p.get("clock") or {}).get("displayValue")))
            typ = (p.get("type") or {}).get("text") or ""
            low = typ.lower()
            text = (p.get("text") or "").lower()
            tid = str((p.get("team") or {}).get("id") or "")
            parts = [str((x.get("athlete") or {}).get("id") or "") for x in p.get("participants") or []]
            if typ == "Substitution":
                if t > last_t:
                    credit(last_t, t)
                    last_t = t
                if len(parts) >= 2:
                    on.discard(parts[1])
                    if parts[0] in players:
                        on.add(parts[0])
                continue
            if low == "jumpball" and tip is None and per == 1 and t < 30:
                # participants: the two jumpers, then the man who gains possession
                g = parts[2] if len(parts) > 2 else ""
                tip = players[g]["t"] if g in players else (tid if tid in teams else "")
            made_fg = p.get("scoringPlay") and p.get("shootingPlay") and "free throw" not in low
            if made_fg:
                possession(tid)
                if "dunk" in low and parts and parts[0] in players:
                    dunks.append([round(t, 1), parts[0]])
                    players[parts[0]]["dk"] += 1
            elif "turnover" in low or "turnover" in text or low.startswith(("traveling", "double dribble", "back court")):
                possession(tid)
                if "steal" in text and tid in teams:
                    teams[tid]["lto"] += 1
            elif low == "defensive rebound" and tid in other:
                possession(other[tid])
            elif low in LAST_FT and p.get("scoringPlay"):
                possession(tid)
        end = _elapsed(per, 0)
        credit(last_t, end)
        last_t = end
    dunks.sort(key=lambda x: x[0])

    out_p = {}
    err = n = 0.0
    for aid, p in players.items():
        curve = "".join(chr(48 + min(9, int(round(s / 60 * 9)))) for s in secs[aid])
        out_p[aid] = [p["n"], p["t"], p["pos"], p["st"], int(p["min"]), p["dk"], curve, p["poss"]]
        err += abs(p["sec"] / 60 - p["min"])
        n += 1
    return {"id": eid, "v": GAMES_V, "s": season, "d": (comp.get("date") or "")[:10], "teams": teams,
            "p": out_p, "dunks": dunks, "tip": tip or "", "ok": 1 if on_ok else 0,
            "merr": round(err / n, 2) if n else None}


def fetch(seasons: list[int], workers: int) -> list[dict]:
    sys.path.insert(0, HERE)
    from nba_fetch_correlations import make_session            # noqa: E402
    from nba_fetch_teammates import get_json, season_event_ids  # noqa: E402

    have: dict[str, dict] = {}
    if os.path.exists(GAMES):
        with open(GAMES) as fh:
            have = {g["id"]: g for g in json.load(fh)["games"] if g.get("v") == GAMES_V}
    for season in sorted(seasons):
        ids = season_event_ids(make_session(), season)
        todo = [i for i in ids if i not in have]
        print(f"season {season}: {len(ids)} final games, {len(todo)} to fetch", file=sys.stderr)

        def one(eid, season=season):
            data = get_json(make_session(), SUMMARY.format(eid))
            try:
                return parse_game(eid, data, season) if data else None
            except Exception as e:  # noqa: BLE001  one odd game must not stop the pull
                print(f"  ! game {eid}: {e!r}", file=sys.stderr)
                return None

        done = 0
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            for g in ex.map(one, todo):
                done += 1
                if g:
                    have[g["id"]] = g
                if done % 200 == 0:
                    print(f"  {done}/{len(todo)}", file=sys.stderr)
        if have:
            with open(GAMES, "w") as fh:
                json.dump({"games": sorted(have.values(), key=lambda g: (g["d"], g["id"]))}, fh, separators=(",", ":"))
    games = sorted(have.values(), key=lambda g: (g["d"], g["id"]))
    if not games:
        sys.exit("No games fetched; leaving the data files alone.")
    with open(GAMES, "w") as fh:
        json.dump({"games": games}, fh, separators=(",", ":"))
    return games


def load_games() -> list[dict]:
    if not os.path.exists(GAMES):
        sys.exit(f"{GAMES} is missing; run with --fetch first.")
    with open(GAMES) as fh:
        return json.load(fh)["games"]


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
def bucket(role: int, mpg: float | None) -> int:
    """Minutes tier within a role, for the league's on-floor curves."""
    if mpg is None:
        return 1 if role else 0
    if role:
        return 0 if mpg < 26 else (1 if mpg < 32 else 2)
    return 0 if mpg < 10 else (1 if mpg < 18 else 2)


def hazards(entries: list[dict], m: list[float], gamma: float = 1.0) -> list[list[float]]:
    """Expected dunks by each player in each of the 48 minutes.

    entries: {id, rate (dunks per minute on the floor, after pace and the
    other team), early (multiplier in the first EARLY_MIN minutes), tip
    (multiplier in the opening minute), curve (share of each of the first
    24 minutes on the floor), after (share of the last 24)}.
    """
    out = []
    for k in range(GAME_MIN):
        h = []
        for e in entries:
            x = e["rate"] * m[k] * (e["curve"][k] if k < CURVE_MIN else e["after"])
            if k < EARLY_MIN:
                x *= e.get("early", 1.0)
            if k == 0:
                x *= e.get("tip", 1.0)
            h.append(x)
        tot = sum(h)
        if tot > 0 and gamma != 1.0:
            z = sum(x ** gamma for x in h)
            h = [tot * x ** gamma / z for x in h]
        out.append(h)
    return out


def price(entries: list[dict], m: list[float], gamma: float = 1.0) -> dict:
    """Closed form. For each minute with total rate L:
         P(first dunk in it) = P(no dunk before) x (1 - exp(-L)),  player i's share = his rate / L.
    Returns probs (they sum to 1 - no_dunk), no_dunk, each team's chance of the
    game's first dunk, and the expected minute of the first dunk and of each
    team's own first dunk."""
    hz = hazards(entries, m, gamma)
    p = [0.0] * len(entries)
    alive = 1.0
    t_first = 0.0
    teams = sorted({e["t"] for e in entries})
    t_alive = {t: 1.0 for t in teams}
    t_time = {t: 0.0 for t in teams}
    for k, h in enumerate(hz):
        tot = sum(h)
        if tot > 0:
            q = alive * (1 - math.exp(-tot))
            for i, x in enumerate(h):
                p[i] += q * x / tot
            # a dunk inside the minute lands, on average, just before its middle
            t_first += q * (k + 0.5)
            alive *= math.exp(-tot)
        for t in teams:
            lt = sum(x for e, x in zip(entries, h) if e["t"] == t)
            if lt > 0:
                t_time[t] += t_alive[t] * (1 - math.exp(-lt)) * (k + 0.5)
                t_alive[t] *= math.exp(-lt)
    probs = {e["id"]: v for e, v in zip(entries, p)}
    share = {t: sum(v for e, v in zip(entries, p) if e["t"] == t) for t in teams}
    return {"probs": probs, "no_dunk": alive, "team": share,
            "t_first": t_first / (1 - alive) if alive < 1 else None,
            "t_team": {t: (t_time[t] / (1 - t_alive[t]) if t_alive[t] < 1 else None) for t in teams}}


def monte_carlo(entries, m, gamma=1.0, patterns=None, n=200000, seed=7):
    """The same game by simulation. Each run draws a rotation (for each player,
    one of his own past games in tonight's role, when `patterns` has them),
    then draws the minute and the man of the first dunk from that run's rates.
    Returns the same probs / no_dunk as price()."""
    import numpy as np
    rng = np.random.default_rng(seed)
    P = len(entries)
    on = np.empty((n, P, GAME_MIN))
    for i, e in enumerate(entries):
        pats = (patterns or {}).get(e["id"])
        if pats:
            arr = np.array([[(ord(c) - 48) / 9 for c in s_] for s_ in pats])
            on[:, i, :CURVE_MIN] = arr[rng.integers(0, len(arr), n)]
        else:
            on[:, i, :CURVE_MIN] = np.array(e["curve"])[None, :]
        on[:, i, CURVE_MIN:] = e["after"]
    base = np.ones((P, GAME_MIN))
    for i, e in enumerate(entries):
        base[i, :] = e["rate"] * np.array(m)
        base[i, :EARLY_MIN] *= e.get("early", 1.0)
        base[i, 0] *= e.get("tip", 1.0)
    h = on * base[None, :, :]                       # (n, P, 48)
    tot = h.sum(axis=1)                             # (n, 48)
    if gamma != 1.0:
        hg = h ** gamma
        z = hg.sum(axis=1)
        h = np.where(z[:, None, :] > 0, hg * (tot / np.where(z > 0, z, 1))[:, None, :], 0.0)
    cum = np.cumsum(tot, axis=1)
    # first dunk time: an exponential clock against the cumulative rate
    u = rng.exponential(size=n)
    k = (cum < u[:, None]).sum(axis=1)              # minute of the first dunk; 48 = none
    hit = k < GAME_MIN
    kk = np.where(hit, k, 0)
    rows = np.arange(n)
    hk = h[rows, :, kk]                             # (n, P) rates in that minute
    c = np.cumsum(hk, axis=1)
    pick = (c < (rng.random(n) * c[:, -1])[:, None]).sum(axis=1)
    pick = np.minimum(pick, P - 1)
    counts = np.bincount(pick[hit], minlength=P)
    return {"probs": {e["id"]: counts[i] / n for i, e in enumerate(entries)}, "no_dunk": 1 - hit.mean()}


def american(p: float) -> str:
    if not (0 < p < 1):
        return ""
    return f"-{round(100 * p / (1 - p))}" if p >= 0.5 else f"+{round(100 * (1 - p) / p)}"


class State:
    """Everything known before a game, built up one game at a time."""

    def __init__(self, **kw):
        self.P = {**PARAMS, **kw}
        self.pl = defaultdict(lambda: defaultdict(lambda: {
            "poss": 0, "min": 0.0, "dk": 0, "g": 0,
            "c": [[0.0] * CURVE_MIN, [0.0] * CURVE_MIN], "cn": [0, 0], "rm": [0.0, 0.0]}))
        self.meta: dict[str, dict] = {}
        self.pos = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))        # season -> group -> [dunks, possessions]
        self.lcurve = defaultdict(lambda: defaultdict(lambda: [[0.0] * CURVE_MIN, 0, 0.0]))
        self.team = defaultdict(lambda: defaultdict(lambda: {
            "g": 0, "poss": 0, "dk": 0, "allowed": 0, "opp_poss": 0, "lto": 0, "tipw": 0, "tipn": 0,
            "exp": 0.0, "e_obs": 0, "e_exp": 0.0, "first": 0, "tfirst": 0.0, "tn": 0}))
        self.lg = defaultdict(lambda: {"g": 0, "dk": 0, "poss": 0, "lto": 0})
        self.obs = defaultdict(lambda: [0.0] * CURVE_MIN)
        self.exp = defaultdict(lambda: [0.0] * CURVE_MIN)
        self.tinfo: dict[str, dict] = {}

    # ---- sums over this season and the two before, weighted ----
    def _w(self, season):
        return ((season, 1.0), (season - 1, self.P["w1"]), (season - 2, self.P["w2"]))

    def _sum(self, table, season, f):
        return sum(w * f(table[s]) for s, w in self._w(season) if w and s in table)

    def _lg(self, season, key):
        return self._sum(self.lg, season, lambda r: r[key])

    def _tm(self, tid, season, key):
        t = {s: v[tid] for s, v in self.team.items() if tid in v}
        return self._sum(t, season, lambda r: r[key])

    def mpg(self, aid, season):
        t = self.pl.get(aid)
        if not t:
            return None
        g = self._sum(t, season, lambda r: r["g"])
        return self._sum(t, season, lambda r: r["min"]) / g if g else None

    # ---- player ----
    def pos_rate(self, group, season):
        dk = ps = 0.0
        for s, w in self._w(season):
            if w and s in self.pos:
                for gname, (d, p_) in self.pos[s].items():
                    if group is None or gname == group:
                        dk += w * d
                        ps += w * p_
        if ps < 5000 and group is not None:
            return self.pos_rate(None, season)
        return dk / ps if ps else 0.002

    def lam(self, aid, pos, season):
        """Made dunks per possession on the floor, shrunk toward his position's."""
        t = self.pl.get(aid) or {}
        dk = self._sum(t, season, lambda r: r["dk"])
        ps = self._sum(t, season, lambda r: r["poss"])
        k = self.P["prior_poss"]
        return (dk + k * self.pos_rate(POS_GROUP.get(pos), season)) / (ps + k)

    def lam_recent(self, aid, pos, season, n=10):
        """The same rate from his last n games only."""
        rec = (self.meta.get(aid) or {}).get("recent") or []
        rec = rec[-n:]
        k = self.P["prior_poss"]
        return (sum(r[2] for r in rec) + k * self.pos_rate(POS_GROUP.get(pos), season)) / (sum(r[3] for r in rec) + k)

    def league_curve(self, role, tier, season):
        sm, n, mins = [0.0] * CURVE_MIN, 0.0, 0.0
        for s, w in self._w(season):
            if w and s in self.lcurve and (role, tier) in self.lcurve[s]:
                c, cn, cm = self.lcurve[s][(role, tier)]
                sm = [a + w * b for a, b in zip(sm, c)]
                n += w * cn
                mins += w * cm
        if n < 20:
            return [1.0 if role else 0.25] * CURVE_MIN, (30.0 if role else 14.0)
        return [x / n for x in sm], mins / n

    def curve(self, aid, role, season):
        """(share of each of the first 24 minutes on the floor, share of the last 24) in a role."""
        lc, lmin = self.league_curve(role, bucket(role, self.mpg(aid, season)), season)
        t = self.pl.get(aid) or {}
        n = self._sum(t, season, lambda r: r["cn"][role])
        k = self.P["curve_k"]
        c = [(self._sum(t, season, lambda r, j=j: r["c"][role][j]) + k * lc[j]) / (n + k) for j in range(CURVE_MIN)]
        mins = (self._sum(t, season, lambda r: r["rm"][role]) + k * lmin) / (n + k)
        after = min(1.0, max(0.02, (mins - sum(c)) / (GAME_MIN - CURVE_MIN)))
        return c, after

    # ---- team ----
    def lg_ppg(self, season):
        g = self._lg(season, "g")
        return self._lg(season, "poss") / (2 * g) if g else 97.0

    def lg_rate(self, season):
        ps = self._lg(season, "poss")
        return self._lg(season, "dk") / ps if ps else 0.05

    def pace(self, tid, season):
        """The team's possessions a game, shrunk toward the league's."""
        k, avg = self.P["team_k"], self.lg_ppg(season)
        return (self._tm(tid, season, "poss") + k * avg) / (self._tm(tid, season, "g") + k)

    def dfac(self, tid, season):
        """Dunks this team allows per possession, over the league's rate."""
        r, k = self.lg_rate(season), self.P["team_k"] * self.lg_ppg(season)
        return ((self._tm(tid, season, "allowed") + k * r) / (self._tm(tid, season, "opp_poss") + k)) / r if r else 1.0

    def tofac(self, tid, season):
        """This team's live-ball turnovers per possession, over the league's rate."""
        ps = self._lg(season, "poss")
        r = self._lg(season, "lto") / ps if ps else 0.0
        k = self.P["team_k"] * self.lg_ppg(season)
        return ((self._tm(tid, season, "lto") + k * r) / (self._tm(tid, season, "poss") + k)) / r if r else 1.0

    def ofac(self, tid, season):
        """The team's dunks over what its players' rates expected (scheme, spacing, lobs)."""
        k = self.P["team_k"] * self.lg_rate(season) * self.lg_ppg(season)
        return (self._tm(tid, season, "dk") + k) / (self._tm(tid, season, "exp") + k)

    def efac(self, tid, season):
        """The team's dunks in the opening six minutes over what was expected (how fast it gets one)."""
        k = self.P["team_k"] * 0.6
        return (self._tm(tid, season, "e_obs") + k) / (self._tm(tid, season, "e_exp") + k)

    def tip_p(self, tid, opp, season):
        """Chance this team wins the opening tip against that one."""
        def wr(t):
            return (self._tm(t, season, "tipw") + 5) / (self._tm(t, season, "tipn") + 10)
        return min(0.9, max(0.1, 0.5 + (wr(tid) - wr(opp))))

    def mult(self, season):
        """The league's dunk rate in each minute, over what the players' rates expect."""
        o = [self._sum(self.obs, season, lambda r, j=j: r[j]) for j in range(CURVE_MIN)]
        e = [self._sum(self.exp, season, lambda r, j=j: r[j]) for j in range(CURVE_MIN)]
        return [(o[j] + 30) / (e[j] + 30) for j in range(CURVE_MIN)] + [1.0] * (GAME_MIN - CURVE_MIN)

    def team_ctx(self, tid, opp, season, home=None):
        """A team's side of a matchup: possessions a minute and the multipliers on its players' rates."""
        avg = self.lg_ppg(season)
        pace = avg * (self.pace(tid, season) / avg) * (self.pace(opp, season) / avg) / GAME_MIN
        mult = self.dfac(opp, season)
        if self.P["to_pow"]:
            mult *= self.tofac(opp, season) ** self.P["to_pow"]
        if self.P["off_pow"]:
            mult *= self.ofac(tid, season) ** self.P["off_pow"]
        if home is not None and self.P["home"]:
            mult *= 1 + self.P["home"] if home else 1 - self.P["home"]
        early = self.efac(tid, season) ** self.P["early_pow"] if self.P["early_pow"] else 1.0
        tip = 1.0 + self.P["tip_pow"] * (2 * self.tip_p(tid, opp, season) - 1) if self.P["tip_pow"] else 1.0
        return {"pace": pace, "mult": mult, "early": early, "tip": tip}

    def entry(self, aid, tid, pos, st, ctx, season, lam=None):
        c, after = self.curve(aid, st, season)
        lam = self.lam(aid, pos, season) if lam is None else lam
        return {"id": aid, "t": tid, "st": st, "lam": lam,
                "rate": lam * ctx["pace"] * ctx["mult"] * (1.0 if st else self.P["bench"]),
                "early": ctx["early"], "tip": ctx["tip"], "curve": c, "after": after}

    def entries(self, game, lineup=None):
        """Pricing rows for a game. lineup: {aid: (team id, pos, starter)}; the box score's by default."""
        if lineup is None:
            lineup = {aid: (p[1], p[2], p[3]) for aid, p in game["p"].items()}
        tids = list(game["teams"])
        hm = {t: game["teams"][t]["h"] for t in tids}
        ctx = {tids[0]: self.team_ctx(tids[0], tids[1], game["s"], hm[tids[0]]),
               tids[1]: self.team_ctx(tids[1], tids[0], game["s"], hm[tids[1]])}
        return [self.entry(aid, tid, pos, st, ctx[tid], game["s"]) for aid, (tid, pos, st) in lineup.items()]

    def update(self, game, ent=None):
        s = game["s"]
        ent = ent or self.entries(game)
        tids = list(game["teams"])
        other = {tids[0]: tids[1], tids[1]: tids[0]}
        ok = game.get("ok")
        got = defaultdict(int)
        # what the pre-game rates expected, with the minutes and possessions actually played
        for e in ent:
            row = game["p"][e["id"]]
            d_opp = self.dfac(other[e["t"]], s)
            self.team[s][e["t"]]["exp"] += e["lam"] * row[7] * d_opp
            if ok:
                cv = row[6]
                for j in range(CURVE_MIN):
                    x = e["rate"] * (ord(cv[j]) - 48) / 9
                    self.exp[s][j] += x
                    if j < EARLY_MIN:
                        self.team[s][e["t"]]["e_exp"] += x
        if ok:
            for t, aid in game["dunks"]:
                if t < CURVE_MIN * 60:
                    self.obs[s][int(t // 60)] += 1
                if t < EARLY_MIN * 60 and aid in game["p"]:
                    self.team[s][game["p"][aid][1]]["e_obs"] += 1
        for aid, (name, tid, pos, st, mn, dk, cv, ps) in game["p"].items():
            tier = bucket(st, self.mpg(aid, s))
            r = self.pl[aid][s]
            r["min"] += mn
            r["poss"] += ps
            r["dk"] += dk
            r["g"] += 1
            m = self.meta.setdefault(aid, {"recent": [], "pat": {0: [], 1: []}})
            if ok:
                on = [(ord(ch) - 48) / 9 for ch in cv]
                r["c"][st] = [a + b for a, b in zip(r["c"][st], on)]
                r["cn"][st] += 1
                r["rm"][st] += mn
                lc = self.lcurve[s][(st, tier)]
                lc[0] = [a + b for a, b in zip(lc[0], on)]
                lc[1] += 1
                lc[2] += mn
                m["pat"][st] = (m["pat"][st] + [cv])[-30:]
            grp = POS_GROUP.get(pos)
            if grp:
                self.pos[s][grp][0] += dk
                self.pos[s][grp][1] += ps
            got[tid] += dk
            m.update(n=name, pos=pos, t=tid, d=game["d"])
            m["recent"] = (m["recent"] + [(st, mn, dk, ps)])[-10:]
        first_by = {}
        for t, aid in game["dunks"]:
            if aid in game["p"]:
                first_by.setdefault(game["p"][aid][1], t)
        for tid in tids:
            opp = other[tid]
            tm = self.team[s][tid]
            tm["g"] += 1
            tm["poss"] += game["teams"][tid]["poss"]
            tm["opp_poss"] += game["teams"][opp]["poss"]
            tm["dk"] += got[tid]
            tm["allowed"] += got[opp]
            tm["lto"] += game["teams"][tid]["lto"]
            if game.get("tip"):
                tm["tipn"] += 1
                tm["tipw"] += 1 if game["tip"] == tid else 0
            if tid in first_by:
                tm["tfirst"] += first_by[tid]
                tm["tn"] += 1
                if game["dunks"] and game["p"][game["dunks"][0][1]][1] == tid:
                    tm["first"] += 1
            self.tinfo[tid] = {"a": game["teams"][tid]["a"], "d": game["d"],
                               "dates": ((self.tinfo.get(tid) or {}).get("dates") or [])[-2:] + [game["d"]],
                               "st": [aid for aid, p in game["p"].items() if p[1] == tid and p[3]]}
            self.lg[s]["poss"] += game["teams"][tid]["poss"]
            self.lg[s]["lto"] += game["teams"][tid]["lto"]
        self.lg[s]["dk"] += len(game["dunks"])
        self.lg[s]["g"] += 1


# --------------------------------------------------------------------------
# Uncertain lineups: a starter who is doubtful, questionable or probable
# --------------------------------------------------------------------------
def mix(rows: list[dict], make_entries, m, gamma=1.0, max_unsure=8) -> dict:
    """Price a game whose lineup is not settled.

    rows: {id, t (team), st (listed to start), play (chance he plays, 0..1),
    sub (order to step in for a starter who sits; lower first)}. Every way the
    unsure players can turn out is priced with its chance and the results are
    added up; in each one a team short of five starters takes its next men up.
    make_entries(lineup) -> pricing rows for {id: starter flag}.
    """
    unsure = sorted((r for r in rows if 0 < r["play"] < 1), key=lambda r: -abs(0.5 - r["play"]))
    # past max_unsure, the most settled are rounded to in or out
    fixed_extra = unsure[: max(0, len(unsure) - max_unsure)]
    unsure = unsure[len(fixed_extra):]
    plays = {r["id"]: r["play"] >= 0.5 if r in fixed_extra else r["play"] >= 1 for r in rows}
    total = {"probs": defaultdict(float), "no_dunk": 0.0, "team": defaultdict(float), "t_first": 0.0,
             "t_team": defaultdict(float)}
    teams = sorted({r["t"] for r in rows})
    for mask in range(1 << len(unsure)):
        w = 1.0
        for b, r in enumerate(unsure):
            inn = bool(mask >> b & 1)
            plays[r["id"]] = inn
            w *= r["play"] if inn else 1 - r["play"]
        if w <= 0:
            continue
        lineup = {}
        for t in teams:
            act = [r for r in rows if r["t"] == t and plays[r["id"]]]
            st = [r for r in act if r["st"]]
            bench = sorted((r for r in act if not r["st"]), key=lambda r: r["sub"])
            while len(st) < 5 and bench:
                st.append(bench.pop(0))
            ids = {r["id"] for r in st}
            for r in act:
                lineup[r["id"]] = 1 if r["id"] in ids else 0
        res = price(make_entries(lineup), m, gamma)
        for k, v in res["probs"].items():
            total["probs"][k] += w * v
        total["no_dunk"] += w * res["no_dunk"]
        total["t_first"] += w * (res["t_first"] or 0.0)
        for t in teams:
            total["team"][t] += w * res["team"].get(t, 0.0)
            total["t_team"][t] += w * (res["t_team"].get(t) or 0.0)
    return {"probs": dict(total["probs"]), "no_dunk": total["no_dunk"], "team": dict(total["team"]),
            "t_first": total["t_first"], "t_team": dict(total["t_team"]), "scenarios": 1 << len(unsure)}


# --------------------------------------------------------------------------
# Backtest: price every game from what was known before it
# --------------------------------------------------------------------------
EDGES = [0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 1.01]


def backtest(games, verbose=True, **kw):
    st = State(**kw)
    gamma = st.P["gamma"]
    first = min(g["s"] for g in games)
    n = 0
    ll = ll_u = ll_b = 0.0
    top = top3 = 0
    cal = [[0, 0.0, 0] for _ in EDGES[:-1]]
    grp = defaultdict(lambda: [0.0, 0])
    nodunk = late = 0
    t_pred = t_act = 0.0
    oth_p = oth_hit = 0.0
    for g in games:
        ent = st.entries(g)
        if g["s"] > first and g.get("ok"):
            if not g["dunks"]:
                nodunk += 1
            else:
                t1, who = g["dunks"][0]
                res = price(ent, st.mult(g["s"]), gamma)
                probs = res["probs"]
                starters = [e["id"] for e in ent if e["st"]]
                # baselines: the ten starters evenly; the starters by dunks a game so far
                dpg = {}
                for a in starters:
                    t = st.pl.get(a) or {}
                    dpg[a] = (st._sum(t, g["s"], lambda r: r["dk"]) + 0.3) / (st._sum(t, g["s"], lambda r: r["g"]) + 3)
                tot = sum(dpg.values())
                eps = 0.03   # what the baselines leave for the bench, split evenly
                nb = max(1, len(ent) - len(starters))
                pu = (1 - eps) / len(starters) if who in starters else eps / nb
                pb = (1 - eps) * dpg[who] / tot if who in starters else eps / nb
                n += 1
                ll -= math.log(max(probs[who], 1e-9))
                ll_u -= math.log(pu)
                ll_b -= math.log(pb)
                rank = sorted(probs, key=probs.get, reverse=True)
                top += 1 if rank[0] == who else 0
                top3 += 1 if who in rank[:3] else 0
                late += 1 if t1 >= 720 else 0
                t_pred += res["t_first"]
                t_act += t1 / 60
                oth_p += sum(probs[e["id"]] for e in ent if not e["st"])
                oth_hit += 0 if who in starters else 1
                for e in ent:
                    pr = probs[e["id"]]
                    hit = 1 if e["id"] == who else 0
                    for bi in range(len(EDGES) - 1):
                        if EDGES[bi] <= pr < EDGES[bi + 1]:
                            cal[bi][0] += 1
                            cal[bi][1] += pr
                            cal[bi][2] += hit
                            break
                    pos = POS_GROUP.get(g["p"][e["id"]][2], "?")
                    for key in ("starter" if e["st"] else "bench", "pos " + pos,
                                "home" if g["teams"][e["t"]]["h"] else "away",
                                "won the tip" if g.get("tip") == e["t"] else "lost the tip"):
                        grp[key][0] += pr
                        grp[key][1] += hit
        st.update(g, ent)
    res = {"n": n, "ll": ll / n, "ll_even": ll_u / n, "ll_dpg": ll_b / n, "top": top / n, "top3": top3 / n,
           "no_dunk": nodunk, "after_q1": late / n, "t_pred": t_pred / n, "t_act": t_act / n,
           "other_pred": oth_p / n, "other_hit": oth_hit / n,
           "cal": [{"lo": EDGES[i], "hi": min(1.0, EDGES[i + 1]), "n": c[0],
                    "pred": c[1] / c[0] if c[0] else None, "hit": c[2] / c[0] if c[0] else None}
                   for i, c in enumerate(cal)],
           "groups": {k: {"pred": v[0] / n, "hit": v[1] / n} for k, v in sorted(grp.items())}}
    if verbose:
        print(f"{n} games priced from what was known before each ({nodunk} more had no dunk)")
        print(f"log loss  model {res['ll']:.4f}   starters by dunks a game {res['ll_dpg']:.4f}   ten starters evenly {res['ll_even']:.4f}")
        print(f"first dunker was the top pick {100 * res['top']:.1f}%, in the top three {100 * res['top3']:.1f}%")
        print(f"minutes to the first dunk: priced {res['t_pred']:.2f}, happened {res['t_act']:.2f}; after Q1 {100 * res['after_q1']:.1f}%")
        print(f"\"Other\" (anyone but the ten starters): priced {100 * res['other_pred']:.1f}%, happened {100 * res['other_hit']:.1f}%")
        print("priced at      players   avg priced   made it")
        for c in res["cal"]:
            if c["n"]:
                print(f"  {100 * c['lo']:4.0f}-{100 * c['hi']:3.0f}%  {c['n']:7d}   {100 * c['pred']:8.2f}%  {100 * c['hit']:7.2f}%")
        print("share of first dunks   priced   happened")
        for k, v in res["groups"].items():
            print(f"  {k:13s} {100 * v['pred']:11.1f}% {100 * v['hit']:9.1f}%")
    return res


GRID = {
    "prior_poss": [50, 100, 200, 400, 800],
    "w1": [0.3, 0.6, 0.8, 1.0],
    "w2": [0.0, 0.15, 0.3, 0.5],
    "gamma": [1.0, 1.1, 1.2],
    "team_k": [5, 10, 20, 40],
    "curve_k": [2, 4, 8],
    "to_pow": [0.0, 0.5, 1.0],
    "off_pow": [0.0, 0.5, 1.0],
    "early_pow": [0.0, 0.5, 1.0],
    "tip_pow": [0.0, 0.3, 0.6],
    "home": [0.0, 0.03, 0.06, 0.09],
    "bench": [0.8, 0.9, 1.0],
}


def tune(games, rounds=2):
    """Coordinate search on log loss: each setting in turn over its grid, the best kept, twice round."""
    best = dict(PARAMS)
    base = backtest(games, verbose=False, **best)["ll"]
    print(f"start      log loss {base:.4f}  {best}")
    for rnd in range(rounds):
        for key, vals in GRID.items():
            scores = []
            for v in vals:
                r = backtest(games, verbose=False, **{**best, key: v})
                scores.append((r["ll"], v, r["top3"]))
            print(f"{key:10s} " + "  ".join(f"{v}:{ll:.4f}" for ll, v, _ in scores))
            ll, v, _ = min(scores)
            if ll < base - 1e-5:
                base, best[key] = ll, v
        print(f"after round {rnd + 1}: log loss {base:.4f}  {best}")
    return best


# --------------------------------------------------------------------------
# Build the page's file
# --------------------------------------------------------------------------
def build(games, roster: dict | None):
    st = State()
    for g in games:
        st.update(g)
    season = max(g["s"] for g in games)
    r3 = lambda xs: [round(x, 3) for x in xs]  # noqa: E731
    lgr = st.lg_rate(season)
    teams = {}
    for tid, info in st.tinfo.items():
        tm = st.team[season].get(tid)
        if not tm or not tm["g"]:
            continue
        teams[info["a"]] = {
            "id": tid, "g": tm["g"], "last": info["d"], "since": info["dates"][0], "starters": info["st"],
            # the multipliers the model uses (this season and the two before, weighted and shrunk)
            "pace": round(st.pace(tid, season), 2), "d": round(st.dfac(tid, season), 3),
            "to": round(st.tofac(tid, season), 3), "o": round(st.ofac(tid, season), 3),
            "e": round(st.efac(tid, season), 3),
            "tip": round((st._tm(tid, season, "tipw") + 5) / (st._tm(tid, season, "tipn") + 10), 3),
            # this season, as played
            "dk": tm["dk"], "allowed": tm["allowed"],
            "dk100": round(100 * tm["dk"] / tm["poss"], 2) if tm["poss"] else None,
            "allowed100": round(100 * tm["allowed"] / tm["opp_poss"], 2) if tm["opp_poss"] else None,
            "first": tm["first"], "tfirst": round(tm["tfirst"] / tm["tn"] / 60, 2) if tm["tn"] else None,
        }
    abbr = {v["id"]: k for k, v in teams.items()}
    players = {}
    flags = []
    for aid, m in st.meta.items():
        t = st.pl[aid]
        if not any(s_ in t for s_ in (season, season - 1, season - 2)):
            continue
        tid = (roster or {}).get(aid, {}).get("team_id") or (m["t"] if not roster else None)
        if tid not in abbr:
            continue
        cur = t.get(season) or {"g": 0, "min": 0, "dk": 0, "poss": 0}
        prev = t.get(season - 1) or {"g": 0, "min": 0, "dk": 0, "poss": 0}
        cs, a_s = st.curve(aid, 1, season)
        cb, a_b = st.curve(aid, 0, season)
        lam = st.lam(aid, m["pos"], season)
        lam10 = st.lam_recent(aid, m["pos"], season)
        rec = m["recent"]
        players[aid] = {
            "n": m["n"], "t": abbr[tid], "pos": m["pos"],
            "g": cur["g"], "min": int(cur["min"]), "dk": cur["dk"], "poss": cur["poss"],
            "pg": prev["g"], "pmin": int(prev["min"]), "pdk": prev["dk"],
            "lam": round(lam, 6), "lam10": round(lam10, 6),
            "r10": [sum(r[2] for r in rec), len(rec)],
            "rs": sum(1 for r in rec[-5:] if r[0]), "rn": len(rec[-5:]),
            "last": m["d"], "cs": r3(cs), "as": round(a_s, 3), "cb": r3(cb), "ab": round(a_b, 3),
        }
        if len(rec) >= 8 and max(lam, lam10) > 0.5 * lgr / 5 and abs(lam10 / lam - 1) > 0.25:
            flags.append({"id": aid, "n": m["n"], "t": abbr[tid], "full": round(100 * lam, 2),
                          "last10": round(100 * lam10, 2), "move": round(lam10 / lam - 1, 3)})
    flags.sort(key=lambda f: -abs(f["last10"] - f["full"]))
    firsts = sorted(g["dunks"][0][0] for g in games if g["s"] >= season - 1 and g["dunks"])
    lg = st.lg[season]
    bt = backtest(games, verbose=False)
    return {
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "season": season, "games": len(games), "through": games[-1]["d"],
        "m": r3(st.mult(season)),
        "league": {"dunks_pg": round(lg["dk"] / lg["g"], 2) if lg["g"] else None,
                   "dk100": round(100 * lg["dk"] / lg["poss"], 2) if lg["poss"] else None,
                   "ppg": round(st.lg_ppg(season), 2),
                   "first_median_sec": firsts[len(firsts) // 2] if firsts else None,
                   "first_in_q1": round(sum(1 for x in firsts if x < 720) / len(firsts), 3) if firsts else None},
        "params": PARAMS, "play_p": PLAY_P, "backtest": bt, "flags": flags, "teams": teams, "players": players,
    }, st


# --------------------------------------------------------------------------
# One game
# --------------------------------------------------------------------------
def _norm(n: str) -> str:
    import re
    import unicodedata
    n = unicodedata.normalize("NFD", n or "")
    n = "".join(c for c in n if unicodedata.category(c) != "Mn").lower()
    n = re.sub(r"[.'’`]", "", n).replace("-", " ")
    n = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", n)
    return re.sub(r"\s+", " ", n).strip()


def price_game(home_starters, away_starters, date=None, home=None, away=None, status=None, odds=None, games=None):
    """Fair odds on the first dunk of one game.

    home_starters / away_starters: five names (or ESPN ids) each. date: price
    from games before this day (YYYY-MM-DD; default: every game on file).
    home / away: team abbreviations, only needed when the starters don't settle
    it. status: {name: "out" | "doubt" | "ques" | "prob" | a chance of
    playing}. odds: {name: American or decimal price}, with "Other" for the
    book's any-other-player line, to add EV.

    Returns {rows: [{player, team, start, prob, fair, price, ev}], other,
    no_dunk, team, t_first, t_team}, rows sorted by probability. "other" is
    everyone but the ten starters named, the way DraftKings lists the market.
    """
    games = games or load_games()
    if date:
        games = [g for g in games if g["d"] < date]
    st = State()
    for g in games:
        st.update(g)
    season = max(g["s"] for g in games)
    by_name = defaultdict(list)
    for aid, m in st.meta.items():
        by_name[_norm(m["n"])].append(aid)

    def find(x):
        if str(x) in st.meta:
            return str(x)
        c = by_name.get(_norm(str(x)))
        if not c:
            raise ValueError(f"no player named {x!r} in the games on file")
        return max(c, key=lambda a: st.meta[a]["d"])

    hs, as_ = [find(x) for x in home_starters], [find(x) for x in away_starters]
    ab2id = {v["a"]: k for k, v in st.tinfo.items()}

    def team_of(ids, given):
        if given:
            return ab2id[given]
        ts = [st.meta[a]["t"] for a in ids]
        return max(set(ts), key=ts.count)

    th, ta = team_of(hs, home), team_of(as_, away)
    play = {find(k): (PLAY_P[v] if isinstance(v, str) else float(v)) for k, v in (status or {}).items()}
    rows = []
    for tid, starters in ((ta, as_), (th, hs)):
        since = st.tinfo[tid]["dates"][0]
        pool = [a for a, m in st.meta.items() if m["t"] == tid and (m["d"] >= since or a in starters)]
        for a in pool:
            rec = st.meta[a]["recent"]
            rows.append({"id": a, "t": tid, "st": 1 if a in starters else 0, "play": play.get(a, 1.0),
                         "sub": -(sum(r[0] for r in rec[-5:]) * 100 + (st.mpg(a, season) or 0))})
    ctx = {th: st.team_ctx(th, ta, season, 1), ta: st.team_ctx(ta, th, season, 0)}

    def make(lineup):
        return [st.entry(a, st.meta[a]["t"] if a not in hs + as_ else (th if a in hs else ta),
                         st.meta[a]["pos"], s_, ctx[th if any(r["id"] == a and r["t"] == th for r in rows) else ta], season)
                for a, s_ in lineup.items()]

    res = mix(rows, make, st.mult(season), PARAMS["gamma"])
    px = {}
    for k, v in (odds or {}).items():
        d_ = _decimal(v)
        if d_:
            px["other" if _norm(str(k)) in ("other", "any other player", "field") else find(k)] = d_
    out = []
    for r in rows:
        pr = res["probs"].get(r["id"], 0.0)
        d_ = px.get(r["id"])
        out.append({"player": st.meta[r["id"]]["n"], "team": st.tinfo[r["t"]]["a"], "start": r["st"], "play": r["play"],
                    "prob": pr, "fair": american(pr), "price": d_, "ev": pr * d_ - 1 if d_ else None})
    out.sort(key=lambda r: -r["prob"])
    other = sum(r["prob"] for r in out if not r["start"])
    return {"rows": out, "other": {"prob": other, "fair": american(other), "price": px.get("other"),
                                   "ev": other * px["other"] - 1 if px.get("other") else None},
            "no_dunk": res["no_dunk"], "team": {st.tinfo[t]["a"]: v for t, v in res["team"].items()},
            "t_first": res["t_first"], "t_team": {st.tinfo[t]["a"]: v for t, v in res["t_team"].items()},
            "scenarios": res["scenarios"]}


def _decimal(v):
    try:
        s_ = str(v).strip().replace("−", "-").rstrip("xX")
        x = float(s_)
    except ValueError:
        return None
    if s_[:1] in "+-" or abs(x) >= 100:
        return 1 + x / 100 if x > 0 else 1 + 100 / -x
    return x if x > 1 else None


def print_game(res):
    print(f"first dunk by team: " + "  ".join(f"{t} {100 * v:.1f}%" for t, v in res["team"].items())
          + f"   no dunk {100 * res['no_dunk']:.3f}%")
    print(f"expected minutes to the first dunk {res['t_first']:.1f}; to each team's own first: "
          + "  ".join(f"{t} {v:.1f}" for t, v in res["t_team"].items()))
    print(f"{'player':26s} {'team':5s} {'':6s} {'prob':>7s} {'fair':>7s} {'price':>7s} {'EV':>7s}")
    for r in res["rows"] + [dict(res["other"], player="Other (not a starter)", team="", start=0, play=1)]:
        if r["prob"] < 0.0005:
            continue
        role = "start" if r["start"] else ("" if r["player"].startswith("Other") else "bench")
        if r.get("play", 1) < 1:
            role += f" {round(100 * r['play'])}%"
        print(f"{r['player'][:26]:26s} {r['team']:5s} {role:6s} {100 * r['prob']:6.1f}% {r['fair']:>7s} "
              f"{(str(round(r['price'], 2)) if r['price'] else ''):>7s} {(f'{100 * r['ev']:+.1f}%' if r['ev'] is not None else ''):>7s}")


def check_mc(games, n_games=3, sims=200000):
    """The closed form against the simulation, on the last few games on file."""
    st = State()
    for g in games[:-n_games]:
        st.update(g)
    for g in games[-n_games:]:
        ent = st.entries(g)
        m = st.mult(g["s"])
        cf_ = price(ent, m, PARAMS["gamma"])
        same = monte_carlo(ent, m, PARAMS["gamma"], None, sims)
        pats = {e["id"]: (st.meta.get(e["id"]) or {}).get("pat", {}).get(e["st"]) for e in ent}
        rot = monte_carlo(ent, m, PARAMS["gamma"], pats, sims)
        d1 = max(abs(cf_["probs"][k] - same["probs"][k]) for k in cf_["probs"])
        d2 = max(abs(cf_["probs"][k] - rot["probs"][k]) for k in cf_["probs"])
        top = max(cf_["probs"], key=cf_["probs"].get)
        print(f"game {g['id']}: {sims:,} runs. Largest gap from the closed form, any player: "
              f"{100 * d1:.2f} points on the same rotation, {100 * d2:.2f} points drawing each man's rotation from his past games "
              f"(top pick {g['p'][top][0]}: {100 * cf_['probs'][top]:.1f}% closed, {100 * same['probs'][top]:.1f}% / {100 * rot['probs'][top]:.1f}% simulated)")
        st.update(g, ent)


def write_fixture(games):
    """One real game priced from the games before it, for the JS check: settled, and with two starters unsure."""
    st = State()
    for g in games[:-1]:
        st.update(g)
    g = games[-1]
    ent = st.entries(g)
    m = st.mult(g["s"])
    res = price(ent, m, 1.15)
    tids = list(g["teams"])
    ctx = {t: st.team_ctx(t, o, g["s"], g["teams"][t]["h"]) for t, o in ((tids[0], tids[1]), (tids[1], tids[0]))}
    starters = [e["id"] for e in ent if e["st"]]
    rows = [{"id": e["id"], "t": e["t"], "st": e["st"], "sub": i,
             "play": 0.5 if e["id"] == starters[0] else (0.15 if e["id"] == starters[7] else 1.0)}
            for i, e in enumerate(ent)]
    both = {}
    for e in ent:
        for role in (0, 1):
            both[f"{e['id']}:{role}"] = st.entry(e["id"], e["t"], g["p"][e["id"]][2], role, ctx[e["t"]], g["s"])
    mx = mix(rows, lambda lineup: [both[f"{a}:{s_}"] for a, s_ in lineup.items()], m, 1.15)
    with open(FIXTURE, "w") as fh:
        json.dump({"game": g["id"], "m": m, "gamma": 1.15, "entries": ent, "probs": res["probs"], "no_dunk": res["no_dunk"],
                   "team": res["team"], "t_first": res["t_first"], "t_team": res["t_team"],
                   "rows": rows, "both": both, "mixed": mx}, fh, separators=(",", ":"))
    print(f"wrote {FIXTURE}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="pull new final games from ESPN first")
    ap.add_argument("--seasons", type=int, nargs="+", default=None,
                    help="seasons to pull (default: the current one and the one before)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--mc", action="store_true")
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--price", nargs=2, metavar=("AWAY", "HOME"), help="price one game from the last starters on file")
    ap.add_argument("--date", help="with --price: use only games before this day (YYYY-MM-DD)")
    args = ap.parse_args()
    if args.fetch:
        seasons = args.seasons
        if not seasons:
            today = dt.date.today()
            cur = today.year + 1 if today.month >= 10 else today.year
            seasons = [cur - 1, cur]
        games = fetch(seasons, args.workers)
    else:
        games = load_games()
    if args.tune:
        tune(games)
        return
    if args.backtest:
        backtest(games)
        return
    if args.mc:
        return check_mc(games)
    if args.fixture:
        return write_fixture(games)
    if args.price:
        last = {}
        for g in games:
            if args.date and g["d"] >= args.date:
                break
            for tid, t in g["teams"].items():
                last[t["a"]] = [aid for aid, p in g["p"].items() if p[1] == tid and p[3]]
        away, home = args.price
        return print_game(price_game(last[home], last[away], args.date, home, away, games=games))
    roster = None
    try:
        sys.path.insert(0, HERE)
        from nba_fetch_correlations import make_session, team_roster_map  # noqa: E402
        roster = team_roster_map(make_session()) or None
    except Exception as e:  # noqa: BLE001
        print(f"  ! rosters: {e!r}", file=sys.stderr)
    if not roster:
        print("No rosters from ESPN; each player stays on the team he last played for.", file=sys.stderr)
    out, _ = build(games, roster)
    with open(OUT, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"wrote {OUT}: {len(out['players'])} players, {len(out['teams'])} teams, {out['games']} games through {out['through']}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
