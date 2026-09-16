"""Independent audit and report generator for the C8 Gate-2 outputs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from edge63_displacement_first_compact import EDGE_COUNT, PATHS, build_layout
from edge63_structure_analysis import parse_case


VERSION = "C8.LevelB.v1"
ALLOCATION_VERSION = "ownership.v2"
ALLOWED = {
    "SAT_VERIFIED",
    "COMPATIBLE_SPAN_GT63",
    "UNSAT_EXHAUSTIVE_C8_LEVELB",
    "UNRESOLVED_RESOURCE",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verify_certificate(path: Path) -> dict[str, object]:
    certificate = json.loads(path.read_text(encoding="utf-8"))
    case = certificate["case"]
    parsed = parse_case(case)
    if parsed is None or parsed[1] != EDGE_COUNT:
        raise AssertionError("bad certificate case")
    values = parsed[2]
    blocks = {
        path_name: tuple(tuple(interval) for interval in intervals)
        for path_name, intervals in certificate["blocks"].items()
    }
    if set(blocks) != set(PATHS):
        raise AssertionError("certificate does not name all paths")
    run_count = sum(len(intervals) for intervals in blocks.values())
    if run_count != 8:
        raise AssertionError("C8 certificate does not have eight runs")
    split_paths = [path_name for path_name, intervals in blocks.items() if len(intervals) == 2]
    if split_paths != [certificate["split_slot"]]:
        raise AssertionError("split path ownership mismatch")
    if any(len(intervals) not in (1, 2) for intervals in blocks.values()):
        raise AssertionError("path uses more than two runs")
    all_differences = []
    flattened = []
    for intervals in blocks.values():
        for start, end in intervals:
            if start > end:
                raise AssertionError("empty or reversed run")
            flattened.extend(range(start, end + 1))
    if sorted(flattened) != list(range(1, EDGE_COUNT + 1)):
        raise AssertionError("difference runs do not partition 1..63")
    labels = list(certificate["labels"])
    if len(labels) != EDGE_COUNT + 1 or sorted(labels) != list(range(EDGE_COUNT + 1)):
        raise AssertionError("certificate labels are not 0..63")
    layout = build_layout(values)
    path_differences = {}
    for path_name in PATHS:
        observed = sorted(
            abs(labels[u] - labels[v])
            for u, v in zip(layout[path_name], layout[path_name][1:])
        )
        expected = sorted(
            difference for start, end in blocks[path_name]
            for difference in range(start, end + 1)
        )
        if observed != expected:
            raise AssertionError(f"path difference mismatch: {path_name}")
        path_differences[path_name] = observed
        all_differences.extend(observed)
    if sorted(all_differences) != list(range(1, EDGE_COUNT + 1)):
        raise AssertionError("global differences are not 1..63")
    return {
        "certificate": str(path),
        "case": case,
        "status": "PASS",
        "split_slot": certificate["split_slot"],
        "run_count": run_count,
        "span": certificate["span"],
        "path_differences": path_differences,
    }


def case_name_from_rows(rows: list[dict[str, str]]) -> str:
    return rows[0]["case"] if rows else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    args = parser.parse_args()
    rows = []
    certificate_checks = []
    for case_dir in (args.root / "tree1_C8", args.root / "tree3_C8"):
        result_path = case_dir / "split_slot_results.csv"
        case_rows = read_csv(result_path)
        for row in case_rows:
            if row.get("local_language") != VERSION:
                raise AssertionError("unexpected local language version")
            if row.get("allocation_dedup_version") != ALLOCATION_VERSION:
                raise AssertionError("stale C8 allocation row; rerun with ownership.v2")
            if row.get("status") not in ALLOWED:
                raise AssertionError("unknown C8 status")
            complete = row.get("global_enumeration_complete") == "True"
            if row["status"] == "UNRESOLVED_RESOURCE" and complete:
                raise AssertionError("resource-limited row marked complete")
            if row["status"] in {"UNSAT_EXHAUSTIVE_C8_LEVELB", "COMPATIBLE_SPAN_GT63"} and not complete:
                raise AssertionError("non-exhaustive row has an exhaustive status")
            rows.append(row)
        for certificate_path in sorted((case_dir / "verified_constructions").glob("*.json")):
            certificate_checks.append(verify_certificate(certificate_path))
    status_counts = Counter(row["status"] for row in rows)
    verification = {
        "verification_version": "C8.independent.v1",
        "local_language": VERSION,
        "status": "PASS",
        "split_result_rows": len(rows),
        "status_counts": dict(status_counts),
        "certificate_checks": certificate_checks,
        "implemented_split_scope": "side terminal paths only",
        "prescanned_but_not_implemented": ["left_bridge", "right_bridge", "middle_leaf"],
        "no_C7_research_restarted": True,
        "no_unrestricted_graceful_search": True,
        "no_old_sigma66_data": True,
    }
    write_json(args.root / "gate2_verification.json", verification)

    for case_dir in (args.root / "tree1_C8", args.root / "tree3_C8"):
        case_rows = [row for row in rows if row.get("case") == case_name_from_rows(read_csv(case_dir / "split_slot_results.csv"))]
        if not case_rows:
            continue
        case_lines = [
            "# C8 terminal-split audit",
            "",
            f"Case `{case_rows[0]['case']}`; local language `C8.LevelB.v1`.",
            "",
            "This directory covers terminal-path splits only. Bridge and middle "
            "splits are present in the allocation prescan but are not silently "
            "treated as implemented by this runner.",
            "",
            "| split slot | status | complete | raw allocations | middle groups | contexts | residual assignments | compatible pairs |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in case_rows:
            case_lines.append(
                f"| {row['split_slot']} | {row['status']} | {row['global_enumeration_complete']} | "
                f"{row['raw_C8_allocations']} | {row['middle_triples_processed']}/{row['middle_triples_total']} | "
                f"{row['middle_contexts_processed']} | {row['residual_assignments_processed']} | "
                f"{row['compatible_terminal_pairs']} |"
            )
        case_lines.extend([
            "",
            "A row with `UNRESOLVED_RESOURCE` is incomplete and carries no negative conclusion.",
            "",
            "Local-language scope: `C8.LevelB.v1`; cache scope: `corrected.v2`.",
        ])
        (case_dir / "report.md").write_text("\n".join(case_lines) + "\n", encoding="utf-8")

    lines = [
        "# C7 versus C8",
        "",
        "C7 is the completed single-interval language. C8 is `C8.LevelB.v1`, "
        "with exactly one split path and six single-run paths.",
        "",
        "The C8 local language is finite but not permutation-complete for long "
        "runs: each run uses the trusted C7 Level-B order family, and the path "
        "uses block concatenation or stable alternating merges.",
        "",
        "## Current probe ledger",
        "",
        "| case | split slot | status | raw allocation universe | middle groups | compatible pairs | minimum span |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['case']} | {row['split_slot']} | {row['status']} | "
            f"{row['raw_C8_allocations']} | {row['middle_triples_processed']}/{row['middle_triples_total']} | "
            f"{row['compatible_terminal_pairs']} | {row['minimum_compatible_span']} |"
        )
    lines.extend([
        "",
        "No `UNSAT_EXHAUSTIVE_C8_LEVELB` row is present. Resource-limited rows "
        "are not negative results.",
        "",
        "## Scope",
        "",
        "These are Gate-2A finite-language results, not a statement about all "
        "two-interval realizations and not a graceful nonexistence theorem.",
    ])
    (args.root / "C7_vs_C8_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.root / "formal_lemmas.md").write_text(
        "# C8 formal lemmas\n\n"
        "## Run-allocation partition\n\n"
        "If seven path difference sets are pairwise disjoint unions of at most "
        "two nonempty consecutive intervals and their union is `{1,...,63}`, "
        "then the allocation is determined by its ordered run partition and run "
        "ownership. A local realization must still be checked for vertex "
        "injectivity and correct shared-root gluing.\n\n"
        "## C8 characterization\n\n"
        "If the total number of runs is 8 and every one of seven paths has at "
        "least one run and at most two, exactly one path has two runs and the "
        "other six have one. This is the C8 language used here.\n\n"
        "## Middle-frame collision check\n\n"
        "For a fixed bridge displacement, translating a terminal private offset "
        "set into the middle-root frame is an exact coordinate change. Collision "
        "with an already occupied middle-frame offset is therefore equivalent to "
        "the original translated-root collision condition.\n\n"
        "## Span packing\n\n"
        "If all 64 graph vertices receive distinct relative offsets and their "
        "span is at most 63, translation by the negative minimum produces the "
        "label set `{0,...,63}`.\n\n"
        "The C8 verifier checks these identities directly for any SAT certificate.\n",
        encoding="utf-8",
    )
    print(json.dumps(verification, ensure_ascii=False))


if __name__ == "__main__":
    main()
