#!/usr/bin/env python3
"""DraftKings NBA SGP scan: the Novig scanner's NBA slips, priced on DraftKings.

  python3 scan_dk.py --dry          # the slips it would price, no price asked
  python3 scan_dk.py                # price them and print the best
  python3 scan_dk.py --json         # one JSON event per line (server.js: the DK NBA board)

What it prices, per player on tonight's DraftKings slate:
  1  Points Over + Threes Over at DraftKings' own O/U lines (the player's
     shrunk correlation, as on the Novig board).
  2  His other Over + Over pairs where r is at least --min-r: points +
     rebounds, points + assists, rebounds + assists, rebounds + threes,
     assists + threes.
  T  Teammates: each team's two highest points lines, Over + Over, as
     unrelated legs (scan.nba_mate_candidates has the measurement).

Fair value: each leg is Novig's exchange book on the same line, devigged
worst case, where Novig has a two-sided book inside --max-spread on that
line. Where it has none, the leg is DraftKings' own Over / Under with the
margin taken out, and the row is marked rough (~): a book's own two-way
price is a weaker fair value than an exchange's. The legs are joined with
the same Gaussian copula as the Novig board.

Price: DraftKings' same-game-parlay price for the two selections
(dk_api._price_combo, the calculateBets call the main app's DK pricing
uses). That call sits behind DraftKings' bot protection: it answers only
from a connection DraftKings trusts (see LOCAL_RUN.md: a validated cookie,
or DK_PROXY). Where it is refused the scan stops with that as its error
instead of asking again and again. Reading the slate and the lines needs
no such trust.
"""
import argparse
import json
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "nba-ast-pts-sgp"))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))
import novig  # noqa: E402
import price  # noqa: E402  shrunk_r
import scan  # noqa: E402  leg_text, usable, NBA_MATE_R, NBA_MATE_MIN
import sgp  # noqa: E402  joint, american, devig_worst, load

OU = {"Points O/U": "pts", "Rebounds O/U": "reb", "Assists O/U": "ast", "Three Pointers Made O/U": "tpm"}
NAME = re.compile(r"^(.*?) (Points|Rebounds|Assists|Three Pointers Made) O/U$")
PAIRS = (("pts", "reb"), ("pts", "ast"), ("reb", "ast"), ("reb", "tpm"), ("ast", "tpm"))
PACE_S = 1.0          # between two price requests
BLOCKED_AFTER = 4     # this many refusals with no price at all: stop


def dk_lines(dk, before=None):
    """{normalised player name: {"event", "starts" (ms), "lines": {stat:
    {"line", "over": (selection id, decimal), "under": (...)}}}} from
    DraftKings' O/U markets on today's pregame NBA games."""
    out = {}
    for g in (dk.get_games_nba() or {}).get("events", []):
        if g.get("isLive") or g.get("status") != "NOT_STARTED":
            continue
        try:
            starts = int(time.mktime(time.strptime(g["startDate"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone) * 1000
        except (KeyError, ValueError):
            continue
        if before and starts >= before:
            continue
        for p in (dk.get_markets(g["id"], nba_only=True) or {}).get("props", []):
            stat, m = OU.get(p.get("marketType")), NAME.match(p.get("marketName") or "")
            side = (p.get("outcomeType") or "").lower()
            if not stat or not m or side not in ("over", "under") or p.get("points") is None or not p.get("oddsDecimal"):
                continue
            who = out.setdefault(novig.norm(m.group(1)), {"event": g["id"], "game": g.get("name"), "starts": starts, "lines": {}})
            row = who["lines"].setdefault(stat, {"line": float(p["points"])})
            if row["line"] == float(p["points"]):
                row[side] = (p["selectionId"], float(p["oddsDecimal"]))
    return out


def candidates(dk, a):
    d, by = sgp.load()
    key = {novig.norm(n): p for n, p in by.items()}
    board = dk_lines(dk, a.before)
    markets = novig.fetch()
    out, teams = [], {}
    for nm, info in board.items():
        p = key.get(nm)
        if not p:
            continue
        _, rows = novig.ladder(markets, p["name"])
        legs = {}
        for stat, row in info["lines"].items():
            if "over" not in row or "under" not in row:
                continue
            sid, dec = row["over"]
            nv = next((r for r in rows.get(stat, []) if r["line"] == row["line"] and scan.usable(r, a.max_spread)), None)
            if nv:
                fo, width, src = nv["fo"], nv["spread"], "novig"
            else:
                io, iu = 1 / dec, 1 / row["under"][1]
                fo, width, src = sgp.devig_worst(io, iu)[0], io + iu - 1, "dk"
            legs[stat] = {"stat": stat, "side": "over", "line": row["line"], "p": fo, "fair": sgp.american(fo), "width": width,
                          "id": sid, "dk": dec, "dk_american": sgp.american(1 / dec), "src": src}

        def row_of(tier, r, la, lb, who=None, pid=None, label=None, kind=None):
            j = sgp.joint(r, la["p"], lb["p"])
            c = {"key": f"{la['id']},{lb['id']}", "tier": tier, "player": who or p["name"], "id": pid or p["athlete_id"],
                 "team": p.get("team_abbr") or "", "starts": info["starts"], "legs": [dict(la), dict(lb)],
                 "label": label or f"{scan.leg_text(la)} · {scan.leg_text(lb)}", "r": r, "j": j, "forced": False,
                 "devig_r": sgp.devig_r(j, la["p"], lb["p"]), "book": "dk", "event": info["event"],
                 "rough": any(L["src"] == "dk" for L in (la, lb)),
                 # what the two legs would pay multiplied together at DraftKings' own prices
                 "legs_x": la["dk"] * lb["dk"]}
            if kind:
                c["kind"] = kind
            return c
        if "pts" in legs and "tpm" in legs:
            r = price.shrunk_r(d, by, p, "pts", "tpm")[0]
            # k threes are 3k points: a threes Over that forces the points Over is one leg, not two
            if r > 0 and 3 * (math.floor(legs["tpm"]["line"]) + 1) <= legs["pts"]["line"]:
                out.append(dict(row_of(1, r, legs["pts"], legs["tpm"]), main=True))
        for x, y in PAIRS:
            if x in legs and y in legs:
                r = price.shrunk_r(d, by, p, x, y)[0]
                if r is not None and r >= a.min_r:
                    out.append(row_of(2, r, legs[x], legs[y]))
        if "pts" in legs and p.get("team_abbr"):
            teams.setdefault((info["event"], p["team_abbr"]), []).append((p, legs["pts"], row_of))
    last = lambda p: p["name"].split(" ", 1)[-1]   # noqa: E731
    for ps in teams.values():
        ps.sort(key=lambda x: -x[1]["line"])
        if len(ps) >= 2 and ps[1][1]["line"] >= scan.NBA_MATE_MIN:
            (pa, la, mk), (pb, lb, _) = ps[0], ps[1]
            out.append(mk(2, scan.NBA_MATE_R, la, lb, who=f"{pa['name']} + {pb['name']}", pid=f"{pa['athlete_id']}+{pb['athlete_id']}",
                          label=f"{last(pa)} {scan.leg_text(la)} · {last(pb)} {scan.leg_text(lb)}", kind="mates"))
    out.sort(key=lambda c: (c["tier"], c["starts"], -c["r"]))
    return (out[:a.max] if a.max else out), d


def finish(c, dec, unit, kelly):
    p = sgp.prob(sgp.american(c["j"]))
    b = dec - 1
    qk = max(0.0, (p * b - (1 - p)) / b) * kelly * 100
    c.update(fair=sgp.american(c["j"]), fair_x=1 / p, quote=1 / dec, raw_x=dec, slip_x=dec, slip=sgp.american(1 / dec),
             ev=p * dec - 1, qk=qk, wager=qk * unit, at=time.time())
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="stream events as JSON lines (server.js)")
    ap.add_argument("--dry", action="store_true", help="list the slips, ask DraftKings for no price")
    ap.add_argument("--max", type=int, default=0, help="price at most this many slips")
    ap.add_argument("--min-r", type=float, default=0.25, help="smallest r for a pair other than Points + Threes")
    ap.add_argument("--max-spread", type=float, default=novig.MAX_SPREAD, help="widest Novig book a leg's fair value is read from")
    ap.add_argument("--before", type=float, default=None, metavar="MS", help="only games starting before this time (epoch ms)")
    ap.add_argument("--unit", type=float, default=250.0)
    ap.add_argument("--kelly", type=float, default=0.25)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--first", default=None, help="accepted for server.js; not used")
    ap.add_argument("--events", nargs="+", default=None, help="accepted for server.js; not used")
    a = ap.parse_args()
    import dk_api as dk
    t0 = time.time()

    def emit(e):
        if a.json:
            print(json.dumps(e), flush=True)
    cands, d = candidates(dk, a)
    emit({"type": "start", "total": len(cands), "players": len({c["id"] for c in cands}), "league": "dknba",
          "data": d["generated_at"][:10], "at": t0})
    if a.dry:
        for c in cands:
            print(f"{c['player'][:30]:30s} {c['label'][:34]:34s} r {c['r']:+.2f} fair {sgp.american(c['j']):+5d}  legs "
                  + " / ".join(f"{L['p']:.2f} ({L['src']}, DK {L['dk_american']:+d})" for L in c["legs"]))
        print(f"{len(cands)} slips, {sum(1 for c in cands if c['rough'])} with a leg priced off DraftKings' own book")
        return
    rows, refused = [], 0
    for c in cands:
        got = dk._price_combo([L["id"] for L in c["legs"]])
        dec = got and got.get("sgpDecimal")
        if dec and float(dec) > 1:
            finish(c, float(dec), a.unit, a.kelly)
            rows.append(c)
            emit(dict(c, type="row"))
        else:
            diag = dk._PRICE_DIAG
            refused = sum(n for k, n in diag.get("http", {}).items() if k in ("403", "429")) + diag.get("skipped_blocked", 0)
            emit({"type": "miss", "key": c["key"], "player": c["player"], "label": c["label"],
                  "why": "DraftKings won't combine these legs" if diag.get("incompatible") else "no price"})
            if not rows and refused >= BLOCKED_AFTER:
                # Its own line on stderr: server.js shows the last one as the board's error.
                raise SystemExit("DraftKings is refusing this server's price requests (its bot protection). The lines read "
                                 "fine; pricing needs a connection it trusts: a fresh DK cookie in the main app, or DK_PROXY.")
        time.sleep(PACE_S)
    emit({"type": "done", "quoted": len(cands), "priced": len(rows), "seconds": time.time() - t0, "at": time.time()})
    if not a.json:
        rows.sort(key=lambda c: -c["ev"])
        for c in rows[:a.top or None]:
            print(f"{c['ev']:+6.1%}  {c['player'][:28]:28s} {c['label'][:32]:32s} fair {c['fair']:+5d}  DK {c['slip']:+5d} ({c['slip_x']:.2f}x)"
                  + ("  ~" if c["rough"] else ""))
        print(f"{len(rows)} of {len(cands)} priced in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
