"""Exact reusable negative and positive certificates for C8 left queries."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any, Iterable


VERSION = "left-negative-cert.v1"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"


def canonical_family_key(
    intervals_a: tuple[tuple[int, int], ...],
    intervals_b: tuple[tuple[int, int], ...],
    left_shift: int,
    middle_min: int,
    middle_max: int,
    span_mode: bool = True,
) -> str:
    payload = {
        "intervals_a": intervals_a,
        "intervals_b": intervals_b,
        "left_shift": int(left_shift),
        "middle_min": int(middle_min),
        "middle_max": int(middle_max),
        "span_mode": bool(span_mode),
        "language": LANGUAGE,
        "ownership": OWNERSHIP,
        "terminal_cache": TERMINAL_CACHE,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _global_private(state: Any, shift: int) -> frozenset[int]:
    return frozenset(int(value) + int(shift) for value in state.private)


def find_small_hitting_set(
    behaviors: Iterable[Any],
    occupied_offsets: Iterable[int],
    shift: int,
    max_size: int = 3,
) -> tuple[int, ...] | None:
    """Return a sound occupied-offset blocker, if one of size <= max_size exists."""
    sets = [_global_private(state, shift) for state in behaviors]
    if not sets:
        return tuple()
    universe = sorted(set(int(value) for value in occupied_offsets))
    for size in range(1, min(max_size, len(universe)) + 1):
        for candidate in itertools.combinations(universe, size):
            chosen = set(candidate)
            if all(private & chosen for private in sets):
                return tuple(candidate)
    return None


class NegativeCertificateCache:
    """Persistent monotone blockers plus positive witness reuse.

    Certificates are sound only for the exact family key.  A stored blocker
    is global-frame data, so it can be reused whenever it is a subset of a
    future occupied set for that family.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.negative: dict[str, list[tuple[int, ...]]] = {}
        self.positive: dict[str, list[tuple[int, ...]]] = {}
        self.stats = {
            "negative_certificate_hits": 0,
            "positive_witness_hits": 0,
            "empty_queries_recorded": 0,
            "small_certificates_recorded": 0,
            "certificate_candidates_missed": 0,
        }
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != VERSION:
                return
            self.negative = {
                str(key): [tuple(int(value) for value in item) for item in values]
                for key, values in payload.get("negative", {}).items()
            }
            self.positive = {
                str(key): [tuple(int(value) for value in item) for item in values]
                for key, values in payload.get("positive", {}).items()
            }
        except (OSError, ValueError, TypeError):
            return

    def _save(self) -> None:
        payload = {
            "version": VERSION,
            "two_run_language": LANGUAGE,
            "allocation_dedup_version": OWNERSHIP,
            "terminal_pair_cache_version": TERMINAL_CACHE,
            "negative": {key: [list(item) for item in values] for key, values in self.negative.items()},
            "positive": {key: [list(item) for item in values] for key, values in self.positive.items()},
            "stats": self.stats,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def probe(self, family_key: str, occupied_offsets: Iterable[int]) -> dict[str, Any] | None:
        occupied = set(int(value) for value in occupied_offsets)
        for witness in self.positive.get(family_key, []):
            if not occupied.intersection(witness):
                self.stats["positive_witness_hits"] += 1
                return {"kind": "POSITIVE_WITNESS", "witness": witness}
        for blocker in self.negative.get(family_key, []):
            if set(blocker).issubset(occupied):
                self.stats["negative_certificate_hits"] += 1
                return {"kind": "NEGATIVE_CERTIFICATE", "blocker": blocker}
        return None

    def record_positive(self, family_key: str, behavior: Any, shift: int) -> None:
        witness = tuple(sorted(_global_private(behavior, shift)))
        values = self.positive.setdefault(family_key, [])
        if witness not in values:
            values.append(witness)
            self._save()

    def record_empty(
        self,
        family_key: str,
        behaviors: Iterable[Any],
        occupied_offsets: Iterable[int],
        shift: int,
        max_size: int = 3,
    ) -> tuple[int, ...] | None:
        behavior_tuple = tuple(behaviors)
        self.stats["empty_queries_recorded"] += 1
        blocker = find_small_hitting_set(behavior_tuple, occupied_offsets, shift, max_size)
        if blocker is None:
            self.stats["certificate_candidates_missed"] += 1
        else:
            values = self.negative.setdefault(family_key, [])
            if blocker not in values:
                values.append(blocker)
                self.stats["small_certificates_recorded"] += 1
                self._save()
        return blocker
