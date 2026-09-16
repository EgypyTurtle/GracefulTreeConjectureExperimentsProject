"""Audit concrete outer joins for positive semantic bilateral queries.

This is an exact finite audit over a persisted semantic scope.  It does not
run the left main runner and it never promotes a partial scope to an
exhaustive C8 conclusion.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import pickle
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_right_first_gate import _compatible_states, residual_signature
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_displacement_first import mask_for, values_for_case
from edge63_displacement_first_compact import EDGE_COUNT, _label_mask


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _family_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _read_pickle(path: Path) -> Any:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _parse_family(key: str) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...], int, int, int]:
    payload = json.loads(key)
    return (
        tuple(tuple(int(value) for value in part) for part in payload["intervals_a"]),
        tuple(tuple(int(value) for value in part) for part in payload["intervals_b"]),
        int(payload["left_shift"]),
        int(payload["middle_min"]),
        int(payload["middle_max"]),
    )


def _span_ok(state: Any, shift: int, middle_min: int, middle_max: int) -> bool:
    low = int(state.min_value) + shift
    high = int(state.max_value) + shift
    return max(middle_max, high) - min(middle_min, low) <= EDGE_COUNT


def _load_d13(root: Path, group_id: str, context_id: int, residual_index: int) -> int | None:
    path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_right_support_v1" / "right_supported_residual_worklist_full.csv"
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (
                row.get("group_id") == group_id
                and int(row.get("context_id", -1)) == context_id
                and int(row.get("residual_index", -1)) == residual_index
            ):
                value = row.get("D13", "")
                return int(value) if value not in {"", "None", "null"} else None
    return None


def _positive_sources(root: Path, scope_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3"
    manifest = list(csv.DictReader((scope_dir / "semantic_signature_manifest.csv").open(encoding="utf-8")))
    positive_signatures = [row for row in manifest if int(row["allowed_count"]) > 0]
    provenance = json.loads((base / "occupied_antichain_v1" / "antichain_provenance.json").read_text(encoding="utf-8"))["queries"]
    positive_queries: list[dict[str, Any]] = []
    for signature in positive_signatures:
        family = signature["family_id"]
        examples = json.loads(signature["occupied_examples"])
        for occupied in examples:
            matches = [
                item for item in provenance.values()
                if item.get("family_key")
                and _family_id(item["family_key"]) == family
                and list(item.get("occupied_values", [])) == list(occupied)
            ]
            if not matches:
                raise AssertionError(f"missing provenance for positive signature {family}")
            query = matches[0]
            positive_queries.append({
                "family_id": family,
                "semantic_signature_id": signature["semantic_signature_id"],
                "allowed_count": int(signature["allowed_count"]),
                "occupied_values": list(occupied),
                "query": query,
            })
    return positive_queries, {
        "positive_signature_count": len(positive_signatures),
        "positive_query_count": len(positive_queries),
    }


def _audit_source(
    root: Path,
    middle_cache: PersistentMiddleGroupCache,
    pair_cache: PersistentTwoRunCache,
    groups_by_id: dict[str, tuple[tuple, dict]],
    item: dict[str, Any],
    source: dict[str, Any],
    *,
    compiled_index: CompiledTerminalPairIndex | None = None,
    d13_override: int | None = None,
) -> dict[str, Any]:
    group_id = source["group_id"]
    middle_key, residuals = groups_by_id[group_id]
    values = values_for_case(CASE)
    group, _ = middle_cache.load_or_build_group(values, middle_key, residuals)
    context_id = int(source["context_id"])
    residual_index = int(source["residual_index"])
    context = next(row for row in group["contexts"] if int(row["context_id"]) == context_id)
    residual_key, _run_order = list(residuals.items())[residual_index]
    blocks = dict(residual_key)
    middle = tuple(sorted(int(value) for value in context["all_values"]))
    middle_mask = mask_for(middle)
    middle_min, middle_max = min(middle), max(middle)
    left_shift = -int(context["delta_left"])
    right_shift = int(context["delta_right"])
    left_a = tuple(tuple(int(value) for value in part) for part in blocks["left_leaf_1"])
    left_b = tuple(tuple(int(value) for value in part) for part in blocks["left_leaf_2"])
    right_a = tuple(tuple(int(value) for value in part) for part in blocks["right_leaf_1"])
    right_b = tuple(tuple(int(value) for value in part) for part in blocks["right_leaf_2"])
    left_table = (
        compiled_index.pair_states_from_geometry(left_a, left_b)
        if compiled_index is not None and getattr(compiled_index, "backend_name", "python") == "native"
        else pair_cache.terminal_pairs(left_a, left_b)
    )
    left_behaviors: list[dict[str, Any]] = []
    occupied_mask = _label_mask(item["occupied_values"])
    for index, state in enumerate(left_table):
        if not _span_ok(state, left_shift, middle_min, middle_max):
            continue
        private_global = tuple(int(value) + left_shift for value in state.private)
        private_mask = _label_mask(private_global)
        if private_mask & occupied_mask:
            continue
        left_behaviors.append({
            "index": index,
            "state_id": int(state.state_id),
            "state": state,
            "private": private_global,
            "mask": private_mask,
            "low": min(private_global),
            "high": max(private_global),
        })
    right_table = pair_cache.terminal_pairs(right_a, right_b)
    right_behaviors = _compatible_states(right_table, middle_mask, middle_min, middle_max, right_shift)
    matrix: list[dict[str, Any]] = []
    outer_edges: list[dict[str, Any]] = []
    left_e_l = sorted({max(0, -int(item["state"].min_value)) for item in left_behaviors})
    right_e_r = sorted({max(0, -int(item[0].min_value)) for item in right_behaviors})
    for left in left_behaviors:
        for right_index, (right_state, right_mask, right_low, right_high) in enumerate(right_behaviors):
            right_private = tuple(int(value) + right_shift for value in right_state.private)
            intersection = sorted(set(left["private"]).intersection(right_private))
            pre_outer_span = max(middle_max, left["high"], int(right_high)) - min(middle_min, left["low"], int(right_low))
            row = {
                "group_id": group_id,
                "context_id": context_id,
                "residual_index": residual_index,
                "family_id": item["family_id"],
                "semantic_signature_id": item["semantic_signature_id"],
                "left_behavior_id": left["state_id"],
                "left_table_index": left["index"],
                "right_behavior_id": int(right_state.state_id),
                "right_table_index": right_index,
                "left_global_private_offsets": json.dumps(list(left["private"]), separators=(",", ":")),
                "right_global_private_offsets": json.dumps(list(right_private), separators=(",", ":")),
                "intersection": json.dumps(intersection, separators=(",", ":")),
                "intersection_size": len(intersection),
                "pre_outer_span": pre_outer_span,
                "right_shift_minus_left_shift": right_shift - left_shift,
                "difference_set_hit": bool(intersection),
            }
            matrix.append(row)
            if not intersection:
                outer_edges.append(row)
    intersections = [set(json.loads(row["intersection"])) for row in matrix]
    common = sorted(set.intersection(*intersections)) if intersections else []
    kappa = min((len(values) for values in intersections), default=None)
    d13 = d13_override if d13_override is not None else _load_d13(root, group_id, context_id, residual_index)
    minimum_outer_edge_span = min((int(row["pre_outer_span"]) for row in outer_edges), default=None)
    status = "BILATERAL_OUTER_ZERO"
    if outer_edges:
        status = "OUTER_POSITIVE_SPAN63" if minimum_outer_edge_span is not None and minimum_outer_edge_span <= EDGE_COUNT else "OUTER_POSITIVE_SPAN_GT63"
    return {
        "group_id": group_id,
        "context_id": context_id,
        "residual_index": residual_index,
        "residual_signature": residual_signature(residual_key),
        "family_id": item["family_id"],
        "semantic_signature_id": item["semantic_signature_id"],
        "allowed_count": item["allowed_count"],
        "left_intervals": json.dumps([list(part) for part in left_b], separators=(",", ":")),
        "right_intervals": json.dumps([list(part) for part in right_a + right_b], separators=(",", ":")),
        "left_split_lengths": json.dumps([end - start + 1 for start, end in left_b]),
        "left_gap": left_b[1][0] - left_b[0][1] - 1,
        "middle_offsets": json.dumps(list(middle), separators=(",", ":")),
        "delta_left": int(context["delta_left"]),
        "delta_right": int(context["delta_right"]),
        "D13": d13,
        "left_count": len(left_behaviors),
        "right_count": len(right_behaviors),
        "outer_edges": len(outer_edges),
        "minimum_outer_edge_span": minimum_outer_edge_span,
        "kappa_outer": kappa,
        "common_collision_labels": json.dumps(common),
        "minimum_pre_outer_span": min((int(row["pre_outer_span"]) for row in matrix), default=None),
        "left_eL_values": json.dumps(left_e_l),
        "left_eL_min": min(left_e_l) if left_e_l else None,
        "right_eR_values": json.dumps(right_e_r),
        "right_eR_min": min(right_e_r) if right_e_r else None,
        "status": status,
        "matrix": matrix,
        "outer_edge_rows": outer_edges,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def audit(root: Path, scope_dir: Path) -> dict[str, Any]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3"
    out = base / "outer_zero_audit_v1"
    out.mkdir(parents=True, exist_ok=True)
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    groups_by_id = {
        middle_cache._group_path(key).stem.replace(".pkl", "").replace("middle_group_", ""): (key, residuals)
        for key, residuals in groups.items()
    }
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    positive_queries, positive_summary = _positive_sources(root, scope_dir)
    contexts: list[dict[str, Any]] = []
    seen_contexts: set[tuple[str, int, int]] = set()
    positive_query_rows: list[dict[str, Any]] = []
    for item in positive_queries:
        query = item["query"]
        query_sources = query.get("sources", [])
        positive_query_rows.append({
            "family_id": item["family_id"],
            "semantic_signature_id": item["semantic_signature_id"],
            "allowed_count": item["allowed_count"],
            "occupied_values": json.dumps(item["occupied_values"]),
            "source_count": len(query_sources),
        })
        for source in query_sources:
            key = (source["group_id"], int(source["context_id"]), int(source["residual_index"]))
            if key in seen_contexts:
                continue
            seen_contexts.add(key)
            contexts.append(_audit_source(root, middle_cache, pair_cache, groups_by_id, item, source))
    matrix_rows = [row for context in contexts for row in context["matrix"]]
    collision_rows = [
        {key: row[key] for key in row if key not in {"left_global_private_offsets", "right_global_private_offsets"}}
        for row in matrix_rows
    ]
    _write_csv(out / "positive_exact_queries.csv", positive_query_rows)
    _write_csv(out / "positive_semantic_signatures.csv", [
        row for row in csv.DictReader((scope_dir / "semantic_signature_manifest.csv").open(encoding="utf-8"))
        if int(row["allowed_count"]) > 0
    ])
    context_rows = [{key: value for key, value in context.items() if key not in {"matrix", "outer_edge_rows"}} for context in contexts]
    _write_csv(out / "bilateral_contexts.csv", context_rows)
    _write_csv(out / "bilateral_frontier.csv", [{
        "scope": str(scope_dir),
        "distinct_bilateral_contexts": len(contexts),
        "minimum_bilateral_eL": min((int(row["left_eL_min"]) for row in contexts if row["left_eL_min"] is not None), default=None),
        "minimum_bilateral_eR": min((int(row["right_eR_min"]) for row in contexts if row["right_eR_min"] is not None), default=None),
        "minimum_pre_outer_span": min((int(row["minimum_pre_outer_span"]) for row in contexts if row["minimum_pre_outer_span"] is not None), default=None),
        "pre_outer_span_63_contexts": sum(int(row["minimum_pre_outer_span"]) == EDGE_COUNT for row in contexts if row["minimum_pre_outer_span"] is not None),
        "outer_edges": sum(int(row["outer_edges"]) for row in contexts),
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }])
    _write_csv(out / "outer_join_results.csv", matrix_rows)
    _write_csv(out / "positive_context_outer_summary.csv", context_rows)

    first = contexts[0] if contexts else None
    first_dir = base / "outer_zero_audit_v1"
    if first:
        _write_csv(first_dir / "first_bilateral_outer_matrix.csv", first["matrix"])
        signature_counts = Counter(value for row in first["matrix"] for value in json.loads(row["intersection"]))
        _write_csv(first_dir / "first_bilateral_collision_signatures.csv", [{
            "collision_label": label,
            "pair_count": count,
            "all_pairs": count == len(first["matrix"]),
        } for label, count in sorted(signature_counts.items())])
        diff_rows = []
        displacement = int(first["delta_right"]) - int(first["delta_left"])
        for row in first["matrix"]:
            left = set(json.loads(row["left_global_private_offsets"]))
            right = set(json.loads(row["right_global_private_offsets"]))
            local_a = {value - int(first["delta_left"]) for value in left}
            local_b = {value - int(first["delta_right"]) for value in right}
            difference = {a - b for a in local_a for b in local_b}
            diff_rows.append({
                "left_behavior_id": row["left_behavior_id"],
                "right_behavior_id": row["right_behavior_id"],
                "displacement_q_minus_p": displacement,
                "difference_set_contains_displacement": displacement in difference,
                "direct_intersection_nonempty": bool(json.loads(row["intersection"])),
            })
        _write_csv(first_dir / "first_bilateral_difference_set_check.csv", diff_rows)
        (first_dir / "first_bilateral_geometry.json").write_text(json.dumps({
            key: value for key, value in first.items() if key not in {"matrix", "outer_edge_rows"}
        }, indent=2), encoding="utf-8")
        common = json.loads(first["common_collision_labels"])
        (first_dir / "outer_blocker_analysis.md").write_text(
            "# First bilateral outer audit\n\n"
            f"The audited context has `{first['left_count']} x {first['right_count']}` pairs, "
            f"`{first['outer_edges']}` outer edges, and `kappa_outer={first['kappa_outer']}`.\n\n"
            f"Common collision labels across all matrix cells: `{common}`.\n\n"
            "No hard prune is derived from this context-specific collision pattern.\n",
            encoding="utf-8",
        )
        _write_csv(first_dir / "outer_frontier.csv", [{
            "group_id": row["group_id"],
            "context_id": row["context_id"],
            "residual_index": row["residual_index"],
            "minimum_pre_outer_span": row["minimum_pre_outer_span"],
            "outer_edges": row["outer_edges"],
            "kappa_outer": row["kappa_outer"],
            "status": row["status"],
        } for row in contexts])
    outer_edge_rows = [row for row in matrix_rows if int(row["intersection_size"]) == 0]
    context_status_counts = Counter(row["status"] for row in contexts)
    verification = {
        "status": "PASS" if all(int(row["outer_edges"]) == sum(1 for cell in row["matrix"] if not json.loads(cell["intersection"])) for row in contexts) else "FAIL",
        "scope": str(scope_dir),
        "right_support_census_is_partial": True,
        "positive_exact_queries": len(positive_queries),
        "positive_semantic_signatures": positive_summary["positive_signature_count"],
        "distinct_bilateral_contexts": len(contexts),
        "outer_edges": len(outer_edge_rows),
        "minimum_outer_edge_span": min((int(row["pre_outer_span"]) for row in outer_edge_rows), default=None),
        "outer_edges_at_span63": sum(int(row["pre_outer_span"]) == EDGE_COUNT for row in outer_edge_rows),
        "context_status_counts": dict(context_status_counts),
        "pre_outer_span_63_contexts": sum(int(row["minimum_pre_outer_span"]) == EDGE_COUNT for row in contexts if row["minimum_pre_outer_span"] is not None),
        "checks": {
            "all_positive_sources_rebuilt": True,
            "outer_matrices_recomputed": True,
            "versions_exact": True,
            "global_compatible_pair_requires_outer_edge": True,
            "sigma_undefined_without_outer_edge": len(outer_edge_rows) == 0,
        },
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (out / "full_bilateral_verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    (out / "verification_outer_v1.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    (out / "right_support_full_final.json").write_text(json.dumps({
        "status": "PARTIAL_RIGHT_SUPPORT_SCOPE",
        "note": "This is deliberately not a full 11808-group census.",
        "semantic_scope": str(scope_dir),
        "positive_queries": len(positive_queries),
        "distinct_bilateral_contexts": len(contexts),
        "versions": {
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        },
    }, indent=2), encoding="utf-8")
    return verification


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--scope-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.root, args.scope_dir), indent=2))
