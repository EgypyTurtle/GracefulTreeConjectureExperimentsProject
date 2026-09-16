"""Independently verify the persisted Tree3 obstruction certificate."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


CASE = "fiveleaf3e-63-3-21-2-14-15-4-4"
ROOT = Path("results/edge63_tree3_compatibility_obstruction")
EXACT = Path("results/edge63_containment_frontier_test/third_tree_exact")


def rows(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    certificate = load(ROOT / "tree3_compatibility_obstruction_certificate.json")
    context_rows = rows(ROOT / "context_failure_census.csv")
    left_rows = rows(ROOT / "left_blocking_analysis.csv")
    outer_rows = rows(ROOT / "outer_collision_16.csv")
    matrix_rows = rows(ROOT / "outer_collision_matrix_summary.csv")
    final_rows = rows(EXACT / "final_span_candidates.csv")
    exact = rows(EXACT / "exact_case_results.csv")
    prediction = load(Path("results/edge63_containment_frontier_test/third_tree_prediction.json"))

    classes = Counter(row["earliest_failure"] for row in context_rows)
    left_contexts = sum(bool(int(row["left_nonempty_assignments"])) for row in context_rows)
    right_contexts = sum(bool(int(row["right_nonempty_assignments"])) for row in context_rows)
    both_contexts = sum(bool(int(row["both_sides_nonempty_assignments"])) for row in context_rows)
    outer_contexts = sum(bool(int(row["outer_compatible_assignments"])) for row in context_rows)
    distinct_outer_contexts = len({(row["triple_id"], row["context_id"]) for row in outer_rows})

    checks = {
        "case": certificate["case"] == CASE and len(exact) == 1 and exact[0]["case"] == CASE,
        "corrected_v2": certificate["cache_version"] == "corrected.v2",
        "context_count": len(context_rows) == 19452,
        "context_keys_unique": len({(row["triple_id"], row["context_id"]) for row in context_rows}) == 19452,
        "context_classes_match": dict(classes) == certificate["context_census"],
        "context_classes_cover_all": sum(classes.values()) == 19452,
        "left_context_count_match": left_contexts == certificate["near_survivor"]["contexts_with_left_nonempty"],
        "right_context_count_match": right_contexts == certificate["near_survivor"]["contexts_with_right_nonempty"],
        "both_context_count_match": both_contexts == 6,
        "outer_context_count_zero": outer_contexts == 0,
        "outer_events_match": len(outer_rows) == 16,
        "outer_contexts_match": distinct_outer_contexts == 6,
        "matrix_rows_match": len(matrix_rows) == 6 and all(int(row["outer_compatible_pairs"]) == 0 for row in matrix_rows),
        "left_rows_complete": len(left_rows) == 19452,
        "no_final_rows": len(final_rows) == 0,
        "exact_gate1_unsat": exact[0]["status"] == "UNSAT_EXHAUSTIVE",
        "prediction_frozen": prediction["frozen_before_exact_run"] is True,
        "old_baseline_not_used": certificate["old_baseline_used"] is False,
    }
    if not all(checks.values()):
        raise AssertionError("failed checks: " + ", ".join(k for k, v in checks.items() if not v))

    result = {
        "verification_version": "tree3-obstruction-independent.v1",
        "case": CASE,
        "status": "PASS",
        "checks": checks,
        "derived": {
            "context_classes": dict(classes),
            "contexts_with_left_nonempty": left_contexts,
            "contexts_with_right_nonempty": right_contexts,
            "contexts_with_both_sides_nonempty": both_contexts,
            "contexts_with_outer_compatible": outer_contexts,
            "outer_collision_events": len(outer_rows),
            "outer_collision_contexts": distinct_outer_contexts,
        },
        "hitting_set_note": "The persisted hitting-set rows are a cross-context exact sample, not a claim that one set covers every left-blocked context.",
        "finite_scope_note": "This verifies the finite construction obstruction only; it is not a graceful nonexistence proof.",
    }
    (ROOT / "tree3_compatibility_obstruction_verification.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
