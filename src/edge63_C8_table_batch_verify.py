"""Independent verifier for one frontier-directed C8 table batch.

The verifier reads only the batch artifacts and persistent compiled objects.
It samples one stored semantic family per table and recomputes that family
through the existing exact semantic path, without advancing any runner.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from edge63_C8_collision_signature import _process_family
from edge63_C8_compile_two_run_geometry import PersistentCompiledGeometryCache
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_two_run_cache import PersistentTwoRunCache


LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verify(root: Path) -> dict[str, object]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3" / "frontier_directed_v1" / "table_batch_structure_v1"
    key_rows = _read_csv(base / "batch_key_manifest.csv")
    outcome_rows = {row["table_key"]: row for row in _read_csv(base / "batch_outcomes.csv")}
    geometry_cache = PersistentCompiledGeometryCache(root, CASE, SLOT)
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    index = CompiledTerminalPairIndex(root, CASE, SLOT)
    checks = {
        "batch_key_count": len(key_rows) == 32,
        "unique_table_keys": len({row["table_key"] for row in key_rows}) == len(key_rows),
        "versions_exact": all(
            row.get("two_run_language") == LANGUAGE
            and row.get("allocation_dedup_version") == OWNERSHIP
            and row.get("terminal_pair_cache_version") == TERMINAL_CACHE
            for row in key_rows
        ),
        "compiled_objects_valid": True,
        "table_results_consistent": True,
        "semantic_samples_consistent": True,
        "no_unresolved_compile_error": True,
    }
    sample_details: list[dict[str, object]] = []
    for key_row in key_rows:
        table_key = key_row["table_key"]
        result_path = base / "table_results" / f"{table_key}.json"
        signature_path = base / "table_results" / f"{table_key}_semantic_signatures.csv"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
        intervals = tuple(tuple(int(value) for value in part) for part in json.loads(key_row["intervals_b"]))
        cache_path = geometry_cache._path(intervals, "terminal")
        compiled = geometry_cache._read(cache_path, intervals, "terminal") if cache_path.exists() else None
        compiled_ok = compiled is not None and len(compiled.records) == int(key_row["behavior_count"])
        checks["compiled_objects_valid"] = bool(checks["compiled_objects_valid"] and compiled_ok)
        expected_outcome = outcome_rows.get(table_key, {}).get("outcome")
        result_ok = (
            result.get("table_key") == table_key
            and result.get("outcome") == expected_outcome
            and result.get("two_run_language") == LANGUAGE
            and result.get("allocation_dedup_version") == OWNERSHIP
            and result.get("terminal_pair_cache_version") == TERMINAL_CACHE
            and (expected_outcome != "ALL_QUERIES_EMPTY" or (
                int(result.get("local_behavior_count", 0)) > 0
                and int(result.get("positive_queries", 0)) == 0
                and int(result.get("empty_queries", -1)) == int(result.get("distinct_exact_queries", -2))
            ))
        )
        checks["table_results_consistent"] = bool(checks["table_results_consistent"] and result_ok)
        sample_ok = True
        sampled_family = None
        if signature_path.exists() and compiled_ok:
            signature_rows = _read_csv(signature_path)
            if signature_rows:
                sampled = signature_rows[0]
                sampled_family = sampled["family_key"]
                occupied_examples = json.loads(sampled["occupied_examples"])
                query_rows = [{"occupied_values_parsed": frozenset(int(value) for value in values)} for values in occupied_examples]
                fresh_signatures, _effect, _details = _process_family(
                    pair_cache,
                    index,
                    sampled_family,
                    query_rows,
                    {},
                )
                stored_counts = sorted(int(row["allowed_count"]) for row in fresh_signatures)
                expected_counts = sorted(int(row["allowed_count"]) for row in signature_rows if row["family_id"] == sampled["family_id"])
                sample_ok = stored_counts == expected_counts[:len(stored_counts)]
        checks["semantic_samples_consistent"] = bool(checks["semantic_samples_consistent"] and sample_ok)
        sample_details.append({
            "table_key": table_key,
            "compiled_records": len(compiled.records) if compiled is not None else None,
            "expected_behavior_count": int(key_row["behavior_count"]),
            "sampled_family_key": sampled_family,
            "semantic_sample_pass": sample_ok,
        })
    checks["no_unresolved_compile_error"] = all(row.get("outcome") != "UNRESOLVED_RESOURCE" for row in outcome_rows.values())
    status = "PASS" if all(bool(value) for value in checks.values()) else "FAIL"
    return {
        "status": status,
        "checks": checks,
        "sample_details": sample_details,
        "scope": "frontier-directed top-32 table batch only",
        "full_slot_claim": False,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    args = parser.parse_args()
    result = verify(args.root)
    output = args.root / "tree1_C8" / "left_leaf_2_exact_v3" / "frontier_directed_v1" / "table_batch_structure_v1" / "independent_verification_v13.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
