#!/usr/bin/env python3
"""DraftKings SGP API helper.

Uses curl_cffi with Chrome TLS impersonation to bypass Akamai bot protection.
Called from Node.js server via subprocess.

Usage:
  python3 dk_api.py games                  # Get today's MLB games
  python3 dk_api.py markets <eventId>      # Get pitcher prop markets for a game
  python3 dk_api.py price <sel1> <sel2> .. # Get SGP price for selections
"""

import sys
import json
from curl_cffi import requests as cffi_requests

DK_MLB_LEAGUE_ID = "84240"
DK_NAV = "https://sportsbook-nash.draftkings.com/api/sportscontent/navigation/dkusnj/v1/nav/leagues"
DK_MARKETS = "https://sportsbook-nash.draftkings.com/sites/US-SB/api/sportscontent/controldata/event/eventSubcategory/v1/markets"
DK_SGP = "https://sportsbook-nash.draftkings.com/sites/US-SB/api/sportscontent/parlays/v1/sgp/events"
DK_PRICE = "https://gaming-us-nj.draftkings.com/api/wager/v1/calculateBets"

session = cffi_requests.Session(impersonate="chrome")


def get_games():
    """Return today's MLB games from DraftKings."""
    r = session.get(f"{DK_NAV}/{DK_MLB_LEAGUE_ID}", timeout=15)
    r.raise_for_status()
    events = r.json().get("events", [])
    out = []
    for e in events:
        tags = e.get("tags", [])
        participants = e.get("participants", [])
        home = next((p for p in participants if p.get("venueRole") == "Home"), {})
        away = next((p for p in participants if p.get("venueRole") == "Away"), {})
        out.append({
            "id": e.get("eventId"),
            "name": e.get("name", ""),
            "startDate": e.get("startDate", ""),
            "homeTeam": home.get("name", e.get("teamName2", "")),
            "awayTeam": away.get("name", e.get("teamName1", "")),
            "homeShort": home.get("metadata", {}).get("shortName", e.get("teamShortName2", "")),
            "awayShort": away.get("metadata", {}).get("shortName", e.get("teamShortName1", "")),
            "hasSGP": "SGP" in tags,
            "isLive": e.get("isLive", False),
            "status": e.get("status", ""),
        })
    out.sort(key=lambda x: x["startDate"])
    return {"events": out}


def get_markets(event_id):
    """Return pitcher prop markets and all SGP-eligible markets for an event."""
    # Step 1: Get event metadata (subcategories + market groups)
    r0 = session.get(f"{DK_SGP}/{event_id}", timeout=15)
    r0.raise_for_status()
    evt = r0.json()["data"]["events"][0]
    subcats = evt.get("clientMetadata", {}).get("subCategories", [])
    market_groups = evt.get("marketGroups", [])

    # Step 2: Fetch markets for each subcategory
    all_markets = []
    all_selections = []
    sel_by_mkt = {}

    for sc in subcats:
        try:
            r = session.get(DK_MARKETS, params={
                "isBatchable": "false",
                "templateVars": event_id,
                "marketsQuery": f"$filter=clientMetadata/subCategoryId eq '{sc['id']}'",
                "entity": "markets",
            }, timeout=10)
            if r.status_code != 200:
                continue
            d = r.json()
            mkts = d.get("markets", [])
            sels = d.get("selections", [])
            for m in mkts:
                m["_subCategoryName"] = sc.get("name", "")
                m["_subCategoryId"] = sc.get("id", "")
            all_markets.extend(mkts)
            all_selections.extend(sels)
            for s in sels:
                mid = s.get("marketId", "")
                if mid not in sel_by_mkt:
                    sel_by_mkt[mid] = []
                sel_by_mkt[mid].append(s)
        except Exception:
            continue

    # Step 3: Build structured output
    pitcher_keywords = {"strikeout", "earned run", "walk", "hits allowed", "pitching out",
                        "pitcher", "outs recorded"}
    props = []
    for m in all_markets:
        mname = m.get("name", "")
        mtype = m.get("marketType", {}).get("name", "")
        mid = m.get("id", "")
        m_sels = sel_by_mkt.get(mid, [])

        is_pitcher = any(kw in mname.lower() or kw in mtype.lower() for kw in pitcher_keywords)

        # Extract player name from market name by removing market type suffix
        # e.g. "Kris Bubic Strikeouts Thrown O/U" -> "Kris Bubic"
        player_name = mname
        for suffix in [mtype, m.get("_subCategoryName", "")]:
            if suffix and player_name.endswith(suffix):
                player_name = player_name[:-len(suffix)].strip()
            elif suffix:
                # Try removing common suffix patterns
                for pat in [suffix, suffix.replace(" O/U", ""), suffix.replace(" Milestones", "")]:
                    if pat and player_name.lower().endswith(pat.lower()):
                        player_name = player_name[:-len(pat)].strip()
                        break
        # Fallback: split on known stat keywords
        if player_name == mname:
            for kw in ["Strikeouts", "Earned Runs", "Walks", "Hits Allowed",
                        "Pitching Outs", "Total Bases", "Home Runs", "RBIs",
                        "Hits", "Runs", "Singles", "Doubles", "Stolen Bases"]:
                idx = mname.find(kw)
                if idx > 0:
                    player_name = mname[:idx].strip()
                    break

        for s in m_sels:
            # Selection data from this endpoint uses 'label' and 'outcomeType'
            outcome_type = s.get("outcomeType", s.get("name", ""))
            points = s.get("points")
            display = f"{outcome_type} {points}" if points is not None else outcome_type

            # Also check for players array (present in SGP endpoint but not subcategory endpoint)
            sel_players = s.get("players", [])
            pname = sel_players[0].get("name", "") if sel_players else player_name

            props.append({
                "selectionId": s.get("id", ""),
                "marketId": mid,
                "marketName": mname,
                "marketType": mtype,
                "subcategory": m.get("_subCategoryName", ""),
                "player": pname,
                "outcomeType": outcome_type,
                "displayPoints": display,
                "points": points,
                "oddsAmerican": s.get("displayOdds", {}).get("american", ""),
                "oddsDecimal": s.get("trueOdds"),
                "isPitcherProp": is_pitcher,
                "isDisabled": s.get("isDisabled", False),
            })

    return {
        "eventId": event_id,
        "totalMarkets": len(all_markets),
        "totalSelections": len(all_selections),
        "marketGroups": [{"id": mg["id"], "name": mg["name"], "count": mg.get("marketsCount", 0)} for mg in market_groups],
        "props": props,
    }


def get_price(selection_ids):
    """Get correlated SGP price from DraftKings."""
    payload = {
        "selections": [],
        "selectionsForYourBet": [{"id": sid, "yourBetGroup": 0} for sid in selection_ids],
        "selectionsForCombinator": [],
        "selectionsForProgressiveParlay": [],
        "oddsStyle": "american",
    }
    r = session.post(DK_PRICE, json=payload, timeout=15)

    if r.status_code == 422:
        return {"error": "Incompatible leg combination", "incompatible": True}

    r.raise_for_status()
    data = r.json()

    restrictions = data.get("combinabilityRestrictions", [])
    if restrictions:
        return {"error": "Legs cannot be combined", "incompatible": True, "restrictions": restrictions}

    # Extract bet info
    bets = data.get("bets", [])
    bet = next((b for b in bets if b.get("trueOdds") and len(b.get("selectionsMapped", [])) >= 2), None)
    if not bet:
        return {"error": "No valid SGP price returned"}

    # Also return individual leg info
    legs = []
    for sel in data.get("selectionsForYourBet", []):
        legs.append({
            "id": sel.get("id"),
            "displayOdds": sel.get("displayOdds", ""),
            "trueOdds": sel.get("trueOdds"),
            "points": sel.get("points"),
        })

    return {
        "sgpOdds": bet.get("displayOdds", ""),
        "sgpDecimal": bet.get("trueOdds"),
        "legs": legs,
        "legCount": len(legs),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: dk_api.py <games|markets|price> [args]"}))
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        if cmd == "games":
            result = get_games()
        elif cmd == "markets" and len(sys.argv) >= 3:
            result = get_markets(sys.argv[2])
        elif cmd == "price":
            # Read selection IDs from stdin (JSON array) to avoid shell escaping issues
            stdin_data = sys.stdin.read().strip()
            if stdin_data:
                selection_ids = json.loads(stdin_data)
            elif len(sys.argv) >= 4:
                selection_ids = sys.argv[3:]
            else:
                selection_ids = []
            if len(selection_ids) < 2:
                result = {"error": "Need at least 2 selection IDs"}
            else:
                result = get_price(selection_ids)
        else:
            result = {"error": f"Unknown command or missing args: {cmd}"}
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
