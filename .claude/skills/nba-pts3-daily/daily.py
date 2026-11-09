#!/usr/bin/env python3
"""Daily NBA Points + Threes SGP run (Novig). Two steps:

  python3 daily.py slate                 # Vulture /run commands for today's shooters
  python3 daily.py slate --round 2       # the next batch (players not in round 1)
  python3 daily.py handoff --dummy 0.980 legs.txt   # Claude-in-Chrome handoff

slate: every player with an open pregame NBA prop on Novig whose season 3PM
average is >= --min-tpm (default 1.8), ranked by his shrunk PTS-3PM r
(public/data/nba_correlations.json). Prints the round's Vulture commands,
--chunk names per command (Overs only, points + threes, books dk,fd).
Round 2 = the players after round 1, then shooters down to 1.3 3PM.

handoff: one player per line, legs from the Vulture sheet's Sharp odds
(Over then Under) at the main line, or "novig" for a leg the sheet lacks:

  Cade Cunningham | pts 24.5 -120 -109 | tpm 2.5 +109 -145
  Davion Mitchell | pts 12.5 novig     | tpm 1.5 -145 +109

Prints the full handoff (dummy, build steps, Fair x / +5% x table sorted by
Fair x, grading, quarter-Kelly math at $250 units, report format).
Fair x = 1 / (joint x pD), so it compares straight to a slip with the dummy.
"""
import argparse
import json
import math
import os
import sys
import unicodedata
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-sgp-fv"))
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-ast-pts-sgp"))


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    w = "".join(c if c.isalnum() or c == " " else " " for c in s.replace("'", "").replace(".", "")).split()
    return "".join(x for x in w if x not in {"jr", "sr", "ii", "iii", "iv", "v"})


def novig_players():
    q = {"league": "NBA", "marketType": "POINTS,THREE_POINTERS_MADE", "eventStatus": "OPEN_PREGAME", "limit": 5000}
    names, events, after = set(), set(), None
    for _ in range(20):
        if after:
            q["after"] = after
        req = urllib.request.Request("https://api.novig.com/v3/public/catalog/markets?" + urllib.parse.urlencode(q),
                                     headers={"Accept": "application/json", "User-Agent": "nba-pts3-daily"})
        with urllib.request.urlopen(req, timeout=30) as r:
            page = json.load(r)
        for m in page.get("items", []):
            names.add(norm(m["description"].rsplit(" ", 2)[0]))
            events.add(m["eventId"])
        after = page.get("next")
        if not after:
            break
    return names, len(events)


def slate(a):
    d = json.load(open(os.path.join(ROOT, "public", "data", "nba_correlations.json")))
    names, n_games = novig_players()
    pool = []
    for p in d["players"]:
        r = (p.get("pts_3pm") or {}).get("shrunk", {}).get("r")
        if r is None or norm(p["name"]) not in names:
            continue
        pool.append((r, p["name"], p.get("team_abbr", ""), p.get("tpm_mean", 0)))
    pool.sort(reverse=True)
    main = [x for x in pool if x[3] >= a.min_tpm]
    low = [x for x in pool if 1.3 <= x[3] < a.min_tpm]
    if a.round == 1:
        pick = main[:a.n]
    else:
        pick = (main[a.n:] + low)[:a.n]
    print(f"Novig: {n_games} NBA games open pregame · r data {d['generated_at'][:10]} · round {a.round}: {len(pick)} players\n")
    for i in range(0, len(pick), a.chunk):
        names_ = ", ".join(f"{x[1]} Over" for x in pick[i:i + a.chunk])
        print(f"/run command_name:twa markets:player points, player made threes bet_names:{names_} books:dk,fd\n")
    print("| # | Player | Tm | 3PM/g | r |\n|---|---|---|---|---|")
    for i, x in enumerate(pick, 1):
        print(f"| {i} | {x[1]} | {x[2]} | {x[3]:.1f} | {x[0]:.3f} |")


def handoff(a):
    import price  # nba-sgp-fv/price.py
    import sgp
    d, by = sgp.load()
    lines = [l for l in (open(a.file) if a.file else sys.stdin).read().splitlines() if l.strip() and not l.startswith("#")]
    rows, notes = [], []
    for line in lines:
        name, *legs = [x.strip() for x in line.split("|")]
        hits = [n for n in by if norm(n) == norm(name)] or [n for n in by if name.lower() in n.lower()]
        if len(hits) != 1:
            notes.append(f"{name}: not in the data ({'no match' if not hits else 'ambiguous'})")
            continue
        p = by[hits[0]]
        parsed = []
        for t in legs:
            w = t.split()
            stat, line_ = w[0], w[1]
            parsed.append(price.parse_leg(f"{stat} over {line_} " + ("novig" if w[2] == "novig" else "odds " + " ".join(w[2:]))))
        try:
            if any(l.get("novig") for l in parsed):
                price.novig_legs(hits[0], parsed, a.novig_spread)
        except SystemExit as e:
            notes.append(str(e) if hits[0] in str(e) else f"{hits[0]}: {e}")
            continue
        ps = []
        for leg in parsed:
            q, note = price.leg_prob(p, leg)
            ps.append(q)
            if note and "from" in note:
                notes.append(f"{hits[0]}: {leg['stat']} {leg['line']:g} was shifted ({note}); use Novig's own main line instead")
        pts = next(l for l in parsed if l["stat"] == "pts")
        tpm = next(l for l in parsed if l["stat"] == "tpm")
        r, _ = price.shrunk_r(d, by, p, "pts", "tpm")
        forced = 3 * (math.floor(tpm["line"]) + 1) > pts["line"]
        j = min(ps) if forced else sgp.joint(r, ps[0], ps[1])
        fx = 1 / (j * a.dummy)
        rows.append((fx, hits[0], f"{int(pts['line'] + .5)}+ PTS / {int(tpm['line'] + .5)}+ 3PM", sgp.american(j)))
    rows.sort()
    tbl = "\n".join(f"| {n} | {legs} | {fx:.2f}x | {fx * 1.05:.2f}x |" for fx, n, legs, _ in rows)
    print(f"""```
TASK: Novig NBA Points + Threes SGP scan. Never place a bet or type an amount: only build slips and read multipliers.

DUMMY: add {a.dummy_name} once and keep it in the slip for every combo; never remove it. The breakevens below include it (pD = {a.dummy:.3f}). If it goes live before you finish, re-read both moneyline %s and report the new pD.

BUILD: type each player's name into Novig's search bar (do NOT go through the game page: search is much faster). Add "<N>+ Points · Yes" and "<M>+ Three Pointers Made · Yes". Read the multiplier M at the top right of Order Slip > Parlays. Remove only the two NBA legs (keep the dummy), then the next row. Skip games that have started.

| Player | Legs | Fair x | +5% x |
|---|---|---|---|
{tbl}

GRADE: M >= +5% x -> PLAY. Fair x <= M < +5% x -> THIN. Below Fair x -> PASS.

MATH FOR PLAYS:
P = 1 / Fair x
EV% = (M x P - 1) x 100
b = M - 1
QK = max(0, (P*b - (1-P)) / b) / 4 x 100 units (quarter Kelly)
$ = QK x 250

REPORT: one table, highest EV first: Player | Legs | M | Fair x | EV% | QK u | $
Prices as American odds or x multipliers, never percentages (EV% is the only %). Then list THIN rows and any player whose props weren't posted.
```""")
    if notes:
        print("\nNotes:\n" + "\n".join(f"- {n}" for n in notes))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("slate")
    s.add_argument("--round", type=int, default=1, choices=(1, 2))
    s.add_argument("--min-tpm", type=float, default=1.8)
    s.add_argument("--n", type=int, default=25, help="players per round")
    s.add_argument("--chunk", type=int, default=13, help="names per /run command")
    h = sub.add_parser("handoff")
    h.add_argument("file", nargs="?", help="legs file (default stdin)")
    h.add_argument("--dummy", type=float, required=True, help="dummy leg fair win prob, e.g. 0.980")
    h.add_argument("--dummy-name", default="the dummy leg", help='e.g. "St. John\'s ML (vs Iona, CBB)"')
    h.add_argument("--novig-spread", type=float, default=0.04)
    a = ap.parse_args()
    slate(a) if a.cmd == "slate" else handoff(a)


if __name__ == "__main__":
    main()
