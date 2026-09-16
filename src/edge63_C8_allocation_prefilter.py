"""Sound, cheap necessary-condition filters for C8 outer joins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edge63_C8_two_run_cache import PersistentTwoRunCache, TerminalPairState
from edge63_displacement_first_compact import EDGE_COUNT, _label_mask


@dataclass(frozen=True)
class PrefilterCandidate:
    context: dict[str, Any]
    residual_key: tuple
    run_order: tuple[str, ...]
    left_states: tuple[TerminalPairState, ...]
    right_states: tuple[TerminalPairState, ...]
    left_intervals: tuple | None = None
    lazy_left: bool = False


class PrefilterStats:
    def __init__(self) -> None:
        self.values: dict[str, int] = {
            "groups_seen": 0,
            "groups_local_empty": 0,
            "contexts_seen": 0,
            "contexts_middle_span_overflow": 0,
            "residual_assignments_seen": 0,
            "terminal_pair_tables_empty": 0,
            "context_residual_checks": 0,
            "left_envelope_empty": 0,
            "right_envelope_empty": 0,
            "both_envelopes_empty": 0,
            "prefilter_survivors": 0,
        }

    def add(self, key: str, count: int = 1) -> None:
        self.values[key] = self.values.get(key, 0) + count


def _envelope_states(
    states: tuple[TerminalPairState, ...],
    middle_min: int,
    middle_max: int,
    delta: int,
) -> tuple[TerminalPairState, ...]:
    result = []
    for state in states:
        low = min(middle_min, state.min_value + delta)
        high = max(middle_max, state.max_value + delta)
        if high - low <= EDGE_COUNT:
            result.append(state)
    return tuple(result)


def prefilter_group(
    group: dict[str, object],
    pair_cache: PersistentTwoRunCache,
    stats: PrefilterStats,
    context_envelope: bool = False,
    lazy_left: bool = False,
) -> list[PrefilterCandidate]:
    """Return only context/residual rows passing optimistic span filters.

    The default filter deliberately ignores collision tests and
    context-specific envelope scans. It removes only a row when a side has
    no local pair table, or when the optional envelope pass proves that no
    state can fit the middle envelope. Every exact survivor remains in the
    returned list.
    """
    stats.add("groups_seen")
    contexts = tuple(group["contexts"])
    residuals = group["residuals"]
    if not contexts:
        stats.add("groups_local_empty")
        return []
    for context in contexts:
        stats.add("contexts_seen")
        middle_values = tuple(context["all_values"])
        middle_min = min(middle_values)
        middle_max = max(middle_values)
        if middle_max - middle_min > EDGE_COUNT:
            stats.add("contexts_middle_span_overflow")

    table_cache: dict[tuple, tuple[TerminalPairState, ...]] = {}
    result: list[PrefilterCandidate] = []
    for residual_key, run_order in residuals.items():
        stats.add("residual_assignments_seen")
        block_map = dict(residual_key)
        left_a = block_map["left_leaf_1"]
        left_b = block_map["left_leaf_2"]
        right_a = block_map["right_leaf_1"]
        right_b = block_map["right_leaf_2"]
        left_key = (left_a, left_b)
        right_key = (right_a, right_b)
        if not lazy_left and left_key not in table_cache:
            table_cache[left_key] = pair_cache.terminal_pairs(left_a, left_b)
        if right_key not in table_cache:
            table_cache[right_key] = pair_cache.terminal_pairs(right_a, right_b)
        left_states = table_cache.get(left_key, ())
        right_states = table_cache[right_key]
        if (not lazy_left and not left_states) or not right_states:
            stats.add("terminal_pair_tables_empty")
            continue
        for context in contexts:
            stats.add("context_residual_checks")
            middle_values = tuple(context["all_values"])
            middle_min = min(middle_values)
            middle_max = max(middle_values)
            delta_left = int(context["delta_left"])
            delta_right = int(context["delta_right"])
            if context_envelope:
                # Optional diagnostic mode. It is sound but duplicates the
                # state scan that the exact join must perform anyway.
                left_exists = any(
                    max(middle_max, state.max_value - delta_left)
                    - min(middle_min, state.min_value - delta_left)
                    <= EDGE_COUNT
                    for state in left_states
                )
                if left_exists:
                    right_exists = any(
                        max(middle_max, state.max_value + delta_right)
                        - min(middle_min, state.min_value + delta_right)
                        <= EDGE_COUNT
                        for state in right_states
                    )
                else:
                    right_exists = False
                    stats.add("right_check_skipped_left_empty")
                left_fit = _envelope_states(left_states, middle_min, middle_max, -delta_left) if left_exists else ()
                right_fit = _envelope_states(right_states, middle_min, middle_max, delta_right) if right_exists else ()
            else:
                # Allocation-level mode: pair tables are already known to be
                # nonempty; defer the single envelope/collision pass to the
                # exact join instead of scanning the same states twice.
                # A lazy-left candidate is admitted on the basis of the
                # nonempty right table only.  The exact left query runs in
                # the persistent runner after the middle mask is available.
                left_fit = (None,) if lazy_left else left_states
                right_fit = right_states
            if not left_fit:
                stats.add("left_envelope_empty")
            if not right_fit:
                stats.add("right_envelope_empty")
            if not left_fit and not right_fit:
                stats.add("both_envelopes_empty")
            if left_fit and right_fit:
                stats.add("prefilter_survivors")
                result.append(PrefilterCandidate(
                    context=context,
                    residual_key=residual_key,
                    run_order=run_order,
                    left_states=tuple() if lazy_left else left_fit,
                    right_states=right_fit,
                    left_intervals=left_key if lazy_left else None,
                    lazy_left=lazy_left,
                ))
    return result


def prefilter_version() -> str:
    return "allocation-prefilter.v2:ownership.v2:table-and-middle-span"
