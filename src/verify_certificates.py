#!/usr/bin/env python3
"""
Verify labeling certificates written by the graceful and antimagic search tools.

The verifier performs no search. It checks only the graph, the emitted labels,
and the defining labeling condition. This makes CSV logs independently
checkable as certificate files.
"""

from __future__ import annotations

import argparse
import csv
import sys

from graceful_tree import Edge, assert_tree, build_adj, parse_edge_string, verify_labeling
from antimagic_tree import parse_edge_labels, verify_antimagic


def parse_vertex_labels(text: str) -> list[int]:
    return [int(x) for x in text.split()] if text.strip() else []


def verify_graceful_row(row: dict[str, str]) -> tuple[bool, str]:
    case = row.get("case", "")
    if row.get("solved") != "1":
        return True, "skipped unsolved row"
    edges = parse_edge_string(row.get("edges", ""))
    labels = parse_vertex_labels(row.get("labels", ""))
    n = int(row.get("vertices") or len(labels))
    if len(labels) != n:
        return False, f"{case}: expected {n} vertex labels, got {len(labels)}"
    assert_tree(n, edges, build_adj(n, edges))
    if not verify_labeling(edges, labels):
        return False, f"{case}: graceful certificate failed"
    return True, "ok"


def verify_antimagic_row(row: dict[str, str]) -> tuple[bool, str]:
    case = row.get("case", "")
    if row.get("solved") != "1":
        return True, "skipped unsolved row"
    edges = parse_edge_string(row.get("edges", ""))
    labels = parse_edge_labels(row.get("edge_labels", ""))
    n = int(row.get("vertices") or (1 + max(max(u, v) for u, v in edges)))
    if len(labels) != len(edges):
        return False, f"{case}: expected {len(edges)} edge labels, got {len(labels)}"
    assert_tree(n, edges, build_adj(n, edges))
    if not verify_antimagic(n, edges, labels):
        return False, f"{case}: antimagic certificate failed"
    return True, "ok"


def verify_log(path: str, kind: str, max_rows: int | None = None) -> int:
    checked = 0
    skipped = 0
    bad = 0
    verifier = verify_graceful_row if kind == "graceful" else verify_antimagic_row
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if max_rows is not None and checked + skipped >= max_rows:
                break
            case_name = row.get("case", "")
            if not case_name or "\x00" in case_name:
                skipped += 1
                continue
            try:
                ok, message = verifier(row)
            except Exception as exc:  # keep reporting on malformed certificate rows
                ok, message = False, f"{case_name}: {exc}"
            if row.get("solved") == "1":
                checked += 1
            else:
                skipped += 1
            if not ok:
                bad += 1
                print(message, file=sys.stderr)
                if bad >= 20:
                    print("stopping after 20 bad rows", file=sys.stderr)
                    break
    print(f"log={path}")
    print(f"kind={kind}, checked_solved={checked}, skipped={skipped}, bad={bad}")
    return 0 if bad == 0 else 2


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify graceful or antimagic CSV certificates.")
    parser.add_argument("--kind", choices=["graceful", "antimagic"], required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--max-rows", type=int, help="verify only the first N rows")
    args = parser.parse_args(argv)
    return verify_log(args.log, args.kind, args.max_rows)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
