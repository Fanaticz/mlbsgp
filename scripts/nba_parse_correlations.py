#!/usr/bin/env python3
"""NBA correlations xlsx parser + archiver.

Reads an xlsx file (from stdin or --input-path), validates the 18-column
schema, filters to same-player rows only, normalizes types, and writes:

  <out-dir>/correlations_current.json.gz      — {season, uploaded_at, entries, by_player}
  <out-dir>/correlations_meta.json            — {uploaded_at, season, source_filename, ...}
  <out-dir>/correlations_history/<ts>.json.gz — previous current (last 7 kept)

Exits 0 in all cases and writes a single JSON line to stdout describing the
result. Non-zero exit would be a server/exec error; callers should treat
stdout `ok:false` as a user-facing validation failure.

Invocation (upload):
  python3 nba_parse_correlations.py \
    --out-dir /data/nba \
    --source-filename foo.xlsx < foo.xlsx

Invocation (rollback):
  python3 nba_parse_correlations.py --action rollback --out-dir /data/nba

NBA v1 scope: same-player only. Teammate/cross-player rows are rejected at
ingestion — we don't have a joint-probability model for them yet and silently
accepting them would poison downstream candidate enumeration.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import os
import shutil
import sys
from typing import Any

# Exact 18-column schema from the user-provided spec. Header match is strict
# (case-sensitive, whitespace-stripped). Missing any of these triggers a fatal
# error — we refuse to partially-parse a file whose schema we don't recognize.
REQUIRED_COLUMNS = [
    "Player_1", "Prop_1", "Side_1",
    "Player_2", "Prop_2", "Side_2",
    "Line_1", "Line_2",
    "Correlation", "Adjusted_Correlation",
    "P_Value", "Total_Games",
    "Hit_Rate_1", "Hit_Rate_2",
    "Independent_Prob", "Adjusted_Prob", "Empirical_Prob",
    "Type",
]

SCHEMA_VERSION = 1
MAX_BYTES = 10 * 1024 * 1024
HISTORY_KEEP = 7


def _err(msg: str, details: str = "") -> None:
    print(json.dumps({"ok": False, "error": msg, "details": details}))
    sys.exit(0)


def _norm_side(s: Any) -> str | None:
    """Return canonical lowercase 'over'/'under' or None if unparseable."""
    if s is None:
        return None
    s = str(s).strip().lower()
    if s in ("over", "o"):
        return "over"
    if s in ("under", "u"):
        return "under"
    return None


def _norm_num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _derive_season(today: dt.date | None = None) -> str:
    """NBA season label, e.g. '2025-26'. Season starts in Oct, so Jan-Jul uses
    the season that started the prior October."""
    today = today or dt.date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def parse_xlsx(buf: bytes) -> tuple[list[dict], dict]:
    """Parse xlsx bytes to (entries, stats). Raises ValueError for fatal schema
    errors (missing columns, unreadable file). Row-level rejects are counted
    in stats['rejected_reasons'] but do not raise."""
    try:
        import openpyxl
    except ImportError as e:
        raise ValueError(f"openpyxl not installed on server: {e}")

    try:
        wb = openpyxl.load_workbook(io.BytesIO(buf), read_only=True, data_only=True)
    except Exception as e:
        raise ValueError(f"Could not open xlsx: {e}")

    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        raise ValueError("xlsx is empty")

    col_idx: dict[str, int] = {}
    for i, h in enumerate(header):
        if h is None:
            continue
        col_idx[str(h).strip()] = i

    for c in REQUIRED_COLUMNS:
        if c not in col_idx:
            raise ValueError(f"Missing required column: {c}")

    entries: list[dict] = []
    rejected_reasons: dict[str, int] = {}
    players: set[str] = set()

    def reject(reason: str) -> None:
        rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1

    for raw in rows_iter:
        if raw is None:
            continue
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in raw):
            continue

        def g(col: str) -> Any:
            idx = col_idx[col]
            return raw[idx] if idx < len(raw) else None

        p1 = str(g("Player_1") or "").strip()
        p2 = str(g("Player_2") or "").strip()

        # NBA v1: same-player only. Cross-player rows are unsupported.
        if not p1 or not p2:
            reject("missing player name")
            continue
        if p1 != p2:
            reject("cross-player row (v1 is same-player only)")
            continue

        side1 = _norm_side(g("Side_1"))
        side2 = _norm_side(g("Side_2"))
        if not side1 or not side2:
            reject("invalid Side (must be Over/Under)")
            continue

        prop1 = str(g("Prop_1") or "").strip()
        prop2 = str(g("Prop_2") or "").strip()
        if not prop1 or not prop2:
            reject("missing Prop")
            continue

        line1 = _norm_num(g("Line_1"))
        line2 = _norm_num(g("Line_2"))
        if line1 is None or line2 is None:
            reject("non-numeric Line")
            continue

        n_games_f = _norm_num(g("Total_Games"))
        if n_games_f is None or n_games_f < 1:
            reject("Total_Games < 1")
            continue
        n_games = int(n_games_f)

        # Empirical_Prob is THE joint probability we trust. Adjusted_Prob from
        # the xlsx is explicitly rejected by the user — it's a black-box
        # adjustment that produces implausible values at small n. We still
        # carry p_independent (Independent_Prob) so the UI can flag
        # implausible gap badges.
        empirical = _norm_num(g("Empirical_Prob"))
        if empirical is None or empirical < 0 or empirical > 1:
            reject("Empirical_Prob null/out-of-range")
            continue

        p_value = _norm_num(g("P_Value"))
        if p_value is None or p_value < 0 or p_value > 1:
            reject("P_Value null/out-of-range")
            continue

        ttype = str(g("Type") or "").strip()

        # r_adj is the Adjusted_Correlation column; raw Correlation is kept
        # too so diagnostics and future blending work can compare the two.
        r_adj = _norm_num(g("Adjusted_Correlation"))
        r_raw = _norm_num(g("Correlation"))
        hit_rate_1 = _norm_num(g("Hit_Rate_1"))
        hit_rate_2 = _norm_num(g("Hit_Rate_2"))
        p_independent = _norm_num(g("Independent_Prob"))
        adjusted_prob_excel = _norm_num(g("Adjusted_Prob"))  # carried, NOT used for joint

        players.add(p1)
        entries.append({
            "player": p1,
            "leg1": {"prop": prop1, "side": side1, "line": line1},
            "leg2": {"prop": prop2, "side": side2, "line": line2},
            "r_adj": r_adj,
            "r_raw": r_raw,
            "p_value": p_value,
            "n_games": n_games,
            "hit_rate_1": hit_rate_1,
            "hit_rate_2": hit_rate_2,
            "p_joint": empirical,
            "p_independent": p_independent,
            "_adjusted_prob_excel": adjusted_prob_excel,
            "type": ttype or None,
        })

    return entries, {
        "rejected_rows": sum(rejected_reasons.values()),
        "rejected_reasons": rejected_reasons,
        "distinct_players": len(players),
    }


def build_payload(entries: list[dict], now: dt.datetime) -> dict:
    by_player: dict[str, list[int]] = {}
    for i, e in enumerate(entries):
        by_player.setdefault(e["player"], []).append(i)
    return {
        "schema_version": SCHEMA_VERSION,
        "season": _derive_season(now.date()),
        "uploaded_at": now.isoformat().replace("+00:00", "Z"),
        "entries": entries,
        "by_player": by_player,
    }


def write_outputs(entries: list[dict], stats: dict, out_dir: str,
                  source_filename: str, now: dt.datetime) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    history_dir = os.path.join(out_dir, "correlations_history")
    os.makedirs(history_dir, exist_ok=True)

    current_path = os.path.join(out_dir, "correlations_current.json.gz")
    meta_path = os.path.join(out_dir, "correlations_meta.json")

    # Archive previous current before overwriting so rollback has something to
    # restore. Skips silently on cold start (no current yet).
    if os.path.exists(current_path):
        ts = now.strftime("%Y-%m-%d_%H%M%S")
        shutil.copy2(current_path, os.path.join(history_dir, f"correlations_{ts}.json.gz"))
        hist = sorted(
            (f for f in os.listdir(history_dir) if f.endswith(".json.gz")),
            reverse=True,
        )
        for old in hist[HISTORY_KEEP:]:
            try:
                os.remove(os.path.join(history_dir, old))
            except OSError:
                pass

    payload = build_payload(entries, now)
    with gzip.open(current_path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))

    meta = {
        "schema_version": SCHEMA_VERSION,
        "uploaded_at": payload["uploaded_at"],
        "season": payload["season"],
        "source_filename": source_filename,
        "row_count": len(entries),
        "distinct_players": stats["distinct_players"],
        "rejected_rows": stats["rejected_rows"],
        "rejected_reasons": stats["rejected_reasons"],
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta


def rollback(out_dir: str) -> dict:
    history_dir = os.path.join(out_dir, "correlations_history")
    if not os.path.isdir(history_dir):
        return {"ok": False, "error": "No history directory"}
    files = sorted(
        (f for f in os.listdir(history_dir) if f.endswith(".json.gz")),
        reverse=True,
    )
    if not files:
        return {"ok": False, "error": "No history entries to roll back to"}
    newest = files[0]
    src = os.path.join(history_dir, newest)
    dst = os.path.join(out_dir, "correlations_current.json.gz")
    shutil.copy2(src, dst)
    try:
        with gzip.open(dst, "rt", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        players = {e.get("player") for e in entries if e.get("player")}
        meta = {
            "schema_version": data.get("schema_version", SCHEMA_VERSION),
            "uploaded_at": data.get("uploaded_at"),
            "season": data.get("season") or _derive_season(),
            "source_filename": f"(rolled back from {newest})",
            "row_count": len(entries),
            "distinct_players": len(players),
            "rejected_rows": 0,
            "rejected_reasons": {},
        }
        with open(os.path.join(out_dir, "correlations_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return {"ok": True, "restored_from": newest, "meta": meta}
    except Exception as e:
        return {"ok": False, "error": f"Restore succeeded but meta rebuild failed: {e}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.environ.get("NBA_DATA_DIR", "/data/nba"))
    ap.add_argument("--source-filename", default="uploaded.xlsx")
    ap.add_argument("--action", default="upload", choices=["upload", "rollback"])
    ap.add_argument("--input-path", default=None,
                    help="Read xlsx bytes from this path instead of stdin.")
    args = ap.parse_args()

    if args.action == "rollback":
        print(json.dumps(rollback(args.out_dir)))
        return

    if args.input_path:
        with open(args.input_path, "rb") as f:
            buf = f.read()
    else:
        buf = sys.stdin.buffer.read()

    if not buf:
        _err("Empty upload body")
    if len(buf) > MAX_BYTES:
        _err(f"File too large: {len(buf)} bytes (max {MAX_BYTES})")

    try:
        entries, stats = parse_xlsx(buf)
    except ValueError as e:
        _err(str(e))
        return

    if not entries:
        _err("No valid rows parsed from xlsx",
             details=json.dumps(stats.get("rejected_reasons") or {}))

    now = dt.datetime.now(dt.timezone.utc)
    try:
        meta = write_outputs(entries, stats, args.out_dir, args.source_filename, now)
    except OSError as e:
        _err(f"Could not write output: {e}")
        return

    print(json.dumps({
        "ok": True,
        "uploaded_at": meta["uploaded_at"],
        "season": meta["season"],
        "row_count": meta["row_count"],
        "distinct_players": meta["distinct_players"],
        "rejected_rows": meta["rejected_rows"],
        "rejected_reasons": meta["rejected_reasons"],
    }))


if __name__ == "__main__":
    main()
