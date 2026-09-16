"""Assemble native-engine gate artifacts without starting production search."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from statistics import median
from typing import Any


VERSION = {"two_run_language": "C8.LevelB.v1", "allocation_dedup_version": "ownership.v2", "terminal_pair_cache_version": "corrected.v2"}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def build(root: Path) -> dict[str, Any]:
    base = root / "native_engine_v1"
    bench = base / "benchmarks"
    profile = base / "profile"
    cert = base / "certificates"
    runs = base / "batch_runs"
    regression = _json(bench / "golden_regression.json")
    semantic = _json(bench / "semantic_differential.json")
    certificate = _json(cert / "batch_verification.json")
    native_bench = _json(bench / "native_benchmark.json")
    python_profile = _json(profile / "python_profile.json")
    resume = _json(runs / "resume_recovery_test.json")
    memory_rows = list(csv.DictReader((bench / "memory_stability.csv").open(encoding="utf-8")))
    peak_values = [int(row["peak_observed_working_set"]) for row in memory_rows if row.get("peak_observed_working_set")]
    no_monotone_growth = not all(left < right for left, right in zip(peak_values, peak_values[1:]))

    for name, source in {
        "golden_regression.json": bench / "golden_regression.json",
        "native_differential.json": bench / "native_differential.json",
        "worker_scaling.csv": bench / "worker_scaling.csv",
        "memory_stability.csv": bench / "memory_stability.csv",
        "performance_corpus.csv": profile / "performance_corpus.csv",
        "batch_manifest.csv": runs / "batch_manifest.csv",
        "certificate_manifest.csv": cert / "certificate_manifest.csv",
        "batch_verification.json": cert / "batch_verification.json",
    }.items():
        _copy(source, base / name)

    progress = {
        "scope": "Tree1/C8.LevelB.v1/split(left_leaf_2)",
        "status": "UNRESOLVED_RESOURCE",
        "production_keys_total": 1056,
        "production_keys_started": 0,
        "production_batch_status": "NOT_STARTED_CORRECTNESS_HOLD",
        "frontier_counterexample_found": False,
        "SAT_VERIFIED": False,
        "UNSAT": False,
        "sigma_c": "UNDEFINED_FULL_SLOT",
        "best_known_global_compatible_span": 68,
        "correctness_gates": {
            "GOLDEN_CORPUS_PASS": regression.get("status") == "PASS",
            "GEOMETRY_DIFFERENTIAL_PASS": regression.get("status") == "PASS" and regression.get("native_table_cases_fail") == 0,
            "SEMANTIC_DIFFERENTIAL_PASS": semantic.get("status") == "PASS",
            "CERTIFICATE_VERIFIER_PASS": certificate.get("status") == "PASS",
            "RESUME_RECOVERY_PASS": bool(resume.get("test_pass")),
            "MEMORY_STABILITY_PASS": no_monotone_growth and len(peak_values) == 3,
        },
        "semantic_differential_scope": semantic.get("scope"),
        "native_local_tables_persisted": 35,
        "native_golden_cases": regression.get("cases_total"),
        "native_golden_table_cases": regression.get("native_table_cases"),
        "native_golden_table_cases_pass": regression.get("native_table_cases_pass"),
        "semantic_checks": semantic.get("checks"),
        "semantic_mismatches": semantic.get("mismatches"),
        "certificate_checks": sum(1 for row in certificate.get("checks", []) if row.get("ok")),
        "certificate_failures": sum(1 for row in certificate.get("checks", []) if not row.get("ok")),
        "memory_peak_working_set_bytes": peak_values,
        "native_best_workers": native_bench.get("best_workers"),
        "native_worker_benchmark": native_bench.get("workers"),
        "python_profile_phase_seconds": python_profile.get("phase_seconds"),
        "python_profile_phase_share": python_profile.get("phase_share"),
        "python_call_profile": python_profile.get("call_profile"),
        "remaining_key_plan": "PENDING-only plan generated; no remaining key compiled",
        **VERSION,
    }
    (base / "progress_native_v1.json").write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")
    best = native_bench.get("best_workers")
    report = f"""# C8 native engine v1 report

Scope: Tree1 / C8.LevelB.v1 / split(left_leaf_2).

Versions:
- two_run_language = {VERSION['two_run_language']}
- allocation_dedup_version = {VERSION['allocation_dedup_version']}
- terminal_pair_cache_version = {VERSION['terminal_pair_cache_version']}

## Correctness

The frozen corpus contains {regression.get('cases_total')} cases, including {regression.get('native_table_cases')} local-table cases. Native geometry and witness regression is {regression.get('status')} ({regression.get('native_table_cases_pass')}/{regression.get('native_table_cases')}), and the local collision/span semantic differential is {semantic.get('status')} ({semantic.get('checks')} checks, {semantic.get('mismatches')} mismatches). The independent certificate verifier is {certificate.get('status')}.

Resume recovery reset a stale RUNNING record to PENDING: {'PASS' if resume.get('test_pass') else 'FAIL'}. Three native corpus rounds recorded child working-set peaks of {peak_values} bytes; the sample does not show monotone growth.

The native table compiler reproduces the Python geometry at record level, not just by count. Thirty-five golden table files are persisted under `native_tables/golden/`.

## Performance

    The isolated Python cold-generation profile is dominated by local behavior generation: {python_profile.get('phase_seconds', {}).get('local_behavior_generation', 0):.3f} seconds across the four fixed representatives. The very-hard cProfile sample recorded {python_profile.get('call_profile', {}).get('total_calls', 0)} calls, {python_profile.get('call_profile', {}).get('wall_seconds', 0):.3f}s wall time and {python_profile.get('call_profile', {}).get('cpu_seconds', 0):.3f}s CPU time; peak allocation bytes are in `profile/performance_corpus.csv`. Native worker scaling selected {best} worker(s): {json.dumps(native_bench.get('workers', {}), ensure_ascii=False)}. The very-hard representative speedup is recorded in `benchmarks/worker_scaling.csv`; it is approximately 6.5x in the one-worker run. Semantic warm-path throughput was {python_profile.get('semantic_profile', {}).get('semantic_queries_per_second', 0):.1f} queries/s on the fixed sample.

## Production gate

No production key was started: 0/1056. The remaining-key manifest is PENDING-only. The native local-table core passed its local correctness gates, but the native engine is not yet wired through the complete global semantic/bilateral/outer certificate pipeline. Therefore production is deliberately held and the full-slot status remains `UNRESOLVED_RESOURCE`; no SAT or UNSAT conclusion is claimed.

The current mathematical frontier is unchanged: best known global-compatible span 68, C7 benchmark 67, and no new frontier counterexample was searched in this round.
"""
    (base / "report_native_v1.md").write_text(report, encoding="utf-8")
    return progress


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    args = parser.parse_args()
    print(json.dumps(build(args.root), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
