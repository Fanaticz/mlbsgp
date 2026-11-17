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
(dunks per minute, shrunk toward his position's average), scaled by the
league's rate at that point of the game and by how many dunks the other team
allows. The first dunk goes to player i in minute k with probability

    (no dunk before k) x (a dunk in k) x (i's share of the rates in k)

summed over the game. FirstDunk.price in public/utils/firstDunk.js is the
same arithmetic as price() here; scripts/nba_first_dunk_check.js holds the
two together.

  python3 scripts/nba_first_dunk.py --fetch          # new finals, then rebuild
  python3 scripts/nba_first_dunk.py                  # rebuild from the games file
  python3 scripts/nba_first_dunk.py --backtest       # walk-forward check
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
# Fitted on the walk-forward backtest (--tune); see CHANGES.md.
PRIOR_MIN = 100.0     # minutes of his position's average rate mixed into a player's
PREV_W = 0.75         # weight of last season's minutes and dunks
CURVE_K = 4.0         # games of the league's curve mixed into a player's
GAMMA = 1.15         # 1 = each man's share of a minute is his share of the rates
DEF_K = 20.0          # games of league average mixed into a team's dunks allowed
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


def parse_game(eid: str, data: dict, season: int) -> dict | None:
    try:
        comp = data["header"]["competitions"][0]
    except (KeyError, IndexError, TypeError):
        return None
    teams = {}
    for c in comp["competitors"]:
        teams[str(c["team"]["id"])] = {"a": c["team"].get("abbreviation", ""), "h": 1 if c.get("homeAway") == "home" else 0}
    if len(teams) != 2:
        return None
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
                    "dk": 0,
                }
    plays = data.get("plays") or []
    if not players or not plays:
        return None

    # Who is on the floor. Start from the starters, follow the substitutions,
    # and at the start of each later quarter (ESPN lists no substitutions
    # between quarters) take whoever acts in the quarter before he is sent in.
    on = {aid for aid, p in players.items() if p["st"]}
    if sum(1 for a in on if players[a]["t"] == list(teams)[0]) != 5 or len(on) != 10:
        on_ok = False
    else:
        on_ok = True
    secs = {aid: [0.0] * CURVE_MIN for aid in players}
    horizon = CURVE_MIN * 60

    def credit(t0: float, t1: float) -> None:
        t0, t1 = max(0.0, t0), min(float(horizon), t1)
        if t1 <= t0:
            return
        k = int(t0 // 60)
        while k < CURVE_MIN and k * 60 < t1:
            ov = min(t1, (k + 1) * 60) - max(t0, k * 60)
            if ov > 0:
                for aid in on:
                    secs[aid][k] += ov
            k += 1

    by_period: dict[int, list] = defaultdict(list)
    for p in plays:
        by_period[int((p.get("period") or {}).get("number") or 0)].append(p)

    dunks = []
    last_t = 0.0
    for per in sorted(by_period):
        if per < 1:
            continue
        pp = by_period[per]
        if per > 1 and per <= 2:
            # quarter-start five for each team
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
            for tid in teams:
                five = [a for a in seen if a in players and players[a]["t"] == tid][:5]
                if len(five) < 5:
                    # men who played the whole quarter without a recorded play
                    for a in on:
                        if len(five) >= 5:
                            break
                        if players[a]["t"] == tid and a not in five and a not in sent_in:
                            five.append(a)
                new_on.update(five)
            last_t = _elapsed(per, 720)
            on = new_on
        for p in pp:
            t = _elapsed(per, _clock((p.get("clock") or {}).get("displayValue")))
            typ = (p.get("type") or {}).get("text") or ""
            parts = [str((x.get("athlete") or {}).get("id") or "") for x in p.get("participants") or []]
            if typ == "Substitution":
                if t > last_t:
                    credit(last_t, t)
                    last_t = t
                if len(parts) >= 2:
                    on.discard(parts[1])
                    if parts[0] in players:
                        on.add(parts[0])
            elif "dunk" in typ.lower() and p.get("scoringPlay") and parts and parts[0] in players:
                dunks.append([round(t, 1), parts[0]])
                players[parts[0]]["dk"] += 1
        end = _elapsed(per, 0)
        credit(last_t, end)
        last_t = end
    dunks.sort(key=lambda x: x[0])

    out_p = {}
    for aid, p in players.items():
        curve = "".join(chr(48 + min(9, int(round(s / 60 * 9)))) for s in secs[aid])
        out_p[aid] = [p["n"], p["t"], p["pos"], p["st"], int(p["min"]), p["dk"], curve]
    return {"id": eid, "s": season, "d": (comp.get("date") or "")[:10], "teams": teams,
            "p": out_p, "dunks": dunks, "ok": 1 if on_ok else 0}


def fetch(seasons: list[int], workers: int) -> list[dict]:
    sys.path.insert(0, HERE)
    from nba_fetch_correlations import make_session            # noqa: E402
    from nba_fetch_teammates import get_json, season_event_ids  # noqa: E402

    have: dict[str, dict] = {}
    if os.path.exists(GAMES):
        with open(GAMES) as fh:
            have = {g["id"]: g for g in json.load(fh)["games"]}
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


def price(entries: list[dict], m: list[float], gamma: float = None) -> tuple[dict[str, float], float]:
    """First-dunk probabilities for one game, and the chance of no dunk at all.

    entries: {id, lam (dunks a minute), d (the other team's dunks-allowed
    factor), curve (share of each of the first 24 minutes on the floor),
    after (share of the last 24)}. m: the league's dunk-rate multiplier in
    each of the 48 minutes.
    """
    p = {e["id"]: 0.0 for e in entries}
    alive = 1.0
    for k in range(GAME_MIN):
        h = [(e["id"], e["lam"] * e["d"] * m[k] * (e["curve"][k] if k < CURVE_MIN else e["after"])) for e in entries]
        tot = sum(x for _, x in h)
        if tot <= 0:
            continue
        g_ = GAMMA if gamma is None else gamma
        if g_ != 1.0:
            # the same dunks in the minute, shared out more (or less) toward the big dunkers
            z = sum(x ** g_ for _, x in h)
            h = [(i, tot * x ** g_ / z) for i, x in h]
        q = alive * (1 - math.exp(-tot))
        for i, x in h:
            p[i] += q * x / tot
        alive *= math.exp(-tot)
    s = sum(p.values()) or 1.0
    return {i: v / s for i, v in p.items()}, alive


class State:
    """Everything known before a game, built up one game at a time."""

    def __init__(self, prior_min=PRIOR_MIN, prev_w=PREV_W, curve_k=CURVE_K, def_k=DEF_K, use_m=True):
        self.prior_min, self.prev_w, self.curve_k, self.def_k, self.use_m = prior_min, prev_w, curve_k, def_k, use_m
        # aid -> season -> totals
        self.pl = defaultdict(lambda: defaultdict(lambda: {
            "min": 0.0, "dk": 0, "g": 0, "c": [[0.0] * CURVE_MIN, [0.0] * CURVE_MIN], "cn": [0, 0], "rm": [0.0, 0.0]}))
        self.meta: dict[str, dict] = {}
        self.pos = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))        # season -> group -> [dunks, minutes]
        self.lcurve = defaultdict(lambda: defaultdict(lambda: [[0.0] * CURVE_MIN, 0, 0.0]))  # season -> (role, tier) -> [sum, n, minutes]
        self.team = defaultdict(lambda: defaultdict(lambda: [0, 0]))           # season -> tid -> [dunks allowed, games]
        self.lg = defaultdict(lambda: [0, 0])                                  # season -> [dunks, games]
        self.obs = defaultdict(lambda: [0.0] * CURVE_MIN)                      # season -> dunks seen in minute k
        self.exp = defaultdict(lambda: [0.0] * CURVE_MIN)                      # season -> dunks the rates expected
        self.tinfo: dict[str, dict] = {}

    def _w(self, season):
        return ((season, 1.0), (season - 1, self.prev_w))

    def _sum(self, table, season, f):
        return sum(w * f(table[s]) for s, w in self._w(season) if s in table)

    def mpg(self, aid, season):
        t = self.pl.get(aid)
        if not t:
            return None
        g = self._sum(t, season, lambda r: r["g"])
        return self._sum(t, season, lambda r: r["min"]) / g if g else None

    def pos_rate(self, group, season):
        dk = mn = 0.0
        for s, w in self._w(season):
            if s in self.pos:
                for gname, (d, m_) in self.pos[s].items():
                    if group is None or gname == group:
                        dk += w * d
                        mn += w * m_
        if mn < 2000 and group is not None:
            return self.pos_rate(None, season)
        return dk / mn if mn else 0.004

    def lam(self, aid, pos, season):
        t = self.pl.get(aid) or {}
        dk = self._sum(t, season, lambda r: r["dk"])
        mn = self._sum(t, season, lambda r: r["min"])
        return (dk + self.prior_min * self.pos_rate(POS_GROUP.get(pos), season)) / (mn + self.prior_min)

    def league_curve(self, role, tier, season):
        sm, n, mins = [0.0] * CURVE_MIN, 0.0, 0.0
        for s, w in self._w(season):
            if s in self.lcurve and (role, tier) in self.lcurve[s]:
                c, cn, cm = self.lcurve[s][(role, tier)]
                sm = [a + w * b for a, b in zip(sm, c)]
                n += w * cn
                mins += w * cm
        if n < 20:
            flat = (1.0 if role else 0.25)
            return [flat] * CURVE_MIN, (30.0 if role else 14.0)
        return [x / n for x in sm], mins / n

    def curve(self, aid, role, season):
        """(share of each of the first 24 minutes on the floor, share of the last 24) in a role."""
        lc, lmin = self.league_curve(role, bucket(role, self.mpg(aid, season)), season)
        t = self.pl.get(aid) or {}
        n = self._sum(t, season, lambda r: r["cn"][role])
        k = self.curve_k
        c = [(self._sum(t, season, lambda r, j=j: r["c"][role][j]) + k * lc[j]) / (n + k) for j in range(CURVE_MIN)]
        mins = (self._sum(t, season, lambda r: r["rm"][role]) + k * lmin) / (n + k)
        after = min(1.0, max(0.02, (mins - sum(c)) / (GAME_MIN - CURVE_MIN)))
        return c, after

    def dfac(self, tid, season):
        """Dunks this team allows a game, over the league's average."""
        ld = self._sum(self.lg, season, lambda r: r[0])
        lgm = self._sum(self.lg, season, lambda r: r[1])
        if not lgm or not self.def_k:
            return 1.0
        avg = ld / (2 * lgm)
        t = {s: v[tid] for s, v in self.team.items() if tid in v}
        a = self._sum(t, season, lambda r: r[0])
        g = self._sum(t, season, lambda r: r[1])
        return ((a + self.def_k * avg) / (g + self.def_k)) / avg if avg else 1.0

    def mult(self, season):
        """The league's dunk rate in each minute, over what the players' rates expect."""
        if not self.use_m:
            return [1.0] * GAME_MIN
        o = [self._sum(self.obs, season, lambda r, j=j: r[j]) for j in range(CURVE_MIN)]
        e = [self._sum(self.exp, season, lambda r, j=j: r[j]) for j in range(CURVE_MIN)]
        return [(o[j] + 30) / (e[j] + 30) for j in range(CURVE_MIN)] + [1.0] * (GAME_MIN - CURVE_MIN)

    def entries(self, game, lineup=None):
        """Pricing rows for a game. lineup: {aid: (team id, pos, starter)}; the box score's by default."""
        if lineup is None:
            lineup = {aid: (p[1], p[2], p[3]) for aid, p in game["p"].items()}
        tids = list(game["teams"])
        out = []
        for aid, (tid, pos, st) in lineup.items():
            opp = tids[1] if tid == tids[0] else tids[0]
            c, after = self.curve(aid, st, game["s"])
            out.append({"id": aid, "t": tid, "st": st, "lam": self.lam(aid, pos, game["s"]),
                        "d": self.dfac(opp, game["s"]), "curve": c, "after": after})
        return out

    def update(self, game, ent=None):
        s = game["s"]
        ent = ent or self.entries(game)
        tids = list(game["teams"])
        if game.get("ok"):
            for e in ent:
                cv = game["p"][e["id"]][6]
                for j in range(CURVE_MIN):
                    self.exp[s][j] += e["lam"] * e["d"] * (ord(cv[j]) - 48) / 9
            for t, _aid in game["dunks"]:
                if t < CURVE_MIN * 60:
                    self.obs[s][int(t // 60)] += 1
        got = defaultdict(int)
        for aid, (name, tid, pos, st, mn, dk, cv) in game["p"].items():
            tier = bucket(st, self.mpg(aid, s))
            r = self.pl[aid][s]
            r["min"] += mn
            r["dk"] += dk
            r["g"] += 1
            if game.get("ok"):
                on = [(ord(ch) - 48) / 9 for ch in cv]
                r["c"][st] = [a + b for a, b in zip(r["c"][st], on)]
                r["cn"][st] += 1
                r["rm"][st] += mn
                lc = self.lcurve[s][(st, tier)]
                lc[0] = [a + b for a, b in zip(lc[0], on)]
                lc[1] += 1
                lc[2] += mn
            grp = POS_GROUP.get(pos)
            if grp:
                self.pos[s][grp][0] += dk
                self.pos[s][grp][1] += mn
            got[tid] += dk
            m = self.meta.setdefault(aid, {"recent": []})
            m.update(n=name, pos=pos, t=tid, d=game["d"])
            m["recent"] = (m["recent"] + [(st, mn)])[-5:]
        for tid in tids:
            opp = tids[1] if tid == tids[0] else tids[0]
            self.team[s][tid][0] += got[opp]
            self.team[s][tid][1] += 1
            self.tinfo[tid] = {"a": game["teams"][tid]["a"], "d": game["d"],
                               "dates": ((self.tinfo.get(tid) or {}).get("dates") or [])[-2:] + [game["d"]],
                               "st": [aid for aid, p in game["p"].items() if p[1] == tid and p[3]]}
        self.lg[s][0] += len(game["dunks"])
        self.lg[s][1] += 1


# --------------------------------------------------------------------------
# Backtest: price every game from what was known before it
# --------------------------------------------------------------------------
EDGES = [0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 1.01]


def backtest(games, verbose=True, gamma=None, **kw):
    st = State(**kw)
    first = min(g["s"] for g in games)
    n = 0
    ll = ll_u = ll_b = 0.0
    top = 0
    cal = [[0, 0.0, 0] for _ in EDGES[:-1]]
    grp = defaultdict(lambda: [0.0, 0])
    nodunk = late = 0
    for g in games:
        ent = st.entries(g)
        if g["s"] > first and g.get("ok"):
            if not g["dunks"]:
                nodunk += 1
            else:
                t1, who = g["dunks"][0]
                probs, _ = price(ent, st.mult(g["s"]), gamma)
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
                top += 1 if max(probs, key=probs.get) == who else 0
                late += 1 if t1 >= 720 else 0
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
                                "home" if g["teams"][e["t"]]["h"] else "away"):
                        grp[key][0] += pr
                        grp[key][1] += hit
        st.update(g, ent)
    res = {"n": n, "ll": ll / n, "ll_even": ll_u / n, "ll_dpg": ll_b / n, "top": top / n,
           "no_dunk": nodunk, "after_q1": late / n,
           "cal": [{"lo": EDGES[i], "hi": min(1.0, EDGES[i + 1]), "n": c[0],
                    "pred": c[1] / c[0] if c[0] else None, "hit": c[2] / c[0] if c[0] else None}
                   for i, c in enumerate(cal)],
           "groups": {k: {"pred": v[0] / n, "hit": v[1] / n} for k, v in sorted(grp.items())}}
    if verbose:
        print(f"{n} games priced from what was known before each ({nodunk} more had no dunk)")
        print(f"log loss  model {res['ll']:.4f}   starters by dunks a game {res['ll_dpg']:.4f}   ten starters evenly {res['ll_even']:.4f}")
        print(f"top pick made the first dunk {100 * res['top']:.1f}%   first dunk after Q1 {100 * res['after_q1']:.1f}%")
        print("priced at      players   avg priced   made it")
        for c in res["cal"]:
            if c["n"]:
                print(f"  {100 * c['lo']:4.0f}-{100 * c['hi']:3.0f}%  {c['n']:7d}   {100 * c['pred']:8.2f}%  {100 * c['hit']:7.2f}%")
        print("share of first dunks   priced   happened")
        for k, v in res["groups"].items():
            print(f"  {k:10s} {100 * v['pred']:14.1f}% {100 * v['hit']:9.1f}%")
    return res


def tune(games):
    base = dict(prior_min=PRIOR_MIN, prev_w=PREV_W, curve_k=CURVE_K, def_k=DEF_K, use_m=True)
    grid = {"prior_min": [100, 250, 500, 1000], "prev_w": [0.25, 0.5, 0.75, 1.0],
            "curve_k": [2, 4, 8], "def_k": [0, 10, 20, 40], "use_m": [True, False]}
    for key, vals in grid.items():
        for v in vals:
            r = backtest(games, verbose=False, **{**base, key: v})
            print(f"{key:10s} {str(v):6s} log loss {r['ll']:.4f}  top {100 * r['top']:.1f}%")


# --------------------------------------------------------------------------
# Build the page's file
# --------------------------------------------------------------------------
def build(games, roster: dict | None):
    st = State()
    for g in games:
        st.update(g)
    season = max(g["s"] for g in games)
    r3 = lambda xs: [round(x, 3) for x in xs]  # noqa: E731
    teams = {}
    for tid, info in st.tinfo.items():
        if tid not in st.team[season]:
            continue
        a, gm = st.team[season][tid]
        teams[info["a"]] = {"id": tid, "d": round(st.dfac(tid, season), 3), "allowed": a, "g": gm,
                            "last": info["d"], "since": info["dates"][0], "starters": info["st"]}
    abbr = {v["id"]: k for k, v in teams.items()}
    players = {}
    for aid, m in st.meta.items():
        t = st.pl[aid]
        if season not in t and (season - 1) not in t:
            continue
        tid = (roster or {}).get(aid, {}).get("team_id") or (m["t"] if not roster else None)
        if tid not in abbr:
            continue
        cur = t.get(season) or {"g": 0, "min": 0, "dk": 0}
        prev = t.get(season - 1) or {"g": 0, "min": 0, "dk": 0}
        cs, a_s = st.curve(aid, 1, season)
        cb, a_b = st.curve(aid, 0, season)
        players[aid] = {
            "n": m["n"], "t": abbr[tid], "pos": m["pos"],
            "g": cur["g"], "min": int(cur["min"]), "dk": cur["dk"],
            "pg": prev["g"], "pmin": int(prev["min"]), "pdk": prev["dk"],
            "lam": round(st.lam(aid, m["pos"], season), 5),
            "rs": sum(1 for s_, _ in m["recent"] if s_), "rn": len(m["recent"]),
            "last": m["d"], "cs": r3(cs), "as": round(a_s, 3), "cb": r3(cb), "ab": round(a_b, 3),
        }
    firsts = sorted(g["dunks"][0][0] for g in games if g["s"] >= season - 1 and g["dunks"])
    lg = st.lg[season]
    bt = backtest(games, verbose=False)
    return {
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "season": season, "games": len(games), "through": games[-1]["d"],
        "m": r3(st.mult(season)),
        "league": {"dunks_pg": round(lg[0] / lg[1], 2) if lg[1] else None,
                   "first_median_sec": firsts[len(firsts) // 2] if firsts else None,
                   "first_in_q1": round(sum(1 for x in firsts if x < 720) / len(firsts), 3) if firsts else None},
        "params": {"prior_min": PRIOR_MIN, "prev_w": PREV_W, "curve_k": CURVE_K, "def_k": DEF_K, "gamma": GAMMA},
        "backtest": bt, "teams": teams, "players": players,
    }, st


def write_fixture(games):
    """One real game priced from the games before it, for the JS check."""
    st = State()
    for g in games[:-1]:
        st.update(g)
    g = games[-1]
    ent = st.entries(g)
    m = st.mult(g["s"])
    probs, alive = price(ent, m)
    with open(FIXTURE, "w") as fh:
        json.dump({"game": g["id"], "m": m, "entries": ent, "probs": probs, "no_dunk": alive}, fh, separators=(",", ":"))
    print(f"wrote {FIXTURE}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="pull new final games from ESPN first")
    ap.add_argument("--seasons", type=int, nargs="+", default=None,
                    help="seasons to pull (default: the last one in the games file and the next)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--fixture", action="store_true")
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
        return tune(games)
    if args.backtest:
        backtest(games)
        return
    if args.fixture:
        return write_fixture(games)
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
