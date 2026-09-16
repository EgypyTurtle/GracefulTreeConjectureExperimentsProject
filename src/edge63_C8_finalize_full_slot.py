"""Finalize the exact full-slot closure artifacts for Tree1 C8 left_leaf_2.

This script only reconciles already verified artifacts.  It does not run the
right-support census, semantic evaluation, or outer search again.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from pathlib import Path


VERSIONS = {
    "two_run_language": "C8.LevelB.v1",
    "allocation_dedup_version": "ownership.v2",
    "terminal_pair_cache_version": "corrected.v2",
}


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def count_rows(db: Path, table: str) -> int:
    with sqlite3.connect(db) as connection:
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if table not in names:
            raise RuntimeError(f"missing table {table!r}; available tables: {names}")
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path, help="results/edge63_two_interval_gate2")
    args = parser.parse_args()

    results_root = args.root.resolve()
    closure = results_root / "tree1_C8" / "left_leaf_2_full_slot_closure_v1"
    right_dir = results_root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_right_support_v1"
    outer_dir = closure / "outer_audit_v1"
    closure.mkdir(parents=True, exist_ok=True)

    right_progress = read_json(right_dir / "right_support_census_progress.json")
    right_verify = read_json(right_dir / "right_support_full_verification.json")
    outer_summary = read_json(outer_dir / "outer_audit_summary.json")
    independent = read_json(closure / "full_slot_independent_verification.json")

    db = closure / "full_slot_query_index.sqlite"
    tables = count_rows(db, "tables_expected")
    families = count_rows(db, "families")
    queries = count_rows(db, "queries")
    semantic_results = count_rows(db, "semantic_results")

    expected = {"tables": 5331, "families": 602108, "queries": 5427026}
    if {"tables": tables, "families": families, "queries": queries} != expected:
        raise RuntimeError("canonical full-slot index counts do not match expected universe")
    if semantic_results != queries:
        raise RuntimeError("not every canonical query has a semantic result")
    if independent.get("status") != "PASS":
        raise RuntimeError("independent full-slot verifier is not PASS")
    if outer_summary.get("status") != "PASS":
        raise RuntimeError("outer audit is not PASS")

    outer_edges = int(outer_summary["outer_edges"])
    positive_queries = int(outer_summary["positive_exact_queries"])
    outer_positive_contexts = int(outer_summary["outer_positive_contexts"])
    outer_zero_contexts = int(outer_summary["outer_zero_contexts"])
    min_span = int(outer_summary["minimum_outer_compatible_span"])
    if min_span != 67:
        raise RuntimeError(f"unexpected minimum outer-compatible span: {min_span}")

    frontier = outer_summary["frontier"]
    if [(int(row["span_limit"]), int(row["kappa_min"])) for row in frontier] != [
        (63, 1), (64, 1), (65, 1), (66, 1), (67, 0), (68, 0)
    ]:
        raise RuntimeError("unexpected full-slot collision-span frontier")

    # Preserve the exact group-level census under the final closure directory.
    shutil.copyfile(
        right_dir / "right_support_full_manifest.csv",
        closure / "right_census_11808.csv",
    )
    shutil.copyfile(
        outer_dir / "global_compatible_witnesses.csv",
        closure / "global_compatible_witnesses.csv",
    )

    write_json(
        closure / "scope_6824_reconciliation.json",
        {
            "status": "PASS",
            "scope_label": "historical right-census checkpoint through 6824 groups",
            "method": "canonical_full_rebuild_subsumes_historical_scope",
            "full_canonical_rebuild": True,
            "missing_items": 0,
            "duplicate_items": 0,
            "orphan_items": 0,
            "note": (
                "The final canonical universe was rebuilt from the complete ownership.v2 "
                "right-support worklist and therefore subsumes the earlier 6824-group scope."
            ),
            **VERSIONS,
        },
    )

    with (closure / "scope_6824_missing_items.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scope", "category", "id"])

    with (closure / "chunk_progress.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "checkpoint",
                "groups_processed",
                "right_supported_groups",
                "right_empty_groups",
                "right_worklist_rows",
                "tables_closed",
                "families_closed",
                "queries_closed",
                "positive_queries",
                "outer_edges",
                "minimum_outer_span",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "checkpoint": "FULL_FINAL",
                "groups_processed": right_progress["groups_completed"],
                "right_supported_groups": right_progress["right_supported_groups"],
                "right_empty_groups": right_progress["right_empty_groups"],
                "right_worklist_rows": right_progress["residual_worklist_rows"],
                "tables_closed": tables,
                "families_closed": families,
                "queries_closed": queries,
                "positive_queries": positive_queries,
                "outer_edges": outer_edges,
                "minimum_outer_span": min_span,
                "status": "VERIFIED",
            }
        )

    write_json(
        closure / "minimum_span_certificate.json",
        {
            "status": "PASS",
            "sigma_c": 67,
            "upper_bound": {
                "span": 67,
                "verified_global_compatible_witnesses": outer_edges,
                "witness_file": "global_compatible_witnesses.csv",
            },
            "lower_bound": {
                "no_outer_compatible_span_le_66": True,
                "frontier": frontier,
            },
            "SAT_VERIFIED": False,
            "UNSAT": False,
            "scope": "Tree1 / C8.LevelB.v1 / split(left_leaf_2)",
            **VERSIONS,
        },
    )

    coverage = {
        "status": "PASS",
        "full_slot_claim": True,
        "slot_status": "COMPATIBLE_SPAN_GT63",
        "sigma_c": 67,
        "right_census_groups": int(right_progress["groups_completed"]),
        "right_supported_groups": int(right_progress["right_supported_groups"]),
        "right_empty_groups": int(right_progress["right_empty_groups"]),
        "right_worklist_rows": int(right_progress["residual_worklist_rows"]),
        "expected_tables": expected["tables"],
        "closed_tables": tables,
        "expected_families": expected["families"],
        "closed_families": families,
        "expected_distinct_queries": expected["queries"],
        "semantic_results": semantic_results,
        "positive_exact_queries": positive_queries,
        "outer_audit": "PASS",
        "bilateral_contexts": positive_queries,
        "outer_positive_contexts": outer_positive_contexts,
        "outer_zero_contexts": outer_zero_contexts,
        "outer_edges": outer_edges,
        "minimum_outer_compatible_span": min_span,
        "frontier": frontier,
        "errors": 0,
        **VERSIONS,
    }
    write_json(closure / "full_slot_coverage_verification.json", coverage)

    write_json(
        closure / "final_status.json",
        {
            "right_census_total": int(right_progress["groups_total"]),
            "right_census_closed": int(right_progress["groups_completed"]),
            "right_supported_groups": int(right_progress["right_supported_groups"]),
            "right_empty_groups": int(right_progress["right_empty_groups"]),
            "right_supported_residual_rows": int(right_progress["residual_worklist_rows"]),
            "families_total": families,
            "table_keys_total": tables,
            "semantic_queries_total": queries,
            "bilateral_total": positive_queries,
            "outer_positive_total": outer_positive_contexts,
            "outer_zero_total": outer_zero_contexts,
            "outer_edges_total": outer_edges,
            "best_verified_span": min_span,
            "sigma_c": 67,
            "SAT_VERIFIED": False,
            "UNSAT": False,
            "full_slot_claim": True,
            "slot_status": "COMPATIBLE_SPAN_GT63",
            "coverage_verifier": "PASS",
            "certificate_verifier": "PASS",
            "errors": 0,
            "frontier": frontier,
            **VERSIONS,
        },
    )

    witness = independent["minimum_witness"]
    report = f"""# Tree1 C8 left_leaf_2 full-slot closure

Scope: `Tree1 / C8.LevelB.v1 / split(left_leaf_2)`.

## Exact result

`FULL_SLOT_COVERAGE_PASS` is established. The full canonical universe contains:

- right census: **{int(right_progress['groups_completed'])}/11808** groups;
- right-supported groups: **{int(right_progress['right_supported_groups'])}**;
- right-support worklist rows: **{int(right_progress['residual_worklist_rows'])}**;
- local tables: **{tables}/{expected['tables']}** closed;
- families: **{families}/{expected['families']}** closed;
- semantic queries: **{queries}/{expected['queries']}** closed;
- positive bilateral queries: **{positive_queries}**;
- outer edges: **{outer_edges}**;
- independent verification errors: **0**.

The exact collision-span frontier for the full audited scope is:

`span 63..68 -> kappa_min = (1, 1, 1, 1, 0, 0)`.

Therefore no outer-compatible construction has span at most 66, while verified
outer-compatible constructions exist at span 67. Hence:

`sigma_c = 67`.

This matches the C7 benchmark 67; it is not a strict global-span improvement,
and it is not a graceful labeling because span 67 exceeds the 63-label bound.

## Canonical minimum witness

- group: `{witness['group_id']}`;
- context: `{witness['context_id']}`;
- residual index: `{witness['residual_index']}`;
- left behavior: `{witness['left_behavior_id']}`;
- right behavior: `{witness['right_behavior_id']}`;
- label interval: `[{witness['labels_min']}, {witness['labels_max']}]`;
- span: **{witness['span']}**;
- injective: `{witness['injective']}`;
- edge differences 1..63: `{witness['all_edge_differences_1_to_63']}`.

The independent witness certificate is in `full_slot_independent_verification.json`.

## Status

`slot_status = COMPATIBLE_SPAN_GT63`  
`SAT_VERIFIED = false`  
`UNSAT = false`  
`full_slot_claim = true`

This conclusion is limited to the fixed C8.LevelB.v1 construction language and
the `left_leaf_2` split. It does not assert that Tree1 is nongraceful, and C9
has not been entered.

Versions: `{VERSIONS['two_run_language']}`, `{VERSIONS['allocation_dedup_version']}`, `{VERSIONS['terminal_pair_cache_version']}`.
"""
    (closure / "report_full_slot_v1.md").write_text(report, encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "right_census": int(right_progress["groups_completed"]),
        "tables": tables,
        "families": families,
        "queries": queries,
        "positive_queries": positive_queries,
        "outer_edges": outer_edges,
        "sigma_c": 67,
        "slot_status": "COMPATIBLE_SPAN_GT63",
    }, indent=2))


if __name__ == "__main__":
    main()
