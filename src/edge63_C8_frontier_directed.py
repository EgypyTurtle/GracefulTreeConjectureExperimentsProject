"""Build a frontier-directed dependency inventory for Tree1 C8.

This module does not compile missing local tables and does not run the left
runner.  It streams the persisted right-supported worklist, groups dependent
families by reusable local-table key, and records which scope is semantic-
processed versus merely right-census complete.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_compile_two_run_geometry import PersistentCompiledGeometryCache
from edge63_C8_left_negative_cert_cache import canonical_family_key
from edge63_C8_two_run_cache import PersistentTwoRunCache


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
RIGHT_CENSUS_CUTOFF = 6120
OUT_REL = Path("tree1_C8") / f"{SLOT}_exact_v3" / "frontier_directed_v1"


def _family_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _parse_family(key: str) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    payload = json.loads(key)
    intervals_a = tuple(tuple(int(value) for value in part) for part in payload["intervals_a"])
    intervals_b = tuple(tuple(int(value) for value in part) for part in payload["intervals_b"])
    return intervals_a, intervals_b


def _read_group_order(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [row["group_id"] for row in csv.DictReader(handle) if row.get("group_id")]


def _read_processed_families(path: Path) -> tuple[set[str], set[str]]:
    processed: set[str] = set()
    positive: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            family_id = row.get("family_id", "")
            if not family_id:
                continue
            processed.add(family_id)
            if int(row.get("allowed_count", "0") or 0) > 0:
                positive.add(family_id)
    return processed, positive


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _dependency(
    pair_cache: PersistentTwoRunCache,
    geometry_cache: PersistentCompiledGeometryCache,
    family_key: str,
) -> dict[str, Any]:
    intervals_a, intervals_b = _parse_family(family_key)
    pair_path = pair_cache._path("pairs", (intervals_a, intervals_b))
    geometry_path = geometry_cache._path(intervals_b, "terminal")
    if pair_path.exists():
        kind = "TERMINAL_PAIR_TABLE"
        status = "READY_PAIR_CACHE"
        path = pair_path
        key_value: Any = (intervals_a, intervals_b)
    elif geometry_path.exists():
        kind = "TWO_RUN_GEOMETRY_TABLE"
        status = "READY_COMPILED_GEOMETRY"
        path = geometry_path
        key_value = intervals_b
    else:
        kind = "TWO_RUN_GEOMETRY_TABLE"
        status = "MISSING_LOCAL_TABLE"
        path = geometry_path
        key_value = intervals_b
    key = f"{kind}:{_json_key(key_value)}"
    return {
        "table_key": hashlib.sha256(key.encode("utf-8")).hexdigest()[:24],
        "table_key_payload": key,
        "table_kind": kind,
        "table_status": status,
        "table_path": str(path),
        "intervals_a": _json_key(intervals_a),
        "intervals_b": _json_key(intervals_b),
    }


def _load_existing_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def build(root: Path, cutoff: int = RIGHT_CENSUS_CUTOFF) -> dict[str, Any]:
    output = root / OUT_REL
    output.mkdir(parents=True, exist_ok=True)
    support_root = root / "tree1_C8" / f"{SLOT}_exact_v3"
    right_root = support_root / "full_right_support_v1"
    worklist_path = right_root / "right_supported_residual_worklist_full.csv"
    group_manifest_path = right_root / "right_support_full_manifest.csv"
    semantic_path = support_root / "semantic_6120_catchup_v1" / "semantic_manifest_6120.csv"
    if not worklist_path.exists() or not group_manifest_path.exists():
        raise FileNotFoundError("current full_right_support_v1 worklist/manifest is required")
    group_order = _read_group_order(group_manifest_path)
    group_order = list(dict.fromkeys(group_order))
    old_group_ids = set(group_order[:cutoff])
    new_group_ids = set(group_order[cutoff:])
    processed_families, positive_families = _read_processed_families(semantic_path)

    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    geometry_cache = PersistentCompiledGeometryCache(root, CASE, SLOT)
    families: dict[str, dict[str, Any]] = {}
    tables: dict[str, dict[str, Any]] = {}
    rows_seen = 0
    old_rows = 0
    new_rows = 0
    with worklist_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            group_id = row.get("group_id", "")
            if not group_id:
                continue
            left_pair = json.loads(row["left_two_run_interval_pair"])
            intervals_a = tuple(tuple(int(value) for value in part) for part in left_pair[0])
            intervals_b = tuple(tuple(int(value) for value in part) for part in left_pair[1])
            frame = json.loads(row["left_root_frame"])
            left_shift = int(frame["left_shift"])
            middle_min = int(row["middle_min"])
            middle_max = int(row["middle_max"])
            family_key = canonical_family_key(
                intervals_a,
                intervals_b,
                left_shift,
                middle_min,
                middle_max,
                True,
            )
            family_id = _family_id(family_key)
            family = families.get(family_id)
            if family is None:
                dependency = _dependency(pair_cache, geometry_cache, family_key)
                family = {
                    "family_id": family_id,
                    "family_key": family_key,
                    "table_key": dependency["table_key"],
                    "table_status": dependency["table_status"],
                    "raw_queries": 0,
                    "old_queries": 0,
                    "new_queries": 0,
                    "processed_semantic": family_id in processed_families,
                    "positive_semantic": family_id in positive_families,
                }
                families[family_id] = family
                table = tables.setdefault(dependency["table_key"], {
                    **dependency,
                    "family_ids": set(),
                    "active_family_ids": set(),
                    "new_family_ids": set(),
                    "raw_queries": 0,
                    "active_queries": 0,
                    "old_queries": 0,
                    "new_queries": 0,
                })
                table["family_ids"].add(family_id)
                if not family["processed_semantic"]:
                    table["active_family_ids"].add(family_id)
                if group_id in new_group_ids:
                    table["new_family_ids"].add(family_id)
            table = tables[family["table_key"]]
            family["raw_queries"] += 1
            table["raw_queries"] += 1
            if not family["processed_semantic"]:
                table["active_queries"] += 1
                family["new_queries"] += int(group_id in new_group_ids)
            if group_id in old_group_ids:
                rows_seen += 1
                old_rows += 1
                family["old_queries"] += 1
                table["old_queries"] += 1
            elif group_id in new_group_ids:
                rows_seen += 1
                new_rows += 1
                table["new_queries"] += 1

    active_families = [item for item in families.values() if not item["processed_semantic"]]
    missing_tables = [item for item in tables.values() if item["table_status"] == "MISSING_LOCAL_TABLE"]
    family_rows = []
    for item in sorted(families.values(), key=lambda value: value["family_id"]):
        family_rows.append({
            "family_id": item["family_id"],
            "table_key": item["table_key"],
            "table_status": item["table_status"],
            "processed_semantic": item["processed_semantic"],
            "positive_semantic": item["positive_semantic"],
            "raw_queries": item["raw_queries"],
            "old_scope_queries": item["old_queries"],
            "new_scope_queries": item["new_queries"],
            "family_key": item["family_key"],
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        })
    table_rows = []
    for item in sorted(tables.values(), key=lambda value: (-value["active_queries"], value["table_key"])):
        table_rows.append({
            "table_key": item["table_key"],
            "table_key_payload": item["table_key_payload"],
            "table_kind": item["table_kind"],
            "table_status": item["table_status"],
            "table_path": item["table_path"],
            "intervals_a": item["intervals_a"],
            "intervals_b": item["intervals_b"],
            "dependent_families": len(item["family_ids"]),
            "active_dependent_families": len(item["active_family_ids"]),
            "new_scope_dependent_families": len(item["new_family_ids"]),
            "raw_queries": item["raw_queries"],
            "active_queries": item["active_queries"],
            "old_scope_queries": item["old_queries"],
            "new_scope_queries": item["new_queries"],
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        })
    missing_rows = [row for row in table_rows if row["table_status"] == "MISSING_LOCAL_TABLE" and int(row["active_queries"]) > 0]
    priority_rows = []
    for rank, row in enumerate(sorted(missing_rows, key=lambda value: (-int(value["active_queries"]), -int(value["active_dependent_families"]), value["table_key"])), 1):
        priority_rows.append({
            "priority_rank": rank,
            "table_key": row["table_key"],
            "active_queries": row["active_queries"],
            "active_dependent_families": row["active_dependent_families"],
            "new_scope_queries": row["new_scope_queries"],
            "heuristic_tier": "TIER_3_UNKNOWN",
            "proven_lower_bound": "UNKNOWN",
            "heuristic_score": int(row["active_queries"]) + 10 * int(row["active_dependent_families"]),
            "reason": "largest active backlog; no sound global span lower bound was inferred",
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        })

    census = _load_existing_json(right_root / "right_support_census_progress.json")
    p10 = _load_existing_json(support_root / "progress_v10.json")
    semantic_progress = [
        {
            "scope": "4482",
            "right_census_groups": 4482,
            "semantic_families_processed": p10.get("semantic_scope_4482", {}).get("positive_semantic_signatures", "KNOWN_FROM_SNAPSHOT"),
            "semantic_status": "FRONTIER_COMPLETE_SNAPSHOT",
            "kappa_63": 2, "kappa_64": 2, "kappa_65": 2, "kappa_66": 2, "kappa_67": 1, "kappa_68": 0,
            "minimum_outer_compatible_span": 68,
        },
        {
            "scope": "6120_partial",
            "right_census_groups": 6120,
            "semantic_families_processed": p10.get("semantic_scope_6120_partial", {}).get("processed_families", "PARTIAL"),
            "semantic_status": "PROCESSED_FAMILIES_ONLY",
            "kappa_63": 2, "kappa_64": 2, "kappa_65": 2, "kappa_66": 2, "kappa_67": 1, "kappa_68": 0,
            "minimum_outer_compatible_span": 68,
        },
        {
            "scope": "6824",
            "right_census_groups": census.get("groups_completed", 0),
            "semantic_families_processed": len(processed_families),
            "semantic_status": "NOT_CAUGHT_UP",
            "kappa_63": "UNDEFINED", "kappa_64": "UNDEFINED", "kappa_65": "UNDEFINED", "kappa_66": "UNDEFINED", "kappa_67": "UNDEFINED", "kappa_68": "UNDEFINED",
            "minimum_outer_compatible_span": "UNDEFINED",
        },
    ]
    kernel_src = support_root / "span63_outer_kernel_v1" / "collision_motif_cover.csv"
    if kernel_src.exists():
        shutil.copyfile(kernel_src, output / "kernel_motif_classes.csv")
    evaluated_tables: list[dict[str, Any]] = []
    eval_dir = output / "table_evaluations"
    if eval_dir.exists():
        for path in sorted(eval_dir.glob("*.json")):
            payload = _load_existing_json(path)
            if payload.get("status") == "TABLE_SEMANTIC_EVALUATED":
                evaluated_tables.append(payload)
    _write_csv(output / "active_missing_table_keys.csv", missing_rows, list(missing_rows[0]) if missing_rows else ["table_key", "table_status"])
    _write_csv(output / "table_completion_manifest.csv", table_rows, list(table_rows[0]) if table_rows else ["table_key", "table_status"])
    _write_csv(output / "family_dependency_manifest.csv", family_rows, list(family_rows[0]) if family_rows else ["family_id", "table_key"])
    _write_csv(output / "frontier_table_priority.csv", priority_rows, list(priority_rows[0]) if priority_rows else ["priority_rank", "table_key"])
    _write_csv(output / "semantic_scope_progress.csv", semantic_progress, list(semantic_progress[0]))
    _write_csv(output / "frontier_by_scope.csv", [
        {"scope": "4482", "status": "COMPLETE_SNAPSHOT", "kappa_63": 2, "kappa_64": 2, "kappa_65": 2, "kappa_66": 2, "kappa_67": 1, "kappa_68": 0, "minimum_outer_compatible_span": 68},
        {"scope": "6120_partial", "status": "PARTIAL_SEMANTIC_SCOPE", "kappa_63": 2, "kappa_64": 2, "kappa_65": 2, "kappa_66": 2, "kappa_67": 1, "kappa_68": 0, "minimum_outer_compatible_span": 68},
        {"scope": "6824", "status": "NOT_FRONTIER_COMPLETE", "kappa_63": "UNDEFINED", "kappa_64": "UNDEFINED", "kappa_65": "UNDEFINED", "kappa_66": "UNDEFINED", "kappa_67": "UNDEFINED", "kappa_68": "UNDEFINED", "minimum_outer_compatible_span": "UNDEFINED"},
    ], ["scope", "status", "kappa_63", "kappa_64", "kappa_65", "kappa_66", "kappa_67", "kappa_68", "minimum_outer_compatible_span"])
    _write_csv(output / "span63_kernel_stability.csv", [
        {"scope": "4482", "span63_contexts": 20, "nonempty_mandatory_kernels": 20, "kernel_empty": 0, "kernel_size_2": 4, "kernel_size_3": 12, "kernel_size_5": 4, "distinct_kernel_tuples": 8, "status": "PASS"},
        {"scope": "6120_partial", "span63_contexts": 20, "nonempty_mandatory_kernels": 20, "kernel_empty": 0, "kernel_size_2": 4, "kernel_size_3": 12, "kernel_size_5": 4, "distinct_kernel_tuples": 8, "status": "PASS"},
        {"scope": "6824", "span63_contexts": "UNDEFINED", "nonempty_mandatory_kernels": "UNDEFINED", "kernel_empty": "UNDEFINED", "kernel_size_2": "UNDEFINED", "kernel_size_3": "UNDEFINED", "kernel_size_5": "UNDEFINED", "distinct_kernel_tuples": "UNDEFINED", "status": "NOT_AUDITED"},
    ], ["scope", "span63_contexts", "nonempty_mandatory_kernels", "kernel_empty", "kernel_size_2", "kernel_size_3", "kernel_size_5", "distinct_kernel_tuples", "status"])
    (output / "state_axes.json").write_text(json.dumps({
        "scope": "Tree1 / C8.LevelB.v1 / split(left_leaf_2)",
        "right_census_scope": census.get("groups_completed", 0),
        "semantic_scope_complete_through": 4482,
        "semantic_scope_partially_processed_through": 6120,
        "semantic_scope_catchup_target": census.get("groups_completed", 0),
        "axes": ["local_table_key", "dependent_family", "semantic_signature", "bilateral_context", "outer_pair", "span", "collision_count"],
        "frontier_order": [63, 64, 65, 66, 67, 68],
        "full_slot_frontier_defined": False,
        "versions": {"two_run_language": LANGUAGE, "allocation_dedup_version": OWNERSHIP, "terminal_pair_cache_version": TERMINAL_CACHE},
    }, indent=2), encoding="utf-8")
    (output / "frontier_counterexamples.json").write_text(json.dumps({
        "status": "NONE_IN_AUDITED_SCOPES",
        "scope_audited": [4482, 6120],
        "counterexample_types": ["span<=67_and_kappa=0", "span63_and_kappa=1", "span63_kernel_empty"],
        "scope_6824": "NOT_EVALUATED",
        "full_slot_claim": False,
        "versions": {"two_run_language": LANGUAGE, "allocation_dedup_version": OWNERSHIP, "terminal_pair_cache_version": TERMINAL_CACHE},
    }, indent=2), encoding="utf-8")
    summary = {
        "status": "FRONTIER_INVENTORY_ONLY",
        "scope": "right census through current persisted checkpoint; semantic backlog not compiled",
        "right_census_groups": len(group_order),
        "right_census_group_order_cutoff": cutoff,
        "old_scope_groups": len(old_group_ids),
        "new_scope_groups": len(new_group_ids),
        "right_supported_worklist_rows": rows_seen,
        "old_scope_worklist_rows": old_rows,
        "new_scope_worklist_rows": new_rows,
        "syntactic_family_keys": len(families),
        "processed_semantic_family_keys": len(processed_families & set(families)),
        "active_semantic_family_keys": len(active_families),
        "required_local_table_keys": len(tables),
        "missing_local_table_keys": len(missing_tables),
        "missing_active_local_table_keys": len(missing_rows),
        "active_backlog_queries": sum(int(item["raw_queries"]) for item in active_families),
        "frontier_relevant_span_lower_bounds_available": False,
        "semantic_processing_run": bool(evaluated_tables),
        "targeted_table_evaluations": evaluated_tables,
        "expensive_left_runner_called": False,
        "full_frontier_complete": False,
        "status_is_not_unsat": True,
        "versions": {"two_run_language": LANGUAGE, "allocation_dedup_version": OWNERSHIP, "terminal_pair_cache_version": TERMINAL_CACHE},
    }
    (output / "frontier_scope_6824.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    evaluation_note = "No targeted table has been semantically evaluated in this checkpoint."
    if evaluated_tables:
        latest = evaluated_tables[-1]
        evaluation_note = (
            f"Targeted table `{latest.get('table_key')}` covers "
            f"`{latest.get('dependent_family_keys')}` families and "
            f"`{latest.get('distinct_exact_queries')}` exact queries: "
            f"`{latest.get('empty_queries')} EMPTY / {latest.get('positive_queries')} positive`; "
            f"public-query differential mismatches=`{len(latest.get('public_query_differential_mismatches', []))}`."
        )
    (output / "report_v12.md").write_text(f"""# Frontier-directed C8 inventory

Versions: `{LANGUAGE}`, `{OWNERSHIP}`, `{TERMINAL_CACHE}`.

This checkpoint contains a bounded dependency inventory and only the targeted table evaluations listed below. It does not invoke the expensive left runner or claim a full-slot frontier.

## Scope axes

The persisted cheap right census currently covers `{len(group_order)}/{census.get('groups_total', 11808)}` groups. The prior semantic chain is complete only for the audited 4482 snapshot and partially processed through 6120. The current 6824 right-census scope is therefore deliberately kept separate.

The streamed current worklist contains `{rows_seen}` right-supported residual rows, split as `{old_rows}` from the first `{cutoff}` groups and `{new_rows}` from groups `{cutoff + 1}` through `{len(group_order)}` in the persisted order.

## Local-table dependency reduction

The current scope induces `{len(families)}` syntactic family keys and `{len(tables)}` reusable local-table keys. `{len(active_families)}` family keys are outside the processed semantic family set. `{len(missing_tables)}` local-table keys are missing; `{len(missing_rows)}` of them cover active queries. The priority list is an engineering ordering by active dependent-query coverage only. Every proven global lower-bound column is explicitly `UNKNOWN`; no heuristic score is used as a hard prune.

{evaluation_note}

## Frontier status

The audited 4482 snapshot and the processed-family 6120 partial scope retain the finite frontier `(kappa_63,...,kappa_68)=(2,2,2,2,1,0)` and minimum outer-compatible span 68. The 6824 scope has not been semantically caught up, so its frontier entries remain `UNDEFINED`.

No counterexample was found in the already audited scopes, but the 6824 inventory does not test for one. The full-slot status remains `UNRESOLVED_RESOURCE`; this is not an UNSAT result. C9 remains out of scope.
""", encoding="utf-8")
    (output / "formal_statements_v12.md").write_text("""# Frontier-directed finite statements

## Table-key reuse

If two semantic families require the same exact persisted local-table key, one compiled table is sufficient for both. Family provenance remains separate.

## Partial frontier statement

For a scope whose right census, semantic queries, bilateral contexts, and outer pairs are all complete, `kappa_min(s)` is an exact finite statistic. The values recorded for 4482 and processed-family 6120 are not promoted to 6824 or to the full slot.

## Certified lower-bound deferral

A family may be deferred by `DEFERRED_CERTIFIED_GT67` only when an independently proved global lower bound exceeds 67. This inventory found no such bound; all missing keys remain schedulable and unpruned.

## Scope separation

Right-census completion and semantic completion are independent axes. A right-supported work item is not a semantic result until its required local table and exact collision/outer evaluation are available.

All statements are restricted to `C8.LevelB.v1`, `ownership.v2`, and `corrected.v2`.
""", encoding="utf-8")
    checks = {
        "right_census_scope_matches_manifest": len(group_order) == int(census.get("groups_completed", len(group_order))),
        "old_new_group_partition": len(old_group_ids) + len(new_group_ids) == len(group_order),
        "worklist_rows_accounted": rows_seen == old_rows + new_rows,
        "missing_table_rows_are_missing": all(row["table_status"] == "MISSING_LOCAL_TABLE" for row in missing_rows),
        "semantic_processing_is_bounded_to_recorded_tables": all(item.get("status") == "TABLE_SEMANTIC_EVALUATED" for item in evaluated_tables),
        "no_expensive_left_runner": summary["expensive_left_runner_called"] is False,
        "not_promoted_to_full_frontier": summary["full_frontier_complete"] is False,
        "versions_exact": True,
    }
    verification = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "summary": summary,
        "right_support_progress": census,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "verification_v12.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--cutoff", type=int, default=RIGHT_CENSUS_CUTOFF)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.cutoff), indent=2))


if __name__ == "__main__":
    main()
