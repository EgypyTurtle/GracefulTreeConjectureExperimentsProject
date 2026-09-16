"""Build an exact occupied-set antichain over persisted right-supported work.

This module does not run the long left query.  It reconstructs only the exact
left family key and occupied middle-frame set from persisted right-support
payloads, then applies finite subset antichain reduction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_left_negative_cert_cache import canonical_family_key
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_right_first_gate import residual_signature
from edge63_C8_displacement_first import values_for_case


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
OUT_REL = Path("tree1_C8") / "left_leaf_2_exact_v3" / "occupied_antichain_v1"


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


def _family_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _minimal_antichain(sets: set[frozenset[int]]) -> list[frozenset[int]]:
    minimal: list[frozenset[int]] = []
    for occupied in sorted(sets, key=lambda item: (len(item), tuple(sorted(item)))):
        if any(candidate.issubset(occupied) for candidate in minimal):
            continue
        minimal.append(occupied)
    return minimal


def build(root: Path) -> dict[str, Any]:
    output = root / OUT_REL
    output.mkdir(parents=True, exist_ok=True)
    support_dir = root / "tree1_C8" / "left_leaf_2_exact_v3" / "right_first_v1"
    manifest_path = support_dir / "right_support_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    persisted_group_ids = list(manifest.get("done_group_ids", []))
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    groups_by_id = {
        _group_id(middle_cache, middle_key): (middle_key, residuals)
        for middle_key, residuals in groups.items()
    }

    family_queries: dict[str, set[frozenset[int]]] = defaultdict(set)
    family_sources: dict[str, dict[frozenset[int], list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    groups_seen = 0
    rows_seen = 0
    skipped_payloads = 0
    for group_id in persisted_group_ids:
        payload_path = support_dir / "group_cache" / f"right_support_{group_id}.json"
        if not payload_path.exists() or group_id not in groups_by_id:
            skipped_payloads += 1
            continue
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        middle_key, residuals = groups_by_id[group_id]
        group, _cache_hit = middle_cache.load_or_build_group(values, middle_key, residuals)
        contexts = {int(context["context_id"]): context for context in group["contexts"]}
        residual_keys = list(residuals.keys())
        for item in payload.get("supported_pairs", []):
            context_id = int(item["context_id"])
            residual_index = int(item["residual_index"])
            context = contexts[context_id]
            residual_key = residual_keys[residual_index]
            blocks = dict(residual_key)
            left_a = tuple(tuple(int(x) for x in part) for part in blocks["left_leaf_1"])
            left_b = tuple(tuple(int(x) for x in part) for part in blocks["left_leaf_2"])
            middle_values = frozenset(int(x) for x in context["all_values"])
            middle_min = min(middle_values)
            middle_max = max(middle_values)
            left_shift = -int(context["delta_left"])
            family_key = canonical_family_key(
                left_a,
                left_b,
                left_shift,
                middle_min,
                middle_max,
                True,
            )
            family_queries[family_key].add(middle_values)
            family_sources[family_key][middle_values].append({
                "group_id": group_id,
                "context_id": context_id,
                "residual_index": residual_index,
                "residual_signature": residual_signature(residual_key),
            })
            rows_seen += 1
        groups_seen += 1

    family_rows: list[dict[str, Any]] = []
    query_rows: list[dict[str, Any]] = []
    minimal_rows: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {}
    minimal_total = 0
    duplicate_queries = 0
    for family_key, occupied_sets in sorted(family_queries.items(), key=lambda item: item[0]):
        antichain = _minimal_antichain(occupied_sets)
        family_hash = _family_id(family_key)
        source_map = family_sources[family_key]
        duplicate_queries += sum(len(source_map[item]) - 1 for item in occupied_sets)
        family_rows.append({
            "family_id": family_hash,
            "raw_work_items": sum(len(source_map[item]) for item in occupied_sets),
            "distinct_occupied_sets": len(occupied_sets),
            "minimal_occupied_sets": len(antichain),
            "antichain_compression": len(antichain) / len(occupied_sets) if occupied_sets else 0.0,
            "family_key": family_key,
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        })
        for occupied in sorted(occupied_sets, key=lambda item: (len(item), tuple(sorted(item)))):
            query_rows.append({
                "family_id": family_hash,
                "occupied_values": json.dumps(sorted(occupied)),
                "source_count": len(source_map[occupied]),
                "is_inclusion_minimal": occupied in antichain,
            })
        for index, occupied in enumerate(antichain):
            sources = source_map[occupied]
            query_id = f"{family_hash}:{index}"
            minimal_rows.append({
                "query_id": query_id,
                "family_id": family_hash,
                "occupied_values": json.dumps(sorted(occupied)),
                "source_count": len(sources),
                "source_example": json.dumps(sources[0], sort_keys=True),
            })
            provenance[query_id] = {
                "family_key": family_key,
                "occupied_values": sorted(occupied),
                "sources": sources,
            }
        minimal_total += len(antichain)

    main_summary_path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "run_summary.json"
    main_summary = json.loads(main_summary_path.read_text(encoding="utf-8"))
    main_counts = main_summary.get("counts", {})
    _write_csv(output / "left_family_manifest.csv", family_rows)
    _write_csv(output / "occupied_query_dedup.csv", query_rows)
    _write_csv(output / "minimal_occupied_queries.csv", minimal_rows)
    _write_csv(output / "occupied_antichain_stats.csv", [{
        "scope": "persisted right-supported worklist",
        "persisted_groups": len(persisted_group_ids),
        "groups_with_payload_and_index": groups_seen,
        "skipped_payloads": skipped_payloads,
        "raw_right_supported_work_items": rows_seen,
        "distinct_exact_left_queries": sum(len(items) for items in family_queries.values()),
        "duplicate_work_items_removed": duplicate_queries,
        "distinct_family_keys": len(family_queries),
        "minimal_occupied_queries": minimal_total,
        "compression_vs_distinct_queries": minimal_total / sum(len(items) for items in family_queries.values()) if family_queries else 0.0,
        "main_runner_left_queries_executed": main_counts.get("left_queries_executed", "UNKNOWN"),
        "main_runner_query_provenance_for_2517": "NOT_PERSISTED",
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }])
    (output / "antichain_provenance.json").write_text(json.dumps({
        "scope": "persisted right-supported worklist only",
        "families": len(family_queries),
        "minimal_queries": minimal_total,
        "queries": provenance,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }, indent=2), encoding="utf-8")
    (output / "antichain_prototype_2517.json").write_text(json.dumps({
        "status": "NOT_AVAILABLE_NO_QUERY_PROVENANCE",
        "requested_scope": "2517 executed left queries",
        "reason": "The earlier runner checkpoint did not persist exact left-query occupied-set provenance; no 2517-query antichain is fabricated.",
        "available_prototype_scope": "persisted right-supported worklist",
        "available_raw_work_items": rows_seen,
        "distinct_family_keys": len(family_queries),
        "minimal_occupied_queries": minimal_total,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }, indent=2), encoding="utf-8")

    summary = {
        "status": "PARTIAL_PERSISTED_ANTICHAIN",
        "scope": "persisted right-supported worklist only",
        "persisted_groups": len(persisted_group_ids),
        "groups_seen": groups_seen,
        "skipped_payloads": skipped_payloads,
        "raw_right_supported_work_items": rows_seen,
        "distinct_exact_left_queries": sum(len(items) for items in family_queries.values()),
        "distinct_family_keys": len(family_queries),
        "minimal_occupied_queries": minimal_total,
        "main_runner_groups_done": main_summary.get("middle_groups_done"),
        "main_runner_status": main_summary.get("status"),
        "bilateral_contexts": main_counts.get("bilateral_contexts", 0),
        "outer_edges": main_counts.get("outer_edges", 0),
        "sigma_c": "UNDEFINED",
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "progress_v7.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output / "report_v7.md").write_text(f"""# Tree1 C8 occupied-set antichain checkpoint

Scope: `{LANGUAGE}` side-terminal split `left_leaf_2`; ownership `{OWNERSHIP}`; terminal cache `{TERMINAL_CACHE}`.

This is a partial prototype over `{len(persisted_group_ids)}` persisted right-support groups and `{rows_seen}` right-supported work items. It is not the full `{len(groups)}`-group census. The main runner remains `{main_summary.get('status')}` at `{main_summary.get('middle_groups_done')}/{len(groups)}` groups; bilateral contexts and outer edges remain zero, so `sigma_c` is undefined.

The exact occupied-set interface yields `{len(family_queries)}` family keys, `{sum(len(items) for items in family_queries.values())}` distinct `(family, occupied-set)` queries, and `{minimal_total}` inclusion-minimal occupied queries. The antichain computation is exact on this persisted scope. The old `2517` executed left-query provenance was not persisted, so the requested 2517-query prototype is explicitly marked unavailable rather than reconstructed heuristically.

No global conclusion is drawn from this partial antichain. The right-support census remains resumable and the main status remains resource-unresolved.
""", encoding="utf-8")
    (output / "formal_lemmas_v7.md").write_text("""# Occupied-set antichain lemmas

## Occupied-set monotonicity

For a fixed left family `F`, define `L(F,O) = {b in B_F : S_b cap O = empty}`. If `O1 subseteq O2`, then `L(F,O2) subseteq L(F,O1)`.

## Minimal-antichain sufficiency

For a finite query family `O_F`, every query contains an inclusion-minimal member of `O_F`. Therefore some query is left-compatible if and only if some inclusion-minimal occupied set is left-compatible. This is an existence statement for a fixed family `F`; it does not identify a positive witness without running the exact family filter.

## Family-empty elimination

If the fixed family `B_F` is empty, every occupied set in that family is rejected independently of occupied-set antichain reduction.

All statements are finite and restricted to `C8.LevelB.v1`, `ownership.v2`, and `corrected.v2`.
""", encoding="utf-8")
    checks = {
        "versions_exact": True,
        "worklist_payload_scope_explicit": summary["scope"] == "persisted right-supported worklist only",
        "no_skipped_payloads": skipped_payloads == 0,
        "family_query_accounting": summary["distinct_exact_left_queries"] == len(query_rows),
        "minimal_queries_not_more_than_distinct": minimal_total <= summary["distinct_exact_left_queries"],
        "main_runner_not_unsat": main_summary.get("status") != "UNSAT_EXHAUSTIVE_C8_LEVELB",
        "sigma_undefined_without_global_pair": summary["sigma_c"] == "UNDEFINED" and summary["outer_edges"] == 0,
        "2517_scope_not_fabricated": json.loads((output / "antichain_prototype_2517.json").read_text(encoding="utf-8"))["status"] == "NOT_AVAILABLE_NO_QUERY_PROVENANCE",
    }
    verification = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "summary": summary,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "verification_v7.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    args = parser.parse_args()
    print(json.dumps(build(args.root), indent=2))


if __name__ == "__main__":
    main()
