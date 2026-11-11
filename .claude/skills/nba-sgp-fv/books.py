#!/usr/bin/env python3
"""DraftKings' and FanDuel's one-way Over ladders, as a ceiling on a shifted leg.

  python3 books.py "Payton Pritchard"          # both books' ladders for him
  python3 books.py "Payton Pritchard" pts 24.5 # one line: prices and the ceiling

Both books post every milestone ("25+ Points") as a one-way Over. The true
chance sits under a one-way price by the book's margin, so the price with the
least margin that book charges taken out is a ceiling on the leg, and with its
usual margin taken out it is an estimate. Margins were measured 11-11 against
Novig's tight two-way price on the same line (about 60 lines per cell):

                      DK usual  DK least   FD usual  FD least
  Over 40% and up       1.07      1.02       1.05      1.02
  Over 15-40%           1.13      1.02       1.05      1.00
  Over under 15%        1.44      1.13       1.29      1.05

FanDuel: the public site API (event-page tabs). DraftKings: dk_api.py at the
repo root (needs curl_cffi); when it can't load or DK refuses, FanDuel alone
is used. One game's pull is kept for TTL seconds in the temp directory, so a
second slip on the same game costs nothing.
"""
import json
import os
import re
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import novig  # noqa: E402  norm, american

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
FD = "https://sbapi.nj.sportsbook.fanduel.com/api"
FD_KEY = os.environ.get("FD_API_KEY", "FhMFpcPWXMeyZxOx")  # the public site's own key
FD_TABS = {"player-points": "pts", "player-rebounds": "reb", "player-assists": "ast", "player-threes": "tpm"}
DK_SUB = {"Points": "pts", "Rebounds": "reb", "Assists": "ast", "Threes": "tpm"}
# NFL yards (11-11): both books post 10-yard milestones as one-way Overs and a
# two-way main line. The main line is kept too ("main:yds": [line, P(over)]),
# for players Novig has no tight main line on (most of them before Saturday).
DK_NFL_LEAGUE = "88808"
DK_NFL = {"Receiving Yards": "yds", "Rushing Yards": "ryds", "Passing Yards": "pyds"}
FD_NFL_TABS = {"receiving-props": ("RECEIVING_YARDS", "yds"), "rushing-props": ("RUSHING_YARDS", "ryds"),
               "passing-props": ("PASSING_YARDS", "pyds")}
NFL_DAYS = 6.5   # this week's games only
TTL = 240
CACHE = os.path.join(tempfile.gettempdir(), "nba_sgp_books.json")
# (implied chance under this, usual margin, least margin), first match wins
MARGIN = {"dk": [(0.15, 1.44, 1.13), (0.40, 1.13, 1.02), (1.01, 1.07, 1.02)],
          "fd": [(0.15, 1.29, 1.05), (0.40, 1.05, 1.00), (1.01, 1.05, 1.02)]}
NAME = {"dk": "DK", "fd": "FD"}
ERRORS = {}   # book -> why its last pull failed (the scanner shows it)


def implied(american):
    a = float(str(american).replace("−", "-").replace("+", ""))
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def nick(team):
    """'Boston Celtics' / 'BOS Celtics' / 'Portland Trail Blazers' -> 'celtics' / 'blazers'."""
    return team.split()[-1].lower() if team else ""


def _fd_get(path):
    req = urllib.request.Request(f"{FD}/{path}", headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def fd_events(league="nba"):
    """[(event id, name)] for today's real NBA games (no futures, no sims), or
    this week's NFL games."""
    ev = _fd_get(f"content-managed-page?page=CUSTOM&customPageId={league}&_ak={FD_KEY}&timezone=America/New_York")
    soon = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + NFL_DAYS * 86400))
    return [(str(e["eventId"]), e["name"]) for e in ev["attachments"]["events"].values()
            if " @ " in e["name"] and "(" not in e["name"] and (league == "nba" or e.get("openDate", "") <= soon)]


def _pair(d, stat, line, side, q):
    """Collect a two-way main line; once both sides are in, store its devig."""
    m = d.setdefault("_m:" + stat, {})
    m[side] = (line, q)
    if "over" in m and "under" in m and m["over"][0] == m["under"][0]:
        d["main:" + stat] = [m["over"][0], m["over"][1] / (m["over"][1] + m["under"][1]), m["over"][1] + m["under"][1] - 1]


def fd_game_nfl(event_id):
    out = {}
    for tab, (word, stat) in FD_NFL_TABS.items():
        try:
            markets = _fd_get(f"event-page?_ak={FD_KEY}&eventId={event_id}&tab={tab}")["attachments"].get("markets", {})
        except Exception:
            continue
        for m in markets.values():
            mt = m["marketType"]
            alt = re.fullmatch(rf"PLAYER_[A-Z]+_ALT_{word}(_[A-Z]+)?", mt)
            main = re.fullmatch(rf"PLAYER_[A-Z]+_{word}(_[A-Z]+)?", mt)
            if m.get("marketStatus") != "OPEN" or not (alt or main):
                continue
            for rn in m["runners"]:
                try:
                    q = implied(rn["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"])
                except (KeyError, TypeError):
                    continue
                if rn.get("runnerStatus") != "ACTIVE":
                    continue
                if alt:
                    mm = re.fullmatch(r"(.+) (\d+)\+ Yards", rn["runnerName"])
                    if mm:
                        d = out.setdefault(novig.norm(mm.group(1)), {}).setdefault(stat, {})
                        line = str(int(mm.group(2)) - 0.5)
                        d[line] = min(q, d.get(line, 1.0))
                else:
                    name, _, side = rn["runnerName"].rpartition(" ")
                    if side.lower() in ("over", "under") and rn.get("handicap"):
                        _pair(out.setdefault(novig.norm(name), {}), stat, float(rn["handicap"]), side.lower(), q)
        time.sleep(0.2)
    return out


def fd_game(event_id):
    """{player key: {stat: {line: implied}}} of one FanDuel game's one-way Overs."""
    out = {}
    for tab, stat in FD_TABS.items():
        try:
            markets = _fd_get(f"event-page?_ak={FD_KEY}&eventId={event_id}&tab={tab}")["attachments"].get("markets", {})
        except Exception:
            continue
        for m in markets.values():
            mt = m["marketType"]
            if m.get("marketStatus") != "OPEN" or "QUARTER" in mt or "HALF" in mt or "1ST_" in mt:
                continue
            alt = re.fullmatch(r"PLAYER_[A-Z]+_ALT_TOTAL_\w+", mt)
            mile = re.fullmatch(r"(?:TO_SCORE_|TO_RECORD_)?(\d+)\+_\w+", mt)
            if not alt and not mile:
                continue
            for rn in m["runners"]:
                try:
                    q = implied(rn["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"])
                except (KeyError, TypeError):
                    continue
                if rn.get("runnerStatus") != "ACTIVE":
                    continue
                if alt:
                    mm = re.fullmatch(r"(.+) Over ([\d.]+)", rn["runnerName"])
                    if not mm:
                        continue
                    name, line = mm.group(1), float(mm.group(2))
                else:
                    name, line = rn["runnerName"], int(mile.group(1)) - 0.5
                d = out.setdefault(novig.norm(name), {}).setdefault(stat, {})
                d[str(line)] = min(q, d.get(str(line), 1.0))
        time.sleep(0.2)
    return out


_DK = []


def _dk():
    """dk_api, or None when it can't be imported here (no curl_cffi)."""
    if not _DK:
        try:
            sys.path.insert(0, ROOT)
            import dk_api
            _DK.append(dk_api)
        except Exception as e:  # noqa: BLE001  missing dependency: FanDuel alone
            ERRORS["dk"] = f"{type(e).__name__}: {e}"[:160]
            print(f"books: DraftKings unavailable ({type(e).__name__}: {e})", file=sys.stderr)
            _DK.append(None)
    return _DK[0]


def dk_events(league="nba"):
    api = _dk()
    if not api:
        return []
    if league == "nba":
        return [(str(e["id"]), e["name"]) for e in api.get_games_nba()["events"]
                if not e.get("isLive") and e.get("status") == "NOT_STARTED"]
    soon = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + NFL_DAYS * 86400))
    evs = api._get_with_retry(f"{api.DK_LEAGUES}/{DK_NFL_LEAGUE}").json().get("events", [])
    return [(str(api._ev_id(e)), e.get("name", "")) for e in evs
            if e.get("status") == "NOT_STARTED" and str(api._ev_start(e)) <= soon]


def dk_game_nfl(event_id):
    out = {}
    for p in _dk().get_markets(event_id).get("props", []):
        if p.get("isDisabled"):
            continue
        mt = p["marketType"]
        if mt.endswith(" Milestones") and mt[:-11] in DK_NFL:
            d = out.setdefault(novig.norm(p["player"]), {}).setdefault(DK_NFL[mt[:-11]], {})
            line = str(p["points"] - 0.5)
            d[line] = min(implied(p["oddsAmerican"]), d.get(line, 1.0))
        elif mt.endswith(" O/U") and mt[:-4] in DK_NFL and p["outcomeType"] in ("Over", "Under"):
            _pair(out.setdefault(novig.norm(p["player"]), {}), DK_NFL[mt[:-4]], float(p["points"]),
                  p["outcomeType"].lower(), implied(p["oddsAmerican"]))
    return out


def dk_game(event_id):
    out = {}
    for p in _dk().get_markets(event_id, nba_only=True).get("props", []):
        if p.get("isDisabled") or not p["marketType"].endswith("Milestones") or p["subcategory"] not in DK_SUB:
            continue
        d = out.setdefault(novig.norm(p["player"]), {}).setdefault(DK_SUB[p["subcategory"]], {})
        line = str(p["points"] - 0.5)
        d[line] = min(implied(p["oddsAmerican"]), d.get(line, 1.0))
    return out


def _cache():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load(team=None, league="nba"):
    """{book: {player key: {stat: {line: implied}}}} for the game `team` (his
    team's full name) plays in, or for every game. A book that fails is left
    out: the other still caps. NFL also carries each two-way main line as
    "main:<stat>": [line, P(over), hold]."""
    c, now, out, dirty = _cache(), time.time(), {}, False
    games = {"fd": fd_game if league == "nba" else fd_game_nfl, "dk": dk_game if league == "nba" else dk_game_nfl}
    for book, events in (("fd", fd_events), ("dk", dk_events)):
        game = games[book]
        try:
            evs = c.get(f"{league}:{book}:events")
            if not evs or now - evs["at"] > TTL:
                evs = c[f"{league}:{book}:events"] = {"at": now, "list": events(league)}
                dirty = True
            for eid, name in evs["list"]:
                if team and nick(team) not in {nick(t) for t in name.split(" @ ")}:
                    continue
                g = c.get(f"{league}:{book}:{eid}")
                if not g or now - g["at"] > TTL:
                    g = c[f"{league}:{book}:{eid}"] = {"at": now, "players": game(eid)}
                    dirty = True
                out.setdefault(book, {}).update(g["players"])
        except Exception as e:  # noqa: BLE001  a book being down must not stop a price
            ERRORS[book] = f"{type(e).__name__}: {e}"[:160]
            print(f"books: {NAME[book]} pull failed ({type(e).__name__}: {e})", file=sys.stderr)
    if dirty:
        fresh = {k: v for k, v in c.items() if now - v["at"] <= TTL}
        try:
            with open(CACHE + ".tmp", "w") as f:
                json.dump(fresh, f)
            os.replace(CACHE + ".tmp", CACHE)
        except OSError:
            pass
    return out


def main_line(ladders, player, stat):
    """(line, P(over), 'DK 54.5') from a book's two-way main line: the book
    with the lower hold, or None."""
    key, best = novig.norm(player), None
    for book in ("dk", "fd"):
        m = ladders.get(book, {}).get(key, {}).get("main:" + stat)
        if m and abs(m[1] - 0.5) <= 0.15 and (best is None or m[2] < best[0][2]):
            best = (m, book)
    return (best[0][0], best[0][1], f"{NAME[best[1]]} {best[0][0]:g}") if best else None


def fair_ladder(ladders, player, stat):
    """(line, P(over), [(line, fair P(over))]) from the book with the lower
    hold: its two-way main line and its one-way ladder with the usual margin
    taken out, for fitting that player's own spread. None without a main."""
    key, best = novig.norm(player), None
    for book in ("dk", "fd"):
        d = ladders.get(book, {}).get(key, {})
        m = d.get("main:" + stat)
        if m and abs(m[1] - 0.5) <= 0.15 and (best is None or m[2] < best[0][2]):
            best = (m, book, d.get(stat, {}))
    if not best:
        return None
    m, book, lad = best
    return m[0], m[1], [(float(ln), q / margins(book, q)[0]) for ln, q in lad.items() if q >= 0.012]


def margins(book, q):
    for under, usual, least in MARGIN[book]:
        if q < under:
            return usual, least


def check(ladders, player, stat, line):
    """(ceiling, estimate, text) for the Over at `line`, or (None, None, "").
    ceiling: the lowest of each book's price with its least margin taken out.
    estimate: the lowest with its usual margin taken out. text: 'DK +552 · FD +560'."""
    key, caps, ests, shown = novig.norm(player), [], [], []
    for book in ("dk", "fd"):
        q = ladders.get(book, {}).get(key, {}).get(stat, {}).get(str(float(line)))
        if q is None or q < 0.012:   # +8000 and longer is a price cap, not a price
            continue
        usual, least = margins(book, q)
        caps.append(q / least); ests.append(q / usual)
        shown.append(f"{NAME[book]} {novig.american(q):+d}")
    if not caps:
        return None, None, ""
    return min(caps), min(ests), " · ".join(shown)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nba-ast-pts-sgp"))
    import sgp
    _, by = sgp.load()
    hits = [n for n in by if sys.argv[1].lower() in n.lower()]
    if len(hits) != 1:
        raise SystemExit(f"player {sys.argv[1]!r}: {'no match' if not hits else 'ambiguous: ' + ', '.join(hits)}")
    lad = load(by[hits[0]].get("team_name"))
    stats = [sys.argv[2].lower()] if len(sys.argv) > 2 else list(DK_SUB.values())
    print(f"{hits[0]} · one-way Overs · {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    for s in stats:
        lines = sorted({float(x) for b in lad.values() for x in b.get(novig.norm(hits[0]), {}).get(s, {})})
        if len(sys.argv) > 3:
            lines = [float(sys.argv[3])]
        for ln in lines:
            cap, est, text = check(lad, hits[0], s, ln)
            if cap is not None:
                print(f"  {s} {int(ln + 0.5)}+  {text}  ->  about {novig.american(est):+d} fair, no shorter than {novig.american(cap):+d}")


if __name__ == "__main__":
    main()
