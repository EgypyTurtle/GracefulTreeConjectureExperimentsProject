"""Independent verifier for the bounded native C8 production pilot."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_collision_signature import _process_family
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_native_bridge import read_native_table
from edge63_C8_native_geometry_cache import NativeCompiledGeometryCache
from edge63_C8_table_batch_scheduler import CASE, SLOT, _route_worklist
from edge63_C8_two_run_cache import PersistentTwoRunCache


LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _recompute_table(root: Path, output: Path, table_data: dict[str, Any]) -> dict[str, Any]:
    cache = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=output / "native_tables")
    index = CompiledTerminalPairIndex(root, CASE, SLOT, geometry_cache=cache)
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    total = empty = positive = 0
    family_count = 0
    for family_id in sorted(table_data["families"]):
        family = table_data["families"][family_id]
        query_rows = [{"occupied_values_parsed": occupied} for occupied in sorted(
            family["queries"], key=lambda value: (len(value), tuple(sorted(value)))
        )]
        if not query_rows:
            continue
        signatures, _effects, _details = _process_family(
            pair_cache, index, family["family_key"], query_rows, family["sources"]
        )
        family_count += 1
        for row in signatures:
            count = int(row["query_count"])
            total += count
            if int(row["allowed_count"]) == 0:
                empty += count
            else:
                positive += count
    table_key = table_data["table"]["table_key"]
    table_path = cache._path(tuple(tuple(int(value) for value in part) for part in json.loads(table_data["table"]["intervals_b"])), "terminal")
    table = read_native_table(table_path)
    summary_path = output / "table_results" / f"{table_key}.json"
    expected_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    outer_path = output / "table_results" / f"{table_key}_outer_audit.csv"
    outer_rows = _read_rows(outer_path) if outer_path.exists() else []
    edges = sum(int(row.get("outer_edges", 0) or 0) for row in outer_rows)
    if len(table.records) == 0:
        outcome = "LOCAL_EMPTY"
    elif positive == 0:
        outcome = "ALL_QUERIES_EMPTY"
    elif edges and any(int(row.get("minimum_outer_edge_span", 10**9)) == 63 for row in outer_rows if row.get("minimum_outer_edge_span") not in {"", None}):
        outcome = "SAT_SPAN63"
    elif edges and any(int(row.get("minimum_outer_edge_span", 10**9)) <= 67 for row in outer_rows if row.get("minimum_outer_edge_span") not in {"", None}):
        outcome = "FRONTIER_COUNTEREXAMPLE_LE67"
    elif edges:
        outcome = "HAS_OUTER_POSITIVE_GT67"
    else:
        outcome = "HAS_BILATERAL_OUTER_ZERO"
    return {
        "table_key": table_key,
        "behavior_count": len(table.records),
        "exact_queries": total,
        "empty_queries": empty,
        "positive_queries": positive,
        "dependent_families": family_count,
        "outer_edges": edges,
        "recomputed_outcome": outcome,
        "scheduler_outcome": expected_summary.get("outcome"),
        "native_checksum": __import__("edge63_C8_compile_two_run_geometry", fromlist=["_checksum_records"])._checksum_records(tuple(
            __import__("edge63_C8_native_geometry_cache", fromlist=["_from_native"])._from_native(table, table.intervals, "terminal", 0.0).records
        )),
    }


def run(root: Path, output: Path) -> dict[str, Any]:
    pilot_manifest = _read_rows(output / "pilot_manifest.csv")
    key_results = {row["table_key"]: row for row in _read_rows(output / "key_results.csv")}
    selected = [{
        "table_key": row["table_key"],
        "table_key_payload": row["table_key_payload"],
        "intervals_b": row["intervals_b"],
        "priority_rank": row.get("priority_rank", ""),
    } for row in pilot_manifest]
    tables = _route_worklist(root, selected)
    recomputed = [_recompute_table(root, output, tables[item["table_key"]]) for item in selected]
    result_by_key = {row["table_key"]: row for row in recomputed}
    manifest_unique = len({row["table_key"] for row in pilot_manifest}) == len(pilot_manifest) == 64
    results_match = all(
        result_by_key[key]["recomputed_outcome"] == key_results[key].get("outcome")
        and result_by_key[key]["exact_queries"] == int(key_results[key].get("distinct_exact_queries", 0) or 0)
        and result_by_key[key]["positive_queries"] == int(key_results[key].get("positive_queries", 0) or 0)
        for key in result_by_key
    )
    cache = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=output / "native_tables")
    cache_checks = []
    for row in pilot_manifest:
        intervals = tuple(tuple(int(value) for value in part) for part in json.loads(row["intervals_b"]))
        path = cache._path(intervals, "terminal")
        try:
            table = read_native_table(path)
            cache_checks.append(table.intervals == intervals and table.language == LANGUAGE and table.ownership == OWNERSHIP and table.terminal_cache == TERMINAL_CACHE)
        except (OSError, ValueError, TypeError, IndexError, UnicodeError):
            cache_checks.append(False)
    cert_rows = _read_rows(output / "certificate_manifest.csv")
    certificates_sound = all(
        (int(row.get("allowed_count", 0) or 0) == 0 and row.get("certificate_type") in {"FAMILY_BEHAVIOR_EMPTY", "H1", "H2", "H3", "FULL_MASK_EMPTY"})
        or int(row.get("allowed_count", 0) or 0) > 0
        for row in cert_rows
    )
    result = {
        "status": "PASS" if manifest_unique and results_match and all(cache_checks) and certificates_sound else "FAIL",
        "keys_verified": len(recomputed),
        "manifest_unique_64": manifest_unique,
        "results_match": results_match,
        "native_cache_checks_pass": sum(cache_checks),
        "native_cache_checks_total": len(cache_checks),
        "certificate_rows": len(cert_rows),
        "certificates_sound": certificates_sound,
        "recomputed": recomputed,
        **_versions(),
    }
    (output / "pilot_verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/production_pilot_64"))
    args = parser.parse_args()
    result = run(args.root, args.output)
    print(json.dumps({key: result[key] for key in ("status", "keys_verified", "results_match", "certificates_sound")}, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
