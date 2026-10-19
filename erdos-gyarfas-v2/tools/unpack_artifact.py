#!/usr/bin/env python3
"""Verify a collected archive and safely extract it into a new directory."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import tarfile


def unpack(archive, output):
    expected = archive.with_name(archive.name + ".sha256").read_text(encoding="ascii").split()[0]
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("archive SHA-256 mismatch")
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        names = {}
        for member in members:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or "\\" in member.name or ":" in member.name
                    or member.name in names or not path.parts
                    or path.as_posix() != member.name
                    or any(part.endswith((".", " ")) or PureWindowsPath(part).is_reserved() for part in path.parts)):
                raise ValueError("unsafe/duplicate archive member: " + member.name)
            names[member.name] = member
        if len(members) > 100000 or sum(m.size for m in members) > 2 * 1024 ** 3:
            raise ValueError("archive exceeds extraction limits")
        records = tar.extractfile(names["ARTIFACT_SHA256SUMS"]).read().decode("ascii").splitlines()
        checksums = {}
        for line in records:
            checksum, name = line.split("  ", 1)
            if name in checksums:
                raise ValueError("duplicate checksum entry")
            checksums[name] = checksum
        if set(checksums) != set(names) - {"ARTIFACT_SHA256SUMS"}:
            raise ValueError("checksum inventory mismatch")
        # Check every member before creating an output tree.
        for name, checksum in checksums.items():
            if hashlib.sha256(tar.extractfile(names[name]).read()).hexdigest() != checksum:
                raise ValueError("member SHA-256 mismatch: " + name)
        output.mkdir(parents=True, exist_ok=False)
        for member in members:
            destination = output.joinpath(*PurePosixPath(member.name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(tar.extractfile(member).read())
    return {"archive": archive.name, "sha256": actual, "files": len(members),
            "all_member_checksums_passed": True, "extracted_to": str(output.resolve())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(unpack(args.archive, args.output), indent=2))
