"""Diagnostic: reproduce the edge64 full-production stall.

The compressed_0.5s stage stopped after writing batch_003824640_003825152.csv.
The next batch (index 7472, cases 3825152..3825663) was never written.
This script replays exactly those cases, one at a time, in a subprocess-safe
way, with generous wall-clock accounting, and reports any case that exceeds the
expected budget by a large factor.

Usage:
    python src/diag_stuck_batch.py --start 3825152 --count 512
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge64_baseline import run_one  # noqa: E402

CASE_MANIFEST = ROOT / "results" / "edge64_baseline_v1" / "edge64_case_manifest.csv"
CACHE_DIR = ROOT / "results" / "edge64_full_production_v1" / "case_results" / "compressed_0.5s"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=3_825_152)
    parser.add_argument("--count", type=int, default=512)
    parser.add_argument("--budget", type=float, default=0.5)
    parser.add_argument("--alarm", type=float, default=20.0)
    parser.add_argument("--cache-tag", default="diag")
    args = parser.parse_args()

    rows = []
    with CASE_MANIFEST.open("r", newline="", encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            if index < args.start:
                continue
            if index >= args.start + args.count:
                break
            rows.append(row)

    print(f"replaying {len(rows)} cases from index {args.start}", flush=True)
    cache_db = str(CACHE_DIR / f"diag_extension_{args.cache_tag}.sqlite3")
    slow: list[dict[str, object]] = []
    for offset, row in enumerate(rows):
        case_id = row["case_id"]
        seed = int.from_bytes(
            hashlib.blake2b(f"compressed_0.5s:{case_id}".encode("ascii"), digest_size=8).digest(),
            "big",
        )
        started = time.time()
        result = run_one(case_id, "compressed", args.budget, cache_db, seed)
        elapsed = time.time() - started
        if elapsed > args.alarm:
            record = {
                "offset": offset,
                "index": args.start + offset,
                "case_id": case_id,
                "elapsed_seconds": round(elapsed, 3),
                "solved": result.get("solved"),
                "strategy": result.get("strategy"),
                "nodes": result.get("nodes"),
                "error": result.get("error"),
            }
            slow.append(record)
            print("SLOW " + json.dumps(record), flush=True)
        if offset % 64 == 0:
            print(f"  progress {offset}/{len(rows)} elapsed={elapsed:.3f}s", flush=True)

    print(json.dumps({"replayed": len(rows), "slow_or_hung": slow}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
