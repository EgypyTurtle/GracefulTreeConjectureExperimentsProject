#!/usr/bin/env python3
"""Record the local regression suite, without claiming full large-run replay."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = ".exe" if os.name == "nt" else ""
commands = [[str(ROOT / "out" / (name + SUFFIX))] for name in ("kernels", "wide_oracles")]
commands += [[sys.executable, name] for name in (
    "tests/test_verifier.py", "tools/regression.py", "tests/test_refine.py", "tests/test_audit.py")]
result = {"recorded_utc": datetime.now(timezone.utc).isoformat(),
          "platform": platform.platform(), "python": platform.python_version(),
          "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                            for name in ("search.cpp", "refine.cpp")},
          "full_k14_search_independently_replayed": False, "tests": []}
with tempfile.TemporaryDirectory(prefix="run-release-", dir=ROOT / "tests") as directory:
    env = dict(os.environ)
    env.update({name: directory for name in ("TEMP", "TMP", "TMPDIR")})
    for command in commands:
        completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
        label = str(Path(command[-1]).relative_to(ROOT)) if len(command) == 1 else command[-1]
        print(label + "\n" + completed.stdout + completed.stderr, flush=True)
        result["tests"].append({"test": label, "exit_status": completed.returncode,
                                "stdout": completed.stdout, "stderr": completed.stderr})
        if completed.returncode:
            break
result["passed"] = len(result["tests"]) == len(commands) and all(item["exit_status"] == 0 for item in result["tests"])
(ROOT / "tests" / "release_validation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
raise SystemExit(0 if result["passed"] else 1)
