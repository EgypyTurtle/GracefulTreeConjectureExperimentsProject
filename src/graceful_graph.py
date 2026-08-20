#!/usr/bin/env python3
"""Generic graceful-labeling search for an arbitrary simple graph.

The tree solver in ``graceful_tree.py`` relies on ``m = n - 1`` and on
tree-specific structure.  This module deliberately has neither assumption:
it accepts any simple undirected edge set, including cyclic and disconnected
graphs.  Graph-family generators can import ``solve_graceful_graph`` and
``verify_graceful_labeling`` without depending on a family-specific solver.

For a graph with ``m`` edges, a graceful labeling is an injective map from the
vertices to ``0..m`` whose edge differences are exactly ``1..m``.  The
search assigns differences from large to small.  The difference ``m`` must
join labels ``0`` and ``m``; trying each possible edge for that role is a
complete symmetry-broken initialization, since global label complementation
handles the opposite orientation.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


Edge = tuple[int, int]


@dataclass
class GraphSearchStats:
    nodes: int = 0
    backtracks: int = 0
    started_at: float = 0.0
    strategy: str = "generic-difference"
    timed_out: bool = False
    max_edge_cases: int = 0


def read_edges(path: str | Path) -> list[Edge]:
    """Read one undirected edge ``u v`` per line.

    Blank lines and text after ``#`` are ignored.  Vertex ids may be arbitrary
    integers; ``normalize_edges`` maps them to a compact internal range.
    """

    edges: list[Edge] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.replace(",", " ").split()
            if len(parts) != 2:
                raise ValueError(f"{path}:{line_no}: expected two vertex ids")
            u, v = int(parts[0]), int(parts[1])
            edges.append((u, v))
    return edges


def normalize_edges(
    edges: Iterable[Edge],
    vertices: int | None = None,
) -> tuple[int, list[Edge], list[int]]:
    """Validate an edge set and return ``(n, normalized_edges, original_ids)``.

    When ``vertices`` is supplied, ids are interpreted as ``0..vertices-1``
    and isolated vertices are retained.  Without it, only ids appearing in
    the edge set are included.
    """

    raw = [(int(u), int(v)) for u, v in edges]
    if vertices is not None and vertices < 0:
        raise ValueError("--vertices must be nonnegative")
    if any(u == v for u, v in raw):
        loop = next((u for u, v in raw if u == v), None)
        raise ValueError(f"self-loop is not allowed: {loop}")

    if vertices is None:
        original = sorted({x for edge in raw for x in edge})
    else:
        original = list(range(vertices))
        if any(u < 0 or v < 0 or u >= vertices or v >= vertices for u, v in raw):
            raise ValueError("edge endpoint is outside 0..vertices-1")

    index = {vertex: i for i, vertex in enumerate(original)}
    normalized: list[Edge] = []
    seen: set[Edge] = set()
    for u, v in raw:
        edge = tuple(sorted((index[u], index[v])))
        if edge in seen:
            raise ValueError(f"duplicate edge {u} {v}")
        seen.add(edge)
        normalized.append(edge)
    normalized.sort()
    return len(original), normalized, original


def build_adjacency(n: int, edges: list[Edge]) -> list[list[int]]:
    adjacency = [[] for _ in range(n)]
    for u, v in edges:
        if not (0 <= u < n and 0 <= v < n):
            raise ValueError(f"edge out of range: {u} {v}")
        adjacency[u].append(v)
        adjacency[v].append(u)
    return adjacency


def verify_graceful_labeling(n: int, edges: list[Edge], labels: list[int]) -> bool:
    """Verify the ordinary graceful-labeling definition for any graph."""

    m = len(edges)
    if len(labels) != n or n > m + 1:
        return False
    if any(label < 0 or label > m for label in labels):
        return False
    if len(set(labels)) != n:
        return False
    differences = sorted(abs(labels[u] - labels[v]) for u, v in edges)
    return differences == list(range(1, m + 1))


def solve_graceful_graph(
    n: int,
    edges: list[Edge],
    *,
    time_limit: float | None = None,
    max_nodes: int | None = None,
    seed: int | None = None,
    candidate_limit: int | None = None,
) -> tuple[list[int] | None, GraphSearchStats]:
    """Search for a graceful labeling of an arbitrary simple graph.

    The default search is complete if neither ``time_limit``, ``max_nodes``,
    nor ``candidate_limit`` truncates it.  ``candidate_limit`` is explicitly
    a heuristic cutoff and should not be used for exhaustive claims.
    """

    m = len(edges)
    stats = GraphSearchStats(started_at=time.perf_counter())
    rng = random.Random(seed)

    if n <= 0:
        raise ValueError("a graph must have at least one vertex")
    build_adjacency(n, edges)
    if n > m + 1:
        return None, stats
    if m == 0:
        return [0], stats

    adjacency = build_adjacency(n, edges)
    degrees = [len(neighbors) for neighbors in adjacency]
    current_difference = 0

    def timed_out() -> bool:
        if max_nodes is not None and stats.nodes >= max_nodes:
            stats.timed_out = True
            return True
        if time_limit is not None and time.perf_counter() - stats.started_at >= time_limit:
            stats.timed_out = True
            return True
        return False

    def can_assign(
        labels: list[int],
        used_labels: list[bool],
        edge_index: int,
        low: int,
        high_at_u: bool,
    ) -> tuple[bool, list[tuple[int, int]]]:
        u, v = edges[edge_index]
        high = low + current_difference
        assignments = [(u, high), (v, low)] if high_at_u else [(u, low), (v, high)]
        changes: list[tuple[int, int]] = []
        changed_vertices: set[int] = set()
        for vertex, label in assignments:
            if vertex in changed_vertices:
                return False, []
            changed_vertices.add(vertex)
            current = labels[vertex]
            if current != -1:
                if current != label:
                    return False, []
                continue
            if used_labels[label] or any(old_label == label for _, old_label in changes):
                return False, []
            changes.append((vertex, label))
        return True, changes

    def candidate_moves(
        labels: list[int],
        used_labels: list[bool],
        used_edges: list[bool],
        difference: int,
    ) -> list[tuple[int, list[tuple[int, int]], tuple[int, int, int, int]]]:
        """Return legal placements, ordered by constraint strength."""

        nonlocal current_difference
        current_difference = difference
        moves: list[tuple[int, list[tuple[int, int]], tuple[int, int, int, int]]] = []
        for edge_index, (u, v) in enumerate(edges):
            if timed_out():
                return moves
            if used_edges[edge_index]:
                continue
            lu, lv = labels[u], labels[v]
            known = int(lu != -1) + int(lv != -1)
            if lu != -1 and lv != -1:
                if abs(lu - lv) != difference:
                    continue
                ok, changes = can_assign(labels, used_labels, edge_index, min(lu, lv), lu > lv)
                if ok:
                    score = (2, known, degrees[u] + degrees[v], -edge_index)
                    moves.append((edge_index, changes, score))
                continue

            if lu != -1:
                lows = [lu - difference, lu]
            elif lv != -1:
                lows = [lv - difference, lv]
            else:
                lows = range(0, m - difference + 1)

            for low in lows:
                if timed_out():
                    return moves
                if not (0 <= low <= m - difference):
                    continue
                orientations = (False, True) if lu == -1 and lv == -1 else (False, True)
                for high_at_u in orientations:
                    ok, changes = can_assign(labels, used_labels, edge_index, low, high_at_u)
                    if not ok:
                        continue
                    score = (known, known, degrees[u] + degrees[v], -edge_index)
                    moves.append((edge_index, changes, score))

        if seed is not None:
            rng.shuffle(moves)
        moves.sort(key=lambda item: item[2], reverse=True)
        if candidate_limit is not None:
            return moves[:candidate_limit]
        return moves

    def next_difference_has_move(
        labels: list[int],
        used_labels: list[bool],
        used_edges: list[bool],
        difference: int,
    ) -> bool:
        if difference <= 0:
            return True
        return bool(candidate_moves(labels, used_labels, used_edges, difference))

    def backtrack(
        difference: int,
        labels: list[int],
        used_labels: list[bool],
        used_edges: list[bool],
    ) -> bool:
        if timed_out():
            return False
        stats.nodes += 1
        if difference == 0:
            return True

        moves = candidate_moves(labels, used_labels, used_edges, difference)
        for edge_index, changes, _score in moves:
            if timed_out():
                return False
            used_edges[edge_index] = True
            for vertex, label in changes:
                labels[vertex] = label
                used_labels[label] = True

            if next_difference_has_move(labels, used_labels, used_edges, difference - 1) and backtrack(
                difference - 1, labels, used_labels, used_edges
            ):
                return True

            for vertex, label in reversed(changes):
                labels[vertex] = -1
                used_labels[label] = False
            used_edges[edge_index] = False
        stats.backtracks += 1
        return False

    # The edge carrying difference m must join labels 0 and m.  Enumerating
    # its position is necessary for arbitrary graphs; fixing its orientation
    # loses no solutions because complementing all labels swaps the orientation.
    for max_edge_index, (u, v) in enumerate(edges):
        if timed_out():
            break
        stats.max_edge_cases += 1
        labels = [-1] * n
        used_labels = [False] * (m + 1)
        used_edges = [False] * m
        labels[u] = 0
        labels[v] = m
        used_labels[0] = True
        used_labels[m] = True
        used_edges[max_edge_index] = True
        if backtrack(m - 1, labels, used_labels, used_edges):
            # Isolated vertices have no difference constraints.  Fill them
            # with any remaining labels so the returned object is total.
            unused = [label for label, used in enumerate(used_labels) if not used]
            for vertex, label in enumerate(labels):
                if label == -1:
                    if not unused:
                        break
                    labels[vertex] = unused.pop()
            if verify_graceful_labeling(n, edges, labels):
                return labels, stats
        # The arrays are recreated for the next possible maximum-difference
        # edge, so no state needs to be undone here.

    return None, stats


def print_solution(edges: list[Edge], labels: list[int], original_ids: list[int]) -> None:
    print("graceful labeling found")
    print("vertices:")
    for internal, label in enumerate(labels):
        print(f"  {original_ids[internal]}: {label}")
    print("edge differences:")
    for u, v in edges:
        print(f"  {original_ids[u]} {original_ids[v]}: {abs(labels[u] - labels[v])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Search for a graceful labeling of an arbitrary simple graph."
    )
    parser.add_argument("--edges", required=True, help="edge file with one 'u v' per line")
    parser.add_argument(
        "--vertices",
        type=int,
        help="number of vertices; retain isolated vertices with ids 0..N-1",
    )
    parser.add_argument("--time-limit", type=float, help="seconds before stopping")
    parser.add_argument("--max-nodes", type=int, help="node limit before stopping")
    parser.add_argument("--candidate-limit", type=int, help="heuristic candidate cutoff per difference")
    parser.add_argument("--seed", type=int, help="shuffle tied candidate moves")
    parser.add_argument("--show-edges", action="store_true", help="print normalized input edges")
    args = parser.parse_args(argv)

    try:
        raw_edges = read_edges(args.edges)
        n, edges, original_ids = normalize_edges(raw_edges, args.vertices)
        if n == 0:
            raise ValueError("edge file contains no vertices; use --vertices 1 for the one-vertex graph")
        if n > len(edges) + 1:
            print(
                f"no graceful labeling: {n} vertices require at least {n - 1} edges, "
                f"but the graph has {len(edges)}",
                file=sys.stderr,
            )
            return 2
        if args.show_edges:
            print("normalized edges:")
            for u, v in edges:
                print(f"  {original_ids[u]} {original_ids[v]}")

        labels, stats = solve_graceful_graph(
            n,
            edges,
            time_limit=args.time_limit,
            max_nodes=args.max_nodes,
            seed=args.seed,
            candidate_limit=args.candidate_limit,
        )
        elapsed = time.perf_counter() - stats.started_at
        if labels is None:
            if stats.timed_out:
                print(
                    f"no labeling found before limit; searched {stats.nodes} nodes "
                    f"in {elapsed:.3f}s"
                )
            else:
                print(
                    f"no graceful labeling found; exhausted {stats.nodes} search nodes "
                    f"in {elapsed:.3f}s"
                )
            return 2
        print_solution(edges, labels, original_ids)
        print(f"strategy: {stats.strategy}")
        print(
            f"searched {stats.nodes} nodes, {stats.backtracks} backtracks, "
            f"{elapsed:.3f}s"
        )
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
