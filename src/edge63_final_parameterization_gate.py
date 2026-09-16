"""Final bounded compression audit for Tree3 left compatibility.

This module does not enlarge the Level-B language or search new graceful
labelings. It replays the already closed corrected.v2 context corpus and
tests whether occupied-offset and left-facing interfaces separate the 146
nonempty controls from the 19306 left-empty contexts.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_displacement_first_compact import (  # noqa: E402
    TerminalIndexCache,
    all_allocations,
    middle_contexts,
    path_lengths,
)
from edge63_structure_analysis import parse_case  # noqa: E402


CASE = "fiveleaf3e-63-3-21-2-14-15-4-4"
EDGE = 63
OUT = Path("results/edge63_tree3_left_block_final_compression")
SOURCE = Path("results/edge63_tree3_left_block_parameterization")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_offsets(text: str) -> tuple[int, ...]:
    if not text:
        return ()
    return tuple(int(value) for value in text.split(";"))


def interval_text(block: tuple[int, int]) -> str:
    return f"{block[0]}-{block[1]}"


def run_stats(values: tuple[int, ...]) -> tuple[int, int]:
    if not values:
        return 0, 0
    ordered = sorted(set(values))
    count = 1
    longest = 1
    current = 1
    for left, right in zip(ordered, ordered[1:]):
        if right == left + 1:
            current += 1
        else:
            count += 1
            longest = max(longest, current)
            current = 1
    return count, max(longest, current)


def role_map(context) -> dict[int, str]:
    delta_left = int(context["delta_left"])
    delta_right = int(context["delta_right"])
    roles = {
        -delta_left: "SHARED_ROOT_r1",
        0: "SHARED_ROOT_r2",
        delta_right: "SHARED_ROOT_r3",
    }
    bridge = context["bridge"]
    for index, value in enumerate(bridge.left_offsets[1:-1], 1):
        roles[value - delta_left] = f"left_bridge_internal[{index}]"
    for index, value in enumerate(bridge.right_offsets[1:-1], 1):
        roles[value] = f"right_bridge_internal[{index}]"
    central = context["central"]
    for index, value in enumerate(central.offsets[1:], 1):
        roles[value] = f"middle_leaf_private[{index}]"
    return roles


def digest(value) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()[:20]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source_contexts = read_csv(SOURCE / "middle_context_features.csv")
    source_h = {
        (row["triple_id"], row["context_id"]): row
        for row in read_csv(SOURCE / "mandatory_kernel_analysis.csv")
    }
    if len(source_contexts) != 19452:
        raise AssertionError("corrected.v2 context corpus is incomplete")

    parsed = parse_case(CASE)
    if parsed is None or parsed[1] != EDGE:
        raise ValueError(CASE)
    lengths = path_lengths(parsed[2])
    _, middle_to_orders, _ = all_allocations(parsed[2])
    index_cache = TerminalIndexCache(64)

    records: list[dict[str, object]] = []
    occupied_h_distribution = Counter()
    blocker_kind_distribution = Counter()
    shared_root_cases: list[dict[str, object]] = []
    footprint_groups = defaultdict(lambda: Counter())
    key_groups = {f"K{i}": defaultdict(set) for i in range(1, 6)}
    key_contexts = {f"K{i}": defaultdict(list) for i in range(1, 6)}
    exact_footprint_groups = defaultdict(set)
    exact_footprint_contexts = defaultdict(list)
    motif_groups = {1: defaultdict(set), 2: defaultdict(set), 3: defaultdict(set)}
    high_h_rows: list[dict[str, object]] = []
    control_rows: list[dict[str, object]] = []
    global_id = 0

    for triple_id, (middle_key, residual_items) in enumerate(middle_to_orders.items()):
        left_block, central_block, right_block = middle_key
        contexts, _stats = middle_contexts(
            left_block[1], left_block[2] - left_block[1] + 1,
            central_block[1], central_block[2] - central_block[1] + 1,
            right_block[1], right_block[2] - right_block[1] + 1,
            "B",
        )
        for context in contexts:
            context_id = str(context["context_id"])
            source = source_contexts[global_id]
            if source["triple_id"] != str(triple_id) or source["context_id"] != context_id:
                raise AssertionError("context ordering disagrees with corrected.v2 corpus")

            delta_left = int(context["delta_left"])
            delta_right = int(context["delta_right"])
            middle_values = tuple(context["all_values"])
            middle_set = set(middle_values)
            own_left_root = -delta_left
            occupied = tuple(sorted(middle_set - {own_left_root}))
            roles = role_map(context)

            left_pairs = set()
            raw_offsets = set()
            span_states = set()
            for residual in residual_items:
                blocks = residual["blocks"]
                left_pairs.add(
                    f"{interval_text(blocks['left_leaf_1'])};{interval_text(blocks['left_leaf_2'])}"
                )
                left_key = (
                    "left_leaf_1", blocks["left_leaf_1"][0], lengths["left_leaf_1"],
                    "left_leaf_2", blocks["left_leaf_2"][0], lengths["left_leaf_2"],
                )
                index = index_cache.get(left_key, "B")
                for state in index.states:
                    shifted = tuple(sorted(value - delta_left for value in state.private))
                    raw_offsets.update(shifted)
                    low = min(min(middle_values), min(shifted, default=0))
                    high = max(max(middle_values), max(shifted, default=0))
                    if high - low <= EDGE:
                        span_states.add(shifted)

            footprint = tuple(sorted(set(occupied) & raw_offsets))
            span_signature = tuple(sorted(span_states))
            footprint_runs, footprint_longest = run_stats(footprint)
            h_source = source_h[(source["triple_id"], source["context_id"])]
            h_status = h_source["h_all_status"]
            h_value = h_source["h_all"]
            h_offsets = parse_offsets(h_source["h_all_offsets"])
            if h_status == "EXACT":
                if any(offset not in occupied for offset in h_offsets):
                    raise AssertionError("occupied hitting set uses the left path's own legal root")
                occupied_h_distribution[(h_status, str(h_value))] += 1

                # For h=1, h_offsets is the complete singleton kernel, so classify
                # all available singleton blocker roles. For h>=2 it is the
                # canonical exact minimum hitting set returned by the solver.
                if h_value.isdigit():
                    h_int = int(h_value)
                    root_offsets = {0, delta_right}
                    root_hits_count = sum(offset in root_offsets for offset in h_offsets)
                    if root_hits_count == len(h_offsets):
                        blocker_kind = "SHARED_ROOT_ONLY"
                    elif root_hits_count == 0:
                        blocker_kind = "PRIVATE_OR_INTERNAL_ONLY"
                    else:
                        blocker_kind = "MIXED"
                    blocker_kind_distribution[(h_int, blocker_kind)] += 1

            private_status = h_source["h_private_status"]
            root_candidates = {-delta_left: "SHARED_ROOT_r1", 0: "SHARED_ROOT_r2", delta_right: "SHARED_ROOT_r3"}
            usable_roots = {offset: role for offset, role in root_candidates.items() if offset != own_left_root}
            root_hits = tuple(sorted((offset, usable_roots[offset]) for offset in h_offsets if offset in usable_roots))
            if private_status == "INFEASIBLE":
                shared_root_cases.append({
                    "global_context_id": source["global_context_id"],
                    "triple_id": triple_id,
                    "context_id": context_id,
                    "left_interval_pairs": "|".join(sorted(left_pairs)),
                    "delta_left": delta_left,
                    "delta_right": delta_right,
                    "D13": delta_left + delta_right,
                    "span_feasible_left_states": source["left_span_feasible_states"],
                    "private_h_status": private_status,
                    "occupied_h": h_value,
                    "occupied_h_offsets": ";".join(map(str, h_offsets)),
                    "shared_root_blockers": ";".join(f"{offset}:{role}" for offset, role in root_hits),
                    "left_root_excluded": own_left_root,
                    "root_semantics": "r1 excluded as the left pair's legal shared endpoint; r2/r3 remain occupied blockers",
                })

            status = "EMPTY" if source["left_empty"] == "True" else "NONEMPTY"
            left_pair_key = "|".join(sorted(left_pairs))
            k1 = (left_pair_key, delta_left)
            k2 = k1 + (min(middle_values), max(middle_values))
            k3 = k2 + (len(footprint), footprint_runs, footprint_longest)
            role_motif = tuple(sorted(roles.get(offset, "OCCUPIED_INTERNAL") for offset in h_offsets))
            k4 = k3 + (h_value, role_motif)
            k5 = (span_signature, footprint)
            for name, key in {"K1": k1, "K2": k2, "K3": k3, "K4": k4, "K5": k5}.items():
                key_groups[name][key].add(status)
                key_contexts[name][key].append(source["global_context_id"])
            exact_footprint_key = (
                left_pair_key, delta_left, min(middle_values), max(middle_values), footprint
            )
            exact_footprint_groups[exact_footprint_key].add(status)
            exact_footprint_contexts[exact_footprint_key].append(source["global_context_id"])

            if h_status == "EXACT" and h_value.isdigit() and int(h_value) in motif_groups:
                motif_groups[int(h_value)][(h_offsets, role_motif)].add(source["global_context_id"])
            if h_status == "EXACT" and h_value.isdigit() and int(h_value) >= 4:
                high_h_rows.append({
                    "global_context_id": source["global_context_id"],
                    "triple_id": triple_id,
                    "context_id": context_id,
                    "occupied_h": h_value,
                    "occupied_h_offsets": ";".join(map(str, h_offsets)),
                    "left_interface_digest_K5": digest(k5),
                })

            footprint_groups[footprint][status] += 1
            row = {
                "global_context_id": source["global_context_id"],
                "triple_id": triple_id,
                "context_id": context_id,
                "status": status,
                "blocking_subtype": source["blocking_subtype"],
                "left_block_detail": source["left_block_detail"],
                "left_interval_pairs": left_pair_key,
                "delta_left": delta_left,
                "delta_right": delta_right,
                "D13": delta_left + delta_right,
                "middle_min": min(middle_values),
                "middle_max": max(middle_values),
                "middle_span": max(middle_values) - min(middle_values),
                "occupied_offset_count": len(occupied),
                "occupied_offsets": ";".join(map(str, occupied)),
                "left_root_excluded": own_left_root,
                "left_raw_offset_count": len(raw_offsets),
                "left_span_behavior_count": len(span_signature),
                "left_span_behavior_digest": digest(span_signature),
                "left_facing_footprint": ";".join(map(str, footprint)),
                "footprint_count": len(footprint),
                "footprint_run_count": footprint_runs,
                "footprint_longest_run": footprint_longest,
                "footprint_digest": digest(footprint),
                "occupied_h_status": h_status,
                "occupied_h": h_value,
                "occupied_h_offsets": ";".join(map(str, h_offsets)),
                "occupied_h_role_motif": ";".join(role_motif),
                "private_h_status": private_status,
                "K1_digest": digest(k1),
                "K2_digest": digest(k2),
                "K3_digest": digest(k3),
                "K4_digest": digest(k4),
                "K5_digest": digest(k5),
            }
            records.append(row)
            if status == "NONEMPTY":
                control_rows.append({
                    "global_context_id": source["global_context_id"],
                    "left_interval_pairs": left_pair_key,
                    "delta_left": delta_left,
                    "middle_min": min(middle_values),
                    "middle_max": max(middle_values),
                    "span_feasible_left_states": source["left_span_feasible_states"],
                    "collision_free_left_states": source["left_collision_free_states"],
                    "occupied_h": h_value,
                    "K1_digest": digest(k1),
                    "K2_digest": digest(k2),
                    "K3_digest": digest(k3),
                    "K4_digest": digest(k4),
                    "K5_digest": digest(k5),
                })
            global_id += 1

    if global_id != len(source_contexts):
        raise AssertionError("context replay count mismatch")

    write_csv(OUT / "occupied_domain_hitting_distribution.csv", [
        {"offset_domain": "occupied_offsets", "status": status, "h": h, "context_count": count}
        for (status, h), count in sorted(occupied_h_distribution.items(), key=lambda item: (int(item[0][1]), item[0][0]))
    ])
    subtype_counts = Counter(
        row["left_block_detail"] for row in records if row["status"] == "EMPTY"
    )
    write_csv(OUT / "left_empty_subtypes.csv", [
        {"blocking_subtype": subtype, "context_count": subtype_counts[subtype]}
        for subtype in ("SPAN_ONLY_BLOCK", "COLLISION_ONLY_BLOCK", "MIXED_BLOCK")
    ])
    write_csv(OUT / "occupied_blocker_kind_summary.csv", [
        {"h": h, "blocker_kind": kind, "context_count": count,
         "interpretation": (
             "available singleton blockers in the full kernel" if h == 1
             else "canonical exact minimum hitting set"
         )}
        for (h, kind), count in sorted(blocker_kind_distribution.items())
    ])
    write_csv(OUT / "shared_root_block_cases.csv", shared_root_cases)
    write_csv(OUT / "left_facing_footprint_classes.csv", [
        {
            "footprint_digest": digest(footprint),
            "footprint": ";".join(map(str, footprint)),
            "footprint_count": len(footprint),
            "run_count": run_stats(footprint)[0],
            "longest_run": run_stats(footprint)[1],
            "context_count": sum(counter.values()),
            "empty_contexts": counter["EMPTY"],
            "nonempty_controls": counter["NONEMPTY"],
        }
        for footprint, counter in sorted(footprint_groups.items(), key=lambda item: (len(item[0]), item[0]))
    ])

    compression_rows = []
    definitions = {
        "K1": "(left_interval_pair, Delta_L)",
        "K2": "K1 + (middle_min, middle_max)",
        "K3": "K2 + (|F_L|, run_count(F_L), longest_run(F_L))",
        "K4": "K3 + occupied h and role-annotated hitting motif",
        "K5": "(exact span-feasible left behavior signature, exact F_L)",
    }
    for name in ("K1", "K2", "K3", "K4", "K5"):
        groups = key_groups[name]
        mixed = [key for key, labels in groups.items() if labels == {"EMPTY", "NONEMPTY"}]
        compression_rows.append({
            "key": name,
            "classes": len(groups),
            "mixed_classes": len(mixed),
            "mixed_contexts": sum(len(key_contexts[name][key]) for key in mixed),
            "empty_classes": sum("EMPTY" in labels for labels in groups.values()),
            "nonempty_classes": sum("NONEMPTY" in labels for labels in groups.values()),
            "exact_separating": len(mixed) == 0,
            "key_definition": definitions[name],
        })
    write_csv(OUT / "compression_quality_K1_K5.csv", compression_rows)
    exact_footprint_mixed = [
        key for key, labels in exact_footprint_groups.items()
        if labels == {"EMPTY", "NONEMPTY"}
    ]
    write_csv(OUT / "left_interface_exact_classes.csv", [{
        "key": "(left_interval_pair, Delta_L, middle_min, middle_max, exact_F_L)",
        "classes": len(exact_footprint_groups),
        "mixed_classes": len(exact_footprint_mixed),
        "mixed_contexts": sum(len(exact_footprint_contexts[key]) for key in exact_footprint_mixed),
        "empty_classes": sum("EMPTY" in labels for labels in exact_footprint_groups.values()),
        "nonempty_classes": sum("NONEMPTY" in labels for labels in exact_footprint_groups.values()),
        "exact_separating": len(exact_footprint_mixed) == 0,
    }])
    write_csv(OUT / "high_h_residual.csv", high_h_rows)
    write_csv(OUT / "left_nonempty_control_collisions.csv", control_rows)

    for h in (1, 2, 3):
        write_csv(OUT / f"blocker_motif_classes_h{h}.csv", [
            {
                "h": h,
                "raw_offsets": ";".join(map(str, offsets)),
                "role_motif": ";".join(roles),
                "context_count": len(context_ids),
                "context_ids": ";".join(sorted(context_ids, key=int)),
            }
            for (offsets, roles), context_ids in sorted(motif_groups[h].items())
        ])

    all_empty = sum(row["status"] == "EMPTY" for row in records)
    controls = sum(row["status"] == "NONEMPTY" for row in records)
    h_le_3 = sum(count for (status, h), count in occupied_h_distribution.items() if status == "EXACT" and int(h) <= 3)
    k4 = next(row for row in compression_rows if row["key"] == "K4")
    k5 = next(row for row in compression_rows if row["key"] == "K5")
    motif_counts = {f"h{h}": sum(len(ids) for ids in motif_groups[h].values()) for h in (1, 2, 3)}
    if k5["mixed_classes"] == 0 and (k4["mixed_classes"] > 0 or k4["classes"] >= 1000):
        decision = "STOP_LOW_DIMENSIONAL_PARAMETERIZATION"
        decision_reason = "K5 is exact, but K4 is exact-separating only at high cardinality; full local behavior/footprint is needed for a compact sound separation."
    elif k4["mixed_classes"] == 0 and k4["classes"] < 3000:
        decision = "CONTINUE_SINGLE_INTERVAL PARAMETERIZATION"
        decision_reason = "K4 is exact-separating and materially smaller than the previous class census."
    elif sum(motif_counts.values()) <= 100:
        decision = "CONTINUE_SINGLE INTERVAL PARAMETERIZATION"
        decision_reason = "The h<=3 blocker motifs collapse to a small finite family."
    else:
        decision = "STOP_LOW_DIMENSIONAL_PARAMETERIZATION"
        decision_reason = "No tested low-dimensional key or small blocker-motif family meets the pre-registered GO criteria."

    certificate = {
        "certificate_version": "tree3-final-compression.v1",
        "case": CASE,
        "cache_version": "corrected.v2",
        "language": "complete Level-B single-interval language",
        "occupied_domain": {
            "definition": "all middle-frame occupied offsets except the left terminal pair's own legal root",
            "left_root_excluded": True,
            "shared_roots_r2_r3_remain_blockers": True,
        },
        "contexts": {
            "total": len(records),
            "left_empty": all_empty,
            "left_nonempty_controls": controls,
            "left_empty_subtypes": {
                "SPAN_ONLY_BLOCK": sum(row["left_block_detail"] == "SPAN_ONLY_BLOCK" for row in source_contexts),
                "COLLISION_ONLY_BLOCK": sum(row["left_block_detail"] == "COLLISION_ONLY_BLOCK" for row in source_contexts),
                "MIXED_BLOCK": sum(row["left_block_detail"] == "MIXED_BLOCK" for row in source_contexts),
            },
        },
        "occupied_h": {
            "distribution": [
                {"status": status, "h": h, "context_count": count}
                for (status, h), count in sorted(occupied_h_distribution.items(), key=lambda item: (int(item[0][1]), item[0][0]))
            ],
            "h_le_3_contexts": h_le_3,
            "mixed_contexts_total": sum(occupied_h_distribution.values()),
        },
        "shared_root_only_private_cases": {
            "count": len(shared_root_cases),
            "occupied_h_distribution": dict(Counter(row["occupied_h"] for row in shared_root_cases)),
        },
        "compression": compression_rows,
        "exact_footprint_interface": {
            "classes": len(exact_footprint_groups),
            "mixed_classes": len(exact_footprint_mixed),
            "mixed_contexts": sum(len(exact_footprint_contexts[key]) for key in exact_footprint_mixed),
            "exact_separating": len(exact_footprint_mixed) == 0,
        },
        "blocker_motif_counts": motif_counts,
        "blocker_kind_distribution_h1_h9": [
            {"h": h, "blocker_kind": kind, "context_count": count}
            for (h, kind), count in sorted(blocker_kind_distribution.items())
        ],
        "decision": decision,
        "decision_reason": decision_reason,
        "old_sigma66_data_used": False,
    }
    (OUT / "final_compression_certificate.json").write_text(
        json.dumps(certificate, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (OUT / "go_stop_decision.md").write_text(f"""# Tree3 final compression gate

Decision: {decision}

Reason: {decision_reason}

K5 is retained as the exact local interface:
(span-feasible left behavior signature, exact occupied left-facing footprint).
It is a correctness interface, not evidence that the geometry has become
low-dimensional. This decision concerns compression of the finite solver
behavior only; it is not a statement about gracefulness.
""", encoding="utf-8")

    write_csv(OUT / "tree1_tree3_locality_check.csv", [
        {
            "status": "NOT_PAIRED",
            "tree1_case": "fiveleaf3e-63-3-21-2-20-9-4-4",
            "tree3_case": CASE,
            "reason": "middle path lengths differ; no context-to-context pairing was forced",
            "exact_locality_statement": "K5 is exact within a fixed Tree3 context corpus; cross-tree locality was not claimed",
        }
    ])

    report = f"""# Tree3 final single-interval compression

Case {CASE}; corrected.v2; no new tree search.

## Exact census

- contexts: {len(records)}
- LEFT_EMPTY: {all_empty}
- LEFT_NONEMPTY controls: {controls}
- SPAN_ONLY_BLOCK: {certificate['contexts']['left_empty_subtypes']['SPAN_ONLY_BLOCK']}
- COLLISION_ONLY_BLOCK: {certificate['contexts']['left_empty_subtypes']['COLLISION_ONLY_BLOCK']}
- MIXED_BLOCK: {certificate['contexts']['left_empty_subtypes']['MIXED_BLOCK']}
- occupied-domain h<=3: {h_le_3}/{sum(occupied_h_distribution.values())} mixed contexts
- shared-root-only private cases: {len(shared_root_cases)}
- blocker-kind audit (h<=3): {sum(count for (h, _), count in blocker_kind_distribution.items() if h <= 3)} exact mixed-context rows

The occupied domain excludes only the left terminal pair's own legal root.
r2 and r3 remain occupied blockers for left private vertices. Offset 0 is
therefore a valid SHARED_ROOT_r2 blocker when a private left vertex tries to
use that label; it is not a private-middle vertex.

## Interface compression

The detailed K1-K5 table is in compression_quality_K1_K5.csv. K5 is exact
from the span-feasible left behavior set and F_L = O_L(M) intersect U_L.
K1-K4 are diagnostic coarse keys and are never hard pruning rules.

## Interpretation

The final compression gate is {decision}. The finite obstruction has a useful
local description, but a low-dimensional rule theorem is warranted only if
the reported coarse key or blocker motifs pass the pre-registered thresholds.
No general containment or graceful theorem is inferred.
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    (OUT / "formal_lemmas.md").write_text("""# Formal lemmas for the final Tree3 compression gate

## Occupied-offset hitting

Fix a middle context and let O_L(M) be the occupied middle-frame offsets that
a private left vertex may not use, excluding the left terminal pair's own
legal shared root. If H subset O_L(M) meets every span-feasible left private
offset set, then no compatible left completion exists.

## Left-facing footprint

Let U_L be the union of all raw Level-B left private offset sets after
translation to the middle frame. The left-facing footprint is
F_L(M) = O_L(M) intersect U_L. Occupied offsets outside U_L cannot collide
with a left behavior state.

## Exact local interface

For a fixed left behavior corpus, the pair consisting of the exact set of
span-feasible left behavior sets and the exact F_L(M) determines whether a
left state is collision-free: each state is compatible exactly when its
intersection with F_L(M) is empty. This is a finite locality statement, not
a claim that F_L itself has a low-dimensional parametrization.

## Shared-root blocker

A shared-root label is legal only for graph vertices that identify that root.
It remains an occupied blocker for a distinct private left vertex. The left
path's own root is excluded from O_L(M) because its endpoint sharing is legal.
""", encoding="utf-8")
    print(json.dumps({
        "case": CASE,
        "contexts": len(records),
        "left_empty": all_empty,
        "left_nonempty_controls": controls,
        "occupied_h_le_3": h_le_3,
        "occupied_mixed_total": sum(occupied_h_distribution.values()),
        "shared_root_only_private_cases": len(shared_root_cases),
        "K4": k4,
        "K5": k5,
        "blocker_motif_counts": motif_counts,
        "decision": decision,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
