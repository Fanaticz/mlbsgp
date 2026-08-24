#!/usr/bin/env python3
"""Smoke test for the one-button "scrape all soccer SGPs" sweep.

Guards find_sgps_soccer_all's orchestration + aggregation: Pinnacle fair lines
for every combo family always render; DK prices layer in when calculateBets is
reachable; a DK-unreachable league degrades to fair-lines-only (dk_blocked)
without dropping rows. Stubs Pinnacle at the function level and DK with the
committed EPL feed fixture. Run: python3 scripts/smoke_soccer_sweep.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import dk_api  # noqa: E402

DK_FEED = json.load(open(os.path.join(ROOT, "scripts", "fixtures", "dk_epl_sgp_event.json")))
HOME, AWAY = "Nottingham Forest", "Leeds United"

failures = []
def check(c, m):
    print(("  ok: " if c else "  FAIL: ") + m)
    if not c:
        failures.append(m)


# --- Pinnacle stubs (one league, one match, a few combo families) ---
def fake_pin_games(league=None, league_id=None):
    return {"matches": [{"id": 999, "home": HOME, "away": AWAY,
                         "startTime": "2099-01-01T00:00:00Z"}]}


def fake_pin_specials(mid):
    # Minimal groups with the structured `fields` the DK matcher consumes.
    return {"home": HOME, "away": AWAY, "groups": [
        {"key": "btts_total", "kind": "btts_total", "label": "BTTS/Total", "sels": [
            {"name": "Yes & Over 2.5", "odds": 140, "fair_prob": 0.40, "fair_american": 150,
             "fields": {"btts": "Yes", "total_side": "Over", "total_line": 2.5}},
            {"name": "No & Under 2.5", "odds": 154, "fair_prob": 0.37, "fair_american": 167,
             "fields": {"btts": "No", "total_side": "Under", "total_line": 2.5}},
        ]},
        {"key": "winner_total", "kind": "winner_total", "label": "Winner/Total", "sels": [
            {"name": "Draw & Under 2.5", "odds": 330, "fair_prob": 0.217, "fair_american": 360,
             "fields": {"result": "draw", "total_side": "Under", "total_line": 2.5}},
        ]},
    ]}


class _R:
    def json(self):
        return DK_FEED


dk_api.pinnacle_wc_games = fake_pin_games
dk_api.pinnacle_wc_specials = fake_pin_specials
dk_api._get_with_retry = lambda *a, **k: _R()            # get_markets -> EPL feed
dk_api._parse_iso_epoch = lambda s: None                 # bypass time window
dk_api._dk_games_for_league = lambda key, attempts=2: (
    [{"id": DK_FEED["data"]["events"][0]["id"], "homeTeam": "Nottingham Forest",
      "awayTeam": "Leeds", "hasSGP": True}], None)

ARGS = {"leagues": ["epl"], "max_games": 5, "sgp_only": True, "window_hours": 99999}

print("sweep, calculateBets UP:")
dk_api._price_combo = lambda ids: {"sgpOdds": "+330", "sgpDecimal": 4.3, "legInfo": []}
res = dk_api.find_sgps_soccer_all(dict(ARGS))
rows, s = res["rows"], res["summary"]
check(s["games_with_candidates"] == 1, "one game with candidates")
check(all(r["fair_american"] is not None for r in rows), "every row has a Pinnacle fair line")
kinds = set(r["market_key"] for r in rows)
check({"btts_total", "winner_total"} <= kinds, "combo families present (%s)" % ",".join(sorted(kinds)))
check(s["dk_priced_any"], "DK priced at least one combo")
priced = [r for r in rows if r["ev_pct"] is not None]
check(priced, "at least one row has an EV vs Pinnacle")
# EV ranking: priced +EV rows sort ahead of fair-only rows
check(rows[0]["ev_pct"] is not None, "priced rows rank ahead of fair-only rows")

print("\nsweep, calculateBets DOWN:")
dk_api._price_combo = lambda ids: None
res = dk_api.find_sgps_soccer_all(dict(ARGS))
rows, s = res["rows"], res["summary"]
check(not s["dk_priced_any"], "no DK prices when calculateBets down")
check(all(r["fair_american"] is not None for r in rows), "Pinnacle fair board still fully rendered")
check(len(rows) >= 3, "rows retained even with DK down (%d)" % len(rows))

print("\nsweep, DK league unreachable (403/IP block):")
dk_api._dk_games_for_league = lambda key, attempts=2: (None, "HTTP 403 AkamaiGHost")
res = dk_api.find_sgps_soccer_all(dict(ARGS))
rows, s = res["rows"], res["summary"]
check(s["dk_blocked"], "dk_blocked flagged when the first league 403s")
check(len(rows) >= 3, "Pinnacle rows still returned when DK is blocked (%d)" % len(rows))
check(all(r["dk_status"] == "blocked" for r in rows), "rows marked dk_status=blocked")

print("\n%s" % ("ALL SWEEP SMOKE CHECKS PASSED" if not failures else "%d FAILURE(S)" % len(failures)))
sys.exit(1 if failures else 0)
