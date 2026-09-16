#!/usr/bin/env python3
"""Freeze the prescan comparison and preregister the third-tree test."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


SELECTED = "fiveleaf3e-63-3-21-2-14-15-4-4"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prescan-dir", type=Path, default=Path("results/edge63_containment_frontier_test/coarse_level0"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/edge63_containment_frontier_test"))
    args = parser.parse_args()
    summary = json.loads((args.prescan_dir / "prescan_summary.json").read_text(encoding="utf-8"))
    rows = summary["cases"]
    if {row["case"] for row in rows} != {
        "fiveleaf3e-63-3-21-2-14-15-4-4",
        "fiveleaf3e-63-15-1-1-4-13-14-15",
        "fiveleaf3e-63-5-2-2-4-17-11-22",
    }:
        raise ValueError("prescan summary does not contain exactly the three unused representative trees")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "remaining_three_prescan.csv", rows)
    selected = next(row for row in rows if row["case"] == SELECTED)
    prediction = {
        "prediction_version": "prescan-fixed.v1",
        "selected_case": SELECTED,
        "selection_basis": {
            "path_lengths": selected["path_lengths"],
            "active_pattern": selected["active_pattern"],
            "rho": selected["rho"],
            "same_bridge_profile_as_tree1": True,
            "same_right_terminal_profile_as_tree1": True,
            "reason": "Controlled Tree1 perturbation: retain bridge lengths 3 and 21 and right terminal lengths 4,4, while move six edges from the long left terminal to the middle path. This is the closest structural control among the three unused cases.",
        },
        "prescan_metrics": selected,
        "pre_run_prediction": {
            "containment": "UNRESOLVED_BY_L0; optimistic right containment appears in the relaxation, exact containment not tested",
            "expected_regime": "likely forced cross-root rather than single-root-dominant",
            "expected_gate1": "likely UNSAT_EXHAUSTIVE",
            "expected_span": "likely greater than 63",
            "confidence": "moderate",
            "reason": "The case shares Tree1's active pattern 111 and rho=2, while its bridge/root geometry is unchanged; the L0 relaxation is too coarse to override this controlled comparison.",
        },
        "frozen_before_exact_run": True,
        "scope": "Prediction only; not a theorem and not an exact Gate-1 result.",
    }
    (args.output_dir / "third_tree_prediction.json").write_text(json.dumps(prediction, indent=2), encoding="utf-8")
    (args.output_dir / "prescan_comparison.md").write_text(
        "# Remaining representative-tree prescan\n\n"
        "The three cases were compared with the same L0 bridge-envelope\n"
        "relaxation. It is intentionally optimistic and does not decide exact\n"
        "containment or Gate 1. The preregistered third case is\n"
        f"`{SELECTED}`. It is the controlled Tree1 perturbation with the same\n"
        "bridge lengths and right terminal profile.\n",
        encoding="utf-8",
    )
    print(json.dumps(prediction, indent=2))


if __name__ == "__main__":
    main()
