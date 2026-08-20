#!/usr/bin/env python3
"""Stream free trees through the existing certificate-producing solver."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from argparse import Namespace
from pathlib import Path

try:
    from free_tree_generator import iter_free_tree_layers, parse_shape, shape_edges
    from graceful_tree import (
        build_adj,
        close_pendant_extension_cache,
        solve_tree,
        verify_labeling,
    )
except ModuleNotFoundError:  # pragma: no cover - useful when imported from repo root
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from free_tree_generator import iter_free_tree_layers, parse_shape, shape_edges
    from graceful_tree import (
        build_adj,
        close_pendant_extension_cache,
        solve_tree,
        verify_labeling,
    )


def edge_string(edges: list[tuple[int, int]]) -> str:
    return " ".join(f"{left}-{right}" for left, right in edges)


def label_string(labels: list[int] | None) -> str:
    return "" if labels is None else " ".join(map(str, labels))


def load_solved_cases(paths: list[str]) -> set[str]:
    solved: set[str] = set()
    for path in paths:
        with open(path, "r", encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                if row.get("solved") == "1":
                    solved.add(row.get("case", ""))
    return solved


def solver_args(args: argparse.Namespace) -> Namespace:
    return Namespace(
        no_constructive_fastpath=False,
        method="compressed",
        extension_adaptive_budget=False,
        extension_fastpath_nodes=args.extension_fastpath_nodes,
        extension_adaptive_nodes=args.extension_adaptive_nodes,
        extension_cache_size=args.extension_cache_size,
        extension_cache_db=args.extension_cache_db,
        extension_try_all_paths=args.extension_try_all_paths,
        time_limit=args.time_limit,
        diff_candidates=None,
    )


def run(args: argparse.Namespace) -> int:
    skip_solved = load_solved_cases(args.skip_solved_from)
    solver_options = solver_args(args)
    started = time.time()
    processed = solved = unsolved = skipped = 0
    output = Path(args.log)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case",
        "vertices",
        "solved",
        "strategy",
        "nodes",
        "backtracks",
        "elapsed_seconds",
        "edges",
        "labels",
    ]

    with output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        try:
            for vertices, codes in iter_free_tree_layers(
                args.max_vertices, args.generation_progress
            ):
                if vertices < args.min_vertices:
                    continue
                for code in sorted(codes):
                    if args.max_cases is not None and processed >= args.max_cases:
                        break
                    if args.total_time_limit is not None and time.time() - started >= args.total_time_limit:
                        break
                    edges = shape_edges(parse_shape(code))
                    case = f"free-{vertices}-{code}"
                    if case in skip_solved:
                        skipped += 1
                        continue

                    tree_started = time.time()
                    adjacency_labels, stats = solve_tree(
                        build_adj(vertices, edges),
                        solver_options,
                    )
                    elapsed = time.time() - tree_started
                    ok = adjacency_labels is not None and verify_labeling(edges, adjacency_labels)
                    solved += int(ok)
                    unsolved += int(not ok)
                    processed += 1
                    writer.writerow(
                        {
                            "case": case,
                            "vertices": vertices,
                            "solved": int(ok),
                            "strategy": stats.strategy,
                            "nodes": stats.nodes,
                            "backtracks": stats.backtracks,
                            "elapsed_seconds": f"{elapsed:.6f}",
                            "edges": edge_string(edges),
                            "labels": label_string(adjacency_labels),
                        }
                    )
                    destination.flush()
                    if args.progress and (processed == 1 or processed % args.progress == 0):
                        rate = processed / max(time.time() - started, 1e-9)
                        print(
                            f"case={processed}: solved={solved}, unsolved={unsolved}, "
                            f"skipped={skipped}, rate={rate:.2f}/s",
                            flush=True,
                        )
                if args.max_cases is not None and processed >= args.max_cases:
                    break
                if args.total_time_limit is not None and time.time() - started >= args.total_time_limit:
                    break
        finally:
            close_pendant_extension_cache()

    print(
        f"complete: processed={processed}, solved={solved}, unsolved={unsolved}, "
        f"skipped={skipped}, elapsed={time.time() - started:.3f}s"
    )
    print(f"log: {args.log}")
    return 0 if unsolved == 0 else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-vertices", type=int, default=15)
    parser.add_argument("--min-vertices", type=int, default=1)
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--total-time-limit", type=float)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--progress", type=int, default=1000)
    parser.add_argument(
        "--generation-progress",
        type=int,
        default=0,
        help="print free-tree generation progress every N parent trees (0 disables it)",
    )
    parser.add_argument("--log", default="results/free_tree_graceful.csv")
    parser.add_argument("--skip-solved-from", action="append", default=[])
    parser.add_argument("--extension-fastpath-nodes", type=int, default=2000)
    parser.add_argument("--extension-adaptive-nodes", type=int, default=100000)
    parser.add_argument("--extension-cache-size", type=int, default=100000)
    parser.add_argument(
        "--extension-cache-db",
        default="results/pendant_extension_cache.sqlite3",
    )
    parser.add_argument("--extension-try-all-paths", action="store_true")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
