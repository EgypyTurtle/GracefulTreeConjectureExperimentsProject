"""Compare move orderings across many disjoint regions of the edge64 manifest.

A single contiguous sample is misleading here: the manifest is ordered by
structure, so difficulty and the best ordering both vary along it.  A candidate
ordering is only worth adopting if it wins broadly, so this samples several
disjoint regions, measures each ordering in each region under a fixed node
budget, and reports per-region wins plus totals.

Usage:
    python src/diag_move_order_multi.py --regions 8 --per-region 200 --nodes 20000
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
from edge64_baseline import reconstruct_named_five_leaf_case  # noqa: E402

CASE_MANIFEST = ROOT / "results" / "edge64_baseline_v1" / "edge64_case_manifest.csv"
TOTAL_CASES = 10_040_677


def seeds_for(case_id: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(f"compressed_0.5s:{case_id}".encode("ascii"), digest_size=8).digest(), "big"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions", type=int, default=8)
    parser.add_argument("--per-region", type=int, default=200)
    parser.add_argument("--nodes", type=int, default=20_000)
    parser.add_argument("--budget", type=float, default=0.5)
    parser.add_argument("--orders", default="default,branch_first,placement")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "_diag" / "move_order_multi.json")
    args = parser.parse_args()

    orders = [o.strip() for o in args.orders.split(",") if o.strip()]
    stride = TOTAL_CASES // (args.regions * args.per_region)

    # Deterministic, evenly spread sample: one in every `stride` cases.
    entries = []
    with CASE_MANIFEST.open("r", newline="", encoding="utf-8") as handle:
        for index, entry in enumerate(csv.DictReader(handle)):
            if index % stride == 0:
                entries.append(entry)
            if len(entries) >= args.regions * args.per_region:
                break

    prepared = []
    for entry in entries:
        n, edges = reconstruct_named_five_leaf_case(entry["case_id"])
        prepared.append((entry["case_id"], n, edges, seeds_for(entry["case_id"])))

    per_region: list[dict[str, object]] = []
    for region in range(args.regions):
        chunk = prepared[region * args.per_region : (region + 1) * args.per_region]
        if not chunk:
            continue
        row: dict[str, object] = {"region": region, "start_index": region * args.per_region * stride}
        for order in orders:
            nodes = 0
            solved = 0
            failures: list[dict[str, object]] = []
            started = time.perf_counter()
            for case_id, n, edges, seed in chunk:
                adj = gt.build_adj(n, edges)
                try:
                    labels, stats = gt.solve_graceful_branch_differences(
                        adj, time_limit=args.budget, seed=seed, max_nodes=args.nodes, move_order=order
                    )
                except MemoryError:
                    failures.append({"case_id": case_id, "kind": "MemoryError"})
                    raise SystemExit(
                        f"MemoryError: region={region} order={order} case={case_id} "
                        f"nodes_before={nodes}"
                    )
                nodes += int(stats.nodes or 0)
                if labels is not None and gt.verify_labeling(edges, labels):
                    solved += 1
            row[order] = {"solved": solved, "nodes": nodes, "wall_s": round(time.perf_counter() - started, 2)}
        per_region.append(row)
        winners = ", ".join(f"{o}={row[o]['solved']}" for o in orders)  # type: ignore[index]
        print(f"region {region:2d}: {winners}", flush=True)

    print()
    header = f"{'ordering':14s} {'solved':>9s} {'nodes':>13s} {'nodes/solved':>13s} {'region wins':>12s}"
    print(header)
    print("-" * len(header))
    totals = {}
    for order in orders:
        solved = sum(int(r[order]["solved"]) for r in per_region)  # type: ignore[index]
        nodes = sum(int(r[order]["nodes"]) for r in per_region)  # type: ignore[index]
        wins = sum(
            1
            for r in per_region
            if int(r[order]["solved"]) == max(int(r[o]["solved"]) for o in orders)  # type: ignore[index]
        )
        totals[order] = {
            "solved": solved,
            "nodes": nodes,
            "nodes_per_solved": round(nodes / solved, 1) if solved else None,
            "region_wins": wins,
            "regions": len(per_region),
        }
        print(f"{order:14s} {solved:>9d} {nodes:>13,d} {totals[order]['nodes_per_solved']:>13} {wins:>7d}/{len(per_region)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"per_region": per_region, "totals": totals, "stride": stride}, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
