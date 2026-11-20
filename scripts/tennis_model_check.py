#!/usr/bin/env python3
"""Tennis: the score model behind the Novig tennis scan
(.claude/skills/novig-tennis-scan/tennis.py), checked against real results.

  python3 scripts/tennis_model_check.py --fetch /path/to/tml-database   # rebuild the matches file from the yearly CSVs first
  python3 scripts/tennis_model_check.py                                 # run the check from the matches on disk

Matches (public/data/tennis_matches.json): every completed best-of-three ATP
tour match from 2005 on (TennisMyLife's TML-Database, github.com/Tennismylife/
TML-Database: non-commercial use, from the ATP's results), each as [the
favourite's chance to win before the match, surface, year, the sets as
"favourite's games-underdog's games"]. Retirements, walkovers, Davis Cup and
matches with a deciding match tiebreak are left out. The file has no odds, so
the favourite and his chance come from an Elo rating run forward through
every match since 1990 (half overall, half on the surface), never using the
match itself.

The check (public/data/tennis_model_check.json): matches are grouped by the
favourite's chance. In each group the model is fitted the way the scan fits
it to a match, to three numbers: how often the favourite won, how often the
match went over the total nearest 50/50, how often the favourite covered the
game spread nearest 50/50. Then, for the scan's four slips on those lines and
the lines one either side, the model's joint is set against the share of
matches where both legs hit. "off" is model / counted - 1 on the scan's
careful fair value (+0.05: the model calls a slip fair that loses 5%); "se"
is the count's standard error.

A group is many matches, not one: players of different serve strength are
mixed in it, which one match's fit never has. Hard, clay and grass are also
checked apart for that reason.
"""
import argparse
import collections
import csv
import datetime
import json
import math
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "novig-tennis-scan"))
MATCHES = os.path.join(ROOT, "public", "data", "tennis_matches.json")
OUT = os.path.join(ROOT, "public", "data", "tennis_model_check.json")
BANDS = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 0.80), (0.80, 0.86), (0.86, 1.01)]
FIRST = 2005


def sets_of(score):
    """[(winner's games, loser's games)] for a completed best-of-three match
    with tiebreak sets, or None."""
    out = []
    for tok in score.split():
        tok = tok.split("(")[0]
        try:
            a, b = (int(x) for x in tok.split("-"))
        except ValueError:
            return None
        if max(a, b) > 7 or max(a, b) < 6 or (max(a, b) == 6 and abs(a - b) < 2) or (max(a, b) == 7 and min(a, b) < 5):
            return None
        out.append((a, b))
    won = sum(1 for a, b in out if a > b)
    return out if len(out) in (2, 3) and won == 2 and len(out) - won in (0, 1) else None


def fetch(src):
    elo, surf, played = collections.defaultdict(lambda: 1500.0), collections.defaultdict(lambda: 1500.0), collections.Counter()
    rows = []
    for y in range(1990, datetime.date.today().year + 1):
        path = os.path.join(src, f"{y}.csv")
        if not os.path.exists(path):
            continue
        ms = list(csv.DictReader(open(path, encoding="utf-8")))
        order = {"R128": 0, "R64": 1, "R32": 2, "R16": 3, "QF": 4, "SF": 5, "F": 7, "RR": 3, "BR": 6}
        ms.sort(key=lambda r: (r["tourney_date"], r["tourney_id"], order.get(r["round"], 3)))
        for r in ms:
            w, lo, s = r["winner_id"], r["loser_id"], (r["surface"] or "Hard")[:1].upper()
            dw = (elo[w] + surf[(w, s)]) / 2 - (elo[lo] + surf[(lo, s)]) / 2
            pw = 1 / (1 + 10 ** (-dw / 400))
            st = sets_of(r["score"]) if r["best_of"] == "3" and r["tourney_level"] != "D" else None
            if st and y >= FIRST and min(played[w], played[lo]) >= 20:
                if pw >= 0.5:
                    rows.append([round(pw, 3), s, y, " ".join(f"{a}{b}" for a, b in st)])
                else:
                    rows.append([round(1 - pw, 3), s, y, " ".join(f"{b}{a}" for a, b in st)])
            if "W/O" in r["score"].upper() or not r["score"].strip():
                continue
            for table, kw, kl in ((elo, w, lo), (surf, (w, s), (lo, s))):
                e = 1 / (1 + 10 ** (-(table[kw] - table[kl]) / 400))
                k = 32 if table is elo else 24
                table[kw] += k * (1 - e)
                table[kl] -= k * (1 - e)
            played[w] += 1
            played[lo] += 1
    json.dump({"source": "TennisMyLife TML-Database (ATP tour results; non-commercial use), favourite's chance from a walk-forward Elo",
               "first": FIRST, "rows": rows}, open(MATCHES, "w"), separators=(",", ":"))
    print(f"{len(rows)} matches -> {MATCHES}")


def facts(row):
    """(favourite won, sets, favourite's games, underdog's games)."""
    st = [(int(x[0]), int(x[1])) for x in row[3].split()]
    return sum(1 for a, b in st if a > b) == 2, len(st), sum(a for a, _ in st), sum(b for _, b in st)


def check(M, say=print):
    import tennis
    out = []
    for lo, hi in BANDS:
        xs = [facts(m) for m in M if lo <= m[0] < hi]
        if len(xs) < 800:
            continue
        n = len(xs)
        rate = lambda f: sum(1 for x in xs if f(*x)) / n   # noqa: E731
        pw = rate(lambda w, k, a, b: w)
        tl = min((t + 0.5 for t in range(14, 30)), key=lambda t: abs(rate(lambda w, k, a, b: a + b > t) - 0.5))
        sl = min((s + 0.5 for s in range(-3, 9)), key=lambda s: abs(rate(lambda w, k, a, b: a - b > s) - 0.5))
        fits = tennis.fit(pw, tl, rate(lambda w, k, a, b: a + b > tl), sl, rate(lambda w, k, a, b: a - b > sl))
        tables = [f[3] for f in fits if f[0] <= fits[0][0] + tennis.FIT_SLACK]
        best = fits[0][3]
        band = {"fav": [lo, min(hi, 1.0)], "n": n, "won": round(pw, 3), "total": tl, "spread": sl, "fit_miss": round(fits[0][0], 4),
                "sigma": fits[0][1], "three_sets": {"counted": round(rate(lambda w, k, a, b: k == 3), 3),
                                                    "model": round(tennis.P(best, lambda w, k, a, b: k == 3), 3)}, "slips": {}}
        shapes = {"dog_games_over": lambda s, t: (lambda w, k, a, b: a - b < s and a + b > t),
                  "fav_games_under": lambda s, t: (lambda w, k, a, b: a - b > s and a + b < t),
                  "fav_ml_under": lambda s, t: (lambda w, k, a, b: w and a + b < t),
                  "dog_ml_over": lambda s, t: (lambda w, k, a, b: (not w) and a + b > t)}
        for name, mk in shapes.items():
            cells = []
            for s in ((sl - 1, sl, sl + 1) if "games" in name else (sl,)):
                for t in (tl - 1, tl, tl + 1):
                    f = mk(s, t)
                    seen = rate(f)
                    if seen * n < 60:
                        continue
                    js = [tennis.P(d, f) for d in tables]
                    cells.append({"spread": s, "total": t, "counted": round(seen, 4), "model": round(min(js), 4), "model_hi": round(max(js), 4),
                                  "off": round(min(js) / seen - 1, 3), "se": round(math.sqrt((1 - seen) / (seen * n)), 3)})
            main = next((c for c in cells if c["spread"] == sl and c["total"] == tl), None)
            band["slips"][name] = {"main": main, "mean_off": round(sum(c["off"] for c in cells) / len(cells), 3) if cells else None,
                                   "worst_off": max((c["off"] for c in cells), key=abs) if cells else None, "cells": cells}
        out.append(band)
        say(f"fav {lo:.2f}-{min(hi, 1):.2f}: {n} matches, won {pw:.1%}, lines {tl} / -{sl}, 3 sets counted {band['three_sets']['counted']:.1%} model {band['three_sets']['model']:.1%}\n   " +
            " | ".join(f"{k} main {v['main']['off']:+.1%} (se {v['main']['se']:.1%}), all lines {v['mean_off']:+.1%}, worst {v['worst_off']:+.1%}"
                       for k, v in band["slips"].items() if v["main"]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", metavar="DIR", help="a checkout of github.com/Tennismylife/TML-Database: rebuild the matches file from it first")
    a = ap.parse_args()
    if a.fetch:
        fetch(a.fetch)
    D = json.load(open(MATCHES))
    M = D["rows"]
    doc = {"generated_at": datetime.date.today().isoformat(), "matches": len(M), "source": D["source"], "all": None, "by_surface": {}}
    print(f"all surfaces, {len(M)} matches")
    doc["all"] = check(M)
    for s, name in (("H", "hard"), ("C", "clay"), ("G", "grass")):
        xs = [m for m in M if m[1] == s]
        print(f"\n{name}, {len(xs)} matches")
        doc["by_surface"][name] = check(xs)
    json.dump(doc, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
