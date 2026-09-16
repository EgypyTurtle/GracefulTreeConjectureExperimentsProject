#!/usr/bin/env python3
"""Small in-memory cache for exact compiled terminal queries."""

from __future__ import annotations

from typing import Any


class CompiledQueryCache:
    """Cache query results only; compiled geometry persistence is separate."""

    def __init__(self) -> None:
        self._values: dict[tuple, tuple] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple) -> tuple | None:
        value = self._values.get(key)
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        return value

    def put(self, key: tuple, value: tuple) -> None:
        self._values[key] = value

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "query_cache_requests": total,
            "query_cache_hits": self.hits,
            "query_cache_misses": self.misses,
            "query_cache_hit_rate": self.hits / total if total else 0.0,
            "query_cache_entries": len(self._values),
        }
