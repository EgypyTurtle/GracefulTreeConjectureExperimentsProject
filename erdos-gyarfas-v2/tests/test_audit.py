#!/usr/bin/env python3
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_checkpoint import audit_checkpoint, AuditError
from collect_artifact import collect
from audit_initial_frontier import replay_manifest
from unpack_artifact import unpack

SUFFIX = ".exe" if os.name == "nt" else ""


def execute(binary, *args):
    p = subprocess.run([str(ROOT / "out" / (binary + SUFFIX))] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=120)
    if p.returncode:
        raise AssertionError(p.stdout + p.stderr)
    return p.stdout


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="eg-audit-")
        cls.root = Path(cls.directory.name)
        source = cls.root / "checkpoints" / "source"
        child = cls.root / "checkpoints" / "child"
        execute("eg_search", "--k", 10, "--threads", 2, "--split-depth", 1,
                "--checkpoint", source, "--audit")
        records = sorted((source / "done").glob("*.txt"), key=lambda p: int(p.stem))
        for index, p in enumerate(records):
            if index % 4:
                p.unlink()
        execute("eg_refine", "--from", source, "--to", child, "--task-limit", 5000)
        execute("eg_search", "--k", 10, "--threads", 2, "--split-depth", 2,
                "--task-limit", 5000, "--checkpoint", child, "--audit")
        cls.source, cls.child = source, child
        for name in ("search.cpp", "refine.cpp", "Makefile", "reference/LICENSE"):
            target = cls.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_independent_split_replay(self):
        result = audit_checkpoint(self.root, self.child, replay=True)
        self.assertTrue(result["integrity_passed"])
        self.assertFalse(result["full_search_independently_replayed"])
        self.assertTrue(result["checkpoints"][-1]["split_layer_independently_replayed"])
        self.assertEqual(result["final_statistics"]["states"], 3007)

    def test_independent_initial_frontier(self):
        result = replay_manifest(self.source / "tasks.txt")
        self.assertTrue(result["initial_frontier_independently_replayed"])
        self.assertFalse(result["full_search_independently_replayed"])

    def test_corrupt_done_and_summary(self):
        done = next((self.child / "done").glob("*.txt"))
        data = done.read_bytes()
        try:
            done.write_bytes(b"0 0\n0 0 0 0 0 0 0 0\n")
            with self.assertRaises(AuditError):
                audit_checkpoint(self.root, self.child)
        finally:
            done.write_bytes(data)
        summary = self.child / "summary.txt"
        data = summary.read_bytes()
        try:
            summary.write_bytes(data.replace(b"states=3007", b"states=3008"))
            with self.assertRaises(AuditError):
                audit_checkpoint(self.root, self.child)
        finally:
            summary.write_bytes(data)

    def test_archive_and_privacy_whitelist(self):
        (self.root / "secret.env").write_text("not for publication", encoding="utf-8")
        result = collect(self.root, self.child, self.root / "artifacts", expect_k=10, expect_states=3007)
        archive = Path(result["archive"])
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), result["sha256"])
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            self.assertNotIn("secret.env", names)
            records = tar.extractfile("ARTIFACT_SHA256SUMS").read().decode().splitlines()
            for line in records:
                digest, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256(tar.extractfile(name).read()).hexdigest(), digest)
            report = json.load(tar.extractfile("verification/integrity_audit.json"))
            self.assertFalse(report["full_search_independently_replayed"])

        extracted = unpack(archive, self.root / "extracted")
        self.assertTrue(extracted["all_member_checksums_passed"])
        with self.assertRaises(FileExistsError):
            unpack(archive, self.root / "extracted")

    def test_archive_rejects_traversal(self):
        archive = self.root / "unsafe.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("../outside")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        archive.with_name(archive.name + ".sha256").write_text(
            hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name, encoding="ascii")
        with self.assertRaises(ValueError):
            unpack(archive, self.root / "unsafe-output")
        self.assertFalse((self.root / "unsafe-output").exists())

    def test_relocated_ancestry(self):
        # Force source lookup by content rather than the original absolute path.
        metadata = self.child / "refinement.txt"
        original = metadata.read_bytes()
        try:
            text = metadata.read_text().splitlines()
            text[0] = "source=/nonexistent-original-server/checkpoints/source"
            metadata.write_text("\n".join(text) + "\n", encoding="utf-8")
            result = audit_checkpoint(self.root, self.child, replay=True)
            self.assertTrue(result["integrity_passed"])
        finally:
            metadata.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
