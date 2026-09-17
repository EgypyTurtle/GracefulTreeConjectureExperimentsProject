"""Profile the compressed_0.5s stage: where does the budget actually go?

Samples cases from the frozen edge64 manifest, runs the production worker on
them, and reports the strategy mix plus the per-case wall time distribution.
Hard (timeout-bounded) cases are the ones that dominate stage cost, so the
script also reports which strategies those cases land on.

Usage:
    python src/diag_profile_stage.py --start 3825152 --count 2000
"""

from __future__ import annotations

import argparse
import csv
import collections
import hashlib
import json
import statistics
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
    parser.add_argument("--count", type=int, default=2_000)
    parser.add_argument("--budget", type=float, default=0.5)
    parser.add_argument("--cache-tag", default="prof")
    parser.add_argument("--nodes", type=int, default=None, help="override extension_fastpath_nodes")
    args = parser.parse_args()

    rows = []
    with CASE_MANIFEST.open("r", newline="", encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            if index < args.start:
                continue
            if index >= args.start + args.count:
                break
            rows.append(row)

    cache_db = str(CACHE_DIR / f"prof_extension_{args.cache_tag}.sqlite3")
    if args.nodes is not None:
        import edge64_baseline as _eb

        _orig_options = _eb.options

        def _patched(method, time_limit, cache_db_arg, adaptive=False):
            opt = _orig_options(method, time_limit, cache_db_arg, adaptive)
            opt.extension_fastpath_nodes = args.nodes
            return opt

        _eb.options = _patched

    times: list[float] = []
    strategies: collections.Counter[str] = collections.Counter()
    nodes_by_strategy: collections.Counter[str] = collections.Counter()
    solved = 0
    budget_hits = 0
    started = time.time()

    for offset, row in enumerate(rows):
        case_id = row["case_id"]
        seed = int.from_bytes(
            hashlib.blake2b(f"compressed_0.5s:{case_id}".encode("ascii"), digest_size=8).digest(),
            "big",
        )
        t0 = time.time()
        result = run_one(case_id, "compressed", args.budget, cache_db, seed)
        elapsed = time.time() - t0
        times.append(elapsed)
        strategy = str(result.get("strategy") or "?")
        strategies[strategy] += 1
        nodes_by_strategy[strategy] += int(result.get("nodes") or 0)
        solved += int(result.get("solved") or 0)
        if elapsed >= args.budget * 0.9:
            budget_hits += 1
        if offset and offset % 500 == 0:
            print(f"  {offset}/{len(rows)} wall={time.time()-started:.1f}s", flush=True)

    wall = time.time() - started
    times_sorted = sorted(times)
    def pct(p: float) -> float:
        if not times_sorted:
            return 0.0
        return times_sorted[min(len(times_sorted) - 1, int(p * len(times_sorted)))]

    report = {
        "cases": len(rows),
        "budget_seconds": args.budget,
        "solved": solved,
        "survivors": len(rows) - solved,
        "budget_hits": budget_hits,
        "wall_seconds": round(wall, 3),
        "case_seconds_total": round(sum(times), 3),
        "mean_ms": round(1000 * statistics.fmean(times), 3) if times else 0.0,
        "p50_ms": round(1000 * pct(0.50), 3),
        "p90_ms": round(1000 * pct(0.90), 3),
        "p99_ms": round(1000 * pct(0.99), 3),
        "max_ms": round(1000 * max(times), 3) if times else 0.0,
        "strategies": dict(strategies.most_common()),
        "nodes_by_strategy": dict(nodes_by_strategy.most_common()),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
