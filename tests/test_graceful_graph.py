import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graceful_graph import (  # noqa: E402
    normalize_edges,
    solve_graceful_graph,
    verify_graceful_labeling,
)


class GenericGracefulGraphTests(unittest.TestCase):
    def test_triangle_is_solved(self):
        n, edges, _original = normalize_edges([(10, 20), (20, 30), (30, 10)])
        labels, stats = solve_graceful_graph(n, edges, time_limit=5)
        self.assertIsNotNone(labels)
        self.assertEqual(stats.strategy, "generic-difference")
        self.assertTrue(verify_graceful_labeling(n, edges, labels))

    def test_complete_bipartite_k33_is_solved(self):
        edges = [(u, 3 + v) for u in range(3) for v in range(3)]
        labels, _stats = solve_graceful_graph(6, edges, time_limit=5)
        self.assertIsNotNone(labels)
        self.assertTrue(verify_graceful_labeling(6, edges, labels))

    def test_disconnected_matching_fails_label_pool_precheck(self):
        edges = [(0, 1), (2, 3)]
        labels, stats = solve_graceful_graph(4, edges)
        self.assertIsNone(labels)
        self.assertEqual(stats.nodes, 0)

    def test_isolated_vertices_are_retained_when_explicit(self):
        n, edges, original = normalize_edges([(0, 1)], vertices=3)
        self.assertEqual((n, edges, original), (3, [(0, 1)], [0, 1, 2]))
        labels, _stats = solve_graceful_graph(n, edges)
        self.assertIsNone(labels)

    def test_noncontiguous_ids_are_compacted(self):
        n, edges, original = normalize_edges([(7, 11)])
        self.assertEqual((n, edges, original), (2, [(0, 1)], [7, 11]))
        labels, _stats = solve_graceful_graph(n, edges)
        self.assertEqual(labels, [0, 1])
        self.assertTrue(verify_graceful_labeling(n, edges, labels))


if __name__ == "__main__":
    unittest.main()

