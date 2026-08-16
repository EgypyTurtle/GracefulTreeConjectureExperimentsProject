import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hard_pattern_experiment import hard_pattern_cases  # noqa: E402


class HardPatternExperimentTests(unittest.TestCase):
    def test_case_count_and_parameters(self):
        cases = list(hard_pattern_cases(47, 47))
        self.assertEqual(len(cases), 154)
        for _name, edges, a, b, c, edge_list in cases:
            self.assertEqual(edges, 2 + 1 + 1 + a + b + c)
            self.assertLessEqual(a, b)
            self.assertLessEqual(b, c)
            self.assertEqual(len(edge_list), edges)

    def test_case_count_47_to_65(self):
        self.assertEqual(len(list(hard_pattern_cases(47, 65))), 4327)


if __name__ == "__main__":
    unittest.main()
