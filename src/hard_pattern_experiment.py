#!/usr/bin/env python3
"""Compare branch search with two pendant-reduction budgets on one hard family."""

from __future__ import annotations

import argparse
import csv
import time
from collections import defaultdict
from pathlib import Path
import sys


SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graceful_tree import (  # noqa: E402
    build_adj,
    five_leaf_nonspider_two_branch,
    solve_graceful_branch_differences,
    solve_graceful_pendant_extension,
    verify_labeling,
)


def hard_pattern_cases(min_edges: int, max_edges: int):
    """Yield bridge=2, short=(1,1), and sorted long pendant triples."""
    for total_edges in range(min_edges, max_edges + 1):
        target = total_edges - 4  # bridge 2 + two short paths of length 1
        for a in range(1, target + 1):
            for b in range(a, target + 1):
                c = target - a - b
                if b <= c:
                    edges = five_leaf_nonspider_two_branch(2, (1, 1), (a, b, c))
                    name = f"hardpattern2e-{total_edges}-2-1-1-{a}-{b}-{c}"
                    yield name, total_edges, a, b, c, edges


def run_one(
    adj: list[list[int]],
    mode: str,
    time_limit: float | None,
    reduction_nodes: int | None = None,
) -> dict[str, object]:
    started = time.time()
    if mode == "branch":
        labels, stats = solve_graceful_branch_differences(adj, time_limit=time_limit)
    else:
        labels, stats = solve_graceful_pendant_extension(
            adj,
            max_nodes=reduction_nodes or 0,
            time_limit=time_limit,
            cache_size=0,
            cache_db=None,
        )
    elapsed = time.time() - started
    ok = labels is not None
    return {
        "solved": int(ok and verify_labeling(
            [(u, v) for u, neighbors in enumerate(adj) for v in neighbors if u < v],
            labels,
        )),
        "nodes": stats.nodes,
        "backtracks": stats.backtracks,
        "elapsed_seconds": f"{elapsed:.6f}",
        "strategy": stats.strategy,
        "reduction_base": stats.reduction_base,
    }


def summarize(rows: list[dict[str, str]]) -> None:
    print(f"cases={len(rows)}")
    for prefix, label in (
        ("branch", "branch"),
        ("reduce2000", "reduction-2000"),
        ("reduce20000", "reduction-20000"),
    ):
        solved = sum(row[f"{prefix}_solved"] == "1" for row in rows)
        nodes = sum(int(row[f"{prefix}_nodes"] or 0) for row in rows)
        seconds = sum(float(row[f"{prefix}_elapsed_seconds"] or 0) for row in rows)
        print(f"{label}: solved={solved}/{len(rows)}, nodes={nodes}, seconds={seconds:.3f}")

    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["mod3"])].append(row)
    print("by edge count mod 3:")
    for residue in sorted(grouped):
        group = grouped[residue]
        line = [f"mod3={residue}", f"cases={len(group)}"]
        for prefix in ("branch", "reduce2000", "reduce20000"):
            solved = sum(row[f"{prefix}_solved"] == "1" for row in group)
            seconds = sum(float(row[f"{prefix}_elapsed_seconds"] or 0) for row in group)
            line.append(f"{prefix}={solved}/{len(group)} ({seconds:.2f}s)")
        print("  " + ", ".join(line))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-edges", type=int, default=47)
    parser.add_argument("--max-edges", type=int, default=65)
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--total-time-limit", type=float, default=None)
    parser.add_argument("--log", default="results/hard_pattern_47_65_comparison.csv")
    parser.add_argument("--progress", type=int, default=50)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args(argv)

    if args.min_edges < 6 or args.min_edges > args.max_edges:
        parser.error("require 6 <= --min-edges <= --max-edges")

    if args.summary_only:
        with open(args.log, "r", encoding="utf-8", newline="") as source:
            summarize(list(csv.DictReader(source)))
        return 0

    fieldnames = [
        "case", "edges", "a", "b", "c", "mod3", "vertices",
        "branch_solved", "branch_nodes", "branch_backtracks", "branch_elapsed_seconds", "branch_strategy",
        "reduce2000_solved", "reduce2000_nodes", "reduce2000_backtracks", "reduce2000_elapsed_seconds", "reduce2000_strategy", "reduce2000_base",
        "reduce20000_solved", "reduce20000_nodes", "reduce20000_backtracks", "reduce20000_elapsed_seconds", "reduce20000_strategy", "reduce20000_base",
    ]
    existing: dict[str, dict[str, str]] = {}
    if args.resume and Path(args.log).exists():
        with open(args.log, "r", encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                if row.get("case"):
                    existing[row["case"]] = row

    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.resume and Path(args.log).exists() else "w"
    started_all = time.time()
    rows = list(existing.values())
    with open(args.log, mode, encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        if mode == "w":
            writer.writeheader()
        for case_name, total_edges, a, b, c, edges in hard_pattern_cases(args.min_edges, args.max_edges):
            if case_name in existing:
                continue
            if args.total_time_limit is not None and time.time() - started_all >= args.total_time_limit:
                print(f"stopping: total time limit reached after {len(rows)} cases")
                break
            adj = build_adj(total_edges + 1, edges)
            row: dict[str, object] = {
                "case": case_name,
                "edges": total_edges,
                "a": a,
                "b": b,
                "c": c,
                "mod3": total_edges % 3,
                "vertices": total_edges + 1,
            }
            for prefix, mode_name, budget in (
                ("branch", "branch", None),
                ("reduce2000", "reduce", 2_000),
                ("reduce20000", "reduce", 20_000),
            ):
                result = run_one(adj, mode_name, args.time_limit, budget)
                for key, value in result.items():
                    if key == "reduction_base" and prefix == "branch":
                        continue
                    if key == "reduction_base":
                        key = "base"
                    row[f"{prefix}_{key}"] = value
            writer.writerow(row)
            destination.flush()
            rows.append({key: str(value) for key, value in row.items()})
            if args.progress and len(rows) % args.progress == 0:
                print(f"case {len(rows)}: elapsed={time.time() - started_all:.1f}s")

    summarize(rows)
    print(f"log: {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
