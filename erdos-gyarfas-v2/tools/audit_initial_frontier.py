#!/usr/bin/env python3
"""Independently reconstruct a saved initial frontier, not its full subtrees."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

from audit_checkpoint import independently_expand, parse_manifest, require


def replay_manifest(manifest):
    raw = manifest.read_bytes()
    config, base, tasks = parse_manifest(raw)
    k = config["k"]
    rows = [0] * k
    for v in range(k - 1):
        rows[v] |= 1 << (v + 1)
        rows[v + 1] |= 1 << v
    frontier = Counter({(k - 2, tuple(rows)): 1})
    totals = Counter()
    max_n = 0
    digest = 0
    start = time.monotonic()
    for level in range(config["depth"]):
        children = Counter()
        counts = Counter()
        local_digest = 0
        local_max = 0
        overflow = False
        for index, (task, multiplicity) in enumerate(frontier.items(), 1):
            expanded, measured, hashed = independently_expand(task, k, config["audit"])
            for child, number in expanded.items():
                children[child] += number * multiplicity
            counts["states"] += multiplicity
            for name, number in measured.items():
                counts[name] += number * multiplicity
            local_digest += hashed * multiplicity
            local_max = max(local_max, len(task[1]))
            if sum(children.values()) > config["limit"]:
                overflow = True
                break
            if index % 100 == 0:
                print(f"initial replay: depth={level + 1} parents={index}/{len(frontier)}", file=sys.stderr, flush=True)
        if overflow:
            break
        totals.update(counts)
        digest = (digest + local_digest) & ((1 << 64) - 1)
        max_n = max(max_n, local_max)
        frontier = children
        if not frontier:
            break
    require(frontier == Counter(tasks), "independent initial frontier mismatch")
    for name in ("states", "subsets", "accepted", "path_prunes"):
        require(totals[name] == base[name], "initial split count mismatch: " + name)
    require(max_n == base["max_n"], "initial maximum order mismatch")
    require(digest == base["audit_digest"], "initial graph digest mismatch")
    return {"passed": True, "configuration": config, "tasks": len(tasks),
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "initial_frontier_independently_replayed": True,
            "full_search_independently_replayed": False,
            "seconds": time.monotonic() - start,
            "checked_counts": {name: totals[name] for name in ("states", "subsets", "accepted", "path_prunes")}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = replay_manifest(args.manifest)
    text = json.dumps(result, indent=2) + "\n"
    if args.report:
        with args.report.open("x", encoding="utf-8") as out:
            out.write(text)
    print(text)
