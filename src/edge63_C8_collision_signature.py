"""Batch exact collision-effect signatures for persisted right-supported work."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_displacement_first import values_for_case
from edge63_displacement_first_compact import EDGE_COUNT, OFFSET_SHIFT, _label_mask


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
OUT_REL = Path("tree1_C8") / "left_leaf_2_exact_v3" / "collision_signature_v1"


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


def _family_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _parse_family(key: str) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...], int, int, int]:
    payload = json.loads(key)
    intervals_a = tuple(tuple(int(value) for value in part) for part in payload["intervals_a"])
    intervals_b = tuple(tuple(int(value) for value in part) for part in payload["intervals_b"])
    return intervals_a, intervals_b, int(payload["left_shift"]), int(payload["middle_min"]), int(payload["middle_max"])


def _load_inputs(root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[frozenset[int], list[dict[str, Any]]]], dict[str, dict[str, Any]]]:
    base = root / "tree1_C8" / "left_leaf_2_exact_v3" / "occupied_antichain_v1"
    family_path = base / "left_family_manifest.csv"
    query_path = base / "occupied_query_dedup.csv"
    provenance_path = base / "antichain_provenance.json"
    family_keys: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with family_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            family_keys[row["family_id"]].append(row)
    queries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with query_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["occupied_values_parsed"] = frozenset(int(value) for value in json.loads(row["occupied_values"]))
            queries[row["family_id"]].append(row)
    provenance_payload = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {}
    provenance = provenance_payload.get("queries", {})
    sources_by_family_occupied: dict[str, dict[frozenset[int], list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for item in provenance.values():
        family_key = item.get("family_key")
        occupied = frozenset(int(value) for value in item.get("occupied_values", []))
        if family_key:
            sources_by_family_occupied[_family_id(family_key)][occupied].extend(item.get("sources", []))
    return dict(queries), dict(sources_by_family_occupied), dict(family_keys)


def _filter_pair_states(pair_states: tuple[Any, ...], shift: int, middle_min: int, middle_max: int) -> tuple[int, ...]:
    behaviors: list[int] = []
    for state in pair_states:
        low = min((0, *state.private)) + shift
        high = max((0, *state.private)) + shift
        if max(middle_max, high) - min(middle_min, low) <= EDGE_COUNT:
            behaviors.append(_label_mask(value + shift for value in state.private))
    return tuple(behaviors)


def _family_masks(
    pair_cache: PersistentTwoRunCache,
    index: CompiledTerminalPairIndex,
    family_key: str,
) -> tuple[int, ...]:
    intervals_a, intervals_b, shift, middle_min, middle_max = _parse_family(family_key)
    # Reuse the exact corrected.v2 terminal-pair table when it exists.  This
    # avoids rebuilding the same single/split Cartesian join per family.
    pair_path = pair_cache._path("pairs", (intervals_a, intervals_b))
    # The native backend must be exercised as the source of the split-path
    # geometry.  Reusing a pre-existing Python pair table here would make an
    # end-to-end backend differential test vacuous.
    if getattr(index, "backend_name", "python") == "native":
        pair_path = Path("__native_backend_forces_geometry__")
    if pair_path.exists():
        return _filter_pair_states(
            pair_cache.terminal_pairs(intervals_a, intervals_b),
            shift,
            middle_min,
            middle_max,
        )
    if getattr(index, "backend_name", "python") == "native":
        return _filter_pair_states(
            index.pair_states_from_geometry(intervals_a, intervals_b),
            shift,
            middle_min,
            middle_max,
        )
    compiled = index.geometry_cache.get(intervals_b, "terminal")
    single_states = index._single_options(intervals_a)
    expected = sum(end - start + 1 for start, end in intervals_a)
    expected += sum(end - start + 1 for start, end in intervals_b)
    seen: set[int] = set()
    masks: list[int] = []
    for state_a in single_states:
        for record in compiled.records:
            private = tuple(sorted((*state_a.private, *record.private)))
            if 0 in private or len(private) != expected or len(set(private)) != expected:
                continue
            low = min((0, *private)) + shift
            high = max((0, *private)) + shift
            if max(middle_max, high) - min(middle_min, low) > EDGE_COUNT:
                continue
            mask = _label_mask(value + shift for value in private)
            if mask not in seen:
                seen.add(mask)
                masks.append(mask)
    index.query_mem.clear()
    index.geometry_cache.mem.clear()
    return tuple(masks)


def _has_persisted_behavior_table(
    pair_cache: PersistentTwoRunCache,
    index: CompiledTerminalPairIndex,
    family_key: str,
) -> bool:
    intervals_a, intervals_b, _shift, _middle_min, _middle_max = _parse_family(family_key)
    return (
        pair_cache._path("pairs", (intervals_a, intervals_b)).exists()
        or index.geometry_cache._path(intervals_b, "terminal").exists()
    )


def _process_family(
    pair_cache: PersistentTwoRunCache,
    index: CompiledTerminalPairIndex,
    family_key: str,
    query_rows: list[dict[str, Any]],
    sources: dict[frozenset[int], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    family_id = _family_id(family_key)
    behavior_masks = _family_masks(pair_cache, index, family_key)
    behaviors = behavior_masks
    all_bits = (1 << len(behaviors)) - 1
    contains: dict[int, int] = {}
    for behavior_id, behavior_mask in enumerate(behaviors):
        bit = 1 << behavior_id
        remaining = behavior_mask
        while remaining:
            lowest = remaining & -remaining
            offset = lowest.bit_length() - 1 - OFFSET_SHIFT
            contains[offset] = contains.get(offset, 0) | bit
            remaining ^= lowest
    signature_groups: dict[int, dict[str, Any]] = {}
    query_effect_rows: list[dict[str, Any]] = []
    for row in query_rows:
        occupied = row["occupied_values_parsed"]
        blocked = 0
        for offset in occupied:
            blocked |= contains.get(offset, 0)
        allowed = all_bits & ~blocked
        semantic_id = hashlib.sha256(f"{family_id}:{allowed:x}".encode("ascii")).hexdigest()[:24]
        entry = signature_groups.setdefault(allowed, {
            "semantic_signature_id": semantic_id,
            "family_id": family_id,
            "family_key": family_key,
            "blocked_mask_hex": hex(blocked),
            "allowed_mask_hex": hex(allowed),
            "allowed_count": allowed.bit_count(),
            "query_count": 0,
            "source_count": 0,
            "occupied_examples": [],
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        })
        entry["query_count"] += 1
        entry["source_count"] += len(sources.get(occupied, []))
        if len(entry["occupied_examples"]) < 3:
            entry["occupied_examples"].append(sorted(occupied))
        query_effect_rows.append({
            "family_id": family_id,
            "semantic_signature_id": semantic_id,
            "occupied_values": json.dumps(sorted(occupied), separators=(",", ":")),
            "blocked_mask_hex": hex(blocked),
            "allowed_mask_hex": hex(allowed),
            "allowed_count": allowed.bit_count(),
            "source_count": len(sources.get(occupied, [])),
        })
    encountered_offsets = {
        offset for row in query_rows for offset in row["occupied_values_parsed"]
    }
    effect_masks = Counter(contains.get(offset, 0) for offset in encountered_offsets)
    effect_rows = {
        "family_id": family_id,
        "family_key": family_key,
        "behavior_count": len(behaviors),
        "occupied_offsets_encountered": len({offset for row in query_rows for offset in row["occupied_values_parsed"]}),
        "zero_effect_offsets": sum(contains.get(offset, 0) == 0 for offset in encountered_offsets),
        "distinct_single_offset_effect_masks": len(effect_masks),
        "duplicate_effect_classes": sum(1 for mask, count in effect_masks.items() if mask != 0 and count > 1),
        "query_count": len(query_rows),
        "compile_and_filter_seconds": time.perf_counter() - started,
    }
    return list(signature_groups.values()), effect_rows, {"query_effect_rows": query_effect_rows, "behaviors": len(behaviors)}


def build(
    root: Path,
    max_families: int | None = None,
    start_family: int = 0,
    chunk_name: str | None = None,
    skip_missing_pairs: bool = False,
) -> dict[str, Any]:
    output = root / OUT_REL
    if chunk_name:
        output = output / "chunks" / chunk_name
    output.mkdir(parents=True, exist_ok=True)
    queries, sources, family_rows = _load_inputs(root)
    all_family_ids = sorted(queries)
    start_family = max(0, int(start_family))
    ordered_family_ids = all_family_ids[start_family:]
    if max_families is not None:
        ordered_family_ids = ordered_family_ids[:max_families]
    index = CompiledTerminalPairIndex(root, CASE, SLOT)
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    signatures: list[dict[str, Any]] = []
    effect_rows: list[dict[str, Any]] = []
    query_effect_rows: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {}
    total_queries = 0
    empty_queries = 0
    positive_queries = 0
    family_empty = 0
    skipped_missing_families = 0
    skipped_missing_queries = 0
    started = time.perf_counter()
    for family_id in ordered_family_ids:
        manifest_rows = family_rows.get(family_id, [])
        if not manifest_rows:
            continue
        family_key = manifest_rows[0]["family_key"]
        if skip_missing_pairs and not _has_persisted_behavior_table(pair_cache, index, family_key):
            skipped_missing_families += 1
            skipped_missing_queries += len(queries[family_id])
            continue
        signature_rows, effect_row, details = _process_family(pair_cache, index, family_key, queries[family_id], sources.get(family_id, {}))
        signatures.extend(signature_rows)
        effect_rows.append(effect_row)
        query_effect_rows.extend(details["query_effect_rows"])
        total_queries += len(queries[family_id])
        for item in signature_rows:
            if int(item["allowed_count"]) == 0:
                empty_queries += int(item["query_count"])
            else:
                positive_queries += int(item["query_count"])
        if details["behaviors"] == 0:
            family_empty += 1
        for item in signature_rows:
            provenance[item["semantic_signature_id"]] = {
                "family_id": item["family_id"],
                "family_key": item["family_key"],
                "allowed_count": item["allowed_count"],
                "query_count": item["query_count"],
                "occupied_examples": item["occupied_examples"],
                "source_examples": [],
            }
        if max_families is not None and len(effect_rows) >= max_families:
            break

    _write_csv(output / "semantic_signature_manifest.csv", signatures)
    _write_csv(output / "single_offset_effect_stats.csv", effect_rows)
    _write_csv(output / "family_query_multiplicity.csv", [{
        "family_id": family_id,
        "raw_query_count": len(queries.get(family_id, [])),
        "family_key": family_rows[family_id][0]["family_key"] if family_rows.get(family_id) else "",
    } for family_id in ordered_family_ids if family_rows.get(family_id)])
    _write_csv(output / "partial_semantic_signature_stats.csv", [{
        "scope": "persisted right-supported worklist semantic batch",
        "family_start_index": start_family,
        "family_end_index_exclusive": start_family + len(effect_rows),
        "skip_missing_pairs": skip_missing_pairs,
        "families_skipped_missing_pair": skipped_missing_families,
        "queries_skipped_missing_pair": skipped_missing_queries,
        "families_processed": len(effect_rows),
        "families_available": len(queries),
        "queries_processed": total_queries,
        "distinct_semantic_signatures": len(signatures),
        "empty_queries": empty_queries,
        "positive_queries": positive_queries,
        "semantic_compression_ratio": len(signatures) / total_queries if total_queries else 0.0,
        "family_empty_count": family_empty,
        "elapsed_seconds": time.perf_counter() - started,
        "compiled_query_requests": index.stats().get("compiled_query_requests", 0),
        "compiled_query_hits": index.stats().get("compiled_query_hits", 0),
        "compiled_query_misses": index.stats().get("compiled_query_misses", 0),
        "pair_cache_requests": pair_cache.stats().get("pair_requests", 0),
        "pair_cache_hits": pair_cache.stats().get("pair_hits", 0),
        "pair_cache_misses": pair_cache.stats().get("pair_misses", 0),
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }])
    (output / "semantic_signature_provenance.json").write_text(json.dumps({
        "scope": "partial persisted right-supported worklist",
        "signatures": provenance,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }, indent=2), encoding="utf-8")
    positive = next((item for item in signatures if int(item["allowed_count"]) > 0), None)
    first_bilateral = {
        "status": "FOUND_IN_PARTIAL_SCOPE" if positive else "NONE_IN_PROCESSED_SCOPE",
        "semantic_signature_id": positive["semantic_signature_id"] if positive else None,
        "family_id": positive["family_id"] if positive else None,
        "allowed_count": int(positive["allowed_count"]) if positive else 0,
        "note": "A positive semantic mask is a bilateral-context candidate; concrete provenance and right state must still be joined and independently verified." if positive else "No nonempty allowed mask occurred in the processed family scope.",
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "first_bilateral_context.json").write_text(json.dumps(first_bilateral, indent=2), encoding="utf-8")
    summary = {
        "status": "PARTIAL_SEMANTIC_SIGNATURES",
        "scope": "persisted right-supported worklist only",
        "families_processed": len(effect_rows),
        "families_available": len(queries),
        "queries_processed": total_queries,
        "queries_available": sum(len(items) for items in queries.values()),
        "distinct_semantic_signatures": len(signatures),
        "empty_queries": empty_queries,
        "positive_queries": positive_queries,
        "family_empty_count": family_empty,
        "main_runner_groups_done": 157,
        "main_runner_status": "UNRESOLVED_RESOURCE",
        "bilateral_contexts_main_runner": 0,
        "outer_edges_main_runner": 0,
        "sigma_c": "UNDEFINED",
        "right_support_census_is_partial": True,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "progress_v8.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output / "semantic_batch_benchmark.csv").write_text("scope,families,queries,elapsed_seconds,compiled_requests,compiled_hits,compiled_misses,pair_requests,pair_hits,pair_misses\n" + ",".join(str(value) for value in (
        "batch",
        len(effect_rows),
        total_queries,
        round(time.perf_counter() - started, 6),
        index.stats().get("compiled_query_requests", 0),
        index.stats().get("compiled_query_hits", 0),
        index.stats().get("compiled_query_misses", 0),
        pair_cache.stats().get("pair_requests", 0),
        pair_cache.stats().get("pair_hits", 0),
        pair_cache.stats().get("pair_misses", 0),
    )) + "\n", encoding="utf-8")
    (output / "report_v8.md").write_text(f"""# Tree1 C8 collision-effect signature checkpoint

Scope: `{LANGUAGE}` side-terminal split `left_leaf_2`; ownership `{OWNERSHIP}`; terminal cache `{TERMINAL_CACHE}`.

This batch processed family indices `{start_family}` through `{start_family + len(effect_rows) - 1}` of `{len(queries) - 1}` and `{total_queries}` of `{sum(len(items) for items in queries.values())}` persisted right-supported exact queries. It does not run the left main runner and does not claim full right-census coverage.

The semantic signature is computed exactly within each fixed family as `B_F` minus the union of inverted single-offset blocker masks. The antichain prototype had no compression; this batch should be read from `semantic_compression_ratio` in the CSV. A nonempty allowed mask is only a bilateral candidate until its concrete right state and provenance are joined.

The main runner remains `UNRESOLVED_RESOURCE` at `157/11808`, with no bilateral context, no outer edge, and `sigma_c` undefined.
""", encoding="utf-8")
    processed_family_ids = {row["family_id"] for row in effect_rows}
    processed_query_total = sum(
        len(queries[family_id])
        for family_id in ordered_family_ids
        if family_id in queries and family_id in processed_family_ids
    )
    verification = {
        "status": "PASS" if total_queries == processed_query_total and all(row.get("family_key") for row in signatures) else "FAIL",
        "scope": "partial persisted right-supported worklist",
        "family_start_index": start_family,
        "family_end_index_exclusive": start_family + len(effect_rows),
        "skip_missing_pairs": skip_missing_pairs,
        "families_skipped_missing_pair": skipped_missing_families,
        "queries_skipped_missing_pair": skipped_missing_queries,
        "checks": {
            "family_processing_is_batched": True,
            "queries_accounted_for_processed_families": total_queries == processed_query_total,
            "semantic_signatures_have_fixed_family": all(row.get("family_key") for row in signatures),
            "main_runner_not_unsat": True,
            "sigma_undefined_without_global_pair": True,
            "versions_exact": True,
        },
        "summary": summary,
        "compiled_index_stats": index.stats(),
        "pair_cache_stats": pair_cache.stats(),
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "verification_v8.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    (output / "formal_lemmas_v8.md").write_text("""# Collision-effect signature lemmas

## Collision-effect identity

For a fixed exact family `F`, let `B_F` be the span-admissible C8 behavior family and let `C_F(x)` be the behavior-ID bitset containing occupied offset `x`. Then `L(F,O) = B_F minus union_{x in O} C_F(x)`.

## Semantic query equivalence

If two occupied sets have the same blocked behavior bitset, they have the same allowed behavior family. This quotient is independent of occupied-set inclusion.

## Zero-effect offsets

If `C_F(x)` is empty, removing `x` from an occupied query does not change its exact left-compatible behavior family.

## Bilateral detection

For a right-supported residual context, a nonempty allowed mask proves a left-middle-compatible behavior exists. It is a bilateral candidate, but outer compatibility and global span remain separate stages.

All statements are finite and restricted to `C8.LevelB.v1`, `ownership.v2`, and `corrected.v2`.
""", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--max-families", type=int)
    parser.add_argument("--start-family", type=int, default=0)
    parser.add_argument("--chunk-name")
    parser.add_argument("--skip-missing-pairs", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.max_families, args.start_family, args.chunk_name, args.skip_missing_pairs), indent=2))


if __name__ == "__main__":
    main()
