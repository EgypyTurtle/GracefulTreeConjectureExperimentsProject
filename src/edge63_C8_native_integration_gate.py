"""Run the native-to-Python global integration gates.

This gate is intentionally bounded to frozen golden witnesses.  It never
starts the 1056-key production manifest.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import struct
import tempfile
from pathlib import Path
from typing import Any

# Import the small harness helpers without duplicating the global semantics.
from edge63_C8_native_end_to_end import (
    CASE,
    SLOT,
    _collect_target_rows,
    _family_semantic,
    _outer_case,
    _parse_intervals,
    _read_json,
    _source_for_target,
)
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_native_bridge import read_native_table
from edge63_C8_native_geometry_cache import NativeCompiledGeometryCache


LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _family_key_from_payload(payload: dict[str, Any]) -> str:
    return str(payload["family_key"])


def _mixed_audit(root: Path, e2e: dict[str, Any], output: Path) -> dict[str, Any]:
    empty_intervals = tuple(tuple(int(value) for value in part) for part in e2e["empty_case"]["intervals"])
    bilateral_intervals = _parse_intervals(e2e["bilateral_case"]["family_key"] and json.dumps(
        json.loads(e2e["bilateral_case"]["family_key"])["intervals_b"]
    ))
    global_intervals = _parse_intervals(json.dumps(json.loads(e2e["global_case"]["family_key"])["intervals_b"]))
    targets = {empty_intervals, bilateral_intervals, global_intervals}
    buckets = _collect_target_rows(root, targets)
    golden = root / "native_engine_v1" / "native_tables" / "golden"
    cached_root = output / "native_tables"
    fresh_root = output / "mixed_fresh_native"
    if fresh_root.exists():
        shutil.rmtree(fresh_root)
    python_empty = _family_semantic(root, buckets[empty_intervals], CompiledTerminalPairIndex(root, CASE, SLOT))
    cached_native_outer = _outer_case(
        root,
        buckets[bilateral_intervals],
        ("345e9b3c3bfdeb1914b08bb0", 114, 0),
        cached_root,
    )
    fresh_native_outer = _outer_case(
        root,
        buckets[global_intervals],
        (str(json.loads((root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_bilateral_v1" / "first_global_compatible_pair.json").read_text(encoding="utf-8"))["group_id"]), 4, 0),
        fresh_root,
    )
    checks = {
        "python_cached_all_empty": python_empty["positive_queries"] == 0 and python_empty["empty_queries"] == python_empty["exact_queries"],
        "native_cached_bilateral": cached_native_outer["exact_equal"] and int(cached_native_outer["native"]["outer_edges"]) == 0,
        "native_fresh_global": fresh_native_outer["exact_equal"] and int(fresh_native_outer["native"]["outer_edges"]) == 1,
        "fresh_native_compilation_occurred": any(fresh_root.glob("*.bin")),
    }
    result = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "backends": {
            "all_empty": "python_cached",
            "bilateral": "native_cached",
            "global": "native_fresh",
        },
        "python_cached_all_empty": {key: value for key, value in python_empty.items() if key not in {"signatures", "effects"}},
        "native_cached_bilateral": cached_native_outer,
        "native_fresh_global": fresh_native_outer,
        **_versions(),
    }
    (output / "mixed_backend_differential.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=list), encoding="utf-8")
    return result


def _cache_reload_audit(root: Path, e2e: dict[str, Any], output: Path) -> dict[str, Any]:
    cache_root = output / "native_tables"
    target_intervals = [
        tuple(tuple(int(value) for value in part) for part in e2e["empty_case"]["intervals"]),
        _parse_intervals(json.dumps(json.loads(e2e["bilateral_case"]["family_key"])["intervals_b"])),
        _parse_intervals(json.dumps(json.loads(e2e["global_case"]["family_key"])["intervals_b"])),
    ]
    fresh = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=cache_root)
    first = [fresh.get(intervals, "terminal") for intervals in target_intervals]
    reloaded_cache = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=cache_root)
    second = [reloaded_cache.get(intervals, "terminal") for intervals in target_intervals]
    reload_checks = [first[index].checksum == second[index].checksum for index in range(len(first))]
    stale_path = output / "stale_format_test.bin"
    data = bytearray((cache_root / next(path.name for path in cache_root.glob("*.bin"))).read_bytes())
    data[8:12] = struct.pack("<I", 999)
    stale_path.write_bytes(data)
    stale_intervals = target_intervals[0]
    stale_rejected = NativeCompiledGeometryCache(root, CASE, SLOT, cache_root=output / "stale_reader")._read(stale_path, stale_intervals, "terminal") is None
    result = {
        "status": "PASS" if all(reload_checks) and reloaded_cache.reload_count == len(first) and stale_rejected else "FAIL",
        "cache_files": len(list(cache_root.glob("*.bin"))),
        "reload_count": reloaded_cache.reload_count,
        "checksum_equal": reload_checks,
        "stale_format_rejected": stale_rejected,
        "invalidated_format_version": 999,
        "versions": _versions(),
    }
    (output / "cache_reload_verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def run(root: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    e2e = _read_json(output / "golden_global_differential.json") if (output / "golden_global_differential.json").exists() else None
    if e2e is None or e2e.get("status") != "PASS":
        from edge63_C8_native_end_to_end import run as run_e2e
        e2e = run_e2e(root, output)
    mixed = _mixed_audit(root, e2e, output)
    reload = _cache_reload_audit(root, e2e, output)
    cert = _read_json(root / "native_engine_v1" / "certificates" / "batch_verification.json")
    checks = {
        "END_TO_END_GOLDEN_PASS": e2e.get("status") == "PASS",
        "MIXED_BACKEND_PASS": mixed.get("status") == "PASS",
        "CACHE_RELOAD_PASS": reload.get("status") == "PASS",
        "INDEPENDENT_CERTIFICATE_VERIFIER_PASS": cert.get("status") == "PASS",
        "production_not_started": not (root / "native_engine_v1" / "batch_runs" / "production_started.marker").exists(),
    }
    result = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "production_gate": "PRODUCTION_ALLOWED_AFTER_BOUNDED_PILOT_ONLY" if all(checks.values()) else "HOLD",
        "note": "This gate does not start the 1056-key production batch.",
        **_versions(),
    }
    (output / "integration_report.md").write_text(
        "# Native to Python end-to-end integration gate\n\n"
        f"Versions: `{LANGUAGE}`, `{OWNERSHIP}`, `{TERMINAL_CACHE}`.\n\n"
        "The native engine supplies only the `left_leaf_2` two-run geometry. "
        "The existing Python semantic, bilateral, outer-join, span, and certificate paths are reused unchanged.\n\n"
        + "\n".join(f"- `{key}`: `{value}`" for key, value in checks.items())
        + "\n\nProduction keys remain untouched until this gate passes and a bounded pilot is run.\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/end_to_end_gate"))
    args = parser.parse_args()
    result = run(args.root, args.output)
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
