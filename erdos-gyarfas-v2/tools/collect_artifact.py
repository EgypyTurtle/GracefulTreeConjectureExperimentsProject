#!/usr/bin/env python3
"""Collect an audited completed run; never upload or alter search records."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import uuid

from audit_checkpoint import audit_checkpoint, AuditError


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def collect(root, checkpoint, output, expect_k=None, expect_states=None):
    root = root.resolve()
    for required in ("search.cpp", "refine.cpp", "Makefile", "reference/LICENSE"):
        if not (root / required).is_file():
            raise AuditError("missing reproducibility source: " + required)
    cp = checkpoint if checkpoint.is_absolute() else root / checkpoint
    print("Auditing records and refinement ancestry...", file=sys.stderr, flush=True)
    audit = audit_checkpoint(root, cp)
    actual_k = audit["checkpoints"][-1]["configuration"]["k"]
    if expect_k is not None and actual_k != expect_k:
        raise AuditError("unexpected k")
    if expect_states is not None and audit["final_statistics"]["states"] != expect_states:
        raise AuditError("unexpected total state count")
    # Whitelist public research files; do not recurse into home, .git,
    # credential/config directories, or arbitrary files in the project root.
    files = {}
    def include(path, name=None):
        if path.is_symlink():
            raise AuditError("symlink in artifact input: " + str(path))
        if path.is_file():
            path.resolve().relative_to(root)
            files[name or path.relative_to(root).as_posix()] = path
    for name in ("search.cpp", "refine.cpp", "Makefile", "run.sh", "run_checkpoint.sh",
                 "README.md", "RUN_SERVER_zh.md", "SHA256SUMS", "CITATION.cff", "LICENSE"):
        include(root / name)
    for directory in ("reference", "tools", "tests", "publication", "results"):
        location = root / directory
        if location.is_symlink():
            raise AuditError("symlinked source directory")
        if location.is_dir():
            for p in location.rglob("*"):
                if p.is_symlink():
                    raise AuditError("symlinked source input")
                # Tests' temporary run directories are not release sources.
                relative = p.relative_to(location)
                if any(part.startswith(("run-", "demo-", "bench-", "__pycache__")) for part in relative.parts):
                    continue
                if p.suffix in (".cpp", ".h", ".py", ".md", ".json", ".cff", ".txt") or p.name == "LICENSE":
                    include(p)
    for record in audit["checkpoints"]:
        directory = root / record["checkpoint"]
        for p in directory.rglob("*"):
            if p.is_symlink():
                raise AuditError("symlinked checkpoint input")
            if p.is_file() and p.suffix != ".tmp" and p.name != "run.lock":
                include(p)
    for p in (root / "logs").glob("k1[34]*.log"):
        include(p)
    # These are the collectors just used, possibly staged outside the project.
    # Include only these two explicitly named audit sources from that location.
    collector = Path(__file__).resolve()
    files["verification/collect_artifact.py"] = collector
    files["verification/audit_checkpoint.py"] = collector.with_name("audit_checkpoint.py")
    if (root / "out" / "eg_search").is_file():
        include(root / "out" / "eg_search", "run_binary/eg_search")

    environment = {}
    for command in (["lscpu"], ["g++", "--version"], ["uname", "-srmo"]):
        try:
            p = subprocess.run(command, capture_output=True, text=True, timeout=15)
            environment[" ".join(command)] = {"returncode": p.returncode, "output": p.stdout, "error": p.stderr}
        except (OSError, subprocess.TimeoutExpired) as error:
            environment[" ".join(command)] = {"unavailable": str(error)}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"eg_k{actual_k}_{stamp}_{uuid.uuid4().hex[:8]}.tar.gz"
    hashes = {name: digest(path) for name, path in sorted(files.items())}
    generated = {
        "verification/integrity_audit.json": json.dumps(audit, indent=2).encode() + b"\n",
        "verification/environment.json": json.dumps(environment, indent=2).encode() + b"\n",
        "verification/README.txt": (
            "Status: research artifact, pending independent mathematical review.\n"
            "integrity_audit.json checks records and lineage; it does not replay all DFS exclusions.\n"
            "This archive was collected after the reported run. SHA256SUMS records collected bytes,\n"
            "not a pre-run freeze. Original logs and checkpoint sources are retained.\n"
            "To audit a relocated archive: python3 verification/audit_checkpoint.py\n"
            f"  --project-root . --checkpoint {audit['checkpoints'][-1]['checkpoint']}\n"
            "Use --replay-refinement to independently replay only the refinement split layers.\n"
        ).encode(),
    }
    for name, data in generated.items():
        hashes[name] = hashlib.sha256(data).hexdigest()
    generated["ARTIFACT_SHA256SUMS"] = "".join(f"{h}  {name}\n" for name, h in sorted(hashes.items())).encode()
    print(f"Packaging {len(files)} files...", file=sys.stderr, flush=True)
    with archive.open("xb") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz") as tar:
            for name, path in sorted(files.items()):
                # Catch concurrent changes rather than silently archiving
                # different bytes from those checked above.
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != hashes[name]:
                    raise AuditError("input changed during collection: " + name)
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mtime = int(path.stat().st_mtime)
                info.mode = 0o755 if name == "run_binary/eg_search" else 0o644
                tar.addfile(info, io.BytesIO(data))
            for name, data in sorted(generated.items()):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
    archive_digest = digest(archive)
    sidecar = archive.with_name(archive.name + ".sha256")
    with sidecar.open("x", encoding="ascii") as out:
        out.write(f"{archive_digest}  {archive.name}\n")
    return {"archive": str(archive), "sha256_file": str(sidecar), "sha256": archive_digest,
            "files": len(files) + len(generated), "integrity_passed": True,
            "full_search_independently_replayed": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expect-k", type=int)
    parser.add_argument("--expect-states", type=int)
    args = parser.parse_args()
    result = collect(args.project_root, args.checkpoint, args.output_dir, args.expect_k, args.expect_states)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (AuditError, ValueError, KeyError, StopIteration, OSError) as error:
        print("COLLECTION FAILED: " + str(error), file=sys.stderr)
        raise SystemExit(2)
