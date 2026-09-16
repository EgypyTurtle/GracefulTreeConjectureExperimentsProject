"""Rank remaining Tree1 side-terminal C8 split slots from audited structure."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--audit-dir", type=Path, default=None)
    args = parser.parse_args()
    root = args.root
    audit = args.audit_dir or (root / "results" / "edge63_two_interval_gate2" / "tree1_C8" / "left_leaf_1_geometry_audit")
    prescan = read_csv(root / "results" / "edge63_two_interval_gate2" / "C8_split_slot_prescan.csv")
    rows = [row for row in prescan if row["case"] == CASE and row["role"] == "terminal" and row["split_slot"] != "left_leaf_1"]
    rank = {
        "left_leaf_2": (1, "long left terminal block is part of the C7 span-67 controlling left-terminal envelope; split can change the max-side geometry", "HIGH", "HIGH"),
        "right_leaf_1": (2, "right terminal pair supplies the C7 minimum-side extreme; split may change the large right outward envelope", "HIGH", "MEDIUM"),
        "right_leaf_2": (3, "same structural leverage as right_leaf_1 under the length-4 leaf symmetry", "HIGH", "MEDIUM"),
    }
    out = []
    for row in rows:
        slot = row["split_slot"]
        if slot not in rank:
            continue
        order, leverage, expected, cost = rank[slot]
        out.append({
            "rank": order,
            "case": CASE,
            "split_slot": slot,
            "path_length": row["split_path_length"],
            "raw_C8_allocations_ownership_v2": row["raw_C8_allocations"],
            "split_length_choices": row["split_length_choices"],
            "sampled_local_state_median": row["sampled_local_state_median"],
            "structural_leverage": leverage,
            "expected_span_change_capacity": expected,
            "estimated_computational_cost": cost,
            "decision": "NEXT" if order == 1 else "DEFER",
            "evidence": "C7 span-67 allocation pattern: left terminal 1..2 and 44..63; right terminal 12..15 and 37..40; C8 left_leaf_1 audit leaves this geometry unchanged",
        })
    out.sort(key=lambda row: int(row["rank"]))
    write_csv(audit / "next_split_slot_ranking.csv", out)
    summary = {
        "selected_next_slot": "left_leaf_2",
        "reason": "It is the only remaining left terminal slot carrying the long 44..63 C7 near-miss block and the left terminal pair controls the span-67 envelope. The audited left_leaf_1 split only resegments 1..2.",
        "do_not_run": ["right_leaf_1", "right_leaf_2", "bridge splits", "middle split", "C9"],
        "rows": out,
    }
    (audit / "next_split_slot_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
