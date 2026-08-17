#!/usr/bin/env python3
"""Fetch 2026 MLB starting-pitcher box scores from ESPN into a supplement file.

The 2026 xlsx season feed (05-15-2026-mlb-season-player-feed.xlsx) ends on
2026-05-15. This script pulls every completed regular-season game from ESPN's
public site API for a date window (default 2026-05-16 .. today) and writes the
starting pitcher lines to espn-2026-pitcher-supplement.json at the repo root,
using the same record schema as public/data/pitchers_YYYY.json.

build_pitcher_data.py merges this supplement into pitchers_2026.json and
dedupes against the xlsx rows by (pitcher name, date), so re-running either
script never double-counts a start. This script itself dedupes by ESPN event
id, so overlapping date windows across runs are also safe.

Field notes vs the xlsx feed:
  * p / t / o are accent-stripped to match the feed ("Jesus Luzardo").
  * pid / h (throwing hand) are reused from existing pitchers_YYYY.json rows
    by name; new pitchers fall back to the ESPN athlete id and the ESPN core
    API's throws.abbreviation.
  * bf / gb / fb are not in ESPN box scores -> null. The correlation builds
    only use k, er, bb, h_allowed and ip (outs), so nothing downstream needs
    them.
  * qs is derived: outs >= 18 and er <= 3.

Usage:
    python3 scripts/fetch_espn_2026_pitchers.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "public" / "data"
OUT_PATH = ROOT / "espn-2026-pitcher-supplement.json"

# ESPN serves the same site-API payloads from several hosts and blocks them
# independently: site.api.espn.com started returning 403 to datacenter IPs
# (which killed this job on GitHub Actions), while site.web.api.espn.com and
# cdn.espn.com kept serving. So each endpoint lists its mirrors in preference
# order and fetch_mirrored() falls through on failure. The cdn.espn.com
# variants wrap the identical payload one level down — see unwrap().
SCOREBOARD_URLS = (
    "https://site.web.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
    "?dates={ymd}&limit=100",
    "https://cdn.espn.com/core/mlb/scoreboard?xhr=1&date={ymd}",
)
SUMMARY_URLS = (
    "https://site.web.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event={eid}",
    "https://cdn.espn.com/core/mlb/boxscore?xhr=1&gameId={eid}",
)
ATHLETE_URL = (
    "https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/athletes/{aid}"
)

DEFAULT_START = "2026-05-16"  # day after the xlsx feed's last covered date
REQUEST_PAUSE_S = 0.15


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def name_key(s: str) -> str:
    """Matching key: accent-stripped, lowercased, no periods, single spaces."""
    return " ".join(strip_accents(s).replace(".", "").lower().split())


def fetch_json(url: str, retries: int = 4) -> dict:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            # A blocked host or a missing event answers the same way every
            # time, so don't burn the backoff on it — let the caller fall
            # through to the next mirror immediately.
            if err.code in (403, 404, 451):
                raise RuntimeError(f"GET {url} refused: HTTP {err.code}") from err
            last_err = err
            time.sleep(2 ** attempt)
        except Exception as err:  # noqa: BLE001 - retry any transient failure
            last_err = err
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET {url} failed after {retries} tries: {last_err}")


def unwrap(payload: dict) -> dict:
    """Normalize a cdn.espn.com response to the site-API shape.

    cdn.espn.com returns the same objects the site API does, nested under a
    page-data wrapper: the scoreboard under content.sbData and the box score
    under gamepackageJSON. Site-API responses pass through untouched.
    """
    if "gamepackageJSON" in payload:
        return payload["gamepackageJSON"]
    sb_data = (payload.get("content") or {}).get("sbData")
    if sb_data is not None:
        return sb_data
    return payload


def fetch_mirrored(templates: tuple[str, ...], retries: int = 3, **fmt) -> dict:
    """Fetch the first mirror that answers, normalized to the site-API shape."""
    errors: list[str] = []
    for template in templates:
        url = template.format(**fmt)
        try:
            return unwrap(fetch_json(url, retries=retries))
        except Exception as err:  # noqa: BLE001 - try the next mirror
            errors.append(f"{url}: {err}")
    raise RuntimeError("all mirrors failed:\n  " + "\n  ".join(errors))


def load_known_pitchers() -> dict[str, dict]:
    """name_key -> {p, pid, h} from existing pitcher JSONs, latest year wins."""
    known: dict[str, dict] = {}
    for year in (2023, 2024, 2025, 2026):
        path = DATA_DIR / f"pitchers_{year}.json"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for r in json.load(f):
                name = r.get("p")
                if not name:
                    continue
                known[name_key(name)] = {"p": name, "pid": r.get("pid"), "h": r.get("h")}
    return known


def ip_to_outs(ip: float | None) -> int | None:
    if ip is None:
        return None
    whole = int(math.floor(ip))
    frac = round((ip - whole) * 10)
    if frac < 0 or frac > 2:
        return int(round(ip * 3))
    return whole * 3 + frac


def parse_float(s) -> float | None:
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


_hand_cache: dict[str, str | None] = {}


def fetch_hand(athlete_id: str) -> str | None:
    if athlete_id in _hand_cache:
        return _hand_cache[athlete_id]
    hand = None
    try:
        d = fetch_json(ATHLETE_URL.format(aid=athlete_id), retries=2)
        hand = (d.get("throws") or {}).get("abbreviation")
    except Exception:
        pass
    _hand_cache[athlete_id] = hand
    time.sleep(REQUEST_PAUSE_S)
    return hand


def extract_starters(event_id: str, game_date: str, known: dict[str, dict]) -> list[dict]:
    summary = fetch_mirrored(SUMMARY_URLS, eid=event_id)
    comp = (summary.get("header", {}).get("competitions") or [{}])[0]
    side_by_team: dict[str, str] = {}
    name_by_team: dict[str, str] = {}
    for c in comp.get("competitors", []):
        tid = str(c.get("team", {}).get("id"))
        side_by_team[tid] = c.get("homeAway", "")
        name_by_team[tid] = strip_accents(c.get("team", {}).get("displayName", ""))
    if len(name_by_team) != 2:
        return []

    records: list[dict] = []
    for teamblock in summary.get("boxscore", {}).get("players", []):
        tid = str(teamblock.get("team", {}).get("id"))
        team_name = name_by_team.get(tid, "")
        opp_name = next((n for t, n in name_by_team.items() if t != tid), "")
        venue = "Home" if side_by_team.get(tid) == "home" else "Road"
        for grp in teamblock.get("statistics", []):
            if grp.get("type") != "pitching" and grp.get("name") != "pitching":
                continue
            labels = grp.get("labels", [])
            idx = {lab: i for i, lab in enumerate(labels)}
            athletes = grp.get("athletes", [])
            # The starting pitcher is the first *actual pitcher* in the
            # pitching group (appearance order). Two ESPN traps here:
            # the `starter` flag is set on anyone who started the game,
            # including position players who mopped up a blowout (and
            # sometimes random relievers); and position-player pitchers
            # can be mis-sorted to the top of the list (e.g. RF Carlos
            # Cortes listed above the real starter in 401815762). Openers
            # (RP position) genuinely start games, so only non-pitcher
            # positions are skipped.
            starters = []
            for a in athletes:
                pos = (a.get("athlete", {}).get("position") or {})
                pos_name = str(pos.get("name") or "")
                pos_abbr = str(pos.get("abbreviation") or "")
                if pos_abbr in ("SP", "RP", "P") or "Pitcher" in pos_name:
                    starters = [a]
                    break
            if not starters and athletes:
                starters = [athletes[0]]
            for a in starters:
                ath = a.get("athlete", {})
                stats = a.get("stats", [])

                def stat(label: str) -> float | None:
                    i = idx.get(label)
                    return parse_float(stats[i]) if i is not None and i < len(stats) else None

                ip = stat("IP")
                if ip is None or ip <= 0:
                    continue
                decision = ""
                for note in a.get("notes") or []:
                    if note.get("type") == "pitchingDecision":
                        decision = (note.get("text") or "").strip().upper()
                er = stat("ER")
                outs = ip_to_outs(ip)
                display = strip_accents(ath.get("displayName", "")).strip()
                match = known.get(name_key(display))
                try:
                    espn_pid = int(ath.get("id"))
                except (TypeError, ValueError):
                    espn_pid = None
                records.append({
                    "gid": f"espn-{event_id}",
                    "d": game_date,
                    "pid": match["pid"] if match else espn_pid,
                    "p": match["p"] if match else display,
                    "t": team_name,
                    "o": opp_name,
                    "v": venue,
                    "h": (match or {}).get("h") or fetch_hand(str(ath.get("id"))),
                    "ip": ip,
                    "h_allowed": stat("H"),
                    "er": er,
                    "bb": stat("BB"),
                    "k": stat("K"),
                    "w": 1.0 if decision.startswith("W") else None,
                    "l": 1.0 if decision.startswith("L") else None,
                    "hra": stat("HR"),
                    "qs": 1.0 if (outs is not None and outs >= 18 and er is not None and er <= 3) else 0.0,
                    "bf": None,
                    "gb": None,
                    "fb": None,
                })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=date.today().isoformat())
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    known = load_known_pitchers()

    records: list[dict] = []
    seen_events: set[str] = set()
    day = start
    n_games = 0
    while day <= end:
        ymd = day.strftime("%Y%m%d")
        sb = fetch_mirrored(SCOREBOARD_URLS, ymd=ymd)
        for ev in sb.get("events", []):
            eid = str(ev.get("id"))
            status = ev.get("status", {}).get("type", {}).get("name")
            season_type = ev.get("season", {}).get("type")
            # Regular season only (type 2); skip in-progress/postponed games.
            if eid in seen_events or status != "STATUS_FINAL" or season_type != 2:
                continue
            seen_events.add(eid)
            recs = extract_starters(eid, day.isoformat(), known)
            records.extend(recs)
            n_games += 1
            time.sleep(REQUEST_PAUSE_S)
        print(f"  {day}: {len(sb.get('events', []))} events, cumulative starters={len(records)}")
        day += timedelta(days=1)
        time.sleep(REQUEST_PAUSE_S)

    records.sort(key=lambda r: (r["d"], r["gid"], r["p"]))
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, separators=(",", ":"))

    new_names = sorted({r["p"] for r in records if name_key(r["p"]) not in known})
    print("-" * 64)
    print(f"  window: {start} .. {end}   final games: {n_games}")
    print(f"  starter rows: {len(records)} -> {OUT_PATH.name}")
    print(f"  pitchers not in existing data ({len(new_names)}): {new_names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
