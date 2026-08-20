import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from free_tree_graceful_experiment import solver_args  # noqa: E402


class FreeTreeGracefulExperimentTests(unittest.TestCase):
    def test_solver_options_use_compressed_method(self):
        args = type(
            "Args",
            (),
            {
                "extension_fastpath_nodes": 2000,
                "extension_adaptive_nodes": 100000,
                "extension_cache_size": 100000,
                "extension_cache_db": "cache.sqlite3",
                "extension_try_all_paths": True,
                "time_limit": 30.0,
            },
        )()
        options = solver_args(args)
        self.assertEqual(options.method, "compressed")
        self.assertTrue(options.extension_try_all_paths)
        self.assertEqual(options.extension_fastpath_nodes, 2000)


if __name__ == "__main__":
    unittest.main()
