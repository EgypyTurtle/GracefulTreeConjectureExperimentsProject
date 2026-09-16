"""Resume-safe full production search for Tree1 C8 left_leaf_2.

This module keeps the existing Python global semantics and replaces only the
local two-run table backend with the verified native backend.  Production is
checkpointed in 64-key chunks, while the right-support universe is routed
once for the fixed 1056-key manifest.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from edge63_C8_collision_signature import _process_family
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_native_geometry_cache import NativeCompiledGeometryCache
from edge63_C8_native_pilot import _compile_worker, _make_cert_manifest
from edge63_C8_native_pilot_verify import _recompute_table
from edge63_C8_native_batch_scheduler import _atomic_csv
from edge63_C8_table_batch_scheduler import CASE, SLOT, _evaluate_table, _route_worklist
from edge63_C8_two_run_cache import PersistentTwoRunCache


LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
VERSIONS = {
    "two_run_language": LANGUAGE,
    "allocation_dedup_version": OWNERSHIP,
    "terminal_pair_cache_version": TERMINAL_CACHE,
}
CLOSED_STATUSES = {
    "LOCAL_EMPTY",
    "ALL_QUERIES_EMPTY",
    "HAS_BILATERAL_OUTER_ZERO",
    "HAS_GLOBAL_COMPATIBLE",
}
CHUNK_SIZE = 64
BASELINE_KAPPA = {63: 2, 64: 2, 65: 2, 66: 2, 67: 1, 68: 0}
RESULT_FIELDS = (
    "table_key", "table_key_payload", "intervals_b", "priority_rank", "outcome", "production_status",
    "rows_seen", "dependent_families", "distinct_exact_queries", "local_behavior_count", "semantic_signatures",
    "empty_queries", "positive_queries", "outer_audited_contexts", "outer_edges", "best_pre_outer_span",
    "best_outer_compatible_span", "minimum_kappa", "frontier_counterexamples_le67", "elapsed_seconds",
    "compile_seconds", "cache_bytes", "checksum", "error", "backend", *VERSIONS,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def _versions() -> dict[str, str]:
    return dict(VERSIONS)


def _source_manifest(root: Path) -> tuple[Path, list[dict[str, str]], str]:
    path = root / "native_engine_v1" / "batch_runs" / "batch_manifest.csv"
    raw = path.read_bytes()
    rows = _read_csv(path)
    if len(rows) != 1056 or len({row["table_key"] for row in rows}) != 1056:
        raise RuntimeError(f"expected immutable 1056-key manifest, got {len(rows)}")
    if any(row.get("status") != "PENDING" for row in rows):
        raise RuntimeError("source production manifest is not PENDING-only")
    if any({row.get(key) for key in VERSIONS} != {VERSIONS[key]} for row in rows for key in []):
        raise RuntimeError("unreachable version check")
    for row in rows:
        for key, value in VERSIONS.items():
            if row.get(key) != value:
                raise RuntimeError(f"source manifest version mismatch: {key}")
    return path, rows, hashlib.sha256(raw).hexdigest()


def _ensure_immutable_manifest(out: Path, source_path: Path, rows: list[dict[str, str]], source_sha256: str) -> None:
    path = out / "production_1056_manifest.json"
    payload = {
        "manifest_type": "IMMUTABLE_PRODUCTION_UNIVERSE",
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "keys_total": len(rows),
        "rows": rows,
        **_versions(),
    }
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("source_sha256") != source_sha256 or [r["table_key"] for r in existing.get("rows", [])] != [r["table_key"] for r in rows]:
            raise RuntimeError("immutable production manifest mismatch")
        return
    _atomic_json(path, payload)


def _ensure_runtime_manifest(out: Path, rows: list[dict[str, str]], *, retry_errors: bool = False) -> Path:
    path = out / "production_manifest.csv"
    if not path.exists():
        runtime = [{**row, "status": "PENDING", "production_output_path": "", "last_error": "", **_versions()} for row in rows]
        _atomic_csv(path, runtime)
        return path
    runtime = _read_csv(path)
    expected = {row["table_key"] for row in rows}
    if {row["table_key"] for row in runtime} != expected:
        raise RuntimeError("runtime production manifest key set mismatch")
    changed = False
    for row in runtime:
        if row.get("status") == "RUNNING":
            row["status"] = "PENDING"
            changed = True
        elif retry_errors and row.get("status") == "ERROR":
            row["status"] = "PENDING"
            row["last_error"] = ""
            changed = True
        for key, value in VERSIONS.items():
            if row.get(key) != value:
                raise RuntimeError(f"runtime manifest version mismatch: {key}")
    if changed:
        _atomic_csv(path, runtime)
    return path


def _closed_outcome(outcome: str) -> str:
    if outcome in {"SAT_SPAN63", "HAS_OUTER_POSITIVE_GT67", "FRONTIER_COUNTEREXAMPLE_LE67"}:
        return "HAS_GLOBAL_COMPATIBLE"
    return outcome


def _summary_row(result: dict[str, Any], item: dict[str, str], compile_row: dict[str, Any]) -> dict[str, Any]:
    outer_rows = result.get("outer_rows", [])
    outer_spans = [int(row["minimum_outer_edge_span"]) for row in outer_rows if row.get("minimum_outer_edge_span") not in {None, ""} and int(row.get("outer_edges", 0) or 0) > 0]
    kappas = [int(row["kappa_outer"]) for row in outer_rows if row.get("kappa_outer") not in {None, ""}]
    return {
        "table_key": item["table_key"],
        "table_key_payload": item.get("table_key_payload", ""),
        "intervals_b": item.get("intervals_b", ""),
        "priority_rank": item.get("priority_rank", ""),
        "outcome": result.get("outcome", "ERROR"),
        "production_status": _closed_outcome(result.get("outcome", "ERROR")) if result.get("outcome") != "ERROR" else "ERROR",
        "rows_seen": result.get("rows_seen", 0),
        "dependent_families": result.get("dependent_families", 0),
        "distinct_exact_queries": result.get("distinct_exact_queries", 0),
        "local_behavior_count": result.get("local_behavior_count", 0),
        "semantic_signatures": result.get("semantic_signatures", 0),
        "empty_queries": result.get("empty_queries", 0),
        "positive_queries": result.get("positive_queries", 0),
        "outer_audited_contexts": result.get("outer_audited_contexts", 0),
        "outer_edges": result.get("outer_edges", 0),
        "best_pre_outer_span": min((int(row["minimum_pre_outer_span"]) for row in outer_rows if row.get("minimum_pre_outer_span") not in {None, ""}), default=""),
        "best_outer_compatible_span": min(outer_spans, default=""),
        "minimum_kappa": min(kappas, default=""),
        "frontier_counterexamples_le67": result.get("frontier_counterexamples_le67", 0),
        "elapsed_seconds": result.get("elapsed_seconds", ""),
        "compile_seconds": compile_row.get("compile_seconds", ""),
        "cache_bytes": compile_row.get("cache_bytes", ""),
        "checksum": compile_row.get("checksum", ""),
        "error": result.get("error", ""),
        "backend": "native",
        **_versions(),
    }


def _write_results(out: Path, rows_by_key: dict[str, dict[str, Any]]) -> None:
    rows = sorted(rows_by_key.values(), key=lambda row: (int(row.get("priority_rank") or 10**9), row["table_key"]))
    rows = [{field: row.get(field, "") for field in RESULT_FIELDS} for row in rows]
    _atomic_csv(out / "key_results.csv", rows)
    performance = [{key: row.get(key, "") for key in ("table_key", "priority_rank", "outcome", "production_status", "compile_seconds", "elapsed_seconds", "distinct_exact_queries", "local_behavior_count", "cache_bytes", "backend", *VERSIONS)} for row in rows]
    _atomic_csv(out / "key_performance.csv", performance)
    if rows:
        elapsed = sorted(float(row["elapsed_seconds"]) for row in rows if row.get("elapsed_seconds") not in {None, ""})
        if elapsed:
            p95 = elapsed[max(0, int(len(elapsed) * 0.95) - 1)]
            heavy = [row for row in rows if float(row.get("elapsed_seconds") or 0) >= p95]
    _atomic_csv(out / "heavy_keys.csv", heavy)


def _load_result_rows(out: Path, runtime_rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    result_path = out / "key_results.csv"
    if result_path.exists():
        for row in _read_csv(result_path):
            rows_by_key[row["table_key"]] = row
    for item in runtime_rows:
        key = item["table_key"]
        if item.get("status") not in CLOSED_STATUSES or key in rows_by_key and rows_by_key[key].get("production_status") in CLOSED_STATUSES:
            continue
        summary_path = out / "table_results" / f"{key}.json"
        if not summary_path.exists():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        rows_by_key[key] = _summary_row(summary, item, summary.get("compile", {}))
    return rows_by_key


def _update_frontier(out: Path, completed: int) -> dict[str, Any]:
    frontier = dict(BASELINE_KAPPA)
    best_outer = None
    for path in (out / "table_results").glob("*_outer_audit.csv"):
        for row in _read_csv(path):
            matrix_text = row.get("matrix", "")
            if matrix_text:
                try:
                    matrix = json.loads(matrix_text)
                except json.JSONDecodeError:
                    try:
                        matrix = ast.literal_eval(matrix_text)
                    except (SyntaxError, ValueError):
                        matrix = []
                for cell in matrix if isinstance(matrix, list) else []:
                    try:
                        span = int(cell["pre_outer_span"])
                        kappa = int(cell["intersection_size"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    for limit in frontier:
                        if span <= limit:
                            frontier[limit] = min(frontier[limit], kappa)
            edge_span = row.get("minimum_outer_edge_span")
            if edge_span not in {None, ""} and int(row.get("outer_edges", 0) or 0) > 0:
                best_outer = min(best_outer or int(edge_span), int(edge_span))
    payload = {
        "checkpoint": completed,
        "scope": "audited historical baseline plus closed production keys",
        "kappa_min": {str(key): value for key, value in frontier.items()},
        "best_outer_compatible_span": best_outer if best_outer is not None else 68,
        "full_slot_claim": False,
        **_versions(),
    }
    rows = _read_csv(out / "frontier_progress.csv") if (out / "frontier_progress.csv").exists() else []
    rows.append({"checkpoint": completed, **{f"kappa_min_{key}": value for key, value in frontier.items()}, "best_outer_compatible_span": payload["best_outer_compatible_span"], "full_slot_claim": False, **_versions()})
    _atomic_csv(out / "frontier_progress.csv", rows)
    _atomic_json(out / "frontier_current.json", payload)
    return payload


def _write_best_witness(out: Path) -> None:
    best: dict[str, Any] | None = None
    for path in (out / "table_results").glob("*_outer_audit.csv"):
        for row in _read_csv(path):
            if int(row.get("outer_edges", 0) or 0) <= 0 or row.get("minimum_outer_edge_span") in {None, ""}:
                continue
            candidate = {"table_result": path.with_suffix(".json").name, "outer_audit": path.name, "context": row, **_versions()}
            if best is None or int(row["minimum_outer_edge_span"]) < int(best["context"]["minimum_outer_edge_span"]):
                best = candidate
    _atomic_json(out / "best_global_witness.json", best or {"status": "NONE", **_versions()})


def _verify_checkpoint(root: Path, out: Path, tables: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    cache = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=out / "native_tables")
    for row in rows:
        key = row["table_key"]
        try:
            recomputed = _recompute_table(root, out, tables[key])
            if recomputed["recomputed_outcome"] != row["outcome"] or recomputed["exact_queries"] != int(row["distinct_exact_queries"] or 0) or recomputed["positive_queries"] != int(row["positive_queries"] or 0):
                mismatches.append({"table_key": key, "expected": row, "recomputed": recomputed})
            intervals = tuple(tuple(int(value) for value in part) for part in json.loads(row["intervals_b"]))
            loaded = cache.get(intervals, "terminal")
            if loaded.checksum != row.get("checksum"):
                mismatches.append({"table_key": key, "error": "native checksum mismatch"})
        except Exception as exc:
            mismatches.append({"table_key": key, "error": repr(exc)})
    result = {"status": "PASS" if not mismatches else "FAIL", "keys": len(rows), "mismatches": mismatches, **_versions()}
    checkpoint_rows = _read_csv(out / "checkpoint_verifications.csv") if (out / "checkpoint_verifications.csv").exists() else []
    checkpoint_rows.append({"checkpoint": max((int(row.get("completed_at_checkpoint", 0) or 0) for row in checkpoint_rows), default=0) + len(rows), "keys": len(rows), "status": result["status"], "mismatch_count": len(mismatches), **_versions()})
    _atomic_csv(out / "checkpoint_verifications.csv", checkpoint_rows)
    return result


def _progress(out: Path, manifest_rows: list[dict[str, str]], result_rows: dict[str, dict[str, Any]], checkpoint: int, status: str, frontier: dict[str, Any] | None = None) -> dict[str, Any]:
    counts = Counter(row.get("status", "PENDING") for row in manifest_rows)
    outcomes = Counter(row.get("outcome", "") for row in result_rows.values())
    payload = {
        "status": status,
        "checkpoint": checkpoint,
        "completed": sum(counts[value] for value in CLOSED_STATUSES),
        "pending": counts["PENDING"],
        "running": counts["RUNNING"],
        "errors": counts["ERROR"],
        "status_counts": dict(counts),
        "outcome_counts": dict(outcomes),
        "positive_queries": sum(int(row.get("positive_queries", 0) or 0) for row in result_rows.values()),
        "bilateral_contexts": sum(int(row.get("outer_audited_contexts", 0) or 0) for row in result_rows.values()),
        "outer_edges": sum(int(row.get("outer_edges", 0) or 0) for row in result_rows.values()),
        "best_known_global_compatible_span": (frontier or {}).get("best_outer_compatible_span", 68),
        "full_slot_claim": False,
        **_versions(),
    }
    _atomic_json(out / "production_progress.json", payload)
    return payload


def _coverage(root: Path, out: Path, source_rows: list[dict[str, str]], runtime_rows: list[dict[str, str]], result_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3" / "frontier_directed_v1"
    table_manifest = _read_csv(base / "table_completion_manifest.csv")
    expected_missing = {row["table_key"] for row in table_manifest if row.get("table_status") == "MISSING_LOCAL_TABLE"}
    production_keys = {row["table_key"] for row in source_rows}
    closed = all(row.get("status") in CLOSED_STATUSES for row in runtime_rows)
    table_partition = expected_missing == production_keys and len(table_manifest) == len({row["table_key"] for row in table_manifest})
    orphan_rows = 0
    expected_by_interval = {row["intervals_b"]: row["table_key"] for row in table_manifest}
    worklist = root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_right_support_v1" / "right_supported_residual_worklist_full.csv"
    with worklist.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pair = json.loads(row["left_two_run_interval_pair"])
            if json.dumps(pair[1], separators=(",", ":")) not in expected_by_interval:
                orphan_rows += 1
    coverage = {
        "status": "PASS" if closed and table_partition and orphan_rows == 0 else "FAIL",
        "production_keys_total": len(source_rows),
        "production_keys_closed": sum(row.get("status") in CLOSED_STATUSES for row in runtime_rows),
        "production_errors": sum(row.get("status") == "ERROR" for row in runtime_rows),
        "expected_table_keys": len(table_manifest),
        "historical_table_keys": len(table_manifest) - len(expected_missing),
        "missing_table_keys_expected": len(expected_missing),
        "table_partition_exact": table_partition,
        "worklist_orphan_interval_rows": orphan_rows,
        "allocation_worklist_present": worklist.exists(),
        "ownership_version": OWNERSHIP,
        "right_support_scope_is_partial": True,
        "semantic_history_requires_merge": True,
        "full_slot_claim": False,
        **_versions(),
    }
    _atomic_json(out / "full_slot_coverage.json", coverage)
    return coverage


def run(root: Path, out: Path, workers: int = 2, chunk_size: int = CHUNK_SIZE, *, retry_errors: bool = False) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    source_path, source_rows, source_sha256 = _source_manifest(root)
    _ensure_immutable_manifest(out, source_path, source_rows, source_sha256)
    manifest_path = _ensure_runtime_manifest(out, source_rows, retry_errors=retry_errors)
    runtime_rows = _read_csv(manifest_path)
    selected = [row for row in runtime_rows if row.get("status") == "PENDING"]
    result_rows = _load_result_rows(out, runtime_rows)
    if not selected:
        coverage = _coverage(root, out, source_rows, runtime_rows, result_rows)
        return {"status": "ALREADY_COMPLETE", "coverage": coverage, **_versions()}

    # Route the fixed worklist once; later checkpoints only operate on table data
    # already partitioned in memory.
    tables = _route_worklist(root, selected)
    cache = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=out / "native_tables")
    stop_event: dict[str, Any] | None = None
    checkpoint = sum(row.get("status") in CLOSED_STATUSES for row in runtime_rows)
    for start in range(0, len(selected), chunk_size):
        chunk = selected[start:start + chunk_size]
        runtime_rows = _read_csv(manifest_path)
        by_key = {row["table_key"]: row for row in runtime_rows}
        for item in chunk:
            by_key[item["table_key"]]["status"] = "RUNNING"
            by_key[item["table_key"]]["last_error"] = ""
        runtime_rows = list(by_key.values())
        _atomic_csv(manifest_path, runtime_rows)

        payloads = [(str(root), item["table_key"], item["table_key_payload"], item["intervals_b"], str(out)) for item in chunk]
        compile_rows: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        started = time.perf_counter()
        with ProcessPoolExecutor(max_workers=max(1, min(4, workers))) as pool:
            future_by_key = {pool.submit(_compile_worker, payload): payload[1] for payload in payloads}
            for future in as_completed(future_by_key):
                key = future_by_key[future]
                try:
                    compile_rows[key] = future.result()
                except Exception as exc:
                    errors[key] = repr(exc)

        current_summaries: list[dict[str, Any]] = []
        for item in chunk:
            key = item["table_key"]
            if key in errors:
                summary = {"table_key": key, "outcome": "ERROR", "production_status": "ERROR", "error": errors[key], **_versions()}
                current_summaries.append(summary)
                continue
            try:
                result = _evaluate_table(root, out, tables[key], compile_rows[key], geometry_cache=cache)
                summary = _summary_row(result, item, compile_rows[key])
                current_summaries.append(summary)
                if result.get("outcome") in {"SAT_SPAN63", "FRONTIER_COUNTEREXAMPLE_LE67"}:
                    stop_event = {"table_key": key, "outcome": result.get("outcome"), "summary": summary}
                    break
            except Exception as exc:
                current_summaries.append({"table_key": key, "outcome": "ERROR", "production_status": "ERROR", "error": repr(exc), **_versions()})
                errors[key] = repr(exc)

        processed_keys = {summary["table_key"] for summary in current_summaries}
        if stop_event:
            for item in chunk:
                if item["table_key"] not in processed_keys:
                    by_key[item["table_key"]]["status"] = "PENDING"

        for summary in current_summaries:
            result_rows[summary["table_key"]] = summary
            row = by_key[summary["table_key"]]
            row["status"] = summary.get("production_status", "ERROR")
            row["production_output_path"] = str(out / "table_results" / f"{summary['table_key']}.json")
            row["last_error"] = summary.get("error", "")
            row["checksum"] = summary.get("checksum", "")
        _atomic_csv(manifest_path, list(by_key.values()))
        runtime_rows = list(by_key.values())
        _write_results(out, result_rows)
        closed_outcomes = list(result_rows.values())
        _make_cert_manifest(out, source_rows, closed_outcomes)
        checkpoint += len(current_summaries)
        frontier = _update_frontier(out, checkpoint)
        _write_best_witness(out)
        checkpoint_rows = [row for row in current_summaries if row.get("production_status") != "ERROR"]
        verification = _verify_checkpoint(root, out, tables, checkpoint_rows)
        _progress(out, runtime_rows, result_rows, checkpoint, "PRODUCTION_PAUSED_VERIFICATION_FAILURE" if verification["status"] != "PASS" else ("FRONTIER_BREAKTHROUGH" if stop_event else "RUNNING"), frontier)
        _atomic_json(out / f"checkpoint_{checkpoint:04d}.json", {"checkpoint": checkpoint, "chunk_start": start, "chunk_size": len(chunk), "compile_stage_seconds": round(time.perf_counter() - started, 6), "verification": verification, "frontier": frontier, **_versions()})
        if verification["status"] != "PASS":
            raise RuntimeError(f"production checkpoint verification failed: {verification}")
        if errors:
            raise RuntimeError(f"production compile/evaluation errors: {errors}")
        if stop_event:
            _atomic_json(out / "frontier_counterexample.json", {"status": "FOUND", **stop_event, **_versions()})
            break

    runtime_rows = _read_csv(manifest_path)
    coverage = _coverage(root, out, source_rows, runtime_rows, result_rows)
    counts = Counter(row.get("status", "PENDING") for row in runtime_rows)
    if stop_event:
        status = "FRONTIER_BREAKTHROUGH"
    elif counts["ERROR"]:
        status = "ERROR"
    elif counts["PENDING"] or counts["RUNNING"]:
        status = "UNRESOLVED_RESOURCE"
    else:
        status = "FULL_PRODUCTION_COMPLETE"
    _progress(out, runtime_rows, result_rows, checkpoint, status, _update_frontier(out, checkpoint))
    return {"status": status, "checkpoint": checkpoint, "counts": dict(counts), "coverage": coverage, "frontier_counterexample": stop_event, **_versions()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/production_full_v1"))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--retry-errors", action="store_true")
    args = parser.parse_args()
    result = run(args.root, args.output, workers=max(1, min(4, args.workers)), chunk_size=max(1, args.chunk_size), retry_errors=args.retry_errors)
    print(json.dumps({key: result.get(key) for key in ("status", "checkpoint", "counts", "coverage", "frontier_counterexample")}, indent=2, ensure_ascii=False))
    if result["status"] in {"ERROR", "FRONTIER_BREAKTHROUGH"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
