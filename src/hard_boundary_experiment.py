#!/usr/bin/env python3
"""Target the six boundary cases left by the 47--65 hard-pattern study."""

from __future__ import annotations

import argparse
import csv
import time
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


BOUNDARY_CASES = (
    (61, 11, 23, 23),
    (62, 11, 23, 24),
    (63, 11, 23, 25),
    (64, 11, 23, 26),
    (65, 9, 26, 26),
    (65, 11, 23, 27),
)


def cases():
    for total_edges, a, b, c in BOUNDARY_CASES:
        edges = five_leaf_nonspider_two_branch(2, (1, 1), (a, b, c))
        name = f"hardboundary2e-{total_edges}-2-1-1-{a}-{b}-{c}"
        yield name, total_edges, a, b, c, edges


def run_one(
    adj: list[list[int]],
    edges: list[tuple[int, int]],
    mode: str,
    time_limit: float | None,
    reduction_nodes: int | None = None,
    try_all_paths: bool = False,
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
            try_all_paths=try_all_paths,
        )
    elapsed = time.time() - started
    solved = labels is not None and verify_labeling(edges, labels)
    return {
        "solved": int(solved),
        "nodes": stats.nodes,
        "backtracks": stats.backtracks,
        "elapsed_seconds": f"{elapsed:.6f}",
        "strategy": stats.strategy,
        "base": stats.reduction_base,
        "extended_edges": stats.extended_edges,
    }


def summarize(rows: list[dict[str, str]], prefixes: list[str]) -> None:
    print(f"cases={len(rows)}")
    for prefix in prefixes:
        solved = sum(row[f"{prefix}_solved"] == "1" for row in rows)
        nodes = sum(int(row[f"{prefix}_nodes"] or 0) for row in rows)
        seconds = sum(float(row[f"{prefix}_elapsed_seconds"] or 0) for row in rows)
        print(f"{prefix}: solved={solved}/{len(rows)}, nodes={nodes}, seconds={seconds:.3f}")
    print("cases:")
    for row in rows:
        line = [row["case"]]
        for prefix in prefixes:
            line.append(
                f"{prefix}={row[prefix + '_solved']}/"
                f"{row[prefix + '_nodes']} nodes/"
                f"{row[prefix + '_elapsed_seconds']}s"
            )
        print("  " + ", ".join(line))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--total-time-limit", type=float, default=None)
    parser.add_argument("--low-nodes", type=int, default=20_000)
    parser.add_argument("--high-nodes", type=int, default=100_000)
    parser.add_argument("--log", default="results/hard_boundary_61_65.csv")
    parser.add_argument("--progress", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args(argv)

    prefixes = ["branch", "reduce20k", "reduce100k", "allpaths100k"]
    fieldnames = ["case", "edges", "a", "b", "c", "mod3", "vertices"]
    for prefix in prefixes:
        fieldnames.extend(
            [
                f"{prefix}_solved",
                f"{prefix}_nodes",
                f"{prefix}_backtracks",
                f"{prefix}_elapsed_seconds",
                f"{prefix}_strategy",
                f"{prefix}_base",
                f"{prefix}_extended_edges",
            ]
        )

    if args.summary_only:
        with open(args.log, "r", encoding="utf-8", newline="") as source:
            summarize(list(csv.DictReader(source)), prefixes)
        return 0

    existing: dict[str, dict[str, str]] = {}
    log_path = Path(args.log)
    if args.resume and log_path.exists():
        with open(log_path, "r", encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                if row.get("case"):
                    existing[row["case"]] = row

    log_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.resume and log_path.exists() else "w"
    started_all = time.time()
    rows = list(existing.values())
    with open(log_path, mode, encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        if mode == "w":
            writer.writeheader()
        for case_name, total_edges, a, b, c, edges in cases():
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
            experiments = (
                ("branch", "branch", None, False),
                ("reduce20k", "reduce", args.low_nodes, False),
                ("reduce100k", "reduce", args.high_nodes, False),
                ("allpaths100k", "reduce", args.high_nodes, True),
            )
            for prefix, mode_name, budget, try_all_paths in experiments:
                result = run_one(adj, edges, mode_name, args.time_limit, budget, try_all_paths)
                for key, value in result.items():
                    row[f"{prefix}_{key}"] = value
            writer.writerow(row)
            destination.flush()
            rows.append({key: str(value) for key, value in row.items()})
            if args.progress:
                print(f"case {len(rows)}/{len(BOUNDARY_CASES)}: {case_name}")

    summarize(rows, prefixes)
    print(f"log: {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
