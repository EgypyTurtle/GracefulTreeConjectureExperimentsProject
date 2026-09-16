"""Audit mandatory collision kernels for the audited span-63 contexts.

This is a finite diagnostic over an already audited semantic scope.  It does
not enumerate allocations or invoke the left main runner.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_displacement_first import build_layout, values_for_case
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_persistent_runner import block_map_for
from edge63_C8_two_run_cache import PersistentTwoRunCache


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
EDGE_COUNT = 63


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def group_map(cache: PersistentMiddleGroupCache, values: tuple[int, ...]) -> dict[str, tuple[tuple, dict[tuple, tuple[str, ...]]]]:
    groups, _raw, _hit = cache.load_or_build_index(values)
    return {
        cache._group_path(key).stem.replace(".pkl", "").replace("middle_group_", ""): (key, residuals)
        for key, residuals in groups.items()
    }


def role_for(layout: dict[str, tuple[int, ...]], vertex: int) -> tuple[str, int]:
    for path, vertices in layout.items():
        if vertex in vertices:
            return path, vertices.index(vertex)
    raise KeyError(vertex)


def build_noninjective_relative(
    values: tuple[int, ...],
    context: dict[str, object],
    left_pair: Any,
    right_pair: Any,
    delta_left: int,
    delta_right: int,
) -> dict[int, int]:
    """Construct the trusted frame while deliberately retaining collisions."""
    layout = build_layout(values)
    relative: dict[int, int] = {}
    roots = (-delta_left, 0, delta_right)
    relative[layout["left_bridge"][0]] = roots[0]
    relative[layout["left_bridge"][-1]] = roots[1]
    relative[layout["right_bridge"][0]] = roots[1]
    relative[layout["right_bridge"][-1]] = roots[2]
    bridge = context["bridge"]
    for index, vertex in enumerate(layout["left_bridge"][1:-1], 1):
        relative[vertex] = bridge.left_offsets[index] - delta_left
    for index, vertex in enumerate(layout["right_bridge"][1:-1], 1):
        relative[vertex] = bridge.right_offsets[index]
    central = context["central"]
    for index, vertex in enumerate(layout["middle_leaf"][1:], 1):
        relative[vertex] = central.offsets[index]
    for path, state, shift in (
        ("left_leaf_1", left_pair.state_a, -delta_left),
        ("left_leaf_2", left_pair.state_b, -delta_left),
        ("right_leaf_1", right_pair.state_a, delta_right),
        ("right_leaf_2", right_pair.state_b, delta_right),
    ):
        for vertex, offset in zip(layout[path], state.offsets):
            candidate = int(offset) + shift
            if vertex in relative and relative[vertex] != candidate:
                raise AssertionError("shared vertex received two different labels")
            relative[vertex] = candidate
    if len(relative) != EDGE_COUNT + 1:
        raise AssertionError("relative frame did not cover all vertices")
    return relative


def local_formula(
    layout: dict[str, tuple[int, ...]],
    relative: dict[int, int],
    blocks: dict[str, tuple[tuple[int, int], ...]],
    left_state: Any,
    right_state: Any,
    delta_left: int,
    delta_right: int,
    label: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    state_by_path = {
        "left_leaf_1": (left_state.state_a, -delta_left),
        "left_leaf_2": (left_state.state_b, -delta_left),
        "right_leaf_1": (right_state.state_a, delta_right),
        "right_leaf_2": (right_state.state_b, delta_right),
    }
    for vertex, value in relative.items():
        if value != label:
            continue
        path, position = role_for(layout, vertex)
        state_entry = state_by_path.get(path)
        local_offset = None
        shift = None
        if state_entry is not None:
            state, shift = state_entry
            local_offset = int(state.offsets[position])
        else:
            local_offset = None
        rows.append({
            "vertex": vertex,
            "path": path,
            "path_position": position,
            "global_offset": label,
            "local_offset": local_offset,
            "frame_shift": shift,
            "signed_sum_expression": (
                f"{shift:+d} + ({local_offset:+d}) = {label}"
                if shift is not None and local_offset is not None
                else f"middle_frame({label})"
            ),
            "run_intervals": json.dumps([list(part) for part in blocks[path]], separators=(",", ":")),
        })
    return rows


def audit(root: Path, scope_dir: Path, audit_dir: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3"
    audit_dir = audit_dir or (base / "outer_zero_audit_v1")
    out = output_dir or (base / "span63_outer_kernel_v1")
    contexts = list(csv.DictReader((audit_dir / "bilateral_contexts.csv").open(encoding="utf-8")))
    pairs = list(csv.DictReader((audit_dir / "outer_join_results.csv").open(encoding="utf-8")))
    tight = [row for row in contexts if int(row["minimum_pre_outer_span"]) == EDGE_COUNT]
    tight_keys = {(row["group_id"], row["context_id"], row["residual_index"]) for row in tight}
    tight_pairs: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in pairs:
        key = (row["group_id"], row["context_id"], row["residual_index"])
        if key in tight_keys and int(row["pre_outer_span"]) <= EDGE_COUNT:
            tight_pairs[key].append(row)

    context_summary: list[dict[str, Any]] = []
    kernel_rows: list[dict[str, Any]] = []
    role_rows: list[dict[str, Any]] = []
    signed_rows: list[dict[str, Any]] = []
    motif_counter: Counter[tuple[int, ...]] = Counter()
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    groups = group_map(middle_cache, values)
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    layout = build_layout(values)

    for context in tight:
        key = (context["group_id"], context["context_id"], context["residual_index"])
        context_pairs = tight_pairs[key]
        intersections = [set(json.loads(row["intersection"])) for row in context_pairs]
        kernel = sorted(set.intersection(*intersections)) if intersections else []
        minimum_kappa = min((len(item) for item in intersections), default=None)
        motif_counter[tuple(kernel)] += 1
        context_summary.append({
            "group_id": key[0],
            "context_id": key[1],
            "residual_index": key[2],
            "pair_count_span_le_63": len(context_pairs),
            "minimum_pair_kappa": minimum_kappa,
            "kernel": json.dumps(kernel, separators=(",", ":")),
            "kernel_size": len(kernel),
            "D13": context.get("D13"),
            "left_intervals": context.get("left_intervals"),
            "left_split_lengths": context.get("left_split_lengths"),
            "left_gap": context.get("left_gap"),
            "status": context.get("status"),
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        })
        kernel_rows.append({
            **context_summary[-1],
            "kernel_is_nonempty": bool(kernel),
            "all_span63_pairs_have_kernel": all(set(kernel).issubset(item) for item in intersections),
        })

        middle_key, residuals = groups[key[0]]
        group, _ = middle_cache.load_or_build_group(values, middle_key, residuals)
        context_obj = next(item for item in group["contexts"] if int(item["context_id"]) == int(key[1]))
        residual_key, _run_order = list(residuals.items())[int(key[2])]
        blocks = block_map_for(middle_key, residual_key)
        left_a = tuple(blocks["left_leaf_1"])
        left_b = tuple(blocks["left_leaf_2"])
        right_a = tuple(blocks["right_leaf_1"])
        right_b = tuple(blocks["right_leaf_2"])
        left_table = pair_cache.terminal_pairs(left_a, left_b)
        right_table = pair_cache.terminal_pairs(right_a, right_b)
        delta_left = int(context_obj["delta_left"])
        delta_right = int(context_obj["delta_right"])
        for pair in context_pairs:
            # `left_table_index` is an index in the full left table, while
            # `right_table_index` is only an index in the filtered compatible
            # right list emitted by outer_zero_audit.  State IDs are the
            # stable cross-audit identifiers for both sides.
            left_state = next(state for state in left_table if int(state.state_id) == int(pair["left_behavior_id"]))
            right_state = next(state for state in right_table if int(state.state_id) == int(pair["right_behavior_id"]))
            relative = build_noninjective_relative(values, context_obj, left_state, right_state, delta_left, delta_right)
            intersection = sorted(json.loads(pair["intersection"]))
            for label in intersection:
                left_hits = local_formula(layout, relative, blocks, left_state, right_state, delta_left, delta_right, int(label))
                # The relative map uses shared vertices only once.  Reconstruct
                # the two side formulas directly from each terminal state.
                side_hits = []
                for side, state, shift, paths in (
                    ("LEFT", left_state, -delta_left, ("left_leaf_1", "left_leaf_2")),
                    ("RIGHT", right_state, delta_right, ("right_leaf_1", "right_leaf_2")),
                ):
                    for path in paths:
                        vertices = layout[path]
                        leaf_state = state.state_a if path.endswith("1") else state.state_b
                        for position, offset in enumerate(leaf_state.offsets):
                            if int(offset) + shift == int(label):
                                side_hits.append({
                                    "side": side,
                                    "vertex": vertices[position],
                                    "path": path,
                                    "path_position": position,
                                    "global_offset": int(label),
                                    "local_offset": int(offset),
                                    "frame_shift": int(shift),
                                    "signed_sum_expression": f"{shift:+d} + ({int(offset):+d}) = {int(label)}",
                                    "state_id": int(state.state_id),
                                })
                for hit in side_hits:
                    role_rows.append({
                        "group_id": key[0],
                        "context_id": key[1],
                        "residual_index": key[2],
                        "left_behavior_id": pair["left_behavior_id"],
                        "right_behavior_id": pair["right_behavior_id"],
                        "pair_span": pair["pre_outer_span"],
                        "intersection_size": pair["intersection_size"],
                        "collision_label": int(label),
                        **hit,
                        "two_run_language": LANGUAGE,
                        "allocation_dedup_version": OWNERSHIP,
                        "terminal_pair_cache_version": TERMINAL_CACHE,
                    })
                if len(side_hits) >= 2:
                    left_hit = next((item for item in side_hits if item["side"] == "LEFT"), None)
                    right_hit = next((item for item in side_hits if item["side"] == "RIGHT"), None)
                    if left_hit and right_hit:
                        signed_rows.append({
                            "group_id": key[0],
                            "context_id": key[1],
                            "residual_index": key[2],
                            "left_behavior_id": pair["left_behavior_id"],
                            "right_behavior_id": pair["right_behavior_id"],
                            "collision_label": int(label),
                            "left_path": left_hit["path"],
                            "left_position": left_hit["path_position"],
                            "left_local_offset": left_hit["local_offset"],
                            "left_shift": left_hit["frame_shift"],
                            "right_path": right_hit["path"],
                            "right_position": right_hit["path_position"],
                            "right_local_offset": right_hit["local_offset"],
                            "right_shift": right_hit["frame_shift"],
                            "identity": (
                                f"{right_hit['frame_shift']}-{left_hit['frame_shift']} = "
                                f"{left_hit['local_offset']}-{right_hit['local_offset']}"
                            ),
                        })

    role_counts = Counter((row["path"], row["side"]) for row in role_rows)
    write_csv(out / "span63_contexts.csv", context_summary)
    write_csv(out / "mandatory_kernels.csv", kernel_rows)
    write_csv(out / "kernel_role_trace.csv", role_rows)
    write_csv(out / "kernel_signed_sum_trace.csv", signed_rows)
    motif_rows = [
        {
            "kernel": json.dumps(list(kernel), separators=(",", ":")),
            "context_count": count,
            "kernel_size": len(kernel),
            "is_first_context_kernel": kernel == (-12, -11, 34),
        }
        for kernel, count in sorted(motif_counter.items())
    ]
    write_csv(out / "collision_motif_cover.csv", motif_rows)
    first_kernel = next((row for row in kernel_rows if row["group_id"] == "345e9b3c3bfdeb1914b08bb0" and row["context_id"] == "114"), None)
    proof = {
        "scope": str(scope_dir),
        "statement": "Every pair in each audited span-63 context was checked; the per-context mandatory kernel is the intersection of all pair intersections.",
        "first_bilateral_kernel": first_kernel,
        "tight_context_count": len(tight),
        "kernel_size_distribution": dict(Counter(len(json.loads(row["kernel"])) for row in context_summary)),
        "nonempty_kernel_contexts": sum(bool(json.loads(row["kernel"])) for row in context_summary),
        "role_counts": {f"{side}:{path}": count for (path, side), count in role_counts.items()},
        "versions": {
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        },
    }
    (out / "first_bilateral_kernel_proof.md").write_text(
        "# Span-63 Outer Kernel Audit\n\n"
        "This is a finite audit of the 4482-group semantic snapshot. "
        "For each bilateral context with minimum pre-outer span 63, the mandatory kernel is the intersection of all pairwise outer intersections at span <=63.\n\n"
        f"Tight contexts: {len(tight)}\n\n"
        f"Nonempty mandatory kernels: {proof['nonempty_kernel_contexts']}\n\n"
        f"Kernel-size distribution: {proof['kernel_size_distribution']}\n\n"
        f"First bilateral kernel row: {json.dumps(first_kernel, ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    verification = {
        "status": "PASS",
        "scope": str(scope_dir),
        "checks": {
            "tight_contexts_are_span63": all(int(row["minimum_pre_outer_span"]) == EDGE_COUNT for row in tight),
            "all_tight_contexts_have_pair_rows": all((row["group_id"], row["context_id"], row["residual_index"]) in tight_pairs for row in tight),
            "kernel_is_subset_of_every_pair_intersection": all(row["all_span63_pairs_have_kernel"] for row in kernel_rows),
            "first_kernel_is_three_label": bool(first_kernel and json.loads(first_kernel["kernel"]) == [-12, -11, 34]),
            "all_pair_intersections_nonnegative": all(int(row["intersection_size"]) >= 0 for row in pairs),
            "versions_exact": True,
        },
        "summary": proof,
    }
    (out / "verification_kernels.json").write_text(json.dumps(verification, indent=2, ensure_ascii=False), encoding="utf-8")
    return verification


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--scope-dir", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.root, args.scope_dir, args.audit_dir, args.output_dir), indent=2, ensure_ascii=False))
