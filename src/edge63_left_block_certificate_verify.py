"""Independently verify the persisted Tree3 left-block audit."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


CASE = "fiveleaf3e-63-3-21-2-14-15-4-4"
OUT = Path("results/edge63_tree3_left_block_parameterization")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ints(text: str) -> tuple[int, ...]:
    if not text:
        return ()
    return tuple(int(value) for value in text.split(";"))


def main() -> None:
    certificate = read_json(OUT / "tree3_left_block_certificate.json")
    contexts = read_csv(OUT / "middle_context_features.csv")
    subtypes = read_csv(OUT / "left_empty_subtypes.csv")
    kernels = read_csv(OUT / "mandatory_kernel_analysis.csv")
    h_rows = read_csv(OUT / "hitting_set_distribution.csv")
    role_rows = read_csv(OUT / "blocker_vertex_roles.csv")

    keys = {(row["triple_id"], row["context_id"]) for row in contexts}
    subtype_counts = Counter(row["left_block_detail"] for row in contexts)
    left_empty = [row for row in contexts if row["left_empty"] == "True"]
    left_controls = [row for row in contexts if row["left_empty"] == "False"]
    mixed = [row for row in left_empty if row["left_block_detail"] == "MIXED_BLOCK"]

    persisted_subtypes = {row["subtype"]: int(row["context_count"]) for row in subtypes}
    expected_subtypes = {
        key: subtype_counts.get(key, 0)
        for key in (
            "SPAN_ONLY_BLOCK",
            "COLLISION_ONLY_BLOCK",
            "MIXED_BLOCK",
            "LEFT_NONEMPTY_CONTROL",
        )
    }
    persisted_h = {
        (row["offset_domain"], row["status"], row["h"]): int(row["context_count"])
        for row in h_rows
    }

    all_h_exact = sum(
        count for (domain, status, _h), count in persisted_h.items()
        if domain == "all_offsets" and status == "EXACT"
    )
    private_h_exact = sum(
        count for (domain, status, _h), count in persisted_h.items()
        if domain == "private_offsets" and status == "EXACT"
    )
    private_resource = sum(
        count for (domain, status, _h), count in persisted_h.items()
        if domain == "private_offsets" and status == "RESOURCE_LIMIT"
    )
    private_infeasible = sum(
        count for (domain, status, _h), count in persisted_h.items()
        if domain == "private_offsets" and status == "INFEASIBLE"
    )
    all_infeasible = sum(
        count for (domain, status, _h), count in persisted_h.items()
        if domain == "all_offsets" and status == "INFEASIBLE"
    )

    # The root/private audit is intentionally semantic: a root may be a valid
    # occupied blocker for a private vertex, but it is never counted as a
    # private-middle offset in the private-domain hitting-set calculation.
    zero_roles = [row for row in role_rows if int(row["offset"]) == 0 and int(row["blocked_state_hits"]) > 0]
    zero_role_names = {row["middle_role"] for row in zero_roles}
    shared_zero_is_explicit = zero_role_names == {"SHARED_ROOT_r2"}

    checks = {
        "case": certificate["case"] == CASE,
        "corrected_v2": certificate["cache_version"] == "corrected.v2",
        "complete_level_b_language": "complete Level-B" in certificate["language"],
        "context_count": len(contexts) == 19452 and certificate["context_total"] == 19452,
        "context_keys_unique": len(keys) == 19452,
        "context_class_sum": sum(subtype_counts.values()) == 19452,
        "left_empty_count": len(left_empty) == 19306 and certificate["left_empty_contexts"] == 19306,
        "left_nonempty_count": len(left_controls) == 146 and certificate["left_nonempty_contexts"] == 146,
        "left_context_controls": sum(subtype_counts.values()) == 19452,
        "subtype_table_match": persisted_subtypes == expected_subtypes,
        "no_collision_only_contexts": subtype_counts.get("COLLISION_ONLY_BLOCK", 0) == 0,
        "right_support": sum(int(row["right_nonempty_assignments"]) > 0 for row in contexts) == 3656,
        "both_support": sum(int(row["both_sides_nonempty_assignments"]) > 0 for row in contexts) == 6,
        "all_h_exact_complete": all_h_exact == 12960,
        "private_h_accounted": private_h_exact + private_infeasible + private_resource == 12960,
        "private_resource_count": private_resource == 0,
        "private_infeasible_count": private_infeasible == 104,
        "all_offset_no_infeasible": all_infeasible == 0,
        "kernel_counts_match": certificate["kernel"]["all_offset_kernel_contexts"] == 4046
        and certificate["kernel"]["private_offset_kernel_contexts"] == 4018,
        "kernel_rows_complete": len(kernels) == 19452,
        "zero_role_explicit": shared_zero_is_explicit,
        "old_baseline_not_used": certificate["old_baseline_used"] is False,
    }
    if not all(checks.values()):
        raise AssertionError("failed checks: " + ", ".join(key for key, value in checks.items() if not value))

    result = {
        "verification_version": "tree3-left-block-independent.v2",
        "case": CASE,
        "status": "PASS",
        "checks": checks,
        "derived": {
            "contexts": len(contexts),
            "left_empty": len(left_empty),
            "left_nonempty_controls": len(left_controls),
            "left_empty_subtypes": dict(subtype_counts),
            "mixed_contexts_with_exact_h": sum(
                1 for row in mixed if row["h_all_status"] == "EXACT"
            ),
            "all_offset_h_exact_contexts": all_h_exact,
            "private_offset_h_exact_contexts": private_h_exact,
            "private_offset_h_infeasible_contexts": private_infeasible,
            "private_offset_h_resource_limit_contexts": private_resource,
            "zero_blocker_roles": sorted(zero_role_names),
        },
        "scope_note": (
            "The all-offset hitting-set distribution is complete for the 12,960 "
            "MIXED_BLOCK contexts. The private-offset distribution has 12,856 "
            "exact rows and 104 INFEASIBLE rows; it has no resource-limited rows."
        ),
        "finite_scope_note": (
            "This verifies the persisted finite left-compatibility audit only; "
            "it is not a graceful nonexistence theorem."
        ),
    }
    path = OUT / "tree3_left_block_certificate_verification.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
