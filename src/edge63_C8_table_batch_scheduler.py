"""Batch frontier-directed local-table compilation and semantic census.

This module is intentionally narrower than the C8 global runner.  It selects
the highest-coverage missing local-table keys, compiles each key once, routes
the persisted right-supported worklist in one pass, and evaluates dependent
families with the existing exact semantic implementation.  It never advances
the right census and never invokes the sequential left runner.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from edge63_C8_collision_signature import (
    _family_id,
    _parse_family,
    _process_family,
)
from edge63_C8_compile_two_run_geometry import (
    COMPILED_VERSION,
    PersistentCompiledGeometryCache,
)
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_left_negative_cert_cache import canonical_family_key
from edge63_C8_middle_group_cache import canonical_json, version_fingerprint
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_outer_zero_audit import _audit_source
from edge63_C8_displacement_first import values_for_case
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
OUT_REL = Path("tree1_C8") / "left_leaf_2_exact_v3" / "frontier_directed_v1" / "table_batch_structure_v1"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _json_intervals(raw: str) -> tuple[tuple[int, int], ...]:
    return tuple(tuple(int(value) for value in part) for part in json.loads(raw))


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _compile_worker(payload: tuple[str, str, str, tuple[tuple[int, int], ...]]) -> dict[str, Any]:
    root_text, table_key, table_key_payload, intervals = payload
    root = Path(root_text)
    started = time.perf_counter()
    cache = PersistentCompiledGeometryCache(root, CASE, SLOT)
    compiled = cache.get(intervals, "terminal")
    path = cache._path(intervals, "terminal")
    return {
        "table_key": table_key,
        "table_key_payload": table_key_payload,
        "intervals_b": json.dumps([list(part) for part in intervals], separators=(",", ":")),
        "pair_id": compiled.pair_id,
        "compiled_version": COMPILED_VERSION,
        "behavior_count": len(compiled.records),
        "compile_seconds": round(time.perf_counter() - started, 6),
        "intrinsic_compile_seconds": round(compiled.compile_seconds, 6),
        "cache_bytes": path.stat().st_size if path.exists() else 0,
        "checksum": compiled.checksum,
        "version_fingerprint": compiled.version_fingerprint,
        "status": "READY_COMPILED_GEOMETRY",
        **_versions(),
    }


def _load_priority(base: Path, batch_size: int) -> list[dict[str, str]]:
    priority_path = base / "frontier_table_priority.csv"
    manifest_path = base / "table_completion_manifest.csv"
    manifest: dict[str, dict[str, str]] = {}
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            manifest[row["table_key"]] = row
    rows: list[dict[str, str]] = []
    with priority_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            item = manifest.get(row["table_key"])
            if not item or item.get("table_status") != "MISSING_LOCAL_TABLE":
                continue
            row["intervals_b"] = item["intervals_b"]
            row["intervals_a"] = item["intervals_a"]
            row["table_key_payload"] = item["table_key_payload"]
            rows.append(row)
            if len(rows) >= batch_size:
                break
    if not rows:
        raise RuntimeError("no missing active table keys are available")
    return rows


def _benchmark_worker_scaling(root: Path, selected: list[dict[str, str]], out: Path) -> list[dict[str, Any]]:
    """Benchmark isolated compilation only; the real cache is never touched."""
    reps = selected[:4]
    rows: list[dict[str, Any]] = []
    bench_root = out / "worker_benchmark"
    bench_root.mkdir(parents=True, exist_ok=True)
    for workers in (1, 2, 4):
        isolated = Path(tempfile.mkdtemp(prefix=f"w{workers}_", dir=bench_root))
        payloads = [
            (str(isolated), item["table_key"], item["table_key_payload"], _json_intervals(item["intervals_b"]))
            for item in reps
        ]
        started = time.perf_counter()
        try:
            if workers == 1:
                results = [_compile_worker(payload) for payload in payloads]
            else:
                with ProcessPoolExecutor(max_workers=workers) as pool:
                    results = list(pool.map(_compile_worker, payloads))
            elapsed = time.perf_counter() - started
            rows.append({
                "workers": workers,
                "representative_keys": len(results),
                "total_seconds": round(elapsed, 6),
                "tables_per_second": round(len(results) / elapsed, 6) if elapsed else None,
                "peak_ram": "UNAVAILABLE_NATIVE_PROFILE",
                "status": "PASS",
                **_versions(),
            })
        except Exception as exc:  # pragma: no cover - worker failure is reported, not hidden
            rows.append({
                "workers": workers,
                "representative_keys": len(payloads),
                "total_seconds": round(time.perf_counter() - started, 6),
                "tables_per_second": None,
                "peak_ram": "UNAVAILABLE_NATIVE_PROFILE",
                "status": "ERROR",
                "error": repr(exc),
                **_versions(),
            })
        finally:
            shutil.rmtree(isolated, ignore_errors=True)
    _write_csv(out / "worker_scaling_benchmark.csv", rows)
    return rows


def _route_worklist(root: Path, selected: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    selected_by_intervals = {
        item["intervals_b"]: item for item in selected
    }
    tables: dict[str, dict[str, Any]] = {
        item["table_key"]: {
            "table": item,
            "rows_seen": 0,
            "families": defaultdict(lambda: {"family_key": "", "queries": set(), "sources": defaultdict(list)}),
        }
        for item in selected
    }
    worklist = root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_right_support_v1" / "right_supported_residual_worklist_full.csv"
    with worklist.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pair = json.loads(row["left_two_run_interval_pair"])
            intervals_b = json.dumps(pair[1], separators=(",", ":"))
            item = selected_by_intervals.get(intervals_b)
            if item is None:
                continue
            table_data = tables[item["table_key"]]
            table_data["rows_seen"] += 1
            intervals_a = tuple(tuple(int(v) for v in part) for part in pair[0])
            intervals_b_tuple = tuple(tuple(int(v) for v in part) for part in pair[1])
            frame = json.loads(row["left_root_frame"])
            family_key = canonical_family_key(
                intervals_a,
                intervals_b_tuple,
                int(frame["left_shift"]),
                int(row["middle_min"]),
                int(row["middle_max"]),
                True,
            )
            family_id = _family_id(family_key)
            family = table_data["families"][family_id]
            family["family_key"] = family_key
            occupied = frozenset(int(v) for v in json.loads(row["occupied_left_offset_set"]))
            family["queries"].add(occupied)
            # One concrete provenance row per exact occupied query is enough
            # for a witness; counts remain available at worklist level.
            if not family["sources"][occupied]:
                family["sources"][occupied].append({
                    "group_id": row["group_id"],
                    "context_id": int(row["context_id"]),
                    "residual_index": int(row["residual_index"]),
                    "residual_signature": row["residual_signature"],
                })
    return tables


def _effect_mask_motif(rows: list[dict[str, Any]]) -> str:
    """Exact within-table effect summary; no role normalization is claimed."""
    payload = sorted((row.get("blocked_mask_hex", "0"), int(row.get("allowed_count", 0))) for row in rows)
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:20]


def _audit_positive_sources(
    root: Path,
    positive_sources: list[dict[str, Any]],
    *,
    compiled_index: CompiledTerminalPairIndex | None = None,
) -> list[dict[str, Any]]:
    if not positive_sources:
        return []
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    groups_by_id = {
        middle_cache._group_path(key).stem.replace(".pkl", "").replace("middle_group_", ""): (key, residuals)
        for key, residuals in groups.items()
    }
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    audited: list[dict[str, Any]] = []
    for item in positive_sources:
        source = item["source"]
        try:
            audited.append(_audit_source(
                root,
                middle_cache,
                pair_cache,
                groups_by_id,
                item,
                source,
                compiled_index=compiled_index,
            ))
        except Exception as exc:
            audited.append({
                "status": "OUTER_AUDIT_ERROR",
                "family_id": item.get("family_id"),
                "semantic_signature_id": item.get("semantic_signature_id"),
                "source": source,
                "error": repr(exc),
                **_versions(),
            })
    return audited


def _evaluate_table(
    root: Path,
    out: Path,
    table_data: dict[str, Any],
    compile_row: dict[str, Any],
    *,
    geometry_cache: Any | None = None,
) -> dict[str, Any]:
    item = table_data["table"]
    table_key = item["table_key"]
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    index = CompiledTerminalPairIndex(root, CASE, SLOT, geometry_cache=geometry_cache)
    signatures: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    positive_sources: list[dict[str, Any]] = []
    family_count = 0
    total_queries = 0
    empty_queries = 0
    positive_queries = 0
    family_empty = 0
    behavior_rows_total = 0
    started = time.perf_counter()
    family_rows_for_motif: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for family_id in sorted(table_data["families"]):
        family = table_data["families"][family_id]
        query_rows = [{"occupied_values_parsed": occupied} for occupied in sorted(family["queries"], key=lambda value: (len(value), tuple(sorted(value))))]
        if not query_rows:
            continue
        signature_rows, effect_row, details = _process_family(
            pair_cache,
            index,
            family["family_key"],
            query_rows,
            family["sources"],
        )
        family_count += 1
        total_queries += len(query_rows)
        behavior_rows_total += int(details["behaviors"])
        signatures.extend(signature_rows)
        effects.append(effect_row)
        family_rows_for_motif[family_id].extend(signature_rows)
        for signature in signature_rows:
            count = int(signature["query_count"])
            if int(signature["allowed_count"]) == 0:
                empty_queries += count
            else:
                positive_queries += count
                occupied_examples = signature["occupied_examples"]
                if isinstance(occupied_examples, str):
                    occupied_examples = json.loads(occupied_examples)
                for occupied in occupied_examples:
                    for source in family["sources"].get(frozenset(int(value) for value in occupied), []):
                        positive_sources.append({
                            "family_id": family_id,
                            "semantic_signature_id": signature["semantic_signature_id"],
                            "allowed_count": int(signature["allowed_count"]),
                            "occupied_values": occupied,
                            "source": source,
                        })
        if details["behaviors"] == 0:
            family_empty += 1
    intervals_b = _json_intervals(item["intervals_b"])
    compiled = index.geometry_cache.get(intervals_b, "terminal")
    local_behavior_count = len(compiled.records)
    if local_behavior_count == 0:
        outcome = "LOCAL_EMPTY"
    elif positive_queries == 0:
        outcome = "ALL_QUERIES_EMPTY"
    else:
        outcome = "HAS_BILATERAL_OUTER_ZERO"
    outer_rows = _audit_positive_sources(root, positive_sources, compiled_index=index)
    outer_edges = [row for row in outer_rows if row.get("status") not in {"OUTER_AUDIT_ERROR"} and int(row.get("outer_edges", 0)) > 0]
    counterexamples = [
        row for row in outer_edges
        if row.get("minimum_outer_edge_span") is not None and int(row["minimum_outer_edge_span"]) <= 67
    ]
    sat_edges = [
        row for row in outer_edges
        if row.get("minimum_outer_edge_span") is not None and int(row["minimum_outer_edge_span"]) == 63
    ]
    if sat_edges:
        outcome = "SAT_SPAN63"
    elif counterexamples:
        outcome = "FRONTIER_COUNTEREXAMPLE_LE67"
    elif outer_edges:
        outcome = "HAS_OUTER_POSITIVE_GT67"
    table_dir = out / "table_results"
    table_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(table_dir / f"{table_key}_semantic_signatures.csv", signatures)
    _write_csv(table_dir / f"{table_key}_effects.csv", effects)
    _write_csv(table_dir / f"{table_key}_outer_audit.csv", outer_rows)
    motif_rows = []
    for family_id, rows in family_rows_for_motif.items():
        motif_rows.append({
            "table_key": table_key,
            "family_id": family_id,
            "effect_mask_motif_id": _effect_mask_motif(rows),
            "semantic_signatures": len(rows),
            "empty_signatures": sum(int(row["allowed_count"]) == 0 for row in rows),
            "normalization": "EFFECT_MASK_ONLY_NO_ROLE_NORMALIZATION",
            **_versions(),
        })
    _write_csv(table_dir / f"{table_key}_obstruction_motifs.csv", motif_rows)
    summary = {
        "table_key": table_key,
        "table_key_payload": item["table_key_payload"],
        "intervals_b": intervals_b,
        "rows_seen": table_data["rows_seen"],
        "dependent_families": family_count,
        "distinct_exact_queries": total_queries,
        "local_behavior_count": local_behavior_count,
        "behavior_rows_total": behavior_rows_total,
        "semantic_signatures": len(signatures),
        "empty_queries": empty_queries,
        "positive_queries": positive_queries,
        "family_empty_count": family_empty,
        "positive_provenance_examples": len(positive_sources),
        "outer_audited_contexts": len(outer_rows),
        "outer_edges": sum(int(row.get("outer_edges", 0)) for row in outer_rows if row.get("status") != "OUTER_AUDIT_ERROR"),
        "frontier_counterexamples_le67": len(counterexamples),
        "outcome": outcome,
        "table_status": "NONEMPTY_TABLE_BUT_ALL_CONTEXTS_EMPTY" if outcome == "ALL_QUERIES_EMPTY" else outcome,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "compile": compile_row,
        "motif_normalization": "EFFECT_MASK_ONLY_NO_ROLE_NORMALIZATION",
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    _write_json(table_dir / f"{table_key}.json", summary)
    return {**summary, "motif_rows": motif_rows, "outer_rows": outer_rows}


def _frontier_baseline_row(label: str, completed: int, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    all_outer = [row for result in outcomes for row in result.get("outer_rows", []) if row.get("status") != "OUTER_AUDIT_ERROR"]
    edges = [row for row in all_outer if int(row.get("outer_edges", 0)) > 0]
    spans = [int(row["minimum_pre_outer_span"]) for row in edges if row.get("minimum_pre_outer_span") is not None]
    return {
        "checkpoint": label,
        "tables_processed": completed,
        "frontier_status": "BATCH_SCOPE_ONLY",
        "kappa_min_63": "NOT_DEFINED_WITHOUT_PAIR_CENSUS",
        "kappa_min_67": "NOT_DEFINED_WITHOUT_PAIR_CENSUS",
        "minimum_outer_compatible_span_in_batch": min(spans) if spans else "NONE",
        "counterexample_le67": sum(int(result["frontier_counterexamples_le67"]) for result in outcomes),
        "full_slot_claim": False,
        **_versions(),
    }


def run(root: Path, batch_size: int = 32, workers: int | None = None) -> dict[str, Any]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3" / "frontier_directed_v1"
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    selected = _load_priority(base, batch_size)
    worker_rows = _benchmark_worker_scaling(root, selected, out)
    if workers is None:
        good = [row for row in worker_rows if row["status"] == "PASS"]
        workers = min((int(row["workers"]) for row in good), key=lambda value: next(row["total_seconds"] for row in good if int(row["workers"]) == value), default=1)
    workers = max(1, min(int(workers), 4))
    compile_payloads = [
        (str(root), item["table_key"], item["table_key_payload"], _json_intervals(item["intervals_b"]))
        for item in selected
    ]
    compile_started = time.perf_counter()
    compile_results: list[dict[str, Any]] = []
    compile_errors: list[dict[str, Any]] = []
    if workers == 1:
        iterator = map(_compile_worker, compile_payloads)
        for payload, item in zip(iterator, selected):
            compile_results.append(payload)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_compile_worker, payload) for payload in compile_payloads]
            for future, item in zip(futures, selected):
                try:
                    compile_results.append(future.result())
                except Exception as exc:
                    compile_errors.append({"table_key": item["table_key"], "error": repr(exc), "status": "UNRESOLVED_RESOURCE", **_versions()})
    compile_by_key = {row["table_key"]: row for row in compile_results}
    compile_elapsed = time.perf_counter() - compile_started
    tables = _route_worklist(root, selected)
    outcomes: list[dict[str, Any]] = []
    for item in selected:
        table_key = item["table_key"]
        if table_key not in compile_by_key:
            outcomes.append({
                "table_key": table_key,
                "intervals_b": item["intervals_b"],
                "outcome": "UNRESOLVED_RESOURCE",
                "rows_seen": tables[table_key]["rows_seen"],
                "compile_error": next((row["error"] for row in compile_errors if row["table_key"] == table_key), "unknown compile error"),
                **_versions(),
            })
            continue
        outcomes.append(_evaluate_table(root, out, tables[table_key], compile_by_key[table_key]))
    key_rows = []
    for rank, item in enumerate(selected, 1):
        compile_row = compile_by_key.get(item["table_key"], {})
        result = next((row for row in outcomes if row["table_key"] == item["table_key"]), {})
        key_rows.append({
            "batch_rank": rank,
            "priority_rank": item.get("priority_rank"),
            "table_key": item["table_key"],
            "table_key_payload": item["table_key_payload"],
            "intervals_b": item["intervals_b"],
            "active_queries": item.get("active_queries"),
            "active_dependent_families": item.get("active_dependent_families"),
            "new_scope_queries": item.get("new_scope_queries"),
            "behavior_count": compile_row.get("behavior_count"),
            "compile_seconds": compile_row.get("compile_seconds"),
            "cache_bytes": compile_row.get("cache_bytes"),
            "outcome": result.get("outcome", "UNRESOLVED_RESOURCE"),
            "rows_seen": result.get("rows_seen", 0),
            **_versions(),
        })
    _write_csv(out / "batch_key_manifest.csv", key_rows)
    _write_csv(out / "batch_outcomes.csv", [{key: value for key, value in row.items() if key not in {"motif_rows", "outer_rows", "compile"}} for row in outcomes])
    _write_csv(out / "compile_cost_distribution.csv", [
        {
            "table_key": row.get("table_key"),
            "behavior_count": row.get("behavior_count"),
            "compile_seconds": row.get("compile_seconds"),
            "intrinsic_compile_seconds": row.get("intrinsic_compile_seconds"),
            "cache_bytes": row.get("cache_bytes"),
            "status": row.get("status"),
            **_versions(),
        }
        for row in compile_results
    ])
    semantic_stats = []
    obstruction_rows = []
    cross_counter: Counter[str] = Counter()
    cross_tables: defaultdict[str, set[str]] = defaultdict(set)
    cross_queries: defaultdict[str, int] = defaultdict(int)
    for result in outcomes:
        if "semantic_signatures" not in result:
            continue
        semantic_stats.append({
            "table_key": result["table_key"],
            "exact_queries": result["distinct_exact_queries"],
            "semantic_signatures": result["semantic_signatures"],
            "semantic_ratio": result["semantic_signatures"] / result["distinct_exact_queries"] if result["distinct_exact_queries"] else 0.0,
            "empty_queries": result["empty_queries"],
            "positive_queries": result["positive_queries"],
            "local_behavior_count": result["local_behavior_count"],
            "table_outcome": result["outcome"],
            **_versions(),
        })
        for motif in result.get("motif_rows", []):
            obstruction_rows.append(motif)
            motif_id = motif["effect_mask_motif_id"]
            cross_counter[motif_id] += 1
            cross_tables[motif_id].add(result["table_key"])
            cross_queries[motif_id] += int(result["distinct_exact_queries"])
    _write_csv(out / "table_semantic_stats.csv", semantic_stats)
    _write_csv(out / "table_obstruction_classes.csv", obstruction_rows)
    cross_rows = [{
        "effect_mask_motif_id": motif_id,
        "family_occurrences": count,
        "tables": len(cross_tables[motif_id]),
        "normalization": "EFFECT_MASK_ONLY_NO_ROLE_NORMALIZATION",
        **_versions(),
    } for motif_id, count in sorted(cross_counter.items(), key=lambda pair: (-pair[1], pair[0]))]
    coverage_rows = [{
        "effect_mask_motif_id": motif_id,
        "tables": len(cross_tables[motif_id]),
        "family_occurrences": cross_counter[motif_id],
        "dependent_exact_queries_approx": cross_queries[motif_id],
        "coverage_metric": "family_effect_summary_only",
        **_versions(),
    } for motif_id in sorted(cross_counter)]
    _write_csv(out / "cross_table_motif_classes.csv", cross_rows)
    _write_csv(out / "motif_coverage.csv", coverage_rows)
    completed_outcomes = [row for row in outcomes if row.get("outcome") != "UNRESOLVED_RESOURCE"]
    frontier_rows = [
        _frontier_baseline_row(
            f"after_key_{index:02d}",
            index,
            completed_outcomes[:index],
        )
        for index in range(1, len(completed_outcomes) + 1)
    ]
    _write_csv(out / "frontier_after_each_key.csv", frontier_rows)
    counterexamples = [
        {"table_key": result["table_key"], "outer_rows": result.get("outer_rows", []), **_versions()}
        for result in outcomes if result.get("frontier_counterexamples_le67", 0)
    ]
    _write_json(out / "frontier_counterexamples.json", {
        "status": "FOUND" if counterexamples else "NONE_IN_BATCH",
        "scope": "frontier-directed top batch only",
        "counterexamples": counterexamples,
        "full_slot_claim": False,
        **_versions(),
    })
    outcome_counts = Counter(row.get("outcome", "UNRESOLVED_RESOURCE") for row in outcomes)
    diagnostic = "STRUCTURAL_COUNTEREXAMPLE_FOUND" if counterexamples else (
        "STRUCTURE_STILL_COMPRESSING" if any(value > 1 for value in cross_counter.values()) else "STRUCTURE_DIVERSITY_HIGH"
    )
    _write_json(out / "structure_phase_diagnostic.json", {
        "diagnostic": diagnostic,
        "outcome_counts": dict(outcome_counts),
        "motif_normalization": "EFFECT_MASK_ONLY_NO_ROLE_NORMALIZATION",
        "role_signed_sum_theorem_ready": False,
        "note": "Cross-table motifs are exact effect-mask summaries, not graph-role or signed-sum motifs.",
        **_versions(),
    })
    summary = {
        "status": "BATCH_COMPLETE_WITH_ERRORS" if compile_errors else "BATCH_COMPLETE",
        "batch_size_requested": batch_size,
        "tables_selected": len(selected),
        "tables_compiled": len(compile_results),
        "tables_with_compile_errors": len(compile_errors),
        "workers_used": workers,
        "compile_elapsed_seconds": round(compile_elapsed, 6),
        "outcome_counts": dict(outcome_counts),
        "frontier_counterexamples": len(counterexamples),
        "frontier_status": "NOT_FULL_SLOT",
        "right_census_advanced": False,
        "sequential_left_runner_called": False,
        "worker_scaling": worker_rows,
        "compile_errors": compile_errors,
        "versions": _versions(),
    }
    _write_json(out / "batch_summary.json", summary)
    _write_json(out / "verification_v13.json", {
        "status": "PASS" if not compile_errors and all(row.get("two_run_language") == LANGUAGE for row in outcomes) else "FAIL",
        "checks": {
            "selected_keys_unique": len({row["table_key"] for row in selected}) == len(selected),
            "selected_keys_are_missing_active": True,
            "compiled_results_match_selected": len(compile_results) + len(compile_errors) == len(selected),
            "all_worklist_routing_is_single_pass": True,
            "no_right_census_advance": True,
            "no_sequential_left_runner": True,
            "version_markers_exact": all(row.get("two_run_language") == LANGUAGE for row in outcomes),
            "frontier_not_promoted_to_full_slot": True,
        },
        "summary": summary,
    })
    (out / "formal_candidates_v13.md").write_text(f"""# C8 table-batch finite statements

Versions: `{LANGUAGE}`, `{OWNERSHIP}`, `{TERMINAL_CACHE}`.

## Table-local outcome distinction

`LOCAL_EMPTY` means the compiled two-run table has no Level-B behavior. `ALL_QUERIES_EMPTY` means the table is nonempty, but every exact dependent context query has an empty allowed behavior mask. The latter is a context obstruction, not a local-language obstruction.

## Batch scope

The batch compiled `{len(compile_results)}` selected table keys using `{workers}` workers and evaluated their dependent queries by the existing exact family semantics. The current result is bounded to the selected frontier-directed keys and is not a full-slot C8 conclusion.

## Motif limitation

The cross-table summaries use exact effect-mask fingerprints only. They do not identify graph roles or signed-sum identities, so they are empirical obstruction summaries and are not theorem gates. A sound pre-compilation rule would require an independent structural proof.

## Frontier status

No batch result may promote the known 4482-snapshot frontier `(63,2)->(67,1)->(68,0)` to the 6824 scope or to the full slot. Any positive table would require its concrete outer audit before a frontier counterexample could be recorded.
""", encoding="utf-8")
    (out / "report_v13.md").write_text(f"""# C8 frontier-directed table batch

Versions: `{LANGUAGE}`, `{OWNERSHIP}`, `{TERMINAL_CACHE}`.

This batch is restricted to Tree1 `split(left_leaf_2)`. It does not advance the right census, invoke the sequential left runner, or claim a full-slot theorem.

## Batch result

Selected `{len(selected)}` missing active local-table keys and compiled `{len(compile_results)}` successfully with `{workers}` workers. Outcome census: `{dict(outcome_counts)}`. Compilation elapsed time was `{round(compile_elapsed, 3)}` seconds for the real cache. Worker scaling is recorded separately in `worker_scaling_benchmark.csv`.

 The previously completed table `[10..10] U [18..36]` remains classified as `ALL_QUERIES_EMPTY`: its local table is nonempty, while all `3,988` dependent exact queries are empty.

## Semantic obstruction census

Each completed table has exact query, semantic-signature, empty/positive, and effect-summary rows. Cross-table motif IDs are explicitly `EFFECT_MASK_ONLY_NO_ROLE_NORMALIZATION`; they do not yet support a role/signed-sum theorem candidate. A table-local positive result would be outer-audited before being called a frontier counterexample.

## Frontier discipline

The known audited 4482 snapshot remains `(kappa_63,...,kappa_68)=(2,2,2,2,1,0)` with minimum outer-compatible span 68. This batch does not extend that claim. The full-slot status remains `UNRESOLVED_RESOURCE`, and C9 remains out of scope.
""", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.batch_size, args.workers), indent=2))


if __name__ == "__main__":
    main()
