#!/usr/bin/env python3
"""
Small experiments for extending antimagic labelings across subdivisions.

The first experiment tries to construct an antimagic labeling for an edge-(m+1)
non-spider 5-leaf tree from a solved edge-m predecessor by increasing one
reduced-edge segment length by one.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from typing import Iterable
from itertools import permutations

from antimagic_tree import (
    edge_labels_string,
    five_leaf_nonspider_by_edges_cases,
    parse_edge_labels,
    verify_antimagic,
)
from graceful_tree import Edge, edge_string


def parse_case_name(name: str) -> tuple[str, int, tuple[int, ...]]:
    parts = name.split("-")
    kind = parts[0]
    total_edges = int(parts[1])
    values = tuple(int(x) for x in parts[2:])
    if kind not in {"fiveleaf2e", "fiveleaf3e"}:
        raise ValueError(f"unsupported case kind: {kind}")
    return kind, total_edges, values


def make_case_name(kind: str, total_edges: int, values: tuple[int, ...]) -> str:
    return "-".join([kind, str(total_edges), *(str(x) for x in values)])


def predecessor_names(name: str) -> Iterable[str]:
    kind, total_edges, values = parse_case_name(name)
    if total_edges <= 6:
        return
    for index, value in enumerate(values):
        if value <= 1:
            continue
        new_values = list(values)
        new_values[index] -= 1
        if kind == "fiveleaf2e":
            # values = bridge, left1, left2, right1, right2, right3
            left = sorted(new_values[1:3])
            right = sorted(new_values[3:6])
            canonical = (new_values[0], *left, *right)
        else:
            # values = left_bridge, right_bridge, left1, left2, middle, right1, right2
            left = tuple(sorted(new_values[2:4]))
            right = tuple(sorted(new_values[5:7]))
            if (left, new_values[0]) > (right, new_values[1]):
                canonical = (new_values[1], new_values[0], *right, new_values[4], *left)
            else:
                canonical = (new_values[0], new_values[1], *left, new_values[4], *right)
        yield make_case_name(kind, total_edges - 1, tuple(canonical))


def vertex_sums(n: int, edges: list[Edge], labels: list[int]) -> list[int]:
    sums = [0] * n
    for label, (u, v) in zip(labels, edges):
        sums[u] += label
        sums[v] += label
    return sums


def edge_distance_from_vertices(edges: list[Edge], starts: set[int]) -> list[int]:
    n = 1 + max(max(u, v) for u, v in edges)
    adj_edges = [[] for _ in range(n)]
    for edge_index, (u, v) in enumerate(edges):
        adj_edges[u].append((v, edge_index))
        adj_edges[v].append((u, edge_index))
    dist_v = [-1] * n
    queue = list(starts)
    for start in starts:
        dist_v[start] = 0
    head = 0
    while head < len(queue):
        u = queue[head]
        head += 1
        for v, _edge_index in adj_edges[u]:
            if dist_v[v] == -1:
                dist_v[v] = dist_v[u] + 1
                queue.append(v)
    return [min(dist_v[u], dist_v[v]) for u, v in edges]


def try_lift_by_matching_target(
    pred_edges: list[Edge],
    pred_labels: list[int],
    target_edges: list[Edge],
) -> list[int] | None:
    """Try all ways to split one predecessor edge using labels old and m+1.

    This assumes the target generator extends the predecessor by appending one
    vertex at the end of some generated path. The test is intentionally simple:
    keep labels on common edges, put old split-edge label and the new maximum on
    the two target edges adjacent to the new vertex.
    """
    old_m = len(pred_edges)
    new_label = old_m + 1
    pred_edge_set = {tuple(sorted(edge)): i for i, edge in enumerate(pred_edges)}
    target_edge_set = {tuple(sorted(edge)): i for i, edge in enumerate(target_edges)}
    n = 1 + max(max(u, v) for u, v in target_edges)

    common = set(pred_edge_set) & set(target_edge_set)
    missing_pred = [edge for edge in pred_edge_set if edge not in common]
    extra_target = [edge for edge in target_edge_set if edge not in common]
    if len(missing_pred) != 1 or len(extra_target) != 2:
        return None

    split_u, split_v = missing_pred[0]
    old_edge_index = pred_edge_set[missing_pred[0]]
    old_label = pred_labels[old_edge_index]
    candidates = []
    for extra1, extra2 in ((extra_target[0], extra_target[1]), (extra_target[1], extra_target[0])):
        labels = [0] * len(target_edges)
        ok = True
        for edge, pred_index in pred_edge_set.items():
            if edge == missing_pred[0]:
                continue
            target_index = target_edge_set.get(edge)
            if target_index is None:
                ok = False
                break
            labels[target_index] = pred_labels[pred_index]
        if not ok:
            continue
        labels[target_edge_set[extra1]] = old_label
        labels[target_edge_set[extra2]] = new_label
        if sorted(labels) == list(range(1, len(target_edges) + 1)) and verify_antimagic(n, target_edges, labels):
            candidates.append(labels)
    return candidates[0] if candidates else None


def try_lift_with_local_permutation(
    pred_edges: list[Edge],
    pred_labels: list[int],
    target_edges: list[Edge],
    window: int,
    max_permutations: int,
) -> list[int] | None:
    old_m = len(pred_edges)
    pred_edge_set = {tuple(sorted(edge)): i for i, edge in enumerate(pred_edges)}
    target_edge_set = {tuple(sorted(edge)): i for i, edge in enumerate(target_edges)}
    n = 1 + max(max(u, v) for u, v in target_edges)

    common = set(pred_edge_set) & set(target_edge_set)
    missing_pred = [edge for edge in pred_edge_set if edge not in common]
    extra_target = [edge for edge in target_edge_set if edge not in common]
    if len(missing_pred) != 1 or len(extra_target) != 2:
        return None

    split_vertices = set(missing_pred[0])
    dist = edge_distance_from_vertices(target_edges, split_vertices)
    target_local = sorted(
        range(len(target_edges)),
        key=lambda i: (dist[i], i),
    )[:window]
    local_set = set(target_local) | {target_edge_set[edge] for edge in extra_target}
    target_local = sorted(local_set)

    fixed_labels = [0] * len(target_edges)
    local_labels = set()
    for edge, pred_index in pred_edge_set.items():
        if edge == missing_pred[0]:
            local_labels.add(pred_labels[pred_index])
            continue
        target_index = target_edge_set.get(edge)
        if target_index is None:
            return None
        if target_index in local_set:
            local_labels.add(pred_labels[pred_index])
        else:
            fixed_labels[target_index] = pred_labels[pred_index]
    local_labels.add(old_m + 1)
    if len(local_labels) != len(target_local):
        return None

    tried = 0
    local_label_list = sorted(local_labels, reverse=True)
    for perm in permutations(local_label_list):
        tried += 1
        if tried > max_permutations:
            break
        labels = fixed_labels[:]
        for edge_index, label in zip(target_local, perm):
            labels[edge_index] = label
        if verify_antimagic(n, target_edges, labels):
            return labels
    return None


def try_lift_with_boundary_repair(
    pred_edges: list[Edge],
    pred_labels: list[int],
    target_edges: list[Edge],
    radius: int,
    node_limit: int,
) -> list[int] | None:
    """Repair a bounded neighborhood while keeping the rest of the lift fixed.

    The local labels are searched with incremental vertex-sum checks.  Vertices
    whose incident edges are all frozen provide boundary sums that the local
    assignment must avoid.
    """
    old_m = len(pred_edges)
    pred_edge_set = {tuple(sorted(edge)): i for i, edge in enumerate(pred_edges)}
    target_edge_set = {tuple(sorted(edge)): i for i, edge in enumerate(target_edges)}
    n = 1 + max(max(u, v) for u, v in target_edges)
    common = set(pred_edge_set) & set(target_edge_set)
    missing_pred = [edge for edge in pred_edge_set if edge not in common]
    extra_target = [edge for edge in target_edge_set if edge not in common]
    if len(missing_pred) != 1 or len(extra_target) != 2:
        return None

    # Distances from the old split edge determine the mutable neighborhood.
    starts = set(missing_pred[0])
    adj = [[] for _ in range(n)]
    for edge_index, (u, v) in enumerate(target_edges):
        adj[u].append((v, edge_index))
        adj[v].append((u, edge_index))
    dist = [-1] * n
    queue = list(starts)
    for u in starts:
        dist[u] = 0
    head = 0
    while head < len(queue):
        u = queue[head]
        head += 1
        for v, _edge_index in adj[u]:
            if dist[v] == -1:
                dist[v] = dist[u] + 1
                queue.append(v)

    local_set = {
        i for i, (u, v) in enumerate(target_edges)
        if min(dist[u], dist[v]) <= radius
    }
    local_set.update(target_edge_set[edge] for edge in extra_target)
    local_edges = sorted(local_set, key=lambda i: (-(len(adj[target_edges[i][0]]) + len(adj[target_edges[i][1]])), i))
    fixed_labels = [0] * len(target_edges)
    sums = [0] * n
    local_degree = [0] * n
    local_labels = {old_m + 1}

    for edge_index, (u, v) in enumerate(target_edges):
        if edge_index in local_set:
            local_degree[u] += 1
            local_degree[v] += 1
            if (u, v) in target_edge_set:
                pass
        else:
            edge = tuple(sorted((u, v)))
            pred_index = pred_edge_set.get(edge)
            if pred_index is None:
                return None
            fixed_labels[edge_index] = pred_labels[pred_index]
            sums[u] += fixed_labels[edge_index]
            sums[v] += fixed_labels[edge_index]

    old_split_label = pred_labels[pred_edge_set[missing_pred[0]]]
    local_labels.add(old_split_label)
    for edge_index in local_set:
        edge = tuple(sorted(target_edges[edge_index]))
        if edge in common and edge != missing_pred[0]:
            local_labels.add(pred_labels[pred_edge_set[edge]])
    if len(local_labels) != len(local_edges):
        return None

    # Reject collisions already forced entirely by the frozen part.
    frozen_vertices = [u for u in range(n) if local_degree[u] == 0]
    if len({sums[u] for u in frozen_vertices}) != len(frozen_vertices):
        return None
    frozen_sums = {sums[u] for u in frozen_vertices}
    assigned_local = [False] * len(target_edges)
    labels = fixed_labels[:]
    used = set(fixed_labels) - {0}
    nodes = 0
    started = time.time()

    def backtrack(pos: int) -> bool:
        nonlocal nodes
        nodes += 1
        if nodes > node_limit:
            return False
        if pos == len(local_edges):
            return len(set(sums)) == n
        edge_index = local_edges[pos]
        u, v = target_edges[edge_index]
        for label in sorted(local_labels - used, reverse=True):
            labels[edge_index] = label
            used.add(label)
            sums[u] += label
            sums[v] += label
            assigned_local[edge_index] = True

            # A vertex becomes final when all of its local edges are assigned.
            final_vertices = []
            ok = True
            for vertex in (u, v):
                if all(
                    assigned_local[i] or i not in local_set
                    for i, (a, b) in enumerate(target_edges)
                    if vertex in (a, b)
                ):
                    final_vertices.append(vertex)
            final_sums = [sums[x] for x in final_vertices]
            if len(set(final_sums)) != len(final_sums):
                ok = False
            if ok and any(value in frozen_sums for value in final_sums):
                ok = False
            if ok and backtrack(pos + 1):
                return True

            assigned_local[edge_index] = False
            sums[u] -= label
            sums[v] -= label
            used.remove(label)
            labels[edge_index] = 0
        return False

    if backtrack(0) and verify_antimagic(n, target_edges, labels):
        return labels
    return None


def load_solved_log(path: str) -> dict[str, tuple[int, list[Edge], list[int]]]:
    solved = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("solved") != "1":
                continue
            edges = []
            for token in row["edges"].split():
                a, b = token.split("-", 1)
                edges.append((int(a), int(b)))
            solved[row["case"]] = (int(row["vertices"]), edges, parse_edge_labels(row["edge_labels"]))
    return solved


def label_variants(labels: list[int], use_complement: bool) -> Iterable[list[int]]:
    yield labels
    if use_complement:
        m = len(labels)
        yield [m + 1 - label for label in labels]


def generate_source_variants(
    edges: list[Edge],
    labels: list[int],
    count: int,
    window: int,
    max_permutations: int,
) -> list[list[int]]:
    """Generate a few valid alternatives by repairing small source windows."""
    if count <= 1:
        return [labels]
    n = 1 + max(max(u, v) for u, v in edges)
    adj = [[] for _ in range(n)]
    for edge_index, (u, v) in enumerate(edges):
        adj[u].append((v, edge_index))
        adj[v].append((u, edge_index))
    variants = [labels]
    seen = {tuple(labels)}
    for center in range(len(edges)):
        if len(variants) >= count:
            break
        center_u, center_v = edges[center]
        dist = [-1] * n
        queue = [center_u, center_v]
        dist[center_u] = dist[center_v] = 0
        head = 0
        while head < len(queue):
            u = queue[head]
            head += 1
            for v, _edge_index in adj[u]:
                if dist[v] == -1:
                    dist[v] = dist[u] + 1
                    queue.append(v)
        local = sorted(
            range(len(edges)),
            key=lambda i: (min(dist[edges[i][0]], dist[edges[i][1]]), i),
        )[:window]
        local_labels = [labels[i] for i in local]
        tried = 0
        for perm in permutations(local_labels):
            tried += 1
            if tried > max_permutations:
                break
            if list(perm) == local_labels:
                continue
            candidate = labels[:]
            for edge_index, label in zip(local, perm):
                candidate[edge_index] = label
            key = tuple(candidate)
            if key in seen:
                continue
            if verify_antimagic(n, edges, candidate):
                seen.add(key)
                variants.append(candidate)
                if len(variants) >= count:
                    break
    return variants


def run(args: argparse.Namespace) -> int:
    solved = load_solved_log(args.source_log)
    source_variant_cache: dict[str, list[list[int]]] = {}
    target_cases = [
        item for item in five_leaf_nonspider_by_edges_cases(args.target_edges)
        if len(item[2]) == args.target_edges
    ]
    total = 0
    source_found = 0
    extended = 0
    rows = []
    for case_name, n, target_edges in target_cases:
        total += 1
        found_pred = ""
        success = False
        labels = None
        for pred_name in predecessor_names(case_name):
            pred = solved.get(pred_name)
            if pred is None:
                continue
            if not found_pred:
                found_pred = pred_name
            _pred_n, pred_edges, pred_labels = pred
            if pred_name not in source_variant_cache:
                source_variant_cache[pred_name] = generate_source_variants(
                    pred_edges,
                    pred_labels,
                    args.source_variants,
                    args.source_window,
                    args.source_max_permutations,
                )
            for source_variant in source_variant_cache[pred_name]:
                for variant in label_variants(source_variant, args.try_complement):
                    if args.mode == "simple":
                        labels = try_lift_by_matching_target(pred_edges, variant, target_edges)
                    elif args.mode == "local":
                        labels = try_lift_with_local_permutation(
                            pred_edges,
                            variant,
                            target_edges,
                            args.window,
                            args.max_permutations,
                        )
                    else:
                        labels = try_lift_with_boundary_repair(
                            pred_edges,
                            variant,
                            target_edges,
                            args.radius,
                            args.node_limit,
                        )
                    if labels is not None:
                        success = True
                        found_pred = pred_name
                        break
                if success:
                    break
            if success:
                break
            if not args.try_all_predecessors:
                break
        source_found += int(bool(found_pred))
        extended += int(success)
        rows.append(
            {
                "case": case_name,
                "vertices": n,
                "source_found": int(bool(found_pred)),
                "extended": int(success),
                "predecessor": found_pred,
                "edges": edge_string(target_edges),
                "edge_labels": edge_labels_string(labels),
            }
        )
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["case", "vertices", "source_found", "extended", "predecessor", "edges", "edge_labels"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"target_edges={args.target_edges}, cases={total}, source_found={source_found}, extended={extended}")
    print(f"output: {args.output}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Test simple antimagic labeling extension rules.")
    parser.add_argument("--source-log", required=True)
    parser.add_argument("--target-edges", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=["simple", "local", "adaptive"], default="simple")
    parser.add_argument("--window", type=int, default=5, help="number of nearby target edges to permute in local mode")
    parser.add_argument("--max-permutations", type=int, default=5040)
    parser.add_argument("--radius", type=int, default=2, help="edge-neighborhood radius for adaptive repair")
    parser.add_argument("--node-limit", type=int, default=100000, help="search-node limit per predecessor in adaptive mode")
    parser.add_argument("--try-all-predecessors", action="store_true")
    parser.add_argument("--try-complement", action="store_true", help="also try m+1-label on each predecessor labeling")
    parser.add_argument("--source-variants", type=int, default=1, help="number of cached valid source labelings to try")
    parser.add_argument("--source-window", type=int, default=5, help="source edge window size for variant generation")
    parser.add_argument("--source-max-permutations", type=int, default=120)
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
