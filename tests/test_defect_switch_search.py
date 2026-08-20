import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from defect_switch_search import (  # noqa: E402
    ROOTS,
    SEED_WORDS,
    UNUSED_DIFFERENCES,
    UNUSED_LABELS,
    all_states,
    main,
    neighboring_states,
    solve_tail_packing,
    verify_tail_certificate,
    words_to_paths,
)


class DefectSwitchSearchTests(unittest.TestCase):
    def test_built_in_seeds_are_valid(self):
        for state, words in SEED_WORDS.items():
            paths = words_to_paths(ROOTS, words)
            ok, reason = verify_tail_certificate(
                ROOTS, UNUSED_LABELS, UNUSED_DIFFERENCES, state, paths
            )
            self.assertTrue(ok, reason)

    def test_default_state_space_has_253_vectors(self):
        states = all_states()
        self.assertEqual(len(states), 253)
        self.assertTrue(all(sum(state) == 23 for state in states))
        self.assertTrue(all(state[0] == 1 and state[1] >= 1 for state in states))

    def test_neighbors_transfer_one_edge(self):
        states = set(all_states())
        source = (1, 5, 11, 6)
        neighbors = neighboring_states(source, states)
        self.assertIn(((1, 6, 10, 6), 2, 1), neighbors)
        self.assertIn(((1, 5, 10, 7), 2, 3), neighbors)
        for target, _, _ in neighbors:
            self.assertEqual(sum(abs(a - b) for a, b in zip(source, target)), 2)

    def test_generic_solver_handles_one_path(self):
        result = solve_tail_packing(
            (0,),
            (1, 2, 3),
            (1, 2, 3),
            (3,),
            time_limit=1.0,
            node_limit=10000,
            memo_limit=10000,
        )
        self.assertEqual(result.status, "solved")
        ok, reason = verify_tail_certificate(
            (0,), (1, 2, 3), (1, 2, 3), (3,), result.paths
        )
        self.assertTrue(ok, reason)

    def test_seed_only_cli_writes_verified_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "switches"
            code = main(["--output-dir", str(output), "--seed-only"])
            self.assertEqual(code, 0)
            with (output / "states.csv").open(
                "r", encoding="utf-8", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row["verified"] == "1" for row in rows))
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["total_states"], 253)
            self.assertEqual(summary["solved_states"], 3)
            self.assertEqual(summary["seed_connected_states"], 3)
            self.assertEqual(summary["switch_components"], 3)

            resumed = main(
                ["--output-dir", str(output), "--seed-only", "--resume"]
            )
            self.assertEqual(resumed, 0)
            with (output / "states.csv").open(
                "r", encoding="utf-8", newline=""
            ) as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 3)


if __name__ == "__main__":
    unittest.main()
