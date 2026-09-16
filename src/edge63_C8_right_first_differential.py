"""Differentially audit LEFT_FIRST versus RIGHT_FIRST on completed groups."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from edge63_C8_allocation_prefilter import PrefilterStats, prefilter_group
from edge63_C8_displacement_first import mask_for, values_for_case
from edge63_C8_hybrid_terminal_backend import HybridTerminalBackend
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_persistent_runner import compatible_states, mask_shift
from edge63_C8_right_first_gate import RightSupportCache, residual_signature
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SPLIT_SLOT = "left_leaf_2"


def _key(state: Any) -> tuple[tuple[int, ...], int, int]:
    return tuple(state.private), int(state.min_value), int(state.max_value)


def _read_done(root: Path) -> list[str]:
    path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "progress.json"
    return list(json.loads(path.read_text(encoding="utf-8")).get("done_group_ids", []))


def _run_order(root: Path, done_ids: list[str], right_first: bool) -> dict[str, Any]:
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SPLIT_SLOT)
    pair_cache = PersistentTwoRunCache(root, CASE, SPLIT_SLOT)
    compiled = CompiledTerminalPairIndex(root, CASE, SPLIT_SLOT)
    hybrid = HybridTerminalBackend(pair_cache, compiled)
    support_cache = RightSupportCache(root, CASE, SPLIT_SLOT)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    done = set(done_ids)
    counters = {
        "groups": 0,
        "residual_candidates": 0,
        "right_support_queries": 0,
        "right_empty_candidates": 0,
        "left_queries_executed": 0,
        "left_queries_avoided": 0,
        "left_states": 0,
        "right_states": 0,
        "global_pairs": 0,
    }
    left_results: set[tuple] = set()
    global_results: set[tuple] = set()
    best_span: int | None = None
    started = time.perf_counter()

    for middle_key, residuals in sorted(groups.items(), key=lambda item: (len(item[1]), item[0])):
        group_id = middle_cache._group_path(middle_key).stem.replace(".pkl", "").replace("middle_group_", "")
        if group_id not in done:
            continue
        counters["groups"] += 1
        group, _ = middle_cache.load_or_build_group(values, middle_key, residuals)
        support_payload, _ = support_cache.build_or_load(group_id, group, pair_cache)
        candidates = prefilter_group(
            group,
            pair_cache,
            PrefilterStats(),
            context_envelope=False,
            lazy_left=True,
        )
        left_cache: dict[tuple, list[tuple]] = {}
        right_cache: dict[tuple, list[tuple]] = {}
        for candidate in candidates:
            counters["residual_candidates"] += 1
            context = candidate.context
            blocks = dict(candidate.residual_key)
            middle_values = tuple(context["all_values"])
            middle_mask = mask_for(middle_values)
            middle_min = min(middle_values)
            middle_max = max(middle_values)
            delta_left = int(context["delta_left"])
            delta_right = int(context["delta_right"])
            context_id = int(context["context_id"])
            left_key = (tuple(blocks["left_leaf_1"]), tuple(blocks["left_leaf_2"]), context_id)
            right_key = (tuple(blocks["right_leaf_1"]), tuple(blocks["right_leaf_2"]), context_id)

            def get_left() -> list[tuple]:
                if left_key not in left_cache:
                    result, _stats = hybrid.query(
                        left_key[0], left_key[1], occupied_mask=middle_mask,
                        left_shift=-delta_left, middle_min=middle_min,
                        middle_max=middle_max, span_mode=True,
                    )
                    left_cache[left_key] = result
                    counters["left_queries_executed"] += 1
                return left_cache[left_key]

            def get_right() -> list[tuple]:
                if right_key not in right_cache:
                    right_cache[right_key] = compatible_states(
                        candidate.right_states, middle_mask, middle_min, middle_max, delta_right
                    )
                return right_cache[right_key]

            if right_first:
                support_key = residual_signature(candidate.residual_key)
                counters["right_support_queries"] += 1
                supported = RightSupportCache.pair_supported(support_payload, context_id, support_key)
                if not supported:
                    counters["right_empty_candidates"] += 1
                    counters["left_queries_avoided"] += 1
                    continue
                right_states = get_right()
                if not right_states:
                    raise AssertionError("right support cache disagrees with exact right states")
                left_states = get_left()
            else:
                left_states = get_left()
                if not left_states:
                    continue
                right_states = get_right()

            counters["left_states"] += len(left_states)
            counters["right_states"] += len(right_states)
            for left_state, left_mask, left_low, left_high in left_states:
                left_results.add((group_id, context_id, residual_signature(candidate.residual_key), _key(left_state)))
                for right_state, right_mask, right_low, right_high in right_states:
                    if left_mask & right_mask:
                        continue
                    counters["global_pairs"] += 1
                    key = (group_id, context_id, residual_signature(candidate.residual_key), _key(left_state), _key(right_state))
                    global_results.add(key)
                    span = max(middle_max, left_high, right_high) - min(middle_min, left_low, right_low)
                    best_span = span if best_span is None else min(best_span, span)

    counters["seconds"] = time.perf_counter() - started
    return {
        "right_first": right_first,
        "counters": counters,
        "left_result_count": len(left_results),
        "global_result_count": len(global_results),
        "left_results": sorted(map(str, left_results)),
        "global_results": sorted(map(str, global_results)),
        "best_span": best_span if best_span is not None else "NONE",
        "hybrid_backend": dict(hybrid.stats),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--max-groups", type=int)
    args = parser.parse_args()
    done = _read_done(args.root)
    if args.max_groups is not None:
        done = done[: args.max_groups]
    left_first = _run_order(args.root, done, False)
    right_first = _run_order(args.root, done, True)
    equal = (
        left_first["left_results"] == right_first["left_results"]
        and left_first["global_results"] == right_first["global_results"]
        and left_first["best_span"] == right_first["best_span"]
    )
    payload = {
        "status": "PASS" if equal else "FAIL",
        "groups": len(done),
        "left_first": left_first,
        "right_first": right_first,
        "accepted_set_equal": equal,
        "two_run_language": "C8.LevelB.v1",
        "allocation_dedup_version": "ownership.v2",
        "terminal_pair_cache_version": "corrected.v2",
    }
    output = args.root / "tree1_C8" / "left_leaf_2_exact_v3" / "right_first_v1"
    output.mkdir(parents=True, exist_ok=True)
    (output / "right_first_differential.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (output / "right_first_performance.csv").write_text(
        "mode,groups,residual_candidates,right_support_queries,right_empty_candidates,left_queries_executed,left_queries_avoided,left_states,right_states,global_pairs,seconds\n"
        + "\n".join(
            ",".join(str(result["counters"].get(field, "")) for field in (
                "right_first", "groups", "residual_candidates", "right_support_queries", "right_empty_candidates",
                "left_queries_executed", "left_queries_avoided", "left_states", "right_states", "global_pairs", "seconds"
            ))
            for result in (left_first, right_first)
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": payload["status"], "groups": len(done), "left_first": left_first["counters"], "right_first": right_first["counters"]}, indent=2))


if __name__ == "__main__":
    main()
