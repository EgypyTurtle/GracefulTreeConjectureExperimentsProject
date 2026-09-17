"""Report aggregate progress of the sharded edge64 stage-1 run.

Reads every per-shard heartbeat and progress file and prints one summary line per
shard plus an aggregate.  Safe to run while the shards are live: it only reads.

Usage:
    python src/diag_shard_status.py
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "edge64_full_production_v1"
STAGE = "compressed_0.5s"
TOTAL_CASES = 10_040_677

PATTERN = re.compile(r"stage=(\S+) shard=(\d+)/(\d+) processed=(\d+) solved=(\d+) survivors=(\d+) range=(\d+)-(\d+) reused=(\d+)")


def main() -> int:
    now = time.time()
    rows = []
    for path in sorted(glob.glob(str(OUT / "heartbeat.shard*.log"))):
        shard = os.path.basename(path).replace("heartbeat.shard", "").replace(".log", "")
        last = None
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                match = PATTERN.search(line)
                if match:
                    last = match
        if last is None:
            rows.append((shard, 0, 0, 0, None))
            continue
        age = now - os.path.getmtime(path)
        rows.append((shard, int(last.group(4)), int(last.group(5)), int(last.group(6)), age))

    print(f"{'shard':>6s} {'processed':>11s} {'solved':>11s} {'survivors':>10s} {'hb_age_s':>9s}")
    print("-" * 54)
    tp = ts = tv = 0
    stale = []
    for shard, processed, solved, survivors, age in rows:
        age_s = f"{age:.0f}" if age is not None else "no-output"
        print(f"{shard:>6s} {processed:>11,d} {solved:>11,d} {survivors:>10,d} {age_s:>9s}")
        tp += processed
        ts += solved
        tv += survivors
        if age is not None and age > 900:
            stale.append(shard)
    print("-" * 54)
    print(f"{'TOTAL':>6s} {tp:>11,d} {ts:>11,d} {tv:>10,d}")
    pct = 100.0 * tp / TOTAL_CASES if TOTAL_CASES else 0.0
    print(f"\naggregate progress: {tp:,} / {TOTAL_CASES:,} = {pct:.2f}%")
    print(f"solve rate: {100.0 * ts / tp:.2f}%" if tp else "solve rate: n/a")
    batches = len(glob.glob(str(OUT / "case_results" / STAGE / "batch_*.csv")))
    print(f"batch files written: {batches:,}")
    if stale:
        print(f"\nWARNING: no heartbeat for >900s in shard(s): {', '.join(stale)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
