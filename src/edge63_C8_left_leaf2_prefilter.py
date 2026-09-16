#!/usr/bin/env python3
"""Ownership-correct C8 prefilter and v3 launcher for Tree1 left_leaf_2.

This module is intentionally scoped to the Tree1 side-terminal split
``left_leaf_2``.  It builds or reuses the persistent allocation index, records
adjacent versus genuinely separated split runs, and can audit middle groups
incrementally.  It never turns an incomplete audit into a negative result.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_C8_allocations import (  # noqa: E402
    ALLOCATION_DEDUP_VERSION,
    LANGUAGE_VERSION,
    allocation_order_text,
)
from edge63_C8_displacement_first import values_for_case  # noqa: E402
from edge63_C8_middle_group_cache import (  # noqa: E402
    PersistentMiddleGroupCache,
    TERMINAL_PAIR_CACHE_VERSION,
    version_fingerprint,
)
from edge63_C8_persistent_runner import search_case  # noqa: E402
from edge63_C8_two_run_cache import PersistentTwoRunCache  # noqa: E402
from edge63_displacement_first_compact import EDGE_COUNT, MIDDLE_PATHS, PATHS, path_lengths  # noqa: E402


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SPLIT_SLOT = "left_leaf_2"
OUTPUT_NAME = "left_leaf_2_exact_v3"
PREFILTER_VERSION = "left-leaf2-prefilter.v3:ownership.v2:necessary-only"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def split_shape(residual_key: tuple) -> tuple[str, int, int, int, str]:
    intervals = dict(residual_key)[SPLIT_SLOT]
    if len(intervals) != 2:
        raise AssertionError("left_leaf_2 must own exactly two runs")
    first, second = sorted(intervals)
    gap = second[0] - first[1] - 1
    if gap < 0:
        raise AssertionError("split intervals overlap")
    return SPLIT_SLOT, first[1] - first[0] + 1, second[1] - second[0] + 1, gap, (
        "ADJACENT_RESEGMENTATION" if gap == 0 else "GENUINE_SEPARATED"
    )


def automorphism_key(middle_key: tuple, residual_key: tuple) -> tuple:
    """Canonical orbit key for the actual right-leaf swap.

    Tree1 has one relevant graph automorphism here: it exchanges the two
    equal-length right terminal leaves.  This is an audit statistic only; the
    exact runner retains both ownership maps.
    """
    swap = {"right_leaf_1": "right_leaf_2", "right_leaf_2": "right_leaf_1"}

    def swapped_middle(key: tuple) -> tuple:
        return tuple(sorted(key))

    def swapped_residual(key: tuple) -> tuple:
        items = []
        for path, intervals in key:
            items.append((swap.get(path, path), intervals))
        return tuple(sorted(items))

    original = (tuple(middle_key), tuple(residual_key))
    image = (swapped_middle(middle_key), swapped_residual(residual_key))
    return min(original, image)


def allocation_index_audit(
    groups: dict[tuple, dict[tuple, tuple[str, ...]]], raw_allocations: int
) -> dict[str, object]:
    residuals = [
        (middle_key, residual_key, run_order)
        for middle_key, group in groups.items()
        for residual_key, run_order in group.items()
    ]
    shape_counts: Counter[str] = Counter()
    gap_counts: Counter[int] = Counter()
    weighted_shape_counts: Counter[str] = Counter()
    weighted_gap_counts: Counter[int] = Counter()
    pair_keys: set[tuple] = set()
    orbit_keys: set[tuple] = set()
    for middle_key, residual_key, _run_order in residuals:
        _slot, a, b, gap, shape = split_shape(residual_key)
        multiplicity = 1 if a == b else 2
        shape_counts[shape] += 1
        gap_counts[gap] += 1
        weighted_shape_counts[shape] += multiplicity
        weighted_gap_counts[gap] += multiplicity
        intervals = tuple(sorted(dict(residual_key)[SPLIT_SLOT]))
        pair_keys.add((a, b, intervals))
        orbit_keys.add(automorphism_key(middle_key, residual_key))
    return {
        "raw_C8_allocations": raw_allocations,
        "residual_assignment_keys": len(residuals),
        "distinct_actual_automorphism_orbits_audit": len(orbit_keys),
        "exact_runner_allocations_retained": raw_allocations,
        "adjacent_residual_keys": shape_counts["ADJACENT_RESEGMENTATION"],
        "genuine_separated_residual_keys": shape_counts["GENUINE_SEPARATED"],
        "adjacent_raw_allocations": weighted_shape_counts["ADJACENT_RESEGMENTATION"],
        "genuine_separated_raw_allocations": weighted_shape_counts["GENUINE_SEPARATED"],
        "distinct_two_run_interval_pairs": len(pair_keys),
        "gap_distribution_residual_keys": dict(sorted(gap_counts.items())),
        "gap_distribution_raw_allocations": dict(sorted(weighted_gap_counts.items())),
    }


def make_metadata(root: Path, groups: dict[tuple, dict[tuple, tuple[str, ...]]], raw: int, index_hit: bool) -> dict[str, object]:
    cache = PersistentMiddleGroupCache(root, CASE, SPLIT_SLOT)
    fingerprint = version_fingerprint(CASE, SPLIT_SLOT)
    audit = allocation_index_audit(groups, raw)
    lengths = path_lengths(values_for_case(CASE))
    return {
        "case": CASE,
        "split_slot": SPLIT_SLOT,
        "split_path_length": lengths[SPLIT_SLOT],
        "two_run_language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
        "prefilter_version": PREFILTER_VERSION,
        "version_fingerprint": fingerprint,
        "allocation_index_cache_hit": index_hit,
        "middle_groups": len(groups),
        "raw_index_count": raw,
        "audit": audit,
        "middle_frame_convention": "r2=0; left=-Delta_L; right=+Delta_R",
        "bitset_universe": "signed-offset-mask.v1:edge63:shift256",
        "persistent_group_cache": cache.stats(),
    }


def build_funnel(root: Path) -> dict[str, object]:
    started = time.time()
    values = values_for_case(CASE)
    cache = PersistentMiddleGroupCache(root, CASE, SPLIT_SLOT)
    groups, raw, index_hit = cache.load_or_build_index(values)
    cache.sync_manifest(groups)
    metadata = make_metadata(root, groups, raw, index_hit)
    output_dir = root / "tree1_C8" / OUTPUT_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "prefilter_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    funnel = [
        {"stage": "raw", "count": raw, "hard_filter": "no", "reason": "ownership.v2 allocation index"},
        {
            "stage": "actual_automorphism_orbit_audit",
            "count": metadata["audit"]["distinct_actual_automorphism_orbits_audit"],
            "hard_filter": "no",
            "reason": "audit only; exact runner retains ownership-distinct allocations",
        },
        {
            "stage": "adjacent_resegmentation_residual_keys",
            "count": metadata["audit"]["adjacent_residual_keys"],
            "hard_filter": "no",
            "reason": "diagnostic; C7-equivalent candidates are not removed",
        },
        {
            "stage": "genuine_separated_residual_keys",
            "count": metadata["audit"]["genuine_separated_residual_keys"],
            "hard_filter": "no",
            "reason": "priority class, not a prune",
        },
        {
            "stage": "distinct_middle_groups",
            "count": len(groups),
            "hard_filter": "no",
            "reason": "persistent group decomposition",
        },
        {
            "stage": "middle_local_and_terminal_prefilter",
            "count": None,
            "hard_filter": "pending",
            "reason": "requires incremental group build and corrected.v2 pair tables",
        },
        {
            "stage": "optimistic_global_span_lower_bound",
            "count": None,
            "hard_filter": "pending",
            "reason": "computed only when the required group and terminal envelopes are available",
        },
    ]
    write_csv(output_dir / "allocation_prefilter_funnel.csv", funnel)
    write_csv(root / "allocation_prefilter_v1" / "allocation_prefilter_stats.csv", [{
        "case": CASE,
        "split_slot": SPLIT_SLOT,
        "status": "INDEX_READY_PREFILTER_PENDING",
        "prefilter_version": PREFILTER_VERSION,
        **metadata["audit"],
    }])
    stats = {
        "status": "INDEX_READY_PREFILTER_PENDING",
        "elapsed_seconds": round(time.time() - started, 3),
        **metadata,
    }
    (output_dir / "prefilter_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def run(time_limit: float | None, root: Path) -> dict[str, object]:
    stats = build_funnel(root)
    summary = search_case(CASE, SPLIT_SLOT, root, time_limit, OUTPUT_NAME)
    output_dir = root / "tree1_C8" / OUTPUT_NAME
    (output_dir / "v3_launch.json").write_text(json.dumps({
        "prefilter": stats,
        "runner_summary": summary,
        "two_run_language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--time-limit", type=float, default=120.0)
    parser.add_argument("--prefilter-only", action="store_true")
    args = parser.parse_args()
    result = build_funnel(args.root) if args.prefilter_only else run(args.time_limit, args.root)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
