#!/usr/bin/env python3
"""NBA: how often two legs of a slip hit together where one or both are game
lines, measured on final scores against closing lines. Feeds the NBA Team
board of the Novig Scan (.claude/skills/nba-sgp-fv/scan.py --league nbateam).

  python3 scripts/nba_line_correlations.py --fetch 2024 2025 2026 2027   # seasons by the year they end; adds missing days
  python3 scripts/nba_line_correlations.py --fetch                       # this season's new games (the daily refresh)
  python3 scripts/nba_line_correlations.py                               # rebuild the correlations from the games on disk

Games (public/data/nba_game_lines.json): every regular-season and playoff
final from ESPN's scoreboard with its quarter scores, and the closing spread
and total from ESPN's odds feed (one call a game; DraftKings for nearly all).
Rows: [day asked, id, UTC date, home, away, home quarters, away quarters,
home's spread, total].

Correlations (public/data/nba_line_correlations.json):

shapes: slips across one game's own lines, as scripts/cbb_line_correlations.py
measures them: for each shape, overall and by size of spread, the share of
games both legs hit and the Gaussian-copula r that reproduces it. Posted team
totals and first-half lines aren't in the feed: a team's total line is
(total -/+ spread) / 2, the first-half spread and total are the closing
ones times the fitted slope.

props: a player's prop with a game line, league-wide by role. Box scores
(public/data/nba_game_boxes.json, one ESPN summary call a game): {game id:
{team: [[athlete id, minutes, points, rebounds, assists, threes], ...]}}.
His line is not in any feed, so the leg is "over his own median that
season" (points, rebounds, assists, threes, points + rebounds + assists;
players with 20+ games at 20+ minutes in the season) against: his team
covers, the game goes over, his team's total goes over, the other team's
total goes over, his team covers the first half, the first half goes over.
Roles are his season average of the stat. The r with a spread depends on
who is favoured (a 25-point scorer's points go against his team covering
as a 10-point favourite, -0.27, and with it as an underdog, +0.4), so each
role has r in seven bands of his team's spread and a straight-line fit,
r = a + b x spread, which the board reads at tonight's spread (held
between lo and hi, the average spreads of the outermost bands with games).
The fit's standard error at a spread x is sqrt(a_se^2 + ((x - x0) b_se)^2);
the board prices at the fit less one of those. Fitted on three seasons and
tested on the fourth, each in turn (11-13): slips at a fit r of 0.42+ hit
30.5% of the time where the fit said 31.5% and the fit less one standard
error 30.3%; in every other group the plain fit was within 1% and the
haircut 2.5% to 5% under.
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
import sgp  # noqa: E402  joint

GAMES = os.path.join(ROOT, "public", "data", "nba_game_lines.json")
BOXES = os.path.join(ROOT, "public", "data", "nba_game_boxes.json")
OUT = os.path.join(ROOT, "public", "data", "nba_line_correlations.json")
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events"
BUCKETS = [(0, 4), (4, 8), (8, 12), (12, 99)]   # by the closing spread, points


def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                return json.load(r)
        except Exception:
            if i == 3:
                return None
            time.sleep(1 + 2 * i)


def copula_r(j, a, b):
    """The Gaussian-copula r at which legs hitting a and b of the time both
    hit j of the time (sgp.joint, solved by bisection). Not sgp.devig_r:
    that is the devig tool's own scale, about two thirds of this."""
    lo, hi = -0.999, 0.999
    for _ in range(50):
        mid = (lo + hi) / 2
        if sgp.joint(mid, a, b) < j:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def day(d):
    """A date's finals, or None when ESPN didn't answer."""
    j = get(f"{SITE}?dates={d}&limit=100")
    if j is None:
        return None
    out = []
    for e in j.get("events", []):
        c = e["competitions"][0]
        if c["status"]["type"]["name"] != "STATUS_FINAL" or e.get("season", {}).get("type") not in (2, 3):
            continue
        t = {x["homeAway"]: x for x in c["competitors"]}
        try:
            q = [[int(l["value"]) for l in t[k]["linescores"]] for k in ("home", "away")]
        except (KeyError, ValueError, TypeError):
            continue
        if len(q[0]) < 4 or len(q[1]) < 4:
            continue
        out.append([d, e["id"], e["date"][:10], t["home"]["team"]["abbreviation"], t["away"]["team"]["abbreviation"]] + q)
    return out


def odds(g):
    o = get(f"{CORE}/{g[1]}/competitions/{g[1]}/odds")
    for it in (o or {}).get("items", []):
        if it.get("spread") is not None and it.get("overUnder") is not None:
            return g + [it["spread"], it["overUnder"]]
    return g + [None, None]


def box(gid):
    """One game's box score: {team: [[athlete id, minutes, points, rebounds, assists, threes], ...]}, or None."""
    j = get(f"{SUMMARY}?event={gid}")
    try:
        out = {}
        for t in j["boxscore"]["players"]:
            st = t["statistics"][0]
            k = {n: i for i, n in enumerate(st["keys"])}
            rows = []
            for a in st["athletes"]:
                v = a.get("stats") or []
                if a.get("didNotPlay") or len(v) < len(k) or not v[k["minutes"]].isdigit() or int(v[k["minutes"]]) == 0:
                    continue
                rows.append([a["athlete"]["id"], int(v[k["minutes"]]), int(v[k["points"]]), int(v[k["rebounds"]]), int(v[k["assists"]]),
                             int(v[k["threePointFieldGoalsMade-threePointFieldGoalsAttempted"]].split("-")[0])])
            out[t["team"]["abbreviation"]] = rows
        return out if len(out) == 2 and all(out.values()) else None
    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
        return None


def fetch_boxes():
    """Box scores for every game on disk that has none yet."""
    games = json.load(open(GAMES))["games"]
    have = json.load(open(BOXES)) if os.path.exists(BOXES) else {}
    want = [g[1] for g in games if g[1] not in have]
    with cf.ThreadPoolExecutor(8) as ex:
        for i in range(0, len(want), 200):
            chunk = want[i:i + 200]
            for gid, b in zip(chunk, ex.map(box, chunk)):
                if b:
                    have[gid] = b
            json.dump(have, open(BOXES, "w"), separators=(",", ":"))
            print(f"{min(i + 200, len(want))} / {len(want)} box scores, {len(have)} on disk", file=sys.stderr, flush=True)


def fetch(seasons):
    have = json.load(open(GAMES)) if os.path.exists(GAMES) else {"days": [], "games": []}
    done, today = set(have["days"]), datetime.date.today()
    want = []
    for y in seasons:
        d = datetime.date(y - 1, 10, 15)
        while d <= min(datetime.date(y, 6, 25), today - datetime.timedelta(days=2)):
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


def measure(v):
    """[(leg a hit, leg b hit)] -> the hit rates, the share both hit and the copula r, or None under 150 games."""
    n = len(v)
    if n < 150:
        return None
    pa, pb, j = sum(x for x, _ in v) / n, sum(y for _, y in v) / n, sum(x and y for x, y in v) / n
    if not 0 < pa < 1 or not 0 < pb < 1:
        return None
    r, se = copula_r(j, pa, pb), math.sqrt(max(j * (1 - j), 1e-9) / n)
    return {"n": n, "pa": round(pa, 4), "pb": round(pb, 4), "both": round(j, 4), "se": round(se, 4), "r": round(r, 3),
            "r_lo": round(copula_r(max(j - 2 * se, 1e-4), pa, pb), 3), "r_hi": round(copula_r(min(j + 2 * se, min(pa, pb) - 1e-4), pa, pb), 3)}


# Slips across a game's own lines: the two legs as (value, sign). A leg hits
# when sign x value > 0; a 0 is a push and the game is left out.
# m: favourite's margin less the spread. t: points less the total. ef / eu:
# the favourite's / underdog's points less their team total. w: the
# favourite's margin. h, ht, w1: the first half's margin less its spread,
# points less its total, and margin.
SHAPES = {
    "fav_cover+over": (("m", 1), ("t", 1)), "fav_cover+under": (("m", 1), ("t", -1)),
    "dog_cover+over": (("m", -1), ("t", 1)), "dog_cover+under": (("m", -1), ("t", -1)),
    "fav_cover+fav_tt_over": (("m", 1), ("ef", 1)), "fav_cover+dog_tt_under": (("m", 1), ("eu", -1)),
    "dog_cover+dog_tt_over": (("m", -1), ("eu", 1)), "dog_cover+fav_tt_under": (("m", -1), ("ef", -1)),
    "dog_cover+dog_tt_under": (("m", -1), ("eu", -1)), "fav_cover+fav_tt_under": (("m", 1), ("ef", -1)),
    "fav_tt_over+over": (("ef", 1), ("t", 1)), "dog_tt_over+over": (("eu", 1), ("t", 1)),
    "fav_tt_under+under": (("ef", -1), ("t", -1)), "dog_tt_under+under": (("eu", -1), ("t", -1)),
    "fav_tt_over+dog_tt_over": (("ef", 1), ("eu", 1)), "fav_tt_under+dog_tt_under": (("ef", -1), ("eu", -1)),
    "fav_tt_over+dog_tt_under": (("ef", 1), ("eu", -1)), "fav_tt_under+dog_tt_over": (("ef", -1), ("eu", 1)),
    "fav_1h_cover+fav_cover": (("h", 1), ("m", 1)), "dog_1h_cover+dog_cover": (("h", -1), ("m", -1)),
    "1h_over+over": (("ht", 1), ("t", 1)), "1h_under+under": (("ht", -1), ("t", -1)),
    "fav_1h_ml+fav_ml": (("w1", 1), ("w", 1)), "dog_1h_ml+dog_ml": (("w1", -1), ("w", -1)),
    "fav_ml+over": (("w", 1), ("t", 1)), "fav_ml+under": (("w", 1), ("t", -1)),
    "dog_ml+over": (("w", -1), ("t", 1)), "dog_ml+under": (("w", -1), ("t", -1)),
    "fav_ml+fav_tt_over": (("w", 1), ("ef", 1)), "dog_ml+dog_tt_over": (("w", -1), ("eu", 1)),
    "fav_ml+dog_tt_under": (("w", 1), ("eu", -1)), "dog_ml+fav_tt_under": (("w", -1), ("ef", -1)),
    "1h_over+fav_cover": (("ht", 1), ("m", 1)), "1h_under+dog_cover": (("ht", -1), ("m", -1)),
    "fav_1h_cover+over": (("h", 1), ("t", 1)), "dog_1h_cover+under": (("h", -1), ("t", -1)),
    "1h_over+fav_tt_over": (("ht", 1), ("ef", 1)), "1h_over+dog_tt_over": (("ht", 1), ("eu", 1)),
    "1h_under+fav_tt_under": (("ht", -1), ("ef", -1)), "1h_under+dog_tt_under": (("ht", -1), ("eu", -1)),
    "fav_1h_cover+fav_tt_over": (("h", 1), ("ef", 1)), "dog_1h_cover+dog_tt_over": (("h", -1), ("eu", 1)),
    "fav_1h_cover+dog_tt_under": (("h", 1), ("eu", -1)), "dog_1h_cover+fav_tt_under": (("h", -1), ("ef", -1)),
    "fav_1h_cover+1h_over": (("h", 1), ("ht", 1)), "dog_1h_cover+1h_under": (("h", -1), ("ht", -1)),
}

# A player's prop with a game line. Roles: his season average of that stat.
PROP_ROLES = {"pts": [0, 10, 15, 20, 25, 99], "reb": [0, 6, 9, 99], "ast": [0, 4, 6.5, 99], "tpm": [0, 1.5, 2.5, 99],
              "pra": [0, 25, 35, 99]}
PROP_EVENTS = {"cover": "his team covers", "over": "the game goes over", "tt": "his team's total goes over",
               "opp_tt": "the other team's total goes over", "h1cover": "his team covers the first half",
               "h1over": "the first half goes over"}
# His team's closing spread (negative: favoured), in bands; the fit is r = a + b x spread, the spread held to +/- SPREAD_CAP.
SPREAD_BANDS = [(-99, -10), (-10, -6), (-6, -2.5), (-2.5, 3), (3, 6.5), (6.5, 10.5), (10.5, 99)]
SPREAD_CAP = 13.0
MIN_GAMES, MIN_MINUTES = 20, 20.0


def build():
    rows = [g for g in json.load(open(GAMES))["games"] if g[7] is not None and g[8]]
    G, by_key = [], {}
    for d, gid, utc, home, away, hq, aq, sp, tot in rows:
        h, a, h1, a1 = sum(hq), sum(aq), hq[0] + hq[1], aq[0] + aq[1]
        s = abs(sp)
        f, u, f1, u1 = (h, a, h1, a1) if sp < 0 else (a, h, a1, h1)
        g = {"s": s, "tot": tot, "m": f - u - s, "t": f + u - tot, "ef": f - (tot + s) / 2, "eu": u - (tot - s) / 2,
             "w": f - u, "m1": f1 - u1, "t1": f1 + u1, "w1": f1 - u1, "sp": sp, "home": (h, h1), "away": (a, a1)}
        G.append(g)
        for dd in (utc, f"{d[:4]}-{d[4:6]}-{d[6:]}"):
            by_key[(dd, home, away)] = g
    # First-half lines: the slopes of first-half margin on the closing spread and of first-half points on the total.
    slope = sum(g["m1"] * g["s"] for g in G) / sum(g["s"] ** 2 for g in G)
    slope_t = sum(g["t1"] * g["tot"] for g in G) / sum(g["tot"] ** 2 for g in G)
    for g in G:
        g["h"], g["ht"] = g["m1"] - slope * g["s"], g["t1"] - slope_t * g["tot"]

    def pair(games, legs):
        (ka, sa), (kb, sb) = legs
        return measure([(sa * g[ka] > 0, sb * g[kb] > 0) for g in games if g[ka] != 0 and g[kb] != 0])
    out = {"generated_at": time.strftime("%Y-%m-%d"), "games": len(G), "first_half_slope": round(slope, 3),
           "first_half_total_slope": round(slope_t, 3), "days": [rows[0][0], max(r[0] for r in rows)], "buckets": BUCKETS, "shapes": {}}
    for name, legs in SHAPES.items():
        out["shapes"][name] = {"all": pair(G, legs), "by_spread": [pair([g for g in G if lo <= g["s"] < hi], legs) for lo, hi in BUCKETS]}

    # Props with a line: each player-season of 20+ games at 20+ minutes a game, from the box scores.
    boxes = json.load(open(BOXES)) if os.path.exists(BOXES) else {}
    logs = {}   # (athlete, season) -> [(minutes, {stat: value}, his team's spread, {event: margin over its line})]
    for (d, gid, utc, home, away, hq, aq, sp, tot), g in zip(rows, G):
        b = boxes.get(gid)
        if not b or home not in b or away not in b:
            continue
        season = int(d[:4]) + (1 if int(d[4:6]) >= 9 else 0)
        for team, mine, theirs, my_sp in ((home, g["home"], g["away"], sp), (away, g["away"], g["home"], -sp)):
            ev = {"cover": mine[0] - theirs[0] + my_sp, "over": g["t"], "tt": mine[0] - (tot - my_sp) / 2,
                  "opp_tt": theirs[0] - (tot + my_sp) / 2, "h1cover": mine[1] - theirs[1] + slope * my_sp, "h1over": g["ht"]}
            for aid, mn, pts, reb, ast, tpm in b[team]:
                logs.setdefault((aid, season), []).append((mn, {"pts": pts, "reb": reb, "ast": ast, "tpm": tpm, "pra": pts + reb + ast}, my_sp, ev))
    obs, seasons = {s: [] for s in PROP_ROLES}, 0   # (his season average, his team's spread, leg hit, events)
    for rs in logs.values():
        if len(rs) < MIN_GAMES or sum(r[0] for r in rs) / len(rs) < MIN_MINUTES:
            continue
        seasons += 1
        for s in PROP_ROLES:
            v = sorted(r[1][s] for r in rs)
            med = v[len(v) // 2]
            # His line: the half-point beside his median whose Over is nearer half his games.
            line = min((med - 0.5, med + 0.5), key=lambda L: abs(sum(x > L for x in v) / len(v) - 0.5))
            if line < 0:
                continue
            avg = sum(v) / len(v)
            obs[s] += [(avg, r[2], r[1][s] > line, r[3]) for r in rs]
    props = []
    for s, cuts in PROP_ROLES.items():
        for lo, hi in zip(cuts, cuts[1:]):
            role = [o for o in obs[s] if lo <= o[0] < hi]
            for e in PROP_EVENTS:
                every = measure([(o[2], o[3][e] > 0) for o in role if o[3][e] != 0])
                if not every:
                    continue
                bands, pts = [], []
                for a, b in SPREAD_BANDS:
                    cell = [o for o in role if a <= o[1] < b and o[3][e] != 0]
                    m = measure([(o[2], o[3][e] > 0) for o in cell])
                    bands.append(m)
                    if m:
                        x = sum(max(-SPREAD_CAP, min(SPREAD_CAP, o[1])) for o in cell) / len(cell)
                        pts.append((x, m["r"], 1 / max((m["r_hi"] - m["r_lo"]) / 4, 0.01) ** 2))
                # r against his team's spread: a weighted straight line through the bands.
                w, wx, wy = sum(p[2] for p in pts), sum(p[2] * p[0] for p in pts), sum(p[2] * p[1] for p in pts)
                sxx = sum(p[2] * (p[0] - wx / w) ** 2 for p in pts)
                slope_r = sum(p[2] * (p[0] - wx / w) * (p[1] - wy / w) for p in pts) / sxx if len(pts) >= 4 and sxx > 0 else 0.0
                se_b = math.sqrt(1 / sxx) if sxx > 0 else 9.0
                props.append({"stat": s, "min": lo, "max": hi, "ev": e, "all": every, "by_spread": bands,
                              "fit": {"a": round(wy / w - slope_r * wx / w, 4), "b": round(slope_r, 5), "b_se": round(se_b, 5),
                                      "x0": round(wx / w, 3), "a_se": round(math.sqrt(1 / w), 4),
                                      "lo": round(min(p[0] for p in pts), 2), "hi": round(max(p[0] for p in pts), 2)}})
    out.update(player_seasons=seasons, prop_events=PROP_EVENTS, spread_bands=SPREAD_BANDS, spread_cap=SPREAD_CAP, props=props)
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"{len(G)} games with a closing spread and total; 1H spread = {slope:.3f} x spread, 1H total = {slope_t:.3f} x total")
    for name, v in out["shapes"].items():
        a = v["all"]
        print(f"{name:28s} n {a['n']:5d}  both {a['both']:.3f} ±{a['se']:.3f}  r {a['r']:+.3f} ({a['r_lo']:+.2f} to {a['r_hi']:+.2f})  by spread: "
              + "  ".join("  -  " if b is None else f"{b['r']:+.2f}" for b in v["by_spread"]))
    print(f"{seasons} player-seasons, {sum(len(v) for v in obs.values())} player-game legs; r by his team's spread, big favourite to big underdog")
    for e in props:
        f = e["fit"]
        print(f"{e['stat']:4s} {e['min']:4g}-{e['max']:<4g} {e['ev']:8s} n {e['all']['n']:6d}  r {e['all']['r']:+.2f}  "
              + " ".join("  -  " if b is None else f"{b['r']:+.2f}" for b in e["by_spread"])
              + f"   fit {f['a']:+.3f} {f['b']:+.4f}/pt (±{f['b_se']:.4f}): -10 {f['a'] - 10 * f['b']:+.2f}, +10 {f['a'] + 10 * f['b']:+.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", type=int, nargs="*", metavar="SEASON",
                    help="seasons to add, by the year they end (2027 = 2026-27); no year: the season being played")
    a = ap.parse_args()
    if a.fetch is not None:
        today = datetime.date.today()
        fetch(a.fetch or [today.year + (today.month >= 9)])
        fetch_boxes()
    build()
