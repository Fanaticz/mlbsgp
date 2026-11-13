#!/usr/bin/env python3
"""Pinnacle's no-vig soccer prices, for the legs of the corners slips.

  python3 pinnacle.py Albania     # one match: 3-way, goals totals, team corners

Novig's own corner books are often 10c to 16c wide, and the middle of a book
that wide is not a price: 11-12 Albania v Finland, Novig's middle said 49% on
Albania Under 4.5 corners where Pinnacle offered +107 (48.3% before any
margin, 45% after). Pinnacle posts two-way prices on every line, so the
soccer scan reads each leg's fair value here and keeps Novig's book only
where Pinnacle has no such line.

Two calls for the whole soccer board (matches, then prices), public guest
API, standard library only. Corners are a child match ("Albania (Corners)")
of the main one.
"""
import difflib
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import novig  # noqa: E402  norm
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nba-ast-pts-sgp"))
import sgp  # noqa: E402  devig_worst

API = "https://guest.api.arcadia.pinnacle.com/0.1"
KEY = os.environ.get("PINNACLE_GUEST_KEY", "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi2R")  # the public site's own key
SOCCER = 29
ML_GAP = 0.06   # a match whose 3-way price is this far from Novig's is not the same match


def get(path):
    req = urllib.request.Request(API + path, headers={"X-API-Key": KEY, "Accept": "application/json",
                                                      "User-Agent": "Mozilla/5.0"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception:
            if i == 2:
                raise
            time.sleep(1 + i)


def implied(american):
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


def two_way(prices):
    """{'over': (fair chance, American price), 'under': ...} or None."""
    by = {p.get("designation"): p.get("price") for p in prices}
    o, u = by.get("over"), by.get("under")
    if not isinstance(o, (int, float)) or not isinstance(u, (int, float)):
        return None
    fo, fu = sgp.devig_worst(implied(o), implied(u))
    return {"over": (fo, int(o)), "under": (fu, int(u))}


def board():
    """Every pregame soccer match: [{home, away, start (epoch s), ml: {home/away:
    (fair, price)}, goals: {line: two_way}, corners: {(side, line): two_way}}]."""
    games, kids = {}, {}
    for m in get(f"/sports/{SOCCER}/matchups?withSpecials=false&brandId=0"):
        if m.get("type") != "matchup" or m.get("isLive"):
            continue
        if m.get("parentId"):
            if m.get("units") == "Corners":
                kids[m["id"]] = m["parentId"]
            continue
        ps = {p.get("alignment"): p.get("name") for p in m.get("participants", [])}
        if not ps.get("home") or not ps.get("away"):
            continue
        try:
            start = time.mktime(time.strptime(m["startTime"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
        except Exception:
            continue
        games[m["id"]] = {"home": ps["home"], "away": ps["away"], "start": start, "ml": {}, "goals": {}, "corners": {}}
    for mk in get(f"/sports/{SOCCER}/markets/straight?primaryOnly=false&withSpecials=false"):
        if mk.get("period") != 0 or mk.get("status", "open") != "open":
            continue
        mid, prices, kind = mk.get("matchupId"), mk.get("prices") or [], mk.get("type")
        line = next((p.get("points") for p in prices if p.get("points") is not None), None)
        if mid in games:
            g = games[mid]
            if kind == "moneyline":
                by = {p.get("designation"): p.get("price") for p in prices}
                if all(isinstance(by.get(k), (int, float)) for k in ("home", "draw", "away")):
                    tot = sum(implied(by[k]) for k in ("home", "draw", "away"))
                    g["ml"] = {k: (implied(by[k]) / tot, int(by[k])) for k in ("home", "away")}
            elif kind == "total" and line is not None and two_way(prices):
                g["goals"][float(line)] = two_way(prices)
        elif kids.get(mid) in games and kind == "team_total" and mk.get("side") in ("home", "away") \
                and line is not None and two_way(prices):
            games[kids[mid]]["corners"][(mk["side"], float(line))] = two_way(prices)
    return [g for g in games.values() if g["ml"]]


COLLEGE = {"NCAAB": 493, "NCAAF": 880}   # Pinnacle's league ids


def lines(league):
    """Every pregame game in a college league, with each two-way line's no-vig
    price: [{home, away, start (epoch s), mk: {(period, kind, side, points):
    {designation: (fair chance, American price)}}}]. period 0 is the game, 1
    the first half. kind 'spread' is keyed by the home team's points
    (designations home / away), 'total' by the line (over / under),
    'team_total' by side ('home' / 'away') and line, 'moneyline' by nothing.
    Two calls, alt lines included."""
    lg = COLLEGE[league]
    games = {}
    for m in get(f"/leagues/{lg}/matchups?brandId=0"):
        if m.get("type") != "matchup" or m.get("isLive") or m.get("parentId"):
            continue
        ps = {p.get("alignment"): p.get("name") for p in m.get("participants", [])}
        if not ps.get("home") or not ps.get("away"):
            continue
        try:
            start = time.mktime(time.strptime(m["startTime"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
        except Exception:
            continue
        games[m["id"]] = {"home": ps["home"], "away": ps["away"], "start": start, "mk": {}}
    for mk in get(f"/leagues/{lg}/markets/straight?primaryOnly=false"):
        g, kind, prices = games.get(mk.get("matchupId")), mk.get("type"), mk.get("prices") or []
        if not g or mk.get("period") not in (0, 1) or mk.get("status", "open") != "open" or len(prices) != 2:
            continue
        a, b = prices
        if not all(isinstance(x.get("price"), (int, float)) for x in prices):
            continue
        fa, fb = sgp.devig_worst(implied(a["price"]), implied(b["price"]))
        if kind == "spread":
            pts = next((x.get("points") for x in prices if x.get("designation") == "home"), None)
            side = None
        elif kind in ("total", "team_total"):
            pts, side = a.get("points"), mk.get("side") if kind == "team_total" else None
        elif kind == "moneyline":
            pts, side = 0.0, None
        else:
            continue
        if pts is None or (kind == "team_total" and side not in ("home", "away")):
            continue
        g["mk"][(mk["period"], kind, side, float(pts))] = {a["designation"]: (fa, int(a["price"])), b["designation"]: (fb, int(b["price"]))}
    return [g for g in games.values() if g["mk"]]


def college_match(games, away, home, start):
    """Pinnacle's game for Novig's "away @ home", or None: same tip (10 min)
    and both names close. `away` / `home` are lists of the names Novig uses
    for each team (its short code and, where it lists a team total, the full name)."""
    best = (0.0, None)
    for g in games:
        if abs(g["start"] - start) > 600:
            continue
        s = max(alike(n, g["away"]) for n in away) + max(alike(n, g["home"]) for n in home)
        if s > best[0]:
            best = (s, g)
    return best[1] if best[0] >= 1.3 else None


def alike(a, b):
    a, b = novig.norm(a), novig.norm(b)
    if a == b:
        return 1.0
    if a and b and (a in b or b in a):
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def match(games, fav, dog, start, p_fav):
    """(game, favourite's side) for Novig's match, or (None, None). Same
    kickoff, both names close, and a 3-way price near Novig's: a wrong match
    would price the slip off another game."""
    best = (0.0, None, None)
    for g in games:
        if abs(g["start"] - start) > 600:
            continue
        for side, other in (("home", "away"), ("away", "home")):
            s = alike(fav, g[side]) + alike(dog, g[other])
            if s > best[0]:
                best = (s, g, side)
    s, g, side = best
    if g is None or s < 1.3 or abs(g["ml"][side][0] - p_fav) > ML_GAP:
        return None, None
    return g, side


def main():
    want = novig.norm(" ".join(sys.argv[1:]))
    for g in board():
        if want and want not in novig.norm(g["home"]) and want not in novig.norm(g["away"]):
            continue
        print(f"{g['home']} v {g['away']} · {time.strftime('%m-%d %H:%M UTC', time.gmtime(g['start']))}")
        for k in ("home", "away"):
            print(f"  {g[k]} win: {g['ml'][k][1]:+d}, fair {g['ml'][k][0]:.1%}")
        for line, t in sorted(g["goals"].items()):
            if line % 1 == 0.5:
                print(f"  goals {line}: Over {t['over'][1]:+d} / Under {t['under'][1]:+d}, fair Over {t['over'][0]:.1%}")
        for (side, line), t in sorted(g["corners"].items()):
            print(f"  {g[side]} corners {line}: Over {t['over'][1]:+d} / Under {t['under'][1]:+d}, "
                  f"fair Over {t['over'][0]:.1%} / Under {t['under'][0]:.1%}")


if __name__ == "__main__":
    main()
