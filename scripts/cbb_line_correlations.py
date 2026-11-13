#!/usr/bin/env python3
"""College basketball: how often two game-line legs hit together, measured on
final scores against closing lines. Feeds the CBB board of the Novig Scan
(.claude/skills/nba-sgp-fv/scan.py --league cbb).

  python3 scripts/cbb_line_correlations.py --fetch 2024 2025 2026   # seasons by the year they end; adds missing days
  python3 scripts/cbb_line_correlations.py                          # rebuild the correlations from the games on disk

Games (public/data/cbb_game_lines.json): every Division I final from ESPN's
scoreboard, with halftime scores, and the closing spread and total from
ESPN's odds feed (one call a game; the book is DraftKings for nearly all).
Rows: [date, id, home, away, home 1H, away 1H, home's spread, total].

Correlations (public/data/cbb_line_correlations.json): for each slip shape
the board asks, by size of spread, the copula correlation r of the two
legs' hit / miss record: the r at which a Gaussian copula with the legs' own
hit rates gives the share of games where both hit. Pushes are left out.
Posted team totals and first-half spreads aren't in the feed, so a team's
total line is (total -/+ spread) / 2 and the first-half spread is the
closing spread times the slope of first-half margin on it. r describes how
the legs move together, not where the lines sit, so the board applies it to
each leg's real price.
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import math
import os
import sys
import time
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-ast-pts-sgp"))
import sgp  # noqa: E402  devig_r, joint

GAMES = os.path.join(ROOT, "public", "data", "cbb_game_lines.json")
OUT = os.path.join(ROOT, "public", "data", "cbb_line_correlations.json")
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/events"
BUCKETS = [(0, 6), (6, 12), (12, 20), (20, 99)]   # by the closing spread, points


def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                return json.load(r)
        except Exception:
            if i == 3:
                return None
            time.sleep(1 + 2 * i)


def day(d):
    """A date's finals: [date, id, home, away, home 1H, away 1H], or None when ESPN didn't answer."""
    j = get(f"{SITE}?dates={d}&groups=50&limit=400")
    if j is None:
        return None
    out = []
    for e in j.get("events", []):
        c = e["competitions"][0]
        if c["status"]["type"]["name"] != "STATUS_FINAL":
            continue
        t = {x["homeAway"]: x for x in c["competitors"]}
        try:
            half = [int(t[k]["linescores"][0]["value"]) for k in ("home", "away")]
        except (KeyError, IndexError, ValueError, TypeError):
            half = [None, None]
        out.append([d, e["id"], int(t["home"]["score"]), int(t["away"]["score"])] + half)
    return out


def odds(g):
    o = get(f"{CORE}/{g[1]}/competitions/{g[1]}/odds")
    for it in (o or {}).get("items", []):
        if it.get("spread") is not None and it.get("overUnder") is not None:
            return g + [it["spread"], it["overUnder"]]
    return g + [None, None]


def fetch(seasons):
    have = json.load(open(GAMES)) if os.path.exists(GAMES) else {"days": [], "games": []}
    done, today = set(have["days"]), datetime.date.today()
    want = []
    for y in seasons:
        d = datetime.date(y - 1, 11, 1)
        while d <= min(datetime.date(y, 4, 10), today - datetime.timedelta(days=2)):
            if d.strftime("%Y%m%d") not in done:
                want.append(d.strftime("%Y%m%d"))
            d += datetime.timedelta(days=1)
    with cf.ThreadPoolExecutor(8) as ex:
        for i in range(0, len(want), 20):
            chunk = want[i:i + 20]
            days = list(ex.map(day, chunk))
            new = [g for gs in days if gs for g in gs]
            have["games"] += list(ex.map(odds, new))
            have["days"] += [d for d, gs in zip(chunk, days) if gs is not None]
            json.dump(have, open(GAMES, "w"), separators=(",", ":"))
            print(f"{min(i + 20, len(want))} / {len(want)} days, {len(have['games'])} games", file=sys.stderr, flush=True)


def build():
    rows = [g for g in json.load(open(GAMES))["games"] if g[6] is not None and g[7] and g[7] > 90 and abs(g[6]) < 50]
    G = []   # favourite's and underdog's score against their own lines, and the first half
    for d, _, h, a, h1, a1, sp, tot in rows:
        s = abs(sp)
        f, u, f1, u1 = (h, a, h1, a1) if sp < 0 else (a, h, a1, h1)
        G.append({"s": s, "tot": tot, "m": f - u - s, "t": f + u - tot, "ef": f - (tot + s) / 2, "eu": u - (tot - s) / 2,
                  "m1": None if f1 is None else f1 - u1})
    # First-half spread: the slope of first-half margin on the closing spread.
    H = [g for g in G if g["m1"] is not None]
    slope = sum(g["m1"] * g["s"] for g in H) / sum(g["s"] ** 2 for g in H)
    for g in H:
        g["h"] = g["m1"] - slope * g["s"]
    # Each shape: the two legs as (value, sign); a leg hits when sign x value > 0, a 0 is a push.
    shapes = {
        "fav_cover+over": (("m", 1), ("t", 1)), "dog_cover+under": (("m", -1), ("t", -1)),
        "dog_cover+dog_tt_under": (("m", -1), ("eu", -1)), "fav_cover+fav_tt_over": (("m", 1), ("ef", 1)),
        "fav_tt_under+under": (("ef", -1), ("t", -1)), "dog_tt_under+under": (("eu", -1), ("t", -1)),
        "fav_tt_over+over": (("ef", 1), ("t", 1)), "dog_tt_over+over": (("eu", 1), ("t", 1)),
        "fav_tt_under+dog_tt_under": (("ef", -1), ("eu", -1)), "fav_tt_over+dog_tt_over": (("ef", 1), ("eu", 1)),
        "fav_1h_cover+fav_cover": (("h", 1), ("m", 1)), "dog_1h_cover+dog_cover": (("h", -1), ("m", -1)),
    }

    def measure(games, legs):
        (ka, sa), (kb, sb) = legs
        v = [(sa * g[ka] > 0, sb * g[kb] > 0) for g in games if g.get(ka) is not None and g.get(kb) is not None and g[ka] != 0 and g[kb] != 0]
        n = len(v)
        if n < 150:
            return None
        pa, pb, j = sum(x for x, _ in v) / n, sum(y for _, y in v) / n, sum(x and y for x, y in v) / n
        r, se = sgp.devig_r(j, pa, pb), math.sqrt(j * (1 - j) / n)
        return {"n": n, "pa": round(pa, 4), "pb": round(pb, 4), "both": round(j, 4), "se": round(se, 4), "r": round(r, 3),
                "r_lo": round(sgp.devig_r(max(j - 2 * se, 1e-4), pa, pb), 3), "r_hi": round(sgp.devig_r(j + 2 * se, pa, pb), 3)}
    out = {"generated_at": time.strftime("%Y-%m-%d"), "games": len(G), "first_half_slope": round(slope, 3),
           "days": [rows[0][0], max(r[0] for r in rows)], "buckets": BUCKETS, "shapes": {}}
    for name, legs in shapes.items():
        out["shapes"][name] = {"all": measure(G, legs),
                               "by_spread": [measure([g for g in G if lo <= g["s"] < hi], legs) for lo, hi in BUCKETS]}
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"{len(G)} games with a closing spread and total, {len(H)} with a halftime score; 1H spread = {slope:.3f} x spread")
    for name, v in out["shapes"].items():
        a = v["all"]
        print(f"{name:28s} n {a['n']:6d}  both {a['both']:.3f} ±{a['se']:.3f}  r {a['r']:+.3f} ({a['r_lo']:+.2f} to {a['r_hi']:+.2f})  by spread: "
              + "  ".join("  -  " if b is None else f"{b['r']:+.2f}" for b in v["by_spread"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", type=int, nargs="+", metavar="SEASON", help="seasons to add, by the year they end (2026 = 2025-26)")
    a = ap.parse_args()
    if a.fetch:
        fetch(a.fetch)
    build()
