#!/usr/bin/env python3
"""Compare full accepted-state fingerprints, task splitting and restart behavior."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = ".exe" if os.name == "nt" else ""
FAST = ROOT / "out" / ("eg_search" + SUFFIX)
REF = ROOT / "out" / ("reference_audit" + SUFFIX)


def fields(text):
    return dict(re.findall(r"([a-z_]+)=([^\s]+)", text.splitlines()[-1]))


def run(args, codes=(0,)):
    p = subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=300)
    if p.returncode not in codes:
        raise AssertionError(f"exit={p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


def compare(expected, actual):
    for key in ("states", "accepted", "audit_digest"):
        if expected[key] != actual[key]:
            raise AssertionError(f"{key}: reference={expected[key]} fast={actual[key]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-k", type=int, default=10)
    parser.add_argument("--report", type=Path)
    options = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="eg-regression-") as directory:
        temp = Path(directory)
        for k in range(3, options.max_k + 1):
            reference = fields(run([REF, k]).stdout)
            for depth, threads in ((0, 1), (1, 4), (3, 4)):
                cp = temp / f"k{k}-d{depth}-t{threads}"
                args = [FAST, "--k", k, "--threads", threads, "--split-depth", depth,
                        "--checkpoint", cp, "--audit"]
                actual = fields(run(args).stdout)
                compare(reference, actual)
                again = run(args).stdout
                compare(reference, fields(again))
                if not re.search(r"pending=0\b", again):
                    raise AssertionError("completed task was not reused")
                results.append({"k": k, "depth": depth, "threads": threads,
                                "states": int(actual["states"]), "digest": actual["audit_digest"]})
            capped = run([FAST, "--k", k, "--split-depth", 3, "--task-limit", 1,
                          "--checkpoint", temp / f"cap{k}", "--audit"])
            compare(reference, fields(capped.stdout))
            print(f"PASS k={k} state fingerprints, split=0/1/3, task cap, restart", flush=True)

        # Create a real partial checkpoint by killing a process after its first
        # completed task. Unfinished tasks must never be marked done.
        cp = temp / "interrupted"
        args = [FAST, "--k", 11, "--threads", 1, "--split-depth", 3,
                "--checkpoint", cp, "--audit", "--progress", 0.05]
        with (temp / "interrupted.log").open("w", encoding="utf-8") as log:
            p = subprocess.Popen([str(x) for x in args], stdout=log, stderr=log)
            deadline = time.monotonic() + 60
            while p.poll() is None and not list((cp / "done").glob("*.txt")):
                if time.monotonic() > deadline:
                    p.kill(); p.wait(); raise AssertionError("no task completed within 60 seconds")
                time.sleep(0.005)
            if p.poll() is None:
                p.kill()
            else:
                raise AssertionError("interruption test finished before it could be killed")
            p.wait()
        done_before = len(list((cp / "done").glob("*.txt")))
        if done_before == 0:
            raise AssertionError("no durable task checkpoint")
        # The OS lock must have been released even after abrupt process death.
        args[args.index("--threads") + 1] = 4
        resumed = run(args)
        reference = fields(run([REF, 11]).stdout)
        compare(reference, fields(resumed.stdout))
        if f"reused={done_before} " not in resumed.stdout:
            raise AssertionError("partial checkpoint was not reused")
        print(f"PASS abrupt kill/resume: reused={done_before}, final fingerprint equals reference", flush=True)

        # Explicit stop must return incomplete, not an empty success result.
        stopped = run([FAST, "--k", 12, "--threads", 1, "--split-depth", 0,
                       "--time-limit", 0.01, "--checkpoint", temp / "limited"], codes=(3,))
        if "incomplete:" not in stopped.stdout or "complete:" in stopped.stdout.replace("incomplete:", ""):
            raise AssertionError("time-limited run reported completion")
        print("PASS time limit reports incomplete", flush=True)

        # Reject changed parameters and corrupted completion records.
        mismatch = run([FAST, "--k", 12, "--threads", 1, "--split-depth", 1,
                        "--checkpoint", temp / "limited"], codes=(2,))
        if "differ" not in mismatch.stderr:
            raise AssertionError("configuration mismatch not rejected")
        print("PASS checkpoint configuration mismatch rejected", flush=True)

        broken_cp = temp / "k3-d0-t1"
        (broken_cp / "done" / "0.txt").write_text("0 0\n0 0 0 0 0 0 0 0\n", encoding="utf-8")
        broken = run([FAST, "--k", 3, "--split-depth", 0, "--checkpoint", broken_cp,
                      "--audit"], codes=(2,))
        if "fingerprint mismatch" not in broken.stderr:
            raise AssertionError("corrupt completion record was not rejected")
        print("PASS corrupt completion fingerprint rejected", flush=True)

    if options.report:
        options.report.write_text(json.dumps({"passed": True, "cases": results,
            "abrupt_kill_resume": {"k": 11, "reused_tasks": done_before,
                                   "matches_reference": True},
            "time_limit_incomplete": True, "configuration_mismatch_rejected": True,
            "corrupt_completion_rejected": True}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
