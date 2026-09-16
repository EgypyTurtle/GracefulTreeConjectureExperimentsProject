#!/usr/bin/env python3
"""Independent verifier for the declared lazy-oracle differential cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from edge63_C8_lazy_terminal_oracle import compare_query, LANGUAGE_VERSION, ORACLE_VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/tree1_C8/left_leaf_2_exact_v3/lazy_oracle_v1/lazy_oracle_differential_tests.json"))
    args = parser.parse_args()
    cases = [
        (((1, 1), (3, 3)), (), 0, 0, 0),
        (((1, 2), (5, 6)), (0, 1, -1), -4, -10, 10),
        (((4, 6), (20, 21)), (2, -2, 7), -9, -15, 15),
        (((7, 9), (31, 34)), (0, 3, -3, 5), -12, -20, 20),
    ]
    tests = [compare_query(*case) for case in cases]
    payload = {
        "verification_version": "lazy-oracle.verify.v1",
        "oracle_version": ORACLE_VERSION,
        "two_run_language": LANGUAGE_VERSION,
        "status": "PASS" if all(test["geometry_equal"] for test in tests) else "FAIL",
        "tests": tests,
    }
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
