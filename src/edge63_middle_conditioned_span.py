#!/usr/bin/env python3
"""Analyze corrected tree-1 Gate-1 output by middle-conditioned spans.

The script is read-only with respect to the search. It consumes the completed
corrected ledger and re-enumerates only the terminal-pair states needed to
audit the 36 non-span final candidates.
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
    compact_options,
    middle_contexts,
    path_lengths,
)
from edge63_structure_analysis import parse_case  # noqa: E402


TREE1 = "fiveleaf3e-63-3-21-2-20-9-4-4"
TREE2 = "fiveleaf3e-63-3-5-4-20-1-14-16"
EDGE_COUNT = 63
CACHE_VERSION = "corrected.v2"


class PairState:
    __slots__ = ("state_id", "private", "path_a", "path_b", "min_value", "max_value")

    def __init__(self, state_id, private, path_a, path_b):
        self.state_id = state_id
        self.private = tuple(private)
        self.path_a = tuple(path_a)
        self.path_b = tuple(path_b)
        self.min_value = min((0, *self.private))
        self.max_value = max((0, *self.private))


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


def values_for_case(case: str) -> tuple[int, ...]:
    parsed = parse_case(case)
    if parsed is None or parsed[1] != EDGE_COUNT:
        raise ValueError(f"not an edge-63 generated case: {case}")
    return parsed[2]


def interval_text(block: tuple[int, int]) -> str:
    return f"{block[0]}-{block[1]}"


def residual_key_text(blocks: dict[str, tuple[int, int]]) -> str:
    return ";".join(
        f"{path}={interval_text(blocks[path])}" for path in TERMINAL_PATHS
    )


def middle_key_text(blocks: dict[str, tuple[int, int]]) -> str:
    return ";".join(
        f"{path}={interval_text(blocks[path])}"
        for path in ("left_bridge", "middle_leaf", "right_bridge")
    )


def build_allocation_index(values: tuple[int, ...]):
    lengths, middle_to_orders, triple_rows = all_allocations(values)
    order_map: dict[int, dict[str, object]] = {}
    order_to_triple: dict[int, int] = {}
    triple_to_orders: dict[int, list[dict[str, object]]] = {}
    triple_to_middle_key: dict[int, tuple] = {}
    for triple_id, (middle_key, items) in enumerate(middle_to_orders.items()):
        triple_to_orders[triple_id] = items
        triple_to_middle_key[triple_id] = middle_key
        for item in items:
            order_index = int(item["order_index"])
            order_map[order_index] = item
            order_to_triple[order_index] = triple_id
    return (
        lengths,
        triple_rows,
        order_map,
        order_to_triple,
        triple_to_orders,
        triple_to_middle_key,
    )


def build_middle_index(values: tuple[int, ...], triple_to_middle_key: dict[int, tuple]):
    contexts_by_triple: dict[int, dict[int, dict[str, object]]] = {}
    context_count = 0
    for triple_id, middle_key in triple_to_middle_key.items():
        left = middle_key[0]
        central = middle_key[1]
        right = middle_key[2]
        contexts, _stats = middle_contexts(
            left[1], left[2] - left[1] + 1,
            central[1], central[2] - central[1] + 1,
            right[1], right[2] - right[1] + 1,
            "B",
        )
        contexts_by_triple[triple_id] = {
            int(context["context_id"]): context for context in contexts
        }
        context_count += len(contexts)
    return contexts_by_triple, context_count


PAIR_CACHE: dict[tuple[int, int, int, int], tuple[PairState, ...]] = {}


def terminal_pair_states(
    start_a: int, length_a: int, start_b: int, length_b: int
) -> tuple[PairState, ...]:
    """Reconstruct corrected terminal-pair states with the regression guard."""
    key = (start_a, length_a, start_b, length_b)
    if key in PAIR_CACHE:
        return PAIR_CACHE[key]
    options_a = compact_options("terminal", start_a, length_a, "B")
    options_b = compact_options("terminal", start_b, length_b, "B")
    representatives: dict[tuple[int, ...], PairState] = {}
    for option_a, option_b in itertools.product(options_a, options_b):
        private_a = tuple(option_a.offsets[1:])
        private_b = tuple(option_b.offsets[1:])
        private = tuple(sorted((*private_a, *private_b)))
        if 0 in private or len(set(private)) != len(private):
            continue
        if max((0, *private)) - min((0, *private)) > EDGE_COUNT:
            continue
        representatives.setdefault(
            private,
            PairState(len(representatives), private, private_a, private_b),
        )
    states = tuple(representatives.values())
    PAIR_CACHE[key] = states
    return states


def shifted_state(state: PairState, shift: int) -> tuple[int, ...]:
    return tuple(value + shift for value in state.private)


def span_from_ranges(ranges: list[tuple[int, int]]) -> int:
    return max(high for _low, high in ranges) - min(low for low, _high in ranges)


def roles_for_ranges(
    middle: tuple[int, ...], left: tuple[int, ...], right: tuple[int, ...]
) -> tuple[str, str]:
    low = min(min(middle), min(left), min(right))
    high = max(max(middle), max(left), max(right))
    min_roles = []
    max_roles = []
    for role, values in (
        ("middle", middle),
        ("left_terminal_pair", left),
        ("right_terminal_pair", right),
    ):
        if min(values) == low:
            min_roles.append(role)
        if max(values) == high:
            max_roles.append(role)
    return "|".join(min_roles), "|".join(max_roles)


def outer_extensions(
    left: tuple[int, ...], right: tuple[int, ...], delta_left: int, delta_right: int
) -> tuple[int, int, int]:
    root1, root3 = -delta_left, delta_right
    if root1 < root3:
        e_left = max(0, root1 - min(left))
        e_right = max(0, max(right) - root3)
    else:
        e_left = max(0, max(left) - root1)
        e_right = max(0, root3 - min(right))
    return e_left, e_right, abs(root3 - root1)


def is_subset_in_envelope(values: tuple[int, ...], envelope: tuple[int, ...]) -> bool:
    return all(min(envelope) <= value <= max(envelope) for value in values)


def classify_regime(
    middle: tuple[int, ...], left: tuple[int, ...], right: tuple[int, ...],
    min_roles: str, max_roles: str,
) -> tuple[str, bool, bool, bool]:
    left_dominant = is_subset_in_envelope(middle, left) and is_subset_in_envelope(right, left)
    right_dominant = is_subset_in_envelope(middle, right) and is_subset_in_envelope(left, right)
    middle_dominant = is_subset_in_envelope(left, middle) and is_subset_in_envelope(right, middle)
    if left_dominant:
        regime = "left_terminal_dominant"
    elif right_dominant:
        regime = "right_terminal_dominant"
    elif middle_dominant:
        regime = "middle_dominant"
    else:
        # Outward means the low extreme is on the lower-coordinate outer
        # root's side and the high extreme is on the higher-coordinate root's
        # side. The reversed role pattern is cross-root but inward.
        # The caller supplies role names only, so retain the two role-pattern
        # classes here; the exact direction is filled by classify_direction.
        regime = "cross_root_extreme"
    return regime, left_dominant, right_dominant, middle_dominant


def classify_direction(
    min_roles: str, max_roles: str, delta_left: int, delta_right: int, regime: str
) -> str:
    if regime != "cross_root_extreme":
        return regime
    root1, root3 = -delta_left, delta_right
    if root1 < root3:
        outward = "left_terminal_pair" in min_roles and "right_terminal_pair" in max_roles
    else:
        outward = "right_terminal_pair" in min_roles and "left_terminal_pair" in max_roles
    return "cross_root_outward" if outward else "cross_root_inward"


def analyze_assignment(
    order_item: dict[str, object],
    context: dict[str, object],
    lengths: dict[str, int],
) -> dict[str, object]:
    blocks = order_item["blocks"]
    delta_left = int(context["delta_left"])
    delta_right = int(context["delta_right"])
    middle = tuple(int(value) for value in context["all_values"])
    left_key = (
        blocks["left_leaf_1"][0], lengths["left_leaf_1"],
        blocks["left_leaf_2"][0], lengths["left_leaf_2"],
    )
    right_key = (
        blocks["right_leaf_1"][0], lengths["right_leaf_1"],
        blocks["right_leaf_2"][0], lengths["right_leaf_2"],
    )
    left_states = terminal_pair_states(*left_key)
    right_states = terminal_pair_states(*right_key)
    middle_set = set(middle)
    middle_min, middle_max = min(middle), max(middle)

    left_compatible = []
    for state in left_states:
        values = shifted_state(state, -delta_left)
        if middle_set.intersection(values):
            continue
        if max(middle_max, max(values)) - min(middle_min, min(values)) > EDGE_COUNT:
            continue
        left_compatible.append((state, values))

    right_compatible = []
    for state in right_states:
        values = shifted_state(state, delta_right)
        if middle_set.intersection(values):
            continue
        if max(middle_max, max(values)) - min(middle_min, min(values)) > EDGE_COUNT:
            continue
        right_compatible.append((state, values))

    independent_best = None
    independent_witness = None
    independent_left_ext = []
    independent_right_ext = []
    for left_state, left_values in left_compatible:
        e_left, _unused, _d13 = outer_extensions(left_values, (0,), delta_left, delta_right)
        independent_left_ext.append(e_left)
        for right_state, right_values in right_compatible:
            _unused, e_right, _d13 = outer_extensions((0,), right_values, delta_left, delta_right)
            independent_right_ext.append(e_right)
            span = span_from_ranges([
                (middle_min, middle_max),
                (min(left_values), max(left_values)),
                (min(right_values), max(right_values)),
            ])
            if independent_best is None or span < independent_best:
                independent_best = span
                independent_witness = (left_state.state_id, right_state.state_id)

    joint_rows = []
    for left_state, left_values in left_compatible:
        left_set = set(left_values)
        e_left, _unused, d13 = outer_extensions(left_values, (0,), delta_left, delta_right)
        for right_state, right_values in right_compatible:
            if left_set.intersection(right_values):
                continue
            _unused, e_right, _d13 = outer_extensions((0,), right_values, delta_left, delta_right)
            span = span_from_ranges([
                (middle_min, middle_max),
                (min(left_values), max(left_values)),
                (min(right_values), max(right_values)),
            ])
            min_roles, max_roles = roles_for_ranges(middle, left_values, right_values)
            regime, left_dominant, right_dominant, middle_dominant = classify_regime(
                middle, left_values, right_values, min_roles, max_roles
            )
            regime = classify_direction(
                min_roles, max_roles, delta_left, delta_right, regime
            )
            joint_rows.append({
                "case": TREE1,
                "order_index": int(order_item["order_index"]),
                "middle_triple_id": int(order_item["middle_triple_id"]),
                "middle_context_id": int(context["context_id"]),
                "delta_left": delta_left,
                "delta_right": delta_right,
                "D13": d13,
                "left_state_id": left_state.state_id,
                "right_state_id": right_state.state_id,
                "left_interval_a": interval_text(blocks["left_leaf_1"]),
                "left_interval_b": interval_text(blocks["left_leaf_2"]),
                "right_interval_a": interval_text(blocks["right_leaf_1"]),
                "right_interval_b": interval_text(blocks["right_leaf_2"]),
                "left_min": min(left_values),
                "left_max": max(left_values),
                "right_min": min(right_values),
                "right_max": max(right_values),
                "middle_min": middle_min,
                "middle_max": middle_max,
                "e_left": e_left,
                "e_right": e_right,
                "e_sum": e_left + e_right,
                "span": span,
                "min_roles": min_roles,
                "max_roles": max_roles,
                "regime": regime,
                "left_dominant": left_dominant,
                "right_dominant": right_dominant,
                "middle_dominant": middle_dominant,
                "left_private": ";".join(map(str, left_values)),
                "right_private": ";".join(map(str, right_values)),
                "middle_values": ";".join(map(str, middle)),
            })

    joint_min = min((int(row["span"]) for row in joint_rows), default=None)
    joint_min_rows = [row for row in joint_rows if int(row["span"]) == joint_min]
    joint_e_sum_min = min((int(row["e_sum"]) for row in joint_rows), default=None)
    return {
        "order_index": int(order_item["order_index"]),
        "middle_triple_id": int(order_item["middle_triple_id"]),
        "middle_context_id": int(context["context_id"]),
        "residual_key": residual_key_text(blocks),
        "middle_key": middle_key_text(blocks),
        "delta_left": delta_left,
        "delta_right": delta_right,
        "D13": d13,
        "left_state_count": len(left_states),
        "right_state_count": len(right_states),
        "left_compatible_count": len(left_compatible),
        "right_compatible_count": len(right_compatible),
        "joint_pair_count": len(joint_rows),
        "sigma_ind": independent_best if independent_best is not None else "NONE",
        "sigma_joint": joint_min if joint_min is not None else "NONE",
        "kappa_sigma": (
            joint_min - independent_best
            if joint_min is not None and independent_best is not None else "NONE"
        ),
        "independent_witness": ";".join(map(str, independent_witness)) if independent_witness else "NONE",
        "independent_e_left_min": min(independent_left_ext, default=None),
        "independent_e_right_min": min(independent_right_ext, default=None),
        "independent_e_sum": (
            min(independent_left_ext) + min(independent_right_ext)
            if independent_left_ext and independent_right_ext else "NONE"
        ),
        "joint_e_sum_min": joint_e_sum_min if joint_e_sum_min is not None else "NONE",
        "joint_cross_root_e_sum_min": min(
            (int(row["e_sum"]) for row in joint_rows if row["regime"] == "cross_root_outward"),
            default=None,
        ),
        "joint_min_roles": ";".join(sorted({row["min_roles"] for row in joint_min_rows})),
        "joint_max_roles": ";".join(sorted({row["max_roles"] for row in joint_min_rows})),
        "joint_min_regimes": ";".join(sorted({row["regime"] for row in joint_min_rows})),
        "middle_min": min(middle),
        "middle_max": max(middle),
        "joint_rows": joint_rows,
    }


def load_tree2_certificate(path: Path) -> dict[str, object]:
    fields = dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    delta_left = int(fields["delta_left"])
    delta_right = int(fields["delta_right"])
    root1, root3 = -delta_left, delta_right
    left = tuple(sorted(
        value + root1
        for value in (*ints(fields["left_path_a"]), *ints(fields["left_path_b"]))
    ))
    right = tuple(sorted(
        value + root3
        for value in (*ints(fields["right_path_a"]), *ints(fields["right_path_b"]))
    ))
    bridge_left = ints(fields["left_bridge"])[1:-1]
    bridge_right = ints(fields["right_bridge"])[1:-1]
    central = ints(fields["central"])[1:]
    middle = tuple(sorted((root1, 0, root3, *(value + root1 for value in bridge_left),
                           *bridge_right, *central)))
    all_values = (*middle, *left, *right)
    low, high = min(all_values), max(all_values)
    left_dominant = is_subset_in_envelope(middle, left) and is_subset_in_envelope(right, left)
    right_dominant = is_subset_in_envelope(middle, right) and is_subset_in_envelope(left, right)
    middle_dominant = is_subset_in_envelope(left, middle) and is_subset_in_envelope(right, middle)
    regime = (
        "left_terminal_dominant" if left_dominant else
        "right_terminal_dominant" if right_dominant else
        "middle_dominant" if middle_dominant else "mixed"
    )
    min_role = (
        "left_terminal_pair" if min(left) == low else
        "right_terminal_pair" if min(right) == low else "middle"
    )
    max_role = (
        "left_terminal_pair" if max(left) == high else
        "right_terminal_pair" if max(right) == high else "middle"
    )
    if root1 < root3:
        e_left = max(0, root1 - min(left))
        e_right = max(0, max(right) - root3)
    else:
        e_left = max(0, max(left) - root1)
        e_right = max(0, root3 - min(right))
    d13 = abs(root3 - root1)
    return {
        "case": TREE2,
        "source": "verified_certificate",
        "delta_left": delta_left,
        "delta_right": delta_right,
        "D13": d13,
        "span": high - low,
        "min_offset": low,
        "max_offset": high,
        "min_role": min_role,
        "max_role": max_role,
        "left_min": min(left),
        "left_max": max(left),
        "right_min": min(right),
        "right_max": max(right),
        "middle_min": min(middle),
        "middle_max": max(middle),
        "left_outward_extension": e_left,
        "right_outward_extension": e_right,
        "outward_lower_bound": d13 + e_left + e_right,
        "outward_bound_match": high - low == d13 + e_left + e_right,
        "left_dominant": left_dominant,
        "right_dominant": right_dominant,
        "middle_dominant": middle_dominant,
        "regime": regime,
        "left_values": ";".join(map(str, left)),
        "right_values": ";".join(map(str, right)),
        "middle_values": ";".join(map(str, middle)),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gate-dir", type=Path,
        default=Path("results/edge63_span_feasibility_frontier/corrected_tree1_gate1"),
    )
    parser.add_argument(
        "--tree2-certificate", type=Path,
        default=Path("results/edge63_displacement_first_gate1/case2_exact_v5/verified_constructions/certificate.txt"),
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("results/edge63_span_feasibility_frontier/middle_conditioned_coupling_v1"),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    gate_summary = json.loads((args.gate_dir / "summary.json").read_text(encoding="utf-8"))
    case_record = gate_summary["cases"][0]
    stats = json.loads(case_record["stats"])
    if case_record["case"] != TREE1 or case_record["status"] != "UNSAT_EXHAUSTIVE":
        raise ValueError("the selected gate directory is not the corrected closed tree1 run")
    if int(case_record["contexts_done"]) != 112410 or int(case_record["orders_covered"]) != 5040:
        raise ValueError("corrected tree1 gate ledger is incomplete")

    values = values_for_case(TREE1)
    lengths, _triple_rows, order_map, order_to_triple, triple_to_orders, triple_to_middle_key = build_allocation_index(values)
    contexts_by_triple, reconstructed_context_count = build_middle_index(values, triple_to_middle_key)
    if reconstructed_context_count != int(case_record["contexts_done"]):
        raise ValueError("reconstructed middle-context count disagrees with the ledger")

    feasibility_rows = read_csv(args.gate_dir / "left_right_feasibility.csv")
    source_candidates = read_csv(args.gate_dir / "final_span_candidates.csv")
    if len(feasibility_rows) != reconstructed_context_count:
        raise ValueError("feasibility CSV row count disagrees with the ledger")

    candidate_groups: dict[tuple[int, int, int], list[dict[str, str]]] = defaultdict(list)
    for row in source_candidates:
        order_index = int(row["order_index"])
        triple_id = order_to_triple[order_index]
        context_id = int(row["middle_context_id"])
        if context_id not in contexts_by_triple[triple_id]:
            raise ValueError("candidate refers to a missing context")
        candidate_groups[(triple_id, context_id, order_index)].append(row)

    exact_analyses = {}
    frontiers = []
    for key in sorted(candidate_groups):
        triple_id, context_id, order_index = key
        item = dict(order_map[order_index])
        item["middle_triple_id"] = triple_id
        analysis = analyze_assignment(item, contexts_by_triple[triple_id][context_id], lengths)
        source_rows = candidate_groups[key]
        source_spans = sorted(int(row["span"]) for row in source_rows)
        recomputed_spans = sorted(int(row["span"]) for row in analysis["joint_rows"])
        if len(source_rows) != analysis["joint_pair_count"] or source_spans != recomputed_spans:
            raise ValueError(f"joint candidate mismatch at order/context {order_index}/{context_id}")
        exact_analyses[key] = analysis
        frontiers.extend(analysis["joint_rows"])

    if len(frontiers) != len(source_candidates):
        raise ValueError("recomputed frontier size disagrees with source candidates")
    write_csv(args.output_dir / "tree1_joint_extension_frontiers.csv", frontiers)
    write_csv(args.output_dir / "tree1_span67_candidates.csv", [row for row in frontiers if int(row["span"]) == 67])

    classification_fields = (
        "case", "order_index", "middle_triple_id", "middle_context_id", "delta_left",
        "delta_right", "D13", "span", "min_roles", "max_roles", "regime",
        "left_dominant", "right_dominant", "middle_dominant", "e_left", "e_right",
        "e_sum", "left_min", "left_max", "right_min", "right_max", "middle_min", "middle_max",
    )
    write_csv(args.output_dir / "tree1_valid36_classification.csv", [
        {field: row[field] for field in classification_fields} for row in frontiers
    ])
    write_csv(args.output_dir / "tree1_dominance_regime_scan.csv", [
        {field: row[field] for field in classification_fields} for row in frontiers
    ])

    coupling_fields = (
        "order_index", "middle_triple_id", "middle_context_id", "residual_key", "middle_key",
        "delta_left", "delta_right", "D13", "left_state_count", "right_state_count",
        "left_compatible_count", "right_compatible_count", "joint_pair_count", "sigma_ind",
        "sigma_joint", "kappa_sigma", "independent_witness", "independent_e_left_min",
        "independent_e_right_min", "independent_e_sum", "joint_e_sum_min",
        "joint_cross_root_e_sum_min", "joint_min_roles", "joint_max_roles", "joint_min_regimes",
    )
    write_csv(args.output_dir / "tree1_coupling_penalty.csv", [
        {field: exact_analyses[key][field] for field in coupling_fields}
        for key in sorted(exact_analyses)
    ])

    feasibility_by_context = {
        (int(row["middle_triple_id"]), int(row["context_id"])): row
        for row in feasibility_rows
    }
    candidates_by_context: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    analyses_by_context: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    for key, analysis in exact_analyses.items():
        triple_id, context_id, _order_index = key
        candidates_by_context[(triple_id, context_id)].extend(analysis["joint_rows"])
        analyses_by_context[(triple_id, context_id)].append(analysis)

    context_rows = []
    for key in sorted(feasibility_by_context):
        triple_id, context_id = key
        feasibility = feasibility_by_context[key]
        context = contexts_by_triple[triple_id][context_id]
        candidates = candidates_by_context.get(key, [])
        analyses = analyses_by_context.get(key, [])
        if candidates:
            sigma_min = min(int(row["span"]) for row in candidates)
            joint_e_sum_min = min(int(row["e_sum"]) for row in candidates)
            status = f"JOINT_SPAN_MIN_{sigma_min}"
        else:
            sigma_min = "NONE"
            joint_e_sum_min = "NONE"
            status = "NO_JOINT_TERMINAL_COMPLETION"
        sigma_ind_values = [int(a["sigma_ind"]) for a in analyses if a["sigma_ind"] != "NONE"]
        sigma_joint_values = [int(a["sigma_joint"]) for a in analyses if a["sigma_joint"] != "NONE"]
        kappa_values = [int(a["kappa_sigma"]) for a in analyses if a["kappa_sigma"] != "NONE"]
        independent_e_sum_values = [
            int(a["independent_e_sum"])
            for a in analyses if a["independent_e_sum"] != "NONE"
        ]
        context_rows.append({
            "case": TREE1,
            "middle_triple_id": triple_id,
            "middle_context_id": context_id,
            "delta_left": int(feasibility["delta_left"]),
            "delta_right": int(feasibility["delta_right"]),
            "D13": abs(int(feasibility["delta_left"]) + int(feasibility["delta_right"])),
            "middle_min": int(context["min"]),
            "middle_max": int(context["max"]),
            "middle_span": int(context["max"]) - int(context["min"]),
            "orders_covered_by_middle_triple": len(triple_to_orders[triple_id]),
            "residual_assignments": int(feasibility["residual_assignments"]),
            "compatible_left_total": int(feasibility["compatible_left_total"]),
            "compatible_right_total": int(feasibility["compatible_right_total"]),
            "final_join_checks_from_ledger": int(feasibility["final_join_checks"]),
            "joint_pair_count": len(candidates),
            "sigma_min_joint": sigma_min,
            "sigma_min_ind": min(sigma_ind_values) if sigma_ind_values else "NOT_RECOMPUTED",
            "sigma_joint_recomputed": min(sigma_joint_values) if sigma_joint_values else "NOT_RECOMPUTED",
            "kappa_sigma": min(kappa_values) if kappa_values else "NOT_RECOMPUTED",
            "independent_e_sum": min(independent_e_sum_values) if independent_e_sum_values else "NOT_RECOMPUTED",
            "joint_e_sum_min": joint_e_sum_min,
            "joint_min_regimes": ";".join(sorted({
                regime for analysis in analyses
                for regime in str(analysis["joint_min_regimes"]).split(";") if regime
            })),
            "status": status,
        })
    write_csv(args.output_dir / "tree1_middle_conditioned_span.csv", context_rows)

    tree2 = load_tree2_certificate(args.tree2_certificate)
    write_csv(args.output_dir / "tree2_verified_regime_analysis.csv", [tree2])

    span_classes: dict[tuple, list[dict[str, object]]] = defaultdict(list)
    for row in frontiers:
        key = (
            row["regime"], row["min_roles"], row["max_roles"], int(row["D13"]),
            int(row["span"]), int(row["e_left"]), int(row["e_right"]),
        )
        span_classes[key].append(row)
    class_rows = []
    for class_id, (key, rows) in enumerate(sorted(span_classes.items()), 1):
        regime, min_roles, max_roles, d13, span, e_left, e_right = key
        class_rows.append({
            "class_id": class_id,
            "regime": regime,
            "min_roles": min_roles,
            "max_roles": max_roles,
            "D13": d13,
            "span": span,
            "e_left": e_left,
            "e_right": e_right,
            "candidate_count": len(rows),
            "orders": ";".join(map(str, sorted({int(row["order_index"]) for row in rows}))),
            "contexts": ";".join(map(str, sorted({int(row["middle_context_id"]) for row in rows}))),
        })
    write_csv(args.output_dir / "span_behavior_classes.csv", class_rows)

    minima = [row for row in frontiers if int(row["span"]) == 67]
    minimum_orders = {}
    for order_index in sorted({int(row["order_index"]) for row in minima}):
        item = order_map[order_index]
        minimum_orders[order_index] = {
            "order": list(item["order"]),
            "middle_triple_id": order_to_triple[order_index],
            "blocks": {path: list(item["blocks"][path]) for path in PATHS},
        }

    candidate_spans = Counter(int(row["span"]) for row in frontiers)
    context_status = Counter(row["status"] for row in context_rows)
    regime_counts = Counter(row["regime"] for row in frontiers)
    coupling_values = []
    for key in sorted(exact_analyses):
        value = exact_analyses[key]["kappa_sigma"]
        if value != "NONE":
            coupling_values.append(int(value))
    coupling_hist = Counter(coupling_values)
    context_min_counter = Counter(
        row["sigma_min_joint"] for row in context_rows if row["sigma_min_joint"] != "NONE"
    )
    summary = {
        "case": TREE1,
        "cache_version": CACHE_VERSION,
        "corrected_gate_status": case_record["status"],
        "corrected_gate_orders": int(case_record["orders_covered"]),
        "corrected_gate_contexts": int(case_record["contexts_done"]),
        "reconstructed_contexts": reconstructed_context_count,
        "source_final_candidates": len(source_candidates),
        "recomputed_joint_candidates": len(frontiers),
        "final_span_histogram": dict(sorted(candidate_spans.items())),
        "sigma_min_tree1": min(int(row["span"]) for row in frontiers),
        "span_gap": min(int(row["span"]) for row in frontiers) - EDGE_COUNT,
        "minimum_candidate_count": len(minima),
        "minimum_orders": minimum_orders,
        "context_status_counts": dict(context_status),
        "context_sigma_min_histogram": {str(k): v for k, v in sorted(context_min_counter.items(), key=lambda item: str(item[0]))},
        "contexts_with_joint_terminal_completion": reconstructed_context_count - context_status["NO_JOINT_TERMINAL_COMPLETION"],
        "contexts_without_joint_terminal_completion": context_status["NO_JOINT_TERMINAL_COMPLETION"],
        "regime_counts": dict(regime_counts),
        "single_root_dominant_candidate_count": sum(
            1 for row in frontiers
            if row["regime"] in {
                "left_terminal_dominant", "right_terminal_dominant", "middle_dominant"
            }
        ),
        "cross_root_outward_candidate_count": regime_counts["cross_root_outward"],
        "cross_root_inward_candidate_count": regime_counts["cross_root_inward"],
        "coupling_sigma_histogram": {str(k): v for k, v in sorted(coupling_hist.items())},
        "exact_assignment_keys": len(exact_analyses),
        "exact_assignment_scope_note": (
            "sigma_ind and kappa_sigma are recomputed for the 12 order/context assignments "
            "that produced all 36 completed final-join rows; the all-context joint frontier "
            "comes from the corrected exhaustive ledger."
        ),
        "tree2": tree2,
        "source_sha256": {
            "gate_summary": sha256(args.gate_dir / "summary.json"),
            "final_span_candidates": sha256(args.gate_dir / "final_span_candidates.csv"),
            "left_right_feasibility": sha256(args.gate_dir / "left_right_feasibility.csv"),
        },
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    certificate = {
        "certificate_kind": "finite_corrected_gate1_span_audit",
        "case": TREE1,
        "cache_version": CACHE_VERSION,
        "language": "seven maximal paths; one consecutive difference interval per path; complete Level-B local behavior",
        "source_gate": {
            "status": case_record["status"],
            "orders_total": 5040,
            "orders_done": int(case_record["orders_covered"]),
            "contexts_total": 112410,
            "contexts_done": int(case_record["contexts_done"]),
            "unsafe_dominance": False,
            "verifier_failures": int(stats.get("verifier_failure", 0)),
        },
        "non_span_final_candidates": {
            "count": len(frontiers),
            "span_histogram": dict(sorted(candidate_spans.items())),
            "minimum_span": min(int(row["span"]) for row in frontiers),
            "minimum_candidate_count": len(minima),
        },
        "claim": "sigma_min(T1; corrected Level-B single-interval language) = 67",
        "scope_warning": "Finite certificate for the declared construction language; not a claim that the tree is non-graceful.",
        "source_sha256": summary["source_sha256"],
    }
    (args.output_dir / "compact_span_certificate.json").write_text(json.dumps(certificate, indent=2), encoding="utf-8")

    formal = r'''# Middle-conditioned span lemmas

## 1. Exact middle-conditioned span identity

Fix a middle context and a left/right terminal-pair choice. In the common
middle-root frame let the three finite offset sets be `L`, `M`, and `R`.
The minimum of a finite union is the minimum of the component minima, and
the maximum is the maximum of the component maxima. Hence

`span(L union M union R) = max(max L, max M, max R) - min(min L, min M, min R)`.

Taking the minimum over the exactly joint-compatible terminal choices gives
the `sigma_min(M)` used in the analysis.

## 2. Independent versus joint relaxation

Let `L(M)` and `R(M)` be the two terminal families after their individual
compatibility checks with the fixed middle context. Let `P(M)` be the subset
of pairs whose translated private offset sets are disjoint. Since
`P(M) subset L(M) x R(M)`, minimizing the same span function over `P(M)`
cannot give a smaller value than minimizing over the larger Cartesian product.
Therefore `sigma_joint(M) >= sigma_ind(M)` whenever both exist, and
`kappa_sigma(M) = sigma_joint(M)-sigma_ind(M) >= 0`.

## 3. Cross-root extreme formula

Let the outer roots be `r1 < r3`. If the global minimum is attained by the
left terminal pair and the global maximum by the right terminal pair, set
`eL = r1-min(L)` and `eR = max(R)-r3`. The global extrema are then
`r1-eL` and `r3+eR`, so `span = (r3-r1)+eL+eR`. The reversed-root case is
the analogous formula. Without the extreme-role hypothesis the expression is
only a lower-bound candidate, not an equality.

## 4. Single-root dominance criterion

If `L union M subset [min(R), max(R)]`, then the extrema of `R` are also the
global extrema and `span = span(R)`. This is a sufficient right-dominant
criterion; the left analogue is identical.

## 5. Corrected terminal-pair injectivity condition

For private offset tuples `A` and `B`, a pair is admissible only if
`len(set(A union B)) = len(A)+len(B)`, with the root offset excluded. The
tautological size test on the already-concatenated union does not detect
cross-path private-vertex collisions.
'''
    (args.output_dir / "formal_lemmas.md").write_text(formal, encoding="utf-8")

    comparison = f'''# Tree1 / Tree2 regime comparison

| quantity | Tree1 corrected minimum layer | Tree2 verified certificate |
| --- | ---: | ---: |
| global span | 67 | 63 |
| outer-root separation D13 | 16 | 5 |
| left outward extension | 10 | 40 |
| right outward extension | 41 | 7 |
| outward expression D13+eL+eR | 67 | 52 |
| minimum role | right terminal pair | right terminal pair |
| maximum role | left terminal pair | right terminal pair |
| regime | cross-root-outward | right-terminal-dominant |

Tree1's four span-67 rows are the only cross-root-outward rows. The other 32
valid non-span rows are cross-root-inward under the coordinate-aware
classification, so the outward equality is not a universal tree1 identity.
Tree1 has no single-root-dominant row among its 36 corrected final rows.

Tree2 is a control against universalizing the Tree1 formula: its right
terminal envelope contains the left and middle offsets and supplies both
global extrema, so its span is the right-pair envelope span 63.

The two Tree1 minimum block orders differ only by swapping
`right_leaf_1` and `right_leaf_2`. In the generator those two terminal paths
have equal length 4, so this is the actual right-branch leaf-swap
automorphism, not an interval-axis reversal.
'''
    (args.output_dir / "tree1_tree2_regime_comparison.md").write_text(comparison, encoding="utf-8")

    report = f'''# Middle-conditioned coupling analysis

This analysis uses terminal-pair cache version `{CACHE_VERSION}` and the
completed corrected tree-1 Gate1 ledger. It did not start a new full graceful
search, enter two-interval constructions, expand Level-B, or modify the
edge63 main log.

## Corrected finite result

Tree1 `{TREE1}` is `UNSAT_EXHAUSTIVE` for the declared seven-path,
single-consecutive-interval, complete Level-B language. The corrected ledger
covers all 5040 orders and all 112410 middle contexts. Its 36 candidates that
pass all non-span conditions have span histogram
`{dict(sorted(candidate_spans.items()))}`, so the exact finite minimum is
`sigma_min=67` and the span gap is 4.

The all-context table contains `{context_status["NO_JOINT_TERMINAL_COMPLETION"]}`
contexts with no joint terminal completion. The remaining contexts and their
joint minimum spans are in `tree1_middle_conditioned_span.csv`.

## Joint coupling audit

The 36 source rows collapse to `{len(exact_analyses)}` exact order/context
assignments. For these assignments the script recomputes both the independent
relaxation and the exact left-right disjoint minimum. The resulting
`kappa_sigma` histogram is `{dict(sorted(coupling_hist.items()))}`.
Independent values are intentionally marked `NOT_RECOMPUTED` for contexts that
never reach a final pair; no partial computation is presented as a theorem.

## Extreme regimes

The 36-row regime counts are `{dict(regime_counts)}`. The four span-67 rows
are the cross-root-outward rows and satisfy the exact regime-specific
`D13+eL+eR=67` decomposition. The other 32 rows are cross-root-inward, so
this is not a universal formula. No corrected final row is single-root
dominant.

Tree2's verified certificate has span `{tree2["span"]}`, `D13={tree2["D13"]}`,
and is classified as `{tree2["regime"]}`. Its right terminal envelope
contains the left and middle offsets, so it is a concrete single-root control;
its outward expression is only `{tree2["outward_lower_bound"]}` and is not tight.

## Interpretation

For the 12 exact order/context assignments that produce all 36 final rows,
the independent and joint minima agree throughout: `kappa_sigma=0`. Thus the
four-unit gap is already present after fixing the middle context and imposing
the individual middle-compatibility/span checks; it is not an additional
penalty from the final left-right disjointness step. This conclusion is
scoped to those 12 assignments. The all-context joint frontier itself is
covered by the corrected exhaustive ledger.

This is a finite computational obstruction to the declared construction
language, not a graceful nonexistence result and not yet an analytic parameter
theorem.
'''
    (args.output_dir / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
