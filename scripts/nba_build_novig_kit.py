#!/usr/bin/env python3
"""Rebuild novig-kit/pts3_r.json from public/data/nba_correlations.json.

  python3 scripts/nba_build_novig_kit.py          # the json (daily workflow)
  python3 scripts/nba_build_novig_kit.py --zip    # also share/novig-kit.zip

The kit is a standalone copy of the PTS + 3PM scanner for a local Claude, so
its r file is a snapshot. Run after nba_fetch_correlations.py so the snapshot
follows the daily data.
"""
import json
import os
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KIT = os.path.join(ROOT, "novig-kit")


def main():
    d = json.load(open(os.path.join(ROOT, "public", "data", "nba_correlations.json")))
    players = {}
    for p in sorted(d["players"], key=lambda p: p["name"].lower()):
        r = (p.get("pts_3pm") or {}).get("shrunk", {}).get("r")
        if r is None:
            continue
        players[p["name"]] = {"team": p.get("team_abbr", ""), "r": r, "pts": round(p["pts_mean"], 1),
                              "tpm": round(p["tpm_mean"], 1), "min": round(p["min_mean"], 1)}
    if len(players) < 200:
        raise SystemExit(f"only {len(players)} players with a shrunk PTS-3PM r: leaving the kit alone")
    out = {"generated_at": d["generated_at"],
           "note": "PTS-3PM margin r (shrunk), per player. Gaussian-copula input, NOT the devig-tool r.",
           "players": players}
    with open(os.path.join(KIT, "pts3_r.json"), "w") as f:
        json.dump(out, f, indent=0, ensure_ascii=False)
        f.write("\n")
    print(f"novig-kit/pts3_r.json: {len(players)} players, data {d['generated_at'][:10]}")
    if "--zip" in sys.argv:
        dest = os.path.join(ROOT, "share", "novig-kit.zip")
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ("README.md", "SKILL.md", "scan.py", "pts3_r.json"):
                z.write(os.path.join(KIT, name), f"novig-kit/{name}")
        print(f"share/novig-kit.zip rebuilt ({os.path.getsize(dest):,} bytes)")


if __name__ == "__main__":
    main()
