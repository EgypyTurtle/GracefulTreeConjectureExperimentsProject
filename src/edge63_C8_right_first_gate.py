"""Exact right-support gate for Tree1 C8 left_leaf_2 runs.

The right side is not split in this scope, so its middle compatibility can be
computed cheaply and cached per middle group.  The cache is only a join-order
optimization: it never changes the accepted construction set.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from edge63_C8_middle_group_cache import (
    PersistentMiddleGroupCache,
    canonical_json,
    version_fingerprint,
)
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_displacement_first import mask_for, values_for_case
from edge63_displacement_first_compact import EDGE_COUNT


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SPLIT_SLOT = "left_leaf_2"
VERSION = "right-support.v1"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def _mask_shift(mask: int, shift: int) -> int:
    return mask << shift if shift >= 0 else mask >> (-shift)


def _compatible_states(states: tuple, middle_mask: int, middle_min: int, middle_max: int, shift: int) -> list[tuple]:
    result = []
    for state in states:
        shifted_mask = _mask_shift(state.mask, shift)
        if shifted_mask & middle_mask:
            continue
        low = min(middle_min, state.min_value + shift)
        high = max(middle_max, state.max_value + shift)
        if high - low <= EDGE_COUNT:
            result.append((state, shifted_mask, low, high))
    return result


def residual_signature(residual_key: tuple) -> str:
    return canonical_json(residual_key)


class RightSupportCache:
    def __init__(self, root: Path, case: str = CASE, split_slot: str = SPLIT_SLOT):
        self.root = root
        self.case = case
        self.split_slot = split_slot
        self.output = root / "tree1_C8" / f"{split_slot}_exact_v3" / "right_first_v1"
        self.cache_root = self.output / "group_cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.fingerprint = version_fingerprint(case, split_slot)

    def path(self, group_id: str) -> Path:
        return self.cache_root / f"right_support_{group_id}.json"

    def load(self, group_id: str) -> dict[str, Any] | None:
        path = self.path(group_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("version") == VERSION
                and payload.get("version_fingerprint") == self.fingerprint
                and payload.get("case") == self.case
                and payload.get("split_slot") == self.split_slot
            ):
                return payload
        except (OSError, ValueError, TypeError):
            pass
        return None

    def build_or_load(
        self,
        group_id: str,
        group: dict[str, Any],
        pair_cache: PersistentTwoRunCache,
        support_index: Any | None = None,
    ) -> tuple[dict[str, Any], bool]:
        cached = self.load(group_id)
        if cached is not None:
            return cached, True

        started = time.perf_counter()
        contexts = tuple(group["contexts"])
        residuals = group["residuals"]
        table_cache: dict[tuple, Any] = {}
        supported_pairs: list[dict[str, Any]] = []
        residual_supported_contexts: dict[str, list[int]] = {}
        right_table_counts: dict[str, int] = {}
        context_count = len(contexts)
        right_support_contexts: set[int] = set()
        right_support_residuals: set[str] = set()
        total_checks = 0
        right_state_total = 0

        for context_index, context in enumerate(contexts):
            middle_values = tuple(int(x) for x in context["all_values"])
            middle_mask = mask_for(middle_values)
            middle_min = min(middle_values)
            middle_max = max(middle_values)
            delta_right = int(context["delta_right"])
            for residual_index, (residual_key, _run_order) in enumerate(residuals.items()):
                total_checks += 1
                blocks = dict(residual_key)
                right_a = tuple(blocks["right_leaf_1"])
                right_b = tuple(blocks["right_leaf_2"])
                pair_key = (right_a, right_b)
                if pair_key not in table_cache:
                    if support_index is None:
                        table_cache[pair_key] = pair_cache.terminal_pairs(right_a, right_b)
                        right_table_counts[residual_signature(pair_key)] = len(table_cache[pair_key])
                    else:
                        table_cache[pair_key] = support_index.get(right_a, right_b)
                        right_table_counts[residual_signature(pair_key)] = int(table_cache[pair_key].state_count)
                right_table = table_cache[pair_key]
                if support_index is None:
                    right_compatible_count = len(_compatible_states(
                        right_table,
                        middle_mask,
                        middle_min,
                        middle_max,
                        delta_right,
                    ))
                else:
                    right_compatible_count = int(right_table.compatible_count(
                        occupied_mask=middle_mask,
                        shift=delta_right,
                        middle_min=middle_min,
                        middle_max=middle_max,
                    ))
                right_state_total += right_compatible_count
                if right_compatible_count == 0:
                    continue
                right_support_contexts.add(int(context["context_id"]))
                right_sig = residual_signature(residual_key)
                right_support_residuals.add(right_sig)
                residual_supported_contexts.setdefault(right_sig, []).append(int(context["context_id"]))
                supported_pairs.append({
                    "context_index": context_index,
                    "context_id": int(context["context_id"]),
                    "residual_index": residual_index,
                    "residual_signature": right_sig,
                    "right_state_count": right_compatible_count,
                })

        payload: dict[str, Any] = {
            "version": VERSION,
            "version_fingerprint": self.fingerprint,
            "case": self.case,
            "split_slot": self.split_slot,
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
            "group_id": group_id,
            "context_count": context_count,
            "residual_count": len(residuals),
            "right_support_context_count": len(right_support_contexts),
            "right_support_residual_count": len(right_support_residuals),
            "supported_pair_count": len(supported_pairs),
            "right_compatible_state_total": right_state_total,
            "total_context_residual_checks": total_checks,
            "right_table_counts": right_table_counts,
            "supported_pairs": supported_pairs,
            "residual_supported_contexts": residual_supported_contexts,
            "runtime_seconds": time.perf_counter() - started,
        }
        self.path(group_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload, False

    @staticmethod
    def pair_supported(payload: dict[str, Any], context_id: int, residual_sig: str) -> bool:
        return bool(payload.get("residual_supported_contexts", {}).get(residual_sig, []) and any(
            int(item.get("context_id", -1)) == int(context_id)
            and item.get("residual_signature") == residual_sig
            for item in payload.get("supported_pairs", [])
        ))

    @staticmethod
    def group_supported(payload: dict[str, Any]) -> bool:
        return int(payload.get("supported_pair_count", 0)) > 0


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"])
        writer.writeheader()
        writer.writerows(rows)


def _append_csv(path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        writer.writerow(row)


def precompute_all(
    root: Path,
    time_limit: float | None = None,
    support_index: Any | None = None,
) -> dict[str, Any]:
    values = values_for_case(CASE)
    middle_cache = PersistentMiddleGroupCache(root, CASE, SPLIT_SLOT)
    pair_cache = PersistentTwoRunCache(root, CASE, SPLIT_SLOT)
    right_cache = RightSupportCache(root, CASE, SPLIT_SLOT)
    groups, raw, index_hit = middle_cache.load_or_build_index(values)
    manifest_path = right_cache.output / "right_support_manifest.json"
    manifest: dict[str, Any] = {
        "version": VERSION,
        "version_fingerprint": right_cache.fingerprint,
        "done_group_ids": [],
        "status": "PENDING",
    }
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            if old.get("version_fingerprint") == right_cache.fingerprint:
                manifest.update(old)
        except (OSError, ValueError, TypeError):
            pass
    done = set(manifest.get("done_group_ids", []))
    summary_path = right_cache.output / "right_support_by_group.csv"
    existing_ids: set[str] = set()
    if summary_path.exists():
        with summary_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                existing_ids.add(row.get("group_id", ""))
    started = time.perf_counter()
    group_rows: list[dict[str, Any]] = []
    residual_rows: list[dict[str, Any]] = []
    residual_path = right_cache.output / "right_support_by_residual.csv"

    ordered = sorted(groups.items(), key=lambda item: (len(item[1]), item[0]))
    processed_this_run = 0
    for middle_key, residuals in ordered:
        group_id = middle_cache._group_path(middle_key).stem.replace(".pkl", "").replace("middle_group_", "")
        if group_id in done:
            continue
        if time_limit is not None and time.perf_counter() - started >= time_limit:
            break
        group, _hit = middle_cache.load_or_build_group(values, middle_key, residuals)
        payload, _cache_hit = right_cache.build_or_load(
            group_id,
            group,
            pair_cache,
            support_index=support_index,
        )
        group_row = {
            "group_id": group_id,
            "case": CASE,
            "split_slot": SPLIT_SLOT,
            "context_count": payload["context_count"],
            "residual_count": payload["residual_count"],
            "right_support_context_count": payload["right_support_context_count"],
            "right_support_residual_count": payload["right_support_residual_count"],
            "supported_pair_count": payload["supported_pair_count"],
            "right_compatible_state_total": payload["right_compatible_state_total"],
            "right_supported": RightSupportCache.group_supported(payload),
            "runtime_seconds": payload["runtime_seconds"],
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
        }
        _append_csv(summary_path, group_row, list(group_row))
        group_rows.append(group_row)
        for item in payload["supported_pairs"]:
            residual_row = {
                "group_id": group_id,
                **item,
                "two_run_language": LANGUAGE,
                "allocation_dedup_version": OWNERSHIP,
                "terminal_pair_cache_version": TERMINAL_CACHE,
            }
            _append_csv(residual_path, residual_row, list(residual_row))
            residual_rows.append(residual_row)
        done.add(group_id)
        processed_this_run += 1
        manifest.update({
            "done_group_ids": sorted(done),
            "done_group_count": len(done),
            "groups_total": len(groups),
            "raw_C8_allocations": raw,
            "allocation_index_cache_hit": index_hit,
            "status": "RUNNING",
        "last_group_id": group_id,
        "support_index_version": getattr(support_index, "VERSION", None) if support_index is not None else None,
        })
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        existing_ids.add(group_id)

    complete = len(done) == len(groups)
    if summary_path.exists():
        with summary_path.open(newline="", encoding="utf-8") as handle:
            all_group_rows = list(csv.DictReader(handle))
    else:
        all_group_rows = []
    manifest.update({
        "done_group_ids": sorted(done),
        "done_group_count": len(done),
        "groups_total": len(groups),
        "status": "COMPLETE" if complete else "UNRESOLVED_RESOURCE",
        "groups_processed_this_run": processed_this_run,
        "right_supported_groups": sum(str(row.get("right_supported", "False")).lower() == "true" for row in all_group_rows),
        "right_empty_groups": sum(str(row.get("right_supported", "False")).lower() != "true" for row in all_group_rows),
    })
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--time-limit", type=float)
    args = parser.parse_args()
    print(json.dumps(precompute_all(args.root, args.time_limit), indent=2))


if __name__ == "__main__":
    main()
