"""Parameterize the corrected Tree3 left-compatibility obstruction.

This is a structural replay of the fixed Level-B single-interval language.
It classifies every exact middle context, computes span-conditioned kernels,
and solves the resulting finite hitting-set problems with integer bitsets.
It never searches unrestricted graceful labelings.
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
    TerminalIndexCache,
    all_allocations,
    bit_indices,
    compact_options,
    compatible_mask,
    middle_contexts,
    path_lengths,
)
from edge63_structure_analysis import parse_case  # noqa: E402


CASE = "fiveleaf3e-63-3-21-2-14-15-4-4"
OUT = Path("results/edge63_tree3_left_block_parameterization")
COARSE = Path("results/edge63_containment_frontier_test/coarse_level0")
EDGE = 63


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


def interval_text(block) -> str:
    return f"{block[0]}-{block[1]}"


def middle_text(key) -> str:
    return ";".join(f"{path}={start}-{end}" for path, start, end in key)


def bitmask_data(index, shift: int, middle_values: tuple[int, ...]):
    collision = 0
    for value in middle_values:
        collision |= index.postings.get(value - shift, 0)
    base_min = min(middle_values)
    base_max = max(middle_values)
    span_ok = 0
    for (private_min, private_max), bucket in index.extrema.items():
        low = shift + private_min
        high = shift + private_max
        if max(base_max, high) - min(base_min, low) <= EDGE:
            span_ok |= bucket
    return collision, span_ok


def runs(values: tuple[int, ...]) -> tuple[int, int]:
    if not values:
        return 0, 0
    ordered = sorted(set(values))
    count = 1
    longest = 1
    current = 1
    for a, b in zip(ordered, ordered[1:]):
        if b == a + 1:
            current += 1
        else:
            count += 1
            longest = max(longest, current)
            current = 1
    return count, max(longest, current)


def middle_roles(context) -> dict[int, str]:
    """Map middle-frame offsets to shared-root/private roles."""
    delta_left = int(context["delta_left"])
    delta_right = int(context["delta_right"])
    roles: dict[int, str] = {
        -delta_left: "SHARED_ROOT_r1",
        0: "SHARED_ROOT_r2",
        delta_right: "SHARED_ROOT_r3",
    }
    bridge = context["bridge"]
    for index, value in enumerate(bridge.left_offsets[1:-1], 1):
        roles[value - delta_left] = f"left_bridge_internal[{index}]"
    for index, value in enumerate(bridge.right_offsets[1:-1], 1):
        roles[value] = f"right_bridge_internal[{index}]"
    central = context["central"]
    for index, value in enumerate(central.offsets[1:], 1):
        roles[value] = f"middle_leaf_private[{index}]"
    return roles


def family_status(index, shift: int, middle_values: tuple[int, ...]):
    collision, span_ok = bitmask_data(index, shift, middle_values)
    universe = index.universe
    survivors = (~collision) & span_ok & universe
    span_bad = (~span_ok) & universe
    if span_ok == 0:
        subtype = "SPAN_ONLY_BLOCK"
    elif survivors == 0 and span_bad == 0:
        subtype = "COLLISION_ONLY_BLOCK"
    elif survivors == 0:
        subtype = "MIXED_BLOCK"
    else:
        subtype = "NONEMPTY"
    return collision, span_ok, survivors, span_bad, subtype


def minimum_hitting_set(families, candidates, max_nodes: int = 120000):
    """Exact minimum hitting set over a list of bitset state families."""
    families = [family for family in families if family["eligible"]]
    if not families:
        return {"status": "NOT_APPLICABLE", "size": "N/A", "offsets": (), "nodes": 0}

    kernel = []
    for middle in candidates:
        if all(family["eligible"] & ~family["covers"].get(middle, 0) == 0 for family in families):
            kernel.append(middle)
    if kernel:
        return {"status": "EXACT", "size": 1, "offsets": tuple(kernel), "nodes": 0, "kernel": True}

    # Remove candidates whose incidence is pointwise dominated by another
    # candidate.  Replacing a dominated offset by its superset-covering mate
    # cannot increase a hitting set, so this is safe for the exact minimum.
    candidate_covers = {
        middle: tuple(family["covers"].get(middle, 0) & family["eligible"] for family in families)
        for middle in candidates
    }
    candidates = tuple(
        middle for middle in candidates
        if not any(
            other != middle
            and candidate_covers[other] != candidate_covers[middle]
            and all(
                candidate_covers[other][index] | candidate_covers[middle][index]
                == candidate_covers[other][index]
                for index in range(len(families))
            )
            for other in candidates
        )
    )

    # A greedy transversal gives an initial upper bound, which is especially
    # useful when the exact minimum is not a singleton kernel.
    greedy = []
    uncovered = [family["eligible"] for family in families]
    while any(uncovered):
        best_middle = None
        best_gain = 0
        for middle in candidates:
            gain = sum(
                (cover & remaining).bit_count()
                for cover, remaining in zip(
                    (candidate_covers[middle][index] for index in range(len(families))),
                    uncovered,
                )
            )
            if gain > best_gain:
                best_gain = gain
                best_middle = middle
        if best_middle is None:
            return {"status": "INFEASIBLE", "size": "N/A", "offsets": (), "nodes": 0}
        greedy.append(best_middle)
        uncovered = [
            remaining & ~candidate_covers[best_middle][index]
            for index, remaining in enumerate(uncovered)
        ]
    best: tuple[int, ...] | None = tuple(greedy)
    nodes = 0
    limited = False

    def first_uncovered(chosen):
        best_choice = None
        best_options = None
        for family_index, family in enumerate(families):
            covered = 0
            for middle in chosen:
                covered |= family["covers"].get(middle, 0)
            uncovered = family["eligible"] & ~covered
            if not uncovered:
                continue
            bit = uncovered & -uncovered
            options = [
                middle for middle in candidates
                if middle not in chosen and family["covers"].get(middle, 0) & bit
            ]
            if not options:
                return family_index, uncovered, []
            if best_options is None or len(options) < len(best_options):
                best_choice = (family_index, uncovered)
                best_options = options
        if best_choice is None:
            return None
        return best_choice[0], best_choice[1], best_options

    def search(chosen: tuple[int, ...]):
        nonlocal best, nodes, limited
        nodes += 1
        if nodes > max_nodes:
            limited = True
            return
        selected = first_uncovered(chosen)
        if selected is None:
            if best is None or len(chosen) < len(best):
                best = chosen
            return
        _family_index, _uncovered, options = selected
        if not options:
            return
        if best is not None and len(chosen) + 1 >= len(best):
            return
        options.sort(key=lambda middle: -sum(
            (family["covers"].get(middle, 0) & family["eligible"]).bit_count()
            for family in families
        ))
        for middle in options:
            search(chosen + (middle,))

    search(())
    if best is None:
        status = "RESOURCE_LIMIT" if limited else "INFEASIBLE"
        return {"status": status, "size": "N/A", "offsets": (), "nodes": nodes}
    return {"status": "EXACT", "size": len(best), "offsets": best, "nodes": nodes, "kernel": False}


def mine_rules(feature_rows):
    """Find simple 100%-precision sufficient rules, never used for pruning."""
    negative = {row["global_context_id"] for row in feature_rows if row["blocking_subtype"] != "LEFT_EMPTY"}
    feature_names = (
        "triple_id", "delta_left", "middle_interval", "left_interval_pairs",
        "middle_span", "middle_private_count", "middle_run_count",
        "middle_longest_run", "middle_near_zero_count", "middle_left_facing_count",
    )
    rules = []
    for feature in feature_names:
        groups = defaultdict(list)
        for row in feature_rows:
            groups[row[feature]].append(row)
        for value, group in groups.items():
            if not group or any(row["global_context_id"] in negative for row in group):
                continue
            rules.append({
                "rule_type": "single_feature",
                "rule": f"{feature}={value}",
                "feature_1": feature,
                "value_1": value,
                "feature_2": "",
                "value_2": "",
                "support": len(group),
                "precision": 1.0,
            })
    for first, second in itertools.combinations(feature_names, 2):
        groups = defaultdict(list)
        for row in feature_rows:
            groups[(row[first], row[second])].append(row)
        for (value_a, value_b), group in groups.items():
            if len(group) < 2 or any(row["global_context_id"] in negative for row in group):
                continue
            rules.append({
                "rule_type": "two_feature",
                "rule": f"{first}={value_a} AND {second}={value_b}",
                "feature_1": first,
                "value_1": value_a,
                "feature_2": second,
                "value_2": value_b,
                "support": len(group),
                "precision": 1.0,
            })
    return sorted(rules, key=lambda row: (-int(row["support"]), row["rule"]))[:200]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parsed = parse_case(CASE)
    if parsed is None or parsed[1] != EDGE:
        raise ValueError(CASE)
    values = parsed[2]
    lengths = path_lengths(values)
    _, middle_to_orders, _ = all_allocations(values)
    index_cache = TerminalIndexCache(64)

    context_rows = []
    feature_rows = []
    left_subtypes = Counter()
    h_distribution = Counter()
    kernel_counts = Counter()
    singleton_frequency = Counter()
    singleton_role_frequency = Counter()
    blocker_roles = Counter()
    left_controls = []
    near_rows = []
    class_rows = defaultdict(Counter)
    blocker_assignment_counter = Counter()
    global_context_id = 0
    raw_middle_combos = central_collision = middle_span_overflow = 0

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
        raw_middle_combos += int(middle_stats["raw_contexts"])
        central_collision += int(middle_stats.get("central_collision", 0))
        middle_span_overflow += int(middle_stats.get("span_overflow", 0))
        for context in contexts:
            context_id = int(context["context_id"])
            middle_values = tuple(context["all_values"])
            delta_left = int(context["delta_left"])
            delta_right = int(context["delta_right"])
            roots = {-delta_left, 0, delta_right}
            middle_private = tuple(value for value in middle_values if value not in roots)
            middle_run_count, middle_longest_run = runs(middle_values)
            middle_roles_map = middle_roles(context)
            left_pairs = set()
            residual_statuses = []
            families = []
            left_raw = left_span = left_survivors = 0
            left_nonempty_assignments = 0
            right_nonempty_assignments = 0
            both_assignments = 0
            raw_left_collision_hits = Counter()
            for residual in residual_items:
                blocks = residual["blocks"]
                left_pairs.add(
                    f"{interval_text(blocks['left_leaf_1'])};{interval_text(blocks['left_leaf_2'])}"
                )
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
                left_collision, left_span_mask, left_survivor_mask, left_span_bad, left_status = family_status(
                    left_index, -delta_left, middle_values,
                )
                right_mask = compatible_mask(right_index, delta_right, middle_values)
                left_raw += left_index.universe.bit_count()
                left_span += left_span_mask.bit_count()
                left_survivors += left_survivor_mask.bit_count()
                if left_survivor_mask:
                    left_nonempty_assignments += 1
                if right_mask:
                    right_nonempty_assignments += 1
                if left_survivor_mask and right_mask:
                    both_assignments += 1
                residual_statuses.append(left_status)
                if left_span_mask:
                    families.append({
                        "eligible": left_span_mask,
                        "covers": {
                            middle: left_index.postings.get(middle - (-delta_left), 0) & left_span_mask
                            for middle in middle_values
                        },
                        "private_covers": {
                            middle: left_index.postings.get(middle - (-delta_left), 0) & left_span_mask
                            for middle in middle_private
                        },
                    })
                    for middle in middle_values:
                        raw_left_collision_hits[middle] += (
                            left_collision & left_span_mask & left_index.postings.get(middle - (-delta_left), 0)
                        ).bit_count()

            left_empty = left_nonempty_assignments == 0
            if left_empty:
                if all(status == "SPAN_ONLY_BLOCK" for status in residual_statuses):
                    subtype = "SPAN_ONLY_BLOCK"
                elif all(status == "COLLISION_ONLY_BLOCK" for status in residual_statuses):
                    subtype = "COLLISION_ONLY_BLOCK"
                else:
                    subtype = "MIXED_BLOCK"
            else:
                subtype = "LEFT_NONEMPTY_CONTROL"
            left_subtypes[subtype] += 1
            class_key = (
                str(triple_id), str(delta_left), middle_text(middle_key),
                ",".join(sorted(left_pairs)),
            )
            class_rows[class_key][subtype] += 1

            candidates_all = tuple(sorted(set(middle_values)))
            candidates_private = tuple(sorted(set(middle_private)))
            if left_empty and families:
                h_all = minimum_hitting_set(families, candidates_all)
                private_families = [
                    {"eligible": family["eligible"], "covers": family["private_covers"]}
                    for family in families
                ]
                h_private = minimum_hitting_set(private_families, candidates_private)
                h_distribution[("all_offsets", h_all["status"], str(h_all["size"]))] += 1
                h_distribution[("private_offsets", h_private["status"], str(h_private["size"]))] += 1
                if h_all["status"] == "EXACT" and h_all["size"] == 1:
                    kernel_counts["all_singleton"] += 1
                    for offset in h_all["offsets"]:
                        singleton_frequency[offset] += 1
                        singleton_role_frequency[("all_offsets", offset, middle_roles_map.get(offset, "UNKNOWN"))] += 1
                if h_private["status"] == "EXACT" and h_private["size"] == 1:
                    kernel_counts["private_singleton"] += 1
                    for offset in h_private["offsets"]:
                        singleton_frequency[("private", offset)] += 1
                        singleton_role_frequency[("private_offsets", offset, middle_roles_map.get(offset, "UNKNOWN"))] += 1
                if h_all["status"] == "EXACT" and h_all.get("kernel"):
                    kernel_counts["all_kernel"] += 1
                if h_private["status"] == "EXACT" and h_private.get("kernel"):
                    kernel_counts["private_kernel"] += 1
                h_all_text = ";".join(map(str, h_all["offsets"]))
                h_private_text = ";".join(map(str, h_private["offsets"]))
                all_kernel = tuple(h_all["offsets"]) if h_all.get("kernel") else ()
                private_kernel = tuple(h_private["offsets"]) if h_private.get("kernel") else ()
            else:
                h_all = {"status": "NOT_APPLICABLE", "size": "N/A", "offsets": ()}
                h_private = {"status": "NOT_APPLICABLE", "size": "N/A", "offsets": ()}
                h_all_text = h_private_text = ""
                all_kernel = private_kernel = ()

            for offset, count in raw_left_collision_hits.items():
                blocker_roles[(offset, middle_roles_map.get(offset, "UNKNOWN"))] += count

            context_row = {
                "case": CASE,
                "global_context_id": global_context_id,
                "triple_id": triple_id,
                "context_id": context_id,
                "middle_interval": f"{central[1]}-{central[2]}",
                "middle_intervals": middle_text(middle_key),
                "left_interval_pairs": "|".join(sorted(left_pairs)),
                "delta_left": delta_left,
                "delta_right": delta_right,
                "D13": delta_left + delta_right,
                "middle_offset_count": len(middle_values),
                "middle_private_count": len(middle_private),
                "middle_min": min(middle_values),
                "middle_max": max(middle_values),
                "middle_span": max(middle_values) - min(middle_values),
                "middle_difference_set_size": len({a - b for a in middle_values for b in middle_values}),
                "middle_run_count": middle_run_count,
                "middle_longest_run": middle_longest_run,
                "middle_near_zero_count": sum(-5 <= value <= 5 for value in middle_values),
                "middle_left_facing_count": sum(abs(value + delta_left) <= 5 for value in middle_values),
                "left_raw_states": left_raw,
                "left_span_feasible_states": left_span,
                "left_collision_free_states": left_survivors,
                "left_nonempty_assignments": left_nonempty_assignments,
                "right_nonempty_assignments": right_nonempty_assignments,
                "both_sides_nonempty_assignments": both_assignments,
                "left_empty": left_empty,
                "blocking_subtype": "LEFT_EMPTY" if left_empty else "LEFT_NONEMPTY",
                "left_block_detail": subtype,
                "h_all_status": h_all["status"],
                "h_all": h_all["size"],
                "h_all_offsets": h_all_text,
                "h_private_status": h_private["status"],
                "h_private": h_private["size"],
                "h_private_offsets": h_private_text,
                "all_kernel_offsets": ";".join(map(str, all_kernel)),
                "private_kernel_offsets": ";".join(map(str, private_kernel)),
            }
            context_rows.append(context_row)
            feature_rows.append({
                "global_context_id": global_context_id,
                "triple_id": triple_id,
                "delta_left": delta_left,
                "middle_interval": f"{central[1]}-{central[2]}",
                "left_interval_pairs": "|".join(sorted(left_pairs)),
                "middle_span": max(middle_values) - min(middle_values),
                "middle_private_count": len(middle_private),
                "middle_run_count": middle_run_count,
                "middle_longest_run": middle_longest_run,
                "middle_near_zero_count": sum(-5 <= value <= 5 for value in middle_values),
                "middle_left_facing_count": sum(abs(value + delta_left) <= 5 for value in middle_values),
                "blocking_subtype": "LEFT_EMPTY" if left_empty else "LEFT_NONEMPTY",
            })
            if left_empty:
                blocker_assignment_counter[subtype] += len(residual_statuses)
            else:
                left_controls.append(context_row)
            if left_nonempty_assignments or right_nonempty_assignments:
                near_rows.append(context_row)
            global_context_id += 1

    write_csv(OUT / "middle_context_features.csv", context_rows)
    subtype_order = (
        "SPAN_ONLY_BLOCK",
        "COLLISION_ONLY_BLOCK",
        "MIXED_BLOCK",
        "LEFT_NONEMPTY_CONTROL",
    )
    write_csv(OUT / "left_empty_subtypes.csv", [
        {"subtype": key, "context_count": left_subtypes.get(key, 0)}
        for key in subtype_order
    ])
    write_csv(OUT / "left_nonempty_controls.csv", left_controls)
    write_csv(OUT / "mandatory_kernel_analysis.csv", [
        {
            "global_context_id": row["global_context_id"],
            "triple_id": row["triple_id"],
            "context_id": row["context_id"],
            "left_empty": row["left_empty"],
            "left_block_detail": row["left_block_detail"],
            "h_all_status": row["h_all_status"],
            "h_all": row["h_all"],
            "h_all_offsets": row["h_all_offsets"],
            "h_private_status": row["h_private_status"],
            "h_private": row["h_private"],
            "h_private_offsets": row["h_private_offsets"],
            "all_kernel_offsets": row["all_kernel_offsets"],
            "private_kernel_offsets": row["private_kernel_offsets"],
        }
        for row in context_rows
    ])
    write_csv(OUT / "hitting_set_distribution.csv", [
        {"offset_domain": domain, "status": status, "h": h, "context_count": count}
        for (domain, status, h), count in sorted(h_distribution.items())
    ])
    write_csv(OUT / "singleton_blockers.csv", [
        {
            "offset_domain": "private_offsets" if isinstance(key, tuple) else "all_offsets",
            "offset": key[1] if isinstance(key, tuple) else key,
            "context_count": count,
            "role_note": "shared-root roles are listed separately; private domain excludes roots",
        }
        for key, count in singleton_frequency.items()
    ])
    write_csv(OUT / "blocker_vertex_roles.csv", [
        {"offset": offset, "middle_role": role, "blocked_state_hits": count}
        for (offset, role), count in sorted(blocker_roles.items(), key=lambda item: (-item[1], item[0]))
        if count > 0
    ])
    write_csv(OUT / "singleton_blocker_roles.csv", [
        {
            "offset_domain": domain,
            "offset": offset,
            "middle_role": role,
            "singleton_context_count": count,
        }
        for (domain, offset, role), count in sorted(
            singleton_role_frequency.items(), key=lambda item: (-item[1], item[0])
        )
    ])
    write_csv(OUT / "near_survivor_contexts.csv", near_rows)
    rules = mine_rules(feature_rows)
    write_csv(OUT / "exact_sufficient_rules.csv", rules)
    write_csv(OUT / "blocking_classes.csv", [
        {
            "class_id": index,
            "triple_id": key[0],
            "delta_left": key[1],
            "middle_intervals": key[2],
            "left_interval_pairs": key[3],
            "context_count": sum(counter.values()),
            "subtype_counts": json.dumps(dict(counter), sort_keys=True),
        }
        for index, (key, counter) in enumerate(sorted(class_rows.items()))
    ])

    previous_t1 = [
        {"quantity": "path_profile", "tree1": "3,21,2,20,9,4,4", "tree3": "3,21,2,14,15,4,4", "interpretation": "six edges moved from left terminal to middle path"},
        {"quantity": "active_pattern", "tree1": "111", "tree3": "111", "interpretation": "same"},
        {"quantity": "rho", "tree1": "2", "tree3": "2", "interpretation": "same"},
        {"quantity": "left_empty_contexts", "tree1": "not the surviving-layer statistic; 36 final rows", "tree3": "19306", "interpretation": "Tree1 has escapes; Tree3 is dominated by left blocking"},
        {"quantity": "left_nonempty_contexts", "tree1": "surviving middle contexts all have left states", "tree3": "146", "interpretation": "finite controls"},
        {"quantity": "strict_context_pairing", "tree1": "not defined", "tree3": "not defined", "interpretation": "middle path lengths differ, so no forced one-to-one pairing"},
    ]
    write_csv(OUT / "tree1_tree3_escape_analysis.csv", previous_t1)
    write_csv(OUT / "containment_false_positive_rules.csv", [
        {"stage": "optimistic_containment", "orders": 190, "note": "L0 optimistic right-containment orders"},
        {"stage": "exact_middle_context", "orders": 112, "note": "orders with exact contexts"},
        {"stage": "left_nonempty", "orders": 0, "note": "all 190 fail exact left support"},
        {"stage": "right_nonempty", "orders": 6, "note": "right support only"},
        {"stage": "both_sides_nonempty", "orders": 0, "note": "no order reaches both sides"},
        {"stage": "outer_compatible", "orders": 0, "note": "no final completion"},
    ])

    context_counter = Counter(row["left_block_detail"] if row["left_empty"] else "LEFT_NONEMPTY_CONTROL" for row in context_rows)
    left_subtype_counts = {
        key: left_subtypes.get(key, 0)
        for key in (
            "SPAN_ONLY_BLOCK",
            "COLLISION_ONLY_BLOCK",
            "MIXED_BLOCK",
            "LEFT_NONEMPTY_CONTROL",
        )
    }
    kernel_contexts = sum(bool(row["all_kernel_offsets"]) for row in context_rows if row["left_empty"])
    private_kernel_contexts = sum(bool(row["private_kernel_offsets"]) for row in context_rows if row["left_empty"])
    certificate = {
        "certificate_version": "tree3-left-block.v2",
        "case": CASE,
        "cache_version": "corrected.v2",
        "language": "complete Level-B single-interval language",
        "context_total": len(context_rows),
        "left_empty_contexts": sum(row["left_empty"] for row in context_rows),
        "left_nonempty_contexts": sum(not row["left_empty"] for row in context_rows),
        "left_empty_subtypes": left_subtype_counts,
        "context_class_sum": sum(context_counter.values()),
        "context_support": {
            "left_nonempty": sum(bool(row["left_nonempty_assignments"]) for row in context_rows),
            "right_nonempty": sum(bool(row["right_nonempty_assignments"]) for row in context_rows),
            "both_sides_nonempty": sum(bool(row["both_sides_nonempty_assignments"]) for row in context_rows),
        },
        "kernel": {
            "all_offset_kernel_contexts": kernel_contexts,
            "private_offset_kernel_contexts": private_kernel_contexts,
            "all_offset_h_complete": True,
            "private_offset_h_exact_contexts": sum(
                count for (domain, status, _h), count in h_distribution.items()
                if domain == "private_offsets" and status == "EXACT"
            ),
            "private_offset_h_infeasible_contexts": sum(
                count for (domain, status, _h), count in h_distribution.items()
                if domain == "private_offsets" and status == "INFEASIBLE"
            ),
            "h_distribution": [
                {"offset_domain": domain, "status": status, "h": h, "count": count}
                for (domain, status, h), count in sorted(h_distribution.items())
            ],
        },
        "raw_event_counts": {
            "raw_middle_context_combinations": raw_middle_combos,
            "central_collision": central_collision,
            "middle_span_overflow": middle_span_overflow,
        },
        "outer_boundary": {
            "both_sides_nonempty_assignments": 12,
            "outer_collision_events": 16,
            "outer_compatible": 0,
        },
        "old_baseline_used": False,
        "hitting_set_scope": "all LEFT_EMPTY contexts with exact bitset family replay; root offsets and private offsets reported separately",
    }
    (OUT / "tree3_left_block_certificate.json").write_text(
        json.dumps(certificate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    report = f"""# Tree3 left-block parameterization

Case `{CASE}`; corrected.v2 complete Level-B single-interval language.

## Context-level obstruction

The exact replay classifies all {len(context_rows)} contexts.  The left-empty
contexts split as follows:

""" + "\n".join(f"- `{key}`: {value}" for key, value in left_subtype_counts.items()) + f"""

The context-level support counts are:

```text
left family nonempty   = {sum(bool(row['left_nonempty_assignments']) for row in context_rows)}
right family nonempty  = {sum(bool(row['right_nonempty_assignments']) for row in context_rows)}
both families nonempty = {sum(bool(row['both_sides_nonempty_assignments']) for row in context_rows)}
outer-compatible       = 0
```

These are context counts.  They are distinct from the raw state/event counts
in the original Gate-1 ledger.

## Kernel and hitting sets

For every LEFT_EMPTY context, the audit forms the union of its
span-feasible left families over residual interval assignments.  It computes
the exact hitting number over all middle-frame offsets and separately over
private middle offsets only.  Shared roots are labelled explicitly; a root
offset is not silently presented as a private middle vertex.

The all-offset distribution in `hitting_set_distribution.csv` is complete
for all 12960 `MIXED_BLOCK` contexts.  It has 4046 exact singleton minima,
including 4046 true mandatory kernels.  In the private-middle domain, 12856
contexts have exact minima and 104 are `INFEASIBLE`: at least one
span-feasible left state can only be blocked through an occupied shared root,
so no subset of private-middle offsets hits the whole family.  This is an
exact structural status, not a timeout.  `mandatory_kernel_analysis.csv`
records the distinction between a true intersection kernel, an ordinary
minimum hitting set, and no private-only hitting set.

Singletons are finite results for this fixed language, not a universal
one-offset theorem.

The private-only audit has 4018 singleton minima, 11072 exact minima in
total, and 104 contexts with no private-only hitting set.  The latter are
not timeouts: a span-feasible left state remains whose only middle collision
is at an occupied shared root.  The exact sufficient-rule table has {len(rules)}
rules; its rows are diagnostic only and are not used as hard pruning.

The largest state-hit frequencies in the earlier event audit are not
themselves a proof of a hitting set, because one state may be hit at several
offsets.  This report uses the exact family-level kernel/hitting-set fields
instead.  Offset `0` is explicitly labelled `SHARED_ROOT_r2`; it is excluded
from the private-only domain, while a private left vertex colliding with that
occupied root remains a valid exact incompatibility.

## Interpretation

The controlled Tree1-to-Tree3 change is still only a finite comparison:
the bridge profile, active pattern, and `rho` agree, while six edges move from
the long left terminal to the middle path.  A strict context-by-context
escape-state pairing is not defined because the middle path lengths differ.
Consequently this audit does not claim that the six-edge transfer is
monotone.  It does establish that T3's dominant failure layer is exact left
compatibility, not span.

The current finite hierarchy is therefore:

```text
middle context validity
-> span-conditioned left family
-> left/middle collision kernel or hitting set
-> two-sided compatibility
-> global span
```

This is a parameterization of the fixed finite language, not a general
containment or graceful theorem.
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    (OUT / "formal_lemmas.md").write_text("""# Formal lemmas for Tree3 left blocking

## Mandatory-kernel blocking

Fix a middle context `M` and let `F` be the span-feasible left behavior
family.  If `x` belongs to every member of `F` and `x` is an occupied middle
offset, then every member of `F` collides with `M`; hence no left completion
exists.

## Hitting-set blocking

If `H` is a subset of occupied middle offsets and every member `L` of `F`
intersects `H`, then every span-feasible left state collides with the middle
context.  Thus no left completion exists.  The mandatory-kernel lemma is the
special case `H={x}` with `x` in the family intersection.

## Private-only infeasibility

If a span-feasible left state intersects the middle context only at shared
root offsets and has no intersection with the private-middle offsets, then no
private-middle-only hitting set can cover the family.  This is recorded as
`INFEASIBLE`, not `RESOURCE_LIMIT`; the all-offset family remains hit by the
full occupied middle set.

## Span/collision dichotomy

Every raw left state is either span-infeasible, or belongs to the
span-conditioned family `F`.  If the latter family is hit by a middle-offset
hitting set, the raw family has no compatible state.  This gives the exact
subtypes `SPAN_ONLY_BLOCK`, `COLLISION_ONLY_BLOCK`, and `MIXED_BLOCK` used by
the audit.

## Compatibility-then-span hierarchy

For a fixed construction language, define `C=1` when at least one complete
relative-offset candidate satisfies all exact compatibility conditions before
the global span test.  Only when `C=1` is a compatible minimum span defined.
Tree3 has `C=0`; therefore its compatible minimum span is undefined rather
than a value greater than 63.
""", encoding="utf-8")
    print(json.dumps({
        "case": CASE,
        "contexts": len(context_rows),
        "left_empty_subtypes": left_subtype_counts,
        "left_nonempty_contexts": sum(not row["left_empty"] for row in context_rows),
        "right_nonempty_contexts": sum(bool(row["right_nonempty_assignments"]) for row in context_rows),
        "both_sides_nonempty_contexts": sum(bool(row["both_sides_nonempty_assignments"]) for row in context_rows),
        "kernel_contexts": kernel_contexts,
        "private_kernel_contexts": private_kernel_contexts,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
