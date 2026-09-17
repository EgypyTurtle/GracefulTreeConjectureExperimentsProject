"""Function-level profile of the compressed solver on real edge64 cases.

The aggregate distribution is bimodal: most cases solve in milliseconds and a
hard minority burns the entire time budget.  A plain mean therefore says nothing
about where to optimize, so this profiles a sample and reports the functions that
actually dominate, ranked by total time, separately for the fast majority and
for the budget-burning tail.

Usage:
    python src/diag_cprofile_stage.py --start 0 --count 1500
    python src/diag_cprofile_stage.py --start 3825152 --count 400 --tail-only
"""

from __future__ import annotations

import argparse
import cProfile
import csv
import hashlib
import io
import json
import pstats
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


def collect(start: int, count: int, stride: int) -> list[dict[str, str]]:
    rows = []
    with CASE_MANIFEST.open("r", newline="", encoding="utf-8") as handle:
        for index, entry in enumerate(csv.DictReader(handle)):
            if index < start:
                continue
            if len(rows) >= count:
                break
            if (index - start) % stride:
                continue
            rows.append(entry)
    return rows


def seed_for(case_id: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(f"compressed_0.5s:{case_id}".encode("ascii"), digest_size=8).digest(), "big"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=1_500)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--budget", type=float, default=0.5)
    parser.add_argument("--tail-only", action="store_true", help="profile only cases that exhaust the budget")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--tag", default="cp")
    args = parser.parse_args()

    rows = collect(args.start, args.count, args.stride)
    cache_db = str(CACHE_DIR / f"cp_extension_{args.tag}.sqlite3")

    # First pass: classify cases as fast or budget-burning.
    selected = []
    started = time.time()
    for entry in rows:
        case_id = entry["case_id"]
        t0 = time.time()
        result = run_one(case_id, "compressed", args.budget, cache_db, seed_for(case_id))
        elapsed = time.time() - t0
        burning = elapsed >= 0.8 * args.budget
        if args.tail_only and not burning:
            continue
        if not args.tail_only and burning:
            continue
        selected.append((case_id, result.get("strategy"), elapsed))
    print(f"classified {len(rows)} cases in {time.time()-started:.1f}s; profiling {len(selected)}", flush=True)

    if not selected:
        print(json.dumps({"note": "no cases matched the filter", "scanned": len(rows)}, indent=2))
        return 0

    profiler = cProfile.Profile()
    profiler.enable()
    for case_id, _strategy, _elapsed in selected:
        run_one(case_id, "compressed", args.budget, cache_db, seed_for(case_id))
    profiler.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("tottime")
    stats.print_stats(args.top)
    text = stream.getvalue()
    print(text)

    # pstats.stats maps func -> (cc, nc, tt, ct, callers).
    ranked = sorted(stats.stats.items(), key=lambda item: item[1][2], reverse=True)
    top = [
        {
            "function": f"{func[2]}:{func[0]}" if len(func) > 2 else str(func),
            "tottime_s": round(data[2], 4),
            "cumtime_s": round(data[3], 4),
            "ncalls": data[1],
        }
        for func, data in ranked[: args.top]
    ]
    print(json.dumps({"profiled_cases": len(selected), "budget": args.budget, "top_by_tottime": top}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
