#!/usr/bin/env python3
"""Differential benchmark for lazy left-existence queries on cached groups."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_C8_lazy_terminal_oracle import query_terminal_pair_states  # noqa: E402
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache  # noqa: E402
from edge63_C8_persistent_runner import compatible_states  # noqa: E402
from edge63_C8_two_run_cache import PersistentTwoRunCache  # noqa: E402
from edge63_C8_displacement_first import mask_for, values_for_case  # noqa: E402


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SPLIT_SLOT = "left_leaf_2"
LANGUAGE_VERSION = "C8.LevelB.v1"


def state_key(state) -> tuple:
    return state.private, state.min_value, state.max_value


def run(root: Path, limit: int) -> dict[str, object]:
    output = root / "tree1_C8" / "left_leaf_2_exact_v3" / "lazy_oracle_v1"
    output.mkdir(parents=True, exist_ok=True)
    progress_path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "progress.json"
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        progress = {}
    done = set(progress.get("done_group_ids", []))
    cache = PersistentMiddleGroupCache(root, CASE, SPLIT_SLOT)
    groups, _raw, _hit = cache.load_or_build_index(values_for_case(CASE))
    pair_cache = PersistentTwoRunCache(root, CASE, SPLIT_SLOT)
    rows = []
    old_seconds = 0.0
    lazy_seconds = 0.0
    old_states = 0
    lazy_states = 0
    lazy_prefix_steps = 0
    lazy_occupied_pruned = 0
    lazy_span_pruned = 0
    queries = 0
    checked_groups = 0
    checked_assignments = 0
    mismatch = None
    for middle_key, residuals in sorted(groups.items(), key=lambda item: (len(item[1]), item[0])):
        group_id = cache._group_path(middle_key).stem.replace(".pkl", "").replace("middle_group_", "")
        if group_id not in done:
            continue
        group, _ = cache.load_or_build_group(values_for_case(CASE), middle_key, residuals)
        checked_groups += 1
        for context in tuple(group["contexts"]):
            middle_values = tuple(context["all_values"])
            middle_mask = mask_for(middle_values)
            middle_min = min(middle_values)
            middle_max = max(middle_values)
            delta_left = int(context["delta_left"])
            for residual_key in residuals:
                if checked_assignments >= limit:
                    break
                blocks = dict(residual_key)
                left_a = tuple(blocks["left_leaf_1"])
                left_b = tuple(blocks["left_leaf_2"])
                started = time.time()
                full = pair_cache.terminal_pairs(left_a, left_b)
                old = compatible_states(full, middle_mask, middle_min, middle_max, -delta_left)
                old_seconds += time.time() - started
                started = time.time()
                lazy, lazy_stat = query_terminal_pair_states(
                    left_a,
                    left_b,
                    occupied_mask=middle_mask,
                    left_shift=-delta_left,
                    middle_min=middle_min,
                    middle_max=middle_max,
                )
                lazy_seconds += time.time() - started
                old_keys = {state_key(item[0]) for item in old}
                lazy_keys = {state_key(item) for item in lazy}
                if old_keys != lazy_keys and mismatch is None:
                    mismatch = {
                        "context_id": context["context_id"],
                        "left_a": left_a,
                        "left_b": left_b,
                        "full_only": [list(key[0]) for key in old_keys - lazy_keys],
                        "lazy_only": [list(key[0]) for key in lazy_keys - old_keys],
                    }
                queries += 1
                checked_assignments += 1
                old_states += len(full)
                lazy_states += len(lazy)
                lazy_prefix_steps += lazy_stat["local_raw_prefix_steps"]
                lazy_occupied_pruned += lazy_stat["local_occupied_pruned_branches"]
                lazy_span_pruned += lazy_stat["local_span_pruned_branches"]
            if checked_assignments >= limit:
                break
        if checked_assignments >= limit:
            break
    payload = {
        "status": "PASS" if mismatch is None else "FAIL",
        "scope": "cached completed Tree1 left_leaf_2 groups only",
        "groups_available_done": len(done),
        "groups_checked": checked_groups,
        "left_existence_queries": queries,
        "old_full_pair_states_visited": old_states,
        "lazy_pair_states_returned": lazy_states,
        "lazy_partial_prefix_steps": lazy_prefix_steps,
        "lazy_occupied_pruned_branches": lazy_occupied_pruned,
        "lazy_span_pruned_branches": lazy_span_pruned,
        "old_seconds": round(old_seconds, 6),
        "lazy_seconds": round(lazy_seconds, 6),
        "speedup": old_seconds / lazy_seconds if lazy_seconds else None,
        "mismatch": mismatch,
        "two_run_language": LANGUAGE_VERSION,
        "allocation_dedup_version": "ownership.v2",
        "terminal_pair_cache_version": "corrected.v2",
    }
    (output / "left_existence_stats.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (output / "left_existence_stats.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["status", "queries", "old_seconds", "lazy_seconds", "speedup", "old_states", "lazy_states", "prefix_steps"])
        writer.writeheader()
        writer.writerow({
            "status": payload["status"],
            "queries": queries,
            "old_seconds": payload["old_seconds"],
            "lazy_seconds": payload["lazy_seconds"],
            "speedup": payload["speedup"],
            "old_states": old_states,
            "lazy_states": lazy_states,
            "prefix_steps": lazy_prefix_steps,
        })
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.limit), ensure_ascii=False))


if __name__ == "__main__":
    main()
