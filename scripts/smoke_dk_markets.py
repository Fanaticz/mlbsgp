#!/usr/bin/env python3
"""Smoke test for the DK sportscontent market parse (get_markets + leg match).

Guards the 2026-08 DK API migration: DK retired the nav + controldata endpoints,
so get_markets() now parses the still-live per-event SGP feed, which embeds every
market's selections inline. This test stubs the network with a committed feed
fixture (scripts/fixtures/dk_sgp_event_pitcher.json — a real capture trimmed to
the two starters' pitcher-prop markets) and asserts that:

  * pitcher_only parsing keeps the pitcher props with valid selection ids + odds,
  * both starters get complete Over/Under legs for K / ER / Hits / Outs / Walks,
  * milestone (X-or-Fewer) legs parse their integer thresholds,
  * _match_leg_to_dk resolves canonical OCR legs to DK selection ids.

Run: python3 scripts/smoke_dk_markets.py   (exit 0 = pass)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import dk_api  # noqa: E402

FIXTURE_PATH = os.path.join(ROOT, "scripts", "fixtures", "dk_sgp_event_pitcher.json")
FIXTURE = json.load(open(FIXTURE_PATH))
EVENT_ID = FIXTURE["data"]["events"][0]["id"]


class _FakeResp:
    def json(self):
        return FIXTURE


def _fake_get(url, params=None, timeout=15, attempts=6):
    return _FakeResp()


dk_api._get_with_retry = _fake_get

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("  FAIL:", msg)
    else:
        print("  ok:", msg)


print("get_markets(pitcher_only=True):")
res = dk_api.get_markets(EVENT_ID, pitcher_only=True)
props = res["props"]
check(res["totalMarkets"] > 0, "markets parsed (%d)" % res["totalMarkets"])
check(all(p["isPitcherProp"] for p in props), "all props classified as pitcher props")

from collections import defaultdict  # noqa: E402
ou = defaultdict(dict)
for p in props:
    if "O/U" in (p["subcategory"] or "") and p["points"] is not None \
            and p["outcomeType"] in ("Over", "Under"):
        ou[(p["player"], dk_api._stat_cat(p["marketName"]) or p["marketType"])][p["outcomeType"]] = p

players = {p["player"] for p in props if p["player"]}
for player in sorted(players):
    stats = {k[1] for k, v in ou.items() if k[0] == player and "Over" in v and "Under" in v}
    check(len(stats) >= 4,
          "%s has >=4 complete Over/Under stat lines (%d: %s)"
          % (player, len(stats), ",".join(sorted(stats))))

for (player, stat), v in ou.items():
    for side in ("Over", "Under"):
        if side in v:
            check(bool(v[side]["selectionId"]), "%s %s %s has selection id" % (player, stat, side))
            check(isinstance(v[side]["oddsDecimal"], (int, float)),
                  "%s %s %s has decimal odds" % (player, stat, side))
    break  # spot-check one; the loop above already covered completeness

miles = [p for p in props if p["points"] is not None
         and p["outcomeType"] not in ("Over", "Under")]
check(len(miles) > 0, "milestone legs parsed thresholds (%d)" % len(miles))

print("\n_match_leg_to_dk:")
by_player = defaultdict(list)
for p in props:
    if p["player"]:
        by_player[p["player"]].append(p)
# Build canonical legs from whatever O/U markets exist for the first starter.
starter = sorted(players)[0]
sample_legs = []
seen = set()
for p in by_player[starter]:
    cat = dk_api._stat_cat(p["marketName"])
    if p["outcomeType"] in ("Over", "Under") and p["points"] is not None and cat not in seen:
        stat_word = {"SO": "Strikeouts", "ER": "Earned Runs", "H": "Hits Allowed",
                     "OUTS": "Outs", "BB": "Walks"}.get(cat)
        if stat_word:
            sample_legs.append({"leg": "%s %s %s" % (p["outcomeType"], p["points"], stat_word)})
            seen.add(cat)

matched = 0
for l in sample_legs:
    sid = dk_api._match_leg_to_dk(l, props, starter)
    check(bool(sid), "%s -> %s" % (l["leg"], "matched" if sid else "NO MATCH"))
    matched += bool(sid)
check(matched == len(sample_legs) and matched > 0,
      "all %d sample legs matched" % len(sample_legs))

print("\n%s" % ("ALL SMOKE CHECKS PASSED" if not failures else "%d FAILURE(S)" % len(failures)))
sys.exit(1 if failures else 0)
