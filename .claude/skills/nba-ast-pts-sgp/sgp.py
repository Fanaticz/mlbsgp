#!/usr/bin/env python3
"""NBA Assists x Points SGP helper.

  python3 sgp.py players [--min-ast 5] [--min-pts 17] [--max-r 0]
      Today's high-assist players (from public/data/nba_correlations.json)
      whose shrunk PTS-AST margin r is negative, plus the Vulture commands.

  python3 sgp.py fv legs.json [--card card.html]
      legs.json: {"Cade Cunningham": {"ast": {"line": 8.5, "over": -119, "under": 121},
                                      "pts": {"line": 24.5, "over": 106, "under": -106}},
                  "Cade Cunningham|9.5": {...alt line, same player...},
                  "_meta": {"slips": [{"key": "Cade Cunningham|9.5", "combo": "UO",
                                       "payout": 4.14, "book": "Novig"}],
                            "market_note": "...", "notes": ["..."]}}
      Fair values are the avg_fv column from Vulture. A missing side is
      filled from the other side's complement (marked *). A leg can carry
      "src": "market" (devigged from other books, marked †) or "earlier"
      (FV from a previous pull, marked ‡). A leg with "from": {line, over,
      under} is shifted from an FV posted at another line (e.g. Novig 25+
      vs DK 23.5) with the player's game-log SD, marked ≈. Omit "pts"/"ast"
      when there is no FV at all. Prints both opposite-direction combos (Ast U + Pts O,
      Ast O + Pts U): shrunk margin r, the binary corr it implies at those
      lines, and the Gaussian-copula joint / FV. --card writes the Discord
      card; render it with `node render.js card.html card.png`.
"""
import argparse
import html
import json
import math
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CORR = os.path.join(ROOT, "public", "data", "nba_correlations.json")
SRC_MARK = {"market": "†", "earlier": "‡"}


def prob(o):
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def american(p):
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def ncdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def nppf(p):
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if ncdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def joint(r, a, b):
    """P(U < a-quantile, V < b-quantile) under a Gaussian copula with margin
    corr r. Plackett: d/drho Phi2(x,y;rho) = phi2(x,y;rho); Simpson in rho."""
    x, y = nppf(a), nppf(b)
    n = 200
    h = r / n
    tot = 0.0
    for i in range(n + 1):
        rho = i * h
        q = 1 - rho * rho
        f = math.exp(-(x * x - 2 * rho * x * y + y * y) / (2 * q)) / (2 * math.pi * math.sqrt(q))
        tot += f * (1 if i in (0, n) else 4 if i % 2 else 2)
    return a * b + tot * h / 3


def binary(r, a, b):
    j = joint(r, a, b)
    return (j - a * b) / math.sqrt(a * (1 - a) * b * (1 - b))


_POOL = {}


def pool_stats(by):
    """(prior, tau2, n) for high-assist starters (>=4 AST, >=24 MPG, >=60 games)."""
    if id(by) not in _POOL:
        pool = [p for p in by.values()
                if p["ast_mean"] >= 4 and p["n_games"] >= 60 and p["min_mean"] >= 24]
        rs = [p["pts_ast"]["weighted"]["r"] for p in pool]
        noise = [(1 - r * r) ** 2 / p["effective_n"] for r, p in zip(rs, pool)]
        prior = sum(rs) / len(rs)
        var = sum((r - prior) ** 2 for r in rs) / len(rs)
        _POOL[id(by)] = (prior, max(var - sum(noise) / len(noise), 1e-4), len(pool))
    return _POOL[id(by)]


def margin_r(by, name):
    """Recency-weighted within-season PTS-AST r, shrunk toward players in a
    similar role. Per-player r carries ~0.10 of sampling noise vs ~0.08 of
    real spread, so raw r's overstate differences between players. Uses the
    data file's role-matched value (scripts/nba_fetch_correlations.py
    add_shrinkage, also shown on the dashboard); older files fall back to
    shrinking toward high-assist starters here."""
    p = by[name]
    if "shrunk" in p["pts_ast"]:
        return p["pts_ast"]["shrunk"]["r"]
    prior, tau2, _ = pool_stats(by)
    r = p["pts_ast"]["weighted"]["r"]
    w = tau2 / (tau2 + (1 - r * r) ** 2 / p["effective_n"])
    return w * r + (1 - w) * prior


def load():
    d = json.load(open(CORR))
    return d, {p["name"]: p for p in d["players"]}


def players(args):
    d, by = load()
    teams = {t for g in d["schedule_today"]["games"] for t in g["team_abbrs"]}
    rows = [p for p in d["players"]
            if p["team_abbr"] in teams and p["n_games"] >= 20
            and p["ast_mean"] >= args.min_ast and p["pts_mean"] >= args.min_pts
            and margin_r(by, p["name"]) < args.max_r]
    rows.sort(key=lambda p: margin_r(by, p["name"]))
    print(f"slate {d['schedule_today']['date']}  (data {d['generated_at']})")
    for p in rows:
        w = p["pts_ast"]["weighted"]
        print(f"  {p['name']:26} {p['team_abbr']:5} ast {p['ast_mean']:4.1f} pts {p['pts_mean']:4.1f}"
              f"  raw r {w['r']:+.3f}  shrunk {margin_r(by, p['name']):+.3f} (n {p['n_games']})")
    names = ", ".join(p["name"] for p in rows)
    # Split by market so an EV cutoff in Vulture can't crowd out the points lines.
    print("\nVulture:")
    for market in ("player assist", "player points"):
        print(f"/run command_name:twa markets:{market} bet_names:{names} books:dk")


def sides(leg):
    """(p_over, p_under, over_implied, under_implied)"""
    o, u = leg.get("over"), leg.get("under")
    po = prob(o) if o is not None else 1 - prob(u)
    pu = prob(u) if u is not None else 1 - prob(o)
    return po, pu, o is None, u is None


def stat_sd(p, stat):
    """Within-season SD of a box stat from the game log (short games excluded)."""
    seasons = {}
    for g in p["recent_games"]:
        if not g.get("short"):
            seasons.setdefault(g["s"], []).append(g[stat])
    seasons = [v for v in seasons.values() if len(v) > 1]
    dev = [x - sum(v) / len(v) for v in seasons for x in v]
    return math.sqrt(sum(d * d for d in dev) / (len(dev) - len(seasons)))


def leg_probs(p, stat, leg):
    """sides() for a leg, shifting it first when its FV was posted at another
    line: fit a normal with the player's SD through the posted line, read off
    the target line."""
    if "from" not in leg:
        return sides(leg)
    fo, fu, _, _ = sides(leg["from"])
    sd = stat_sd(p, stat)
    mu = leg["from"]["line"] - sd * nppf(fu / (fo + fu))
    po = 1 - ncdf((leg["line"] - mu) / sd)
    return po, 1 - po, False, False


def leg_label(side, leg, implied):
    return (f"{side}{leg['line']:g}{'*' if implied else ''}{'≈' if 'from' in leg else ''}"
            f"{SRC_MARK.get(leg.get('src'), '')}")


def price(by, legs):
    rows = []
    for key, L in legs.items():
        name = key.split("|")[0]
        if name not in by:
            print(f"{key}: no correlation data, skipped")
            continue
        r = margin_r(by, name)
        row = {"key": key, "name": name, "r": r, "combos": None, "legs": L}
        if L.get("ast") and L.get("pts"):
            ao, au, ao_i, au_i = leg_probs(by[name], "ast", L["ast"])
            po, pu, po_i, pu_i = leg_probs(by[name], "pts", L["pts"])
            row["combos"] = []
            # Opposite-direction combos: corr(AST, -PTS) = -margin r.
            for code, a, ai, b, bi, asd, psd in (("UO", au, au_i, po, po_i, "U", "O"),
                                                 ("OU", ao, ao_i, pu, pu_i, "O", "U")):
                j = joint(-r, a, b)
                row["combos"].append({
                    "code": code,
                    "label": f"{leg_label(asd, L['ast'], ai)} + {leg_label(psd, L['pts'], bi)}",
                    "binary": binary(-r, a, b), "joint": j, "fv": american(j), "fair": 1 / j})
        rows.append(row)
    rows.sort(key=lambda w: (w["combos"] is None, w["r"]))
    return rows


def fv(args):
    d, by = load()
    legs = json.load(open(args.legs))
    meta = legs.pop("_meta", {})
    rows = price(by, legs)
    print(f"{'player':24} {'combo':22} {'r':>7} {'binary':>7} {'joint':>6} {'FV':>6} {'fair x':>7}")
    for w in rows:
        for c in w["combos"] or []:
            print(f"{w['key']:24} {c['label']:22} {w['r']:+.3f} {c['binary']:+.3f} "
                  f"{c['joint']*100:5.1f}% {c['fv']:+6d} {c['fair']:6.2f}x")
        if not w["combos"]:
            print(f"{w['key']:24} missing {'pts' if not w['legs'].get('pts') else 'ast'} FV")
    for s in meta.get("slips", []):
        c = next(c for w in rows if w["key"] == s["key"] for c in (w["combos"] or [])
                 if c["code"] == s["combo"])
        s["ev"] = s["payout"] * c["joint"] - 1
        s["fair"] = c["fair"]
        s["label"] = c["label"]
        print(f"slip {s.get('book', '')} {s['key']} {s['combo']} @ {s['payout']}x: "
              f"fair {c['fair']:.2f}x, EV {s['ev']*100:+.1f}%")
    if args.card:
        open(args.card, "w").write(card(d, by, rows, meta))
        print(f"card -> {args.card}")


CSS = """
body{margin:0;background:#0f1115;font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;color:#e8eaed}
.c{width:1000px;padding:28px 30px 22px}
h1{font-size:24px;margin:0 0 4px}
.sub{color:#9aa0a6;font-size:14px;margin-bottom:18px}
table{width:100%;border-collapse:collapse;font-size:15px}
th{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#9aa0a6;font-weight:600;padding:8px 10px;text-align:left}
th.nt{text-transform:none}
th.g{text-align:center;font-size:13px;color:#e8eaed;border-bottom:2px solid}
th.g1{border-color:#4ea1ff}th.g2{border-color:#f5a524}
td{padding:9px 10px;border-top:1px solid #23262d}
tr:nth-child(even) td{background:#151820}
.n{font-weight:600}.l{color:#c4c7cc}
.fv{font-weight:700;font-variant-numeric:tabular-nums}.x{color:#9aa0a6;font-variant-numeric:tabular-nums}
.a{color:#6cb4ff}.b{color:#ffbe55}
.sep{border-left:1px solid #2c3038}
.foot{margin-top:16px;font-size:14px;color:#c4c7cc;line-height:1.55}
.ev{color:#3ddc84;font-weight:700}.neg{color:#ff6b6b;font-weight:700}.mu{color:#80868b}
.miss{color:#ff6b6b;font-weight:600;font-size:13px}.st{color:#ff6b6b}
.r{color:#c9a7ff;font-variant-numeric:tabular-nums;font-weight:600}
"""


def card(d, by, rows, meta):
    e = html.escape
    if "shrinkage" in d:
        pool = (f'rotation players with a similar assist volume '
                f'(prior {d["shrinkage"]["pairs"]["pts_ast"]["knots"][-1][1]:+.3f} for heavy passers)')
    else:
        prior, _, n_pool = pool_stats(by)
        pool = f"{n_pool} high-assist starters (avg {prior:+.3f})"
    date = d["schedule_today"]["date"]
    used = set()
    body = []
    for w in rows:
        cells = [f'<td class="n">{e(w["name"])}</td>', f'<td class="r">{w["r"]:+.3f}</td>']
        if w["combos"]:
            uo, ou = w["combos"]
            cells.append(f'<td class="r">{uo["binary"]:+.3f}</td>')
            for c, cls, sep in ((uo, "a", ""), (ou, "b", " sep")):
                used.update(ch for ch in "*†‡≈" if ch in c["label"])
                cells.append(f'<td class="l{sep}">{c["label"]}</td><td class="fv {cls}">{c["fv"]:+d}</td>'
                             f'<td class="x">{c["fair"]:.2f}x</td>')
        else:
            used.add("?")
            L = w["legs"]
            have, gone = ("ast", "pts") if L.get("ast") else ("pts", "ast")
            tag = "Ast" if gone == "ast" else "Pts"
            q = f'<span class="st">{tag} ?</span>'
            cells.append('<td></td>')
            for sd, sep in (("UO", ""), ("OU", " sep")):
                if have == "ast":
                    lab = f'{leg_label(sd[0], L["ast"], False)} + {q}'
                elif L.get("pts"):
                    lab = f'{q} + {leg_label(sd[1], L["pts"], False)}'
                else:
                    lab = q
                cells.append(f'<td class="l{sep}">{lab}</td><td class="miss" colspan="2">no {tag} FV</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    foot = [f'<span class="r">PTS/AST r</span> = margin corr (season-centered, recency-weighted), '
            f'shrunk toward {pool}',
            '<span class="r">combo binary</span> = what that implies for Ast Under + Pts Over at these '
            'lines (Gaussian copula); joint priced off the copula',
            'Bet it if the payout is above the fair multiplier.']
    for s in meta.get("slips", []):
        cls = "ev" if s["ev"] >= 0 else "neg"
        foot.append(f'{e(s.get("book", ""))} {e(s["key"].split("|")[0])} {s["label"]} @ '
                    f'<b>{s["payout"]:.2f}x</b> vs {s["fair"]:.2f}x fair = '
                    f'<span class="{cls}">{s["ev"]*100:+.1f}% EV</span>')
    mu = []
    if "?" in used:
        mu.append('<span class="st">?</span> = no FV posted yet for that leg')
    if "†" in used:
        mu.append("† " + e(meta.get("market_note", "Pts FV devigged from other books' main line "
                                                  "(DK hangs a different number)")))
    if "‡" in used:
        mu.append("‡ " + e(meta.get("earlier_note", "FV from an earlier pull (not in the latest screenshot)")))
    if "≈" in used:
        mu.append("≈ " + e(meta.get("shift_note", "line shifted from the FV posted at another number "
                                                 "(normal with his game-log SD)")))
    if "*" in used:
        mu.append("* side implied from the other side's FV (only one side posted)")
    mu += [e(x) for x in meta.get("notes", [])]
    if mu:
        foot.append('<span class="mu">' + "<br>".join(mu) + "</span>")
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>'
            f'<div class="c"><h1>NBA {date[4:6]}/{date[6:8]} · Assists × Points SGP Fair Values</h1>'
            f'<div class="sub">DraftKings FVs + shrunk PTS/AST correlation via Gaussian copula</div><table>'
            '<tr><th></th><th></th><th></th><th class="g g1" colspan="3">Ast Under + Pts Over</th>'
            '<th class="g g2 sep" colspan="3">Ast Over + Pts Under</th></tr>'
            '<tr><th>Player</th><th class="nt">PTS/AST r</th><th class="nt">combo binary</th>'
            '<th>Legs</th><th>FV</th><th>Fair</th><th class="sep">Legs</th><th>FV</th><th>Fair</th></tr>'
            + "".join(body) + '</table><div class="foot">' + "<br>".join(foot) + "</div></div></body></html>")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("players")
    s.add_argument("--min-ast", type=float, default=5)
    s.add_argument("--min-pts", type=float, default=17)
    s.add_argument("--max-r", type=float, default=0)
    s.set_defaults(fn=players)
    s = sub.add_parser("fv")
    s.add_argument("legs")
    s.add_argument("--card")
    s.set_defaults(fn=fv)
    a = ap.parse_args()
    a.fn(a)
