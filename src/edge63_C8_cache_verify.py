"""Independent checks for C8 ownership and persistent-cache invariants."""

from __future__ import annotations

import argparse
import csv
import json
import pickle
from pathlib import Path

from edge63_C8_allocations import allocation_count, iter_allocations
from edge63_C8_allocation_prefilter import PrefilterStats, prefilter_group
from edge63_C8_middle_group_cache import (
    ALLOCATION_DEDUP_VERSION,
    PersistentMiddleGroupCache,
    TERMINAL_PAIR_CACHE_VERSION,
    version_fingerprint,
)
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_displacement_first import values_for_case
from edge63_displacement_first_compact import middle_contexts


def _allocation_signature(allocation: dict[str, object]) -> tuple:
    blocks = allocation["blocks"]
    return tuple(
        (path, tuple(tuple(interval) for interval in blocks[path]))
        for path in sorted(blocks)
    )


def write_latest_rows(path: Path, rows: list[dict[str, object]], keys: tuple[str, ...] = ("case", "split_slot")) -> None:
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            existing = list(csv.DictReader(handle))
    replacement_keys = {tuple(str(row.get(key, "")) for key in keys) for row in rows}
    existing = [
        row for row in existing
        if tuple(row.get(key, "") for key in keys) not in replacement_keys
    ]
    all_rows = existing + rows
    if not all_rows:
        return
    fields = list(all_rows[0])
    for row in all_rows[1:]:
        for field in row:
            if field not in fields:
                fields.append(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)


def rebuild_summary_tables(root: Path) -> list[dict[str, object]]:
    summaries = []
    for summary_path in sorted(root.glob("tree*_C8/*_exact_v2/run_summary.json")):
        summaries.append(json.loads(summary_path.read_text(encoding="utf-8")))
    reuse_rows = []
    prefilter_rows = []
    local_rows = []
    performance_rows = []
    for summary in summaries:
        case = summary["case"]
        split_slot = summary["split_slot"]
        cache = PersistentMiddleGroupCache(root, case, split_slot)
        groups, raw_allocations, index_hit = cache.load_or_build_index(values_for_case(case))
        residual_count = sum(len(residuals) for residuals in groups.values())
        group_sizes = [len(residuals) for residuals in groups.values()]
        reuse_rows.append({
            "case": case,
            "split_slot": split_slot,
            "raw_allocations": raw_allocations,
            "distinct_middle_groups": len(groups),
            "unique_residual_assignments": residual_count,
            "average_raw_allocations_per_group": raw_allocations / len(groups) if groups else 0.0,
            "average_unique_residuals_per_group": residual_count / len(groups) if groups else 0.0,
            "maximum_unique_residuals_per_group": max(group_sizes, default=0),
            "raw_to_middle_group_ratio": raw_allocations / len(groups) if groups else 0.0,
            "allocation_index_cache_hit": index_hit,
            "allocation_dedup_version": summary["allocation_dedup_version"],
            "version_fingerprint": summary["version_fingerprint"],
        })
        counts = summary["counts"]
        prefilter_rows.append({
            "case": case,
            "split_slot": split_slot,
            "status": summary["status"],
            "version_fingerprint": summary["version_fingerprint"],
            **{key: value for key, value in counts.items() if key.startswith("prefilter_")},
        })
        local_rows.append({
            "case": case,
            "split_slot": split_slot,
            **summary["persistent_two_run_cache"],
            "two_run_language": summary["two_run_language"],
            "allocation_dedup_version": summary["allocation_dedup_version"],
            "terminal_pair_cache_version": summary["terminal_pair_cache_version"],
        })
        performance_rows.append({
            "case": case,
            "split_slot": split_slot,
            "status": summary["status"],
            "groups_total": summary["middle_groups_total"],
            "groups_done": summary["middle_groups_done"],
            "raw_allocations": summary["raw_C8_allocations"],
            "allocation_index_cache_hit": summary["allocation_index_cache_hit"],
            **summary["timing"],
            "elapsed_seconds": summary["elapsed_seconds"],
            "prefilter_survivors": counts.get("prefilter_survivors", 0),
            "compatible_terminal_pairs": counts.get("compatible_terminal_pairs", 0),
            "right_compatibility_scans": counts.get("right_compatibility_scans", 0),
            "right_compatibility_scans_skipped_left_empty": counts.get(
                "right_compatibility_scans_skipped_left_empty", 0
            ),
            "minimum_compatible_span": summary["minimum_compatible_span"],
        })
    write_latest_rows(root / "middle_group_reuse_stats.csv", reuse_rows)
    write_latest_rows(root / "allocation_prefilter_stats.csv", prefilter_rows)
    write_latest_rows(root / "two_run_local_cache_stats.csv", local_rows)
    write_latest_rows(root / "performance_profile_v2.csv", performance_rows)
    return summaries


def verify_persistent_summary(summary: dict[str, object]) -> dict[str, object]:
    status = summary.get("status")
    counts = summary.get("counts", {})
    complete = summary.get("complete") is True
    groups_done = int(summary.get("middle_groups_done", 0))
    groups_total = int(summary.get("middle_groups_total", 0))
    pairs = int(counts.get("compatible_terminal_pairs", 0))
    min_span = summary.get("minimum_compatible_span")
    if summary.get("two_run_language") != "C8.LevelB.v1":
        raise AssertionError("persistent summary has unexpected local language")
    if summary.get("allocation_dedup_version") != ALLOCATION_DEDUP_VERSION:
        raise AssertionError("persistent summary has stale allocation ownership")
    if summary.get("terminal_pair_cache_version") != TERMINAL_PAIR_CACHE_VERSION:
        raise AssertionError("persistent summary has stale terminal cache")
    if groups_done < 0 or groups_done > groups_total:
        raise AssertionError("persistent summary group accounting is invalid")
    if status == "UNRESOLVED_RESOURCE" and complete:
        raise AssertionError("resource-limited persistent row marked complete")
    if status == "COMPATIBLE_SPAN_GT63":
        if not complete or pairs <= 0 or not isinstance(min_span, int) or min_span <= 63:
            raise AssertionError("inconsistent compatible-span persistent row")
    if status == "UNSAT_EXHAUSTIVE_C8_LEVELB":
        if not complete or pairs != 0:
            raise AssertionError("inconsistent exhaustive-unsat persistent row")
    return {
        "case": summary.get("case"),
        "split_slot": summary.get("split_slot"),
        "status": status,
        "complete": complete,
        "groups_done": groups_done,
        "groups_total": groups_total,
        "compatible_terminal_pairs": pairs,
        "minimum_compatible_span": min_span,
        "status_consistent": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--case", default="fiveleaf3e-63-3-21-2-20-9-4-4")
    parser.add_argument("--split-slot", default="left_leaf_1")
    args = parser.parse_args()

    values = values_for_case(args.case)
    generated = list(iter_allocations(values, args.split_slot))
    expected = allocation_count(values, args.split_slot)
    signatures = {_allocation_signature(item) for item in generated}
    ownership = {
        "status": "PASS" if len(generated) == expected and len(signatures) == expected else "FAIL",
        "case": args.case,
        "split_slot": args.split_slot,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "expected_raw_allocations": expected,
        "generated_raw_allocations": len(generated),
        "distinct_ownership_maps": len(signatures),
        "same_length_ownership_preserved": len(signatures) == expected,
    }
    (args.root / "ownership_regression_tests.json").write_text(
        json.dumps(ownership, indent=2) + "\n", encoding="utf-8"
    )
    if ownership["status"] != "PASS":
        raise AssertionError(ownership)

    cache = PersistentMiddleGroupCache(args.root, args.case, args.split_slot)
    groups, _raw, index_hit = cache.load_or_build_index(values)
    cache.sync_manifest(groups)
    if not groups:
        raise AssertionError("empty allocation index")
    middle_key, residuals = next(iter(sorted(groups.items(), key=lambda item: item[0])))
    group, group_hit = cache.load_or_build_group(values, middle_key, residuals)
    left_block, central_block, right_block = middle_key
    fresh_contexts, fresh_stats = middle_contexts(
        left_block[1], left_block[2] - left_block[1] + 1,
        central_block[1], central_block[2] - central_block[1] + 1,
        right_block[1], right_block[2] - right_block[1] + 1,
        "B",
    )
    cached_equal_fresh = pickle.dumps(tuple(group["contexts"]), protocol=5) == pickle.dumps(tuple(fresh_contexts), protocol=5)
    pair_cache = PersistentTwoRunCache(args.root, args.case, args.split_slot)
    prefilter_stats = PrefilterStats()
    candidates = prefilter_group(group, pair_cache, prefilter_stats)
    differential = {
        "status": "PASS" if cached_equal_fresh else "FAIL",
        "case": args.case,
        "split_slot": args.split_slot,
        "index_cache_hit": index_hit,
        "middle_group_cache_hit": group_hit,
        "middle_group_id": group["group_id"],
        "cached_context_count": len(group["contexts"]),
        "fresh_context_count": len(fresh_contexts),
        "cached_build_stats": group["build_stats"],
        "fresh_build_stats": dict(fresh_stats),
        "cached_equals_fresh": cached_equal_fresh,
        "prefilter_candidate_count": len(candidates),
        "prefilter_version": "allocation-prefilter.v2:ownership.v2:table-and-middle-span",
        "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
        "version_fingerprint": version_fingerprint(args.case, args.split_slot),
    }
    (args.root / "cache_differential_tests.json").write_text(
        json.dumps(differential, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if not cached_equal_fresh:
        raise AssertionError(differential)
    run_summaries = []
    for case_dir in (args.root / "tree1_C8", args.root / "tree3_C8"):
        summary_path = case_dir / f"{args.split_slot}_exact_v2" / "run_summary.json"
        if summary_path.exists():
            run_summaries.append(json.loads(summary_path.read_text(encoding="utf-8")))
    persistent_summary_checks = [verify_persistent_summary(summary) for summary in run_summaries]
    gate2_verification = {
        "verification_version": "C8.gate2.v2.independent",
        "runner_version": "persistent-runner.v2",
        "two_run_language": "C8.LevelB.v1",
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
        "status": "PASS",
        "run_summaries": run_summaries,
        "persistent_summary_checks": persistent_summary_checks,
        "ownership_regression": ownership,
        "cache_differential": differential,
        "side_terminal_runner_only": True,
        "bridge_middle_splits_prescanned_only": True,
        "resource_timeout_is_not_unsat": True,
        "no_old_allocation_counts": True,
    }
    (args.root / "gate2_v2_verification.json").write_text(
        json.dumps(gate2_verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_lines = [
        "# C8 Gate 2 v2 report",
        "",
        "This report covers the persistent middle-group/cache architecture for the "
        "`C8.LevelB.v1` side-terminal split sublanguage.",
        "",
        "Versions: allocation `ownership.v2`; terminal-pair cache `corrected.v2`; "
        "middle frame `r2=0`, `left=-Delta_L`, `right=+Delta_R`.",
        "",
        "| case | split slot | status | groups done | groups total | raw allocations | outer join seconds |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for summary in run_summaries:
        report_lines.append(
            f"| {summary['case']} | {summary['split_slot']} | {summary['status']} | "
            f"{summary['middle_groups_done']} | {summary['middle_groups_total']} | "
            f"{summary['raw_C8_allocations']} | {summary['timing']['outer_join_seconds']:.3f} |"
        )
    report_lines.extend([
        "",
        "The persistent-runner summaries below are separate from the first bounded "
        "probe CSVs. A completed row is exhaustive only for the named side-terminal "
        "split slot and declared `C8.LevelB.v1` language; `UNRESOLVED_RESOURCE` is "
        "never a negative result.",
        "",
        "| case | split slot | contexts | prefilter survivors | compatible pairs | right scans skipped by empty left | minimum span | cache option hit | cache pair hit |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for summary in run_summaries:
        counts = summary["counts"]
        cache_stats = summary["persistent_two_run_cache"]
        report_lines.append(
            f"| {summary['case']} | {summary['split_slot']} | {counts.get('middle_contexts_processed', 0)} | "
            f"{counts.get('prefilter_survivors', 0)} | {counts.get('compatible_terminal_pairs', 0)} | "
            f"{counts.get('right_compatibility_scans_skipped_left_empty', 0)} | "
            f"{summary['minimum_compatible_span']} | {cache_stats.get('options_hit_rate', 0.0):.1%} | "
            f"{cache_stats.get('pair_hit_rate', 0.0):.1%} |"
        )
    report_lines.extend([
        "",
        "The persistent runner resumes from `progress.json`; incomplete rows remain "
        "`UNRESOLVED_RESOURCE` and are never converted to UNSAT.",
        "",
        "The allocation prefilter is a necessary-condition filter. The exact join "
        "still performs the final collision and span checks.",
        "",
        "No C9 search, unrestricted graceful search, or edge63 main-log edit was performed.",
    ])
    (args.root / "gate2_v2_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    rebuild_summary_tables(args.root)
    print(json.dumps({"ownership": ownership, "differential": differential}, ensure_ascii=False))


if __name__ == "__main__":
    main()
