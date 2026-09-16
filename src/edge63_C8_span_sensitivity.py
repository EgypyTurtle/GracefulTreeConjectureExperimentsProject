"""Read-only Tree1 C8 span sensitivity and path-role audit."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from edge63_C8_displacement_first import values_for_case
from edge63_displacement_first_compact import PATHS, interval_blocks, path_lengths


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
AUDIT_DIR_NAME = "left_leaf_1_geometry_audit"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0])
    for row in rows[1:]:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def json_field(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_ints(text: str) -> tuple[int, ...]:
    return tuple(int(item) for item in text.split(";") if item != "")


def split_roles(text: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in text.split(",") if item.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--audit-dir", type=Path, default=None)
    args = parser.parse_args()
    root = args.root
    audit = args.audit_dir or (root / "results" / "edge63_two_interval_gate2" / "tree1_C8" / AUDIT_DIR_NAME)
    c7_path = root / "results" / "edge63_span_feasibility_frontier" / "corrected_tree1_gate1" / "final_span_candidates.csv"
    c7_min_path = root / "results" / "edge63_span_feasibility_frontier" / "corrected_analysis_v1" / "tree1_min_span_candidates.csv"
    match_rows = read_csv(audit / "C7_C8_candidate_matching.csv")
    c8_rows = json.loads((audit / "geometry_audit_certificate.json").read_text(encoding="utf-8"))["c8_rows"]
    c7_rows = read_csv(c7_path)
    c7_min_rows = read_csv(c7_min_path)
    values = values_for_case(CASE)
    lengths = path_lengths(values)

    by_c8 = {
        (row["group_id"], str(row["context_id"]), str(row["left_state_id"]), str(row["right_state_id"])): row
        for row in c8_rows
    }
    c7_by_key = {
        (row["order_index"], row["middle_context_id"]): row
        for row in c7_min_rows
    }
    decomposition = []
    for c8 in c8_rows:
        if int(c8["span"]) != 67:
            continue
        related = [
            row for row in match_rows
            if row["c8_group_id"] == c8["group_id"]
            and row["c8_context_id"] == str(c8["context_id"])
            and row["c8_left_state_id"] == str(c8["left_state_id"])
            and row["c8_right_state_id"] == str(c8["right_state_id"])
        ]
        for match in related:
            c7 = c7_by_key.get((match["c7_order_index"], match["c7_middle_context_id"]))
            if c7 is None:
                continue
            decomposition.append({
                "c7_order_index": c7["order_index"],
                "c8_group_id": c8["group_id"],
                "c8_context_id": c8["context_id"],
                "c7_span": c7["span"],
                "c8_span": c8["span"],
                "c7_D13": c7["D13"],
                "c8_D13_abs": c8["D13_abs"],
                "c7_left_outward": c7["left_outward_extension"],
                "c8_left_cross_root": c8["left_cross_root_extension"],
                "c7_right_outward": c7["right_outward_extension"],
                "c8_right_cross_root": c8["right_cross_root_extension"],
                "c7_min_roles": c7["min_roles"],
                "c7_max_roles": c7["max_roles"],
                "c8_left_leaf_1_runs": c8["left_leaf_1_runs"],
                "c8_left_leaf_1_run_gap": c8["left_leaf_1_run_gap"],
                "c8_run_order": c8["run_order"],
            })
    write_csv(audit / "span67_decomposition_compare.csv", decomposition)

    min_rows = [row for row in c8_rows if int(row["span"]) == 67]
    sensitivity = []
    for path in PATHS:
        min_control = 0
        max_control = 0
        for row in min_rows:
            private = json.loads(row["path_private_middle_frame"])
            all_values = [item for vals in private.values() for item in vals]
            # Root labels are not private; terminal-extreme roles are supplied
            # by the corrected C7 audit for the matched minimum layer.
            if path in {"left_leaf_1", "left_leaf_2"} and any(int(value) == int(row["min_offset"]) for value in private.get(path, [])):
                min_control += 1
            if path in {"left_leaf_1", "left_leaf_2"} and any(int(value) == int(row["max_offset"]) for value in private.get(path, [])):
                max_control += 1
            if path in {"right_leaf_1", "right_leaf_2"} and any(int(value) == int(row["min_offset"]) for value in private.get(path, [])):
                min_control += 1
            if path in {"right_leaf_1", "right_leaf_2"} and any(int(value) == int(row["max_offset"]) for value in private.get(path, [])):
                max_control += 1
        length = lengths[path]
        sensitivity.append({
            "path": path,
            "path_length": length,
            "c8_min_span67_rows_with_private_extreme": min_control + max_control,
            "c8_min_role_hits_min": min_control,
            "c8_min_role_hits_max": max_control,
            "c7_min_pair_role_evidence": "left_terminal_pair=max; right_terminal_pair=min" if path.startswith("left_") or path.startswith("right_") else "middle/bridge not terminal extreme",
            "span_active_assessment": "HIGH" if (path == "left_leaf_2" or path.startswith("right_leaf_")) else "LOW",
            "assessment_basis": "C7 span-67 block pattern and matched C8 envelope; left_leaf_1 is the 1..2 block and its C8 runs are adjacent",
        })
    write_csv(audit / "path_sensitivity.csv", sensitivity)
    summary = {
        "c7_rows": len(c7_rows),
        "c8_rows": len(c8_rows),
        "c8_min_span": min(int(row["span"]) for row in c8_rows),
        "c8_span_distribution": dict(sorted(Counter(int(row["span"]) for row in c8_rows).items())),
        "c8_minimum_rows": len(min_rows),
        "matching_rows": len(match_rows),
        "values": list(values),
        "path_lengths": lengths,
    }
    (audit / "span_sensitivity_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
