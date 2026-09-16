"""Independent final verifier for the 1056-key native production run."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from edge63_C8_native_geometry_cache import NativeCompiledGeometryCache
from edge63_C8_native_pilot_verify import _recompute_table
from edge63_C8_table_batch_scheduler import CASE, SLOT, _route_worklist


LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
VERSIONS = {
    "two_run_language": LANGUAGE,
    "allocation_dedup_version": OWNERSHIP,
    "terminal_pair_cache_version": TERMINAL_CACHE,
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def run(root: Path, output: Path) -> dict[str, Any]:
    manifest = _rows(output / "production_manifest.csv")
    key_results = {row["table_key"]: row for row in _rows(output / "key_results.csv")}
    selected = [{
        "table_key": row["table_key"],
        "table_key_payload": row["table_key_payload"],
        "intervals_b": row["intervals_b"],
        "priority_rank": row.get("priority_rank", ""),
    } for row in manifest]
    tables = _route_worklist(root, selected)
    cache = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=output / "native_tables")
    mismatches: list[dict[str, Any]] = []
    recomputed: list[dict[str, Any]] = []
    for row in selected:
        key = row["table_key"]
        expected = key_results.get(key, {})
        try:
            result = _recompute_table(root, output, tables[key])
            recomputed.append(result)
            checks = {
                "outcome": result["recomputed_outcome"] == expected.get("outcome"),
                "queries": result["exact_queries"] == int(expected.get("distinct_exact_queries", 0) or 0),
                "positive": result["positive_queries"] == int(expected.get("positive_queries", 0) or 0),
                "behaviors": result["behavior_count"] == int(expected.get("local_behavior_count", 0) or 0),
                "manifest_closed": expected.get("production_status") in {"LOCAL_EMPTY", "ALL_QUERIES_EMPTY", "HAS_GLOBAL_COMPATIBLE", "HAS_BILATERAL_OUTER_ZERO"},
            }
            intervals = tuple(tuple(int(value) for value in part) for part in json.loads(row["intervals_b"]))
            loaded = cache.get(intervals, "terminal")
            checks["checksum"] = loaded.checksum == expected.get("checksum")
            if not all(checks.values()):
                mismatches.append({"table_key": key, "checks": checks, "recomputed": result, "expected": expected})
        except Exception as exc:
            mismatches.append({"table_key": key, "error": repr(exc)})

    cert_rows = _rows(output / "certificate_manifest.csv")
    certificate_refs = {row.get("table_key", "") for row in cert_rows}
    certificate_key_coverage = all(any(row.get("table_key") == key for row in cert_rows) or int(key_results[key].get("distinct_exact_queries", 0) or 0) == 0 for key in key_results)
    runtime_closed = all(row.get("status") in {"LOCAL_EMPTY", "ALL_QUERIES_EMPTY", "HAS_GLOBAL_COMPATIBLE", "HAS_BILATERAL_OUTER_ZERO"} for row in manifest)
    coverage = json.loads((output / "full_slot_coverage.json").read_text(encoding="utf-8"))
    production_closure = len(manifest) == 1056 and runtime_closed and not mismatches and coverage.get("table_partition_exact") and coverage.get("worklist_orphan_interval_rows") == 0
    full_slot_claim = bool(production_closure and not coverage.get("right_support_scope_is_partial", True) and not coverage.get("semantic_history_requires_merge", True))
    result = {
        "status": "PASS" if production_closure else "FAIL",
        "production_key_closure": "PASS" if production_closure else "FAIL",
        "full_slot_mathematical_closure": "NOT_CLAIMED" if not full_slot_claim else "PASS",
        "keys_expected": 1056,
        "keys_verified": len(recomputed),
        "runtime_closed": runtime_closed,
        "mismatch_count": len(mismatches),
        "certificate_rows": len(cert_rows),
        "certificate_key_coverage": certificate_key_coverage,
        "coverage_table_partition_exact": coverage.get("table_partition_exact"),
        "coverage_worklist_orphans": coverage.get("worklist_orphan_interval_rows"),
        "right_support_scope_is_partial": coverage.get("right_support_scope_is_partial"),
        "semantic_history_requires_merge": coverage.get("semantic_history_requires_merge"),
        "full_slot_claim": full_slot_claim,
        "mismatches": mismatches,
        **VERSIONS,
    }
    (output / "full_slot_verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/production_full_v1"))
    args = parser.parse_args()
    result = run(args.root, args.output)
    print(json.dumps({key: result[key] for key in ("status", "production_key_closure", "full_slot_mathematical_closure", "keys_verified", "mismatch_count", "full_slot_claim")}, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
