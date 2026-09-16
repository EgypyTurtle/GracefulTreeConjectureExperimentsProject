"""Compiled exact support index for the unsplit right terminal pair.

The index is an accelerator for the cheap right-support census.  It stores
only bitset indexes over the existing corrected.v2 terminal-pair states and
therefore does not change the accepted state family.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_displacement_first_compact import EDGE_COUNT, OFFSET_SHIFT


VERSION = "right-support-index.v1"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


@dataclass(frozen=True)
class CompiledRightPair:
    intervals_a: tuple[tuple[int, int], ...]
    intervals_b: tuple[tuple[int, int], ...]
    state_count: int
    all_bits: int
    contains_by_offset: dict[int, int]
    min_values: tuple[int, ...]
    min_suffix_bits: tuple[int, ...]
    max_values: tuple[int, ...]
    max_prefix_bits: tuple[int, ...]
    states: tuple[Any, ...]

    def _occupied_original_offsets(self, occupied_mask: int, shift: int) -> tuple[int, ...]:
        values: list[int] = []
        bits = int(occupied_mask)
        while bits:
            lowest = bits & -bits
            label = lowest.bit_length() - 1 - OFFSET_SHIFT
            values.append(label - shift)
            bits ^= lowest
        return tuple(values)

    def matching_bits(
        self,
        *,
        occupied_mask: int,
        shift: int,
        middle_min: int,
        middle_max: int,
    ) -> int:
        if middle_max - middle_min > EDGE_COUNT:
            return 0
        result = self.all_bits
        blocked = 0
        for offset in self._occupied_original_offsets(occupied_mask, shift):
            blocked |= self.contains_by_offset.get(offset, 0)
        result &= ~blocked

        min_threshold = middle_max - EDGE_COUNT - shift
        min_index = bisect_left(self.min_values, min_threshold)
        min_allowed = self.min_suffix_bits[min_index] if min_index < self.state_count else 0
        result &= min_allowed

        max_threshold = middle_min + EDGE_COUNT - shift
        max_index = bisect_right(self.max_values, max_threshold) - 1
        max_allowed = self.max_prefix_bits[max_index] if max_index >= 0 else 0
        result &= max_allowed
        return result

    def compatible_count(self, *, occupied_mask: int, shift: int, middle_min: int, middle_max: int) -> int:
        return self.matching_bits(
            occupied_mask=occupied_mask,
            shift=shift,
            middle_min=middle_min,
            middle_max=middle_max,
        ).bit_count()


class RightSupportIndex:
    """Process-local compiled indexes over corrected terminal-pair tables."""

    def __init__(self, root: Path, case: str, split_slot: str):
        self.version = VERSION
        self.pair_cache = PersistentTwoRunCache(root, case, split_slot)
        self.mem: dict[tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]], CompiledRightPair] = {}
        self.compile_requests = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def get(
        self,
        intervals_a: tuple[tuple[int, int], ...],
        intervals_b: tuple[tuple[int, int], ...],
    ) -> CompiledRightPair:
        key = (intervals_a, intervals_b)
        self.compile_requests += 1
        cached = self.mem.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached
        states = tuple(self.pair_cache.terminal_pairs(intervals_a, intervals_b))
        all_bits = (1 << len(states)) - 1
        contains: dict[int, int] = {}
        min_buckets: dict[int, int] = {}
        max_buckets: dict[int, int] = {}
        for index, state in enumerate(states):
            bit = 1 << index
            for offset in state.private:
                contains[int(offset)] = contains.get(int(offset), 0) | bit
            min_buckets[int(state.min_value)] = min_buckets.get(int(state.min_value), 0) | bit
            max_buckets[int(state.max_value)] = max_buckets.get(int(state.max_value), 0) | bit

        min_values = tuple(sorted(min_buckets))
        min_suffix: list[int] = [0] * (len(min_values) + 1)
        for index in range(len(min_values) - 1, -1, -1):
            min_suffix[index] = min_suffix[index + 1] | min_buckets[min_values[index]]
        max_values = tuple(sorted(max_buckets))
        max_prefix: list[int] = [0] * len(max_values)
        running = 0
        for index, value in enumerate(max_values):
            running |= max_buckets[value]
            max_prefix[index] = running
        compiled = CompiledRightPair(
            intervals_a=intervals_a,
            intervals_b=intervals_b,
            state_count=len(states),
            all_bits=all_bits,
            contains_by_offset=contains,
            min_values=min_values,
            min_suffix_bits=tuple(min_suffix),
            max_values=max_values,
            max_prefix_bits=tuple(max_prefix),
            states=states,
        )
        self.mem[key] = compiled
        self.cache_misses += 1
        return compiled

    def stats(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "requests": self.compile_requests,
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "compiled_pairs_in_memory": len(self.mem),
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        }
