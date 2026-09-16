#!/usr/bin/env python3
"""Independent final verifier for the full C8 left_leaf_2 closure."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from edge63_C8_displacement_first import build_layout, build_relative_labels, values_for_case
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_persistent_runner import block_map_for
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_full_slot_closure import CASE, SLOT, _db_path, _versions


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _verify_counts(out: Path) -> dict[str, Any]:
    with sqlite3.connect(_db_path(out)) as db:
        tables = int(db.execute("SELECT COUNT(*) FROM tables_expected").fetchone()[0])
        closed_tables = int(db.execute("SELECT COUNT(*) FROM table_state WHERE status=?", ("SEMANTIC_DONE",)).fetchone()[0])
        families = int(db.execute("SELECT COUNT(*) FROM families").fetchone()[0])
        closed_families = int(db.execute("SELECT COUNT(*) FROM family_state WHERE status=?", ("SEMANTIC_DONE",)).fetchone()[0])
        queries = int(db.execute("SELECT COUNT(*) FROM queries").fetchone()[0])
        semantic = int(db.execute("SELECT COUNT(*) FROM semantic_results").fetchone()[0])
        positives = int(db.execute("SELECT COUNT(*) FROM semantic_results WHERE status=?", ("POSITIVE",)).fetchone()[0])
    expected = {"tables": 5331, "families": 602108, "queries": 5427026}
    actual = {
        "tables": tables, "closed_tables": closed_tables,
        "families": families, "closed_families": closed_families,
        "queries": queries, "semantic_results": semantic, "positive_queries": positives,
    }
    actual["counts_pass"] = (
        tables == expected["tables"] == closed_tables
        and families == expected["families"] == closed_families
        and queries == expected["queries"] == semantic
    )
    return {"expected": expected, "actual": actual}


def _verify_outer_rows(out: Path) -> dict[str, Any]:
    audit = out / "outer_audit_v1"
    context_rows = _read_rows(audit / "bilateral_contexts.csv")
    matrix_rows = _read_rows(audit / "outer_join_results.csv")
    edge_rows = _read_rows(audit / "global_compatible_witnesses.csv")
    positive_rows = _read_rows(audit / "positive_exact_queries.csv")
    by_context: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in matrix_rows:
        key = (row["group_id"], row["context_id"], row["residual_index"])
        by_context.setdefault(key, []).append(row)
    context_pass = True
    recomputed_edges = 0
    recomputed_min_span: int | None = None
    for context in context_rows:
        key = (context["group_id"], context["context_id"], context["residual_index"])
        cells = by_context.get(key, [])
        edges = [cell for cell in cells if int(cell["intersection_size"]) == 0]
        recomputed_edges += len(edges)
        if edges:
            span = min(int(cell["pre_outer_span"]) for cell in edges)
            recomputed_min_span = span if recomputed_min_span is None else min(recomputed_min_span, span)
        if len(edges) != int(context["outer_edges"]):
            context_pass = False
        if cells and int(context["minimum_pre_outer_span"]) != min(int(cell["pre_outer_span"]) for cell in cells):
            context_pass = False
    edge_pass = recomputed_edges == len(edge_rows) and recomputed_min_span == 67
    frontier = []
    for limit in range(63, 69):
        eligible = [int(row["intersection_size"]) for row in matrix_rows if int(row["pre_outer_span"]) <= limit]
        frontier.append({"span_limit": limit, "kappa_min": min(eligible) if eligible else None})
    return {
        "positive_exact_queries": len(positive_rows),
        "bilateral_context_rows": len(context_rows),
        "matrix_rows": len(matrix_rows),
        "outer_edge_rows": len(edge_rows),
        "recomputed_outer_edges": recomputed_edges,
        "minimum_outer_edge_span": recomputed_min_span,
        "frontier": frontier,
        "context_consistency_pass": context_pass,
        "edge_consistency_pass": edge_pass,
    }


def _verify_minimum_witness(root: Path, out: Path) -> dict[str, Any]:
    edge_rows = _read_rows(out / "outer_audit_v1" / "global_compatible_witnesses.csv")
    edge = min(edge_rows, key=lambda row: int(row["pre_outer_span"]))
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    group_map = {
        middle_cache._group_path(key).stem.replace(".pkl", "").replace("middle_group_", ""): (key, residuals)
        for key, residuals in groups.items()
    }
    middle_key, residuals = group_map[edge["group_id"]]
    group, _ = middle_cache.load_or_build_group(values, middle_key, residuals)
    context = next(item for item in group["contexts"] if int(item["context_id"]) == int(edge["context_id"]))
    residual_key, run_order = list(residuals.items())[int(edge["residual_index"])]
    blocks = block_map_for(middle_key, residual_key)
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    left_table = pair_cache.terminal_pairs(tuple(blocks["left_leaf_1"]), tuple(blocks["left_leaf_2"]))
    right_table = pair_cache.terminal_pairs(tuple(blocks["right_leaf_1"]), tuple(blocks["right_leaf_2"]))
    left_global = set(int(value) for value in json.loads(edge["left_global_private_offsets"]))
    right_global = set(int(value) for value in json.loads(edge["right_global_private_offsets"]))
    delta_left = int(context["delta_left"])
    delta_right = int(context["delta_right"])
    left_shift = -delta_left
    right_shift = delta_right
    left_state = next(state for state in left_table if {int(value) + left_shift for value in state.private} == left_global)
    right_state = next(state for state in right_table if {int(value) + right_shift for value in state.private} == right_global)
    labels, relative = build_relative_labels(values, context, left_state, right_state, delta_left, delta_right)
    layout = build_layout(values)
    differences: list[int] = []
    for path, intervals in blocks.items():
        observed = sorted(abs(int(relative[u]) - int(relative[v])) for u, v in zip(layout[path], layout[path][1:]))
        expected = sorted(value for start, end in intervals for value in range(start, end + 1))
        if observed != expected:
            raise AssertionError({"path": path, "observed": observed, "expected": expected})
        differences.extend(observed)
    offset_values = list(relative.values())
    result = {
        "group_id": edge["group_id"],
        "context_id": int(edge["context_id"]),
        "residual_index": int(edge["residual_index"]),
        "split_blocks": {path: [list(interval) for interval in intervals] for path, intervals in blocks.items()},
        "run_order": list(run_order),
        "left_behavior_id": int(edge["left_behavior_id"]),
        "right_behavior_id": int(edge["right_behavior_id"]),
        "labels_min": min(offset_values),
        "labels_max": max(offset_values),
        "span": max(offset_values) - min(offset_values),
        "injective": len(offset_values) == 64 and len(set(offset_values)) == 64,
        "outer_intersection": sorted(left_global & right_global),
        "all_edge_differences_1_to_63": sorted(differences) == list(range(1, 64)),
        "expected_edge_span": int(edge["pre_outer_span"]),
        "versions": _versions(),
    }
    result["pass"] = (
        result["span"] == 67
        and result["injective"]
        and result["outer_intersection"] == []
        and result["all_edge_differences_1_to_63"]
    )
    (out / "span67_global_witness_verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def verify(root: Path) -> dict[str, Any]:
    out = root / "tree1_C8" / "left_leaf_2_full_slot_closure_v1"
    counts = _verify_counts(out)
    outer = _verify_outer_rows(out)
    witness = _verify_minimum_witness(root, out)
    result = {
        "status": "PASS" if counts["actual"]["counts_pass"] and outer["context_consistency_pass"] and outer["edge_consistency_pass"] and witness["pass"] else "FAIL",
        "counts": counts,
        "outer": outer,
        "minimum_witness": witness,
        "right_census_groups": 11808,
        "coverage_claim": "FULL_SEMANTIC_AND_OUTER_AUDIT" if counts["actual"]["counts_pass"] and outer["edge_consistency_pass"] else "INCOMPLETE",
        "two_run_language": _versions()["two_run_language"],
        "allocation_dedup_version": _versions()["allocation_dedup_version"],
        "terminal_pair_cache_version": _versions()["terminal_pair_cache_version"],
    }
    (out / "full_slot_independent_verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    args = parser.parse_args()
    print(json.dumps(verify(args.root), indent=2))
