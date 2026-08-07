#!/usr/bin/env python3
"""
Antimagic tree labeling search tool.

An antimagic labeling of a graph with m edges is a bijection from the edges to
1..m such that the induced vertex sums are pairwise distinct.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from collections import deque
from dataclasses import dataclass
from itertools import combinations_with_replacement
from typing import Iterable

from graceful_tree import (
    Edge,
    assert_tree,
    build_adj,
    edge_string,
    five_leaf_nonspider_three_branch,
    five_leaf_nonspider_two_branch,
    parse_edge_string,
    read_edges,
)


@dataclass
class SearchStats:
    nodes: int = 0
    backtracks: int = 0
    started_at: float = 0.0


def positive_tuples(parts: int, total: int) -> Iterable[tuple[int, ...]]:
    if parts == 1:
        if total >= 1:
            yield (total,)
        return
    for first in range(1, total - parts + 2):
        for rest in positive_tuples(parts - 1, total - first):
            yield (first, *rest)


def five_leaf_nonspider_by_edges_cases(max_edges: int) -> Iterable[tuple[str, int, list[Edge]]]:
    if max_edges < 6:
        raise ValueError("non-spider 5-leaf trees need at least 6 edges")
    for total_edges in range(6, max_edges + 1):
        for lengths in positive_tuples(6, total_edges):
            bridge = lengths[0]
            left = tuple(sorted(lengths[1:3]))
            right = tuple(sorted(lengths[3:6]))
            if lengths[1:3] != left or lengths[3:6] != right:
                continue
            edges = five_leaf_nonspider_two_branch(bridge, left, right)
            name = "fiveleaf2e-" + "-".join(map(str, (total_edges, bridge, *left, *right)))
            yield name, len(edges) + 1, edges

        for lengths in positive_tuples(7, total_edges):
            left_bridge, right_bridge = lengths[0], lengths[1]
            left = tuple(sorted(lengths[2:4]))
            middle_leaf = lengths[4]
            right = tuple(sorted(lengths[5:7]))
            if lengths[2:4] != left or lengths[5:7] != right:
                continue
            if (left, left_bridge) > (right, right_bridge):
                continue
            edges = five_leaf_nonspider_three_branch(
                left_bridge,
                right_bridge,
                left,
                middle_leaf,
                right,
            )
            name = "fiveleaf3e-" + "-".join(
                map(str, (total_edges, left_bridge, right_bridge, *left, middle_leaf, *right))
            )
            yield name, len(edges) + 1, edges


def edge_labels_string(edge_labels: list[int] | None) -> str:
    return "" if edge_labels is None else " ".join(map(str, edge_labels))


def parse_edge_labels(text: str) -> list[int]:
    return [int(x) for x in text.split()] if text.strip() else []


def verify_antimagic(n: int, edges: list[Edge], edge_labels: list[int]) -> bool:
    m = len(edges)
    if sorted(edge_labels) != list(range(1, m + 1)):
        return False
    sums = [0] * n
    for label, (u, v) in zip(edge_labels, edges):
        sums[u] += label
        sums[v] += label
    return len(set(sums)) == n


def solve_antimagic_branch(
    n: int,
    edges: list[Edge],
    time_limit: float | None = None,
    random_seed: int | None = None,
) -> tuple[list[int] | None, SearchStats]:
    adj = build_adj(n, edges)
    degrees = [len(nei) for nei in adj]
    stats = SearchStats(started_at=time.time())
    m = len(edges)
    edge_labels = [0] * m
    used_label = [False] * (m + 1)
    vertex_sums = [0] * n
    remaining_degree = degrees[:]

    branch_vertices = [u for u, d in enumerate(degrees) if d >= 3]
    dist = [-1] * n
    q: deque[int] = deque()
    for root in branch_vertices or [max(range(n), key=lambda u: degrees[u])]:
        dist[root] = 0
        q.append(root)
    while q:
        u = q.popleft()
        for v in adj[u]:
            if dist[v] == -1:
                dist[v] = dist[u] + 1
                q.append(v)

    edge_order = list(range(m))
    rng = random.Random(random_seed) if random_seed is not None else None
    if rng is not None:
        rng.shuffle(edge_order)
    edge_order = sorted(
        edge_order,
        key=lambda i: (
            -(degrees[edges[i][0]] + degrees[edges[i][1]]),
            dist[edges[i][0]] + dist[edges[i][1]],
            rng.random() if rng is not None else i,
        ),
    )

    def timed_out() -> bool:
        return time_limit is not None and time.time() - stats.started_at >= time_limit

    def finished_conflict(vertices: Iterable[int]) -> bool:
        seen = {}
        for u in range(n):
            if remaining_degree[u] == 0:
                s = vertex_sums[u]
                if s in seen:
                    return True
                seen[s] = u
        for u in vertices:
            if remaining_degree[u] == 0:
                s = vertex_sums[u]
                for v in range(n):
                    if v != u and remaining_degree[v] == 0 and vertex_sums[v] == s:
                        return True
        return False

    def possible_final_interval(u: int) -> tuple[int, int]:
        unused = [label for label in range(1, m + 1) if not used_label[label]]
        r = remaining_degree[u]
        if r == 0:
            return vertex_sums[u], vertex_sums[u]
        return vertex_sums[u] + sum(unused[:r]), vertex_sums[u] + sum(unused[-r:])

    def interval_prune() -> bool:
        finished = {vertex_sums[u] for u in range(n) if remaining_degree[u] == 0}
        for u in range(n):
            if remaining_degree[u] == 0:
                continue
            low, high = possible_final_interval(u)
            if all(value < low or value > high for value in finished):
                continue
        return False

    def backtrack(pos: int) -> bool:
        if timed_out():
            return False
        stats.nodes += 1
        if pos == m:
            return verify_antimagic(n, edges, edge_labels)
        edge_index = edge_order[pos]
        u, v = edges[edge_index]
        labels = [label for label in range(m, 0, -1) if not used_label[label]]
        if rng is not None:
            rng.shuffle(labels)
        for label in labels:
            edge_labels[edge_index] = label
            used_label[label] = True
            vertex_sums[u] += label
            vertex_sums[v] += label
            remaining_degree[u] -= 1
            remaining_degree[v] -= 1
            if not finished_conflict((u, v)) and not interval_prune() and backtrack(pos + 1):
                return True
            remaining_degree[u] += 1
            remaining_degree[v] += 1
            vertex_sums[u] -= label
            vertex_sums[v] -= label
            used_label[label] = False
            edge_labels[edge_index] = 0
        stats.backtracks += 1
        return False

    if backtrack(0):
        return edge_labels[:], stats
    return None, stats


def load_solved_cases(path: str) -> set[str]:
    solved: set[str] = set()
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            case_name = row.get("case", "")
            if not case_name or "\x00" in case_name:
                continue
            if row.get("solved") == "1":
                solved.add(case_name)
    return solved


def run_cases(cases: Iterable[tuple[str, int, list[Edge]]], args: argparse.Namespace) -> int:
    fieldnames = [
        "case",
        "vertices",
        "edges_count",
        "status",
        "solved",
        "nodes",
        "backtracks",
        "elapsed_seconds",
        "primary_nodes",
        "fallback_nodes",
        "fallback_used",
        "random_trials_used",
        "edges",
        "edge_labels",
    ]
    skip_solved = load_solved_cases(args.skip_solved_from) if args.skip_solved_from else set()
    skipped = 0
    solved = 0
    timeouts = 0
    checked = 0
    best_nodes = -1
    best_elapsed = -1.0
    started = time.time()
    with open(args.log, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for case_name, n, edges in cases:
            if case_name in skip_solved:
                skipped += 1
                continue
            adj = build_adj(n, edges)
            assert_tree(n, edges, adj)
            labels = None
            stats = SearchStats(started_at=time.time())
            primary_nodes = 0
            fallback_nodes = 0
            fallback_used = 0
            random_trials_used = 0
            if args.random_trials > 1:
                trial_limit = args.time_limit / args.random_trials if args.time_limit is not None else None
                for trial in range(args.random_trials):
                    trial_labels, trial_stats = solve_antimagic_branch(
                        n,
                        edges,
                        time_limit=trial_limit,
                        random_seed=args.random_seed + trial,
                    )
                    stats.nodes += trial_stats.nodes
                    stats.backtracks += trial_stats.backtracks
                    random_trials_used += 1
                    if trial_labels is not None:
                        labels = trial_labels
                        break
            else:
                trial_labels, trial_stats = solve_antimagic_branch(
                    n,
                    edges,
                    time_limit=args.time_limit,
                )
                stats.nodes += trial_stats.nodes
                stats.backtracks += trial_stats.backtracks
                primary_nodes = trial_stats.nodes
                labels = trial_labels

                # Spend extra effort only on cases that defeated the primary order.
                if labels is None and args.random_fallback_trials > 0:
                    fallback_limit = (
                        args.random_fallback_time / args.random_fallback_trials
                        if args.random_fallback_time is not None
                        else None
                    )
                    for trial in range(args.random_fallback_trials):
                        trial_labels, trial_stats = solve_antimagic_branch(
                            n,
                            edges,
                            time_limit=fallback_limit,
                            random_seed=args.random_seed + trial,
                        )
                        stats.nodes += trial_stats.nodes
                        stats.backtracks += trial_stats.backtracks
                        fallback_nodes += trial_stats.nodes
                        fallback_used = 1
                        random_trials_used += 1
                        if trial_labels is not None:
                            labels = trial_labels
                            break
            elapsed = time.time() - stats.started_at
            ok = labels is not None and verify_antimagic(n, edges, labels)
            checked += 1
            solved += int(ok)
            timeouts += int(not ok)
            if stats.nodes > best_nodes or (stats.nodes == best_nodes and elapsed > best_elapsed):
                best_nodes = stats.nodes
                best_elapsed = elapsed
            writer.writerow(
                {
                    "case": case_name,
                    "vertices": n,
                    "edges_count": len(edges),
                    "status": "solved" if ok else "timeout_or_failed",
                    "solved": int(ok),
                    "nodes": stats.nodes,
                    "backtracks": stats.backtracks,
                    "elapsed_seconds": f"{elapsed:.6f}",
                    "primary_nodes": primary_nodes,
                    "fallback_nodes": fallback_nodes,
                    "fallback_used": fallback_used,
                    "random_trials_used": random_trials_used,
                    "edges": edge_string(edges),
                    "edge_labels": edge_labels_string(labels),
                }
            )
            f.flush()
            if args.progress and (checked == 1 or checked % args.progress == 0):
                rate = checked / max(time.time() - started, 1e-9)
                print(
                    f"case {checked}: solved={solved}, timeouts={timeouts}, "
                    f"skipped={skipped}, hardest_nodes={best_nodes}, rate={rate:.2f}/s"
                )
    elapsed_total = time.time() - started
    print(
        f"complete: checked={checked}, solved={solved}, timeouts={timeouts}, "
        f"skipped={skipped}, elapsed={elapsed_total:.3f}s"
    )
    print(f"log: {args.log}")
    print(f"hardest_nodes={best_nodes}, hardest_elapsed={best_elapsed:.6f}s")
    return 0 if timeouts == 0 else 2


def run_replay_unsolved(args: argparse.Namespace) -> int:
    def cases() -> Iterable[tuple[str, int, list[Edge]]]:
        with open(args.replay_unsolved, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("solved") == "1":
                    continue
                edges = parse_edge_string(row["edges"])
                n = int(row["vertices"])
                yield row["case"], n, edges
    return run_cases(cases(), args)


def run_summarize_log(args: argparse.Namespace) -> int:
    with open(args.summarize_log, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    solved = [row for row in rows if row.get("solved") == "1"]
    unsolved = [row for row in rows if row.get("solved") != "1"]
    print(f"log: {args.summarize_log}")
    print(f"rows={len(rows)}, solved={len(solved)}, unsolved={len(unsolved)}")
    for row in sorted(rows, key=lambda r: int(r.get("nodes") or 0), reverse=True)[:10]:
        print(
            f"  {row.get('case','')}: solved={row.get('solved','')}, "
            f"vertices={row.get('vertices','')}, nodes={row.get('nodes','')}, "
            f"elapsed={row.get('elapsed_seconds','')}"
        )
    if unsolved:
        print("unsolved cases:")
        for row in unsolved[:50]:
            print(
                f"  {row.get('case','')}: vertices={row.get('vertices','')}, "
                f"nodes={row.get('nodes','')}, elapsed={row.get('elapsed_seconds','')}"
            )
    return 0 if not unsolved else 2


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Search for antimagic labelings of trees.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--edges", help="text file with one edge 'u v' per line")
    source.add_argument("--five-leaf-nonspider-by-edges", type=int, metavar="MAX_EDGES")
    source.add_argument("--replay-unsolved", help="CSV log to replay unsolved rows")
    source.add_argument("--summarize-log", help="CSV log to summarize")
    parser.add_argument("--time-limit", type=float, default=10)
    parser.add_argument("--log", default="antimagic_log.csv")
    parser.add_argument("--progress", type=int, default=100)
    parser.add_argument("--random-trials", type=int, default=1, help="independent search orders per case")
    parser.add_argument("--random-seed", type=int, default=20260805)
    parser.add_argument("--random-fallback-trials", type=int, default=0, help="random trials only after primary timeout")
    parser.add_argument("--random-fallback-time", type=float, default=60, help="total fallback time per case")
    parser.add_argument("--skip-solved-from", help="CSV log whose solved case names should be skipped")
    args = parser.parse_args(argv)

    if args.summarize_log:
        return run_summarize_log(args)
    if args.replay_unsolved:
        return run_replay_unsolved(args)
    if args.five_leaf_nonspider_by_edges is not None:
        return run_cases(five_leaf_nonspider_by_edges_cases(args.five_leaf_nonspider_by_edges), args)
    edges = read_edges(args.edges)
    n = 1 + max(max(u, v) for u, v in edges)
    return run_cases((("input", n, edges),), args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
