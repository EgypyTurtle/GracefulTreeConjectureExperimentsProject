"""Ablate move ordering on the branch difference search.

Move ordering is the main lever on node count for this search: the base search
explores one edge per difference and the ordering decides which candidate is
tried first, so a better ordering reaches a solution in fewer nodes or proves
failure sooner.

Each ordering is measured under a fixed node budget so that "solved" and "nodes
used" are comparable across them, and every returned certificate is verified.

Usage:
    python src/diag_move_order.py --start 3825152 --count 300 --method branch --nodes 20000
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
from edge64_baseline import reconstruct_named_five_leaf_case  # noqa: E402

CASE_MANIFEST = ROOT / "results" / "edge64_baseline_v1" / "edge64_case_manifest.csv"
ORDERS = ("default", "placement", "branch_first", "edge_index", "extremeness")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=3_825_152)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--method", choices=("branch", "pendant", "compressed"), default="branch")
    parser.add_argument("--nodes", type=int, default=20_000)
    parser.add_argument("--budget", type=float, default=0.5)
    parser.add_argument("--orders", default=",".join(ORDERS))
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "_diag" / "move_order.json")
    args = parser.parse_args()

    orders = [o.strip() for o in args.orders.split(",") if o.strip()]
    rows = []
    with CASE_MANIFEST.open("r", newline="", encoding="utf-8") as handle:
        for index, entry in enumerate(csv.DictReader(handle)):
            if index < args.start:
                continue
            if len(rows) >= args.count:
                break
            rows.append(entry)

    prepared = []
    for entry in rows:
        n, edges = reconstruct_named_five_leaf_case(entry["case_id"])
        seed = int.from_bytes(
            hashlib.blake2b(f"compressed_0.5s:{entry['case_id']}".encode("ascii"), digest_size=8).digest(), "big"
        )
        prepared.append((entry["case_id"], n, edges, seed))

    summary = {}
    for order in orders:
        nodes_total = 0
        solved = 0
        invalid = 0
        times: list[float] = []
        for case_id, n, edges, seed in prepared:
            adj = gt.build_adj(n, edges)
            t0 = time.perf_counter()
            if args.method == "branch":
                labels, stats = gt.solve_graceful_branch_differences(
                    adj,
                    time_limit=args.budget,
                    seed=seed,
                    max_nodes=args.nodes,
                    move_order=order,
                )
            elif args.method == "compressed":
                from edge64_baseline import options

                opted = options("compressed", args.budget, str(ROOT / "results" / "_diag" / "mo.sqlite3"))
                opted.extension_persistent_cache = False
                opted.extension_fastpath_nodes = args.nodes
                opted.extension_move_order = order
                labels, stats = gt.solve_tree(adj, opted, seed=seed)
            else:
                labels, stats = gt.solve_graceful_pendant_extension(
                    adj,
                    max_nodes=args.nodes,
                    time_limit=args.budget,
                    move_order=order,
                )
            times.append(time.perf_counter() - t0)
            nodes_total += int(stats.nodes or 0)
            if labels is not None:
                if gt.verify_labeling(edges, labels):
                    solved += 1
                else:
                    invalid += 1
        summary[order] = {
            "solved": solved,
            "invalid": invalid,
            "cases": len(prepared),
            "total_nodes": nodes_total,
            "mean_ms": round(1000 * statistics.fmean(times), 3) if times else 0.0,
            "wall_s": round(sum(times), 3),
            "nodes_per_solved": round(nodes_total / solved, 1) if solved else None,
        }
        print(f"  {order:14s} solved={solved}/{len(prepared)} nodes={nodes_total:,} "
              f"nodes/solved={summary[order]['nodes_per_solved']}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
