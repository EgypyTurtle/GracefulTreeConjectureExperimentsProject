"""Independent differential check for the cheap right-support bitset index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from edge63_C8_displacement_first import mask_for, values_for_case
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_right_first_gate import RightSupportCache, residual_signature
from edge63_C8_right_support_index import RightSupportIndex
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_displacement_first_compact import EDGE_COUNT


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def local_shift(mask: int, shift: int) -> int:
    return mask << shift if shift >= 0 else mask >> (-shift)


def local_count(states: tuple[Any, ...], occupied_mask: int, middle_min: int, middle_max: int, shift: int) -> int:
    count = 0
    for state in states:
        shifted = local_shift(int(state.mask), shift)
        if shifted & occupied_mask:
            continue
        low = min(middle_min, int(state.min_value) + shift)
        high = max(middle_max, int(state.max_value) + shift)
        if high - low <= EDGE_COUNT:
            count += 1
    return count


def run(root: Path, max_groups: int = 12, max_contexts_per_group: int = 24) -> dict[str, Any]:
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SLOT)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    right_cache = RightSupportCache(root, CASE, SLOT)
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    support_index = RightSupportIndex(root, CASE, SLOT)
    manifest = json.loads((right_cache.output / "right_support_manifest.json").read_text(encoding="utf-8"))
    ids = list(manifest.get("done_group_ids", []))[:max_groups]
    by_id = {
        middle_cache._group_path(key).stem.replace(".pkl", "").replace("middle_group_", ""): (key, residuals)
        for key, residuals in groups.items()
    }
    checks = 0
    mismatches: list[dict[str, Any]] = []
    for group_id in ids:
        if group_id not in by_id:
            mismatches.append({"group_id": group_id, "reason": "group_missing_from_index"})
            continue
        payload_path = right_cache.path(group_id)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        middle_key, residuals = by_id[group_id]
        group, _ = middle_cache.load_or_build_group(values, middle_key, residuals)
        residual_keys = list(residuals.keys())
        contexts = tuple(group["contexts"][:max_contexts_per_group])
        for context in contexts:
            middle_values = tuple(int(x) for x in context["all_values"])
            occupied = mask_for(middle_values)
            middle_min = min(middle_values)
            middle_max = max(middle_values)
            shift = int(context["delta_right"])
            for residual_key in residual_keys:
                blocks = dict(residual_key)
                pair = (tuple(blocks["right_leaf_1"]), tuple(blocks["right_leaf_2"]))
                states = pair_cache.terminal_pairs(*pair)
                old_count = local_count(states, occupied, middle_min, middle_max, shift)
                compiled = support_index.get(*pair)
                new_count = compiled.compatible_count(
                    occupied_mask=occupied,
                    shift=shift,
                    middle_min=middle_min,
                    middle_max=middle_max,
                )
                checks += 1
                if old_count != new_count:
                    mismatches.append({
                        "group_id": group_id,
                        "context_id": int(context["context_id"]),
                        "residual_signature": residual_signature(residual_key),
                        "old_count": old_count,
                        "new_count": new_count,
                    })
                    if len(mismatches) >= 10:
                        break
            if len(mismatches) >= 10:
                break
        if len(mismatches) >= 10:
            break
    result = {
        "status": "PASS" if not mismatches else "FAIL",
        "groups_checked": min(len(ids), max_groups),
        "checks": checks,
        "mismatches": mismatches,
        "right_support_index": support_index.stats(),
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    output = root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_right_support_v1"
    output.mkdir(parents=True, exist_ok=True)
    (output / "right_support_index_differential.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--max-groups", type=int, default=12)
    parser.add_argument("--max-contexts-per-group", type=int, default=24)
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.max_groups, args.max_contexts_per_group), indent=2))


if __name__ == "__main__":
    main()
