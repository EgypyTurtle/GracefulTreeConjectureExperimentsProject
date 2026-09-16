"""Persistent C8 local and terminal-pair behavior tables."""

from __future__ import annotations

import gzip
import hashlib
import itertools
import json
import pickle
from pathlib import Path
from typing import Any, NamedTuple

from edge63_C8_middle_group_cache import (
    ALLOCATION_DEDUP_VERSION,
    BITSET_UNIVERSE,
    C8_LANGUAGE_VERSION,
    TERMINAL_PAIR_CACHE_VERSION,
    canonical_json,
)
from edge63_two_run_local_states import RunState, options_for_runs
from edge63_displacement_first_compact import EDGE_COUNT, _label_mask


TWO_RUN_CACHE_VERSION = "two-run-table-cache.v2"


class TerminalPairState(NamedTuple):
    state_id: int
    private: tuple[int, ...]
    mask: int
    min_value: int
    max_value: int
    state_a: RunState
    state_b: RunState


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=6) as handle:
        pickle.dump(payload, handle, protocol=5)


def _read(path: Path) -> object:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


class PersistentTwoRunCache:
    def __init__(self, root: Path, case: str, split_slot: str):
        self.root = root / "cache_v2" / "two_run_tables" / case / split_slot
        self.root.mkdir(parents=True, exist_ok=True)
        self.case = case
        self.split_slot = split_slot
        self.options_mem: dict[tuple, tuple[RunState, ...]] = {}
        self.pairs_mem: dict[tuple, tuple[TerminalPairState, ...]] = {}
        self.options_hits = 0
        self.options_misses = 0
        self.pair_hits = 0
        self.pair_misses = 0

    def _key(self, kind: str, value: Any) -> tuple:
        return (
            TWO_RUN_CACHE_VERSION,
            C8_LANGUAGE_VERSION,
            ALLOCATION_DEDUP_VERSION,
            TERMINAL_PAIR_CACHE_VERSION,
            BITSET_UNIVERSE,
            kind,
            value,
        )

    def _path(self, kind: str, value: Any) -> Path:
        digest = hashlib.sha256(canonical_json(self._key(kind, value)).encode("utf-8")).hexdigest()[:28]
        return self.root / f"{kind}_{digest}.pkl.gz"

    def options(self, intervals: tuple[tuple[int, int], ...], role: str) -> tuple[RunState, ...]:
        key = self._key("options", (intervals, role))
        if key in self.options_mem:
            self.options_hits += 1
            return self.options_mem[key]
        path = self._path("options", (intervals, role))
        if path.exists():
            try:
                payload = _read(path)
                if payload.get("key") == key:
                    result = tuple(payload["states"])
                    self.options_mem[key] = result
                    self.options_hits += 1
                    return result
            except (OSError, EOFError, KeyError, ValueError, AttributeError, pickle.PickleError):
                pass
        result = tuple(options_for_runs(intervals, role))
        _write(path, {"key": key, "states": result})
        self.options_mem[key] = result
        self.options_misses += 1
        return result

    def terminal_pairs(
        self,
        intervals_a: tuple[tuple[int, int], ...],
        intervals_b: tuple[tuple[int, int], ...],
    ) -> tuple[TerminalPairState, ...]:
        key = self._key("pairs", (intervals_a, intervals_b))
        if key in self.pairs_mem:
            self.pair_hits += 1
            return self.pairs_mem[key]
        path = self._path("pairs", (intervals_a, intervals_b))
        if path.exists():
            try:
                payload = _read(path)
                if payload.get("key") == key:
                    result = tuple(payload["states"])
                    self.pairs_mem[key] = result
                    self.pair_hits += 1
                    return result
            except (OSError, EOFError, KeyError, ValueError, AttributeError, pickle.PickleError):
                pass
        options_a = self.options(intervals_a, "terminal")
        options_b = self.options(intervals_b, "terminal")
        expected = sum(end - start + 1 for start, end in intervals_a)
        expected += sum(end - start + 1 for start, end in intervals_b)
        representatives: dict[tuple[int, ...], TerminalPairState] = {}
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
                TerminalPairState(
                    state_id=len(representatives),
                    private=private,
                    mask=_label_mask(private),
                    min_value=low,
                    max_value=high,
                    state_a=state_a,
                    state_b=state_b,
                ),
            )
        result = tuple(representatives.values())
        _write(path, {"key": key, "states": result})
        self.pairs_mem[key] = result
        self.pair_misses += 1
        return result

    def stats(self) -> dict[str, object]:
        option_total = self.options_hits + self.options_misses
        pair_total = self.pair_hits + self.pair_misses
        return {
            "options_requests": option_total,
            "options_hits": self.options_hits,
            "options_misses": self.options_misses,
            "options_hit_rate": self.options_hits / option_total if option_total else 0.0,
            "pair_requests": pair_total,
            "pair_hits": self.pair_hits,
            "pair_misses": self.pair_misses,
            "pair_hit_rate": self.pair_hits / pair_total if pair_total else 0.0,
            "cache_root": str(self.root),
            "two_run_cache_version": TWO_RUN_CACHE_VERSION,
        }
