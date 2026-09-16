"""Independent verifier for native golden and existing C8 certificates."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _versions() -> dict[str, str]:
    return {"two_run_language": LANGUAGE, "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE}


def _check_global_certificate(path: Path) -> dict[str, Any]:
    cert = json.loads(path.read_text(encoding="utf-8"))
    relative = {int(key): int(value) for key, value in cert["relative_offsets"].items()}
    diffs = sorted(value for values in cert["path_differences"].values() for value in values)
    return {
        "status": cert.get("status") == "COMPATIBLE_SPAN_GT63_PARTIAL",
        "vertices": len(relative) == 64 and len(set(relative.values())) == 64,
        "span": max(relative.values()) - min(relative.values()) == int(cert["span"]) == 68,
        "edge_differences": diffs == list(range(1, 64)),
        "split_slot": cert.get("split_slot") == "left_leaf_2",
        "versions": all(cert.get(key) == value for key, value in _versions().items()),
    }


def run(native_bench: Path, golden_regression: Path, results_root: Path, output: Path) -> dict[str, Any]:
    regression = json.loads(golden_regression.read_text(encoding="utf-8"))
    rows = regression.get("rows", [])
    checks = [{"check": "native_geometry_regression", "ok": regression.get("status") == "PASS" and all(row.get("status") == "PASS" for row in rows)}]
    base = results_root / "tree1_C8" / "left_leaf_2_exact_v3"
    local = json.loads(next(base.rglob("first_left_witness_geometry.json")).read_text(encoding="utf-8"))["witness"]
    checks.extend([
        {"check": "known_local_eL2", "ok": local.get("geometry_class") == "NEW_C8_GEOMETRY" and int(local["left_outward_extension"]) == 2},
        {"check": "known_local_split", "ok": local.get("left_leaf_2_intervals") == "[[6, 18], [28, 34]]" and int(local["run_gap"]) == 9},
    ])
    bilateral_path = base / "full_bilateral_v1" / "bilateral_contexts.csv"
    bilateral = next(row for row in csv.DictReader(bilateral_path.open(encoding="utf-8"))
                     if row["group_id"] == "345e9b3c3bfdeb1914b08bb0" and row["context_id"] == "114")
    checks.append({"check": "known_bilateral_outer_zero", "ok": int(bilateral["left_count"]) == 4 and int(bilateral["right_count"]) == 2 and int(bilateral["outer_edges"]) == 0 and int(bilateral["minimum_pre_outer_span"]) == 63})
    global_path = base / "full_bilateral_v1" / "first_global_compatible_pair.json"
    for name, value in _check_global_certificate(global_path).items():
        checks.append({"check": f"global_certificate_{name}", "ok": value})
    result = {"status": "PASS" if all(item["ok"] for item in checks) else "FAIL", "checks": checks,
              "certificate_verifier": "independent-read-and-recompute", **_versions()}
    output.mkdir(parents=True, exist_ok=True)
    with (output / "certificate_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["check", "ok"])
        writer.writeheader()
        writer.writerows(checks)
    (output / "batch_verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-benchmark", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/benchmarks/native_benchmark.json"))
    parser.add_argument("--golden-regression", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/benchmarks/golden_regression.json"))
    parser.add_argument("--results-root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--output", type=Path, default=Path("results/edge63_two_interval_gate2/native_engine_v1/certificates"))
    args = parser.parse_args()
    result = run(args.native_benchmark, args.golden_regression, args.results_root, args.output)
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
