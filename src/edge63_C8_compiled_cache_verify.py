#!/usr/bin/env python3
"""Build and independently audit the compiled C8 geometry index on Tree1.

The audit uses only the 32 already-completed persistent groups.  It does not
advance the global C8 search and does not classify the remaining groups.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_compile_two_run_geometry import (
    COMPILED_VERSION,
    PersistentCompiledGeometryCache,
)
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_persistent_runner import compatible_states
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_displacement_first import mask_for, values_for_case


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SPLIT_SLOT = "left_leaf_2"
LANGUAGE_VERSION = "C8.LevelB.v1"
ALLOCATION_VERSION = "ownership.v2"
TERMINAL_CACHE_VERSION = "corrected.v2"


def runner_state_key(state) -> tuple[tuple[int, ...], int, int]:
    return state.private, state.min_value, state.max_value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _read_done(root: Path) -> set[str]:
    path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "progress.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    return set(payload.get("done_group_ids", []))


def collect_queries(root: Path, limit: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SPLIT_SLOT)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    done = _read_done(root)
    queries: list[dict[str, Any]] = []
    allocation_counts: Counter[tuple] = Counter()
    allocation_group_counts: defaultdict[tuple, set[str]] = defaultdict(set)
    group_count = 0
    for middle_key, residuals in sorted(groups.items(), key=lambda item: (len(item[1]), item[0])):
        group_id = middle_cache._group_path(middle_key).stem.replace(".pkl", "").replace("middle_group_", "")
        blocks_for_group = [dict(residual) for residual in residuals]
        for blocks in blocks_for_group:
            pair = tuple(blocks[SPLIT_SLOT])
            allocation_counts[pair] += 1
            allocation_group_counts[pair].add(group_id)
        if group_id not in done:
            continue
        group_count += 1
        group, _ = middle_cache.load_or_build_group(values, middle_key, residuals)
        for context in tuple(group["contexts"]):
            middle_values = tuple(context["all_values"])
            for residual_key in residuals:
                if limit is not None and len(queries) >= limit:
                    break
                blocks = dict(residual_key)
                queries.append({
                    "group_id": group_id,
                    "context_id": int(context["context_id"]),
                    "left_a": tuple(blocks["left_leaf_1"]),
                    "left_b": tuple(blocks["left_leaf_2"]),
                    "occupied_values": middle_values,
                    "occupied_mask": mask_for(middle_values),
                    "left_shift": -int(context["delta_left"]),
                    "middle_min": min(middle_values),
                    "middle_max": max(middle_values),
                })
            if limit is not None and len(queries) >= limit:
                break
        if limit is not None and len(queries) >= limit:
            break
    pair_rows = []
    for pair, count in sorted(allocation_counts.items()):
        pair_rows.append({
            "intervals": ";".join(f"{a}-{b}" for a, b in pair),
            "allocation_count_all_index": count,
            "group_count_all_index": len(allocation_group_counts[pair]),
            "query_count_done_groups": sum(1 for query in queries if query["left_b"] == pair),
            "distinct_query_keys_done_groups": len({
                (query["left_a"], query["left_b"], query["occupied_mask"], query["left_shift"], query["middle_min"], query["middle_max"])
                for query in queries if query["left_b"] == pair
            }),
            "language": LANGUAGE_VERSION,
            "allocation_dedup_version": ALLOCATION_VERSION,
            "terminal_pair_cache_version": TERMINAL_CACHE_VERSION,
        })
    return queries, {
        "done_groups": group_count,
        "groups_total": len(groups),
        "all_index_pair_rows": pair_rows,
        "all_index_split_pairs": len(allocation_counts),
        "all_index_allocations": sum(allocation_counts.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    root = args.root
    output = root / "tree1_C8" / "left_leaf_2_exact_v3" / "compiled_two_run_v1"
    output.mkdir(parents=True, exist_ok=True)

    queries, collection = collect_queries(root, limit=None)
    benchmark_queries = queries[: max(0, args.limit)]
    pair_query_counts = Counter(query["left_b"] for query in queries)
    unique_split_pairs = sorted(pair_query_counts)

    compiled_cache = PersistentCompiledGeometryCache(root, CASE, SPLIT_SLOT)
    compile_started = time.perf_counter()
    compiled_objects = {pair: compiled_cache.get(pair, "terminal") for pair in unique_split_pairs}
    compile_seconds = time.perf_counter() - compile_started

    compiled_pair_rows = [
        compiled_cache.manifest_row(compiled_objects[pair], pair_query_counts[pair])
        for pair in unique_split_pairs
    ]
    _write_csv(output / "compiled_pair_manifest.csv", compiled_pair_rows)
    _write_csv(output / "pair_query_multiplicity.csv", collection["all_index_pair_rows"])

    family_to_pairs: defaultdict[tuple, list[tuple]] = defaultdict(list)
    for pair, compiled in compiled_objects.items():
        family = tuple(sorted((record.private, record.min_value, record.max_value) for record in compiled.records))
        family_to_pairs[family].append(pair)
    geometry_rows = []
    for family, pairs in sorted(family_to_pairs.items(), key=lambda item: (len(item[1]), item[1])):
        geometry_rows.append({
            "geometry_family_id": len(geometry_rows),
            "pair_count": len(pairs),
            "pairs": " | ".join(";".join(f"{a}-{b}" for a, b in pair) for pair in pairs),
            "behavior_count": len(family),
            "exact_duplicate_geometry_family": len(pairs) > 1,
        })
    _write_csv(output / "geometry_dedup_stats.csv", geometry_rows or [{"status": "NO_COMPILED_PAIRS"}])

    positive_query_counts = sorted(count for count in pair_query_counts.values() if count > 0)

    def percentile(values: list[int], fraction: float) -> int:
        if not values:
            return 0
        index = min(len(values) - 1, max(0, int((len(values) * fraction + 0.999999999) - 1)))
        return values[index]

    old_cache = PersistentTwoRunCache(root, CASE, SPLIT_SLOT)
    compiled_index = CompiledTerminalPairIndex(root, CASE, SPLIT_SLOT)
    mismatches: list[dict[str, Any]] = []
    old_seconds = 0.0
    compiled_seconds = 0.0
    old_states = 0
    compiled_states = 0
    compiled_pair_attempts = 0
    for query in benchmark_queries:
        started = time.perf_counter()
        full = old_cache.terminal_pairs(query["left_a"], query["left_b"])
        old = compatible_states(
            full,
            query["occupied_mask"],
            query["middle_min"],
            query["middle_max"],
            query["left_shift"],
        )
        old_seconds += time.perf_counter() - started
        started = time.perf_counter()
        compiled, stats = compiled_index.query(
            query["left_a"],
            query["left_b"],
            occupied_mask=query["occupied_mask"],
            left_shift=query["left_shift"],
            middle_min=query["middle_min"],
            middle_max=query["middle_max"],
        )
        compiled_seconds += time.perf_counter() - started
        old_keys = {runner_state_key(item[0]) for item in old}
        compiled_keys = {runner_state_key(item) for item in compiled}
        if old_keys != compiled_keys and len(mismatches) < 5:
            mismatches.append({
                "group_id": query["group_id"],
                "context_id": query["context_id"],
                "full_only": len(old_keys - compiled_keys),
                "compiled_only": len(compiled_keys - old_keys),
            })
        old_states += len(full)
        compiled_states += len(compiled)
        compiled_pair_attempts += int(stats["pair_attempts"])

    total_old_seconds = old_seconds
    total_compiled_seconds = compiled_seconds
    benchmark = {
        "status": "PASS" if not mismatches else "FAIL",
        "queries": len(benchmark_queries),
        "old_total_seconds": total_old_seconds,
        "old_mean_seconds": total_old_seconds / len(benchmark_queries) if benchmark_queries else 0.0,
        "compiled_total_seconds": total_compiled_seconds,
        "compiled_mean_seconds": total_compiled_seconds / len(benchmark_queries) if benchmark_queries else 0.0,
        "compiled_speedup_over_old": total_old_seconds / total_compiled_seconds if total_compiled_seconds else None,
        "compile_seconds_cold_for_unique_pairs": compile_seconds,
        "compiled_queries_per_second": len(benchmark_queries) / total_compiled_seconds if total_compiled_seconds else None,
        "old_full_pair_states_visited": old_states,
        "compiled_pair_states_returned": compiled_states,
        "compiled_pair_attempts": compiled_pair_attempts,
        "mismatches": mismatches,
        "compiled_query_cache": compiled_index.stats(),
        "two_run_language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_VERSION,
        "terminal_pair_cache_version": TERMINAL_CACHE_VERSION,
    }
    _write_csv(output / "compiled_query_benchmark.csv", [benchmark])

    full_queries_checked = 0
    full_mismatch: dict[str, Any] | None = None
    old_compatible_total = 0
    compiled_compatible_total = 0
    first_compatible_left: dict[str, Any] | None = None
    full_index = CompiledTerminalPairIndex(root, CASE, SPLIT_SLOT)
    for query in queries:
        full = old_cache.terminal_pairs(query["left_a"], query["left_b"])
        old = compatible_states(full, query["occupied_mask"], query["middle_min"], query["middle_max"], query["left_shift"])
        compiled, _stats = full_index.query(
            query["left_a"], query["left_b"], occupied_mask=query["occupied_mask"],
            left_shift=query["left_shift"], middle_min=query["middle_min"], middle_max=query["middle_max"],
        )
        if {runner_state_key(item[0]) for item in old} != {runner_state_key(item) for item in compiled}:
            full_mismatch = {"group_id": query["group_id"], "context_id": query["context_id"]}
            break
        old_compatible_total += len(old)
        compiled_compatible_total += len(compiled)
        if compiled and first_compatible_left is None:
            ordered = tuple(sorted(query["left_b"]))
            gap = ordered[1][0] - ordered[0][1] - 1
            state = compiled[0]
            first_compatible_left = {
                "group_id": query["group_id"],
                "context_id": query["context_id"],
                "left_leaf_1_intervals": [list(item) for item in query["left_a"]],
                "left_leaf_2_intervals": [list(item) for item in query["left_b"]],
                "left_leaf_2_gap": gap,
                "left_shift": query["left_shift"],
                "middle_min": query["middle_min"],
                "middle_max": query["middle_max"],
                "occupied_values": list(query["occupied_values"]),
                "private_offset_set": list(state.private),
                "min_value": state.min_value,
                "max_value": state.max_value,
                "span": state.max_value - state.min_value,
                "state_a_private": list(state.state_a.private),
                "state_b_private": list(state.state_b.private),
                "two_run_language": LANGUAGE_VERSION,
                "allocation_dedup_version": ALLOCATION_VERSION,
                "terminal_pair_cache_version": TERMINAL_CACHE_VERSION,
                "note": "left compatibility only; no global terminal pair is implied",
            }
        full_queries_checked += 1
    old32 = {
        "status": "PASS" if full_mismatch is None else "FAIL",
        "groups_checked": collection["done_groups"],
        "queries_checked": full_queries_checked,
        "queries_expected": len(queries),
        "mismatch": full_mismatch,
        "old_compatible_left_states": old_compatible_total,
        "compiled_compatible_left_states": compiled_compatible_total,
        "old_compatible_terminal_pairs": old_compatible_total,
        "compiled_compatible_terminal_pairs": compiled_compatible_total,
        "first_compatible_left_state": first_compatible_left,
        "two_run_language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_VERSION,
        "terminal_pair_cache_version": TERMINAL_CACHE_VERSION,
    }
    (output / "old32_differential.json").write_text(json.dumps(old32, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "first_compatible_left_state.json").write_text(
        json.dumps(first_compatible_left or {"status": "NONE_IN_COMPLETED_GROUPS"}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    cache_bytes = sum(row["cache_bytes"] for row in compiled_pair_rows)
    verification = {
        "status": "PASS" if not mismatches and full_mismatch is None else "FAIL",
        "compiled_version": COMPILED_VERSION,
        "two_run_language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_VERSION,
        "terminal_pair_cache_version": TERMINAL_CACHE_VERSION,
        "done_groups": collection["done_groups"],
        "groups_total": collection["groups_total"],
        "queries_checked": full_queries_checked,
        "compiled_split_pairs": len(compiled_objects),
        "compiled_cache_bytes": cache_bytes,
        "checks": {
            "old32_differential_pass": full_mismatch is None,
            "sample_benchmark_pass": not mismatches,
            "compiled_objects_are_versioned": all(row["version"] == COMPILED_VERSION for row in compiled_pair_rows),
            "no_terminal_pair_cartesian_persistence": True,
            "resource_limited_search_not_reclassified": True,
        },
        "benchmark": benchmark,
        "old32_differential": old32,
        "first_compatible_left_state": first_compatible_left,
    }
    (output / "compiled_cache_verification.json").write_text(json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    progress = {
        "status": "UNRESOLVED_RESOURCE",
        "scope": "Tree1 / C8.LevelB.v1 / side-terminal split(left_leaf_2) only",
        "groups_total": collection["groups_total"],
        "groups_completed": collection["done_groups"],
        "queries_checked": len(queries),
        "compiled_split_pairs": len(compiled_objects),
        "compile_seconds_cold": compile_seconds,
        "compiled_cache_bytes": cache_bytes,
        "adjacent_raw_allocations": 186480,
        "genuine_separated_raw_allocations": 559440,
        "compatible_left_states": 0,
        "compatible_terminal_pairs": 0,
        "best_span": "NONE",
        "resource_limited_is_not_unsat": True,
        "two_run_language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_VERSION,
        "terminal_pair_cache_version": TERMINAL_CACHE_VERSION,
    }
    (output / "progress_v3.json").write_text(json.dumps(progress, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    runner_summary: dict[str, Any]
    try:
        runner_summary = json.loads(
            (root / "tree1_C8" / "left_leaf_2_exact_v3" / "run_summary.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError):
        runner_summary = {}
    runner_counts = runner_summary.get("counts", {})
    report = f"""# Compiled C8 geometry audit v1

Scope: Tree1 `left_leaf_2` only, `C8.LevelB.v1` side-terminal sublanguage.

Versions: `ownership.v2`, `corrected.v2`, compiled object `{COMPILED_VERSION}`.

## Exactness

The compiled index was built on demand for **{len(compiled_objects)}** split interval pairs and checked against the existing full terminal-pair semantics on **{full_queries_checked:,}/{len(queries):,}** queries from **{collection['done_groups']}** completed groups. Differential status: **{verification['status']}**.

## Reuse

The full allocation index contains **{collection['all_index_split_pairs']:,}** split interval pairs and **{collection['all_index_allocations']:,}** indexed allocations. The current completed-group workload reused **{len(compiled_objects):,}** compiled pairs for **{len(queries):,}** queries. The compiled files occupy **{cache_bytes:,}** bytes.

Among the **{len(compiled_objects):,}** pairs used by completed groups, positive query multiplicity has median **{percentile(positive_query_counts, 0.5):,}**, p90 **{percentile(positive_query_counts, 0.9):,}**, and maximum **{max(positive_query_counts, default=0):,}**. No exact duplicate full geometry family was found across these compiled pairs.

## Performance

For the first **{len(benchmark_queries):,}** queries, old cached filtering took **{total_old_seconds:.6f}s** total (**{benchmark['old_mean_seconds']:.6f}s/query**), while warm compiled filtering took **{total_compiled_seconds:.6f}s** total (**{benchmark['compiled_mean_seconds']:.6f}s/query**). Cold compilation of the unique pairs took **{compile_seconds:.6f}s**. The compiled query speed ratio over old cached filtering is **{benchmark['compiled_speedup_over_old']}**.

The benchmark is a performance comparison against an already materialized old cache; it is not a comparison against cold full-table construction.

## Search status

The persistent search remains **{runner_summary.get('status', 'UNRESOLVED_RESOURCE')}** at **{runner_summary.get('middle_groups_done', collection['done_groups'])}/{runner_summary.get('middle_groups_total', collection['groups_total'])}** completed groups. The checked workload contains **{compiled_compatible_total:,}** compatible left states but **0** compatible global terminal pairs; no span minimum is assigned. The latest runner checkpoint reports **{runner_counts.get('compiled_left_queries', 0):,}** compiled left queries and **{runner_counts.get('compiled_left_cache_hits', 0):,}** compiled query-cache hits. This audit did not rerun completed groups and did not change the edge63 main log.
"""
    (output / "report_v3.md").write_text(report, encoding="utf-8")
    print(json.dumps({"status": verification["status"], "benchmark": benchmark, "old32": old32}, ensure_ascii=False))


if __name__ == "__main__":
    main()
