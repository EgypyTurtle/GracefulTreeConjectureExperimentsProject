"""Differentially verify native local filtering against the Python index."""

from __future__ import annotations

import argparse
import csv
import json
import random
import tempfile
from pathlib import Path
from typing import Any

from edge63_C8_compile_two_run_geometry import PersistentCompiledGeometryCache
from edge63_C8_middle_group_cache import BITSET_UNIVERSE
from edge63_C8_native_bridge import LANGUAGE, OWNERSHIP, TERMINAL_CACHE, read_native_table, run_native
from edge63_C8_native_semantic import NativeSemanticIndex
from edge63_displacement_first_compact import _label_mask


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"


def _versions() -> dict[str, str]:
    return {"two_run_language": LANGUAGE, "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE, "bitset_universe": BITSET_UNIVERSE}


def _queries(table: Any) -> list[tuple[frozenset[int], int, int, int]]:
    offsets = sorted({value for row in table.records for value in row.private})
    candidates = [frozenset(), frozenset(offsets[:2]), frozenset(offsets[-2:]), frozenset(offsets[::3])]
    return [(occupied, shift, middle_min, middle_max)
            for occupied, shift, middle_min, middle_max in (
                (candidates[0], 0, -20, 20),
                (candidates[1], 0, -10, 20),
                (candidates[2], 3, -10, 40),
                (candidates[3], -4, -30, 20),
            )]


def run(results_root: Path, batch: Path, executable: Path, output: Path) -> dict[str, Any]:
    rows = list(csv.DictReader((batch / "batch_key_manifest.csv").open(encoding="utf-8")))
    checks = []
    with tempfile.TemporaryDirectory(prefix="c8_native_semantic_") as temp:
        for row in rows:
            intervals = tuple(tuple(int(x) for x in part) for part in json.loads(row["intervals_b"]))
            native = run_native(executable, intervals, Path(temp) / f"{row['table_key']}.bin")
            native_index = NativeSemanticIndex.build(native)
            python = PersistentCompiledGeometryCache(results_root, CASE, SLOT).get(intervals, "terminal")
            for index, (occupied, shift, middle_min, middle_max) in enumerate(_queries(native)):
                occupied_mask = _label_mask(value + shift for value in occupied)
                expected = python.query_bits(occupied_mask=occupied_mask, shift=shift,
                                             middle_min=middle_min, middle_max=middle_max, span_mode=True)
                actual = native_index.query_bits(occupied, shift, middle_min, middle_max)
                checks.append({"table_key": row["table_key"], "query": index,
                               "python_bits": hex(expected), "native_bits": hex(actual),
                               "equal": expected == actual})
    result = {"checks": len(checks), "mismatches": sum(not row["equal"] for row in checks),
              "status": "PASS" if all(row["equal"] for row in checks) else "FAIL",
              "scope": "native local collision/span bitset filter", **_versions()}
    output.mkdir(parents=True, exist_ok=True)
    (output / "semantic_differential.json").write_text(json.dumps({**result, "sample": checks[:20]}, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--batch", type=Path, default=Path("results/edge63_two_interval_gate2/tree1_C8/left_leaf_2_exact_v3/frontier_directed_v1/table_batch_structure_v1"))
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/benchmarks"))
    args = parser.parse_args()
    result = run(args.results_root, args.batch, args.executable, args.output)
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
