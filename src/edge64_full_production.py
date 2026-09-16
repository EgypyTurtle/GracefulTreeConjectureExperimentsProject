"""Resumable full edge64 production runner.

This module orchestrates the already-verified edge64 cascade.  It does not
change case generation or solver semantics; it only streams the frozen case
manifest through the existing ``edge64_baseline.run_one`` worker.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge64_baseline import MANIFEST_FIELDS, EXPECTED_EDGE64_CASES, iter_edge64_rows, run_one  # noqa: E402


READINESS = ROOT / "results" / "edge64_production_readiness_v1"
BASE = ROOT / "results" / "edge64_baseline_v1"
OUT = ROOT / "results" / "edge64_full_production_v1"
CASE_MANIFEST = BASE / "edge64_case_manifest.csv"
FULL_MANIFEST = OUT / "edge64_full_production_manifest.json"
WORKERS = 2
BATCH_SIZE = 512
CHECKPOINT_ATTEMPTS = 100_000
# Base allowance for one independent-verification child, scaled by certificate
# count.  A measured checkpoint of ~99k certificates verifies in about 4s.
VERIFY_TIMEOUT_SECONDS = 600.0
# Optional streaming progress log, set from --log-file.  Each batch appends one
# line, so an external watchdog can distinguish "slow" from "wedged".
HEARTBEAT_PATH: str | None = None

STAGES = (
    ("compressed_0.5s", "compressed", 0.5),
    ("compressed_1s", "compressed", 1.0),
    ("compressed_2s", "compressed", 2.0),
    ("compressed_5s", "compressed", 5.0),
    ("diff_1s", "diff", 1.0),
    ("tension_1s", "tension", 1.0),
    ("hybrid_1s", "hybrid", 1.0),
    ("branch_1s", "branch", 1.0),
    ("compressed_30s_fallback", "compressed", 30.0),
)

RESULT_FIELDS = [
    "case_id",
    "stage",
    "method",
    "budget_seconds",
    "status",
    "solved",
    "strategy",
    "nodes",
    "backtracks",
    "elapsed_seconds",
    "error",
    "labels",
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_id_hash(path: Path) -> tuple[int, str]:
    count = 0
    digest = hashlib.sha256()
    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            count += 1
            digest.update(row["case_id"].encode("ascii"))
            digest.update(b"\n")
    return count, digest.hexdigest()


def build_immutable_manifest() -> dict[str, object]:
    OUT.mkdir(parents=True, exist_ok=True)
    count, id_hash = manifest_id_hash(CASE_MANIFEST)
    csv_hash = sha256_file(CASE_MANIFEST)
    meta = {
        "format": "edge64-full-production-manifest-v1",
        "edge_count": 64,
        "expected_cases": EXPECTED_EDGE64_CASES,
        "case_count": count,
        "case_manifest_csv": str(CASE_MANIFEST),
        "case_manifest_sha256": csv_hash,
        "canonical_case_id_sha256": id_hash,
        "initial_status": "PENDING",
        "cascade_config": str(READINESS / "edge64_production_cascade_v1.json"),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if count != EXPECTED_EDGE64_CASES:
        raise RuntimeError(f"case manifest count mismatch: {count} != {EXPECTED_EDGE64_CASES}")
    existing_meta = OUT / "edge64_full_production_manifest.meta.json"
    if FULL_MANIFEST.exists() and existing_meta.exists():
        prior = read_json(existing_meta)
        if prior.get("case_manifest_sha256") != csv_hash or prior.get("canonical_case_id_sha256") != id_hash:
            raise RuntimeError("immutable production manifest does not match the frozen case manifest")
        return prior

    # Keep the requested JSON manifest valid while streaming records, so the
    # 10M-case universe never has to be materialized in Python memory.
    tmp = FULL_MANIFEST.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as out:
        out.write("{\"format\":\"edge64-full-production-manifest-v1\",\"metadata\":")
        out.write(json.dumps(meta, separators=(",", ":")))
        out.write(",\"cases\":[")
        first = True
        with CASE_MANIFEST.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                record = {
                    "case_id": row["case_id"],
                    "family_type": row["skeleton"],
                    "tree_parameters": {
                        key: row[key]
                        for key in (
                            "edge_count",
                            "vertices",
                            "bridge_length",
                            "left_bridge",
                            "right_bridge",
                            "middle_leaf",
                            "terminal_lengths",
                            "branch_balance",
                            "bridge_profile",
                            "central_tail_parity",
                        )
                    },
                    "stratum": row["stratum"],
                    "initial_status": "PENDING",
                }
                if not first:
                    out.write(",")
                out.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")))
                first = False
        out.write("]}\n")
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, FULL_MANIFEST)
    atomic_json(existing_meta, meta)
    return meta


def worker(payload: tuple[str, str, float, str, int]) -> dict[str, object]:
    case_id, method, budget, cache_dir, seed = payload
    cache_path = str(Path(cache_dir) / f"production_extension_{method}_{os.getpid()}.sqlite3")
    return run_one(case_id, method, budget, cache_path, seed)


def input_rows(path: Path):
    with path.open("r", newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def stage_dir(stage: str) -> Path:
    directory = OUT / "case_results" / stage
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def batch_path(stage: str, start: int, end: int) -> Path:
    return stage_dir(stage) / f"batch_{start:09d}_{end:09d}.csv"


def pending_path(stage: str) -> Path:
    return OUT / "pending" / f"after_{stage}.csv"


def make_pending(stage: str, input_path: Path, batch_ranges: list[tuple[int, int, Path]]) -> tuple[int, int]:
    target = pending_path(stage)
    if target.exists():
        count = sum(1 for _ in input_rows(target))
        return count, 0
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    written = 0
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        with input_path.open("r", newline="", encoding="utf-8") as source:
            source_reader = csv.DictReader(source)
            for start, end, result_file in batch_ranges:
                result_rows = {row["case_id"]: row for row in read_result_rows(result_file)}
                for offset in range(start, end):
                    try:
                        row = next(source_reader)
                    except StopIteration as exc:
                        raise RuntimeError("input ended while rebuilding pending stage") from exc
                    result = result_rows[row["case_id"]]
                    if result.get("solved") != "1":
                        writer.writerow(row)
                        written += 1
    os.replace(tmp, target)
    return written, 0


def input_rows_slice(path: Path, start: int, end: int):
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if index < start:
                continue
            if index >= end:
                break
            yield row


def read_result_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verify_checkpoint(result_files: list[Path], checkpoint_name: str) -> dict[str, object]:
    verification_dir = OUT / "verification"
    verification_dir.mkdir(parents=True, exist_ok=True)
    cert_path = verification_dir / f"{checkpoint_name}.csv"
    rows: list[dict[str, object]] = []
    for path in result_files:
        for row in read_result_rows(path):
            if row.get("solved") == "1":
                rows.append({"case_id": row["case_id"], "solved": 1, "labels": row.get("labels", "")})
    atomic_csv(cert_path, rows, ["case_id", "solved", "labels"])
    command = [sys.executable, str(SRC / "edge64_full_production_verify.py"), "--results", str(cert_path)]
    # A watchdog is mandatory here: the parent blocks on this child, and an
    # unbounded wait is how a single stuck verifier can silently stall the whole
    # production run.
    timeout = max(VERIFY_TIMEOUT_SECONDS, 0.001 * len(rows))
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        returncode = -1
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = f"verification timed out after {timeout:.0f}s: {exc}"
    report_path = verification_dir / f"{checkpoint_name}.json"
    result = {
        "status": "PASS" if returncode == 0 else "FAIL",
        "results_file": str(cert_path),
        "checked": len(rows),
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
    }
    atomic_json(report_path, result)
    if result["status"] != "PASS":
        raise RuntimeError(f"independent certificate verification failed: {report_path}")
    return result


def current_memory_mb() -> float:
    try:
        import psutil  # type: ignore

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def run_stage(
    stage: str,
    method: str,
    budget: float,
    input_path: Path,
    workers: int,
    chunk_size: int = 1,
) -> dict[str, object]:
    directory = stage_dir(stage)
    stage_progress = OUT / "stage_progress" / f"{stage}.json"
    stage_progress.parent.mkdir(parents=True, exist_ok=True)
    pending_path(stage).parent.mkdir(parents=True, exist_ok=True)
    pending_tmp = pending_path(stage).with_suffix(".csv.tmp")
    if pending_tmp.exists():
        pending_tmp.unlink()
    pending_handle = pending_tmp.open("w", newline="", encoding="utf-8")
    pending_writer = csv.DictWriter(pending_handle, fieldnames=MANIFEST_FIELDS)
    pending_writer.writeheader()
    input_count = 0
    total_solved = 0
    total_errors = 0
    total_nodes = 0
    total_runtime = 0.0
    processed = 0
    verified_checkpoints: list[str] = []
    checkpoint_files: list[Path] = []
    # ``workers < 1`` selects an in-process sequential run.  It needs no
    # multiprocessing transport, so it stays usable in restricted environments
    # where ProcessPoolExecutor cannot create its wakeup pipe, and it avoids the
    # per-task IPC cost that dominates the common case here.
    pool = ProcessPoolExecutor(max_workers=workers) if workers >= 1 else None
    try:
        with input_path.open("r", newline="", encoding="utf-8") as source:
            source_reader = csv.DictReader(source)
            range_index = 0
            while True:
                rows = []
                for _ in range(BATCH_SIZE):
                    try:
                        rows.append(next(source_reader))
                    except StopIteration:
                        break
                if not rows:
                    break
                range_start = input_count
                input_count += len(rows)
                range_end = input_count
                result_file = batch_path(stage, range_start, range_end)
                reused = result_file.exists()
                if reused:
                    result_rows = read_result_rows(result_file)
                else:
                    payloads = [
                        (
                            row["case_id"],
                            method,
                            budget,
                            str(directory),
                            int.from_bytes(hashlib.blake2b(f"{stage}:{row['case_id']}".encode("ascii"), digest_size=8).digest(), "big"),
                        )
                        for row in rows
                    ]
                    if pool is None:
                        computed = [worker(payload) for payload in payloads]
                    else:
                        batch_results: list[dict[str, object]] = []
                        for offset in range(0, len(payloads), chunk_size):
                            window = payloads[offset : offset + chunk_size]
                            batch_results.extend(pool.map(worker, window, chunksize=1))
                        computed = batch_results
                    result_rows = [
                        {
                            "case_id": row["case_id"],
                            "stage": stage,
                            "method": method,
                            "budget_seconds": budget,
                            "status": result.get("status", "error"),
                            "solved": int(result.get("solved", 0)),
                            "strategy": result.get("strategy", method),
                            "nodes": result.get("nodes", 0),
                            "backtracks": result.get("backtracks", 0),
                            "elapsed_seconds": result.get("elapsed_seconds", 0.0),
                            "error": result.get("error", ""),
                            "labels": " ".join(map(str, result.get("labels") or [])),
                        }
                        for row, result in zip(rows, computed)
                    ]
                    atomic_csv(result_file, result_rows, RESULT_FIELDS)
                result_by_id = {row["case_id"]: row for row in result_rows}
                for source_row in rows:
                    if result_by_id[source_row["case_id"]].get("solved") != "1":
                        pending_writer.writerow(source_row)
                processed += len(result_rows)
                append_heartbeat(
                    f"stage={stage} processed={processed} solved={total_solved} "
                    f"range={range_start}-{range_end} reused={int(reused)}"
                )
                total_solved += sum(row.get("solved") == "1" for row in result_rows)
                total_errors += sum(row.get("status") == "error" for row in result_rows)
                total_nodes += sum(int(float(row.get("nodes", 0) or 0)) for row in result_rows)
                total_runtime += sum(float(row.get("elapsed_seconds", 0) or 0) for row in result_rows)
                checkpoint_files.append(result_file)
                if total_errors:
                    atomic_json(OUT / "final_status.json", {"status": "PRODUCTION_PAUSED_ERROR", "stage": stage, "errors": total_errors})
                    raise RuntimeError(f"production error in stage {stage}")
                last_batch = len(rows) < BATCH_SIZE
                if processed % CHECKPOINT_ATTEMPTS < len(result_rows) or last_batch:
                    checkpoint_name = f"{stage}_{range_index:06d}"
                    verification = verify_checkpoint(checkpoint_files, checkpoint_name)
                    checkpoint_files = []
                    verified_checkpoints.append(checkpoint_name)
                    progress = {
                        "status": "RUNNING",
                        "stage": stage,
                        "method": method,
                        "budget_seconds": budget,
                        "input_cases": input_count,
                        "processed_cases": processed,
                        "solved": total_solved,
                        "survivors": processed - total_solved,
                        "errors": total_errors,
                        "nodes": total_nodes,
                        "runtime_seconds": total_runtime,
                        "nodes_per_second": total_nodes / max(total_runtime, 1e-9),
                        "memory_rss_mb": current_memory_mb(),
                        "verification": verification,
                        "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                    atomic_json(stage_progress, progress)
                    append_checkpoint({**progress, "checkpoint": checkpoint_name})
                    print(json.dumps(progress), flush=True)
                    range_index += 1
    finally:
        if pool is not None:
            pool.shutdown(wait=True)
        pending_handle.flush()
        os.fsync(pending_handle.fileno())
        pending_handle.close()
    pending_path(stage).unlink(missing_ok=True)
    os.replace(pending_tmp, pending_path(stage))
    if checkpoint_files:
        checkpoint_name = f"{stage}_final"
        verification = verify_checkpoint(checkpoint_files, checkpoint_name)
        verified_checkpoints.append(checkpoint_name)
    summary = {
        "stage": stage,
        "method": method,
        "budget_seconds": budget,
        "input_cases": input_count,
        "processed_cases": processed,
        "solved": total_solved,
        "survivors": input_count - total_solved,
        "errors": total_errors,
        "nodes": total_nodes,
        "runtime_seconds": total_runtime,
        "nodes_per_second": total_nodes / max(total_runtime, 1e-9),
        "verification_checkpoints": verified_checkpoints,
    }
    atomic_json(stage_progress, {**summary, "status": "VERIFIED"})
    return summary


def append_checkpoint(row: dict[str, object]) -> None:
    path = OUT / "checkpoint_progress.csv"
    fields = list(row)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())


def append_heartbeat(line: str) -> None:
    """Write one progress line so a stall is visible without waiting for a checkpoint."""
    if not HEARTBEAT_PATH:
        return
    path = Path(HEARTBEAT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {line}\n")
        handle.flush()


def main() -> int:
    global BATCH_SIZE, HEARTBEAT_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=WORKERS, help="worker processes; 0 or less runs sequentially in-process")
    parser.add_argument("--chunk-size", type=int, default=1, help="cases handed to the pool per round trip")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--log-file", type=Path, default=None, help="append a heartbeat line per processed batch")
    parser.add_argument("--build-manifest-only", action="store_true")
    args = parser.parse_args()
    BATCH_SIZE = args.batch_size
    HEARTBEAT_PATH = str(args.log_file) if args.log_file else None
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_meta = build_immutable_manifest()
    atomic_json(OUT / "production_1056_manifest.json", {"status": "NOT_APPLICABLE_FULL_EDGE64", "readiness_source": str(READINESS / "edge64_production_cascade_v1.json"), "note": "Full edge64 production uses edge64_full_production_manifest.json; the 1056-key readiness artifact remains frozen."})
    if args.build_manifest_only:
        print(json.dumps(manifest_meta, indent=2))
        return 0

    config = read_json(READINESS / "edge64_production_cascade_v1.json")
    if config.get("status") != "EDGE64_PRODUCTION_READY" or config.get("full_production_started"):
        raise RuntimeError("authoritative readiness configuration is not production-ready")
    summaries = []
    input_path = CASE_MANIFEST
    stage_survival: list[dict[str, object]] = []
    for stage, method, budget in STAGES:
        summary = run_stage(stage, method, budget, input_path, args.workers, args.chunk_size)
        summaries.append(summary)
        stage_survival.append(summary)
        atomic_csv(OUT / "stage_survival.csv", stage_survival, list(stage_survival[0]))
        if summary["errors"]:
            raise RuntimeError(f"stage {stage} has errors")
        if summary["survivors"] == 0:
            break
        next_path = pending_path(stage)
        if not next_path.exists():
            ranges = []
            stage_dir_path = stage_dir(stage)
            for path in sorted(stage_dir_path.glob("batch_*.csv")):
                stem = path.stem.split("_")
                ranges.append((int(stem[1]), int(stem[2]), path))
            make_pending(stage, input_path, ranges)
        input_path = next_path

    final_unresolved = summaries[-1]["survivors"] if summaries else EXPECTED_EDGE64_CASES
    expected_count, expected_id_hash = manifest_id_hash(CASE_MANIFEST)
    generated_count = 0
    generated_hash = hashlib.sha256()
    for generated_row in iter_edge64_rows():
        generated_count += 1
        generated_hash.update(generated_row["case_id"].encode("ascii"))
        generated_hash.update(b"\n")
    coverage_pass = bool(
        final_unresolved == 0
        and summaries
        and summaries[0]["input_cases"] == EXPECTED_EDGE64_CASES
        and expected_count == EXPECTED_EDGE64_CASES
        and generated_count == EXPECTED_EDGE64_CASES
        and generated_hash.hexdigest() == expected_id_hash
    )
    verification_files = list((OUT / "verification").glob("*.json"))
    verification_reports = [read_json(path) for path in verification_files]
    verified_count = sum(int(report.get("checked", 0)) for report in verification_reports if report.get("status") == "PASS")
    certificate_pass = bool(verified_count == sum(int(item["solved"]) for item in summaries) and all(report.get("status") == "PASS" for report in verification_reports))
    final_status = {
        "expected_cases": EXPECTED_EDGE64_CASES,
        "processed_cases": expected_count if summaries and summaries[0]["input_cases"] == EXPECTED_EDGE64_CASES else 0,
        "stage_attempts_total": sum(int(item["processed_cases"]) for item in summaries),
        "solved": EXPECTED_EDGE64_CASES - int(final_unresolved),
        "verified": verified_count,
        "unresolved": int(final_unresolved),
        "errors": sum(int(item["errors"]) for item in summaries),
        "pending": int(final_unresolved),
        "running": 0,
        "stage_survivors": stage_survival,
        "full_coverage_pass": coverage_pass,
        "certificate_verification_pass": certificate_pass,
        "universe_audit": {"manifest_count": expected_count, "generated_count": generated_count, "manifest_id_hash": expected_id_hash, "generated_id_hash": generated_hash.hexdigest()},
        "status": "EDGE64_ENUMERATED_FAMILY_COMPLETE" if coverage_pass and certificate_pass and final_unresolved == 0 else "EDGE64_ENUMERATION_INCOMPLETE",
        "manifest": manifest_meta,
    }
    atomic_json(OUT / "final_status.json", final_status)
    print(json.dumps(final_status, indent=2))
    return 0 if final_status["status"] == "EDGE64_ENUMERATED_FAMILY_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
