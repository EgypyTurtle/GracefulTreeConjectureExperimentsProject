"""Freeze the C8 native-engine golden regression corpus from audited artifacts."""

from __future__ import annotations

import argparse
import ast
import csv
import json
from pathlib import Path
from typing import Any


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_one(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if not matches:
        raise FileNotFoundError(name)
    return matches[0]


def _parse_intervals(raw: str) -> list[list[int]]:
    """Accept the JSON form and the existing CSV tuple form."""
    value = json.loads(raw) if raw.lstrip().startswith("[") else ast.literal_eval(raw)
    return [[int(part[0]), int(part[1])] for part in value]


def build(results_root: Path, output_root: Path) -> dict[str, Any]:
    base = results_root / "tree1_C8" / "left_leaf_2_exact_v3"
    batch = base / "frontier_directed_v1" / "table_batch_structure_v1"
    rows = list(csv.DictReader((batch / "batch_outcomes.csv").open(encoding="utf-8")))
    tables = []
    for row in rows:
        tables.append({
            "case_id": f"batch_empty_{row['table_key']}",
            "kind": "ALL_EMPTY_TABLE",
            "table_key": row["table_key"],
            "intervals": _parse_intervals(row["intervals_b"]),
            "expected": {
                "outcome": row["outcome"],
                "table_status": "NONEMPTY_TABLE_BUT_ALL_CONTEXTS_EMPTY",
                "local_behavior_count": int(row.get("behavior_count") or row.get("local_behavior_count") or 0),
                "positive_queries": 0,
            },
            "source": str(batch / "batch_outcomes.csv"),
        })

    local_path = _find_one(base, "first_left_witness_geometry.json")
    local = _read_json(local_path)["witness"]
    bilateral_path = base / "full_bilateral_v1" / "bilateral_contexts.csv"
    bilateral_rows = list(csv.DictReader(bilateral_path.open(encoding="utf-8")))
    bilateral = next(row for row in bilateral_rows
                     if row["group_id"] == "345e9b3c3bfdeb1914b08bb0" and row["context_id"] == "114")
    global_path = base / "full_bilateral_v1" / "first_global_compatible_pair.json"
    global_cert = _read_json(global_path)
    cases = tables + [
        {
            "case_id": "known_local_positive_eL2",
            "kind": "KNOWN_LOCAL_POSITIVE",
            "intervals": json.loads(local["left_leaf_2_intervals"]),
            "expected": {
                "geometry_class": local["geometry_class"],
                "eL": int(local["left_outward_extension"]),
                "gap": int(local["run_gap"]),
                "right_middle_compatible_count": int(local["right_middle_compatible_count"]),
            },
            "source": str(local_path),
        },
        {
            "case_id": "known_bilateral_outer_zero_span63",
            "kind": "KNOWN_BILATERAL_OUTER_ZERO",
            "intervals": json.loads(bilateral["left_intervals"]),
            "expected": {
                "left_count": int(bilateral["left_count"]),
                "right_count": int(bilateral["right_count"]),
                "pre_outer_span": int(bilateral["minimum_pre_outer_span"]),
                "outer_edges": int(bilateral["outer_edges"]),
                "mandatory_kernel": [-12, -11, 34],
                "D13": int(bilateral["D13"]),
            },
            "source": str(bilateral_path),
        },
        {
            "case_id": "known_global_compatible_span68",
            "kind": "KNOWN_GLOBAL_COMPATIBLE",
            "intervals": global_cert["blocks"]["left_leaf_2"],
            "expected": {
                "status": global_cert["status"],
                "span": int(global_cert["span"]),
                "all_edge_differences": list(range(1, 64)),
                "global_offset_injective": True,
            },
            "source": str(global_path),
        },
        {
            "case_id": "frontier_span63_kappa2",
            "kind": "FRONTIER_WITNESS",
            "expected": {"span": 63, "kappa": 2},
            "source": str(base / "collision_span_frontier_v1" / "snapshot_outer_frontier.json"),
        },
        {
            "case_id": "frontier_span67_kappa1",
            "kind": "FRONTIER_WITNESS",
            "expected": {"span": 67, "kappa": 1},
            "source": str(base / "collision_span_frontier_v1" / "snapshot_outer_frontier.json"),
        },
        {
            "case_id": "frontier_span68_kappa0",
            "kind": "FRONTIER_WITNESS",
            "expected": {"span": 68, "kappa": 0},
            "source": str(base / "collision_span_frontier_v1" / "snapshot_outer_frontier.json"),
        },
    ]
    for case in cases:
        case.update({"case": CASE, "split_slot": SLOT, **_versions()})
    manifest = {
        "corpus_version": "native-golden.v1",
        "scope": "Tree1/C8.LevelB.v1/split(left_leaf_2)",
        "case_count": len(cases),
        "all_empty_table_count": len(tables),
        "cases": [{"case_id": case["case_id"], "kind": case["kind"], "source": case["source"]} for case in cases],
        **_versions(),
    }
    expected = {"manifest": manifest, "cases": cases}
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_root / "expected_results.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--output-root", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/golden_corpus"))
    args = parser.parse_args()
    print(json.dumps(build(args.results_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
