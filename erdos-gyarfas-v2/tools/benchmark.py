#!/usr/bin/env python3
"""Same-host wall-time benchmark; every search uses a fresh checkpoint."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = ".exe" if os.name == "nt" else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, nargs="+", default=[10, 11])
    parser.add_argument("--threads", type=int, nargs="+", default=[1, 8, 32])
    parser.add_argument("--split-depth", type=int, default=3)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="eg-bench-") as directory:
        for k in args.k:
            configurations = [("reference", None)] + [("v2", t) for t in args.threads]
            for label, threads in configurations:
                if label == "reference":
                    command = [str(ROOT / "out" / ("reference" + SUFFIX)), str(k)]
                else:
                    command = [str(ROOT / "out" / ("eg_search" + SUFFIX)), "--k", str(k),
                               "--threads", str(threads), "--split-depth", str(args.split_depth),
                               "--checkpoint", str(Path(directory) / f"k{k}-t{threads}")]
                start = time.perf_counter()
                p = subprocess.run(command, capture_output=True, text=True)
                elapsed = time.perf_counter() - start
                if p.returncode:
                    raise RuntimeError(f"{command}\n{p.stdout}\n{p.stderr}")
                result = {"k": k, "implementation": label, "threads": threads,
                          "wall_seconds": elapsed, "output": p.stdout.strip()}
                results.append(result)
                print(f"k={k} implementation={label} threads={threads} wall={elapsed:.6f}s", flush=True)
    if args.report:
        args.report.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
