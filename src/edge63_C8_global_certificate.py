"""Build and independently verify the first global C8 certificate from an outer edge."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import pickle
from pathlib import Path
from typing import Any

from edge63_C8_displacement_first import build_layout, build_relative_labels, verify_c8_labeling, values_for_case
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_persistent_runner import block_map_for
from edge63_C8_two_run_cache import PersistentTwoRunCache


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _read_pickle(path: Path) -> Any:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


def build(root: Path) -> dict[str, Any]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3"
    outer_path = base / "outer_zero_audit_v1" / "outer_join_results.csv"
    rows = list(csv.DictReader(outer_path.open(encoding="utf-8")))
    outer_edges = [row for row in rows if int(row["intersection_size"]) == 0]
    if not outer_edges:
        raise AssertionError("no outer edge in the audited semantic scope")
    edge = min(outer_edges, key=lambda row: int(row["pre_outer_span"]))
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    group_map = {
        middle_cache._group_path(key).stem.replace(".pkl", "").replace("middle_group_", ""): (key, residuals)
        for key, residuals in groups.items()
    }
    group_id = edge["group_id"]
    middle_key, residuals = group_map[group_id]
    group, _ = middle_cache.load_or_build_group(values, middle_key, residuals)
    context_id = int(edge["context_id"])
    residual_index = int(edge["residual_index"])
    context = next(item for item in group["contexts"] if int(item["context_id"]) == context_id)
    residual_key, run_order = list(residuals.items())[residual_index]
    blocks = block_map_for(middle_key, residual_key)
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    left_a = tuple(blocks["left_leaf_1"])
    left_b = tuple(blocks["left_leaf_2"])
    right_a = tuple(blocks["right_leaf_1"])
    right_b = tuple(blocks["right_leaf_2"])
    left_table = pair_cache.terminal_pairs(left_a, left_b)
    right_table = pair_cache.terminal_pairs(right_a, right_b)
    left_state = next(state for state in left_table if int(state.state_id) == int(edge["left_behavior_id"]))
    right_state = next(state for state in right_table if int(state.state_id) == int(edge["right_behavior_id"]))
    delta_left = int(context["delta_left"])
    delta_right = int(context["delta_right"])
    allocation = {
        "split_slot": SLOT,
        "split_lengths": tuple(end - start + 1 for start, end in blocks[SLOT]),
        "run_order": run_order,
        "blocks": blocks,
    }
    labels, relative = build_relative_labels(values, context, left_state, right_state, delta_left, delta_right)
    span = max(labels) - min(labels)
    layout = build_layout(values)
    path_differences: dict[str, list[int]] = {}
    all_differences: list[int] = []
    for path, intervals in blocks.items():
        observed = sorted(abs(int(relative[u]) - int(relative[v])) for u, v in zip(layout[path], layout[path][1:]))
        expected = sorted(value for start, end in intervals for value in range(start, end + 1))
        if observed != expected:
            raise AssertionError({"path": path, "observed": observed, "expected": expected})
        path_differences[path] = observed
        all_differences.extend(observed)
    if sorted(all_differences) != list(range(1, 64)):
        raise AssertionError("outer-compatible near-miss has incorrect global differences")
    tight = span == 63
    normalized_labels = [int(relative[index]) - min(relative.values()) for index in range(64)]
    if tight:
        verification = verify_c8_labeling(values, allocation, normalized_labels)
        if not verification["verified"]:
            raise AssertionError(verification)
    else:
        verification = {
            "verified": False,
            "reason": "span_gt_63",
            "path_differences_verified": True,
            "span": span,
        }
    certificate = {
        "certificate_version": "C8.LevelB.v1.semantic-outer.v1",
        "case": CASE,
        "split_slot": SLOT,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
        "scope": "partial right-support semantic scope; existential certificate",
        "group_id": group_id,
        "context_id": context_id,
        "residual_index": residual_index,
        "split_lengths": list(allocation["split_lengths"]),
        "run_order": list(run_order),
        "blocks": {path: [list(interval) for interval in intervals] for path, intervals in blocks.items()},
        "middle_context": {
            "delta_left": delta_left,
            "delta_right": delta_right,
            "roots_middle_frame": [-delta_left, 0, delta_right],
            "middle_values": list(context["all_values"]),
            "middle_min": min(context["all_values"]),
            "middle_max": max(context["all_values"]),
            "D13": delta_left + delta_right,
        },
        "left_behavior_id": int(left_state.state_id),
        "right_behavior_id": int(right_state.state_id),
        "relative_offsets": {str(vertex): int(offset) for vertex, offset in relative.items()},
        "labels": normalized_labels,
        "span": span,
        "outer_intersection": [],
        "verification": verification,
        "sigma_c": span,
        "status": "SAT_VERIFIED" if tight else "COMPATIBLE_SPAN_GT63_PARTIAL",
        "path_differences": path_differences,
    }
    out = base / "full_bilateral_v1"
    out.mkdir(parents=True, exist_ok=True)
    cert_path = out / "first_global_compatible_pair.json"
    cert_path.write_text(json.dumps(certificate, indent=2), encoding="utf-8")
    if tight:
        verified_dir = base / "verified_constructions"
        verified_dir.mkdir(parents=True, exist_ok=True)
        (verified_dir / "left_leaf_2_semantic_outer.json").write_text(json.dumps(certificate, indent=2), encoding="utf-8")
    else:
        near_miss_dir = base / "full_bilateral_v1" / "near_misses"
        near_miss_dir.mkdir(parents=True, exist_ok=True)
        (near_miss_dir / "left_leaf_2_semantic_outer.json").write_text(json.dumps(certificate, indent=2), encoding="utf-8")
    result = {
        "status": "PASS",
        "certificate": str(cert_path),
        "label_verification": verification,
        "checks": {
            "outer_edge_rebuilt": True,
            "global_offset_injective": len(relative) == 64 and len(set(relative.values())) == 64,
            "labels_are_0_through_63": tight and sorted(normalized_labels) == list(range(64)),
            "global_span_is_63": span == 63,
            "all_edge_differences_are_1_through_63": sorted(all_differences) == list(range(1, 64)),
            "exactly_one_split_path": sum(len(intervals) for intervals in blocks.values()) == 8,
            "versions_exact": True,
        },
        "result_status": "SAT_VERIFIED" if tight else "COMPATIBLE_SPAN_GT63_PARTIAL",
        "scope_is_partial_but_existence_is_exact": True,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (out / "first_global_compatible_pair_verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {"certificate": certificate, "verification": result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    args = parser.parse_args()
    print(json.dumps(build(args.root), indent=2))
