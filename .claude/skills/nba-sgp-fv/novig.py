#!/usr/bin/env python3
"""Novig exchange prices for NBA player props, as fair values.

  python3 novig.py "Domantas Sabonis"          # the player's ladder
  python3 novig.py "Domantas Sabonis" ast 6.5  # one stat, nearest lines first

Reads Novig's public catalog (GET /v3/public/catalog/markets, no key, throttled
per IP at the edge): every open pregame market with each outcome's best bid.
Novig is an exchange, so a two-sided market has no vig to strip: the Over ask
is 1 - the Under bid, and the fair probability is the mid of bid and ask.
Pregame game markets charge no taker fee (fee.charged = WHEN_LIVE), so the mid
needs no fee adjustment.

The mid is only as good as the market is tight. Main lines run 0.5-2c wide;
alt lines run wider and some are junk (one-sided, or out of order with the
ladder). A line wider than MAX_SPREAD is shown but never priced from:
price.py shifts from the nearest tight line instead.
"""
import json
import os
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

HOST = os.environ.get("NOVIG_HOST", "https://api.novig.com")
TYPES = {"pts": "POINTS", "reb": "REBOUNDS", "ast": "ASSISTS", "tpm": "THREE_POINTERS_MADE"}
STAT = {v: k for k, v in TYPES.items()}
MAX_SPREAD = 0.04  # ask - bid on the Over, in probability
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm(name):
    """'Darius Acuff Jr.' / 'Nikola Jokić' -> 'darius acuff' / 'nikola jokic'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = "".join(c if c.isalnum() or c == " " else " " for c in s.replace("'", "")).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def fetch(league="NBA", stats=tuple(TYPES)):
    """Every open pregame market of these stat types, all pages."""
    q = {"league": league, "marketType": ",".join(TYPES[s] for s in stats),
         "eventStatus": "OPEN_PREGAME", "limit": 5000}
    out, after = [], None
    for _ in range(20):
        if after:
            q["after"] = after
        url = f"{HOST}/v3/public/catalog/markets?{urllib.parse.urlencode(q)}"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "mlbsgp-nba-sgp-fv"})
        with urllib.request.urlopen(req, timeout=30) as r:
            page = json.load(r)
        out += page.get("items", [])
        after = page.get("next")
        if not after:
            break
    return out


def quote(m):
    """One market as a row: line, Over bid/ask/mid, spread, volume."""
    side = {o["name"].split()[0].lower(): o for o in m["outcomes"]}
    bo = side.get("over", {}).get("bid")
    bu = side.get("under", {}).get("bid")
    row = {"stat": STAT[m["marketType"]], "line": float(m["strike"]), "volume": m["volume"],
           "starts": m["startsTs"], "market": m["marketId"],
           "bid": float(bo["price"]) if bo else None,
           "ask": 1 - float(bu["price"]) if bu else None}
    if row["bid"] is not None and row["ask"] is not None:
        row["mid"] = (row["bid"] + row["ask"]) / 2
        row["spread"] = row["ask"] - row["bid"]
    else:
        row["mid"] = row["spread"] = None
    return row


def player_name(m):
    """'Isaiah Stewart 1.5 REBOUNDS' -> 'Isaiah Stewart'."""
    return m["description"].rsplit(" ", 2)[0]


def ladder(markets, player):
    """(Novig's name, {stat: rows sorted by line}) for the player, or (None, {})."""
    want = norm(player)
    names = {player_name(m) for m in markets}
    hits = [n for n in names if norm(n) == want] or [n for n in names if want in norm(n)]
    if len(hits) != 1:
        return None, {}
    rows = {}
    for m in markets:
        if player_name(m) == hits[0] and m["marketType"] in STAT:
            rows.setdefault(STAT[m["marketType"]], []).append(quote(m))
    for v in rows.values():
        v.sort(key=lambda r: r["line"])
    return hits[0], rows


def tight(row, max_spread=MAX_SPREAD):
    return row["spread"] is not None and row["spread"] <= max_spread + 1e-9


def pick(rows, line, max_spread=MAX_SPREAD):
    """The row to price a leg at `line` from: that line if it's tight, else the
    nearest tight line (ties to the busier one). None when nothing is tight."""
    ok = [r for r in rows if tight(r, max_spread)]
    if not ok:
        return None
    return min(ok, key=lambda r: (abs(r["line"] - line), -r["volume"]))


def american(p):
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def show(name, rows, stat=None, line=None):
    print(f"Novig · {name} · {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    for s in ([stat] if stat else [k for k in TYPES if k in rows]):
        rs = rows.get(s, [])
        if line is not None:
            rs = sorted(rs, key=lambda r: abs(r["line"] - line))
        for r in rs:
            if r["mid"] is None:
                print(f"  {s} {r['line']:>5g}  one-sided (bid {r['bid']}, ask {r['ask']})")
                continue
            flag = "" if tight(r) else "  wide"
            print(f"  {s} {r['line']:>5g}  bid {r['bid']:.3f} ask {r['ask']:.3f}  mid {r['mid']:.1%}"
                  f"  O {american(r['mid']):+d} / U {american(1 - r['mid']):+d}"
                  f"  spread {r['spread'] * 100:.1f}c  vol {r['volume']:,}{flag}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    stat = sys.argv[2].lower() if len(sys.argv) > 2 else None
    if stat == "3pm" or stat == "threes":
        stat = "tpm"
    if stat and stat not in TYPES:
        raise SystemExit(f"stat {stat!r}: use pts, reb, ast or tpm")
    line = float(sys.argv[3]) if len(sys.argv) > 3 else None
    name, rows = ladder(fetch(), sys.argv[1])
    if not name:
        raise SystemExit(f"{sys.argv[1]!r}: not on Novig's open pregame NBA props (or ambiguous)")
    show(name, rows, stat, line)


if __name__ == "__main__":
    main()
