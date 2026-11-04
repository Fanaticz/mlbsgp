#!/usr/bin/env python3
"""Tonight's NBA teammate correlation sheet (xlsx), one row per combo.

For every pair of current teammates on tonight's slate who both have a
Pinnacle line, and every stat pairing of PTS / REB / AST / 3PM, the sheet
gives the correlation between the two stat lines and all four directions
(O+O, O+U, U+O, U+U) at tonight's lines: how often that combo hit in their
games together, and its fair price from Pinnacle's devigged legs.

Columns follow last season's teammate_correlations sheet, plus:
  correlation   shrunk r: the pair's r pulled toward the league average for
                that stat pairing by sample size (empirical Bayes, Fisher z).
                Pairs with few games together move most. Price with this.
  raw_r         the plain Pearson r over their games together (within-season
                centered), what Excel's CORREL gives
  leg1_fair / leg2_fair   Pinnacle's price for each side, worst-case devig
  fair_odds     the combo's fair price: Gaussian copula at the shrunk r
  no_corr_odds  what the combo would be if the legs were independent
  bet_if        fair_odds plus a 3% cushion: bet the SGP at or above this
  mpg_last / mpg_now   both players' minutes, last season vs this season;
                a big change means last season's games are a weak guide

Data: ESPN game summaries cached by scripts/nba_fetch_teammates.py
(.cache/nba_games_<season>.json, last and current season), Pinnacle props
via dk_api.pinnacle_nba_props(), ESPN current rosters.

Usage:
  python3 scripts/nba_teammate_sheet.py                     # tonight
  python3 scripts/nba_teammate_sheet.py --out sheet.xlsx --min-games 30
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, ".claude", "skills", "nba-ast-pts-sgp"))

import openpyxl  # noqa: E402
from openpyxl.styles import Font, PatternFill  # noqa: E402

import sgp  # noqa: E402  devig_worst, joint (Gaussian copula), prob
from nba_fetch_correlations import make_session, pearson_pvalue, team_roster_map  # noqa: E402
from nba_fetch_teammates import fetch_games  # noqa: E402

STATS = ("pts", "reb", "ast", "tpm")
STAT_NAME = {"pts": "Points", "reb": "Rebounds", "ast": "Assists", "tpm": "3-Pointers"}
SIDES = (("over", "over"), ("over", "under"), ("under", "over"), ("under", "under"))
COMBO = {"over": "O", "under": "U"}


def norm(name: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = "".join(c if c.isalnum() or c == " " else " " for c in s.replace("'", "").replace(".", "")).split()
    return "".join(w for w in words if w not in {"jr", "sr", "ii", "iii", "iv", "v"})


def american(p: float) -> int:
    return round(100 * (1 - p) / p) if p < 0.5 else -round(100 * p / (1 - p))


def fz(r: float) -> float:
    return math.atanh(max(min(r, 0.999), -0.999))


def pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def centered(vals, seasons):
    by = defaultdict(list)
    for v, s in zip(vals, seasons):
        by[s].append(v)
    mean = {s: sum(v) / len(v) for s, v in by.items()}
    return [v - mean[s] for v, s in zip(vals, seasons)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="+", default=[2026, 2027],
                    help="ESPN seasons to pool (2026 = 2025-26)")
    ap.add_argument("--min-games", type=int, default=25, help="min games together")
    ap.add_argument("--min-r", type=float, default=0.10, help="drop pairs with |raw r| below this")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default="nba_teammate_correlations.xlsx")
    args = ap.parse_args()

    import dk_api
    pin = dk_api.pinnacle_nba_props()
    if not pin or not pin.get("props"):
        sys.exit("No Pinnacle NBA props; nothing to build.")
    lines = {}
    for p in pin["props"]:
        if p.get("stat") in STATS and p.get("over") and p.get("under"):
            lines[(norm(p["player"]), p["stat"])] = p

    games = []
    for s in args.seasons:
        for g in fetch_games(s, args.workers, os.path.join(ROOT, ".cache", f"nba_games_{s}.json")):
            g["season"] = s
            games.append(g)
    roster = team_roster_map(make_session())

    names: dict[str, str] = {}
    abbr: dict[str, str] = {}
    log = defaultdict(dict)          # (team abbr, aid) -> gid -> box line (+ season)
    edges = {}
    for g in games:
        names.update(g["names"])
        abbr.update(g["abbr"])
        edges[g["id"]] = g["ae"]
        for aid, ln in g["p"].items():
            log[(g["abbr"][ln["t"]], aid)][g["id"]] = dict(ln, season=g["season"])

    # tonight's players: on their team today, with at least one Pinnacle line
    tonight = defaultdict(list)
    for aid, info in roster.items():
        team = info.get("team_abbr")
        if not team or aid not in names:
            continue
        if any((norm(names[aid]), s) in lines for s in STATS):
            tonight[team].append(aid)

    def mpg(aid, team, season):
        gl = [l for l in log[(team, aid)].values() if l["season"] == season]
        return round(sum(l["min"] for l in gl) / len(gl), 1) if gl else None

    last, now = min(args.seasons), max(args.seasons)
    pairs = []
    for team, aids in tonight.items():
        for a in aids:
            for b in aids:
                if a >= b:
                    continue                              # each pair once; all 16 stat pairings below
                ga, gb = log[(team, a)], log[(team, b)]
                shared = sorted(set(ga) & set(gb))
                if len(shared) < args.min_games:
                    continue
                seasons = [ga[g]["season"] for g in shared]
                for sa in STATS:
                    la = lines.get((norm(names[a]), sa))
                    if not la:
                        continue
                    for sb in STATS:
                        lb = lines.get((norm(names[b]), sb))
                        if not lb or lb["game_id"] != la["game_id"]:
                            continue
                        xa = [ga[g][sa] for g in shared]
                        xb = [gb[g][sb] for g in shared]
                        r = pearson(centered(xa, seasons), centered(xb, seasons))
                        if r is None:
                            continue
                        pairs.append(dict(team=team, a=a, b=b, sa=sa, sb=sb, la=la, lb=lb,
                                          shared=shared, xa=xa, xb=xb, r=r, n=len(shared)))

    # empirical-Bayes shrinkage per unordered stat pairing, over every pair on the slate
    groups = defaultdict(list)
    for p in pairs:
        groups[tuple(sorted((p["sa"], p["sb"])))].append(p)
    for cs in groups.values():
        z = [fz(p["r"]) for p in cs]
        se2 = [1 / (p["n"] - 3) for p in cs]
        mu = sum(z) / len(z)
        tau2 = max(sum((v - mu) ** 2 for v in z) / len(z) - sum(se2) / len(se2), 0.04 ** 2)
        for p, v, s in zip(cs, z, se2):
            w = tau2 / (tau2 + s)
            p["shrunk"] = math.tanh(w * v + (1 - w) * mu)

    out_rows = []
    for p in pairs:
        if abs(p["r"]) < args.min_r:
            continue
        a, b, sa, sb, la, lb = p["a"], p["b"], p["sa"], p["sb"], p["la"], p["lb"]
        poa, pua = sgp.devig_worst(sgp.prob(la["over"]), sgp.prob(la["under"]))
        pob, pub = sgp.devig_worst(sgp.prob(lb["over"]), sgp.prob(lb["under"]))
        # direct assist link, either direction where one side is assists
        rel, note, apg, pct, extra = "Same-Game Performance", None, 0.0, 0.0, None
        for passer, scorer, ps, ss in ((a, b, sa, sb), (b, a, sb, sa)):
            if ps == "ast" and ss in ("pts", "tpm"):
                two = sum((edges[g].get(f"{passer}>{scorer}") or [0, 0])[0] for g in p["shared"])
                three = sum((edges[g].get(f"{passer}>{scorer}") or [0, 0])[1] for g in p["shared"])
                tot_b = sum(log[(p["team"], scorer)][g][ss] for g in p["shared"])
                if ss == "pts":
                    per = (2 * two + 3 * three) / p["n"]
                    share = (2 * two + 3 * three) / tot_b if tot_b else 0
                    unit = "pts"
                else:
                    per = three / p["n"]
                    share = three / tot_b if tot_b else 0
                    unit = "3PM"
                apg, pct = round((two + three) / p["n"], 2), round(100 * share, 1)
                if per >= 0.5:
                    rel = "Direct Assist-To"
                    note = (f"{per:.2f} {unit}/gm from {names[passer]} -> {pct}% of "
                            f"{names[scorer]}'s {'points' if ss == 'pts' else '3PM'}")
                    extra = "Assists+Scoring: includes both same-game & direct assist correlation"
        for s1, s2 in SIDES:
            ha = [(v > la["line"]) == (s1 == "over") for v in p["xa"]]
            hb = [(v > lb["line"]) == (s2 == "over") for v in p["xb"]]
            hit = sum(1 for x, y in zip(ha, hb) if x and y) / p["n"]
            pa = poa if s1 == "over" else pua
            pb = pob if s2 == "over" else pub
            rho = p["shrunk"] if s1 == s2 else -p["shrunk"]
            # latent "hit" variables correlate at +rho (flipped for Unders); the
            # copula is radially symmetric, so P(both hit) = joint(rho, pa, pb)
            joint = sgp.joint(rho, pa, pb)
            row = {
                "player1": names[a], "stat1": STAT_NAME[sa], "side1": s1, "line1": la["line"],
                "player2": names[b], "stat2": STAT_NAME[sb], "side2": s2, "line2": lb["line"],
                "combo": f"{COMBO[s1]}+{COMBO[s2]}",
                "correlation": round(rho, 4), "raw_r": round(p["r"] if s1 == s2 else -p["r"], 4),
                "p_value": round(pearson_pvalue(p["r"], p["n"]) or 0, 4), "sample_size": p["n"], "hit_rate": round(hit, 3),
                "relationship_type": rel, "assist_to_note": note, "assists_per_game": apg,
                "pct_of_receivers_stat": pct,
                "p1_avg": round(sum(p["xa"]) / p["n"], 1), "p2_avg": round(sum(p["xb"]) / p["n"], 1),
                "leg1_fair": american(pa), "leg2_fair": american(pb),
                "fair_odds": american(joint), "no_corr_odds": american(pa * pb),
                "bet_if": american(joint / 1.03),
                "team": p["team"], "mpg_last": f"{mpg(a, p['team'], last)} / {mpg(b, p['team'], last)}",
                "mpg_now": f"{mpg(a, p['team'], now)} / {mpg(b, p['team'], now)}",
                "note": extra,
            }
            out_rows.append(row)

    out_rows.sort(key=lambda r: (-abs(r["correlation"]), r["player1"], r["player2"], r["combo"]))
    cols = ["player1", "stat1", "side1", "line1", "player2", "stat2", "side2", "line2", "combo",
            "correlation", "raw_r", "p_value", "sample_size", "hit_rate", "relationship_type",
            "assist_to_note", "assists_per_game", "pct_of_receivers_stat", "p1_avg", "p2_avg",
            "leg1_fair", "leg2_fair", "fair_odds", "no_corr_odds", "bet_if",
            "team", "mpg_last", "mpg_now", "note"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = dt.date.today().isoformat()
    ws.append(cols)
    for r in out_rows:
        ws.append([r[c] for c in cols])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDDDDD")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    widths = {"player1": 24, "player2": 24, "assist_to_note": 52, "relationship_type": 22, "note": 40}
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = widths.get(c, 11)
    wb.save(args.out)
    print(f"Wrote {args.out}: {len(out_rows)} rows, {len(out_rows) // 4} stat pairs, "
          f"{sum(len(v) for v in tonight.values())} players on {len(tonight)} teams")


if __name__ == "__main__":
    main()
