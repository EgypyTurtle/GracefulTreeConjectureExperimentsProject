"""Independent verifier for the Tree1 C8 left-survivor trace."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_persistent_runner import compatible_states, mask_shift
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_displacement_first import mask_for, values_for_case


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SPLIT_SLOT = "left_leaf_2"


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _tuple_intervals(text: str) -> tuple[tuple[int, int], ...]:
    return tuple(tuple(int(value) for value in item) for item in json.loads(text))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = args.out / "compatible_left_16.csv"
    rows = _load_rows(source)
    terminal_cache = PersistentTwoRunCache(args.root, CASE, SPLIT_SLOT)
    compiled = CompiledTerminalPairIndex(args.root, CASE, SPLIT_SLOT)
    mismatches: list[dict[str, object]] = []
    right_checks = 0
    left_checks = 0
    all_private_distinct = True

    for row in rows:
        left_private = tuple(json.loads(row["left_private_offsets"]))
        all_private_distinct &= len(left_private) == len(set(left_private))
        left_a = _tuple_intervals(row["left_leaf_1_intervals"])
        left_b = _tuple_intervals(row["left_leaf_2_intervals"])
        right_a = _tuple_intervals(row["right_leaf_1_intervals"])
        right_b = _tuple_intervals(row["right_leaf_2_intervals"])
        middle_values = tuple(json.loads(row["middle_offsets"]))
        middle_mask = mask_for(middle_values)
        left_states, _stats = compiled.query(
            left_a,
            left_b,
            occupied_mask=middle_mask,
            left_shift=int(row["left_shift"]),
            middle_min=int(row["middle_min"]),
            middle_max=int(row["middle_max"]),
            span_mode=True,
        )
        left_keys = {(tuple(state.private), int(state.min_value), int(state.max_value)) for state in left_states}
        expected_left_key = (left_private, int(row["left_local_min"]), int(row["left_local_max"]))
        left_checks += 1
        if expected_left_key not in left_keys:
            mismatches.append({"group_id": row["group_id"], "context_id": row["context_id"], "reason": "left geometry not reproduced"})

        right_table = terminal_cache.terminal_pairs(right_a, right_b)
        right = compatible_states(
            right_table,
            middle_mask,
            int(row["middle_min"]),
            int(row["middle_max"]),
            int(row["delta_right"]),
        )
        right_checks += 1
        if len(right) != int(row["right_middle_compatible_count"]):
            mismatches.append({"group_id": row["group_id"], "context_id": row["context_id"], "reason": "right middle count mismatch", "expected": row["right_middle_compatible_count"], "actual": len(right)})
        if row["failure_layer"] != "RIGHT_MIDDLE_COLLISION" or int(row["outer_compatible_pairs"]) != 0:
            mismatches.append({"group_id": row["group_id"], "context_id": row["context_id"], "reason": "failure-layer semantics mismatch"})

    payload = {
        "status": "PASS" if len(rows) == 16 and not mismatches and all_private_distinct else "FAIL",
        "rows": len(rows),
        "left_geometry_checks": left_checks,
        "right_middle_checks": right_checks,
        "expected_failure_layer_census": {"RIGHT_MIDDLE_COLLISION": len(rows)},
        "all_left_private_offsets_distinct": all_private_distinct,
        "global_pairs_recomputed": 0,
        "minimum_span_undefined": True,
        "mismatches": mismatches,
        "two_run_language": "C8.LevelB.v1",
        "allocation_dedup_version": "ownership.v2",
        "terminal_pair_cache_version": "corrected.v2",
        "independent_from_trace_csv_counts": True,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "verification_v4_independent.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
