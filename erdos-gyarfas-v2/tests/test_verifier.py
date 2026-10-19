import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify", ROOT / "tools" / "verify_candidate.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class VerifierTests(unittest.TestCase):
    def test_cycle_lengths(self):
        for n in (4, 8, 16, 32, 64):
            adj = [{(u - 1) % n, (u + 1) % n} for u in range(n)]
            witness = verify.cycle_witness(adj, n)
            self.assertEqual(len(witness), n + 1)
            if n >= 8:
                self.assertIsNone(verify.cycle_witness(adj, 4))

    def test_induced_chords(self):
        path = [{1}, {0, 2}, {1, 3}, {2}]
        self.assertIsNotNone(verify.induced_witness(path, 4))
        path[0].add(3)
        path[3].add(0)
        self.assertIsNone(verify.induced_witness(path, 4))

    def test_input(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "candidate.txt"
            p.write_text("4\n0: 1 2 3\n1: 2 3\n2: 3\n3:\n", encoding="utf-8")
            adj = verify.read_graph(p)
            self.assertEqual([len(a) for a in adj], [3] * 4)
            p.write_text("4\n0: 1\n1: 2\n2: 3\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify.read_graph(p)


if __name__ == "__main__":
    unittest.main()
