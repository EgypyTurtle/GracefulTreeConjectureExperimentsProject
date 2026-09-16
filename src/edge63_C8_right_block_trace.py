"""Audit the eight raw right states attached to the first C8 left repairs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from edge63_C8_displacement_first import mask_for
from edge63_C8_displacement_first import values_for_case
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_persistent_runner import compatible_states, mask_shift
from edge63_C8_two_run_cache import PersistentTwoRunCache


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
OFFSET_SHIFT = 256


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _decode_mask(mask: int) -> list[int]:
    values: list[int] = []
    while mask:
        bit = mask & -mask
        values.append(bit.bit_length() - 1 - OFFSET_SHIFT)
        mask ^= bit
    return values


def _middle_role(context: dict[str, object], value: int) -> str:
    if value == 0:
        return "SHARED_ROOT_r2"
    roots = tuple(int(x) for x in context.get("roots", ()))
    if value in roots:
        return "SHARED_ROOT"
    central = context.get("central")
    if central is not None and value in tuple(int(x) for x in central.offsets):
        return "MIDDLE_LEAF_PRIVATE"
    bridge = context.get("bridge")
    if bridge is not None:
        if value in tuple(int(x) for x in bridge.left_offsets):
            return "LEFT_BRIDGE_OCCUPIED"
        if value in tuple(int(x) for x in bridge.right_offsets):
            return "RIGHT_BRIDGE_OCCUPIED"
    return "MIDDLE_OCCUPIED"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    out = args.out or (args.root / "tree1_C8" / "left_leaf_2_exact_v3" / "right_first_v1")
    survivor_csv = args.root / "tree1_C8" / "left_leaf_2_exact_v3" / "first_left_repair_analysis" / "compatible_left_16.csv"
    with survivor_csv.open(newline="", encoding="utf-8") as handle:
        survivors = list(csv.DictReader(handle))

    middle_cache = PersistentMiddleGroupCache(args.root, CASE, SLOT)
    values = values_for_case(CASE)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    groups_by_id = {}
    for middle_key, residuals in groups.items():
        group_id = middle_cache._group_path(middle_key).stem.replace(".pkl", "").replace("middle_group_", "")
        groups_by_id[group_id] = (middle_key, residuals)

    cache = PersistentTwoRunCache(args.root, CASE, SLOT)
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, int, int]] = set()
    for survivor in survivors:
        unique_key = (survivor["group_id"], int(survivor["context_id"]), int(survivor["residual_index"]))
        if unique_key in seen:
            continue
        seen.add(unique_key)
        if survivor["group_id"] not in groups_by_id:
            raise AssertionError(f"missing middle group {survivor['group_id']}")
        middle_key, residuals = groups_by_id[survivor["group_id"]]
        group, _group_hit = middle_cache.load_or_build_group(values, middle_key, residuals)
        context_matches = [
            context for context in group["contexts"]
            if int(context["context_id"]) == int(survivor["context_id"])
        ]
        if len(context_matches) != 1:
            raise AssertionError(
                f"expected one context for {unique_key}, found {len(context_matches)}"
            )
        context = context_matches[0]
        right_a = tuple(tuple(int(x) for x in item) for item in json.loads(survivor["right_leaf_1_intervals"]))
        right_b = tuple(tuple(int(x) for x in item) for item in json.loads(survivor["right_leaf_2_intervals"]))
        middle_values = tuple(int(x) for x in context["all_values"])
        middle_mask = mask_for(middle_values)
        table = cache.terminal_pairs(right_a, right_b)
        for state in table:
            shifted_mask = mask_shift(state.mask, int(survivor["delta_right"]))
            collision = shifted_mask & middle_mask
            low = min(int(survivor["middle_min"]), int(state.min_value) + int(survivor["delta_right"]))
            high = max(int(survivor["middle_max"]), int(state.max_value) + int(survivor["delta_right"]))
            span_overflow = high - low > 63
            if collision and span_overflow:
                reason = "MIDDLE_COLLISION_AND_SPAN"
            elif collision:
                reason = "MIDDLE_COLLISION"
            elif span_overflow:
                reason = "MIDDLE_SPAN_OVERFLOW"
            else:
                reason = "RIGHT_MIDDLE_COMPATIBLE"
            collision_values = _decode_mask(collision)
            rows.append({
                "group_id": survivor["group_id"],
                "context_id": survivor["context_id"],
                "residual_index": survivor["residual_index"],
                "right_behavior_id": int(state.state_id),
                "right_private_offsets_local": json.dumps(list(state.private)),
                "right_private_offsets_shifted": json.dumps([int(x) + int(survivor["delta_right"] ) for x in state.private]),
                "collision_offsets": json.dumps(collision_values),
                "collision_offset_roles": json.dumps({str(x): _middle_role(context, x) for x in collision_values}),
                "collision_size": len(collision_values),
                "shifted_min": int(state.min_value) + int(survivor["delta_right"]),
                "shifted_max": int(state.max_value) + int(survivor["delta_right"]),
                "middle_min": survivor["middle_min"],
                "middle_max": survivor["middle_max"],
                "span_overflow": span_overflow,
                "reason": reason,
            })

    _write_csv(out / "current16_right_block_analysis.csv", rows)
    census = Counter(row["reason"] for row in rows)
    summary = {
        "status": "PASS" if len(survivors) == 16 and len(rows) == len(seen) * 8 else "CHECK",
        "survivor_rows": len(survivors),
        "unique_survivor_contexts": len(seen),
        "raw_right_state_rows": len(rows),
        "expected_raw_right_state_rows": len(seen) * 8,
        "failure_census": dict(census),
        "right_middle_compatible_rows": sum(row["reason"] == "RIGHT_MIDDLE_COMPATIBLE" for row in rows),
        "two_run_language": "C8.LevelB.v1",
        "allocation_dedup_version": "ownership.v2",
        "terminal_pair_cache_version": "corrected.v2",
    }
    (out / "current16_right_block_analysis.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
