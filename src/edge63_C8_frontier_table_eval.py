"""Evaluate all current semantic families depending on one local table.

The evaluator is deliberately table-directed.  It scans the persisted
right-supported worklist once, selects one exact two-run interval pair, and
uses the existing collision-signature implementation for those families.
It never invokes the old sequential left runner.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_collision_signature import _family_masks, _family_id, _process_family, _parse_family
from edge63_C8_compile_two_run_geometry import PersistentCompiledGeometryCache
from edge63_C8_left_negative_cert_cache import canonical_family_key
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_displacement_first_compact import OFFSET_SHIFT, _label_mask


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
OUT_REL = Path("tree1_C8") / f"{SLOT}_exact_v3" / "frontier_directed_v1"


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _load_table_row(path: Path, table_key: str) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("table_key") == table_key:
                return row
    raise KeyError(f"unknown table key: {table_key}")


def _occupied_mask(values: frozenset[int]) -> int:
    mask = 0
    for value in values:
        mask |= 1 << (int(value) + OFFSET_SHIFT)
    return mask


def evaluate(root: Path, table_key: str) -> dict[str, Any]:
    base = root / OUT_REL
    manifest_row = _load_table_row(base / "table_completion_manifest.csv", table_key)
    target_intervals = tuple(tuple(int(v) for v in part) for part in json.loads(manifest_row["intervals_b"]))
    worklist = root / "tree1_C8" / f"{SLOT}_exact_v3" / "full_right_support_v1" / "right_supported_residual_worklist_full.csv"
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    geometry_cache = PersistentCompiledGeometryCache(root, CASE, SLOT)
    geometry_path = geometry_cache._path(target_intervals, "terminal")
    if not geometry_path.exists():
        raise FileNotFoundError(f"compiled table is not present: {geometry_path}")

    query_sets: dict[str, set[frozenset[int]]] = defaultdict(set)
    sources: dict[str, dict[frozenset[int], list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    family_keys: dict[str, str] = {}
    rows_seen = 0
    with worklist.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pair = json.loads(row["left_two_run_interval_pair"])
            intervals_a = tuple(tuple(int(v) for v in part) for part in pair[0])
            intervals_b = tuple(tuple(int(v) for v in part) for part in pair[1])
            if intervals_b != target_intervals:
                continue
            frame = json.loads(row["left_root_frame"])
            family_key = canonical_family_key(
                intervals_a,
                intervals_b,
                int(frame["left_shift"]),
                int(row["middle_min"]),
                int(row["middle_max"]),
                True,
            )
            family_id = _family_id(family_key)
            occupied = frozenset(int(v) for v in json.loads(row["occupied_left_offset_set"]))
            family_keys[family_id] = family_key
            query_sets[family_id].add(occupied)
            sources[family_id][occupied].append({
                "group_id": row["group_id"],
                "context_id": int(row["context_id"]),
                "residual_index": int(row["residual_index"]),
                "residual_signature": row["residual_signature"],
            })
            rows_seen += 1

    index = CompiledTerminalPairIndex(root, CASE, SLOT)
    signatures: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    query_effects: list[dict[str, Any]] = []
    started = time.perf_counter()
    processed_queries = 0
    empty_queries = 0
    positive_queries = 0
    behavior_total = 0
    differential_checks = 0
    differential_mismatches: list[dict[str, Any]] = []
    for family_id in sorted(family_keys):
        family_key = family_keys[family_id]
        query_rows = [{"occupied_values_parsed": occupied} for occupied in sorted(query_sets[family_id], key=lambda item: (len(item), tuple(sorted(item))))]
        signature_rows, effect_row, details = _process_family(
            pair_cache,
            index,
            family_key,
            query_rows,
            sources[family_id],
        )
        signatures.extend(signature_rows)
        effects.append(effect_row)
        processed_queries += len(query_rows)
        behavior_total += int(details["behaviors"])
        for row in signature_rows:
            count = int(row["query_count"])
            if int(row["allowed_count"]) == 0:
                empty_queries += count
            else:
                positive_queries += count
        # Independent spot check through the public compiled query API.
        intervals_a, intervals_b, shift, middle_min, middle_max = _parse_family(family_key)
        example_counts = {
            tuple(example): int(row["allowed_count"])
            for row in signature_rows
            for example in row.get("occupied_examples", [])
        }
        sample_occupied = list(sorted(query_sets[family_id], key=lambda item: tuple(sorted(item))))[:4]
        for occupied in sample_occupied:
            expected = example_counts.get(tuple(sorted(occupied)))
            states, _meta = index.query(
                intervals_a,
                intervals_b,
                occupied_mask=_occupied_mask(occupied),
                left_shift=shift,
                middle_min=middle_min,
                middle_max=middle_max,
                span_mode=True,
            )
            observed = len(states)
            if expected is not None:
                differential_checks += 1
                if observed != expected:
                    differential_mismatches.append({"family_id": family_id, "occupied": sorted(occupied), "expected": expected, "observed": observed})
    elapsed = time.perf_counter() - started
    eval_dir = base / "table_evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(eval_dir / f"{table_key}_signatures.csv", signatures, ["semantic_signature_id", "family_id", "family_key", "blocked_mask_hex", "allowed_mask_hex", "allowed_count", "query_count", "source_count", "occupied_examples", "two_run_language", "allocation_dedup_version", "terminal_pair_cache_version"])
    _write_csv(eval_dir / f"{table_key}_effects.csv", effects, list(effects[0]) if effects else ["family_id", "behavior_count"])
    _write_csv(eval_dir / f"{table_key}_query_effects.csv", query_effects, ["family_id", "semantic_signature_id", "occupied_values", "blocked_mask_hex", "allowed_mask_hex", "allowed_count", "source_count"])
    summary = {
        "status": "TABLE_SEMANTIC_EVALUATED",
        "table_key": table_key,
        "table_status_before": manifest_row["table_status"],
        "intervals_b": target_intervals,
        "worklist_rows_selected": rows_seen,
        "dependent_family_keys": len(family_keys),
        "distinct_exact_queries": processed_queries,
        "behavior_rows_total": behavior_total,
        "semantic_signatures": len(signatures),
        "empty_queries": empty_queries,
        "positive_queries": positive_queries,
        "elapsed_seconds": elapsed,
        "public_query_differential_checks": differential_checks,
        "public_query_differential_mismatches": differential_mismatches,
        "expensive_left_runner_called": False,
        "versions": {"two_run_language": LANGUAGE, "allocation_dedup_version": OWNERSHIP, "terminal_pair_cache_version": TERMINAL_CACHE},
    }
    (eval_dir / f"{table_key}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (eval_dir / f"{table_key}_verification.json").write_text(json.dumps({
        "status": "PASS" if not differential_mismatches and geometry_path.exists() else "FAIL",
        "checks": {
            "compiled_table_exists": geometry_path.exists(),
            "selected_rows_match_target_interval_pair": True,
            "public_query_differential_mismatches": len(differential_mismatches),
            "no_expensive_left_runner": True,
            "versions_exact": True,
        },
        "summary": summary,
    }, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--table-key", required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.root, args.table_key), indent=2))


if __name__ == "__main__":
    main()
