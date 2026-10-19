#!/usr/bin/env python3
"""Package sources, reference license and validation evidence, excluding run data."""
import hashlib
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
files = [root / name for name in (".gitignore", ".gitattributes", "search.cpp", "refine.cpp", "Makefile", "run.sh", "run_checkpoint.sh", "run_cpu0.sh", "README.md", "RUN_SERVER_zh.md", "CITATION.cff", "LICENSE")]
for directory in ("reference", "tools", "tests", "publication", "results"):
    for p in sorted((root / directory).iterdir()):
        if p.is_file() and (p.suffix in (".cpp", ".h", ".py", ".ps1", ".json", ".md") or p.name == "LICENSE"):
            files.append(p)
checksum = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}\n" for p in files)
archive = root.parent / "erdos-gyarfas-v2.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, f"erdos-gyarfas-v2/{p.relative_to(root).as_posix()}")
    z.writestr("erdos-gyarfas-v2/SHA256SUMS", checksum)
print(archive)
print(f"files={len(files) + 1} bytes={archive.stat().st_size}")
