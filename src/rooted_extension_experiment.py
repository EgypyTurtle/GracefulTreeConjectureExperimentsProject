#!/usr/bin/env python3
"""Small-scale experiment for reusable graceful leaf-extension certificates.

The main search program works on a structured five-leaf family.  This module
tests a broader idea without opening its SQLite cache: solve a rooted tree once,
then try every vertex and every possible label gap for attaching one new leaf.
Each successful child is stored as a certificate and can be processed without
running the solver again.

This is an experiment and a sufficient certificate finder.  A failed parent or
failed gap search is not a proof that the corresponding tree is non-graceful.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    from graceful_tree import (
        build_adj,
        solve_graceful,
        solve_graceful_branch_differences,
        verify_labeling,
    )
except ModuleNotFoundError:  # pragma: no cover - useful when imported from repo root
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from graceful_tree import (
        build_adj,
        solve_graceful,
        solve_graceful_branch_differences,
        verify_labeling,
    )


Shape = tuple


def shape_code(shape: Shape) -> str:
    """Return an AHU-style code for a rooted unlabeled tree shape."""
    return "(" + "".join(shape_code(child) for child in shape) + ")"


def canonical_shape(children: tuple[Shape, ...] | list[Shape]) -> Shape:
    return tuple(sorted(children, key=shape_code))


def shape_size(shape: Shape) -> int:
    return 1 + sum(shape_size(child) for child in shape)


def add_leaf_at_every_vertex(shape: Shape):
    """Yield rooted shapes obtained by attaching a leaf at every vertex."""
    yield canonical_shape((*shape, ()))
    for index, child in enumerate(shape):
        for new_child in add_leaf_at_every_vertex(child):
            children = list(shape)
            children[index] = new_child
            yield canonical_shape(children)


def rooted_shape_layers(max_vertices: int) -> dict[int, set[Shape]]:
    """Generate all rooted tree types up to ``max_vertices``."""
    if max_vertices < 1:
        raise ValueError("max_vertices must be positive")
    layers: dict[int, set[Shape]] = {1: {()}}
    for vertices in range(1, max_vertices):
        next_layer: set[Shape] = set()
        for shape in layers[vertices]:
            next_layer.update(add_leaf_at_every_vertex(shape))
        layers[vertices + 1] = next_layer
    return layers


def shape_edges(shape: Shape) -> list[tuple[int, int]]:
    """Convert a rooted shape to edges in its canonical preorder."""
    edges: list[tuple[int, int]] = []
    next_vertex = 0

    def visit(node: Shape, parent: int | None) -> None:
        nonlocal next_vertex
        vertex = next_vertex
        next_vertex += 1
        if parent is not None:
            edges.append((parent, vertex))
        for child in node:
            visit(child, vertex)

    visit(shape, None)
    return edges


def attach_shape_at_vertex(shape: Shape, target: int) -> Shape:
    """Return the canonical shape after attaching a leaf at preorder vertex."""
    if not 0 <= target < shape_size(shape):
        raise IndexError("target vertex is outside the rooted shape")
    if target == 0:
        return canonical_shape((*shape, ()))

    offset = 1
    children = list(shape)
    for index, child in enumerate(shape):
        child_vertices = shape_size(child)
        if target < offset + child_vertices:
            children[index] = attach_shape_at_vertex(child, target - offset)
            return canonical_shape(children)
        offset += child_vertices
    raise AssertionError("preorder target was not found")


def attach_with_gap(
    shape: Shape,
    labels: tuple[int, ...],
    target: int,
    gap: int,
) -> tuple[Shape, tuple[int, ...]]:
    """Attach a leaf using an insertion gap and remap labels canonically.

    If the parent has ``m`` edges, old labels >= ``gap`` are shifted by one,
    and the new leaf receives ``gap``.  The result is a valid certificate only
    when its edge differences are exactly 1..m+1.
    """
    vertices = shape_size(shape)
    if len(labels) != vertices:
        raise ValueError("label count does not match the rooted shape")
    if not 0 <= target < vertices:
        raise IndexError("target vertex is outside the rooted shape")
    if not 0 <= gap <= vertices:
        raise ValueError("gap must be in 0..m+1")

    shifted = tuple(label + int(label >= gap) for label in labels)

    def visit(node: Shape, sublabels: tuple[int, ...], local_target: int):
        root_label = sublabels[0]
        children: list[tuple[Shape, tuple[int, ...]]] = []
        offset = 1
        if local_target == 0:
            children.append(((), (gap,)))
        for child in node:
            child_vertices = shape_size(child)
            child_labels = sublabels[offset : offset + child_vertices]
            if local_target != 0 and offset <= local_target < offset + child_vertices:
                child_result = visit(
                    child,
                    child_labels,
                    local_target - offset,
                )
                children.append(child_result)
            else:
                children.append((child, child_labels))
            offset += child_vertices
        if local_target != 0 and offset <= local_target:
            raise AssertionError("preorder target was not found")
        children.sort(key=lambda item: (shape_code(item[0]), item[1]))
        result_shape = tuple(child_shape for child_shape, _child_labels in children)
        result_labels = (root_label,)
        for _child_shape, child_labels in children:
            result_labels += child_labels
        return result_shape, result_labels

    result_shape, result_labels = visit(shape, shifted, target)
    if len(result_labels) != vertices + 1:
        raise AssertionError("leaf extension changed the wrong number of vertices")
    return result_shape, result_labels


@dataclass(frozen=True)
class ExtensionCertificate:
    labels: tuple[int, ...]
    parent_code: str
    target: int
    gap: int


def find_extensions(
    shape: Shape,
    labels: tuple[int, ...],
    certificates: dict[Shape, ExtensionCertificate],
) -> int:
    """Try all one-leaf extensions and add verified child certificates."""
    edges = shape_edges(shape)
    vertices = shape_size(shape)
    maximum_difference = vertices
    added = 0
    parent_code = shape_code(shape)
    for gap in range(vertices + 1):
        shifted = [label + int(label >= gap) for label in labels]
        counts = [0] * (maximum_difference + 1)
        valid_old_edges = True
        for left, right in edges:
            difference = abs(shifted[left] - shifted[right])
            if difference == 0 or difference > maximum_difference or counts[difference]:
                valid_old_edges = False
                break
            counts[difference] = 1
        if not valid_old_edges:
            continue
        missing = next(
            (difference for difference in range(1, maximum_difference + 1) if not counts[difference]),
            None,
        )
        if missing is None:
            continue
        for target in range(vertices):
            if abs(shifted[target] - gap) != missing:
                continue
            child_shape, child_labels = attach_with_gap(shape, labels, target, gap)
            child_edges = shape_edges(child_shape)
            if not verify_labeling(child_edges, list(child_labels)):
                raise AssertionError("fast gap check disagreed with certificate verification")
            if child_shape not in certificates:
                certificates[child_shape] = ExtensionCertificate(
                    labels=child_labels,
                    parent_code=parent_code,
                    target=target,
                    gap=gap,
                )
                added += 1
    return added


def solve_one_shape(shape: Shape, time_limit: float) -> tuple[tuple[int, ...] | None, str, float]:
    """Find one labeling, using branch search then exact fallback."""
    started = time.time()
    adj = build_adj(shape_size(shape), shape_edges(shape))
    labels, _stats = solve_graceful_branch_differences(adj, time_limit=time_limit)
    if labels is not None:
        return tuple(labels), "branch", time.time() - started
    remaining = max(0.0, time_limit - (time.time() - started))
    if remaining <= 0:
        return None, "timeout", time.time() - started
    labels, _stats = solve_graceful(adj, time_limit=remaining)
    if labels is not None:
        return tuple(labels), "exact", time.time() - started
    return None, "unsolved", time.time() - started


def run_experiment(
    max_vertices: int,
    time_limit: float,
    progress: int = 100,
    csv_path: str | None = None,
) -> list[dict[str, int | float]]:
    """Run the rooted closure experiment and return one row per layer."""
    layers = rooted_shape_layers(max_vertices)
    certificates: dict[Shape, ExtensionCertificate] = {(): ExtensionCertificate((0,), "", 0, 0)}
    rows: list[dict[str, int | float]] = []
    writer = None
    csv_file = None
    if csv_path:
        output = Path(csv_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        csv_file = output.open("w", encoding="utf-8", newline="")
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "vertices",
                "rooted_types",
                "extension_reused",
                "direct_solved",
                "timeouts_or_unsolved",
                "new_child_certificates",
                "next_rooted_types",
                "next_certified_before_search",
                "elapsed_seconds",
            ],
        )
        writer.writeheader()

    try:
        for vertices in range(1, max_vertices + 1):
            started = time.time()
            rooted_types = layers[vertices]
            extension_reused = 0
            direct_solved = 0
            timeouts_or_unsolved = 0
            new_child_certificates = 0

            for index, shape in enumerate(sorted(rooted_types, key=shape_code), start=1):
                certificate = certificates.get(shape)
                labels = certificate.labels if certificate else None
                if labels is not None and verify_labeling(shape_edges(shape), list(labels)):
                    extension_reused += 1
                    source = "extension"
                else:
                    labels, source, _elapsed = solve_one_shape(shape, time_limit)
                    if labels is None:
                        timeouts_or_unsolved += 1
                        continue
                    direct_solved += 1
                new_child_certificates += find_extensions(shape, labels, certificates)
                if progress > 0 and index % progress == 0:
                    print(
                        f"vertices={vertices}: {index}/{len(rooted_types)}, "
                        f"extension={extension_reused}, direct={direct_solved}, "
                        f"unsolved={timeouts_or_unsolved}",
                        flush=True,
                    )

            next_types = len(layers.get(vertices + 1, set()))
            next_certified = (
                sum(shape in certificates for shape in layers.get(vertices + 1, set()))
                if vertices < max_vertices
                else 0
            )
            row: dict[str, int | float] = {
                "vertices": vertices,
                "rooted_types": len(rooted_types),
                "extension_reused": extension_reused,
                "direct_solved": direct_solved,
                "timeouts_or_unsolved": timeouts_or_unsolved,
                "new_child_certificates": new_child_certificates,
                "next_rooted_types": next_types,
                "next_certified_before_search": next_certified,
                "elapsed_seconds": round(time.time() - started, 6),
            }
            rows.append(row)
            print(
                "layer "
                + ", ".join(f"{key}={value}" for key, value in row.items()),
                flush=True,
            )
            if writer:
                writer.writerow(row)
                csv_file.flush()
    finally:
        if csv_file:
            csv_file.close()
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-vertices", type=int, default=10)
    parser.add_argument("--time-limit", type=float, default=2.0)
    parser.add_argument("--progress", type=int, default=100)
    parser.add_argument("--csv", help="optional per-layer CSV output")
    args = parser.parse_args(argv)
    run_experiment(
        max_vertices=args.max_vertices,
        time_limit=args.time_limit,
        progress=args.progress,
        csv_path=args.csv,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
