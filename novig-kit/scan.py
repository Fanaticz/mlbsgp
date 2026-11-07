#!/usr/bin/env python3
"""Novig Points + Threes SGP scanner. Standard library only (Python 3.8+).

  python3 scan.py                 # every open pregame NBA player, main lines
  python3 scan.py --alts          # also PTS one line up and 3PM one line up
  python3 scan.py --min-tpm 2.0   # only shooters averaging 2+ threes
  python3 scan.py --dummy 0.979   # divide breakevens by a dummy leg's fair win prob

For each player it takes Novig's main Points and Threes lines (the tightest,
busiest two-sided book), devigs each leg worst-case from the two asks, and
prices "PTS Over + 3PM Over" with a Gaussian copula on the player's PTS-3PM
correlation from pts3_r.json. Output (markdown, best fair first):

  Player | Legs | PTS fair | 3PM fair | Fair odds | Fair x | +5% x | Devig r

Fair x is the SGP multiplier that breaks even; +5% x is a 5% edge. With
--dummy, both are divided by the dummy leg's fair win probability, so they
compare straight to a slip that includes it. Devig r is what to type into
the devig tool's Correlation box (it scales r to min(pA,pB) - pA*pB).

Legs on books wider than --max-spread (default 4c) are skipped, never guessed.
"""
import argparse
import json
import math
import os
import time
import unicodedata
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = "https://api.novig.com"
TYPES = {"POINTS": "pts", "THREE_POINTERS_MADE": "tpm"}
SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    w = "".join(c if c.isalnum() or c == " " else " " for c in s.replace("'", "").replace(".", "")).split()
    return "".join(x for x in w if x not in SUFFIX)


def fetch():
    q = {"league": "NBA", "marketType": ",".join(TYPES), "eventStatus": "OPEN_PREGAME", "limit": 5000}
    out, after = [], None
    for _ in range(20):
        if after:
            q["after"] = after
        req = urllib.request.Request(f"{HOST}/v3/public/catalog/markets?{urllib.parse.urlencode(q)}",
                                     headers={"Accept": "application/json", "User-Agent": "novig-sgp-scan"})
        with urllib.request.urlopen(req, timeout=30) as r:
            page = json.load(r)
        out += page.get("items", [])
        after = page.get("next")
        if not after:
            break
    return out


# --- math -------------------------------------------------------------------
def ncdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def nppf(p):
    lo, hi = -10.0, 10.0
    for _ in range(100):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if ncdf(m) < p else (lo, m)
    return (lo + hi) / 2


def joint(r, a, b):
    """P(both legs hit) under a Gaussian copula with margin correlation r."""
    x, y, n = nppf(a), nppf(b), 200
    h, tot = r / n, 0.0
    for i in range(n + 1):
        rho = i * h
        q = 1 - rho * rho
        f = math.exp(-(x * x - 2 * rho * x * y + y * y) / (2 * q)) / (2 * math.pi * math.sqrt(q))
        tot += f * (1 if i in (0, n) else 4 if i % 2 else 2)
    return a * b + tot * h / 3


def devig_worst(po, pu):
    """Worst (lowest) of multiplicative, additive, power and Shin devigs."""
    s = po + pu
    if s <= 1 + 1e-9:
        return po, pu
    c = [(po / s, pu / s), (po - (s - 1) / 2, pu - (s - 1) / 2)]
    lo, hi = 1.0, 20.0
    for _ in range(100):
        k = (lo + hi) / 2
        lo, hi = (k, hi) if po ** k + pu ** k > 1 else (lo, k)
    c.append((po ** k, pu ** k))

    def shin(z, q):
        return (math.sqrt(z * z + 4 * (1 - z) * q * q / s) - z) / (2 * (1 - z))
    lo, hi = 0.0, 0.5
    for _ in range(100):
        z = (lo + hi) / 2
        lo, hi = (z, hi) if shin(z, po) + shin(z, pu) > 1 else (lo, z)
    c.append((shin(z, po), shin(z, pu)))
    return min(x[0] for x in c), min(x[1] for x in c)


def american(p):
    return f"{-round(100 * p / (1 - p))}" if p >= 0.5 else f"+{round(100 * (1 - p) / p)}"


def devig_r(j, a, b):
    room = min(a, b) - a * b
    return (j - a * b) / room if room > 0 else 0.0


# --- Novig ladder -----------------------------------------------------------
def ladders(markets, max_spread):
    """{novig name: {stat: [rows sorted by line]}}, two-sided books only."""
    out = {}
    for m in markets:
        stat = TYPES.get(m["marketType"])
        if not stat:
            continue
        side = {o["name"].split()[0].lower(): o for o in m["outcomes"]}
        bo, bu = side.get("over", {}).get("bid"), side.get("under", {}).get("bid")
        if not bo or not bu:
            continue
        bid, ask = float(bo["price"]), 1 - float(bu["price"])
        if ask - bid > max_spread + 1e-9 or not 0 < bid < ask < 1:
            continue
        fo, _ = devig_worst(ask, 1 - bid)
        name = m["description"].rsplit(" ", 2)[0]
        out.setdefault(name, {}).setdefault(stat, []).append(
            {"line": float(m["strike"]), "p": fo, "spread": ask - bid, "vol": m.get("volume") or 0})
    for st in out.values():
        for rows in st.values():
            rows.sort(key=lambda r: r["line"])
    return out


def main_line(rows):
    """Main line = the one nearest 50/50 among the busiest/tightest books."""
    return min(rows, key=lambda r: (abs(r["p"] - 0.5) + r["spread"], -r["vol"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alts", action="store_true", help="also price one line up on each leg")
    ap.add_argument("--min-tpm", type=float, default=1.5, help="season 3PM average floor (default 1.5)")
    ap.add_argument("--min-r", type=float, default=0.0, help="PTS-3PM margin r floor")
    ap.add_argument("--max-spread", type=float, default=0.04, help="widest Novig book to price from (prob)")
    ap.add_argument("--dummy", type=float, default=1.0, help="dummy leg fair win prob, e.g. 0.979")
    ap.add_argument("--out", default=os.path.join(HERE, "fair_table.md"))
    a = ap.parse_args()

    rdata = json.load(open(os.path.join(HERE, "pts3_r.json")))
    rmap = {norm(k): (k, v) for k, v in rdata["players"].items()}
    lad = ladders(fetch(), a.max_spread)

    rows = []
    for nv_name, st in lad.items():
        hit = rmap.get(norm(nv_name))
        if not hit or "pts" not in st or "tpm" not in st:
            continue
        name, info = hit
        if info["tpm"] < a.min_tpm or info["r"] < a.min_r:
            continue
        P, T = main_line(st["pts"]), main_line(st["tpm"])
        combos = [(P, T)]
        if a.alts:
            up = lambda rs, L: next((r for r in rs if r["line"] == L["line"] + 1), None)
            for pp, tt in ((up(st["pts"], P), T), (P, up(st["tpm"], T))):
                if pp and tt:
                    combos.append((pp, tt))
        for pp, tt in combos:
            pa, pb = pp["p"], tt["p"]
            # k threes are 3k points: a 3PM line that forces the PTS line makes
            # the parlay just the 3PM leg.
            forced = 3 * (math.floor(tt["line"]) + 1) > pp["line"]
            j = min(pa, pb) if forced else joint(info["r"], pa, pb)
            fx = 1 / j / a.dummy
            rows.append({"name": name, "team": info["team"], "r": info["r"],
                         "legs": f"{int(pp['line'] + 0.5)}+ PTS / {int(tt['line'] + 0.5)}+ 3PM",
                         "pf": american(pa), "tf": american(pb), "fair": american(j),
                         "fx": fx, "fx5": fx * 1.05, "dv": devig_r(j, pa, pb), "j": j})
    rows.sort(key=lambda r: r["fx"])

    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    dummy = f" · breakevens include a dummy leg at {a.dummy:.3f}" if a.dummy < 1 else ""
    lines = [f"# Novig PTS + 3PM fair table · {when}{dummy}",
             f"r data: {rdata['generated_at'][:10]} · legs: Novig worst-case devig, books <= {a.max_spread * 100:g}c wide", "",
             "| Player | Tm | Legs | PTS fair | 3PM fair | Fair odds | Fair x | +5% x | Devig r |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['team']} | {r['legs']} | {r['pf']} | {r['tf']} | {r['fair']} | "
                     f"{r['fx']:.2f}x | {r['fx5']:.2f}x | {r['dv']:+.3f} |")
    text = "\n".join(lines) + "\n"
    open(a.out, "w").write(text)
    print(text)
    print(f"{len(rows)} combos -> {a.out}")


if __name__ == "__main__":
    main()
