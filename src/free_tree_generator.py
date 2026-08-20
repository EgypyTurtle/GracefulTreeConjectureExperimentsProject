#!/usr/bin/env python3
"""Canonical generator for unlabeled (free) trees.

The generator uses leaf augmentation: every tree on n+1 vertices can be
obtained by attaching a new leaf to a tree on n vertices.  Each candidate is
canonicalized at the one or two centers of the resulting tree, so isomorphic
duplicates are removed before the next layer is stored.

Only canonical rooted-shape strings are kept in a layer.  This is deliberately
separate from the graceful solver until the counts have been checked against
the standard free-tree sequence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from rooted_extension_experiment import (
        Shape,
        attach_shape_at_vertex,
        shape_code,
        shape_edges,
        shape_size,
    )
except ModuleNotFoundError:  # pragma: no cover - useful when imported from repo root
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from rooted_extension_experiment import (
        Shape,
        attach_shape_at_vertex,
        shape_code,
        shape_edges,
        shape_size,
    )


def parse_shape(code: str) -> Shape:
    """Parse a parenthesized rooted-tree code into a nested tuple shape."""
    stack: list[list[Shape]] = []
    result: Shape | None = None
    for character in code:
        if character == "(":
            stack.append([])
        elif character == ")":
            if not stack:
                raise ValueError("unbalanced rooted shape code")
            node = tuple(stack.pop())
            if stack:
                stack[-1].append(node)
            else:
                result = node
        elif not character.isspace():
            raise ValueError(f"unexpected shape-code character: {character!r}")
    if stack or result is None:
        raise ValueError("incomplete rooted shape code")
    return result


def adjacency_from_shape(shape: Shape) -> list[list[int]]:
    """Build an adjacency list in the shape's preorder vertex numbering."""
    edges = shape_edges(shape)
    n = shape_size(shape)
    adjacency = [[] for _ in range(n)]
    for left, right in edges:
        adjacency[left].append(right)
        adjacency[right].append(left)
    return adjacency


def tree_centers(adjacency: list[list[int]]) -> list[int]:
    """Return the one or two centers of a tree by leaf peeling."""
    n = len(adjacency)
    if n <= 2:
        return list(range(n))
    degrees = [len(neighbors) for neighbors in adjacency]
    leaves = [vertex for vertex, degree in enumerate(degrees) if degree <= 1]
    remaining = n
    while remaining > 2:
        remaining -= len(leaves)
        next_leaves: list[int] = []
        for leaf in leaves:
            for neighbor in adjacency[leaf]:
                degrees[neighbor] -= 1
                if degrees[neighbor] == 1:
                    next_leaves.append(neighbor)
        leaves = next_leaves
    return sorted(leaves)


def rooted_shape_from_adjacency(
    adjacency: list[list[int]], root: int, parent: int = -1
) -> Shape:
    children = [
        rooted_shape_from_adjacency(adjacency, child, root)
        for child in adjacency[root]
        if child != parent
    ]
    return tuple(sorted(children, key=shape_code))


def free_tree_code(shape: Shape) -> str:
    """Return the canonical code of an unrooted tree represented by ``shape``."""
    adjacency = adjacency_from_shape(shape)
    centers = tree_centers(adjacency)
    rooted_candidates = [
        rooted_shape_from_adjacency(adjacency, center) for center in centers
    ]
    return shape_code(min(rooted_candidates, key=shape_code))


def free_tree_layers(max_vertices: int, progress: int = 0) -> dict[int, set[str]]:
    """Generate canonical free-tree codes through ``max_vertices``."""
    if max_vertices < 1:
        raise ValueError("max_vertices must be positive")
    layers: dict[int, set[str]] = {1: {"()"}}
    for vertices in range(1, max_vertices):
        current = layers[vertices]
        next_codes: set[str] = set()
        for index, code in enumerate(sorted(current), start=1):
            shape = parse_shape(code)
            for target in range(vertices):
                child = attach_shape_at_vertex(shape, target)
                next_codes.add(free_tree_code(child))
            if progress > 0 and index % progress == 0:
                print(
                    f"generate {vertices}->{vertices + 1}: "
                    f"{index}/{len(current)}, candidates={len(next_codes)}",
                    flush=True,
                )
        layers[vertices + 1] = next_codes
        print(
            f"vertices={vertices + 1}: free_tree_types={len(next_codes)}",
            flush=True,
        )
    return layers


def iter_free_tree_layers(max_vertices: int, progress: int = 0):
    """Yield one free-tree layer at a time to keep memory bounded."""
    if max_vertices < 1:
        raise ValueError("max_vertices must be positive")
    current = {"()"}
    yield 1, current
    for vertices in range(1, max_vertices):
        next_codes: set[str] = set()
        for index, code in enumerate(sorted(current), start=1):
            shape = parse_shape(code)
            for target in range(vertices):
                child = attach_shape_at_vertex(shape, target)
                next_codes.add(free_tree_code(child))
            if progress > 0 and index % progress == 0:
                print(
                    f"generate {vertices}->{vertices + 1}: "
                    f"{index}/{len(current)}, candidates={len(next_codes)}",
                    flush=True,
                )
        current = next_codes
        yield vertices + 1, current


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-vertices", type=int, default=15)
    parser.add_argument("--progress", type=int, default=0)
    args = parser.parse_args(argv)
    free_tree_layers(args.max_vertices, progress=args.progress)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
