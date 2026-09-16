"""Persistent allocation and middle-context cache for C8 side-terminal runs.

The cache is deliberately versioned.  A cached group is reusable only when
the allocation ownership, local-language, middle-frame, and bitset
fingerprints all agree with the current request.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import pickle
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from edge63_C8_allocations import ALLOCATION_DEDUP_VERSION, iter_allocations
from edge63_C8_allocations import LANGUAGE_VERSION as C8_LANGUAGE_VERSION
from edge63_displacement_first_compact import MIDDLE_PATHS, PATHS, TERMINAL_PATHS, middle_contexts


MIDDLE_CACHE_VERSION = "middle-group-cache.v2"
MIDDLE_FRAME_CONVENTION = "r2=0; left=-Delta_L; right=+Delta_R"
BITSET_UNIVERSE = "signed-offset-mask.v1:edge63:shift256"
TERMINAL_PAIR_CACHE_VERSION = "corrected.v2"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def version_fingerprint(case: str, split_slot: str) -> str:
    payload = {
        "case": case,
        "split_slot": split_slot,
        "two_run_language": C8_LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
        "middle_cache_version": MIDDLE_CACHE_VERSION,
        "middle_frame_convention": MIDDLE_FRAME_CONVENTION,
        "bitset_universe": BITSET_UNIVERSE,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def stable_group_id(case: str, split_slot: str, middle_key: tuple) -> str:
    payload = {
        "fingerprint": version_fingerprint(case, split_slot),
        "middle_key": middle_key,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:24]


def allocation_keys(allocation: dict[str, object]) -> tuple[tuple, tuple]:
    blocks = allocation["blocks"]
    middle_key = tuple((path, blocks[path][0][0], blocks[path][0][1]) for path in MIDDLE_PATHS)
    residual_key = tuple((path, tuple(blocks[path])) for path in TERMINAL_PATHS)
    return middle_key, residual_key


def build_allocation_index(values: tuple[int, ...], split_slot: str) -> tuple[dict[tuple, dict[tuple, tuple[str, ...]]], int]:
    """Build the ownership-preserving index once for this case and split slot."""
    groups: dict[tuple, dict[tuple, tuple[str, ...]]] = defaultdict(dict)
    raw_allocations = 0
    for allocation in iter_allocations(values, split_slot):
        middle_key, residual_key = allocation_keys(allocation)
        entries = []
        for path, intervals in allocation["blocks"].items():
            for index, interval in enumerate(intervals, 1):
                token = path if len(intervals) == 1 else f"{path}__run_{index}"
                entries.append((interval[0], token))
        run_order = tuple(token for _start, token in sorted(entries))
        groups[middle_key].setdefault(residual_key, run_order)
        raw_allocations += 1
    return dict(groups), raw_allocations


def _write_gzip_pickle(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=6) as handle:
        pickle.dump(value, handle, protocol=5)


def _read_gzip_pickle(path: Path) -> object:
    with gzip.open(path, "rb") as handle:
        return pickle.load(handle)


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PersistentMiddleGroupCache:
    """Persistent group cache plus resumable group manifest."""

    def __init__(self, root: Path, case: str, split_slot: str):
        self.root = root
        self.case = case
        self.split_slot = split_slot
        self.fingerprint = version_fingerprint(case, split_slot)
        safe_case = case.replace("/", "_").replace("\\", "_")
        self.cache_root = root / "cache_v2" / safe_case / split_slot
        self.group_root = root / "persistent_middle_groups" / safe_case / split_slot
        self.index_path = self.cache_root / "allocation_index.pkl.gz"
        self.fingerprint_path = self.cache_root / "fingerprint.json"
        self.manifest_path = root / "middle_group_manifest.csv"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.group_root.mkdir(parents=True, exist_ok=True)
        self._groups: dict[tuple, dict[tuple, tuple[str, ...]]] | None = None
        self._raw_allocations = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def _write_fingerprint(self) -> None:
        payload = {
            "cache_version": MIDDLE_CACHE_VERSION,
            "two_run_language": C8_LANGUAGE_VERSION,
            "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
            "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
            "middle_frame_convention": MIDDLE_FRAME_CONVENTION,
            "bitset_universe": BITSET_UNIVERSE,
            "case": self.case,
            "split_slot": self.split_slot,
            "version_fingerprint": self.fingerprint,
        }
        self.fingerprint_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def load_or_build_index(self, values: tuple[int, ...]) -> tuple[dict[tuple, dict[tuple, tuple[str, ...]]], int, bool]:
        if self._groups is not None:
            return self._groups, self._raw_allocations, True
        if self.index_path.exists() and self.fingerprint_path.exists():
            try:
                metadata = json.loads(self.fingerprint_path.read_text(encoding="utf-8"))
                if metadata.get("version_fingerprint") == self.fingerprint:
                    payload = _read_gzip_pickle(self.index_path)
                    if payload.get("version_fingerprint") == self.fingerprint:
                        self._groups = payload["groups"]
                        self._raw_allocations = payload["raw_allocations"]
                        self.cache_hits += 1
                        return self._groups, self._raw_allocations, True
            except (OSError, EOFError, KeyError, ValueError, pickle.PickleError):
                pass
        groups, raw_allocations = build_allocation_index(values, self.split_slot)
        _write_gzip_pickle(self.index_path, {
            "version_fingerprint": self.fingerprint,
            "groups": groups,
            "raw_allocations": raw_allocations,
        })
        self._write_fingerprint()
        self._groups = groups
        self._raw_allocations = raw_allocations
        self.cache_misses += 1
        self.sync_manifest(groups)
        return groups, raw_allocations, False

    def _group_path(self, middle_key: tuple) -> Path:
        return self.group_root / f"middle_group_{stable_group_id(self.case, self.split_slot, middle_key)}.pkl.gz"

    def _manifest_rows_from_index(self, groups: dict[tuple, dict[tuple, tuple[str, ...]]]) -> list[dict[str, object]]:
        existing: dict[str, dict[str, str]] = {}
        if self.manifest_path.exists():
            with self.manifest_path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    if row.get("version_fingerprint") == self.fingerprint:
                        existing[row["group_id"]] = row
        rows = []
        for middle_key, residuals in sorted(groups.items(), key=lambda item: item[0]):
            group_id = stable_group_id(self.case, self.split_slot, middle_key)
            old = existing.get(group_id, {})
            group_path = self._group_path(middle_key)
            status = old.get("status", "PENDING")
            behavior_states = old.get("behavior_states", "")
            runtime = old.get("runtime", "")
            checksum = old.get("checksum", "")
            if group_path.exists():
                try:
                    cached = _read_gzip_pickle(group_path)
                    if cached.get("version_fingerprint") == self.fingerprint:
                        status = cached.get("status", status)
                        behavior_states = len(cached.get("contexts", ()))
                        runtime = cached.get("runtime", runtime)
                        checksum = file_checksum(group_path)
                except (OSError, EOFError, KeyError, ValueError, AttributeError, pickle.PickleError):
                    pass
            rows.append({
                "group_id": group_id,
                "tree": self.case,
                "split_slot": self.split_slot,
                "split_lengths": "",
                "allocation_key": canonical_json(middle_key),
                "raw_middle_combinations": len(residuals),
                "behavior_states": behavior_states,
                "status": status,
                "runtime": runtime,
                "cache_path": str(group_path),
                "checksum": checksum or (file_checksum(group_path) if group_path.exists() else ""),
                "version_fingerprint": self.fingerprint,
                "two_run_language": C8_LANGUAGE_VERSION,
                "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
                "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
            })
        return rows

    def sync_manifest(self, groups: dict[tuple, dict[tuple, tuple[str, ...]]]) -> None:
        rows = self._manifest_rows_from_index(groups)
        if not rows:
            return
        preserved: list[dict[str, str]] = []
        if self.manifest_path.exists():
            with self.manifest_path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    if row.get("version_fingerprint") != self.fingerprint:
                        preserved.append(row)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = list(rows[0])
            for row in preserved:
                for field in row:
                    if field not in fieldnames:
                        fieldnames.append(field)
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(preserved)
            writer.writerows(rows)

    def load_or_build_group(self, values: tuple[int, ...], middle_key: tuple, residuals: dict[tuple, tuple[str, ...]]) -> tuple[dict[str, object], bool]:
        path = self._group_path(middle_key)
        if path.exists():
            try:
                payload = _read_gzip_pickle(path)
                if payload.get("version_fingerprint") == self.fingerprint:
                    self.cache_hits += 1
                    return payload, True
            except (OSError, EOFError, KeyError, ValueError, pickle.PickleError):
                pass
        started = time.time()
        left_block, central_block, right_block = middle_key
        contexts, stats = middle_contexts(
            left_block[1], left_block[2] - left_block[1] + 1,
            central_block[1], central_block[2] - central_block[1] + 1,
            right_block[1], right_block[2] - right_block[1] + 1,
            "B",
        )
        payload = {
            "version_fingerprint": self.fingerprint,
            "group_id": stable_group_id(self.case, self.split_slot, middle_key),
            "case": self.case,
            "split_slot": self.split_slot,
            "middle_key": middle_key,
            "residuals": residuals,
            "contexts": tuple(contexts),
            "build_stats": dict(stats),
            "status": "BUILT" if contexts else "LOCAL_UNSAT",
            "runtime": round(time.time() - started, 6),
        }
        _write_gzip_pickle(path, payload)
        self.cache_misses += 1
        return payload, False

    def stats(self) -> dict[str, object]:
        return {
            "middle_cache_hits": self.cache_hits,
            "middle_cache_misses": self.cache_misses,
            "middle_cache_hit_rate": self.cache_hits / (self.cache_hits + self.cache_misses)
            if self.cache_hits + self.cache_misses else 0.0,
            "index_path": str(self.index_path),
            "manifest_path": str(self.manifest_path),
        }
