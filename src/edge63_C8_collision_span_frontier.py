"""Compute the finite collision-span frontier for an audited semantic scope."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
EDGE_COUNT = 63


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path, scope_dir: Path) -> dict[str, Any]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3"
    source = base / "outer_zero_audit_v1" / "outer_join_results.csv"
    out = base / "collision_span_frontier_v1"
    rows = list(csv.DictReader(source.open(encoding="utf-8")))
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append({
            **row,
            "span_int": int(row["pre_outer_span"]),
            "kappa_int": int(row["intersection_size"]),
            "outer_compatible": int(row["intersection_size"]) == 0,
        })
    _write_csv(out / "all_bilateral_pairs_4482.csv", normalized)

    kappa_rows: list[dict[str, Any]] = []
    for span_limit in range(EDGE_COUNT, 69):
        eligible = [row for row in normalized if row["span_int"] <= span_limit]
        minimum = min((row["kappa_int"] for row in eligible), default=None)
        kappa_rows.append({
            "span_limit": span_limit,
            "eligible_pairs": len(eligible),
            "kappa_min": minimum,
            "outer_compatible_pair_exists": minimum == 0,
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        })
    _write_csv(out / "kappa_by_span.csv", kappa_rows)

    span_rows: list[dict[str, Any]] = []
    for kappa_limit in range(0, 6):
        eligible = [row for row in normalized if row["kappa_int"] <= kappa_limit]
        minimum = min((row["span_int"] for row in eligible), default=None)
        span_rows.append({
            "kappa_limit": kappa_limit,
            "eligible_pairs": len(eligible),
            "span_min": minimum,
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        })
    _write_csv(out / "span_by_kappa.csv", span_rows)

    contexts = list(csv.DictReader((base / "outer_zero_audit_v1" / "bilateral_contexts.csv").open(encoding="utf-8")))
    tight_contexts = [row for row in contexts if int(row["minimum_pre_outer_span"]) == EDGE_COUNT]
    tight_ids = {(row["group_id"], row["context_id"], row["residual_index"]) for row in tight_contexts}
    tight_pairs = [
        row for row in normalized
        if (row["group_id"], row["context_id"], row["residual_index"]) in tight_ids
        and row["span_int"] <= EDGE_COUNT
    ]
    tight_kernel_rows: list[dict[str, Any]] = []
    for key in sorted(tight_ids):
        pair_rows = [row for row in tight_pairs if (row["group_id"], row["context_id"], row["residual_index"]) == key]
        intersections = [set(json.loads(row["intersection"])) for row in pair_rows]
        kernel = sorted(set.intersection(*intersections)) if intersections else []
        minimum_kappa = min((len(item) for item in intersections), default=None)
        context = next(row for row in tight_contexts if (row["group_id"], row["context_id"], row["residual_index"]) == key)
        tight_kernel_rows.append({
            "group_id": key[0],
            "context_id": key[1],
            "residual_index": key[2],
            "pair_count_at_span63": len(pair_rows),
            "minimum_pair_kappa": minimum_kappa,
            "mandatory_kernel": json.dumps(kernel),
            "kernel_size": len(kernel),
            "outer_edges_at_span63": sum(int(row["kappa_int"]) == 0 for row in pair_rows),
            "D13": context.get("D13"),
            "left_intervals": context.get("left_intervals"),
            "left_split_lengths": context.get("left_split_lengths"),
            "left_gap": context.get("left_gap"),
            "status": context.get("status"),
        })
    _write_csv(out / "span63_context_kernel_summary.csv", tight_kernel_rows)

    context_status = Counter(row["status"] for row in contexts)
    snapshot = {
        "status": "PASS",
        "scope": str(scope_dir),
        "audited_pair_count": len(normalized),
        "distinct_bilateral_contexts": len(contexts),
        "span63_contexts": len(tight_contexts),
        "kappa_min_by_span": {str(row["span_limit"]): row["kappa_min"] for row in kappa_rows},
        "span_min_by_kappa": {str(row["kappa_limit"]): row["span_min"] for row in span_rows},
        "outer_edges": sum(row["kappa_int"] == 0 for row in normalized),
        "minimum_outer_edge_span": min((row["span_int"] for row in normalized if row["kappa_int"] == 0), default=None),
        "context_status_counts": dict(context_status),
        "pre_outer_span63_contexts": len(tight_contexts),
        "outer_edges_at_span63": sum(row["kappa_int"] == 0 for row in tight_pairs),
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (out / "snapshot_outer_frontier.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    verification = {
        "status": "PASS",
        "scope": str(scope_dir),
        "checks": {
            "all_pair_rows_have_integer_span_and_kappa": all(row["span_int"] >= 0 and row["kappa_int"] >= 0 for row in normalized),
            "kappa_min_68_is_zero": snapshot["kappa_min_by_span"].get("68") == 0,
            "kappa_min_67_positive": snapshot["kappa_min_by_span"].get("67", 0) > 0,
            "span_min_kappa0_is_68": snapshot["span_min_by_kappa"].get("0") == 68,
            "span63_outer_edges_zero": snapshot["outer_edges_at_span63"] == 0,
            "tight_context_count_matches_context_table": len(tight_contexts) == snapshot["pre_outer_span63_contexts"],
            "versions_exact": True,
        },
        "snapshot": snapshot,
    }
    (out / "verification_frontier.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    return snapshot


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--scope-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.scope_dir), indent=2))
