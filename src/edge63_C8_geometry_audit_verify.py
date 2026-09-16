"""Independent checks for the cache-only Tree1 C7/C8 geometry audit."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--audit-dir", type=Path, default=None)
    args = parser.parse_args()
    root = args.root
    audit = args.audit_dir or (root / "results" / "edge63_two_interval_gate2" / "tree1_C8" / "left_leaf_1_geometry_audit")
    cert = json.loads((audit / "geometry_audit_certificate.json").read_text(encoding="utf-8"))
    c7_path = root / "results" / "edge63_span_feasibility_frontier" / "corrected_tree1_gate1" / "final_span_candidates.csv"
    c7_rows = read_csv(c7_path)
    match_rows = read_csv(audit / "C7_C8_candidate_matching.csv")
    sep_rows = read_csv(audit / "C8_run_separation.csv")
    checks: dict[str, bool] = {}
    checks["versions_current"] = (
        cert.get("two_run_language") == "C8.LevelB.v1"
        and cert.get("allocation_dedup_version") == "ownership.v2"
        and cert.get("terminal_pair_cache_version") == "corrected.v2"
    )
    checks["cache_only_replay"] = cert.get("c8_stats", {}).get("cache_only_replay") is True
    checks["c7_rows_36"] = len(c7_rows) == 36
    checks["c7_no_stale_sigma66"] = min(int(row["span"]) for row in c7_rows) == 67
    checks["c8_rows_36"] = cert.get("c8_stats", {}).get("compatible_pairs") == 36 and len(cert.get("c8_rows", [])) == 36
    checks["c8_span_min_67"] = min(int(row["span"]) for row in cert.get("c8_rows", [])) == 67
    checks["c8_span_distribution_4_16_16"] = {int(k): int(v) for k, v in cert.get("c8_span_distribution", {}).items()} == {67: 4, 68: 16, 69: 16}
    checks["all_c8_rows_matched"] = cert.get("matching_stats", {}).get("c8_rows_unmatched") == 0
    checks["all_matches_exact_or_complement"] = all(row["relation"] in {"EXACT", "LABEL_COMPLEMENT"} for row in match_rows)
    # Each normalized C7 geometry has two raw rows because the actual tree
    # automorphism swaps the two equal-length right terminal leaves.  The
    # candidate-level cardinality is therefore checked through the 36 C8 rows;
    # the raw 72-row relation is expected and audited separately.
    checks["matching_cardinality_36"] = (
        cert.get("matching_stats", {}).get("matching_geometry_pairs") == 36
        and cert.get("matching_stats", {}).get("c8_rows_exactly_matched") == 0
        and cert.get("matching_stats", {}).get("c8_rows_label_complement_matched") == 36
        and len(match_rows) == 36
    )
    checks["actual_automorphism_documented"] = (
        cert.get("actual_graph_automorphism", {}).get("group_order") == 2
        and cert.get("actual_graph_automorphism", {}).get("nontrivial_action") == "swap right_leaf_1 and right_leaf_2"
    )
    checks["separation_rows_36"] = len(sep_rows) == 36
    checks["adjacent_count_recorded"] = cert.get("c8_adjacent_split_count", -1) + cert.get("c8_separated_split_count", -1) == 36
    checks["no_c8_span_le_63"] = all(int(row["span"]) > 63 for row in cert.get("c8_rows", []))
    checks["ownership_v2_raw_allocation_count"] = cert.get("c8_stats", {}).get("raw_allocations") == 20160
    checks["split_slot_is_left_leaf_1"] = cert.get("split_slot") == "left_leaf_1"
    checks["case_is_tree1"] = cert.get("case") == "fiveleaf3e-63-3-21-2-20-9-4-4"
    payload = {
        "verification_version": "C7-C8-geometry-audit-verify.v1",
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "c7_rows": len(c7_rows),
        "c8_rows": len(cert.get("c8_rows", [])),
        "matching_rows": len(match_rows),
        "scope": "Tree1 side-terminal split(left_leaf_1) only; cache-only replay; no C8 rerun",
    }
    (audit / "geometry_audit_verification.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
