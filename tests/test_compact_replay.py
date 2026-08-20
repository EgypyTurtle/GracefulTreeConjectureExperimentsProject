import csv
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graceful_tree import (  # noqa: E402
    five_leaf_nonspider_three_branch,
    main,
    reconstruct_named_five_leaf_case,
)


class CompactReplayTests(unittest.TestCase):
    def test_reconstruct_three_branch_case(self):
        name = "fiveleaf3e-62-1-7-1-1-21-8-23"
        vertices, edges = reconstruct_named_five_leaf_case(name)
        expected = five_leaf_nonspider_three_branch(1, 7, (1, 1), 21, (8, 23))
        self.assertEqual(vertices, 63)
        self.assertEqual(edges, expected)
        self.assertEqual(len(edges), 62)

    def test_rejects_non_edge_indexed_name(self):
        with self.assertRaises(ValueError):
            reconstruct_named_five_leaf_case("fiveleaf3-1-7-1-1-21-8-23")

    def test_replay_accepts_compact_csv_without_edges(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "compact.csv"
            output = Path(directory) / "replay.csv"
            source.write_text(
                "case,vertices,seed,strategy,reduction_base,extended_edges,status,solved,nodes,backtracks,elapsed_seconds\n"
                "fiveleaf3e-62-1-7-1-1-21-8-23,63,,pendant-extension+branch,,13,timeout_or_failed,0,1,1,300.0\n",
                encoding="utf-8",
            )
            code = main(
                [
                    "--replay-unsolved",
                    str(source),
                    "--replay-log",
                    str(output),
                    "--method",
                    "branch",
                    "--time-limit",
                    "0",
                    "--extension-cache-db",
                    "",
                    "--progress",
                    "1",
                ]
            )
            self.assertEqual(code, 2)
            with output.open("r", encoding="utf-8", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["vertices"], "63")
            self.assertTrue(row["edges"].startswith("0-1 1-3 3-4"))


if __name__ == "__main__":
    unittest.main()
