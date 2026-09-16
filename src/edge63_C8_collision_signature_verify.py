"""Independent differential checks for collision-effect semantic signatures."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_displacement_first_compact import EDGE_COUNT, _label_mask


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _family_parts(key: str) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...], int, int, int]:
    payload = json.loads(key)
    return (
        tuple(tuple(int(value) for value in part) for part in payload["intervals_a"]),
        tuple(tuple(int(value) for value in part) for part in payload["intervals_b"]),
        int(payload["left_shift"]),
        int(payload["middle_min"]),
        int(payload["middle_max"]),
    )


def verify(scope_dir: Path, sample_size: int) -> dict[str, Any]:
    manifest_path = scope_dir / "semantic_signature_manifest.csv"
    rows = list(csv.DictReader(manifest_path.open(encoding="utf-8")))
    ordered = sorted(rows, key=lambda row: (row["family_id"], row["semantic_signature_id"]))
    positives = [row for row in ordered if int(row["allowed_count"]) > 0]
    sample = ordered[:sample_size]
    for row in positives:
        if row not in sample:
            sample.append(row)
    index = CompiledTerminalPairIndex(scope_dir.parents[4], CASE, SLOT)
    pair_cache = PersistentTwoRunCache(scope_dir.parents[4], CASE, SLOT)
    checks: list[dict[str, Any]] = []
    for row in sample:
        intervals_a, intervals_b, shift, middle_min, middle_max = _family_parts(row["family_key"])
        occupied_examples = json.loads(row["occupied_examples"])
        if not occupied_examples:
            occupied_examples = [[]]
        for occupied in occupied_examples[:3]:
            occupied_mask = _label_mask(int(value) for value in occupied)
            pair_path = pair_cache._path("pairs", (intervals_a, intervals_b))
            if pair_path.exists():
                direct = tuple(
                    state for state in pair_cache.terminal_pairs(intervals_a, intervals_b)
                    if not (_label_mask(value + shift for value in state.private) & occupied_mask)
                    and max(middle_max, max((0, *state.private)) + shift)
                    - min(middle_min, min((0, *state.private)) + shift) <= EDGE_COUNT
                )
            else:
                direct, _stats = index.query(
                    intervals_a,
                    intervals_b,
                    occupied_mask=occupied_mask,
                    left_shift=shift,
                    middle_min=middle_min,
                    middle_max=middle_max,
                    span_mode=True,
                )
            direct_masks = sorted({_label_mask(value + shift for value in state.private) for state in direct})
            expected_count = int(row["allowed_count"])
            checks.append({
                "family_id": row["family_id"],
                "semantic_signature_id": row["semantic_signature_id"],
                "occupied": occupied,
                "expected_allowed_count": expected_count,
                "direct_allowed_count": len(direct_masks),
                "match": len(direct_masks) == expected_count,
            })
        index.query_mem.clear()
        index.geometry_cache.mem.clear()
    result = {
        "status": "PASS" if all(item["match"] for item in checks) else "FAIL",
        "scope_dir": str(scope_dir),
        "sampled_signature_rows": len(sample),
        "differential_checks": len(checks),
        "positive_rows_in_scope": len(positives),
        "mismatches": [item for item in checks if not item["match"]],
        "checks": checks,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (scope_dir / "collision_signature_independent_verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope-dir", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=64)
    args = parser.parse_args()
    print(json.dumps(verify(args.scope_dir, args.sample_size), indent=2))
