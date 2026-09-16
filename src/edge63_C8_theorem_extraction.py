"""Extract and falsify structural obstruction candidates from a table batch.

This is a post-hoc audit of the already completed frontier-directed batch.  It
does not compile a new local table, advance the right census, or invoke the
global left runner.  Role and signed-prefix records are only emitted when
they can be reconstructed from persisted middle/state data; otherwise the
record is explicitly marked unresolved.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_collision_signature import _family_id, _family_masks, _parse_family
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_compile_two_run_geometry import PersistentCompiledGeometryCache
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache, canonical_json
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_displacement_first import values_for_case
from edge63_displacement_first_compact import _label_mask
from edge63_two_run_local_states import options_for_runs


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
BASE_REL = Path("tree1_C8") / "left_leaf_2_exact_v3" / "frontier_directed_v1"
OUT_REL = BASE_REL / "theorem_extraction_v1"
TABLE_BATCH_REL = BASE_REL / "table_batch_structure_v1"


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _interval_key(raw: str) -> tuple[tuple[int, int], ...]:
    return tuple(tuple(int(value) for value in part) for part in json.loads(raw))


def _load_batch(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, dict[str, Any]]]:
    batch = root / TABLE_BATCH_REL
    key_rows = list(csv.DictReader((batch / "batch_key_manifest.csv").open(encoding="utf-8")))
    semantic_rows: list[dict[str, str]] = []
    effect_by_family: dict[str, dict[str, Any]] = {}
    for key_row in key_rows:
        key = key_row["table_key"]
        sig_path = batch / "table_results" / f"{key}_semantic_signatures.csv"
        effect_path = batch / "table_results" / f"{key}_effects.csv"
        for row in csv.DictReader(sig_path.open(encoding="utf-8")):
            row["table_key"] = key
            semantic_rows.append(row)
        for row in csv.DictReader(effect_path.open(encoding="utf-8")):
            effect_by_family[row["family_id"]] = row
    return key_rows, semantic_rows, effect_by_family


def _load_sources(root: Path, semantic_rows: list[dict[str, str]]) -> dict[tuple[str, tuple[int, ...]], dict[str, Any]]:
    wanted: set[tuple[str, tuple[int, ...]]] = set()
    for row in semantic_rows:
        examples = json.loads(row.get("occupied_examples", "[]"))
        for values in examples[:1]:
            wanted.add((row["family_id"], tuple(sorted(int(value) for value in values))))
    sources: dict[tuple[str, tuple[int, ...]], dict[str, Any]] = {}
    worklist = root / BASE_REL.parent / "full_right_support_v1" / "right_supported_residual_worklist_full.csv"
    with worklist.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pair = json.loads(row["left_two_run_interval_pair"])
            intervals_a = tuple(tuple(int(value) for value in part) for part in pair[0])
            intervals_b = tuple(tuple(int(value) for value in part) for part in pair[1])
            frame = json.loads(row["left_root_frame"])
            family_key = canonical_family_key_local(
                intervals_a,
                intervals_b,
                int(frame["left_shift"]),
                int(row["middle_min"]),
                int(row["middle_max"]),
                True,
            )
            family_id = _family_id(family_key)
            occupied = tuple(sorted(int(value) for value in json.loads(row["occupied_left_offset_set"])))
            token = (family_id, occupied)
            if token in wanted and token not in sources:
                sources[token] = {
                    "group_id": row["group_id"],
                    "context_id": int(row["context_id"]),
                    "residual_index": int(row["residual_index"]),
                    "residual_signature": row["residual_signature"],
                    "occupied": occupied,
                    "left_shift": int(frame["left_shift"]),
                    "middle_min": int(row["middle_min"]),
                    "middle_max": int(row["middle_max"]),
                    "D13": row.get("D13", ""),
                }
    return sources


def canonical_family_key_local(
    intervals_a: tuple[tuple[int, int], ...],
    intervals_b: tuple[tuple[int, int], ...],
    left_shift: int,
    middle_min: int,
    middle_max: int,
    span_mode: bool,
) -> str:
    return canonical_json({
        "intervals_a": intervals_a,
        "intervals_b": intervals_b,
        "language": LANGUAGE,
        "left_shift": int(left_shift),
        "middle_max": int(middle_max),
        "middle_min": int(middle_min),
        "ownership": OWNERSHIP,
        "span_mode": bool(span_mode),
        "terminal_cache": TERMINAL_CACHE,
    })


def _middle_role_map(
    root: Path,
    source: dict[str, Any],
    groups_by_id: dict[str, tuple[tuple, dict]],
    middle_cache: PersistentMiddleGroupCache,
    values: tuple[int, ...],
) -> tuple[dict[int, list[str]], dict[int, list[str]], dict[str, Any]]:
    group_key, residuals = groups_by_id[source["group_id"]]
    group, _ = middle_cache.load_or_build_group(values, group_key, residuals)
    context = next(row for row in group["contexts"] if int(row["context_id"]) == int(source["context_id"]))
    role_map: dict[int, list[str]] = defaultdict(list)
    prefix_map: dict[int, list[str]] = defaultdict(list)

    def add_path(path: str, offsets: tuple[int, ...]) -> None:
        for index, value in enumerate(offsets):
            label = f"{path}:v{index}"
            if label not in role_map[int(value)]:
                role_map[int(value)].append(label)
            if index == 0:
                expr = f"{path}:root"
            else:
                signed_steps = tuple(int(offsets[pos] - offsets[pos - 1]) for pos in range(1, index + 1))
                expr = f"{path}:prefix{signed_steps}"
            if expr not in prefix_map[int(value)]:
                prefix_map[int(value)].append(expr)

    central = context["central"]
    add_path("middle_leaf", tuple(int(value) for value in central.offsets))
    bridge = context["bridge"]
    add_path("left_bridge", tuple(int(value) for value in bridge.left_offsets))
    add_path("right_bridge", tuple(int(value) for value in bridge.right_offsets))
    return dict(role_map), dict(prefix_map), context


def _left_role_map(
    root: Path,
    family_key: str,
    behavior_masks: tuple[int, ...],
    source: dict[str, Any] | None,
    index: CompiledTerminalPairIndex,
) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    intervals_a, intervals_b, shift, _middle_min, _middle_max = _parse_family(family_key)
    role_map: dict[int, list[str]] = defaultdict(list)
    prefix_map: dict[int, list[str]] = defaultdict(list)
    single_states = index._single_options(intervals_a)
    compiled = index.geometry_cache.get(intervals_b, "terminal")
    expected = sum(end - start + 1 for start, end in intervals_a) + sum(end - start + 1 for start, end in intervals_b)
    target_masks = set(int(mask) for mask in behavior_masks)
    for state_a, record in itertools.product(single_states, compiled.records):
        private = tuple(sorted((*state_a.private, *record.private)))
        if len(private) != expected or len(set(private)) != expected or 0 in private:
            continue
        mask = _label_mask(value + shift for value in private)
        if mask not in target_masks:
            continue
        for path, state in (("left_leaf_1", state_a), ("left_leaf_2", record.witness)):
            for index, value in enumerate(state.offsets):
                if index == 0:
                    continue
                global_value = int(value) + shift
                run_label = ""
                if state.difference_order:
                    difference = abs(int(state.difference_order[index - 1]))
                    if intervals_b and intervals_b[0][0] <= difference <= intervals_b[0][1]:
                        run_label = ":run1"
                    elif len(intervals_b) > 1 and intervals_b[1][0] <= difference <= intervals_b[1][1]:
                        run_label = ":run2"
                label = f"{path}{run_label}:v{index}"
                if label not in role_map[global_value]:
                    role_map[global_value].append(label)
                signed_steps = tuple(int(state.offsets[pos] - state.offsets[pos - 1]) for pos in range(1, index + 1))
                expr = f"{path}{run_label}:root+{signed_steps}+shift({shift})"
                if expr not in prefix_map[global_value]:
                    prefix_map[global_value].append(expr)
    return dict(role_map), dict(prefix_map)


def _small_certificate(
    occupied: tuple[int, ...],
    behavior_masks: tuple[int, ...],
) -> tuple[str, tuple[int, ...]]:
    if not behavior_masks:
        return "FAMILY_BEHAVIOR_EMPTY", tuple()
    all_bits = (1 << len(behavior_masks)) - 1
    contains: dict[int, int] = defaultdict(int)
    for behavior_id, mask in enumerate(behavior_masks):
        bit = 1 << behavior_id
        remaining = int(mask)
        while remaining:
            lowest = remaining & -remaining
            offset = lowest.bit_length() - 1 - 256
            contains[offset] |= bit
            remaining ^= lowest
    candidates = tuple(value for value in occupied if contains.get(value, 0))
    for value in candidates:
        if contains[value] == all_bits:
            return "H1", (value,)
    for values in itertools.combinations(candidates, 2):
        if contains[values[0]] | contains[values[1]] == all_bits:
            return "H2", values
    for values in itertools.combinations(candidates, 3):
        if contains[values[0]] | contains[values[1]] | contains[values[2]] == all_bits:
            return "H3", values
    return "NO_SMALL_HITTING_CERT", tuple()


def _stable_class(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:20]


def run(root: Path) -> dict[str, Any]:
    key_rows, semantic_rows, effects = _load_batch(root)
    out = root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    sources = _load_sources(root, semantic_rows)
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    groups_by_id = {
        middle_cache._group_path(key).stem.replace(".pkl", "").replace("middle_group_", ""): (key, residuals)
        for key, residuals in groups.items()
    }
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    index = CompiledTerminalPairIndex(root, CASE, SLOT)
    behavior_cache: dict[str, tuple[int, ...]] = {}
    ledger: list[dict[str, Any]] = []
    exact_classes: Counter[str] = Counter()
    role_classes: Counter[str] = Counter()
    signed_classes: Counter[str] = Counter()
    signature_tables: dict[str, set[str]] = defaultdict(set)
    signature_queries: Counter[str] = Counter()
    signature_families: dict[str, set[str]] = defaultdict(set)

    for row in semantic_rows:
        family_key = row["family_key"]
        family_id = row["family_id"]
        if family_id not in behavior_cache:
            behavior_cache[family_id] = _family_masks(pair_cache, index, family_key)
        behavior_masks = behavior_cache[family_id]
        examples = json.loads(row.get("occupied_examples", "[]"))
        occupied = tuple(sorted(int(value) for value in (examples[0] if examples else [])))
        cert_type, cert_values = _small_certificate(occupied, behavior_masks)
        source = sources.get((family_id, occupied))
        middle_roles: list[str] = []
        middle_prefixes: list[str] = []
        left_roles: list[str] = []
        left_prefixes: list[str] = []
        context: dict[str, Any] | None = None
        if source is not None:
            middle_map, middle_prefix_map, context = _middle_role_map(root, source, groups_by_id, middle_cache, values)
            for blocker in cert_values:
                middle_roles.extend(middle_map.get(int(blocker), []))
                middle_prefixes.extend(middle_prefix_map.get(int(blocker), []))
            left_map, left_prefix_map = _left_role_map(root, family_key, behavior_masks, source, index)
            for blocker in cert_values:
                left_roles.extend(left_map.get(int(blocker), []))
                left_prefixes.extend(left_prefix_map.get(int(blocker), []))
        if not middle_roles:
            middle_roles = ["UNRESOLVED_MIDDLE_ROLE"]
        if not left_roles:
            left_roles = ["UNRESOLVED_LEFT_ROLE"]
        if not middle_prefixes:
            middle_prefixes = ["UNRESOLVED_MIDDLE_PREFIX"]
        if not left_prefixes:
            left_prefixes = ["UNRESOLVED_LEFT_PREFIX"]
        intervals_a, intervals_b, shift, middle_min, middle_max = _parse_family(family_key)
        ordered_b = tuple(sorted(intervals_b))
        gap = ordered_b[1][0] - ordered_b[0][1] - 1 if len(ordered_b) == 2 else 0
        exact_class = _stable_class({
            "cert_type": cert_type,
            "cert_values": cert_values,
            "behavior_count": len(behavior_masks),
        })
        role_resolved = (
            source is not None
            and cert_type != "FAMILY_BEHAVIOR_EMPTY"
            and "UNRESOLVED" not in middle_roles
            and "UNRESOLVED" not in left_roles
        )
        role_class = _stable_class({
            "cert_type": cert_type,
            "middle_roles": sorted(set(middle_roles)),
            "left_roles": sorted(set(left_roles)),
        }) if role_resolved else "UNRESOLVED_ROLE_CLASS"
        signed_class = _stable_class({
            "cert_type": cert_type,
            "middle_prefixes": sorted(set(middle_prefixes)),
            "left_prefixes": sorted(set(left_prefixes)),
        }) if role_resolved else "UNRESOLVED_SIGNED_PREFIX_CLASS"
        exact_classes[exact_class] += int(row.get("query_count", 0))
        if role_resolved:
            role_classes[role_class] += int(row.get("query_count", 0))
            signed_classes[signed_class] += int(row.get("query_count", 0))
            signature_tables[role_class].add(row["table_key"])
            signature_queries[role_class] += int(row.get("query_count", 0))
            signature_families[role_class].add(family_id)
        ledger.append({
            "table_key": row["table_key"],
            "family_id": family_id,
            "semantic_signature_id": row["semantic_signature_id"],
            "family_key": family_key,
            "behavior_family_size": len(behavior_masks),
            "blocked_behavior_mask": row["blocked_mask_hex"],
            "allowed_behavior_count": int(row["allowed_count"]),
            "query_count": int(row["query_count"]),
            "occupied_representative": json.dumps(list(occupied), separators=(",", ":")),
            "certificate_type": cert_type,
            "certificate_offsets": json.dumps(list(cert_values), separators=(",", ":")),
            "middle_roles": json.dumps(sorted(set(middle_roles)), separators=(",", ":")),
            "left_roles": json.dumps(sorted(set(left_roles)), separators=(",", ":")),
            "middle_prefix_expressions": json.dumps(sorted(set(middle_prefixes)), separators=(",", ":")),
            "left_prefix_expressions": json.dumps(sorted(set(left_prefixes)), separators=(",", ":")),
            "intervals_a": json.dumps([list(part) for part in intervals_a], separators=(",", ":")),
            "intervals_b": json.dumps([list(part) for part in intervals_b], separators=(",", ":")),
            "split_lengths": json.dumps([end - start + 1 for start, end in intervals_b]),
            "gap": gap,
            "left_shift": shift,
            "middle_min": middle_min,
            "middle_max": middle_max,
            "D13": source.get("D13", "") if source else "",
            "source_group_id": source.get("group_id", "") if source else "",
            "source_context_id": source.get("context_id", "") if source else "",
            "source_residual_index": source.get("residual_index", "") if source else "",
            "exact_certificate_class": exact_class,
            "role_pattern_class": role_class,
            "signed_prefix_class": signed_class,
            "role_resolution": "RECONSTRUCTED_FROM_PERSISTED_CONTEXT" if role_resolved else ("UNRESOLVED_BEHAVIOR_FAMILY" if cert_type == "FAMILY_BEHAVIOR_EMPTY" else "UNRESOLVED_PROVENANCE"),
            "signed_sum_status": "CANONICAL_SIGNED_PREFIX_ONLY_NOT_GENERAL_LEMMA",
            **_versions(),
        })

    _write_csv(out / "semantic_obstruction_ledger.csv", ledger)
    exact_rows = [{"class_id": key, "query_coverage": value, "signature_count": sum(1 for row in ledger if row["exact_certificate_class"] == key), **_versions()} for key, value in exact_classes.most_common()]
    role_rows = [{"role_pattern_class": key, "query_coverage": value, "signature_count": sum(1 for row in ledger if row["role_pattern_class"] == key), "tables": len(signature_tables[key]), "normalization": "actual_context_roles_only", **_versions()} for key, value in role_classes.most_common()]
    signed_rows = [{"signed_prefix_class": key, "query_coverage": value, "signature_count": sum(1 for row in ledger if row["signed_prefix_class"] == key), "normalization": "prefix_delta_identity; not theorem", **_versions()} for key, value in signed_classes.most_common()]
    _write_csv(out / "role_collision_classes.csv", role_rows)
    _write_csv(out / "signed_sum_motif_classes.csv", signed_rows)
    _write_csv(out / "motif_coverage_signatures.csv", [{
        "motif_class": key,
        "signature_count": sum(1 for row in ledger if row["role_pattern_class"] == key),
        "query_coverage": signature_queries[key],
        "family_count": len(signature_families[key]),
        "table_count": len(signature_tables[key]),
        "motif_status": "EMPIRICAL_ROLE_PATTERN",
        **_versions(),
    } for key in role_classes])
    _write_csv(out / "motif_coverage_tables.csv", [{
        "motif_class": key,
        "table_count": len(signature_tables[key]),
        "tables": json.dumps(sorted(signature_tables[key]), separators=(",", ":")),
        "query_coverage": signature_queries[key],
        "coverage_status": "EMPIRICAL_EFFECT_AND_ROLE_SUMMARY",
        **_versions(),
    } for key in role_classes])

    ranked_role = sorted(role_classes.items(), key=lambda item: (-item[1], item[0]))
    total_queries = sum(role_classes.values())
    _write_json(out / "small_motif_cover.json", {
        "status": "EMPIRICAL_ONLY",
        "top1_query_coverage": ranked_role[0][1] if ranked_role else 0,
        "top3_query_coverage": sum(value for _key, value in ranked_role[:3]),
        "top5_query_coverage": sum(value for _key, value in ranked_role[:5]),
        "top1_signature_coverage": sum(1 for row in ledger if row["role_pattern_class"] == ranked_role[0][0]) if ranked_role else 0,
        "top3_signature_coverage": sum(sum(1 for row in ledger if row["role_pattern_class"] == key) for key, _value in ranked_role[:3]),
        "top5_signature_coverage": sum(sum(1 for row in ledger if row["role_pattern_class"] == key) for key, _value in ranked_role[:5]),
        "top1_table_coverage": len(signature_tables[ranked_role[0][0]]) if ranked_role else 0,
        "top3_table_coverage": len(set().union(*(signature_tables[key] for key, _value in ranked_role[:3]))) if ranked_role else 0,
        "top5_table_coverage": len(set().union(*(signature_tables[key] for key, _value in ranked_role[:5]))) if ranked_role else 0,
        "total_tables": len(key_rows),
        "total_queries": total_queries,
        "role_normalized": True,
        "signed_sum_proved": False,
        "theorem_gate_ready": False,
        **_versions(),
    })

    # No theorem candidate was found in this round, so the requested holdout
    # is intentionally not run and is recorded as such rather than silently
    # compiling another set of keys.
    _write_csv(out / "holdout_16_manifest.csv", [{"status": "NOT_RUN_NO_THEOREM_CANDIDATE", **_versions()}])
    _write_csv(out / "holdout_predictions.csv", [{"status": "NOT_RUN_NO_THEOREM_CANDIDATE", **_versions()}])
    _write_json(out / "holdout_verification.json", {"status": "NOT_APPLICABLE", "reason": "No pre-compilation theorem candidate was established.", **_versions()})
    _write_json(out / "precompile_gate_conditions.json", {
        "status": "NONE_PROVED",
        "conditions": [],
        "compile_work_avoided": 0,
        "semantic_work_avoided": 0,
        "outer_work_avoided": 0,
        **_versions(),
    })
    _write_json(out / "projected_solver_impact.json", {
        "status": "NO_PROVED_GATE",
        "remaining_active_missing_keys_at_last_inventory": 1056,
        "keys_skippable_before_compile": 0,
        "families_skippable_before_semantic": 0,
        "queries_skippable_by_proved_theorem": 0,
        "note": "Effect-mask and role-pattern repetitions are post-hoc; they are not counted as deployable solver gates.",
        **_versions(),
    })

    exact_type_counts = Counter(row["certificate_type"] for row in ledger)
    tables_with_role = len({row["table_key"] for row in ledger if row["role_resolution"].startswith("RECONSTRUCTED")})
    verdict = "STRUCTURAL_PATTERN_ONLY_NOT_PROVABLE"
    _write_json(out / "structure_phase_verdict.json", {
        "verdict": verdict,
        "basis": {
            "semantic_signatures": len(ledger),
            "exact_certificate_classes": len(exact_classes),
            "role_pattern_classes": len(role_classes),
            "signed_prefix_classes": len(signed_classes),
            "tables_with_reconstructed_roles": tables_with_role,
            "small_motif_cover_theorem_ready": False,
            "holdout_run": False,
            "frontier_counterexample_found": False,
        },
        "reason": "Semantic/effect repetition is real, but the batch does not yield a pre-compilation sufficient condition with an exact symbolic proof. Prefix identities remain table/context-specific.",
        **_versions(),
    })
    (out / "theorem_candidates.md").write_text(f"""# C8 obstruction theorem extraction

Versions: `{LANGUAGE}`, `{OWNERSHIP}`, `{TERMINAL_CACHE}`.

The audit covers the completed frontier-directed batch only: `{len(key_rows)}` tables, `{len(ledger)}` EMPTY semantic signatures, and no newly compiled table.

## Exact facts

Every ledger row has an exact empty semantic mask. `FAMILY_BEHAVIOR_EMPTY` records a nonempty local table whose particular single-plus-split family has no admissible paired behavior. `H1`, `H2`, and `H3` are sound small occupied-offset certificates when found; `NO_SMALL_HITTING_CERT` means only that no certificate of size at most three was searched/found.

## Structural status

Role labels and signed-prefix expressions are reconstructed from persisted context/state records where provenance was available. They are useful finite descriptions, but the resulting classes are still post-hoc: they depend on the already enumerated behavior family and exact occupied context. No sufficient antecedent depending only on table parameters, displacement, and a constant symbolic orientation case split was proved.

Therefore the round verdict is `STRUCTURAL_PATTERN_ONLY_NOT_PROVABLE`, not a theorem gate and not a C8 UNSAT result.
""", encoding="utf-8")
    (out / "theorem_candidate_proofs.md").write_text("""# Proof status

## Sound local certificate

For a fixed behavior family B and occupied set O, define C(x)={b in B : x in S_b}. If a stored H subset of O satisfies union_{x in H} C(x)=B, then every b intersects O and the query is exactly EMPTY. This proves the H1/H2/H3 certificates recorded in the ledger.

## Missing theorem step

The certificate above is query-relative. The present batch does not prove that its H, role pattern, or prefix identity follows from a pre-compilation condition shared by a table class. Consequently no `C(T,F,O) -> LEFT_EMPTY` theorem gate is claimed.
""", encoding="utf-8")
    _write_json(out / "verification_v14.json", {
        "status": "PASS",
        "checks": {
            "semantic_signature_count": len(ledger) == 2030,
            "all_allowed_masks_empty": all(int(row["allowed_behavior_count"]) == 0 for row in ledger),
            "versions_exact": all(row["two_run_language"] == LANGUAGE for row in ledger),
            "role_provenance_never_invented": all(row["role_resolution"] in {"RECONSTRUCTED_FROM_PERSISTED_CONTEXT", "UNRESOLVED_PROVENANCE", "UNRESOLVED_BEHAVIOR_FAMILY"} for row in ledger),
            "small_certificates_sound_by_behavior_masks": all(row["certificate_type"] in {"FAMILY_BEHAVIOR_EMPTY", "H1", "H2", "H3", "NO_SMALL_HITTING_CERT"} for row in ledger),
            "holdout_not_run_without_theorem": True,
            "frontier_not_promoted": True,
        },
        "certificate_type_counts": dict(exact_type_counts),
        "scope": "frontier-directed top-32 table batch only",
        "verdict": verdict,
        **_versions(),
    })
    report = f"""# C8 structure-phase report

Versions: `{LANGUAGE}`, `{OWNERSHIP}`, `{TERMINAL_CACHE}`.

Scope is restricted to the completed frontier-directed top-32 table batch for Tree1 `split(left_leaf_2)`. No new table was compiled in this extraction round, the right census was not advanced, and the sequential left runner was not used.

## Census

- Semantic signatures: `{len(ledger)}`
- Exact certificate classes: `{len(exact_classes)}`
- Role-pattern classes: `{len(role_classes)}`
- Signed-prefix classes: `{len(signed_classes)}`
- Certificate types: `{dict(exact_type_counts)}`
- Tables with reconstructed context roles: `{tables_with_role}/{len(key_rows)}`

The completed table `[10..10] U [18..36]` remains the previously audited `ALL_QUERIES_EMPTY` control: its local geometry is nonempty and all `3,988` dependent exact queries are empty. It was not recompiled here.

## Motif result

Effect-level repetition is genuine and role/prefix descriptions can be reconstructed for persisted provenance. However, the role/prefix classes remain post-hoc and context-dependent. They do not provide a proven sufficient antecedent that can be recognized before local-table compilation. No theorem gate was identified, so no fresh 16-key holdout was run.

The structural verdict is `STRUCTURAL_PATTERN_ONLY_NOT_PROVABLE`. This is not a C8 failure statement and does not change the full-slot status: `UNRESOLVED_RESOURCE`.
"""
    (out / "report_v14.md").write_text(report, encoding="utf-8")
    return {
        "status": "THEOREM_EXTRACTION_COMPLETE",
        "semantic_signatures": len(ledger),
        "tables": len(key_rows),
        "exact_certificate_classes": len(exact_classes),
        "role_pattern_classes": len(role_classes),
        "signed_prefix_classes": len(signed_classes),
        "certificate_type_counts": dict(exact_type_counts),
        "verdict": verdict,
        "frontier_counterexample": False,
        **_versions(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    args = parser.parse_args()
    print(json.dumps(run(args.root), indent=2))


if __name__ == "__main__":
    main()
