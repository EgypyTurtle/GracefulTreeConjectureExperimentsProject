"""Cheap C8 split-slot prescan for the two benchmark trees.

This pass counts all raw eight-run allocations analytically and samples a
small, deterministic set of run placements only to estimate local behavior
size.  It does not enumerate global C8 contexts and does not make a Gate-2
decision.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_C8_allocations import (  # noqa: E402
    LANGUAGE_VERSION,
    allocation_count,
    allocation_from_tokens,
    allocation_summary,
    split_tokens,
)
from edge63_displacement_first_compact import PATHS, path_lengths  # noqa: E402
from edge63_structure_analysis import parse_case  # noqa: E402
from edge63_two_run_local_states import local_state_summary  # noqa: E402


CASES = (
    "fiveleaf3e-63-3-21-2-20-9-4-4",
    "fiveleaf3e-63-3-21-2-14-15-4-4",
)
EDGE_COUNT = 63


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def values_for_case(case: str) -> tuple[int, ...]:
    parsed = parse_case(case)
    if parsed is None or parsed[1] != EDGE_COUNT:
        raise ValueError(case)
    return parsed[2]


def sample_orders(split_slot: str) -> list[tuple[str, ...]]:
    other = [path for path in PATHS if path != split_slot]
    first, second = split_tokens(split_slot)
    orders = [
        (first, second, *other),
        (*other, first, second),
        (first, *other[:3], second, *other[3:]),
        (second, *other[:3], first, *other[3:]),
        (first, *reversed(other), second),
        (second, *reversed(other), first),
    ]
    return list(dict.fromkeys(tuple(order) for order in orders))


def prescan_case(case: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    values = values_for_case(case)
    lengths = path_lengths(values)
    allocation_rows: list[dict[str, object]] = []
    local_rows: list[dict[str, object]] = []
    for split_slot in PATHS:
        summary = allocation_summary(values, split_slot)
        summary["case"] = case
        allocation_rows.append(summary)
        split_length = lengths[split_slot]
        choices = sorted({1, split_length // 2, split_length - 1})
        state_counts: list[int] = []
        for first_length in choices:
            for token_order in sample_orders(split_slot):
                allocation = allocation_from_tokens(lengths, split_slot, first_length, token_order)
                intervals = tuple(allocation["blocks"][split_slot])
                role = "terminal" if "leaf" in split_slot else "bridge"
                state = local_state_summary(intervals, role)
                state_counts.append(int(state["state_count"]))
                local_rows.append({
                    "case": case,
                    "split_slot": split_slot,
                    "first_run_length": first_length,
                    "second_run_length": split_length - first_length,
                    "run_order": ",".join(token_order),
                    **state,
                })
        role = "terminal" if "leaf" in split_slot else "bridge"
        allocation_rows[-1].update({
            "role": role,
            "sampled_split_lengths": ";".join(map(str, choices)),
            "sample_count": len(state_counts),
            "sampled_local_state_min": min(state_counts),
            "sampled_local_state_median": statistics.median(state_counts),
            "sampled_local_state_max": max(state_counts),
            "sampled_local_state_mean": round(statistics.mean(state_counts), 3),
            "priority_basis": "terminal slots first for Tree1/Tree3; sampled C8.LevelB.v1 state size",
        })
    return allocation_rows, local_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--case", action="append", choices=CASES)
    args = parser.parse_args()
    cases = tuple(args.case) if args.case else CASES
    allocation_rows: list[dict[str, object]] = []
    local_rows: list[dict[str, object]] = []
    for case in cases:
        rows, sampled = prescan_case(case)
        allocation_rows.extend(rows)
        local_rows.extend(sampled)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "C8_allocation_counts.csv", allocation_rows)
    write_csv(args.output_dir / "C8_split_slot_prescan.csv", allocation_rows)
    write_csv(args.output_dir / "two_run_local_state_counts.csv", local_rows)
    (args.output_dir / "prescan_report.md").write_text(
        "# C8 split-slot prescan\n\n"
        f"Language: `{LANGUAGE_VERSION}`. Cases: {', '.join(cases)}.\n\n"
        "Raw run-order allocation counts are exact after the equal-split ownership "
        "correction: `(path_length - 1) * 8!` minus `8!/2` when the two split runs "
        "are equal. Local-state "
        "counts are deterministic samples over split lengths 1, floor(k/2), and k-1 "
        "and six representative run orders; they are resource estimates, not global results.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
