#!/usr/bin/env python3
"""Cheap containment/envelope prescan for the three unused benchmarks.

The prescan keeps the corrected.v2 Level-B local language, but stops before
the full Gate-1 left/right final join.  It records optimistic envelope
containment (ignoring left/right private-set collision) and, only when an
optimistic zero-deficit pair exists, checks exact terminal-state disjointness.
It does not run unrestricted graceful search.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_displacement_first_compact import (  # noqa: E402
    all_allocations,
    bridge_pairs,
    compact_options,
    middle_contexts,
    path_lengths,
)
from edge63_middle_conditioned_span import terminal_pair_states  # noqa: E402
from edge63_structure_analysis import parse_case  # noqa: E402


EDGE_COUNT = 63
CACHE_VERSION = "corrected.v2"
DEFAULT_CASES = (
    "fiveleaf3e-63-3-21-2-14-15-4-4",
    "fiveleaf3e-63-15-1-1-4-13-14-15",
    "fiveleaf3e-63-5-2-2-4-17-11-22",
)


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


def values_for_case(case: str) -> tuple[int, ...]:
    parsed = parse_case(case)
    if parsed is None or parsed[1] != EDGE_COUNT:
        raise ValueError(f"not an edge-63 case: {case}")
    return parsed[2]


def read_repair_metadata(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    return {row["case"]: row for row in read_csv(path)}


def residual_key(item: dict[str, object], terminal_names: tuple[str, ...]) -> tuple[tuple[str, int, int], ...]:
    blocks = item["blocks"]
    return tuple((name, blocks[name][0], blocks[name][1]) for name in terminal_names)


def compatible_states(states, shift: int, middle: tuple[int, ...]):
    middle_set = set(middle)
    middle_min, middle_max = min(middle), max(middle)
    result = []
    for state in states:
        values = tuple(value + shift for value in state.private)
        if middle_set.intersection(values):
            continue
        low = min(middle_min, shift + state.min_value)
        high = max(middle_max, shift + state.max_value)
        if high - low > EDGE_COUNT:
            continue
        result.append((state, values, shift + state.min_value, shift + state.max_value))
    return result


def exact_zero_containment(
    left_states, right_states, middle: tuple[int, ...]
) -> tuple[bool, bool]:
    """Check zero-deficit containment with actual private-set disjointness."""
    middle_min, middle_max = min(middle), max(middle)
    right_ok = False
    left_ok = False
    for _left_state, left_values, left_min, left_max in left_states:
        left_middle_min = min(middle_min, left_min)
        left_middle_max = max(middle_max, left_max)
        left_value_set = set(left_values)
        for _right_state, right_values, right_min, right_max in right_states:
            if left_value_set.intersection(right_values):
                continue
            if right_min <= left_middle_min and right_max >= left_middle_max:
                right_ok = True
            right_other_min = min(middle_min, right_min)
            right_other_max = max(middle_max, right_max)
            if left_min <= right_other_min and left_max >= right_other_max:
                left_ok = True
            if left_ok and right_ok:
                return True, True
    return left_ok, right_ok


def optimistic_metrics(
    left_ranges: list[tuple[int, int]],
    right_ranges: list[tuple[int, int]],
    middle: tuple[int, ...],
    delta_left: int,
    delta_right: int,
) -> dict[str, object]:
    """Return envelope-only scores and safe independent span lower bounds."""
    middle_min, middle_max = min(middle), max(middle)
    if not left_ranges or not right_ranges:
        return {
            "best_opt_deficit": None,
            "best_opt_left_deficit": None,
            "best_opt_right_deficit": None,
            "best_opt_span": None,
            "optimistic_span_lb": None,
            "cross_root_outward_lb": None,
            "cross_root_inward_lb": None,
            "optimistic_right_zero": False,
            "optimistic_left_zero": False,
        }
    # Level 1 is deliberately optimistic: min/max endpoints are allowed to
    # come from different local states.  This is a prediction relaxation, not
    # an exact completion test.
    left_best_min = max(low for low, _high in left_ranges)
    left_best_max = min(high for _low, high in left_ranges)
    right_best_min = min(low for low, _high in right_ranges)
    right_best_max = max(high for _low, high in right_ranges)
    left_middle_min = min(middle_min, left_best_min)
    left_middle_max = max(middle_max, left_best_max)
    right_other_min = min(middle_min, right_best_min)
    right_other_max = max(middle_max, right_best_max)
    best_left_deficit = max(0, left_best_min - right_other_min) + max(0, right_other_max - left_best_max)
    best_right_deficit = max(0, right_best_min - left_middle_min) + max(0, left_middle_max - right_best_max)
    best_deficit = min(best_left_deficit, best_right_deficit)
    best_span = max(middle_max, left_best_max, right_best_max) - min(middle_min, left_best_min, right_best_min)
    root1, root3 = -delta_left, delta_right
    d13 = abs(root3 - root1)
    left_outward = []
    right_outward = []
    left_inward = []
    right_inward = []

    for left_min, left_max in left_ranges:
        if root1 < root3:
            left_outward.append(max(0, root1 - left_min))
            left_inward.append(max(0, left_max - root1))
        else:
            left_outward.append(max(0, left_max - root1))
            left_inward.append(max(0, root1 - left_min))
    for right_min, right_max in right_ranges:
        if root1 < root3:
            right_outward.append(max(0, right_max - root3))
            right_inward.append(max(0, root3 - right_min))
        else:
            right_outward.append(max(0, root3 - right_min))
            right_inward.append(max(0, right_max - root3))

    # The endpoint min/max relaxation is a safe lower bound: each actual
    # union maximum is at least the minimum achievable component maximum, and
    # each actual union minimum is at most the maximum achievable component
    # minimum.  It is deliberately optimistic and never used as an UNSAT
    # claim in this prescan.
    high_lb = max(middle_max, min(high for _low, high in left_ranges), min(high for _low, high in right_ranges))
    low_ub = min(middle_min, max(low for low, _high in left_ranges), max(low for low, _high in right_ranges))
    optimistic_span_lb = max(0, high_lb - low_ub)

    inward_lb = min(left_inward) + min(right_inward) - d13
    return {
        "best_opt_deficit": best_deficit,
        "best_opt_left_deficit": best_left_deficit,
        "best_opt_right_deficit": best_right_deficit,
        "best_opt_span": best_span,
        "optimistic_span_lb": optimistic_span_lb,
        "cross_root_outward_lb": d13 + min(left_outward) + min(right_outward) if left_outward and right_outward else None,
        "cross_root_inward_lb": inward_lb,
        "optimistic_right_zero": best_right_deficit == 0,
        "optimistic_left_zero": best_left_deficit == 0,
    }


def endpoint_summary(states, shift: int) -> dict[str, object]:
    if not states:
        return {"min_min": None, "max_min": None, "min_max": None, "max_max": None,
                "outward_min": None, "inward_min": None}
    mins = [shift + state.min_value for state in states]
    maxes = [shift + state.max_value for state in states]
    return {
        "min_min": min(mins),
        "max_min": max(mins),
        "min_max": min(maxes),
        "max_max": max(maxes),
    }


def endpoint_summary_from_base(summary: dict[str, object], shift: int) -> dict[str, object]:
    if summary["min_min"] is None:
        return dict(summary)
    return {
        key: int(value) + shift
        for key, value in summary.items()
    }


def coarse_pair_metrics(left: dict[str, object], right: dict[str, object], middle_min: int, middle_max: int,
                        delta_left: int, delta_right: int) -> dict[str, object]:
    """Endpoint-only Level-1 relaxation; all extrema may come from different states."""
    if left["min_min"] is None or right["min_min"] is None:
        return {"deficit": None, "left_deficit": None, "right_deficit": None,
                "span_lb": None, "outward_lb": None, "inward_lb": None,
                "left_zero": False, "right_zero": False}
    left_min = int(left["max_min"])
    left_max = int(left["min_max"])
    right_min = int(right["min_min"])
    right_max = int(right["max_max"])
    left_other_min = min(middle_min, right_min)
    left_other_max = max(middle_max, right_max)
    right_other_min = min(middle_min, left_min)
    right_other_max = max(middle_max, left_max)
    left_deficit = max(0, left_min - left_other_min) + max(0, left_other_max - left_max)
    right_deficit = max(0, right_min - right_other_min) + max(0, right_other_max - right_max)
    high_lb = max(middle_max, int(left["min_max"]), int(right["min_max"]))
    low_ub = min(middle_min, int(left["max_min"]), int(right["max_min"]))
    root1, root3 = -delta_left, delta_right
    if root1 < root3:
        e_left = max(0, root1 - int(left["max_min"]))
        e_right = max(0, int(right["min_max"]) - root3)
        i_left = max(0, int(left["min_max"]) - root1)
        i_right = max(0, root3 - int(right["max_min"]))
    else:
        e_left = max(0, int(left["min_max"]) - root1)
        e_right = max(0, root3 - int(right["max_min"]))
        i_left = max(0, root1 - int(left["max_min"]))
        i_right = max(0, int(right["min_max"]) - root3)
    d13 = abs(root3 - root1)
    return {
        "deficit": min(left_deficit, right_deficit),
        "left_deficit": left_deficit,
        "right_deficit": right_deficit,
        "span_lb": max(0, high_lb - low_ub),
        "outward_lb": d13 + e_left + e_right,
        "inward_lb": i_left + i_right - d13,
        "left_zero": left_deficit == 0,
        "right_zero": right_deficit == 0,
    }


def prescan_case(case: str, metadata: dict[str, str] | None, output_dir: Path):
    started = time.perf_counter()
    values = values_for_case(case)
    lengths, middle_to_orders, triple_rows = all_allocations(values)
    terminal_names = ("left_leaf_1", "left_leaf_2", "right_leaf_1", "right_leaf_2")
    orders = {int(item["order_index"]): item for items in middle_to_orders.values() for item in items}
    order_rows = {
        index: {
            "case": case, "order_index": index,
            "optimistic_left_containment": False, "optimistic_right_containment": False,
            "minimum_optimistic_deficit": None, "minimum_optimistic_span": None,
            "best_optimistic_span_lb": None, "best_cross_root_outward_lb": None,
            "best_cross_root_inward_lb": None, "middle_triples_seen": 0,
        }
        for index in orders
    }
    context_total = 0
    residual_assignment_total = 0
    middle_stats_totals = Counter()
    context_opt_zero = set()
    triple_rows_output = []
    for triple_id, (middle_key, residual_items) in enumerate(middle_to_orders.items()):
        blocks = residual_items[0]["blocks"]
        contexts, context_stats = middle_contexts(
            blocks["left_bridge"][0], lengths["left_bridge"],
            blocks["middle_leaf"][0], lengths["middle_leaf"],
            blocks["right_bridge"][0], lengths["right_bridge"], "B",
        )
        context_total += len(contexts)
        middle_stats_totals.update(context_stats)
        unique_residuals = defaultdict(list)
        for item in residual_items:
            unique_residuals[residual_key(item, terminal_names)].append(int(item["order_index"]))
        residual_assignment_total += len(unique_residuals)
        residual_data = []
        for signature, order_indices in unique_residuals.items():
            block_map = {name: (start, end) for name, start, end in signature}
            left_states = terminal_pair_states(
                block_map["left_leaf_1"][0], lengths["left_leaf_1"],
                block_map["left_leaf_2"][0], lengths["left_leaf_2"],
            )
            right_states = terminal_pair_states(
                block_map["right_leaf_1"][0], lengths["right_leaf_1"],
                block_map["right_leaf_2"][0], lengths["right_leaf_2"],
            )
            residual_data.append((signature, order_indices, endpoint_summary(left_states, 0), endpoint_summary(right_states, 0)))
        triple_best = {"deficit": None, "span_lb": None, "outward_lb": None, "inward_lb": None}
        triple_deltas = set()
        for context in contexts:
            middle_min, middle_max = int(context["min"]), int(context["max"])
            delta_left, delta_right = int(context["delta_left"]), int(context["delta_right"])
            triple_deltas.add((delta_left, delta_right))
            for _signature, order_indices, left_base, right_base in residual_data:
                left = endpoint_summary_from_base(left_base, -delta_left)
                right = endpoint_summary_from_base(right_base, delta_right)
                metrics = coarse_pair_metrics(left, right, middle_min, middle_max, delta_left, delta_right)
                if metrics["deficit"] is None:
                    continue
                opt_left = bool(metrics["left_zero"])
                opt_right = bool(metrics["right_zero"])
                if opt_left or opt_right:
                    context_opt_zero.add((triple_id, int(context["context_id"])))
                for order_index in order_indices:
                    row = order_rows[order_index]
                    row["optimistic_left_containment"] |= opt_left
                    row["optimistic_right_containment"] |= opt_right
                    for field, value in (
                        ("minimum_optimistic_deficit", metrics["deficit"]),
                        ("minimum_optimistic_span", metrics["span_lb"]),
                        ("best_optimistic_span_lb", metrics["span_lb"]),
                        ("best_cross_root_outward_lb", metrics["outward_lb"]),
                        ("best_cross_root_inward_lb", metrics["inward_lb"]),
                    ):
                        if value is not None:
                            row[field] = value if row[field] is None else min(row[field], value)
                    row["middle_triples_seen"] += 1
                for field, value in (("deficit", metrics["deficit"]), ("span_lb", metrics["span_lb"]),
                                     ("outward_lb", metrics["outward_lb"]), ("inward_lb", metrics["inward_lb"])):
                    if value is not None:
                        triple_best[field] = value if triple_best[field] is None else min(triple_best[field], value)
        triple_rows_output.append({
            "case": case, "middle_triple_id": triple_id,
            "middle_intervals": ";".join(f"{path}={start}-{end}" for path, start, end in middle_key),
            "middle_contexts": len(contexts), "residual_assignments": len(unique_residuals),
            "delta_pairs": ";".join(f"{left},{right}" for left, right in sorted(triple_deltas)),
            "best_optimistic_deficit": triple_best["deficit"] if triple_best["deficit"] is not None else "NONE",
            "best_optimistic_span_lb": triple_best["span_lb"] if triple_best["span_lb"] is not None else "NONE",
            "best_cross_root_outward_lb": triple_best["outward_lb"] if triple_best["outward_lb"] is not None else "NONE",
            "best_cross_root_inward_lb": triple_best["inward_lb"] if triple_best["inward_lb"] is not None else "NONE",
        })

    order_output = []
    for index, row in sorted(order_rows.items()):
        order_output.append({
            **row,
            "path_lengths": ";".join(f"{name}={lengths[name]}" for name in lengths),
            **{field: ("NONE" if row[field] is None else row[field]) for field in (
                "minimum_optimistic_deficit", "minimum_optimistic_span", "best_optimistic_span_lb",
                "best_cross_root_outward_lb", "best_cross_root_inward_lb")},
        })
    write_csv(output_dir / f"{case}_order_prescan.csv", order_output)
    write_csv(output_dir / f"{case}_middle_triple_prescan.csv", triple_rows_output)
    def count_flag(field: str) -> int:
        return sum(bool(row[field]) for row in order_rows.values())
    min_deficit = min((row["minimum_optimistic_deficit"] for row in order_rows.values() if row["minimum_optimistic_deficit"] is not None), default=None)
    best_span_lb = min((row["best_optimistic_span_lb"] for row in order_rows.values() if row["best_optimistic_span_lb"] is not None), default=None)
    best_outward = min((row["best_cross_root_outward_lb"] for row in order_rows.values() if row["best_cross_root_outward_lb"] is not None), default=None)
    best_inward = min((row["best_cross_root_inward_lb"] for row in order_rows.values() if row["best_cross_root_inward_lb"] is not None), default=None)
    if count_flag("optimistic_left_containment") or count_flag("optimistic_right_containment"):
        predicted_class = "A_OPTIMISTIC_ONLY"
    elif best_outward is not None and best_outward <= EDGE_COUNT:
        predicted_class = "B"
    else:
        predicted_class = "C"
    result = {
        "case": case, "cache_version": CACHE_VERSION, "path_lengths": lengths,
        "active_pattern": metadata.get("active_pattern", "UNKNOWN") if metadata else "UNKNOWN",
        "rho": int(metadata["rho"]) if metadata and metadata.get("rho", "").isdigit() else "UNKNOWN",
        "interval_orders": len(orders), "middle_triples": len(triple_rows),
        "middle_contexts": context_total, "unique_residual_assignments": residual_assignment_total,
        "contexts_with_optimistic_containment": len(context_opt_zero),
        "contexts_with_exact_containment": "NOT_RUN",
        "orders_optimistic_left_containment": count_flag("optimistic_left_containment"),
        "orders_optimistic_right_containment": count_flag("optimistic_right_containment"),
        "orders_optimistic_any_containment": sum(bool(row["optimistic_left_containment"] or row["optimistic_right_containment"]) for row in order_rows.values()),
        "orders_exact_left_containment": "NOT_RUN", "orders_exact_right_containment": "NOT_RUN",
        "orders_exact_any_containment": "NOT_RUN",
        "minimum_optimistic_containment_deficit": min_deficit if min_deficit is not None else "NONE",
        "best_optimistic_span_lb": best_span_lb if best_span_lb is not None else "NONE",
        "best_cross_root_outward_lb": best_outward if best_outward is not None else "NONE",
        "best_cross_root_inward_lb": best_inward if best_inward is not None else "NONE",
        "predicted_class": predicted_class, "prediction_basis": "Level-1 endpoint relaxation; exact containment not run",
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "context_stats": {"raw_contexts": middle_stats_totals.get("raw_contexts", 0), "totals": dict(middle_stats_totals)},
        "prescan_scope": "Level-1 envelope prescan only; not Gate-1 decision.",
    }
    return result, order_output, triple_rows_output


def prescan_case_coarse(case: str, metadata: dict[str, str] | None, output_dir: Path):
    """Run the same order-level relaxation without materializing contexts."""
    started = time.perf_counter()
    values = values_for_case(case)
    lengths, middle_to_orders, triple_rows = all_allocations(values)
    terminal_names = ("left_leaf_1", "left_leaf_2", "right_leaf_1", "right_leaf_2")
    orders = {int(item["order_index"]): item for items in middle_to_orders.values() for item in items}
    order_rows = {
        index: {
            "case": case, "order_index": index,
            "optimistic_left_containment": False, "optimistic_right_containment": False,
            "minimum_optimistic_deficit": None, "minimum_optimistic_span": None,
            "best_optimistic_span_lb": None, "best_cross_root_outward_lb": None,
            "best_cross_root_inward_lb": None, "middle_triples_seen": 0,
        }
        for index in orders
    }
    triple_rows_output = []
    delta_support_total = 0
    for triple_id, (middle_key, residual_items) in enumerate(middle_to_orders.items()):
        blocks = residual_items[0]["blocks"]
        bridges = bridge_pairs(
            blocks["left_bridge"][0], lengths["left_bridge"],
            blocks["right_bridge"][0], lengths["right_bridge"], "B",
        )
        central_options = compact_options("terminal", blocks["middle_leaf"][0], lengths["middle_leaf"], "B")
        central_min = min(min(option.offsets[1:]) for option in central_options)
        central_max = max(max(option.offsets[1:]) for option in central_options)
        delta_envelopes = {}
        for bridge in bridges:
            delta_left = int(bridge.roots[1] - bridge.roots[0])
            delta_right = int(bridge.roots[2] - bridge.roots[1])
            bridge_values = tuple(value - delta_left for value in bridge.used)
            current = delta_envelopes.get((delta_left, delta_right))
            low = min(min(bridge_values), central_min)
            high = max(max(bridge_values), central_max)
            if current is None:
                delta_envelopes[(delta_left, delta_right)] = [low, high]
            else:
                current[0] = min(current[0], low)
                current[1] = max(current[1], high)
        delta_support_total += len(delta_envelopes)
        unique_residuals = defaultdict(list)
        for item in residual_items:
            unique_residuals[residual_key(item, terminal_names)].append(int(item["order_index"]))
        residual_data = []
        for signature, order_indices in unique_residuals.items():
            block_map = {name: (start, end) for name, start, end in signature}
            left_states = terminal_pair_states(
                block_map["left_leaf_1"][0], lengths["left_leaf_1"],
                block_map["left_leaf_2"][0], lengths["left_leaf_2"],
            )
            right_states = terminal_pair_states(
                block_map["right_leaf_1"][0], lengths["right_leaf_1"],
                block_map["right_leaf_2"][0], lengths["right_leaf_2"],
            )
            residual_data.append((order_indices, endpoint_summary(left_states, 0), endpoint_summary(right_states, 0)))
        triple_best = {"deficit": None, "span_lb": None, "outward_lb": None, "inward_lb": None}
        for (delta_left, delta_right), (middle_min, middle_max) in delta_envelopes.items():
            for order_indices, left_base, right_base in residual_data:
                left = endpoint_summary_from_base(left_base, -delta_left)
                right = endpoint_summary_from_base(right_base, delta_right)
                metrics = coarse_pair_metrics(left, right, middle_min, middle_max, delta_left, delta_right)
                if metrics["deficit"] is None:
                    continue
                for order_index in order_indices:
                    row = order_rows[order_index]
                    row["optimistic_left_containment"] |= bool(metrics["left_zero"])
                    row["optimistic_right_containment"] |= bool(metrics["right_zero"])
                    for field, value in (
                        ("minimum_optimistic_deficit", metrics["deficit"]),
                        ("minimum_optimistic_span", metrics["span_lb"]),
                        ("best_optimistic_span_lb", metrics["span_lb"]),
                        ("best_cross_root_outward_lb", metrics["outward_lb"]),
                        ("best_cross_root_inward_lb", metrics["inward_lb"]),
                    ):
                        if value is not None:
                            row[field] = value if row[field] is None else min(row[field], value)
                    row["middle_triples_seen"] += 1
                for field, value in (("deficit", metrics["deficit"]), ("span_lb", metrics["span_lb"]),
                                     ("outward_lb", metrics["outward_lb"]), ("inward_lb", metrics["inward_lb"])):
                    if value is not None:
                        triple_best[field] = value if triple_best[field] is None else min(triple_best[field], value)
        triple_rows_output.append({
            "case": case, "middle_triple_id": triple_id,
            "middle_intervals": ";".join(f"{path}={start}-{end}" for path, start, end in middle_key),
            "middle_contexts": "NOT_MATERIALIZED", "bridge_delta_pairs": len(delta_envelopes),
            "best_optimistic_deficit": triple_best["deficit"] if triple_best["deficit"] is not None else "NONE",
            "best_optimistic_span_lb": triple_best["span_lb"] if triple_best["span_lb"] is not None else "NONE",
            "best_cross_root_outward_lb": triple_best["outward_lb"] if triple_best["outward_lb"] is not None else "NONE",
            "best_cross_root_inward_lb": triple_best["inward_lb"] if triple_best["inward_lb"] is not None else "NONE",
        })
    order_output = []
    for index, row in sorted(order_rows.items()):
        order_output.append({
            **row,
            "path_lengths": ";".join(f"{name}={lengths[name]}" for name in lengths),
            **{field: ("NONE" if row[field] is None else row[field]) for field in (
                "minimum_optimistic_deficit", "minimum_optimistic_span", "best_optimistic_span_lb",
                "best_cross_root_outward_lb", "best_cross_root_inward_lb")},
        })
    write_csv(output_dir / f"{case}_order_prescan.csv", order_output)
    write_csv(output_dir / f"{case}_middle_triple_prescan.csv", triple_rows_output)
    def count_flag(field: str) -> int:
        return sum(bool(row[field]) for row in order_rows.values())
    min_deficit = min((row["minimum_optimistic_deficit"] for row in order_rows.values() if row["minimum_optimistic_deficit"] is not None), default=None)
    best_span_lb = min((row["best_optimistic_span_lb"] for row in order_rows.values() if row["best_optimistic_span_lb"] is not None), default=None)
    best_outward = min((row["best_cross_root_outward_lb"] for row in order_rows.values() if row["best_cross_root_outward_lb"] is not None), default=None)
    best_inward = min((row["best_cross_root_inward_lb"] for row in order_rows.values() if row["best_cross_root_inward_lb"] is not None), default=None)
    predicted_class = "A_OPTIMISTIC_ONLY" if count_flag("optimistic_left_containment") or count_flag("optimistic_right_containment") else ("B" if best_outward is not None and best_outward <= EDGE_COUNT else "C")
    result = {
        "case": case, "cache_version": CACHE_VERSION, "prescan_level": "L0_BRIDGE_ENVELOPE",
        "path_lengths": lengths, "active_pattern": metadata.get("active_pattern", "UNKNOWN") if metadata else "UNKNOWN",
        "rho": int(metadata["rho"]) if metadata and metadata.get("rho", "").isdigit() else "UNKNOWN",
        "interval_orders": len(orders), "middle_triples": len(triple_rows),
        "middle_contexts": "NOT_MATERIALIZED", "bridge_delta_pairs_total": delta_support_total,
        "contexts_with_optimistic_containment": "NOT_MATERIALIZED",
        "contexts_with_exact_containment": "NOT_RUN",
        "orders_optimistic_left_containment": count_flag("optimistic_left_containment"),
        "orders_optimistic_right_containment": count_flag("optimistic_right_containment"),
        "orders_optimistic_any_containment": sum(bool(row["optimistic_left_containment"] or row["optimistic_right_containment"]) for row in order_rows.values()),
        "orders_exact_any_containment": "NOT_RUN",
        "minimum_optimistic_containment_deficit": min_deficit if min_deficit is not None else "NONE",
        "best_optimistic_span_lb": best_span_lb if best_span_lb is not None else "NONE",
        "best_cross_root_outward_lb": best_outward if best_outward is not None else "NONE",
        "best_cross_root_inward_lb": best_inward if best_inward is not None else "NONE",
        "predicted_class": predicted_class, "prediction_basis": "L0 bridge-envelope relaxation; exact containment not run",
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "prescan_scope": "coarse interval-level prescan; not a Gate-1 decision",
    }
    return result, order_output, triple_rows_output

    order_output = []
    for index, row in sorted(order_rows.items()):
        order_output.append({
            **row,
            "path_lengths": ";".join(f"{name}={lengths[name]}" for name in lengths),
            "minimum_optimistic_deficit": "NONE" if row["minimum_optimistic_deficit"] is None else row["minimum_optimistic_deficit"],
            "minimum_optimistic_span": "NONE" if row["minimum_optimistic_span"] is None else row["minimum_optimistic_span"],
            "best_optimistic_span_lb": "NONE" if row["best_optimistic_span_lb"] is None else row["best_optimistic_span_lb"],
            "best_cross_root_outward_lb": "NONE" if row["best_cross_root_outward_lb"] is None else row["best_cross_root_outward_lb"],
            "best_cross_root_inward_lb": "NONE" if row["best_cross_root_inward_lb"] is None else row["best_cross_root_inward_lb"],
        })
    write_csv(output_dir / f"{case}_order_prescan.csv", order_output)
    write_csv(output_dir / f"{case}_context_prescan.csv", context_rows)

    def count_flag(field: str) -> int:
        return sum(bool(row[field]) for row in order_rows.values())

    min_deficit = min((row["minimum_optimistic_deficit"] for row in order_rows.values() if row["minimum_optimistic_deficit"] is not None), default=None)
    best_span_lb = min((row["best_optimistic_span_lb"] for row in order_rows.values() if row["best_optimistic_span_lb"] is not None), default=None)
    best_outward = min((row["best_cross_root_outward_lb"] for row in order_rows.values() if row["best_cross_root_outward_lb"] is not None), default=None)
    best_inward = min((row["best_cross_root_inward_lb"] for row in order_rows.values() if row["best_cross_root_inward_lb"] is not None), default=None)
    exact_any = count_flag("exact_left_containment") + count_flag("exact_right_containment")
    if count_flag("exact_left_containment") or count_flag("exact_right_containment"):
        predicted_class = "A"
    elif best_outward is not None and best_outward <= EDGE_COUNT:
        predicted_class = "B"
    else:
        predicted_class = "C"
    result = {
        "case": case,
        "cache_version": CACHE_VERSION,
        "path_lengths": lengths,
        "active_pattern": metadata.get("active_pattern", "UNKNOWN") if metadata else "UNKNOWN",
        "rho": int(metadata["rho"]) if metadata and metadata.get("rho", "").isdigit() else "UNKNOWN",
        "interval_orders": len(orders),
        "middle_triples": len(triple_rows),
        "middle_contexts": context_total,
        "unique_residual_assignments": residual_assignment_total,
        "contexts_with_optimistic_containment": len(context_opt_zero),
        "contexts_with_exact_containment": len(context_exact_zero),
        "orders_optimistic_left_containment": count_flag("optimistic_left_containment"),
        "orders_optimistic_right_containment": count_flag("optimistic_right_containment"),
        "orders_optimistic_any_containment": sum(
            bool(row["optimistic_left_containment"] or row["optimistic_right_containment"])
            for row in order_rows.values()
        ),
        "orders_exact_left_containment": count_flag("exact_left_containment"),
        "orders_exact_right_containment": count_flag("exact_right_containment"),
        "orders_exact_any_containment": sum(
            bool(row["exact_left_containment"] or row["exact_right_containment"])
            for row in order_rows.values()
        ),
        "minimum_optimistic_containment_deficit": min_deficit if min_deficit is not None else "NONE",
        "best_optimistic_span_lb": best_span_lb if best_span_lb is not None else "NONE",
        "best_cross_root_outward_lb": best_outward if best_outward is not None else "NONE",
        "best_cross_root_inward_lb": best_inward if best_inward is not None else "NONE",
        "predicted_class": predicted_class,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "context_stats": {
            "raw_contexts": middle_stats_totals.get("raw_contexts", 0),
            "totals": dict(middle_stats_totals),
        },
        "prescan_scope": "Level-1 envelope prescan plus exact zero-deficit containment checks; not Gate-1 decision.",
    }
    return result, order_output, context_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("results/edge63_containment_frontier_test"))
    parser.add_argument("--repair-cover-csv", type=Path, default=Path("results/edge63_root_packing/repair_cover_numbers.csv"))
    parser.add_argument("--case", action="append", dest="cases", default=None)
    parser.add_argument("--coarse-only", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metadata = read_repair_metadata(args.repair_cover_csv)
    cases = tuple(args.cases) if args.cases else DEFAULT_CASES
    summaries = []
    for case in cases:
        print(f"PRESCAN_START {case}", flush=True)
        runner = prescan_case_coarse if args.coarse_only else prescan_case
        result, _order_rows, _context_rows = runner(case, metadata.get(case), args.output_dir)
        summaries.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
    write_csv(args.output_dir / "remaining_three_prescan.csv", summaries)
    (args.output_dir / "prescan_summary.json").write_text(json.dumps({
        "cache_version": CACHE_VERSION,
        "cases": summaries,
        "full_graceful_search_started": False,
        "two_interval_entered": False,
        "main_log_modified": False,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
