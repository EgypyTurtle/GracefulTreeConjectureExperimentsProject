#!/usr/bin/env python3
"""Audit every positive full-slot semantic query at the concrete outer layer."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_full_slot_closure import (
    CASE,
    SLOT,
    _db_path,
    _native_cache,
    _versions,
)
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_outer_zero_audit import _audit_source
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_displacement_first import values_for_case
from edge63_displacement_first_compact import EDGE_COUNT


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _load_d13_map(root: Path, needed: set[tuple[str, int, int]]) -> dict[tuple[str, int, int], int | None]:
    path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_right_support_v1" / "right_supported_residual_worklist_full.csv"
    found: dict[tuple[str, int, int], int | None] = {}
    if not path.exists():
        return found
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("group_id", ""), int(row.get("context_id", -1)), int(row.get("residual_index", -1)))
            if key not in needed:
                continue
            value = row.get("D13", "")
            found[key] = int(value) if value not in {"", "None", "null"} else None
            if len(found) == len(needed):
                break
    return found


def _positive_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            """
            SELECT s.family_id, f.table_key, s.occupied_json, s.semantic_signature_id,
                   s.allowed_count, q.group_id, q.context_id, q.residual_index,
                   q.residual_signature
            FROM semantic_results s
            JOIN families f ON f.family_id=s.family_id
            JOIN queries q ON q.family_id=s.family_id AND q.occupied_json=s.occupied_json
            WHERE s.status='POSITIVE'
            ORDER BY q.group_id, q.context_id, q.residual_index, s.family_id, s.occupied_json
            """
        ).fetchall()
    return [
        {
            "family_id": row[0],
            "table_key": row[1],
            "occupied_values": [int(value) for value in json.loads(row[2])],
            "semantic_signature_id": row[3],
            "allowed_count": int(row[4]),
            "source": {
                "group_id": row[5],
                "context_id": int(row[6]),
                "residual_index": int(row[7]),
                "residual_signature": row[8],
            },
        }
        for row in rows
    ]


def audit(root: Path) -> dict[str, Any]:
    out = root / "tree1_C8" / "left_leaf_2_full_slot_closure_v1"
    audit_dir = out / "outer_audit_v1"
    audit_dir.mkdir(parents=True, exist_ok=True)
    db_path = _db_path(out)
    positive = _positive_rows(db_path)
    needed = {
        (item["source"]["group_id"], int(item["source"]["context_id"]), int(item["source"]["residual_index"]))
        for item in positive
    }
    d13_map = _load_d13_map(root, needed)

    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    groups_by_id = {
        middle_cache._group_path(key).stem.replace(".pkl", "").replace("middle_group_", ""): (key, residuals)
        for key, residuals in groups.items()
    }
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    compiled_index = CompiledTerminalPairIndex(root, CASE, SLOT, geometry_cache=_native_cache(root, out))

    positive_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    matrix_rows: list[dict[str, Any]] = []
    outer_edges: list[dict[str, Any]] = []
    context_keys: set[tuple[str, int, int]] = set()
    failures: list[dict[str, Any]] = []
    for item in positive:
        source = item["source"]
        source_key = (source["group_id"], source["context_id"], source["residual_index"])
        positive_rows.append({
            "family_id": item["family_id"],
            "table_key": item["table_key"],
            "semantic_signature_id": item["semantic_signature_id"],
            "allowed_count": item["allowed_count"],
            "occupied_values": json.dumps(item["occupied_values"], separators=(",", ":")),
            **source,
            "D13": d13_map.get(source_key),
        })
        try:
            audited = _audit_source(
                root,
                middle_cache,
                pair_cache,
                groups_by_id,
                item,
                source,
                compiled_index=compiled_index,
                d13_override=d13_map.get(source_key),
            )
        except Exception as exc:
            failures.append({
                "family_id": item["family_id"],
                "group_id": source["group_id"],
                "context_id": source["context_id"],
                "residual_index": source["residual_index"],
                "error": repr(exc),
            })
            continue
        key = source_key
        context_keys.add(key)
        context_rows.append({key: value for key, value in audited.items() if key not in {"matrix", "outer_edge_rows"}})
        matrix_rows.extend(audited["matrix"])
        outer_edges.extend(audited["outer_edge_rows"])

    context_status_counts = Counter(row["status"] for row in context_rows)
    edge_spans = [int(row["pre_outer_span"]) for row in outer_edges]
    pre_spans = [int(row["minimum_pre_outer_span"]) for row in context_rows if row.get("minimum_pre_outer_span") is not None]
    kappa_values = [int(row["kappa_outer"]) for row in context_rows if row.get("kappa_outer") is not None]
    frontier = []
    for span in range(63, 69):
        eligible = [int(row["intersection_size"]) for row in matrix_rows if int(row["pre_outer_span"]) <= span]
        frontier.append({"span_limit": span, "kappa_min": min(eligible) if eligible else None})

    _write_csv(audit_dir / "positive_exact_queries.csv", positive_rows)
    _write_csv(audit_dir / "bilateral_contexts.csv", context_rows)
    _write_csv(audit_dir / "outer_join_results.csv", matrix_rows)
    _write_csv(audit_dir / "global_compatible_witnesses.csv", outer_edges)
    _write_csv(audit_dir / "outer_frontier.csv", frontier)
    _write_csv(audit_dir / "outer_audit_errors.csv", failures)

    summary = {
        "status": "PASS" if not failures else "FAIL",
        "positive_exact_queries": len(positive),
        "distinct_bilateral_contexts": len(context_keys),
        "audited_context_rows": len(context_rows),
        "outer_edges": len(outer_edges),
        "outer_positive_contexts": sum(1 for row in context_rows if int(row["outer_edges"]) > 0),
        "outer_zero_contexts": sum(1 for row in context_rows if int(row["outer_edges"]) == 0),
        "minimum_outer_compatible_span": min(edge_spans) if edge_spans else None,
        "minimum_pre_outer_span": min(pre_spans) if pre_spans else None,
        "minimum_kappa": min(kappa_values) if kappa_values else None,
        "frontier": frontier,
        "context_status_counts": dict(context_status_counts),
        "d13_found": len(d13_map),
        "d13_needed": len(needed),
        "errors": len(failures),
        "right_census_total": 11808,
        "two_run_language": _versions()["two_run_language"],
        "allocation_dedup_version": _versions()["allocation_dedup_version"],
        "terminal_pair_cache_version": _versions()["terminal_pair_cache_version"],
    }
    (audit_dir / "outer_audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (audit_dir / "full_slot_outer_verification.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    args = parser.parse_args()
    print(json.dumps(audit(args.root), indent=2))
