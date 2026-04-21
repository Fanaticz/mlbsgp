#!/usr/bin/env python3
"""DraftKings SGP API helper.

Uses curl_cffi with Chrome TLS impersonation to bypass Akamai bot protection.
Called from Node.js server via subprocess.

Usage:
  python3 dk_api.py games                       # Get today's MLB games
  python3 dk_api.py markets <eventId>           # Get markets for a game (scoped)
  python3 dk_api.py featured <eventId>          # Auto-build + price SGPs for game
  python3 dk_api.py price                       # Price SGP (selections via stdin JSON)
"""

import sys
import json
import re
import random
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests as cffi_requests

DK_MLB_LEAGUE_ID = "84240"
# NBA league ID on DraftKings' nav endpoint. Override-able via env if DK
# ever renumbers. Verified against the /nav/leagues response April 2026.
import os as _os
DK_NBA_LEAGUE_ID = _os.environ.get("DK_NBA_LEAGUE_ID", "42648")
DK_NAV = "https://sportsbook-nash.draftkings.com/api/sportscontent/navigation/dkusnj/v1/nav/leagues"
DK_MARKETS = "https://sportsbook-nash.draftkings.com/sites/US-SB/api/sportscontent/controldata/event/eventSubcategory/v1/markets"
DK_SGP = "https://sportsbook-nash.draftkings.com/sites/US-SB/api/sportscontent/parlays/v1/sgp/events"
DK_PRICE = "https://gaming-us-nj.draftkings.com/api/wager/v1/calculateBets"

# Rotate TLS fingerprints so Akamai can't pin a single one as "bot" and 403
# every subcategory request for the remainder of the subprocess. Order is
# deliberate: latest "chrome" first because Akamai aggressively 503s the
# pinned-version fingerprints (chrome120/116/etc) on some IPs, while latest
# "chrome" stays under the radar. We round-robin in this order on each rotate
# rather than random.choice'ing — guarantees we exhaust all fingerprints in
# at most N attempts instead of stochastically retrying the bad ones.
_IMPERSONATES = ["chrome", "chrome120", "chrome116", "chrome110", "chrome107",
                 "chrome101", "edge101", "edge99", "safari17_2_ios"]

_session_lock = threading.Lock()
_imp_idx = 0
session = cffi_requests.Session(impersonate=_IMPERSONATES[0])

# Throttle gate: once DK returns a 403 we pause all threads for a cool-off.
# Without this, every in-flight request races into the Akamai block and the
# retry budget burns out in a fraction of a second.
_cooloff_until = 0.0


def _rotate_session():
    global session, _imp_idx
    with _session_lock:
        _imp_idx = (_imp_idx + 1) % len(_IMPERSONATES)
        session = cffi_requests.Session(impersonate=_IMPERSONATES[_imp_idx])


def _trigger_cooloff(seconds):
    global _cooloff_until
    target = _time.time() + seconds
    if target > _cooloff_until:
        _cooloff_until = target


def _wait_for_cooloff():
    now = _time.time()
    if _cooloff_until > now:
        _time.sleep(_cooloff_until - now + random.uniform(0, 0.25))


def _get_with_retry(url, params=None, timeout=15, attempts=6):
    """GET with exponential backoff + session rotation on Akamai blocks.

    DK rate-limits aggressively once we fan out across ~100 subcategory
    fetches; once Akamai 403s one request it will 403 the rest in flight. Before
    giving up we:
      - rotate the curl_cffi TLS impersonation profile (new fingerprint)
      - hold a global cool-off so parallel threads don't burn their retry budget
        hammering the block
      - back off with jitter."""
    last_exc = None
    last_status = None
    for attempt in range(attempts):
        _wait_for_cooloff()
        try:
            sess = session
            r = sess.get(url, params=params, timeout=timeout)
            last_status = r.status_code
            if r.status_code == 200:
                return r
            if r.status_code in (403, 429, 502, 503, 504):
                # 403 = Akamai bot block — longer cool-off + session rotation.
                if r.status_code in (403, 429):
                    _trigger_cooloff(1.5 + attempt * 1.2)
                    if attempt >= 1:
                        _rotate_session()
                _time.sleep(0.6 * (2 ** attempt) + random.uniform(0, 0.4))
                continue
            # Any other non-200 is unrecoverable
            r.raise_for_status()
        except Exception as e:
            last_exc = e
            _time.sleep(0.6 * (2 ** attempt) + random.uniform(0, 0.4))
            continue
    if last_exc:
        raise last_exc
    raise RuntimeError(f"DK request failed after {attempts} attempts: {url} (last status={last_status})")


def get_games():
    """Return today's MLB games from DraftKings."""
    r = _get_with_retry(f"{DK_NAV}/{DK_MLB_LEAGUE_ID}")
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
            "homeStarterId": home.get("metadata", {}).get("startingPitcherPlayerId", ""),
            "awayStarterId": away.get("metadata", {}).get("startingPitcherPlayerId", ""),
            "hasSGP": "SGP" in tags,
            "isLive": e.get("isLive", False),
            "status": e.get("status", ""),
        })
    out.sort(key=lambda x: x["startDate"])
    return {"events": out}


def get_games_nba():
    """Return today's NBA games from DraftKings. Mirrors get_games() but
    scoped to the NBA league ID. Response shape is identical so any
    downstream code that iterates `events` works unchanged."""
    r = _get_with_retry(f"{DK_NAV}/{DK_NBA_LEAGUE_ID}")
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


def _extract_player_name(market_name, market_type, subcat_name):
    """Strip market type/subcategory suffix from the market name to get the player name."""
    name = market_name
    for suffix in [market_type, subcat_name]:
        if not suffix:
            continue
        for pat in [suffix, suffix.replace(" O/U", ""), suffix.replace(" Milestones", "")]:
            if pat and name.lower().endswith(pat.lower()):
                name = name[:-len(pat)].strip()
                break
    # Fallback: split on known stat keywords
    if name == market_name:
        for kw in ["Strikeouts", "Earned Runs", "Walks", "Hits Allowed",
                    "Pitching Outs", "Total Bases", "Home Runs", "RBIs",
                    "Hits", "Runs", "Singles", "Doubles", "Stolen Bases",
                    # NBA player-prop stat names used by the DK market catalog.
                    # 3-Pointers Made has several DK spellings — all three are
                    # kept so the split-on-keyword fallback catches every variant.
                    "3-Pointers Made", "3-Point Made", "Threes Made",
                    "Points", "Rebounds", "Assists", "Steals", "Blocks",
                    "Turnovers"]:
            idx = market_name.find(kw)
            if idx > 0:
                name = market_name[:idx].strip()
                break
    return name


def _fetch_subcategory(event_id, sc):
    """Fetch one subcategory worth of markets, scoped to this event.

    DK's Akamai layer rate-limits aggressively when we fan out across all ~100
    subcategories in parallel. A single 503 here used to silently drop every
    market in that subcategory — e.g. "Hits Allowed O/U" missing meant every
    Over/Under X.5 Hits Allowed leg ended up in unmatched_legs."""
    try:
        r = _get_with_retry(DK_MARKETS, params={
            "isBatchable": "false",
            "templateVars": event_id,
            "marketsQuery": f"$filter=clientMetadata/subCategoryId eq '{sc['id']}'",
            "entity": "markets",
        }, timeout=10)
    except Exception as e:
        sys.stderr.write(f"dk_api: subcat {sc.get('id')} ({sc.get('name')}) failed: {e}\n")
        return [], []
    d = r.json()
    # Client-side filter by eventId — the DK API doesn't filter server-side even
    # though it's called "eventSubcategory". Returns markets from other games too.
    mkts = [m for m in d.get("markets", []) if m.get("eventId") == event_id]
    for m in mkts:
        m["_subCategoryName"] = sc.get("name", "")
        m["_subCategoryId"] = sc.get("id", "")
    kept_mids = {m.get("id", "") for m in mkts}
    sels = [s for s in d.get("selections", []) if s.get("marketId", "") in kept_mids]
    return mkts, sels


def get_markets(event_id, pitcher_only=False, batter_only=False, nba_only=False):
    """Return all markets and selections for an event, scoped properly to that event.

    When pitcher_only=True, skip subcategories that are clearly batter/team/game
    markets before making the per-subcat HTTP call. DK's subcategory endpoint is
    the slowest/most rate-limited part of the flow, so dropping ~80% of the
    fetches (we only care about pitcher props for SGP pricing) is the biggest
    lever we have on end-to-end latency.

    When batter_only=True, the inverse: keep only subcategories whose names
    suggest batter props (Hits, Runs, RBI, TB, HR, Walks, Singles/Doubles/
    Triples, Stolen Bases). Used by find_sgps_teammate to scope teammate-pair
    pricing to a manageable set of fetches per game.

    When nba_only=True, keep only subcats whose names suggest supported NBA
    player props (Points, Rebounds, Assists, 3-Pointers Made). Used by
    find_sgps_nba to scope per-event fetches to the 4 props we actually
    have correlation data for in v1 — Steals/Blocks/Turnovers/PRA/etc.
    scans would burn Akamai quota with no downstream benefit."""
    # Step 1: Get event metadata (subcategories + market groups)
    r0 = _get_with_retry(f"{DK_SGP}/{event_id}")
    evt = r0.json()["data"]["events"][0]
    subcats = evt.get("clientMetadata", {}).get("subCategories", [])
    market_groups = evt.get("marketGroups", [])

    if pitcher_only:
        _SC_BATTER_HINTS = ("batter", "hitter", "home run", "rbi", "total bases",
                            "at bat", "stolen base", "singles", "doubles", "batting",
                            "team total", "game prop", "game lines", "moneyline",
                            "run line", "first inning", "first 5", "1st 5",
                            "innings", "player combo", "alternate run",
                            "parlay", "quick pick")
        _SC_PITCHER_HINTS = ("pitcher", "pitching", "strikeout", "earned run",
                             "walks allowed", "walk allowed", "hits allowed",
                             "outs recorded", "outs o/u", "outs thrown")
        def _keep(sc):
            n = (sc.get("name") or "").lower()
            if any(h in n for h in _SC_BATTER_HINTS):
                return False
            return any(k in n for k in _SC_PITCHER_HINTS)
        subcats = [sc for sc in subcats if _keep(sc)]
    elif batter_only:
        # Symmetric to pitcher_only: keep batter subcats, drop pitcher/team/
        # game-line subcats. Note "home run" appears in both batter (Player
        # Home Runs) and team (Team Total Home Runs) names; the team-line
        # exclusion below catches the latter.
        _SC_BATTER_HINTS = ("hits", "runs", "rbi", "total bases", "home run",
                            "at bat", "stolen base", "singles", "doubles",
                            "triples", "walks", "batter", "hitter", "batting",
                            "extra base")
        _SC_TEAM_OR_GAME_HINTS = ("team total", "team to", "moneyline",
                                  "run line", "game prop", "game lines",
                                  "first inning", "first 5", "1st 5",
                                  "innings", "alternate run line", "spread")
        _SC_PITCHER_HINTS = ("pitcher", "pitching", "strikeout", "earned run",
                             "walks allowed", "walk allowed", "hits allowed",
                             "outs recorded", "outs o/u", "outs thrown")
        def _keep_batter(sc):
            n = (sc.get("name") or "").lower()
            if any(h in n for h in _SC_PITCHER_HINTS):
                return False
            if any(h in n for h in _SC_TEAM_OR_GAME_HINTS):
                return False
            return any(k in n for k in _SC_BATTER_HINTS)
        subcats = [sc for sc in subcats if _keep_batter(sc)]
    elif nba_only:
        # Keep NBA player-prop subcats for our 4 supported stats, drop
        # team/game lines + quarter/half splits + unsupported-stat subcats.
        # "Pointers" catches all the "3-Pointers Made" spellings DK uses.
        _SC_NBA_HINTS = ("points", "rebounds", "assists", "pointers",
                         "three-point", "3-point", "3 pt", "threes")
        _SC_NBA_EXCLUDE = ("team total", "team to", "moneyline", "spread",
                           "game prop", "game lines", "quarter", "half",
                           "1st quarter", "2nd quarter", "3rd quarter",
                           "4th quarter", "first quarter", "first half",
                           "parlay", "quick pick", "race to", "alternate",
                           "steals", "blocks", "turnovers",
                           "double-double", "triple-double", "same game",
                           "player combo", "pra", "points+", "points +")
        def _keep_nba(sc):
            n = (sc.get("name") or "").lower()
            if any(h in n for h in _SC_NBA_EXCLUDE):
                return False
            return any(k in n for k in _SC_NBA_HINTS)
        subcats = [sc for sc in subcats if _keep_nba(sc)]

    # Step 2: Fetch markets for each subcategory in parallel
    all_markets = []
    all_selections = []
    sel_by_mkt = {}

    # max_workers=2 (was 4, originally 8): Akamai 403's once it detects a burst
    # against the subcategory endpoint, and a single 403 cascades — every
    # in-flight request trips the same block. Keeping concurrency low here is
    # measurably faster end-to-end than retrying through a block.
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_fetch_subcategory, event_id, sc) for sc in subcats]
        for fut in as_completed(futures):
            try:
                mkts, sels = fut.result()
            except Exception:
                continue
            all_markets.extend(mkts)
            all_selections.extend(sels)
            for s in sels:
                mid = s.get("marketId", "")
                sel_by_mkt.setdefault(mid, []).append(s)

    # Step 3: Build structured output
    # Pitcher prop detector: match against name AND subcategory AND market type.
    # Order matters — more specific matches first. Skip batter markets explicitly.
    PITCHER_KEYWORDS = ("strikeout", "earned run", "walks", "walk ", "hits allowed",
                        "pitching out", "pitcher", "outs recorded", "pitching strikeouts",
                        "outs o/u", "outs thrown")
    BATTER_HINTS = ("rbi", "total bases", "home run", "at bat", "stolen base", "singles",
                    "doubles", "triples", "batting")
    # Batter prop detector: complement of pitcher detector. A prop is batter
    # if its name/subcat/type blob is clearly batter-flavored AND lacks any
    # pitcher signal. "Walks"/"Hits" alone are ambiguous (pitcher walks-
    # allowed and batter walks both contain "walks"); the pitcher-keyword
    # exclusion disambiguates via the "allowed"/"pitching" qualifier.
    BATTER_KEYWORDS = ("hits", "runs", "rbi", "total bases", "home run",
                       "at bat", "stolen base", "singles", "doubles",
                       "triples", "walks", "batter", "hitter")
    props = []
    for m in all_markets:
        mname = m.get("name", "")
        mtype = m.get("marketType", {}).get("name", "")
        subcat = m.get("_subCategoryName", "")
        mid = m.get("id", "")
        m_sels = sel_by_mkt.get(mid, [])

        blob_lower = (mname + " " + mtype + " " + subcat).lower()
        # Only pitcher if pitcher keywords hit AND no batter hints
        is_pitcher = any(kw in blob_lower for kw in PITCHER_KEYWORDS) and \
                     not any(bh in blob_lower for bh in BATTER_HINTS)
        # Only batter if batter keywords hit AND no pitcher signal. The
        # "team total" / "1st inning" exclusion happens at subcat-keep time
        # for batter_only=True; here we additionally guard so a stray team-
        # total market that slipped through doesn't get tagged as batter.
        is_batter = (any(kw in blob_lower for kw in BATTER_KEYWORDS)
                     and not any(pkw in blob_lower for pkw in PITCHER_KEYWORDS)
                     and "team" not in blob_lower)
        # NBA player prop: one of our 4 supported stats in the market blob,
        # no team/game-line qualifier. The subcat-keep filter already drops
        # PRA / combo / quarter markets for nba_only scans; this guard is
        # the belt+suspenders for per-market classification.
        _NBA_STAT_KWS = ("points", "rebounds", "assists", "pointers",
                         "3-point", "three-point", "3 pt", "threes")
        _NBA_EXCLUDE = ("team", "quarter", "half", "1st", "2nd", "3rd", "4th",
                        "race to", "parlay", "double-double", "triple-double",
                        "pra", "steal", "block", "turnover", "combo")
        is_nba_prop = (any(kw in blob_lower for kw in _NBA_STAT_KWS)
                       and not any(ex in blob_lower for ex in _NBA_EXCLUDE)
                       and not is_pitcher and not is_batter)
        player_name = _extract_player_name(mname, mtype, m.get("_subCategoryName", ""))

        for s in m_sels:
            # Milestone selections (e.g. "5+", "4 or Fewer") omit outcomeType,
            # points, and players entirely — the threshold is in `label` and
            # `milestoneValue`, and the pitcher is in `participants`. Fall back
            # through those so milestone legs actually get matched downstream.
            outcome_type = s.get("outcomeType") or s.get("name") or s.get("label") or ""
            points = s.get("points")
            if points is None:
                points = s.get("milestoneValue")
            if points is None:
                # Last resort: parse an integer threshold out of the label text
                # (handles "5+", "5 or More", "4 or Fewer", etc.)
                label = s.get("label") or ""
                m_pts = re.search(r"\d+", label)
                if m_pts:
                    points = int(m_pts.group(0))
            display = f"{outcome_type} {points}" if points is not None else outcome_type
            sel_players = s.get("players") or s.get("participants") or []
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
                "isBatterProp": is_batter,
                "isNbaProp": is_nba_prop,
                "isDisabled": s.get("isDisabled", False),
            })

    return {
        "eventId": event_id,
        "totalMarkets": len(all_markets),
        "totalSelections": len(all_selections),
        "marketGroups": [{"id": mg["id"], "name": mg["name"], "count": mg.get("marketsCount", 0)} for mg in market_groups],
        "props": props,
    }


def _american_from_decimal(dec):
    if not dec or dec <= 1:
        return ""
    if dec >= 2:
        return f"+{round((dec - 1) * 100)}"
    return f"{round(-100 / (dec - 1))}"


def _price_combo(selection_ids):
    """Call calculateBets for a list of selection IDs. Returns None on incompat/error."""
    try:
        payload = {
            "selections": [],
            "selectionsForYourBet": [{"id": sid, "yourBetGroup": 0} for sid in selection_ids],
            "selectionsForCombinator": [],
            "selectionsForProgressiveParlay": [],
            "oddsStyle": "american",
        }
        r = session.post(DK_PRICE, json=payload, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("combinabilityRestrictions"):
            return None
        bet = next((b for b in data.get("bets", [])
                   if b.get("trueOdds") and len(b.get("selectionsMapped", [])) >= 2), None)
        if not bet:
            return None
        return {
            "sgpOdds": bet.get("displayOdds", ""),
            "sgpDecimal": bet.get("trueOdds"),
            "legInfo": data.get("selectionsForYourBet", []),
        }
    except Exception:
        return None


def get_featured(event_id):
    """Auto-build and price a handful of interesting SGPs for the game."""
    mkts_data = get_markets(event_id)
    props = mkts_data["props"]

    # Group props by player (only Over/Under O/U markets on pitcher props)
    by_player = {}
    for p in props:
        if not p["isPitcherProp"] or p["outcomeType"] not in ("Over", "Under"):
            continue
        # Only standard O/U markets (skip milestones which have no Over/Under semantics)
        if "O/U" not in p["subcategory"]:
            continue
        by_player.setdefault(p["player"], []).append(p)

    # Identify pitchers - they should each have an Over and Under
    pitchers = []
    for player, legs in by_player.items():
        over = next((l for l in legs if l["outcomeType"] == "Over"), None)
        under = next((l for l in legs if l["outcomeType"] == "Under"), None)
        if over and under and over["points"] == under["points"]:
            pitchers.append({"name": player, "over": over, "under": under, "line": over["points"]})

    # Also collect team total strikeout props
    team_total_k = []
    for p in props:
        if "Total" in p["marketName"] and "Strikeout" in p["marketName"] and p["outcomeType"] in ("Over", "Under"):
            team_total_k.append(p)

    # Build candidate SGPs
    candidates = []

    # Cross-pitcher combos: both starters Over, both Under, split directions
    if len(pitchers) >= 2:
        # Take the two most common (typically the starters)
        p1, p2 = pitchers[0], pitchers[1]
        candidates.append({
            "title": "Both Starters Over K's",
            "legs": [p1["over"], p2["over"]],
            "thesis": "Dominant pitching duel — both starters rack up strikeouts",
        })
        candidates.append({
            "title": "Both Starters Under K's",
            "legs": [p1["under"], p2["under"]],
            "thesis": "Bullpen game / both starters exit early",
        })
        candidates.append({
            "title": f"{p1['name']} Over + {p2['name']} Under K's",
            "legs": [p1["over"], p2["under"]],
            "thesis": f"{p1['name']} dominates, {p2['name']} struggles",
        })
        candidates.append({
            "title": f"{p1['name']} Under + {p2['name']} Over K's",
            "legs": [p1["under"], p2["over"]],
            "thesis": f"{p2['name']} dominates, {p1['name']} struggles",
        })

    # Individual pitcher + opposing team total K combos
    # (Pitcher K Over is positively correlated with opposing team K Total Over)
    for pitcher in pitchers[:2]:
        for tt in team_total_k[:2]:
            candidates.append({
                "title": f"{pitcher['name']} Over {pitcher['line']} K + {tt['marketName']} {tt['displayPoints']}",
                "legs": [pitcher["over"], tt],
                "thesis": f"{pitcher['name']} getting strikeouts correlates with team K total {tt['outcomeType'].lower()}",
            })

    # Limit to 6 candidates max
    candidates = candidates[:6]

    # Price all candidates in parallel
    def _price_candidate(c):
        sel_ids = [l["selectionId"] for l in c["legs"]]
        price = _price_combo(sel_ids)
        if not price:
            return None
        # Compute uncorrelated parlay price for comparison
        uncorr_dec = 1.0
        for l in c["legs"]:
            if l["oddsDecimal"]:
                uncorr_dec *= l["oddsDecimal"]
        return {
            "title": c["title"],
            "thesis": c["thesis"],
            "legs": [{
                "player": l["player"],
                "description": f"{l['displayPoints']} {l['subcategory'] or l['marketName']}",
                "selectionId": l["selectionId"],
                "oddsAmerican": l["oddsAmerican"],
                "oddsDecimal": l["oddsDecimal"],
            } for l in c["legs"]],
            "sgpOdds": price["sgpOdds"],
            "sgpDecimal": price["sgpDecimal"],
            "uncorrelatedOdds": _american_from_decimal(uncorr_dec),
            "uncorrelatedDecimal": uncorr_dec,
            "correlationFactor": price["sgpDecimal"] / uncorr_dec if uncorr_dec else None,
        }

    priced = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_price_candidate, c) for c in candidates]
        for f in as_completed(futs):
            try:
                result = f.result()
                if result:
                    priced.append(result)
            except Exception:
                pass

    # Sort by correlation factor (DK-loosened SGPs first — usually more interesting)
    priced.sort(key=lambda x: -(x.get("correlationFactor") or 0))

    return {
        "eventId": event_id,
        "pitchers": [{"name": p["name"], "line": p["line"]} for p in pitchers],
        "sgps": priced,
    }


def _normalize_name(n):
    """Normalize a player name for fuzzy matching."""
    n = (n or "").lower().strip()
    n = re.sub(r"[^a-z\s]", "", n)
    return " ".join(n.split())


def _pitcher_matches(name_a, name_b):
    """Fuzzy match two pitcher names. Handles 'Kris Bubic' vs 'K Bubic' vs 'kris bubic'."""
    a = _normalize_name(name_a)
    b = _normalize_name(name_b)
    if not a or not b:
        return False
    if a == b:
        return True
    a_parts = a.split()
    b_parts = b.split()
    if len(a_parts) >= 2 and len(b_parts) >= 2:
        # Last name match + first-letter match
        if a_parts[-1] == b_parts[-1] and a_parts[0][0] == b_parts[0][0]:
            return True
    # Last name only match (some OCR might drop first name)
    if len(a_parts) >= 1 and len(b_parts) >= 1 and a_parts[-1] == b_parts[-1] and len(a_parts[-1]) > 3:
        return True
    return False


def _stat_matches_market(stat_str, market_blob):
    """Check if the leg's stat type matches the DK market's name/subcategory."""
    stat_lower = stat_str.lower()
    # Strip "strikeout" from market so it doesn't pollute the outs check
    # (strikeouts contains "out" as a substring)
    market_lower = market_blob.lower()
    market_no_so = market_lower.replace("strikeouts", "").replace("strikeout", "")

    if "earned run" in stat_lower:
        return "earned run" in market_lower
    if "hits allowed" in stat_lower or stat_lower == "hits":
        return ("hits allowed" in market_lower or "hits" in market_lower) and \
               ("pitch" in market_lower or "allow" in market_lower or "pitcher" in market_lower)
    if "walk" in stat_lower:
        return "walk" in market_lower
    if "strikeout" in stat_lower:
        return "strikeout" in market_lower
    if "out" in stat_lower:
        # Any "outs" market — Pitching Outs, Outs Recorded, Total Outs, or just Outs
        # (strikeouts already filtered out above)
        return "outs" in market_no_so
    return False


def _stat_cat(leg):
    """Short stat category for a canonical leg string, used to canonicalize
    2-leg combo ordering so ("Over 4.5 SO", "Under 2.5 ER") always renders
    with the same leg first regardless of matched[] insertion order.
    Alphabetical over: BB < ER < H < OUTS < SO."""
    s = leg or ""
    if "Strikeout" in s:
        return "SO"
    if "Earned Run" in s:
        return "ER"
    if "Walk" in s:
        return "BB"
    if "Hit" in s:
        return "H"
    if "Out" in s:
        return "OUTS"
    return "ZZZ"


def _selection_direction(outcome_type):
    """Resolve a DK selection's outcomeType to 'Over' / 'Under', handling
    milestone selections whose outcomeType may be literal text like '5+' or
    '4 or Fewer' instead of the plain word."""
    if not outcome_type:
        return None
    ot = str(outcome_type).strip()
    if ot in ("Over", "Under"):
        return ot
    lo = ot.lower()
    if "fewer" in lo or "or less" in lo or "at most" in lo:
        return "Under"
    if "or more" in lo or "at least" in lo or ot.endswith("+"):
        return "Over"
    return None


def _match_leg_to_dk(leg, props, pitcher):
    """Given an OCR'd leg (dict with 'leg', 'avg_fv'), find the matching DK selection ID."""
    leg_str = leg.get("leg", "")
    # Parse: "Over 5.5 Strikeouts" → direction, line, stat
    parts = leg_str.split(None, 2)
    if len(parts) < 3:
        return None
    direction, line_str, stat_str = parts[0], parts[1], parts[2]
    try:
        line = float(line_str)
    except (ValueError, TypeError):
        return None

    # DK exposes pitcher Strikeouts / Hits Allowed as milestone markets (5+,
    # 4 or Fewer, …) as well as O/U markets. Over X.5 is equivalent to the
    # "X+1 or more" milestone; Under X.5 is equivalent to "X or fewer". So we
    # accept both the exact .5 line and the integer milestone threshold.
    if direction == "Over":
        accept_points = (line, line + 0.5)
    elif direction == "Under":
        accept_points = (line, line - 0.5)
    else:
        accept_points = (line,)

    for p in props:
        if not p.get("isPitcherProp"):
            continue
        if not _pitcher_matches(pitcher, p.get("player", "")):
            continue
        if _selection_direction(p.get("outcomeType")) != direction:
            continue
        pts = p.get("points")
        if pts is None or pts not in accept_points:
            continue
        blob = (p.get("marketName", "") + " " + p.get("subcategory", "") + " " + p.get("marketType", ""))
        if _stat_matches_market(stat_str, blob):
            return p.get("selectionId")
    return None


def _stat_matches_batter_market(stat_str, market_blob):
    """Batter version of _stat_matches_market. Caller has already scoped
    `market_blob` to a batter prop (via batter_only subcat filter), so we
    only need to disambiguate within batter stats. Stat strings here are
    the canonical leg labels emitted by the FV-sheet OCR normalizer:
    Hits, Runs, RBIs, Home Runs, Total Bases, Walks, Stolen Bases,
    Singles, Doubles, Triples."""
    s = (stat_str or "").lower().strip()
    m = (market_blob or "").lower()

    # Order matters: more specific stats first so "Total Bases" doesn't
    # collide with the bare "bases" in "Stolen Bases", and "Home Runs"
    # doesn't collide with plain "Runs".
    if "total base" in s or s == "tb":
        return "total base" in m
    if "home run" in s or s == "hr":
        return "home run" in m
    if "stolen base" in s or s == "sb":
        return "stolen base" in m
    if "single" in s or s == "1b":
        return "single" in m
    if "double" in s or s == "2b":
        return "double" in m
    if "triple" in s or s == "3b":
        return "triple" in m
    if "rbi" in s:
        return "rbi" in m
    if "walk" in s or s == "bb":
        return "walk" in m
    if s == "runs" or s == "r":
        # Plain runs — must NOT be Home Runs / RBIs (caller-side stat
        # already excluded those above; market side may still mention
        # "Home Runs" so guard here).
        return ("runs" in m) and ("home run" not in m) and ("rbi" not in m)
    if s == "hits" or s == "h":
        # Plain batter Hits market. The pitcher Hits-Allowed disambiguation
        # is upstream (subcat filter) — within batter scope, "hits" is hits.
        return "hits" in m
    return False


def _match_leg_to_dk_batter(leg_str, props, player):
    """Batter analog of _match_leg_to_dk. Same .5 O/U ↔ integer-milestone
    equivalence as the pitcher path: Over 0.5 Hits ≡ "1+ Hits"; Under 1.5
    Total Bases ≡ "1 or Fewer Total Bases".

    Returns a dict { selection_id, direction, points, stat_str,
    over_american, under_american, market_blob } or None when the primary
    leg can't be matched. over_american / under_american are ints when
    DK offers that side at the matched threshold (used by hybrid-mode
    no-vig), else None. Callers expecting just the legacy selection-id
    string should read `.selection_id` off the dict.

    Hybrid mode (commit plan #1) needs BOTH sides of the matched
    threshold to compute no-vig fair probability on the missing-FV leg,
    so we do the opposite-direction lookup here once and cache both
    onto the return dict rather than scanning props[] twice downstream."""
    parts = (leg_str or "").split(None, 2)
    if len(parts) < 3:
        return None
    direction, line_str, stat_str = parts[0], parts[1], parts[2]
    try:
        line = float(line_str)
    except (ValueError, TypeError):
        return None

    if direction == "Over":
        accept_points = (line, line + 0.5)
    elif direction == "Under":
        accept_points = (line, line - 0.5)
    else:
        accept_points = (line,)

    def _american_of(sel):
        """Parse '+250'/'−140'/'140' into an int, or None."""
        raw = (sel or {}).get("oddsAmerican") or ""
        if not raw:
            return None
        s = str(raw).replace("−", "-").replace("+", "").strip()
        try:
            return int(s)
        except (ValueError, TypeError):
            return None

    # Two-pass match. DK offers most batter stats in BOTH a milestone
    # form ("1+ Hits" at points=1) and a two-way O/U form ("Hits O/U"
    # Over 0.5 at points=0.5). For hybrid-mode no-vig we need the
    # two-way variant so the opposite-direction lookup succeeds. Prefer
    # subcategories containing "O/U" on the first pass; fall back to any
    # match on the second. Full-FV candidates don't care which flavor
    # gets picked — any priced selectionId works for calculateBets.
    def _scan(prefer_two_way):
        for p in props:
            if not p.get("isBatterProp"):
                continue
            if not _pitcher_matches(player, p.get("player", "")):
                continue
            if _selection_direction(p.get("outcomeType")) != direction:
                continue
            pts = p.get("points")
            if pts is None or pts not in accept_points:
                continue
            subcat = (p.get("subcategory") or "")
            if prefer_two_way and ("o/u" not in subcat.lower()):
                continue
            blob = (p.get("marketName", "") + " " + subcat + " " + p.get("marketType", ""))
            if _stat_matches_batter_market(stat_str, blob):
                return p
        return None

    matched = _scan(prefer_two_way=True) or _scan(prefer_two_way=False)

    if not matched:
        return None

    # Find the opposite-direction selection at the SAME matched points
    # value. Must be same player + same stat-market blob + same threshold
    # + same subcategory (so we don't cross-match a milestone 2+ partner
    # against an O/U Over 1.5 primary). If DK only priced one side (common
    # on milestone-only markets), this lookup returns None and the
    # caller's hybrid-mode skip path kicks in.
    opposite_dir = "Under" if direction == "Over" else "Over"
    matched_pts = matched.get("points")
    matched_subcat = matched.get("subcategory") or ""
    opp = None
    for p in props:
        if not p.get("isBatterProp"):
            continue
        if not _pitcher_matches(player, p.get("player", "")):
            continue
        if _selection_direction(p.get("outcomeType")) != opposite_dir:
            continue
        if p.get("points") != matched_pts:
            continue
        if (p.get("subcategory") or "") != matched_subcat:
            continue
        blob = (p.get("marketName", "") + " " + p.get("subcategory", "") + " " + p.get("marketType", ""))
        if _stat_matches_batter_market(stat_str, blob):
            opp = p
            break

    matched_am = _american_of(matched)
    opp_am = _american_of(opp) if opp else None
    over_am  = matched_am if direction == "Over"  else opp_am
    under_am = matched_am if direction == "Under" else opp_am

    return {
        "selection_id":     matched.get("selectionId"),
        "direction":        direction,
        "points":           matched_pts,
        "stat_str":         stat_str,
        "over_american":    over_am,
        "under_american":   under_am,
        "opposite_selection_id": (opp.get("selectionId") if opp else None),
    }


def _normalize_team(name):
    """Normalize a team string to a comparable token. Phase-1 teammate data
    uses full city + nickname ("San Francisco Giants"); DK exposes the same
    under homeTeam/awayTeam. Lowercase + strip non-alpha covers the "St."
    vs "Saint" / "A's" vs "As" edge cases."""
    n = (name or "").lower()
    n = re.sub(r"[^a-z0-9 ]+", "", n)
    return " ".join(n.split())


# Tokens that are city prefixes (NOT part of the nickname). Includes both
# full city words ("kansas", "city", "los", "angeles") and DK's 2-3 letter
# city codes ("kc", "laa", "wsh"). Anything not in this set is treated as a
# nickname token. Lets us treat "Kansas City Royals" / "KC Royals" / "Royals"
# as the same team without an alias table.
_TEAM_CITY_TOKENS = {
    "arizona","atlanta","baltimore","boston","chicago","cincinnati",
    "cleveland","colorado","detroit","houston","kansas","city","la",
    "los","angeles","miami","milwaukee","minnesota","new","york",
    "oakland","philadelphia","pittsburgh","san","diego","francisco",
    "seattle","st","saint","louis","tampa","bay","texas","toronto",
    "washington",
    "ari","atl","bal","bos","chc","cws","cin","cle","col","det",
    "hou","kc","laa","lad","mia","mil","min","nym","nyy","ath","oak",
    "phi","pit","sd","sf","sea","stl","tb","tex","tor","wsh","was",
}


def _team_nickname(name):
    """Extract a comparable nickname from a team string. Strips city
    prefix (full words or DK short codes) and returns the remainder.
    Examples:
      'Kansas City Royals' -> 'royals'
      'KC Royals'           -> 'royals'
      'Boston Red Sox'      -> 'red sox'
      'BOS Red Sox'         -> 'red sox'
      'Athletics'           -> 'athletics'
      'Diamondbacks'        -> 'diamondbacks'
    """
    n = _normalize_team(name)
    if not n:
        return ""
    tokens = n.split()
    for i, t in enumerate(tokens):
        if t not in _TEAM_CITY_TOKENS:
            return " ".join(tokens[i:])
    return tokens[-1]  # all-city fallback (shouldn't happen for real team names)


def _team_in_event(team_str, event):
    """Match a Phase-1 team string against a DK event. Returns 'home',
    'away', or None. Compares on nickname so "Kansas City Royals" vs
    "KC Royals" / "Royals" all collapse to 'royals'."""
    nick = _team_nickname(team_str)
    if not nick:
        return None
    home_full_nick = _team_nickname(event.get("homeTeam"))
    away_full_nick = _team_nickname(event.get("awayTeam"))
    home_short_nick = _team_nickname(event.get("homeShort"))
    away_short_nick = _team_nickname(event.get("awayShort"))
    if nick and nick in (home_full_nick, home_short_nick):
        return "home"
    if nick and nick in (away_full_nick, away_short_nick):
        return "away"
    return None


def find_sgps_teammate(payload):
    """Price a batch of teammate 2-leg SGP candidates against DraftKings.

    Input shape (passed via stdin JSON):
      {
        "candidates": [
          {
            "id": "<arbitrary frontend handle>",     # echoed back; used to align response rows
            "team": "Kansas City Royals",            # full team name from Phase-1 teammate dataset
            "player_a": "Bobby Witt Jr.",
            "leg_a":    "Over 0.5 Hits",             # canonical leg string (same shape as pitcher side)
            "player_b": "Salvador Perez",
            "leg_b":    "Over 0.5 RBIs"
          },
          ...
        ]
      }

    Output:
      {
        "results": [
          {
            "id": ...,
            "event_id": "...",
            "game_name": "...",
            "matched": true|false,
            "missing": ["player_a leg_a", ...],   # only present when matched=false
            "dk_odds": "+350",                     # only present when matched=true
            "dk_decimal": 4.5,
            "selection_a": "...",
            "selection_b": "..."
          }, ...
        ],
        "events_scanned": [eid, ...],
        "team_event_map": { "<team>": eid|null },
        "truncated": bool
      }

    Invariants:
      - Each unique team is scanned exactly once (via batter_only get_markets).
      - Each unique (player, leg) is matched to a selectionId exactly once.
      - Each unique unordered (sel_a, sel_b) pair is priced at most once;
        candidates that map to the same pair share the price.
      - Soft 110s deadline mirrors find_sgps; whatever is missing comes back
        as matched=false rather than failing the whole request.
    """
    from itertools import combinations  # noqa: F401  (kept for future expansion)
    import concurrent.futures

    pricing_deadline = _time.monotonic() + 110.0
    truncated = False

    candidates = (payload or {}).get("candidates", []) or []
    if not isinstance(candidates, list) or not candidates:
        return {"error": "candidates array required"}

    # Dedupe teams.
    needed_teams = []
    seen_teams = set()
    for c in candidates:
        t = c.get("team")
        if not t:
            continue
        nt = _normalize_team(t)
        if nt in seen_teams:
            continue
        seen_teams.add(nt)
        needed_teams.append(t)

    # Resolve team → DK event.
    try:
        games_data = get_games()
    except Exception as e:
        return {"error": f"DK games endpoint unavailable: {e}. Try again in a moment."}
    events = [e for e in games_data["events"] if e.get("hasSGP")]

    team_event_map = {}
    for t in needed_teams:
        chosen = None
        for e in events:
            if _team_in_event(t, e):
                chosen = e["id"]
                break
        team_event_map[t] = chosen

    needed_event_ids = sorted({eid for eid in team_event_map.values() if eid})

    # Scan markets per event in parallel. Same low max_workers (and the
    # nested batter_only get_markets uses its own workers=2) so effective
    # concurrency against DK stays at 4 — the level pitcher find_sgps
    # established as safe against Akamai's 403 cascade.
    event_markets = {}
    def scan(eid):
        try:
            md = get_markets(eid, batter_only=True)
            return eid, md
        except Exception as ex:
            sys.stderr.write(f"dk_api: teammate event {eid} scan failed: {ex}\n")
            return eid, None

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(scan, eid): eid for eid in needed_event_ids}
        for fut in as_completed(futs):
            eid, md = fut.result()
            if md is not None:
                event_markets[eid] = md

    # Match each unique (event, player, leg) to a DK match-record exactly
    # once. match-record is a dict with selection_id + per-leg over/under
    # American odds (needed by the client for hybrid-mode no-vig on a
    # missing-FV leg). See _match_leg_to_dk_batter.
    leg_match_cache = {}  # key: (eid, player_norm, leg_str) -> match-record | None

    def match_leg(eid, player, leg_str):
        if not eid or eid not in event_markets:
            return None
        key = (eid, _normalize_name(player), leg_str)
        if key in leg_match_cache:
            return leg_match_cache[key]
        m = _match_leg_to_dk_batter(leg_str, event_markets[eid]["props"], player)
        leg_match_cache[key] = m
        return m

    # Resolve every candidate to a (sel_a, sel_b) pair + both legs'
    # match-records so the response can carry per-leg over/under prices.
    resolved = []  # parallel to `candidates`
    for c in candidates:
        team = c.get("team")
        eid = team_event_map.get(team)
        game_info = next((e for e in events if e["id"] == eid), {}) if eid else {}
        ma = match_leg(eid, c.get("player_a"), c.get("leg_a")) if eid else None
        mb = match_leg(eid, c.get("player_b"), c.get("leg_b")) if eid else None
        sa = ma["selection_id"] if ma else None
        sb = mb["selection_id"] if mb else None
        missing = []
        if not eid:
            missing.append(f"team:{team}")
        else:
            if not sa:
                missing.append(f"{c.get('player_a')} :: {c.get('leg_a')}")
            if not sb:
                missing.append(f"{c.get('player_b')} :: {c.get('leg_b')}")
        resolved.append({
            "id": c.get("id"),
            "event_id": eid,
            "game_name": game_info.get("name", "") if eid else "",
            "selection_a": sa,
            "selection_b": sb,
            "match_a": ma,
            "match_b": mb,
            "missing": missing,
        })

    # Dedupe pricing on the unordered selection pair.
    price_cache = {}  # key: frozenset({sa, sb}) -> price dict|None|"pending"
    pricing_jobs = []
    for r in resolved:
        if not r["selection_a"] or not r["selection_b"]:
            continue
        if r["selection_a"] == r["selection_b"]:
            continue  # same selection used twice would fail calculateBets anyway
        key = frozenset({r["selection_a"], r["selection_b"]})
        if key in price_cache:
            continue
        price_cache[key] = "pending"
        pricing_jobs.append((key, r["selection_a"], r["selection_b"]))

    def price_one(key, sa, sb):
        return key, _price_combo([sa, sb])

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(price_one, *job) for job in pricing_jobs]
        remaining = max(0.5, pricing_deadline - _time.monotonic())
        try:
            for f in as_completed(futs, timeout=remaining):
                try:
                    key, price = f.result()
                    price_cache[key] = price  # may be None on incompat / DK error
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            truncated = True
            for f in futs:
                f.cancel()

    # Build response rows. Per-leg over/under American odds surface on
    # every matched result regardless of hybrid vs full-FV usage — the
    # client decides which prices it needs based on its own FV coverage.
    # Carrying both sides of both legs costs ~16 bytes per candidate in
    # the JSON payload; trivially small next to the SGP pricing calls
    # this function already makes.
    results = []
    for src, r in zip(candidates, resolved):
        ma = r.get("match_a") or {}
        mb = r.get("match_b") or {}
        out = {
            "id": r["id"],
            "event_id": r["event_id"],
            "game_name": r["game_name"],
            "team": src.get("team"),
            "player_a": src.get("player_a"),
            "leg_a": src.get("leg_a"),
            "player_b": src.get("player_b"),
            "leg_b": src.get("leg_b"),
            "selection_a": r["selection_a"],
            "selection_b": r["selection_b"],
            # Per-leg DK prices (for hybrid-mode no-vig). None when the
            # matched prop had no opposite-direction selection priced on
            # DK — caller's hybrid path then skips the candidate.
            "leg_a_over_american":  ma.get("over_american"),
            "leg_a_under_american": ma.get("under_american"),
            "leg_b_over_american":  mb.get("over_american"),
            "leg_b_under_american": mb.get("under_american"),
        }
        if r["missing"]:
            out["matched"] = False
            out["missing"] = r["missing"]
            results.append(out)
            continue
        key = frozenset({r["selection_a"], r["selection_b"]})
        price = price_cache.get(key)
        if price in (None, "pending"):
            out["matched"] = False
            out["missing"] = ["dk:price_unavailable"]
            results.append(out)
            continue
        out["matched"] = True
        out["dk_odds"] = price["sgpOdds"]
        out["dk_decimal"] = price["sgpDecimal"]
        results.append(out)

    response = {
        "results": results,
        "events_scanned": needed_event_ids,
        "team_event_map": team_event_map,
    }
    if truncated:
        response["truncated"] = True
    return response


def _stat_matches_market_nba(stat_str, market_blob):
    """NBA stat → market blob matcher. Caller has already scoped
    `market_blob` to an NBA player prop via the nba_only subcat filter
    + isNbaProp check, so this only disambiguates within the 4 supported
    stats. Order matters: 3-Pointers Made first so a bare "points" match
    doesn't grab 3-point markets. Canonical stat_str values come from the
    nbaEvTab.js enumerator: Points, Rebounds, Assists, 3-Pointers Made."""
    s = (stat_str or "").lower().strip()
    m = (market_blob or "").lower()
    # 3-Pointers Made has many DK spellings. Check for any of them first.
    if "3-pointer" in s or "3-point" in s or "three" in s or s == "3pm":
        return ("3-point" in m or "3 point" in m or "threes" in m
                or "pointers" in m or "3pt" in m or "3 pt" in m)
    if s == "points":
        # Plain Points — must NOT be 3-Point, PRA, or a combo market. We
        # exclude "rebound"/"assist" substrings because DK sometimes
        # emits combo markets (PRA, PR) under Points subcats.
        return ("point" in m
                and "3-point" not in m and "3 point" not in m
                and "three" not in m and "pointers" not in m
                and "rebound" not in m and "assist" not in m)
    if s == "rebounds":
        return "rebound" in m and "assist" not in m and "point" not in m
    if s == "assists":
        return "assist" in m and "rebound" not in m and "point" not in m
    return False


def _match_leg_to_dk_nba(player, prop, side, line, props):
    """NBA analog of _match_leg_to_dk_batter. Takes structured inputs
    directly — nbaEvTab.js emits (player, prop, side, line) fields, not
    the "Over 0.5 Hits" composite string the MLB paths parse, so
    building a string and re-parsing would be a needless round-trip.

    Line matching is exact (points == line). NBA doesn't use the
    .5 ↔ milestone equivalence MLB has; line-approximation already
    happened upstream in nbaEvTab.js's line-ignorant enumerator (the
    candidate here has the FV line; the caller wants DK's selectionId
    at that exact line, if DK offers it).

    Returns a dict { selection_id, direction, points, prop,
    over_american, under_american, opposite_selection_id } when DK has
    the leg + an opposite-direction partner at the same points/subcat.
    Returns None if DK doesn't offer the primary leg. The opposite-
    direction side may still be absent (opp_american=None) — the
    caller's no-vig path handles that."""
    if not prop or side not in ("over", "under") or line is None:
        return None
    try:
        line = float(line)
    except (ValueError, TypeError):
        return None
    direction = "Over" if side == "over" else "Under"

    def _american_of(sel):
        raw = (sel or {}).get("oddsAmerican") or ""
        if not raw:
            return None
        t = str(raw).replace("−", "-").replace("+", "").strip()
        try:
            return int(t)
        except (ValueError, TypeError):
            return None

    matched = None
    for p in props:
        if not p.get("isNbaProp"):
            continue
        if not _pitcher_matches(player, p.get("player", "")):
            continue
        if _selection_direction(p.get("outcomeType")) != direction:
            continue
        pts = p.get("points")
        try:
            if pts is None or float(pts) != line:
                continue
        except (ValueError, TypeError):
            continue
        blob = (p.get("marketName", "") + " " + p.get("subcategory", "") + " " + p.get("marketType", ""))
        if _stat_matches_market_nba(prop, blob):
            matched = p
            break
    if not matched:
        return None

    # Opposite-direction lookup at the same (points, subcat) for no-vig.
    opposite_dir = "Under" if direction == "Over" else "Over"
    matched_pts = matched.get("points")
    matched_subcat = matched.get("subcategory") or ""
    opp = None
    for p in props:
        if not p.get("isNbaProp"):
            continue
        if not _pitcher_matches(player, p.get("player", "")):
            continue
        if _selection_direction(p.get("outcomeType")) != opposite_dir:
            continue
        if p.get("points") != matched_pts:
            continue
        if (p.get("subcategory") or "") != matched_subcat:
            continue
        blob = (p.get("marketName", "") + " " + p.get("subcategory", "") + " " + p.get("marketType", ""))
        if _stat_matches_market_nba(prop, blob):
            opp = p
            break

    matched_am = _american_of(matched)
    opp_am = _american_of(opp) if opp else None
    over_am  = matched_am if direction == "Over"  else opp_am
    under_am = matched_am if direction == "Under" else opp_am
    return {
        "selection_id":     matched.get("selectionId"),
        "direction":        direction,
        "points":           matched_pts,
        "prop":             prop,
        "over_american":    over_am,
        "under_american":   under_am,
        "opposite_selection_id": (opp.get("selectionId") if opp else None),
    }


def find_sgps_nba(payload):
    """Price a batch of NBA same-player 2-leg SGP candidates against DK.

    Input shape (passed via stdin JSON):
      {
        "candidates": [
          {
            "id": "<frontend candidate handle>",   # echoed back
            "player": "Donovan Mitchell",
            "game":   "CLE@BOS",                   # optional, tiebreaker
            "team":   "CLE",                       # optional, tiebreaker
            "prop1":  "Points", "side1": "over", "line1": 27.5,
            "prop2":  "Rebounds", "side2": "over", "line2": 4.5
          }, ...
        ]
      }

    Output (mirrors find_sgps_teammate shape so nbaEvTab.js can reuse
    the same merge logic):
      {
        "results": [
          { "id", "event_id", "game_name", "matched": bool,
            "missing": [...],                   # when matched=false
            "dk_odds": "+275", "dk_decimal": 3.75,
            "selection_1", "selection_2",
            "leg_1_over_american", "leg_1_under_american",
            "leg_2_over_american", "leg_2_under_american"
          }, ...
        ],
        "events_scanned": [...]
      }

    Edit 1 (this commit): stub. Returns matched=false missing="nba dk
    pricing not wired yet (Edits 2-4)" for every candidate so the
    client can wire its merge path now without waiting for the
    full pricing implementation. Edits 2-4 replace this with the
    real matcher + pricer.
    """
    candidates = (payload or {}).get("candidates", []) or []
    if not isinstance(candidates, list) or not candidates:
        return {"error": "candidates array required"}
    results = []
    for c in candidates:
        results.append({
            "id": c.get("id"),
            "event_id": None,
            "game_name": c.get("game") or "",
            "matched": False,
            "missing": ["nba dk pricing not wired yet (Phase 4 follow-up Edits 2-4)"],
            "player": c.get("player"),
            "prop1": c.get("prop1"), "side1": c.get("side1"), "line1": c.get("line1"),
            "prop2": c.get("prop2"), "side2": c.get("side2"), "line2": c.get("line2"),
        })
    return {"results": results, "events_scanned": [], "stub": True}


def find_sgps(legs):
    """Given OCR'd legs, auto-match them to DK selections, enumerate 2-leg combos,
    and return DK-priced SGPs. Frontend computes FV and EV."""
    from itertools import combinations
    import concurrent.futures

    # Soft deadline: return partial results before Node's spawn timeout SIGTERMs us.
    pricing_deadline = _time.monotonic() + 110.0
    truncated = False

    # Group by pitcher
    by_pitcher = {}
    for l in legs:
        by_pitcher.setdefault(l.get("pitcher", ""), []).append(l)
    by_pitcher.pop("", None)

    if not by_pitcher:
        return {"error": "No pitcher legs provided"}

    # Fetch games list (graceful on DK rate-limit failure so the subprocess
    # doesn't exit 1 and surface as an opaque "dk_api.py exited with code 1"
    # to the frontend).
    try:
        games_data = get_games()
    except Exception as e:
        return {"error": f"DK games endpoint unavailable: {e}. Try again in a moment."}
    events = [e for e in games_data["events"] if e.get("hasSGP")]

    # Scan games in parallel to find each pitcher's event
    event_markets = {}
    pitcher_events = {}
    unfound = set(by_pitcher.keys())

    def scan(eid):
        try:
            md = get_markets(eid, pitcher_only=True)
            return eid, md
        except Exception:
            return eid, None

    # max_workers=2: each per-event scan itself fans out 2 subcat workers, so
    # effective concurrency against DK is 4. Anything higher triggers Akamai's
    # 403 cascade and the whole find-sgps call ends up retrying through a block.
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(scan, e["id"]): e["id"] for e in events[:15]}
        for fut in as_completed(futs):
            eid, md = fut.result()
            if md is None:
                continue
            event_markets[eid] = md
            for p in md["props"]:
                if not p.get("isPitcherProp"):
                    continue
                player = p.get("player", "")
                if not player:
                    continue
                for pitcher in list(unfound):
                    if _pitcher_matches(pitcher, player):
                        pitcher_events[pitcher] = eid
                        unfound.discard(pitcher)
            if not unfound:
                # Cancel remaining futures
                for f in futs:
                    f.cancel()
                break

    results = {}
    for pitcher, plegs in by_pitcher.items():
        eid = pitcher_events.get(pitcher)
        game_info = next((e for e in events if e["id"] == eid), {}) if eid else {}
        if not eid or eid not in event_markets:
            results[pitcher] = {"error": "Pitcher not found in today's DK games"}
            continue

        md = event_markets[eid]
        matched = []
        unmatched = []
        for l in plegs:
            dk_id = _match_leg_to_dk(l, md["props"], pitcher)
            if dk_id:
                matched.append({
                    "leg": l.get("leg"),
                    "avg_fv": l.get("avg_fv"),
                    "_fv_suspicious": bool(l.get("_fv_suspicious", False)),
                    "dk_selection_id": dk_id,
                })
            else:
                unmatched.append(l.get("leg"))

        base = {
            "event_id": eid,
            "game_name": game_info.get("name", ""),
            "start_date": game_info.get("startDate", ""),
            "matched_legs": matched,
            "unmatched_legs": unmatched,
        }

        if len(matched) < 2:
            results[pitcher] = {**base, "combos_2": [],
                               "warning": f"Need 2+ matched legs ({len(matched)}/{len(plegs)} matched to DK)"}
            continue

        if _time.monotonic() >= pricing_deadline:
            truncated = True
            results[pitcher] = {**base, "combos_2": [],
                               "warning": "Skipped: pricing time budget exceeded. Try again."}
            continue

        # Enumerate 2-leg combos (indices into matched[]).
        # combinations() gives canonical (i,j) with i<j but matched[] order
        # follows the OCR row order, so the same logical combo can render
        # "ER x Outs" on one sheet and "Outs x ER" on another. Canonicalize
        # by stat category (alphabetical) so the leg pair is stable.
        combos_by_size = {2: []}
        for combo in combinations(range(len(matched)), 2):
            a, b = combo
            if _stat_cat(matched[a].get("leg")) > _stat_cat(matched[b].get("leg")):
                a, b = b, a
            combos_by_size[2].append([a, b])

        # Price every combo in parallel
        all_combos_flat = [(2, idx, indices) for idx, indices in enumerate(combos_by_size[2])]

        def price_one(size, idx, indices):
            sel_ids = [matched[i]["dk_selection_id"] for i in indices]
            price = _price_combo(sel_ids)
            return size, idx, indices, price

        priced_combos = {2: {}}
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(price_one, *c) for c in all_combos_flat]
            remaining = max(0.5, pricing_deadline - _time.monotonic())
            try:
                for f in as_completed(futs, timeout=remaining):
                    try:
                        size, idx, indices, price = f.result()
                        if price:
                            priced_combos[size][tuple(indices)] = price
                    except Exception:
                        pass
            except concurrent.futures.TimeoutError:
                truncated = True
                for f in futs:
                    f.cancel()

        combos_2 = []
        for indices in combos_by_size[2]:
            price = priced_combos[2].get(tuple(indices))
            if not price:
                continue
            combos_2.append({
                "leg_indices": indices,
                "dk_odds": price["sgpOdds"],
                "dk_decimal": price["sgpDecimal"],
            })

        results[pitcher] = {**base, "combos_2": combos_2}

    out = {"pitchers": results}
    if truncated:
        out["truncated"] = True
    return out


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

    bets = data.get("bets", [])
    bet = next((b for b in bets if b.get("trueOdds") and len(b.get("selectionsMapped", [])) >= 2), None)
    if not bet:
        return {"error": "No valid SGP price returned"}

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
        print(json.dumps({"error": "Usage: dk_api.py <games|markets|featured|price> [args]"}))
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        if cmd == "games":
            result = get_games()
        elif cmd == "markets" and len(sys.argv) >= 3:
            result = get_markets(sys.argv[2])
        elif cmd == "featured" and len(sys.argv) >= 3:
            result = get_featured(sys.argv[2])
        elif cmd == "find-sgps":
            stdin_data = sys.stdin.read().strip()
            legs = json.loads(stdin_data) if stdin_data else []
            result = find_sgps(legs)
        elif cmd == "find-sgps-teammate":
            stdin_data = sys.stdin.read().strip()
            payload = json.loads(stdin_data) if stdin_data else {}
            result = find_sgps_teammate(payload)
        elif cmd == "find-sgps-nba":
            stdin_data = sys.stdin.read().strip()
            payload = json.loads(stdin_data) if stdin_data else {}
            result = find_sgps_nba(payload)
        elif cmd == "price":
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
