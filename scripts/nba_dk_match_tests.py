#!/usr/bin/env python3
"""NBA DK market matcher unit tests.

DO NOT DELETE — regression guard for _stat_matches_market_nba +
_match_leg_to_dk_nba. Run any time the NBA matchers or the
get_markets(nba_only) subcat filter is touched.

Exercises the pure matchers without a live DK call: synthesizes a
props list mirroring what get_markets(nba_only=True) would return and
verifies matcher output.

Invocation:
  python3 scripts/nba_dk_match_tests.py
Expected final line: "ALL NBA DK MATCH TESTS PASS"
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import dk_api as D

passes = 0
failures = 0
def check(label, got, want):
    global passes, failures
    if got == want:
        passes += 1
        print(f"PASS  {label}")
    else:
        failures += 1
        print(f"FAIL  {label}  got={got!r} want={want!r}")


# --- _stat_matches_market_nba ---
blobs = {
    "points_o_u":  "Player Points O/U Player Points Points",
    "rebounds":    "Player Rebounds Rebounds O/U Rebounds",
    "assists":     "Player Assists Assists O/U Assists",
    "threes":      "Player 3-Pointers Made 3-Pointers Made Threes",
    "three_pt":    "Player 3-Pt Made 3-Pt Made Threes Made",
    "pra_combo":   "Player Points + Rebounds + Assists PRA",
    "pr_combo":    "Player Points + Rebounds",
    "pa_combo":    "Player Points + Assists",
    "steals":      "Player Steals Steals O/U",
}
check("Points matches plain-points blob",           D._stat_matches_market_nba("Points", blobs["points_o_u"]), True)
check("Points does NOT match 3-pointers blob",      D._stat_matches_market_nba("Points", blobs["threes"]), False)
check("Points does NOT match PRA",                  D._stat_matches_market_nba("Points", blobs["pra_combo"]), False)
check("Points does NOT match PR",                   D._stat_matches_market_nba("Points", blobs["pr_combo"]), False)
check("Rebounds matches rebounds blob",             D._stat_matches_market_nba("Rebounds", blobs["rebounds"]), True)
check("Rebounds does NOT match PRA",                D._stat_matches_market_nba("Rebounds", blobs["pra_combo"]), False)
check("Assists matches assists blob",               D._stat_matches_market_nba("Assists", blobs["assists"]), True)
check("Assists does NOT match Points+Assists",      D._stat_matches_market_nba("Assists", blobs["pa_combo"]), False)
check("3-Pointers Made matches 3-Pt blob",          D._stat_matches_market_nba("3-Pointers Made", blobs["three_pt"]), True)
check("3-Pointers Made matches threes blob",        D._stat_matches_market_nba("3-Pointers Made", blobs["threes"]), True)
check("Steals (unsupported) returns false",         D._stat_matches_market_nba("Steals", blobs["steals"]), False)


# --- _match_leg_to_dk_nba ---
props = [
    {"selectionId": "pts-over-27",  "player": "Donovan Mitchell", "outcomeType": "Over",
     "points": 27.5, "marketName": "Donovan Mitchell Points O/U", "subcategory": "Points O/U",
     "marketType": "Player Points", "oddsAmerican": "+125", "isNbaProp": True},
    {"selectionId": "pts-under-27", "player": "Donovan Mitchell", "outcomeType": "Under",
     "points": 27.5, "marketName": "Donovan Mitchell Points O/U", "subcategory": "Points O/U",
     "marketType": "Player Points", "oddsAmerican": "-150", "isNbaProp": True},
    {"selectionId": "reb-over-4",   "player": "Donovan Mitchell", "outcomeType": "Over",
     "points": 4.5,  "marketName": "Donovan Mitchell Rebounds O/U", "subcategory": "Rebounds O/U",
     "marketType": "Player Rebounds", "oddsAmerican": "-140", "isNbaProp": True},
    {"selectionId": "pra-over-40",  "player": "Donovan Mitchell", "outcomeType": "Over",
     "points": 40.5, "marketName": "Donovan Mitchell PRA", "subcategory": "PRA O/U",
     "marketType": "Player PRA", "oddsAmerican": "-115", "isNbaProp": False},
]

m = D._match_leg_to_dk_nba("Donovan Mitchell", "Points", "over", 27.5, props)
check("points over 27.5 matches", m["selection_id"] if m else None, "pts-over-27")
check("points over 27.5 returns opposite",  m["opposite_selection_id"] if m else None, "pts-under-27")
check("points over 27.5 over_american = +125", m["over_american"] if m else None, 125)
check("points over 27.5 under_american = -150", m["under_american"] if m else None, -150)

m = D._match_leg_to_dk_nba("Donovan Mitchell", "Points", "under", 27.5, props)
check("points under 27.5 matches", m["selection_id"] if m else None, "pts-under-27")

m = D._match_leg_to_dk_nba("Donovan Mitchell", "Rebounds", "over", 4.5, props)
check("rebounds over 4.5 matches", m["selection_id"] if m else None, "reb-over-4")
check("rebounds over 4.5 has no opposite in fixture",
      m["opposite_selection_id"] if m else None, None)

# Line that DK doesn't offer → None (the nbaEvTab.js enumerator already
# picked the closest correlation line; the DK lookup is strict exact).
m = D._match_leg_to_dk_nba("Donovan Mitchell", "Points", "over", 22.5, props)
check("points over 22.5 absent from DK returns None", m, None)

# PRA prop shouldn't match Points (isNbaProp=False on the fixture row).
m = D._match_leg_to_dk_nba("Donovan Mitchell", "Points", "over", 40.5, props)
check("PRA row with isNbaProp=False is not matched by Points lookup", m, None)

# Wrong player → None
m = D._match_leg_to_dk_nba("LeBron James", "Points", "over", 27.5, props)
check("different player returns None", m, None)


# --- _event_for_nba_candidate (team/game → DK event) ---
# Direct call to the module-level resolver. No network — just the pure
# string matching against a canned 2-event fixture that mirrors what DK
# returns on a typical nav/leagues response.
EVENTS = [
    {"id": "e_phi_bos", "name": "Philadelphia 76ers @ Boston Celtics",
     "homeTeam": "Boston Celtics", "awayTeam": "Philadelphia 76ers",
     "homeShort": "BOS", "awayShort": "PHI"},
    {"id": "e_lal_gsw", "name": "Los Angeles Lakers @ Golden State Warriors",
     "homeTeam": "Golden State Warriors", "awayTeam": "Los Angeles Lakers",
     "homeShort": "GSW", "awayShort": "LAL"},
]

def match_team_game(team, game):
    r = D._event_for_nba_candidate({"team": team, "game": game}, EVENTS)
    return r["id"] if r else None

check("team='PHI' short code",                         match_team_game("PHI", ""), "e_phi_bos")
check("team='BOS' short code",                         match_team_game("BOS", ""), "e_phi_bos")
check("team='LAL' short code → LAL/GSW event",         match_team_game("LAL", ""), "e_lal_gsw")
check("game='PHI@BOS' short-code pair",                match_team_game("", "PHI@BOS"), "e_phi_bos")
check("game='PHI @ BOS' short-code pair with spaces",  match_team_game("", "PHI @ BOS"), "e_phi_bos")
# Full team names (the user's actual FV-sheet format that was failing)
check("team='Philadelphia 76ers' full name",
      match_team_game("Philadelphia 76ers", ""), "e_phi_bos")
check("team='Boston Celtics' full name",
      match_team_game("Boston Celtics", ""), "e_phi_bos")
check("game='Philadelphia 76ers @ Boston Celtics' full-name game",
      match_team_game("", "Philadelphia 76ers @ Boston Celtics"), "e_phi_bos")
check("game='Los Angeles Lakers vs Golden State Warriors' full-name + vs",
      match_team_game("", "Los Angeles Lakers vs Golden State Warriors"), "e_lal_gsw")
# Nickname-only
check("team='76ers' nickname",
      match_team_game("76ers", ""), "e_phi_bos")
check("team='Celtics' nickname",
      match_team_game("Celtics", ""), "e_phi_bos")
# Unknown team / game
check("team='MIA' not in fixture → None",  match_team_game("MIA", ""), None)
check("empty team + empty game → None",    match_team_game("", ""), None)

print(f"\n{passes} pass, {failures} fail")
if failures:
    sys.exit(1)
print("ALL NBA DK MATCH TESTS PASS")
