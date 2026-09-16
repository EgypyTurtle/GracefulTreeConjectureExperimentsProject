"""Finite local states for the C8 two-run construction language.

``C8.LevelB.v1`` is deliberately explicit and finite.  Each difference run
uses the existing Level-B order family: all permutations through length six,
and the controlled order family for longer runs.  A two-run path uses block
concatenation in either order plus two stable alternating merges.  The sign
language is the existing Level-B bounded-turn family for the total path
length.  This module never claims permutation completeness for longer runs.
"""

from __future__ import annotations

import itertools
from functools import lru_cache
from typing import NamedTuple

from edge63_displacement_first_compact import (
    EDGE_COUNT,
    _controlled_orders,
    _relative_offsets,
    _sign_words,
    compact_options,
)


LANGUAGE_VERSION = "C8.LevelB.v1"
FULL_RUN_PERMUTATION_LIMIT = 6


class RunState(NamedTuple):
    state_id: int
    offsets: tuple[int, ...]
    private: tuple[int, ...]
    endpoint: int | None
    min_value: int
    max_value: int
    difference_order: tuple[int, ...]
    sign_word: tuple[int, ...]
    run_intervals: tuple[tuple[int, int], ...]
    order_mode: str


def _run_orders(start: int, length: int) -> tuple[tuple[int, ...], ...]:
    values = tuple(range(start, start + length))
    if length <= FULL_RUN_PERMUTATION_LIMIT:
        return tuple(itertools.permutations(values))
    return _controlled_orders(start, length, "B")


def _alternating_merge(
    first: tuple[int, ...], second: tuple[int, ...], first_turn: bool
) -> tuple[int, ...]:
    result: list[int] = []
    left = 0
    right = 0
    turn_first = first_turn
    while left < len(first) or right < len(second):
        if turn_first and left < len(first):
            result.append(first[left])
            left += 1
        elif not turn_first and right < len(second):
            result.append(second[right])
            right += 1
        elif left < len(first):
            result.append(first[left])
            left += 1
        else:
            result.append(second[right])
            right += 1
        turn_first = not turn_first
    return tuple(result)


@lru_cache(maxsize=None)
def two_run_orders(
    start_a: int, length_a: int, start_b: int, length_b: int
) -> tuple[tuple[tuple[int, ...], str], ...]:
    """Return the declared finite order family for two disjoint runs."""
    if min(start_a, length_a, start_b, length_b) <= 0:
        raise ValueError("two-run intervals must be positive")
    orders_a = _run_orders(start_a, length_a)
    orders_b = _run_orders(start_b, length_b)
    result: dict[tuple[int, ...], str] = {}
    for order_a, order_b in itertools.product(orders_a, orders_b):
        result.setdefault(order_a + order_b, "block_a_then_b")
        result.setdefault(order_b + order_a, "block_b_then_a")
        result.setdefault(_alternating_merge(order_a, order_b, True), "alternating_a_first")
        result.setdefault(_alternating_merge(order_a, order_b, False), "alternating_b_first")
    return tuple(sorted(result.items(), key=lambda item: (item[1], item[0])))


def _private_for_role(offsets: tuple[int, ...], role: str) -> tuple[int, ...]:
    if role == "terminal":
        return offsets[1:]
    if role == "bridge":
        return offsets[1:-1]
    raise ValueError(role)


@lru_cache(maxsize=None)
def two_run_options(
    start_a: int,
    length_a: int,
    start_b: int,
    length_b: int,
    role: str,
) -> tuple[RunState, ...]:
    """Generate quotient states for one path whose differences use two runs."""
    total_length = length_a + length_b
    canonical: dict[tuple[int, ...], tuple[tuple[int, ...], str, tuple[int, ...]]] = {}
    for order, order_mode in two_run_orders(start_a, length_a, start_b, length_b):
        for signs in _sign_words(total_length):
            offsets = _relative_offsets(order, signs)
            if len(set(offsets)) != len(offsets):
                continue
            if max(offsets) - min(offsets) > EDGE_COUNT:
                continue
            key = min(offsets, tuple(-value for value in offsets))
            stored_signs = signs if key == offsets else tuple(-value for value in signs)
            canonical.setdefault(key, (order, order_mode, stored_signs))

    representatives: dict[tuple[tuple[int, ...], int | None], RunState] = {}
    for key in sorted(canonical, key=lambda row: (max(row) - min(row), row)):
        order, order_mode, signs = canonical[key]
        orientations = (key,) if key == tuple(-value for value in key) else (key, tuple(-value for value in key))
        for offsets in orientations:
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
                    run_intervals=((start_a, start_a + length_a - 1), (start_b, start_b + length_b - 1)),
                    order_mode=order_mode,
                ),
            )
    return tuple(representatives.values())


@lru_cache(maxsize=None)
def single_run_options(start: int, length: int, role: str) -> tuple[RunState, ...]:
    """Adapt the trusted C7 Level-B states to the common RunState shape."""
    result: list[RunState] = []
    for state_id, option in enumerate(compact_options(role, start, length, "B")):
        offsets = tuple(option.offsets)
        private = tuple(sorted(_private_for_role(offsets, role)))
        endpoint = None if role == "terminal" else offsets[-1]
        result.append(
            RunState(
                state_id=state_id,
                offsets=offsets,
                private=private,
                endpoint=endpoint,
                min_value=min((0, *private)),
                max_value=max((0, *private)),
                difference_order=tuple(),
                sign_word=tuple(),
                run_intervals=((start, start + length - 1),),
                order_mode="C7.LevelB",
            )
        )
    return tuple(result)


def options_for_runs(
    intervals: tuple[tuple[int, int], ...], role: str
) -> tuple[RunState, ...]:
    """Return single- or two-run states for a path allocation."""
    if len(intervals) == 1:
        start, end = intervals[0]
        return single_run_options(start, end - start + 1, role)
    if len(intervals) == 2:
        (start_a, end_a), (start_b, end_b) = intervals
        return two_run_options(
            start_a,
            end_a - start_a + 1,
            start_b,
            end_b - start_b + 1,
            role,
        )
    raise ValueError("C8 supports at most two runs per path")


def local_state_summary(intervals: tuple[tuple[int, int], ...], role: str) -> dict[str, object]:
    states = options_for_runs(intervals, role)
    return {
        "language": LANGUAGE_VERSION if len(intervals) == 2 else "C7.LevelB",
        "role": role,
        "intervals": ";".join(f"{a}-{b}" for a, b in intervals),
        "state_count": len(states),
        "min_span": min((state.max_value - state.min_value for state in states), default=0),
        "max_span": max((state.max_value - state.min_value for state in states), default=0),
    }
