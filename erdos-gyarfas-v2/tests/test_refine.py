#!/usr/bin/env python3
"""Check partial-frontier refinement without recomputing already completed work."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = ".exe" if os.name == "nt" else ""
SEARCH = ROOT / "out" / ("eg_search" + SUFFIX)
REFINE = ROOT / "out" / ("eg_refine" + SUFFIX)
REFERENCE = ROOT / "out" / ("reference_audit" + SUFFIX)


def run(args, expected=0):
    p = subprocess.run([str(a) for a in args], text=True, capture_output=True, timeout=300)
    if p.returncode != expected:
        raise AssertionError(f"exit={p.returncode}\n{p.stdout}\n{p.stderr}")
    return p.stdout


def fields(text):
    return dict(re.findall(r"([a-z_]+)=([^\s]+)", text.splitlines()[-1]))


def snapshot(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*") if p.is_file()}


def execute(cp, depth, limit=20000):
    return fields(run([SEARCH, "--k", 10, "--threads", 4, "--split-depth", depth,
                       "--task-limit", limit, "--checkpoint", cp, "--audit"]))


def main():
    reference = fields(run([REFERENCE, 10]))
    checks = []
    with tempfile.TemporaryDirectory(prefix="eg-refine-") as directory:
        temp = Path(directory)
        source = temp / "source"
        execute(source, 1)
        # A controlled partial checkpoint: retain a known subset of completed
        # records; the other tasks now have to be searched again.
        records = sorted((source / "done").glob("*.txt"), key=lambda p: int(p.stem))
        for i, p in enumerate(records):
            if i % 4:
                p.unlink()
        completed = len(list((source / "done").glob("*.txt")))
        pending = len(records) - completed
        before = snapshot(source)
        destination = temp / "refined"
        result = fields(run([REFINE, "--from", source, "--to", destination,
                             "--task-limit", 5000]))
        assert int(result["completed_preserved"]) == completed
        assert int(result["old_pending"]) == pending
        assert snapshot(source) == before, "source checkpoint was modified"
        assert int(result["new_tasks"]) > pending, "test did not split pending tasks"

        # Repeated refinement must carry forward prior work and graph hashes.
        twice = temp / "refined-twice"
        run([REFINE, "--from", destination, "--to", twice, "--task-limit", 5000])
        actual = execute(twice, 3, 5000)
        for key in ("states", "accepted", "audit_digest"):
            assert actual[key] == reference[key], (key, actual, reference)
        checks.append("partial and repeated refinement preserves reference state count and digest")
        print("PASS partial + repeated refinement, original checkpoint unchanged", flush=True)

        # A tight cap leaves some parents intact. A mixed-depth frontier must
        # still cover exactly the original remaining search.
        capped = temp / "capped"
        limit = pending + 5
        result = fields(run([REFINE, "--from", source, "--to", capped, "--task-limit", limit]))
        assert int(result["retained"]) > 0
        assert int(result["new_tasks"]) <= limit
        actual = execute(capped, 2, limit)
        for key in ("states", "accepted", "audit_digest"):
            assert actual[key] == reference[key]
        checks.append("capped mixed-depth frontier retains all branches")
        print("PASS capped refinement retains branches and reference fingerprint", flush=True)

        # A fully completed source produces a valid empty frontier carrying
        # all prior work, rather than forgetting the completed search.
        finished = temp / "finished"
        run([REFINE, "--from", twice, "--to", finished])
        actual = execute(finished, 4, 200000)
        for key in ("states", "accepted", "audit_digest"):
            assert actual[key] == reference[key]
        checks.append("fully completed checkpoint carries all statistics")
        print("PASS completed source carries all statistics", flush=True)

        # In-place or destination-overwriting operations must fail.
        run([REFINE, "--from", source, "--to", source], expected=2)
        run([REFINE, "--from", source, "--to", destination], expected=2)
        assert snapshot(source) == before
        checks.append("source and existing destination overwrite rejected")
        print("PASS unsafe destination rejected", flush=True)

    report = ROOT / "tests" / "refinement_validation.json"
    report.write_text(json.dumps({"passed": True, "checks": checks}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
