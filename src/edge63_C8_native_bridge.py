"""Small, reference-oriented bridge for the C8 native local-table engine.

The native executable produces geometry records only.  Python remains the
authority for C8 semantics, provenance, certificates, and global joins.
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edge63_two_run_local_states import options_for_runs


LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
MAGIC = b"GTC8TAB1"
FORMAT_VERSION = 2


@dataclass(frozen=True)
class NativeRecord:
    behavior_id: int
    min_value: int
    max_value: int
    span: int
    private: tuple[int, ...]
    offsets: tuple[int, ...]
    difference_order: tuple[int, ...]
    signs: tuple[int, ...]
    order_mode: str


@dataclass(frozen=True)
class NativeTable:
    intervals: tuple[tuple[int, int], ...]
    records: tuple[NativeRecord, ...]
    language: str
    ownership: str
    terminal_cache: str
    payload_checksum: int


def _u32(data: bytes, pos: int) -> tuple[int, int]:
    return struct.unpack_from("<I", data, pos)[0], pos + 4


def _i32(data: bytes, pos: int) -> tuple[int, int]:
    return struct.unpack_from("<i", data, pos)[0], pos + 4


def _u64(data: bytes, pos: int) -> tuple[int, int]:
    return struct.unpack_from("<Q", data, pos)[0], pos + 8


def _string(data: bytes, pos: int) -> tuple[str, int]:
    size, pos = _u32(data, pos)
    return data[pos:pos + size].decode("utf-8"), pos + size


def _vec(data: bytes, pos: int) -> tuple[tuple[int, ...], int]:
    size, pos = _u32(data, pos)
    values = []
    for _ in range(size):
        value, pos = _i32(data, pos)
        values.append(value)
    return tuple(values), pos


def read_native_table(path: Path) -> NativeTable:
    data = path.read_bytes()
    if data[:8] != MAGIC:
        raise ValueError(f"bad native table magic: {path}")
    pos = 8
    format_version, pos = _u32(data, pos)
    edge_count, pos = _u32(data, pos)
    offset_shift, pos = _u32(data, pos)
    if format_version != FORMAT_VERSION or edge_count != 63 or offset_shift != 256:
        raise ValueError("native table header mismatch")
    start_a, pos = _i32(data, pos)
    end_a, pos = _i32(data, pos)
    start_b, pos = _i32(data, pos)
    end_b, pos = _i32(data, pos)
    language, pos = _string(data, pos)
    ownership, pos = _string(data, pos)
    terminal_cache, pos = _string(data, pos)
    header_checksum, pos = _u64(data, pos)
    count, pos = _u32(data, pos)
    records = []
    for _ in range(count):
        behavior_id, pos = _u32(data, pos)
        min_value, pos = _i32(data, pos)
        max_value, pos = _i32(data, pos)
        span, pos = _i32(data, pos)
        private, pos = _vec(data, pos)
        offsets, pos = _vec(data, pos)
        difference_order, pos = _vec(data, pos)
        signs, pos = _vec(data, pos)
        order_mode, pos = _string(data, pos)
        records.append(NativeRecord(
            behavior_id=behavior_id,
            min_value=min_value,
            max_value=max_value,
            span=span,
            private=private,
            offsets=offsets,
            difference_order=difference_order,
            signs=signs,
            order_mode=order_mode,
        ))
    checksum, pos = _u32(data, pos)
    if pos != len(data):
        raise ValueError(f"trailing bytes in native table: {path}")
    if header_checksum & 0xffffffff != checksum:
        raise ValueError(f"native checksum header/footer mismatch: {path}")
    return NativeTable(
        intervals=((start_a, end_a), (start_b, end_b)),
        records=tuple(records),
        language=language,
        ownership=ownership,
        terminal_cache=terminal_cache,
        payload_checksum=header_checksum,
    )


def run_native(executable: Path, intervals: tuple[tuple[int, int], ...], output: Path) -> NativeTable:
    if len(intervals) != 2:
        raise ValueError("native C8 engine currently accepts exactly two intervals")
    (start_a, end_a), (start_b, end_b) = intervals
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(executable),
        "--a-start", str(start_a), "--a-end", str(end_a),
        "--b-start", str(start_b), "--b-end", str(end_b),
        "--output", str(output),
    ], check=True, capture_output=True, text=True)
    return read_native_table(output)


def compare_geometry(table: NativeTable, intervals: tuple[tuple[int, int], ...], role: str = "terminal") -> dict[str, Any]:
    reference = options_for_runs(intervals, role)
    expected = [
        {
            "behavior_id": index,
            "private": tuple(state.private),
            "offsets": tuple(state.offsets),
            "min": int(state.min_value),
            "max": int(state.max_value),
            "span": int(state.max_value - state.min_value),
            "difference_order": tuple(state.difference_order),
            "signs": tuple(state.sign_word),
            "order_mode": state.order_mode,
        }
        for index, state in enumerate(reference)
    ]
    actual = [
        {
            "behavior_id": row.behavior_id,
            "private": row.private,
            "offsets": row.offsets,
            "min": row.min_value,
            "max": row.max_value,
            "span": row.span,
            "difference_order": row.difference_order,
            "signs": row.signs,
            "order_mode": row.order_mode,
        }
        for row in table.records
    ]
    geometry_equal = [
        {key: row[key] for key in ("behavior_id", "private", "min", "max", "span")}
        for row in actual
    ] == [
        {key: row[key] for key in ("behavior_id", "private", "min", "max", "span")}
        for row in expected
    ]
    witness_equal = actual == expected
    return {
        "geometry_equal": geometry_equal,
        "witness_equal": witness_equal,
        "reference_count": len(expected),
        "native_count": len(actual),
        "native_header_versions": {
            "two_run_language": table.language,
            "allocation_dedup_version": table.ownership,
            "terminal_pair_cache_version": table.terminal_cache,
        },
        "versions_equal": table.language == LANGUAGE and table.ownership == OWNERSHIP and table.terminal_cache == TERMINAL_CACHE,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--intervals", type=str, required=True, help="JSON, e.g. [[6,18],[28,34]]")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    intervals = tuple(tuple(int(value) for value in part) for part in json.loads(args.intervals))
    table = run_native(args.executable, intervals, args.output)
    result = compare_geometry(table, intervals)
    print(json.dumps(result, indent=2))
    if not result["geometry_equal"] or not result["witness_equal"] or not result["versions_equal"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
