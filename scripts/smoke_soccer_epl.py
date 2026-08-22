#!/usr/bin/env python3
"""Smoke test for EPL (and general multi-league) soccer SGP support.

Guards the 2026-08 EPL enablement:
  * the soccer league registry resolves 'epl' to DK 40253 / Pinnacle 1980,
  * DK-vs-Pinnacle club-name aliases match short vs long forms
    (Man City / Manchester City, Wolves / Wolverhampton, ...),
  * get_markets(soccer_only) on an EPL feed exposes the BTTS + Total legs and
    carries the HT/FT bet-slip line,
  * find_sgps_worldcup(league='epl') matches DK's prebuilt HT/FT combo to
    Pinnacle candidates with NO calculateBets call (works cookie-free), and
    resolves the BTTS + Over 2.5 legs for the SGP-priced path.

Stubs the network with a committed feed fixture
(scripts/fixtures/dk_epl_sgp_event.json — a real capture trimmed to the
combo/leg markets). Run: python3 scripts/smoke_soccer_epl.py  (exit 0 = pass)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import dk_api  # noqa: E402

FEED = json.load(open(os.path.join(ROOT, "scripts", "fixtures", "dk_epl_sgp_event.json")))
EID = FEED["data"]["events"][0]["id"]

failures = []


def check(cond, msg):
    print(("  ok: " if cond else "  FAIL: ") + msg)
    if not cond:
        failures.append(msg)


# The DK games feed (sportscontent leagues) and the per-event SGP feed have
# different shapes: games has top-level `events`, the SGP feed nests them under
# `data`. Route the stub by URL so both callers get the shape they expect.
_GAMES_FEED = {"events": [FEED["data"]["events"][0]]}


class _R:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _fake_get(url, params=None, timeout=15, attempts=6):
    if "/sgp/events/" in url:
        return _R(FEED)
    return _R(_GAMES_FEED)


dk_api._get_with_retry = _fake_get
# calculateBets unavailable — the realistic datacenter/no-cookie case. Prebuilt
# combos (HT/FT) must still match; SGP-priced combos degrade to no-match.
dk_api._price_combo = lambda ids: None

print("league registry:")
epl = dk_api._soccer_league("epl")
check(epl["dk_id"] == "40253", "epl -> DK league 40253 (got %s)" % epl["dk_id"])
check(epl["pin_id"] == "1980", "epl -> Pinnacle league 1980 (got %s)" % epl["pin_id"])
check(dk_api._soccer_league("nope")["label"] == dk_api._soccer_league(None)["label"],
      "unknown league key falls back to default")

print("\nclub-name aliases (DK short vs Pinnacle long):")
for a, b in [("Manchester City", "Man City"), ("Manchester United", "Man Utd"),
             ("Wolverhampton Wanderers", "Wolves"), ("Tottenham Hotspur", "Spurs"),
             ("Leeds United", "Leeds"), ("Newcastle United", "Newcastle")]:
    check(dk_api._team_matches_soccer(a, b), "'%s' matches '%s'" % (a, b))

print("\nget_markets(soccer_only) on EPL feed:")
md = dk_api.get_markets(EID, soccer_only=True)
props = md["props"]
kinds = {}
for p in props:
    blob = " ".join([p.get("marketName", ""), p.get("marketType", ""), p.get("subcategory", "")])
    k = dk_api._soccer_market_kind(blob) or dk_api._soccer_straight_kind(p.get("marketName", ""), p.get("subcategory", ""))
    if k:
        kinds.setdefault(k, 0)
        kinds[k] += 1
check(kinds.get("btts", 0) > 0, "BTTS leg market present")
check(kinds.get("total_goals", 0) > 0, "Total Goals leg market present")
check(kinds.get("ht_ft", 0) >= 9, "HT/FT prebuilt combo present (%d cells)" % kinds.get("ht_ft", 0))
htft = [p for p in props if dk_api._soccer_market_kind(
    " ".join([p.get("marketName", ""), p.get("marketType", ""), p.get("subcategory", "")])) == "ht_ft"]
check(any(p.get("betslipLine") for p in htft), "HT/FT props carry betslipLine pairing")

print("\nBTTS + Over 2.5 leg resolution (needed for the SGP-priced path):")
props_by_kind = {}
for p in props:
    blob = " ".join([p.get("marketName", ""), p.get("marketType", ""), p.get("subcategory", "")])
    k = dk_api._soccer_market_kind(blob) or dk_api._soccer_straight_kind(p.get("marketName", ""), p.get("subcategory", ""))
    if k:
        props_by_kind.setdefault(k, []).append(p)
home, away = "Nottingham Forest", "Leeds United"
mb = dk_api._match_soccer_selection({"market_key": "btts", "btts": "Yes"}, props_by_kind.get("btts", []), home, away)
mt = dk_api._match_soccer_selection({"market_key": "total_goals", "total_side": "Over", "total_line": 2.5},
                                    props_by_kind.get("total_goals", []), home, away)
check(bool(mb and mb.get("selectionId")), "BTTS Yes leg resolves to a DK selection id")
check(bool(mt and mt.get("selectionId")), "Over 2.5 leg resolves to a DK selection id")

print("\nfind_sgps_worldcup(league='epl') HT/FT prebuilt match (cookie-free):")
htft_cands = [
    {"id": "ht_ft:0", "market_key": "ht_ft", "ht": "home", "ft": "home"},
    {"id": "ht_ft:1", "market_key": "ht_ft", "ht": "away", "ft": "home"},
    {"id": "ht_ft:2", "market_key": "ht_ft", "ht": "draw", "ft": "draw"},
]
res = dk_api.find_sgps_worldcup({"league": "epl", "home": home, "away": away, "candidates": htft_cands})
check("error" not in res, "scan ran without error (%s)" % res.get("error", "ok"))
by_id = {r["id"]: r for r in res.get("results", [])}
matched = [i for i in ("ht_ft:0", "ht_ft:1", "ht_ft:2")
           if by_id.get(i, {}).get("matched") and by_id[i].get("via") == "prebuilt"]
check(len(matched) == 3, "all 3 HT/FT cells matched via DK prebuilt (%d/3)" % len(matched))
sample = by_id.get("ht_ft:1", {})
check(sample.get("dk_american") not in (None, ""), "HT/FT cell carries a DK price (%s)" % sample.get("dk_american"))

print("\n%s" % ("ALL SMOKE CHECKS PASSED" if not failures else "%d FAILURE(S)" % len(failures)))
sys.exit(1 if failures else 0)
