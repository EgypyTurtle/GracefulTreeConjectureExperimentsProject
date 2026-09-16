#!/usr/bin/env python3
"""Context-conditioned lazy oracle for one C8 terminal two-run path.

The oracle enumerates exactly the declared C8.LevelB.v1 order/sign family,
but stops a partial realization as soon as its private offsets collide with
the occupied query footprint or its current span already exceeds 63.  It is
not a new local language: the differential test compares its behavior family
with the existing full-table generator.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_C8_two_run_cache import TerminalPairState  # noqa: E402
from edge63_two_run_local_states import (  # noqa: E402
    RunState,
    _private_for_role,
    _sign_words,
    _relative_offsets,
    two_run_orders,
)
from edge63_displacement_first_compact import EDGE_COUNT, _label_mask  # noqa: E402


LANGUAGE_VERSION = "C8.LevelB.v1"
ORACLE_VERSION = "lazy-terminal-oracle.v1:prefix-collision-span"


@dataclass(frozen=True)
class LazyStats:
    raw_order_sign_branches: int
    raw_prefix_steps: int
    local_invalid_branches: int
    occupied_pruned_branches: int
    span_pruned_branches: int
    output_states: int


def _mask(values: tuple[int, ...]) -> int:
    return _label_mask(values)


def _fits_query(
    offsets: tuple[int, ...],
    occupied_mask: int,
    shift: int,
    middle_min: int,
    middle_max: int,
) -> tuple[bool, str]:
    private = tuple(offsets[1:])
    if _mask(tuple(value + shift for value in private)) & occupied_mask:
        return False, "occupied"
    # The root is already accounted for in most middle contexts, but keeping
    # it in the local envelope makes the oracle exact for standalone queries
    # as well.  Collision checks intentionally use private offsets only.
    low = min(middle_min, min(offsets) + shift)
    high = max(middle_max, max(offsets) + shift)
    if high - low > EDGE_COUNT:
        return False, "span"
    return True, "ok"


def query_two_run_options(
    intervals: tuple[tuple[int, int], ...],
    role: str,
    *,
    occupied_mask: int = 0,
    shift: int = 0,
    middle_min: int = -EDGE_COUNT,
    middle_max: int = EDGE_COUNT,
    span_mode: bool = True,
) -> tuple[tuple[RunState, ...], LazyStats]:
    """Return exactly the full-table states satisfying one local query."""
    if len(intervals) != 2:
        raise ValueError("lazy oracle is for a two-run interval pair")
    (start_a, end_a), (start_b, end_b) = intervals
    length_a = end_a - start_a + 1
    length_b = end_b - start_b + 1
    canonical: dict[tuple[int, ...], tuple[tuple[int, ...], str, tuple[int, ...]]] = {}
    raw_branches = 0
    prefix_steps = 0
    local_invalid = 0
    occupied_pruned = 0
    span_pruned = 0

    # Query pruning is monotone.  A private offset can never disappear from
    # a completed state, and a span can never shrink after adding vertices.
    for order, order_mode in two_run_orders(start_a, length_a, start_b, length_b):
        for signs in _sign_words(length_a + length_b):
            raw_branches += 1
            current = 0
            offsets = [0]
            rejected = False
            for difference, sign in zip(order, signs):
                current += sign * difference
                offsets.append(current)
                prefix_steps += 1
                if len(set(offsets)) != len(offsets):
                    local_invalid += 1
                    rejected = True
                    break
                if span_mode:
                    okay, reason = _fits_query(tuple(offsets), occupied_mask, shift, middle_min, middle_max)
                    if not okay:
                        if reason == "occupied":
                            occupied_pruned += 1
                        else:
                            span_pruned += 1
                        rejected = True
                        break
            if rejected:
                continue
            offsets_tuple = tuple(offsets)
            if max(offsets_tuple) - min(offsets_tuple) > EDGE_COUNT:
                span_pruned += 1
                continue
            key = min(offsets_tuple, tuple(-value for value in offsets_tuple))
            stored_signs = signs if key == offsets_tuple else tuple(-value for value in signs)
            canonical.setdefault(key, (order, order_mode, stored_signs))

    representatives: dict[tuple[tuple[int, ...], int | None], RunState] = {}
    for key in sorted(canonical, key=lambda row: (max(row) - min(row), row)):
        orientations = (key,) if key == tuple(-value for value in key) else (key, tuple(-value for value in key))
        order, order_mode, signs = canonical[key]
        for offsets in orientations:
            if span_mode:
                okay, reason = _fits_query(offsets, occupied_mask, shift, middle_min, middle_max)
                if not okay:
                    continue
            private = tuple(sorted(_private_for_role(offsets, role)))
            endpoint = None if role == "terminal" else offsets[-1]
            if len(set(private)) != len(private):
                continue
            representatives.setdefault(
                (private, endpoint),
                RunState(
                    state_id=len(representatives),
                    offsets=offsets,
                    private=private,
                    endpoint=endpoint,
                    min_value=min((0, *private)),
                    max_value=max((0, *private)),
                    difference_order=order,
                    sign_word=signs,
                    run_intervals=intervals,
                    order_mode=order_mode,
                ),
            )
    states = tuple(representatives.values())
    return states, LazyStats(
        raw_order_sign_branches=raw_branches,
        raw_prefix_steps=prefix_steps,
        local_invalid_branches=local_invalid,
        occupied_pruned_branches=occupied_pruned,
        span_pruned_branches=span_pruned,
        output_states=len(states),
    )


def state_geometry(state: RunState) -> tuple[tuple[int, ...], int, int]:
    return state.private, state.min_value, state.max_value


def query_terminal_pair_states(
    intervals_a: tuple[tuple[int, int], ...],
    intervals_b: tuple[tuple[int, int], ...],
    *,
    occupied_mask: int,
    left_shift: int,
    middle_min: int,
    middle_max: int,
) -> tuple[tuple[TerminalPairState, ...], dict[str, int]]:
    """Lazily build only left terminal-pair states surviving a middle query."""
    from edge63_two_run_local_states import options_for_runs, single_run_options  # local import avoids a cycle

    if len(intervals_b) != 2:
        raise ValueError("left_leaf_2 must be the split path")
    states_b, stats = query_two_run_options(
        intervals_b,
        "terminal",
        occupied_mask=occupied_mask,
        shift=left_shift,
        middle_min=middle_min,
        middle_max=middle_max,
    )
    states_a = options_for_runs(intervals_a, "terminal")
    expected = sum(end - start + 1 for start, end in intervals_a + intervals_b)
    representatives: dict[tuple[int, ...], TerminalPairState] = {}
    pair_attempts = 0
    pair_rejected = 0
    for state_a in states_a:
        if _mask(tuple(value + left_shift for value in state_a.private)) & occupied_mask:
            continue
        for state_b in states_b:
            pair_attempts += 1
            private = tuple(sorted((*state_a.private, *state_b.private)))
            if 0 in private or len(set(private)) != len(private):
                pair_rejected += 1
                continue
            if len(private) != expected:
                raise AssertionError("lazy terminal pair cardinality regression")
            low = min((0, *private)) + left_shift
            high = max((0, *private)) + left_shift
            low = min(middle_min, low)
            high = max(middle_max, high)
            if high - low > EDGE_COUNT:
                pair_rejected += 1
                continue
            representatives.setdefault(
                private,
                TerminalPairState(
                    state_id=len(representatives),
                    private=private,
                    mask=_mask(private),
                    min_value=min((0, *private)),
                    max_value=max((0, *private)),
                    state_a=state_a,
                    state_b=state_b,
                ),
            )
    return tuple(representatives.values()), {
        "local_raw_order_sign_branches": stats.raw_order_sign_branches,
        "local_raw_prefix_steps": stats.raw_prefix_steps,
        "local_occupied_pruned_branches": stats.occupied_pruned_branches,
        "local_span_pruned_branches": stats.span_pruned_branches,
        "local_output_states": stats.output_states,
        "pair_attempts": pair_attempts,
        "pair_rejected": pair_rejected,
        "pair_output_states": len(representatives),
    }


def compare_query(
    intervals: tuple[tuple[int, int], ...],
    occupied_values: tuple[int, ...],
    shift: int,
    middle_min: int,
    middle_max: int,
) -> dict[str, object]:
    from edge63_two_run_local_states import options_for_runs

    occupied_mask = _mask(occupied_values)
    full = options_for_runs(intervals, "terminal")
    full_filtered = tuple(
        state for state in full
        if not (_mask(tuple(value + shift for value in state.private)) & occupied_mask)
        and max(middle_max, state.max_value + shift) - min(middle_min, state.min_value + shift) <= EDGE_COUNT
    )
    lazy, stats = query_two_run_options(
        intervals,
        "terminal",
        occupied_mask=occupied_mask,
        shift=shift,
        middle_min=middle_min,
        middle_max=middle_max,
    )
    full_geometry = {state_geometry(state) for state in full_filtered}
    lazy_geometry = {state_geometry(state) for state in lazy}
    return {
        "intervals": [list(interval) for interval in intervals],
        "occupied_values": list(occupied_values),
        "shift": shift,
        "middle_min": middle_min,
        "middle_max": middle_max,
        "full_count": len(full_filtered),
        "lazy_count": len(lazy),
        "geometry_equal": full_geometry == lazy_geometry,
        "full_only": len(full_geometry - lazy_geometry),
        "lazy_only": len(lazy_geometry - full_geometry),
        "lazy_stats": stats.__dict__,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/tree1_C8/left_leaf_2_exact_v3/lazy_oracle_v1"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [
        (((1, 1), (3, 3)), (), 0, 0, 0),
        (((1, 2), (5, 6)), (0, 1, -1), -4, -10, 10),
        (((4, 6), (20, 21)), (2, -2, 7), -9, -15, 15),
        (((7, 9), (31, 34)), (0, 3, -3, 5), -12, -20, 20),
    ]
    tests = [compare_query(*case) for case in cases]
    payload = {
        "oracle_version": ORACLE_VERSION,
        "two_run_language": LANGUAGE_VERSION,
        "tests": tests,
        "status": "PASS" if all(test["geometry_equal"] for test in tests) else "FAIL",
    }
    (args.output / "lazy_oracle_differential_tests.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (args.output / "lazy_oracle_performance.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["intervals", "full_count", "lazy_count", "geometry_equal", "raw_branches", "prefix_steps", "occupied_pruned", "span_pruned"])
        writer.writeheader()
        for test in tests:
            stats = test["lazy_stats"]
            writer.writerow({
                "intervals": json.dumps(test["intervals"]),
                "full_count": test["full_count"],
                "lazy_count": test["lazy_count"],
                "geometry_equal": test["geometry_equal"],
                "raw_branches": stats["raw_order_sign_branches"],
                "prefix_steps": stats["raw_prefix_steps"],
                "occupied_pruned": stats["occupied_pruned_branches"],
                "span_pruned": stats["span_pruned_branches"],
            })
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
