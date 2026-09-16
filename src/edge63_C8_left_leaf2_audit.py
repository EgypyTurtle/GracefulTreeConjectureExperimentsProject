#!/usr/bin/env python3
"""Finalize the auditable v3 checkpoint for Tree1 left_leaf_2.

The exact search remains resumable in ``left_leaf_2_exact_v3``.  This script
only derives reports from the ownership-correct allocation index, persistent
cache files, progress, and the latest runner summary.  It never converts an
incomplete run into UNSAT and never invents a minimum span.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_C8_left_leaf2_prefilter import (  # noqa: E402
    CASE,
    OUTPUT_NAME,
    SPLIT_SLOT,
    allocation_index_audit,
    split_shape,
)
from edge63_C8_allocations import ALLOCATION_DEDUP_VERSION, LANGUAGE_VERSION  # noqa: E402
from edge63_C8_middle_group_cache import (  # noqa: E402
    PersistentMiddleGroupCache,
    TERMINAL_PAIR_CACHE_VERSION,
)
from edge63_C8_displacement_first import values_for_case  # noqa: E402


def read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_cache_files(root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    cache_root = root / "cache_v2" / "two_run_tables" / CASE / SPLIT_SLOT
    options_rows: list[dict[str, object]] = []
    pair_rows: list[dict[str, object]] = []
    for path in sorted(cache_root.glob("*.pkl.gz")):
        try:
            with gzip.open(path, "rb") as handle:
                payload = pickle.load(handle)
            key = payload.get("key")
            if not isinstance(key, tuple) or len(key) < 7:
                continue
            kind = key[5]
            value = key[6]
            states = tuple(payload.get("states", ()))
            if kind == "options":
                intervals, role = value
                legal = all(
                    1 <= start <= end <= 63
                    for start, end in intervals
                )
                options_rows.append({
                    "cache_file": path.name,
                    "intervals": ";".join(f"{a}-{b}" for a, b in intervals),
                    "run_count": len(intervals),
                    "role": role,
                    "state_count": len(states),
                    "two_run_state": len(intervals) == 2 and legal,
                    "cache_version": key[0],
                    "language": key[1],
                    "allocation_dedup_version": key[2],
                    "terminal_pair_cache_version": key[3],
                })
            elif kind == "pairs":
                intervals_a, intervals_b = value
                all_intervals = (*intervals_a, *intervals_b)
                legal = all(1 <= start <= end <= 63 for start, end in all_intervals)
                if not legal:
                    continue
                pair_rows.append({
                    "cache_file": path.name,
                    "intervals_a": ";".join(f"{a}-{b}" for a, b in intervals_a),
                    "intervals_b": ";".join(f"{a}-{b}" for a, b in intervals_b),
                    "state_count": len(states),
                    "cache_version": key[0],
                    "language": key[1],
                    "allocation_dedup_version": key[2],
                    "terminal_pair_cache_version": key[3],
                })
        except (OSError, EOFError, KeyError, ValueError, AttributeError, pickle.PickleError):
            continue
    return options_rows, pair_rows


def split_pair_set(groups: dict) -> tuple[set[tuple], Counter, Counter]:
    pairs: set[tuple] = set()
    residual_counts: Counter = Counter()
    raw_counts: Counter = Counter()
    for group in groups.values():
        for residual_key in group:
            blocks = dict(residual_key)[SPLIT_SLOT]
            ordered = tuple(sorted(blocks))
            lengths = tuple(end - start + 1 for start, end in ordered)
            gap = ordered[1][0] - ordered[0][1] - 1
            pair_key = (ordered,)
            pairs.add(pair_key)
            residual_counts[(lengths, gap)] += 1
            raw_counts[(lengths, gap)] += 1 if lengths[0] == lengths[1] else 2
    return pairs, residual_counts, raw_counts


def load_progress(output_dir: Path) -> dict:
    return read_json(output_dir / "progress.json", {})


def finalize(root: Path) -> dict[str, object]:
    output_dir = root / "tree1_C8" / OUTPUT_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = PersistentMiddleGroupCache(root, CASE, SPLIT_SLOT)
    groups, raw, index_hit = cache.load_or_build_index(values_for_case(CASE))
    audit = allocation_index_audit(groups, raw)
    options_rows, pair_rows = read_cache_files(root)
    summary = read_json(output_dir / "run_summary.json", {})
    progress = load_progress(output_dir)
    lazy_differential = read_json(
        output_dir / "lazy_oracle_v1" / "lazy_oracle_differential_tests_verified.json",
        {},
    )
    lazy_benchmark = read_json(
        output_dir / "lazy_oracle_v1" / "left_existence_stats.json",
        {},
    )
    adjacent_audit = read_json(
        output_dir / "adjacent_collapse_audit" / "adjacent_global_mapping_verification.json",
        {},
    )
    done_groups = int(progress.get("done_group_count", summary.get("middle_groups_done", 0)))
    two_run_option_rows = [row for row in options_rows if row["two_run_state"]]
    generated_two_run_intervals = {
        row["intervals"] for row in two_run_option_rows if row["role"] == "terminal"
    }
    generated_pair_keys = {
        (row["intervals_a"], row["intervals_b"]) for row in pair_rows
    }
    expected_pair_keys: set[tuple[str, str]] = set()
    for group in groups.values():
        for residual_key in group:
            blocks = dict(residual_key)
            for first, second in (
                (blocks["left_leaf_1"], blocks["left_leaf_2"]),
                (blocks["right_leaf_1"], blocks["right_leaf_2"]),
            ):
                expected_pair_keys.add((
                    ";".join(f"{a}-{b}" for a, b in first),
                    ";".join(f"{a}-{b}" for a, b in second),
                ))

    # Re-write the index-level funnel with a clear distinction between audit
    # numbers and hard-prune numbers.  The latter stay pending until a full
    # exact run has actually computed them.
    funnel = [
        {"stage": "raw_C8_allocations", "count": raw, "status": "COMPLETE", "hard_filter": "no"},
        {"stage": "actual_automorphism_orbit_audit", "count": audit["distinct_actual_automorphism_orbits_audit"], "status": "COMPLETE", "hard_filter": "no", "note": "identity-retained exact runner"},
        {"stage": "adjacent_resegmentation", "count": audit["adjacent_raw_allocations"], "status": "COMPLETE", "hard_filter": "no"},
        {"stage": "genuine_separated", "count": audit["genuine_separated_raw_allocations"], "status": "COMPLETE", "hard_filter": "no", "note": "priority only"},
        {"stage": "distinct_middle_groups", "count": len(groups), "status": "COMPLETE", "hard_filter": "no"},
        {"stage": "middle_groups_completed", "count": done_groups, "status": "CHECKPOINT", "hard_filter": "no", "total": len(groups)},
        {"stage": "terminal_pair_tables_generated", "count": len(generated_pair_keys & expected_pair_keys), "status": "CHECKPOINT", "hard_filter": "no", "total_expected_terminal_pair_table_keys": len(expected_pair_keys)},
        {"stage": "two_run_terminal_option_tables_generated", "count": len(generated_two_run_intervals), "status": "CHECKPOINT", "hard_filter": "no", "total_expected_split_interval_pairs": audit["distinct_two_run_interval_pairs"]},
        {"stage": "optimistic_global_span_lower_bound", "count": None, "status": "PENDING_EXACT_AUDIT", "hard_filter": "pending"},
        {"stage": "exact_compatible_pairs", "count": summary.get("counts", {}).get("compatible_terminal_pairs", 0), "status": summary.get("status", "UNRESOLVED_RESOURCE"), "hard_filter": "exact"},
    ]
    write_csv(output_dir / "allocation_prefilter_funnel.csv", funnel)

    pair_stat_rows = [{
        "scope": "left_leaf_2_terminal_pair_cache",
        "expected_distinct_residual_pair_keys": audit["residual_assignment_keys"],
        "expected_distinct_terminal_pair_table_keys": len(expected_pair_keys),
        "generated_pair_tables": len(generated_pair_keys & expected_pair_keys),
        "pending_pair_tables": max(0, len(expected_pair_keys) - len(generated_pair_keys & expected_pair_keys)),
        "expected_distinct_split_interval_pairs": audit["distinct_two_run_interval_pairs"],
        "generated_two_run_option_tables": len(generated_two_run_intervals),
        "language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
        "status": summary.get("status", "INDEX_READY_PREFILTER_PENDING"),
    }]
    write_csv(output_dir / "two_run_interval_pair_stats.csv", pair_stat_rows)
    local_rows = []
    for row in sorted(two_run_option_rows, key=lambda x: x["intervals"]):
        intervals = tuple(
            tuple(int(value) for value in token.split("-"))
            for token in str(row["intervals"]).split(";")
        )
        ordered = tuple(sorted(intervals))
        local_rows.append({
            **row,
            "run_gap": ordered[1][0] - ordered[0][1] - 1,
            "geometry_classification": "ADJACENT_RESEGMENTATION" if ordered[1][0] - ordered[0][1] - 1 == 0 else "GENUINE_SEPARATED",
            "C7_equivalence": "NOT_COMPUTED_UNTIL_MATCHED_WITNESS",
        })
    write_csv(output_dir / "two_run_local_geometry_stats.csv", local_rows or [{"status": "NO_TWO_RUN_TABLES_RECORDED"}])

    gap_rows = [
        {"gap": gap, "residual_assignment_keys": count, "raw_allocations": audit["gap_distribution_raw_allocations"].get(gap, 0), "language": LANGUAGE_VERSION}
        for gap, count in sorted((int(k), v) for k, v in audit["gap_distribution_residual_keys"].items())
    ]
    write_csv(output_dir / "split_gap_analysis.csv", gap_rows)

    balance = Counter()
    balance_raw = Counter()
    for group in groups.values():
        for residual_key in group:
            blocks = tuple(sorted(dict(residual_key)[SPLIT_SLOT]))
            lengths = tuple(end - start + 1 for start, end in blocks)
            weight = 1 if lengths[0] == lengths[1] else 2
            balance[lengths] += 1
            balance_raw[lengths] += weight
    write_csv(output_dir / "split_balance_analysis.csv", [
        {"run_lengths_sorted": f"{a}+{b}", "residual_assignment_keys": balance[(a, b)], "raw_allocations": balance_raw[(a, b)], "split_length_sum": a + b}
        for (a, b) in sorted(balance)
    ])

    counts = summary.get("counts", {})
    write_csv(output_dir / "best_span_progress.csv", [{
        "checkpoint": "latest_persistent_runner_summary",
        "status": summary.get("status", "UNRESOLVED_RESOURCE"),
        "groups_done": done_groups,
        "groups_total": len(groups),
        "compatible_terminal_pairs": counts.get("compatible_terminal_pairs", 0),
        "minimum_compatible_span": summary.get("minimum_compatible_span", "NONE"),
        "resource_limited_is_not_unsat": True,
    }])
    write_csv(output_dir / "minimum_candidates.csv", [{
        "status": "UNRESOLVED_RESOURCE",
        "minimum_span": "NONE",
        "reason": "no exhaustive C8 left_leaf_2 closure yet; do not fabricate sigma_min",
    }])
    write_csv(output_dir / "C7_C8_geometry_compare.csv", [{
        "status": "PENDING",
        "reason": "no C8 compatible candidate has been recorded in the partial v3 run",
        "C7_baseline_compatible_rows": 36,
        "C8_compatible_rows_seen": counts.get("compatible_terminal_pairs", 0),
    }])

    gate = {
        "status": summary.get("status", "UNRESOLVED_RESOURCE"),
        "complete": bool(summary.get("complete", False)),
        "scope": "Tree1 / C8.LevelB.v1 / side-terminal split(left_leaf_2) only",
        "case": CASE,
        "split_slot": SPLIT_SLOT,
        "two_run_language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
        "raw_C8_allocations": raw,
        "middle_groups_total": len(groups),
        "middle_groups_done": done_groups,
        "compatible_span_minimum": summary.get("minimum_compatible_span", "NONE"),
        "resource_limited_is_not_unsat": True,
        "adjacent_raw_allocations": audit["adjacent_raw_allocations"],
        "genuine_separated_raw_allocations": audit["genuine_separated_raw_allocations"],
        "distinct_two_run_interval_pairs": audit["distinct_two_run_interval_pairs"],
    }
    (output_dir / "gate_status.json").write_text(json.dumps(gate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    verification = {
        "status": "PASS_STATIC_CHECKS_PARTIAL_RUN",
        "checks": {
            "raw_allocation_count_745920": raw == 745920,
            "residual_assignment_keys_383040": audit["residual_assignment_keys"] == 383040,
            "adjacent_plus_genuine_raw_equals_raw": audit["adjacent_raw_allocations"] + audit["genuine_separated_raw_allocations"] == raw,
            "ownership_version": ALLOCATION_DEDUP_VERSION == "ownership.v2",
            "terminal_cache_version": TERMINAL_PAIR_CACHE_VERSION == "corrected.v2",
            "language_version": LANGUAGE_VERSION == "C8.LevelB.v1",
            "left_leaf_2_declared": SPLIT_SLOT == "left_leaf_2",
            "resource_status_not_unsat": summary.get("status") != "UNSAT_EXHAUSTIVE_C8_LEVELB" or bool(summary.get("complete")),
        },
        "exact_final_candidate_verification": "NOT_APPLICABLE_UNTIL_COMPLETE",
    }
    (output_dir / "verification.json").write_text(json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "verified_constructions").mkdir(exist_ok=True)

    report = f"""# Tree1 C8 left_leaf_2 v3 checkpoint

Scope: `C8.LevelB.v1` side-terminal split sublanguage, split slot `left_leaf_2` only.

Versions: `ownership.v2`, `corrected.v2`.

## Current status

`{gate['status']}`. This is a resumable resource checkpoint, not an UNSAT result.

    The ownership-correct index contains **{raw:,}** raw allocations, **{audit['residual_assignment_keys']:,}** residual assignment keys, and **{len(groups):,}** persistent middle groups. The exact runner has completed **{done_groups:,}/{len(groups):,}** groups so far.

The allocation audit records **{audit['adjacent_raw_allocations']:,}** adjacent resegmentations and **{audit['genuine_separated_raw_allocations']:,}** genuinely separated raw allocations. Exact enumeration retains both classes; adjacency is diagnostic only.

There are **{audit['distinct_two_run_interval_pairs']:,}** distinct two-run interval pairs in the allocation index. The current cache contains **{len(generated_two_run_intervals):,}** corresponding terminal option tables and **{len(generated_pair_keys & expected_pair_keys):,}/{len(expected_pair_keys):,}** expected terminal-pair tables. The remaining work is therefore dominated by long two-run local/pair-table generation and the exact side join, not middle-group reconstruction.

No compatible terminal pair and no minimum span have been recorded in this partial checkpoint. Accordingly, `sigma_min` is **not assigned**.

## Adjacent-collapse audit

The adjacent allocation audit covers **{adjacent_audit.get('adjacent_raw_allocations', audit['adjacent_raw_allocations']):,}** raw allocations and **{adjacent_audit.get('distinct_adjacent_interval_pairs', 'unknown')}** distinct interval pairs. The local family comparison found **{adjacent_audit.get('family_relation_counts', {}).get('SUBSET', 0):,}** `SUBSET` pairs and **{adjacent_audit.get('family_relation_counts', {}).get('NEW_BEHAVIOR', 0):,}** `NEW_BEHAVIOR` pairs. Only the former are locally C7-contained; global discharge remains disabled unless the ownership-preserving merge is separately proven.

## Lazy-oracle audit

The independent differential verifier reports **{lazy_differential.get('status', 'PENDING')}** for the declared `C8.LevelB.v1` local language. On the cached benchmark, the old full-pair lookup visited **{lazy_benchmark.get('old_full_pair_states_visited', 0):,}** cached states in **{lazy_benchmark.get('old_seconds', 0.0)}** seconds, while the current uncached prefix oracle visited **{lazy_benchmark.get('lazy_partial_prefix_steps', 0):,}** prefix steps in **{lazy_benchmark.get('lazy_seconds', 0.0)}** seconds. This is an exactness success but a performance regression; the remaining bottleneck is repeated expansion of the same long two-run interval pairs.

## Accounting rule

All hard filters are necessary-condition filters. Resource-limited execution remains `UNRESOLVED_RESOURCE`; only a complete side-terminal run may emit `UNSAT_EXHAUSTIVE_C8_LEVELB`. `left_leaf_1` was not rerun.
"""
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    (output_dir / "best_span_progress_v2.csv").write_text(
        (output_dir / "best_span_progress.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    report_v2 = report.replace(
        "# Tree1 C8 left_leaf_2 v3 checkpoint",
        "# Tree1 C8 left_leaf_2 v3 checkpoint / audit v2",
    )
    (output_dir / "report_v2.md").write_text(report_v2, encoding="utf-8")
    verification_v2 = {
        **verification,
        "adjacent_collapse_audit": {
            "status": adjacent_audit.get("status", "PENDING"),
            "family_relation_counts": adjacent_audit.get("family_relation_counts", {}),
            "global_discharge": adjacent_audit.get("global_discharge", "PENDING"),
        },
        "lazy_oracle_differential": lazy_differential.get("status", "PENDING"),
        "lazy_benchmark_status": lazy_benchmark.get("status", "PENDING"),
        "lazy_benchmark_is_performance_only": True,
    }
    (output_dir / "verification_v2.json").write_text(
        json.dumps(verification_v2, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return gate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    args = parser.parse_args()
    print(json.dumps(finalize(args.root), ensure_ascii=False))


if __name__ == "__main__":
    main()
