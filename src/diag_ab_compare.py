"""Controlled A/B of the compressed solver against the pre-optimization revision.

Loads two copies of ``graceful_tree`` (the working tree and a baseline worktree)
as isolated modules and runs the identical cases through both, so the only
difference measured is the solver code.  Cases go through ``solve_tree``
directly rather than ``run_one`` so that case reconstruction and certificate
verification -- which are identical in both revisions -- do not dilute the
comparison.

Variants:
  baseline            baseline code, persistent cache on (what production used)
  baseline_nocache    baseline code, persistent cache disabled by forcing the
                      module's connection to stay unopened
  optimized           working-tree code

Correctness is checked by verifying every certificate each variant returns.

Usage:
    python src/diag_ab_compare.py --baseline-root ../_baseline_wt --start 3825152 --count 400
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
CASE_MANIFEST = ROOT / "results" / "edge64_baseline_v1" / "edge64_case_manifest.csv"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_cases(start: int, count: int, stride: int) -> list[dict[str, str]]:
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


def run_variant(gt, eb, rows, budget: float, cache_db: str, disable_cache: bool) -> dict[str, object]:
    if disable_cache:
        # Force every persistent-cache entry point to no-op without editing the
        # baseline source: _PENDANT_EXTENSION_DB is set to None, but "None" is a
        # valid sentinel for "not open", so wrap the public helpers instead.
        gt.open_pendant_extension_cache = lambda path: None
        gt.persistent_cache_get = lambda key, size: None
        gt.persistent_cache_put = lambda key, labels: False

    times: list[float] = []
    total_nodes = 0
    solved = 0
    bad = 0
    strategies: dict[str, int] = {}
    for entry in rows:
        case_id = entry["case_id"]
        n, edges = eb.reconstruct_named_five_leaf_case(case_id)
        adj = gt.build_adj(n, edges)
        seed = int.from_bytes(
            hashlib.blake2b(f"compressed_0.5s:{case_id}".encode("ascii"), digest_size=8).digest(), "big"
        )
        opted = eb.options("compressed", budget, cache_db)
        t0 = time.perf_counter()
        labels, stats = gt.solve_tree(adj, opted, seed=seed)
        times.append(time.perf_counter() - t0)
        total_nodes += int(stats.nodes or 0)
        strategies[stats.strategy] = strategies.get(stats.strategy, 0) + 1
        if labels is not None:
            if gt.verify_labeling(edges, labels):
                solved += 1
            else:
                bad += 1
    ordered = sorted(times)
    return {
        "solved": solved,
        "invalid": bad,
        "cases": len(rows),
        "survivors": len(rows) - solved,
        "wall_s": round(sum(times), 3),
        "mean_ms": round(1000 * statistics.fmean(times), 3) if times else 0.0,
        "p50_ms": round(1000 * ordered[len(ordered) // 2], 3) if ordered else 0.0,
        "p95_ms": round(1000 * ordered[int(0.95 * len(ordered))], 3) if ordered else 0.0,
        "total_nodes": total_nodes,
        "strategies": strategies,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--budget", type=float, default=0.5)
    parser.add_argument("--tag", default="ab")
    args = parser.parse_args()

    sys.path.insert(0, str(SRC))
    base_root = args.baseline_root.resolve()

    opt_gt = load_module("opt_graceful_tree", SRC / "graceful_tree.py")
    opt_eb = load_module("opt_edge64_baseline", SRC / "edge64_baseline.py")
    base_gt = load_module("base_graceful_tree", base_root / "src" / "graceful_tree.py")
    base_eb = load_module("base_edge64_baseline", base_root / "src" / "edge64_baseline.py")

    rows = load_cases(args.start, args.count, args.stride)
    print(f"cases: {len(rows)} (start={args.start}, stride={args.stride}, budget={args.budget}s)", flush=True)

    scratch = ROOT / "results" / "_diag"
    scratch.mkdir(parents=True, exist_ok=True)
    results = {}
    for label, gt, eb, disable in (
        ("baseline", base_gt, base_eb, False),
        ("baseline_nocache", base_gt, base_eb, True),
        ("optimized", opt_gt, opt_eb, True),
    ):
        db = str(scratch / f"ab_{label}_{args.tag}.sqlite3")
        for ext in ("", "-wal", "-shm"):
            Path(db + ext).unlink(missing_ok=True)
        t0 = time.time()
        results[label] = run_variant(gt, eb, rows, args.budget, db, disable)
        print(f"  {label:18s} solved={results[label]['solved']}/{len(rows)} wall={results[label]['wall_s']}s "
              f"({time.time()-t0:.1f}s incl. setup)", flush=True)

    print()
    header = f"{'variant':18s} {'solved':>9s} {'invalid':>8s} {'wall_s':>9s} {'mean_ms':>9s} {'p50_ms':>8s} {'p95_ms':>8s} {'nodes':>12s}"
    print(header)
    print("-" * len(header))
    for label, data in results.items():
        print(f"{label:18s} {data['solved']:>4d}/{data['cases']:<4d} {data['invalid']:>8d} "
              f"{data['wall_s']:>9.2f} {data['mean_ms']:>9.2f} {data['p50_ms']:>8.2f} {data['p95_ms']:>8.2f} "
              f"{data['total_nodes']:>12,d}")

    base = results["baseline_nocache"]
    opt = results["optimized"]
    print()
    print("optimized vs baseline_nocache:")
    for key in ("solved", "wall_s", "mean_ms", "p50_ms", "p95_ms", "total_nodes"):
        a, b = base[key], opt[key]
        pct = f"{100.0*(b-a)/a:+.1f}%" if a else "n/a"
        print(f"  {key:14s} {a} -> {b}   {pct}")
    print()
    print("strategy mixes:")
    for label, data in results.items():
        print(f"  {label:18s} {json.dumps(data['strategies'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
