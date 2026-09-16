"""Benchmark the exact hybrid backend on the existing Tree1 checkpoint queries."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from edge63_C8_compiled_cache_verify import collect_queries
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_hybrid_terminal_backend import HybridTerminalBackend
from edge63_C8_persistent_runner import compatible_states
from edge63_C8_two_run_cache import PersistentTwoRunCache


def _key(state: Any) -> tuple[tuple[int, ...], int, int]:
    return tuple(state.private), int(state.min_value), int(state.max_value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    queries, _collection = collect_queries(args.root, limit=None)
    queries = queries[: max(0, args.limit)]

    pair_cache = PersistentTwoRunCache(args.root, "fiveleaf3e-63-3-21-2-20-9-4-4", "left_leaf_2")
    compiled_index = CompiledTerminalPairIndex(args.root, "fiveleaf3e-63-3-21-2-20-9-4-4", "left_leaf_2")
    hybrid = HybridTerminalBackend(pair_cache, compiled_index)
    mismatches: list[dict[str, Any]] = []
    old_seconds = 0.0
    hybrid_seconds = 0.0
    old_states = 0
    hybrid_states = 0
    backend_counts = {"OLD_CACHED_FILTER": 0, "COMPILED_GEOMETRY_INDEX": 0}

    for query in queries:
        started = time.perf_counter()
        full = pair_cache.terminal_pairs(query["left_a"], query["left_b"])
        old = compatible_states(
            full,
            query["occupied_mask"],
            query["middle_min"],
            query["middle_max"],
            query["left_shift"],
        )
        old_seconds += time.perf_counter() - started

        started = time.perf_counter()
        hybrid_result, backend_stats = hybrid.query(
            query["left_a"],
            query["left_b"],
            occupied_mask=query["occupied_mask"],
            left_shift=query["left_shift"],
            middle_min=query["middle_min"],
            middle_max=query["middle_max"],
            span_mode=True,
        )
        hybrid_seconds += time.perf_counter() - started
        backend_counts[backend_stats["backend"]] += 1
        old_keys = {_key(item[0]) for item in old}
        hybrid_keys = {_key(item[0]) for item in hybrid_result}
        if old_keys != hybrid_keys and len(mismatches) < 10:
            mismatches.append({
                "group_id": query["group_id"],
                "context_id": query["context_id"],
                "old_only": len(old_keys - hybrid_keys),
                "hybrid_only": len(hybrid_keys - old_keys),
            })
        old_states += len(full)
        hybrid_states += len(hybrid_result)

    output = args.root / "tree1_C8" / "left_leaf_2_exact_v3" / "first_left_repair_analysis"
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "PASS" if not mismatches else "FAIL",
        "queries": len(queries),
        "old_cached_filter_total_seconds": old_seconds,
        "old_cached_filter_mean_seconds": old_seconds / len(queries) if queries else 0.0,
        "hybrid_total_seconds": hybrid_seconds,
        "hybrid_mean_seconds": hybrid_seconds / len(queries) if queries else 0.0,
        "hybrid_speedup_over_old": old_seconds / hybrid_seconds if hybrid_seconds else None,
        "old_full_pair_states_visited": old_states,
        "hybrid_compatible_states_returned": hybrid_states,
        "backend_counts": backend_counts,
        "old_cache_queries": int(hybrid.stats["old_cache_queries"]),
        "compiled_queries": int(hybrid.stats["compiled_queries"]),
        "old_cache_hits": int(hybrid.stats["old_cache_hits"]),
        "compiled_cache_hits": int(hybrid.stats["compiled_cache_hits"]),
        "seconds_old_cache": float(hybrid.stats["seconds_old_cache"]),
        "seconds_compiled": float(hybrid.stats["seconds_compiled"]),
        "mismatches": mismatches,
        "two_run_language": "C8.LevelB.v1",
        "allocation_dedup_version": "ownership.v2",
        "terminal_pair_cache_version": "corrected.v2",
    }
    (output / "hybrid_backend_benchmark.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (output / "hybrid_backend_benchmark.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(payload))
        writer.writeheader()
        writer.writerow({key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in payload.items()})
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
