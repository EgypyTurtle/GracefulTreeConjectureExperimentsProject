"""Compare two captured diag_profile_stage.py outputs side by side."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8-sig")
    return json.loads(raw[raw.index("{") :])


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: compare_profiles.py OLD.json NEW.json")
        return 2
    old = load(Path(sys.argv[1]))
    new = load(Path(sys.argv[2]))

    header = f"{'metric':22s} {'old':>14s} {'new':>14s} {'delta':>12s}"
    print(header)
    print("-" * len(header))

    def row(name: str, a: float, b: float, fmt: str = "{:.2f}") -> None:
        delta = b - a
        pct = f"{100.0 * delta / a:+.1f}%" if a else "n/a"
        print(f"{name:22s} {fmt.format(a):>14s} {fmt.format(b):>14s} {pct:>12s}")

    row("cases", old["cases"], new["cases"], "{:.0f}")
    row("solved", old["solved"], new["solved"], "{:.0f}")
    row("survivors", old["survivors"], new["survivors"], "{:.0f}")
    row("budget_hits", old["budget_hits"], new["budget_hits"], "{:.0f}")
    row("wall_seconds", old["wall_seconds"], new["wall_seconds"])
    row("mean_ms", old["mean_ms"], new["mean_ms"])
    row("p50_ms", old["p50_ms"], new["p50_ms"])
    row("p90_ms", old["p90_ms"], new["p90_ms"])
    row("p99_ms", old["p99_ms"], new["p99_ms"])
    row("max_ms", old["max_ms"], new["max_ms"])

    print()
    print("strategy mix (old):", json.dumps(old["strategies"]))
    print("strategy mix (new):", json.dumps(new["strategies"]))
    print()
    print("nodes (old):", json.dumps(old["nodes_by_strategy"]))
    print("nodes (new):", json.dumps(new["nodes_by_strategy"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
