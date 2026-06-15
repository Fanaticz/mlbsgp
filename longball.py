#!/usr/bin/env python3
"""
LONG BALL JACKPOT MODEL  -  daily EV optimizer for Fanatics' $50K longest-HR promo.

The promo pays $50,000 in FanCash split EQUALLY among everyone who bet an anytime
HR on the player who hits the day's LONGEST home run. So your edge is NOT "who hits
the longest" alone -- it's:

      EV per $5 ticket  =  P(player hits the day's longest HR)  x  ( $50,000 / entries )

Two levers the public ignores:
  1. DISTANCE CEILING  -> use each hitter's top-5 avg HR distance (real Statcast), not rep.
  2. DILUTION          -> divide by how many other people are on him (live entry counts).

A 471-ft monster split 436 ways pays $115. A 450-ft bat split 9 ways pays $5,556.

------------------------------------------------------------------------------------
AUTOMATED ROUTINE (no manual uploads -- see run_today.py):
  * savant.py  pulls per-HR distances + the xHR leaderboard (cached daily in data/).
  * dk_odds.py pulls DraftKings anytime-HR odds (real P(HR) + a popularity proxy).
  * totals.py  pulls game O/U totals and builds the per-team carry (PARKS) automatically.
  * build_card() merges them; run_today.py prints the ranked card + floor + stack views.

The CONFIG block below is still honored as a manual override / fallback when a live
source is unreachable, but the daily path is fully automated.
------------------------------------------------------------------------------------
"""

import json
import math
import os
import sys

import pandas as pd

from names import to_display, norm_key

HERE = os.path.dirname(os.path.abspath(__file__))

# ====================================================================================
# CONFIG  --  fallbacks / manual overrides. The automated path (run_today.py) passes
# these in as arguments instead, sourced live from savant.py / dk_odds.py / totals.py.
# ====================================================================================

# --- data files (savant.py writes these; see README for the exact Savant URLs) ---
EVENT_CSV       = os.path.join(HERE, "data", "savant_event.csv")  # event-level HRs -> ceiling
LEADERBOARD_CSV = os.path.join(HERE, "data", "savant_lb.csv")     # season xHR leaderboard

# --- season progress: roughly how many team games have been played so far ---
# (used to turn season xHR into a per-game HR probability; ~67 in mid-June, ~110 in Aug)
GAMES_ELAPSED = 69

# --- today's parks & air. Key per TEAM that is PLAYING today. Value = feet of carry
#     to ADD (or subtract) vs neutral. totals.py builds this automatically from O/U;
#     leave the manual dict here as a fallback when totals are unreachable. A team
#     present here = it's on the slate; anything absent is treated as off-slate.
PARKS = {}

# --- LIVE ENTRY COUNTS off the Fanatics leaderboard (THE key input once it posts).
#     Player display name : number of entries currently on him.
#     Payout if he wins = 50000 / entries.  Empty -> model estimates from odds.
LIVE_ENTRIES = {}

# --- model knobs / calibration defaults (overridden by calibration.json) ---
POOL_SIZE_GUESS  = 5200          # calibrated daily pool size
MIN_PAYOUT_FLOOR = 1000          # only surface bats whose split clears this ($1000 -> <=50 entries)
DEFAULT_OWNERSHIP = 0.012        # for an unlisted, low-profile bat (pre-odds fallback)
CEILING_GATE     = 445           # a bat needs ~this top-5 ceiling to realistically win a day

TAU          = 9.0    # distance softmax temp; lower = ceiling matters more
FIELD_HRS    = 28     # unmodeled league HRs/day that could steal the title
FIELD_CEIL   = 417    # their average ceiling (ft)
POT          = 50000  # FanCash jackpot
MIN_HR_SAMPLE = 4     # ignore hitters with fewer than this many HRs in the file
VIG_HAIRCUT  = 0.88   # flat de-vig on anytime-HR longshots

# entries-from-odds curve: est_entries = pool * K * implied_prob**ALPHA  (alpha>1: the
# public over-concentrates on favorites). Calibrated against real Fanatics boards.
ENTRIES_K     = 2.71
ENTRIES_ALPHA = 2.77

# Optional: restrict output to a hand-picked watchlist (display names). Empty = all on slate.
WATCHLIST = []


def load_calibration(path=None):
    """Load calibration.json (pool size, entries curve, env params). Falls back to
    the module defaults above if the file is missing so the model always runs."""
    path = path or os.path.join(HERE, "calibration.json")
    cal = {
        "pool_size": POOL_SIZE_GUESS,
        "games_elapsed": GAMES_ELAPSED,
        "min_payout_floor": MIN_PAYOUT_FLOOR,
        "ceiling_gate": CEILING_GATE,
        "entries_from_odds": {"k": ENTRIES_K, "alpha": ENTRIES_ALPHA},
        "env": {"mult": 1.8, "cap": 9.0, "base": 8.5},
        "model": {"tau": TAU, "field_hrs": FIELD_HRS, "field_ceil": FIELD_CEIL,
                  "pot": POT, "min_hr_sample": MIN_HR_SAMPLE, "vig_haircut": VIG_HAIRCUT},
    }
    try:
        with open(path) as f:
            cal.update(json.load(f))
    except FileNotFoundError:
        pass
    return cal


# ====================================================================================
# CALIBRATION LOG (update calibration.json as results come in)
#   Observed daily winning distances Jun8-Jun14: 483, 446, 466, 445, 471, 454, 462.
#   Median ~466; plenty of winning days in the 445-455 range. Takeaway: you need a
#   ~445+ ceiling, but 470+ is NOT required most days -- don't over-inflate off one total.
#   Pool size: Jun12 Kurtz won w/ 435 entries (50000/115). ~8% ownership -> ~5,200 pool.
#   Jun13 lesson: a 13.5 total pushed Sacramento ceilings +12.5 ft and the moonshots
#   never came. ENV is now gentler: mult 1.8, cap +9 (see env_from_total).
# ====================================================================================

def env_from_total(total, mult=1.8, cap=9.0, base=8.5):
    """Convert a game's over/under into carry-feet vs a neutral 8.5 total.
    Gentler than the first pass (was 2.5 / cap 13) after Jun13 over-shot Sacramento.
    Use this for every game so environment is book-driven, not vibes-driven."""
    return round(max(-cap, min(cap, (total - base) * mult)), 1)


# ====================================================================================
# MODEL
# ====================================================================================

def load_distance_profile(path: str) -> pd.DataFrame:
    """Per-player distance ceiling from event-level HR data (all seasons in file).

    Savant's Statcast CSV calls the distance column `hit_distance_sc`; savant.py
    also writes a `bbdist` alias. Accept either so a hand-downloaded CSV still works."""
    raw = pd.read_csv(path, low_memory=False)
    dist_col = "bbdist" if "bbdist" in raw.columns else "hit_distance_sc"
    df = raw[["player_name", dist_col]].rename(columns={dist_col: "bbdist"})
    df = df.dropna(subset=["bbdist"])
    g = df.groupby("player_name")["bbdist"]
    prof = pd.DataFrame({
        "n_hr":  g.size(),
        "max_d": g.max(),
        "top5":  g.apply(lambda s: s.nlargest(5).mean()),
        "top3":  g.apply(lambda s: s.nlargest(3).mean()),
    }).reset_index()
    prof = prof[prof.n_hr >= MIN_HR_SAMPLE]
    prof["display"] = prof.player_name.map(to_display)
    return prof


def load_hr_rate(path: str, games_elapsed: int) -> pd.DataFrame:
    """Season xHR -> per-game HR probability. Prefer the most recent year if duplicated."""
    df = pd.read_csv(path)
    if "year" in df.columns:
        df = df.sort_values("year").groupby("player", as_index=False).last()
    df["display"] = df.player.map(to_display)
    df["phr"] = 1 - (math.e ** (-df.xhr / games_elapsed))   # 1 - exp(-xhr / G)
    keep = ["display", "team_abbrev", "hr_total", "xhr", "phr"]
    for opt in ("xhr_diff", "no_doubter_per"):
        if opt in df.columns:
            keep.append(opt)
    return df[keep]


def implied_from_american(odds):
    """American HR odds -> implied probability (raw, includes vig)."""
    odds = float(odds)
    return 100 / (odds + 100) if odds > 0 else (-odds) / (-odds + 100)


def odds_tier(odds):
    """Ownership-tier proxy from anytime-HR price. Shorter odds -> more entries.
      CHALK (<+250), MOD (+250..+400), LIGHT (+400..+650), DART (>+650)."""
    o = float(odds)
    if o < 250:   return "CHALK"
    if o < 400:   return "MOD"
    if o < 650:   return "LIGHT"
    return "DART"


def ingest_hr_odds(odds_dict, vig_haircut=VIG_HAIRCUT):
    """DK anytime-HR odds {display_name: american_odds} -> {name: {phr, tier, odds}}.
    de-vigged with a flat haircut for longshot over-round."""
    out = {}
    for name, o in odds_dict.items():
        out[name] = {
            "phr": round(implied_from_american(o) * vig_haircut, 4),
            "tier": odds_tier(o),
            "odds": int(o),
        }
    return out


def est_entries_from_odds(implied_p, pool, k, alpha):
    """Pre-game ownership proxy: the public over-concentrates on favorites, so entries
    scale super-linearly with implied HR probability. Calibrated vs real boards."""
    return max(1.0, pool * k * (implied_p ** alpha))


def build_card(event_csv=None, leaderboard_csv=None, parks=None, odds=None,
               live_entries=None, calib=None, watchlist=None) -> pd.DataFrame:
    """Merge distance ceiling + P(HR) + environment + ownership into a ranked EV card.

    odds: {display_name: american_odds} from dk_odds.py. When present it OVERRIDES the
          xHR-derived P(HR) with the sharper de-vigged market probability and drives the
          estimated-entries (ownership) curve. Without odds, falls back to xHR + a flat
          ownership guess.
    parks: {team_abbrev: carry_ft} -- the slate. Defaults to module PARKS.
    live_entries: {display_name: entries} from the Fanatics board (overrides estimates).
    """
    calib = calib or load_calibration()
    parks = parks if parks is not None else PARKS
    live_entries = live_entries if live_entries is not None else LIVE_ENTRIES
    watchlist = watchlist if watchlist is not None else WATCHLIST
    event_csv = event_csv or EVENT_CSV
    leaderboard_csv = leaderboard_csv or LEADERBOARD_CSV

    mk = calib["model"]
    pool = calib["pool_size"]
    ecurve = calib["entries_from_odds"]
    games_elapsed = calib.get("games_elapsed", GAMES_ELAPSED)

    if not parks:
        sys.exit("No slate: PARKS is empty. Pass parks=... (totals.py) or fill PARKS.")

    prof = load_distance_profile(event_csv)
    rate = load_hr_rate(leaderboard_csv, games_elapsed)
    m = prof.merge(rate, on="display", how="inner")

    # on slate?  -> team must be in parks
    m = m[m.team_abbrev.isin(parks.keys())].copy()
    if watchlist:
        m = m[m.display.isin(watchlist)]
    if m.empty:
        sys.exit("No players matched the slate. Check PARKS teams vs the CSV team codes.")

    # --- odds override: sharper P(HR) + a popularity tier, joined on the accent-safe key
    odds_by_key = {}
    if odds:
        ing = ingest_hr_odds(odds, vig_haircut=mk["vig_haircut"])
        odds_by_key = {norm_key(name): v for name, v in ing.items()}
    live_by_key = {norm_key(k): v for k, v in live_entries.items()}

    def row_odds(row):
        return odds_by_key.get(norm_key(row.display))

    oinfo = m.apply(row_odds, axis=1)
    m["hr_odds"] = [o["odds"] if o else None for o in oinfo]
    m["tier"]    = [o["tier"] if o else "" for o in oinfo]
    # market P(HR) when we have odds, else the xHR-derived rate
    m["phr"] = [o["phr"] if o else p for o, p in zip(oinfo, m["phr"])]

    # env-adjusted distance ceiling (top-5 avg + tonight's carry)
    m["ceil"] = m.top5 + m.team_abbrev.map(parks).fillna(0)

    # entries / payout-if-win
    def entries_for(row):
        lk = norm_key(row.display)
        if lk in live_by_key:
            return float(live_by_key[lk]), "live"
        o = odds_by_key.get(lk)
        if o:                                   # odds-driven ownership curve
            est = est_entries_from_odds(o["phr"], pool, ecurve["k"], ecurve["alpha"])
            return est, "odds"
        # last-resort: flat ownership guess scaled by P(HR)
        est = max(1.0, DEFAULT_OWNERSHIP * pool * row.phr / 0.18)
        return est, "est"

    ent = m.apply(entries_for, axis=1)
    m["entries"] = [e for e, _ in ent]
    m["live"]    = [src for _, src in ent]
    m["payout_if_win"] = mk["pot"] / m.entries

    # P(player owns the day's longest HR)  -- distance softmax gated by P(HR)
    w = lambda s: math.e ** ((s - 430) / mk["tau"])
    field = mk["field_hrs"] * w(mk["field_ceil"])
    denom = field + (m.phr * m.ceil.map(w)).sum()
    m["p_long"] = m.phr * m.ceil.map(w) / denom

    # the number that matters
    m["EV"] = m.p_long * m.payout_if_win

    return m.sort_values("EV", ascending=False)


def launchpad_stack(card, max_carry_threshold=6.0, max_entries=60, min_ceil=438, n=5):
    """When a game's environment is an outlier, you can't know WHICH bat in it goes
    deepest -- so basket the cheap ones. Returns the low-owned, high-ceiling bats in
    the single best environment on the slate. Feed it the full card from build_card().
    Strategy lesson (Jun14): A's/Rockies (14 total) had the day's longest, but it was
    Soderstrom -- a career outlier no model ranks. Spreading darts across that game
    cashes regardless of which bat connects."""
    if card.empty:
        return card
    carry = card["ceil"].sub(card.top5).round(1)  # carry actually applied
    card = card.assign(_carry=carry)
    top_carry = card["_carry"].max()
    if top_carry < max_carry_threshold:
        return card.iloc[0:0]  # no real launchpad today -> no stack
    spot = card[card["_carry"] >= top_carry - 0.1]
    darts = spot[(spot.entries <= max_entries) & (spot.ceil >= min_ceil)]
    return darts.sort_values("entries").head(n)


def under_floor(card, calib=None):
    """Only the bats whose split would clear MIN_PAYOUT_FLOOR (the default view)."""
    calib = calib or load_calibration()
    return card[card.payout_if_win >= calib["min_payout_floor"]]


def _fmt(card):
    cols = ["display", "team_abbrev", "n_hr", "max_d", "top5", "ceil",
            "phr", "hr_odds", "tier", "entries", "live", "payout_if_win", "p_long", "EV"]
    show = card[cols].copy()
    show.columns = ["Player", "Tm", "#HR", "MaxD", "Top5", "Ceil",
                    "P(HR)", "Odds", "Tier", "Entries", "src", "Pay$", "P(long)", "EV$"]
    show["P(HR)"]   = (show["P(HR)"] * 100).round(0).astype("Int64").astype(str) + "%"
    show["P(long)"] = (show["P(long)"] * 100).round(2).astype(str) + "%"
    for c in ("Top5", "Ceil", "MaxD", "Entries", "Pay$"):
        show[c] = show[c].round(0).astype("Int64")
    show["Odds"] = show["Odds"].map(lambda o: "--" if pd.isna(o)
                                    else (f"+{int(o)}" if o > 0 else str(int(o))))
    show["EV$"] = show["EV$"].round(2)
    return show


def main():
    calib = load_calibration()
    card = build_card(calib=calib)
    show = _fmt(card)

    print("\n" + "=" * 100)
    print(f"  LONG BALL JACKPOT MODEL   |   {len(card)} bats on slate   |   "
          f"games elapsed: {calib.get('games_elapsed', GAMES_ELAPSED)}")
    print("=" * 100)
    print(show.head(20).to_string(index=False))
    print("-" * 100)
    print("  EV$ = expected FanCash per $5 ticket.  src: live=board, odds=odds curve, est=guess.")
    print("  Higher Ceil + small Entries = the model's edge. Confirm lineups before betting.\n")

    floor = under_floor(card, calib)
    if not floor.empty:
        print(f"  -- UNDER FLOOR (split clears ${calib['min_payout_floor']}) --")
        print(_fmt(floor).head(15).to_string(index=False), "\n")

    stack = launchpad_stack(card)
    if not stack.empty:
        print("  -- LAUNCHPAD STACK (one outlier game; spread the darts) --")
        print(_fmt(stack).to_string(index=False), "\n")

    out = os.path.join(HERE, "data", "longball_card_today.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    card.to_csv(out, index=False)
    print(f"  Full ranked card saved -> {out}\n")


if __name__ == "__main__":
    main()
