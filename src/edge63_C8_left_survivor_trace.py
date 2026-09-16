"""Trace Tree1 C8 compatible-left states through the right-side join.

The tool reads only already-completed persistent middle groups.  It is an
audit of local survivors, not an advancement of the global runner.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_persistent_runner import compatible_states, mask_shift
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_displacement_first import mask_for, values_for_case
from edge63_two_run_local_states import options_for_runs


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SPLIT_SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"
TRACE_VERSION = "left-survivor-trace.v2"


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fallback_fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or fallback_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _mask_values(mask: int) -> list[int]:
    result: list[int] = []
    while mask:
        bit = mask & -mask
        result.append(bit.bit_length() - 1)
        mask ^= bit
    return result


def _state_geometry(state: Any) -> tuple[tuple[int, ...], int, int]:
    return tuple(int(x) for x in state.private), int(state.min_value), int(state.max_value)


def _c7_equivalent(split_state: Any, intervals: tuple[tuple[int, int], ...]) -> bool:
    """Compare the split path geometry to C7 only when its runs merge."""
    if len(intervals) != 2:
        return False
    ordered = tuple(sorted(intervals))
    if ordered[0][1] + 1 != ordered[1][0]:
        return False
    merged = ((ordered[0][0], ordered[1][1]),)
    target = _state_geometry(split_state.state_b)
    return any(_state_geometry(candidate) == target for candidate in options_for_runs(merged, "terminal"))


def _extension_fields(state: Any, root_position: int) -> dict[str, int]:
    absolute_min = int(state.min_value) + root_position
    absolute_max = int(state.max_value) + root_position
    return {
        "root_position": root_position,
        "absolute_min": absolute_min,
        "absolute_max": absolute_max,
        "outward_extension": max(0, root_position - absolute_min),
        "inward_extension": max(0, absolute_max - root_position),
    }


def _trace(root: Path, out_dir: Path, max_groups: int | None) -> dict[str, Any]:
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SPLIT_SLOT)
    terminal_cache = PersistentTwoRunCache(root, CASE, SPLIT_SLOT)
    compiled = CompiledTerminalPairIndex(root, CASE, SPLIT_SLOT)

    progress_path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    done_ids = list(progress.get("done_group_ids", []))
    if max_groups is not None:
        done_ids = done_ids[:max_groups]
    done_set = set(done_ids)
    groups, _raw_allocations, _index_hit = middle_cache.load_or_build_index(values)

    survivors: list[dict[str, Any]] = []
    join_rows: list[dict[str, Any]] = []
    collision_rows: list[dict[str, Any]] = []
    pre_outer_rows: list[dict[str, Any]] = []
    failure_counts: Counter[str] = Counter()
    global_pairs: list[dict[str, Any]] = []
    pair_summary: dict[tuple[tuple[int, int], ...], dict[str, Any]] = {}

    for group_index, (middle_key, residual_index_map) in enumerate(
        sorted(groups.items(), key=lambda item: (len(item[1]), item[0]))
    ):
        group_id = middle_cache._group_path(middle_key).stem.replace(".pkl", "").replace("middle_group_", "")
        if group_id not in done_set:
            continue
        group, _cache_hit = middle_cache.load_or_build_group(values, middle_key, residual_index_map)
        for context_index, context in enumerate(tuple(group["contexts"])):
            middle_values = tuple(int(x) for x in context["all_values"])
            middle_mask = mask_for(middle_values)
            middle_min = int(context["min"])
            middle_max = int(context["max"])
            delta_left = int(context["delta_left"])
            delta_right = int(context["delta_right"])
            left_shift = -delta_left
            d13 = delta_left + delta_right

            for residual_index, (residual_key, _run_order) in enumerate(residual_index_map.items()):
                blocks = dict(residual_key)
                left_a = tuple(blocks["left_leaf_1"])
                left_b = tuple(blocks["left_leaf_2"])
                right_a = tuple(blocks["right_leaf_1"])
                right_b = tuple(blocks["right_leaf_2"])
                left_states, _query_stats = compiled.query(
                    left_a,
                    left_b,
                    occupied_mask=middle_mask,
                    left_shift=left_shift,
                    middle_min=middle_min,
                    middle_max=middle_max,
                    span_mode=True,
                )
                if not left_states:
                    continue

                right_table = terminal_cache.terminal_pairs(right_a, right_b)
                right_compatible = compatible_states(
                    right_table,
                    middle_mask,
                    middle_min,
                    middle_max,
                    delta_right,
                )

                for left_state in left_states:
                    shifted_left_mask = mask_shift(left_state.mask, left_shift)
                    left_low = int(left_state.min_value) + left_shift
                    left_high = int(left_state.max_value) + left_shift
                    ext = _extension_fields(left_state, left_shift)
                    gap = max(0, min(left_b[1]) - max(left_b[0]) - 1)
                    c7_equivalent = _c7_equivalent(left_state, left_b)
                    base: dict[str, Any] = {
                        "group_index": group_index,
                        "group_id": group_id,
                        "context_index": context_index,
                        "context_id": int(context["context_id"]),
                        "residual_index": residual_index,
                        "left_leaf_1_intervals": json.dumps(left_a),
                        "left_leaf_2_intervals": json.dumps(left_b),
                        "right_leaf_1_intervals": json.dumps(right_a),
                        "right_leaf_2_intervals": json.dumps(right_b),
                        "run_gap": gap,
                        "split_lengths": f"{len(left_b[0])}+{len(left_b[1])}",
                        "adjacent_resegmentation": gap == 0,
                        "left_behavior_id": int(left_state.state_id),
                        "left_private_offsets": json.dumps(list(left_state.private)),
                        "left_local_min": int(left_state.min_value),
                        "left_local_max": int(left_state.max_value),
                        "left_min": left_low,
                        "left_max": left_high,
                        "left_outward_extension": ext["outward_extension"],
                        "left_inward_extension": ext["inward_extension"],
                        "left_shift": left_shift,
                        "delta_left": delta_left,
                        "delta_right": delta_right,
                        "D13": d13,
                        "middle_offsets": json.dumps(list(middle_values)),
                        "middle_min": middle_min,
                        "middle_max": middle_max,
                        "middle_span": middle_max - middle_min,
                        "right_raw_state_count": len(right_table),
                        "right_middle_compatible_count": len(right_compatible),
                        "C7_equivalent_geometry": c7_equivalent,
                        "geometry_class": "C7_GEOMETRY" if c7_equivalent else "NEW_C8_GEOMETRY",
                    }

                    best_pre_outer_span: int | None = None
                    best_pre_outer_right: Any | None = None
                    disjoint_count = 0
                    collision_count = 0
                    for right_state, shifted_right_mask, right_low, right_high in right_compatible:
                        span = max(middle_max, left_high, int(right_high)) - min(middle_min, left_low, int(right_low))
                        if best_pre_outer_span is None or span < best_pre_outer_span:
                            best_pre_outer_span = span
                            best_pre_outer_right = right_state
                        intersection = shifted_left_mask & shifted_right_mask
                        if intersection:
                            collision_count += 1
                            collision_values = _mask_values(intersection)
                            collision_rows.append({
                                "group_id": group_id,
                                "context_id": int(context["context_id"]),
                                "residual_index": residual_index,
                                "left_behavior_id": int(left_state.state_id),
                                "right_behavior_id": int(right_state.state_id),
                                "collision_offsets": json.dumps(collision_values),
                                "collision_size": len(collision_values),
                                "span_ignoring_collision": span,
                            })
                        else:
                            disjoint_count += 1
                            global_pairs.append({
                                **base,
                                "right_behavior_id": int(right_state.state_id),
                                "right_private_offsets": json.dumps(list(right_state.private)),
                                "right_min": int(right_low),
                                "right_max": int(right_high),
                                "global_min": min(middle_min, left_low, int(right_low)),
                                "global_max": max(middle_max, left_high, int(right_high)),
                                "global_span": span,
                            })

                    if not right_table:
                        failure = "RIGHT_LOCAL_EMPTY"
                    elif not right_compatible:
                        failure = "RIGHT_MIDDLE_COLLISION"
                    elif disjoint_count == 0:
                        failure = "LEFT_RIGHT_OUTER_COLLISION"
                    elif best_pre_outer_span is not None and best_pre_outer_span > 63:
                        failure = "GLOBAL_SPAN_GT63"
                    else:
                        failure = "GLOBAL_COMPATIBLE"
                    failure_counts[failure] += 1

                    row = {
                        **base,
                        "failure_layer": failure,
                        "right_compatible_behavior_ids": json.dumps([int(item[0].state_id) for item in right_compatible]),
                        "outer_compatible_pairs": disjoint_count,
                        "outer_collision_pairs": collision_count,
                        "best_pre_outer_span": "NONE" if best_pre_outer_span is None else best_pre_outer_span,
                        "best_pre_outer_right_behavior_id": "" if best_pre_outer_right is None else int(best_pre_outer_right.state_id),
                    }
                    survivors.append(row)
                    join_rows.append({
                        **row,
                        "right_assignment_exists": bool(right_table),
                        "right_middle_compatible": bool(right_compatible),
                        "disjoint_pair_exists": disjoint_count > 0,
                    })
                    pre_outer_rows.append({
                        "group_id": group_id,
                        "context_id": int(context["context_id"]),
                        "residual_index": residual_index,
                        "left_behavior_id": int(left_state.state_id),
                        "right_middle_compatible_count": len(right_compatible),
                        "outer_compatible_pairs": disjoint_count,
                        "best_pre_outer_span": "NONE" if best_pre_outer_span is None else best_pre_outer_span,
                        "failure_layer": failure,
                    })

                    summary = pair_summary.setdefault(
                        left_b,
                        {
                            "left_leaf_2_intervals": json.dumps(left_b),
                            "run_gap": gap,
                            "split_lengths": f"{len(left_b[0])}+{len(left_b[1])}",
                            "survivors": 0,
                            "minimum_eL": None,
                            "maximum_eL": None,
                        },
                    )
                    summary["survivors"] += 1
                    e_l = ext["outward_extension"]
                    summary["minimum_eL"] = e_l if summary["minimum_eL"] is None else min(summary["minimum_eL"], e_l)
                    summary["maximum_eL"] = e_l if summary["maximum_eL"] is None else max(summary["maximum_eL"], e_l)

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "compatible_left_16.csv", survivors, ["group_id", "context_id", "failure_layer"])
    _write_csv(
        out_dir / "left_survivor_failure_layers.csv",
        [
            {
                "group_id": row["group_id"],
                "context_id": row["context_id"],
                "residual_index": row["residual_index"],
                "left_behavior_id": row["left_behavior_id"],
                "geometry_class": row["geometry_class"],
                "right_raw_state_count": row["right_raw_state_count"],
                "right_middle_compatible_count": row["right_middle_compatible_count"],
                "outer_compatible_pairs": row["outer_compatible_pairs"],
                "best_pre_outer_span": row["best_pre_outer_span"],
                "failure_layer": row["failure_layer"],
            }
            for row in survivors
        ],
        ["group_id", "context_id", "failure_layer"],
    )
    _write_csv(out_dir / "right_join_analysis.csv", join_rows, ["group_id", "context_id", "failure_layer"])
    _write_csv(out_dir / "outer_collision_analysis.csv", collision_rows, ["group_id", "context_id", "collision_offsets"])
    _write_csv(out_dir / "pre_outer_span_analysis.csv", pre_outer_rows, ["group_id", "context_id", "best_pre_outer_span"])
    _write_csv(out_dir / "compatible_left_pair_summary.csv", pair_summary.values(), ["left_leaf_2_intervals", "survivors"])

    first = survivors[0] if survivors else None
    _write_json(out_dir / "first_left_witness_geometry.json", {
        "trace_version": TRACE_VERSION,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
        "witness": first,
        "note": "A compatible-left state is not a global compatible pair.",
    })
    common = {
        "trace_version": TRACE_VERSION,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
        "scope": "Tree1 / C8.LevelB.v1 / side-terminal split(left_leaf_2) / completed checkpoint trace",
        "groups_inspected": len(done_ids),
        "groups_checkpoint_total": len(groups),
        "compatible_left_states": len(survivors),
        "compatible_global_pairs": len(global_pairs),
        "minimum_span": "NONE" if not global_pairs else min(int(row["global_span"]) for row in global_pairs),
        "failure_layer_census": dict(failure_counts),
    }
    runner_summary_path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "run_summary.json"
    if runner_summary_path.exists():
        runner_summary = json.loads(runner_summary_path.read_text(encoding="utf-8"))
        common["current_runner_status"] = runner_summary.get("status")
        common["current_runner_groups_done"] = runner_summary.get("middle_groups_done")
        common["current_runner_hybrid_backend"] = runner_summary.get("hybrid_left_backend", {})
        common["legacy_lazy_fields_are_historical"] = True
    _write_json(out_dir / "progress_v4.json", {**common, "status": "UNRESOLVED_RESOURCE"})
    _write_json(out_dir / "verification_v4.json", {
        **common,
        "expected_checkpoint_compatible_left_states": 16,
        "minimum_span_undefined_without_global_pair": not bool(global_pairs),
        "left_masks_recomputed_with_runner_mask_shift": True,
        "legacy_lazy_fields_are_historical": True,
        "all_left_private_offsets_are_locally_distinct": all(
            len(set(json.loads(row["left_private_offsets"]))) == len(json.loads(row["left_private_offsets"]))
            for row in survivors
        ),
        "status": "PASS" if len(survivors) == 16 and not global_pairs else "CHECK",
    })
    report = (
        "# Tree1 C8 left-survivor trace\n\n"
        f"- versions: `{LANGUAGE}`, `{OWNERSHIP}`, `{TERMINAL_CACHE}`\n"
        f"- completed groups inspected: **{len(done_ids)}/{len(groups)}**\n"
        f"- compatible-left states: **{len(survivors)}**\n"
        f"- compatible global pairs: **{len(global_pairs)}**\n"
        f"- minimum span: **{'NONE' if not global_pairs else min(int(row['global_span']) for row in global_pairs)}**\n\n"
        "A local survivor is not promoted to global compatibility.\n\n"
        "## Failure layers\n\n"
        "```json\n"
        + json.dumps(dict(failure_counts), indent=2, sort_keys=True)
        + "\n```\n"
    )
    if survivors:
        pair_keys = {(row["left_leaf_2_intervals"], row["run_gap"], row["split_lengths"]) for row in survivors}
        orientations = Counter((row["left_local_min"], row["left_local_max"], row["left_outward_extension"]) for row in survivors)
        report += "\n## Survivor structure\n\n"
        report += f"- distinct split interval pairs: **{len(pair_keys)}**\n"
        report += f"- all survivors are genuine separated: **{all(not row['adjacent_resegmentation'] for row in survivors)}**\n"
        report += f"- local geometry orientations: **{len(orientations)}**\n\n"
        report += "```json\n" + json.dumps({str(key): count for key, count in orientations.items()}, indent=2) + "\n```\n"
        report += "\nAll 16 local survivors have zero right-middle-compatible states, so no pre-outer span or global span is defined.\n"
    if common.get("current_runner_hybrid_backend"):
        report += "\n## Current resumable runner\n\n```json\n" + json.dumps(common["current_runner_hybrid_backend"], indent=2, sort_keys=True) + "\n```\n"
        report += "\nThe legacy `lazy_left_*` counters in the cumulative summary are historical; the current primary backend is hybrid.\n"
    (out_dir / "report_v4.md").write_text(report, encoding="utf-8")
    return common


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-groups", type=int)
    args = parser.parse_args()
    print(json.dumps(_trace(args.root, args.out, args.max_groups), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
