"""Independently verify the completed third-tree Gate-1 accounting.

The verifier intentionally does not import the search implementation.  It
checks the persisted CSV/JSON ledger and the finite-exhaustion invariants.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


CASE = "fiveleaf3e-63-3-21-2-14-15-4-4"
ROOT = Path("results/edge63_containment_frontier_test")
EXACT = ROOT / "third_tree_exact"


def rows(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    exact_rows = rows(EXACT / "exact_case_results.csv")
    if len(exact_rows) != 1:
        raise AssertionError(f"expected one exact row, got {len(exact_rows)}")
    exact = exact_rows[0]
    stats = json.loads(exact["stats"])
    summary = load(EXACT / "summary.json")
    constraints = summary["constraints"]
    middle_rows = rows(EXACT / "middle_context_stats.csv")
    final_rows = rows(EXACT / "final_span_candidates.csv")
    prediction = load(ROOT / "third_tree_prediction.json")

    checks = {
        "case": exact["case"] == CASE,
        "status": exact["status"] == "UNSAT_EXHAUSTIVE",
        "all_middle_triples_done": int(exact["middle_triples_done"]) == int(exact["middle_triples_total"]) == 960,
        "all_middle_triple_rows_present": len(middle_rows) == 960,
        "all_contexts_done": int(exact["contexts_done"]) == int(exact["contexts_generated"]) == 19452,
        "all_orders_covered": int(exact["orders_covered"]) == 5040,
        "no_final_rows": len(final_rows) == 0,
        "no_final_join_checks": int(stats.get("final_join_checks", 0)) == 0,
        "no_verifier_failures": int(stats.get("verifier_failure", 0)) == 0,
        "two_interval_false": constraints["two_interval_entered"] is False,
        "unrestricted_search_false": constraints["full_graceful_search_started"] is False,
        "main_log_false": constraints["main_log_modified"] is False,
        "prediction_frozen": prediction["frozen_before_exact_run"] is True,
        "prediction_case": prediction["selected_case"] == CASE,
        "corrected_v2": prediction["prescan_metrics"]["cache_version"] == "corrected.v2",
    }
    if not all(checks.values()):
        raise AssertionError("failed checks: " + ", ".join(k for k, v in checks.items() if not v))

    result = {
        "verification_version": "third-tree-gate1-independent.v1",
        "case": CASE,
        "status": "PASS",
        "construction_language": {
            "maximal_paths": 7,
            "interval_runs_per_path": 1,
            "local_language": "complete Level-B",
            "terminal_pair_cache": "corrected.v2",
        },
        "checks": checks,
        "derived": {
            "middle_triples": 960,
            "exact_contexts": 19452,
            "interval_orders": 5040,
            "final_compatible_candidates": 0,
            "regime": "NOT_CLASSIFIABLE_NO_FINAL_COMPATIBLE_COMPLETION",
            "sigma_min": "NONE",
        },
        "note": "Finite construction-language UNSAT only; not a graceful nonexistence result.",
    }
    (EXACT / "gate1_audit_verification.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
