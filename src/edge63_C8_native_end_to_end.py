"""End-to-end differential gate for the native C8 local-table backend.

The native component is deliberately exercised through the existing Python
semantic and global code.  This module freezes the result of that comparison
before the bounded production pilot is allowed to run.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import shutil
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_collision_signature import _family_id, _process_family
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_displacement_first import mask_for
from edge63_C8_left_negative_cert_cache import canonical_family_key
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_native_geometry_cache import NativeCompiledGeometryCache
from edge63_C8_native_bridge import read_native_table
from edge63_C8_outer_zero_audit import _audit_source
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_displacement_first_compact import EDGE_COUNT, OFFSET_SHIFT


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_intervals(raw: str) -> tuple[tuple[int, int], ...]:
    value = json.loads(raw) if raw.lstrip().startswith("[") else ast.literal_eval(raw)
    return tuple(tuple(int(value) for value in part) for part in value)


def _row_intervals(row: dict[str, str]) -> tuple[tuple[int, int], ...]:
    pair = json.loads(row["left_two_run_interval_pair"])
    return tuple(tuple(int(value) for value in part) for part in pair[1])


def _family_from_worklist(row: dict[str, str]) -> tuple[str, frozenset[int], dict[str, Any]]:
    pair = json.loads(row["left_two_run_interval_pair"])
    intervals_a = tuple(tuple(int(value) for value in part) for part in pair[0])
    intervals_b = tuple(tuple(int(value) for value in part) for part in pair[1])
    frame = json.loads(row["left_root_frame"])
    family_key = canonical_family_key(
        intervals_a,
        intervals_b,
        int(frame["left_shift"]),
        int(row["middle_min"]),
        int(row["middle_max"]),
        True,
    )
    occupied = frozenset(int(value) for value in json.loads(row["occupied_left_offset_set"]))
    source = {
        "group_id": row["group_id"],
        "context_id": int(row["context_id"]),
        "residual_index": int(row["residual_index"]),
        "residual_signature": row["residual_signature"],
    }
    return family_key, occupied, source


def _collect_target_rows(root: Path, targets: set[tuple[tuple[int, int], ...]]) -> dict[tuple[tuple[int, int], ...], dict[str, Any]]:
    path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_right_support_v1" / "right_supported_residual_worklist_full.csv"
    result: dict[tuple[tuple[int, int], ...], dict[str, Any]] = {
        target: {"rows": 0, "families": defaultdict(lambda: {"family_key": "", "queries": set(), "sources": defaultdict(list)}), "raw_rows": []}
        for target in targets
    }
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            intervals = _row_intervals(row)
            if intervals not in result:
                continue
            family_key, occupied, source = _family_from_worklist(row)
            bucket = result[intervals]
            family_id = _family_id(family_key)
            family = bucket["families"][family_id]
            family["family_key"] = family_key
            family["queries"].add(occupied)
            family["sources"][occupied].append(source)
            bucket["rows"] += 1
            if len(bucket["raw_rows"]) < 4:
                bucket["raw_rows"].append(row)
    return result


def _family_semantic(root: Path, bucket: dict[str, Any], index: CompiledTerminalPairIndex) -> dict[str, Any]:
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    signatures: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    total_queries = 0
    empty_queries = 0
    positive_queries = 0
    family_rows = bucket["families"]
    for family_id in sorted(family_rows):
        family = family_rows[family_id]
        query_rows = [{"occupied_values_parsed": occupied} for occupied in sorted(
            family["queries"], key=lambda value: (len(value), tuple(sorted(value)))
        )]
        rows, effect, _details = _process_family(
            pair_cache,
            index,
            family["family_key"],
            query_rows,
            family["sources"],
        )
        signatures.extend(rows)
        effects.append(effect)
        total_queries += len(query_rows)
        for row in rows:
            if int(row["allowed_count"]) == 0:
                empty_queries += int(row["query_count"])
            else:
                positive_queries += int(row["query_count"])
    return {
        "rows_seen": bucket["rows"],
        "family_count": len(family_rows),
        "exact_queries": total_queries,
        "empty_queries": empty_queries,
        "positive_queries": positive_queries,
        "signatures": signatures,
        "effects": effects,
    }


def _signature_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("family_id"),
        row.get("blocked_mask_hex"),
        row.get("allowed_mask_hex"),
        int(row.get("allowed_count", 0)),
        int(row.get("query_count", 0)),
    )


def _effect_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("family_id"),
        int(row.get("behavior_count", 0)),
        int(row.get("query_count", 0)),
        int(row.get("zero_effect_offsets", 0)),
        int(row.get("distinct_single_offset_effect_masks", 0)),
    )


def _index_for(root: Path, cache_root: Path, source_root: Path | None = None) -> CompiledTerminalPairIndex:
    cache = NativeCompiledGeometryCache(
        root,
        CASE,
        SLOT,
        cache_root=cache_root,
        source_root=source_root,
    )
    return CompiledTerminalPairIndex(root, CASE, SLOT, geometry_cache=cache)


def _local_case(root: Path, cache_root: Path) -> dict[str, Any]:
    payload = _read_json(root / "tree1_C8" / "left_leaf_2_exact_v3" / "first_left_repair_analysis" / "first_left_witness_geometry.json")["witness"]
    intervals_a = _parse_intervals(payload["left_leaf_1_intervals"])
    intervals_b = _parse_intervals(payload["left_leaf_2_intervals"])
    occupied = tuple(int(value) for value in json.loads(payload["middle_offsets"]))
    occupied_mask = mask_for(occupied)
    results: dict[str, dict[str, Any]] = {}
    for name, index in (
        ("python", CompiledTerminalPairIndex(root, CASE, SLOT)),
        ("native", _index_for(root, cache_root, root / "native_engine_v1" / "native_tables" / "golden")),
    ):
        states, meta = index.query(
            intervals_a,
            intervals_b,
            occupied_mask=occupied_mask,
            left_shift=int(payload["left_shift"]),
            middle_min=int(payload["middle_min"]),
            middle_max=int(payload["middle_max"]),
            span_mode=True,
        )
        results[name] = {
            "states": [
                {
                    "private": list(state.private),
                    "min": int(state.min_value),
                    "max": int(state.max_value),
                    "span": int(state.max_value - state.min_value),
                }
                for state in states
            ],
            "meta": meta,
        }
    same = results["python"]["states"] == results["native"]["states"]
    e_l = max((0, -int(results["native"]["states"][0]["min"])) if results["native"]["states"] else (0,))
    return {
        "case_id": "known_local_positive_eL2",
        "intervals_a": intervals_a,
        "intervals_b": intervals_b,
        "expected_geometry_class": payload["geometry_class"],
        "expected_eL": int(payload["left_outward_extension"]),
        "expected_gap": int(payload["run_gap"]),
        "python": results["python"],
        "native": results["native"],
        "exact_equal": same,
        "eL_recomputed": e_l,
        "pass": same and e_l == 2 and int(payload["run_gap"]) == 9,
        **_versions(),
    }


def _source_for_target(bucket: dict[str, Any], selector: tuple[str, int, int] | None = None) -> tuple[str, frozenset[int], dict[str, Any]]:
    for family_id in sorted(bucket["families"]):
        family = bucket["families"][family_id]
        for occupied in sorted(family["sources"], key=lambda value: (len(value), tuple(sorted(value)))):
            for source in family["sources"][occupied]:
                if selector is None or (source["group_id"], source["context_id"], source["residual_index"]) == selector:
                    return family["family_key"], occupied, source
    raise KeyError("target source not found")


def _groups_by_id(root: Path) -> tuple[PersistentMiddleGroupCache, dict[str, tuple[tuple, dict]]]:
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    values = __import__("edge63_C8_displacement_first", fromlist=["values_for_case"]).values_for_case(CASE)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    by_id = {
        middle_cache._group_path(key).stem.replace(".pkl", "").replace("middle_group_", ""): (key, residuals)
        for key, residuals in groups.items()
    }
    return middle_cache, by_id


def _outer_case(root: Path, bucket: dict[str, Any], selector: tuple[str, int, int], cache_root: Path) -> dict[str, Any]:
    family_key, occupied, source = _source_for_target(bucket, selector)
    family_id = _family_id(family_key)
    item = {
        "family_id": family_id,
        "semantic_signature_id": "e2e-golden",
        "allowed_count": 1,
        "occupied_values": list(occupied),
    }
    middle_cache, groups_by_id = _groups_by_id(root)
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    rows: dict[str, dict[str, Any]] = {}
    for name, index in (
        ("python", CompiledTerminalPairIndex(root, CASE, SLOT)),
        ("native", _index_for(root, cache_root, root / "native_engine_v1" / "native_tables" / "golden")),
    ):
        rows[name] = _audit_source(
            root,
            middle_cache,
            pair_cache,
            groups_by_id,
            item,
            source,
            compiled_index=index,
        )
    def matrix_key(row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            int(row["left_behavior_id"]),
            int(row["right_behavior_id"]),
            tuple(json.loads(row["intersection"])),
            int(row["intersection_size"]),
            int(row["pre_outer_span"]),
        )
    py_matrix = sorted(matrix_key(row) for row in rows["python"]["matrix"])
    native_matrix = sorted(matrix_key(row) for row in rows["native"]["matrix"])
    return {
        "selector": selector,
        "family_id": family_id,
        "family_key": family_key,
        "source": source,
        "python": {key: value for key, value in rows["python"].items() if key not in {"matrix", "outer_edge_rows"}},
        "native": {key: value for key, value in rows["native"].items() if key not in {"matrix", "outer_edge_rows"}},
        "python_matrix": py_matrix,
        "native_matrix": native_matrix,
        "exact_equal": py_matrix == native_matrix and rows["python"]["outer_edges"] == rows["native"]["outer_edges"],
        **_versions(),
    }


def _semantic_case(root: Path, bucket: dict[str, Any], cache_root: Path) -> dict[str, Any]:
    results = {}
    for name, index in (
        ("python", CompiledTerminalPairIndex(root, CASE, SLOT)),
        ("native", _index_for(root, cache_root, root / "native_engine_v1" / "native_tables" / "golden")),
    ):
        results[name] = _family_semantic(root, bucket, index)
    py_sig = sorted(_signature_key(row) for row in results["python"]["signatures"])
    native_sig = sorted(_signature_key(row) for row in results["native"]["signatures"])
    py_effect = sorted(_effect_key(row) for row in results["python"]["effects"])
    native_effect = sorted(_effect_key(row) for row in results["native"]["effects"])
    return {
        "python": {key: value for key, value in results["python"].items() if key not in {"signatures", "effects"}},
        "native": {key: value for key, value in results["native"].items() if key not in {"signatures", "effects"}},
        "signature_exact_equal": py_sig == native_sig,
        "effect_exact_equal": py_effect == native_effect,
        "semantic_exact_equal": py_sig == native_sig and py_effect == native_effect and results["python"]["positive_queries"] == results["native"]["positive_queries"],
        "signature_count_python": len(py_sig),
        "signature_count_native": len(native_sig),
        **_versions(),
    }


def _load_global_cert(root: Path) -> dict[str, Any]:
    return _read_json(root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_bilateral_v1" / "first_global_compatible_pair.json")


def run(root: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    native_root = output / "native_tables"
    golden_root = root / "native_engine_v1" / "native_tables" / "golden"
    batch_outcomes = list(csv.DictReader((root / "tree1_C8" / "left_leaf_2_exact_v3" / "frontier_directed_v1" / "table_batch_structure_v1" / "batch_outcomes.csv").open(encoding="utf-8")))
    empty_intervals = _parse_intervals(batch_outcomes[0]["intervals_b"])
    bilateral_intervals = _parse_intervals(next(row["left_intervals"] for row in csv.DictReader((root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_bilateral_v1" / "bilateral_contexts.csv").open(encoding="utf-8")) if row["group_id"] == "345e9b3c3bfdeb1914b08bb0" and row["context_id"] == "114"))
    global_cert = _load_global_cert(root)
    global_intervals = tuple(tuple(int(value) for value in part) for part in global_cert["blocks"][SLOT])
    targets = {empty_intervals, bilateral_intervals, global_intervals}
    collected = _collect_target_rows(root, targets)
    empty_semantic = _semantic_case(root, collected[empty_intervals], native_root)
    bilateral_selector = ("345e9b3c3bfdeb1914b08bb0", 114, 0)
    global_selector = (str(global_cert["group_id"]), int(global_cert["context_id"]), int(global_cert["residual_index"]))
    bilateral_outer = _outer_case(root, collected[bilateral_intervals], bilateral_selector, native_root)
    global_outer = _outer_case(root, collected[global_intervals], global_selector, native_root)
    local = _local_case(root, native_root)
    native_cache = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=native_root, source_root=golden_root)
    for intervals in sorted(targets):
        native_cache.get(intervals, "terminal")
    reload_cache = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=native_root, source_root=golden_root)
    reloaded = [reload_cache.get(intervals, "terminal") for intervals in sorted(targets)]
    reload_ok = all(row.checksum == reloaded[index].checksum for index, row in enumerate(
        [native_cache.get(intervals, "terminal") for intervals in sorted(targets)]
    )) and reload_cache.reload_count == len(targets)
    expected_empty = {
        "outcome": "ALL_QUERIES_EMPTY",
        "local_behavior_count": int(batch_outcomes[0]["local_behavior_count"]),
        "positive_queries": 0,
    }
    empty_pass = (
        empty_semantic["semantic_exact_equal"]
        and empty_semantic["native"]["positive_queries"] == 0
        and empty_semantic["native"]["empty_queries"] == empty_semantic["native"]["exact_queries"]
    )
    bilateral_pass = (
        bilateral_outer["exact_equal"]
        and int(bilateral_outer["native"]["left_count"]) == 4
        and int(bilateral_outer["native"]["right_count"]) == 2
        and int(bilateral_outer["native"]["outer_edges"]) == 0
        and int(bilateral_outer["native"]["minimum_pre_outer_span"]) == 63
    )
    global_pass = (
        global_outer["exact_equal"]
        and int(global_outer["native"]["outer_edges"]) > 0
        and (
            int(global_cert["left_behavior_id"]),
            int(global_cert["right_behavior_id"]),
            (),
            0,
            int(global_cert["span"]),
        ) in global_outer["native_matrix"]
        and global_cert["status"] == "COMPATIBLE_SPAN_GT63_PARTIAL"
    )
    result = {
        "status": "PASS" if empty_pass and bilateral_pass and global_pass and local["pass"] and reload_ok else "FAIL",
        "scope": "Tree1/C8.LevelB.v1/split(left_leaf_2)",
        "empty_case": {"intervals": empty_intervals, "collected_rows": collected[empty_intervals]["rows"], "expected": expected_empty, "actual": empty_semantic, "pass": empty_pass},
        "local_case": local,
        "bilateral_case": bilateral_outer,
        "global_case": global_outer,
        "cache_reload": {"pass": reload_ok, "reload_count": reload_cache.reload_count, "checksums": [row.checksum for row in reloaded]},
        "native_tables_persisted": len(list(native_root.glob("*.bin"))),
        **_versions(),
    }
    (output / "golden_global_differential.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=list), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/end_to_end_gate"))
    args = parser.parse_args()
    result = run(args.root, args.output)
    print(json.dumps({"status": result["status"], "cache_reload": result["cache_reload"]}, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
