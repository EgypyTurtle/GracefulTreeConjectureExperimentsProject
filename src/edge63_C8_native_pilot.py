"""Run the bounded 64-key native C8 production pilot after integration gates."""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from edge63_C8_native_geometry_cache import NativeCompiledGeometryCache
from edge63_C8_native_pilot_verify import run as verify_pilot
from edge63_C8_table_batch_scheduler import (
    CASE,
    SLOT,
    _evaluate_table,
    _route_worklist,
)
from edge63_C8_native_batch_scheduler import _atomic_csv, recover


LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
PILOT_SIZE = 64


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _read_pending(root: Path) -> list[dict[str, str]]:
    path = root / "native_engine_v1" / "batch_runs" / "batch_manifest.csv"
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") == "PENDING":
                rows.append(row)
            if len(rows) == PILOT_SIZE:
                break
    if len(rows) != PILOT_SIZE:
        raise RuntimeError(f"expected {PILOT_SIZE} pending keys, found {len(rows)}")
    if len({row["table_key"] for row in rows}) != PILOT_SIZE:
        raise AssertionError("pilot keys are not unique")
    return rows


def _compile_worker(payload: tuple[str, str, str, str, str]) -> dict[str, Any]:
    root_text, table_key, table_key_payload, intervals_b, output_text = payload
    root = Path(root_text)
    output = Path(output_text)
    intervals = tuple(tuple(int(value) for value in part) for part in json.loads(intervals_b))
    started = time.perf_counter()
    cache = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=output / "native_tables")
    compiled = cache.get(intervals, "terminal")
    row = cache.manifest_row(compiled)
    return {
        "table_key": table_key,
        "table_key_payload": table_key_payload,
        "intervals_b": intervals_b,
        "status": "COMPILED",
        "compile_seconds": round(time.perf_counter() - started, 6),
        "intrinsic_compile_seconds": round(compiled.compile_seconds, 6),
        "behavior_count": len(compiled.records),
        "cache_bytes": row["cache_bytes"],
        "checksum": compiled.checksum,
        "output_path": str(cache._path(intervals, "terminal")),
        "backend": "native",
        **_versions(),
    }


def _working_set() -> int | None:
    try:
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("pages", ctypes.c_size_t), ("peak", ctypes.c_size_t), ("working", ctypes.c_size_t), ("quota_peak", ctypes.c_size_t), ("quota", ctypes.c_size_t), ("pool_nonpaged", ctypes.c_size_t), ("pool_paged", ctypes.c_size_t), ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t)]
        process = ctypes.windll.kernel32.GetCurrentProcess()
        counters = Counters()
        if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), ctypes.sizeof(counters)):
            return int(counters.working)
    except (AttributeError, OSError, TypeError):
        return None
    return None


def _make_cert_manifest(output: Path, selected: list[dict[str, str]], outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in outcomes:
        key = result["table_key"]
        effects_path = output / "table_results" / f"{key}_effects.csv"
        behavior_count: dict[str, int] = {}
        if effects_path.exists():
            with effects_path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    behavior_count[row["family_id"]] = int(row.get("behavior_count", 0) or 0)
        signature_path = output / "table_results" / f"{key}_semantic_signatures.csv"
        if not signature_path.exists():
            continue
        with signature_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                allowed = int(row.get("allowed_count", 0) or 0)
                cert_type = "POSITIVE_BEHAVIOR_MASK" if allowed else ("FAMILY_BEHAVIOR_EMPTY" if behavior_count.get(row.get("family_id", ""), 0) == 0 else "FULL_MASK_EMPTY")
                rows.append({
                    "table_key": key,
                    "family_id": row.get("family_id", ""),
                    "semantic_signature_id": row.get("semantic_signature_id", ""),
                    "allowed_count": allowed,
                    "blocked_mask_hex": row.get("blocked_mask_hex", "0x0"),
                    "allowed_mask_hex": row.get("allowed_mask_hex", "0x0"),
                    "certificate_type": cert_type,
                    "certificate_ref": str(signature_path),
                    **_versions(),
                })
    _write_csv(output / "certificate_manifest.csv", rows)
    return rows


def _resume_test(output: Path, selected: list[dict[str, str]], compile_rows: list[dict[str, Any]]) -> dict[str, Any]:
    test_dir = output / "resume_test"
    test_dir.mkdir(parents=True, exist_ok=True)
    path = test_dir / "manifest.csv"
    rows = []
    for index, item in enumerate(selected[:3]):
        compiled = compile_rows[index]
        rows.append({
            "table_key": item["table_key"],
            "status": "COMPILED" if index == 0 else ("RUNNING" if index == 1 else "PENDING"),
            "output_path": compiled.get("output_path", "") if index == 0 else str(test_dir / "missing.bin"),
            "checksum": compiled.get("checksum", "") if index == 0 else "",
            **_versions(),
        })
    _atomic_csv(path, rows)
    recovered = recover(path)
    after = list(csv.DictReader(path.open(encoding="utf-8")))
    checks = {
        "completed_preserved": after[0]["status"] == "COMPILED" and after[0]["checksum"] == rows[0]["checksum"],
        "running_reset": after[1]["status"] == "PENDING",
        "pending_preserved": after[2]["status"] == "PENDING",
        "unique_keys": len({row["table_key"] for row in after}) == 3,
    }
    result = {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "recovery": recovered, **_versions()}
    (output / "resume_test.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run(root: Path, output: Path, workers: int = 2) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    selected = _read_pending(root)
    _write_csv(output / "pilot_manifest.csv", [{**row, "pilot_status": "PENDING", "backend": "native", **_versions()} for row in selected])
    payloads = [(str(root), row["table_key"], row["table_key_payload"], row["intervals_b"], str(output)) for row in selected]
    compile_started = time.perf_counter()
    compile_errors: list[dict[str, Any]] = []
    if workers == 1:
        compile_rows = [_compile_worker(payload) for payload in payloads]
    else:
        compile_rows = []
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_compile_worker, payload) for payload in payloads]
            for item, future in zip(selected, futures):
                try:
                    compile_rows.append(future.result())
                except Exception as exc:
                    compile_errors.append({"table_key": item["table_key"], "status": "ERROR", "error": repr(exc), **_versions()})
    compile_elapsed = time.perf_counter() - compile_started
    compile_by_key = {row["table_key"]: row for row in compile_rows}
    tables = _route_worklist(root, selected)
    outcomes: list[dict[str, Any]] = []
    memory_rows: list[dict[str, Any]] = []
    eval_started = time.perf_counter()
    cache = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=output / "native_tables")
    for item in selected:
        key = item["table_key"]
        if key not in compile_by_key:
            outcomes.append({"table_key": key, "outcome": "ERROR", "error": "native compilation failed", **_versions()})
            continue
        before = _working_set()
        result = _evaluate_table(root, output, tables[key], compile_by_key[key], geometry_cache=cache)
        after = _working_set()
        result["backend"] = "native"
        outcomes.append(result)
        memory_rows.append({
            "table_key": key,
            "working_set_before_bytes": before,
            "working_set_after_bytes": after,
            "cache_bytes": compile_by_key[key].get("cache_bytes"),
            "behavior_count": compile_by_key[key].get("behavior_count"),
            **_versions(),
        })
    eval_elapsed = time.perf_counter() - eval_started
    _write_csv(output / "key_results.csv", [{
        "table_key": row["table_key"],
        "table_key_payload": next(item["table_key_payload"] for item in selected if item["table_key"] == row["table_key"]),
        "intervals_b": next(item["intervals_b"] for item in selected if item["table_key"] == row["table_key"]),
        "distinct_exact_queries": row.get("distinct_exact_queries", 0),
        "positive_queries": row.get("positive_queries", 0),
        "local_behavior_count": row.get("local_behavior_count", compile_by_key.get(row["table_key"], {}).get("behavior_count", 0)),
        "outer_edges": row.get("outer_edges", 0),
        "outcome": row.get("outcome", "ERROR"),
        "compile_seconds": compile_by_key.get(row["table_key"], {}).get("compile_seconds", ""),
        "elapsed_seconds": row.get("elapsed_seconds", ""),
        **_versions(),
    } for row in outcomes])
    outcome_by_key = {row["table_key"]: row.get("outcome", "ERROR") for row in outcomes}
    _write_csv(output / "pilot_manifest.csv", [{
        **row,
        "pilot_status": outcome_by_key.get(row["table_key"], "ERROR"),
        "backend": "native",
        **_versions(),
    } for row in selected])
    cert_rows = _make_cert_manifest(output, selected, outcomes)
    resume = _resume_test(output, selected, compile_rows) if not compile_errors else {"status": "SKIPPED_COMPILE_ERRORS"}
    profile = {
        "status": "PASS" if not compile_errors else "ERROR",
        "keys_requested": len(selected),
        "keys_compiled": len(compile_rows),
        "compile_errors": compile_errors,
        "workers": workers,
        "compile_elapsed_seconds": compile_elapsed,
        "evaluation_elapsed_seconds": eval_elapsed,
        "end_to_end_elapsed_seconds": compile_elapsed + eval_elapsed,
        "tables_per_second_compile": len(compile_rows) / compile_elapsed if compile_elapsed else None,
        "tables_per_second_end_to_end": len(outcomes) / (compile_elapsed + eval_elapsed) if compile_elapsed + eval_elapsed else None,
        "local_compilation_share": compile_elapsed / (compile_elapsed + eval_elapsed) if compile_elapsed + eval_elapsed else None,
        "semantic_queries": sum(int(row.get("distinct_exact_queries", 0) or 0) for row in outcomes),
        "certificate_rows": len(cert_rows),
        "native_cache_files": len(list((output / "native_tables").glob("*.bin"))),
        "memory_scope": "parent evaluation process; worker peak memory covered by native benchmark",
        **_versions(),
    }
    (output / "pilot_profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")
    _write_csv(output / "memory_profile.csv", memory_rows)
    verification = verify_pilot(root, output) if not compile_errors else {"status": "SKIPPED_COMPILE_ERRORS"}
    result = {
        "status": "PASS" if not compile_errors and resume.get("status") == "PASS" and verification.get("status") == "PASS" else "FAIL",
        "keys": len(selected),
        "outcomes": {value: sum(row.get("outcome") == value for row in outcomes) for value in sorted({row.get("outcome", "ERROR") for row in outcomes})},
        "compile_errors": compile_errors,
        "resume": resume,
        "verification": verification,
        "profile": profile,
        "frontier_counterexamples": [row["table_key"] for row in outcomes if row.get("outcome") in {"SAT_SPAN63", "FRONTIER_COUNTEREXAMPLE_LE67"}],
        **_versions(),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/production_pilot_64"))
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    result = run(args.root, args.output, max(1, min(4, args.workers)))
    print(json.dumps({"status": result["status"], "keys": result["keys"], "outcomes": result["outcomes"], "verification": result["verification"]}, indent=2, ensure_ascii=False))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
