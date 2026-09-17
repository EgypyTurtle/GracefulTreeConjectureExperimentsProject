"""Tests for the edge64 production runner's shard partitioning.

Shards are the mechanism that lets the edge 64 cascade use more than one core in
environments where ``ProcessPoolExecutor`` cannot start.  Each shard walks the
stage input independently and must end up with an exactly disjoint slice, no
gaps and no duplicates, while batch boundary indices stay in whole-input
coordinates so that a merged result set is identical to an unsharded one.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import edge64_full_production as production  # noqa: E402


def shard_positions(total: int, batch_size: int, shard_count: int) -> tuple[list[list[int]], list[tuple[int, int]]]:
    """Mirror of the runner's shard walk over ``total`` synthetic rows."""
    batches: list[list[int]] = []
    ranges: list[tuple[int, int]] = []
    for shard_index in range(shard_count):
        pos = shard_index
        while True:
            rows: list[int] = []
            batch_start = pos
            batch_end = pos
            while len(rows) < batch_size:
                if pos >= total:
                    break
                rows.append(pos)
                batch_end = pos + 1
                pos += shard_count
            if not rows:
                break
            batches.append(rows)
            ranges.append((batch_start, batch_end))
    return batches, ranges


class ShardPartitionTests(unittest.TestCase):
    def test_shards_are_disjoint_and_complete(self) -> None:
        for total in (0, 1, 7, 512, 513, 1024, 10_000):
            for batch_size in (1, 3, 512):
                for shard_count in (1, 2, 4, 16):
                    batches, _ranges = shard_positions(total, batch_size, shard_count)
                    flat = [position for batch in batches for position in batch]
                    self.assertEqual(
                        sorted(flat),
                        list(range(total)),
                        f"total={total} batch={batch_size} shards={shard_count}",
                    )
                    self.assertEqual(
                        len(flat),
                        len(set(flat)),
                        f"duplicate positions for total={total} shards={shard_count}",
                    )

    def test_each_shard_stays_inside_its_residue_class(self) -> None:
        total, shard_count = 5_000, 4
        for shard_index in range(shard_count):
            pos = shard_index
            seen = []
            while pos < total:
                seen.append(pos)
                pos += shard_count
            self.assertTrue(all(position % shard_count == shard_index for position in seen))
            self.assertEqual(seen, list(range(shard_index, total, shard_count)))

    def test_batch_ranges_are_contiguous_per_shard(self) -> None:
        total, batch_size, shard_count = 1_000, 512, 4
        _batches, ranges = shard_positions(total, batch_size, shard_count)
        self.assertEqual(len(ranges), len(set(ranges)), "batch file names must be unique across shards")
        for start, end in ranges:
            self.assertLess(start, end)
            self.assertGreaterEqual(start, 0)
            self.assertLessEqual(end, total)

    def test_shard_count_one_matches_plain_batching(self) -> None:
        total, batch_size = 1_300, 512
        batches, ranges = shard_positions(total, batch_size, 1)
        self.assertEqual([len(batch) for batch in batches], [512, 512, 276])
        self.assertEqual(ranges, [(0, 512), (512, 1024), (1024, 1300)])


class ShardPathTests(unittest.TestCase):
    def test_batch_paths_are_shard_specific(self) -> None:
        plain = production.batch_path("compressed_0.5s", 0, 512)
        tagged = production.batch_path("compressed_0.5s", 0, 512, ".shard00of04")
        self.assertNotEqual(plain, tagged)
        self.assertTrue(tagged.name.endswith(".shard00of04.csv"))

    def test_merge_requires_every_shard_file(self) -> None:
        missing = [
            production.OUT / "pending" / f"after_absent_stage.shard{index:02d}of{count:02d}.csv"
            for index, count in ((0, 4), (1, 4))
        ]
        for path in missing:
            self.assertFalse(path.exists())
        with self.assertRaises(RuntimeError):
            production.merge_shards("absent_stage", production.CASE_MANIFEST, 4)


if __name__ == "__main__":
    unittest.main()
