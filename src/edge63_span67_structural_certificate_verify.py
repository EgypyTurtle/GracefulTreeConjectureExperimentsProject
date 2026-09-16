#!/usr/bin/env python3
"""Independently verify the corrected six-context Tree1 span certificate.

This verifier reads completed Gate-1 ledgers and the structural audit files,
then recomputes spans, regimes, containment deficits, complement pairing, and
the Tree2 control envelope.  It does not launch a search.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from edge63_displacement_first_compact import build_layout


TREE1 = "fiveleaf3e-63-3-21-2-20-9-4-4"
TREE2 = "fiveleaf3e-63-3-5-4-20-1-14-16"
EDGE_COUNT = 63


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def ints(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in value.split(";") if item)


def interval_span(values: tuple[int, ...]) -> int:
    return max(values) - min(values)


def adjacency_for_case(case: str) -> list[set[int]]:
    parts = case.split("-")
    values = tuple(int(item) for item in parts[2:])
    layout = build_layout(values)
    vertex_count = max(vertex for path in layout.values() for vertex in path) + 1
    adjacency = [set() for _ in range(vertex_count)]
    for path in layout.values():
        for left, right in zip(path, path[1:]):
            adjacency[left].add(right)
            adjacency[right].add(left)
    return adjacency


def tree_center(adjacency: list[set[int]]) -> int:
    alive = set(range(len(adjacency)))
    while len(alive) > 2:
        leaves = {v for v in alive if len(adjacency[v] & alive) <= 1}
        alive -= leaves
    if len(alive) != 1:
        raise AssertionError("expected a unique tree center")
    return next(iter(alive))


def rooted_signature(adjacency: list[set[int]], vertex: int, parent: int | None):
    children = [
        rooted_signature(adjacency, child, vertex)
        for child in adjacency[vertex]
        if child != parent
    ]
    return tuple(sorted(children, key=repr))


def rooted_automorphism_count(adjacency: list[set[int]], vertex: int, parent: int | None) -> int:
    child_signatures = [
        rooted_signature(adjacency, child, vertex)
        for child in adjacency[vertex]
        if child != parent
    ]
    counts = Counter(child_signatures)
    return math.prod(math.factorial(count) for count in counts.values()) * math.prod(
        rooted_automorphism_count(adjacency, child, vertex)
        for child in adjacency[vertex]
        if child != parent
    )


def containment_deficit(container: tuple[int, ...], other: tuple[int, ...]) -> int:
    return max(0, min(container) - min(other)) + max(0, max(other) - max(container))


def classify_regime(row: dict[str, str]) -> str:
    left = ints(row["left_private"])
    right = ints(row["right_private"])
    middle = ints(row["middle_values"])
    r1 = -int(row["delta_left"])
    r3 = int(row["delta_right"])
    left_dominant = containment_deficit(left, (*middle, *right)) == 0
    right_dominant = containment_deficit(right, (*middle, *left)) == 0
    middle_dominant = containment_deficit(middle, (*left, *right)) == 0
    if left_dominant:
        return "left-terminal-dominant"
    if right_dominant:
        return "right-terminal-dominant"
    if middle_dominant:
        return "middle-dominant"
    min_role = row["min_roles"]
    max_role = row["max_roles"]
    if r1 < r3:
        if min_role == "left_terminal_pair" and max_role == "right_terminal_pair":
            return "cross-root-outward"
        if min_role == "right_terminal_pair" and max_role == "left_terminal_pair":
            return "cross-root-inward"
    else:
        if min_role == "right_terminal_pair" and max_role == "left_terminal_pair":
            return "cross-root-outward"
        if min_role == "left_terminal_pair" and max_role == "right_terminal_pair":
            return "cross-root-inward"
    return "mixed"


def tree2_control(certificate_path: Path) -> dict[str, object]:
    fields = {}
    for line in certificate_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    labels = tuple(int(item) for item in fields["labels"].split(";"))
    values = tuple(int(item) for item in fields["case"].split("-")[2:])
    layout = build_layout(values)
    root2_label = labels[1]
    root_labels = (labels[0], labels[1], labels[2])

    left = tuple(sorted(
        labels[vertex] - root2_label
        for name in ("left_leaf_1", "left_leaf_2")
        for vertex in layout[name][1:]
    ))
    right = tuple(sorted(
        labels[vertex] - root2_label
        for name in ("right_leaf_1", "right_leaf_2")
        for vertex in layout[name][1:]
    ))
    middle_vertices = {0, 1, 2}
    for name in ("left_bridge", "right_bridge", "middle_leaf"):
        path = layout[name]
        middle_vertices.update(path[1:-1] if name != "middle_leaf" else path[1:])
    middle = tuple(sorted(labels[vertex] - root2_label for vertex in middle_vertices))
    all_values = (*left, *right, *middle)
    return {
        "labels_are_0_to_63": sorted(labels) == list(range(64)),
        "middle_frame_offsets_are_injective": len(all_values) == 64 and len(set(all_values)) == 64,
        "span": interval_span(all_values),
        "D13": abs(root_labels[2] - root_labels[0]),
        "left_min": min(left),
        "left_max": max(left),
        "right_min": min(right),
        "right_max": max(right),
        "middle_min": min(middle),
        "middle_max": max(middle),
        "right_contains_left_and_middle": containment_deficit(right, (*left, *middle)) == 0,
        "right_left_low_slack": min(left) - min(right),
        "right_left_high_slack": max(right) - max(left),
        "right_middle_low_slack": min(middle) - min(right),
        "right_middle_high_slack": max(right) - max(middle),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--structural-dir", type=Path,
        default=Path("results/edge63_span_feasibility_frontier/six_context_structural_v1"),
    )
    parser.add_argument(
        "--analysis-dir", type=Path,
        default=Path("results/edge63_span_feasibility_frontier/middle_conditioned_coupling_v1"),
    )
    parser.add_argument(
        "--gate-dir", type=Path,
        default=Path("results/edge63_span_feasibility_frontier/corrected_tree1_gate1"),
    )
    parser.add_argument(
        "--tree2-certificate", type=Path,
        default=Path("results/edge63_displacement_first_gate1/case2_exact_v5/verified_constructions/certificate.txt"),
    )
    args = parser.parse_args()

    structural = args.structural_dir
    certificate = json.loads((structural / "tree1_span67_structural_certificate.json").read_text(encoding="utf-8"))
    gate_summary = json.loads((args.gate_dir / "summary.json").read_text(encoding="utf-8"))
    source_contexts = read_csv(args.analysis_dir / "tree1_middle_conditioned_span.csv")
    source_frontiers = read_csv(args.analysis_dir / "tree1_joint_extension_frontiers.csv")
    six_contexts = read_csv(structural / "six_surviving_contexts.csv")
    orbit_rows = read_csv(structural / "context_automorphism_orbits.csv")
    scan_rows = read_csv(structural / "single_root_containment_scan.csv")
    deficit_rows = read_csv(structural / "containment_deficits.csv")
    penalty_rows = read_csv(structural / "conditioned_extension_penalties.csv")

    checks: dict[str, bool] = {}
    checks["case_is_tree1"] = certificate["case"] == TREE1 and all(row["case"] == TREE1 for row in source_frontiers)
    checks["corrected_cache_version"] = certificate["cache_version"] == "corrected.v2"
    checks["gate_status_and_orders"] = (
        gate_summary["cases"][0]["status"] == "UNSAT_EXHAUSTIVE"
        and int(gate_summary["cases"][0]["orders_covered"]) == 5040
    )
    checks["all_contexts_reconstructed"] = len(source_contexts) == 112410 and len({
        (int(row["middle_triple_id"]), int(row["middle_context_id"]))
        for row in source_contexts
    }) == 112410
    checks["exactly_six_surviving_contexts"] = sum(int(row["joint_pair_count"]) > 0 for row in source_contexts) == 6
    checks["exactly_thirty_six_final_rows"] = len(source_frontiers) == 36 and len(six_contexts) == 6

    recomputed_spans = []
    recomputed_regimes = []
    row_containment = {}
    injective = True
    for row in source_frontiers:
        middle = ints(row["middle_values"])
        left = ints(row["left_private"])
        right = ints(row["right_private"])
        all_offsets = (*middle, *left, *right)
        injective = injective and len(all_offsets) == 64 and len(set(all_offsets)) == 64
        span = interval_span(all_offsets)
        recomputed_spans.append(span)
        recomputed_regimes.append(classify_regime(row))
        row_containment[(int(row["order_index"]), int(row["middle_triple_id"]), int(row["middle_context_id"]))] = (
            containment_deficit(left, (*middle, *right)),
            containment_deficit(right, (*middle, *left)),
        )
    checks["all_frontier_offsets_injective"] = injective
    checks["frontier_spans_recompute"] = all(int(row["span"]) == span for row, span in zip(source_frontiers, recomputed_spans))
    checks["span_histogram_is_4_16_16"] = Counter(recomputed_spans) == Counter({67: 4, 68: 16, 69: 16})
    checks["minimum_span_is_67"] = min(recomputed_spans) == 67
    checks["no_old_66_result"] = min(recomputed_spans) >= 67 and certificate["span_result"]["minimum"] == 67
    checks["regime_labels_recompute"] = all(
        row["regime"].replace("_", "-") == regime
        for row, regime in zip(source_frontiers, recomputed_regimes)
    )
    checks["regime_counts_are_candidate_counts"] = Counter(row["regime"] for row in source_frontiers) == Counter({
        "cross_root_outward": 4,
        "cross_root_inward": 32,
    })
    checks["no_single_root_dominant_rows"] = not any(
        left == 0 or right == 0
        for left, right in row_containment.values()
    )

    context_keys = sorted({
        (int(row["middle_triple_id"]), int(row["middle_context_id"]))
        for row in source_frontiers
    })
    checks["structural_context_keys_match"] = sorted({
        (int(row["middle_triple_id"]), int(row["middle_context_id"]))
        for row in six_contexts
    }) == context_keys
    context_minima = {}
    for key in context_keys:
        rows = [row for row in source_frontiers if (int(row["middle_triple_id"]), int(row["middle_context_id"])) == key]
        context_minima[key] = min(int(row["span"]) for row in rows)
    source_minima = {
        (int(row["middle_triple_id"]), int(row["middle_context_id"])): int(row["sigma_min_joint"])
        for row in source_contexts if int(row["joint_pair_count"]) > 0
    }
    checks["context_minima_recompute"] = source_minima == context_minima
    checks["context_minimum_histogram"] = Counter(context_minima.values()) == Counter({67: 2, 68: 4})

    computed_deficits = defaultdict(list)
    for row in source_frontiers:
        key = (int(row["middle_triple_id"]), int(row["middle_context_id"]))
        metric = row_containment[(int(row["order_index"]), *key)]
        computed_deficits[key].append(metric)
    expected_deficits = {
        (int(row["middle_triple_id"]), int(row["middle_context_id"])): row
        for row in deficit_rows
    }
    checks["containment_deficits_recompute"] = all(
        int(expected_deficits[key]["minimum_left_containment_deficit"]) == min(pair[0] for pair in values)
        and int(expected_deficits[key]["minimum_right_containment_deficit"]) == min(pair[1] for pair in values)
        and all(pair[0] > 0 and pair[1] > 0 for pair in values)
        for key, values in computed_deficits.items()
    ) and len(expected_deficits) == 6
    recomputed_deficit_summary = {
        f"{key[0]}:{key[1]}": {
            "left": min(pair[0] for pair in values),
            "right": min(pair[1] for pair in values),
        }
        for key, values in computed_deficits.items()
    }
    checks["certificate_deficit_summary_matches"] = (
        certificate.get("containment_deficit_summary") == recomputed_deficit_summary
    )

    checks["six_context_regime_counts"] = Counter(row["regimes"] for row in six_contexts) == Counter({
        "cross_root_outward": 2,
        "cross_root_inward": 4,
    })
    checks["minimum_context_records_are_outward"] = all(
        row["regimes"] == "cross_root_outward" and int(row["span_min"]) == 67
        for row in six_contexts if int(row["span_min"]) == 67
    )
    checks["minimum_arithmetic_is_67"] = all(
        int(row["D13"]) == 16
        and int(row["delta_left"]) in {-42, 42}
        and int(row["delta_right"]) in {-26, 26}
        and (int(row["delta_left"]) + int(row["delta_right"]) in {-16, 16})
        for row in source_frontiers if int(row["span"]) == 67
    )

    checks["automorphism_group_order_is_two"] = (
        rooted_automorphism_count(adjacency_for_case(TREE1), tree_center(adjacency_for_case(TREE1)), None) == 2
    )
    checks["six_actual_context_orbits"] = len(orbit_rows) == 6 and len({row["actual_graph_automorphism_orbit"] for row in orbit_rows}) == 6
    checks["three_complement_pairs"] = len({row["legal_complement_orbit"] for row in orbit_rows}) == 3 and all(
        sum(row["legal_complement_orbit"] == orbit for row in orbit_rows) == 2
        for orbit in {row["legal_complement_orbit"] for row in orbit_rows}
    )
    context_signatures = {
        (int(row["middle_triple_id"]), int(row["middle_context_id"])): (
            int(row["delta_left"]), int(row["delta_right"]), tuple(sorted(int(x) for x in row["middle_values"].split(";") if x))
        )
        for row in six_contexts
    }
    complement_pairs_ok = True
    for key, signature in context_signatures.items():
        target = (-signature[0], -signature[1], tuple(-x for x in reversed(signature[2])))
        complement_pairs_ok = complement_pairs_ok and target in context_signatures.values()
    checks["complement_pairing_recomputes"] = complement_pairs_ok

    checks["conditioned_penalties_self_consistent"] = all(
        int(row["p_left_middle_conditioning"]) == int(row["e_left_conditioned_min"]) - int(row["e_left_unconditioned_min"])
        and int(row["p_right_middle_conditioning"]) == int(row["e_right_conditioned_min"]) - int(row["e_right_unconditioned_min"])
        and int(row["kappa_sigma"]) == int(row["sigma_joint"]) - int(row["sigma_ind"])
        and int(row["kappa_sigma"]) == 0
        for row in penalty_rows
    ) and len(penalty_rows) == 12
    expected_minimum_penalties = {
        (
            int(row["order_index"]),
            int(row["middle_triple_id"]),
            int(row["middle_context_id"]),
            int(row["p_left_middle_conditioning"]),
            int(row["p_right_middle_conditioning"]),
        )
        for row in penalty_rows if int(row["sigma_joint"]) == 67
    }
    certificate_minimum_penalties = {
        (
            int(row["order_index"]),
            int(row["middle_triple_id"]),
            int(row["middle_context_id"]),
            int(row["left_penalty"]),
            int(row["right_penalty"]),
        )
        for row in certificate["conditioned_penalty_result"]["minimum_span_assignment_penalties"]
    }
    checks["certificate_minimum_penalties_match"] = expected_minimum_penalties == certificate_minimum_penalties

    tree2 = tree2_control(args.tree2_certificate)
    checks["tree2_control_is_verified"] = all([
        tree2["labels_are_0_to_63"],
        tree2["middle_frame_offsets_are_injective"],
        tree2["span"] == 63,
        tree2["D13"] == 5,
        tree2["right_contains_left_and_middle"],
    ])
    checks["certificate_claims_match_recomputation"] = (
        certificate["surviving_contexts"]["count"] == 6
        and certificate["surviving_contexts"]["actual_graph_automorphism_group_order"] == 2
        and certificate["surviving_contexts"]["actual_graph_automorphism_orbits"] == 6
        and certificate["surviving_contexts"]["legal_complement_orbits"] == 3
        and certificate["regime_counts"]["cross_root_outward_candidates"] == 4
        and certificate["regime_counts"]["cross_root_inward_candidates"] == 32
        and certificate["regime_counts"]["single_root_dominant_candidates"] == 0
        and certificate["span_result"]["minimum"] == 67
        and certificate["span_result"]["minimum_candidate_count"] == 4
    )

    result = {
        "certificate": str(structural / "tree1_span67_structural_certificate.json"),
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "recomputed": {
            "frontier_span_histogram": dict(sorted(Counter(recomputed_spans).items())),
            "context_span_minima": {f"{key[0]}:{key[1]}": value for key, value in sorted(context_minima.items())},
            "tree2": tree2,
        },
        "scope": "Corrected finite Tree1 construction-language certificate; not a graceful nonexistence claim.",
    }
    output = structural / "tree1_span67_structural_certificate_verification.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["all_checks_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
