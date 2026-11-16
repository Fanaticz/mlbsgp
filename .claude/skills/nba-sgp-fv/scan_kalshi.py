#!/usr/bin/env python3
"""Kalshi NBA SGP scan: the Novig scanner's NBA slips, priced as Kalshi combos.

  python3 scan_kalshi.py --dry      # the slips it would ask, no price asked (no key needed)
  python3 scan_kalshi.py --check    # is the key accepted? (reads the balance endpoint, asks nothing)
  python3 scan_kalshi.py            # ask them and print the best
  python3 scan_kalshi.py --json     # one JSON event per line (server.js: the Kalshi NBA board)

What it asks, per player with open Kalshi props on a game that has not started:
  1  Points Yes + Threes Yes (the player's shrunk correlation, as on the Novig board).
  2  His other Yes + Yes pairs where r is at least --min-r: points + rebounds,
     points + assists, rebounds + assists, rebounds + threes, assists + threes.
  T  Teammates: each team's two highest points lines, Yes + Yes, as unrelated
     legs (scan.nba_mate_candidates has the measurement).
Kalshi's props are milestones ("25+ points" is Over 24.5). Each leg sits on the
milestone nearest Novig's main line where Novig has a tight book on that same
line; where it has none, on Kalshi's own milestone nearest even money.

Fair value: each leg is Novig's exchange book on the same line, devigged worst
case, where Novig has a two-sided book inside --max-spread. Where it has none,
the leg is Kalshi's own Yes bid / ask (inside --kalshi-spread) with the spread
taken out, and the row is marked rough (~): Kalshi's prop books are whole
cents and 3 to 5 cents wide. The legs are joined with the same Gaussian copula
as the Novig board.

Price: a combo on Kalshi is an auction. For each slip: create the combo market
(POST /multivariate_event_collections/{collection}), send a request for quote
for --stake dollars (POST /communications/rfqs), wait --wait seconds, read the
makers' answers (GET /communications/quotes?rfq_id=), delete the request. A
maker answers with a bid for No; buying Yes costs 1 - the best No bid. The fee
is Kalshi's taker fee, 0.07 x price x (1 - price) a contract, on top.
Nothing is ever accepted: this script has no call that trades.

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
PAIRS = (("pts", "reb"), ("pts", "ast"), ("reb", "ast"), ("reb", "tpm"), ("ast", "tpm"))
# The collections a same-game sports combo can be made in, the one the tape shows first.
COLLECTIONS = ("KXMVECROSSCATEGORY-R", "KXMVESPORTSMULTIGAMEEXTENDED-R")
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


def kalshi_props(before=None):
    """{normalised player name: {"name", "team", "starts" (ms), "game", "stats":
    {stat: [{"line", "ticker", "event", "bid", "ask"}]}}} from Kalshi's open NBA
    player-prop markets on games that have not started. No key needed."""
    out, now = {}, time.time() * 1000
    for series, stat in SERIES.items():
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
                starts *= 1000
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
    """The leg for this stat: Kalshi's milestone on the Novig line nearest
    Novig's main line (fair from Novig), else Kalshi's own milestone nearest
    even money (fair from Kalshi's book, rough). None when neither is priced."""
    by_line = {k["line"]: k for k in kal}
    ok = [r for r in nv_rows if r["line"] in by_line and scan.usable(r, a.max_spread)]
    if ok:
        main = scan.main_line([r for r in nv_rows if scan.usable(r, a.max_spread)])
        r = min(ok, key=lambda r: (abs(r["line"] - main["line"]), abs(r["fo"] - 0.5)))
        k, fo, width, src = by_line[r["line"]], r["fo"], r["spread"], "novig"
    else:
        own = [k for k in kal if 0 < k["bid"] < k["ask"] < 1 and k["ask"] - k["bid"] <= a.kalshi_spread + 1e-9]
        if not own:
            return None
        k = min(own, key=lambda k: abs((k["bid"] + k["ask"]) / 2 - 0.5))
        fo, width, src = sgp.devig_worst(k["ask"], 1 - k["bid"])[0], k["ask"] - k["bid"], "kalshi"
    if not a.lo <= fo <= a.hi:
        return None
    return {"stat": stat, "side": "over", "line": k["line"], "p": fo, "fair": sgp.american(fo), "width": width,
            "id": k["ticker"], "event": k["event"], "src": src}


WORD = {"pts": "points", "reb": "rebounds", "ast": "assists", "tpm": "threes"}


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
                 "rough": any(L["src"] == "kalshi" for L in (la, lb)), "legs_x": 1 / (la["p"] * lb["p"])}
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


def ask(c, a):
    """(Yes price a contract before the fee, None) for the slip, or (None, why)."""
    body = {"selected_markets": [{"market_ticker": L["id"], "event_ticker": L["event"], "side": "yes"} for L in c["legs"]]}
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
            st, d = call("GET", "/communications/quotes", query={"rfq_id": rfq, "limit": 100})
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="stream events as JSON lines (server.js)")
    ap.add_argument("--dry", action="store_true", help="list the slips, ask Kalshi for no price (no key needed)")
    ap.add_argument("--check", action="store_true", help="make one signed read to see that the key is accepted")
    ap.add_argument("--max", type=int, default=60, help="ask at most this many slips a pass (0: all)")
    ap.add_argument("--min-r", type=float, default=0.25, help="smallest r for a pair other than Points + Threes")
    ap.add_argument("--max-spread", type=float, default=novig.MAX_SPREAD, help="widest Novig book a leg's fair value is read from")
    ap.add_argument("--kalshi-spread", type=float, default=0.05, help="widest Kalshi book a leg's fair value is read from when Novig has none")
    ap.add_argument("--lo", type=float, default=0.15, help="a leg's fair value is at least this")
    ap.add_argument("--hi", type=float, default=0.85, help="and at most this")
    ap.add_argument("--stake", type=float, default=25.0, help="dollars each request for quote is sized at")
    ap.add_argument("--wait", type=float, default=3.0, help="seconds to wait for makers' answers")
    ap.add_argument("--polls", type=int, default=2, help="reads of the answers within --wait")
    ap.add_argument("--before", type=float, default=None, metavar="MS", help="only games starting before this time (epoch ms)")
    ap.add_argument("--unit", type=float, default=250.0)
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
    if not a.dry:
        _signer()   # no key, or one that can't be read: say so before anything is fetched
    cands, d = candidates(a)
    emit({"type": "start", "total": len(cands), "players": len({c["id"] for c in cands}), "league": "kalshinba",
          "data": d["generated_at"][:10], "at": t0})
    if a.dry:
        for c in cands:
            print(f"{c['player'][:30]:30s} {c['label'][:36]:36s} r {c['r']:+.2f} fair {sgp.american(c['j']):+5d}  legs "
                  + " / ".join(f"{L['p']:.2f} ({L['src']})" for L in c["legs"]))
        print(f"{len(cands)} slips, {sum(1 for c in cands if c['rough'])} with a leg priced off Kalshi's own book")
        return
    rows, refused, why_refused = [], 0, ""
    for c in cands:
        try:
            yes, why = ask(c, a)
        except Refused as e:
            refused, why_refused, yes, why = refused + 1, str(e), None, "Kalshi refused the key"
            if not rows and refused >= REFUSED_AFTER:
                # Its own line on stderr: server.js shows the last one as the board's error.
                raise SystemExit(f"Kalshi is refusing this key's requests ({why_refused}). If the key has only the Trade "
                                 "permission, make a new one with Full access and put it in Railway.")
        if yes:
            finish(c, yes, a.unit, a.kelly)
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
                  f"({c['slip_x']:.2f}x, Yes at {c['quote']:.3f})" + ("  ~" if c["rough"] else ""))
        print(f"{len(rows)} of {len(cands)} priced in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
