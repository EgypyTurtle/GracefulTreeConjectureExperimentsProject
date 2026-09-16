#!/usr/bin/env python3
"""Audit adjacent C8 split allocations against the trusted C7 family."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from multiprocessing import Pool
from collections import Counter, defaultdict
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_C8_allocations import ALLOCATION_DEDUP_VERSION, iter_allocations, LANGUAGE_VERSION  # noqa: E402
from edge63_C8_displacement_first import values_for_case  # noqa: E402
from edge63_C8_two_run_cache import PersistentTwoRunCache  # noqa: E402
from edge63_two_run_local_states import options_for_runs  # noqa: E402
from edge63_displacement_first_compact import PATHS  # noqa: E402


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SPLIT_SLOT = "left_leaf_2"


def geometry(state) -> tuple[tuple[int, ...], int, int]:
    return state.private, state.min_value, state.max_value


def compare_batch(args: tuple[int, list[tuple[tuple[int, int], tuple[int, int], tuple[int, int]]]]) -> tuple[int, list[dict[str, object]]]:
    batch_id, pairs = args
    pair_cache = PersistentTwoRunCache(
        Path("results/edge63_two_interval_gate2"), CASE, SPLIT_SLOT
    )
    rows = []
    for union, first, second in pairs:
        c7 = {geometry(state) for state in options_for_runs((union,), "terminal")}
        c8_states = pair_cache.options((first, second), "terminal")
        c8 = {geometry(state) for state in c8_states}
        relation = "EQUAL" if c8 == c7 else "SUBSET" if c8 <= c7 else "NEW_BEHAVIOR"
        rows.append({
            "union": f"{union[0]}-{union[1]}",
            "run_1": f"{first[0]}-{first[1]}",
            "run_2": f"{second[0]}-{second[1]}",
            "c7_geometry_count": len(c7),
            "c8_geometry_count": len(c8),
            "relation": relation,
            "c8_minus_c7": len(c8 - c7),
            "c7_minus_c8": len(c7 - c8),
            "language": LANGUAGE_VERSION,
            "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
            "terminal_pair_cache_version": "corrected.v2",
        })
    return batch_id, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=24)
    args = parser.parse_args()
    values = values_for_case(CASE)
    pair_by_union: dict[tuple[int, int], set[tuple[tuple[int, int], tuple[int, int]]] ] = defaultdict(set)
    adjacent_raw = 0
    adjacent_residual = 0
    for allocation in iter_allocations(values, SPLIT_SLOT):
        blocks = allocation["blocks"][SPLIT_SLOT]
        first, second = sorted(blocks)
        gap = second[0] - first[1] - 1
        if gap != 0:
            continue
        adjacent_raw += 1
        union = (first[0], second[1])
        pair_by_union[union].add((first, second))
    adjacent_residual = sum(len(pairs) for pairs in pair_by_union.values())
    pair_list = [
        (union, first, second)
        for union, interval_pairs in sorted(pair_by_union.items())
        for first, second in sorted(interval_pairs)
    ]
    batches = [
        (index, pair_list[start:start + args.batch_size])
        for index, start in enumerate(range(0, len(pair_list), args.batch_size))
    ]
    rows = []
    with Pool(processes=max(1, args.workers)) as pool:
        for _batch_id, batch_rows in pool.imap_unordered(compare_batch, batches):
            rows.extend(batch_rows)
    rows.sort(key=lambda row: (row["union"], row["run_1"], row["run_2"]))
    summary = Counter(row["relation"] for row in rows)
    out = args.root / "tree1_C8" / "left_leaf_2_exact_v3" / "adjacent_collapse_audit"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "adjacent_interval_family_compare.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["status"])
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "status": "PASS" if summary["NEW_BEHAVIOR"] == 0 else "NON_COLLAPSE_FOUND",
        "case": CASE,
        "split_slot": SPLIT_SLOT,
        "adjacent_raw_allocations": adjacent_raw,
        "distinct_adjacent_interval_pairs": adjacent_residual,
        "family_relation_counts": dict(summary),
        "provably_C7_local_collapse": summary["EQUAL"] + summary["SUBSET"],
        "global_discharge": "PENDING_OWNERSHIP_MAPPING" if summary["NEW_BEHAVIOR"] == 0 else "NOT_ALLOWED",
        "two_run_language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "terminal_pair_cache_version": "corrected.v2",
    }
    (out / "adjacent_global_mapping_verification.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (out / "adjacent_collapse_report.md").write_text(
        "# Adjacent C8 collapse audit\n\n"
        f"Adjacent raw allocations: **{adjacent_raw:,}**. Distinct split interval pairs: **{adjacent_residual:,}**.\n\n"
        f"Local family relation counts: `{dict(summary)}`.\n\n"
        "A local `EQUAL`/`SUBSET` relation is not alone a global hard-prune; "
        "the ownership-preserving C8-to-C7 merge must also be independently checked.\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
