import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hard_boundary_experiment import BOUNDARY_CASES, cases  # noqa: E402


class HardBoundaryExperimentTests(unittest.TestCase):
    def test_boundary_case_list(self):
        generated = list(cases())
        self.assertEqual(len(generated), 6)
        self.assertEqual(
            [(row[1], row[2], row[3], row[4]) for row in generated],
            list(BOUNDARY_CASES),
        )
        for _name, edges, a, b, c, edge_list in generated:
            self.assertEqual(edges, 4 + a + b + c)
            self.assertEqual(len(edge_list), edges)


if __name__ == "__main__":
    unittest.main()
