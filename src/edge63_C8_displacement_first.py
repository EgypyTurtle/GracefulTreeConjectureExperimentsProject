"""C8 displacement-first search for exactly one split terminal path.

This is Gate 2A for terminal split slots.  The three bridge/middle paths keep
the trusted C7 middle-context generator.  Only one terminal path is allowed
to use two consecutive difference runs, represented by C8.LevelB.v1 states.
The search reports a bounded run as ``UNRESOLVED_RESOURCE`` and never turns a
partial run into an exhaustive negative result.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_C8_allocations import (  # noqa: E402
    ALLOCATION_DEDUP_VERSION,
    LANGUAGE_VERSION,
    block_texts,
    iter_allocations,
)
from edge63_displacement_first_compact import (  # noqa: E402
    EDGE_COUNT,
    MIDDLE_PATHS,
    PATHS,
    TERMINAL_PATHS,
    _label_mask,
    build_layout,
    middle_contexts,
    path_lengths,
)
from edge63_structure_analysis import parse_case  # noqa: E402
from edge63_two_run_local_states import RunState, options_for_runs  # noqa: E402


CACHE_VERSION = "corrected.v2"
C7_LANGUAGE = "complete Level-B single-run behavior"
# Gate 2A currently implements side-terminal splits.  A middle-path split
# changes the middle-context generator and needs a separate exact pipeline;
# keeping it out of this runner avoids silently dropping the second run.
SPLIT_SLOTS = tuple(path for path in TERMINAL_PATHS if path != "middle_leaf")


@dataclass(frozen=True)
class PairState:
    state_id: int
    private: tuple[int, ...]
    mask: int
    min_value: int
    max_value: int
    state_a: RunState
    state_b: RunState


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    for row in rows[1:]:
        for field in row:
            if field not in fieldnames:
                fieldnames.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def values_for_case(case: str) -> tuple[int, ...]:
    parsed = parse_case(case)
    if parsed is None or parsed[1] != EDGE_COUNT:
        raise ValueError(case)
    return parsed[2]


def mask_shift(mask: int, shift: int) -> int:
    return mask << shift if shift >= 0 else mask >> (-shift)


def mask_for(values: tuple[int, ...]) -> int:
    return _label_mask(values)


PAIR_CACHE: dict[tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]], tuple[PairState, ...]] = {}


def terminal_pair_states(
    intervals_a: tuple[tuple[int, int], ...],
    intervals_b: tuple[tuple[int, int], ...],
) -> tuple[PairState, ...]:
    key = (intervals_a, intervals_b)
    if key in PAIR_CACHE:
        return PAIR_CACHE[key]
    options_a = options_for_runs(intervals_a, "terminal")
    options_b = options_for_runs(intervals_b, "terminal")
    representatives: dict[tuple[int, ...], PairState] = {}
    expected = sum(end - start + 1 for start, end in intervals_a)
    expected += sum(end - start + 1 for start, end in intervals_b)
    for state_a, state_b in itertools.product(options_a, options_b):
        private = tuple(sorted((*state_a.private, *state_b.private)))
        if 0 in private or len(set(private)) != len(private):
            continue
        if len(private) != expected:
            raise AssertionError("terminal pair cardinality regression")
        low = min((0, *private))
        high = max((0, *private))
        if high - low > EDGE_COUNT:
            continue
        representatives.setdefault(
            private,
            PairState(
                state_id=len(representatives),
                private=private,
                mask=mask_for(private),
                min_value=low,
                max_value=high,
                state_a=state_a,
                state_b=state_b,
            ),
        )
    result = tuple(representatives.values())
    PAIR_CACHE[key] = result
    return result


def allocation_keys(allocation: dict[str, object]) -> tuple[tuple, tuple]:
    blocks = allocation["blocks"]
    middle_key = tuple((path, blocks[path][0][0], blocks[path][0][1]) for path in MIDDLE_PATHS)
    residual_key = tuple((path, tuple(blocks[path])) for path in TERMINAL_PATHS)
    return middle_key, residual_key


def build_allocation_groups(values: tuple[int, ...], split_slot: str):
    groups: dict[tuple, dict[tuple, tuple[str, ...]]] = defaultdict(dict)
    allocation_count = 0
    for allocation in iter_allocations(values, split_slot):
        middle_key, residual_key = allocation_keys(allocation)
        run_entries = []
        for path, intervals in allocation["blocks"].items():
            for index, interval in enumerate(intervals, 1):
                token = path if len(intervals) == 1 else f"{path}__run_{index}"
                run_entries.append((interval[0], token))
        order = tuple(token for _start, token in sorted(run_entries))
        groups[middle_key].setdefault(residual_key, order)
        allocation_count += 1
    return groups, allocation_count


def interval_texts(intervals: tuple[tuple[int, int], ...]) -> str:
    return ";".join(f"{start}-{end}" for start, end in intervals)


def serialize_state(state: RunState) -> dict[str, object]:
    return {
        "offsets": list(state.offsets),
        "private": list(state.private),
        "endpoint": state.endpoint,
        "difference_order": list(state.difference_order),
        "sign_word": list(state.sign_word),
        "run_intervals": [list(interval) for interval in state.run_intervals],
        "order_mode": state.order_mode,
    }


def build_relative_labels(
    values: tuple[int, ...],
    context: dict[str, object],
    left_pair: PairState,
    right_pair: PairState,
    delta_left: int,
    delta_right: int,
) -> tuple[list[int], dict[int, int]]:
    layout = build_layout(values)
    relative: dict[int, int] = {}
    roots = (-delta_left, 0, delta_right)
    relative[layout["left_bridge"][0]] = roots[0]
    relative[layout["left_bridge"][-1]] = roots[1]
    relative[layout["right_bridge"][0]] = roots[1]
    relative[layout["right_bridge"][-1]] = roots[2]

    bridge = context["bridge"]
    for index, vertex in enumerate(layout["left_bridge"][1:-1], 1):
        relative[vertex] = bridge.left_offsets[index] - delta_left
    for index, vertex in enumerate(layout["right_bridge"][1:-1], 1):
        relative[vertex] = bridge.right_offsets[index]

    central = context["central"]
    for index, vertex in enumerate(layout["middle_leaf"][1:], 1):
        relative[vertex] = central.offsets[index]

    for path, state, shift in (
        ("left_leaf_1", left_pair.state_a, -delta_left),
        ("left_leaf_2", left_pair.state_b, -delta_left),
        ("right_leaf_1", right_pair.state_a, delta_right),
        ("right_leaf_2", right_pair.state_b, delta_right),
    ):
        vertices = layout[path]
        if len(vertices) != len(state.offsets):
            raise AssertionError(f"path/state length mismatch for {path}")
        for vertex, offset in zip(vertices, state.offsets):
            candidate = offset + shift
            if vertex in relative and relative[vertex] != candidate:
                raise AssertionError("shared vertex received two relative labels")
            relative[vertex] = candidate
    if len(relative) != EDGE_COUNT + 1 or len(set(relative.values())) != EDGE_COUNT + 1:
        raise AssertionError("certificate relative offsets are not injective")
    low = min(relative.values())
    labels = [relative[index] - low for index in range(EDGE_COUNT + 1)]
    return labels, relative


def verify_c8_labeling(values: tuple[int, ...], allocation: dict[str, object], labels: list[int]) -> dict[str, object]:
    layout = build_layout(values)
    if len(labels) != EDGE_COUNT + 1 or sorted(labels) != list(range(EDGE_COUNT + 1)):
        return {"verified": False, "reason": "labels_not_0_63"}
    observed = {}
    all_differences = []
    for path, intervals in allocation["blocks"].items():
        differences = sorted(abs(labels[u] - labels[v]) for u, v in zip(layout[path], layout[path][1:]))
        expected = sorted(value for start, end in intervals for value in range(start, end + 1))
        observed[path] = differences
        all_differences.extend(differences)
        if differences != expected:
            return {"verified": False, "reason": f"difference_block_mismatch:{path}"}
    if sorted(all_differences) != list(range(1, EDGE_COUNT + 1)):
        return {"verified": False, "reason": "global_difference_mismatch"}
    return {"verified": True, "path_differences": observed}


def search_split_slot(case: str, split_slot: str, output_dir: Path, time_limit: float | None) -> dict[str, object]:
    values = values_for_case(case)
    lengths = path_lengths(values)
    if split_slot not in SPLIT_SLOTS:
        raise ValueError(f"terminal split only in Gate 2A: {split_slot}")
    started = time.time()
    groups, raw_allocations = build_allocation_groups(values, split_slot)
    middle_cache: dict[tuple, tuple[dict[str, object], ...]] = {}
    pair_cache_stats_start = len(PAIR_CACHE)
    counts = {
        "middle_triples": 0,
        "middle_contexts": 0,
        "residual_assignments": 0,
        "allocations_covered": 0,
        "contexts_with_left": 0,
        "contexts_with_right": 0,
        "compatible_left_states": 0,
        "compatible_right_states": 0,
        "compatible_terminal_pairs": 0,
        "span_gt63_compatible_pairs": 0,
    }
    min_span: int | None = None
    min_witness: dict[str, object] | None = None
    complete = True
    certificate = None
    processed_middle_keys = 0

    middle_items = sorted(groups.items(), key=lambda item: (len(item[1]), item[0]))
    for middle_key, residuals in middle_items:
        if time_limit is not None and time.time() - started >= time_limit:
            complete = False
            break
        processed_middle_keys += 1
        counts["middle_triples"] += 1
        left_block = middle_key[0]
        central_block = middle_key[1]
        right_block = middle_key[2]
        contexts = middle_cache.get(middle_key)
        if contexts is None:
            generated, _stats = middle_contexts(
                left_block[1], left_block[2] - left_block[1] + 1,
                central_block[1], central_block[2] - central_block[1] + 1,
                right_block[1], right_block[2] - right_block[1] + 1,
                "B",
            )
            contexts = tuple(generated)
            middle_cache[middle_key] = contexts
        counts["middle_contexts"] += len(contexts)
        for context in contexts:
            if time_limit is not None and time.time() - started >= time_limit:
                complete = False
                break
            delta_left = int(context["delta_left"])
            delta_right = int(context["delta_right"])
            middle_values = tuple(context["all_values"])
            middle_mask = mask_for(middle_values)
            middle_min = min(middle_values)
            middle_max = max(middle_values)
            for residual_key, run_order in residuals.items():
                if time_limit is not None and time.time() - started >= time_limit:
                    complete = False
                    break
                counts["residual_assignments"] += 1
                block_map = dict(residual_key)
                left_intervals_a = block_map["left_leaf_1"]
                left_intervals_b = block_map["left_leaf_2"]
                right_intervals_a = block_map["right_leaf_1"]
                right_intervals_b = block_map["right_leaf_2"]
                left_states = terminal_pair_states(left_intervals_a, left_intervals_b)
                right_states = terminal_pair_states(right_intervals_a, right_intervals_b)
                left_compatible: list[tuple[PairState, int, int, int]] = []
                right_compatible: list[tuple[PairState, int, int, int]] = []
                for state in left_states:
                    shifted_mask = mask_shift(state.mask, -delta_left)
                    if shifted_mask & middle_mask:
                        continue
                    low = min(middle_min, state.min_value - delta_left)
                    high = max(middle_max, state.max_value - delta_left)
                    if high - low > EDGE_COUNT:
                        continue
                    left_compatible.append((state, shifted_mask, low, high))
                for state in right_states:
                    shifted_mask = mask_shift(state.mask, delta_right)
                    if shifted_mask & middle_mask:
                        continue
                    low = min(middle_min, state.min_value + delta_right)
                    high = max(middle_max, state.max_value + delta_right)
                    if high - low > EDGE_COUNT:
                        continue
                    right_compatible.append((state, shifted_mask, low, high))
                if left_compatible:
                    counts["contexts_with_left"] += 1
                if right_compatible:
                    counts["contexts_with_right"] += 1
                counts["compatible_left_states"] += len(left_compatible)
                counts["compatible_right_states"] += len(right_compatible)
                for left_state, left_mask, left_low, left_high in left_compatible:
                    for right_state, right_mask, right_low, right_high in right_compatible:
                        if left_mask & right_mask:
                            continue
                        counts["compatible_terminal_pairs"] += 1
                        span = max(middle_max, left_high, right_high) - min(middle_min, left_low, right_low)
                        if span > EDGE_COUNT:
                            counts["span_gt63_compatible_pairs"] += 1
                        if min_span is None or span < min_span:
                            min_span = span
                            min_witness = {
                                "middle_key": middle_key,
                                "context_id": int(context["context_id"]),
                                "residual_key": residual_key,
                                "run_order": run_order,
                                "split_lengths": tuple(
                                    end - start + 1 for start, end in block_map[split_slot]
                                ),
                                "delta_left": delta_left,
                                "delta_right": delta_right,
                                "D13": delta_left + delta_right,
                                "span": span,
                                "left_state_id": left_state.state_id,
                                "right_state_id": right_state.state_id,
                            }
                        if span <= EDGE_COUNT:
                            allocation = {
                                "split_slot": split_slot,
                                "split_lengths": tuple(end - start + 1 for start, end in block_map[split_slot]),
                                "run_order": run_order,
                                "blocks": block_map,
                            }
                            labels, relative = build_relative_labels(
                                values, context, left_state, right_state, delta_left, delta_right
                            )
                            verification = verify_c8_labeling(values, allocation, labels)
                            if not verification["verified"]:
                                raise AssertionError(verification)
                            certificate = {
                                "certificate_version": "C8.LevelB.v1",
                                "cache_version": CACHE_VERSION,
                                "case": case,
                                "split_slot": split_slot,
                                "split_lengths": list(allocation["split_lengths"]),
                                "run_order": list(run_order),
                                "blocks": {path: [list(interval) for interval in intervals] for path, intervals in block_map.items()},
                                "middle_context": {
                                    "context_id": int(context["context_id"]),
                                    "delta_left": delta_left,
                                    "delta_right": delta_right,
                                    "roots_middle_frame": [-delta_left, 0, delta_right],
                                    "middle_values": list(middle_values),
                                    "middle_min": middle_min,
                                    "middle_max": middle_max,
                                    "bridge_left_offsets": list(context["bridge"].left_offsets),
                                    "bridge_right_offsets": list(context["bridge"].right_offsets),
                                    "central_offsets": list(context["central"].offsets),
                                },
                                "left_pair": {
                                    "private_middle_frame": [value - delta_left for value in left_state.private],
                                    "state_a": serialize_state(left_state.state_a),
                                    "state_b": serialize_state(left_state.state_b),
                                },
                                "right_pair": {
                                    "private_middle_frame": [value + delta_right for value in right_state.private],
                                    "state_a": serialize_state(right_state.state_a),
                                    "state_b": serialize_state(right_state.state_b),
                                },
                                "relative_offsets": {str(vertex): offset for vertex, offset in relative.items()},
                                "labels": labels,
                                "span": span,
                                "verification": verification,
                            }
                            break
                    if certificate is not None:
                        break
                if certificate is not None:
                    break
            if certificate is not None or not complete:
                break
        if certificate is not None or not complete:
            break

    if certificate is not None:
        status = "SAT_VERIFIED"
        (output_dir / "verified_constructions").mkdir(parents=True, exist_ok=True)
        (output_dir / "verified_constructions" / f"{split_slot}.json").write_text(
            json.dumps(certificate, indent=2), encoding="utf-8"
        )
    elif not complete:
        status = "UNRESOLVED_RESOURCE"
    elif counts["compatible_terminal_pairs"]:
        status = "COMPATIBLE_SPAN_GT63"
    else:
        status = "UNSAT_EXHAUSTIVE_C8_LEVELB"

    elapsed = time.time() - started
    row = {
        "case": case,
        "split_slot": split_slot,
        "status": status,
        "local_language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "global_enumeration_complete": complete,
        "raw_C8_allocations": raw_allocations,
        "middle_triples_processed": processed_middle_keys,
        "middle_triples_total": len(groups),
        "middle_contexts_processed": counts["middle_contexts"],
        "residual_assignments_processed": counts["residual_assignments"],
        "contexts_with_left": counts["contexts_with_left"],
        "contexts_with_right": counts["contexts_with_right"],
        "compatible_left_states": counts["compatible_left_states"],
        "compatible_right_states": counts["compatible_right_states"],
        "compatible_terminal_pairs": counts["compatible_terminal_pairs"],
        "compatible_span_gt63_pairs": counts["span_gt63_compatible_pairs"],
        "minimum_compatible_span": min_span if min_span is not None else "NONE",
        "minimum_witness": json.dumps(min_witness, separators=(",", ":")) if min_witness else "NONE",
        "pair_cache_entries_before": pair_cache_stats_start,
        "pair_cache_entries_after": len(PAIR_CACHE),
        "elapsed_seconds": round(elapsed, 3),
    }
    result_path = output_dir / "split_slot_results.csv"
    previous_rows = []
    if result_path.exists() and result_path.stat().st_size:
        with result_path.open(newline="", encoding="utf-8") as handle:
            previous_rows = [old for old in csv.DictReader(handle)
                             if not (old.get("case") == case and old.get("split_slot") == split_slot)]
    write_csv(result_path, previous_rows + [row])
    repair_row = {
        "case": case,
        "split_slot": split_slot,
        "status": status,
        "old_C7_compatibility": "Tree1/Tree3 baseline supplied externally",
        "C8_compatible_terminal_pairs": counts["compatible_terminal_pairs"],
        "minimum_compatible_span": min_span if min_span is not None else "NONE",
        "escape_certificate": "verified_constructions/" + split_slot + ".json" if certificate else "NONE",
    }
    repair_path = output_dir / "compatibility_repairs.csv"
    previous_repairs = []
    if repair_path.exists() and repair_path.stat().st_size:
        with repair_path.open(newline="", encoding="utf-8") as handle:
            previous_repairs = [old for old in csv.DictReader(handle)
                                if not (old.get("case") == case and old.get("split_slot") == split_slot)]
    write_csv(repair_path, previous_repairs + [repair_row])
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--split-slot", required=True, choices=SPLIT_SLOTS)
    parser.add_argument("--output-dir", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--time-limit", type=float, default=None)
    args = parser.parse_args()
    case_dir = args.output_dir / ("tree1_C8" if "20-9-4-4" in args.case else "tree3_C8")
    case_dir.mkdir(parents=True, exist_ok=True)
    row = search_split_slot(args.case, args.split_slot, case_dir, args.time_limit)
    report_path = case_dir / "report.md"
    previous_report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    section = (
        f"# C8 terminal split\n\nCase `{args.case}`; split slot `{args.split_slot}`; "
        f"language `{LANGUAGE_VERSION}`; status `{row['status']}`.\n\n"
        "This is exactly one split path, with all other paths single-run. "
        "A bounded run remains UNRESOLVED_RESOURCE.\n"
    )
    report_path.write_text((previous_report + "\n" + section).strip() + "\n", encoding="utf-8")
    print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
