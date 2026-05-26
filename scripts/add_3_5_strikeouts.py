#!/usr/bin/env python3
"""Append 'Over 3.5 Strikeouts' entries to combo_spec.json.

The frontend looks up correlations by leg name (_findRBinaryIn scans for
matching leg1/leg2 strings), so order within the spec is not functional —
appending is safe and produces a small reviewable diff. Aggregates must
be rebuilt afterwards so the per-pitcher combos_2/combos_3 and per-year
global_2/global_3 arrays include rows for the new pairs.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "combo_spec.json"

NEW_K = "Over 3.5 Strikeouts"
OTHER_K = ["Over 4.5 Strikeouts", "Over 5.5 Strikeouts",
           "Over 6.5 Strikeouts", "Over 7.5 Strikeouts"]
ER  = ["Under 1.5 Earned Runs", "Under 2.5 Earned Runs", "Under 3.5 Earned Runs"]
OUTS= ["Over 14.5 Outs Recorded", "Over 15.5 Outs Recorded",
       "Over 16.5 Outs Recorded", "Over 17.5 Outs Recorded",
       "Over 18.5 Outs Recorded"]
BB  = ["Under 1.5 Walks", "Under 2.5 Walks"]
H   = ["Under 3.5 Hits Allowed", "Under 4.5 Hits Allowed", "Under 5.5 Hits Allowed"]


def main() -> int:
    spec = json.loads(SPEC.read_text())
    pairs = spec["pairs_2"]
    triples = spec["triples_3"]

    existing_pairs = {tuple(sorted(p)) for p in pairs}
    existing_triples = {tuple(sorted(t)) for t in triples}

    new_pairs: list[list[str]] = []
    # K × K: only Y > 3.5 (avoid duplicating already-present 4.5×5.5 etc.)
    for k in OTHER_K:
        new_pairs.append([NEW_K, k])
    # K × every non-K leg, in canonical order (ER, OUTS, BB, H)
    for leg in ER + OUTS + BB + H:
        new_pairs.append([NEW_K, leg])

    new_triples: list[list[str]] = []
    # Mirror the existing K-containing triple patterns:
    # K+ER+OUTS, K+ER+BB, K+ER+H, K+OUTS+BB, K+OUTS+H, K+BB+H
    for er in ER:
        for ou in OUTS: new_triples.append([NEW_K, er, ou])
    for er in ER:
        for bb in BB:   new_triples.append([NEW_K, er, bb])
    for er in ER:
        for h  in H:    new_triples.append([NEW_K, er, h])
    for ou in OUTS:
        for bb in BB:   new_triples.append([NEW_K, ou, bb])
    for ou in OUTS:
        for h  in H:    new_triples.append([NEW_K, ou, h])
    for bb in BB:
        for h  in H:    new_triples.append([NEW_K, bb, h])

    # De-dupe against existing
    appended_pairs = [p for p in new_pairs if tuple(sorted(p)) not in existing_pairs]
    appended_triples = [t for t in new_triples if tuple(sorted(t)) not in existing_triples]

    pairs.extend(appended_pairs)
    triples.extend(appended_triples)

    SPEC.write_text(json.dumps(spec, separators=(", ", ": ")))

    print(f"Appended {len(appended_pairs)} pairs (skipped {len(new_pairs)-len(appended_pairs)} dupes)")
    print(f"Appended {len(appended_triples)} triples (skipped {len(new_triples)-len(appended_triples)} dupes)")
    print(f"Totals now: {len(pairs)} pairs, {len(triples)} triples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
