#!/usr/bin/env python3
"""Independently verify the finite corrected tree-1 span audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analysis-dir", type=Path,
        default=Path("results/edge63_span_feasibility_frontier/middle_conditioned_coupling_v1"),
    )
    parser.add_argument(
        "--gate-dir", type=Path,
        default=Path("results/edge63_span_feasibility_frontier/corrected_tree1_gate1"),
    )
    args = parser.parse_args()

    certificate = json.loads(
        (args.analysis_dir / "compact_span_certificate.json").read_text(encoding="utf-8")
    )
    gate_summary = json.loads((args.gate_dir / "summary.json").read_text(encoding="utf-8"))
    case_record = gate_summary["cases"][0]
    candidates = read_csv(args.gate_dir / "final_span_candidates.csv")
    frontiers = read_csv(args.analysis_dir / "tree1_joint_extension_frontiers.csv")
    contexts = read_csv(args.analysis_dir / "tree1_middle_conditioned_span.csv")

    spans = [int(row["span"]) for row in candidates]
    frontier_spans = [int(row["span"]) for row in frontiers]
    def parse_offsets(value: str):
        return tuple(int(item) for item in value.split(";") if item)

    private_offset_checks = []
    for row in frontiers:
        middle = parse_offsets(row["middle_values"])
        left = parse_offsets(row["left_private"])
        right = parse_offsets(row["right_private"])
        all_offsets = (*middle, *left, *right)
        private_offset_checks.append(
            len(all_offsets) == 64 and len(set(all_offsets)) == 64
        )
    checks = {
        "case_name": case_record["case"] == certificate["case"],
        "gate_status": case_record["status"] == "UNSAT_EXHAUSTIVE",
        "orders_complete": int(case_record["orders_covered"]) == 5040,
        "contexts_complete": int(case_record["contexts_done"]) == 112410,
        "context_rows_complete": len(contexts) == 112410,
        "source_and_recomputed_counts_match": len(candidates) == len(frontiers),
        "source_minimum_is_67": min(spans) == 67,
        "recomputed_minimum_is_67": min(frontier_spans) == 67,
        "source_histogram_is_67_4_68_16_69_16": (
            {str(value): spans.count(value) for value in sorted(set(spans))}
            == {"67": 4, "68": 16, "69": 16}
        ),
        "all_recomputed_spans_at_least_67": all(value >= 67 for value in frontier_spans),
        "all_recomputed_offset_sets_injective": all(private_offset_checks),
        "certificate_minimum_is_67": certificate["non_span_final_candidates"]["minimum_span"] == 67,
        "certificate_count_is_36": certificate["non_span_final_candidates"]["count"] == 36,
        "no_old_sigma_66_claim": "66" not in certificate["claim"],
        "no_two_interval_scope": "two-interval" not in certificate["language"],
    }
    hashes = certificate["source_sha256"]
    checks["gate_summary_hash_matches"] = sha256(args.gate_dir / "summary.json") == hashes["gate_summary"]
    checks["final_candidates_hash_matches"] = sha256(args.gate_dir / "final_span_candidates.csv") == hashes["final_span_candidates"]
    checks["feasibility_hash_matches"] = sha256(args.gate_dir / "left_right_feasibility.csv") == hashes["left_right_feasibility"]
    result = {
        "certificate": str(args.analysis_dir / "compact_span_certificate.json"),
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "scope": certificate["scope_warning"],
    }
    (args.analysis_dir / "compact_span_certificate_verification.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    if not result["all_checks_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
