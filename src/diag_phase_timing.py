"""Phase-level timing harness for the compressed solver.

Reports, per case, how long each phase of the compressed method takes:
case reconstruction, adjacency build, the constructive fast paths, the pendant
reduction plus base search, the extension rebuild, and the branch fallback.

This exists because the aggregate profile is bimodal -- most cases finish in
milliseconds and a hard minority burns the whole budget -- so a mean tells you
nothing about where to optimize.  The rows emitted here are meant to be
aggregated with ``diag_phase_report.py``.

Usage:
    python src/diag_phase_timing.py --start 0 --count 3000 --out results/_diag/phases.csv
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

import graceful_tree as gt  # noqa: E402
from edge64_baseline import options, reconstruct_named_five_leaf_case  # noqa: E402

CASE_MANIFEST = ROOT / "results" / "edge64_baseline_v1" / "edge64_case_manifest.csv"
CACHE_DIR = ROOT / "results" / "edge64_full_production_v1" / "case_results" / "compressed_0.5s"

FIELDS = [
    "case_id",
    "stratum",
    "budget",
    "total_s",
    "reconstruct_s",
    "adj_s",
    "caterpillar_s",
    "unitarm_s",
    "pendant_total_s",
    "base_search_s",
    "rebuild_s",
    "flash_s",
    "fallback_s",
    "solved",
    "strategy",
    "nodes",
    "base_nodes",
    "fallback_nodes",
    "extended_edges",
]


def run_case(case_id: str, stratum: str, budget: float, cache_db: str, seed: int) -> dict[str, object]:
    row: dict[str, object] = {"case_id": case_id, "stratum": stratum, "budget": budget}

    t0 = time.perf_counter()
    n, edges = reconstruct_named_five_leaf_case(case_id)
    t1 = time.perf_counter()
    adj = gt.build_adj(n, edges)
    t2 = time.perf_counter()

    # Constructive fast paths, exactly as solve_tree tries them.
    labels, stats = gt.solve_graceful_caterpillar(adj)
    t3 = time.perf_counter()
    if labels is None:
        labels, stats = gt.solve_graceful_unit_arm_two_branch(adj)
    t4 = time.perf_counter()

    opted = options("compressed", budget, cache_db)
    base_nodes = 0
    fallback_nodes = 0
    pendant_total = 0.0
    base_search = 0.0
    rebuild = 0.0
    fallback_s = 0.0
    extended_edges = 0

    if labels is not None:
        chosen = "caterpillar" if t3 - t2 > 0 and stats.strategy == "caterpillar" else stats.strategy
    else:
        # Instrument the pendant extension by wrapping the two inner calls.  The
        # wrappers do take effect: solve_tree reaches these through the module
        # globals, so patching the module attribute intercepts them.  It works
        # because this harness is single-threaded and single-variant per process;
        # do not reuse the pattern to compare two variants in one process, since
        # the module-level in-memory cache would then leak between them.
        orig_branch = gt.solve_graceful_branch_differences
        marks: list[tuple[str, float]] = []

        def timed_branch(*args, **kwargs):
            t_start = time.perf_counter()
            result = orig_branch(*args, **kwargs)
            t_end = time.perf_counter()
            marks.append(("base" if kwargs.get("fixed_zero_vertex") is not None else "fallback", t_end - t_start))
            return result

        orig_rebuild = gt.rebuild_pendant_extension

        def timed_rebuild(*args, **kwargs):
            t_start = time.perf_counter()
            result = orig_rebuild(*args, **kwargs)
            t_end = time.perf_counter()
            marks.append(("rebuild", t_end - t_start))
            return result

        gt.solve_graceful_branch_differences = timed_branch
        gt.rebuild_pendant_extension = timed_rebuild
        try:
            t5 = time.perf_counter()
            labels, stats = gt.solve_tree(adj, opted, seed=seed)
            t6 = time.perf_counter()
        finally:
            gt.solve_graceful_branch_differences = orig_branch
            gt.rebuild_pendant_extension = orig_rebuild

        pendant_total = (t6 - t5)
        for kind, seconds in marks:
            if kind == "base":
                base_search += seconds
            elif kind == "rebuild":
                rebuild += seconds
            else:
                fallback_s += seconds

    t_end = time.perf_counter()
    row.update(
        {
            "total_s": t_end - t0,
            "reconstruct_s": t1 - t0,
            "adj_s": t2 - t1,
            "caterpillar_s": t3 - t2,
            "unitarm_s": t4 - t3,
            "pendant_total_s": pendant_total,
            "base_search_s": base_search,
            "rebuild_s": rebuild,
            "flash_s": (t4 - t2),
            "fallback_s": fallback_s,
            "solved": int(labels is not None),
            "strategy": getattr(stats, "strategy", ""),
            "nodes": int(getattr(stats, "nodes", 0) or 0),
            "base_nodes": base_nodes,
            "fallback_nodes": fallback_nodes,
            "extended_edges": int(getattr(stats, "extended_edges", 0) or 0),
        }
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=2_000)
    parser.add_argument("--budget", type=float, default=0.5)
    parser.add_argument("--stride", type=int, default=1, help="take every Nth case, to sample uniformly")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "_diag" / "phases.csv")
    parser.add_argument("--cache-tag", default="phase")
    args = parser.parse_args()

    cache_db = str(CACHE_DIR / f"phase_extension_{args.cache_tag}.sqlite3")
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

    args.out.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for done, entry in enumerate(rows, 1):
            case_id = entry["case_id"]
            seed = int.from_bytes(
                hashlib.blake2b(f"compressed_0.5s:{case_id}".encode("ascii"), digest_size=8).digest(), "big"
            )
            writer.writerow(run_case(case_id, entry.get("stratum", ""), args.budget, cache_db, seed))
            if done % 250 == 0:
                print(f"  {done}/{len(rows)} wall={time.time()-started:.1f}s", flush=True)

    print(json.dumps({"cases": len(rows), "wall_seconds": round(time.time() - started, 2), "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
