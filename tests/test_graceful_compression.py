import random
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graceful_tree import (  # noqa: E402
    _PENDANT_EXTENSION_CACHE,
    build_adj,
    close_pendant_extension_cache,
    five_leaf_nonspider_two_branch,
    count_five_leaf_three_branch_exact_edges,
    count_five_leaf_two_branch_exact_edges,
    solve_graceful_caterpillar,
    solve_graceful_pendant_extension,
    verify_labeling,
)


def caterpillar_edges(spine_vertices: int, leaf_counts: list[int]):
    edges = [(u, u + 1) for u in range(spine_vertices - 1)]
    next_vertex = spine_vertices
    for spine_vertex, count in enumerate(leaf_counts):
        for _ in range(count):
            edges.append((spine_vertex, next_vertex))
            next_vertex += 1
    return edges, next_vertex


class GracefulCompressionTests(unittest.TestCase):
    def setUp(self):
        close_pendant_extension_cache()
        _PENDANT_EXTENSION_CACHE.clear()

    def test_caterpillar_alpha_labeling(self):
        rng = random.Random(20260809)
        for spine_vertices in range(1, 10):
            for _ in range(20):
                leaf_counts = [rng.randrange(0, 5) for _ in range(spine_vertices)]
                if spine_vertices > 1:
                    leaf_counts[0] = max(1, leaf_counts[0])
                    leaf_counts[-1] = max(1, leaf_counts[-1])
                edges, n = caterpillar_edges(spine_vertices, leaf_counts)
                labels, stats = solve_graceful_caterpillar(build_adj(n, edges))
                self.assertEqual(stats.strategy, "caterpillar")
                self.assertIsNotNone(labels)
                self.assertTrue(verify_labeling(edges, labels))

    def test_non_caterpillar_is_rejected_by_direct_constructor(self):
        edges = []
        next_vertex = 1
        for _ in range(3):
            edges.extend([(0, next_vertex), (next_vertex, next_vertex + 1)])
            next_vertex += 2
        labels, _stats = solve_graceful_caterpillar(build_adj(next_vertex, edges))
        self.assertIsNone(labels)

    def test_pendant_extension_and_cache(self):
        edges = five_leaf_nonspider_two_branch(2, (1, 1), (9, 11, 11))
        adj = build_adj(len(edges) + 1, edges)

        labels, stats = solve_graceful_pendant_extension(adj, max_nodes=2_000)
        self.assertIsNotNone(labels)
        self.assertEqual(stats.strategy, "pendant-extension")
        self.assertTrue(verify_labeling(edges, labels))

        cached_labels, cached_stats = solve_graceful_pendant_extension(adj, max_nodes=2_000)
        self.assertIsNotNone(cached_labels)
        self.assertEqual(cached_stats.strategy, "pendant-extension-cache")
        self.assertEqual(cached_stats.nodes, 0)
        self.assertTrue(verify_labeling(edges, cached_labels))

    def test_edge_count_formulas(self):
        expected_totals = {
            6: (1, 0),
            7: (3, 1),
            10: (33, 24),
            46: (127_092, 1_166_616),
            47: (141_904, 1_337_578),
        }
        for edges, (two_branch, three_branch) in expected_totals.items():
            self.assertEqual(count_five_leaf_two_branch_exact_edges(edges), two_branch)
            self.assertEqual(count_five_leaf_three_branch_exact_edges(edges), three_branch)

    def test_pendant_extension_persistent_cache(self):
        edges = five_leaf_nonspider_two_branch(2, (1, 1), (9, 11, 11))
        adj = build_adj(len(edges) + 1, edges)
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_db = str(Path(temp_dir) / "pendant.sqlite3")
            labels, first_stats = solve_graceful_pendant_extension(
                adj, max_nodes=2_000, cache_db=cache_db
            )
            self.assertIsNotNone(labels)
            self.assertEqual(first_stats.strategy, "pendant-extension")
            close_pendant_extension_cache()
            _PENDANT_EXTENSION_CACHE.clear()

            labels, second_stats = solve_graceful_pendant_extension(
                adj, max_nodes=1, cache_db=cache_db
            )
            self.assertIsNotNone(labels)
            self.assertEqual(second_stats.strategy, "pendant-extension-disk-cache")
            self.assertEqual(second_stats.nodes, 0)
            self.assertTrue(verify_labeling(edges, labels))
            close_pendant_extension_cache()


if __name__ == "__main__":
    unittest.main()
