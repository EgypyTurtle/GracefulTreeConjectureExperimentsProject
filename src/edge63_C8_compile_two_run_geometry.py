#!/usr/bin/env python3
"""Persistent compiled geometry for one C8 two-run interval pair.

The compiled object stores quotient local geometries and inverted offset
indexes.  It deliberately does not materialize a terminal-pair Cartesian
table; pair construction is deferred to the context query layer.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import pickle
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edge63_C8_middle_group_cache import (
    ALLOCATION_DEDUP_VERSION,
    BITSET_UNIVERSE,
    C8_LANGUAGE_VERSION,
    MIDDLE_FRAME_CONVENTION,
    TERMINAL_PAIR_CACHE_VERSION,
    canonical_json,
    version_fingerprint,
)
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_displacement_first_compact import EDGE_COUNT, OFFSET_SHIFT, _label_mask
from edge63_two_run_local_states import RunState


COMPILED_VERSION = "compiled-two-run-geometry.v1"


def _pair_id(intervals: tuple[tuple[int, int], ...], role: str) -> str:
    payload = {
        "compiled_version": COMPILED_VERSION,
        "intervals": intervals,
        "role": role,
        "language": C8_LANGUAGE_VERSION,
        "allocation": ALLOCATION_DEDUP_VERSION,
        "terminal_cache": TERMINAL_PAIR_CACHE_VERSION,
        "bitset": BITSET_UNIVERSE,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:28]


@dataclass(frozen=True)
class GeometryRecord:
    behavior_id: int
    private: tuple[int, ...]
    mask: int
    min_value: int
    max_value: int
    span: int
    witness: RunState


@dataclass(frozen=True)
class CompiledTwoRunGeometry:
    pair_id: str
    intervals: tuple[tuple[int, int], ...]
    role: str
    records: tuple[GeometryRecord, ...]
    contains_by_offset: dict[int, int]
    min_buckets: dict[int, int]
    max_buckets: dict[int, int]
    all_bits: int
    compile_seconds: float
    checksum: str
    version_fingerprint: str

    def _occupied_original_offsets(self, occupied_mask: int, shift: int) -> tuple[int, ...]:
        values: list[int] = []
        bits = int(occupied_mask)
        while bits:
            lowest = bits & -bits
            value = lowest.bit_length() - 1 - OFFSET_SHIFT
            values.append(value - shift)
            bits ^= lowest
        return tuple(values)

    def query_bits(
        self,
        *,
        occupied_mask: int,
        shift: int,
        middle_min: int,
        middle_max: int,
        span_mode: bool = True,
    ) -> int:
        """Return matching geometry IDs using bitset filters only."""
        result = self.all_bits
        blocked = 0
        for offset in self._occupied_original_offsets(occupied_mask, shift):
            blocked |= self.contains_by_offset.get(offset, 0)
        result &= ~blocked
        if span_mode:
            span_bad = 0
            for record in self.records:
                low = min(middle_min, record.min_value + shift)
                high = max(middle_max, record.max_value + shift)
                if high - low > EDGE_COUNT:
                    span_bad |= 1 << record.behavior_id
            result &= ~span_bad
        return result

    def records_for_bits(self, bits: int) -> tuple[GeometryRecord, ...]:
        result: list[GeometryRecord] = []
        remaining = int(bits)
        while remaining:
            lowest = remaining & -remaining
            index = lowest.bit_length() - 1
            result.append(self.records[index])
            remaining ^= lowest
        return tuple(result)


def _checksum_records(records: tuple[GeometryRecord, ...]) -> str:
    payload = [
        {
            "behavior_id": row.behavior_id,
            "private": row.private,
            "min": row.min_value,
            "max": row.max_value,
            "span": row.span,
        }
        for row in records
    ]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class PersistentCompiledGeometryCache:
    """On-demand pair compiler with version-checked persistent storage."""

    def __init__(self, root: Path, case: str, split_slot: str):
        self.root = root
        self.case = case
        self.split_slot = split_slot
        self.cache_root = root / "cache_v2" / "two_run_compiled" / case / split_slot
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.base_cache = PersistentTwoRunCache(root, case, split_slot)
        self.mem: dict[tuple[tuple[tuple[int, int], ...], str], CompiledTwoRunGeometry] = {}
        self.hits = 0
        self.misses = 0

    def _fingerprint(self, intervals: tuple[tuple[int, int], ...], role: str) -> str:
        return hashlib.sha256(canonical_json({
            "base": version_fingerprint(self.case, self.split_slot),
            "compiled_version": COMPILED_VERSION,
            "intervals": intervals,
            "role": role,
        }).encode("utf-8")).hexdigest()

    def _path(self, intervals: tuple[tuple[int, int], ...], role: str) -> Path:
        return self.cache_root / f"pair_{_pair_id(intervals, role)}.pkl.gz"

    def _build(self, intervals: tuple[tuple[int, int], ...], role: str) -> CompiledTwoRunGeometry:
        started = time.perf_counter()
        states = tuple(self.base_cache.options(intervals, role))
        records = tuple(
            GeometryRecord(
                behavior_id=index,
                private=tuple(state.private),
                mask=_label_mask(state.private),
                min_value=int(state.min_value),
                max_value=int(state.max_value),
                span=int(state.max_value - state.min_value),
                witness=state,
            )
            for index, state in enumerate(states)
        )
        contains: dict[int, int] = {}
        min_buckets: dict[int, int] = {}
        max_buckets: dict[int, int] = {}
        for record in records:
            bit = 1 << record.behavior_id
            for offset in record.private:
                contains[offset] = contains.get(offset, 0) | bit
            min_buckets[record.min_value] = min_buckets.get(record.min_value, 0) | bit
            max_buckets[record.max_value] = max_buckets.get(record.max_value, 0) | bit
        checksum = _checksum_records(records)
        return CompiledTwoRunGeometry(
            pair_id=_pair_id(intervals, role),
            intervals=intervals,
            role=role,
            records=records,
            contains_by_offset=contains,
            min_buckets=min_buckets,
            max_buckets=max_buckets,
            all_bits=(1 << len(records)) - 1,
            compile_seconds=time.perf_counter() - started,
            checksum=checksum,
            version_fingerprint=self._fingerprint(intervals, role),
        )

    def _read(self, path: Path, intervals: tuple[tuple[int, int], ...], role: str) -> CompiledTwoRunGeometry | None:
        try:
            with gzip.open(path, "rb") as handle:
                payload = pickle.load(handle)
            if payload.get("version_fingerprint") != self._fingerprint(intervals, role):
                return None
            compiled = payload["compiled"]
            if not isinstance(compiled, CompiledTwoRunGeometry):
                return None
            if compiled.intervals != intervals or compiled.role != role:
                return None
            if compiled.checksum != _checksum_records(compiled.records):
                return None
            return compiled
        except (OSError, EOFError, KeyError, ValueError, AttributeError, pickle.PickleError):
            return None

    def get(self, intervals: tuple[tuple[int, int], ...], role: str = "terminal") -> CompiledTwoRunGeometry:
        key = (intervals, role)
        if key in self.mem:
            self.hits += 1
            return self.mem[key]
        path = self._path(intervals, role)
        compiled = self._read(path, intervals, role) if path.exists() else None
        if compiled is None:
            compiled = self._build(intervals, role)
            # Commit the persistent object atomically so a crashed worker can
            # never leave a syntactically valid-looking partial cache file.
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            os.close(fd)
            temp_path = Path(temp_name)
            try:
                with gzip.open(temp_path, "wb", compresslevel=6) as handle:
                    pickle.dump({
                        "version_fingerprint": compiled.version_fingerprint,
                        "compiled": compiled,
                    }, handle, protocol=5)
                os.replace(temp_path, path)
            finally:
                if temp_path.exists():
                    temp_path.unlink()
            self.misses += 1
        else:
            self.hits += 1
        self.mem[key] = compiled
        return compiled

    def manifest_row(self, compiled: CompiledTwoRunGeometry, query_count: int = 0) -> dict[str, Any]:
        path = self._path(compiled.intervals, compiled.role)
        ordered = tuple(sorted(compiled.intervals))
        gap = ordered[1][0] - ordered[0][1] - 1 if len(ordered) == 2 else 0
        return {
            "pair_id": compiled.pair_id,
            "I1": f"{compiled.intervals[0][0]}-{compiled.intervals[0][1]}",
            "I2": f"{compiled.intervals[1][0]}-{compiled.intervals[1][1]}",
            "gap": gap,
            "lengths": "+".join(str(end - start + 1) for start, end in compiled.intervals),
            "behavior_count": len(compiled.records),
            "compile_seconds": round(compiled.compile_seconds, 6),
            "cache_bytes": path.stat().st_size if path.exists() else 0,
            "query_count": query_count,
            "cache_hits": self.hits,
            "checksum": compiled.checksum,
            "version": COMPILED_VERSION,
            "two_run_language": C8_LANGUAGE_VERSION,
            "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
            "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
            "middle_frame_convention": MIDDLE_FRAME_CONVENTION,
        }
