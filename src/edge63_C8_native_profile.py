"""Fixed Python performance corpus and phase profile for the native rewrite."""

from __future__ import annotations

import argparse
import csv
import cProfile
import io
import json
import pickle
import pstats
import tempfile
import time
import tracemalloc
from collections import Counter
from pathlib import Path
from typing import Any

from edge63_C8_collision_signature import _process_family
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_left_negative_cert_cache import canonical_family_key, find_small_hitting_set
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_two_run_local_states import two_run_options


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _intervals(raw: str) -> tuple[tuple[int, int], ...]:
    value = json.loads(raw)
    return tuple(tuple(int(x) for x in part) for part in value)


def _load_corpus(base: Path) -> list[dict[str, Any]]:
    rows = list(csv.DictReader((base / "batch_key_manifest.csv").open(encoding="utf-8")))
    for row in rows:
        row["intervals"] = _intervals(row["intervals_b"])
        row["behavior_count"] = int(row["behavior_count"])
        row["active_queries"] = int(row["active_queries"] or 0)
    rows.sort(key=lambda row: (row["behavior_count"], -row["active_queries"], row["table_key"]))
    if len(rows) < 4:
        raise RuntimeError("fixed performance corpus requires the 32-key batch")
    selected = [rows[0], rows[len(rows) // 3], rows[(2 * len(rows)) // 3], rows[-1]]
    labels = ("easy", "medium", "hard", "very_hard")
    return [{"class": label, **row} for label, row in zip(labels, selected)]


def _time_call(function, repeats: int = 1) -> tuple[float, Any, int]:
    tracemalloc.start()
    started = time.perf_counter()
    value = None
    for _ in range(repeats):
        value = function()
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, value, peak


def _compile_reference(root: Path, intervals: tuple[tuple[int, int], ...]) -> tuple[float, Any, int]:
    two_run_options.cache_clear()
    cache = PersistentTwoRunCache(root, CASE, SLOT)
    return _time_call(lambda: cache.options(intervals, "terminal"))


def _quotient_reference(states: tuple[Any, ...]) -> tuple[float, Any, int]:
    def work():
        rows = []
        for index, state in enumerate(states):
            private = tuple(sorted(state.private))
            rows.append((index, private, int(state.min_value), int(state.max_value), int(state.max_value - state.min_value)))
        return rows
    return _time_call(work, repeats=10)


def _bitset_reference(states: tuple[Any, ...]) -> tuple[float, Any, int]:
    def work():
        contains: dict[int, int] = {}
        all_bits = (1 << len(states)) - 1
        for index, state in enumerate(states):
            bit = 1 << index
            for offset in state.private:
                contains[offset] = contains.get(offset, 0) | bit
        return all_bits, contains
    return _time_call(work, repeats=10)


def _serialization_reference(states: tuple[Any, ...]) -> tuple[float, Any, int]:
    payload = [{"private": tuple(state.private), "min": int(state.min_value), "max": int(state.max_value)} for state in states]
    return _time_call(lambda: pickle.dumps(payload, protocol=5), repeats=10)


def _semantic_samples(worklist: Path, limit: int = 8) -> list[dict[str, Any]]:
    result = []
    seen = set()
    with worklist.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pair = json.loads(row["left_two_run_interval_pair"])
            intervals_a = tuple(tuple(int(value) for value in part) for part in pair[0])
            intervals_b = tuple(tuple(int(value) for value in part) for part in pair[1])
            frame = json.loads(row["left_root_frame"])
            family = canonical_family_key(intervals_a, intervals_b, int(frame["left_shift"]),
                                          int(row["middle_min"]), int(row["middle_max"]), True)
            if family in seen:
                continue
            seen.add(family)
            result.append({
                "family_key": family,
                "occupied": frozenset(int(value) for value in json.loads(row["occupied_left_offset_set"])),
                "intervals_a": intervals_a,
                "intervals_b": intervals_b,
                "shift": int(frame["left_shift"]),
                "middle_min": int(row["middle_min"]),
                "middle_max": int(row["middle_max"]),
            })
            if len(result) >= limit:
                break
    return result


def _semantic_profile(root: Path, worklist: Path) -> dict[str, Any]:
    samples = _semantic_samples(worklist)
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    index = CompiledTerminalPairIndex(root, CASE, SLOT)
    # Warm the exact persistent dependencies before measuring query work.
    for sample in samples:
        _process_family(pair_cache, index, sample["family_key"],
                        [{"occupied_values_parsed": sample["occupied"]}], {sample["occupied"]: []})
    started = time.perf_counter()
    outcomes = []
    for sample in samples:
        signatures, _effect, details = _process_family(
            pair_cache, index, sample["family_key"],
            [{"occupied_values_parsed": sample["occupied"]}], {sample["occupied"]: []})
        outcomes.append({"allowed_count": int(signatures[0]["allowed_count"]) if signatures else 0,
                         "behaviors": int(details["behaviors"])})
    seconds = time.perf_counter() - started
    cert_started = time.perf_counter()
    certificate_hits = 0
    for sample in samples[:4]:
        states = pair_cache.terminal_pairs(sample["intervals_a"], sample["intervals_b"])
        feasible = [state for state in states if max(sample["middle_max"], max((0, *state.private)) + sample["shift"]) - min(sample["middle_min"], min((0, *state.private)) + sample["shift"]) <= 63]
        if find_small_hitting_set(feasible, sample["occupied"], sample["shift"], max_size=3) is not None:
            certificate_hits += 1
    certificate_seconds = time.perf_counter() - cert_started
    return {
        "sample_queries": len(samples),
        "semantic_seconds": seconds,
        "semantic_queries_per_second": len(samples) / seconds if seconds else None,
        "semantic_outcomes": outcomes,
        "certificate_sample_size": min(4, len(samples)),
        "certificate_hits": certificate_hits,
        "certificate_seconds": certificate_seconds,
        "certificate_queries_per_second": certificate_hits / certificate_seconds if certificate_seconds and certificate_hits else 0.0,
        "scope": "warm existing exact Python semantic/certificate path",
    }


def _artifact_phase_profile(base: Path) -> dict[str, float]:
    """Measure the current exact recovery/join artifact passes separately."""
    phases: dict[str, float] = {}
    bilateral = base / "full_bilateral_v1" / "bilateral_contexts.csv"
    outer = base / "outer_zero_audit_v1" / "outer_join_results.csv"
    started = time.perf_counter()
    if bilateral.exists():
        list(csv.DictReader(bilateral.open(encoding="utf-8")))
    phases["bilateral_recovery_artifact_read"] = time.perf_counter() - started
    started = time.perf_counter()
    if outer.exists():
        list(csv.DictReader(outer.open(encoding="utf-8")))
    phases["outer_join_artifact_read"] = time.perf_counter() - started
    return phases


def _call_profile(intervals: tuple[tuple[int, int], ...]) -> dict[str, Any]:
    """Collect calls and wall/CPU time for one cold representative."""
    with tempfile.TemporaryDirectory(prefix="c8_python_call_profile_") as temp:
        profiler = cProfile.Profile()
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        profiler.enable()
        _compile_reference(Path(temp), intervals)
        profiler.disable()
        elapsed_wall = time.perf_counter() - started_wall
        elapsed_cpu = time.process_time() - started_cpu
        stats = pstats.Stats(profiler, stream=io.StringIO()).sort_stats("cumulative")
        stream = io.StringIO()
        stats.stream = stream
        stats.print_stats(12)
        return {
            "wall_seconds": elapsed_wall,
            "cpu_seconds": elapsed_cpu,
            "total_calls": stats.total_calls,
            "primitive_calls": stats.prim_calls,
            "top_cumulative_calls": stream.getvalue().splitlines()[-12:],
            "allocation_measurement": "tracemalloc peak bytes in performance_corpus.csv; allocation count not inferred",
        }


def _profile(root: Path, corpus: list[dict[str, Any]], worklist: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    phase_rows = []
    phase_times: Counter[str] = Counter()
    phase_peaks: Counter[str] = Counter()
    for item in corpus:
        intervals = item["intervals"]
        # Isolate every representative so this measures reference generation,
        # not a hit in the persistent cache created by earlier runs.
        with tempfile.TemporaryDirectory(prefix="c8_python_profile_") as temp:
            compile_seconds, states, compile_peak = _compile_reference(Path(temp), intervals)
        quotient_seconds, _quotient, quotient_peak = _quotient_reference(states)
        bitset_seconds, _bitset, bitset_peak = _bitset_reference(states)
        serial_seconds, _serial, serial_peak = _serialization_reference(states)
        timings = {
            "local_behavior_generation": compile_seconds,
            "geometry_quotient": quotient_seconds / 10.0,
            "compiled_bitset_construction": bitset_seconds / 10.0,
            "serialization_io": serial_seconds / 10.0,
        }
        for phase, seconds in timings.items():
            phase_times[phase] += seconds
        peak_map = {
            "local_behavior_generation": compile_peak,
            "geometry_quotient": quotient_peak,
            "compiled_bitset_construction": bitset_peak,
            "serialization_io": serial_peak,
        }
        for phase, peak in peak_map.items():
            phase_peaks[phase] = max(phase_peaks[phase], peak)
        phase_rows.append({
            "corpus_class": item["class"],
            "table_key": item["table_key"],
            "intervals": item["intervals"],
            "behavior_count": len(states),
            "active_queries": item["active_queries"],
            **{f"seconds_{key}": round(value, 9) for key, value in timings.items()},
            **{f"peak_bytes_{key}": value for key, value in peak_map.items()},
            **_versions(),
        })
    semantic = _semantic_profile(root, worklist)
    artifact_phases = _artifact_phase_profile(worklist.parents[1])
    phase_times.update({"semantic_query_evaluation": semantic["semantic_seconds"],
                        "certificate_extraction": semantic["certificate_seconds"], **artifact_phases})
    total = sum(phase_times.values()) or 1.0
    summary = {
        "phase_seconds": dict(phase_times),
        "phase_share": {key: value / total for key, value in phase_times.items()},
        "phase_peak_bytes": dict(phase_peaks),
        "semantic_profile": semantic,
        "call_profile": _call_profile(corpus[-1]["intervals"]),
        "profile_note": "local phases are cold isolated reference generation; semantic/certificate are warm exact path samples; bilateral/outer are artifact replay I/O timing",
        **_versions(),
    }
    return phase_rows, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--batch", type=Path, default=Path("results/edge63_two_interval_gate2/tree1_C8/left_leaf_2_exact_v3/frontier_directed_v1/table_batch_structure_v1"))
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/profile"))
    args = parser.parse_args()
    corpus = _load_corpus(args.batch)
    worklist = args.results_root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_right_support_v1" / "right_supported_residual_worklist_full.csv"
    rows, summary = _profile(args.results_root, corpus, worklist)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "performance_corpus.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = list(rows[0])
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "python_profile.json").write_text(json.dumps({"corpus": corpus, **summary}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
