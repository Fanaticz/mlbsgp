#!/usr/bin/env python3
"""Kalshi NBA SGP scan: the Novig scanner's NBA slips, priced as Kalshi combos.

  python3 scan_kalshi.py --dry      # the slips it would ask, no price asked (no key needed)
  python3 scan_kalshi.py --check    # is the key accepted? (reads the balance endpoint, asks nothing)
  python3 scan_kalshi.py            # ask them and print the best
  python3 scan_kalshi.py --json     # one JSON event per line (server.js: the Kalshi NBA board)
  python3 scan_kalshi.py --league nbaline   # a player's prop with a game line (nbaline_candidates)
  python3 scan_kalshi.py --league nba3      # Points + Threes alone (the Kalshi Pts + 3s board)
  python3 scan_kalshi.py --league nbatri    # three legs on the high scorers (the Kalshi NBA 3-Leg board)
  python3 scan_kalshi.py --league nfl       # NFL: a player's own pairs and QB + teammate stacks, Overs and Unders (nfl_candidates)
  python3 scan_kalshi.py --league nflline   # NFL: a player's prop with a game line (nflline_candidates)
  python3 scan_kalshi.py --league cfb       # college football: the Novig CFB board's slips (cfb_candidates)

Two boards share these slips (Max, 11-18): --league nba3 asks 1 alone, --league nba asks 2 and T.
What it asks, per player with open Kalshi props on a game that has not started:
  1  Points Yes + Threes Yes (the player's shrunk correlation, as on the Novig board).
  2  His other Yes + Yes pairs where r is at least --min-r: points + rebounds,
     points + assists, rebounds + assists, rebounds + threes, assists + threes.
  T  Teammates: each team's two highest main points lines, Yes + Yes, as unrelated
     legs; no slip for a team where either has no priced leg (scan.nba_mate_candidates has the measurement).
The three-leg board (--league nbatri; Max, 11-21) asks none of those:
  3  For each player whose main points line is --tri-pts or higher: his points with
     two of rebounds, assists and threes, Yes + Yes + Yes, where all three pair r's
     are --tri-r or better (each leg goes with both others). Also asked with the
     points leg on the milestone the other side of his main line. Fair value is the
     three-way joint from the three pair r's (scan.tri_safe), scaled by TRI_FIX.
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
create 5,000 new combos a week. So a pass asks at most --max slips (400 on the Points + Threes board, 300 on the NBA board, 200 on the others; 60 until 11-18).
"""
import argparse
import base64
import difflib
import itertools
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
TRI_STATS = ("pts", "reb", "ast", "tpm")   # the three-leg board: points with two of the others
# Three legs hit together a little less often than the three pair r's say. 56 players averaging
# 19+ points, three seasons, each season cut at his own median lines (11-21): points + rebounds
# + assists 672 hits against 708 modelled (0.95), points + rebounds + threes 811 against 821
# (0.99), points + assists + threes 755 against 787 (0.96); 0.97 together. The joint is scaled by this.
TRI_FIX = 0.96
# The collections a same-game sports combo can be made in, the one the tape shows first.
COLLECTIONS = ("KXMVECROSSCATEGORY-R", "KXMVESPORTSMULTIGAMEEXTENDED-R")
TIP_S = 3 * 3600      # a market's occurrence_datetime is about this long after the game starts
FEE = 0.07            # taker fee = FEE x price x (1 - price) a contract
PACE_S = 1.0          # between two slips
REFUSED_AFTER = 3     # this many 401 / 403 answers with no price at all: stop


SEEN = {}             # what the NBA props boards read, for the reason an empty pass gives


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
            st, d = call("GET", "/markets", query=q, signed=False)
            if st != 200:   # an unread series used to pass as "no props": the board came back empty with no reason
                raise SystemExit(f"Kalshi's {series} markets could not be read: {st} {d.get('code') or d.get('message') or ''}".strip())
            for m in d.get("markets") or []:
                try:
                    starts = time.mktime(time.strptime(m["occurrence_datetime"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
                    line, parts = float(m["floor_strike"]), m["ticker"].split("-")
                    name = (m.get("yes_sub_title") or "").rsplit(":", 1)[0].strip()
                    bid, ask = float(m["yes_bid_dollars"]), float(m["yes_ask_dollars"])
                except (KeyError, TypeError, ValueError):
                    continue
                try:   # contracts on the thinner side of the best bid and ask (scan.two_books)
                    size = min(float(m["yes_bid_size_fp"]), float(m["yes_ask_size_fp"]))
                except (KeyError, TypeError, ValueError):
                    size = None
                starts = (starts - TIP_S) * 1000
                if not name or len(parts) < 4 or starts <= now or (before and starts >= before):
                    continue
                who = out.setdefault(novig.norm(name), {"name": name, "team": parts[2][:3], "starts": starts,
                                                        "game": parts[1], "stats": {}})
                who["stats"].setdefault(stat, []).append({"line": line, "ticker": m["ticker"], "event": m["event_ticker"],
                                                          "bid": bid, "ask": ask, "size": size})
            cursor = d.get("cursor")
            if not cursor or not d.get("markets"):
                break
    return out


def pick_leg(stat, kal, nv_rows, a, p=None, skip=()):
    """The leg for this stat. Each Kalshi milestone is priced off the tighter
    of two books on that same line: Novig's (inside --max-spread) or Kalshi's
    own Yes bid / ask (inside --kalshi-spread); where the two are within a
    cent of each other in width, off the average of their two fair values. The milestone taken is the one
    just under or just over Novig's main line (the nearer, if both have a
    book), or nearest even money where Novig lists nothing. None when no milestone has a book to price it from.
    skip: lines not to take, for the player's second leg on the stat (the
    milestone on the other side of his main line)."""
    nv = {r["line"]: r for r in nv_rows}   # wide ones too: two_books holds a thin Kalshi book inside them
    priced = []
    for k in kal:
        b = scan.two_books(nv.get(k["line"]), k["bid"], k["ask"], a.max_spread, a.kalshi_spread, k.get("size"))   # the Novig boards' rule too
        if b:
            fo, _, width, src = b
            if a.lo <= fo <= a.hi:
                priced.append((k, fo, width, src))
    if not priced and not p:
        return None
    # His main line is read off every Novig line with a price, tight or not.
    # A leg sits on the Kalshi milestone just under or just over it, or there
    # is no leg: taking the nearest milestone that happened to have a tight
    # book put a leg as far out as it liked (11-18: Murray, main 22.5, 20+ and
    # 25+ both on wide books, was asked at 30+).
    quoted = [r for r in nv_rows if r.get("fo") is not None]
    main = scan.main_line(quoted)["line"] if quoted else None
    if main is not None:
        lines = [k["line"] for k in kal]
        near = {max((x for x in lines if x <= main), default=None), min((x for x in lines if x > main), default=None)}
        near -= set(skip)
        priced = [x for x in priced if x[0]["line"] in near]
        if not priced:
            return shift_leg(stat, kal, nv_rows, a, p, scan.main_line(quoted), near) if p else None
    if not priced or (skip and main is None):
        return None
    k, fo, width, src = min(priced, key=lambda x: (abs(x[0]["line"] - main) if main is not None else 0, abs(x[1] - 0.5)))
    L = {"stat": stat, "side": "over", "line": k["line"], "p": fo, "fair": sgp.american(fo), "width": width,
         "id": k["ticker"], "event": k["event"], "src": src}
    same = next((r for r in nv_rows if r["line"] == k["line"] and r["ids"].get("over")), None)
    if same:   # Novig's Over on this same line, for its price on the same slip (novig_price)
        L["nv"] = same["ids"]["over"]
    return L


def shift_leg(stat, kal, nv_rows, a, p, main, near):
    """NBA: neither milestone beside the main line has a tight book, but
    Novig's main line does (Max, 11-18: use Novig for help on the main line).
    The nearer milestone's fair value is shifted from that main line with the
    Ladder's model (price.leg_prob), then held inside both exchanges' own
    bid and ask on the milestone itself, however wide those are (Kalshi's
    only with size on them, or where Novig has none). The leg
    carries `from`, and its slip is marked modelled (*)."""
    if not scan.usable(main, a.max_spread):
        return None
    nv = {r["line"]: r for r in nv_rows}
    for k in sorted((k for k in kal if k["line"] in near), key=lambda k: abs(k["line"] - main["line"])):
        if k["line"] == main["line"]:
            continue
        po = price.leg_prob(p, {"stat": stat, "side": 1, "line": k["line"], "from": main["line"], "p_over": main["fo"],
                                "over": None, "under": None})[0]
        # Kalshi's own bid and ask bound the leg with real size on them, or
        # where Novig has neither on the line (11-22: one contract bid at 30
        # raised Stirtz's 4+ assists from the model's 0.254).
        ok = lambda x: x is not None and 0 < x < 1   # noqa: E731
        books = [(nv[k["line"]].get("bid"), nv[k["line"]].get("ask"))] if k["line"] in nv else []
        if (k.get("size") or 0) >= scan.KALSHI["size"] or not any(ok(x) for b in books for x in b):
            books.append((k["bid"], k["ask"]))
        asks = [x for _, x in books if x is not None and 0 < x < 1]
        bids = [x for x, _ in books if x is not None and 0 < x < 1]
        if asks:
            po = min(po, min(asks))   # someone sells the Yes there: a ceiling
        if bids:
            po = max(po, max(bids))   # and a buyer is a floor
        if not a.lo <= po <= a.hi:
            continue
        L = {"stat": stat, "side": "over", "line": k["line"], "p": po, "fair": sgp.american(po), "width": main["spread"],
             "id": k["ticker"], "event": k["event"], "src": f"Novig {main['line']:g}", "from": main["line"]}
        if k["line"] in nv and nv[k["line"]]["ids"].get("over"):
            L["nv"] = nv[k["line"]]["ids"]["over"]
        return L
    return None


WORD = {"pts": "points", "reb": "rebounds", "ast": "assists", "tpm": "threes", "rec": "receptions", "yds": "receiving yards",
        "td": "touchdowns", "att": "pass attempts", "cmp": "completions", "pyds": "passing yards", "ptd": "passing TDs",
        "car": "carries", "ryds": "rushing yards", "rry": "rush + rec yards", "pra": "pts + reb + ast"}


NFL_TEAM = {"JAC": "JAX", "WAS": "WSH"}   # Kalshi's team code -> Novig's and the data's
NFL_LINE_SERIES = {"KXNFLSPREAD": "cover", "KXNFLTOTAL": "over", "KXNFLTEAMTOTAL": "tt", "KXNFLGAME": "win",
                   "KXNFL1HSPREAD": "h1cover", "KXNFL1HTOTAL": "h1over", "KXNFL1H": "h1win"}
# Novig's market for each kind of line. Its first-half moneyline is left out: Kalshi's "wins the
# 1st half" loses on a tie at the half, so that leg is priced off Kalshi's own book alone.
NFL_LINE_NOVIG = {"SPREAD": "cover", "TOTAL": "over", "TEAM_TOTAL": "tt", "MONEY": "win", "SPREAD_1H": "h1cover", "TOTAL_1H": "h1over"}


def nfl_legs(a):
    """([(player, his Kalshi props, {stat: (Yes leg, No leg)})], the data) for every player with open
    Kalshi NFL props: per stat the milestone pick_leg takes (beside Novig's main line), as "N+"
    (Yes) and as his Under (No on that same market). A touchdown leg is the anytime one only."""
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
            if stat == "td":   # 2+ touchdowns is a longshot the r's were not fitted for
                kal = [k for k in kal if k["line"] == 0.5]
            L = pick_leg(stat, kal, rows.get(stat, []), a)
            if not L:
                continue
            n = int(L["line"] + 0.5)
            L.update(yes=True, text="anytime touchdown" if stat == "td" else f"{n}+ {WORD[stat]}")
            U = dict(L, side="under", yes=False, p=1 - L["p"], fair=sgp.american(1 - L["p"]),
                     text="no touchdown" if stat == "td" else f"under {n} {WORD[stat]}")
            U.pop("nv", None)
            same = next((r for r in rows.get(stat, []) if r["line"] == L["line"]), None)
            if same and same["ids"].get("under"):
                U["nv"] = same["ids"]["under"]
            legs[stat] = (L, U)
        if legs:
            out.append((p, info, legs))
    return out, d


def nfl_on_team(p, info):
    """Is he still on the team the data has him on? Kalshi's ticker for his prop starts with his team's code."""
    code = {v: k for k, v in NFL_TEAM.items()}.get(p.get("team_abbr"), p.get("team_abbr") or "?")
    return info["team"].startswith(code[:3])


def nfl_order(c):
    """The order slips are asked in, so a capped pass spends itself on the next day of games:
    that day (US Eastern) first, and within it the highest r."""
    return (int((c["starts"] / 1000 - 5 * 3600) // 86400), -c["r"])


def nfl_row(a, p, info, la, lb, r, kind=None, **more):
    """One two-leg NFL slip. A No leg is marked in the key; a Yes + Yes key is the two tickers, as it always was."""
    j = sgp.joint(r, la["p"], lb["p"])
    c = {"key": ",".join(L["id"] + ("" if L["yes"] else ":n") for L in (la, lb)), "tier": 1, "player": p["name"],
         "id": p.get("athlete_id") or p.get("id") or novig.norm(p["name"]), "team": p.get("team_abbr") or p.get("team") or info["team"],
         "starts": info["starts"], "legs": [dict(la), dict(lb)], "label": f"{la['text']} · {lb['text']}", "r": r, "j": j,
         "forced": False, "devig_r": sgp.devig_r(j, la["p"], lb["p"]), "book": "kalshi", "event": info["game"],
         "rough": any(L["width"] > a.max_spread + 1e-9 for L in (la, lb)), "legs_x": 1 / (la["p"] * lb["p"])}
    if kind:
        c["kind"] = kind
    c.update(more)
    return c


def nfl_vol(d):
    """vol(player, "tgt_mean" | "car_mean"): this season's once he has three games in it, as scan.nfl_slate has it."""
    cur = str(max(d["seasons"]))

    def vol(p, k):
        s = (p.get("by_season") or {}).get(cur) or {}
        return (s if s.get("games", 0) >= 3 else p).get(k)
    return vol


def nfl_candidates(a):
    """NFL (--league nfl), the Novig NFL board's two-leg slips on one team's players, as Kalshi combos:
      own     one player's pairs (scan.NFL_PAIRS) with r at least --min-r, Yes + Yes, and his
              Under + Under (No + No on the same two markets) at the same r
      stack   a QB's passing leg with one of his own receivers' (scan.STACK_PAIRS: passing yards +
              receiving yards, passing TDs + his TD, completions + receptions, passing yards + his
              TD), by the receiver's targets a game; Yes + Yes and No + No. And the QB's attempts
              or passing yards against his back's carries or rushing yards (scan.STACK_AGAINST):
              Yes + No both ways. Each receiver's --per highest of each.
    Props with a game line are their own board (--league nflline)."""
    people, d = nfl_legs(a)
    S, vol = json.load(open(scan.STACK_DATA)), nfl_vol(d)
    out, teams = [], {}
    for p, info, legs in people:
        if nfl_on_team(p, info):   # a stack needs his quarterback: not asked for a player who has moved
            teams.setdefault((info["game"], p.get("team_abbr")), []).append((p, info, legs))
        for x, y in scan.NFL_PAIRS:
            if x not in legs or y not in legs:
                continue
            r = scan.nfl_r(p, x, y)
            if r is None or r < a.min_r:
                continue
            out.append(nfl_row(a, p, info, legs[x][0], legs[y][0], r))
            # Under 1 reception is under any yards: one leg, not two
            if a.unders and not any(legs[s][0]["line"] < 1 for s in (x, y) if s not in ("td", "ptd")):
                out.append(nfl_row(a, p, info, legs[x][1], legs[y][1], r))
    for ps in teams.values():
        qbs = [x for x in ps if x[0]["group"] == "QB"]
        if not qbs:
            continue
        qb, _, ql = max(qbs, key=lambda x: x[0].get("att_mean") or 0)
        who = qb["name"].split()[-1] + " "
        named = lambda L: dict(L, text=who + L["text"])   # noqa: E731
        for p, info, legs in ps:
            if p["group"] == "QB":
                continue
            overs, unders = [], []
            for qs, ts in scan.STACK_PAIRS:
                if qs not in ql or ts not in legs:
                    continue
                r = scan.stack_r(S["stack"], p, vol, qs, ts, scan.ptd_at(qs, ql[qs][0]["line"]))
                if r is not None and r >= a.min_r:
                    overs.append(nfl_row(a, p, info, named(ql[qs][0]), legs[ts][0], r, "stack"))
                    unders.append(nfl_row(a, p, info, named(ql[qs][1]), legs[ts][1], r, "stack"))
            for qs, ts in scan.STACK_AGAINST:   # one goes with the other's Under
                if qs not in ql or ts not in legs:
                    continue
                r = scan.role_r(S["stack"], vol(p, "car_mean"), qb=qs, stat=ts, pos=p["group"], by="car")
                if r is not None and -r >= a.min_r:
                    unders += [nfl_row(a, p, info, named(ql[qs][i]), legs[ts][1 - i], -r, "stack") for i in (0, 1)]
            for mine in (overs, unders) if a.unders else (overs,):
                out += sorted(mine, key=lambda c: -c["r"])[:a.per]
    out.sort(key=nfl_order)
    return (out[:a.max] if a.max else out), d


def nflline_candidates(a):
    """NFL prop + game line (--league nflline), the Novig NFL board's slips across a prop and a line:
    a player's milestone with a game line on the side that goes with it, and his Under (No on the
    same milestone) with the line's other side. The lines (scan.LINE_TYPES): the game total, his
    team's spread, moneyline and team total, and the first half's total, spread and winner. The r
    is scan.line_r's: league-wide for his position and targets or carries a game, and, with a
    spread or moneyline, for his team's side of today's spread (favoured by 3.5 or more, an
    underdog by 3.5 or more, or between). Asked where |r| is at least --line-r: his --per
    highest over the total, the spread and his team total, and his best with each kind of line.

    Kalshi lists "X wins", "X wins by over 7.5", "over 44.5 points" and "X over 24.5 points", and
    the same for the first half: the other team covering and an Under are No legs on those
    markets; the other team winning is Yes on its own market. A line leg is priced like a prop
    leg (the tighter of Novig's book on the same line and Kalshi's own) and is the one nearest
    even money, inside --lo to --hi."""
    people, d = nfl_legs(a)
    S, vol = json.load(open(scan.STACK_DATA)), nfl_vol(d)
    now, games = time.time() * 1000, {}   # Kalshi's game code -> {"starts", kind: [row]}
    for series, kind in NFL_LINE_SERIES.items():
        for m in _markets(series):
            tail = m["ticker"].rsplit("-", 1)[-1]
            try:
                starts = (time.mktime(time.strptime(m["occurrence_datetime"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone - TIP_S) * 1000
                row = {"line": float(m.get("floor_strike") or 0), "ticker": m["ticker"], "event": m["event_ticker"],
                       "bid": float(m["yes_bid_dollars"]), "ask": float(m["yes_ask_dollars"])}
            except (KeyError, TypeError, ValueError):
                continue
            if starts <= now or (a.before and starts >= a.before) or tail == "TIE":
                continue
            if kind not in ("over", "h1over"):
                code = re.sub(r"\d+$", "", tail)
                row["team"] = NFL_TEAM.get(code, code)
            games.setdefault(m["event_ticker"].split("-", 1)[1], {"starts": starts}).setdefault(kind, []).append(row)
    # Novig's books on the same lines: {the two team codes: {(kind, team or None, line): (p Yes, width, Yes id, No id)}}
    nv, by_event = {}, {}
    for m in novig.catalog({"league": "NFL", "eventStatus": "OPEN_PREGAME", "marketType": ",".join(NFL_LINE_NOVIG)}):
        by_event.setdefault(m["eventId"], []).append(m)
    for ms in by_event.values():
        sub = {o.get("subjectId"): o["name"] for m in ms if m["marketType"] == "MONEY" for o in m["outcomes"]}
        if len(sub) != 2:
            continue
        book = nv.setdefault(frozenset(sub.values()), {"starts": ms[0]["startsTs"]})
        for m in ms:
            kind, t = NFL_LINE_NOVIG[m["marketType"]], scan.two_way(m)
            if not t or t["spread"] > a.max_spread + 1e-9:
                continue
            if kind.endswith("cover"):
                for i, n in enumerate(t["names"]):   # "DAL -3.5" is Kalshi's "Dallas wins by over 3.5"
                    x = re.match(r"(\S+) -(\d+(?:\.\d+)?)$", n)
                    if x:
                        book[(kind, x.group(1), float(x.group(2)))] = (t["p"][i], t["spread"], t["ids"][i], t["ids"][1 - i])
            elif kind == "win":
                for i, n in enumerate(t["names"]):
                    book[(kind, n, 0.0)] = (t["p"][i], t["spread"], t["ids"][i], None)
            elif kind == "tt":
                tm = sub.get(m["outcomes"][0].get("subjectId"))
                if tm:
                    book[(kind, tm, t["strike"])] = (t["p"][0], t["spread"], t["ids"][0], t["ids"][1])
            else:
                book[(kind, None, t["strike"])] = (t["p"][0], t["spread"], t["ids"][0], t["ids"][1])
    for g in games.values():
        g["teams"] = {r["team"] for k in ("win", "cover", "tt") for r in g.get(k, [])}
        book = nv.get(frozenset(g["teams"]), {})
        g["starts"] = book.get("starts", g["starts"])
        for kind in NFL_LINE_SERIES.values():
            for r in g.get(kind, []):
                books, n = [], book.get((kind, r.get("team"), r["line"]))
                if n:
                    books.append((n[1], n[0], "novig"))
                if 0 < r["bid"] < r["ask"] < 1 and r["ask"] - r["bid"] <= a.kalshi_spread + 1e-9:
                    books.append((r["ask"] - r["bid"], sgp.devig_worst(r["ask"], 1 - r["bid"])[0], "kalshi"))
                if not books:
                    continue
                width, pr, src = min(books)
                if len(books) == 2 and abs(books[0][0] - books[1][0]) <= 0.01 + 1e-9:
                    width, pr, src = max(books)[0], (books[0][1] + books[1][1]) / 2, "both"
                r.update(p=pr, width=width, src=src, nv=n and (n[2], n[3]))
        # who is favoured and by how much: the full-game "wins by over" nearest even money
        sp = [r for r in g.get("cover", []) if "p" in r and 0.25 <= r["p"] <= 0.75]
        if sp:
            m = min(sp, key=lambda r: abs(r["p"] - 0.5) + r["width"])
            g["fav"], g["spread"] = m["team"], m["line"]

    def line_leg(g, kind, team, yes):
        """The game-line leg nearest even money. A spread or a winner: `team` covering or
        winning (Yes on its own market; covering is also No on the other team's "wins by
        over"). A total or `team`'s total: the Over when yes, else the Under."""
        half, opts = " 1H" if kind.startswith("h1") else "", []
        for r in g.get(kind, []):
            if "p" not in r:
                continue
            if kind.endswith("cover"):
                y = r["team"] == team
                text = f"{team} {'-' if y else '+'}{r['line']:g}{half}"
            elif kind.endswith("win"):
                if r["team"] != team:
                    continue
                y, text = True, f"{team}{half} moneyline"
            elif kind == "tt":
                if r["team"] != team:
                    continue
                y, text = yes, f"{team} team total {'Over' if yes else 'Under'} {r['line']:g}"
            else:
                y, text = yes, f"{'Over' if yes else 'Under'} {r['line']:g}{half}"
            pr = r["p"] if y else 1 - r["p"]
            if a.lo <= pr <= a.hi:
                L = {"stat": kind, "side": "over" if y else "under", "yes": y, "line": r["line"], "p": pr, "fair": sgp.american(pr),
                     "width": r["width"], "id": r["ticker"], "event": r["event"], "src": r["src"], "text": text}
                if r.get("nv") and r["nv"][0 if y else 1]:
                    L["nv"] = r["nv"][0 if y else 1]
                opts.append(L)
        return min(opts, key=lambda L: abs(L["p"] - 0.5) + L["width"]) if opts else None

    out = []
    for p, info, legs in people:
        g, me = games.get(info["game"]), p.get("team_abbr")
        if not g or len(g["teams"]) != 2 or me not in g["teams"] or not nfl_on_team(p, info):
            continue   # no lines on his game, or he has changed teams since the data was built
        them = next(t for t in g["teams"] if t != me)
        info["starts"] = g["starts"]
        side = None if "fav" not in g else "even" if g["spread"] < 3.5 else "fav" if g["fav"] == me else "dog"
        overs, unders = [], []
        for s, (la, lu) in legs.items():
            for line in scan.LINE_TYPES:
                r = scan.line_r(S, vol, p, s, line, side, scan.ptd_at(s, la["line"]))
                if r is None or abs(r) < a.line_r:
                    continue
                sided = line.endswith("cover") or line.endswith("win")
                for lp, way, mine in ((la, r, overs), (lu, -r, unders)):   # his Over with the side that goes with it, his Under with the other
                    lb = line_leg(g, line, (me if way > 0 else them) if sided else me, way > 0)
                    if lb:
                        mine.append(nfl_row(a, p, info, lp, lb, abs(r), line, line=line, role=True))
        for mine in (overs, unders) if a.unders else (overs,):
            mine.sort(key=lambda c: -c["r"])
            keep = {c["key"] for c in [c for c in mine if c["kind"] in ("over", "cover", "tt")][:a.per]}
            for line in scan.LINE_TYPES:
                keep |= {c["key"] for c in [c for c in mine if c["kind"] == line][:1]}
            out += [c for c in mine if c["key"] in keep]
    out.sort(key=nfl_order)
    return (out[:a.max] if a.max else out), d


def candidates(a):
    d, by = sgp.load()
    key = {novig.norm(n): p for n, p in by.items()}
    board = kalshi_props(a.before)
    markets = novig.fetch()
    SEEN.update(kalshi=len(board), known=sum(1 for nm in board if nm in key), novig=len(markets))
    out, teams = [], {}
    for nm, info in board.items():
        p = key.get(nm)
        if not p:
            continue
        _, rows = novig.ladder(markets, p["name"])
        info["starts"] = next((r["starts"] for v in rows.values() for r in v), info["starts"])
        # legs: his leg on each stat, the milestone beside his main line. opts:
        # that one first, then the milestone on the other side of the main
        # line (Max, 11-18: the board was missing a lot), so a pair is asked on
        # up to four slips.
        legs, opts = {}, {}
        for stat, kal in info["stats"].items():
            L = pick_leg(stat, kal, rows.get(stat, []), a, p)
            if L:
                L2 = pick_leg(stat, kal, rows.get(stat, []), a, p, skip=(L["line"],))
                opts[stat] = [L] + ([L2] if L2 else [])
                for o in opts[stat]:
                    o["text"] = f"{int(o['line'] + 0.5)}+ {WORD[stat]}"
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
            if la.get("from") is not None or lb.get("from") is not None:
                c["model"] = True   # a leg shifted from Novig's main line: the page marks the slip *
            return c
        # His main points line: Novig's, or Kalshi's milestone nearest even money where Novig lists none.
        rank = None
        if "pts" in info["stats"]:
            nvp = [r for r in rows.get("pts", []) if r.get("fo") is not None]
            mids = [(abs((k["bid"] + k["ask"]) / 2 - 0.5), k["line"]) for k in info["stats"]["pts"] if 0 < k["bid"] < k["ask"] < 1]
            rank = scan.main_line(nvp)["line"] if nvp else min(mids)[1] if mids else None
        if a.league == "nbatri":
            # Three legs on a high scorer, every pair of them going together (Max, 11-21: Wembanyama, Doncic).
            # The points leg is always one of the three: without it (rebounds, assists and threes) the legs are close to unrelated.
            for trio in itertools.combinations([s for s in TRI_STATS if s in legs], 3) if rank is not None and rank >= a.tri_pts else ():
                if "pts" not in trio:
                    continue
                rs = [price.shrunk_r(d, by, p, x, y)[0] for x, y in ((trio[0], trio[1]), (trio[0], trio[2]), (trio[1], trio[2]))]
                if any(r is None or r < a.tri_r for r in rs):
                    continue
                for ls in itertools.product(*(opts[s] if s == "pts" else [legs[s]] for s in trio)):
                    at = {L["stat"]: L["line"] for L in ls}
                    # k threes are 3k points: a threes leg that forces the points leg is two legs, not three
                    if "pts" in at and "tpm" in at and 3 * (math.floor(at["tpm"]) + 1) > at["pts"]:
                        continue
                    ps = [L["p"] for L in ls]
                    try:
                        j = scan.tri_safe(ps, rs) * TRI_FIX
                    except (ValueError, ZeroDivisionError, OverflowError):
                        continue
                    if not 0 < j < 1:
                        continue
                    c = {"key": ",".join(L["id"] for L in ls), "tier": 4, "player": p["name"], "id": p["athlete_id"],
                         "team": p.get("team_abbr") or info["team"], "starts": info["starts"], "legs": [dict(L) for L in ls],
                         "label": " · ".join(L["text"] for L in ls), "r": min(rs), "rs": rs, "j": j, "forced": False,
                         "devig_r": None, "book": "kalshi", "event": info["game"], "pts_line": rank,
                         "rough": any(L["width"] > a.max_spread + 1e-9 for L in ls), "legs_x": 1 / math.prod(ps),
                         "alt": 0 if all(L is legs[L["stat"]] for L in ls) else 1}
                    if any(L.get("from") is not None for L in ls):
                        c["model"] = True
                    out.append(c)
            continue
        # Points + Threes has its own board (--league nba3, Max 11-18); the NBA board asks the rest.
        only3 = a.league == "nba3"
        if only3 and "pts" in legs and "tpm" in legs:
            r = price.shrunk_r(d, by, p, "pts", "tpm")[0]
            # k threes are 3k points: a threes leg that forces the points leg is one leg, not two
            for la in opts["pts"] if r > 0 else ():
                for lb in opts["tpm"]:
                    if 3 * (math.floor(lb["line"]) + 1) <= la["line"]:
                        first = la is legs["pts"] and lb is legs["tpm"]
                        out.append(dict(row_of(1, r, la, lb), main=first, alt=0 if first else 1))
        for x, y in () if only3 else PAIRS:
            if x in legs and y in legs:
                r = price.shrunk_r(d, by, p, x, y)[0]
                if r is not None and r >= a.min_r:
                    out += [dict(row_of(2, r, la, lb), alt=0 if la is legs[x] and lb is legs[y] else 1) for la in opts[x] for lb in opts[y]]
        # Teammates are ranked by each player's own main points line, priced
        # leg or not: ranked by priced legs alone, a second scorer with no
        # tight book on a Kalshi milestone handed his place to the third
        # (11-18: Adebayo, main 17.5, had none, so Thompson was asked with
        # Antetokounmpo).
        if not only3 and rank is not None:
            teams.setdefault((info["game"], info["team"]), []).append((p, rank, opts.get("pts"), row_of))
    last = lambda p: p["name"].split(" ", 1)[-1]   # noqa: E731
    for ps in teams.values():
        ps.sort(key=lambda x: -x[1])
        # the team's top two, or no slip: a top-two scorer with no priced leg is not replaced by the next man
        if len(ps) >= 2 and ps[1][1] >= scan.NBA_MATE_MIN and ps[0][2] and ps[1][2]:
            (pa, _, oa, mk), (pb, _, ob, _) = ps[0], ps[1]
            out += [dict(mk(0, scan.NBA_MATE_R, la, lb, who=f"{pa['name']} + {pb['name']}", pid=f"{pa['athlete_id']}+{pb['athlete_id']}",
                            label=f"{last(pa)} {la['text']} · {last(pb)} {lb['text']}", kind="mates"),
                         alt=0 if la is oa[0] and lb is ob[0] else 1) for la in oa for lb in ob]
    # Each pair's slip beside the main lines first (teammates, the shape Novig misprices; then Points + Threes;
    # then the rest), and after all of those the slips on the other milestones, so a cut at --max drops those.
    # Every leg at --leg-min or better (Max, 11-18). Kalshi's milestones are 5 points apart, so a
    # leg can be stranded well over a player's line, where its fair value and the r are least sure.
    # It replaced a +300 limit on the slip's fair value the same evening: that also cut slips of two
    # legs beside the player's lines (Zubac 15+ points with 10+ rebounds, +392) and needed teammates exempt.
    out = [c for c in out if all(L["p"] >= a.leg_min - 1e-9 for L in c["legs"])]
    if a.max_fair:
        out = [c for c in out if c["j"] >= 100 / (a.max_fair + 100) - 1e-9]
    out.sort(key=lambda c: (c.get("alt", 0), c["tier"], c["starts"], -c["r"]))
    return (out[:a.max] if a.max else out), d


def _markets(series):
    """Every open market of a Kalshi series (no key needed)."""
    out, cursor = [], None
    for _ in range(20):
        q = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            q["cursor"] = cursor
        st, d = call("GET", "/markets", query=q, signed=False)
        if st != 200:
            raise SystemExit(f"Kalshi's {series} markets could not be read: {st} {d.get('code') or d.get('message') or ''}".strip())
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
        r = scan.cbb_r(shapes, "fav_cover+over", ks["line"])["r"]
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


CFB_SERIES = {"KXNCAAFGAME": "ml", "KXNCAAFSPREAD": "cover", "KXNCAAFTOTAL": "tot", "KXNCAAFTEAMTOTAL": "tt",
              "KXNCAAF1HSPREAD": "h1cover", "KXNCAAF1HTOTAL": "h1tot"}
CFB_MATCH = 0.6       # a Novig game is a Kalshi game when each of its teams matches at least this well (cfb_same)
CFB_CLEAR = 0.1       # and no other Kalshi game that day comes within this, on the two teams' average


def cfb_same(x, y, code):
    """How alike two spellings of a college are, 0 to 1: 1 only for the same code, or the same
    name once "St." and "NC" are written out. Anything short of that counts for less (x 0.8),
    so "South Carolina St." never passes for "North Carolina State" (0.9 letter for letter)."""
    if code:
        return 1.0 if x.upper() == y.upper() else 0.8 * difflib.SequenceMatcher(None, x.upper(), y.upper()).ratio()
    x, y = (" ".join({"nc": "north carolina", "miss": "mississippi"}.get(w, w) for w in _team(n).split()) for n in (x, y))
    return 1.0 if x == y else 0.8 * difflib.SequenceMatcher(None, x, y).ratio()


def cfb_candidates(a):
    """College football (--league cfb): the Novig CFB board's slips (scan.cfb_candidates:
    the underdog's moneyline with the Under, spread + total, team totals, the first half),
    asked as Kalshi combos. The model, its r's and every leg's fair value are that board's:
    Novig's own two-sided book on the line. A leg is only put on a line Kalshi lists too, so a
    slip sits on the line nearest even money that both sites have. Kalshi lists "X wins",
    "X wins by over 7.5", "Over 50.5" and "X over 24.5 points", for the game and for the first
    half: a favourite's spread, an Over and a moneyline are Yes legs; the underdog's spread
    is No on the favourite's "wins by over", an Under is No on the Over. A game is matched
    by its day (the date in Kalshi's ticker, US Eastern) and both teams, by code or by name."""
    games = {}   # Kalshi's game code -> its teams and every market by (kind, team code, line)
    for series, kind in CFB_SERIES.items():
        for m in _markets(series):
            g = games.setdefault(m["event_ticker"].split("-", 1)[1], {"teams": {}, "mk": {}})
            tail = m["ticker"].rsplit("-", 1)[-1]
            row = {"ticker": m["ticker"], "event": m["event_ticker"]}
            if kind == "ml":
                g["teams"][tail] = m.get("yes_sub_title") or tail
                g["mk"][(kind, tail, 0.0)] = row
                continue
            try:
                line = float(m["floor_strike"])
            except (KeyError, TypeError, ValueError):
                continue
            g["mk"][(kind, None if kind.endswith("tot") else re.sub(r"\d+$", "", tail), line)] = row
    kmap = {}    # a Novig outcome id -> the Kalshi leg that wins with it

    def listed(name, ms):
        away, _, home = name.partition(" @ ")
        sub, full = {}, {}   # Novig's subject id -> the team's code, and its full name where a team total gives one
        for m in ms:
            if m["marketType"] in ("MONEY", "SPREAD"):
                for o in m["outcomes"]:
                    sub[o.get("subjectId")] = o["name"] if m["marketType"] == "MONEY" else o["name"].rpartition(" ")[0]
            elif m["marketType"] == "TEAM_TOTAL":
                full[m["outcomes"][0].get("subjectId")] = m["description"].rsplit(" ", 2)[0]
        names = {t: [t] + [full[i] for i, c in sub.items() if c == t and i in full] for t in (away, home)}
        # Kalshi's ticker dates a game by its US Eastern day: four or five hours behind UTC
        days = {time.strftime("%y%b%d", time.gmtime(ms[0]["startsTs"] / 1000 - h * 3600)).upper() for h in (4, 5)}
        found = []
        for code, g in games.items():
            if code[:7] not in days or len(g["teams"]) != 2:
                continue
            (k0, n0), (k1, n1) = g["teams"].items()
            same = lambda t, k, n: max([cfb_same(t, k, True)] + [cfb_same(x, n, False) for x in names[t][1:]])   # noqa: E731
            for x, y in ((away, home), (home, away)):
                s0, s1 = same(x, k0, n0), same(y, k1, n1)
                if min(s0, s1) >= CFB_MATCH:
                    found.append(((s0 + s1) / 2, code, {x: k0, y: k1}))
        found.sort(key=lambda f: -f[0])
        if not found or any(f[1] != found[0][1] and f[0] > found[0][0] - CFB_CLEAR for f in found[1:]):
            return None
        _, code, abbr = found[0]
        mk = games[code]["mk"]

        def on(L):
            if L["team"] is not None and L["team"] not in abbr:
                return False
            pre, team = "h1" if L["half"] else "", abbr.get(L["team"])
            if L["stat"] == "ml":
                k, yes = mk.get(("ml", team, 0.0)), True
            elif L["stat"] == "cover":   # "X -7.5" is X wins by over 7.5; "X +7.5" is the other team not doing so
                other = next(v for t, v in abbr.items() if t != L["team"])
                k, yes = (mk.get((pre + "cover", team, -L["line"])), True) if L["line"] < 0 else (mk.get((pre + "cover", other, L["line"])), False)
            elif L["stat"] == "tot":
                k, yes = mk.get((pre + "tot", None, L["line"])), L["side"] == "over"
            else:
                k, yes = (None if L["half"] else mk.get(("tt", team, L["line"]))), L["side"] == "over"
            if k:
                kmap[L["id"]] = dict(k, yes=yes, code=code)
            return bool(k)
        return on
    rows, _ = scan.cfb_candidates(argparse.Namespace(league="cfb", max_spread=a.max_spread, alts=False, max=0), listed)
    out = []
    for c in rows:
        if a.before and c["starts"] >= a.before:
            continue
        legs = []
        for L in c["legs"]:
            k = kmap[L["id"]]
            legs.append(dict(L, nv=L["id"], id=k["ticker"], event=k["event"], yes=k["yes"], src="novig"))
        code = kmap[c["legs"][0]["id"]]["code"]
        p = 1.0
        for L in legs:
            p *= L["p"]
        out.append(dict(c, key=",".join(f"{L['id']}:{'yes' if L['yes'] else 'no'}" for L in legs), tier=1, id=code, team="CFB",
                        legs=legs, book="kalshi", event=code, legs_x=1 / p))
    return (out[:a.max] if a.max else out), {"generated_at": time.strftime("%Y-%m-%d", time.gmtime())}


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
    if a.league in ("cbb", "cfb"):
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
        if L.get("from") is not None and 0 < bid < offer < 1:
            # A leg shifted from Novig's main line (shift_leg) has no tight book of its own: its
            # fair value stands, held inside Kalshi's bid and ask as they are now.
            p = min(max(L["p"], bid), offer)
            L.update(p=p, fair=sgp.american(p))
            continue
        if not (0 < bid < offer < 1 and offer - bid <= a.kalshi_spread + 1e-9):
            # No book to price the leg from now: an old fair value under a new price is worse than no row.
            return f"{L.get('text') or 'a leg'} has no tight book on Kalshi right now: press Fetch"
        p = sgp.devig_worst(offer, 1 - bid)[0]
        p = p if L.get("yes", True) else 1 - p   # a No leg: the other side of the same book
        L.update(p=p, fair=sgp.american(p), width=offer - bid, src="kalshi")
    new = [L["p"] for L in c["legs"]]
    if new != old:
        if len(new) == 3:   # the three-leg board: the same three pair r's
            c["j"] = scan.tri_safe(new, c["rs"]) * TRI_FIX
        else:
            lo, hi = -0.99, 0.99   # the r that gave this row's joint
            for _ in range(30):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if sgp.joint(mid, *old) < c["j"] else (lo, mid)
            c["j"] = sgp.joint((lo + hi) / 2, *new)
            c["devig_r"] = sgp.devig_r(c["j"], *new)
        c["legs_x"] = 1 / math.prod(new)
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
    ap.add_argument("--league", default="nba", choices=("nba", "nba3", "nbatri", "nbaline", "nfl", "nflline", "cbb", "cfb"))
    ap.add_argument("--json", action="store_true", help="stream events as JSON lines (server.js)")
    ap.add_argument("--dry", action="store_true", help="list the slips, ask Kalshi for no price (no key needed)")
    ap.add_argument("--requote", action="store_true", help="re-ask the one slip given as JSON on stdin; print it as JSON")
    ap.add_argument("--bet", action="store_true",
                    help='BUYS the slip given on stdin as {"row", "stake", "min_x", "min_ev"}; prints the bet as JSON (the page\'s Bet button)')
    ap.add_argument("--positions", action="store_true", help="print the account's open combo positions as JSON (read only)")
    ap.add_argument("--check", action="store_true", help="make one signed read to see that the key is accepted")
    ap.add_argument("--max", type=int, default=None, help="ask at most this many slips a pass (0: all; default 400 on the Points + Threes board, 300 on the NBA board, 200 on the others)")
    ap.add_argument("--leg-min", type=float, default=0.30, help="nba, nba3, nbatri: every leg of a slip has a fair value of at least this (teammates slips too)")
    ap.add_argument("--max-fair", type=float, default=0.0,
                    help="nba, nba3: the longest fair value a slip is asked at, American (0: no limit, the default since --leg-min)")
    ap.add_argument("--min-r", type=float, default=0.25, help="smallest r for a pair other than Points + Threes, and for an NFL stack")
    ap.add_argument("--tri-pts", type=float, default=19.5, help="nbatri: a player's main points line is at least this")
    ap.add_argument("--tri-r", type=float, default=0.03, help="nbatri: each of the three pair r's is at least this")
    ap.add_argument("--max-spread", type=float, default=novig.MAX_SPREAD, help="widest Novig book a leg's fair value is read from")
    ap.add_argument("--kalshi-spread", type=float, default=0.05, help="widest Kalshi book a leg's fair value is read from when Novig has none")
    ap.add_argument("--line-r", type=float, default=0.30, help="nbaline, nflline: smallest |r| between a prop and a game line")
    ap.add_argument("--per", type=int, default=2, help="nbaline, nflline: pairings asked per player, highest r first (each as its Over and its Under slip); nfl: stacks per receiver")
    ap.add_argument("--team-lines", nargs="+", default=list(scan.NBA_PROP_LINES), choices=tuple(scan.NBA_PROP_LINES),
                    help="nbaline: the game lines a prop is asked with (default: all six)")
    ap.add_argument("--no-unders", dest="unders", action="store_false",
                    help="nfl, nflline: ask no player-prop Unders (Under + Under, the Over + Under stacks, a prop's Under + a game line)")
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
    if a.max is None:
        a.max = {"nba": 300, "nba3": 400}.get(a.league, 200)
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
    cands, d = nfl_candidates(a) if a.league == "nfl" else nflline_candidates(a) if a.league == "nflline" else cbb_candidates(a) if a.league == "cbb" else cfb_candidates(a) if a.league == "cfb" else nbaline_candidates(a) if a.league == "nbaline" else candidates(a)
    # Each row links to its game's page on Kalshi, where the combo is built (no link fills the slip in).
    game = {"nba": "kxnbagame", "nba3": "kxnbagame", "nbatri": "kxnbagame", "nbaline": "kxnbagame", "nfl": "kxnflgame", "nflline": "kxnflgame", "cbb": "kxncaambgame", "cfb": "kxncaafgame"}[a.league]
    for c in cands:
        c["url"] = f"https://kalshi.com/markets/{game}/game/{game}-{c['event'].lower()}"
    if not cands and SEEN and not a.dry:
        # Its own line on stderr: server.js shows it as the board's error, in place of an empty board with no reason.
        raise SystemExit(f"No slip to ask: Kalshi lists open props on {SEEN['kalshi']} players in games that have not started "
                         f"({SEEN['known']} of them in the data), and Novig lists {SEEN['novig']} NBA prop markets.")
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
