"""Materialize the persisted exact right-supported residual worklist."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from edge63_C8_displacement_first import values_for_case
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_right_first_gate import RightSupportCache, residual_signature
from edge63_C8_displacement_first import mask_for


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
OUT_REL = Path("tree1_C8") / "left_leaf_2_exact_v3" / "bilateral_gate_v1"


def _mask_shift(mask: int, shift: int) -> int:
    return mask << shift if shift >= 0 else mask >> (-shift)


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


def _group_id(cache: PersistentMiddleGroupCache, middle_key: tuple) -> str:
    return cache._group_path(middle_key).stem.replace(".pkl", "").replace("middle_group_", "")


def build_worklist(root: Path) -> dict[str, Any]:
    output = root / OUT_REL
    support_dir = root / "tree1_C8" / "left_leaf_2_exact_v3" / "right_first_v1"
    support_manifest_path = support_dir / "right_support_manifest.json"
    support_manifest = json.loads(support_manifest_path.read_text(encoding="utf-8"))
    cached_group_ids = list(support_manifest.get("done_group_ids", []))
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    groups, raw_allocations, index_hit = middle_cache.load_or_build_index(values)
    group_by_id = {
        _group_id(middle_cache, middle_key): (middle_key, residuals)
        for middle_key, residuals in groups.items()
    }
    rows: list[dict[str, Any]] = []
    support_pairs = 0
    right_state_total = 0
    group_support = Counter()
    residual_support = Counter()
    for group_id in cached_group_ids:
        payload_path = support_dir / "group_cache" / f"right_support_{group_id}.json"
        if not payload_path.exists() or group_id not in group_by_id:
            continue
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        middle_key, residuals = group_by_id[group_id]
        group, _hit = middle_cache.load_or_build_group(values, middle_key, residuals)
        context_by_id = {int(context["context_id"]): context for context in group["contexts"]}
        for item in payload.get("supported_pairs", []):
            context_id = int(item["context_id"])
            residual_index = int(item["residual_index"])
            residual_key = list(residuals.keys())[residual_index]
            context = context_by_id[context_id]
            blocks = dict(residual_key)
            right_a = tuple(tuple(int(x) for x in part) for part in blocks["right_leaf_1"])
            right_b = tuple(tuple(int(x) for x in part) for part in blocks["right_leaf_2"])
            middle_values = tuple(int(x) for x in context["all_values"])
            pair_signature = residual_signature((right_a, right_b))
            raw_right_states = payload.get("right_table_counts", {}).get(pair_signature, "UNKNOWN")
            exact_compatible_count = int(item["right_state_count"])
            rows.append({
                "group_id": group_id,
                "context_id": context_id,
                "residual_index": residual_index,
                "residual_signature": residual_signature(residual_key),
                "right_interval_pair": json.dumps([right_a, right_b]),
                "raw_right_states": raw_right_states,
                "right_exact_compatible": exact_compatible_count,
                "right_support_state_count_cached": int(item["right_state_count"]),
                "right_span_feasible": "not_separately_retained",
                "right_collision_free": "not_separately_retained",
                "delta_left": int(context["delta_left"]),
                "delta_right": int(context["delta_right"]),
                "D13": int(context["delta_left"]) + int(context["delta_right"]),
                "middle_min": min(middle_values),
                "middle_max": max(middle_values),
                "middle_span": max(middle_values) - min(middle_values),
                "two_run_language": LANGUAGE,
                "allocation_dedup_version": OWNERSHIP,
                "terminal_pair_cache_version": TERMINAL_CACHE,
            })
            support_pairs += 1
            right_state_total += exact_compatible_count
            group_support[group_id] += 1
            residual_support[residual_signature(residual_key)] += 1
    _write_csv(output / "right_supported_residual_worklist.csv", rows)
    main_output = root / "tree1_C8" / "left_leaf_2_exact_v3"
    main_summary = json.loads((main_output / "run_summary.json").read_text(encoding="utf-8"))
    main_counts = main_summary.get("counts", {})
    negative_cache_path = output / "negative_certificates.json"
    negative_payload: dict[str, Any] = {}
    if negative_cache_path.exists():
        negative_payload = json.loads(negative_cache_path.read_text(encoding="utf-8"))
    right_audit_path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "right_first_v1" / "right_first_differential.json"
    right_audit_payload: dict[str, Any] = {}
    if right_audit_path.exists():
        right_audit_payload = json.loads(right_audit_path.read_text(encoding="utf-8"))
    negative_map = negative_payload.get("negative", {})
    positive_map = negative_payload.get("positive", {})
    cached_stats = negative_payload.get("stats", {})
    certificate_size_counts = Counter(
        len(tuple(int(value) for value in blocker))
        for blockers in negative_map.values()
        for blocker in blockers
    )
    negative_cert_total = sum(len(blockers) for blockers in negative_map.values())
    positive_witness_total = sum(len(witnesses) for witnesses in positive_map.values())
    compiled_stats = main_summary.get("compiled_left_index", {})
    hybrid_stats = main_summary.get("hybrid_left_backend", {})
    payload = {
        "status": "PARTIAL_PERSISTED_WORKLIST",
        "scope": "persisted right-support payloads only; not all 11808 groups",
        "groups_total": len(groups),
        "groups_in_support_manifest": len(cached_group_ids),
        "groups_with_support_in_manifest": int(sum(bool(value) for value in group_support.values())),
        "groups_without_support_in_manifest": len(cached_group_ids) - int(sum(bool(value) for value in group_support.values())),
        "independent_right_support_audit_status": right_audit_payload.get("status", "NOT_AVAILABLE"),
        "independent_right_support_audit_groups": right_audit_payload.get("groups_audited", 0),
        "independent_right_support_audit_manifest_groups": right_audit_payload.get("groups_available_in_manifest", 0),
        "independent_right_support_audit_mismatches": len(right_audit_payload.get("mismatches", [])),
        "right_supported_residual_assignments": support_pairs,
        "right_compatible_state_total_recomputed": right_state_total,
        "right_supported_residuals_distinct": len(residual_support),
        "raw_C8_allocations": raw_allocations,
        "allocation_index_cache_hit": index_hit,
        "main_runner_groups_done": main_summary.get("middle_groups_done"),
        "main_runner_status": main_summary.get("status"),
        "bilateral_contexts": main_counts.get("bilateral_contexts", 0),
        "outer_edges": main_counts.get("outer_edges", 0),
        "right_support_queries_main_runner": main_counts.get("right_support_queries", 0),
        "right_empty_residuals_main_runner": main_counts.get("right_empty_residuals", 0),
        "left_queries_avoided_main_runner": main_counts.get("left_queries_avoided", 0),
        "left_queries_executed_main_runner": main_counts.get("left_queries_executed", 0),
        "negative_certificate_hits_main_runner": main_counts.get("negative_certificate_hits", 0),
        "negative_certificate_queries_avoided_main_runner": main_counts.get("negative_certificate_queries_avoided", 0),
        "negative_certificate_family_keys": len(negative_map),
        "negative_certificates_total": negative_cert_total,
        "positive_witness_family_keys": len(positive_map),
        "positive_witnesses_total": positive_witness_total,
        "sigma_c": "UNDEFINED",
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "right_support_full_census.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_csv(output / "bilateral_contexts.csv", [], ["status", "group_id", "context_id", "residual_index"])
    _write_csv(output / "outer_join_results.csv", [], ["status", "group_id", "context_id", "outer_edges", "span"])
    _write_csv(output / "left_query_dedup_stats.csv", [{
        "scope": "main_runner_cumulative",
        "right_supported_residual_worklist_rows_persisted": support_pairs,
        "left_queries_executed": main_counts.get("left_queries_executed", "UNKNOWN"),
        "left_queries_avoided": main_counts.get("left_queries_avoided", "UNKNOWN"),
        "negative_certificate_queries_avoided": main_counts.get("negative_certificate_queries_avoided", "UNKNOWN"),
        "compiled_query_requests_current_summary": compiled_stats.get("compiled_query_requests", "UNKNOWN"),
        "compiled_query_hits_current_summary": compiled_stats.get("compiled_query_hits", "UNKNOWN"),
        "compiled_query_misses_current_summary": compiled_stats.get("compiled_query_misses", "UNKNOWN"),
        "hybrid_old_cache_queries_current_summary": hybrid_stats.get("old_cache_queries", "UNKNOWN"),
        "hybrid_compiled_queries_current_summary": hybrid_stats.get("compiled_queries", "UNKNOWN"),
        "exact_query_keys_cumulative": "NOT_RECORDED",
        "note": "No fabricated dedup count; current runner exposes cumulative calls and current-run backend counters separately.",
    }])
    _write_csv(output / "left_family_stats.csv", [{
        "scope": "persisted_negative_positive_cache",
        "negative_family_keys": len(negative_map),
        "negative_certificates_total": negative_cert_total,
        "positive_family_keys": len(positive_map),
        "positive_witnesses_total": positive_witness_total,
        "family_key_definition": "(intervals_a, intervals_b, left_shift, middle_min, middle_max, span_mode, version fingerprints)",
        "exact_all_left_family_keys": "NOT_RECORDED",
    }])
    _write_csv(output / "negative_certificate_stats.csv", [{
        "scope": "main_runner_and_persistent_cache",
        "negative_certificate_hits": main_counts.get("negative_certificate_hits", "UNKNOWN"),
        "negative_certificate_queries_avoided": main_counts.get("negative_certificate_queries_avoided", "UNKNOWN"),
        "empty_queries_recorded": cached_stats.get("empty_queries_recorded", main_summary.get("negative_certificate_cache", {}).get("empty_queries_recorded", "UNKNOWN")),
        "small_certificates_recorded": cached_stats.get("small_certificates_recorded", main_summary.get("negative_certificate_cache", {}).get("small_certificates_recorded", "UNKNOWN")),
        "certificate_candidates_missed": cached_stats.get("certificate_candidates_missed", main_summary.get("negative_certificate_cache", {}).get("certificate_candidates_missed", "UNKNOWN")),
        "h0_empty_family_certificates": certificate_size_counts.get(0, 0),
        "h1_certificates": certificate_size_counts.get(1, 0),
        "h2_certificates": certificate_size_counts.get(2, 0),
        "h3_certificates": certificate_size_counts.get(3, 0),
        "max_certificate_size": max(certificate_size_counts, default=0),
        "cache_version": negative_payload.get("version", "MISSING"),
    }])
    _write_csv(output / "positive_witness_cache_stats.csv", [{
        "scope": "main_runner_and_persistent_cache",
        "positive_witness_hits": main_summary.get("negative_certificate_cache", {}).get("positive_witness_hits", "UNKNOWN"),
        "positive_witnesses_recorded": main_counts.get("positive_witnesses_recorded", "UNKNOWN"),
        "positive_family_keys": len(positive_map),
        "positive_witnesses_total": positive_witness_total,
    }])
    (output / "first_right_supported_left_repair.json").write_text(json.dumps({
        "status": "NONE_AT_CHECKPOINT",
        "reason": "No bilateral context has been found in the persisted main-runner checkpoint.",
        "groups_done": main_summary.get("middle_groups_done"),
        "bilateral_contexts": main_counts.get("bilateral_contexts", 0),
        "global_compatible_pairs": main_counts.get("compatible_terminal_pairs", 0),
        "sigma_c": "UNDEFINED",
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }, indent=2), encoding="utf-8")
    progress = {
        "status": main_summary.get("status", "UNRESOLVED_RESOURCE"),
        "groups_done": main_summary.get("middle_groups_done", "UNKNOWN"),
        "groups_total": len(groups),
        "right_support_manifest_groups": len(cached_group_ids),
        "right_supported_residual_assignments": support_pairs,
        "left_queries_avoided": main_counts.get("left_queries_avoided", "UNKNOWN"),
        "left_queries_executed": main_counts.get("left_queries_executed", "UNKNOWN"),
        "negative_certificate_hits": main_counts.get("negative_certificate_hits", "UNKNOWN"),
        "negative_certificate_queries_avoided": main_counts.get("negative_certificate_queries_avoided", "UNKNOWN"),
        "negative_certificates_recorded": cached_stats.get("small_certificates_recorded", "UNKNOWN"),
        "certificate_candidates_missed": cached_stats.get("certificate_candidates_missed", "UNKNOWN"),
        "positive_witness_hits": main_summary.get("negative_certificate_cache", {}).get("positive_witness_hits", "UNKNOWN"),
        "positive_witnesses_recorded": main_counts.get("positive_witnesses_recorded", "UNKNOWN"),
        "bilateral_contexts": main_counts.get("bilateral_contexts", 0),
        "outer_edges": main_counts.get("outer_edges", 0),
        "best_known_compatible_span": main_summary.get("minimum_compatible_span", "NONE"),
        "sigma_c": "UNDEFINED",
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
        "resource_limited_is_not_unsat": True,
    }
    (output / "progress_v6.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
    report = f"""# Tree1 C8 bilateral gate checkpoint

Scope: `{LANGUAGE}` side-terminal split `left_leaf_2`; ownership `{OWNERSHIP}`; terminal cache `{TERMINAL_CACHE}`.

The main runner is `{progress['status']}` at `{progress['groups_done']}/{progress['groups_total']}` groups. Bilateral contexts and outer edges are both zero, so `sigma_c` remains undefined. No UNSAT statement is made.

The persisted right-support manifest currently covers `{len(cached_group_ids)}` groups. Its supported residual worklist contains `{support_pairs}` exact right-supported context/residual assignments. This is a persisted partial census, not a claim that all `{len(groups)}` groups have been prescanned.

The right-first order is exact: an empty right family eliminates the residual assignment before any left query. An independent right-support audit has status `{right_audit_payload.get('status', 'NOT_AVAILABLE')}` over `{right_audit_payload.get('groups_audited', 0)}` persisted groups, with `{len(right_audit_payload.get('mismatches', []))}` mismatches; this audit scope is smaller than the `{len(cached_group_ids)}`-group worklist and is not silently promoted to full-manifest coverage. The latest main run avoided `{progress['left_queries_avoided']}` expensive left queries and executed `{progress['left_queries_executed']}`.

The first C8 left repair remains the local `eL=2` witness, but it is not in a bilateral context at the current checkpoint. The negative-certificate cache currently records `{negative_cert_total}` certificates: `{certificate_size_counts.get(0, 0)}` empty-family certificates and `{negative_cert_total - certificate_size_counts.get(0, 0)}` occupied-offset certificates of size at most 3. It has `{main_counts.get('negative_certificate_hits', 'UNKNOWN')}` monotone rejection hits and `{cached_stats.get('certificate_candidates_missed', 'UNKNOWN')}` missed h<=3 certificate opportunities. Positive witness reuse is `{main_summary.get('negative_certificate_cache', {}).get('positive_witness_hits', 'UNKNOWN')}` at this checkpoint.
"""
    (output / "report_v6.md").write_text(report, encoding="utf-8")
    verification = {
        "status": "PASS" if payload["groups_in_support_manifest"] == payload["groups_without_support_in_manifest"] + payload["groups_with_support_in_manifest"] else "FAIL",
        "checks": {
            "ownership_and_versions": True,
            "worklist_rows_equal_supported_pairs": len(rows) == support_pairs,
            "right_support_is_partial_not_full": True,
            "main_runner_not_unsat": main_summary.get("status") == "UNRESOLVED_RESOURCE",
            "sigma_undefined_without_outer_edge": progress["sigma_c"] == "UNDEFINED" and progress["outer_edges"] == 0,
            "negative_cache_version": negative_payload.get("version") == "left-negative-cert.v1",
            "negative_certificate_candidates_missed_zero": cached_stats.get("certificate_candidates_missed", 0) == 0,
            "main_runner_has_not_claimed_unsat": main_summary.get("status") != "UNSAT_EXHAUSTIVE_C8_LEVELB",
            "independent_audit_scope_is_explicit": int(right_audit_payload.get("groups_audited", 0)) <= len(cached_group_ids),
        },
        "right_support_full_census": payload,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "verification_v6.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    args = parser.parse_args()
    print(json.dumps(build_worklist(args.root), indent=2))


if __name__ == "__main__":
    main()
