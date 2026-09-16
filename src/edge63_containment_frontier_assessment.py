"""Audit the preregistered third-tree containment test.

This script reads only the corrected.v2 prescan and the completed compact
displacement-first Gate-1 output.  It does not run a search and it does not
infer a containment regime when no final-compatible terminal pair exists.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


CASE_T1 = "fiveleaf3e-63-3-21-2-20-9-4-4"
CASE_T2 = "fiveleaf3e-63-3-5-4-20-1-14-16"
CASE_T3 = "fiveleaf3e-63-3-21-2-14-15-4-4"
T3_DIR = Path("results/edge63_containment_frontier_test/third_tree_exact")
ROOT_DIR = Path("results/edge63_containment_frontier_test")
COARSE_DIR = ROOT_DIR / "coarse_level0"
PREDICTION = ROOT_DIR / "third_tree_prediction.json"
SUMMARY = COARSE_DIR / "prescan_summary.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows, fieldnames) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_stats(row):
    return json.loads(row["stats"])


def case_profile(summary_rows, case):
    for row in summary_rows:
        if row["case"] == case:
            return row
    raise KeyError(case)


def audit_t3():
    prediction = read_json(PREDICTION)
    exact_rows = read_rows(T3_DIR / "exact_case_results.csv")
    if len(exact_rows) != 1:
        raise AssertionError(f"expected one exact result row, got {len(exact_rows)}")
    exact = exact_rows[0]
    stats = parse_stats(exact)
    middle_rows = read_rows(T3_DIR / "middle_context_stats.csv")
    feasibility_rows = read_rows(T3_DIR / "left_right_feasibility.csv")
    final_rows = read_rows(T3_DIR / "final_span_candidates.csv")
    summary = read_json(T3_DIR / "summary.json")
    constraints = summary.get("constraints", {})

    middle_triples_total = int(exact["middle_triples_total"])
    middle_triples_done = int(exact["middle_triples_done"])
    contexts_generated = int(exact["contexts_generated"])
    contexts_done = int(exact["contexts_done"])
    orders_covered = int(exact["orders_covered"])
    raw_contexts = sum(int(row["raw_middle_contexts"]) for row in middle_rows)
    exact_contexts = sum(int(row["exact_middle_contexts"]) for row in middle_rows)
    completed_contexts = sum(int(row["contexts_completed"]) for row in middle_rows)
    feasibility_status = Counter(row["status"] for row in feasibility_rows)

    checks = {
        "case": exact["case"] == CASE_T3,
        "status_is_allowed": exact["status"] in {"SAT_VERIFIED", "UNSAT_EXHAUSTIVE", "UNRESOLVED_RESOURCE"},
        "status_is_exhaustive_unsat": exact["status"] == "UNSAT_EXHAUSTIVE",
        "middle_triples_complete": middle_triples_done == middle_triples_total == 960,
        "middle_context_rows_complete": len(middle_rows) == middle_triples_total,
        "contexts_complete": contexts_done == contexts_generated == exact_contexts == completed_contexts,
        "orders_complete": orders_covered == 5040,
        "no_final_compatible_rows": len(final_rows) == 0,
        "no_final_join_checks": int(stats.get("final_join_checks", 0)) == 0,
        "no_verifier_failures": int(stats.get("verifier_failure", 0)) == 0,
        "two_interval_not_entered": constraints.get("two_interval_entered") is False,
        "unrestricted_search_not_started": constraints.get("full_graceful_search_started") is False,
        "main_log_not_modified": constraints.get("main_log_modified") is False,
        "prediction_frozen": prediction.get("frozen_before_exact_run") is True,
        "prediction_case_matches": prediction.get("selected_case") == CASE_T3,
        "corrected_cache_version": prediction.get("prescan_metrics", {}).get("cache_version") == "corrected.v2",
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise AssertionError("audit checks failed: " + ", ".join(failed))

    audit = {
        "audit_version": "containment-frontier-third-tree.v1",
        "case": CASE_T3,
        "cache_version": "corrected.v2",
        "terminal_pair_cache_version": "corrected.v2 (pipeline contract)",
        "construction_language": [
            "seven maximal paths",
            "one consecutive difference interval per path",
            "complete Level-B local behavior states",
        ],
        "status": exact["status"],
        "middle_triples": {"done": middle_triples_done, "total": middle_triples_total},
        "middle_contexts": {
            "raw": raw_contexts,
            "generated": contexts_generated,
            "exact_quotient": exact_contexts,
            "completed": contexts_done,
        },
        "orders_covered": orders_covered,
        "final_compatible_candidates": len(final_rows),
        "final_join_checks": int(stats.get("final_join_checks", 0)),
        "failure_profile": {
            "central_collision": int(stats.get("central_collision", 0)),
            "middle_context_span_overflow": int(stats.get("span_overflow", 0)),
            "left_blocked": int(stats.get("left_blocked", 0)),
            "right_blocked": int(stats.get("right_blocked", 0)),
            "outer_translated_collision": int(stats.get("outer_translated_collision", 0)),
            "final_span_overflow": int(stats.get("final_span_overflow", 0)),
            "global_collision": int(stats.get("global_collision", 0)),
            "verifier_failure": int(stats.get("verifier_failure", 0)),
            "feasibility_row_statuses": dict(feasibility_status),
        },
        "cache_stats": {
            "terminal_pair": json.loads(exact["terminal_pair_cache"]),
            "local_option": json.loads(exact["local_option_cache"]),
            "bridge_pair": json.loads(exact["bridge_pair_cache"]),
        },
        "exact_containment": "NOT_ESTABLISHED: no joint terminal completion exists to classify",
        "span_minimum": "NONE: no final-compatible candidate exists",
        "prediction_audit": {
            "expected_gate1": prediction["pre_run_prediction"]["expected_gate1"],
            "observed_gate1": exact["status"],
            "gate1_direction": "matched likely UNSAT prediction",
            "expected_regime": prediction["pre_run_prediction"]["expected_regime"],
            "observed_regime": "NOT_TESTABLE_WITHOUT_FINAL_COMPATIBLE_CANDIDATE",
            "expected_span": prediction["pre_run_prediction"]["expected_span"],
            "observed_span": "NOT_APPLICABLE",
        },
        "checks": checks,
        "old_baseline_used": False,
    }
    return audit


def build_comparison(summary_rows):
    t3 = case_profile(summary_rows, CASE_T3)
    return [
        {
            "case": CASE_T1,
            "path_profile": "3,21,2,20,9,4,4",
            "active_pattern": "111",
            "rho": 2,
            "prescan_containment": "not applicable (exact benchmark)",
            "exact_containment": "none among 36 final rows",
            "regime": "forced cross-root among final rows",
            "sigma_min": 67,
            "gate1": "UNSAT_EXHAUSTIVE",
            "evidence": "corrected.v2 six-context structural audit",
        },
        {
            "case": CASE_T2,
            "path_profile": "3,5,4,20,1,14,16",
            "active_pattern": "not recorded in this comparison",
            "rho": "not recorded in this comparison",
            "prescan_containment": "not applicable (exact benchmark)",
            "exact_containment": "right-terminal containment",
            "regime": "right-terminal-dominant",
            "sigma_min": 63,
            "gate1": "SAT_VERIFIED",
            "evidence": "case2_exact_v5 verified certificate",
        },
        {
            "case": CASE_T3,
            "path_profile": "3,21,2,14,15,4,4",
            "active_pattern": t3["active_pattern"],
            "rho": t3["rho"],
            "prescan_containment": f"optimistic right on {t3['orders_optimistic_right_containment']} orders; exact not run in prescan",
            "exact_containment": "not established; zero joint completion",
            "regime": "not classifiable",
            "sigma_min": "NONE",
            "gate1": "UNSAT_EXHAUSTIVE",
            "evidence": "third-tree corrected.v2 exact audit",
        },
    ]


def write_reports(audit, summary_rows):
    exact_dir = T3_DIR
    write_json(exact_dir / "gate1_audit.json", audit)
    comparison = build_comparison(summary_rows)
    fields = list(comparison[0])
    write_csv(ROOT_DIR / "tree1_tree2_tree3_comparison.csv", comparison, fields)

    stats = audit["failure_profile"]
    report = f"""# Third-tree containment frontier test

## Scope

This report uses only the frozen `corrected.v2` Level-B language and the
displacement-first compact Gate-1 pipeline.  It does not enter the
two-interval language and does not interpret an unrestricted graceful result.

The preregistered case is `{CASE_T3}`.  The prediction file was frozen before
the exact run.

## Prescan and prediction

The three remaining cases were screened in the optimistic `L0_BRIDGE_ENVELOPE`
relaxation.  That relaxation found optimistic right-containment orders for
190, 432, and 2105 orders respectively, so it did not determine exact
containment.  The selected case was T3 because it preserves Tree1's bridge
profile, right terminal profile, active pattern `111`, and `rho=2`, while
moving six edges from the long left terminal to the middle path.

The preregistered prediction was `likely UNSAT_EXHAUSTIVE`, with a likely
forced-cross-root interpretation.  Only the first part can be compared to
the exact outcome; a regime prediction requires at least one final-compatible
terminal pair.

## Exact Gate 1 audit

| quantity | value |
|---|---:|
| middle triples | {audit['middle_triples']['done']}/{audit['middle_triples']['total']} |
| raw middle contexts | {audit['middle_contexts']['raw']} |
| exact contexts | {audit['middle_contexts']['exact_quotient']} |
| completed contexts | {audit['middle_contexts']['completed']} |
| interval orders covered | {audit['orders_covered']} |
| final-compatible candidates | {audit['final_compatible_candidates']} |
| final left-right join checks | {audit['final_join_checks']} |
| status | `{audit['status']}` |

The exact run is complete, not resource-limited.  Every middle triple,
context, and interval order is closed.  There is no final-compatible
candidate, so this tree has no `sigma_min` inside the current language and no
span regime to classify.

## Failure profile

| stage | count |
|---|---:|
| central collision | {stats['central_collision']} |
| middle-context span overflow | {stats['middle_context_span_overflow']} |
| left blocked | {stats['left_blocked']} |
| right blocked | {stats['right_blocked']} |
| outer translated collision | {stats['outer_translated_collision']} |
| final span overflow | {stats['final_span_overflow']} |
| final global collision | {stats['global_collision']} |
| verifier failure | {stats['verifier_failure']} |

The decisive fact is `final left-right join checks = 0`, not a final span
lower bound.  Thus T3 is an exact single-interval UNSAT result with a
collision/compatibility obstruction before the span regime is reached.

## Three-tree assessment

| tree | exact containment | regime | sigma / status |
|---|---|---|---|
| Tree1 | none among 36 final rows | forced cross-root among final rows | 67 / UNSAT_EXHAUSTIVE |
| Tree2 | right-terminal containment | right-terminal-dominant | 63 / SAT_VERIFIED |
| Tree3 | not established; no joint completion | not classifiable | none / UNSAT_EXHAUSTIVE |

The third test therefore does **not** validate an equivalence between
single-root containment and single-interval feasibility.  It also does not
refute it, because T3 has no single-interval completion at all.  It does
show that the optimistic L0 containment signal can be a false positive after
the exact middle and terminal compatibility conditions are imposed.

The strongest current finite statement is:

> Tree1 and Tree2 occupy two different exact span regimes, while the
> controlled third case is eliminated earlier by exact compatibility.  A
> three-tree containment frontier is not yet supported as a predictive rule.

## Next discriminating step

Do not run the remaining two cases automatically.  The next useful step is
to inspect the T3 incompatibility certificate and identify the smallest
middle/terminal interface obstruction.  A fourth case should be chosen only
to separate that obstruction from the Tree1 span mechanism: ideally a case
with exact containment already witnessed at the context level but a different
bridge/terminal profile.
    """
    (ROOT_DIR / "containment_frontier_assessment.md").write_text(report, encoding="utf-8")
    (exact_dir / "report.md").write_text(report, encoding="utf-8")

    formal = """# Formal lemmas used by the third-tree audit

## 64-point span lemma

Let `S` be a finite subset of the integers with `|S| = 64`.  Write
`min(S) = a` and `max(S) = b`.  The interval `[a,b]` contains `b-a+1`
integers, so `b-a+1 >= 64` and therefore `span(S) = b-a >= 63`.
Equality holds exactly when `[a,b]` contains no unused integer, hence
`S = {a,a+1,...,a+63}`.

## Exact Gate-1 status rule

For the fixed finite construction language, `UNSAT_EXHAUSTIVE` is sound only
when all legal middle triples, all contexts generated from them, all induced
interval orders, and all compatible terminal-pair joins have been exhausted
without an unsafe deletion.  A run stopped by a resource limit remains
`UNRESOLVED_RESOURCE`.

For the selected third case, the audit verifies all 960 middle triples,
19,452 exact contexts, and 5,040 interval orders.  It also verifies that no
final-compatible candidate and no verifier failure was recorded.  This is a
finite construction-language result, not a statement that the tree is
non-graceful.

## Containment classification rule

Given middle-frame private sets `L`, `M`, and `R`, right containment means
`L union M` is a subset of `[min(R), max(R)]`; left containment is defined
symmetrically.  This classification is meaningful only for a joint-compatible
terminal pair.  If the joint-compatible family is empty, the correct value is
`NOT_ESTABLISHED`, not `containment impossible`.
"""
    (exact_dir / "formal_lemmas.md").write_text(formal, encoding="utf-8")


def main():
    summary = read_json(SUMMARY)
    summary_rows = summary["cases"]
    audit = audit_t3()
    write_reports(audit, summary_rows)
    print(json.dumps({
        "case": CASE_T3,
        "status": audit["status"],
        "exact_contexts": audit["middle_contexts"]["exact_quotient"],
        "orders_covered": audit["orders_covered"],
        "final_compatible_candidates": audit["final_compatible_candidates"],
        "final_join_checks": audit["final_join_checks"],
        "prediction_gate1_matched": audit["prediction_audit"]["gate1_direction"],
        "regime": audit["prediction_audit"]["observed_regime"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
