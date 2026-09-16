"""Benchmark native C8 local-table compilation on the fixed corpus.

The benchmark is deliberately local-table only.  It never advances the right
census or invokes the sequential global runner.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from edge63_C8_native_bridge import LANGUAGE, OWNERSHIP, TERMINAL_CACHE, read_native_table


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _memory_bytes_for_pid(pid: int) -> int | None:
    """Return a child process working set without adding a dependency."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("page_fault_count", wintypes.DWORD),
                    ("peak_working_set_size", ctypes.c_size_t), ("working_set_size", ctypes.c_size_t),
                    ("quota_peak_paged_pool_usage", ctypes.c_size_t), ("quota_paged_pool_usage", ctypes.c_size_t),
                    ("quota_peak_non_paged_pool_usage", ctypes.c_size_t), ("quota_non_paged_pool_usage", ctypes.c_size_t),
                    ("pagefile_usage", ctypes.c_size_t), ("peak_pagefile_usage", ctypes.c_size_t)]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    process = kernel32.OpenProcess(0x0010 | 0x1000, False, pid)
    if not process:
        return None
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    function = psapi.GetProcessMemoryInfo
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    function.restype = wintypes.BOOL
    try:
        if function(process, ctypes.byref(counters), counters.cb):
            return int(counters.working_set_size)
        return None
    finally:
        kernel32.CloseHandle(process)


def _corpus(batch: Path) -> list[dict[str, Any]]:
    rows = list(csv.DictReader((batch / "batch_key_manifest.csv").open(encoding="utf-8")))
    rows.sort(key=lambda row: (int(row["behavior_count"]), row["table_key"]))
    chosen = [rows[0], rows[len(rows) // 3], rows[(2 * len(rows)) // 3], rows[-1]]
    return [{"label": label, "table_key": row["table_key"], "intervals": json.loads(row["intervals_b"]),
             "python_compile_seconds": float(row["compile_seconds"])}
            for label, row in zip(("easy", "medium", "hard", "very_hard"), chosen)]


def _one(payload: tuple[str, dict[str, Any], str]) -> dict[str, Any]:
    executable, item, temp_root = payload
    output = Path(temp_root) / f"{item['label']}.bin"
    (a_start, a_end), (b_start, b_end) = item["intervals"]
    started = time.perf_counter()
    process = subprocess.Popen([
        executable, "--a-start", str(a_start), "--a-end", str(a_end),
        "--b-start", str(b_start), "--b-end", str(b_end), "--output", str(output),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    peak_working_set = 0
    while process.poll() is None:
        current = _memory_bytes_for_pid(process.pid)
        if current is not None:
            peak_working_set = max(peak_working_set, current)
        time.sleep(0.005)
    stdout, stderr = process.communicate()
    elapsed = time.perf_counter() - started
    if process.returncode:
        return {"label": item["label"], "table_key": item["table_key"], "status": "ERROR",
                "error": stderr[-1000:], "seconds": round(elapsed, 6), **_versions()}
    table = read_native_table(output)
    meta = output.with_suffix(output.suffix + ".meta")
    return {
        "label": item["label"], "table_key": item["table_key"], "behavior_count": len(table.records),
        "seconds": round(elapsed, 6), "python_compile_seconds": item["python_compile_seconds"],
        "speedup_vs_python": round(item["python_compile_seconds"] / elapsed, 6) if elapsed else None,
        "output_bytes": output.stat().st_size,
        "peak_child_working_set": peak_working_set or None,
        "meta_present": meta.exists(), "status": "PASS", **_versions(),
    }


def _run_workers(executable: Path, corpus: list[dict[str, Any]], workers: int, out: Path) -> list[dict[str, Any]]:
    root = Path(tempfile.mkdtemp(prefix=f"native_w{workers}_", dir=out))
    payloads = [(str(executable), item, str(root)) for item in corpus]
    started = time.perf_counter()
    try:
        if workers == 1:
            rows = [_one(payload) for payload in payloads]
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                rows = list(pool.map(_one, payloads))
        elapsed = time.perf_counter() - started
        for row in rows:
            row["workers"] = workers
            row["batch_wall_seconds"] = round(elapsed, 6)
            row["tables_per_second"] = round(len(rows) / elapsed, 6) if elapsed else None
        return rows
    finally:
        for path in root.glob("*"):
            path.unlink(missing_ok=True)
        root.rmdir()


def _memory_stability(executable: Path, corpus: list[dict[str, Any]], out: Path) -> list[dict[str, Any]]:
    rows = []
    for round_index in range(1, 4):
        result = _run_workers(executable, corpus, 1, out)
        values = [row["peak_child_working_set"] for row in result if row.get("peak_child_working_set")]
        rows.append({"round": round_index, "peak_observed_working_set": max(values) if values else None,
                     "minimum_observed_working_set": min(values) if values else None,
                     "status": "PASS", **_versions()})
    return rows


def run(executable: Path, corpus: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for workers in (1, 2, 4):
        rows.extend(_run_workers(executable, corpus, workers, out))
    fields = list(rows[0])
    with (out / "worker_scaling.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    stability = _memory_stability(executable, corpus, out)
    with (out / "memory_stability.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stability[0]))
        writer.writeheader()
        writer.writerows(stability)
    good = [row for row in rows if row["status"] == "PASS"]
    by_workers = {}
    for workers in (1, 2, 4):
        group = [row for row in good if row["workers"] == workers]
        by_workers[str(workers)] = {
            "batch_wall_seconds": group[0]["batch_wall_seconds"] if group else None,
            "tables_per_second": group[0]["tables_per_second"] if group else None,
            "mean_table_seconds": sum(row["seconds"] for row in group) / len(group) if group else None,
        }
    best = min((int(key) for key, value in by_workers.items() if value["batch_wall_seconds"] is not None),
               key=lambda key: by_workers[str(key)]["batch_wall_seconds"], default=None)
    result = {"status": "PASS" if len(good) == len(rows) else "FAIL", "corpus_size": len(corpus),
              "workers": by_workers, "best_workers": best, "memory_stability": stability, **_versions()}
    (out / "native_benchmark.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--batch", type=Path, default=Path("results/edge63_two_interval_gate2/tree1_C8/left_leaf_2_exact_v3/frontier_directed_v1/table_batch_structure_v1"))
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/benchmarks"))
    args = parser.parse_args()
    out = args.output
    corpus = _corpus(args.batch)
    result = run(args.executable, corpus, out)
    print(json.dumps({key: value for key, value in result.items() if key != "memory_stability"}, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
