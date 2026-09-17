"""Ablate compressed-method knobs on a fixed case sample.

The compressed stage spends about half its search nodes on the branch fallback,
which runs only when the pendant reduction fails to produce an extensible base.
This script measures whether widening the reduction search (more candidate
paths, a larger base node budget, a larger in-memory cache) turns those cases
into cheap pendant solves, and what it costs on the cases that already succeed.

Usage:
    python src/diag_ablate_compressed.py --start 3825152 --count 500
"""

from __future__ import annotations

import argparse
import collections
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

from edge64_baseline import options, reconstruct_named_five_leaf_case  # noqa: E402
from graceful_tree import solve_tree, verify_labeling  # noqa: E402

CASE_MANIFEST = ROOT / "results" / "edge64_baseline_v1" / "edge64_case_manifest.csv"
CACHE_DIR = ROOT / "results" / "edge64_full_production_v1" / "case_results" / "compressed_0.5s"

# (label, try_all_paths, extension_nodes, cache_size)
VARIANTS = (
    ("baseline", False, 2_000, 100_000),
    ("nodes_5k", False, 5_000, 100_000),
    ("nodes_10k", False, 10_000, 100_000),
    ("nodes_20k", False, 20_000, 100_000),
    ("nodes_50k", False, 50_000, 100_000),
    ("nodes_20k_cache0", False, 20_000, 0),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=3_825_152)
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--budget", type=float, default=0.5)
    parser.add_argument("--variants", default="", help="comma-separated subset of variant labels")
    args = parser.parse_args()

    wanted = {v.strip() for v in args.variants.split(",") if v.strip()}
    variants = [v for v in VARIANTS if not wanted or v[0] in wanted]

    rows = []
    with CASE_MANIFEST.open("r", newline="", encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            if index < args.start:
                continue
            if index >= args.start + args.count:
                break
            rows.append(row)

    prepared = []
    for row in rows:
        n, edges = reconstruct_named_five_leaf_case(row["case_id"])
        seed = int.from_bytes(
            hashlib.blake2b(f"compressed_0.5s:{row['case_id']}".encode("ascii"), digest_size=8).digest(),
            "big",
        )
        prepared.append((row["case_id"], n, edges, seed))

    summary = {}
    for label, try_all, nodes, cache_size in variants:
        cache_db = str(CACHE_DIR / f"ablate_{label}.sqlite3")
        times: list[float] = []
        strategies: collections.Counter[str] = collections.Counter()
        nodes_by_strategy: collections.Counter[str] = collections.Counter()
        solved = 0
        bad = 0
        t_start = time.time()
        for case_id, n, edges, seed in prepared:
            opt = options("compressed", args.budget, cache_db)
            opt.extension_try_all_paths = try_all
            opt.extension_fastpath_nodes = nodes
            opt.extension_cache_size = cache_size
            adj = [[] for _ in range(n)]
            for u, v in edges:
                adj[u].append(v)
                adj[v].append(u)
            t0 = time.time()
            labels, stats = solve_tree(adj, opt, seed=seed)
            times.append(time.time() - t0)
            strategies[stats.strategy] += 1
            nodes_by_strategy[stats.strategy] += int(stats.nodes)
            if labels is not None:
                if verify_labeling(edges, labels):
                    solved += 1
                else:
                    bad += 1
        wall = time.time() - t_start
        ordered = sorted(times)
        summary[label] = {
            "solved": solved,
            "invalid_certificate": bad,
            "survivors": len(prepared) - solved,
            "wall_seconds": round(wall, 3),
            "mean_ms": round(1000 * statistics.fmean(times), 3) if times else 0.0,
            "p50_ms": round(1000 * ordered[len(ordered) // 2], 3) if ordered else 0.0,
            "p90_ms": round(1000 * ordered[int(0.90 * len(ordered))], 3) if ordered else 0.0,
            "strategies": dict(strategies.most_common()),
            "nodes_by_strategy": dict(nodes_by_strategy.most_common()),
            "total_nodes": sum(nodes_by_strategy.values()),
        }
        print(f"{label}: solved={solved}/{len(prepared)} wall={wall:.1f}s", flush=True)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
