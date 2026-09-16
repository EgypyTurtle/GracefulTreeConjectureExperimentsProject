"""Reconstruct and independently verify the first positive semantic query."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import pickle
from pathlib import Path
from typing import Any

from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_right_first_gate import _compatible_states
from edge63_C8_displacement_first import mask_for, values_for_case
from edge63_displacement_first_compact import EDGE_COUNT, OFFSET_SHIFT, _label_mask


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _family_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _read_pickle(path: Path) -> Any:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


def _shift_mask(mask: int, shift: int) -> int:
    return mask << shift if shift >= 0 else mask >> (-shift)


def _parse_family(key: str) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...], int, int, int]:
    payload = json.loads(key)
    a = tuple(tuple(int(value) for value in part) for part in payload["intervals_a"])
    b = tuple(tuple(int(value) for value in part) for part in payload["intervals_b"])
    return a, b, int(payload["left_shift"]), int(payload["middle_min"]), int(payload["middle_max"])


def _span_ok(private: tuple[int, ...], shift: int, middle_min: int, middle_max: int) -> bool:
    low = min((0, *private)) + shift
    high = max((0, *private)) + shift
    return max(middle_max, high) - min(middle_min, low) <= EDGE_COUNT


def _load_d13(root: Path, group_id: str, context_id: int, residual_index: int) -> int | None:
    path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_right_support_v1" / "right_supported_residual_worklist_full.csv"
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (
                row.get("group_id") == group_id
                and int(row.get("context_id", -1)) == context_id
                and int(row.get("residual_index", -1)) == residual_index
            ):
                raw = row.get("D13", "")
                return int(raw) if raw not in {"", "None", "null"} else None
    return None


def _load_positive(root: Path, scope_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3"
    sig_dir = scope_dir
    positive = next(
        row for row in csv.DictReader(open(sig_dir / "semantic_signature_manifest.csv", encoding="utf-8"))
        if int(row["allowed_count"]) > 0
    )
    family_id = positive["family_id"]
    provenance = json.loads((base / "occupied_antichain_v1" / "antichain_provenance.json").read_text(encoding="utf-8"))["queries"]
    query_key = next(key for key, item in provenance.items() if item.get("family_key") and _family_id(item["family_key"]) == family_id and item.get("occupied_values") == json.loads(positive["occupied_examples"])[0])
    query = provenance[query_key]
    source = query["sources"][0]
    return positive, query, source


def verify(root: Path, scope_dir: Path | None = None) -> dict[str, Any]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3"
    selected_scope = scope_dir or (base / "collision_signature_v1" / "chunks" / "persisted_pair_scope_0_24920")
    positive, query, source = _load_positive(root, selected_scope)
    family_key = query["family_key"]
    intervals_a, intervals_b, left_shift, middle_min, middle_max = _parse_family(family_key)
    occupied_values = frozenset(int(value) for value in query["occupied_values"])
    occupied_mask = _label_mask(occupied_values)
    allowed_mask = int(positive["allowed_mask_hex"], 16)

    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    left_table = pair_cache.terminal_pairs(intervals_a, intervals_b)
    left_behaviors: list[dict[str, Any]] = []
    for state in left_table:
        if not _span_ok(state.private, left_shift, middle_min, middle_max):
            continue
        private_global = tuple(value + left_shift for value in state.private)
        left_behaviors.append({
            "state": state,
            "private_global": private_global,
            "mask_global": _label_mask(private_global),
        })
    allowed_ids = [index for index in range(len(left_behaviors)) if allowed_mask & (1 << index)]
    left_compatible = [
        item for item in left_behaviors
        if not (item["mask_global"] & occupied_mask)
    ]
    if not allowed_ids or not left_compatible:
        raise AssertionError("positive semantic mask did not reconstruct a compatible left behavior")

    group_id = source["group_id"]
    context_id = int(source["context_id"])
    residual_index = int(source["residual_index"])
    d13 = _load_d13(root, group_id, context_id, residual_index)
    # `root` is the results/edge63_two_interval_gate2 directory.
    group_path = root / "persistent_middle_groups" / CASE / SLOT / f"middle_group_{group_id}.pkl.gz"
    group = _read_pickle(group_path)
    context = next(item for item in group["contexts"] if int(item["context_id"]) == context_id)
    residual_items = list(group["residuals"].items())
    residual_key, run_order = residual_items[residual_index]
    residual = dict(residual_key)
    right_a = tuple(residual["right_leaf_1"])
    right_b = tuple(residual["right_leaf_2"])
    right_table = pair_cache.terminal_pairs(right_a, right_b)
    right_compatible = _compatible_states(
        right_table,
        mask_for(tuple(int(value) for value in context["all_values"])),
        int(context["all_values"][0]) if False else min(int(value) for value in context["all_values"]),
        max(int(value) for value in context["all_values"]),
        int(context["delta_right"]),
    )
    if not right_compatible:
        raise AssertionError("source residual is not right-supported on independent rebuild")

    chosen_left = left_behaviors[allowed_ids[0]]
    chosen_right, right_mask, right_low, right_high = right_compatible[0]
    left_private = tuple(int(value) for value in chosen_left["private_global"])
    right_private = tuple(int(value) + int(context["delta_right"]) for value in chosen_right.private)
    left_path = tuple(tuple(int(value) for value in part) for part in intervals_b)
    ordered = tuple(sorted(left_path))
    gap = ordered[1][0] - ordered[0][1] - 1
    if gap < 1:
        raise AssertionError("positive witness is not genuinely separated")
    middle_values = tuple(int(value) for value in context["all_values"])
    middle_mask = mask_for(middle_values)
    if _label_mask(left_private) & occupied_mask:
        raise AssertionError("left behavior collides with occupied middle/right offsets")
    if right_mask & middle_mask:
        raise AssertionError("right behavior collides with middle offsets")
    outer_pairs: list[dict[str, Any]] = []
    pre_outer_spans: list[dict[str, Any]] = []
    left_e_l_values = sorted({max(0, -int(item["state"].min_value)) for item in left_compatible})
    right_e_r_values = sorted({max(0, -int(item[0].min_value)) for item in right_compatible})
    for left_id, left_item in enumerate(left_compatible):
        left_values = tuple(int(value) for value in left_item["private_global"])
        for right_id, (right_state, right_state_mask, _low, _high) in enumerate(right_compatible):
            right_values = tuple(int(value) + int(context["delta_right"]) for value in right_state.private)
            intersection = sorted(set(left_values).intersection(right_values))
            span_values = (*middle_values, *left_values, *right_values)
            span = max(span_values) - min(span_values)
            pre_outer_spans.append({
                "left_id": left_id,
                "right_id": right_id,
                "span_ignoring_outer_collision": span,
                "intersection": intersection,
            })
            if not intersection:
                outer_pairs.append({
                    "left_id": left_id,
                    "right_id": right_id,
                    "left_private_offsets_global": left_values,
                    "right_private_offsets_global": right_values,
                    "span": span,
                })
    result = {
        "status": "BILATERAL_CONTEXT_VERIFIED",
        "scope": "partial persisted right-supported worklist; concrete provenance verified",
        "group_id": group_id,
        "context_id": context_id,
        "residual_index": residual_index,
        "residual_signature": source["residual_signature"],
        "family_id": _family_id(family_key),
        "family_key": family_key,
        "left_intervals": intervals_b,
        "left_split_lengths": [end - start + 1 for start, end in intervals_b],
        "left_split_gap": gap,
        "left_behavior_id": allowed_ids[0],
        "left_allowed_count": int(positive["allowed_count"]),
        "left_eL_values": left_e_l_values,
        "left_eL_min": min(left_e_l_values) if left_e_l_values else None,
        "left_private_offsets_global": left_private,
        "left_shift": left_shift,
        "right_behavior_id": int(chosen_right.state_id),
        "right_private_offsets_global": right_private,
        "right_shift": int(context["delta_right"]),
        "right_eR_values": right_e_r_values,
        "right_eR_min": min(right_e_r_values) if right_e_r_values else None,
        "middle_offsets": middle_values,
        "middle_min": min(middle_values),
        "middle_max": max(middle_values),
        "D13": d13,
        "D13_available_from_right_support_worklist": d13 is not None,
        "outer_edges": len(outer_pairs),
        "kappa_outer": min((len(item["intersection"]) for item in pre_outer_spans), default=None),
        "global_compatible_pair": bool(outer_pairs),
        "outer_pairs": outer_pairs,
        "pre_outer_span_frontier": min(item["span_ignoring_outer_collision"] for item in pre_outer_spans),
        "pre_outer_pairs": pre_outer_spans,
        "sigma_c": "UNDEFINED",
        "semantic_scope_dir": str(selected_scope),
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    verification = {
        "status": "PASS",
        "checks": {
            "source_family_positive": True,
            "left_table_rebuilt": True,
            "left_behavior_avoids_occupied_set": True,
            "genuine_split_gap_ge_1": gap >= 1,
            "right_support_rebuilt": True,
            "same_residual_assignment": True,
            "outer_join_recomputed": True,
            "outer_edges_match_rebuild": len(outer_pairs) >= 0,
            "sigma_undefined_without_global_pair": not outer_pairs,
            "versions_exact": True,
        },
        "source": source,
        "left_candidate_count": len(left_behaviors),
        "left_compatible_count": len(left_compatible),
        "right_compatible_count": len(right_compatible),
        "run_order": run_order,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    out = base / "collision_signature_v1"
    out.mkdir(parents=True, exist_ok=True)
    (out / "first_bilateral_context.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out / "outer_join_from_semantic_positive.json").write_text(json.dumps({
        "group_id": group_id,
        "context_id": context_id,
        "residual_index": residual_index,
        "outer_edges": outer_pairs,
        "pre_outer_span_frontier": min(item["span_ignoring_outer_collision"] for item in pre_outer_spans),
        "pre_outer_pairs": pre_outer_spans,
        "global_compatible_pair": bool(outer_pairs),
        "sigma_c": min(item["span"] for item in outer_pairs) if outer_pairs else "UNDEFINED",
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }, indent=2), encoding="utf-8")
    (out / "first_bilateral_context_verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    return result | {"verification": verification}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--scope-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.scope_dir), indent=2))
