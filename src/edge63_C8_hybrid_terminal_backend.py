"""Hybrid exact left-query backend for the Tree1 C8 side-terminal runner."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_two_run_cache import PersistentTwoRunCache, _read
from edge63_displacement_first_compact import EDGE_COUNT


def _mask_shift(mask: int, shift: int) -> int:
    return mask << shift if shift >= 0 else mask >> (-shift)


def _compatible_states(states: tuple, middle_mask: int, middle_min: int, middle_max: int, shift: int) -> list[tuple]:
    result = []
    for state in states:
        shifted_mask = _mask_shift(state.mask, shift)
        if shifted_mask & middle_mask:
            continue
        low = min(middle_min, state.min_value + shift)
        high = max(middle_max, state.max_value + shift)
        if high - low <= EDGE_COUNT:
            result.append((state, shifted_mask, low, high))
    return result


class HybridTerminalBackend:
    """Use a persisted full table when available, otherwise compiled geometry."""

    def __init__(
        self,
        pair_cache: PersistentTwoRunCache,
        compiled_index: CompiledTerminalPairIndex,
    ) -> None:
        self.pair_cache = pair_cache
        self.compiled_index = compiled_index
        self._persisted_pair_status: dict[tuple, bool] = {}
        self.stats: dict[str, float | int] = {
            "old_cache_queries": 0,
            "compiled_queries": 0,
            "old_cache_hits": 0,
            "compiled_cache_hits": 0,
            "seconds_old_cache": 0.0,
            "seconds_compiled": 0.0,
        }

    def has_valid_persisted_pair(
        self,
        intervals_a: tuple[tuple[int, int], ...],
        intervals_b: tuple[tuple[int, int], ...],
    ) -> bool:
        pair_key = (intervals_a, intervals_b)
        cached_status = self._persisted_pair_status.get(pair_key)
        if cached_status is not None:
            return cached_status
        key = self.pair_cache._key("pairs", (intervals_a, intervals_b))
        path: Path = self.pair_cache._path("pairs", (intervals_a, intervals_b))
        if not path.exists():
            self._persisted_pair_status[pair_key] = False
            return False
        try:
            payload = _read(path)
            status = payload.get("key") == key and "states" in payload
            self._persisted_pair_status[pair_key] = status
            return status
        except (OSError, EOFError, KeyError, ValueError, AttributeError, TypeError):
            self._persisted_pair_status[pair_key] = False
            return False

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
    ) -> tuple[list[tuple], dict[str, Any]]:
        started = time.perf_counter()
        if self.has_valid_persisted_pair(intervals_a, intervals_b):
            full = self.pair_cache.terminal_pairs(intervals_a, intervals_b)
            result = _compatible_states(full, occupied_mask, middle_min, middle_max, left_shift)
            elapsed = time.perf_counter() - started
            self.stats["old_cache_queries"] += 1
            self.stats["old_cache_hits"] += 1
            self.stats["seconds_old_cache"] += elapsed
            return result, {
                "backend": "OLD_CACHED_FILTER",
                "backend_cache": "PERSISTED_PAIR_HIT",
                "backend_seconds": elapsed,
                "pair_table_states": len(full),
                "output_states": len(result),
            }

        states, compiled_stats = self.compiled_index.query(
            intervals_a,
            intervals_b,
            occupied_mask=occupied_mask,
            left_shift=left_shift,
            middle_min=middle_min,
            middle_max=middle_max,
            span_mode=span_mode,
        )
        result = []
        for state in states:
            shifted_mask = _mask_shift(state.mask, left_shift)
            low = min(middle_min, state.min_value + left_shift)
            high = max(middle_max, state.max_value + left_shift)
            result.append((state, shifted_mask, low, high))
        elapsed = time.perf_counter() - started
        self.stats["compiled_queries"] += 1
        if compiled_stats.get("compiled_query_cache") == "HIT":
            self.stats["compiled_cache_hits"] += 1
        self.stats["seconds_compiled"] += elapsed
        return result, {
            "backend": "COMPILED_GEOMETRY_INDEX",
            "backend_cache": compiled_stats.get("compiled_query_cache", "MISS"),
            "backend_seconds": elapsed,
            **compiled_stats,
            "output_states": len(result),
        }
