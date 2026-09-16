"""Persist native tables for the golden corpus and emit a manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from edge63_C8_native_bridge import read_native_table, run_native


def run(golden: Path, executable: Path, output: Path) -> dict[str, int | str]:
    cases = json.loads((golden / "expected_results.json").read_text(encoding="utf-8"))["cases"]
    rows = []
    target = output / "golden"
    target.mkdir(parents=True, exist_ok=True)
    for case in cases:
        if "intervals" not in case:
            continue
        intervals = tuple(tuple(int(value) for value in part) for part in case["intervals"])
        path = target / f"{case['case_id']}.bin"
        table = run_native(executable, intervals, path)
        rows.append({
            "case_id": case["case_id"],
            "table_path": str(path),
            "intervals": json.dumps(intervals, separators=(",", ":")),
            "behavior_count": len(table.records),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "status": "PASS",
            "two_run_language": table.language,
            "allocation_dedup_version": table.ownership,
            "terminal_pair_cache_version": table.terminal_cache,
        })
    with (output / "native_table_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = {"status": "PASS", "tables": len(rows), "records": sum(int(row["behavior_count"]) for row in rows)}
    (output / "native_table_compile_corpus.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/golden_corpus"))
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/native_tables"))
    args = parser.parse_args()
    result = run(args.golden, args.executable, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
