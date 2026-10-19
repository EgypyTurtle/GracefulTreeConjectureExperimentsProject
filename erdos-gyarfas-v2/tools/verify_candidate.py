#!/usr/bin/env python3
"""Independent adjacency-list witness checker (standard library only)."""
import argparse
from pathlib import Path


def read_graph(path):
    rows = {}
    declared = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            if declared is None and not rows:
                declared = int(line)
                continue
            raise ValueError("unexpected graph input")
        left, right = line.split(":", 1)
        u = int(left)
        if u in rows:
            raise ValueError("duplicate vertex row")
        neighbors = [int(v) for v in right.split()]
        if len(set(neighbors)) != len(neighbors):
            raise ValueError("duplicate neighbor")
        rows[u] = neighbors
    n = declared if declared is not None else len(rows)
    if n <= 0 or set(rows) != set(range(n)):
        raise ValueError("missing/nonconsecutive vertex rows")
    adj = [set() for _ in range(n)]
    for u, neighbors in rows.items():
        for v in neighbors:
            if not 0 <= v < n or v == u:
                raise ValueError("invalid edge")
            adj[u].add(v)
            adj[v].add(u)
    return adj


def cycle_witness(adj, length):
    def dfs(start, path, used):
        if len(path) == length:
            return path + [start] if start in adj[path[-1]] else None
        for v in sorted(adj[path[-1]]):
            if v > start and v not in used:
                result = dfs(start, path + [v], used | {v})
                if result:
                    return result
        return None
    for s in range(len(adj)):
        result = dfs(s, [s], {s})
        if result:
            return result
    return None


def induced_witness(adj, k):
    def dfs(path):
        if len(path) == k:
            return path
        for v in sorted(adj[path[-1]]):
            if v not in path and all(v not in adj[u] for u in path[:-1]):
                result = dfs(path + [v])
                if result:
                    return result
        return None
    for s in range(len(adj)):
        result = dfs([s])
        if result:
            return result
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", type=Path)
    parser.add_argument("--pk", type=int)
    args = parser.parse_args()
    adj = read_graph(args.graph)
    bad = [v for v in range(len(adj)) if len(adj[v]) < 3]
    print(f"vertices={len(adj)} edges={sum(map(len, adj)) // 2} minimum_degree={min(map(len, adj))}")
    if bad:
        print(f"FAIL: degree below 3 at vertices {bad}")
        return 1
    length = 4
    while length <= len(adj):
        witness = cycle_witness(adj, length)
        if witness:
            print(f"FAIL: C{length} witness={witness}")
            return 1
        print(f"checked: no C{length}", flush=True)
        length *= 2
    if args.pk:
        if args.pk < 2:
            raise ValueError("--pk must be at least 2")
        witness = induced_witness(adj, args.pk)
        if witness:
            print(f"FAIL: induced P{args.pk} witness={witness}")
            return 1
    print("PASS: counterexample conditions verified by independent checker")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
