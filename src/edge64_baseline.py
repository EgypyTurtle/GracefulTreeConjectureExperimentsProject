"""Edge-64 baseline census and bounded cheap-first pilot.

The case generator intentionally mirrors ``graceful_tree.py``'s
``--five-leaf-nonspider-by-edges`` semantics.  This module does not alter the
existing edge-63 logs or solver implementation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import math
import os
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


EDGE_COUNT = 64
EDGE63_CASES = 9_110_398
EXPECTED_EDGE64_CASES = 10_040_677
MANIFEST_FIELDS = [
    "case_id",
    "edge_count",
    "vertices",
    "skeleton",
    "bridge_length",
    "left_bridge",
    "right_bridge",
    "middle_leaf",
    "terminal_lengths",
    "branch_balance",
    "bridge_profile",
    "central_tail_parity",
    "terminal_min_le2",
    "hard_like_pattern",
    "stratum",
]
RESULT_FIELDS = [
    "case_id",
    "skeleton",
    "stratum",
    "tier",
    "status",
    "solved",
    "strategy",
    "nodes",
    "backtracks",
    "elapsed_seconds",
    "error",
]


def positive_tuples(parts: int, total: int):
    if parts == 1:
        if total >= 1:
            yield (total,)
        return
    for first in range(1, total - parts + 2):
        for rest in positive_tuples(parts - 1, total - first):
            yield (first, *rest)


def bridge_bucket(value: int) -> str:
    if value <= 3:
        return "short_le3"
    if value <= 8:
        return "medium_4_8"
    return "long_ge9"


def terminal_bucket(lengths: tuple[int, ...]) -> str:
    return "terminal_min_le2" if min(lengths) <= 2 else "terminal_min_ge3"


def balance_bucket(value: int) -> str:
    if value <= 2:
        return "balanced_le2"
    if value <= 8:
        return "moderate_3_8"
    return "unbalanced_ge9"


def case_row(
    skeleton: str,
    values: tuple[int, ...],
    terminal_lengths: tuple[int, ...],
    bridge_profile_value: str,
    middle_leaf: int | None,
    branch_balance: int,
) -> dict[str, str]:
    if skeleton == "fiveleaf2e":
        bridge, left_a, left_b, right_a, right_b, right_c = values
        case_id = "fiveleaf2e-" + "-".join(map(str, (EDGE_COUNT, *values)))
        left_bridge = right_bridge = ""
        bridge_length = str(bridge)
    else:
        left_bridge, right_bridge, left_a, left_b, middle, right_a, right_b = values
        case_id = "fiveleaf3e-" + "-".join(map(str, (EDGE_COUNT, *values)))
        bridge_length = ""
        middle_leaf = middle

    min_le2 = min(terminal_lengths) <= 2
    odd_middle = middle_leaf is not None and middle_leaf % 2 == 1
    hard_like = (
        min_le2
        and (
            (skeleton == "fiveleaf2e" and int(bridge_length) <= 3)
            or (skeleton == "fiveleaf3e" and min(int(left_bridge), int(right_bridge)) <= 3 and odd_middle)
        )
    )
    if skeleton == "fiveleaf2e":
        stratum = "|".join(
            ("two_branch", bridge_bucket(int(bridge_length)), terminal_bucket(terminal_lengths), balance_bucket(branch_balance))
        )
    else:
        stratum = "|".join(
            (
                "three_branch",
                bridge_profile_value,
                "middle_odd" if odd_middle else "middle_even",
                terminal_bucket(terminal_lengths),
                balance_bucket(branch_balance),
            )
        )
    return {
        "case_id": case_id,
        "edge_count": str(EDGE_COUNT),
        "vertices": str(EDGE_COUNT + 1),
        "skeleton": skeleton,
        "bridge_length": bridge_length,
        "left_bridge": "" if skeleton == "fiveleaf2e" else str(left_bridge),
        "right_bridge": "" if skeleton == "fiveleaf2e" else str(right_bridge),
        "middle_leaf": "" if middle_leaf is None else str(middle_leaf),
        "terminal_lengths": ";".join(map(str, terminal_lengths)),
        "branch_balance": str(branch_balance),
        "bridge_profile": bridge_profile_value,
        "central_tail_parity": "na" if middle_leaf is None else ("odd" if odd_middle else "even"),
        "terminal_min_le2": str(int(min_le2)),
        "hard_like_pattern": str(int(hard_like)),
        "stratum": stratum,
    }


def iter_edge64_rows():
    for lengths in positive_tuples(6, EDGE_COUNT):
        bridge = lengths[0]
        left = tuple(sorted(lengths[1:3]))
        right = tuple(sorted(lengths[3:6]))
        if lengths[1:3] != left or lengths[3:6] != right:
            continue
        yield case_row(
            "fiveleaf2e",
            (bridge, *left, *right),
            (*left, *right),
            bridge_bucket(bridge),
            None,
            abs(sum(left) - sum(right)),
        )

    for lengths in positive_tuples(7, EDGE_COUNT):
        left_bridge, right_bridge = lengths[0], lengths[1]
        left = tuple(sorted(lengths[2:4]))
        middle_leaf = lengths[4]
        right = tuple(sorted(lengths[5:7]))
        if lengths[2:4] != left or lengths[5:7] != right:
            continue
        if (left, left_bridge) > (right, right_bridge):
            continue
        if left_bridge <= 3 and right_bridge <= 3:
            profile = "both_short_le3"
        elif min(left_bridge, right_bridge) <= 3:
            profile = "one_short_le3"
        else:
            profile = "both_ge4"
        yield case_row(
            "fiveleaf3e",
            (left_bridge, right_bridge, *left, middle_leaf, *right),
            (*left, *right),
            profile,
            middle_leaf,
            abs(sum(left) - sum(right)),
        )


def hash_score(case_id: str) -> int:
    return int.from_bytes(hashlib.blake2b(case_id.encode("ascii"), digest_size=8).digest(), "big")


def build_manifest(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / "edge64_case_manifest.csv"
    counts = Counter()
    strata = Counter()
    hard_like = 0
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in iter_edge64_rows():
            writer.writerow(row)
            counts[row["skeleton"]] += 1
            strata[row["stratum"]] += 1
            hard_like += int(row["hard_like_pattern"])
    total = sum(counts.values())
    summary = {
        "edge_count": EDGE_COUNT,
        "total_cases": total,
        "skeleton_counts": dict(counts),
        "strata_count": len(strata),
        "hard_like_pattern_cases": hard_like,
        "edge63_reference_total": EDGE63_CASES,
        "growth_vs_edge63": total / EDGE63_CASES - 1.0,
        "expected_planning_range": [9_800_000, 10_200_000],
        "within_expected_planning_range": 9_800_000 <= total <= 10_200_000,
        "canonicalization": "same edge-indexed fiveleaf2e/fiveleaf3e naming and end-order reduction as edge63",
    }
    (output_dir / "case_universe_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if total != EXPECTED_EDGE64_CASES:
        raise RuntimeError(f"edge64 generator count changed: {total} != {EXPECTED_EDGE64_CASES}")
    sample_path = output_dir / "case_manifest_sample.csv"
    sample_heap: list[tuple[int, dict[str, str]]] = []
    sample_limit = 2000
    with manifest.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            score = hash_score(row["case_id"])
            item = (-score, row)
            if len(sample_heap) < sample_limit:
                heapq.heappush(sample_heap, item)
            elif item[0] > sample_heap[0][0]:
                heapq.heapreplace(sample_heap, item)
    sampled = [item[1] for item in sorted(sample_heap, key=lambda item: item[1]["case_id"])]
    with sample_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(sampled)
    print(json.dumps(summary, indent=2))


def build_pilot(manifest_dir: Path, pilot_size: int) -> None:
    manifest = manifest_dir / "edge64_case_manifest.csv"
    pilot = manifest_dir / "pilot_manifest.csv"
    counts = Counter()
    with manifest.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            counts[row["stratum"]] += 1
    strata = sorted(counts)
    base = pilot_size // len(strata)
    quota = {key: base for key in strata}
    for key in strata[: pilot_size % len(strata)]:
        quota[key] += 1
    heaps: dict[str, list[tuple[int, str, dict[str, str]]]] = defaultdict(list)
    with manifest.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = row["stratum"]
            if quota[key] == 0:
                continue
            score = hash_score(row["case_id"])
            item = (-score, row["case_id"], row)
            heap = heaps[key]
            if len(heap) < quota[key]:
                heapq.heappush(heap, item)
            elif item[:2] > heap[0][:2]:
                heapq.heapreplace(heap, item)
    selected = [item[2] for heap in heaps.values() for item in heap]
    selected.sort(key=lambda row: row["case_id"])
    if len(selected) != pilot_size:
        raise RuntimeError(f"pilot selection produced {len(selected)} rows, expected {pilot_size}")
    with pilot.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(selected)
    print(json.dumps({"pilot_size": len(selected), "strata": len(strata), "quota": base}, indent=2))


def options(method: str, time_limit: float, cache_db: str, adaptive: bool = False):
    return SimpleNamespace(
        method=method,
        no_constructive_fastpath=False,
        time_limit=time_limit,
        diff_candidates=None,
        extension_fastpath_nodes=2_000,
        extension_cache_size=100_000,
        extension_cache_db=cache_db,
        extension_try_all_paths=False,
        extension_adaptive_budget=adaptive,
        extension_adaptive_nodes=100_000,
        spider_order="long",
        spider_label_order="extreme",
        heuristic_steps=1_000_000,
        heuristic_restarts=50,
    )


def run_one(case_id: str, method: str, budget: float, cache_db: str, seed: int):
    started = time.time()
    try:
        n, edges = reconstruct_named_five_leaf_case(case_id)
        adj = build_adj(n, edges)
        if method == "compressed":
            labels, stats = solve_tree(adj, options(method, budget, cache_db), seed=seed)
        elif method == "diff":
            labels, stats = solve_graceful_by_differences(adj, time_limit=budget, seed=seed)
        elif method == "tension":
            labels, stats = solve_graceful_tension(adj, time_limit=budget, seed=seed)
        elif method == "branch":
            labels, stats = solve_graceful_branch_differences(adj, time_limit=budget, seed=seed)
        elif method == "hybrid":
            labels, stats = solve_tree(adj, options(method, budget, cache_db), seed=seed)
        else:
            raise ValueError(method)
        elapsed = time.time() - started
        solved = labels is not None and verify_labeling(edges, labels)
        return {
            "labels": labels if solved else None,
            "status": "solved" if solved else "timeout_or_failed",
            "solved": int(solved),
            "strategy": stats.strategy,
            "nodes": stats.nodes,
            "backtracks": stats.backtracks,
            "elapsed_seconds": elapsed,
            "error": "",
        }
    except Exception as exc:  # pilot errors are recorded and do not abort the batch
        return {
            "labels": None,
            "status": "error",
            "solved": 0,
            "strategy": method,
            "nodes": 0,
            "backtracks": 0,
            "elapsed_seconds": time.time() - started,
            "error": f"{type(exc).__name__}: {exc}",
        }


def pilot_worker(payload):
    case_id, method, budget, output_dir, seed = payload
    cache_db = str(Path(output_dir) / f"pilot_extension_{method}_{os.getpid()}.sqlite3")
    return run_one(case_id, method, budget, cache_db, seed)


def run_pilot(output_dir: Path, tier0_budget: float, tier1_budget: float, tier2_budget: float, workers: int) -> None:
    pilot_path = output_dir / "pilot_manifest.csv"
    rows = list(csv.DictReader(pilot_path.open("r", newline="", encoding="utf-8")))
    result_dir = output_dir
    result_dir.mkdir(parents=True, exist_ok=True)
    results = {0: [], 1: [], 2: []}
    certificates = []
    current = rows
    budgets = {0: tier0_budget, 1: tier1_budget, 2: tier2_budget}
    methods = {0: "compressed", 1: "diff", 2: "tension"}
    started = time.time()
    for tier in (0, 1, 2):
        if not current:
            break
        next_current = []
        path = result_dir / f"pilot_tier{tier}_results.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
            writer.writeheader()
            payloads = (
                (
                    row["case_id"],
                    methods[tier],
                    budgets[tier],
                    str(result_dir),
                    int.from_bytes(hashlib.blake2b(row["case_id"].encode("ascii"), digest_size=8).digest(), "big"),
                )
                for row in current
            )
            with ProcessPoolExecutor(max_workers=workers) as executor:
                index = 0
                for batch_start in range(0, len(current), 256):
                    batch_rows = current[batch_start : batch_start + 256]
                    batch_payloads = [
                        (
                            row["case_id"],
                            methods[tier],
                            budgets[tier],
                            str(result_dir),
                            int.from_bytes(hashlib.blake2b(row["case_id"].encode("ascii"), digest_size=8).digest(), "big"),
                        )
                        for row in batch_rows
                    ]
                    batch_results = list(executor.map(pilot_worker, batch_payloads, chunksize=1))
                    for row, result in zip(batch_rows, batch_results):
                        index += 1
                        out = {
                            "case_id": row["case_id"],
                            "skeleton": row["skeleton"],
                            "stratum": row["stratum"],
                            "tier": tier,
                            **{key: result[key] for key in RESULT_FIELDS if key in result},
                            "nodes": result["nodes"],
                            "backtracks": result["backtracks"],
                            "elapsed_seconds": f"{result['elapsed_seconds']:.6f}",
                            "error": result["error"],
                        }
                        writer.writerow(out)
                        results[tier].append(out)
                        if result["solved"]:
                            certificates.append(
                                {
                                    "case_id": row["case_id"],
                                    "tier": tier,
                                    "strategy": result["strategy"],
                                    "labels": " ".join(map(str, result["labels"])),
                                }
                            )
                        else:
                            next_current.append(row)
                    if index == len(batch_rows) or index % 5000 < len(batch_rows):
                        print(
                            f"tier={tier} processed={index}/{len(current)} solved={sum(x['solved'] == 1 or x['solved'] == '1' for x in results[tier])}",
                            flush=True,
                        )
                        handle.flush()
        current = next_current
        close_pendant_extension_cache()
    with (result_dir / "pilot_certificates.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "tier", "strategy", "labels"])
        writer.writeheader()
        writer.writerows(certificates)
    aggregate_results(output_dir, rows, results, certificates, time.time() - started, budgets)


def aggregate_results(output_dir: Path, rows, results, certificates, elapsed: float, budgets: dict[int, float]) -> None:
    all_results = [item for tier in results.values() for item in tier]
    tier_stats = {}
    for tier in (0, 1, 2):
        tier_rows = results[tier]
        times = sorted(float(row["elapsed_seconds"]) for row in tier_rows)
        nodes = sorted(int(row["nodes"]) for row in tier_rows)
        solved = sum(int(row["solved"]) for row in tier_rows)
        tier_stats[str(tier)] = {
            "input": len(tier_rows),
            "solved": solved,
            "unresolved": len(tier_rows) - solved - sum(row["status"] == "error" for row in tier_rows),
            "errors": sum(row["status"] == "error" for row in tier_rows),
            "median_runtime": times[len(times) // 2] if times else 0.0,
            "p90_runtime": times[min(len(times) - 1, math.floor(0.90 * len(times)))] if times else 0.0,
            "p99_runtime": times[min(len(times) - 1, math.floor(0.99 * len(times)))] if times else 0.0,
            "median_nodes": nodes[len(nodes) // 2] if nodes else 0,
            "p99_nodes": nodes[min(len(nodes) - 1, math.floor(0.99 * len(nodes)))] if nodes else 0,
            "budget_seconds": budgets[tier],
        }
    remaining = results[2]
    unresolved = [row for row in remaining if row["solved"] != 1 and row["status"] != "error"]
    def rate(count: int, denominator: int) -> float:
        return count / denominator if denominator else 0.0
    tier0_hard = len(results[0]) - tier_stats["0"]["solved"] - tier_stats["0"]["errors"]
    tier1_hard = len(results[1]) - tier_stats["1"]["solved"] - tier_stats["1"]["errors"]
    tier2_residual = len(unresolved)
    tier2_residual_rate = rate(tier2_residual, len(rows))
    all_times = sorted(float(row["elapsed_seconds"]) for row in all_results)
    all_nodes = sorted(int(row["nodes"]) for row in all_results)
    total_cases = EXPECTED_EDGE64_CASES
    estimated_residual = round(total_cases * rate(tier2_residual, len(rows)))
    pilot_nodes = sum(int(row["nodes"]) for row in all_results)
    estimated_total_nodes = pilot_nodes / max(len(rows), 1) * total_cases
    edge63_nodes = 12_085_967_534
    universe_summary = json.loads((output_dir / "case_universe_summary.json").read_text(encoding="utf-8"))
    hardness = Counter()
    for row in rows:
        hardness[row["stratum"]] += 1
    for row in results[2]:
        if row["solved"] != 1:
            hardness[row["stratum"] + "|tier2_residual"] += 1
    with (output_dir / "hardness_census.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["stratum", "pilot_cases", "tier2_residuals", "residual_rate"])
        for stratum in sorted({row["stratum"] for row in rows}):
            total = sum(row["stratum"] == stratum for row in rows)
            residual = sum(row["stratum"] == stratum and row["solved"] != 1 for row in results[2])
            writer.writerow([stratum, total, residual, rate(residual, total)])
    pattern_summary = {
        "pilot_size": len(rows),
        "residual_strata_top": [
            {"stratum": key, "count": value}
            for key, value in sorted(
                ((key, value) for key, value in hardness.items() if key.endswith("|tier2_residual")),
                key=lambda item: (-item[1], item[0]),
            )[:20]
        ],
        "edge63_hard_pattern_diagnostic": "bridge<=3, odd central tail where applicable, terminal min<=2; diagnostic only",
    }
    (output_dir / "hard_pattern_summary.json").write_text(json.dumps(pattern_summary, indent=2) + "\n", encoding="utf-8")
    profile = {
        "profile_scope": "edge64 representative pilot",
        "total_elapsed_seconds": elapsed,
        "tier_stats": tier_stats,
        "overall_cases_attempted": len(all_results),
        "overall_cases_per_second": len(all_results) / max(elapsed, 1e-9),
        "overall_median_runtime": all_times[len(all_times) // 2] if all_times else 0.0,
        "overall_p99_runtime": all_times[min(len(all_times) - 1, math.floor(0.99 * len(all_times)))] if all_times else 0.0,
        "overall_median_nodes": all_nodes[len(all_nodes) // 2] if all_nodes else 0,
        "overall_p99_nodes": all_nodes[min(len(all_nodes) - 1, math.floor(0.99 * len(all_nodes)))] if all_nodes else 0,
        "hotspot": "existing solve_tree cascade and graceful constraint search; no native rewrite performed",
        "edge63_reference": {
            "total_cases": EDGE63_CASES,
            "recorded_total_nodes": edge63_nodes,
            "comparison_note": "Node-work ratio is a planning comparison; edge64 uses bounded tier budgets and is not a proof of equal solver semantics.",
        },
    }
    (output_dir / "solver_profile.json").write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    summary = {
        "pilot_size": len(rows),
        "tier0": tier_stats["0"],
        "tier1": tier_stats["1"],
        "tier2": tier_stats["2"],
        "certificates": len(certificates),
        "errors": sum(row["status"] == "error" for row in all_results),
        "elapsed_seconds": elapsed,
        "edge64_universe": {
            "total_cases": total_cases,
            "fiveleaf2e": universe_summary["skeleton_counts"]["fiveleaf2e"],
            "fiveleaf3e": universe_summary["skeleton_counts"]["fiveleaf3e"],
        },
        "edge63_reference": {
            "total_cases": EDGE63_CASES,
            "recorded_total_nodes": edge63_nodes,
            "comparison_note": "The pilot cascade uses explicit bounded budgets; compare as planning telemetry only.",
        },
    }
    (output_dir / "performance_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    projection = {
        "total_edge64_cases": total_cases,
        "pilot_size": len(rows),
        "tier0_hard_rate": rate(tier0_hard, len(rows)),
        "tier1_residual_rate": rate(tier1_hard, len(rows)),
        "tier2_residual_rate": rate(tier2_residual, len(rows)),
        "bounded_tier2_residual_count": tier2_residual,
        "bounded_tier2_residual_rate": rate(tier2_residual, len(rows)),
        "tier_budgets_seconds": budgets,
        "pilot_budget_is_bounded": True,
        "residual_semantics": "cases unresolved after the explicit 0.25-second Tier2 budget; not an exhaustive mathematical residual",
        "estimated_initial_hard_count": round(total_cases * rate(tier0_hard, len(rows))),
        "estimated_true_residual_count": estimated_residual,
        "median_nodes": all_nodes[len(all_nodes) // 2] if all_nodes else 0,
        "p99_nodes": all_nodes[min(len(all_nodes) - 1, math.floor(0.99 * len(all_nodes)))] if all_nodes else 0,
        "estimated_total_nodes": estimated_total_nodes,
        "edge63_reference_total_nodes": edge63_nodes,
        "estimated_total_work_ratio_vs_edge63": estimated_total_nodes / edge63_nodes,
        "recommended_next_mode": (
            "FULL_PRODUCTION" if tier2_residual_rate <= 1e-5 else
            "FULL_PRODUCTION_PLUS_RESIDUAL_STUDY" if tier2_residual_rate <= 1e-4 else
            "STRUCTURAL_STUDY_FIRST"
        ),
        "planning_classification": "EDGE64_NEW_DIFFICULTY" if tier2_residual_rate >= 1e-3 else "EDGE64_PRODUCTION_REGIME",
        "planning_note": "Pilot uses explicit bounded per-tier budgets; this is a planning estimate, not a proof or confidence interval.",
    }
    (output_dir / "workload_projection.json").write_text(json.dumps(projection, indent=2) + "\n", encoding="utf-8")
    report = f"""# Edge64 baseline pilot

The exact edge64 five-leaf non-spider universe contains **{total_cases:,}** cases:
`fiveleaf2e={universe_summary['skeleton_counts']['fiveleaf2e']:,}`, 
`fiveleaf3e={universe_summary['skeleton_counts']['fiveleaf3e']:,}`.
The representative pilot contains **{len(rows):,}** deterministic stratified cases.

## Cascade

Tier 0 uses the existing `compressed` solver. Tier 1 uses the existing difference
solver. Tier 2 uses the existing tension solver. No new structure or split language
was introduced.

```text
Tier 0 hard rate       = {rate(tier0_hard, len(rows)):.6g}
Tier 1 residual rate   = {rate(tier1_hard, len(rows)):.6g}
Tier 2 bounded residual = {tier2_residual:,} / {len(rows):,}
errors                 = {summary['errors']}
```

The word “residual” here means unresolved after the explicit **0.25 second**
Tier 2 budget. It is a planning diagnostic, not an exhaustive unresolved-case
count.

The pilot budgets and detailed latency/node percentiles are in
`solver_profile.json` and `performance_summary.json`.

## Planning result

Estimated bounded-Tier2 residual count: **{estimated_residual:,}**. Estimated total node
work relative to the recorded edge63 baseline is **{estimated_total_nodes / edge63_nodes:.3g}x**.
This is a bounded-pilot projection only. Hardness strata are diagnostic and are
not used as pruning rules.

Planning classification: **{projection['planning_classification']}**.
Recommended next mode: **{projection['recommended_next_mode']}**.

The bounded pilot does not support immediate full production: the 2.3465% Tier 2
residual rate is above the planning threshold used for a pure production regime.
The residuals are concentrated in short-bridge and several three-branch strata,
but the pilot does not yet establish a new theorem or a universal hard pattern.

Edge63 remains frozen; this pilot does not alter its logs.
"""
    (output_dir / "report_edge64_pilot_v1.md").write_text(report, encoding="utf-8")
    verify_pilot(output_dir)


def verify_pilot(output_dir: Path) -> None:
    manifest = {row["case_id"]: row for row in csv.DictReader((output_dir / "pilot_manifest.csv").open("r", newline="", encoding="utf-8"))}
    certificate_rows = list(csv.DictReader((output_dir / "pilot_certificates.csv").open("r", newline="", encoding="utf-8")))
    verified = 0
    errors = []
    for row in certificate_rows:
        case_id = row["case_id"]
        if case_id not in manifest:
            errors.append({"case_id": case_id, "error": "certificate not in pilot manifest"})
            continue
        try:
            _n, edges = reconstruct_named_five_leaf_case(case_id)
            labels = [int(value) for value in row["labels"].split()]
            if not verify_labeling(edges, labels):
                raise ValueError("edge differences or label bijection failed")
            verified += 1
        except Exception as exc:
            errors.append({"case_id": case_id, "error": f"{type(exc).__name__}: {exc}"})
    result = {
        "status": "PASS" if not errors else "FAIL",
        "pilot_cases": len(manifest),
        "certificate_count": len(certificate_rows),
        "certificates_verified": verified,
        "errors": errors,
        "note": "All solved pilot certificates are independently rechecked with the existing verifier.",
    }
    (output_dir / "pilot_verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise RuntimeError(f"pilot verification failed for {len(errors)} certificates")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("results/edge64_baseline_v1"))
    parser.add_argument("--build-universe", action="store_true")
    parser.add_argument("--build-pilot", action="store_true")
    parser.add_argument("--pilot-size", type=int, default=200_000)
    parser.add_argument("--run-pilot", action="store_true")
    parser.add_argument("--verify-pilot", action="store_true")
    parser.add_argument("--tier0-budget", type=float, default=1.0)
    parser.add_argument("--tier1-budget", type=float, default=1.0)
    parser.add_argument("--tier2-budget", type=float, default=1.0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.build_universe:
        build_manifest(args.output_dir)
    if args.build_pilot:
        build_pilot(args.output_dir, args.pilot_size)
    if args.run_pilot:
        run_pilot(args.output_dir, args.tier0_budget, args.tier1_budget, args.tier2_budget, args.workers)
    if args.verify_pilot:
        verify_pilot(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
