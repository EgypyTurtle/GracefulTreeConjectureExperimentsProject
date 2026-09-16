"""Edge64 extreme-tail profiling and controlled solver optimization.

This module deliberately operates only on the frozen residual/robust sets from
``edge64_hardtail_v1``.  It does not regenerate the canonical edge64 universe
and does not launch full production search.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge64_baseline import options as baseline_options  # noqa: E402
from graceful_tree import (  # noqa: E402
    build_adj,
    close_pendant_extension_cache,
    reconstruct_named_five_leaf_case,
    solve_graceful_branch_differences,
    solve_graceful_by_differences,
    solve_graceful_tension,
    solve_tree,
    verify_labeling,
)


BASE = ROOT / "results" / "edge64_hardtail_v1"
OUT = ROOT / "results" / "edge64_solver_optimization_v1"
METHODS = ("compressed", "branch", "hybrid", "tension", "diff")
BENCHMARK_METHODS = METHODS + ("tension_label_first",)
EXTREMES = {
    "EXTREME_A": "fiveleaf3e-64-8-5-9-12-10-10-10",
    "EXTREME_B": "fiveleaf2e-64-7-3-3-9-20-22",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def stable_seed(case_id: str, method: str) -> int:
    return int.from_bytes(hashlib.blake2b(f"{case_id}:{method}:optimization".encode("ascii"), digest_size=8).digest(), "big")


def load_sources() -> tuple[list[dict[str, str]], dict[str, dict[str, str]], dict[str, dict[str, str]], dict[str, list[dict[str, str]]]]:
    residual = read_csv(BASE / "residual4693_manifest.csv")
    residual_by_id = {row["case_id"]: row for row in residual}
    robust_rows = read_csv(BASE / "robust_hard_manifest.csv")
    budgets: dict[str, list[dict[str, str]]] = {}
    for name in ("budget_0.5.csv", "budget_1.csv", "budget_2.csv", "budget_5.csv", "high_budget_256_results.csv"):
        path = BASE / name
        if path.exists():
            budgets[name] = read_csv(path)
    return residual, residual_by_id, {row["case_id"]: row for row in robust_rows}, budgets


def enrich_case(row: dict[str, str], budgets: dict[str, list[dict[str, str]]]) -> dict[str, object]:
    case_id = row["case_id"]
    result: dict[str, object] = dict(row)
    for filename, items in budgets.items():
        item = next((entry for entry in items if entry.get("case_id") == case_id), None)
        if item is None:
            continue
        tag = filename.removesuffix(".csv").replace(".", "_")
        for field in ("status", "solved", "strategy", "nodes", "backtracks", "elapsed_seconds", "error"):
            result[f"{tag}_{field}"] = item.get(field, "")
    return result


def freeze_manifests() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    residual, residual_by_id, robust_by_id, budgets = load_sources()
    robust = [enrich_case(residual_by_id[case_id], budgets) for case_id in sorted(robust_by_id)]
    extremes = [row for row in robust if row["case_id"] in EXTREMES.values()]
    common_fields = list(residual[0].keys())
    for row in robust:
        for key in row:
            if key not in common_fields:
                common_fields.append(key)
    for row in robust:
        row["extreme_tag"] = next((tag for tag, case_id in EXTREMES.items() if case_id == row["case_id"]), "")
    write_csv(OUT / "robust24_manifest.csv", robust, common_fields + ["extreme_tag"])
    write_csv(OUT / "extreme2_manifest.csv", extremes, common_fields + ["extreme_tag"])
    return robust, extremes


def parameter_distance(left: dict[str, str], right: dict[str, str]) -> int:
    fields = ("skeleton", "bridge_length", "left_bridge", "right_bridge", "middle_leaf", "terminal_lengths", "branch_balance")
    distance = 0
    for field in fields:
        if left.get(field, "") != right.get(field, ""):
            distance += 1
    return distance


def select_controls(robust: list[dict[str, object]], extremes: list[dict[str, object]], residual: list[dict[str, str]], budgets: dict[str, list[dict[str, str]]]) -> list[dict[str, object]]:
    robust_ids = {str(row["case_id"]) for row in robust}
    solved30 = {row["case_id"] for row in budgets.get("high_budget_256_results.csv", []) if row.get("solved") == "1"}
    solved5 = {row["case_id"] for row in budgets.get("budget_5.csv", []) if row.get("solved") == "1"}
    solved_fast = {row["case_id"] for row in budgets.get("budget_0.5.csv", []) if row.get("solved") == "1"}
    pool = [row for row in residual if row["case_id"] not in robust_ids]
    controls: list[dict[str, object]] = []
    for extreme in extremes:
        for candidate in sorted(pool, key=lambda item: (item["case_id"])):
            exact = int(candidate.get("stratum", "") == extreme.get("stratum", ""))
            same_skeleton = int(candidate.get("skeleton", "") == extreme.get("skeleton", ""))
            same_bridge = int(candidate.get("bridge_profile", "") == extreme.get("bridge_profile", ""))
            match_level = 0 if exact else 1 if same_skeleton and same_bridge else 2 if same_skeleton else 3
            category = "fast_solved" if candidate["case_id"] in solved_fast else "five_second_solved" if candidate["case_id"] in solved5 else "near_hard"
            category_rank = {"fast_solved": 0, "five_second_solved": 1, "near_hard": 2}[category]
            score = (match_level, category_rank, parameter_distance(candidate, extreme), hashlib.blake2b(candidate["case_id"].encode("ascii"), digest_size=8).hexdigest())
            candidate_copy = dict(candidate)
            candidate_copy.update({"control_for": next(tag for tag, case_id in EXTREMES.items() if case_id == extreme["case_id"]), "match_level": match_level, "control_category": category, "control_score": score[2]})
            controls.append(candidate_copy)
            if sum(1 for row in controls if row["control_for"] == candidate_copy["control_for"]) >= 30:
                break
    fields = []
    for row in controls:
        for key in row:
            if key not in fields:
                fields.append(key)
    write_csv(OUT / "matched_controls.csv", controls, fields)
    return controls


def new_trace(case_id: str, method: str, budget: float) -> dict[str, object]:
    return {
        "case_id": case_id,
        "method": method,
        "budget_seconds": budget,
        "nodes_by_depth": {},
        "branching_by_depth": {},
        "contradictions_by_depth": {},
        "contradiction_reasons": {},
        "rejects": {},
        "branch_choices": [],
        "max_recursion_depth": 0,
    }


def run_traced(case_id: str, method: str, budget: float) -> tuple[dict[str, object], dict[str, object]]:
    started = time.time()
    trace = new_trace(case_id, method, budget)
    labels = None
    error = ""
    try:
        n, edges = reconstruct_named_five_leaf_case(case_id)
        adj = build_adj(n, edges)
        cache = str(OUT / "trace_cache" / f"{method}.sqlite3")
        if method in ("compressed", "hybrid"):
            args = baseline_options(method, budget, cache)
            args.trace = trace
            labels, stats = solve_tree(adj, args, seed=stable_seed(case_id, method))
        elif method == "diff":
            labels, stats = solve_graceful_by_differences(adj, time_limit=budget, seed=stable_seed(case_id, method), trace=trace)
        elif method == "branch":
            labels, stats = solve_graceful_branch_differences(adj, time_limit=budget, seed=stable_seed(case_id, method), trace=trace)
        elif method == "tension":
            labels, stats = solve_graceful_tension(adj, time_limit=budget, seed=stable_seed(case_id, method), trace=trace)
        elif method == "tension_label_first":
            labels, stats = solve_graceful_tension(adj, time_limit=budget, seed=stable_seed(case_id, method), move_order="label_first")
        else:
            raise ValueError(method)
        solved = labels is not None and verify_labeling(edges, labels)
        status = "solved" if solved else "timeout_or_failed"
        strategy = stats.strategy
        nodes = stats.nodes
        backtracks = stats.backtracks
    except Exception as exc:  # profiling must preserve the case for diagnosis
        solved = False
        status = "error"
        strategy = method
        nodes = 0
        backtracks = 0
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.time() - started
    trace["elapsed_seconds"] = elapsed
    trace["solved"] = int(solved)
    trace["status"] = status
    trace["strategy"] = strategy
    trace["nodes"] = nodes
    trace["backtracks"] = backtracks
    trace["error"] = error
    row = {
        "case_id": case_id,
        "method": method,
        "budget_seconds": budget,
        "status": status,
        "solved": int(solved),
        "strategy": strategy,
        "nodes": nodes,
        "backtracks": backtracks,
        "elapsed_seconds": elapsed,
        "nodes_per_second": nodes / elapsed if elapsed else 0.0,
        "error": error,
        "max_recursion_depth": trace.get("max_recursion_depth", 0),
    }
    return row, trace


def trace_summary(trace: dict[str, object]) -> dict[str, object]:
    branching = trace.get("branching_by_depth", {})
    branch_counts = [int(item["sum"]) / int(item["calls"]) for item in branching.values() if int(item["calls"])]
    contradiction_counts = trace.get("contradictions_by_depth", {})
    contradiction_depths = [int(depth) for depth, count in contradiction_counts.items() for _ in range(int(count))]
    return {
        "average_branching_factor": statistics.fmean(branch_counts) if branch_counts else 0.0,
        "max_branching_factor": max((int(item["max"]) for item in branching.values()), default=0),
        "first_contradiction_depth": trace.get("first_contradiction_depth", ""),
        "median_contradiction_depth": statistics.median(contradiction_depths) if contradiction_depths else "",
        "forced_move_calls": sum(int(item["calls"]) for item in branching.values() if int(item["max"]) == 1),
        "contradiction_count": sum(int(value) for value in contradiction_counts.values()),
        "active_branch_count": sum(int(value) for value in trace.get("nodes_by_depth", {}).values()),
        "reject_total": sum(int(value) for value in trace.get("rejects", {}).values()),
    }


def run_trace_corpus(robust: list[dict[str, object]], budget: float = 1.0) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    profile_rows: list[dict[str, object]] = []
    depth_rows: list[dict[str, object]] = []
    strategy_rows: list[dict[str, object]] = []
    raw_trace_path = OUT / "trace_raw.jsonl"
    with raw_trace_path.open("w", encoding="utf-8") as raw:
        for case in robust:
            case_id = str(case["case_id"])
            for method in METHODS:
                row, trace = run_traced(case_id, method, budget)
                summary = trace_summary(trace)
                profile = dict(row)
                profile.update(summary)
                profile["rejects_json"] = json.dumps(trace.get("rejects", {}), sort_keys=True)
                profile["contradiction_reasons_json"] = json.dumps(trace.get("contradiction_reasons", {}), sort_keys=True)
                profile_rows.append(profile)
                for depth, count in sorted(trace.get("nodes_by_depth", {}).items(), key=lambda item: int(item[0])):
                    depth_rows.append({"case_id": case_id, "method": method, "depth": depth, "nodes": count, "branch_calls": trace.get("branching_by_depth", {}).get(depth, {}).get("calls", 0), "branch_sum": trace.get("branching_by_depth", {}).get(depth, {}).get("sum", 0), "branch_max": trace.get("branching_by_depth", {}).get(depth, {}).get("max", 0), "contradictions": trace.get("contradictions_by_depth", {}).get(depth, 0)})
                strategy_rows.append({"case_id": case_id, "method": method, "status": row["status"], "nodes": row["nodes"], "elapsed_seconds": row["elapsed_seconds"], "first_branch_choices": json.dumps(trace.get("branch_choices", [])[:8], sort_keys=True)})
                raw.write(json.dumps(trace, sort_keys=True) + "\n")
                raw.flush()
    write_csv(OUT / "search_tree_profiles.csv", profile_rows, list(profile_rows[0]) if profile_rows else ["case_id"])
    write_csv(OUT / "depth_profiles.csv", depth_rows, list(depth_rows[0]) if depth_rows else ["case_id"])
    write_csv(OUT / "strategy_trace_comparison.csv", strategy_rows, list(strategy_rows[0]) if strategy_rows else ["case_id"])
    return profile_rows, depth_rows, strategy_rows


def basic_worker(payload: tuple[str, str, float]) -> dict[str, object]:
    case_id, method, budget = payload
    started = time.time()
    try:
        n, edges = reconstruct_named_five_leaf_case(case_id)
        adj = build_adj(n, edges)
        if method in ("compressed", "hybrid"):
            args = baseline_options(method, budget, str(OUT / "control_cache" / f"{os.getpid()}.sqlite3"))
            labels, stats = solve_tree(adj, args, seed=stable_seed(case_id, method))
        elif method == "branch":
            labels, stats = solve_graceful_branch_differences(adj, time_limit=budget, seed=stable_seed(case_id, method))
        elif method == "tension":
            labels, stats = solve_graceful_tension(adj, time_limit=budget, seed=stable_seed(case_id, method))
        elif method == "tension_label_first":
            labels, stats = solve_graceful_tension(adj, time_limit=budget, seed=stable_seed(case_id, method), move_order="label_first")
        else:
            labels, stats = solve_graceful_by_differences(adj, time_limit=budget, seed=stable_seed(case_id, method))
        solved = int(labels is not None and verify_labeling(edges, labels))
        return {"case_id": case_id, "method": method, "budget_seconds": budget, "solved": solved, "status": "solved" if solved else "timeout_or_failed", "nodes": stats.nodes, "backtracks": stats.backtracks, "elapsed_seconds": time.time() - started, "strategy": stats.strategy, "error": ""}
    except Exception as exc:
        return {"case_id": case_id, "method": method, "budget_seconds": budget, "solved": 0, "status": "error", "nodes": 0, "backtracks": 0, "elapsed_seconds": time.time() - started, "strategy": method, "error": f"{type(exc).__name__}: {exc}"}


def run_control_tournament(robust: list[dict[str, object]], controls: list[dict[str, object]], budget: float = 1.0) -> list[dict[str, object]]:
    control_ids = sorted({str(row["case_id"]) for row in controls})
    corpus_ids = sorted({str(row["case_id"]) for row in robust} | set(control_ids))
    payloads = [(case_id, method, budget) for case_id in corpus_ids for method in BENCHMARK_METHODS]
    with ProcessPoolExecutor(max_workers=2) as executor:
        rows = list(executor.map(basic_worker, payloads, chunksize=1))
    write_csv(OUT / "candidate_strategy_benchmarks.csv", rows, list(rows[0]) if rows else ["case_id"])
    return rows


def portfolio(rows: list[dict[str, object]]) -> dict[str, object]:
    universe = sorted({str(row["case_id"]) for row in rows})
    methods = tuple(dict.fromkeys(str(row["method"]) for row in rows))
    solved = {method: {str(row["case_id"]) for row in rows if row["method"] == method and str(row["solved"]) == "1"} for method in methods}
    uncovered = set(universe)
    selected = []
    while uncovered:
        options = [(len(solved[method] & uncovered), method) for method in methods if method not in {item["method"] for item in selected}]
        if not options:
            break
        gain, method = max(options)
        if gain == 0:
            break
        uncovered -= solved[method]
        selected.append({"method": method, "newly_solved": gain, "cumulative_solved": len(set(universe) - uncovered)})
    return {"corpus_cases": len(universe), "methods": methods, "greedy_portfolio": selected, "uncovered": len(uncovered), "coverage": (len(universe) - len(uncovered)) / len(universe) if universe else 0.0}


def run_high_budget(extremes: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for budget in (60.0, 120.0, 300.0):
        for case in extremes:
            row = basic_worker((str(case["case_id"]), "compressed", budget))
            row["budget_stage"] = budget
            rows.append(row)
            if row["solved"]:
                break
    write_csv(OUT / "extreme_budget_survival.csv", rows, list(rows[0]) if rows else ["case_id"])
    return rows


def weighted_projection(residual: list[dict[str, str]], robust_ids: set[str]) -> dict[str, object]:
    total = len(residual)
    by_stratum: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in residual:
        by_stratum[row["stratum"]].append(row)
    rows = []
    weighted_robust = 0.0
    for stratum, members in sorted(by_stratum.items()):
        count = sum(row["case_id"] in robust_ids for row in members)
        rate = count / len(members) if members else 0.0
        weight = len(members) / total if total else 0.0
        weighted_robust += weight * rate
        rows.append({"stratum": stratum, "residual_cases": len(members), "robust_hard": count, "robust_rate": rate, "weight": weight})
    universe = 10_040_677
    return {"residual_cases": total, "weighted_robust_rate": weighted_robust, "projected_edge64_robust_hard": round(weighted_robust * universe), "stratum_rows": rows, "note": "Planning projection from the frozen stratified residual scope; not a formal confidence interval."}


def verify_outputs(robust: list[dict[str, object]], extremes: list[dict[str, object]], profile_rows: list[dict[str, object]], benchmark_rows: list[dict[str, object]], high_rows: list[dict[str, object]]) -> dict[str, object]:
    expected_extreme_ids = set(EXTREMES.values())
    profile_cases = {str(row["case_id"]) for row in profile_rows}
    errors = [row for row in profile_rows + benchmark_rows + high_rows if str(row.get("status")) == "error"]
    return {
        "status": "PASS" if len(robust) == 24 and {str(row["case_id"]) for row in extremes} == expected_extreme_ids and expected_extreme_ids <= profile_cases and not errors else "FAIL",
        "robust_count": len(robust),
        "extreme_count": len(extremes),
        "profile_rows": len(profile_rows),
        "benchmark_rows": len(benchmark_rows),
        "high_budget_rows": len(high_rows),
        "errors": errors,
        "trace_backend": "instrumented existing solver; no new search semantics",
    }


def write_report(robust: list[dict[str, object]], controls: list[dict[str, object]], profiles: list[dict[str, object]], benchmarks: list[dict[str, object]], high_rows: list[dict[str, object]], portfolio_data: dict[str, object], projection: dict[str, object], verification: dict[str, object]) -> None:
    benchmark_methods = sorted({str(row["method"]) for row in benchmarks})
    solved_by_method = {method: sum(str(row["solved"]) == "1" for row in benchmarks if row["method"] == method) for method in benchmark_methods}
    extreme_status = {}
    for tag, case_id in EXTREMES.items():
        case_rows = [row for row in high_rows if row["case_id"] == case_id]
        extreme_status[tag] = case_rows[-1].get("status", "not_run") if case_rows else "not_run"
    report = [
        "# Edge64 extreme solver-tail optimization",
        "",
        "This round is restricted to the frozen robust24 set and matched/near-hard controls. Full edge64 production was not started and no structural theorem search was performed.",
        "",
        f"- robust cases: {len(robust)}",
        f"- matched controls: {len(controls)} rows",
        f"- traced profile rows: {len(profiles)}",
        f"- strategy benchmark rows: {len(benchmarks)}",
        f"- existing strategy solved counts: {json.dumps(solved_by_method, sort_keys=True)}",
        f"- greedy portfolio: {json.dumps(portfolio_data.get('greedy_portfolio', []), sort_keys=True)}",
        f"- extreme high-budget status: {json.dumps(extreme_status, sort_keys=True)}",
        f"- projected robust-hard rate: {projection.get('weighted_robust_rate')}",
        f"- projected robust-hard count: {projection.get('projected_edge64_robust_hard')}",
        f"- candidate-portfolio unresolved count: {projection.get('candidate_portfolio_unresolved_count', 'not computed')}",
        f"- projected candidate-portfolio unresolved: {projection.get('projected_candidate_portfolio_unresolved', 'not computed')}",
        f"- verification: {verification.get('status')}",
        "",
        "## Interpretation",
        "",
        "The trace is diagnostic only: it records branch width, depth, contradiction reasons, and rejection counters while leaving the existing solver semantics unchanged. A targeted heuristic is not promoted until the profile establishes a specific pathology and a bounded regression benchmark is available.",
        "",
        "Current status: `SOLVER_OPTIMIZATION`; full production remains intentionally deferred.",
    ]
    (OUT / "report_edge64_solver_optimization_v1.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    robust, extremes = freeze_manifests()
    residual, _residual_by_id, _robust_by_id, budgets = load_sources()
    controls = select_controls(robust, extremes, residual, budgets)
    profiles, _depth_rows, _strategy_rows = run_trace_corpus(robust, budget=1.0)
    benchmarks = run_control_tournament(robust, controls, budget=1.0)
    portfolio_data = portfolio(benchmarks)
    (OUT / "portfolio_optimized.json").write_text(json.dumps(portfolio_data, indent=2) + "\n", encoding="utf-8")
    high_rows = run_high_budget(extremes)
    robust_ids = {str(row["case_id"]) for row in robust}
    projection = weighted_projection(residual, robust_ids)
    (OUT / "weighted_projection_v2.json").write_text(json.dumps(projection, indent=2) + "\n", encoding="utf-8")
    cascade = {"recommended_status": "SOLVER_OPTIMIZATION", "current_existing_methods": METHODS, "profile_first": True, "full_production": False, "reason": "Extreme-tail tree profile and controlled candidate benchmarks are required before promoting a new cascade."}
    (OUT / "production_cascade_candidate.json").write_text(json.dumps(cascade, indent=2) + "\n", encoding="utf-8")
    verification = verify_outputs(robust, extremes, profiles, benchmarks, high_rows)
    (OUT / "verification_solver_optimization.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    write_report(robust, controls, profiles, benchmarks, high_rows, portfolio_data, projection, verification)
    close_pendant_extension_cache()
    print(json.dumps({"verification": verification, "robust": len(robust), "controls": len(controls), "profile_rows": len(profiles), "benchmark_rows": len(benchmarks), "high_budget_rows": len(high_rows)}, indent=2))


if __name__ == "__main__":
    main()
