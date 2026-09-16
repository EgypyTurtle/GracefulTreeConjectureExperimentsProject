"""Resume-safe native batch plan for the remaining local-table keys.

This module intentionally supports planning and crash recovery first.  It does
not start the 1056-key production batch until the complete correctness gate is
explicitly recorded by a later run.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any


STATES = ("PENDING", "RUNNING", "COMPILED", "LOCAL_EMPTY", "SEMANTIC_DONE", "POSITIVE_FOUND", "ERROR")
VERSIONS = {"two_run_language": "C8.LevelB.v1", "allocation_dedup_version": "ownership.v2", "terminal_pair_cache_version": "corrected.v2"}


def _missing(base: Path) -> list[dict[str, str]]:
    manifest = {row["table_key"]: row for row in csv.DictReader((base / "table_completion_manifest.csv").open(encoding="utf-8"))}
    priority = []
    with (base / "frontier_table_priority.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            item = manifest.get(row["table_key"])
            if item and item.get("table_status") == "MISSING_LOCAL_TABLE":
                priority.append({**row, **{key: item.get(key, "") for key in ("intervals_a", "intervals_b", "table_key_payload")}})
    return priority


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["table_key", "status"]
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp = Path(name)
    try:
        with temp.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def init_plan(base: Path, output: Path) -> dict[str, Any]:
    rows = []
    for item in _missing(base):
        rows.append({"table_key": item["table_key"], "table_key_payload": item.get("table_key_payload", ""),
                     "intervals_b": item.get("intervals_b", ""), "priority_rank": item.get("priority_rank", ""),
                     "status": "PENDING", "output_path": "", "checksum": "", **VERSIONS})
    _atomic_csv(output / "batch_manifest.csv", rows)
    result = {"status": "PLAN_ONLY", "keys_total": len(rows), "pending": len(rows), "production_started": False, **VERSIONS}
    (output / "progress_native_v1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def recover(path: Path) -> dict[str, Any]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    reset = 0
    for row in rows:
        if row.get("status") == "RUNNING":
            output = Path(row.get("output_path", ""))
            if not output.exists() or not row.get("checksum"):
                row["status"] = "PENDING"
                reset += 1
    _atomic_csv(path, rows)
    return {"status": "PASS", "running_reset_to_pending": reset}


def self_test(output: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="c8_native_resume_") as temp:
        path = Path(temp) / "manifest.csv"
        rows = [{"table_key": "synthetic", "status": "RUNNING", "output_path": str(Path(temp) / "missing.bin"), "checksum": "", **VERSIONS}]
        _atomic_csv(path, rows)
        result = recover(path)
        result["recovered_state"] = next(csv.DictReader(path.open(encoding="utf-8")))["status"]
        result["test_pass"] = result["recovered_state"] == "PENDING"
    output.mkdir(parents=True, exist_ok=True)
    (output / "resume_recovery_test.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("plan", "recover", "self-test"), required=True)
    parser.add_argument("--base", type=Path, default=Path("results/edge63_two_interval_gate2/tree1_C8/left_leaf_2_exact_v3/frontier_directed_v1"))
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/batch_runs"))
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()
    if args.mode == "plan": result = init_plan(args.base, args.output)
    elif args.mode == "recover": result = recover(args.manifest or (args.output / "batch_manifest.csv"))
    else: result = self_test(args.output)
    print(json.dumps(result, indent=2))
    if args.mode == "self-test" and not result.get("test_pass"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
