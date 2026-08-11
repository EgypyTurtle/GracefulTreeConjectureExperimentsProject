#!/usr/bin/env python3
"""
Graceful tree labeling search tool.

A graceful labeling of a tree with m edges assigns distinct vertex labels from
0..m so that the absolute edge differences are exactly 1..m.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import math
import random
import sqlite3
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Iterable


Edge = tuple[int, int]


_PENDANT_EXTENSION_CACHE: dict[str, tuple[int, ...]] = {}
_PENDANT_EXTENSION_DB: sqlite3.Connection | None = None
_PENDANT_EXTENSION_DB_PATH: str | None = None


def open_pendant_extension_cache(path: str) -> sqlite3.Connection:
    """Open the persistent rooted-certificate cache, creating its schema."""
    global _PENDANT_EXTENSION_DB, _PENDANT_EXTENSION_DB_PATH
    resolved = str(Path(path).resolve())
    if _PENDANT_EXTENSION_DB is not None and _PENDANT_EXTENSION_DB_PATH == resolved:
        return _PENDANT_EXTENSION_DB
    close_pendant_extension_cache()
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS rooted_certificates (
            cache_key TEXT PRIMARY KEY,
            labels TEXT NOT NULL,
            vertex_count INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    connection.commit()
    _PENDANT_EXTENSION_DB = connection
    _PENDANT_EXTENSION_DB_PATH = resolved
    return connection


def close_pendant_extension_cache() -> None:
    """Flush and close the current persistent cache connection."""
    global _PENDANT_EXTENSION_DB, _PENDANT_EXTENSION_DB_PATH
    if _PENDANT_EXTENSION_DB is not None:
        _PENDANT_EXTENSION_DB.commit()
        _PENDANT_EXTENSION_DB.close()
    _PENDANT_EXTENSION_DB = None
    _PENDANT_EXTENSION_DB_PATH = None
    persistent_cache_put.pending = 0


def persistent_cache_get(cache_key: str, cache_size: int) -> tuple[int, ...] | None:
    if _PENDANT_EXTENSION_DB is None:
        return None
    row = _PENDANT_EXTENSION_DB.execute(
        "SELECT labels FROM rooted_certificates WHERE cache_key = ?",
        (cache_key,),
    ).fetchone()
    if row is None:
        return None
    labels = tuple(int(value) for value in row[0].split(","))
    if cache_size > 0 and len(_PENDANT_EXTENSION_CACHE) < cache_size:
        _PENDANT_EXTENSION_CACHE[cache_key] = labels
    return labels


def persistent_cache_put(cache_key: str, labels: tuple[int, ...]) -> bool:
    if _PENDANT_EXTENSION_DB is None:
        return False
    cursor = _PENDANT_EXTENSION_DB.execute(
        """
        INSERT OR IGNORE INTO rooted_certificates
            (cache_key, labels, vertex_count, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (cache_key, ",".join(map(str, labels)), len(labels), time.time()),
    )
    # A small batch keeps the common case fast without losing the whole cache
    # on a normal interrupted run.
    inserted = cursor.rowcount == 1
    if inserted:
        persistent_cache_put.pending += 1
    if persistent_cache_put.pending >= 256:
        _PENDANT_EXTENSION_DB.commit()
        persistent_cache_put.pending = 0
    return inserted


persistent_cache_put.pending = 0


def reduced_certificate_from_full_labels(
    adj: list[list[int]],
    full_labels: list[int],
) -> tuple[str, tuple[int, ...]] | None:
    """Recover the rooted base certificate used by pendant extension."""
    candidates = [path for path in pendant_paths(adj) if len(path) > 2]
    if not candidates or len(full_labels) != len(adj):
        return None
    path = max(candidates, key=lambda item: (len(item), -item[-1]))
    removed_count = len(path) - 2
    removed = set(path[2:])
    kept = [u for u in range(len(adj)) if u not in removed]
    old_to_new = {old: new for new, old in enumerate(kept)}
    reduced_edges = [
        (old_to_new[u], old_to_new[v])
        for u in kept
        for v in adj[u]
        if u < v and v in old_to_new
    ]
    reduced_adj = build_adj(len(kept), reduced_edges)
    working = list(full_labels)
    base_edge_count = len(kept) - 1

    # Undo the extension steps in reverse order.  A newly added leaf is either
    # the new maximum, or the preceding labels were shifted up and it is 0.
    for step in range(removed_count - 1, -1, -1):
        new_vertex = path[2 + step]
        new_label = working[new_vertex]
        current_edges = base_edge_count + step
        if new_label == current_edges + 1:
            pass
        elif new_label == 0:
            previous_vertices = kept + path[2 : 2 + step]
            for vertex in previous_vertices:
                working[vertex] -= 1
        else:
            return None
        working[new_vertex] = -1

    reduced_leaf = old_to_new[path[1]]
    cache_key, canonical_order = rooted_canonical_order(reduced_adj, reduced_leaf)
    reduced_labels = [working[old_vertex] for old_vertex in kept]
    base_labels = tuple(reduced_labels[vertex] for vertex in canonical_order)
    if sorted(base_labels) != list(range(base_edge_count + 1)):
        return None
    if not verify_labeling(reduced_edges, reduced_labels):
        return None
    return cache_key, base_labels


def import_pendant_extension_cache_logs(paths: list[str], cache_db: str) -> int:
    """Import recoverable pendant-extension certificates from CSV logs."""
    open_pendant_extension_cache(cache_db)
    imported = 0
    eligible = 0
    skipped = 0
    for path in paths:
        with open(path, "r", encoding="utf-8", newline="", errors="replace") as source:
            for row in csv.DictReader(source):
                if any("\x00" in (row.get(field) or "") for field in ("case", "strategy", "labels")):
                    skipped += 1
                    continue
                if row.get("solved") != "1":
                    continue
                eligible += 1
                try:
                    n = int(row["vertices"])
                    edges = parse_edge_string(row["edges"])
                    labels = [int(value) for value in row["labels"].split()]
                    if len(labels) != n:
                        raise ValueError("label count does not match vertex count")
                    result = reduced_certificate_from_full_labels(build_adj(n, edges), labels)
                    if result is None:
                        raise ValueError("could not recover reduced certificate")
                    cache_key, base_labels = result
                    expected_base = hashlib.sha256(cache_key.encode("ascii")).hexdigest()[:16]
                    if row.get("reduction_base") and row["reduction_base"] != expected_base:
                        raise ValueError("reduction base hash mismatch")
                except (KeyError, ValueError, IndexError):
                    skipped += 1
                    continue
                imported += int(persistent_cache_put(cache_key, base_labels))
    close_pendant_extension_cache()
    print(f"cache import: eligible={eligible}, imported={imported}, skipped={skipped}")
    print(f"cache database: {cache_db}")
    return 0


@dataclass
class SearchStats:
    nodes: int = 0
    backtracks: int = 0
    started_at: float = 0.0
    strategy: str = "search"
    reduction_base: str = ""
    extended_edges: int = 0


def read_edges(path: str) -> list[Edge]:
    edges: list[Edge] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.replace(",", " ").split()
            if len(parts) != 2:
                raise ValueError(f"{path}:{line_no}: expected two vertex ids")
            u, v = int(parts[0]), int(parts[1])
            if u == v:
                raise ValueError(f"{path}:{line_no}: self-loop {u} {v}")
            edges.append((u, v))
    return edges


def normalize_edges(edges: Iterable[Edge]) -> tuple[list[Edge], list[int]]:
    original = sorted({x for edge in edges for x in edge})
    index = {v: i for i, v in enumerate(original)}
    normalized = [(index[u], index[v]) for u, v in edges]
    return normalized, original


def build_adj(n: int, edges: list[Edge]) -> list[list[int]]:
    adj = [[] for _ in range(n)]
    seen: set[Edge] = set()
    for u, v in edges:
        a, b = sorted((u, v))
        if (a, b) in seen:
            raise ValueError(f"duplicate edge {u} {v}")
        seen.add((a, b))
        if not (0 <= u < n and 0 <= v < n):
            raise ValueError(f"edge out of range: {u} {v}")
        adj[u].append(v)
        adj[v].append(u)
    return adj


def assert_tree(n: int, edges: list[Edge], adj: list[list[int]]) -> None:
    if n == 0:
        raise ValueError("empty graph")
    if len(edges) != n - 1:
        raise ValueError(f"not a tree: {n} vertices need {n - 1} edges, got {len(edges)}")
    seen = [False] * n
    q: deque[int] = deque([0])
    seen[0] = True
    while q:
        u = q.popleft()
        for v in adj[u]:
            if not seen[v]:
                seen[v] = True
                q.append(v)
    if not all(seen):
        raise ValueError("not a tree: graph is disconnected")


def random_tree(n: int, rng: random.Random) -> list[Edge]:
    if n <= 0:
        raise ValueError("random tree size must be positive")
    if n == 1:
        return []
    prufer = [rng.randrange(n) for _ in range(n - 2)]
    degree = [1] * n
    for x in prufer:
        degree[x] += 1
    leaves = sorted(i for i, d in enumerate(degree) if d == 1)
    edges: list[Edge] = []
    for x in prufer:
        leaf = leaves.pop(0)
        edges.append((leaf, x))
        degree[leaf] -= 1
        degree[x] -= 1
        if degree[x] == 1:
            insert_at = 0
            while insert_at < len(leaves) and leaves[insert_at] < x:
                insert_at += 1
            leaves.insert(insert_at, x)
    edges.append((leaves[0], leaves[1]))
    return edges


def spider_tree(legs: list[int]) -> list[Edge]:
    if not legs:
        raise ValueError("a spider needs at least one leg")
    if any(length <= 0 for length in legs):
        raise ValueError("spider leg lengths must be positive")
    edges: list[Edge] = []
    next_vertex = 1
    for length in legs:
        prev = 0
        for _ in range(length):
            cur = next_vertex
            next_vertex += 1
            edges.append((prev, cur))
            prev = cur
    return edges


def _add_path(edges: list[Edge], start: int, length: int, next_vertex: int) -> tuple[int, int]:
    if length <= 0:
        raise ValueError("subdivision lengths must be positive")
    prev = start
    for _ in range(length - 1):
        cur = next_vertex
        next_vertex += 1
        edges.append((prev, cur))
        prev = cur
    end = next_vertex
    next_vertex += 1
    edges.append((prev, end))
    return end, next_vertex


def five_leaf_nonspider_two_branch(
    bridge: int,
    two_leaf_side: tuple[int, int],
    three_leaf_side: tuple[int, int, int],
) -> list[Edge]:
    """A 5-leaf tree with branch degrees 3 and 4."""
    if tuple(sorted(two_leaf_side)) != two_leaf_side:
        raise ValueError("two-leaf side lengths must be sorted")
    if tuple(sorted(three_leaf_side)) != three_leaf_side:
        raise ValueError("three-leaf side lengths must be sorted")
    edges: list[Edge] = []
    branch_a = 0
    branch_b = 1
    next_vertex = 2
    if bridge <= 0:
        raise ValueError("bridge length must be positive")
    if bridge == 1:
        edges.append((branch_a, branch_b))
    else:
        prev = branch_a
        for _ in range(bridge - 1):
            cur = next_vertex
            next_vertex += 1
            edges.append((prev, cur))
            prev = cur
        edges.append((prev, branch_b))
    for length in two_leaf_side:
        _leaf, next_vertex = _add_path(edges, branch_a, length, next_vertex)
    for length in three_leaf_side:
        _leaf, next_vertex = _add_path(edges, branch_b, length, next_vertex)
    return edges


def five_leaf_nonspider_three_branch(
    left_bridge: int,
    right_bridge: int,
    left_leaves: tuple[int, int],
    middle_leaf: int,
    right_leaves: tuple[int, int],
) -> list[Edge]:
    """A 5-leaf tree with three degree-3 branch vertices in a path."""
    if tuple(sorted(left_leaves)) != left_leaves:
        raise ValueError("left leaf lengths must be sorted")
    if tuple(sorted(right_leaves)) != right_leaves:
        raise ValueError("right leaf lengths must be sorted")
    if (left_leaves, left_bridge) > (right_leaves, right_bridge):
        raise ValueError("three-branch trees should be generated in canonical end order")
    edges: list[Edge] = []
    branch_a = 0
    branch_b = 1
    branch_c = 2
    next_vertex = 3
    for start, end, length in (
        (branch_a, branch_b, left_bridge),
        (branch_b, branch_c, right_bridge),
    ):
        if length <= 0:
            raise ValueError("bridge lengths must be positive")
        if length == 1:
            edges.append((start, end))
        else:
            prev = start
            for _ in range(length - 1):
                cur = next_vertex
                next_vertex += 1
                edges.append((prev, cur))
                prev = cur
            edges.append((prev, end))
    for length in left_leaves:
        _leaf, next_vertex = _add_path(edges, branch_a, length, next_vertex)
    _leaf, next_vertex = _add_path(edges, branch_b, middle_leaf, next_vertex)
    for length in right_leaves:
        _leaf, next_vertex = _add_path(edges, branch_c, length, next_vertex)
    return edges


def random_lobster(
    base_vertices: int,
    max_stems_per_base: int,
    max_leaves_per_stem: int,
    rng: random.Random,
    direct_base_leaves: int = 0,
) -> list[Edge]:
    if base_vertices <= 0:
        raise ValueError("lobster base path must have at least one vertex")
    if max_stems_per_base < 0 or max_leaves_per_stem < 0 or direct_base_leaves < 0:
        raise ValueError("lobster limits must be non-negative")

    edges: list[Edge] = [(i, i + 1) for i in range(base_vertices - 1)]
    next_vertex = base_vertices
    for base in range(base_vertices):
        for _ in range(rng.randint(0, direct_base_leaves)):
            leaf = next_vertex
            next_vertex += 1
            edges.append((base, leaf))
        stems = rng.randint(0, max_stems_per_base)
        for _ in range(stems):
            stem = next_vertex
            next_vertex += 1
            edges.append((base, stem))
            leaves = rng.randint(1, max_leaves_per_stem) if max_leaves_per_stem > 0 else 0
            for _ in range(leaves):
                leaf = next_vertex
                next_vertex += 1
                edges.append((stem, leaf))
    return edges


def order_vertices(adj: list[list[int]]) -> list[int]:
    n = len(adj)
    root = max(range(n), key=lambda u: len(adj[u]))
    parent = [-1] * n
    order: list[int] = []
    q: deque[int] = deque([root])
    parent[root] = root
    while q:
        u = q.popleft()
        order.append(u)
        children = [v for v in adj[u] if parent[v] == -1]
        children.sort(key=lambda v: len(adj[v]), reverse=True)
        for v in children:
            parent[v] = u
            q.append(v)
    return order


def solve_graceful(
    adj: list[list[int]],
    time_limit: float | None = None,
    all_solutions: bool = False,
    seed: int | None = None,
) -> tuple[list[int] | None, SearchStats]:
    n = len(adj)
    m = n - 1
    stats = SearchStats(started_at=time.time(), strategy="exact")
    rng = random.Random(seed)

    def timed_out() -> bool:
        return time_limit is not None and time.time() - stats.started_at >= time_limit

    root_candidates = sorted(range(n), key=lambda u: (-len(adj[u]), u))
    if seed is not None:
        degree_groups: dict[int, list[int]] = {}
        for u in root_candidates:
            degree_groups.setdefault(len(adj[u]), []).append(u)
        root_candidates = []
        for degree in sorted(degree_groups, reverse=True):
            group = degree_groups[degree]
            rng.shuffle(group)
            root_candidates.extend(group)

    for root in root_candidates:
        if timed_out():
            break
        labels = [-1] * n
        used_label = [False] * (m + 1)
        used_diff = [False] * (m + 1)
        vertex_order = order_vertices(adj)
        if root in vertex_order:
            vertex_order.remove(root)
        vertex_order.insert(0, root)

        # Complementing every label by m-label is a true global symmetry, so
        # trying label 0 for each possible zero vertex is complete.
        labels[root] = 0
        used_label[0] = True

        def edge_possible_to_unlabeled(u: int) -> bool:
            lu = labels[u]
            for v in adj[u]:
                if labels[v] == -1:
                    ok = False
                    for d in range(1, m + 1):
                        if used_diff[d]:
                            continue
                        for candidate in (lu - d, lu + d):
                            if 0 <= candidate <= m and not used_label[candidate]:
                                ok = True
                                break
                        if ok:
                            break
                    if not ok:
                        return False
            return True

        def choose_vertex() -> int | None:
            best = None
            best_key = None
            for u in range(n):
                if labels[u] != -1:
                    continue
                placed_neighbors = sum(labels[v] != -1 for v in adj[u])
                if placed_neighbors == 0:
                    continue
                key = (-placed_neighbors, -len(adj[u]), u)
                if best_key is None or key < best_key:
                    best_key = key
                    best = u
            if best is not None:
                return best
            for u in vertex_order:
                if labels[u] == -1:
                    return u
            return None

        def candidate_labels(u: int) -> list[int]:
            candidates = []
            placed_neighbors = [v for v in adj[u] if labels[v] != -1]
            for lab in range(m + 1):
                if used_label[lab]:
                    continue
                ok = True
                score = 0
                for v in placed_neighbors:
                    d = abs(lab - labels[v])
                    if d == 0 or used_diff[d]:
                        ok = False
                        break
                    score += d
                if ok:
                    candidates.append((score, lab))
            candidates.sort(reverse=True)
            labs = [lab for _, lab in candidates]
            if seed is not None:
                grouped: dict[int, list[int]] = {}
                for score, lab in candidates:
                    grouped.setdefault(score, []).append(lab)
                labs = []
                for score in sorted(grouped, reverse=True):
                    group = grouped[score]
                    rng.shuffle(group)
                    labs.extend(group)
            return labs

        def backtrack() -> bool:
            if timed_out():
                return False
            stats.nodes += 1
            u = choose_vertex()
            if u is None:
                return all(used_diff[1:])
            for lab in candidate_labels(u):
                new_diffs = []
                valid = True
                for v in adj[u]:
                    if labels[v] == -1:
                        continue
                    d = abs(lab - labels[v])
                    if d == 0 or used_diff[d]:
                        valid = False
                        break
                    new_diffs.append(d)
                if not valid:
                    continue
                labels[u] = lab
                used_label[lab] = True
                for d in new_diffs:
                    used_diff[d] = True
                if edge_possible_to_unlabeled(u) and backtrack():
                    return True
                for d in new_diffs:
                    used_diff[d] = False
                used_label[lab] = False
                labels[u] = -1
            stats.backtracks += 1
            return False

        if backtrack():
            return labels[:], stats

    return None, stats


def solve_graceful_heuristic(
    adj: list[list[int]],
    time_limit: float | None = None,
    seed: int | None = None,
    max_steps: int = 1_000_000,
    restarts: int = 50,
) -> tuple[list[int] | None, SearchStats]:
    n = len(adj)
    m = n - 1
    stats = SearchStats(started_at=time.time(), strategy="heuristic")
    rng = random.Random(seed)
    edges = [(u, v) for u in range(n) for v in adj[u] if u < v]

    def timed_out() -> bool:
        return time_limit is not None and time.time() - stats.started_at >= time_limit

    def unique_diff_count(labels: list[int]) -> int:
        return len({abs(labels[u] - labels[v]) for u, v in edges})

    best_labels: list[int] | None = None
    best_score = -1
    for restart in range(max(1, restarts)):
        if timed_out():
            break
        labels = list(range(n))
        rng.shuffle(labels)
        score = unique_diff_count(labels)
        if score > best_score:
            best_score = score
            best_labels = labels[:]
        temperature = max(1.0, n / 3)
        for step in range(max_steps):
            if timed_out():
                return None, stats
            stats.nodes += 1
            if score == m:
                return labels[:], stats
            a, b = rng.sample(range(n), 2)
            labels[a], labels[b] = labels[b], labels[a]
            new_score = unique_diff_count(labels)
            delta = new_score - score
            accept = delta >= 0 or rng.random() < math.exp(delta / max(temperature, 1e-9))
            if accept:
                score = new_score
                if score > best_score:
                    best_score = score
                    best_labels = labels[:]
            else:
                labels[a], labels[b] = labels[b], labels[a]
            temperature *= 0.99995
            if temperature < 0.01:
                temperature = max(1.0, n / 4) / (restart + 2)
    if best_labels is not None and unique_diff_count(best_labels) == m:
        return best_labels, stats
    return None, stats


def solve_graceful_by_differences(
    adj: list[list[int]],
    time_limit: float | None = None,
    seed: int | None = None,
    max_candidates_per_diff: int | None = None,
) -> tuple[list[int] | None, SearchStats]:
    n = len(adj)
    m = n - 1
    stats = SearchStats(started_at=time.time(), strategy="diff")
    rng = random.Random(seed)
    edges = [(u, v) for u in range(n) for v in adj[u] if u < v]
    edge_order = sorted(range(m), key=lambda i: -(len(adj[edges[i][0]]) + len(adj[edges[i][1]])))
    labels = [-1] * n
    used_label = [False] * (m + 1)
    used_edge = [False] * m

    def timed_out() -> bool:
        return time_limit is not None and time.time() - stats.started_at >= time_limit

    def can_place(d: int, edge_index: int, low_label: int, high_at_u: bool) -> tuple[bool, list[tuple[int, int]]]:
        u, v = edges[edge_index]
        lu = high_label = low_label + d
        if high_label > m:
            return False, []
        assignments = [(u, high_label), (v, low_label)] if high_at_u else [(u, low_label), (v, high_label)]
        changes = []
        for vertex, label in assignments:
            current = labels[vertex]
            if current != -1:
                if current != label:
                    return False, []
                continue
            if used_label[label]:
                return False, []
            changes.append((vertex, label))
        return True, changes

    def candidate_moves(d: int) -> list[tuple[int, int, bool, list[tuple[int, int]]]]:
        moves = []
        for edge_index in edge_order:
            if timed_out():
                break
            if used_edge[edge_index]:
                continue
            u, v = edges[edge_index]
            lu, lv = labels[u], labels[v]
            if lu != -1 and lv != -1:
                if abs(lu - lv) == d:
                    low = min(lu, lv)
                    high_at_u = lu > lv
                    ok, changes = can_place(d, edge_index, low, high_at_u)
                    if ok:
                        edge_degree = len(adj[u]) + len(adj[v])
                        moves.append((edge_index, low, high_at_u, changes, 2, edge_degree))
                continue
            lows: list[int]
            if lu != -1:
                lows = [lu - d, lu]
            elif lv != -1:
                lows = [lv - d, lv]
            else:
                lows = list(range(m - d + 1))
            for low in lows:
                if timed_out():
                    break
                if not (0 <= low <= m - d):
                    continue
                for high_at_u in (False, True):
                    ok, changes = can_place(d, edge_index, low, high_at_u)
                    if ok:
                        placed_now = 2 - len(changes)
                        edge_degree = len(adj[u]) + len(adj[v])
                        moves.append((edge_index, low, high_at_u, changes, placed_now, edge_degree))
        if seed is not None:
            rng.shuffle(moves)
        moves.sort(key=lambda item: (-item[4], -item[5], item[1], item[0]))
        trimmed = [(e, low, high, changes) for e, low, high, changes, _, _ in moves]
        if max_candidates_per_diff is not None and len(trimmed) > max_candidates_per_diff:
            return trimmed[:max_candidates_per_diff]
        return trimmed

    def feasible_remaining(next_d: int) -> bool:
        return next_d <= 0 or bool(candidate_moves(next_d))

    def backtrack(d: int) -> bool:
        if timed_out():
            return False
        stats.nodes += 1
        if d == 0:
            return all(label != -1 for label in labels)
        moves = candidate_moves(d)
        for edge_index, _low, _high_at_u, changes in moves:
            used_edge[edge_index] = True
            for vertex, label in changes:
                labels[vertex] = label
                used_label[label] = True
            if feasible_remaining(d - 1) and backtrack(d - 1):
                return True
            for vertex, label in reversed(changes):
                labels[vertex] = -1
                used_label[label] = False
            used_edge[edge_index] = False
        stats.backtracks += 1
        return False

    if backtrack(m):
        return labels[:], stats
    return None, stats


def solve_graceful_branch_differences(
    adj: list[list[int]],
    time_limit: float | None = None,
    seed: int | None = None,
    max_candidates_per_diff: int | None = None,
    fixed_zero_vertex: int | None = None,
    max_nodes: int | None = None,
) -> tuple[list[int] | None, SearchStats]:
    n = len(adj)
    m = n - 1
    stats = SearchStats(started_at=time.time(), strategy="branch")
    rng = random.Random(seed)
    edges = [(u, v) for u in range(n) for v in adj[u] if u < v]
    branch_vertices = [u for u in range(n) if len(adj[u]) >= 3]
    if fixed_zero_vertex is not None:
        if not 0 <= fixed_zero_vertex < n:
            raise ValueError("fixed zero vertex is outside the graph")
        root_candidates = [fixed_zero_vertex]
    else:
        root_candidates = sorted(branch_vertices or range(n), key=lambda u: (-len(adj[u]), u))
    if seed is not None and fixed_zero_vertex is None:
        rng.shuffle(root_candidates)

    def timed_out() -> bool:
        if max_nodes is not None and stats.nodes >= max_nodes:
            return True
        return time_limit is not None and time.time() - stats.started_at >= time_limit

    def dist_from_roots(roots: list[int]) -> list[int]:
        dist = [-1] * n
        q: deque[int] = deque()
        for root in roots:
            dist[root] = 0
            q.append(root)
        while q:
            u = q.popleft()
            for v in adj[u]:
                if dist[v] == -1:
                    dist[v] = dist[u] + 1
                    q.append(v)
        return dist

    branch_dist = dist_from_roots(branch_vertices or root_candidates[:1])

    for root in root_candidates:
        if timed_out():
            break
        labels = [-1] * n
        used_label = [False] * (m + 1)
        used_edge = [False] * m
        labels[root] = 0
        used_label[0] = True

        def can_place(d: int, edge_index: int, low_label: int, high_at_u: bool) -> tuple[bool, list[tuple[int, int]]]:
            u, v = edges[edge_index]
            high_label = low_label + d
            if high_label > m:
                return False, []
            assignments = [(u, high_label), (v, low_label)] if high_at_u else [(u, low_label), (v, high_label)]
            changes = []
            for vertex, label in assignments:
                current = labels[vertex]
                if current != -1:
                    if current != label:
                        return False, []
                    continue
                if used_label[label]:
                    return False, []
                changes.append((vertex, label))
            return True, changes

        def candidate_moves(d: int) -> list[tuple[int, list[tuple[int, int]]]]:
            moves = []
            for edge_index, (u, v) in enumerate(edges):
                if used_edge[edge_index]:
                    continue
                lu, lv = labels[u], labels[v]
                if lu != -1 and lv != -1:
                    lows = [min(lu, lv)] if abs(lu - lv) == d else []
                elif lu != -1:
                    lows = [lu - d, lu]
                elif lv != -1:
                    lows = [lv - d, lv]
                else:
                    continue
                for low in lows:
                    if not (0 <= low <= m - d):
                        continue
                    for high_at_u in (False, True):
                        ok, changes = can_place(d, edge_index, low, high_at_u)
                        if not ok:
                            continue
                        placed_now = 2 - len(changes)
                        branch_touch = int(u in branch_vertices) + int(v in branch_vertices)
                        near_branch = -(branch_dist[u] + branch_dist[v])
                        extremeness = sum(max(label, m - label) for _vertex, label in changes)
                        moves.append((edge_index, changes, placed_now, branch_touch, near_branch, extremeness))
            if seed is not None:
                rng.shuffle(moves)
            moves.sort(key=lambda item: (-item[2], -item[3], -item[4], -item[5], item[0]))
            trimmed = [(edge_index, changes) for edge_index, changes, *_rest in moves]
            if max_candidates_per_diff is not None and len(trimmed) > max_candidates_per_diff:
                return trimmed[:max_candidates_per_diff]
            return trimmed

        def feasible_remaining(next_d: int) -> bool:
            return next_d <= 0 or bool(candidate_moves(next_d))

        def backtrack(d: int) -> bool:
            if timed_out():
                return False
            stats.nodes += 1
            if d == 0:
                return all(label != -1 for label in labels)
            for edge_index, changes in candidate_moves(d):
                used_edge[edge_index] = True
                for vertex, label in changes:
                    labels[vertex] = label
                    used_label[label] = True
                if feasible_remaining(d - 1) and backtrack(d - 1):
                    return True
                for vertex, label in reversed(changes):
                    labels[vertex] = -1
                    used_label[label] = False
                used_edge[edge_index] = False
            stats.backtracks += 1
            return False

        if backtrack(m):
            return labels[:], stats
    return None, stats


def pendant_paths(adj: list[list[int]]) -> list[list[int]]:
    """Return maximal anchor-to-leaf paths whose internal vertices have degree 2."""
    paths: list[list[int]] = []
    for leaf in range(len(adj)):
        if len(adj[leaf]) != 1:
            continue
        reverse_path = [leaf]
        previous = -1
        current = leaf
        while True:
            next_vertices = [v for v in adj[current] if v != previous]
            if not next_vertices:
                break
            nxt = next_vertices[0]
            reverse_path.append(nxt)
            previous, current = current, nxt
            if len(adj[current]) != 2:
                break
        paths.append(list(reversed(reverse_path)))
    return paths


def rooted_canonical_order(adj: list[list[int]], root: int) -> tuple[str, list[int]]:
    """Return an AHU-style rooted-tree code and a compatible vertex order."""
    def visit(vertex: int, parent: int) -> tuple[str, list[int]]:
        children = [visit(child, vertex) for child in adj[vertex] if child != parent]
        children.sort(key=lambda item: item[0])
        code = "(" + "".join(child_code for child_code, _order in children) + ")"
        order = [vertex]
        for _child_code, child_order in children:
            order.extend(child_order)
        return code, order

    return visit(root, -1)


def solve_graceful_pendant_extension(
    adj: list[list[int]],
    max_nodes: int = 2_000,
    time_limit: float | None = None,
    cache_size: int = 100_000,
    cache_db: str | None = None,
) -> tuple[list[int] | None, SearchStats]:
    """Reduce one pendant path to one edge, then rebuild it by extremal extension."""
    started_at = time.time()
    if cache_db:
        open_pendant_extension_cache(cache_db)
    candidates = [path for path in pendant_paths(adj) if len(path) > 2]
    if not candidates:
        return None, SearchStats(started_at=started_at, strategy="pendant-extension")
    path = max(candidates, key=lambda item: (len(item), -item[-1]))
    removed = set(path[2:])
    kept = [u for u in range(len(adj)) if u not in removed]
    old_to_new = {old: new for new, old in enumerate(kept)}
    reduced_edges = [
        (old_to_new[u], old_to_new[v])
        for u in kept
        for v in adj[u]
        if u < v and v in old_to_new
    ]
    reduced_adj = build_adj(len(kept), reduced_edges)
    reduced_leaf = old_to_new[path[1]]
    cache_key, canonical_order = rooted_canonical_order(reduced_adj, reduced_leaf)
    reduction_base = hashlib.sha256(cache_key.encode("ascii")).hexdigest()[:16]
    cached_labels = _PENDANT_EXTENSION_CACHE.get(cache_key) if cache_size > 0 else None
    cache_strategy = "pendant-extension-cache"
    if cached_labels is None and cache_db:
        cached_labels = persistent_cache_get(cache_key, cache_size)
        if cached_labels is not None:
            cache_strategy = "pendant-extension-disk-cache"
    if cached_labels is not None:
        labels = [-1] * len(kept)
        for canonical_index, vertex in enumerate(canonical_order):
            labels[vertex] = cached_labels[canonical_index]
        stats = SearchStats(started_at=started_at, strategy=cache_strategy)
    else:
        labels, stats = solve_graceful_branch_differences(
            reduced_adj,
            time_limit=time_limit,
            fixed_zero_vertex=reduced_leaf,
            max_nodes=max_nodes,
        )
        stats.started_at = started_at
        stats.strategy = "pendant-extension"
        if labels is None:
            stats.reduction_base = reduction_base
            stats.extended_edges = len(path) - 2
            return None, stats
        if cache_size > 0 and len(_PENDANT_EXTENSION_CACHE) < cache_size:
            _PENDANT_EXTENSION_CACHE[cache_key] = tuple(labels[vertex] for vertex in canonical_order)
        persistent_cache_put(
            cache_key,
            tuple(labels[vertex] for vertex in canonical_order),
        )
    stats.reduction_base = reduction_base
    stats.extended_edges = len(path) - 2

    target_labels = [-1] * len(adj)
    assigned: list[int] = []
    for new_vertex, old_vertex in enumerate(kept):
        target_labels[old_vertex] = labels[new_vertex]
        assigned.append(old_vertex)

    endpoint = path[1]
    current_edges = len(kept) - 1
    for new_vertex in path[2:]:
        if target_labels[endpoint] == 0:
            target_labels[new_vertex] = current_edges + 1
        elif target_labels[endpoint] == current_edges:
            for vertex in assigned:
                target_labels[vertex] += 1
            target_labels[new_vertex] = 0
        else:
            return None, stats
        assigned.append(new_vertex)
        endpoint = new_vertex
        current_edges += 1
    return target_labels, stats


def solve_graceful_caterpillar(adj: list[list[int]]) -> tuple[list[int] | None, SearchStats]:
    """Construct the standard alpha-labeling of a caterpillar in linear time."""
    n = len(adj)
    stats = SearchStats(started_at=time.time(), strategy="caterpillar")
    if n == 0:
        return None, stats
    if n == 1:
        return [0], stats

    spine_vertices = [u for u in range(n) if len(adj[u]) > 1]
    if not spine_vertices:
        if n == 2 and adj[0] == [1] and adj[1] == [0]:
            return [0, 1], stats
        return None, stats

    spine_set = set(spine_vertices)
    spine_adj = {u: [v for v in adj[u] if v in spine_set] for u in spine_vertices}
    if any(len(neighbors) > 2 for neighbors in spine_adj.values()):
        return None, stats
    if len(spine_vertices) == 1:
        spine = spine_vertices
    else:
        endpoints = sorted(u for u in spine_vertices if len(spine_adj[u]) == 1)
        if len(endpoints) != 2:
            return None, stats
        spine = []
        previous = -1
        current = endpoints[0]
        while True:
            spine.append(current)
            next_vertices = [v for v in spine_adj[current] if v != previous]
            if not next_vertices:
                break
            previous, current = current, next_vertices[0]
        if len(spine) != len(spine_vertices):
            return None, stats

    low_order: list[int] = []
    high_order: list[int] = []
    for index, vertex in enumerate(spine):
        leaves = sorted(v for v in adj[vertex] if v not in spine_set)
        if any(len(adj[leaf]) != 1 for leaf in leaves):
            return None, stats
        if index % 2 == 0:
            low_order.append(vertex)
            high_order.extend(leaves)
        else:
            low_order.extend(leaves)
            high_order.append(vertex)

    if len(low_order) + len(high_order) != n:
        return None, stats
    labels = [-1] * n
    for label, vertex in enumerate(low_order):
        labels[vertex] = label
    m = n - 1
    for rank, vertex in enumerate(high_order):
        labels[vertex] = m - rank
    return labels, stats


def spider_paths_from_adj(adj: list[list[int]]) -> tuple[int, list[list[int]]]:
    n = len(adj)
    centers = [u for u in range(n) if len(adj[u]) > 2]
    if len(centers) == 1:
        center = centers[0]
    else:
        center = max(range(n), key=lambda u: len(adj[u]))
    paths: list[list[int]] = []
    for first in sorted(adj[center]):
        path = [first]
        prev = center
        cur = first
        while len(adj[cur]) == 2:
            nxt = adj[cur][0] if adj[cur][1] == prev else adj[cur][1]
            path.append(nxt)
            prev, cur = cur, nxt
        paths.append(path)
    if sum(len(path) for path in paths) != n - 1:
        raise ValueError("graph is not a spider rooted at one center")
    return center, paths


def solve_graceful_spider(
    adj: list[list[int]],
    time_limit: float | None = None,
    seed: int | None = None,
    leg_order: str = "long",
    label_order: str = "extreme",
) -> tuple[list[int] | None, SearchStats]:
    n = len(adj)
    m = n - 1
    stats = SearchStats(started_at=time.time(), strategy="spider")
    rng = random.Random(seed)
    center, paths = spider_paths_from_adj(adj)
    if leg_order == "long":
        paths.sort(key=lambda path: (-len(path), path[0]))
    elif leg_order == "short":
        paths.sort(key=lambda path: (len(path), path[0]))
    elif leg_order == "balanced":
        paths.sort(key=lambda path: (-abs(len(path) - (m / max(1, len(paths)))), -len(path), path[0]))
    elif leg_order == "random":
        rng.shuffle(paths)
    else:
        raise ValueError(f"unknown spider leg order: {leg_order}")
    labels = [-1] * n
    labels[center] = 0
    used_label = [False] * (m + 1)
    used_label[0] = True
    used_diff = [False] * (m + 1)
    positions = [0] * len(paths)

    def timed_out() -> bool:
        return time_limit is not None and time.time() - stats.started_at >= time_limit

    def active_moves(d: int) -> list[tuple[int, int, int]]:
        moves = []
        for leg_index, path in enumerate(paths):
            pos = positions[leg_index]
            if pos >= len(path):
                continue
            parent = center if pos == 0 else path[pos - 1]
            child = path[pos]
            parent_label = labels[parent]
            child_options = [parent_label + d, parent_label - d]
            if label_order == "low":
                child_options.sort()
            elif label_order == "high":
                child_options.sort(reverse=True)
            elif label_order == "random":
                rng.shuffle(child_options)
            elif label_order != "extreme":
                raise ValueError(f"unknown spider label order: {label_order}")
            for child_label in child_options:
                if 0 <= child_label <= m and not used_label[child_label]:
                    remaining_after = len(path) - pos - 1
                    # Prefer forced-looking moves: long unfinished legs, then extreme labels.
                    extremeness = max(child_label, m - child_label)
                    moves.append((leg_index, child, child_label, remaining_after, extremeness))
        if seed is not None:
            rng.shuffle(moves)
        if label_order == "low":
            moves.sort(key=lambda item: (-item[3], item[2], item[0]))
        elif label_order == "high":
            moves.sort(key=lambda item: (-item[3], -item[2], item[0]))
        else:
            moves.sort(key=lambda item: (-item[3], -item[4], item[0], item[2]))
        return [(leg_index, child, child_label) for leg_index, child, child_label, _, _ in moves]

    def has_move_for(d: int) -> bool:
        return bool(active_moves(d))

    def backtrack(d: int) -> bool:
        if timed_out():
            return False
        stats.nodes += 1
        if d == 0:
            return all(pos == len(path) for pos, path in zip(positions, paths))
        moves = active_moves(d)
        for leg_index, child, child_label in moves:
            labels[child] = child_label
            used_label[child_label] = True
            used_diff[d] = True
            positions[leg_index] += 1
            if (d == 1 or has_move_for(d - 1)) and backtrack(d - 1):
                return True
            positions[leg_index] -= 1
            used_diff[d] = False
            used_label[child_label] = False
            labels[child] = -1
        stats.backtracks += 1
        return False

    if backtrack(m):
        return labels[:], stats
    return None, stats


def solve_tree(adj: list[list[int]], args: argparse.Namespace, seed: int | None = None) -> tuple[list[int] | None, SearchStats]:
    if not args.no_constructive_fastpath:
        labels, stats = solve_graceful_caterpillar(adj)
        if labels is not None:
            return labels, stats
    if args.method == "compressed":
        labels, prefix_stats = solve_graceful_pendant_extension(
            adj,
            max_nodes=args.extension_fastpath_nodes,
            cache_size=args.extension_cache_size,
            cache_db=args.extension_cache_db,
        )
        if labels is not None:
            return labels, prefix_stats
        elapsed = time.time() - prefix_stats.started_at
        remaining = None if args.time_limit is None else max(0.0, args.time_limit - elapsed)
        labels, stats = solve_graceful_branch_differences(
            adj,
            time_limit=remaining,
            seed=seed,
            max_candidates_per_diff=args.diff_candidates,
        )
        stats.nodes += prefix_stats.nodes
        stats.backtracks += prefix_stats.backtracks
        stats.started_at = prefix_stats.started_at
        stats.strategy = "pendant-extension+branch"
        stats.reduction_base = prefix_stats.reduction_base
        stats.extended_edges = prefix_stats.extended_edges
        return labels, stats
    if args.method == "exact":
        return solve_graceful(adj, time_limit=args.time_limit, seed=seed)
    if args.method == "spider":
        return solve_graceful_spider(
            adj,
            time_limit=args.time_limit,
            seed=seed,
            leg_order=args.spider_order,
            label_order=args.spider_label_order,
        )
    if args.method == "diff":
        return solve_graceful_by_differences(
            adj,
            time_limit=args.time_limit,
            seed=seed,
            max_candidates_per_diff=args.diff_candidates,
        )
    if args.method == "branch":
        return solve_graceful_branch_differences(
            adj,
            time_limit=args.time_limit,
            seed=seed,
            max_candidates_per_diff=args.diff_candidates,
        )
    if args.method == "heuristic":
        return solve_graceful_heuristic(
            adj,
            time_limit=args.time_limit,
            seed=seed,
            max_steps=args.heuristic_steps,
            restarts=args.heuristic_restarts,
        )
    try:
        labels, stats = solve_graceful_spider(
            adj,
            time_limit=args.time_limit,
            seed=seed,
            leg_order=args.spider_order,
            label_order=args.spider_label_order,
        )
        if labels is not None:
            return labels, stats
        if args.time_limit is not None and time.time() - stats.started_at >= args.time_limit:
            return None, stats
    except ValueError:
        stats = SearchStats(started_at=time.time(), strategy="hybrid")

    labels, stats = solve_graceful_branch_differences(
        adj,
        time_limit=args.time_limit,
        seed=seed,
        max_candidates_per_diff=args.diff_candidates,
    )
    if labels is not None:
        return labels, stats
    if args.time_limit is not None and time.time() - stats.started_at >= args.time_limit:
        return None, stats

    labels, stats = solve_graceful_by_differences(
        adj,
        time_limit=args.time_limit,
        seed=seed,
        max_candidates_per_diff=args.diff_candidates,
    )
    if labels is not None:
        return labels, stats
    if args.time_limit is not None and time.time() - stats.started_at >= args.time_limit:
        return None, stats
    labels, hstats = solve_graceful_heuristic(
        adj,
        time_limit=args.time_limit,
        seed=seed,
        max_steps=args.heuristic_steps,
        restarts=args.heuristic_restarts,
    )
    if labels is not None:
        hstats.nodes += stats.nodes
        hstats.backtracks += stats.backtracks
        hstats.started_at = stats.started_at
        return labels, hstats
    if args.time_limit is not None and time.time() - stats.started_at >= args.time_limit:
        return None, stats
    labels2, stats2 = solve_graceful(adj, time_limit=args.time_limit, seed=seed)
    stats2.nodes += stats.nodes
    stats2.backtracks += stats.backtracks
    stats2.started_at = stats.started_at
    return labels2, stats2


def verify_labeling(edges: list[Edge], labels: list[int]) -> bool:
    m = len(edges)
    if sorted(labels) != list(range(m + 1)):
        return False
    diffs = sorted(abs(labels[u] - labels[v]) for u, v in edges)
    return diffs == list(range(1, m + 1))


def print_solution(edges: list[Edge], labels: list[int], original: list[int] | None = None) -> None:
    print("graceful labeling found")
    print("vertices:")
    for i, lab in enumerate(labels):
        name = original[i] if original else i
        print(f"  {name}: {lab}")
    print("edge differences:")
    for u, v in edges:
        a = original[u] if original else u
        b = original[v] if original else v
        print(f"  {a} {b}: {abs(labels[u] - labels[v])}")


def write_edge_file(path: str, edges: list[Edge]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for u, v in edges:
            f.write(f"{u} {v}\n")


def edge_string(edges: list[Edge]) -> str:
    return " ".join(f"{u}-{v}" for u, v in edges)


def parse_edge_string(text: str) -> list[Edge]:
    edges: list[Edge] = []
    for token in text.split():
        if "-" not in token:
            raise ValueError(f"bad edge token in CSV: {token!r}")
        left, right = token.split("-", 1)
        edges.append((int(left), int(right)))
    return edges


def tree_features(n: int, edges: list[Edge]) -> dict[str, int]:
    adj = build_adj(n, edges)
    degrees = [len(nei) for nei in adj]
    leaves = sum(d == 1 for d in degrees)

    def farthest(start: int) -> tuple[int, int]:
        dist = [-1] * n
        dist[start] = 0
        q: deque[int] = deque([start])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if dist[v] == -1:
                    dist[v] = dist[u] + 1
                    q.append(v)
        far = max(range(n), key=lambda u: dist[u])
        return far, dist[far]

    a, _ = farthest(0)
    _b, diameter = farthest(a)
    return {
        "vertices": n,
        "edges": len(edges),
        "leaves": leaves,
        "max_degree": max(degrees) if degrees else 0,
        "diameter": diameter,
    }


def label_string(labels: list[int] | None) -> str:
    return "" if labels is None else " ".join(map(str, labels))


def load_solved_cases(paths: str | list[str]) -> set[str]:
    if isinstance(paths, str):
        paths = [paths]
    solved: set[str] = set()
    for path in paths:
        with open(path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                case_name = row.get("case", "")
                if not case_name or "\x00" in case_name:
                    continue
                if row.get("solved") == "1":
                    solved.add(case_name)
    return solved


def run_cases(
    cases: Iterable[tuple[str, int, list[Edge], int | None]],
    args: argparse.Namespace,
    default_log: str,
    default_hardest: str,
    default_failed: str,
) -> int:
    log_path = args.log or default_log
    hard_path = args.save_hardest or default_hardest
    failed_path = args.save_failed or default_failed
    best_nodes = -1
    best_elapsed = -1.0
    solved = 0
    timeouts = 0
    skipped = 0
    checked = 0
    started = time.time()
    skip_solved = load_solved_cases(args.skip_solved_from) if args.skip_solved_from else set()
    fieldnames = [
        "case",
        "vertices",
        "seed",
        "strategy",
        "reduction_base",
        "extended_edges",
        "status",
        "solved",
        "nodes",
        "backtracks",
        "elapsed_seconds",
        "edges",
        "labels",
    ]

    with open(log_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for case_name, n, edges, case_seed in cases:
            if case_name in skip_solved:
                skipped += 1
                continue
            if args.total_time_limit is not None and time.time() - started >= args.total_time_limit:
                print(f"stopping: total time limit reached after {checked} cases")
                break
            if args.max_vertices is not None and n > args.max_vertices:
                skipped += 1
                writer.writerow(
                    {
                        "case": case_name,
                        "vertices": n,
                        "seed": "" if case_seed is None else case_seed,
                        "strategy": "skipped",
                        "reduction_base": "",
                        "extended_edges": 0,
                        "status": "skipped_too_large",
                        "solved": 0,
                        "nodes": 0,
                        "backtracks": 0,
                        "elapsed_seconds": "0.000000",
                        "edges": edge_string(edges),
                        "labels": "",
                    }
                )
                if args.progress and (checked + skipped == 1 or (checked + skipped) % args.progress == 0):
                    print(
                        f"case {checked + skipped}: solved={solved}, timeouts={timeouts}, "
                        f"skipped={skipped}, hardest_nodes={best_nodes}"
                    )
                continue
            adj = build_adj(n, edges)
            assert_tree(n, edges, adj)
            labels, stats = solve_tree(adj, args, seed=case_seed)
            elapsed = time.time() - stats.started_at
            ok = labels is not None and verify_labeling(edges, labels)
            checked += 1
            solved += int(ok)
            timeouts += int(not ok)
            status = "solved" if ok else "timeout_or_failed"
            if stats.nodes > best_nodes or (stats.nodes == best_nodes and elapsed > best_elapsed):
                best_nodes = stats.nodes
                best_elapsed = elapsed
                write_edge_file(hard_path, edges)
            if not ok:
                write_edge_file(failed_path, edges)
            writer.writerow(
                {
                    "case": case_name,
                    "vertices": n,
                    "seed": "" if case_seed is None else case_seed,
                    "strategy": stats.strategy,
                    "reduction_base": stats.reduction_base,
                    "extended_edges": stats.extended_edges,
                    "status": status,
                    "solved": int(ok),
                    "nodes": stats.nodes,
                    "backtracks": stats.backtracks,
                    "elapsed_seconds": f"{elapsed:.6f}",
                    "edges": edge_string(edges),
                    "labels": label_string(labels),
                }
            )
            f.flush()
            if args.progress and (checked == 1 or checked % args.progress == 0):
                rate = checked / max(time.time() - started, 1e-9)
                print(
                    f"case {checked}: solved={solved}, timeouts={timeouts}, skipped={skipped}, "
                    f"hardest_nodes={best_nodes}, rate={rate:.2f}/s"
                )

    close_pendant_extension_cache()

    elapsed_total = time.time() - started
    print(
        f"complete: checked={checked}, solved={solved}, timeouts={timeouts}, "
        f"skipped={skipped}, elapsed={elapsed_total:.3f}s"
    )
    print(f"log: {log_path}")
    if best_nodes >= 0:
        print(f"hardest tree: {hard_path} ({best_nodes} search nodes)")
    else:
        print("hardest tree: none, no cases were searched")
    if timeouts:
        print(f"latest failed/timeout tree: {failed_path}")
    return 0 if timeouts == 0 else 2


def run_batch(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    def cases() -> Iterable[tuple[str, int, list[Edge], int | None]]:
        for trial in range(1, args.batch + 1):
            trial_seed = rng.randrange(2**63)
            yield f"random-{trial}", args.vertices, random_tree(args.vertices, random.Random(trial_seed)), trial_seed
    return run_cases(cases(), args, "graceful_batch_log.csv", "hardest_tree.txt", "failed_tree.txt")


def run_spider_sweep(args: argparse.Namespace) -> int:
    def cases() -> Iterable[tuple[str, int, list[Edge], int | None]]:
        for legs in combinations_with_replacement(range(1, args.spider_sweep + 1), args.spider_legs):
            if args.spider_sweep_from is not None and max(legs) < args.spider_sweep_from:
                continue
            edges = spider_tree(list(legs))
            yield "spider-" + "-".join(map(str, legs)), sum(legs) + 1, edges, args.seed
    return run_cases(cases(), args, "spider_sweep_log.csv", "hardest_spider.txt", "failed_spider.txt")


def run_five_leaf_nonspider_sweep(args: argparse.Namespace) -> int:
    max_length = args.five_leaf_nonspider_sweep
    if max_length <= 0:
        raise ValueError("--five-leaf-nonspider-sweep requires a positive maximum segment length")

    def pairs() -> Iterable[tuple[int, int]]:
        yield from combinations_with_replacement(range(1, max_length + 1), 2)

    def triples() -> Iterable[tuple[int, int, int]]:
        yield from combinations_with_replacement(range(1, max_length + 1), 3)

    def cases() -> Iterable[tuple[str, int, list[Edge], int | None]]:
        for bridge in range(1, max_length + 1):
            for left in pairs():
                for right in triples():
                    edges = five_leaf_nonspider_two_branch(bridge, left, right)
                    name = "fiveleaf2-" + "-".join(map(str, (bridge, *left, *right)))
                    yield name, len(edges) + 1, edges, args.seed

        pair_list = list(pairs())
        for left_bridge in range(1, max_length + 1):
            for right_bridge in range(1, max_length + 1):
                for left in pair_list:
                    for middle_leaf in range(1, max_length + 1):
                        for right in pair_list:
                            if (left, left_bridge) > (right, right_bridge):
                                continue
                            edges = five_leaf_nonspider_three_branch(
                                left_bridge,
                                right_bridge,
                                left,
                                middle_leaf,
                                right,
                            )
                            name = "fiveleaf3-" + "-".join(
                                map(str, (left_bridge, right_bridge, *left, middle_leaf, *right))
                            )
                            yield name, len(edges) + 1, edges, args.seed

    return run_cases(
        cases(),
        args,
        "five_leaf_nonspider_sweep_log.csv",
        "hardest_five_leaf_nonspider.txt",
        "failed_five_leaf_nonspider.txt",
    )


def run_five_leaf_nonspider_by_edges(args: argparse.Namespace) -> int:
    max_edges = args.five_leaf_nonspider_by_edges
    if max_edges < 6:
        raise ValueError("--five-leaf-nonspider-by-edges needs at least 6 edges")
    min_edges = max(6, args.min_edges)
    if min_edges > max_edges:
        raise ValueError("--min-edges cannot exceed --five-leaf-nonspider-by-edges")

    def positive_tuples(parts: int, total: int) -> Iterable[tuple[int, ...]]:
        if parts == 1:
            if total >= 1:
                yield (total,)
            return
        for first in range(1, total - parts + 2):
            for rest in positive_tuples(parts - 1, total - first):
                yield (first, *rest)

    def cases() -> Iterable[tuple[str, int, list[Edge], int | None]]:
        for total_edges in range(min_edges, max_edges + 1):
            for lengths in positive_tuples(6, total_edges):
                bridge = lengths[0]
                left = tuple(sorted(lengths[1:3]))
                right = tuple(sorted(lengths[3:6]))
                if lengths[1:3] != left or lengths[3:6] != right:
                    continue
                edges = five_leaf_nonspider_two_branch(bridge, left, right)
                name = "fiveleaf2e-" + "-".join(map(str, (total_edges, bridge, *left, *right)))
                yield name, len(edges) + 1, edges, args.seed

            for lengths in positive_tuples(7, total_edges):
                left_bridge, right_bridge = lengths[0], lengths[1]
                left = tuple(sorted(lengths[2:4]))
                middle_leaf = lengths[4]
                right = tuple(sorted(lengths[5:7]))
                if lengths[2:4] != left or lengths[5:7] != right:
                    continue
                if (left, left_bridge) > (right, right_bridge):
                    continue
                edges = five_leaf_nonspider_three_branch(
                    left_bridge,
                    right_bridge,
                    left,
                    middle_leaf,
                    right,
                )
                name = "fiveleaf3e-" + "-".join(
                    map(str, (total_edges, left_bridge, right_bridge, *left, middle_leaf, *right))
                )
                yield name, len(edges) + 1, edges, args.seed

    return run_cases(
        cases(),
        args,
        "five_leaf_nonspider_by_edges_log.csv",
        "hardest_five_leaf_nonspider_by_edges.txt",
        "failed_five_leaf_nonspider_by_edges.txt",
    )


def unordered_pair_partition_count(total: int) -> int:
    """Positive partitions of total into two unordered parts."""
    return total // 2 if total >= 2 else 0


def unordered_triple_partition_count(total: int) -> int:
    """Positive partitions of total into three unordered parts."""
    return (total * total + 3) // 12 if total >= 3 else 0


def count_five_leaf_two_branch_exact_edges(total_edges: int) -> int:
    count = 0
    for bridge in range(1, total_edges - 4):
        remaining = total_edges - bridge
        for left_sum in range(2, remaining - 2):
            right_sum = remaining - left_sum
            count += unordered_pair_partition_count(left_sum) * unordered_triple_partition_count(right_sum)
    return count


def count_five_leaf_three_branch_exact_edges(total_edges: int) -> int:
    # A side consists of the branch-to-parent path plus two unordered leaf paths.
    side_counts = [0] * (total_edges + 1)
    for side_edges in range(3, total_edges + 1):
        side_counts[side_edges] = sum(
            unordered_pair_partition_count(pair_sum)
            for pair_sum in range(2, side_edges)
        )

    count = 0
    for middle_leaf in range(1, total_edges - 5):
        side_sum = total_edges - middle_leaf
        for left_edges in range(3, side_sum // 2 + 1):
            right_edges = side_sum - left_edges
            if right_edges < 3:
                continue
            if left_edges < right_edges:
                count += side_counts[left_edges] * side_counts[right_edges]
            else:
                count += side_counts[left_edges] * (side_counts[left_edges] + 1) // 2
    return count


def run_count_five_leaf_nonspider_by_edges(args: argparse.Namespace) -> int:
    max_edges = args.count_five_leaf_nonspider_by_edges
    min_edges = max(6, args.min_edges)
    if min_edges > max_edges:
        raise ValueError("--min-edges cannot exceed --count-five-leaf-nonspider-by-edges")

    cumulative = 0
    print("edges,two_branch,three_branch,total,cumulative")
    for total_edges in range(min_edges, max_edges + 1):
        two = count_five_leaf_two_branch_exact_edges(total_edges)
        three = count_five_leaf_three_branch_exact_edges(total_edges)
        total = two + three
        cumulative += total
        print(f"{total_edges},{two},{three},{total},{cumulative}")
    return 0


def run_lobster_batch(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    def cases() -> Iterable[tuple[str, int, list[Edge], int | None]]:
        for trial in range(1, args.lobster_batch + 1):
            trial_seed = rng.randrange(2**63)
            edges = random_lobster(
                args.base_vertices,
                args.max_stems,
                args.max_leaves,
                random.Random(trial_seed),
                args.direct_base_leaves,
            )
            n = 1 + max(max(u, v) for u, v in edges) if edges else args.base_vertices
            yield f"lobster-{trial}", n, edges, trial_seed
    return run_cases(cases(), args, "lobster_batch_log.csv", "hardest_lobster.txt", "failed_lobster.txt")


def run_replay_unsolved(args: argparse.Namespace) -> int:
    source_path = args.replay_unsolved
    out_path = args.replay_log or "replay_unsolved_log.csv"
    solved = 0
    still_unsolved = 0
    replayed = 0
    skipped = 0
    started = time.time()
    fieldnames = [
        "case",
        "vertices",
        "seed",
        "previous_nodes",
        "strategy",
        "reduction_base",
        "extended_edges",
        "status",
        "solved",
        "nodes",
        "backtracks",
        "elapsed_seconds",
        "edges",
        "labels",
    ]

    with open(source_path, "r", encoding="utf-8", newline="") as src, open(
        out_path, "w", encoding="utf-8", newline=""
    ) as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        for row_no, row in enumerate(reader, 1):
            if row.get("solved") not in {"0", "False", "false", ""}:
                continue
            if row_no < args.start_case:
                skipped += 1
                continue
            if args.max_cases is not None and replayed >= args.max_cases:
                print(f"stopping: max replay cases reached after {replayed} cases")
                break
            if args.total_time_limit is not None and time.time() - started >= args.total_time_limit:
                print(f"stopping: total time limit reached after {replayed} replayed cases")
                break

            edges = parse_edge_string(row["edges"])
            n = int(row["vertices"]) if row.get("vertices") else 1 + max(max(u, v) for u, v in edges)
            if args.max_vertices is not None and n > args.max_vertices:
                skipped += 1
                writer.writerow(
                    {
                        "case": row.get("case", f"row-{row_no}"),
                        "vertices": n,
                        "seed": row.get("seed", ""),
                        "previous_nodes": row.get("nodes", ""),
                        "strategy": "skipped",
                        "reduction_base": "",
                        "extended_edges": 0,
                        "status": "skipped_too_large",
                        "solved": 0,
                        "nodes": 0,
                        "backtracks": 0,
                        "elapsed_seconds": "0.000000",
                        "edges": edge_string(edges),
                        "labels": "",
                    }
                )
                continue

            adj = build_adj(n, edges)
            assert_tree(n, edges, adj)
            seed = int(row["seed"]) if row.get("seed") else args.seed
            labels, stats = solve_tree(adj, args, seed=seed)
            elapsed = time.time() - stats.started_at
            ok = labels is not None and verify_labeling(edges, labels)
            solved += int(ok)
            still_unsolved += int(not ok)
            replayed += 1
            status = "solved" if ok else "timeout_or_failed"
            writer.writerow(
                {
                    "case": row.get("case", f"row-{row_no}"),
                    "vertices": n,
                    "seed": row.get("seed", ""),
                    "previous_nodes": row.get("nodes", ""),
                    "strategy": stats.strategy,
                    "reduction_base": stats.reduction_base,
                    "extended_edges": stats.extended_edges,
                    "status": status,
                    "solved": int(ok),
                    "nodes": stats.nodes,
                    "backtracks": stats.backtracks,
                    "elapsed_seconds": f"{elapsed:.6f}",
                    "edges": edge_string(edges),
                    "labels": label_string(labels),
                }
            )
            dst.flush()
            if args.progress and (replayed == 1 or replayed % args.progress == 0):
                rate = replayed / max(time.time() - started, 1e-9)
                print(
                    f"replay {replayed}: solved={solved}, still_unsolved={still_unsolved}, "
                    f"skipped={skipped}, rate={rate:.3f}/s"
                )

    elapsed_total = time.time() - started
    print(
        f"replay complete: replayed={replayed}, solved={solved}, "
        f"still_unsolved={still_unsolved}, skipped={skipped}, elapsed={elapsed_total:.3f}s"
    )
    print(f"replay log: {out_path}")
    return 0 if still_unsolved == 0 else 2


def run_analyze_log(args: argparse.Namespace) -> int:
    source_path = args.analyze_log
    out_path = args.analysis_log or "tree_analysis.csv"
    rows_out = []
    with open(source_path, "r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        for row in reader:
            edges = parse_edge_string(row["edges"])
            n = int(row["vertices"]) if row.get("vertices") else 1 + max(max(u, v) for u, v in edges)
            features = tree_features(n, edges)
            old_nodes = int(row["nodes"]) if row.get("nodes") else 0
            features.update(
                {
                    "case": row.get("case", ""),
                    "seed": row.get("seed", ""),
                    "solved": row.get("solved", ""),
                    "old_nodes": old_nodes,
                    "old_elapsed_seconds": row.get("elapsed_seconds", ""),
                    "leaf_ratio": f"{features['leaves'] / n:.6f}",
                }
            )
            rows_out.append(features)

    fieldnames = [
        "case",
        "seed",
        "solved",
        "vertices",
        "edges",
        "leaves",
        "leaf_ratio",
        "max_degree",
        "diameter",
        "old_nodes",
        "old_elapsed_seconds",
    ]
    rows_out.sort(key=lambda r: (r["vertices"], -r["old_nodes"]))
    with open(out_path, "w", encoding="utf-8", newline="") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    if rows_out:
        print(f"analyzed {len(rows_out)} trees")
        print(
            "vertices min/median/max: "
            f"{rows_out[0]['vertices']}/"
            f"{sorted(r['vertices'] for r in rows_out)[len(rows_out)//2]}/"
            f"{max(r['vertices'] for r in rows_out)}"
        )
        print("smallest unsolved candidates:")
        for row in rows_out[:10]:
            print(
                f"  {row['case']}: n={row['vertices']}, leaves={row['leaves']}, "
                f"diameter={row['diameter']}, old_nodes={row['old_nodes']}"
            )
    print(f"analysis log: {out_path}")
    return 0


def run_summarize_log(args: argparse.Namespace) -> int:
    path = args.summarize_log
    row_count = 0
    solved_count = 0
    unsolved_count = 0
    malformed_count = 0
    strategies: Counter[str] = Counter()
    reduction_bases: set[str] = set()
    hardest: list[tuple[int, int, dict[str, str]]] = []
    unsolved: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row_index, row in enumerate(csv.DictReader(f)):
            case_name = row.get("case", "")
            if not case_name or "\x00" in case_name:
                malformed_count += 1
                continue
            row_count += 1
            is_solved = row.get("solved") == "1"
            solved_count += int(is_solved)
            unsolved_count += int(not is_solved)
            strategies[row.get("strategy") or "legacy-search"] += 1
            if row.get("reduction_base"):
                reduction_bases.add(row["reduction_base"])
            if not is_solved and len(unsolved) < 50:
                unsolved.append(row)
            try:
                nodes = int(row.get("nodes") or 0)
            except ValueError:
                nodes = 0
            item = (nodes, row_index, row)
            if len(hardest) < 10:
                heapq.heappush(hardest, item)
            elif item[:2] > hardest[0][:2]:
                heapq.heapreplace(hardest, item)
    print(f"log: {path}")
    print(
        f"rows={row_count}, solved={solved_count}, unsolved={unsolved_count}, "
        f"malformed={malformed_count}"
    )
    if strategies:
        print("strategies:")
        for strategy, count in strategies.most_common():
            print(f"  {strategy}: {count}")
    if reduction_bases:
        print(f"unique reduction bases: {len(reduction_bases)}")
    if hardest:
        print("top hardest:")
        for _nodes, _row_index, row in sorted(hardest, reverse=True):
            print(
                f"  {row.get('case', '')}: solved={row.get('solved', '')}, "
                f"vertices={row.get('vertices', '')}, nodes={row.get('nodes', '')}, "
                f"elapsed={row.get('elapsed_seconds', '')}, strategy={row.get('strategy', '')}"
            )
    if unsolved_count:
        print("unsolved cases:")
        for row in unsolved:
            print(
                f"  {row.get('case', '')}: vertices={row.get('vertices', '')}, "
                f"nodes={row.get('nodes', '')}, elapsed={row.get('elapsed_seconds', '')}"
            )
        if unsolved_count > len(unsolved):
            print(f"  ... {unsolved_count - len(unsolved)} more unsolved rows")
    return 0 if unsolved_count == 0 else 2


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Search for graceful labelings of trees.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--edges", help="text file with one edge 'u v' per line")
    source.add_argument("--random", type=int, metavar="N", help="generate one random tree on N vertices")
    source.add_argument("--batch", type=int, metavar="TRIALS", help="run many random-tree trials")
    source.add_argument("--spider", type=int, nargs="+", metavar="LEG", help="solve a spider with these leg lengths")
    source.add_argument("--spider-sweep", type=int, metavar="MAX_LEG", help="check all spider leg multisets up to MAX_LEG")
    source.add_argument(
        "--five-leaf-nonspider-sweep",
        type=int,
        metavar="MAX_SEGMENT",
        help="check all non-spider 5-leaf trees with every reduced-edge segment length up to MAX_SEGMENT",
    )
    source.add_argument(
        "--five-leaf-nonspider-by-edges",
        type=int,
        metavar="MAX_EDGES",
        help="check all non-spider 5-leaf trees with at most MAX_EDGES edges",
    )
    source.add_argument(
        "--count-five-leaf-nonspider-by-edges",
        type=int,
        metavar="MAX_EDGES",
        help="count non-spider 5-leaf trees by exact edge count without running search",
    )
    source.add_argument("--lobster-batch", type=int, metavar="TRIALS", help="run many random lobster-tree trials")
    source.add_argument("--replay-unsolved", help="CSV log to replay rows with solved=0")
    source.add_argument("--analyze-log", help="CSV log to analyze tree structure features")
    source.add_argument("--summarize-log", help="CSV log to summarize solved/timeouts and hardest cases")
    source.add_argument(
        "--import-extension-cache",
        nargs="+",
        metavar="CSV",
        help="import recoverable pendant-extension certificates from CSV logs",
    )
    parser.add_argument("--vertices", type=int, help="vertices per tree in --batch mode")
    parser.add_argument("--spider-legs", type=int, help="number of legs for --spider-sweep")
    parser.add_argument("--spider-sweep-from", type=int, help="only include spider-sweep cases whose maximum leg is at least this value")
    parser.add_argument("--spider-order", choices=["long", "short", "balanced", "random"], default="long", help="leg ordering for --method spider")
    parser.add_argument("--spider-label-order", choices=["extreme", "low", "high", "random"], default="extreme", help="label ordering for --method spider")
    parser.add_argument("--base-vertices", type=int, default=8, help="base path vertices for --lobster-batch")
    parser.add_argument("--max-stems", type=int, default=3, help="max distance-1 stems attached to each lobster base vertex")
    parser.add_argument("--max-leaves", type=int, default=3, help="max leaves attached to each lobster stem")
    parser.add_argument("--direct-base-leaves", type=int, default=1, help="max direct leaves attached to each lobster base vertex")
    parser.add_argument("--seed", type=int, help="random seed")
    parser.add_argument("--time-limit", type=float, default=None, help="seconds before giving up")
    parser.add_argument("--method", choices=["exact", "spider", "branch", "compressed", "diff", "heuristic", "hybrid"], default="exact", help="search method")
    parser.add_argument("--no-constructive-fastpath", action="store_true", help="disable direct caterpillar labeling before search")
    parser.add_argument("--extension-fastpath-nodes", type=int, default=2_000, help="node budget for the pendant-extension base search")
    parser.add_argument("--extension-cache-size", type=int, default=100_000, help="maximum rooted base certificates kept in memory")
    parser.add_argument(
        "--extension-cache-db",
        default="results/pendant_extension_cache.sqlite3",
        help="SQLite database for persistent rooted base certificates (use empty string to disable)",
    )
    parser.add_argument("--diff-candidates", type=int, help="limit candidate placements per edge difference")
    parser.add_argument("--heuristic-steps", type=int, default=1_000_000, help="swap attempts per heuristic restart")
    parser.add_argument("--heuristic-restarts", type=int, default=50, help="heuristic random restarts")
    parser.add_argument("--total-time-limit", type=float, default=None, help="total seconds for --batch mode")
    parser.add_argument("--max-vertices", type=int, help="skip generated batch cases above this many vertices")
    parser.add_argument("--min-edges", type=int, default=6, help="first edge count for --five-leaf-nonspider-by-edges")
    parser.add_argument("--log", help="CSV path for --batch results")
    parser.add_argument("--save-hardest", help="edge-list path for the hardest tree seen in --batch")
    parser.add_argument("--save-failed", help="edge-list path for the latest failed/timeout tree")
    parser.add_argument(
        "--skip-solved-from",
        action="append",
        help="CSV log whose solved case names should be skipped; may be repeated",
    )
    parser.add_argument("--replay-log", help="CSV path for --replay-unsolved results")
    parser.add_argument("--analysis-log", help="CSV path for --analyze-log results")
    parser.add_argument("--start-case", type=int, default=1, help="first CSV data row to consider in --replay-unsolved")
    parser.add_argument("--max-cases", type=int, help="maximum unsolved cases to replay")
    parser.add_argument("--progress", type=int, default=10, help="print progress every N batch trials")
    parser.add_argument("--show-edges", action="store_true", help="print generated/normalized edges")
    args = parser.parse_args(argv)

    try:
        if args.batch is not None:
            if args.vertices is None:
                raise ValueError("--batch requires --vertices N")
            return run_batch(args)
        if args.spider_sweep is not None:
            if args.spider_legs is None:
                raise ValueError("--spider-sweep requires --spider-legs K")
            return run_spider_sweep(args)
        if args.five_leaf_nonspider_sweep is not None:
            return run_five_leaf_nonspider_sweep(args)
        if args.five_leaf_nonspider_by_edges is not None:
            return run_five_leaf_nonspider_by_edges(args)
        if args.count_five_leaf_nonspider_by_edges is not None:
            return run_count_five_leaf_nonspider_by_edges(args)
        if args.lobster_batch is not None:
            return run_lobster_batch(args)
        if args.replay_unsolved is not None:
            return run_replay_unsolved(args)
        if args.analyze_log is not None:
            return run_analyze_log(args)
        if args.summarize_log is not None:
            return run_summarize_log(args)
        if args.import_extension_cache is not None:
            if not args.extension_cache_db:
                raise ValueError("--import-extension-cache requires --extension-cache-db")
            return import_pendant_extension_cache_logs(args.import_extension_cache, args.extension_cache_db)

        original: list[int] | None = None
        if args.edges:
            raw_edges = read_edges(args.edges)
            edges, original = normalize_edges(raw_edges)
            n = len(original)
        elif args.spider:
            edges = spider_tree(args.spider)
            n = sum(args.spider) + 1
        else:
            n = args.random
            edges = random_tree(n, random.Random(args.seed))

        adj = build_adj(n, edges)
        assert_tree(n, edges, adj)
        if args.show_edges:
            print("edges:")
            for u, v in edges:
                print(f"  {u} {v}")

        labels, stats = solve_tree(adj, args, seed=args.seed)
        elapsed = time.time() - stats.started_at
        if labels is None:
            print(f"no labeling found before limit; searched {stats.nodes} nodes in {elapsed:.3f}s")
            return 2
        if not verify_labeling(edges, labels):
            print("internal error: produced labeling failed verification", file=sys.stderr)
            return 3
        print_solution(edges, labels, original)
        print(f"strategy: {stats.strategy}")
        print(f"searched {stats.nodes} nodes, {stats.backtracks} backtracks, {elapsed:.3f}s")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
