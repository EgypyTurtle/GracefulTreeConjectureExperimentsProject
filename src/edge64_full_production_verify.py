"""Independent verifier for edge64 production result batches."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graceful_tree import reconstruct_named_five_leaf_case, verify_labeling  # noqa: E402


def verify(path: Path) -> dict[str, object]:
    checked = 0
    bad: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("solved") != "1":
                continue
            case_id = row.get("case_id", "")
            try:
                _n, edges = reconstruct_named_five_leaf_case(case_id)
                labels = [int(value) for value in row.get("labels", "").split()]
                if len(labels) != 65:
                    raise ValueError(f"expected 65 labels, got {len(labels)}")
                if set(labels) != set(range(65)):
                    raise ValueError("labels are not exactly 0..64")
                if not verify_labeling(edges, labels):
                    raise ValueError("edge differences are not exactly 1..64")
                checked += 1
            except Exception as exc:
                bad.append({"case_id": case_id, "error": f"{type(exc).__name__}: {exc}"})
                if len(bad) >= 20:
                    break
    return {"status": "PASS" if not bad else "FAIL", "results_file": str(path), "checked": checked, "bad": bad}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.results)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
