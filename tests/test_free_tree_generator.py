import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from free_tree_generator import (  # noqa: E402
    free_tree_code,
    free_tree_layers,
    parse_shape,
)


class FreeTreeGeneratorTests(unittest.TestCase):
    def test_free_tree_counts(self):
        layers = free_tree_layers(12)
        expected = [1, 1, 1, 2, 3, 6, 11, 23, 47, 106, 235, 551]
        self.assertEqual([len(layers[n]) for n in range(1, 13)], expected)

    def test_center_canonicalization_is_root_independent(self):
        path_shape = parse_shape("(((())))")
        self.assertEqual(free_tree_code(path_shape), "((())())")


if __name__ == "__main__":
    unittest.main()
