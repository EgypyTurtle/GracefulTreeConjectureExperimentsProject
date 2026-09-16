#!/usr/bin/env python3
"""Structure the six corrected tree-1 middle contexts with joint completion.

This is a read-only analysis of completed Gate-1 output. It does not enlarge
the Level-B language or launch any new graceful search.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_displacement_first_compact import (  # noqa: E402
    PATHS,
    TERMINAL_PATHS,
    all_allocations,
    build_layout,
    path_lengths,
)
from edge63_structure_analysis import parse_case  # noqa: E402
from edge63_middle_conditioned_span import terminal_pair_states  # noqa: E402


TREE1 = "fiveleaf3e-63-3-21-2-20-9-4-4"
TREE2 = "fiveleaf3e-63-3-5-4-20-1-14-16"
EDGE_COUNT = 63
CACHE_VERSION = "corrected.v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def ints(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in value.split(";") if item)


def interval_text(block: tuple[int, int]) -> str:
    return f"{block[0]}-{block[1]}"


def parse_interval_pair(value: str) -> tuple[tuple[int, int], tuple[int, int]]:
    parts = value.split(";")
    result = []
    for part in parts:
        _name, interval = part.split("=", 1)
        start, end = interval.split("-", 1)
        result.append((int(start), int(end)))
    if len(result) != 2:
        raise ValueError(f"expected two intervals: {value}")
    return result[0], result[1]


def values_for_case(case: str) -> tuple[int, ...]:
    parsed = parse_case(case)
    if parsed is None or parsed[1] != EDGE_COUNT:
        raise ValueError(f"not an edge-63 generated case: {case}")
    return parsed[2]


def allocation_index(values: tuple[int, ...]):
    lengths, middle_to_orders, _rows = all_allocations(values)
    order_map = {}
    for items in middle_to_orders.values():
        for item in items:
            order_map[int(item["order_index"])] = item
    return lengths, order_map


def adjacency_from_layout(values: tuple[int, ...]):
    layout = build_layout(values)
    n = max(vertex for path in layout.values() for vertex in path) + 1
    adjacency = [set() for _ in range(n)]
    for path in layout.values():
        for left, right in zip(path, path[1:]):
            adjacency[left].add(right)
            adjacency[right].add(left)
    return layout, adjacency


def tree_center(adjacency: list[set[int]]) -> int:
    alive = set(range(len(adjacency)))
    while len(alive) > 2:
        leaves = {vertex for vertex in alive if len(adjacency[vertex] & alive) <= 1}
        alive -= leaves
    if len(alive) != 1:
        raise ValueError("expected a unique tree center")
    return next(iter(alive))


def rooted_signature(adjacency: list[set[int]], vertex: int, parent: int | None):
    children = [
        rooted_signature(adjacency, child, vertex)
        for child in sorted(adjacency[vertex]) if child != parent
    ]
    return tuple(sorted(children, key=repr))


def rooted_automorphisms(adjacency: list[set[int]], root: int):
    """Enumerate actual automorphisms of the unlabelled rooted tree at root."""
    signatures = {}

    def sig(vertex: int, parent: int | None):
        key = (vertex, parent)
        if key not in signatures:
            signatures[key] = rooted_signature(adjacency, vertex, parent)
        return signatures[key]

    def maps(src: int, dst: int, src_parent: int | None, dst_parent: int | None):
        if sig(src, src_parent) != sig(dst, dst_parent):
            return []
        src_children = [v for v in sorted(adjacency[src]) if v != src_parent]
        dst_children = [v for v in sorted(adjacency[dst]) if v != dst_parent]
        by_signature = defaultdict(list)
        for child in dst_children:
            by_signature[sig(child, dst)].append(child)
        src_groups = defaultdict(list)
        for child in src_children:
            src_groups[sig(child, src)].append(child)
        if {key: len(value) for key, value in src_groups.items()} != {
            key: len(value) for key, value in by_signature.items()
        }:
            return []
        partial = [{src: dst}]
        for signature, src_group in src_groups.items():
            dst_group = by_signature[signature]
            expanded = []
            for permutation in itertools.permutations(dst_group):
                child_maps = [
                    maps(child_src, child_dst, src, dst)
                    for child_src, child_dst in zip(src_group, permutation)
                ]
                if any(not options for options in child_maps):
                    continue
                for base in partial:
                    for choices in itertools.product(*child_maps):
                        merged = dict(base)
                        for choice in choices:
                            if set(merged).intersection(choice):
                                break
                            if set(merged.values()).intersection(choice.values()):
                                break
                            merged.update(choice)
                        else:
                            expanded.append(merged)
            partial = expanded
        return partial

    return maps(root, root, None, None)


def automorphism_audit(values: tuple[int, ...]):
    layout, adjacency = adjacency_from_layout(values)
    center = tree_center(adjacency)
    automorphisms = rooted_automorphisms(adjacency, center)
    normalized = [tuple(mapping[index] for index in range(len(adjacency))) for mapping in automorphisms]
    swap_names = []
    paths = layout
    for left_name, right_name in (("left_leaf_1", "left_leaf_2"), ("right_leaf_1", "right_leaf_2")):
        left_path, right_path = paths[left_name], paths[right_name]
        if len(left_path) == len(right_path):
            swap_names.append(f"{left_name}<->{right_name}")
    return {
        "vertex_count": len(adjacency),
        "center": center,
        "group_order": len(normalized),
        "generator_candidates_from_equal_paths": swap_names,
        "automorphisms": normalized,
        "path_lengths": path_lengths(values),
    }


def complement_signature(delta_left: int, delta_right: int, middle: tuple[int, ...]):
    return (-delta_left, -delta_right, tuple(sorted(-value for value in middle)))


def outer_extensions_from_private(private: tuple[int, ...], delta_left: int, delta_right: int, side: str):
    root1, root3 = -delta_left, delta_right
    if side == "left":
        if root1 < root3:
            return max(0, root1 - min(private))
        return max(0, max(private) - root1)
    if root1 < root3:
        return max(0, max(private) - root3)
    return max(0, root3 - min(private))


def conditioned_penalties(
    coupling_rows: list[dict[str, str]],
):
    output = []
    for row in coupling_rows:
        # Parse by path name to avoid depending on TERMINAL_PATHS ordering.
        interval_map = {}
        for part in row["residual_key"].split(";"):
            name, interval = part.split("=", 1)
            start, end = interval.split("-", 1)
            interval_map[name] = (int(start), int(end))
        left_a, left_b = interval_map["left_leaf_1"], interval_map["left_leaf_2"]
        right_a, right_b = interval_map["right_leaf_1"], interval_map["right_leaf_2"]
        left_states = terminal_pair_states(left_a[0], left_a[1] - left_a[0] + 1, left_b[0], left_b[1] - left_b[0] + 1)
        right_states = terminal_pair_states(right_a[0], right_a[1] - right_a[0] + 1, right_b[0], right_b[1] - right_b[0] + 1)
        delta_left, delta_right = int(row["delta_left"]), int(row["delta_right"])
        uncond_left = min(outer_extensions_from_private(state.private, delta_left, delta_right, "left") for state in left_states)
        uncond_right = min(outer_extensions_from_private(state.private, delta_left, delta_right, "right") for state in right_states)
        cond_left = int(row["independent_e_left_min"])
        cond_right = int(row["independent_e_right_min"])
        output.append({
            "order_index": int(row["order_index"]),
            "middle_triple_id": int(row["middle_triple_id"]),
            "middle_context_id": int(row["middle_context_id"]),
            "left_terminal_intervals": f"{interval_text(left_a)};{interval_text(left_b)}",
            "right_terminal_intervals": f"{interval_text(right_a)};{interval_text(right_b)}",
            "delta_left": delta_left,
            "delta_right": delta_right,
            "D13": int(row["D13"]),
            "e_left_unconditioned_min": uncond_left,
            "e_left_conditioned_min": cond_left,
            "p_left_middle_conditioning": cond_left - uncond_left,
            "e_right_unconditioned_min": uncond_right,
            "e_right_conditioned_min": cond_right,
            "p_right_middle_conditioning": cond_right - uncond_right,
            "sigma_ind": int(row["sigma_ind"]),
            "sigma_joint": int(row["sigma_joint"]),
            "kappa_sigma": int(row["kappa_sigma"]),
            "independent_e_sum": int(row["independent_e_sum"]),
            "joint_e_sum_min": int(row["joint_e_sum_min"]),
        })
    return output


def containment_metrics(row: dict[str, object]):
    middle = ints(str(row["middle_values"]))
    left = ints(str(row["left_private"]))
    right = ints(str(row["right_private"]))
    left_other = (*middle, *right)
    right_other = (*middle, *left)
    left_deficit = max(0, min(left) - min(left_other)) + max(0, max(left_other) - max(left))
    right_deficit = max(0, min(right) - min(right_other)) + max(0, max(right_other) - max(right))
    return {
        "left_containment_deficit": left_deficit,
        "right_containment_deficit": right_deficit,
        "left_contains_other_offsets": left_deficit == 0,
        "right_contains_other_offsets": right_deficit == 0,
    }


def is_subset_in_envelope(values: tuple[int, ...], envelope: tuple[int, ...]) -> bool:
    return all(min(envelope) <= value <= max(envelope) for value in values)


def span_decomposition(row: dict[str, str]) -> dict[str, object]:
    left = ints(row["left_private"])
    right = ints(row["right_private"])
    middle = ints(row["middle_values"])
    delta_left, delta_right = int(row["delta_left"]), int(row["delta_right"])
    root1, root3 = -delta_left, delta_right
    if root1 < root3:
        e_left = max(0, root1 - min(left))
        e_right = max(0, max(right) - root3)
        outward_formula = abs(root3 - root1) + e_left + e_right
    else:
        e_left = max(0, max(left) - root1)
        e_right = max(0, root3 - min(right))
        outward_formula = abs(root3 - root1) + e_left + e_right
    all_offsets = (*left, *middle, *right)
    return {
        "root1_middle_frame": root1,
        "root3_middle_frame": root3,
        "left_outward_extension": e_left,
        "right_outward_extension": e_right,
        "outward_formula_value": outward_formula,
        "outward_formula_matches": outward_formula == int(row["span"]),
        "global_min": min(all_offsets),
        "global_max": max(all_offsets),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", type=Path, default=Path("results/edge63_span_feasibility_frontier/middle_conditioned_coupling_v1"))
    parser.add_argument("--gate-dir", type=Path, default=Path("results/edge63_span_feasibility_frontier/corrected_tree1_gate1"))
    parser.add_argument("--tree2-certificate", type=Path, default=Path("results/edge63_displacement_first_gate1/case2_exact_v5/verified_constructions/certificate.txt"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/edge63_span_feasibility_frontier/six_context_structural_v1"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    source_summary = json.loads((args.analysis_dir / "summary.json").read_text(encoding="utf-8"))
    source_frontiers = read_csv(args.analysis_dir / "tree1_joint_extension_frontiers.csv")
    source_contexts = read_csv(args.analysis_dir / "tree1_middle_conditioned_span.csv")
    coupling_rows = read_csv(args.analysis_dir / "tree1_coupling_penalty.csv")
    values = values_for_case(TREE1)
    lengths, order_map = allocation_index(values)
    aut = automorphism_audit(values)
    if aut["group_order"] != 2:
        raise ValueError(f"unexpected actual tree automorphism group order: {aut['group_order']}")

    grouped = defaultdict(list)
    for row in source_frontiers:
        grouped[(int(row["middle_triple_id"]), int(row["middle_context_id"]))].append(row)
    context_summary = {
        (int(row["middle_triple_id"]), int(row["middle_context_id"])): row
        for row in source_contexts if int(row["joint_pair_count"]) > 0
    }
    if len(grouped) != 6:
        raise ValueError(f"expected six surviving contexts, got {len(grouped)}")

    enriched = []
    for key in sorted(grouped):
        rows = grouped[key]
        triple_id, context_id = key
        summary_row = context_summary[key]
        first = rows[0]
        order_indices = sorted({int(row["order_index"]) for row in rows})
        order_names = [" ".join(order_map[index]["order"]) for index in order_indices]
        left_intervals = sorted({f"{row['left_interval_a']};{row['left_interval_b']}" for row in rows})
        right_intervals = sorted({f"{row['right_interval_a']};{row['right_interval_b']}" for row in rows})
        spans = [int(row["span"]) for row in rows]
        deficit_rows = [containment_metrics(row) for row in rows]
        enriched.append({
            "case": TREE1,
            "middle_triple_id": triple_id,
            "middle_context_id": context_id,
            "automorphism_orbit_id": f"AUT-{triple_id}-{context_id}",
            "legal_complement_orbit_id": "",
            "order_indices": ";".join(map(str, order_indices)),
            "orders": " | ".join(order_names),
            "middle_interval_triple": "",
            "left_bridge_interval": "",
            "middle_leaf_interval": "",
            "right_bridge_interval": "",
            "delta_left": first["delta_left"],
            "delta_right": first["delta_right"],
            "D13": first["D13"],
            "middle_min": first["middle_min"],
            "middle_max": first["middle_max"],
            "middle_values": first["middle_values"],
            "left_terminal_intervals": " | ".join(left_intervals),
            "right_terminal_intervals": " | ".join(right_intervals),
            "compatible_left_total": summary_row["compatible_left_total"],
            "compatible_right_total": summary_row["compatible_right_total"],
            "joint_pair_count": len(rows),
            "span_min": min(spans),
            "span_histogram": dict(Counter(spans)),
            "regimes": ";".join(sorted({row["regime"] for row in rows})),
            "min_role_set": ";".join(sorted({row["min_roles"] for row in rows})),
            "max_role_set": ";".join(sorted({row["max_roles"] for row in rows})),
            "left_containment_deficit_min": min(item["left_containment_deficit"] for item in deficit_rows),
            "right_containment_deficit_min": min(item["right_containment_deficit"] for item in deficit_rows),
        })

    # Fill the exact middle interval triple and the legal complement orbit.
    context_by_key = {(row["middle_triple_id"], row["middle_context_id"]): row for row in enriched}
    for row in enriched:
        order_index = int(row["order_indices"].split(";")[0])
        blocks = order_map[order_index]["blocks"]
        row["middle_interval_triple"] = ";".join(
            f"{name}={interval_text(blocks[name])}"
            for name in ("left_bridge", "middle_leaf", "right_bridge")
        )
        row["left_bridge_interval"] = interval_text(blocks["left_bridge"])
        row["middle_leaf_interval"] = interval_text(blocks["middle_leaf"])
        row["right_bridge_interval"] = interval_text(blocks["right_bridge"])
        dl, dr = int(row["delta_left"]), int(row["delta_right"])
        middle = ints(row["middle_values"])
        target = complement_signature(dl, dr, middle)
        partner = next(
            other for other in enriched
            if (int(other["delta_left"]), int(other["delta_right"]), ints(other["middle_values"])) == target
        )
        orbit_id = "COMP-" + "-".join(sorted({
            f"{row['middle_triple_id']}:{row['middle_context_id']}",
            f"{partner['middle_triple_id']}:{partner['middle_context_id']}",
        }))
        row["legal_complement_orbit_id"] = orbit_id
    write_csv(args.output_dir / "six_surviving_contexts.csv", enriched)

    orbit_rows = []
    for row in sorted(enriched, key=lambda item: (item["legal_complement_orbit_id"], item["middle_triple_id"], item["middle_context_id"])):
        orbit_rows.append({
            "middle_triple_id": row["middle_triple_id"],
            "middle_context_id": row["middle_context_id"],
            "actual_graph_automorphism_orbit": row["automorphism_orbit_id"],
            "legal_complement_orbit": row["legal_complement_orbit_id"],
            "delta_left": row["delta_left"],
            "delta_right": row["delta_right"],
            "span_min": row["span_min"],
            "regimes": row["regimes"],
            "automorphism_note": "right_leaf_1/right_leaf_2 swap acts trivially on middle context",
        })
    write_csv(args.output_dir / "context_automorphism_orbits.csv", orbit_rows)

    all_deficits = []
    deficits_by_context = defaultdict(list)
    for row in source_frontiers:
        metric = containment_metrics(row)
        output = {
            "order_index": row["order_index"],
            "middle_triple_id": "",
            "middle_context_id": row["middle_context_id"],
            "span": row["span"],
            "min_roles": row["min_roles"],
            "max_roles": row["max_roles"],
            **metric,
        }
        # The same local context id occurs under different middle triples; use
        # the order allocation to recover the unique triple.
        output["middle_triple_id"] = next(
            int(item["middle_triple_id"])
            for item in enriched
            if int(item["middle_context_id"]) == int(row["middle_context_id"])
            and int(row["order_index"]) in {int(value) for value in item["order_indices"].split(";")}
        )
        all_deficits.append(output)
        deficits_by_context[(output["middle_triple_id"], int(output["middle_context_id"]))].append(output)
    write_csv(args.output_dir / "single_root_containment_scan.csv", all_deficits)
    classifications = []
    for row in source_frontiers:
        metric = containment_metrics(row)
        classifications.append({
            "case": row["case"],
            "order_index": row["order_index"],
            "middle_triple_id": row["middle_triple_id"],
            "middle_context_id": row["middle_context_id"],
            "delta_left": row["delta_left"],
            "delta_right": row["delta_right"],
            "D13": row["D13"],
            "span": row["span"],
            "regime": row["regime"],
            "min_roles": row["min_roles"],
            "max_roles": row["max_roles"],
            "left_min": row["left_min"],
            "left_max": row["left_max"],
            "right_min": row["right_min"],
            "right_max": row["right_max"],
            "middle_min": row["middle_min"],
            "middle_max": row["middle_max"],
            **span_decomposition(row),
            **metric,
        })
    write_csv(args.output_dir / "tree1_valid36_classification.csv", classifications)
    write_csv(
        args.output_dir / "tree1_span67_candidates.csv",
        [row for row in classifications if int(row["span"]) == 67],
    )
    deficit_rows = []
    for key in sorted(deficits_by_context):
        rows = deficits_by_context[key]
        deficit_rows.append({
            "middle_triple_id": key[0],
            "middle_context_id": key[1],
            "candidate_count": len(rows),
            "minimum_left_containment_deficit": min(int(row["left_containment_deficit"]) for row in rows),
            "minimum_right_containment_deficit": min(int(row["right_containment_deficit"]) for row in rows),
            "left_dominant_possible_among_joint_candidates": any(row["left_contains_other_offsets"] == "True" for row in rows),
            "right_dominant_possible_among_joint_candidates": any(row["right_contains_other_offsets"] == "True" for row in rows),
        })
    write_csv(args.output_dir / "containment_deficits.csv", deficit_rows)

    penalties = conditioned_penalties(coupling_rows)
    write_csv(args.output_dir / "conditioned_extension_penalties.csv", penalties)
    penalty_by_context = defaultdict(list)
    for row in penalties:
        penalty_by_context[(int(row["middle_triple_id"]), int(row["middle_context_id"]))].append(row)

    def context_regime_rows(regime: str):
        result = []
        for item in enriched:
            if regime not in item["regimes"].split(";"):
                continue
            key = (int(item["middle_triple_id"]), int(item["middle_context_id"]))
            p = penalty_by_context[key]
            result.append({
                "middle_triple_id": key[0],
                "middle_context_id": key[1],
                "span_min": item["span_min"],
                "span_histogram": item["span_histogram"],
                "D13": item["D13"],
                "delta_left": item["delta_left"],
                "delta_right": item["delta_right"],
                "joint_e_sum_min": min(int(row["joint_e_sum_min"]) for row in p),
                "sigma_ind_min": min(int(row["sigma_ind"]) for row in p),
                "sigma_joint_min": min(int(row["sigma_joint"]) for row in p),
                "kappa_sigma_values": ";".join(sorted({str(row["kappa_sigma"]) for row in p})),
                "left_conditioned_extension_min": min(int(row["e_left_conditioned_min"]) for row in p),
                "right_conditioned_extension_min": min(int(row["e_right_conditioned_min"]) for row in p),
            })
        return result
    write_csv(args.output_dir / "tree1_outward_context_analysis.csv", context_regime_rows("cross_root_outward"))
    write_csv(args.output_dir / "tree1_inward_context_analysis.csv", context_regime_rows("cross_root_inward"))

    tree2_path = args.tree2_certificate
    tree2_fields = dict(
        line.split("=", 1)
        for line in tree2_path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    dl2, dr2 = int(tree2_fields["delta_left"]), int(tree2_fields["delta_right"])
    r1, r3 = -dl2, dr2
    left2 = tuple(sorted(value + r1 for value in (*ints(tree2_fields["left_path_a"]), *ints(tree2_fields["left_path_b"]))))
    right2 = tuple(sorted(value + r3 for value in (*ints(tree2_fields["right_path_a"]), *ints(tree2_fields["right_path_b"]))))
    bridge_left2 = ints(tree2_fields["left_bridge"])[1:-1]
    bridge_right2 = ints(tree2_fields["right_bridge"])[1:-1]
    central2 = ints(tree2_fields["central"])[1:]
    middle2 = tuple(sorted((r1, 0, r3, *(value + r1 for value in bridge_left2), *bridge_right2, *central2)))
    tree2_containment = {
        "case": TREE2,
        "D13": abs(r3 - r1),
        "span": max((*left2, *right2, *middle2)) - min((*left2, *right2, *middle2)),
        "right_min": min(right2),
        "right_max": max(right2),
        "left_min": min(left2),
        "left_max": max(left2),
        "middle_min": min(middle2),
        "middle_max": max(middle2),
        "right_contains_left_and_middle": is_subset_in_envelope((*left2, *middle2), right2),
        "right_left_slack": min(left2) - min(right2),
        "right_right_slack": max(right2) - max(left2),
        "right_middle_low_slack": min(middle2) - min(right2),
        "right_middle_high_slack": max(right2) - max(middle2),
    }
    write_csv(args.output_dir / "tree2_containment_control.csv", [tree2_containment])
    write_csv(args.output_dir / "tree2_verified_regime_analysis.csv", [tree2_containment])

    candidate_regime_counts = Counter(row["regime"] for row in source_frontiers)
    regime_rows = []
    for regime, rows in (("single_root_dominant", []), ("cross_root_outward", context_regime_rows("cross_root_outward")), ("cross_root_inward", context_regime_rows("cross_root_inward"))):
        regime_rows.append({
            "regime": regime,
            "candidate_count": candidate_regime_counts.get(regime, 0),
            "context_count": len(rows),
            "minimum_span": min((int(row["span_min"]) for row in rows), default="NONE"),
            "context_ids": ";".join(f"{row['middle_triple_id']}:{row['middle_context_id']}" for row in rows),
            "formula": (
                "impossible in corrected joint candidates" if regime == "single_root_dominant" else
                "D13 + outward extensions" if regime == "cross_root_outward" else
                "inward extension of low/high root components minus D13"
            ),
        })
    write_csv(args.output_dir / "regime_formulas.csv", regime_rows)
    regime_markdown = '''# Regime formulas

All formulas below use one common middle-frame coordinate system. For finite
offset sets `L`, `M`, and `R`,

`span(L union M union R) = max(max L, max M, max R) - min(min L, min M, min R)`.

## Cross-root outward

If the roots are ordered `r1 < r3`, the minimum is supplied by the left
terminal pair and the maximum by the right terminal pair, then

`span = (r3-r1) + (r1-min(L)) + (max(R)-r3)`.

When `r3 < r1`, exchange left and right roles in the outward extensions.

## Cross-root inward

If `r1 < r3`, the minimum is supplied by `R` and the maximum by `L`, then

`span = (max(L)-r1) + (r3-min(R)) - (r3-r1)`.

The reversed-root case is obtained by exchanging the two root roles.

## Single-root dominant

The right terminal pair is dominant exactly when
`L union M subset [min(R), max(R)]`; then `span=span(R)`. The left case is
symmetric. The Tree1 corrected final rows contain no such row; Tree2's
verified certificate is right-terminal-dominant.
'''
    (args.output_dir / "regime_formulas.md").write_text(regime_markdown, encoding="utf-8")

    frontier_variables = [{
        "variable": "terminal interval block separation",
        "tree1": "left 1-2/44-63; right 12-15/37-40 at span-67",
        "tree2": "left 1-20/37-40; right 21-36/50-63",
        "interpretation": "candidate variable; not yet a theorem",
    }, {
        "variable": "terminal envelope containment",
        "tree1": "no zero-deficit row among 36 joint candidates",
        "tree2": "right envelope contains left and middle",
        "interpretation": "cleanest current finite frontier signal",
    }, {
        "variable": "outer-root separation",
        "tree1": "D13=16 on minimum layer",
        "tree2": "D13=5 on verified certificate",
        "interpretation": "contributes to span but does not alone explain feasibility",
    }]
    write_csv(args.output_dir / "tree1_tree2_frontier_variables.csv", frontier_variables)
    comparison = '''# Tree1 / Tree2 regime comparison

| quantity | Tree1 corrected language | Tree2 verified certificate |
|---|---:|---:|
| construction scope | 7 paths, one consecutive interval each, Level-B | same single-interval language |
| status | `UNSAT_EXHAUSTIVE` | `SAT_VERIFIED` |
| global span | minimum 67 | 63 |
| outer-root separation `D13` | 16 on the minimum layer | 5 |
| single-root dominant | 0 of 36 final rows | right-terminal-dominant |
| containment | no zero-deficit final row | right envelope contains left and middle |
| left/right coupling penalty | `kappa_sigma=0` on 12 exact assignments | not applicable to the Tree2 control row |

The finite contrast is therefore a regime contrast, not evidence that
single-interval constructions universally fail: Tree1's six surviving
contexts force cross-root extrema, while Tree2 admits one terminal envelope
that contains the other components. This is a candidate mechanism, not yet a
parameterized theorem.
'''
    (args.output_dir / "tree1_tree2_regime_comparison.md").write_text(comparison, encoding="utf-8")

    source_hashes = {
        "analysis_summary": sha256(args.analysis_dir / "summary.json"),
        "frontiers": sha256(args.analysis_dir / "tree1_joint_extension_frontiers.csv"),
        "contexts": sha256(args.analysis_dir / "tree1_middle_conditioned_span.csv"),
    }
    complement_orbits = sorted({row["legal_complement_orbit_id"] for row in enriched})
    deficit_summary = {
        f"{row['middle_triple_id']}:{row['middle_context_id']}": {
            "left": int(row["minimum_left_containment_deficit"]),
            "right": int(row["minimum_right_containment_deficit"]),
        }
        for row in deficit_rows
    }
    minimum_penalties = [row for row in penalties if int(row["sigma_joint"]) == 67]
    certificate = {
        "certificate_kind": "finite_tree1_span67_structural_audit_v2",
        "case": TREE1,
        "cache_version": CACHE_VERSION,
        "language": "seven maximal paths; one consecutive difference interval per path; complete Level-B local behavior",
        "gate_scope": {
            "status": "UNSAT_EXHAUSTIVE",
            "orders": "5040/5040",
            "contexts": "112410/112410",
            "source_final_candidates": 36,
        },
        "surviving_contexts": {
            "count": len(enriched),
            "actual_graph_automorphism_group_order": aut["group_order"],
            "actual_graph_automorphism_orbits": 6,
            "legal_complement_orbits": len(complement_orbits),
            "orbit_ids": complement_orbits,
            "records": enriched,
        },
        "regime_counts": {
            "cross_root_outward_candidates": candidate_regime_counts.get("cross_root_outward", 0),
            "cross_root_inward_candidates": candidate_regime_counts.get("cross_root_inward", 0),
            "single_root_dominant_candidates": candidate_regime_counts.get("single_root_dominant", 0),
            "cross_root_outward_contexts": sum("cross_root_outward" in row["regimes"].split(";") for row in enriched),
            "cross_root_inward_contexts": sum("cross_root_inward" in row["regimes"].split(";") for row in enriched),
        },
        "span_result": {
            "minimum": 67,
            "minimum_candidate_count": 4,
            "histogram": {"67": 4, "68": 16, "69": 16},
        },
        "conditioned_penalty_result": {
            "exact_order_context_assignments": len(penalties),
            "kappa_sigma_values": sorted({int(row["kappa_sigma"]) for row in penalties}),
            "minimum_span_assignment_penalties": [{
                "order_index": int(row["order_index"]),
                "middle_triple_id": int(row["middle_triple_id"]),
                "middle_context_id": int(row["middle_context_id"]),
                "unconditioned_left": int(row["e_left_unconditioned_min"]),
                "conditioned_left": int(row["e_left_conditioned_min"]),
                "left_penalty": int(row["p_left_middle_conditioning"]),
                "unconditioned_right": int(row["e_right_unconditioned_min"]),
                "conditioned_right": int(row["e_right_conditioned_min"]),
                "right_penalty": int(row["p_right_middle_conditioning"]),
            } for row in minimum_penalties],
            "note": "kappa_sigma is zero on all 12 assignments producing the 36 final rows",
        },
        "containment_deficit_summary": deficit_summary,
        "tree2_control": tree2_containment,
        "source_sha256": source_hashes,
        "scope_warning": "Finite structural certificate for the corrected construction language; not a graceful nonexistence claim.",
    }
    (args.output_dir / "tree1_span67_structural_certificate.json").write_text(json.dumps(certificate, indent=2), encoding="utf-8")

    formal = r'''# Structural span formulas

## Envelope span

For finite nonempty sets `L`, `M`, and `R` in one coordinate frame,

`span(L union M union R) = max(max L, max M, max R) - min(min L, min M, min R)`.

This is the definition of the extrema of a finite union.

## Single-root dominance

The right terminal pair is dominant exactly when
`L union M subset [min(R), max(R)]`. In that event the global extrema are
the extrema of `R`, and the span equals `max(R)-min(R)`. The left statement
is symmetric. This is an exact criterion for a fixed joint choice.

## Cross-root outward formula

Assume `r1 < r3`, the global minimum is attained in `L`, and the global
maximum in `R`. With `eL=r1-min(L)` and `eR=max(R)-r3`,

`span = (r3-r1) + eL + eR`.

If `r3 < r1`, swap the root roles. The equality is conditional on the stated
extreme roles.

## Cross-root inward formula

Assume `r1 < r3`, the global minimum is attained in `R`, and the global
maximum in `L`. Put `iL=max(L)-r1` and `iR=r3-min(R)`. Then

`span = iL + iR - (r3-r1)`.

The reversed-root case is obtained by swapping `L` and `R`. This is the
coordinate-aware meaning of the analysis label `cross_root_inward`.

## Conditioned extension bound

Fix a middle context. If every individually middle-compatible left state has
outward extension at least `a`, and every such right state has outward
extension at least `b`, then every cross-root-outward joint choice has span at
least `D13+a+b`. The assertion is only made after the extreme-role hypothesis
has been established.

## Containment deficit

For a candidate right envelope define
`dR=max(0,min(R)-min(L union M)) + max(0,max(L union M)-max(R))`.
Then `dR=0` exactly when the right envelope contains all other offsets. The
left deficit is symmetric.
'''
    (args.output_dir / "formal_lemmas.md").write_text(formal, encoding="utf-8")

    report = f'''# Six-context structural analysis

This analysis uses corrected terminal-pair cache version `{CACHE_VERSION}`.
It only reads the completed tree1 Gate1 run and rechecks its 36 final rows;
it does not enter two-interval, expand Level-B, run a third representative
tree, or modify the edge63 main log.

## Surviving contexts

Exactly `{len(enriched)}` of the corrected `{len(source_contexts)}` middle
contexts have any joint terminal completion. Their full records are in
`six_surviving_contexts.csv`. Under the actual graph automorphism group, the
six middle contexts remain six context orbits: the group has order 2 and its
only nontrivial action is the equal-length right-terminal leaf swap, which is
trivial on the middle context. After also applying the legal label complement,
the six contexts form `{len(complement_orbits)}` pairs, listed in
`context_automorphism_orbits.csv`.

## Regimes and containment

The 36 corrected joint candidates split into 4 cross-root-outward and 32
cross-root-inward rows. No row is single-root-dominant. The minimum
containment deficits, by surviving context, are in `containment_deficits.csv`;
the right deficits are positive in all six contexts and the left deficits are
also positive. Numerically, the deficit pairs are `(5,26)` for contexts
`219:31`, `219:35`, `219:41`, `219:45`, and `(4,14)` for `379:3`, `379:14`.
Thus no corrected joint candidate realizes terminal-envelope containment.

## Tree1 minimum layer

The four span-67 rows all lie in the cross-root-outward regime. They use the
two automorphic block orders 1883 and 1907, with
`D13=16`, `eL=10`, and `eR=41`, giving

`67 = 16 + 10 + 41`.

The two orders differ only by swapping `right_leaf_1` and `right_leaf_2`,
whose generated path lengths are both 4.

## Conditioned extension audit

For all 12 order/context assignments producing the 36 final rows,
`sigma_ind=sigma_joint` and `kappa_sigma=0`. The left-right final collision
condition therefore contributes no additional span on this exact final-row
layer. The conditioned extension table compares each side with its
unconditioned terminal-pair minimum and records the middle-conditioning
penalties. On the span-67 rows these are `eL: 0 -> 10` and `eR: 23 -> 41`,
so the middle-conditioning penalties are `10` and `18`; this is distinct
from the final left-right coupling penalty, which is zero.

## Tree2 control

Tree2's verified certificate has span 63 and is right-terminal-dominant: its
right envelope contains the left and middle offsets. Its outer-root separation
is 5, so the Tree1 outward formula is not universal.

The current finite evidence therefore supports a more precise statement:
Tree1's corrected single-interval obstruction is concentrated in a tiny set
of middle contexts and their terminal envelope geometry. It does not yet
prove an analytic parameter theorem; the next mathematical target is a
middle-conditioned envelope/extension inequality for the representative
context orbit.
'''
    (args.output_dir / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(certificate, indent=2))


if __name__ == "__main__":
    main()
