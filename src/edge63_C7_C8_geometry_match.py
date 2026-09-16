"""Cache-only geometry audit for Tree1 C7 versus C8 left_leaf_1.

This module deliberately replays persisted C8 middle groups and terminal-pair
tables.  It never calls an allocation or local-state generator.  The audit is
therefore a read-only reconstruction of the already closed persistent run,
not another C8 search.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import itertools
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_C8_middle_group_cache import (  # noqa: E402
    ALLOCATION_DEDUP_VERSION,
    BITSET_UNIVERSE,
    C8_LANGUAGE_VERSION,
    MIDDLE_FRAME_CONVENTION,
    TERMINAL_PAIR_CACHE_VERSION,
    canonical_json,
    stable_group_id,
    version_fingerprint,
)
from edge63_C8_two_run_cache import PersistentTwoRunCache  # noqa: E402
from edge63_C8_displacement_first import (  # noqa: E402
    build_layout,
    build_relative_labels,
    mask_for,
    values_for_case,
)
from edge63_displacement_first_compact import (  # noqa: E402
    EDGE_COUNT,
    PATHS,
    TERMINAL_PATHS,
    TerminalIndexCache,
    interval_blocks,
    path_lengths,
)


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SPLIT_SLOT = "left_leaf_1"
AUDIT_VERSION = "C7-C8-geometry-audit.v1:cache-only-replay"


def read_gzip_pickle(path: Path) -> object:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0])
    for row in rows[1:]:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def json_field(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def bool_value(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def int_list_field(value: Any) -> str:
    return ";".join(str(int(item)) for item in value)


def tuple_intervals(value: Any) -> tuple[tuple[int, int], ...]:
    return tuple((int(start), int(end)) for start, end in value)


def cache_only_index(root: Path, case: str, split_slot: str, fingerprint: str) -> tuple[dict, int]:
    safe_case = case.replace("/", "_").replace("\\", "_")
    path = root / "cache_v2" / safe_case / split_slot / "allocation_index.pkl.gz"
    metadata_path = path.with_name("fingerprint.json")
    if not path.exists() or not metadata_path.exists():
        raise RuntimeError(f"missing persistent allocation index: {path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("version_fingerprint") != fingerprint:
        raise RuntimeError("allocation-index fingerprint mismatch")
    payload = read_gzip_pickle(path)
    if not isinstance(payload, dict) or payload.get("version_fingerprint") != fingerprint:
        raise RuntimeError("allocation-index payload fingerprint mismatch")
    return payload["groups"], int(payload["raw_allocations"])


def cache_only_group(root: Path, case: str, split_slot: str, middle_key: tuple, fingerprint: str) -> dict:
    safe_case = case.replace("/", "_").replace("\\", "_")
    group_id = stable_group_id(case, split_slot, middle_key)
    path = root / "persistent_middle_groups" / safe_case / split_slot / f"middle_group_{group_id}.pkl.gz"
    if not path.exists():
        raise RuntimeError(f"missing persistent middle group: {path}")
    payload = read_gzip_pickle(path)
    if not isinstance(payload, dict) or payload.get("version_fingerprint") != fingerprint:
        raise RuntimeError(f"middle-group fingerprint mismatch: {group_id}")
    return payload


def cache_only_pairs(pair_cache: PersistentTwoRunCache, intervals_a: tuple, intervals_b: tuple) -> tuple:
    key_value = (intervals_a, intervals_b)
    path = pair_cache._path("pairs", key_value)
    if not path.exists():
        raise RuntimeError(f"missing cached terminal-pair table: {path}")
    payload = read_gzip_pickle(path)
    expected_key = pair_cache._key("pairs", key_value)
    if not isinstance(payload, dict) or payload.get("key") != expected_key:
        raise RuntimeError(f"terminal-pair cache key mismatch: {path}")
    return tuple(payload["states"])


def shifted_mask(mask: int, shift: int) -> int:
    return mask << shift if shift >= 0 else mask >> (-shift)


def compatible(states: tuple, middle_mask: int, middle_min: int, middle_max: int, shift: int) -> list[tuple]:
    result = []
    for state in states:
        mask = shifted_mask(state.mask, shift)
        if mask & middle_mask:
            continue
        low = min(middle_min, state.min_value + shift)
        high = max(middle_max, state.max_value + shift)
        if high - low <= EDGE_COUNT:
            result.append((state, mask, low, high))
    return result


def blocks_from_keys(middle_key: tuple, residual_key: tuple) -> dict[str, tuple[tuple[int, int], ...]]:
    blocks = {path: ((int(start), int(end)),) for path, start, end in middle_key}
    blocks.update({path: tuple_intervals(intervals) for path, intervals in residual_key})
    if set(blocks) != set(PATHS):
        raise AssertionError("allocation ownership is incomplete")
    return blocks


def path_private_values(values: tuple[int, ...], context: dict[str, Any], left_state: Any, right_state: Any,
                        delta_left: int, delta_right: int) -> tuple[dict[str, tuple[int, ...]], dict[int, int]]:
    """Return per-path private offsets and the full relative vertex map."""
    layout = build_layout(values)
    _, relative = build_relative_labels(values, context, left_state, right_state, delta_left, delta_right)
    per_path: dict[str, tuple[int, ...]] = {
        "left_bridge": tuple(relative[v] for v in layout["left_bridge"][1:-1]),
        "right_bridge": tuple(relative[v] for v in layout["right_bridge"][1:-1]),
        "middle_leaf": tuple(relative[v] for v in layout["middle_leaf"][1:]),
        "left_leaf_1": tuple(relative[v] for v in layout["left_leaf_1"][1:]),
        "left_leaf_2": tuple(relative[v] for v in layout["left_leaf_2"][1:]),
        "right_leaf_1": tuple(relative[v] for v in layout["right_leaf_1"][1:]),
        "right_leaf_2": tuple(relative[v] for v in layout["right_leaf_2"][1:]),
    }
    return per_path, relative


def normalize_set(values: tuple[int, ...] | list[int] | set[int]) -> tuple[int, ...]:
    values = tuple(int(value) for value in values)
    low = min(values)
    return tuple(sorted(value - low for value in values))


def c8_signature(relative: dict[int, int], middle_values: tuple[int, ...], left_private: tuple[int, ...],
                 right_private: tuple[int, ...], delta_left: int, delta_right: int) -> tuple:
    all_values = tuple(relative.values())
    low = min(all_values)
    return (
        int(delta_left),
        int(delta_right),
        tuple(sorted(value - low for value in all_values)),
        tuple(sorted(value - low for value in middle_values)),
        tuple(sorted(value - low for value in left_private)),
        tuple(sorted(value - low for value in right_private)),
    )


def c7_signature(row: dict[str, str], values: tuple[int, ...], index_cache: TerminalIndexCache) -> tuple:
    middle = tuple(int(item) for item in row["middle_values"].split(";") if item != "")
    left = tuple(int(item) for item in row["left_private"].split(";") if item != "")
    right = tuple(int(item) for item in row["right_private"].split(";") if item != "")
    all_values = middle + left + right
    low = min(all_values)
    blocks = c7_blocks_for_row(values, int(row["order_index"]))
    left_a = blocks["left_leaf_1"]
    left_b = blocks["left_leaf_2"]
    right_a = blocks["right_leaf_1"]
    right_b = blocks["right_leaf_2"]
    left_index = index_cache.get(
        ("left_leaf_1", left_a[0], left_a[1] - left_a[0] + 1,
         "left_leaf_2", left_b[0], left_b[1] - left_b[0] + 1), "B"
    )
    right_index = index_cache.get(
        ("right_leaf_1", right_a[0], right_a[1] - right_a[0] + 1,
         "right_leaf_2", right_b[0], right_b[1] - right_b[0] + 1), "B"
    )
    left_state = left_index.states[int(row["left_state_id"])]
    right_state = right_index.states[int(row["right_state_id"])]
    terminal_paths = (
        ("left_leaf_1", tuple(value - int(row["delta_left"]) - low for value in left_state.path_a)),
        ("left_leaf_2", tuple(value - int(row["delta_left"]) - low for value in left_state.path_b)),
        ("right_leaf_1", tuple(value + int(row["delta_right"]) - low for value in right_state.path_a)),
        ("right_leaf_2", tuple(value + int(row["delta_right"]) - low for value in right_state.path_b)),
    )
    return (
        int(row["delta_left"]),
        int(row["delta_right"]),
        tuple(sorted(value - low for value in all_values)),
        tuple(sorted(value - low for value in middle)),
        tuple(sorted(value - low for value in left)),
        tuple(sorted(value - low for value in right)),
        terminal_paths,
    )


def reflect_signature(signature: tuple) -> tuple:
    delta_left, delta_right, all_values, middle, left, right, terminal_paths = signature
    span = max(all_values)
    def reflect(values: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(sorted(span - value for value in values))
    reflected_paths = tuple((path, reflect(values)) for path, values in terminal_paths)
    return (-delta_left, -delta_right, reflect(all_values), reflect(middle), reflect(left), reflect(right), reflected_paths)


def c7_blocks_for_row(values: tuple[int, ...], order_index: int) -> dict[str, tuple[int, int]]:
    orders = itertools.permutations(PATHS)
    try:
        order = next(itertools.islice(orders, order_index - 1, order_index))
    except StopIteration as exc:
        raise RuntimeError(f"invalid C7 order index {order_index}") from exc
    return interval_blocks(path_lengths(values), order)


def audit_c8_cache(root: Path, case: str, split_slot: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    values = values_for_case(case)
    fingerprint = version_fingerprint(case, split_slot)
    groups, raw_allocations = cache_only_index(root, case, split_slot, fingerprint)
    pair_cache = PersistentTwoRunCache(root, case, split_slot)
    rows: list[dict[str, Any]] = []
    group_count = 0
    context_count = 0
    residual_count = 0
    prefilter_count = 0
    pair_table_cache: dict[tuple, tuple] = {}

    for middle_key, residuals in sorted(groups.items(), key=lambda item: (len(item[1]), item[0])):
        group_id = stable_group_id(case, split_slot, middle_key)
        payload = cache_only_group(root, case, split_slot, middle_key, fingerprint)
        contexts = tuple(payload["contexts"])
        group_count += 1
        context_count += len(contexts)
        context_data = []
        for context in contexts:
            middle_values = tuple(int(value) for value in context["all_values"])
            context_data.append((
                context,
                middle_values,
                mask_for(middle_values),
                min(middle_values),
                max(middle_values),
                int(context["delta_left"]),
                int(context["delta_right"]),
            ))
        if not context_data:
            # The persistent runner did not need terminal-pair tables for a
            # local-empty middle group.  Skipping it preserves cache-only
            # semantics and avoids manufacturing tables that were never part
            # of the completed run.
            continue
        for residual_key, run_order in residuals.items():
            residual_count += 1
            block_map = blocks_from_keys(middle_key, residual_key)
            left_intervals_a = block_map["left_leaf_1"]
            left_intervals_b = block_map["left_leaf_2"]
            right_intervals_a = block_map["right_leaf_1"]
            right_intervals_b = block_map["right_leaf_2"]
            left_key = (left_intervals_a, left_intervals_b)
            right_key = (right_intervals_a, right_intervals_b)
            if left_key not in pair_table_cache:
                pair_table_cache[left_key] = cache_only_pairs(pair_cache, left_intervals_a, left_intervals_b)
            if right_key not in pair_table_cache:
                pair_table_cache[right_key] = cache_only_pairs(pair_cache, right_intervals_a, right_intervals_b)
            left_states = pair_table_cache[left_key]
            right_states = pair_table_cache[right_key]
            if not left_states or not right_states:
                continue
            for context, middle_values, middle_mask, middle_min, middle_max, delta_left, delta_right in context_data:
                left_compatible = compatible(left_states, middle_mask, middle_min, middle_max, -delta_left)
                if not left_compatible:
                    continue
                right_compatible = compatible(right_states, middle_mask, middle_min, middle_max, delta_right)
                if not right_compatible:
                    continue
                prefilter_count += 1
                for left_state, left_mask, left_low, left_high in left_compatible:
                    for right_state, right_mask, right_low, right_high in right_compatible:
                        if left_mask & right_mask:
                            continue
                        _, relative = build_relative_labels(
                            values, context, left_state, right_state, delta_left, delta_right
                        )
                        all_values = tuple(relative.values())
                        low = min(all_values)
                        high = max(all_values)
                        left_private = tuple(value - delta_left for value in left_state.private)
                        right_private = tuple(value + delta_right for value in right_state.private)
                        middle_values_frame = tuple(middle_values)
                        root_left = -delta_left
                        root_right = delta_right
                        if root_left <= root_right:
                            left_cross_extension = root_left - min(left_private)
                            right_cross_extension = max(right_private) - root_right
                        else:
                            left_cross_extension = max(left_private) - root_left
                            right_cross_extension = root_right - min(right_private)
                        path_private, _ = path_private_values(
                            values, context, left_state, right_state, delta_left, delta_right
                        )
                        rows.append({
                            "case": case,
                            "split_slot": split_slot,
                            "group_id": group_id,
                            "context_id": int(context["context_id"]),
                            "middle_key": json_field(middle_key),
                            "residual_key": json_field(residual_key),
                            "run_order": json_field(list(run_order)),
                            "blocks": json_field({path: [list(item) for item in intervals] for path, intervals in block_map.items()}),
                            "delta_left": delta_left,
                            "delta_right": delta_right,
                            "D13_abs": abs(delta_left + delta_right),
                            "span": high - low,
                            "min_offset": low,
                            "max_offset": high,
                            "left_state_id": int(left_state.state_id),
                            "right_state_id": int(right_state.state_id),
                            "left_private_middle_frame": int_list_field(left_private),
                            "right_private_middle_frame": int_list_field(right_private),
                            "middle_values": int_list_field(middle_values_frame),
                            "normalized_global_offsets": int_list_field(normalize_set(all_values)),
                            "normalized_middle_offsets": int_list_field(tuple(sorted(value - low for value in middle_values_frame))),
                            "normalized_left_offsets": int_list_field(tuple(sorted(value - low for value in left_private))),
                            "normalized_right_offsets": int_list_field(tuple(sorted(value - low for value in right_private))),
                            "left_leaf_1_runs": json_field([list(item) for item in block_map["left_leaf_1"]]),
                            "left_leaf_1_run_gap": (
                                block_map["left_leaf_1"][1][0] - block_map["left_leaf_1"][0][1] - 1
                                if len(block_map["left_leaf_1"]) == 2 else 0
                            ),
                            "left_leaf_1_split_adjacent": (
                                len(block_map["left_leaf_1"]) == 2
                                and block_map["left_leaf_1"][0][1] + 1 == block_map["left_leaf_1"][1][0]
                            ),
                            "left_leaf_1_union": json_field([list(item) for item in block_map["left_leaf_1"]]),
                            # These are the extensions in the same
                            # cross-root orientation used by the corrected
                            # C7 audit: left terminal toward r3 and right
                            # terminal toward r1.  The raw root-local extrema
                            # are not interchangeable with middle-frame
                            # extensions after translation.
                            "left_toward_right_extension": max(left_private) - (-delta_left),
                            "right_toward_left_extension": delta_right - min(right_private),
                            "root_order": "r1<r3" if root_left <= root_right else "r3<r1",
                            "left_cross_root_extension": left_cross_extension,
                            "right_cross_root_extension": right_cross_extension,
                            "left_state_a_offsets": int_list_field(left_state.state_a.offsets),
                            "left_state_b_offsets": int_list_field(left_state.state_b.offsets),
                            "right_state_a_offsets": int_list_field(right_state.state_a.offsets),
                            "right_state_b_offsets": int_list_field(right_state.state_b.offsets),
                            "path_private_middle_frame": json_field({path: list(vals) for path, vals in path_private.items()}),
                            "normalized_terminal_path_private": json_field({
                                path: sorted(value - low for value in path_private[path])
                                for path in TERMINAL_PATHS
                            }),
                        })

    stats = {
        "groups": group_count,
        "contexts": context_count,
        "raw_allocations": raw_allocations,
        "residual_assignments": residual_count,
        "context_residuals_with_both_envelopes": prefilter_count,
        "compatible_pairs": len(rows),
        "version_fingerprint": fingerprint,
        "cache_only_replay": True,
        "pair_tables_loaded": len(pair_table_cache),
        "pair_cache_root": str(pair_cache.root),
    }
    return rows, stats


def load_c7_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 36:
        raise AssertionError(f"corrected C7 row count is {len(rows)}, expected 36")
    if min(int(row["span"]) for row in rows) != 67:
        raise AssertionError("C7 input contains stale sigma_min=66 data")
    return rows


def make_matching(c7_rows: list[dict[str, str]], c8_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    values = values_for_case(CASE)
    c7_index_cache = TerminalIndexCache(capacity=64)
    c7_by_signature: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    for row in c7_rows:
        c7_by_signature[c7_signature(row, values, c7_index_cache)].append(row)
    c7_reflected: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    for signature, rows in c7_by_signature.items():
        c7_reflected[reflect_signature(signature)].extend(rows)
    matches: list[dict[str, Any]] = []
    c8_signature_counts = Counter()
    for row in c8_rows:
        signature = (
            int(row["delta_left"]),
            int(row["delta_right"]),
            tuple(int(item) for item in row["normalized_global_offsets"].split(";") if item != ""),
            tuple(int(item) for item in row["normalized_middle_offsets"].split(";") if item != ""),
            tuple(int(item) for item in row["normalized_left_offsets"].split(";") if item != ""),
            tuple(int(item) for item in row["normalized_right_offsets"].split(";") if item != ""),
            tuple((path, tuple(values)) for path, values in sorted(json.loads(row["normalized_terminal_path_private"]).items())),
        )
        c8_signature_counts[signature] += 1
        exact = c7_by_signature.get(signature, [])
        reflected = c7_reflected.get(signature, [])
        relation = "EXACT" if exact else ("LABEL_COMPLEMENT" if reflected else "UNMATCHED")
        candidates = exact or reflected
        for c7_row in candidates:
            matches.append({
                "c8_group_id": row["group_id"],
                "c8_context_id": row["context_id"],
                "c8_left_state_id": row["left_state_id"],
                "c8_right_state_id": row["right_state_id"],
                "c8_span": row["span"],
                "c8_delta_left": row["delta_left"],
                "c8_delta_right": row["delta_right"],
                "c8_run_order": row["run_order"],
                "c8_left_leaf_1_runs": row["left_leaf_1_runs"],
                "c8_left_leaf_1_run_gap": row["left_leaf_1_run_gap"],
                "c8_left_leaf_1_split_adjacent": row["left_leaf_1_split_adjacent"],
                "c7_order_index": c7_row["order_index"],
                "c7_middle_context_id": c7_row["middle_context_id"],
                "c7_span": c7_row["span"],
                "c7_left_state_id": c7_row["left_state_id"],
                "c7_right_state_id": c7_row["right_state_id"],
                "relation": relation,
            })
    stats = {
        "c7_rows": len(c7_rows),
        "c8_rows": len(c8_rows),
        "c7_distinct_geometry_signatures": len(c7_by_signature),
        "c8_distinct_geometry_signatures": len(c8_signature_counts),
        "matching_rows": len(matches),
        "matching_geometry_pairs": len(c8_signature_counts),
        "c8_rows_exactly_matched": sum(1 for row in c8_rows if any(item["c8_group_id"] == row["group_id"] and item["c8_context_id"] == row["context_id"] and item["relation"] == "EXACT" for item in matches)),
        "c8_rows_label_complement_matched": sum(1 for row in c8_rows if any(item["c8_group_id"] == row["group_id"] and item["c8_context_id"] == row["context_id"] and item["relation"] == "LABEL_COMPLEMENT" for item in matches)),
        "c8_rows_unmatched": sum(1 for row in c8_rows if not any(item["c8_group_id"] == row["group_id"] and item["c8_context_id"] == row["context_id"] for item in matches)),
    }
    return matches, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    root = args.root
    output = args.output_dir or (root / "results" / "edge63_two_interval_gate2" / "tree1_C8" / "left_leaf_1_geometry_audit")
    c7_path = root / "results" / "edge63_span_feasibility_frontier" / "corrected_tree1_gate1" / "final_span_candidates.csv"
    c7_rows = load_c7_rows(c7_path)
    c8_rows, c8_stats = audit_c8_cache(root / "results" / "edge63_two_interval_gate2", CASE, SPLIT_SLOT)
    if len(c8_rows) != 36:
        raise AssertionError(f"cache replay recovered {len(c8_rows)} C8 rows, expected 36")
    matches, matching_stats = make_matching(c7_rows, c8_rows)

    values = values_for_case(CASE)
    c8_by_key = {(row["group_id"], row["context_id"], row["left_state_id"], row["right_state_id"]): row for row in c8_rows}
    separation_rows = []
    for row in c8_rows:
        blocks = json.loads(row["blocks"])
        runs = [tuple(item) for item in blocks["left_leaf_1"]]
        c7_order = ""
        related = [item for item in matches if item["c8_group_id"] == row["group_id"] and item["c8_context_id"] == row["context_id"]]
        if related:
            c7_order = related[0]["c7_order_index"]
            c7_blocks = c7_blocks_for_row(values, int(c7_order))
            c7_block = c7_blocks["left_leaf_1"]
        else:
            c7_block = None
        separation_rows.append({
            "group_id": row["group_id"],
            "context_id": row["context_id"],
            "c7_order_index": c7_order,
            "c7_left_leaf_1_block": json_field(list(c7_block)) if c7_block else "",
            "c8_left_leaf_1_runs": json_field([list(item) for item in runs]),
            "run_gap": row["left_leaf_1_run_gap"],
            "adjacent_resegmentation": bool(c7_block and len(runs) == 2 and runs[0][1] + 1 == runs[1][0] and runs[0][0] == c7_block[0] and runs[1][1] == c7_block[1]),
            "union_equals_c7_block": str(bool(c7_block and runs[0][0] == c7_block[0] and runs[-1][1] == c7_block[1] and all(runs[index][1] + 1 == runs[index + 1][0] for index in range(len(runs) - 1)))),
            "span": row["span"],
        })

    write_csv(output / "C7_C8_candidate_matching.csv", matches)
    write_csv(output / "C8_run_separation.csv", separation_rows)
    certificate = {
        "audit_version": AUDIT_VERSION,
        "case": CASE,
        "split_slot": SPLIT_SLOT,
        "two_run_language": C8_LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
        "middle_frame_convention": MIDDLE_FRAME_CONVENTION,
        "bitset_universe": BITSET_UNIVERSE,
        "actual_graph_automorphism": {
            "group_order": 2,
            "nontrivial_action": "swap right_leaf_1 and right_leaf_2",
            "scope": "equal-length right terminal leaves of this Tree1 skeleton",
        },
        "c7_source": str(c7_path),
        "c8_source": "persistent cache-only replay; no generation calls",
        "c8_stats": c8_stats,
        "matching_stats": matching_stats,
        "c8_span_distribution": dict(sorted(Counter(int(row["span"]) for row in c8_rows).items())),
        "c8_adjacent_split_count": sum(bool_value(row["left_leaf_1_split_adjacent"]) for row in c8_rows),
        "c8_separated_split_count": sum(not bool_value(row["left_leaf_1_split_adjacent"]) for row in c8_rows),
        "c8_run_gap_distribution": dict(sorted(Counter(int(row["left_leaf_1_run_gap"]) for row in c8_rows).items())),
        "c8_rows": c8_rows,
    }
    (output / "geometry_audit_certificate.json").parent.mkdir(parents=True, exist_ok=True)
    (output / "geometry_audit_certificate.json").write_text(json.dumps(certificate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"c8_stats": c8_stats, "matching_stats": matching_stats, "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
