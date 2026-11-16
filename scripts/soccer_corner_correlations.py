#!/usr/bin/env python3
"""Soccer: how the legs of the corners slips move together, measured on
results. Feeds the soccer board of the Novig Scan
(.claude/skills/nba-sgp-fv/scan.py --league soccer).

  python3 scripts/soccer_corner_correlations.py --fetch 2016 2026   # seasons by the year they end; downloads them
  python3 scripts/soccer_corner_correlations.py                     # rebuild the correlations from the matches on disk

Matches (public/data/soccer_matches.json): the top five leagues from
football-data.co.uk, each as [favourite's closing win chance, favourite's
goals, underdog's goals, favourite's corners, underdog's corners]. The
favourite is the side with the shorter closing price (Pinnacle's where the
file has it), margin taken out in proportion.

Correlations (public/data/soccer_corner_correlations.json), by the
favourite's win chance: for each pair of legs the board puts on a slip, the
copula correlation r of their hit / miss record (the r at which a Gaussian
copula with the legs' own hit rates gives the share of matches where both
hit). Corner legs are measured at the line nearest 50/50 for that strength
of favourite and at the lines one corner either side, and averaged: r says
how the legs move together, not where the lines sit, so the board applies
it to each leg's real price on whatever line it is. "check" is how far the
slip's joint from those r's is from the counted share of matches, at each
of those lines (worst and mean) once multiplied by "scale", the mean of
counted / joint over those lines, which the board applies.

Legs: fw / dw the favourite / underdog wins; fu / fo the favourite's corners
Under / Over; do / du the underdog's corners Over / Under; o15 / o25 goals
Over 1.5 / 2.5. A pair with one leg flipped has the opposite sign (fw_fo is
-fw_fu); with both flipped, the same (fo_du is fu_do).
"""
import argparse
import csv
import datetime
import io
import json
import math
import os
import sys
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-ast-pts-sgp"))
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-sgp-fv"))
import sgp  # noqa: E402  joint, devig_r

MATCHES = os.path.join(ROOT, "public", "data", "soccer_matches.json")
OUT = os.path.join(ROOT, "public", "data", "soccer_corner_correlations.json")
LEAGUES = ("E0", "D1", "I1", "SP1", "F1")
BUCKETS = [(0.0, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 1.01)]
ODDS = (("PSCH", "PSCD", "PSCA"), ("PSH", "PSD", "PSA"), ("AvgCH", "AvgCD", "AvgCA"), ("AvgH", "AvgD", "AvgA"),
        ("B365CH", "B365CD", "B365CA"), ("B365H", "B365D", "B365A"), ("BbAvH", "BbAvD", "BbAvA"))


def fetch(first, last):
    rows = []
    for end in range(first, last + 1):
        season = f"{(end - 1) % 100:02d}{end % 100:02d}"
        for lg in LEAGUES:
            url = f"https://www.football-data.co.uk/mmz4281/{season}/{lg}.csv"
            try:
                txt = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) \
                    .read().decode("latin-1").lstrip("﻿").lstrip("ï»¿")
            except Exception as e:
                print(f"{url}: {e}", file=sys.stderr)
                continue
            for r in csv.DictReader(io.StringIO(txt)):
                try:
                    hg, ag, hc, ac = int(r["FTHG"]), int(r["FTAG"]), int(r["HC"]), int(r["AC"])
                except (KeyError, ValueError, TypeError):
                    continue
                o = None
                for ks in ODDS:
                    try:
                        o = [float(r[k]) for k in ks]
                        break
                    except (KeyError, ValueError, TypeError):
                        o = None
                if not o or min(o) <= 1:
                    continue
                tot = sum(1 / x for x in o)
                ph, pa = 1 / o[0] / tot, 1 / o[2] / tot
                rows.append([round(ph, 4), hg, ag, hc, ac] if ph >= pa else [round(pa, 4), ag, hg, ac, hc])
    json.dump({"source": "football-data.co.uk", "leagues": LEAGUES, "seasons": [first, last],
               "rows": rows}, open(MATCHES, "w"), separators=(",", ":"))
    print(f"{len(rows)} matches -> {MATCHES}")


def build():
    import price
    M = json.load(open(MATCHES))["rows"]
    rate = lambda xs, f: sum(1 for x in xs if f(x)) / len(xs)   # noqa: E731
    out = []
    for lo, hi in BUCKETS:
        xs = [m for m in M if lo <= m[0] < hi]
        mid = lambda col: min((k + 0.5 for k in range(16)), key=lambda L: abs(rate(xs, lambda m: m[col] > L) - 0.5))   # noqa: E731
        FC, DC = mid(3), mid(4)
        fl, dl = [FC - 1, FC, FC + 1], [L for L in (DC - 1, DC, DC + 1) if L > 0]
        E = {"fw": lambda m: m[1] > m[2], "dw": lambda m: m[1] < m[2], "o15": lambda m: m[1] + m[2] > 1.5, "o25": lambda m: m[1] + m[2] > 2.5}
        fu = lambda L: (lambda m: m[3] < L)     # noqa: E731
        fo = lambda L: (lambda m: m[3] > L)     # noqa: E731
        do = lambda L: (lambda m: m[4] > L)     # noqa: E731
        du = lambda L: (lambda m: m[4] < L)     # noqa: E731
        r2 = lambda f, g: sgp.devig_r(rate(xs, lambda m: f(m) and g(m)), rate(xs, f), rate(xs, g))   # noqa: E731
        avg = lambda v: sum(v) / len(v)   # noqa: E731
        r = {"fw_fu": avg([r2(E["fw"], fu(L)) for L in fl]), "fw_do": avg([r2(E["fw"], do(L)) for L in dl]),
             "fu_do": avg([r2(fu(a), do(b)) for a in fl for b in dl]),
             "dw_fo": avg([r2(E["dw"], fo(L)) for L in fl]), "dw_du": avg([r2(E["dw"], du(L)) for L in dl])}
        for g in ("o15", "o25"):
            r[f"fw_{g}"] = r2(E["fw"], E[g])
            r[f"fu_{g}"] = avg([r2(fu(L), E[g]) for L in fl])
            r[f"do_{g}"] = avg([r2(do(L), E[g]) for L in dl])
        r = {k: round(v, 3) for k, v in r.items()}

        def check(legs, pairs, joint):
            """scale: the mean of counted / joint over every line combination
            (the board multiplies the slip's joint by it, so it is right on
            average); worst and mean: how far the scaled joint is from the
            count at any one of those lines."""
            ratio = []
            for a in fl:
                for b in dl:
                    fs = legs(a, b)
                    seen = rate(xs, lambda m: all(f(m) for f in fs))
                    if seen * len(xs) < 30:
                        continue
                    ps = [rate(xs, f) for f in fs]
                    R = [[1.0 if i == j else r[pairs[min(i, j)][max(i, j) - min(i, j) - 1]] for j in range(len(fs))] for i in range(len(fs))]
                    ratio.append(seen / joint(ps, R))
            scale = sum(ratio) / len(ratio)
            errs = [scale / x - 1 for x in ratio]
            return {"scale": round(scale, 3), "worst": round(max(errs, key=abs), 3), "mean": round(sum(map(abs, errs)) / len(errs), 3),
                    "lines": len(errs)}
        chk = {"fav": check(lambda a, b: [E["fw"], fu(a), do(b)], [["fw_fu", "fw_do"], ["fu_do"]], price.tri_joint),
               "dog": check(lambda a, b: [E["dw"], fo(a), du(b)], [["dw_fo", "dw_du"], ["fu_do"]], price.tri_joint)}
        for g in ("o15", "o25"):
            chk[f"fav_{g}"] = check(lambda a, b, g=g: [E["fw"], E[g], fu(a), do(b)],
                                    [[f"fw_{g}", "fw_fu", "fw_do"], [f"fu_{g}", f"do_{g}"], ["fu_do"]], price.quad_joint)
        out.append({"fav": [lo, min(hi, 1.0)], "n": len(xs), "lines": {"fav": FC, "dog": DC}, "r": r, "check": chk})
        print(f"fav {lo:.2f}-{hi:.2f}: {len(xs)} matches, main corner lines {FC} / {DC}\n   r {r}\n   check {chk}")
    json.dump({"generated_at": datetime.date.today().isoformat(), "matches": len(M), "source": "football-data.co.uk, top five leagues",
               "by_fav": out}, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", type=int, nargs=2, metavar=("FIRST", "LAST"), help="download these seasons (by the year they end) first")
    a = ap.parse_args()
    if a.fetch:
        fetch(*a.fetch)
    build()
