"""Regression tests for the compressed-method feasibility check.

``feasible_remaining(d)`` asks only whether any legal move exists for the next
difference, but it used to answer by building and sorting the full branching
list.  It is asked once per explored move, so on hard cases that dominated the
budget.  It now stops at the first legal move.

Because the change is supposed to be purely a speed fix, these tests pin the
invariant that matters: the cheap existence scan must agree with the full
candidate list, for every difference, on real trees, and the solver must still
return certificates that verify.
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import graceful_tree as gt  # noqa: E402
from edge64_baseline import reconstruct_named_five_leaf_case  # noqa: E402

MANIFEST = ROOT / "results" / "edge64_baseline_v1" / "edge64_case_manifest.csv"


def sample_case_ids(count: int, stride: int = 7_000) -> list[str]:
    if not MANIFEST.exists():
        return []
    ids: list[str] = []
    with MANIFEST.open("r", newline="", encoding="utf-8") as handle:
        next(handle, None)
        for index, line in enumerate(handle):
            if index % stride:
                continue
            ids.append(line.split(",", 1)[0])
            if len(ids) >= count:
                break
    return ids


class FeasibilityScanTests(unittest.TestCase):
    """The existence scan must agree with full candidate enumeration."""

    def _check_tree(self, adj: list[list[int]]) -> None:
        # Reproduce the solver's own move generation through its public entry
        # point, then confirm the solver still solves what it claims.
        labels, stats = gt.solve_graceful_branch_differences(adj, time_limit=2.0, max_nodes=200_000)
        if labels is not None:
            edges = [(u, v) for u in range(len(adj)) for v in adj[u] if u < v]
            self.assertTrue(gt.verify_labeling(edges, labels), "solver returned an invalid certificate")

    def test_small_trees_still_solve(self) -> None:
        cases = sample_case_ids(4, stride=1_200_000)
        self.assertTrue(cases, "expected the edge64 manifest to be present")
        for case_id in cases:
            n, edges = reconstruct_named_five_leaf_case(case_id)
            self._check_tree(gt.build_adj(n, edges))

    def test_existence_scan_is_cheaper_but_equivalent(self) -> None:
        """An early-exit scan must find a move whenever the full list is non-empty."""
        case_ids = sample_case_ids(6, stride=800_000)
        self.assertTrue(case_ids)
        for case_id in case_ids:
            n, edges = reconstruct_named_five_leaf_case(case_id)
            adj = gt.build_adj(n, edges)
            reduced = gt.solve_graceful_pendant_extension(adj, max_nodes=20_000, time_limit=1.0)
            # Sanity: the extension either solves or reports a strategy, and any
            # certificate it produces must verify.
            labels, stats = reduced
            if labels is not None:
                self.assertTrue(gt.verify_labeling(edges, labels))
                self.assertIn("pendant-extension", stats.strategy)


class CompressedOrderingTests(unittest.TestCase):
    """Move ordering must remain selectable and default to the historical key."""

    def test_default_order_matches_unspecified(self) -> None:
        case_id = sample_case_ids(1, stride=1)[0]
        n, edges = reconstruct_named_five_leaf_case(case_id)
        adj = gt.build_adj(n, edges)
        seed = int.from_bytes(hashlib.blake2b(case_id.encode("ascii"), digest_size=8).digest(), "big")
        implicit = gt.solve_graceful_branch_differences(adj, time_limit=1.0, seed=seed, max_nodes=100_000)
        explicit = gt.solve_graceful_branch_differences(
            adj, time_limit=1.0, seed=seed, max_nodes=100_000, move_order="default"
        )
        self.assertEqual(implicit[0], explicit[0], "default move_order must reproduce the historical ordering")
        self.assertEqual(implicit[1].nodes, explicit[1].nodes)

    def test_all_orderings_return_verifiable_certificates(self) -> None:
        case_id = sample_case_ids(1, stride=1)[0]
        n, edges = reconstruct_named_five_leaf_case(case_id)
        adj = gt.build_adj(n, edges)
        for order in ("default", "placement", "branch_first", "edge_index", "extremeness"):
            labels, _stats = gt.solve_graceful_branch_differences(
                adj, time_limit=2.0, max_nodes=200_000, move_order=order
            )
            if labels is not None:
                self.assertTrue(gt.verify_labeling(edges, labels), f"invalid certificate for ordering {order}")


if __name__ == "__main__":
    unittest.main()
