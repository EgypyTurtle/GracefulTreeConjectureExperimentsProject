"""Run the native local-table engine against the frozen golden corpus."""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from edge63_C8_native_bridge import (
    LANGUAGE,
    OWNERSHIP,
    TERMINAL_CACHE,
    compare_geometry,
    read_native_table,
    run_native,
)


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _witness_valid(row: Any, intervals: tuple[tuple[int, int], ...]) -> bool:
    expected = sorted(value for start, end in intervals for value in range(start, end + 1))
    observed = sorted(abs(a - b) for a, b in zip(row.offsets, row.offsets[1:]))
    return observed == expected and len(row.offsets) == len(expected) + 1


def run(golden: Path, executable: Path, output: Path) -> dict[str, Any]:
    cases = _cases(golden / "expected_results.json")
    table_cases = [case for case in cases if "intervals" in case]
    rows = []
    with tempfile.TemporaryDirectory(prefix="c8_native_regression_") as temp:
        temp_root = Path(temp)
        for case in table_cases:
            intervals = tuple(tuple(int(value) for value in part) for part in case["intervals"])
            table_path = temp_root / f"{case['case_id']}.bin"
            started = time.perf_counter()
            try:
                table = run_native(executable, intervals, table_path)
                result = compare_geometry(table, intervals)
                witness_ok = all(_witness_valid(row, intervals) for row in table.records)
                expected = case["expected"]
                expected_count = expected.get("local_behavior_count")
                count_ok = expected_count is None or int(expected_count) == len(table.records)
                passed = bool(result["geometry_equal"] and result["witness_equal"] and result["versions_equal"] and witness_ok and count_ok)
                rows.append({
                    "case_id": case["case_id"],
                    "kind": case["kind"],
                    "intervals": intervals,
                    "native_count": len(table.records),
                    "expected_count": expected_count,
                    "geometry_equal": result["geometry_equal"],
                    "witness_equal": result["witness_equal"],
                    "witnesses_valid": witness_ok,
                    "count_equal": count_ok,
                    "seconds": round(time.perf_counter() - started, 6),
                    "status": "PASS" if passed else "FAIL",
                    **_versions(),
                })
            except Exception as exc:
                rows.append({
                    "case_id": case["case_id"],
                    "kind": case["kind"],
                    "status": "FAIL",
                    "error": repr(exc),
                    **_versions(),
                })
    passed = sum(row.get("status") == "PASS" for row in rows)
    result = {
        "corpus_version": "native-golden.v1",
        "cases_total": len(cases),
        "native_table_cases": len(rows),
        "native_table_cases_pass": passed,
        "native_table_cases_fail": len(rows) - passed,
        "golden_non_table_cases": len(cases) - len(rows),
        "geometry_level_required": True,
        "status": "PASS" if passed == len(rows) else "FAIL",
        "rows": rows,
        **_versions(),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "golden_regression.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "native_differential.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/golden_corpus"))
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/benchmarks"))
    args = parser.parse_args()
    result = run(args.golden, args.executable, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
