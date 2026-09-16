"""Independent verifier for the final Tree3 compression audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path


CASE = "fiveleaf3e-63-3-21-2-14-15-4-4"
OUT = Path("results/edge63_tree3_left_block_final_compression")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_ints(text: str) -> tuple[int, ...]:
    return tuple(int(value) for value in text.split(";")) if text else ()


def main() -> None:
    certificate = read_json(OUT / "final_compression_certificate.json")
    occupied_h = read_csv(OUT / "occupied_domain_hitting_distribution.csv")
    shared_cases = read_csv(OUT / "shared_root_block_cases.csv")
    footprints = read_csv(OUT / "left_facing_footprint_classes.csv")
    quality = read_csv(OUT / "compression_quality_K1_K5.csv")
    controls = read_csv(OUT / "left_nonempty_control_collisions.csv")
    residual = read_csv(OUT / "high_h_residual.csv")
    motif_rows = {
        h: read_csv(OUT / f"blocker_motif_classes_h{h}.csv")
        for h in (1, 2, 3)
    }

    expected_h = {str(h): count for h, count in (
        (1, 4046), (2, 5586), (3, 2378), (4, 770), (5, 136),
        (6, 36), (7, 4), (8, 2), (9, 2),
    )}
    observed_h = {
        row["h"]: int(row["context_count"])
        for row in occupied_h
        if row["status"] == "EXACT"
    }
    quality_by_key = {row["key"]: row for row in quality}
    subtype = certificate["contexts"]["left_empty_subtypes"]
    motif_contexts = {
        str(h): sum(int(row["context_count"]) for row in rows)
        for h, rows in motif_rows.items()
    }

    checks = {
        "case": certificate["case"] == CASE,
        "corrected_v2": certificate["cache_version"] == "corrected.v2",
        "complete_level_b": "complete Level-B" in certificate["language"],
        "old_sigma66_not_used": certificate["old_sigma66_data_used"] is False,
        "context_total": certificate["contexts"]["total"] == 19452,
        "left_empty": certificate["contexts"]["left_empty"] == 19306,
        "left_nonempty_controls": certificate["contexts"]["left_nonempty_controls"] == 146,
        "subtype_total": sum(subtype.values()) == 19306,
        "span_only": subtype["SPAN_ONLY_BLOCK"] == 6346,
        "collision_only_zero": subtype["COLLISION_ONLY_BLOCK"] == 0,
        "mixed": subtype["MIXED_BLOCK"] == 12960,
        "occupied_h_complete": observed_h == expected_h,
        "occupied_h_all_exact": all(row["status"] == "EXACT" for row in occupied_h),
        "shared_root_cases": len(shared_cases) == 104,
        "shared_root_case_roles_present": all(row["shared_root_blockers"] for row in shared_cases),
        "left_root_excluded": certificate["occupied_domain"]["left_root_excluded"] is True,
        "r2_r3_remain_blockers": certificate["occupied_domain"]["shared_roots_r2_r3_remain_blockers"] is True,
        "footprint_context_total": sum(int(row["context_count"]) for row in footprints) == 19452,
        "control_rows": len(controls) == 146,
        "high_h_residual": len(residual) == 950,
        "motif_h1_contexts": motif_contexts["1"] == 4046,
        "motif_h2_contexts": motif_contexts["2"] == 5586,
        "motif_h3_contexts": motif_contexts["3"] == 2378,
        "K1": quality_by_key["K1"]["classes"] == "2294"
        and quality_by_key["K1"]["mixed_classes"] == "60"
        and quality_by_key["K1"]["mixed_contexts"] == "782",
        "K2": quality_by_key["K2"]["classes"] == "4592"
        and quality_by_key["K2"]["mixed_classes"] == "58"
        and quality_by_key["K2"]["mixed_contexts"] == "434",
        "K3": quality_by_key["K3"]["classes"] == "10878"
        and quality_by_key["K3"]["mixed_classes"] == "30"
        and quality_by_key["K3"]["mixed_contexts"] == "84",
        "K4_exact_but_large": quality_by_key["K4"]["classes"] == "12732"
        and quality_by_key["K4"]["mixed_classes"] == "0"
        and quality_by_key["K4"]["exact_separating"] == "True",
        "K5_exact": quality_by_key["K5"]["classes"] == "16425"
        and quality_by_key["K5"]["mixed_classes"] == "0"
        and quality_by_key["K5"]["exact_separating"] == "True",
        "decision_stop": certificate["decision"] == "STOP_LOW_DIMENSIONAL_PARAMETERIZATION",
    }
    if not all(checks.values()):
        raise AssertionError("failed checks: " + ", ".join(key for key, value in checks.items() if not value))

    result = {
        "verification_version": "tree3-final-compression-independent.v1",
        "case": CASE,
        "status": "PASS",
        "checks": checks,
        "scope_note": (
            "This verifies the persisted finite compression tables and their "
            "accounting. The prior corrected.v2 left-block verifier remains "
            "the source-level check for exact hitting-set completeness."
        ),
        "finite_scope_note": "No graceful nonexistence theorem is inferred.",
    }
    (OUT / "final_compression_certificate_verification.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
