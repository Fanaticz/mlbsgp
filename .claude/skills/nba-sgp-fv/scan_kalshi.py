#!/usr/bin/env python3
"""Kalshi NBA SGP scan: the Novig scanner's NBA slips, priced as Kalshi combos.

  python3 scan_kalshi.py --dry      # the slips it would ask, no price asked (no key needed)
  python3 scan_kalshi.py --check    # is the key accepted? (reads the balance endpoint, asks nothing)
  python3 scan_kalshi.py            # ask them and print the best
  python3 scan_kalshi.py --json     # one JSON event per line (server.js: the Kalshi NBA board)
  python3 scan_kalshi.py --league nbaline   # a player's prop with a game line (nbaline_candidates)

What it asks, per player with open Kalshi props on a game that has not started:
  1  Points Yes + Threes Yes (the player's shrunk correlation, as on the Novig board).
  2  His other Yes + Yes pairs where r is at least --min-r: points + rebounds,
     points + assists, rebounds + assists, rebounds + threes, assists + threes.
  T  Teammates: each team's two highest points lines, Yes + Yes, as unrelated
     legs (scan.nba_mate_candidates has the measurement).
Kalshi's props are milestones ("25+ points" is Over 24.5). Each leg sits on the
milestone nearest Novig's main line where Novig has a tight book on that same
line; where it has none, on Kalshi's own milestone nearest even money.

Fair value: each leg is the tighter of two books on that line, devigged worst
case: Novig's exchange book (inside --max-spread) or Kalshi's own Yes bid /
ask (inside --kalshi-spread); the average of the two where they are within a
cent of each other in width. A row with a leg on a book wider than
--max-spread is marked rough (~). The legs are joined with the same Gaussian copula
as the Novig board.

Price: a combo on Kalshi is an auction. For each slip: create the combo market
(POST /multivariate_event_collections/{collection}), send a request for quote
for --stake dollars (POST /communications/rfqs), wait --wait seconds, read the
makers' answers (GET /communications/quotes?rfq_id=), delete the request. A
maker answers with a bid for No; buying Yes costs 1 - the best No bid. The fee
is Kalshi's taker fee, 0.07 x price x (1 - price) a contract, on top.
A pass and a refresh never accept anything. The one call that trades is
place() (--bet), run only when the page's Bet button is pressed.

Every call that asks is signed with an account's API key:
  KALSHI_KEY_ID        the key id
  KALSHI_PRIVATE_KEY   the private key (PEM text; "\\n" for line breaks is fine)
Asking costs something: Kalshi charges more rate-limit tokens for accounts
that ask often and rarely accept, an account may have 100 requests open and
create 5,000 new combos a week. So a pass asks at most --max slips (60).
"""
import argparse
import base64
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "nba-ast-pts-sgp"))
import novig  # noqa: E402
import price  # noqa: E402  shrunk_r
import scan  # noqa: E402  leg_text, usable, main_line, NBA_MATE_R, NBA_MATE_MIN
import sgp  # noqa: E402  joint, american, devig_worst, load

HOST = os.environ.get("KALSHI_HOST", "https://api.elections.kalshi.com")
API = "/trade-api/v2"
SERIES = {"KXNBAPTS": "pts", "KXNBAREB": "reb", "KXNBAAST": "ast", "KXNBA3PT": "tpm"}
NFL_SERIES = {"KXNFLREC": "rec", "KXNFLRECYDS": "yds", "KXNFLTD": "td", "KXNFLPASSATT": "att", "KXNFLPASSCOMP": "cmp",
              "KXNFLPASSYDS": "pyds", "KXNFLPASSTDS": "ptd", "KXNFLRSHATT": "car", "KXNFLRSHYDS": "ryds", "KXNFLRRYDS": "rry"}
PAIRS = (("pts", "reb"), ("pts", "ast"), ("reb", "ast"), ("reb", "tpm"), ("ast", "tpm"))
# The collections a same-game sports combo can be made in, the one the tape shows first.
COLLECTIONS = ("KXMVECROSSCATEGORY-R", "KXMVESPORTSMULTIGAMEEXTENDED-R")
TIP_S = 3 * 3600      # a market's occurrence_datetime is about this long after the game starts
FEE = 0.07            # taker fee = FEE x price x (1 - price) a contract
PACE_S = 1.0          # between two slips
REFUSED_AFTER = 3     # this many 401 / 403 answers with no price at all: stop


class Refused(Exception):
    """Kalshi answered a signed call with 401 or 403."""


_KEY = None


def _signer():
    """(key id, sign(bytes) -> bytes) from the environment, or SystemExit saying what is missing."""
    global _KEY
    if _KEY:
        return _KEY
    kid, pem = os.environ.get("KALSHI_KEY_ID", "").strip(), os.environ.get("KALSHI_PRIVATE_KEY", "").strip()
    if not kid or not pem:
        raise SystemExit("Kalshi key not set on the server: KALSHI_KEY_ID and KALSHI_PRIVATE_KEY (Railway, Variables).")
    pem = pem.strip('"').replace("\\n", "\n")
    if "BEGIN" not in pem:   # the key's body alone, without its first and last lines
        pem = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(pem.split()) + "\n-----END PRIVATE KEY-----"
    else:                    # a key pasted on one line: the breaks became spaces
        m = re.match(r"\s*(-----BEGIN [A-Z ]+-----)(.*?)(-----END [A-Z ]+-----)\s*$", pem, re.S)
        if m:
            pem = m.group(1) + "\n" + "\n".join(m.group(2).split()) + "\n" + m.group(3)
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519, padding
    except ImportError:
        raise SystemExit("The server is missing the Python package 'cryptography' (requirements.txt): redeploy.")
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except Exception as e:  # noqa: BLE001  whatever the parser says, the cause is the pasted text
        raise SystemExit(f"KALSHI_PRIVATE_KEY could not be read as a private key ({type(e).__name__}). "
                         "Paste the whole downloaded key, from -----BEGIN to -----END.")
    if isinstance(key, ed25519.Ed25519PrivateKey):
        sign = key.sign
    else:   # RSA: RSA-PSS, SHA-256, salt as long as the digest
        sign = lambda b: key.sign(b, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),  # noqa: E731
                                  hashes.SHA256())
    _KEY = (kid, sign)
    return _KEY


def call(method, path, body=None, query=None, signed=True):
    """(status, parsed JSON or {}) for one Kalshi call. 429 and dropped
    connections are retried; 401 / 403 on a signed call raise Refused."""
    full = API + path
    url = HOST + full + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(6):
        headers = {"Accept": "application/json", "User-Agent": "nba-sgp-fv"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if signed:
            kid, sign = _signer()
            ts = str(int(time.time() * 1000))
            # the signed text: timestamp + method + path, without the query string
            headers.update({"KALSHI-ACCESS-KEY": kid, "KALSHI-ACCESS-TIMESTAMP": ts,
                            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sign((ts + method + full).encode())).decode()})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                err = json.loads(raw)
            except ValueError:
                err = {"message": raw[:200]}
            err = err.get("error", err) if isinstance(err, dict) else {"message": str(err)[:200]}
            if e.code == 429 and err.get("code") != "open_rfq_limit_exceeded" and attempt < 5:
                time.sleep(float(e.headers.get("Retry-After") or 2 + 2 * attempt))
                continue
            if signed and e.code in (401, 403):
                raise Refused(f"{e.code} {err.get('code') or ''} {err.get('message') or ''}".strip())
            return e.code, err
        except OSError:
            if attempt == 5:
                return 0, {"message": "unreachable"}
            time.sleep(2 + 2 * attempt)
    return 429, {"code": "too_many_requests"}


def kalshi_props(before=None, series=SERIES):
    """{normalised player name: {"name", "team", "starts" (ms), "game", "stats":
    {stat: [{"line", "ticker", "event", "bid", "ask"}]}}} from Kalshi's open NBA
    player-prop markets on games that have not started. No key needed."""
    out, now = {}, time.time() * 1000
    for series, stat in series.items():
        cursor = None
        for _ in range(20):
            q = {"series_ticker": series, "status": "open", "limit": 1000}
            if cursor:
                q["cursor"] = cursor
            _, d = call("GET", "/markets", query=q, signed=False)
            for m in d.get("markets") or []:
                try:
                    starts = time.mktime(time.strptime(m["occurrence_datetime"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
                    line, parts = float(m["floor_strike"]), m["ticker"].split("-")
                    name = (m.get("yes_sub_title") or "").rsplit(":", 1)[0].strip()
                    bid, ask = float(m["yes_bid_dollars"]), float(m["yes_ask_dollars"])
                except (KeyError, TypeError, ValueError):
                    continue
                starts = (starts - TIP_S) * 1000
                if not name or len(parts) < 4 or starts <= now or (before and starts >= before):
                    continue
                who = out.setdefault(novig.norm(name), {"name": name, "team": parts[2][:3], "starts": starts,
                                                        "game": parts[1], "stats": {}})
                who["stats"].setdefault(stat, []).append({"line": line, "ticker": m["ticker"], "event": m["event_ticker"],
                                                          "bid": bid, "ask": ask})
            cursor = d.get("cursor")
            if not cursor or not d.get("markets"):
                break
    return out


def pick_leg(stat, kal, nv_rows, a):
    """The leg for this stat. Each Kalshi milestone is priced off the tighter
    of two books on that same line: Novig's (inside --max-spread) or Kalshi's
    own Yes bid / ask (inside --kalshi-spread); where the two are within a
    cent of each other in width, off the average of their two fair values. The milestone taken is the one
    nearest Novig's main line, or nearest even money where Novig lists nothing
    usable. None when no milestone has a book to price it from."""
    nv = {r["line"]: r for r in nv_rows if scan.usable(r, a.max_spread)}
    priced = []
    for k in kal:
        books = []
        if k["line"] in nv:
            books.append((nv[k["line"]]["spread"], nv[k["line"]]["fo"], "novig"))
        if 0 < k["bid"] < k["ask"] < 1 and k["ask"] - k["bid"] <= a.kalshi_spread + 1e-9:
            books.append((k["ask"] - k["bid"], sgp.devig_worst(k["ask"], 1 - k["bid"])[0], "kalshi"))
        if books:
            width, fo, src = min(books)   # the tighter book
            if len(books) == 2 and abs(books[0][0] - books[1][0]) <= 0.01 + 1e-9:
                # about as tight as each other: the two fair values averaged
                width, fo, src = max(books)[0], (books[0][1] + books[1][1]) / 2, "both"
            if a.lo <= fo <= a.hi:
                priced.append((k, fo, width, src))
    if not priced:
        return None
    main = scan.main_line(list(nv.values()))["line"] if nv else None
    k, fo, width, src = min(priced, key=lambda x: (abs(x[0]["line"] - main) if main is not None else 0, abs(x[1] - 0.5)))
    L = {"stat": stat, "side": "over", "line": k["line"], "p": fo, "fair": sgp.american(fo), "width": width,
         "id": k["ticker"], "event": k["event"], "src": src}
    same = next((r for r in nv_rows if r["line"] == k["line"] and r["ids"].get("over")), None)
    if same:   # Novig's Over on this same line, for its price on the same slip (novig_price)
        L["nv"] = same["ids"]["over"]
    return L


WORD = {"pts": "points", "reb": "rebounds", "ast": "assists", "tpm": "threes", "rec": "receptions", "yds": "receiving yards",
        "td": "touchdowns", "att": "pass attempts", "cmp": "completions", "pyds": "passing yards", "ptd": "passing TDs",
        "car": "carries", "ryds": "rushing yards", "rry": "rush + rec yards", "pra": "pts + reb + ast"}


def nfl_candidates(a):
    """NFL: one player's own pairs, Yes + Yes, every pair in scan.NFL_PAIRS with r at least --min-r."""
    d = json.load(open(scan.NFL_DATA))
    key = {novig.norm(p["name"]): p for p in d["players"]}
    board = kalshi_props(a.before, NFL_SERIES)
    markets = novig.fetch("NFL", scan.NFL_STATS)
    out = []
    for nm, info in board.items():
        p = key.get(nm)
        if not p:
            continue
        _, rows = novig.ladder(markets, p["name"])
        info["starts"] = next((r["starts"] for v in rows.values() for r in v), info["starts"])
        legs = {}
        for stat, kal in info["stats"].items():
            L = pick_leg(stat, kal, rows.get(stat, []), a)
            if L:
                n = int(L["line"] + 0.5)
                L["text"] = "anytime touchdown" if stat == "td" and n == 1 else f"{n}+ {WORD[stat]}"
                legs[stat] = L
        for x, y in scan.NFL_PAIRS:
            if x not in legs or y not in legs:
                continue
            r = scan.nfl_r(p, x, y)
            if r is None or r < a.min_r:
                continue
            la, lb = legs[x], legs[y]
            j = sgp.joint(r, la["p"], lb["p"])
            out.append({"key": f"{la['id']},{lb['id']}", "tier": 1, "player": p["name"], "id": p.get("athlete_id") or p.get("id") or nm,
                        "team": p.get("team_abbr") or p.get("team") or info["team"], "starts": info["starts"],
                        "legs": [dict(la), dict(lb)], "label": f"{la['text']} · {lb['text']}", "r": r, "j": j, "forced": False,
                        "devig_r": sgp.devig_r(j, la["p"], lb["p"]), "book": "kalshi", "event": info["game"],
                        "rough": any(L["width"] > a.max_spread + 1e-9 for L in (la, lb)), "legs_x": 1 / (la["p"] * lb["p"])})
    out.sort(key=lambda c: (c["starts"], -c["r"]))
    return (out[:a.max] if a.max else out), d


def candidates(a):
    d, by = sgp.load()
    key = {novig.norm(n): p for n, p in by.items()}
    board = kalshi_props(a.before)
    markets = novig.fetch()
    out, teams = [], {}
    for nm, info in board.items():
        p = key.get(nm)
        if not p:
            continue
        _, rows = novig.ladder(markets, p["name"])
        info["starts"] = next((r["starts"] for v in rows.values() for r in v), info["starts"])
        legs = {}
        for stat, kal in info["stats"].items():
            L = pick_leg(stat, kal, rows.get(stat, []), a)
            if L:
                L["text"] = f"{int(L['line'] + 0.5)}+ {WORD[stat]}"
                legs[stat] = L

        def row_of(tier, r, la, lb, who=None, pid=None, label=None, kind=None, info=info, p=p):
            j = sgp.joint(r, la["p"], lb["p"])
            c = {"key": f"{la['id']},{lb['id']}", "tier": tier, "player": who or p["name"], "id": pid or p["athlete_id"],
                 "team": p.get("team_abbr") or info["team"], "starts": info["starts"], "legs": [dict(la), dict(lb)],
                 "label": label or f"{la['text']} · {lb['text']}", "r": r, "j": j, "forced": False,
                 "devig_r": sgp.devig_r(j, la["p"], lb["p"]), "book": "kalshi", "event": info["game"],
                 "rough": any(L["width"] > a.max_spread + 1e-9 for L in (la, lb)), "legs_x": 1 / (la["p"] * lb["p"])}
            if kind:
                c["kind"] = kind
            return c
        if "pts" in legs and "tpm" in legs:
            r = price.shrunk_r(d, by, p, "pts", "tpm")[0]
            # k threes are 3k points: a threes leg that forces the points leg is one leg, not two
            if r > 0 and 3 * (math.floor(legs["tpm"]["line"]) + 1) <= legs["pts"]["line"]:
                out.append(dict(row_of(1, r, legs["pts"], legs["tpm"]), main=True))
        for x, y in PAIRS:
            if x in legs and y in legs:
                r = price.shrunk_r(d, by, p, x, y)[0]
                if r is not None and r >= a.min_r:
                    out.append(row_of(2, r, legs[x], legs[y]))
        if "pts" in legs:
            teams.setdefault((info["game"], info["team"]), []).append((p, legs["pts"], row_of))
    last = lambda p: p["name"].split(" ", 1)[-1]   # noqa: E731
    for ps in teams.values():
        ps.sort(key=lambda x: -x[1]["line"])
        if len(ps) >= 2 and ps[1][1]["line"] >= scan.NBA_MATE_MIN:
            (pa, la, mk), (pb, lb, _) = ps[0], ps[1]
            out.append(mk(0, scan.NBA_MATE_R, la, lb, who=f"{pa['name']} + {pb['name']}", pid=f"{pa['athlete_id']}+{pb['athlete_id']}",
                          label=f"{last(pa)} {la['text']} · {last(pb)} {lb['text']}", kind="mates"))
    # teammates first (one a team, and the shape Novig misprices), then Points + Threes, then the rest
    out.sort(key=lambda c: (c["tier"], c["starts"], -c["r"]))
    return (out[:a.max] if a.max else out), d


def _markets(series):
    """Every open market of a Kalshi series (no key needed)."""
    out, cursor = [], None
    for _ in range(20):
        q = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            q["cursor"] = cursor
        _, d = call("GET", "/markets", query=q, signed=False)
        out += d.get("markets") or []
        cursor = d.get("cursor")
        if not cursor or not d.get("markets"):
            break
    return out


def _team(s):
    """A college's name boiled down for matching: 'Michigan St.' and 'Michigan State' agree."""
    s = re.sub(r"[^a-z ]", "", s.lower().replace("&", " and ").replace("-", " "))
    return " ".join({"st": "state", "u": "university"}.get(w, w) for w in s.split())


def _same(a, b):
    import difflib
    a, b = _team(a), _team(b)
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def cbb_candidates(a):
    """College basketball: a game's spread with its total, the two pairings
    that go together in the box scores (cbb_line_correlations.json, by size of
    spread). Kalshi lists "X wins by over 7.5" and "Over 150.5": the favourite
    covering and the Over are Yes legs, the underdog covering and the Under
    are No legs on those same markets. Fair values are Novig's books on the
    same lines; a game Novig doesn't list, or whose teams can't be matched by
    name, is left out (Kalshi's own college books are 8 to 10 cents wide)."""
    shapes = json.load(open(scan.CBB_LINES))
    S, buckets = shapes["shapes"]["fav_cover+over"], shapes["buckets"]
    now, games = time.time() * 1000, {}
    for kind, series in (("spread", "KXNCAAMBSPREAD"), ("total", "KXNCAAMBTOTAL")):
        for m in _markets(series):
            try:
                starts = (time.mktime(time.strptime(m["occurrence_datetime"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone - TIP_S) * 1000
                line = float(m["floor_strike"])
            except (KeyError, TypeError, ValueError):
                continue
            if starts <= now or (a.before and starts >= a.before):
                continue
            g = games.setdefault(m["event_ticker"].split("-", 1)[1], {"starts": starts, "spread": [], "total": []})
            row = {"line": line, "ticker": m["ticker"], "event": m["event_ticker"]}
            if kind == "spread":
                t, ab = re.match(r"(.+) wins by over", m.get("title") or ""), re.match(r"([A-Z]+)\d+$", m["ticker"].rsplit("-", 1)[-1])
                if not t or not ab:
                    continue
                row["team"], row["abbr"] = t.group(1).strip(), ab.group(1)
            g[kind].append(row)
    nv = {}
    for m in novig.catalog({"league": "NCAAB", "marketType": "SPREAD,TOTAL", "eventStatus": "OPEN_PREGAME"}):
        t = scan.two_way(m)
        if not t or t["spread"] > a.max_spread + 1e-9:
            continue
        e = nv.setdefault(m["eventId"], {"starts": m["startsTs"], "spread": {}, "total": {}, "teams": set(), "desc": ""})
        if m["marketType"] == "TOTAL":
            e["total"][t["strike"]] = t
            e["desc"] = t["desc"].split(" t")[0]
        else:
            for i, n in enumerate(t["names"]):
                x = re.match(r"(.+) ([+-]\d+(?:\.\d+)?)$", n)
                if x:
                    e["teams"].add(x.group(1))
                    e["spread"][(x.group(1), float(x.group(2)))] = (t["p"][i], t["spread"], t["ids"][i])
    import difflib
    like = lambda x, y: difflib.SequenceMatcher(None, x.upper(), y.upper()).ratio()   # noqa: E731
    out = []
    for code, g in games.items():
        if not g["spread"] or not g["total"]:
            continue
        # the game on Novig: the same start (within 45 minutes) and the nearest pair of team codes
        letters, best = re.sub(r"^\d{2}[A-Z]{3}\d{2}", "", code), None
        for e in nv.values():
            if len(e["teams"]) != 2 or not e["desc"] or abs(e["starts"] - g["starts"]) > 45 * 60e3:
                continue
            score = like(letters, e["desc"].replace(" @ ", ""))
            if score >= 0.6 and (not best or score > best[0]):
                best = (score, e)
        if not best:
            continue
        e, name = best[1], {}
        n = sorted(e["teams"])
        for row in g["spread"]:   # Kalshi's team -> Novig's, by code or by name, whichever is the closer
            s0, s1 = (max(like(row["abbr"], x), _same(row["team"], x)) for x in n)
            if abs(s0 - s1) >= 0.15:
                name[row["team"]] = n[0] if s0 > s1 else n[1]
        g["spread"] = [r for r in g["spread"] if r["team"] in name]
        # the spread leg: "X wins by over L" is Novig's "X -L"; nearest even money on a book both list
        sp = [(r, e["spread"][(name[r["team"]], -r["line"])]) for r in g["spread"] if (name[r["team"]], -r["line"]) in e["spread"]]
        to = [(r, e["total"][r["line"]]) for r in g["total"] if r["line"] in e["total"]]
        if not sp or not to:
            continue
        ks, (pf, ws, nv_fav) = min(sp, key=lambda x: abs(x[1][0] - 0.5))
        kt_, t = min(to, key=lambda x: abs(x[1]["p"][0] - 0.5))
        po, wt = t["p"][0], t["spread"]
        if not (a.lo <= pf <= a.hi and a.lo <= po <= a.hi):
            continue
        band = next((b for b, (lo, hi) in zip(S["by_spread"], buckets) if lo <= ks["line"] < hi), None)
        r = S["all"]["r"]
        if band and band["n"] >= scan.CBB_MIN_GAMES and not band["r_lo"] <= r <= band["r_hi"]:
            r = band["r"]
        fav, dog = name[ks["team"]], next(x for x in n if x != name[ks["team"]])
        legs = {"fav": {"stat": "cover", "side": "over", "yes": True, "p": pf, "text": f"{fav} -{ks['line']:g}"},
                "dog": {"stat": "cover", "side": "under", "yes": False, "p": 1 - pf, "text": f"{dog} +{ks['line']:g}"},
                "over": {"stat": "over", "side": "over", "yes": True, "p": po, "text": f"Over {kt_['line']:g}"},
                "under": {"stat": "over", "side": "under", "yes": False, "p": 1 - po, "text": f"Under {kt_['line']:g}"}}
        nv_dog = e["spread"].get((next(x for x in n if x != name[ks["team"]]), ks["line"]), (0, 0, None))[2]
        for k, nid in (("fav", nv_fav), ("dog", nv_dog), ("over", t["ids"][0]), ("under", t["ids"][1])):
            if nid:
                legs[k]["nv"] = nid
        for k, L in legs.items():
            src = ks if k in ("fav", "dog") else kt_
            L.update(line=src["line"], fair=sgp.american(L["p"]), width=ws if k in ("fav", "dog") else wt,
                     id=src["ticker"], event=src["event"], src="novig")
        # fav + over and dog + under share the measured r; the other two pairings have its opposite
        pairs = (("fav", "over"), ("dog", "under")) if r >= 0 else (("fav", "under"), ("dog", "over"))
        for x, y in pairs:
            la, lb, rr = legs[x], legs[y], abs(r)
            j = sgp.joint(rr, la["p"], lb["p"])
            out.append({"key": f"{la['id']}:{x},{lb['id']}:{y}", "tier": 1, "player": e["desc"], "id": code,
                        "team": "CBB", "starts": e["starts"], "legs": [dict(la), dict(lb)], "label": f"{la['text']} · {lb['text']}",
                        "r": rr, "j": j, "forced": False, "devig_r": sgp.devig_r(j, la["p"], lb["p"]), "book": "kalshi",
                        "event": code, "rough": False, "legs_x": 1 / (la["p"] * lb["p"])})
    out.sort(key=lambda c: (c["starts"], -c["r"]))
    return (out[:a.max] if a.max else out), {"generated_at": shapes["generated_at"]}


LINE_SERIES = {"KXNBASPREAD": "cover", "KXNBATOTAL": "tot", "KXNBATEAMTOTAL": "tt", "KXNBA1HSPREAD": "h1cover",
               "KXNBA1HTOTAL": "h1tot"}
LINE_NOVIG = {"SPREAD": "cover", "TOTAL": "tot", "TEAM_TOTAL": "tt", "SPREAD_1H": "h1cover", "TOTAL_1H": "h1tot"}
LINE_STATS = dict(SERIES, KXNBAPRA="pra")
NEAR_EVEN = 0.13      # a leg of a prop + line slip is within this of 50%: the r's are measured at about the median


def nbaline_candidates(a):
    """NBA prop + game line (--league nbaline): a player's milestone with a
    game line on the side that goes with it, and his Under (No on the same
    milestone) with the other side. The lines: his team covering, his team's
    total, the other team's total, the game total, the first half's spread
    and total (--team-lines). The r is scan.nba_prop_r's: league-wide for a
    player with that line on a team with tonight's spread, less one standard
    error; asked where the fitted |r| is at least --line-r, and each player's
    --per highest pairings, as on the Novig NBA Team board.

    Kalshi lists "X wins by over 7.5", "Over 231.5" and "X over 110.5": the
    other team covering and an Under are No legs on those markets. Every leg
    is priced like a prop leg: the tighter of Novig's book on the same line
    and Kalshi's own, and it sits within 13 points of 50%."""
    T = json.load(open(scan.NBA_LINES))
    d, by = sgp.load()
    key = {novig.norm(n): p for n, p in by.items()}
    now, games = time.time() * 1000, {}   # Kalshi's game code -> {"starts", kind: [row]}
    for series, kind in LINE_SERIES.items():
        for m in _markets(series):
            try:
                starts = (time.mktime(time.strptime(m["occurrence_datetime"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone - TIP_S) * 1000
                row = {"line": float(m["floor_strike"]), "ticker": m["ticker"], "event": m["event_ticker"],
                       "bid": float(m["yes_bid_dollars"]), "ask": float(m["yes_ask_dollars"])}
            except (KeyError, TypeError, ValueError):
                continue
            if starts <= now or (a.before and starts >= a.before):
                continue
            if kind in ("cover", "h1cover", "tt"):
                t = re.match(r"([A-Z]+)\d+$", m["ticker"].rsplit("-", 1)[-1])
                if not t:
                    continue
                row["team"] = t.group(1)
            games.setdefault(m["event_ticker"].split("-", 1)[1], {"starts": starts}).setdefault(kind, []).append(row)
    # Novig's books on the same lines: {frozenset of the two team codes: {(kind, team or None, line): (p Yes, width, Yes id, No id)}}
    nv, by_event = {}, {}
    for m in novig.catalog({"league": "NBA", "eventStatus": "OPEN_PREGAME", "marketType": "MONEY," + ",".join(LINE_NOVIG)}):
        by_event.setdefault(m["eventId"], []).append(m)
    for ms in by_event.values():
        sub = {o.get("subjectId"): o["name"] for m in ms if m["marketType"] == "MONEY" for o in m["outcomes"]}
        if len(sub) != 2:
            continue
        book = nv.setdefault(frozenset(sub.values()), {"starts": ms[0]["startsTs"]})
        for m in ms:
            kind, t = LINE_NOVIG.get(m["marketType"]), scan.two_way(m)
            if not kind or not t or t["spread"] > a.max_spread + 1e-9:
                continue
            if kind in ("cover", "h1cover"):
                for i, n in enumerate(t["names"]):   # "LAL -3.5" is Kalshi's "LAL wins by over 3.5"
                    x = re.match(r"(\S+) -(\d+(?:\.\d+)?)$", n)
                    if x:
                        book[(kind, x.group(1), float(x.group(2)))] = (t["p"][i], t["spread"], t["ids"][i], t["ids"][1 - i])
            elif kind == "tt":
                tm = sub.get(m["outcomes"][0].get("subjectId"))
                if tm:
                    book[(kind, tm, t["strike"])] = (t["p"][0], t["spread"], t["ids"][0], t["ids"][1])
            else:
                book[(kind, None, t["strike"])] = (t["p"][0], t["spread"], t["ids"][0], t["ids"][1])
    for code, g in games.items():
        teams = {r["team"] for k in ("cover", "tt", "h1cover") for r in g.get(k, [])}
        book = next((b for ts, b in nv.items() if ts == teams or (len(teams) < 2 and all(t in code for t in ts))), {})
        g["starts"], g["teams"] = book.get("starts", g["starts"]), teams
        for kind in LINE_SERIES.values():
            for r in g.get(kind, []):
                books, n = [], book.get((kind, r.get("team"), r["line"]))
                if n:
                    books.append((n[1], n[0], "novig"))
                if 0 < r["bid"] < r["ask"] < 1 and r["ask"] - r["bid"] <= a.kalshi_spread + 1e-9:
                    books.append((r["ask"] - r["bid"], sgp.devig_worst(r["ask"], 1 - r["bid"])[0], "kalshi"))
                if not books:
                    continue
                width, p, src = min(books)
                if len(books) == 2 and abs(books[0][0] - books[1][0]) <= 0.01 + 1e-9:
                    width, p, src = max(books)[0], (books[0][1] + books[1][1]) / 2, "both"
                r.update(p=p, width=width, src=src, nv=n and (n[2], n[3]))
        # who is favoured and by how much: the full-game "wins by over" nearest even money
        sp = [r for r in g.get("cover", []) if "p" in r and 0.25 <= r["p"] <= 0.75]
        if sp:
            m = min(sp, key=lambda r: abs(r["p"] - 0.5) + r["width"])
            g["fav"], g["spread"] = m["team"], m["line"]

    def line_leg(g, kind, team, yes):
        """The game-line leg nearest even money: team covering (or its total
        going Over) when yes, the Under when not. A team covering is Yes on
        its own "wins by over" or No on the other team's."""
        half, opts = " 1H" if kind.startswith("h1") else "", []
        for r in g.get(kind, []):
            if "p" not in r:
                continue
            if kind.endswith("cover"):
                y = r["team"] == team
                text = f"{team} {'-' if y else '+'}{r['line']:g}{half}"
            elif kind == "tt":
                if r["team"] != team:
                    continue
                y, text = yes, f"{team} team total {'Over' if yes else 'Under'} {r['line']:g}"
            else:
                y, text = yes, f"{'Over' if yes else 'Under'} {r['line']:g}{half}"
            p = r["p"] if y else 1 - r["p"]
            if abs(p - 0.5) <= NEAR_EVEN:
                L = {"stat": kind, "side": "over" if y else "under", "yes": y, "line": r["line"], "p": p, "fair": sgp.american(p),
                     "width": r["width"], "id": r["ticker"], "event": r["event"], "src": r["src"], "text": text}
                if r.get("nv") and r["nv"][0 if y else 1]:
                    L["nv"] = r["nv"][0 if y else 1]
                opts.append(L)
        return min(opts, key=lambda L: abs(L["p"] - 0.5) + L["width"]) if opts else None

    board = kalshi_props(a.before, LINE_STATS)
    markets = novig.fetch("NBA", scan.NBA_TEAM_STATS)
    out = []
    for nm, info in board.items():
        p, g = key.get(nm), games.get(info["game"])
        if not p or not g or "fav" not in g or info["team"] not in g["teams"] or len(g["teams"]) != 2:
            continue
        season = (p.get("by_season") or {}).get(str(p.get("latest_season"))) or {}
        if ((season if season.get("games", 0) >= 5 else p).get("min_mean") or 0) < scan.NBA_MIN_MINUTES:
            continue   # a bench player's numbers go the other way in a blowout (scan.nba_team_candidates)
        me = info["team"]
        them = next(t for t in g["teams"] if t != me)
        my_spread = -g["spread"] if me == g["fav"] else g["spread"]
        _, rows = novig.ladder(markets, p["name"])
        mine = []
        for stat, kal in info["stats"].items():
            la = pick_leg(stat, kal, rows.get(stat, []), a)
            if not la or abs(la["p"] - 0.5) > NEAR_EVEN:
                continue
            n = int(la["line"] + 0.5)
            la.update(yes=True, text=f"{n}+ {WORD[stat]}")
            same = next((r for r in rows.get(stat, []) if r["line"] == la["line"]), None)
            lu = dict(la, side="under", yes=False, p=1 - la["p"], fair=sgp.american(1 - la["p"]), text=f"under {n} {WORD[stat]}")
            lu.pop("nv", None)
            if same and same["ids"].get("under"):
                lu["nv"] = same["ids"]["under"]
            avg = scan.nba_role(stat, {"line": la["line"], "fo": la["p"]})
            for ev in a.team_lines:
                _, kind, whose = scan.NBA_PROP_LINES[ev]
                fit, r, games_n = scan.nba_prop_r(T, stat, avg, ev, my_spread)
                if fit is None or not r:
                    continue
                if fit < 0 and kind.endswith("cover"):   # goes against his own team covering
                    if fit > -scan.NBA_AGAINST_R or my_spread > -scan.NBA_AGAINST_SPREAD:
                        continue
                elif abs(fit) < a.line_r:
                    continue
                team = them if whose == "theirs" else me
                for over in (1, -1):   # his Over with the side that goes with it, his Under with the other
                    way = over if r > 0 else -over
                    lb = line_leg(g, kind, team if way > 0 or not kind.endswith("cover") else next(t for t in g["teams"] if t != team), way > 0)
                    if not lb:
                        continue
                    lp, rr = la if over > 0 else lu, abs(r)
                    j = sgp.joint(rr, lp["p"], lb["p"])
                    mine.append({"key": f"{lp['id']}:{'y' if lp['yes'] else 'n'},{lb['id']}:{'y' if lb['yes'] else 'n'}", "tier": 1,
                                 "player": p["name"], "id": p["athlete_id"], "team": me, "starts": g["starts"],
                                 "legs": [dict(lp), dict(lb)], "label": f"{lp['text']} · {lb['text']}", "r": rr, "j": j, "forced": False,
                                 "devig_r": sgp.devig_r(j, lp["p"], lb["p"]), "book": "kalshi", "event": info["game"], "kind": ev,
                                 "line": ev, "role": True, "spread": my_spread, "fit_r": abs(fit), "games": games_n,
                                 "rough": any(L["width"] > a.max_spread + 1e-9 for L in (lp, lb)), "legs_x": 1 / (lp["p"] * lb["p"])})
        best = sorted({(c["legs"][0]["stat"], c["line"]): c["r"] for c in mine}.items(), key=lambda kv: -kv[1])[:a.per]
        out += [c for c in mine if (c["legs"][0]["stat"], c["line"]) in dict(best)]
    out.sort(key=lambda c: (c["starts"], -c["r"]))
    return (out[:a.max] if a.max else out), d


def ask(c, a):
    """(Yes price a contract before the fee, None) for the slip, or (None, why)."""
    body = {"selected_markets": [{"market_ticker": L["id"], "event_ticker": L["event"], "side": "yes" if L.get("yes", True) else "no"} for L in c["legs"]]}
    ticker = why = None
    for coll in COLLECTIONS:
        st, d = call("POST", f"/multivariate_event_collections/{coll}", body)
        if st in (200, 201) and d.get("market_ticker"):
            ticker = d["market_ticker"]
            break
        why = {"conflicting_leg_outcomes": "Kalshi says these legs can't both hit",
               "duplicated_legs": "Kalshi says one leg already decides the other",
               "invalid_market_combination": "Kalshi won't combine these legs"}.get(d.get("code"), f"{st} {d.get('code') or d.get('message') or ''}".strip())
        if d.get("code") in ("conflicting_leg_outcomes", "duplicated_legs"):
            break
    if not ticker:
        return None, why or "the combo could not be created"
    st, d = call("POST", "/communications/rfqs", {"market_ticker": ticker, "rest_remainder": False,
                                                  "target_cost_dollars": f"{a.stake:.2f}"})
    rfq = d.get("id") or (d.get("rfq") or {}).get("id")
    if st not in (200, 201) or not rfq:
        return None, f"request for quote refused: {st} {d.get('code') or d.get('message') or ''}".strip()
    best = None
    try:
        for _ in range(a.polls):
            time.sleep(a.wait / a.polls)
            st, d = call("GET", "/communications/quotes", query={"rfq_id": rfq, "rfq_user_filter": "self", "limit": 100})
            for q in d.get("quotes") or []:
                try:
                    nb = float(q.get("no_bid_dollars") or 0)
                except ValueError:
                    continue
                if q.get("status", "open") == "open" and 0 < nb < 1:
                    best = max(best or 0, nb)   # the highest No bid is the cheapest Yes
    finally:
        call("DELETE", f"/communications/rfqs/{rfq}")
    if not best:
        return None, "no maker answered"
    return 1 - best, None


def novig_price(c):
    """Novig's price for the same slip, as a second opinion beside Kalshi's:
    c["novig_x"] (what its slip pays after its parlay fee) and c["novig_ev"]
    at this row's fair value. Asked only where Novig lists every leg on the
    same line; one keyless Novig quote."""
    c.pop("novig_x", None)
    c.pop("novig_ev", None)
    ids = [L.get("nv") for L in c["legs"]]
    if not all(ids):
        return
    q, _ = novig.parlay(ids)
    if q:
        c["novig_x"] = novig.slip_multiplier(q)
        c["novig_ev"] = c["j"] * c["novig_x"] - 1


def slip_x(p):
    """What $1 pays on a Yes bought at p a contract: 1 / (price + fee)."""
    return 1 / (p + FEE * p * (1 - p))


def finish(c, yes, unit, kelly):
    p, dec = sgp.prob(sgp.american(c["j"])), slip_x(yes)
    b = dec - 1
    qk = max(0.0, (p * b - (1 - p)) / b) * kelly * 100
    c.update(fair=sgp.american(c["j"]), fair_x=1 / p, quote=yes, raw_x=1 / yes, slip_x=dec, slip=sgp.american(1 / dec),
             ev=p * dec - 1, qk=qk, wager=qk * unit, at=time.time())
    return c


def reprice(c, a):
    """Re-read a row's NBA or NFL legs off Kalshi's own book and rebuild its
    fair value at the same r (see requote). None, or why it can't be done."""
    if a.league == "cbb":
        return None
    _, d = call("GET", "/markets", query={"tickers": ",".join(L["id"] for L in c["legs"]), "limit": 10}, signed=False)
    book = {m["ticker"]: m for m in d.get("markets") or []}
    if any(L["id"] not in book or book[L["id"]].get("status") != "active" for L in c["legs"]):
        return "a leg is no longer open on Kalshi"
    old = [L["p"] for L in c["legs"]]
    for L in c["legs"]:
        try:
            bid, offer = float(book[L["id"]]["yes_bid_dollars"]), float(book[L["id"]]["yes_ask_dollars"])
        except (KeyError, TypeError, ValueError):
            return "Kalshi's book on a leg could not be read"
        if not (0 < bid < offer < 1 and offer - bid <= a.kalshi_spread + 1e-9):
            # No book to price the leg from now: an old fair value under a new price is worse than no row.
            return f"{L.get('text') or 'a leg'} has no tight book on Kalshi right now: press Fetch"
        p = sgp.devig_worst(offer, 1 - bid)[0]
        p = p if L.get("yes", True) else 1 - p   # a No leg: the other side of the same book
        L.update(p=p, fair=sgp.american(p), width=offer - bid, src="kalshi")
    new = [L["p"] for L in c["legs"]]
    if new != old:
        lo, hi = -0.99, 0.99   # the r that gave this row's joint
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if sgp.joint(mid, *old) < c["j"] else (lo, mid)
        c["j"] = sgp.joint((lo + hi) / 2, *new)
        c["devig_r"] = sgp.devig_r(c["j"], *new)
        c["rough"] = any(L["width"] > a.max_spread + 1e-9 for L in c["legs"])
    return None


def place(c, a, stake, min_x, min_ev):
    """Buy the slip on Kalshi: the page's Bet button (--bet). The only code
    here that trades. The legs are re-priced, a request for quote is sent for
    `stake` dollars (fees included), and the best answer is accepted only if
    the slip still pays at least `min_x` and is at least `min_ev` above the
    re-priced fair value. Returns ({"bet": {...}}, None) or (None, why).

    Buying the combo's Yes means taking a maker's bid for No, so the side
    accepted is "no". That reading of Kalshi's docs is checked after every
    bet against the account's position in the combo: a positive position is
    Yes. Anything else comes back as bet["side"] != "yes" and the server
    stops the button."""
    why = reprice(c, a)
    if why:
        return None, why
    body = {"selected_markets": [{"market_ticker": L["id"], "event_ticker": L["event"], "side": "yes" if L.get("yes", True) else "no"} for L in c["legs"]]}
    ticker = None
    for coll in COLLECTIONS:
        st, d = call("POST", f"/multivariate_event_collections/{coll}", body)
        if st in (200, 201) and d.get("market_ticker"):
            ticker = d["market_ticker"]
            break
    if not ticker:
        return None, f"the combo could not be created: {d.get('code') or d.get('message') or st}"
    st, d = call("POST", "/communications/rfqs", {"market_ticker": ticker, "rest_remainder": False, "target_cost_dollars": f"{stake:.2f}"})
    rfq = d.get("id") or (d.get("rfq") or {}).get("id")
    if st not in (200, 201) or not rfq:
        return None, f"request for quote refused: {st} {d.get('code') or d.get('message') or ''}".strip()
    best, accepted = None, False
    try:
        for _ in range(a.polls):
            time.sleep(a.wait / a.polls)
            _, d = call("GET", "/communications/quotes", query={"rfq_id": rfq, "rfq_user_filter": "self", "limit": 100})
            for q in d.get("quotes") or []:
                try:
                    nb = float(q.get("no_bid_dollars") or 0)
                except ValueError:
                    continue
                if q.get("status", "open") == "open" and 0 < nb < 1 and q.get("id") and (not best or nb > best[0]):
                    best = (nb, q["id"])
        if not best:
            return None, "no maker answered"
        yes = 1 - best[0]
        x, p = slip_x(yes), sgp.prob(sgp.american(c["j"]))
        if x < min_x - 1e-9:
            return None, f"not bet: Kalshi now pays {x:.2f}x, under the {min_x:.2f}x asked for"
        if p * x - 1 < min_ev - 1e-9:
            return None, f"not bet: at {x:.2f}x the slip is {p * x - 1:+.1%} against today's fair value"
        st, d = call("PUT", f"/communications/rfqs/{rfq}/quotes/{best[1]}/accept", {"accepted_side": "no"})
        if st not in (200, 204):
            return None, f"Kalshi did not take the acceptance: {st} {d.get('code') or d.get('message') or ''}".strip()
        accepted = True
    finally:
        if not accepted:
            call("DELETE", f"/communications/rfqs/{rfq}")
    # The maker confirms within 3 seconds and the trade prints a second later: read the position.
    pos = cost = None
    for _ in range(6):
        time.sleep(1.5)
        _, d = call("GET", "/portfolio/positions", query={"ticker": ticker, "limit": 10})
        for m in d.get("market_positions") or []:
            if m.get("ticker") == ticker:
                try:
                    pos = float(m.get("position_fp") if m.get("position_fp") is not None else m.get("position") or 0)
                    cost = float(m.get("market_exposure_dollars") or 0) or None
                except (TypeError, ValueError):
                    pass
        if pos:
            break
    finish(c, yes, a.unit, a.kelly)
    bet = {"ticker": ticker, "stake": stake, "x": x, "yes": yes, "contracts": abs(pos) if pos else None, "cost": cost,
           "side": "yes" if pos and pos > 0 else "no" if pos and pos < 0 else "unknown", "at": time.time()}
    return {"bet": bet, "row": c}, None


def requote(c, a):
    """One slip again (the page's refresh button; --requote): (the row with a
    new Kalshi answer and EV, None), or (None, why). Every NBA or NFL leg is
    re-read off Kalshi's own book (inside --kalshi-spread) and the fair value
    rebuilt with the r that gave the row's joint; a leg with no such book
    fails the refresh instead of keeping an old fair value. College legs keep
    theirs (priced off Novig; Kalshi's college books are too wide)."""
    why = reprice(c, a)
    if why:
        return None, why
    try:
        yes, why = ask(c, a)
    except Refused as e:
        return None, f"Kalshi refused the request: {e}"
    if not yes:
        return None, why
    finish(c, yes, a.unit, a.kelly)
    novig_price(c)
    return c, None


def positions():
    """The account's open combo positions (--positions; the page's "On
    Kalshi" strip and row lines): [{"ticker", "contracts" (negative on the No
    side), "cost" (dollars in, before fees), "title", "legs": [{"id", "side"}]}].
    Read only."""
    held, cursor = [], None
    for _ in range(10):
        q = {"count_filter": "position", "limit": 200}
        if cursor:
            q["cursor"] = cursor
        _, d = call("GET", "/portfolio/positions", query=q)
        for m in d.get("market_positions") or []:
            try:
                n = float(m.get("position_fp") if m.get("position_fp") is not None else m.get("position") or 0)
            except (TypeError, ValueError):
                continue
            if n and str(m.get("ticker", "")).startswith("KXMVE"):
                try:
                    cost = float(m.get("market_exposure_dollars") or 0)
                except (TypeError, ValueError):
                    cost = 0.0
                held.append({"ticker": m["ticker"], "contracts": n, "cost": cost})
        cursor = d.get("cursor")
        if not cursor or not d.get("market_positions"):
            break
    info = {}
    for i in range(0, len(held), 40):
        _, d = call("GET", "/markets", query={"tickers": ",".join(h["ticker"] for h in held[i:i + 40]), "limit": 1000, "mve_filter": "only"},
                    signed=False)
        info.update({m["ticker"]: m for m in d.get("markets") or []})
    for h in held:
        m = info.get(h["ticker"]) or {}
        h["title"] = m.get("yes_sub_title") or h["ticker"]
        h["legs"] = [{"id": L.get("market_ticker"), "side": L.get("side")} for L in m.get("mve_selected_legs") or []]
        h["status"] = m.get("status")
    return held


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="nba", choices=("nba", "nbaline", "nfl", "cbb"))
    ap.add_argument("--json", action="store_true", help="stream events as JSON lines (server.js)")
    ap.add_argument("--dry", action="store_true", help="list the slips, ask Kalshi for no price (no key needed)")
    ap.add_argument("--requote", action="store_true", help="re-ask the one slip given as JSON on stdin; print it as JSON")
    ap.add_argument("--bet", action="store_true",
                    help='BUYS the slip given on stdin as {"row", "stake", "min_x", "min_ev"}; prints the bet as JSON (the page\'s Bet button)')
    ap.add_argument("--positions", action="store_true", help="print the account's open combo positions as JSON (read only)")
    ap.add_argument("--check", action="store_true", help="make one signed read to see that the key is accepted")
    ap.add_argument("--max", type=int, default=60, help="ask at most this many slips a pass (0: all)")
    ap.add_argument("--min-r", type=float, default=0.25, help="smallest r for a pair other than Points + Threes")
    ap.add_argument("--max-spread", type=float, default=novig.MAX_SPREAD, help="widest Novig book a leg's fair value is read from")
    ap.add_argument("--kalshi-spread", type=float, default=0.05, help="widest Kalshi book a leg's fair value is read from when Novig has none")
    ap.add_argument("--line-r", type=float, default=0.30, help="nbaline: smallest fitted |r| between a prop and a game line")
    ap.add_argument("--per", type=int, default=2, help="nbaline: pairings asked per player, highest r first (each as its Over and its Under slip)")
    ap.add_argument("--team-lines", nargs="+", default=list(scan.NBA_PROP_LINES), choices=tuple(scan.NBA_PROP_LINES),
                    help="nbaline: the game lines a prop is asked with (default: all six)")
    ap.add_argument("--lo", type=float, default=0.15, help="a leg's fair value is at least this")
    ap.add_argument("--hi", type=float, default=0.85, help="and at most this")
    ap.add_argument("--stake", type=float, default=100.0, help="dollars each request for quote is sized at")
    ap.add_argument("--wait", type=float, default=3.0, help="seconds to wait for makers' answers")
    ap.add_argument("--polls", type=int, default=2, help="reads of the answers within --wait")
    ap.add_argument("--before", type=float, default=None, metavar="MS", help="only games starting before this time (epoch ms)")
    ap.add_argument("--unit", type=float, default=100.0, help="dollars in one unit on the Kalshi boards (Max, 11-16: 1u = $100)")
    ap.add_argument("--kelly", type=float, default=0.25)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--first", default=None, help="accepted for server.js; not used")
    ap.add_argument("--events", nargs="+", default=None, help="accepted for server.js; not used")
    a = ap.parse_args()
    t0 = time.time()

    def emit(e):
        if a.json:
            print(json.dumps(e), flush=True)
    if a.check:
        try:
            st, d = call("GET", "/portfolio/balance")
        except Refused as e:
            raise SystemExit(f"Kalshi refused the key: {e}")
        print("key accepted" if st == 200 else f"unexpected answer: {st} {d}")
        return
    if a.positions:
        try:
            print(json.dumps(positions()))
        except Refused as e:
            raise SystemExit(f"Kalshi refused the read of positions: {e}")
        return
    if a.requote:
        row, why = requote(json.load(sys.stdin), a)
        print(json.dumps(row if row else {"error": why}))
        return
    if a.bet:
        ask_ = json.load(sys.stdin)
        try:
            got, why = place(ask_["row"], a, float(ask_["stake"]), float(ask_["min_x"]), float(ask_.get("min_ev", 0)))
        except Refused as e:
            got, why = None, f"Kalshi refused the request: {e}"
        print(json.dumps(got if got else {"error": why}))
        return
    if not a.dry:
        _signer()   # no key, or one that can't be read: say so before anything is fetched
    cands, d = nfl_candidates(a) if a.league == "nfl" else cbb_candidates(a) if a.league == "cbb" else nbaline_candidates(a) if a.league == "nbaline" else candidates(a)
    # Each row links to its game's page on Kalshi, where the combo is built (no link fills the slip in).
    game = {"nba": "kxnbagame", "nbaline": "kxnbagame", "nfl": "kxnflgame", "cbb": "kxncaambgame"}[a.league]
    for c in cands:
        c["url"] = f"https://kalshi.com/markets/{game}/game/{game}-{c['event'].lower()}"
    emit({"type": "start", "total": len(cands), "players": len({c["id"] for c in cands}), "league": "kalshi" + a.league,
          "data": d["generated_at"][:10], "at": t0})
    if a.dry:
        for c in cands:
            print(f"{c['player'][:30]:30s} {c['label'][:36]:36s} r {c['r']:+.2f} fair {sgp.american(c['j']):+5d}  legs "
                  + " / ".join(f"{L['p']:.2f} ({L['src']})" for L in c["legs"]) + f"  {c['player']}"[:0])
        import collections
        n = collections.Counter(L["src"] for c in cands for L in c["legs"])
        print(f"{len(cands)} slips; legs priced off {dict(n)}, "
              f"{sum(1 for c in cands if c['rough'])} slips with a leg on a book wider than {a.max_spread * 100:g}c")
        return
    rows, refused, why_refused = [], 0, ""
    for c in cands:
        try:
            yes, why = ask(c, a)
        except Refused as e:
            refused, why_refused, yes, why = refused + 1, str(e), None, "Kalshi refused the key"
            if not rows and refused >= REFUSED_AFTER:
                # Its own line on stderr: server.js shows the last one as the board's error.
                raise SystemExit(f"Kalshi is refusing this key's requests: {why_refused}")
        if yes:
            finish(c, yes, a.unit, a.kelly)
            novig_price(c)
            rows.append(c)
            emit(dict(c, type="row"))
        else:
            emit({"type": "miss", "key": c["key"], "player": c["player"], "label": c["label"], "why": why})
        time.sleep(PACE_S)
    emit({"type": "done", "quoted": len(cands), "priced": len(rows), "seconds": time.time() - t0, "at": time.time()})
    if not a.json:
        rows.sort(key=lambda c: -c["ev"])
        for c in rows[:a.top or None]:
            print(f"{c['ev']:+6.1%}  {c['player'][:28]:28s} {c['label'][:34]:34s} fair {c['fair']:+5d}  Kalshi {c['slip']:+5d} "
                  f"({c['slip_x']:.2f}x, Yes at {c['quote']:.3f})" + (f"  Novig {c['novig_x']:.2f}x" if c.get("novig_x") else "")
                  + ("  ~" if c["rough"] else ""))
        print(f"{len(rows)} of {len(cands)} priced in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
