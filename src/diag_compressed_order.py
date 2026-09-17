"""Run the compressed method with one move ordering, in a fresh process.

Move ordering is selected by mutating the solver module's defaults, and the
pendant-extension in-memory cache is a module-level dict, so two orderings
measured in one process contaminate each other: whichever runs second can hit a
warm cache and report zero nodes.  One ordering per process is the only way to
compare them honestly.

Usage:
    python src/diag_compressed_order.py --order branch_first --start 3825152 --count 300 --out x.json
"""

from __future__ import annotations

import argparse
import csv
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

import graceful_tree as gt  # noqa: E402
from edge64_baseline import options, reconstruct_named_five_leaf_case  # noqa: E402

CASE_MANIFEST = ROOT / "results" / "edge64_baseline_v1" / "edge64_case_manifest.csv"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--nodes", type=int, default=20_000)
    parser.add_argument("--budget", type=float, default=0.5)
    parser.add_argument("--stride", type=int, default=1, help="take every Nth case from --start")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = []
    with CASE_MANIFEST.open("r", newline="", encoding="utf-8") as handle:
        for index, entry in enumerate(csv.DictReader(handle)):
            if index < args.start:
                continue
            if len(rows) >= args.count:
                break
            if (index - args.start) % args.stride:
                continue
            rows.append(entry)

    times: list[float] = []
    nodes = 0
    solved = 0
    invalid = 0
    strategies: dict[str, int] = {}
    started = time.perf_counter()
    for entry in rows:
        case_id = entry["case_id"]
        n, edges = reconstruct_named_five_leaf_case(case_id)
        adj = gt.build_adj(n, edges)
        seed = int.from_bytes(
            hashlib.blake2b(f"compressed_0.5s:{case_id}".encode("ascii"), digest_size=8).digest(), "big"
        )
        opted = options("compressed", args.budget, str(ROOT / "results" / "_diag" / f"co_{args.order}.sqlite3"))
        opted.extension_persistent_cache = False
        opted.extension_fastpath_nodes = args.nodes
        opted.extension_move_order = args.order
        t0 = time.perf_counter()
        labels, stats = gt.solve_tree(adj, opted, seed=seed)
        times.append(time.perf_counter() - t0)
        nodes += int(stats.nodes or 0)
        strategies[stats.strategy] = strategies.get(stats.strategy, 0) + 1
        if labels is not None:
            if gt.verify_labeling(edges, labels):
                solved += 1
            else:
                invalid += 1

    ordered = sorted(times)
    payload = {
        "order": args.order,
        "start": args.start,
        "cases": len(rows),
        "nodes_budget": args.nodes,
        "solved": solved,
        "invalid": invalid,
        "total_nodes": nodes,
        "wall_s": round(sum(times), 4),
        "setup_s": round(time.perf_counter() - started - sum(times), 4),
        "mean_ms": round(1000 * statistics.fmean(times), 4) if times else 0.0,
        "p50_ms": round(1000 * ordered[len(ordered) // 2], 4) if ordered else 0.0,
        "p95_ms": round(1000 * ordered[int(0.95 * len(ordered))], 4) if ordered else 0.0,
        "strategies": strategies,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{args.order:14s} solved={solved}/{len(rows)} nodes={nodes:,} wall={payload['wall_s']}s "
          f"mean={payload['mean_ms']}ms p95={payload['p95_ms']}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
