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
TTL = 240
CACHE = os.path.join(tempfile.gettempdir(), "nba_sgp_books.json")
# (implied chance under this, usual margin, least margin), first match wins
MARGIN = {"dk": [(0.15, 1.44, 1.13), (0.40, 1.13, 1.02), (1.01, 1.07, 1.02)],
          "fd": [(0.15, 1.29, 1.05), (0.40, 1.05, 1.00), (1.01, 1.05, 1.02)]}
NAME = {"dk": "DK", "fd": "FD"}


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


def fd_events():
    """[(event id, name)] for today's real NBA games (no futures, no sims)."""
    ev = _fd_get(f"content-managed-page?page=CUSTOM&customPageId=nba&_ak={FD_KEY}&timezone=America/New_York")
    return [(str(e["eventId"]), e["name"]) for e in ev["attachments"]["events"].values()
            if " @ " in e["name"] and "(" not in e["name"]]


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
            print(f"books: DraftKings unavailable ({type(e).__name__}: {e})", file=sys.stderr)
            _DK.append(None)
    return _DK[0]


def dk_events():
    api = _dk()
    if not api:
        return []
    return [(str(e["id"]), e["name"]) for e in api.get_games_nba()["events"]
            if not e.get("isLive") and e.get("status") == "NOT_STARTED"]


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


def load(team=None):
    """{book: {player key: {stat: {line: implied}}}} for the game `team` (his
    team's full name) plays in, or for every game. A book that fails is left
    out: the other still caps."""
    c, now, out, dirty = _cache(), time.time(), {}, False
    for book, events, game in (("fd", fd_events, fd_game), ("dk", dk_events, dk_game)):
        try:
            evs = c.get(f"{book}:events")
            if not evs or now - evs["at"] > TTL:
                evs = c[f"{book}:events"] = {"at": now, "list": events()}
                dirty = True
            for eid, name in evs["list"]:
                if team and nick(team) not in {nick(t) for t in name.split(" @ ")}:
                    continue
                g = c.get(f"{book}:{eid}")
                if not g or now - g["at"] > TTL:
                    g = c[f"{book}:{eid}"] = {"at": now, "players": game(eid)}
                    dirty = True
                out.setdefault(book, {}).update(g["players"])
        except Exception as e:  # noqa: BLE001  a book being down must not stop a price
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
