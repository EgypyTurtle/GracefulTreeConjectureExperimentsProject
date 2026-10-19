#!/usr/bin/env python3
"""Read-only checkpoint integrity and refinement-lineage audit.

This checks archived records, not the mathematical correctness of billions of
DFS steps. Optional refinement replay independently enumerates only the split
layers, using Python set adjacency rather than the C++ search implementation.
"""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import itertools
import json
from pathlib import Path
import re
import sys
import time

NAMES = ("states", "subsets", "accepted", "path_prunes", "pair_tests",
         "conflict_prunes", "audit_digest", "max_n")
MASK64 = (1 << 64) - 1


class AuditError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise AuditError(message)


def fnv(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & MASK64
    return value


def popcount(value):
    return bin(value).count("1")


def stats(values):
    require(len(values) == 8 and all(v >= 0 for v in values), "invalid stats record")
    require(values[1] == values[2] + values[3], "subset/accepted/path-prune mismatch")
    return dict(zip(NAMES, values))


def merge(a, b):
    result = {key: a[key] + b[key] for key in NAMES}
    result["audit_digest"] &= MASK64
    result["max_n"] = max(a["max_n"], b["max_n"])
    return result


def parse_manifest(data):
    lines = iter(data.decode("ascii").splitlines())
    header = next(lines).split()
    require(len(header) == 5 and header[0] == "eg-v2.1", "unsupported task format")
    k, depth, limit, audit = map(int, header[1:])
    require(k >= 3 and depth >= 0 and limit > 0 and audit in (0, 1), "invalid task configuration")
    base = stats(list(map(int, next(lines).split())))
    count = int(next(lines))
    require(0 <= count <= limit, "invalid task count")
    tasks = []
    for _ in range(count):
        n, anchor = map(int, next(lines).split())
        require(k <= n <= k + depth and 0 <= anchor < n - 1, "invalid task graph header")
        rows = []
        for _ in range(n):
            words = list(map(int, next(lines).split()))
            require(len(words) == (n + 63) // 64 and all(0 <= w <= MASK64 for w in words), "invalid adjacency words")
            rows.append(sum(word << (64 * j) for j, word in enumerate(words)))
        for u, row in enumerate(rows):
            require(row >> n == 0 and not (row >> u) & 1, "invalid adjacency bits/self-loop")
            for v in range(u):
                require(((row >> v) & 1) == ((rows[v] >> u) & 1), "asymmetric adjacency")
        require(rows[-1] == 1 << anchor, "pending vertex is not an anchored leaf")
        tasks.append((anchor, tuple(rows)))
    require(not any(line.strip() for line in lines), "trailing manifest data")
    require(base["accepted"] + 1 - base["states"] == count, "base frontier conservation failed")
    return {"k": k, "depth": depth, "limit": limit, "audit": audit}, base, tasks


def contained(path, root):
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise AuditError("checkpoint path escapes project root")
    return resolved


def read_one(path, root):
    path = contained(path, root)
    raw = (path / "tasks.txt").read_bytes()
    config, base, tasks = parse_manifest(raw)
    identity = fnv(raw)
    aggregate = dict(base)
    complete = set()
    require(not (path / "candidate.txt").exists(), "candidate file present; cannot certify an empty run")
    done_path = path / "done"
    require(done_path.is_dir(), "missing done directory")
    for p in done_path.iterdir():
        if p.suffix == ".tmp":
            continue
        require(p.name.endswith(".txt") and p.stem.isdigit(), "unexpected completion file")
        index = int(p.stem)
        require(0 <= index < len(tasks) and index not in complete, "invalid/duplicate completed task id")
        values = list(map(int, p.read_text(encoding="ascii").split()))
        require(len(values) == 10 and values[:2] == [identity, index], "completion fingerprint/id mismatch")
        local = stats(values[2:])
        require(local["states"] == local["accepted"] + 1, "completed subtree conservation failed")
        aggregate = merge(aggregate, local)
        complete.add(index)
    pending = [task for i, task in enumerate(tasks) if i not in complete]
    require(aggregate["accepted"] + 1 - aggregate["states"] == len(pending), "remaining frontier conservation failed")
    summary = None
    if len(complete) == len(tasks):
        summary_file = path / "summary.txt"
        require(summary_file.is_file(), "complete tasks without final summary")
        text = summary_file.read_text(encoding="ascii").strip()
        require(text.startswith("complete:"), "final summary is not complete")
        summary = dict(re.findall(r"([a-z_]+)=([^\s]+)", text))
        require(summary.get("version") == "eg-v2.1" and int(summary["k"]) == config["k"], "summary configuration mismatch")
        require(summary["done"] == f"{len(tasks)}/{len(tasks)}", "summary completion count mismatch")
        for key in NAMES:
            require(int(summary[key]) == aggregate[key], "summary mismatch: " + key)
    return {"path": path, "config": config, "base": base, "tasks": tasks,
            "pending": pending, "done": len(complete), "aggregate": aggregate,
            "summary": summary, "fingerprint": identity, "sha256": hashlib.sha256(raw).hexdigest()}


def source_for(metadata, root):
    declared = Path(metadata["source"])
    candidates = []
    if declared.exists():
        try:
            candidates.append(contained(declared, root))
        except AuditError:
            pass
    # Relocated archives need not reproduce /home/dell. Match the exact source
    # manifest fingerprint, then require a unique match within checkpoints/.
    for p in (root / "checkpoints").glob("*/tasks.txt"):
        if fnv(p.read_bytes()) == int(metadata["source_manifest_fingerprint"]):
            candidates.append(p.parent.resolve())
    matches = set(p for p in candidates if fnv((p / "tasks.txt").read_bytes()) == int(metadata["source_manifest_fingerprint"]))
    require(len(matches) == 1, "missing or ambiguous refinement source")
    return matches.pop()


def classify(parent, child, metadata):
    old = Counter(parent["pending"])
    new = Counter(child["tasks"])
    retained = old & new
    expanded = old - retained
    new -= retained
    groups = defaultdict(Counter)
    for (anchor, rows), multiplicity in new.items():
        n = len(rows) - 1
        core = [row & ((1 << n) - 1) for row in rows[:n]]
        expected_anchor = next((v for v in reversed(range(n)) if popcount(core[v]) < 3), -1)
        require(anchor == expected_anchor, "child task anchor differs from finalized parent rule")
        # Restore the pending leaf state of the old task from its immutable core.
        old_core = [row & ((1 << (n - 1)) - 1) for row in core[:n - 1]]
        previous_anchor = next((v for v in reversed(range(n - 1)) if popcount(old_core[v]) < 3), -1)
        require(previous_anchor >= 0 and (core[-1] >> previous_anchor) & 1, "missing forced parent edge")
        restored = list(old_core) + [1 << previous_anchor]
        restored[previous_anchor] |= 1 << (n - 1)
        parent_key = (previous_anchor, tuple(restored))
        require(parent_key in expanded, "child has no unfinished source parent")
        groups[parent_key][(anchor, rows)] += multiplicity
    require(sum(retained.values()) == int(metadata["retained_parents"]), "retained-parent count mismatch")
    require(sum(expanded.values()) == int(metadata["expanded_parents"]), "expanded-parent count mismatch")
    for key in ("states", "accepted", "subsets", "path_prunes", "pair_tests", "conflict_prunes"):
        require(child["base"][key] >= parent["aggregate"][key], "carried count decreased: " + key)
    require(child["base"]["states"] - parent["aggregate"]["states"] == sum(expanded.values()), "expanded state count mismatch")
    require(child["base"]["accepted"] - parent["aggregate"]["accepted"] == sum(new.values()), "new child count mismatch")
    return expanded, groups


def independently_expand(task, k, audit):
    anchor, rows = task
    n = len(rows)
    adjacency = [{v for v in range(n - 1) if (row >> v) & 1} for row in rows[:-1]]

    @lru_cache(None)
    def incompatible(u, v):
        if adjacency[u] & adjacency[v]:
            return True
        def walk(x, remaining, used):
            if remaining == 0:
                return x == v
            for y in adjacency[x] - used:
                if y == v and remaining != 1:
                    continue
                if walk(y, remaining - 1, used | {y}):
                    return True
            return False
        length = 8
        while length <= n:
            if walk(u, length - 2, {u}):
                return True
            length *= 2
        return False

    def induced(g):
        def walk(path, used):
            if len(path) == k:
                return True
            for u in g[path[-1]] - used:
                if all(u not in g[v] for v in path[:-1]) and walk(path + [u], used | {u}):
                    return True
            return False
        return any(walk([v], {v}) for v in range(n - 1))

    eligible = [v for v in range(n - 1) if v != anchor and not incompatible(min(v, anchor), max(v, anchor))]
    counts = Counter()
    children = Counter()
    digest = 0
    for size in range(len(eligible) + 1):
        for subset in itertools.combinations(eligible, size):
            if any(incompatible(u, v) for u, v in itertools.combinations(subset, 2)):
                continue
            counts["subsets"] += 1
            g = [set(neighbors) for neighbors in adjacency] + [set(subset) | {anchor}]
            for u in g[-1]:
                g[u].add(n - 1)
            if induced(g):
                counts["path_prunes"] += 1
                continue
            counts["accepted"] += 1
            next_anchor = next((v for v in reversed(range(n)) if len(g[v]) < 3), -1)
            require(next_anchor >= 0, "independent split replay found a candidate graph")
            if audit:
                text = str(n) + "\n" + "".join(str(u) + ":" + "".join(" " + str(v) for v in sorted(g[u]) if v > u) + "\n" for u in range(n))
                digest = (digest + fnv(text.encode("ascii"))) & MASK64
            new_rows = [sum(1 << v for v in neighbors) for neighbors in g] + [1 << next_anchor]
            new_rows[next_anchor] |= 1 << n
            children[(next_anchor, tuple(new_rows))] += 1
    return children, counts, digest


def audit_checkpoint(project_root, checkpoint, replay=False):
    root = Path(project_root).resolve()
    records = []
    seen = set()
    def visit(path):
        path = contained(Path(path), root)
        require(path not in seen, "cyclic refinement ancestry")
        seen.add(path)
        node = read_one(path, root)
        relation = path / "refinement.txt"
        replayed = False
        if relation.exists():
            lines = relation.read_text(encoding="utf-8").splitlines()
            metadata = dict(line.split("=", 1) for line in lines)
            parent = visit(source_for(metadata, root))
            require(node["config"]["k"] == parent["config"]["k"] and node["config"]["audit"] == parent["config"]["audit"], "refinement changes k/audit")
            require(node["config"]["depth"] == parent["config"]["depth"] + 1, "refinement depth mismatch")
            require(parent["done"] == int(metadata["source_completed_preserved"]), "source done set differs from preserved count")
            require(len(parent["pending"]) == int(metadata["source_pending"]), "source pending count differs")
            require(len(node["tasks"]) == int(metadata["target_tasks"]), "refined task count differs")
            expanded, groups = classify(parent, node, metadata)
            if replay:
                summed = Counter()
                digest = parent["aggregate"]["audit_digest"]
                for number, (task, multiplicity) in enumerate(expanded.items(), 1):
                    actual, counts, local_digest = independently_expand(task, node["config"]["k"], node["config"]["audit"])
                    expected = Counter({key: value * multiplicity for key, value in actual.items()})
                    require(expected == groups[task], "independent split replay child-set mismatch")
                    for key, value in counts.items():
                        summed[key] += value * multiplicity
                    digest = (digest + local_digest * multiplicity) & MASK64
                    if number % 100 == 0:
                        print(f"replay: parents={number}/{len(expanded)}", file=sys.stderr, flush=True)
                for key in ("subsets", "accepted", "path_prunes"):
                    require(node["base"][key] == parent["aggregate"][key] + summed[key], "split replay count mismatch: " + key)
                if node["config"]["audit"]:
                    require(node["base"]["audit_digest"] == digest, "split replay graph fingerprint mismatch")
                replayed = True
        records.append({"checkpoint": path.relative_to(root).as_posix(), "configuration": node["config"],
                        "tasks": len(node["tasks"]), "done": node["done"], "pending": len(node["pending"]),
                        "manifest_sha256": node["sha256"], "statistics": node["aggregate"],
                        "refinement_present": relation.exists(), "split_layer_independently_replayed": replayed,
                        "summary": node["summary"]})
        return node
    start = time.monotonic()
    final = visit(checkpoint)
    require(final["done"] == len(final["tasks"]), "final checkpoint is incomplete")
    return {"integrity_passed": True, "full_search_independently_replayed": False,
            "meaning": "Record integrity and optional split-layer replay only; not a proof of all DFS exclusions.",
            "seconds": time.monotonic() - start, "checkpoints": records,
            "final_statistics": final["aggregate"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--replay-refinement", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    cp = args.checkpoint if args.checkpoint.is_absolute() else args.project_root / args.checkpoint
    result = audit_checkpoint(args.project_root, cp, args.replay_refinement)
    text = json.dumps(result, indent=2) + "\n"
    if args.report:
        with args.report.open("x", encoding="utf-8") as out:
            out.write(text)
    print(text)


if __name__ == "__main__":
    try:
        main()
    except (AuditError, ValueError, KeyError, StopIteration, OSError) as error:
        print("AUDIT FAILED: " + str(error), file=sys.stderr)
        raise SystemExit(2)
