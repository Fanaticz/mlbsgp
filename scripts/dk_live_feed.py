#!/usr/bin/env python3
"""Stream DraftKings' live sportsbook data feed — the same websocket the DK
event/live pages use for scores, game state and odds updates. No cookie, no
Akamai gate: it's the public sports-data socket, not the wager endpoint.

    python3 scripts/dk_live_feed.py                       # all MLB (league 84240)
    python3 scripts/dk_live_feed.py --event 34669943      # one game
    python3 scripts/dk_live_feed.py --event 34669943 --markets   # + per-prop live stats
    python3 scripts/dk_live_feed.py --league 84240 --raw  # dump every message

Protocol (from cdn.draftkings.com/rj/@draftkings/dk-data-layer, the
`SportsbookLeague` class): JSON-RPC 2.0 over `wss://sportsbook-ws-us-<state>.
draftkings.com/websocket`, one `subscribe` per query:

    {"jsonrpc":"2.0","id":1,"method":"subscribe","params":{
        "entity":"events",
        "queryParams":{"query":"$filter=leagueId eq '84240'",
                       "initialData":true,"projection":"sportsbook",
                       "locale":"en-US"}}}

The server answers `subscribed`, then a stream of `update` messages shaped
{data:{data:{add:{events,markets,selections},remove:{…},change:{…}}}}.
Live game state rides on the event objects — `eventStatus` (state, period,
clock, scores), `eventScorecard` (per-interval scores) — and on markets as
`statistics.live[] = {type, prefix, value}` (e.g. a pitcher's running K
count). By default this prints only rows that carry any of those, one JSON
object per line; `--raw` prints everything.

DK_LIVE_HOST overrides the socket host (default sportsbook-ws-us-nj).
"""
import argparse
import asyncio
import json
import os
import sys
import time

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.exit("pip install websockets")

HOST = os.environ.get("DK_LIVE_HOST", "sportsbook-ws-us-nj.draftkings.com")
URL = f"wss://{HOST}/websocket"
HEADERS = {
    "Origin": "https://sportsbook.draftkings.com",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
}
LIVE_KEYS = ("eventStatus", "eventScorecard", "eventScore", "liveInfo")


def game_state(e):
    """Compact baseball state from a live event object. Observed live
    2026-09-15: `eventStatus` stays null for MLB; the state is on
    `eventScore.metadata` {atBat: home|away, balls, strikes, outs,
    bases: "100" (1B,2B,3B occupied flags), *CurrentBatter ids} with
    per-inning `gamePartScores` and `mainScore` — and, more sparsely, on
    `eventScorecard.mainScorecard.liveScoreData` {baseballBase,
    baseballOuts}. Fields absent on non-baseball or pre-game rows are
    left None rather than guessed."""
    sc = e.get("eventScore") or {}
    md = sc.get("metadata") or {}
    main = sc.get("mainScore") or {}
    parts = sc.get("gamePartScores") or []
    inning = None
    for p in parts:  # last inning with any score posted is the current one
        if p.get("homeScore") is not None or p.get("awayScore") is not None:
            inning = p.get("name")
    at_bat = md.get("atBat")
    return {
        "inning": inning,
        "half": {"away": "top", "home": "bottom"}.get(at_bat),
        "outs": md.get("outs"), "balls": md.get("balls"), "strikes": md.get("strikes"),
        "bases": md.get("bases"),
        "score": {"away": main.get("awayScore"), "home": main.get("homeScore")} if main else None,
        "batter": md.get(f"{at_bat}CurrentBatter") if at_bat else None,
    }


MARKETS_FILTER = "$filter=tags/all(t: t ne 'SportcastBetBuilder')"  # dk-data-layer's default


def subscribe_msg(query, req_id=1, markets=False):
    qp = {"query": query, "initialData": True, "projection": "sportsbook", "locale": "en-US"}
    if markets:
        # Also stream the event's markets; each carries statistics.live[]
        # ({type:"MarketStat", prefix:"Current", value}) — the running
        # per-prop stat (a pitcher's K count so far, a batter's RBIs).
        qp["includeMarkets"] = MARKETS_FILTER
    return json.dumps({
        "jsonrpc": "2.0", "id": req_id, "method": "subscribe",
        "params": {"entity": "events", "queryParams": qp},
    })


def live_rows(msg):
    """Pull the live-state bits out of one `update`: events with status or
    scorecard, and markets carrying live statistics."""
    d = ((msg.get("data") or {}).get("data") or {})
    out = []
    for section in ("add", "change"):
        blk = d.get(section) or {}
        for e in blk.get("events") or []:
            if isinstance(e, dict) and (any(e.get(k) for k in LIVE_KEYS) or e.get("status") not in (None, "NotStarted")):
                out.append({"kind": "event", "op": section, "id": e.get("id"),
                            "name": e.get("name"), "status": e.get("status"),
                            "state": game_state(e),
                            "eventStatus": e.get("eventStatus"),
                            "eventScore": e.get("eventScore"),
                            "eventScorecard": e.get("eventScorecard")})
        for m in blk.get("markets") or []:
            stats = (m.get("statistics") or {}).get("live") if isinstance(m, dict) else None
            if stats:
                out.append({"kind": "market", "op": section, "id": m.get("id"),
                            "eventId": m.get("eventId"), "name": m.get("name"),
                            "live": stats})
    return out


async def run(query, raw, duration, markets=False):
    end = time.time() + duration if duration else None
    backoff = 2
    while end is None or time.time() < end:
        try:
            async with websockets.connect(URL, open_timeout=15, additional_headers=HEADERS,
                                          max_size=None, ping_interval=20) as ws:
                await ws.send(subscribe_msg(query, markets=markets))
                backoff = 2
                while end is None or time.time() < end:
                    r = await asyncio.wait_for(ws.recv(), 180)
                    s = r if isinstance(r, str) else r.decode("utf-8", "replace")
                    try:
                        msg = json.loads(s)
                    except ValueError:
                        continue
                    if msg.get("event") == "exception":
                        print(json.dumps({"kind": "error", "error": msg.get("error")}), flush=True)
                        break  # reconnect
                    if raw:
                        print(s, flush=True)
                        continue
                    for row in live_rows(msg):
                        row["t"] = (msg.get("data") or {}).get("metadata", {}).get("publishedTime")
                        print(json.dumps(row), flush=True)
        except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
            print(json.dumps({"kind": "reconnect", "reason": repr(e)[:200]}), file=sys.stderr, flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--league", default="84240", help="DK league id (default MLB 84240)")
    ap.add_argument("--event", help="DK event id — subscribe to one game instead of the league")
    ap.add_argument("--markets", action="store_true",
                    help="also stream markets (live per-prop stats: statistics.live)")
    ap.add_argument("--raw", action="store_true", help="print every message verbatim")
    ap.add_argument("--seconds", type=float, default=0, help="stop after N seconds (0 = run until killed)")
    a = ap.parse_args()
    query = f"$filter=id eq '{a.event}'" if a.event else f"$filter=leagueId eq '{a.league}'"
    try:
        asyncio.run(run(query, a.raw, a.seconds, markets=a.markets))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
