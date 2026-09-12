"""Edge64 residual isolation: budget ladder, strategy tournament, and census.

This module deliberately reuses the existing edge64 case reconstruction and
solver entry points.  It does not change the canonical universe or introduce a
new mathematical search language.
"""

from __future__ import annotations

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

from edge64_baseline import MANIFEST_FIELDS, pilot_worker
from edge64_baseline import bridge_bucket, balance_bucket, terminal_bucket, positive_tuples
from graceful_tree import five_leaf_nonspider_three_branch, five_leaf_nonspider_two_branch
from graceful_tree import build_adj, reconstruct_named_five_leaf_case, verify_labeling


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "results" / "edge64_baseline_v1"
OUT = ROOT / "results" / "edge64_hardtail_v1"
WORKERS = 8
LADDER = (0.5, 1.0, 2.0, 5.0)
TOURNAMENT_METHODS = ("compressed", "hybrid", "branch", "diff", "tension")


def stable_seed(case_id: str, salt: str = "edge64-hardtail") -> int:
    return int.from_bytes(hashlib.blake2b(f"{salt}:{case_id}".encode("ascii"), digest_size=8).digest(), "big")


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


def freeze_residual_manifest() -> list[dict[str, str]]:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "residual4693_manifest.csv"
    pilot = {row["case_id"]: row for row in read_csv(BASE / "pilot_manifest.csv")}
    tier0 = {row["case_id"]: row for row in read_csv(BASE / "pilot_tier0_results.csv")}
    tier1 = {row["case_id"]: row for row in read_csv(BASE / "pilot_tier1_results.csv")}
    tier2 = {row["case_id"]: row for row in read_csv(BASE / "pilot_tier2_results.csv")}
    residual_ids = sorted(case_id for case_id, row in tier2.items() if row["solved"] != "1")
    fields = list(MANIFEST_FIELDS)
    for tier in (0, 1, 2):
        fields.extend([f"tier{tier}_{name}" for name in ("status", "solved", "strategy", "nodes", "backtracks", "elapsed_seconds", "error")])
    rows: list[dict[str, str]] = []
    for case_id in residual_ids:
        row = dict(pilot[case_id])
        for tier, source in ((0, tier0), (1, tier1), (2, tier2)):
            item = source.get(case_id, {})
            for name in ("status", "solved", "strategy", "nodes", "backtracks", "elapsed_seconds", "error"):
                row[f"tier{tier}_{name}"] = item.get(name, "")
        rows.append(row)
    write_csv(target, rows, fields)
    return rows


def run_batch(case_ids: list[str], method: str, budget: float, workers: int = WORKERS) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    output_dir = str(OUT)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for start in range(0, len(case_ids), 256):
            batch = case_ids[start : start + 256]
            payloads = [(case_id, method, budget, output_dir, stable_seed(case_id, method)) for case_id in batch]
            batch_results = list(executor.map(pilot_worker, payloads, chunksize=1))
            results.update(dict(zip(batch, batch_results)))
            print(f"method={method} budget={budget:g} processed={min(start + len(batch), len(case_ids))}/{len(case_ids)} solved={sum(int(result['solved']) for result in batch_results)}", flush=True)
    return results


def result_row(case_id: str, result: dict[str, object], budget: float, method: str) -> dict[str, object]:
    return {
        "case_id": case_id,
        "method": method,
        "budget_seconds": budget,
        "status": result.get("status", "error"),
        "solved": result.get("solved", 0),
        "strategy": result.get("strategy", method),
        "nodes": result.get("nodes", 0),
        "backtracks": result.get("backtracks", 0),
        "elapsed_seconds": result.get("elapsed_seconds", 0.0),
        "error": result.get("error", ""),
        "labels": " ".join(map(str, result.get("labels") or [])),
    }


def run_budget_ladder(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, list[str]]]:
    active = [row["case_id"] for row in rows]
    survivor_sets: dict[str, list[str]] = {}
    all_result_rows: list[dict[str, object]] = []
    for budget in LADDER:
        path = OUT / f"budget_{budget:g}.csv"
        if path.exists():
            prior = read_csv(path)
            survivor_sets[str(budget)] = [row["case_id"] for row in prior if row["solved"] != "1"]
            all_result_rows.extend(prior)
            active = survivor_sets[str(budget)]
            continue
        results = run_batch(active, "compressed", budget)
        out = [result_row(case_id, results[case_id], budget, "compressed") for case_id in active]
        write_csv(path, out, list(out[0].keys()) if out else ["case_id"])
        all_result_rows.extend(out)
        active = [row["case_id"] for row in out if str(row["solved"]) != "1"]
        survivor_sets[str(budget)] = active[:]
        solved = len(out) - len(active)
        print(f"budget={budget:g} solved={solved} survivors={len(active)}", flush=True)
    survival_rows = []
    total = len(rows)
    for budget in LADDER:
        survivors = len(survivor_sets[str(budget)])
        survival_rows.append({
            "budget_seconds": budget,
            "survivors": survivors,
            "fraction_of_4693": survivors / total if total else 0.0,
            "solved_at_budget": total - survivors,
        })
    write_csv(OUT / "budget_survival.csv", survival_rows, list(survival_rows[0].keys()))
    by_stratum: dict[str, dict[str, object]] = {}
    for row in rows:
        by_stratum.setdefault(row["stratum"], {"stratum": row["stratum"], "pilot_cases": 0})["pilot_cases"] += 1
    for budget in LADDER:
        survivors = Counter(rows_by_id[case_id]["stratum"] for case_id in survivor_sets[str(budget)])
        for stratum, data in by_stratum.items():
            data[f"survivors_{budget:g}"] = survivors.get(stratum, 0)
            data[f"fraction_{budget:g}"] = survivors.get(stratum, 0) / data["pilot_cases"] if data["pilot_cases"] else 0.0
    by_rows = list(by_stratum.values())
    write_csv(OUT / "budget_survival_by_stratum.csv", by_rows, list(by_rows[0].keys()))
    write_csv(OUT / "budget_ladder_results.csv", all_result_rows, list(all_result_rows[0].keys()))
    return rows, survivor_sets


def stratified_sample(rows: list[dict[str, str]], target: int) -> list[str]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["stratum"]].append(row)
    ordered = []
    for stratum, members in sorted(groups.items()):
        ordered.extend(sorted(members, key=lambda row: hashlib.blake2b(row["case_id"].encode("ascii"), digest_size=16).digest()))
    if len(ordered) <= target:
        return [row["case_id"] for row in ordered]
    selected: list[dict[str, str]] = []
    for members in groups.values():
        selected.append(min(members, key=lambda row: hashlib.blake2b(row["case_id"].encode("ascii"), digest_size=16).digest()))
    selected_ids = {row["case_id"] for row in selected}
    for row in ordered:
        if len(selected) >= target:
            break
        if row["case_id"] not in selected_ids:
            selected.append(row)
            selected_ids.add(row["case_id"])
    return sorted(selected_ids)


def strategy_tournament(rows: list[dict[str, str]], robust_ids: list[str]) -> tuple[list[dict[str, str]], dict[str, object]]:
    robust_rows = [rows_by_id[case_id] for case_id in robust_ids]
    corpus_ids = stratified_sample(robust_rows, min(512, len(robust_rows)))
    write_csv(OUT / "strategy_tournament_manifest.csv", [rows_by_id[case_id] for case_id in corpus_ids], MANIFEST_FIELDS)
    all_rows: list[dict[str, object]] = []
    solved_by_method: dict[str, set[str]] = {}
    for method in TOURNAMENT_METHODS:
        results = run_batch(corpus_ids, method, 1.0)
        current = [result_row(case_id, results[case_id], 1.0, method) for case_id in corpus_ids]
        all_rows.extend(current)
        solved_by_method[method] = {row["case_id"] for row in current if str(row["solved"]) == "1"}
    write_csv(OUT / "strategy_tournament.csv", all_rows, list(all_rows[0].keys()))
    universe = set(corpus_ids)
    greedy: list[dict[str, object]] = []
    uncovered = set(universe)
    remaining = set(TOURNAMENT_METHODS)
    while remaining and uncovered:
        method = max(remaining, key=lambda name: len(solved_by_method[name] & uncovered))
        gain = len(solved_by_method[method] & uncovered)
        if gain == 0:
            break
        greedy.append({"method": method, "newly_solved": gain, "cumulative_solved": len(universe - (uncovered - solved_by_method[method]))})
        uncovered -= solved_by_method[method]
        remaining.remove(method)
    portfolio_coverage = [
        {"portfolio_size": index, "methods": [item["method"] for item in greedy[:index]], "solved": greedy[index - 1]["cumulative_solved"], "coverage": greedy[index - 1]["cumulative_solved"] / len(universe) if universe else 0.0}
        for index in range(1, len(greedy) + 1)
    ]
    summary = {
        "corpus_size": len(corpus_ids),
        "methods": [
            {"method": method, "solved": len(solved_by_method[method]), "rate": len(solved_by_method[method]) / len(universe) if universe else 0.0}
            for method in TOURNAMENT_METHODS
        ],
        "greedy_portfolio": greedy,
        "portfolio_coverage": portfolio_coverage,
        "all_strategy_coverage": 1.0 - len(uncovered) / len(universe) if universe else 0.0,
        "uncovered_after_all": len(uncovered),
    }
    complementarity = []
    for i, left in enumerate(TOURNAMENT_METHODS):
        for right in TOURNAMENT_METHODS[i + 1 :]:
            complementarity.append({
                "left": left,
                "right": right,
                "left_only": len(solved_by_method[left] - solved_by_method[right]),
                "right_only": len(solved_by_method[right] - solved_by_method[left]),
                "both": len(solved_by_method[left] & solved_by_method[right]),
                "neither": len(universe - solved_by_method[left] - solved_by_method[right]),
            })
    write_csv(OUT / "strategy_complementarity.csv", complementarity, list(complementarity[0].keys()))
    (OUT / "strategy_portfolio.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return all_rows, summary


def deploy_portfolio(rows: list[dict[str, str]], robust_ids: list[str], portfolio: dict[str, object]) -> tuple[list[str], list[dict[str, object]]]:
    methods = [item["method"] for item in portfolio.get("greedy_portfolio", [])]
    remaining = set(robust_ids)
    output: list[dict[str, object]] = []
    for method in methods:
        if not remaining:
            break
        ids = sorted(remaining)
        results = run_batch(ids, method, 1.0)
        for case_id in ids:
            row = result_row(case_id, results[case_id], 1.0, method)
            output.append(row)
            if str(row["solved"]) == "1":
                remaining.discard(case_id)
    write_csv(OUT / "post_portfolio_results.csv", output, list(output[0].keys()) if output else ["case_id"])
    write_csv(OUT / "robust_hard_manifest.csv", [rows_by_id[case_id] for case_id in sorted(remaining)], MANIFEST_FIELDS)
    return sorted(remaining), output


def feature_map(row: dict[str, str]) -> dict[str, bool]:
    terminal = [int(value) for value in row.get("terminal_lengths", "").split(";") if value]
    profile = row.get("bridge_profile", "")
    skeleton = row.get("skeleton", "")
    return {
        "fiveleaf2e": skeleton == "fiveleaf2e",
        "fiveleaf3e": skeleton == "fiveleaf3e",
        "bridge_le3": profile == "short_le3" or profile in {"both_short_le3", "one_short_le3"},
        "bridge_eq3": row.get("bridge_length") == "3",
        "both_short_le3": profile == "both_short_le3",
        "central_odd": row.get("central_tail_parity") == "odd",
        "central_even": row.get("central_tail_parity") == "even",
        "terminal_min_le2": row.get("terminal_min_le2") == "1",
        "balanced": row.get("branch_balance", "") == "2",
        "unbalanced_ge9": row.get("stratum", "").endswith("unbalanced_ge9"),
        "middle_leaf_short": row.get("middle_leaf", "") in {"1", "2", "3"},
        "terminal_min_ge3": bool(terminal) and min(terminal) >= 3,
    }


def enrichment(rows: list[dict[str, str]], robust_ids: set[str]) -> list[dict[str, object]]:
    totals = Counter()
    robust = Counter()
    feature_names = list(feature_map(rows[0]).keys()) if rows else []
    for row in rows:
        flags = feature_map(row)
        for name, enabled in flags.items():
            if enabled:
                totals[name] += 1
                robust[name] += row["case_id"] in robust_ids
    out = []
    base_rate = len(robust_ids) / len(rows) if rows else 0.0
    for name in feature_names:
        total = totals[name]
        hard = robust[name]
        rate = hard / total if total else 0.0
        out.append({"feature": name, "total": total, "robust_hard": hard, "conditional_rate": rate, "baseline_rate": base_rate, "enrichment": rate / base_rate if base_rate else 0.0})
    return out


def interaction_enrichment(rows: list[dict[str, str]], robust_ids: set[str]) -> list[dict[str, object]]:
    names = list(feature_map(rows[0]).keys()) if rows else []
    records = []
    for size in (1, 2, 3):
        import itertools
        for combo in itertools.combinations(names, size):
            total = 0
            hard = 0
            for row in rows:
                flags = feature_map(row)
                if all(flags[name] for name in combo):
                    total += 1
                    hard += row["case_id"] in robust_ids
            if total:
                rate = hard / total
                base_rate = len(robust_ids) / len(rows) if rows else 0.0
                records.append({"interaction": " AND ".join(combo), "order": size, "total": total, "robust_hard": hard, "conditional_rate": rate, "baseline_rate": base_rate, "enrichment": rate / base_rate if base_rate else 0.0})
    return sorted(records, key=lambda row: (-row["enrichment"], -row["robust_hard"], row["interaction"]))


def weighted_projection(rows: list[dict[str, str]], robust_ids: set[str]) -> dict[str, object]:
    full_counts: Counter[str] = Counter()
    with (BASE / "edge64_case_manifest.csv").open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            full_counts[row["stratum"]] += 1
    pilot_by_stratum = Counter(row["stratum"] for row in rows)
    robust_by_stratum = Counter(row["stratum"] for row in rows if row["case_id"] in robust_ids)
    details = []
    weighted_robust_rate = 0.0
    for stratum, count in sorted(full_counts.items()):
        sample = pilot_by_stratum[stratum]
        robust = robust_by_stratum[stratum]
        rate = robust / sample if sample else 0.0
        weight = count / sum(full_counts.values())
        weighted_robust_rate += weight * rate
        details.append({"stratum": stratum, "universe_cases": count, "pilot_cases": sample, "robust_hard_cases": robust, "estimated_rate": rate, "universe_weight": weight, "projected_robust_cases": round(count * rate)})
    result = {
        "universe_cases": sum(full_counts.values()),
        "weighted_robust_hard_rate": weighted_robust_rate,
        "weighted_projected_robust_hard_cases": round(weighted_robust_rate * sum(full_counts.values())),
        "stratum_details": details,
        "note": "Post-portfolio projection uses pilot stratum conditional rates; it is planning telemetry, not a confidence interval.",
    }
    write_csv(OUT / "weighted_projection_by_stratum.csv", details, list(details[0].keys()))
    return result


def build_exploratory_tree(rows: list[dict[str, str]], robust_ids: set[str], max_depth: int = 4) -> dict[str, object]:
    feature_names = list(feature_map(rows[0]).keys()) if rows else []
    records = [(row, feature_map(row), row["case_id"] in robust_ids) for row in rows]

    def gini(items):
        if not items:
            return 0.0
        p = sum(item[2] for item in items) / len(items)
        return 2.0 * p * (1.0 - p)

    def grow(items, depth, used):
        count = len(items)
        hard = sum(item[2] for item in items)
        leaf = {"count": count, "robust_hard": hard, "hard_rate": hard / count if count else 0.0, "depth": depth}
        if depth >= max_depth or count < 20 or hard == 0 or hard == count:
            leaf["type"] = "leaf"
            return leaf
        parent = gini(items)
        candidates = []
        for name in feature_names:
            if name in used:
                continue
            left = [item for item in items if not item[1][name]]
            right = [item for item in items if item[1][name]]
            if not left or not right:
                continue
            gain = parent - (len(left) * gini(left) + len(right) * gini(right)) / count
            candidates.append((gain, name, left, right))
        if not candidates:
            leaf["type"] = "leaf"
            return leaf
        gain, name, left, right = max(candidates, key=lambda item: (item[0], item[1]))
        if gain <= 0:
            leaf["type"] = "leaf"
            return leaf
        return {
            "type": "split",
            "feature": name,
            "gini_gain": gain,
            "count": count,
            "robust_hard": hard,
            "false": grow(left, depth + 1, used | {name}),
            "true": grow(right, depth + 1, used | {name}),
        }

    return {"type": "exploratory_decision_tree", "max_depth": max_depth, "target": "ROBUST_HARD after 1s portfolio", "tree": grow(records, 0, set()), "note": "Exploratory partition only; no theorem or pruning rule is inferred."}


def verify_result_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    errors = []
    verified = 0
    for row in rows:
        if str(row.get("solved")) != "1":
            continue
        labels_text = row.get("labels", "")
        labels = [int(value) for value in labels_text.split() if value]
        try:
            _n, edges = reconstruct_named_five_leaf_case(str(row["case_id"]))
            if not verify_labeling(edges, labels):
                errors.append({"case_id": row["case_id"], "reason": "verify_labeling=false"})
            else:
                verified += 1
        except Exception as exc:
            errors.append({"case_id": row["case_id"], "reason": f"{type(exc).__name__}: {exc}"})
    return {"status": "PASS" if not errors else "FAIL", "verified": verified, "errors": errors}


def control_case_row(edge_count: int, skeleton: str, values: tuple[int, ...], terminal_lengths: tuple[int, ...], bridge_profile: str, middle_leaf: int | None, branch_balance: int) -> dict[str, str]:
    if skeleton == "fiveleaf2e":
        bridge, left_a, left_b, right_a, right_b, right_c = values
        case_id = "fiveleaf2e-" + "-".join(map(str, (edge_count, *values)))
        left_bridge = right_bridge = ""
        bridge_length = str(bridge)
    else:
        left_bridge, right_bridge, left_a, left_b, middle, right_a, right_b = values
        case_id = "fiveleaf3e-" + "-".join(map(str, (edge_count, *values)))
        bridge_length = ""
        middle_leaf = middle
    min_le2 = min(terminal_lengths) <= 2
    odd_middle = middle_leaf is not None and middle_leaf % 2 == 1
    if skeleton == "fiveleaf2e":
        stratum = "|".join(("two_branch", bridge_bucket(int(bridge_length)), terminal_bucket(terminal_lengths), balance_bucket(branch_balance)))
    else:
        stratum = "|".join(("three_branch", bridge_profile, "middle_odd" if odd_middle else "middle_even", terminal_bucket(terminal_lengths), balance_bucket(branch_balance)))
    return {
        "case_id": case_id,
        "edge_count": str(edge_count),
        "vertices": str(edge_count + 1),
        "skeleton": skeleton,
        "bridge_length": bridge_length,
        "left_bridge": "" if skeleton == "fiveleaf2e" else str(left_bridge),
        "right_bridge": "" if skeleton == "fiveleaf2e" else str(right_bridge),
        "middle_leaf": "" if middle_leaf is None else str(middle_leaf),
        "terminal_lengths": ";".join(map(str, terminal_lengths)),
        "branch_balance": str(branch_balance),
        "bridge_profile": bridge_profile,
        "central_tail_parity": "na" if middle_leaf is None else ("odd" if odd_middle else "even"),
        "terminal_min_le2": str(int(min_le2)),
        "hard_like_pattern": "0",
        "stratum": stratum,
    }


def iter_control_rows(edge_count: int):
    for lengths in positive_tuples(6, edge_count):
        bridge = lengths[0]
        left = tuple(sorted(lengths[1:3]))
        right = tuple(sorted(lengths[3:6]))
        if lengths[1:3] != left or lengths[3:6] != right:
            continue
        yield control_case_row(edge_count, "fiveleaf2e", (bridge, *left, *right), (*left, *right), bridge_bucket(bridge), None, abs(sum(left) - sum(right)))
    for lengths in positive_tuples(7, edge_count):
        left_bridge, right_bridge = lengths[0], lengths[1]
        left = tuple(sorted(lengths[2:4]))
        middle_leaf = lengths[4]
        right = tuple(sorted(lengths[5:7]))
        if lengths[2:4] != left or lengths[5:7] != right:
            continue
        if (left, left_bridge) > (right, right_bridge):
            continue
        profile = "both_short_le3" if left_bridge <= 3 and right_bridge <= 3 else ("one_short_le3" if min(left_bridge, right_bridge) <= 3 else "both_ge4")
        yield control_case_row(edge_count, "fiveleaf3e", (left_bridge, right_bridge, *left, middle_leaf, *right), (*left, *right), profile, middle_leaf, abs(sum(left) - sum(right)))


def run_matched_edge63_control(target: int = 50_000) -> None:
    heap: list[tuple[int, str, dict[str, str]]] = []
    for row in iter_control_rows(63):
        score = int.from_bytes(hashlib.blake2b(row["case_id"].encode("ascii"), digest_size=8).digest(), "big")
        item = (score, row["case_id"], row)
        if len(heap) < target:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    rows = [item[2] for item in sorted(heap, key=lambda item: item[1])]
    write_csv(OUT / "edge63_matched_control_manifest.csv", rows, MANIFEST_FIELDS)
    active = [row["case_id"] for row in rows]
    tier_summaries = []
    all_results: list[dict[str, object]] = []
    for tier, method in enumerate(("compressed", "diff", "tension")):
        if not active:
            break
        results = run_batch(active, method, 0.25)
        current = [result_row(case_id, results[case_id], 0.25, method) for case_id in active]
        write_csv(OUT / f"edge63_matched_tier{tier}.csv", current, list(current[0].keys()))
        all_results.extend(current)
        solved = sum(str(row["solved"]) == "1" for row in current)
        tier_summaries.append({"tier": tier, "method": method, "input": len(current), "solved": solved, "survivors": len(current) - solved})
        active = [row["case_id"] for row in current if str(row["solved"]) != "1"]
    summary = {"control_cases": len(rows), "tiers": tier_summaries, "final_survivors": len(active), "same_configuration": "0.25 seconds per tier; compressed -> diff -> tension"}
    (OUT / "matched_edge63_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    verification = verify_result_rows(all_results)
    (OUT / "matched_edge63_verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    (OUT / "matched_edge63_survival.csv").write_text("stage,survivors,fraction_of_control\n" + "\n".join(f"tier{item['tier']},{item['survivors']},{item['survivors'] / len(rows):.9f}" for item in tier_summaries) + "\n", encoding="utf-8")


def write_report(rows: list[dict[str, str]], survivor_sets: dict[str, list[str]], tournament: dict[str, object], robust_ids: list[str], weighted: dict[str, object], high_budget: list[dict[str, object]] | None = None) -> None:
    high_budget = high_budget or []
    report = {
        "residual_cases": len(rows),
        "budget_survival": [{"budget": budget, "survivors": len(survivor_sets[str(budget)])} for budget in LADDER],
        "tournament": tournament,
        "post_portfolio_robust_hard": len(robust_ids),
        "weighted_projection": weighted,
        "high_budget_probe": {"input": len(high_budget), "solved": sum(str(row.get("solved")) == "1" for row in high_budget), "unresolved": sum(str(row.get("solved")) != "1" for row in high_budget)},
        "classification": "ROBUST_HARD_TAIL" if robust_ids else "STRATEGY_ARTIFACT_OR_BUDGET_ARTIFACT",
    }
    (OUT / "report_edge64_hardtail_v1.md").write_text(
        "# Edge64 hard-tail isolation\n\n" + json.dumps(report, indent=2) + "\n\n"
        "All strategy experiments reuse the frozen 4,693-case residual manifest. "
        "No canonical case-generation rule or edge63 log was modified.\n",
        encoding="utf-8",
    )


def main() -> None:
    global rows_by_id
    OUT.mkdir(parents=True, exist_ok=True)
    rows = freeze_residual_manifest()
    rows_by_id = {row["case_id"]: row for row in rows}
    print(json.dumps({"residual_manifest": len(rows), "output": str(OUT)}, indent=2))
    if "--verify-only" in sys.argv:
        sources = []
        for path in sorted(OUT.glob("budget_*.csv")):
            if path.name in {"budget_survival.csv", "budget_survival_by_stratum.csv"}:
                continue
            sources.extend(read_csv(path))
        for path in (OUT / "strategy_tournament.csv", OUT / "post_portfolio_results.csv", OUT / "high_budget_256_results.csv"):
            if path.exists():
                sources.extend(read_csv(path))
        verification = verify_result_rows(sources)
        verification["unique_solved_case_ids"] = len({row["case_id"] for row in sources if str(row.get("solved")) == "1"})
        verification["verified_result_rows"] = verification["verified"]
        (OUT / "verification_edge64_hardtail_v1.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(verification, indent=2))
        return
    if "--matched-edge63" in sys.argv:
        run_matched_edge63_control()
        return
    if "--refresh-model" in sys.argv:
        robust_ids = {row["case_id"] for row in read_csv(OUT / "robust_hard_manifest.csv")}
        tree = build_exploratory_tree(rows, robust_ids, max_depth=4)
        (OUT / "hardness_tree.json").write_text(json.dumps(tree, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "MODEL_REFRESHED", "robust_hard": len(robust_ids)}, indent=2))
        return
    if "--run" not in sys.argv:
        return
    _, survivor_sets = run_budget_ladder(rows)
    robust_after_budget = survivor_sets[str(LADDER[-1])]
    _tournament_rows, tournament = strategy_tournament(rows, robust_after_budget)
    robust_after_portfolio, post_rows = deploy_portfolio(rows, robust_after_budget, tournament)
    enrich = enrichment(rows, set(robust_after_portfolio))
    interactions = interaction_enrichment(rows, set(robust_after_portfolio))
    write_csv(OUT / "feature_enrichment.csv", enrich, list(enrich[0].keys()) if enrich else ["feature"])
    write_csv(OUT / "interaction_enrichment.csv", interactions, list(interactions[0].keys()) if interactions else ["interaction"])
    for skeleton in ("fiveleaf2e", "fiveleaf3e"):
        subset = [row for row in rows if row["skeleton"] == skeleton]
        robust = set(robust_after_portfolio) & {row["case_id"] for row in subset}
        write_csv(OUT / f"{skeleton}_analysis.csv", [{"skeleton": skeleton, "pilot_cases": len(subset), "robust_hard": len(robust), "robust_rate": len(robust) / len(subset) if subset else 0.0}], ["skeleton", "pilot_cases", "robust_hard", "robust_rate"])
    weighted = weighted_projection(rows, set(robust_after_portfolio))
    (OUT / "weighted_projection.json").write_text(json.dumps(weighted, indent=2) + "\n", encoding="utf-8")
    # Probe a deterministic subset of the post-portfolio robust set at 30 seconds.
    probe_rows = [rows_by_id[case_id] for case_id in stratified_sample([rows_by_id[case_id] for case_id in robust_after_portfolio], min(256, len(robust_after_portfolio)))]
    probe_ids = [row["case_id"] for row in probe_rows]
    probe_results = run_batch(probe_ids, "compressed", 30.0) if probe_ids else {}
    high_budget = [result_row(case_id, probe_results[case_id], 30.0, "compressed") for case_id in probe_ids]
    write_csv(OUT / "high_budget_256_results.csv", high_budget, list(high_budget[0].keys()) if high_budget else ["case_id"])
    profile = {
        "available_telemetry": "nodes, backtracks, elapsed_seconds, strategy",
        "fine_grained_reject_reasons": "not instrumented in the existing solver; no new search semantics added",
        "post_portfolio_robust_count": len(robust_after_portfolio),
        "robust_profile": {"median_nodes": sorted(int(row["nodes"]) for row in high_budget)[len(high_budget) // 2] if high_budget else 0, "max_nodes": max((int(row["nodes"]) for row in high_budget), default=0), "median_backtracks": sorted(int(row["backtracks"]) for row in high_budget)[len(high_budget) // 2] if high_budget else 0},
    }
    (OUT / "hard_profile.json").write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    tree = build_exploratory_tree(rows, set(robust_after_portfolio), max_depth=4)
    (OUT / "hardness_tree.json").write_text(json.dumps(tree, indent=2) + "\n", encoding="utf-8")
    ladder_rows = read_csv(OUT / "budget_ladder_results.csv")
    verification = verify_result_rows(ladder_rows + _tournament_rows + post_rows + high_budget)
    verification["unique_solved_case_ids"] = len({row["case_id"] for row in ladder_rows + _tournament_rows + post_rows + high_budget if str(row.get("solved")) == "1"})
    verification["verified_result_rows"] = verification["verified"]
    (OUT / "verification_edge64_hardtail_v1.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    write_report(rows, survivor_sets, tournament, robust_after_portfolio, weighted, high_budget)
    print(json.dumps({"status": verification["status"], "robust_hard": len(robust_after_portfolio), "high_budget_solved": sum(str(row["solved"]) == "1" for row in high_budget)}, indent=2))


if __name__ == "__main__":
    main()
