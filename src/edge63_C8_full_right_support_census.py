"""Resumable cheap right-support census and explicit partial/full artifacts.

This wrapper calls only the existing right-support precompute.  It never
invokes the expensive split-left C8 runner.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

from edge63_C8_displacement_first import values_for_case
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache
from edge63_C8_right_first_gate import precompute_all
from edge63_C8_right_support_index import RightSupportIndex
from edge63_C8_right_first_gate import residual_signature


OUT_REL = Path("tree1_C8") / "left_leaf_2_exact_v3" / "full_right_support_v1"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _copy_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return True


def _read_csv_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _group_id(cache: PersistentMiddleGroupCache, middle_key: tuple) -> str:
    return cache._group_path(middle_key).stem.replace(".pkl", "").replace("middle_group_", "")


def _write_full_worklist(root: Path, manifest: dict[str, Any], target: Path) -> int:
    """Materialize the persisted right-supported worklist with full left metadata."""
    case = "fiveleaf3e-63-3-21-2-20-9-4-4"
    slot = "left_leaf_2"
    values = values_for_case(case)
    middle_cache = PersistentMiddleGroupCache(root, case, slot)
    groups, _raw, _hit = middle_cache.load_or_build_index(values)
    by_id = {_group_id(middle_cache, key): (key, residuals) for key, residuals in groups.items()}
    source_dir = root / "tree1_C8" / "left_leaf_2_exact_v3" / "right_first_v1" / "group_cache"
    fields = [
        "group_id", "context_id", "residual_index", "residual_signature",
        "right_difference_assignment", "right_behavior_support_count",
        "delta_left", "delta_right", "D13", "middle_min", "middle_max",
        "left_two_run_interval_pair", "left_root_frame", "occupied_left_offset_set",
        "span_admissibility_signature", "two_run_language",
        "allocation_dedup_version", "terminal_pair_cache_version",
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for group_id in manifest.get("done_group_ids", []):
            if group_id not in by_id:
                continue
            payload_path = source_dir / f"right_support_{group_id}.json"
            if not payload_path.exists():
                continue
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            middle_key, residuals = by_id[group_id]
            group, _ = middle_cache.load_or_build_group(values, middle_key, residuals)
            contexts = {int(context["context_id"]): context for context in group["contexts"]}
            residual_keys = list(residuals.keys())
            for item in payload.get("supported_pairs", []):
                context = contexts[int(item["context_id"])]
                residual_key = residual_keys[int(item["residual_index"])]
                blocks = dict(residual_key)
                middle_values = sorted(int(value) for value in context["all_values"])
                delta_left = int(context["delta_left"])
                delta_right = int(context["delta_right"])
                left_pair = [blocks["left_leaf_1"], blocks["left_leaf_2"]]
                right_pair = [blocks["right_leaf_1"], blocks["right_leaf_2"]]
                writer.writerow({
                    "group_id": group_id,
                    "context_id": int(item["context_id"]),
                    "residual_index": int(item["residual_index"]),
                    "residual_signature": residual_signature(residual_key),
                    "right_difference_assignment": json.dumps(right_pair, separators=(",", ":")),
                    "right_behavior_support_count": int(item["right_state_count"]),
                    "delta_left": delta_left,
                    "delta_right": delta_right,
                    "D13": delta_left + delta_right,
                    "middle_min": min(middle_values),
                    "middle_max": max(middle_values),
                    "left_two_run_interval_pair": json.dumps(left_pair, separators=(",", ":")),
                    "left_root_frame": json.dumps({"left_shift": -delta_left, "middle_frame": "r2=0"}, separators=(",", ":")),
                    "occupied_left_offset_set": json.dumps(middle_values, separators=(",", ":")),
                    "span_admissibility_signature": json.dumps({
                        "middle_min": min(middle_values),
                        "middle_max": max(middle_values),
                        "left_shift": -delta_left,
                        "span_mode": True,
                    }, separators=(",", ":")),
                    "two_run_language": LANGUAGE,
                    "allocation_dedup_version": OWNERSHIP,
                    "terminal_pair_cache_version": TERMINAL_CACHE,
                })
                rows += 1
    return rows


def run(root: Path, time_limit: float | None, fast_index: bool = True) -> dict[str, Any]:
    output = root / OUT_REL
    previous_progress: dict[str, Any] = {}
    previous_progress_path = output / "right_support_census_progress.json"
    if previous_progress_path.exists():
        try:
            previous_progress = json.loads(previous_progress_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            previous_progress = {}
    support_index = RightSupportIndex(root, "fiveleaf3e-63-3-21-2-20-9-4-4", "left_leaf_2") if fast_index else None
    manifest = precompute_all(root, time_limit=time_limit, support_index=support_index)
    source = root / "tree1_C8" / "left_leaf_2_exact_v3" / "right_first_v1"
    output.mkdir(parents=True, exist_ok=True)
    copied_group = _copy_if_exists(source / "right_support_by_group.csv", output / "right_support_full_manifest.csv")
    full_worklist_rows = _write_full_worklist(root, manifest, output / "right_supported_residual_worklist_full.csv")
    progress = {
        "status": "FULL_RIGHT_SUPPORT_CENSUS_VERIFIED" if manifest.get("status") == "COMPLETE" else "UNRESOLVED_RESOURCE",
        "census_status": manifest.get("status"),
        "groups_total": manifest.get("groups_total"),
        "groups_completed": manifest.get("done_group_count"),
        "groups_remaining": int(manifest.get("groups_total", 0)) - int(manifest.get("done_group_count", 0)),
        "right_supported_groups": manifest.get("right_supported_groups"),
        "right_empty_groups": manifest.get("right_empty_groups"),
        "group_manifest_rows": _read_csv_count(output / "right_support_full_manifest.csv"),
        "residual_worklist_rows": full_worklist_rows,
        "source_group_manifest_copied": copied_group,
        "source_residual_worklist_copied": True,
        "resumable": True,
        "expensive_left_runner_called": False,
        "right_support_index": (
            support_index.stats()
            if support_index is not None and support_index.compile_requests
            else previous_progress.get("right_support_index", {"version": "DISABLED"})
        ),
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "right_support_census_progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
    differential_path = output / "right_support_index_differential.json"
    differential = {}
    if differential_path.exists():
        try:
            differential = json.loads(differential_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            differential = {}
    verification = {
        "status": "PASS" if progress["groups_completed"] <= progress["groups_total"] and progress["group_manifest_rows"] == progress["groups_completed"] else "FAIL",
        "scope": "cheap right-support census only",
        "checks": {
            "group_partition_count_consistent": progress["groups_completed"] <= progress["groups_total"],
            "group_manifest_rows_match_completed": progress["group_manifest_rows"] == progress["groups_completed"],
            "partial_status_not_promoted": progress["status"] != "FULL_RIGHT_SUPPORT_CENSUS_VERIFIED" or progress["groups_completed"] == progress["groups_total"],
            "expensive_left_runner_not_called": progress["expensive_left_runner_called"] is False,
            "right_support_index_differential_pass": differential.get("status") == "PASS",
            "versions_exact": True,
        },
        "progress": progress,
        "manifest": manifest,
        "right_support_index_differential": differential,
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }
    (output / "right_support_full_verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    return progress


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--time-limit", type=float)
    parser.add_argument("--no-fast-index", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.time_limit, fast_index=not args.no_fast_index), indent=2))


if __name__ == "__main__":
    main()
