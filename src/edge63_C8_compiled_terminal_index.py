#!/usr/bin/env python3
"""Context queries over a compiled two-run geometry object.

The split path is filtered by inverted indexes first.  The other terminal
path remains a trusted C7 table.  Only query survivors are combined, so this
module never persists the full terminal-pair Cartesian table.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from edge63_C8_compile_two_run_geometry import PersistentCompiledGeometryCache
from edge63_C8_two_run_cache import TerminalPairState
from edge63_displacement_first_compact import EDGE_COUNT, _label_mask
from edge63_two_run_local_states import RunState, options_for_runs


def _mask_shift(mask: int, shift: int) -> int:
    return mask << shift if shift >= 0 else mask >> (-shift)


def _state_key(state: TerminalPairState) -> tuple[tuple[int, ...], int, int]:
    return state.private, state.min_value, state.max_value


class CompiledTerminalPairIndex:
    """On-demand compiled query index for `(single terminal, split terminal)`."""

    def __init__(self, root: Path, case: str, split_slot: str, *, geometry_cache: Any | None = None):
        self.root = root
        self.case = case
        self.split_slot = split_slot
        self.geometry_cache = geometry_cache or PersistentCompiledGeometryCache(root, case, split_slot)
        self.backend_name = getattr(self.geometry_cache, "backend_name", "python")
        self.single_options_mem: dict[tuple[tuple[tuple[int, int], ...], str], tuple[RunState, ...]] = {}
        self.pair_states_mem: dict[tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]], tuple[TerminalPairState, ...]] = {}
        self.query_mem: dict[tuple, tuple[TerminalPairState, ...]] = {}
        self.query_hits = 0
        self.query_misses = 0

    def _single_options(self, intervals: tuple[tuple[int, int], ...]) -> tuple[RunState, ...]:
        key = (intervals, "terminal")
        if key not in self.single_options_mem:
            self.single_options_mem[key] = tuple(options_for_runs(intervals, "terminal"))
        return self.single_options_mem[key]

    def query(
        self,
        intervals_a: tuple[tuple[int, int], ...],
        intervals_b: tuple[tuple[int, int], ...],
        *,
        occupied_mask: int,
        left_shift: int,
        middle_min: int,
        middle_max: int,
        span_mode: bool = True,
    ) -> tuple[tuple[TerminalPairState, ...], dict[str, Any]]:
        """Return exact pair states surviving this context query."""
        if len(intervals_b) != 2:
            raise ValueError("compiled terminal index expects the split path in intervals_b")
        key = (
            intervals_a,
            intervals_b,
            int(occupied_mask),
            int(left_shift),
            int(middle_min),
            int(middle_max),
            bool(span_mode),
        )
        cached = self.query_mem.get(key)
        if cached is not None:
            self.query_hits += 1
            return cached, {
                "compiled_query_cache": "HIT",
                "compiled_geometry_states": 0,
                "compiled_geometry_bits": 0,
                "pair_attempts": 0,
                "pair_output_states": len(cached),
                "query_seconds": 0.0,
            }
        started = time.perf_counter()
        compiled = self.geometry_cache.get(intervals_b, "terminal")
        split_bits = compiled.query_bits(
            occupied_mask=occupied_mask,
            shift=left_shift,
            middle_min=middle_min,
            middle_max=middle_max,
            span_mode=span_mode,
        )
        split_records = compiled.records_for_bits(split_bits)
        single_states = self._single_options(intervals_a)
        representatives: dict[tuple[int, ...], TerminalPairState] = {}
        pair_attempts = 0
        for state_a in single_states:
            shifted_a_private = tuple(value + left_shift for value in state_a.private)
            if _label_mask(shifted_a_private) & occupied_mask:
                continue
            for record in split_records:
                pair_attempts += 1
                private = tuple(sorted((*state_a.private, *record.private)))
                if 0 in private or len(private) != len(set(private)):
                    continue
                low = min(middle_min, min((0, *private)) + left_shift)
                high = max(middle_max, max((0, *private)) + left_shift)
                if span_mode and high - low > EDGE_COUNT:
                    continue
                state = TerminalPairState(
                    state_id=len(representatives),
                    private=private,
                    mask=_label_mask(private),
                    min_value=min((0, *private)),
                    max_value=max((0, *private)),
                    state_a=state_a,
                    state_b=record.witness,
                )
                representatives.setdefault(private, state)
        result = tuple(representatives.values())
        self.query_mem[key] = result
        self.query_misses += 1
        return result, {
            "compiled_query_cache": "MISS",
            "compiled_geometry_states": len(compiled.records),
            "compiled_geometry_bits": len(split_records),
            "pair_attempts": pair_attempts,
            "pair_output_states": len(result),
            "query_seconds": time.perf_counter() - started,
        }

    def pair_states_from_geometry(
        self,
        intervals_a: tuple[tuple[int, int], ...],
        intervals_b: tuple[tuple[int, int], ...],
    ) -> tuple[TerminalPairState, ...]:
        """Build the exact pair quotient from this index's local backend."""
        key = (intervals_a, intervals_b)
        cached = self.pair_states_mem.get(key)
        if cached is not None:
            return cached
        compiled = self.geometry_cache.get(intervals_b, "terminal")
        single_states = self._single_options(intervals_a)
        expected = sum(end - start + 1 for start, end in intervals_a)
        expected += sum(end - start + 1 for start, end in intervals_b)
        representatives: dict[tuple[int, ...], TerminalPairState] = {}
        for state_a in single_states:
            for record in compiled.records:
                private = tuple(sorted((*state_a.private, *record.private)))
                if 0 in private or len(private) != expected or len(set(private)) != expected:
                    continue
                low = min((0, *private))
                high = max((0, *private))
                if high - low > EDGE_COUNT:
                    continue
                representatives.setdefault(
                    private,
                    TerminalPairState(
                        state_id=len(representatives),
                        private=private,
                        mask=_label_mask(private),
                        min_value=low,
                        max_value=high,
                        state_a=state_a,
                        state_b=record.witness,
                    ),
                )
        result = tuple(representatives.values())
        self.pair_states_mem[key] = result
        return result

    def stats(self) -> dict[str, Any]:
        return {
            "compiled_query_requests": self.query_hits + self.query_misses,
            "compiled_query_hits": self.query_hits,
            "compiled_query_misses": self.query_misses,
            "compiled_query_hit_rate": self.query_hits / (self.query_hits + self.query_misses)
            if self.query_hits + self.query_misses
            else 0.0,
            "compiled_geometry_cache_hits": self.geometry_cache.hits,
            "compiled_geometry_cache_misses": self.geometry_cache.misses,
        }


def state_geometry(state: TerminalPairState) -> tuple[tuple[int, ...], int, int]:
    return _state_key(state)
