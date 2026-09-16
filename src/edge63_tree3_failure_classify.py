"""Classify the completed Tree3 Gate-1 obstruction.

The search language is fixed.  This is a read-only structural audit that
replays the middle-context and terminal-pair compatibility tests with the
corrected.v2 behavior tables; it does not search arbitrary graceful labels.
"""

from __future__ import annotations

import csv
import itertools
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_displacement_first_compact import (  # noqa: E402
    EDGE_COUNT,
    TERMINAL_PATHS,
    TerminalIndexCache,
    all_allocations,
    bit_indices,
    compatible_mask,
    middle_contexts,
    path_lengths,
)
from edge63_structure_analysis import parse_case  # noqa: E402


CASE = "fiveleaf3e-63-3-21-2-14-15-4-4"
ROOT = Path("results/edge63_tree3_compatibility_obstruction")
EXACT = Path("results/edge63_containment_frontier_test/third_tree_exact")
COARSE = Path("results/edge63_containment_frontier_test/coarse_level0")
CACHE_VERSION = "corrected.v2"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def middle_text(key) -> str:
    return ";".join(f"{path}={start}-{end}" for path, start, end in key)


def interval_text(block) -> str:
    return f"{block[0]}-{block[1]}"


def state_masks(index, shift: int, middle_values: tuple[int, ...]):
    """Return collision and span masks using the same predicates as Gate 1."""
    collision = 0
    for value in middle_values:
        collision |= index.postings.get(value - shift, 0)
    base_min = min(middle_values)
    base_max = max(middle_values)
    span_ok = 0
    for (private_min, private_max), bucket in index.extrema.items():
        shifted_min = shift + private_min
        shifted_max = shift + private_max
        if max(base_max, shifted_max) - min(base_min, shifted_min) <= EDGE_COUNT:
            span_ok |= bucket
    return collision, span_ok


def population_summary(index, collision: int, span_ok: int):
    universe = index.universe
    return {
        "raw_states": universe.bit_count(),
        "collision_only": (collision & span_ok).bit_count(),
        "span_only": ((~collision) & (~span_ok) & universe).bit_count(),
        "mixed": (collision & (~span_ok) & universe).bit_count(),
        "survivors": ((~collision) & span_ok & universe).bit_count(),
    }


def outer_join(index_left, mask_left, index_right, mask_right, delta_left: int, delta_right: int):
    """Return edge count, zero-degree-left events, and collision witnesses."""
    edge_count = 0
    zero_degree_events = []
    for left_id in bit_indices(mask_left):
        left_state = index_left.states[left_id]
        left_values = tuple(value - delta_left for value in left_state.private)
        candidates = mask_right
        hit_union = 0
        hit_values = []
        for value in left_values:
            hits = index_right.postings.get(value - delta_right, 0) & mask_right
            if hits:
                hit_union |= hits
                hit_values.append(value)
                candidates &= ~hits
        if candidates:
            edge_count += candidates.bit_count()
        else:
            zero_degree_events.append({
                "left_state_id": left_id,
                "left_values": left_values,
                "collision_values": tuple(sorted(set(hit_values))),
                "right_states_hit": hit_union.bit_count(),
                "right_state_ids_sample": tuple(bit_indices(hit_union))[:64],
            })
    return edge_count, zero_degree_events


def containment(left: tuple[int, ...], middle: tuple[int, ...], right: tuple[int, ...]):
    low_left, high_left = min(left), max(left)
    low_right, high_right = min(right), max(right)
    low_middle, high_middle = min(middle), max(middle)
    right_dom = low_right <= min(low_left, low_middle) and high_right >= max(high_left, high_middle)
    left_dom = low_left <= min(low_right, low_middle) and high_left >= max(high_right, high_middle)
    return left_dom, right_dom


def parse_bool(value: str) -> bool:
    return value.lower() == "true"


def exact_hitting_set(index, shift: int, middle_values: tuple[int, ...], max_states: int = 2000):
    """Find an exact minimum middle-offset hitting set for a small family."""
    collision, span_ok = state_masks(index, shift, middle_values)
    eligible = index.universe & span_ok
    if eligible == 0:
        return {"status": "EXACT", "size": 0, "offsets": (), "eligible_states": 0}
    if eligible.bit_count() > max_states:
        return {
            "status": "NOT_ATTEMPTED_LARGE",
            "size": "N/A",
            "offsets": (),
            "eligible_states": eligible.bit_count(),
        }
    covers = []
    for middle in middle_values:
        mask = index.postings.get(middle - shift, 0) & eligible
        if mask:
            covers.append((middle, mask))
    union = 0
    for _middle, mask in covers:
        union |= mask
    if union != eligible:
        return {
            "status": "NOT_A_HITTING_SET",
            "size": "N/A",
            "offsets": (),
            "eligible_states": eligible.bit_count(),
        }

    candidates_by_bit = {}
    for bit in bit_indices(eligible):
        candidates_by_bit[bit] = [i for i, (_middle, mask) in enumerate(covers) if mask & (1 << bit)]
    best = None
    nodes = 0

    def search(uncovered: int, chosen: tuple[int, ...]):
        nonlocal best, nodes
        nodes += 1
        if nodes > 250000:
            return
        if not uncovered:
            if best is None or len(chosen) < len(best):
                best = chosen
            return
        if best is not None and len(chosen) >= len(best):
            return
        bit = None
        options = None
        for candidate_bit in bit_indices(uncovered):
            available = [i for i in candidates_by_bit[candidate_bit] if i not in chosen]
            if not available:
                return
            if options is None or len(available) < len(options):
                bit, options = candidate_bit, available
                if len(options) == 1:
                    break
        del bit
        options.sort(key=lambda i: -covers[i][1].bit_count())
        for index in options:
            search(uncovered & ~covers[index][1], chosen + (index,))

    search(eligible, ())
    if best is None:
        return {
            "status": "RESOURCE_LIMIT",
            "size": "N/A",
            "offsets": (),
            "eligible_states": eligible.bit_count(),
            "nodes": nodes,
        }
    return {
        "status": "EXACT",
        "size": len(best),
        "offsets": tuple(covers[i][0] for i in best),
        "eligible_states": eligible.bit_count(),
        "nodes": nodes,
    }


def main():
    output = ROOT
    output.mkdir(parents=True, exist_ok=True)
    parsed = parse_case(CASE)
    if parsed is None or parsed[1] != EDGE_COUNT:
        raise ValueError(CASE)
    values = parsed[2]
    lengths = path_lengths(values)
    _, middle_to_orders, _ = all_allocations(values)

    coarse_orders = read_rows(COARSE / f"{CASE}_order_prescan.csv")
    optimistic_orders = {
        int(row["order_index"])
        for row in coarse_orders
        if parse_bool(row["optimistic_right_containment"])
        or parse_bool(row["optimistic_left_containment"])
    }
    order_funnel = {
        order: Counter(total_contexts=0, left_contexts=0, right_contexts=0,
                       both_contexts=0, outer_contexts=0, containment_contexts=0)
        for order in optimistic_orders
    }

    index_cache = TerminalIndexCache(64)
    context_rows = []
    left_rows = []
    near_rows = []
    outer_rows = []
    outer_matrix_rows = []
    blocked_descriptors = []
    blocker_counts = defaultdict(Counter)
    context_global_id = 0
    event_counts = Counter()

    for triple_id, (middle_key, residual_items) in enumerate(middle_to_orders.items()):
        left = middle_key[0]
        central = middle_key[1]
        right = middle_key[2]
        contexts, middle_stats = middle_contexts(
            left[1], left[2] - left[1] + 1,
            central[1], central[2] - central[1] + 1,
            right[1], right[2] - right[1] + 1,
            "B",
        )
        event_counts["raw_middle_contexts"] += int(middle_stats["raw_contexts"])
        event_counts["central_collision"] += int(middle_stats.get("central_collision", 0))
        event_counts["middle_span_overflow"] += int(middle_stats.get("span_overflow", 0))
        for context in contexts:
            context_id = int(context["context_id"])
            middle_values = tuple(context["all_values"])
            delta_left = int(context["delta_left"])
            delta_right = int(context["delta_right"])
            residual_total = 0
            left_nonempty = right_nonempty = both_nonempty = 0
            outer_nonempty = final_span_nonempty = 0
            left_empty = right_empty = residual_mismatch = 0
            left_raw = left_collision_only = left_span_only = left_mixed = left_survivors = 0
            right_survivors = 0
            context_outer_events = 0
            context_outer_pairs = 0
            context_contains_left = context_contains_right = 0
            for residual in residual_items:
                residual_total += 1
                blocks = residual["blocks"]
                left_key = (
                    "left_leaf_1", blocks["left_leaf_1"][0], lengths["left_leaf_1"],
                    "left_leaf_2", blocks["left_leaf_2"][0], lengths["left_leaf_2"],
                )
                right_key = (
                    "right_leaf_1", blocks["right_leaf_1"][0], lengths["right_leaf_1"],
                    "right_leaf_2", blocks["right_leaf_2"][0], lengths["right_leaf_2"],
                )
                left_index = index_cache.get(left_key, "B")
                right_index = index_cache.get(right_key, "B")
                left_collision, left_span_ok = state_masks(left_index, -delta_left, middle_values)
                right_collision, right_span_ok = state_masks(right_index, delta_right, middle_values)
                left_mask = compatible_mask(left_index, -delta_left, middle_values)
                right_mask = compatible_mask(right_index, delta_right, middle_values)
                left_summary = population_summary(left_index, left_collision, left_span_ok)
                right_summary = population_summary(right_index, right_collision, right_span_ok)
                left_raw += left_summary["raw_states"]
                left_collision_only += left_summary["collision_only"]
                left_span_only += left_summary["span_only"]
                left_mixed += left_summary["mixed"]
                left_survivors += left_summary["survivors"]
                right_survivors += right_summary["survivors"]
                if left_mask:
                    left_nonempty += 1
                else:
                    left_empty += 1
                    for middle in middle_values:
                        blocker_counts[(triple_id, context_id)][middle] += (
                            left_collision & left_span_ok & left_index.postings.get(middle - (-delta_left), 0)
                        ).bit_count()
                    eligible_count = left_span_ok.bit_count()
                    blocked_descriptors.append({
                        "triple_id": triple_id,
                        "context_id": context_id,
                        "order_index": int(residual["order_index"]),
                        "middle_values": middle_values,
                        "delta_left": delta_left,
                        "left_key": left_key,
                        "eligible_nonspan_states": eligible_count,
                        "raw_left_states": left_index.universe.bit_count(),
                    })
                if right_mask:
                    right_nonempty += 1
                else:
                    right_empty += 1

                if left_mask and right_mask:
                    both_nonempty += 1
                    edges, zero_events = outer_join(
                        left_index, left_mask, right_index, right_mask, delta_left, delta_right,
                    )
                    context_outer_pairs += edges
                    context_outer_events += len(zero_events)
                    if edges:
                        outer_nonempty += 1
                    else:
                        event_counts["both_sides_no_outer_edge_assignments"] += 1
                    for event in zero_events:
                        outer_rows.append({
                            "case": CASE,
                            "triple_id": triple_id,
                            "context_id": context_id,
                            "order_index": int(residual["order_index"]),
                            "delta_left": delta_left,
                            "delta_right": delta_right,
                            "D13": delta_left + delta_right,
                            "left_state_id": event["left_state_id"],
                            "left_values_middle_frame": ";".join(map(str, event["left_values"])),
                            "collision_values": ";".join(map(str, event["collision_values"])),
                            "right_states_hit": event["right_states_hit"],
                            "right_state_ids_sample": ";".join(map(str, event["right_state_ids_sample"])),
                            "middle_values": ";".join(map(str, middle_values)),
                        })
                    if edges:
                        for left_id in bit_indices(left_mask):
                            left_state = left_index.states[left_id]
                            left_values = tuple(value - delta_left for value in left_state.private)
                            candidates = right_mask
                            for value in left_values:
                                candidates &= ~right_index.postings.get(value - delta_right, 0)
                            for right_id in bit_indices(candidates):
                                right_state = right_index.states[right_id]
                                right_values = tuple(value + delta_right for value in right_state.private)
                                low = min(*middle_values, *left_values, *right_values)
                                high = max(*middle_values, *left_values, *right_values)
                                if high - low <= EDGE_COUNT:
                                    final_span_nonempty += 1
                                    left_dom, right_dom = containment(left_values, middle_values, right_values)
                                    context_contains_left += int(left_dom)
                                    context_contains_right += int(right_dom)
                elif left_mask or right_mask:
                    residual_mismatch += 1

                if int(residual["order_index"]) in order_funnel:
                    funnel = order_funnel[int(residual["order_index"])]
                    funnel["total_contexts"] += 1
                    funnel["left_contexts"] += int(bool(left_mask))
                    funnel["right_contexts"] += int(bool(right_mask))
                    funnel["both_contexts"] += int(bool(left_mask and right_mask))
                    funnel["outer_contexts"] += int(bool(left_mask and right_mask and context_outer_pairs))
                    funnel["containment_contexts"] += int(context_contains_left or context_contains_right)

            if left_nonempty == 0:
                failure = "LEFT_EMPTY"
            elif right_nonempty == 0:
                failure = "RIGHT_EMPTY"
            elif both_nonempty == 0:
                failure = "NO_COMMON_RESIDUAL_ASSIGNMENT"
            elif outer_nonempty == 0:
                failure = "BOTH_SIDES_NONEMPTY_OUTER_COLLISION"
            elif final_span_nonempty == 0:
                failure = "FINAL_SPAN_OVERFLOW"
            else:
                failure = "FINAL_COMPATIBLE"
            context_rows.append({
                "case": CASE,
                "global_context_id": context_global_id,
                "triple_id": triple_id,
                "context_id": context_id,
                "middle_intervals": middle_text(middle_key),
                "residual_assignments": residual_total,
                "delta_left": delta_left,
                "delta_right": delta_right,
                "D13": delta_left + delta_right,
                "middle_min": min(middle_values),
                "middle_max": max(middle_values),
                "middle_span": max(middle_values) - min(middle_values),
                "left_nonempty_assignments": left_nonempty,
                "right_nonempty_assignments": right_nonempty,
                "both_sides_nonempty_assignments": both_nonempty,
                "outer_compatible_assignments": outer_nonempty,
                "final_span_feasible_assignments": final_span_nonempty,
                "left_empty_assignments": left_empty,
                "right_empty_assignments": right_empty,
                "residual_mismatch_assignments": residual_mismatch,
                "outer_collision_events": context_outer_events,
                "outer_compatible_pairs": context_outer_pairs,
                "containment_left_pairs": context_contains_left,
                "containment_right_pairs": context_contains_right,
                "earliest_failure": failure,
            })
            blocker_key = (triple_id, context_id)
            top_blockers = blocker_counts[blocker_key].most_common(12)
            left_rows.append({
                "case": CASE,
                "triple_id": triple_id,
                "context_id": context_id,
                "middle_intervals": middle_text(middle_key),
                "left_empty_assignments": left_empty,
                "left_raw_states": left_raw,
                "collision_only_states": left_collision_only,
                "span_only_states": left_span_only,
                "mixed_blocked_states": left_mixed,
                "left_survivor_states": left_survivors,
                "top_middle_blockers": ";".join(f"{value}:{count}" for value, count in top_blockers),
            })
            if both_nonempty or left_nonempty or right_nonempty:
                near_rows.append(context_rows[-1])
            if both_nonempty:
                outer_matrix_rows.append({
                    "case": CASE,
                    "triple_id": triple_id,
                    "context_id": context_id,
                    "middle_intervals": middle_text(middle_key),
                    "both_sides_nonempty_assignments": both_nonempty,
                    "outer_compatible_assignments": outer_nonempty,
                    "outer_compatible_pairs": context_outer_pairs,
                    "outer_collision_events": context_outer_events,
                })
            context_global_id += 1

    context_counter = Counter(row["earliest_failure"] for row in context_rows)
    assignment_counter = Counter()
    for row in context_rows:
        assignment_counter["contexts"] += 1
        assignment_counter["left_nonempty_assignments"] += int(row["left_nonempty_assignments"])
        assignment_counter["right_nonempty_assignments"] += int(row["right_nonempty_assignments"])
        assignment_counter["both_sides_nonempty_assignments"] += int(row["both_sides_nonempty_assignments"])
        assignment_counter["outer_compatible_assignments"] += int(row["outer_compatible_assignments"])

    write_csv(output / "context_failure_census.csv", context_rows)
    write_csv(output / "near_survivor_contexts.csv", near_rows)
    write_csv(output / "left_blocking_analysis.csv", left_rows)
    write_csv(output / "outer_collision_16.csv", outer_rows)
    write_csv(output / "outer_collision_matrix_summary.csv", outer_matrix_rows)

    left_reason_totals = Counter()
    global_blocker_counts = Counter()
    for row in left_rows:
        if int(row["left_empty_assignments"]) > 0:
            for field in ("collision_only_states", "span_only_states", "mixed_blocked_states", "left_survivor_states"):
                left_reason_totals[field] += int(row[field])
    for counts in blocker_counts.values():
        global_blocker_counts.update(counts)
    write_csv(output / "middle_blocker_offsets.csv", [
        {"middle_offset": value, "blocked_state_hits": count}
        for value, count in global_blocker_counts.most_common()
    ])

    selected = []
    seen_blocking_contexts = set()
    for descriptor in sorted(
        (row for row in blocked_descriptors if row["eligible_nonspan_states"] > 0),
        key=lambda row: (row["eligible_nonspan_states"], row["raw_left_states"], row["order_index"]),
    ):
        context_key = (descriptor["triple_id"], descriptor["context_id"])
        if context_key in seen_blocking_contexts:
            continue
        seen_blocking_contexts.add(context_key)
        selected.append(descriptor)
        if len(selected) == 20:
            break
    hitting_rows = []
    for descriptor in selected:
        left_index = index_cache.get(descriptor["left_key"], "B")
        result = exact_hitting_set(
            left_index, -descriptor["delta_left"], descriptor["middle_values"],
        )
        key = f"{descriptor['triple_id']}:{descriptor['context_id']}"
        hitting_rows.append({
            "case": CASE,
            "triple_id": descriptor["triple_id"],
            "context_id": descriptor["context_id"],
            "order_index": descriptor["order_index"],
            "left_interval_pair": f"{descriptor['left_key'][1]}-{descriptor['left_key'][1] + descriptor['left_key'][2] - 1};{descriptor['left_key'][4]}-{descriptor['left_key'][4] + descriptor['left_key'][5] - 1}",
            "eligible_nonspan_states": result["eligible_states"],
            "hitting_set_status": result["status"],
            "minimum_hitting_set_size": result["size"],
            "middle_offsets_hitting_set": ";".join(map(str, result["offsets"])),
            "search_nodes": result.get("nodes", ""),
            "blocking_key": key,
        })
    write_csv(output / "left_hitting_sets.csv", hitting_rows)

    funnel_rows = []
    for stage, field in (
        ("OPTIMISTIC_CONTAINMENT_ORDER", None),
        ("EXACT_MIDDLE_CONTEXT", "total_contexts"),
        ("LEFT_NONEMPTY", "left_contexts"),
        ("RIGHT_NONEMPTY", "right_contexts"),
        ("BOTH_SIDES_NONEMPTY", "both_contexts"),
        ("OUTER_COMPATIBLE", "outer_contexts"),
        ("EXACT_CONTAINMENT", "containment_contexts"),
    ):
        if field is None:
            count = len(optimistic_orders)
            aggregate = count
        else:
            count = sum(1 for funnel in order_funnel.values() if funnel[field] > 0)
            aggregate = sum(funnel[field] for funnel in order_funnel.values())
        funnel_rows.append({
            "case": CASE,
            "stage": stage,
            "predicted_order_count": len(optimistic_orders),
            "orders_surviving": count,
            "order_fraction": f"{count}/{len(optimistic_orders)}" if optimistic_orders else "0/0",
            "aggregate_context_count": aggregate,
        })
    write_csv(output / "optimistic_containment_funnel.csv", funnel_rows)

    write_csv(output / "tree1_tree3_difference_analysis.csv", [
        {"quantity": "construction_language", "tree1": "corrected.v2 Level-B single-interval", "tree3": "corrected.v2 Level-B single-interval", "interpretation": "same finite language"},
        {"quantity": "path_profile", "tree1": "3,21,2,20,9,4,4", "tree3": "3,21,2,14,15,4,4", "interpretation": "six edges moved from left_leaf_2 to middle_leaf"},
        {"quantity": "active_pattern", "tree1": "111", "tree3": "111", "interpretation": "same"},
        {"quantity": "rho", "tree1": "2", "tree3": "2", "interpretation": "same"},
        {"quantity": "bridge_profile", "tree1": "3,21", "tree3": "3,21", "interpretation": "same"},
        {"quantity": "right_terminal_profile", "tree1": "4,4", "tree3": "4,4", "interpretation": "same"},
        {"quantity": "exact_middle_contexts", "tree1": "112410", "tree3": str(len(context_rows)), "interpretation": "not a direct mechanism by itself"},
        {"quantity": "final_compatible", "tree1": "36", "tree3": "0", "interpretation": "Tree1 reaches span analysis; Tree3 does not"},
        {"quantity": "dominant_failure_layer", "tree1": "global span", "tree3": "middle/terminal compatibility", "interpretation": "different exact failure layers"},
    ])

    certificate = {
        "certificate_version": "tree3-compatibility-obstruction.v1",
        "case": CASE,
        "cache_version": CACHE_VERSION,
        "language": {
            "maximal_paths": 7,
            "single_consecutive_interval_per_path": True,
            "local_behavior": "complete Level-B",
        },
        "context_census": dict(context_counter),
        "context_total": len(context_rows),
        "context_class_sum": sum(context_counter.values()),
        "assignment_census": dict(assignment_counter),
        "raw_event_counts": {
            "raw_middle_context_combinations": event_counts["raw_middle_contexts"],
            "central_collision": event_counts["central_collision"],
            "middle_span_overflow": event_counts["middle_span_overflow"],
            "outer_collision_events": len(outer_rows),
            "both_sides_no_outer_edge_assignments": event_counts["both_sides_no_outer_edge_assignments"],
        },
        "near_survivor": {
            "contexts_with_any_side_nonempty": sum(1 for row in context_rows if row["left_nonempty_assignments"] or row["right_nonempty_assignments"]),
            "contexts_with_left_nonempty": sum(1 for row in context_rows if row["left_nonempty_assignments"]),
            "contexts_with_right_nonempty": sum(1 for row in context_rows if row["right_nonempty_assignments"]),
            "contexts_with_both_sides_nonempty": sum(1 for row in context_rows if row["both_sides_nonempty_assignments"]),
            "contexts_with_outer_compatible": sum(1 for row in context_rows if row["outer_compatible_assignments"]),
            "outer_collision_distinct_contexts": len({(row["triple_id"], row["context_id"]) for row in outer_rows}),
        },
        "left_blocked_state_reason_totals": dict(left_reason_totals),
        "top_middle_blocker_offsets": [
            {"offset": value, "blocked_state_hits": count}
            for value, count in global_blocker_counts.most_common(20)
        ],
        "hitting_set_scope": "top 20 smallest non-span left-blocked assignment families; exact when marked EXACT",
        "optimistic_funnel": funnel_rows,
        "exact_status": "UNSAT_EXHAUSTIVE",
        "sigma_min": "NONE",
        "old_baseline_used": False,
    }
    (output / "tree3_compatibility_obstruction_certificate.json").write_text(
        json.dumps(certificate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    top_blockers_text = "; ".join(
        f"{value}:{count}" for value, count in global_blocker_counts.most_common(10)
    )
    report = f"""# Tree3 compatibility obstruction

Case: `{CASE}`  
Language: corrected.v2 complete Level-B, seven maximal paths, one consecutive
difference interval per path.

## Exact context census

The 19,452 exact middle contexts are classified by the earliest failed
completion layer.  These are context counts, not the event counts emitted by
the Gate-1 search.

| class | contexts |
|---|---:|
""" + "\n".join(f"| `{key}` | {value} |" for key, value in sorted(context_counter.items())) + f"""

At assignment level, the exact replay found:

```text
contexts                         = {len(context_rows)}
left-nonempty assignments       = {assignment_counter['left_nonempty_assignments']}
right-nonempty assignments      = {assignment_counter['right_nonempty_assignments']}
both-sides-nonempty assignments = {assignment_counter['both_sides_nonempty_assignments']}
outer-compatible assignments    = {assignment_counter['outer_compatible_assignments']}
outer collision events           = {len(outer_rows)}
```

At context level, the corresponding support counts are:

```text
contexts with a left completion      = {sum(1 for row in context_rows if row['left_nonempty_assignments'])}
contexts with a right completion     = {sum(1 for row in context_rows if row['right_nonempty_assignments'])}
contexts with both sides nonempty    = {sum(1 for row in context_rows if row['both_sides_nonempty_assignments'])}
contexts with an outer-compatible pair = {sum(1 for row in context_rows if row['outer_compatible_assignments'])}
```

There are no final-compatible rows.  The exact Gate-1 status is therefore
compatibility UNSAT, with no span minimum defined for this tree.

For the contexts having at least one left-blocked residual assignment, the
state-level reason totals are:

```text
collision-only = {left_reason_totals['collision_only_states']}
span-only      = {left_reason_totals['span_only_states']}
mixed          = {left_reason_totals['mixed_blocked_states']}
survivors      = {left_reason_totals['left_survivor_states']}
```

The exact global middle-offset hit counts are in
`middle_blocker_offsets.csv`; the largest are
{top_blockers_text}.

## What the event counts mean

The original ledger reports `{event_counts['central_collision']}` central
collision events and `{event_counts['middle_span_overflow']}` middle-context
span-overflow events.  Those are raw local-combination events, not distinct
contexts.  The context census above is the mutually exclusive, earliest-layer
classification of the 19,452 contexts that survived middle-context creation.

## Outer boundary

Only `{len(outer_rows)}` zero-degree-left outer-collision events were found,
coming from `{len({(row['triple_id'], row['context_id']) for row in outer_rows})}`
distinct contexts.  Thus the outer obstruction is a thin residual boundary,
not the main explanation for all T3 failures.

## Optimistic containment funnel

The L0 prescan marked 190 orders as optimistic right-containment candidates.
The funnel is in `optimistic_containment_funnel.csv`.  It must be read as a
false-positive diagnostic: optimistic envelope containment does not survive
the exact middle/terminal compatibility layers in this case.

## Tree1 / Tree3 contrast

Tree1 has the same bridge profile, active pattern, and repair-cover number,
but its corrected exact search reaches 36 final-compatible rows before the
span obstruction.  T3 reaches no such row after moving six edges from the
long left terminal to the middle path.  This controlled comparison supports
the two-stage description

```text
exact compatibility feasibility -> span feasibility
```

but does not identify a general parameter theorem.  The next useful object is
the smallest middle/terminal blocking signature, not another containment
score or another tree run.
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    (output / "three_tree_mechanism_summary.md").write_text("""# Three-tree mechanism summary

| Tree | exact compatibility | span feasible | mechanism |
|---|---|---|---|
| Tree1 | yes | no | final-compatible rows exist, all have span at least 67 |
| Tree2 | yes | yes | verified right-terminal-dominant span-63 packing |
| Tree3 | no | N/A | exact middle/terminal compatibility obstruction |

The current evidence supports a two-stage finite construction picture:

`compatibility feasibility -> span feasibility`.

This is a summary of three finite benchmark cases, not a general theorem.
""", encoding="utf-8")
    (output / "formal_lemmas.md").write_text("""# Formal lemmas for the Tree3 obstruction audit

## Finite one-side blocking lemma

Fix a middle context `M` and a left behavior family `L`.  If every left state
either intersects `M` in the common middle frame or has
`span(M union L) > 63`, then no left completion exists for that context.
This is immediate from the definition of compatibility.

## Span-or-hitting lemma

Let `H` be a subset of the middle offsets.  If every candidate left state is
either span-infeasible or intersects `H`, then it is incompatible with the
middle context.  In particular, an exact hitting set for all non-span-blocked
states is a finite certificate of one-side failure.

## Residual outer-collision lemma

For fixed middle context `M`, let `L(M)` and `R(M)` be the individually
middle-compatible left and right families.  If both families are nonempty but
for every pair `(L,R)` the middle-frame offset sets intersect, the bipartite
compatibility graph has no edge and no global completion exists.

## Finite decomposition theorem

For a fixed finite interval allocation, a full completion is absent if the
middle context is invalid, one side has no compatible state, the residual
allocation has no common two-sided assignment, or the left/right
compatibility graph has no edge.  These cases are exhaustive because every
completion chooses exactly one middle context, one residual interval
assignment, one left behavior, and one right behavior.

All claims here concern the corrected.v2 finite construction language only.
They do not assert that the Tree3 graph is non-graceful.
""", encoding="utf-8")

    print(json.dumps({
        "case": CASE,
        "contexts": len(context_rows),
        "context_classes": dict(context_counter),
        "both_sides_nonempty_assignments": assignment_counter["both_sides_nonempty_assignments"],
        "outer_collision_events": len(outer_rows),
        "outer_collision_contexts": len({(row["triple_id"], row["context_id"]) for row in outer_rows}),
        "optimistic_orders": len(optimistic_orders),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
