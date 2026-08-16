import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rooted_extension_experiment import (  # noqa: E402
    attach_with_gap,
    rooted_shape_layers,
    shape_edges,
    shape_size,
)
from graceful_tree import verify_labeling  # noqa: E402


class RootedExtensionExperimentTests(unittest.TestCase):
    def test_rooted_tree_counts(self):
        layers = rooted_shape_layers(10)
        expected = [1, 1, 2, 4, 9, 20, 48, 115, 286, 719]
        self.assertEqual([len(layers[n]) for n in range(1, 11)], expected)

    def test_gap_extension_produces_verified_child(self):
        shape = ((),)
        labels = (0, 1)
        child_shape, child_labels = attach_with_gap(shape, labels, target=0, gap=2)
        self.assertEqual(shape_size(child_shape), 3)
        self.assertTrue(verify_labeling(shape_edges(child_shape), list(child_labels)))


if __name__ == "__main__":
    unittest.main()
