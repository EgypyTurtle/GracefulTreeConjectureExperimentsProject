"""Run one solver variant over a case sample and report metrics.

Invoked as a subprocess by ``diag_ab_compare.py`` so that each variant starts
from a clean module state.  This matters: the pendant-extension in-memory cache
is a module-level dict, and letting it survive between variants silently makes
the later variant look orders of magnitude faster than it is.

Usage:
    python src/diag_ab_run.py --solver-root . --label optimized --start ... --count ... --out x.json
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
CASE_MANIFEST = ROOT / "results" / "edge64_baseline_v1" / "edge64_case_manifest.csv"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solver-root", type=Path, default=ROOT)
    parser.add_argument("--label", default="variant")
    parser.add_argument("--mode", choices=("solve_tree", "run_one"), default="solve_tree")
    parser.add_argument("--disable-persistent-cache", action="store_true")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--budget", type=float, default=0.5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    solver_root = args.solver_root.resolve()
    src = solver_root / "src"
    sys.path.insert(0, str(src))

    import graceful_tree as gt  # noqa: E402
    import edge64_baseline as eb  # noqa: E402

    if args.disable_persistent_cache:
        gt.open_pendant_extension_cache = lambda path: None
        gt.persistent_cache_get = lambda key, size: None
        gt.persistent_cache_put = lambda key, labels: False

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

    cache_db = str(ROOT / "results" / "_diag" / f"ab_{args.label}.sqlite3")
    times: list[float] = []
    total_nodes = 0
    solved = 0
    invalid = 0
    strategies: dict[str, int] = {}
    started = time.perf_counter()

    for entry in rows:
        case_id = entry["case_id"]
        seed = int.from_bytes(
            hashlib.blake2b(f"compressed_0.5s:{case_id}".encode("ascii"), digest_size=8).digest(), "big"
        )
        if args.mode == "run_one":
            t0 = time.perf_counter()
            result = eb.run_one(case_id, "compressed", args.budget, cache_db, seed)
            times.append(time.perf_counter() - t0)
            total_nodes += int(result.get("nodes") or 0)
            strategies[result.get("strategy", "?")] = strategies.get(result.get("strategy", "?"), 0) + 1
            solved += int(result.get("solved") or 0)
        else:
            n, edges = eb.reconstruct_named_five_leaf_case(case_id)
            adj = gt.build_adj(n, edges)
            opted = eb.options("compressed", args.budget, cache_db)
            t0 = time.perf_counter()
            labels, stats = gt.solve_tree(adj, opted, seed=seed)
            times.append(time.perf_counter() - t0)
            total_nodes += int(stats.nodes or 0)
            strategies[stats.strategy] = strategies.get(stats.strategy, 0) + 1
            if labels is not None:
                if gt.verify_labeling(edges, labels):
                    solved += 1
                else:
                    invalid += 1

    ordered = sorted(times)
    payload = {
        "label": args.label,
        "solver_root": str(solver_root),
        "mode": args.mode,
        "disable_persistent_cache": args.disable_persistent_cache,
        "cases": len(rows),
        "start": args.start,
        "stride": args.stride,
        "budget": args.budget,
        "solved": solved,
        "invalid": invalid,
        "survivors": len(rows) - solved,
        "wall_s": round(sum(times), 4),
        "wall_incl_setup_s": round(time.perf_counter() - started, 4),
        "mean_ms": round(1000 * statistics.fmean(times), 4) if times else 0.0,
        "p50_ms": round(1000 * ordered[len(ordered) // 2], 4) if ordered else 0.0,
        "p95_ms": round(1000 * ordered[int(0.95 * len(ordered))], 4) if ordered else 0.0,
        "max_ms": round(1000 * ordered[-1], 4) if ordered else 0.0,
        "total_nodes": total_nodes,
        "nodes_per_s": round(total_nodes / max(sum(times), 1e-9), 1),
        "strategies": strategies,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
