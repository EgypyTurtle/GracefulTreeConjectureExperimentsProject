"""Native-backed drop-in geometry cache for the C8 global pipeline.

Only the local two-run table is native.  The returned object is the same
``CompiledTwoRunGeometry`` used by the reference implementation, so semantic
filtering and global joins remain in the existing Python code.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from edge63_C8_compile_two_run_geometry import (
    COMPILED_VERSION,
    CompiledTwoRunGeometry,
    GeometryRecord,
    _checksum_records,
    _pair_id,
)
from edge63_C8_middle_group_cache import (
    ALLOCATION_DEDUP_VERSION,
    C8_LANGUAGE_VERSION,
    MIDDLE_FRAME_CONVENTION,
    TERMINAL_PAIR_CACHE_VERSION,
    canonical_json,
    version_fingerprint,
)
from edge63_C8_native_bridge import (
    LANGUAGE,
    OWNERSHIP,
    TERMINAL_CACHE,
    NativeTable,
    read_native_table,
    run_native,
)
from edge63_displacement_first_compact import _label_mask
from edge63_two_run_local_states import RunState


NATIVE_CACHE_VERSION = "native-two-run-geometry.v1"


def _native_id(case: str, split_slot: str, intervals: tuple[tuple[int, int], ...], role: str) -> str:
    return hashlib.sha256(canonical_json({
        "cache_version": NATIVE_CACHE_VERSION,
        "case": case,
        "split_slot": split_slot,
        "intervals": intervals,
        "role": role,
        "compiled_version": COMPILED_VERSION,
        "language": LANGUAGE,
        "ownership": OWNERSHIP,
        "terminal_cache": TERMINAL_CACHE,
    }).encode("utf-8")).hexdigest()[:28]


def _record_state(table: NativeTable, row: Any) -> RunState:
    return RunState(
        state_id=int(row.behavior_id),
        offsets=tuple(int(value) for value in row.offsets),
        private=tuple(int(value) for value in row.private),
        endpoint=None,
        min_value=int(row.min_value),
        max_value=int(row.max_value),
        difference_order=tuple(int(value) for value in row.difference_order),
        sign_word=tuple(int(value) for value in row.signs),
        run_intervals=tuple(tuple(int(value) for value in part) for part in table.intervals),
        order_mode=str(row.order_mode),
    )


def _from_native(table: NativeTable, intervals: tuple[tuple[int, int], ...], role: str, compile_seconds: float) -> CompiledTwoRunGeometry:
    if table.intervals != intervals:
        raise ValueError(f"native interval mismatch: expected {intervals}, got {table.intervals}")
    if table.language != LANGUAGE or table.ownership != OWNERSHIP or table.terminal_cache != TERMINAL_CACHE:
        raise ValueError("native table version mismatch")
    records: list[GeometryRecord] = []
    for expected_id, row in enumerate(table.records):
        if int(row.behavior_id) != expected_id:
            raise ValueError("native behavior IDs are not dense")
        witness = _record_state(table, row)
        records.append(GeometryRecord(
            behavior_id=expected_id,
            private=tuple(witness.private),
            mask=_label_mask(witness.private),
            min_value=int(row.min_value),
            max_value=int(row.max_value),
            span=int(row.span),
            witness=witness,
        ))
    frozen = tuple(records)
    contains: dict[int, int] = {}
    min_buckets: dict[int, int] = {}
    max_buckets: dict[int, int] = {}
    for record in frozen:
        bit = 1 << record.behavior_id
        for offset in record.private:
            contains[offset] = contains.get(offset, 0) | bit
        min_buckets[record.min_value] = min_buckets.get(record.min_value, 0) | bit
        max_buckets[record.max_value] = max_buckets.get(record.max_value, 0) | bit
    return CompiledTwoRunGeometry(
        pair_id=_pair_id(intervals, role),
        intervals=intervals,
        role=role,
        records=frozen,
        contains_by_offset=contains,
        min_buckets=min_buckets,
        max_buckets=max_buckets,
        all_bits=(1 << len(frozen)) - 1,
        compile_seconds=float(compile_seconds),
        checksum=_checksum_records(frozen),
        version_fingerprint="",
    )


class NativeCompiledGeometryCache:
    """Version-checked native cache with the reference cache's public shape."""

    backend_name = "native"

    def __init__(
        self,
        root: Path,
        case: str,
        split_slot: str,
        *,
        executable: Path | None = None,
        cache_root: Path | None = None,
        source_root: Path | None = None,
    ):
        self.root = root
        self.case = case
        self.split_slot = split_slot
        self.cache_root = cache_root or (root / "native_engine_v1" / "native_tables" / "runtime")
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.source_root = source_root or (root / "native_engine_v1" / "native_tables" / "golden")
        self.executable = executable or (root / "native_engine_v1" / "native_tables" / "edge63_C8_table_engine.exe")
        self.mem: dict[tuple[tuple[tuple[int, int], ...], str], CompiledTwoRunGeometry] = {}
        self.hits = 0
        self.misses = 0
        self.compile_count = 0
        self.reload_count = 0
        self.source_count = 0

    def _fingerprint(self, intervals: tuple[tuple[int, int], ...], role: str) -> str:
        return hashlib.sha256(canonical_json({
            "base": version_fingerprint(self.case, self.split_slot),
            "compiled_version": COMPILED_VERSION,
            "native_cache_version": NATIVE_CACHE_VERSION,
            "intervals": intervals,
            "role": role,
            "language": LANGUAGE,
            "ownership": OWNERSHIP,
            "terminal_cache": TERMINAL_CACHE,
        }).encode("utf-8")).hexdigest()

    def _path(self, intervals: tuple[tuple[int, int], ...], role: str) -> Path:
        return self.cache_root / f"native_pair_{_native_id(self.case, self.split_slot, intervals, role)}.bin"

    def _valid_table(self, table: NativeTable, intervals: tuple[tuple[int, int], ...]) -> bool:
        return (
            table.intervals == intervals
            and table.language == LANGUAGE
            and table.ownership == OWNERSHIP
            and table.terminal_cache == TERMINAL_CACHE
        )

    def _read(self, path: Path, intervals: tuple[tuple[int, int], ...], role: str) -> CompiledTwoRunGeometry | None:
        if role != "terminal" or not path.exists():
            return None
        try:
            table = read_native_table(path)
            if not self._valid_table(table, intervals):
                return None
            compiled = _from_native(table, intervals, role, 0.0)
            return CompiledTwoRunGeometry(
                pair_id=compiled.pair_id,
                intervals=compiled.intervals,
                role=compiled.role,
                records=compiled.records,
                contains_by_offset=compiled.contains_by_offset,
                min_buckets=compiled.min_buckets,
                max_buckets=compiled.max_buckets,
                all_bits=compiled.all_bits,
                compile_seconds=compiled.compile_seconds,
                checksum=compiled.checksum,
                version_fingerprint=self._fingerprint(intervals, role),
            )
        except (OSError, ValueError, TypeError, IndexError, UnicodeError):
            return None

    def _source_for(self, intervals: tuple[tuple[int, int], ...], role: str) -> Path | None:
        if role != "terminal" or not self.source_root.exists():
            return None
        for path in sorted(self.source_root.rglob("*.bin")):
            try:
                table = read_native_table(path)
            except (OSError, ValueError, TypeError, IndexError, UnicodeError):
                continue
            if self._valid_table(table, intervals):
                return path
        return None

    def _build(self, intervals: tuple[tuple[int, int], ...], role: str) -> tuple[CompiledTwoRunGeometry, Path]:
        if role != "terminal" or len(intervals) != 2:
            raise ValueError("native C8 engine only supports terminal two-run tables")
        if not self.executable.exists():
            raise FileNotFoundError(f"native table executable is missing: {self.executable}")
        started = time.perf_counter()
        temp = Path(tempfile.mkdtemp(prefix="c8_native_build_"))
        generated = temp / "table.bin"
        table = run_native(self.executable, intervals, generated)
        compiled = _from_native(table, intervals, role, time.perf_counter() - started)
        compiled = CompiledTwoRunGeometry(
            pair_id=compiled.pair_id,
            intervals=compiled.intervals,
            role=compiled.role,
            records=compiled.records,
            contains_by_offset=compiled.contains_by_offset,
            min_buckets=compiled.min_buckets,
            max_buckets=compiled.max_buckets,
            all_bits=compiled.all_bits,
            compile_seconds=compiled.compile_seconds,
            checksum=compiled.checksum,
            version_fingerprint=self._fingerprint(intervals, role),
        )
        return compiled, generated

    def _commit(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        os.close(fd)
        temp = Path(temp_name)
        try:
            temp.write_bytes(source.read_bytes())
            with temp.open("r+b") as handle:
                os.fsync(handle.fileno())
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)

    def get(self, intervals: tuple[tuple[int, int], ...], role: str = "terminal") -> CompiledTwoRunGeometry:
        key = (intervals, role)
        if key in self.mem:
            self.hits += 1
            return self.mem[key]
        destination = self._path(intervals, role)
        compiled = self._read(destination, intervals, role)
        if compiled is None:
            source = self._source_for(intervals, role)
            if source is not None:
                compiled = self._read(source, intervals, role)
                if compiled is not None:
                    self._commit(source, destination)
                    self.source_count += 1
            if compiled is None:
                compiled, generated = self._build(intervals, role)
                self._commit(generated, destination)
                shutil.rmtree(generated.parent, ignore_errors=True)
                self.compile_count += 1
            self.misses += 1
        else:
            self.hits += 1
            self.reload_count += 1
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
            "version": NATIVE_CACHE_VERSION,
            "compiled_version": COMPILED_VERSION,
            "two_run_language": C8_LANGUAGE_VERSION,
            "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
            "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
            "middle_frame_convention": MIDDLE_FRAME_CONVENTION,
        }
