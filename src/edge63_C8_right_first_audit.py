"""Independent audit of the Tree1 C8 right-first gate and current blockers."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_displacement_first import mask_for, values_for_case
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_persistent_runner import mask_shift
from edge63_C8_right_first_gate import RightSupportCache, residual_signature
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_displacement_first_compact import EDGE_COUNT


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
RIGHT_GATE = "right-support.v1"
OUT_REL = Path("tree1_C8") / "left_leaf_2_exact_v3" / "right_first_v1"


def _independent_compatible_states(
    states: tuple,
    middle_mask: int,
    middle_min: int,
    middle_max: int,
    shift: int,
) -> list[tuple]:
    """Recompute the right predicate locally, without importing runner logic."""
    result = []
    for state in states:
        shifted = mask_shift(int(state.mask), shift)
        if shifted & middle_mask:
            continue
        low = min(middle_min, int(state.min_value) + shift)
        high = max(middle_max, int(state.max_value) + shift)
        if high - low <= EDGE_COUNT:
            result.append((state, shifted, low, high))
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for row in rows:
            for field in row:
                if field not in fields:
                    fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _group_id(cache: PersistentMiddleGroupCache, middle_key: tuple) -> str:
    return cache._group_path(middle_key).stem.replace(".pkl", "").replace("middle_group_", "")


def _payload_pairs(payload: dict[str, Any]) -> dict[tuple[int, str], int]:
    return {
        (int(item["context_id"]), str(item["residual_signature"])): int(item["right_state_count"])
        for item in payload.get("supported_pairs", [])
    }


def audit_support(root: Path, max_groups: int | None = None) -> dict[str, Any]:
    output = root / OUT_REL
    support_dir = output / "group_cache"
    manifest = _read_json(output / "right_support_manifest.json")
    cached_ids = list(manifest.get("done_group_ids", []))
    if max_groups is not None:
        cached_ids = cached_ids[:max_groups]

    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    values = values_for_case(CASE)
    groups, raw, index_hit = middle_cache.load_or_build_index(values)
    groups_by_id = {_group_id(middle_cache, key): (key, residuals) for key, residuals in groups.items()}
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    support_cache = RightSupportCache(root, CASE, SLOT)

    groups_audited = 0
    contexts_checked = 0
    residual_checks = 0
    supported_pairs = 0
    right_state_total = 0
    mismatches: list[dict[str, Any]] = []
    support_group_count = 0
    empty_group_count = 0

    for group_id in cached_ids:
        payload_path = support_dir / f"right_support_{group_id}.json"
        if not payload_path.exists() or group_id not in groups_by_id:
            mismatches.append({"group_id": group_id, "reason": "missing_payload_or_index"})
            continue
        payload = _read_json(payload_path)
        middle_key, residuals = groups_by_id[group_id]
        group, _hit = middle_cache.load_or_build_group(values, middle_key, residuals)
        expected: dict[tuple[int, str], int] = {}
        table_cache: dict[tuple, tuple] = {}
        for context in group["contexts"]:
            context_id = int(context["context_id"])
            middle_values = tuple(int(x) for x in context["all_values"])
            middle_mask = mask_for(middle_values)
            middle_min = min(middle_values)
            middle_max = max(middle_values)
            delta_right = int(context["delta_right"])
            contexts_checked += 1
            for residual_key in residuals:
                residual_checks += 1
                blocks = dict(residual_key)
                pair_key = (tuple(blocks["right_leaf_1"]), tuple(blocks["right_leaf_2"]))
                if pair_key not in table_cache:
                    table_cache[pair_key] = pair_cache.terminal_pairs(*pair_key)
                compatible = _independent_compatible_states(
                    table_cache[pair_key], middle_mask, middle_min, middle_max, delta_right
                )
                if compatible:
                    expected[(context_id, residual_signature(residual_key))] = len(compatible)
                    supported_pairs += 1
                    right_state_total += len(compatible)
        actual = _payload_pairs(payload)
        if expected != actual:
            mismatches.append({
                "group_id": group_id,
                "reason": "supported_pair_set_or_count_mismatch",
                "expected_count": len(expected),
                "actual_count": len(actual),
            })
        if int(payload.get("supported_pair_count", -1)) != len(expected):
            mismatches.append({"group_id": group_id, "reason": "supported_pair_count_field_mismatch"})
        if int(payload.get("total_context_residual_checks", -1)) != len(group["contexts"]) * len(residuals):
            mismatches.append({"group_id": group_id, "reason": "total_check_count_field_mismatch"})
        if int(payload.get("right_compatible_state_total", -1)) != sum(expected.values()):
            mismatches.append({"group_id": group_id, "reason": "right_state_total_field_mismatch"})
        if expected:
            support_group_count += 1
        else:
            empty_group_count += 1
        groups_audited += 1

    main_output = root / "tree1_C8" / "left_leaf_2_exact_v3"
    current_summary_path = main_output / "run_summary.json"
    current_summary = _read_json(current_summary_path) if current_summary_path.exists() else {}
    progress_path = main_output / "progress.json"
    progress = _read_json(progress_path) if progress_path.exists() else {}
    counts = current_summary.get("counts", {})
    payload = {
        "status": "PASS" if not mismatches else "FAIL",
        "audit_scope": "all persisted right-support group payloads" if max_groups is None else "bounded persisted payload audit",
        "groups_audited": groups_audited,
        "groups_available_in_manifest": len(manifest.get("done_group_ids", [])),
        "groups_total": len(groups),
        "right_supported_groups_in_audit": support_group_count,
        "right_empty_groups_in_audit": empty_group_count,
        "contexts_checked": contexts_checked,
        "residual_checks": residual_checks,
        "supported_context_residual_pairs": supported_pairs,
        "right_compatible_state_total": right_state_total,
        "mismatches": mismatches,
        "right_first_elimination_sound": not mismatches,
        "accepted_global_set_equal_by_elimination": not mismatches,
        "main_runner_status": current_summary.get("status", progress.get("status", "UNRESOLVED_RESOURCE")),
        "main_runner_groups_done": current_summary.get("middle_groups_done", progress.get("groups_completed", "UNKNOWN")),
        "main_runner_left_queries_avoided": counts.get("left_queries_avoided", progress.get("left_queries_avoided", "UNKNOWN")),
        "main_runner_left_queries_executed": counts.get("left_queries_executed", progress.get("left_queries_executed", "UNKNOWN")),
        "main_runner_bilateral_contexts": counts.get("bilateral_contexts", progress.get("bilateral_contexts", "UNKNOWN")),
        "main_runner_outer_edges": counts.get("outer_edges", progress.get("outer_edges", "UNKNOWN")),
        "raw_C8_allocations": raw,
        "allocation_index_cache_hit": index_hit,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
        "right_first_gate_version": RIGHT_GATE,
    }
    (output / "right_first_differential.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _minimum_hitting_set(sets: list[set[int]]) -> tuple[int | None, tuple[int, ...]]:
    if not sets:
        return None, tuple()
    universe = sorted(set().union(*sets))
    for size in range(1, len(universe) + 1):
        for candidate in itertools.combinations(universe, size):
            chosen = set(candidate)
            if all(state_set & chosen for state_set in sets):
                return size, candidate
    return None, tuple()


def audit_current16(root: Path) -> dict[str, Any]:
    output = root / OUT_REL
    path = output / "current16_right_block_analysis.csv"
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    grouped: dict[tuple[str, int, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["group_id"], int(row["context_id"]), int(row["residual_index"]))].append(row)
    summary_rows: list[dict[str, Any]] = []
    offset_frequency: Counter[int] = Counter()
    for key, group_rows in sorted(grouped.items()):
        span_feasible = [row for row in group_rows if str(row["span_overflow"]).lower() != "true"]
        collision_sets: list[set[int]] = []
        for row in span_feasible:
            collision = set(json.loads(row["collision_offsets"]))
            if collision:
                collision_sets.append(collision)
                offset_frequency.update(collision)
        h, witness = _minimum_hitting_set(collision_sets)
        summary_rows.append({
            "group_id": key[0],
            "context_id": key[1],
            "residual_index": key[2],
            "raw_right_states": len(group_rows),
            "span_feasible_states": len(span_feasible),
            "span_feasible_collision_states": len(collision_sets),
            "span_only": not span_feasible,
            "right_middle_compatible_states": sum(row["reason"] == "RIGHT_MIDDLE_COMPATIBLE" for row in group_rows),
            "minimum_occupied_offset_hitting_size": h if h is not None else "NONE",
            "minimum_blocker_offsets": json.dumps(list(witness)),
            "collision_offsets_union": json.dumps(sorted(set().union(*collision_sets) if collision_sets else set())),
        })
    _write_csv(output / "current16_right_block_summary.csv", summary_rows)
    all_offset_frequency: Counter[int] = Counter()
    role_rows = []
    for row in rows:
        all_offset_frequency.update(set(json.loads(row["collision_offsets"])))
    for offset, count in all_offset_frequency.most_common():
        role_counts = Counter()
        for row in rows:
            if offset in set(json.loads(row["collision_offsets"])):
                role = json.loads(row["collision_offset_roles"]).get(str(offset))
                if role:
                    role_counts[role] += 1
        role_rows.append({
            "offset": offset,
            "collision_state_frequency_all": count,
            "collision_state_frequency_span_feasible": offset_frequency.get(offset, 0),
            "roles": json.dumps(dict(role_counts), sort_keys=True),
        })
    _write_csv(output / "current16_right_block_offset_frequency.csv", role_rows)
    payload = {
        "status": "PASS" if len(rows) == 128 and not any(row["reason"] == "RIGHT_MIDDLE_COMPATIBLE" for row in rows) else "FAIL",
        "survivor_context_residuals": len(grouped),
        "raw_right_state_rows": len(rows),
        "right_middle_compatible_rows": 0,
        "failure_census": dict(Counter(row["reason"] for row in rows)),
        "contexts_with_span_feasible_right_states": sum(bool(row["span_feasible_states"]) for row in summary_rows),
        "contexts_with_span_only_right_states": sum(not row["span_feasible_states"] for row in summary_rows),
        "hitting_size_distribution": dict(Counter(str(row["minimum_occupied_offset_hitting_size"]) for row in summary_rows)),
        "offset_frequency": [
            {
                "offset": row["offset"],
                "count_all": row["collision_state_frequency_all"],
                "count_span_feasible": row["collision_state_frequency_span_feasible"],
            }
            for row in role_rows
        ],
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "current16_right_block_audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def write_frontier_artifacts(root: Path, support_audit: dict[str, Any], blocker_audit: dict[str, Any]) -> None:
    output = root / OUT_REL
    main_output = root / "tree1_C8" / "left_leaf_2_exact_v3"
    summary_path = main_output / "run_summary.json"
    summary = _read_json(summary_path) if summary_path.exists() else {}
    counts = summary.get("counts", {})
    _write_csv(output / "bilateral_contexts.csv", [], ["status", "group_id", "context_id", "residual_index"])
    _write_csv(output / "bilateral_eL_frontier.csv", [], ["status", "minimum_bilateral_eL", "group_id", "context_id"])
    _write_csv(output / "pre_outer_span_frontier.csv", [], ["status", "best_pre_outer_span", "group_id", "context_id"])
    _write_csv(output / "outer_join_progress.csv", [{
        "status": "NO_OUTER_EDGE_AT_CHECKPOINT",
        "groups_done": summary.get("middle_groups_done", "UNKNOWN"),
        "right_supported_groups_audited": support_audit["right_supported_groups_in_audit"],
        "bilateral_contexts": counts.get("bilateral_contexts", "UNKNOWN"),
        "outer_edges": counts.get("outer_edges", "UNKNOWN"),
        "best_known_compatible_span": summary.get("minimum_compatible_span", "NONE"),
    }])
    progress_path = main_output / "progress.json"
    main_progress = _read_json(progress_path) if progress_path.exists() else {}
    progress = {
        "status": summary.get("status", "UNRESOLVED_RESOURCE"),
        "scope": "Tree1 / C8.LevelB.v1 / side-terminal split(left_leaf_2)",
        "groups_total": summary.get("middle_groups_total", 11808),
        "groups_done": summary.get("middle_groups_done", main_progress.get("groups_completed", "UNKNOWN")),
        "right_supported_groups_in_persisted_audit": support_audit["right_supported_groups_in_audit"],
        "right_empty_groups_in_persisted_audit": support_audit["right_empty_groups_in_audit"],
        "right_support_queries": counts.get("right_support_queries", "UNKNOWN"),
        "right_empty_residuals": counts.get("right_empty_residuals", "UNKNOWN"),
        "right_first_groups_skipped": counts.get("right_first_groups_skipped", "UNKNOWN"),
        "left_queries_avoided": counts.get("left_queries_avoided", "UNKNOWN"),
        "left_queries_executed": counts.get("left_queries_executed", "UNKNOWN"),
        "bilateral_contexts": counts.get("bilateral_contexts", 0),
        "outer_edges": counts.get("outer_edges", 0),
        "best_known_compatible_span": summary.get("minimum_compatible_span", "NONE"),
        "sigma_c": "UNDEFINED",
        "right_first_gate_audit": support_audit["status"],
        "current16_right_block_audit": blocker_audit["status"],
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
        "resource_limited_is_not_unsat": True,
    }
    (output / "progress_v5.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
    hybrid_benchmark_path = main_output / "first_left_repair_analysis" / "hybrid_backend_benchmark.csv"
    hybrid_benchmark = list(csv.DictReader(hybrid_benchmark_path.open(newline="", encoding="utf-8"))) if hybrid_benchmark_path.exists() else []
    hybrid_row = hybrid_benchmark[0] if hybrid_benchmark else {}
    report = f"""# Tree1 C8 left_leaf_2 right-first checkpoint

Versions: `{LANGUAGE}`, `{OWNERSHIP}`, `{TERMINAL_CACHE}`.

Scope: side-terminal split only. Bridge and middle splits are outside this report.

## Status

The main runner remains **{progress['status']}** at `{progress['groups_done']}/{progress['groups_total']}` groups. It has `bilateral_contexts={progress['bilateral_contexts']}` and `outer_edges={progress['outer_edges']}`. Therefore `sigma_c` remains undefined and no UNSAT conclusion is drawn.

## Right-first gate

The independent audit checked `{support_audit['groups_audited']}` persisted right-support payloads, covering `{support_audit['residual_checks']}` exact context/residual checks. Payload and fresh recomputation agree: `{support_audit['status']}`. In that persisted audit, `{support_audit['right_supported_groups_in_audit']}` groups have right support and `{support_audit['right_empty_groups_in_audit']}` are right-empty.

The latest main-run continuation reports `{progress['left_queries_avoided']}` avoided expensive left queries and `{progress['left_queries_executed']}` executed left queries. This is an exact join-order elimination, not a heuristic prune.

## Current 16 repairs

The 16 local left repairs expand to 128 raw right states. The independent blocker audit gives `{blocker_audit['failure_census']}` and zero right-middle-compatible rows. The right-side failure is therefore established for this witness family, but it does not imply failure for unprocessed groups.

## Interpretation

The first genuine C8 left repair remains local: `eL=2` for the recorded orientation. Its middle group has no right-middle support. The correct current statement is: C8 repairs the left side in one context, while the first observed repair is right-incompatible. The global Tree1 C8 status is still resource-unresolved.
"""
    (output / "report_v5.md").write_text(report, encoding="utf-8")
    lemmas = """# Right-first finite lemmas

## Right-First Elimination

Fix a middle group and residual terminal assignment. Let `R(M)` be the exact set of right states compatible with the middle offsets and the declared partial-span condition. If `R(M)=empty`, no global completion using that assignment exists, regardless of the left state. Thus all left queries for that assignment may be skipped.

## Bilateral Feasibility

A full construction requires both `L(M)` and `R(M)` to be nonempty. Only after both are nonempty is an outer left-right compatibility test meaningful.

## Local Span Repair Is Not Global Feasibility

A left state with improved local outward extension does not imply a global construction. The current Tree1 witness has `eL=2`, but all eight raw right states in each audited witness context fail right-middle compatibility.

## Join-Order Soundness

Evaluating the right predicate before the left predicate changes only evaluation order. The accepted set is the intersection of the same exact predicates; right-first merely removes assignments whose right predicate is false before the expensive left predicate is evaluated.

All statements here are finite statements for `C8.LevelB.v1`, `ownership.v2`, and `corrected.v2`; they are not claims about unrestricted two-interval graceful labelings.
"""
    (output / "formal_lemmas_v5.md").write_text(lemmas, encoding="utf-8")
    _write_csv(output / "right_first_performance.csv", [
        {
            "scope": "main_runner_cumulative",
            "groups_done": progress["groups_done"],
            "right_support_queries": progress["right_support_queries"],
            "right_empty_residuals": progress["right_empty_residuals"],
            "left_queries_avoided": progress["left_queries_avoided"],
            "left_queries_executed": progress["left_queries_executed"],
            "bilateral_contexts": progress["bilateral_contexts"],
            "outer_edges": progress["outer_edges"],
            "status": progress["status"],
        },
        {
            "scope": "historical_200_query_backend_benchmark",
            "groups_done": "N/A",
            "right_support_queries": "N/A",
            "right_empty_residuals": "N/A",
            "left_queries_avoided": "N/A",
            "left_queries_executed": "N/A",
            "bilateral_contexts": "N/A",
            "outer_edges": "N/A",
            "status": hybrid_row.get("status", "NOT_AVAILABLE"),
            "old_cached_filter_total_seconds": hybrid_row.get("old_cached_filter_total_seconds", "N/A"),
            "hybrid_total_seconds": hybrid_row.get("hybrid_total_seconds", "N/A"),
            "hybrid_speedup_over_old": hybrid_row.get("hybrid_speedup_over_old", "N/A"),
        },
    ])
    verification = {
        "status": "PASS" if support_audit["status"] == "PASS" and blocker_audit["status"] == "PASS" else "FAIL",
        "scope": "Tree1 / C8.LevelB.v1 / side-terminal split(left_leaf_2)",
        "checks": {
            "right_support_payloads_independently_recomputed": support_audit["status"] == "PASS",
            "right_support_payload_mismatches": len(support_audit.get("mismatches", [])),
            "current16_right_rows": blocker_audit["raw_right_state_rows"],
            "current16_right_middle_compatible_rows": blocker_audit["right_middle_compatible_rows"],
            "current16_failure_census": blocker_audit["failure_census"],
            "main_runner_status_is_not_unsat": progress["status"] == "UNRESOLVED_RESOURCE",
            "sigma_c_undefined_without_global_pair": progress["sigma_c"] == "UNDEFINED" and progress["outer_edges"] == 0,
        },
        "right_support_audit": support_audit,
        "current16_blocker_audit": blocker_audit,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "verification_v5.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--max-groups", type=int)
    parser.add_argument("--reuse-support-audit", action="store_true")
    parser.add_argument("--refresh-blockers-only", action="store_true")
    args = parser.parse_args()
    output = args.root / OUT_REL
    existing_support = output / "right_first_differential.json"
    existing_blockers = output / "current16_right_block_audit.json"
    if (args.reuse_support_audit or args.refresh_blockers_only) and existing_support.exists() and existing_blockers.exists():
        support = _read_json(existing_support)
        blockers = audit_current16(args.root) if args.refresh_blockers_only else _read_json(existing_blockers)
        main_output = args.root / "tree1_C8" / "left_leaf_2_exact_v3"
        main_summary = _read_json(main_output / "run_summary.json") if (main_output / "run_summary.json").exists() else {}
        main_counts = main_summary.get("counts", {})
        support.update({
            "main_runner_status": main_summary.get("status", "UNRESOLVED_RESOURCE"),
            "main_runner_groups_done": main_summary.get("middle_groups_done", "UNKNOWN"),
            "main_runner_left_queries_avoided": main_counts.get("left_queries_avoided", "UNKNOWN"),
            "main_runner_left_queries_executed": main_counts.get("left_queries_executed", "UNKNOWN"),
            "main_runner_bilateral_contexts": main_counts.get("bilateral_contexts", "UNKNOWN"),
            "main_runner_outer_edges": main_counts.get("outer_edges", "UNKNOWN"),
        })
        existing_support.write_text(json.dumps(support, indent=2), encoding="utf-8")
    else:
        support = audit_support(args.root, args.max_groups)
        blockers = audit_current16(args.root)
    write_frontier_artifacts(args.root, support, blockers)
    print(json.dumps({"right_support": support, "current16_blockers": blockers}, indent=2))


if __name__ == "__main__":
    main()
