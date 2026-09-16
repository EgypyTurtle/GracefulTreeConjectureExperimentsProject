"""Resumable C8 side-terminal runner using persistent middle groups.

This runner is intentionally separate from the first bounded probe runner.
Its hard filters are necessary conditions only; a time-limited execution is
always reported as ``UNRESOLVED_RESOURCE``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from edge63_C8_allocation_prefilter import PrefilterStats, prefilter_group, prefilter_version  # noqa: E402
from edge63_C8_middle_group_cache import (  # noqa: E402
    ALLOCATION_DEDUP_VERSION,
    MIDDLE_FRAME_CONVENTION,
    PersistentMiddleGroupCache,
    TERMINAL_PAIR_CACHE_VERSION,
    version_fingerprint,
)
from edge63_C8_two_run_cache import PersistentTwoRunCache  # noqa: E402
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex  # noqa: E402
from edge63_C8_hybrid_terminal_backend import HybridTerminalBackend  # noqa: E402
from edge63_C8_left_negative_cert_cache import (  # noqa: E402
    NegativeCertificateCache,
    canonical_family_key,
)
from edge63_C8_right_first_gate import RightSupportCache, residual_signature  # noqa: E402
from edge63_C8_displacement_first import (  # noqa: E402
    build_relative_labels,
    mask_for,
    verify_c8_labeling,
    values_for_case,
)
from edge63_C8_allocations import LANGUAGE_VERSION  # noqa: E402
from edge63_displacement_first_compact import EDGE_COUNT, MIDDLE_PATHS, PATHS  # noqa: E402


RUNNER_VERSION = "persistent-runner.v4:hybrid-backend"
SUPPORTED_SPLIT_SLOTS = {
    "left_leaf_1",
    "left_leaf_2",
    "right_leaf_1",
    "right_leaf_2",
}


def mask_shift(mask: int, shift: int) -> int:
    return mask << shift if shift >= 0 else mask >> (-shift)


def occupied_offsets_from_mask(mask: int) -> tuple[int, ...]:
    values: list[int] = []
    remaining = int(mask)
    while remaining:
        lowest = remaining & -remaining
        values.append(lowest.bit_length() - 1 - 256)
        remaining ^= lowest
    return tuple(values)


def compatible_states(
    states: tuple,
    middle_mask: int,
    middle_min: int,
    middle_max: int,
    shift: int,
) -> list[tuple]:
    """Return states compatible with one fixed middle-frame context.

    The caller controls the order of side evaluation.  Keeping this scan in
    one helper makes the short-circuit below explicit and auditable.
    """
    compatible = []
    for state in states:
        shifted_mask = mask_shift(state.mask, shift)
        if shifted_mask & middle_mask:
            continue
        low = min(middle_min, state.min_value + shift)
        high = max(middle_max, state.max_value + shift)
        if high - low <= EDGE_COUNT:
            compatible.append((state, shifted_mask, low, high))
    return compatible


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0])
    for row in rows[1:]:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_progress(path: Path, fingerprint: str) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version_fingerprint") != fingerprint:
            return set()
        return set(payload.get("done_group_ids", []))
    except (OSError, ValueError, TypeError):
        return set()


def write_progress(
    path: Path,
    fingerprint: str,
    done: set[str],
    status: str,
    metadata: dict[str, object] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "runner_version": RUNNER_VERSION,
        "version_fingerprint": fingerprint,
        "status": status,
        "done_group_ids": sorted(done),
        "done_group_count": len(done),
    }
    if metadata:
        payload.update(metadata)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_cumulative(path: Path, fingerprint: str) -> dict[str, object]:
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("version_fingerprint") == fingerprint:
                return payload
        except (OSError, ValueError, TypeError):
            pass
    # A pre-accumulator run summary is still a useful seed for resumption.
    # New runs immediately persist the full accumulator below.
    legacy = path.with_name("run_summary.json")
    if legacy.exists():
        try:
            payload = json.loads(legacy.read_text(encoding="utf-8"))
            if payload.get("version_fingerprint") == fingerprint:
                return {
                    "accumulator_version": "progress-accumulator.v1:legacy-seed",
                    "version_fingerprint": fingerprint,
                    "counts": payload.get("counts", {}),
                    "timing": payload.get("timing", {}),
                    "persistent_two_run_cache": payload.get("persistent_two_run_cache", {}),
                    "minimum_compatible_span": payload.get("minimum_compatible_span", "NONE"),
                    "minimum_witness": payload.get("minimum_witness", "NONE"),
                }
        except (OSError, ValueError, TypeError):
            pass
    return {
        "accumulator_version": "progress-accumulator.v1",
        "version_fingerprint": fingerprint,
        "counts": {},
        "timing": {},
        "minimum_compatible_span": "NONE",
        "minimum_witness": "NONE",
    }


def write_cumulative(path: Path, fingerprint: str, counts: dict[str, object], timing: dict[str, float],
                     minimum_span: int | None, minimum_witness: dict[str, object] | None,
                     two_run_cache: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "accumulator_version": "progress-accumulator.v1",
        "version_fingerprint": fingerprint,
        "counts": counts,
        "timing": timing,
        "persistent_two_run_cache": two_run_cache,
        "minimum_compatible_span": minimum_span if minimum_span is not None else "NONE",
        "minimum_witness": minimum_witness if minimum_witness is not None else "NONE",
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def block_map_for(middle_key: tuple, residual_key: tuple) -> dict[str, tuple[tuple[int, int], ...]]:
    blocks = {path: ((start, end),) for path, start, end in middle_key}
    blocks.update({path: tuple(intervals) for path, intervals in residual_key})
    if set(blocks) != set(PATHS):
        raise AssertionError("allocation ownership lost while rebuilding block map")
    return blocks


def search_case(
    case: str,
    split_slot: str,
    root: Path,
    time_limit: float | None,
    output_dir_name: str | None = None,
) -> dict[str, object]:
    if split_slot not in SUPPORTED_SPLIT_SLOTS:
        raise ValueError(f"persistent runner supports side-terminal slots only: {split_slot}")
    values = values_for_case(case)
    output_dir = root / ("tree1_C8" if "20-9-4-4" in case else "tree3_C8") / (
        output_dir_name or f"{split_slot}_exact_v2"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = version_fingerprint(case, split_slot)
    progress_path = output_dir / "progress.json"
    done_groups = read_progress(progress_path, fingerprint)
    cumulative_path = output_dir / "cumulative_summary.json"
    cumulative = read_cumulative(cumulative_path, fingerprint)
    cumulative_counts = dict(cumulative.get("counts", {}))
    cumulative_timing = dict(cumulative.get("timing", {}))
    cumulative_minimum = cumulative.get("minimum_compatible_span", "NONE")
    cumulative_witness = cumulative.get("minimum_witness", "NONE")
    started = time.time()
    cache = PersistentMiddleGroupCache(root, case, split_slot)
    pair_cache = PersistentTwoRunCache(root, case, split_slot)
    compiled_left_index = CompiledTerminalPairIndex(root, case, split_slot) if split_slot == "left_leaf_2" else None
    hybrid_left_backend = (
        HybridTerminalBackend(pair_cache, compiled_left_index)
        if compiled_left_index is not None
        else None
    )
    right_support_cache = (
        RightSupportCache(root, case, split_slot)
        if split_slot == "left_leaf_2"
        else None
    )
    negative_cache = NegativeCertificateCache(
        output_dir / "bilateral_gate_v1" / "negative_certificates.json"
    )
    prior_pair_stats = cumulative.get("persistent_two_run_cache", {})
    for name in ("options_hits", "options_misses", "pair_hits", "pair_misses"):
        if name in prior_pair_stats:
            setattr(pair_cache, name, int(prior_pair_stats[name]))
    index_started = time.time()
    groups, raw_allocations, index_hit = cache.load_or_build_index(values)
    cache.sync_manifest(groups)
    index_seconds = time.time() - index_started
    prefilter_stats = PrefilterStats()
    counts = {
        "groups_total": len(groups),
        "groups_done_before_run": len(done_groups),
        "groups_processed_this_run": 0,
        "groups_completed_total": len(done_groups),
        "middle_contexts_processed": 0,
        "prefilter_context_residual_checks": 0,
        "prefilter_survivors": 0,
        "residual_assignments_processed": 0,
        "contexts_with_left": 0,
        "contexts_with_right": 0,
        "compatible_left_states": 0,
        "compatible_right_states": 0,
        "compatible_terminal_pairs": 0,
        "compatible_span_gt63_pairs": 0,
        "right_compatibility_scans": 0,
        "right_compatibility_scans_skipped_left_empty": 0,
        "lazy_left_queries": 0,
        "lazy_left_nonempty": 0,
        "lazy_left_states": 0,
        "lazy_left_partial_states_visited": 0,
        "lazy_left_occupied_pruned_branches": 0,
        "lazy_left_span_pruned_branches": 0,
        "compiled_left_queries": 0,
        "compiled_left_cache_hits": 0,
        "compiled_left_cache_misses": 0,
        "compiled_left_geometry_states": 0,
        "compiled_left_pair_attempts": 0,
        "compiled_left_output_states": 0,
        "old_cache_queries": 0,
        "compiled_queries": 0,
        "old_cache_hits": 0,
        "compiled_cache_hits": 0,
        "seconds_old_cache": 0.0,
        "seconds_compiled": 0.0,
        "right_support_queries": 0,
        "right_empty_residuals": 0,
        "right_first_groups_skipped": 0,
        "left_queries_avoided": 0,
        "left_queries_executed": 0,
        "bilateral_contexts": 0,
        "outer_edges": 0,
        "negative_certificate_hits": 0,
        "negative_certificate_queries_avoided": 0,
        "positive_witnesses_recorded": 0,
    }
    for key, value in cumulative_counts.items():
        if key not in {"groups_done_before_run", "groups_processed_this_run", "groups_completed_total"}:
            counts[key] = value
    timing = {
        "index_seconds": float(cumulative_timing.get("index_seconds", 0.0)) + index_seconds,
        "middle_group_build_seconds": float(cumulative_timing.get("middle_group_build_seconds", 0.0)),
        "prefilter_seconds": float(cumulative_timing.get("prefilter_seconds", 0.0)),
        "outer_join_seconds": float(cumulative_timing.get("outer_join_seconds", 0.0)),
    }
    minimum_span: int | None = cumulative_minimum if isinstance(cumulative_minimum, int) else None
    minimum_witness: dict[str, object] | None = cumulative_witness if isinstance(cumulative_witness, dict) else None
    minimum_bilateral_eL: int | None = None
    certificate: dict[str, object] | None = None
    stopped = False

    ordered_groups = sorted(groups.items(), key=lambda item: (len(item[1]), item[0]))
    for middle_key, residuals in ordered_groups:
        group_id = cache._group_path(middle_key).stem.replace(".pkl", "").replace("middle_group_", "")
        if group_id in done_groups:
            continue
        if time_limit is not None and time.time() - started >= time_limit:
            stopped = True
            break
        counts["groups_processed_this_run"] += 1
        build_started = time.time()
        group, _cache_hit = cache.load_or_build_group(values, middle_key, residuals)
        timing["middle_group_build_seconds"] += time.time() - build_started
        contexts = tuple(group["contexts"])
        counts["middle_contexts_processed"] += len(contexts)
        if not contexts:
            done_groups.add(group_id)
            counts["groups_completed_total"] += 1
            write_progress(progress_path, fingerprint, done_groups, "RUNNING")
            continue
        right_support_payload = None
        if right_support_cache is not None:
            right_support_payload, _support_cache_hit = right_support_cache.build_or_load(
                group_id, group, pair_cache
            )
            counts["right_support_queries"] += int(right_support_payload["total_context_residual_checks"])
            counts["right_empty_residuals"] += (
                int(right_support_payload["total_context_residual_checks"])
                - int(right_support_payload["supported_pair_count"])
            )
            if not RightSupportCache.group_supported(right_support_payload):
                counts["right_first_groups_skipped"] += 1
                skipped_queries = int(right_support_payload["total_context_residual_checks"])
                counts["residual_assignments_processed"] += skipped_queries
                counts["left_queries_avoided"] += skipped_queries
                done_groups.add(group_id)
                counts["groups_completed_total"] += 1
                write_progress(progress_path, fingerprint, done_groups, "RUNNING")
                continue
        prefilter_started = time.time()
        candidates = prefilter_group(
            group,
            pair_cache,
            prefilter_stats,
            context_envelope=False,
            lazy_left=(split_slot == "left_leaf_2"),
        )
        timing["prefilter_seconds"] += time.time() - prefilter_started
        counts["prefilter_survivors"] += len(candidates)
        # A middle group reuses the same middle context across many residual
        # terminal allocations.  Compatibility depends only on the terminal
        # interval pair and that context, so memoize the exact state scan at
        # this local boundary.  Counts below remain per residual assignment;
        # only the expensive state traversal is shared.
        left_compat_cache: dict[tuple, list[tuple]] = {}
        right_compat_cache: dict[tuple, list[tuple]] = {}
        for candidate in candidates:
            if time_limit is not None and time.time() - started >= time_limit:
                stopped = True
                break
            join_started = time.time()
            context = candidate.context
            residual_key = candidate.residual_key
            delta_left = int(context["delta_left"])
            delta_right = int(context["delta_right"])
            middle_values = tuple(context["all_values"])
            middle_mask = mask_for(middle_values)
            middle_min = min(middle_values)
            middle_max = max(middle_values)
            residual_blocks = dict(residual_key)
            left_key = (
                tuple(residual_blocks["left_leaf_1"]),
                tuple(residual_blocks["left_leaf_2"]),
                int(context["context_id"]),
            )
            left_compatible = left_compat_cache.get(left_key)
            lazy_stats = None
            right_compatible = None
            if right_support_payload is not None:
                support_key = residual_signature(residual_key)
                counts["right_compatibility_scans"] += 1
                if not RightSupportCache.pair_supported(
                    right_support_payload, int(context["context_id"]), support_key
                ):
                    counts["left_queries_avoided"] += 1
                    counts["residual_assignments_processed"] += 1
                    continue
                right_key = (
                    tuple(residual_blocks["right_leaf_1"]),
                    tuple(residual_blocks["right_leaf_2"]),
                    int(context["context_id"]),
                )
                right_compatible = right_compat_cache.get(right_key)
                if right_compatible is None:
                    right_compatible = compatible_states(
                        candidate.right_states, middle_mask, middle_min, middle_max, delta_right
                    )
                    right_compat_cache[right_key] = right_compatible
                if not right_compatible:
                    raise AssertionError("right-support cache disagrees with exact right compatibility")
                if right_compatible:
                    counts["contexts_with_right"] += 1
                counts["compatible_right_states"] += len(right_compatible)
            if left_compatible is None and candidate.lazy_left:
                if hybrid_left_backend is None:
                    raise AssertionError("hybrid left backend is required for left_leaf_2")
                left_intervals = candidate.left_intervals
                if left_intervals is None:
                    raise AssertionError("lazy-left candidate lost its interval key")
                family_key = canonical_family_key(
                    left_intervals[0],
                    left_intervals[1],
                    -delta_left,
                    middle_min,
                    middle_max,
                    True,
                )
                probe = negative_cache.probe(
                    family_key,
                    occupied_offsets_from_mask(middle_mask),
                )
                if probe is not None and probe.get("kind") == "NEGATIVE_CERTIFICATE":
                    left_compatible = []
                    backend_stats = {
                        "backend": "NEGATIVE_CERTIFICATE",
                        "backend_seconds": 0.0,
                        "compiled_query_cache": "CERTIFICATE",
                    }
                    counts["negative_certificate_hits"] += 1
                    counts["negative_certificate_queries_avoided"] += 1
                else:
                    left_compatible, backend_stats = hybrid_left_backend.query(
                        left_intervals[0],
                        left_intervals[1],
                        occupied_mask=middle_mask,
                        left_shift=-delta_left,
                        middle_min=middle_min,
                        middle_max=middle_max,
                        span_mode=True,
                    )
                    if left_compatible:
                        negative_cache.record_positive(
                            family_key,
                            left_compatible[0][0],
                            -delta_left,
                        )
                        counts["positive_witnesses_recorded"] += 1
                    else:
                        full_family, _full_stats = hybrid_left_backend.query(
                            left_intervals[0],
                            left_intervals[1],
                            occupied_mask=0,
                            left_shift=-delta_left,
                            middle_min=middle_min,
                            middle_max=middle_max,
                            span_mode=True,
                        )
                        negative_cache.record_empty(
                            family_key,
                            (item[0] for item in full_family),
                            occupied_offsets_from_mask(middle_mask),
                            -delta_left,
                            max_size=3,
                        )
                backend = backend_stats["backend"]
                if backend == "NEGATIVE_CERTIFICATE":
                    pass
                elif backend == "OLD_CACHED_FILTER":
                    counts["old_cache_queries"] += 1
                    counts["old_cache_hits"] += 1
                    counts["seconds_old_cache"] += float(backend_stats["backend_seconds"])
                else:
                    counts["compiled_queries"] += 1
                    if backend_stats.get("compiled_query_cache") == "HIT":
                        counts["compiled_cache_hits"] += 1
                    counts["seconds_compiled"] += float(backend_stats["backend_seconds"])
                    counts["compiled_left_queries"] += 1
                    if backend_stats.get("compiled_query_cache") == "HIT":
                        counts["compiled_left_cache_hits"] += 1
                    else:
                        counts["compiled_left_cache_misses"] += 1
                    counts["compiled_left_geometry_states"] += int(backend_stats.get("compiled_geometry_states", 0))
                    counts["compiled_left_pair_attempts"] += int(backend_stats.get("pair_attempts", 0))
                if backend != "NEGATIVE_CERTIFICATE":
                    counts["compiled_left_output_states"] += len(left_compatible)
                counts["lazy_left_states"] += len(left_compatible)
                timing["outer_join_seconds"] += float(backend_stats["backend_seconds"])
                left_compat_cache[left_key] = left_compatible
                if backend != "NEGATIVE_CERTIFICATE":
                    counts["left_queries_executed"] += 1
                else:
                    counts["left_queries_avoided"] += 1
            elif left_compatible is None:
                left_compatible = compatible_states(
                    candidate.left_states, middle_mask, middle_min, middle_max, -delta_left
                )
                left_compat_cache[left_key] = left_compatible
            counts["residual_assignments_processed"] += 1
            if left_compatible:
                counts["contexts_with_left"] += 1
            counts["compatible_left_states"] += len(left_compatible)
            if not left_compatible:
                # A full completion needs a left state.  This is an exact
                # necessary-condition short circuit, not a heuristic prune;
                # avoid scanning the often much larger right table when the
                # left family is already empty.
                counts["right_compatibility_scans_skipped_left_empty"] += 1
                timing["outer_join_seconds"] += time.time() - join_started
                continue
            if right_compatible is None:
                counts["right_compatibility_scans"] += 1
                right_key = (
                    tuple(residual_blocks["right_leaf_1"]),
                    tuple(residual_blocks["right_leaf_2"]),
                    int(context["context_id"]),
                )
                right_compatible = right_compat_cache.get(right_key)
                if right_compatible is None:
                    right_compatible = compatible_states(
                        candidate.right_states, middle_mask, middle_min, middle_max, delta_right
                    )
                    right_compat_cache[right_key] = right_compatible
                if right_compatible:
                    counts["contexts_with_right"] += 1
                counts["compatible_right_states"] += len(right_compatible)
            if right_compatible:
                counts["bilateral_contexts"] += 1
                for left_state, _left_mask, _left_low, _left_high in left_compatible:
                    candidate_eL = max(0, -int(left_state.min_value))
                    minimum_bilateral_eL = (
                        candidate_eL
                        if minimum_bilateral_eL is None
                        else min(minimum_bilateral_eL, candidate_eL)
                    )
            for left_state, left_mask, left_low, left_high in left_compatible:
                for right_state, right_mask, right_low, right_high in right_compatible:
                    if time_limit is not None and time.time() - started >= time_limit:
                        stopped = True
                        break
                    if left_mask & right_mask:
                        continue
                    counts["compatible_terminal_pairs"] += 1
                    counts["outer_edges"] += 1
                    span = max(middle_max, left_high, right_high) - min(middle_min, left_low, right_low)
                    if span > EDGE_COUNT:
                        counts["compatible_span_gt63_pairs"] += 1
                    if minimum_span is None or span < minimum_span:
                        minimum_span = span
                        minimum_witness = {
                            "group_id": group_id,
                            "middle_key": middle_key,
                            "context_id": int(context["context_id"]),
                            "residual_key": residual_key,
                            "run_order": candidate.run_order,
                            "delta_left": delta_left,
                            "delta_right": delta_right,
                            "D13": delta_left + delta_right,
                            "span": span,
                            "left_state_id": left_state.state_id,
                            "right_state_id": right_state.state_id,
                        }
                    if span <= EDGE_COUNT:
                        blocks = block_map_for(middle_key, residual_key)
                        allocation = {
                            "split_slot": split_slot,
                            "split_lengths": tuple(end - start + 1 for start, end in blocks[split_slot]),
                            "run_order": candidate.run_order,
                            "blocks": blocks,
                        }
                        labels, relative = build_relative_labels(
                            values, context, left_state, right_state, delta_left, delta_right
                        )
                        verification = verify_c8_labeling(values, allocation, labels)
                        if not verification["verified"]:
                            raise AssertionError(verification)
                        certificate = {
                            "certificate_version": "C8.LevelB.v1",
                            "runner_version": RUNNER_VERSION,
                            "cache_version": TERMINAL_PAIR_CACHE_VERSION,
                            "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
                            "case": case,
                            "split_slot": split_slot,
                            "split_lengths": list(allocation["split_lengths"]),
                            "run_order": list(candidate.run_order),
                            "blocks": {path: [list(interval) for interval in intervals] for path, intervals in blocks.items()},
                            "middle_context": {
                                "context_id": int(context["context_id"]),
                                "delta_left": delta_left,
                                "delta_right": delta_right,
                                "roots_middle_frame": [-delta_left, 0, delta_right],
                                "middle_values": list(middle_values),
                                "middle_min": middle_min,
                                "middle_max": middle_max,
                                "bridge_left_offsets": list(context["bridge"].left_offsets),
                                "bridge_right_offsets": list(context["bridge"].right_offsets),
                                "central_offsets": list(context["central"].offsets),
                            },
                            "left_pair": {
                                "private_middle_frame": [value - delta_left for value in left_state.private],
                                "state_a": {"offsets": list(left_state.state_a.offsets)},
                                "state_b": {"offsets": list(left_state.state_b.offsets)},
                            },
                            "right_pair": {
                                "private_middle_frame": [value + delta_right for value in right_state.private],
                                "state_a": {"offsets": list(right_state.state_a.offsets)},
                                "state_b": {"offsets": list(right_state.state_b.offsets)},
                            },
                            "relative_offsets": {str(vertex): offset for vertex, offset in relative.items()},
                            "labels": labels,
                            "span": span,
                            "verification": verification,
                        }
                        break
                if stopped or certificate is not None:
                    break
            timing["outer_join_seconds"] += time.time() - join_started
            if stopped or certificate is not None:
                break
        if certificate is not None:
            break
        if stopped:
            break
        done_groups.add(group_id)
        counts["groups_completed_total"] += 1
        write_progress(progress_path, fingerprint, done_groups, "RUNNING")

    complete = not stopped and len(done_groups) == len(groups)
    cache.sync_manifest(groups)
    if certificate is not None:
        status = "SAT_VERIFIED"
        (output_dir / "verified_constructions").mkdir(parents=True, exist_ok=True)
        (output_dir / "verified_constructions" / f"{split_slot}.json").write_text(
            json.dumps(certificate, indent=2), encoding="utf-8"
        )
        write_progress(progress_path, fingerprint, done_groups, "SAT")
    elif not complete:
        status = "UNRESOLVED_RESOURCE"
        write_progress(progress_path, fingerprint, done_groups, "PENDING")
    elif counts["compatible_terminal_pairs"]:
        status = "COMPATIBLE_SPAN_GT63"
        write_progress(progress_path, fingerprint, done_groups, "DONE_NO_SAT")
    else:
        status = "UNSAT_EXHAUSTIVE_C8_LEVELB"
        write_progress(progress_path, fingerprint, done_groups, "DONE_NO_SAT")

    write_progress(
        progress_path,
        fingerprint,
        done_groups,
        status,
        {
            "groups_total": len(groups),
            "groups_completed": len(done_groups),
            "groups_discharged_by_adjacent_collapse": 0,
            "groups_searched_genuine": len(done_groups),
            "residual_queries": counts["residual_assignments_processed"],
            "left_existence_queries": counts.get("compiled_left_queries", 0),
            "left_existence_true": counts.get("contexts_with_left", 0),
            "left_existence_false": max(
                0,
                counts["residual_assignments_processed"] - counts.get("contexts_with_left", 0),
            ),
            "lazy_partial_states_visited": counts.get("lazy_left_partial_states_visited", 0),
            "full_local_states_avoided": counts.get("lazy_left_occupied_pruned_branches", 0)
            + counts.get("lazy_left_span_pruned_branches", 0),
            "compiled_geometry_queries": counts.get("compiled_left_queries", 0),
            "compiled_geometry_cache_hits": counts.get("compiled_left_cache_hits", 0),
            "compiled_geometry_cache_misses": counts.get("compiled_left_cache_misses", 0),
            "old_cache_queries": counts.get("old_cache_queries", 0),
            "compiled_queries": counts.get("compiled_queries", 0),
            "old_cache_hits": counts.get("old_cache_hits", 0),
            "compiled_cache_hits": counts.get("compiled_cache_hits", 0),
            "seconds_old_cache": counts.get("seconds_old_cache", 0.0),
            "seconds_compiled": counts.get("seconds_compiled", 0.0),
            "right_support_queries": counts.get("right_support_queries", 0),
            "right_empty_residuals": counts.get("right_empty_residuals", 0),
            "right_first_groups_skipped": counts.get("right_first_groups_skipped", 0),
            "left_queries_avoided": counts.get("left_queries_avoided", 0),
            "left_queries_executed": counts.get("left_queries_executed", 0),
            "negative_certificate_hits": counts.get("negative_certificate_hits", 0),
            "negative_certificate_queries_avoided": counts.get("negative_certificate_queries_avoided", 0),
            "positive_witnesses_recorded": counts.get("positive_witnesses_recorded", 0),
            "bilateral_contexts": counts.get("bilateral_contexts", 0),
            "outer_edges": counts.get("outer_edges", 0),
            "minimum_bilateral_eL": (
                minimum_bilateral_eL if minimum_bilateral_eL is not None else "NONE"
            ),
            "right_first_gate_version": "right-support.v1",
            "primary_left_query_policy": "RIGHT_FIRST_THEN_HYBRID_LEFT",
            "legacy_lazy_fields_are_historical": True,
            "best_span": minimum_span if minimum_span is not None else "NONE",
        },
    )

    for key, value in prefilter_stats.values.items():
        counts[f"prefilter_{key}"] = int(counts.get(f"prefilter_{key}", 0)) + value
    counts["groups_completed_total"] = len(done_groups)
    write_cumulative(
        cumulative_path, fingerprint, counts, timing, minimum_span, minimum_witness, pair_cache.stats()
    )
    elapsed = time.time() - started
    summary = {
        "runner_version": RUNNER_VERSION,
        "case": case,
        "split_slot": split_slot,
        "status": status,
        "complete": complete,
        "raw_C8_allocations": raw_allocations,
        "middle_groups_total": len(groups),
        "middle_groups_done": len(done_groups),
        "allocation_index_cache_hit": index_hit,
        "version_fingerprint": fingerprint,
        "two_run_language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
        "terminal_pair_cache_version": TERMINAL_PAIR_CACHE_VERSION,
        "middle_frame_convention": MIDDLE_FRAME_CONVENTION,
        "prefilter_version": prefilter_version(),
        "counts": counts,
        "timing": timing,
        "minimum_compatible_span": minimum_span if minimum_span is not None else "NONE",
        "minimum_witness": minimum_witness if minimum_witness is not None else "NONE",
        "persistent_middle_cache": cache.stats(),
        "persistent_two_run_cache": pair_cache.stats(),
        "compiled_left_index": compiled_left_index.stats() if compiled_left_index is not None else {},
        "hybrid_left_backend": dict(hybrid_left_backend.stats) if hybrid_left_backend is not None else {},
        "negative_certificate_cache": {
            "path": str(output_dir / "bilateral_gate_v1" / "negative_certificates.json"),
            **negative_cache.stats,
            "version": "left-negative-cert.v1",
        },
        "right_first_gate": {
            "version": "right-support.v1",
            "policy": "RIGHT_FIRST_THEN_HYBRID_LEFT",
            "counts": {
                "right_support_queries": counts.get("right_support_queries", 0),
                "right_empty_residuals": counts.get("right_empty_residuals", 0),
                "right_first_groups_skipped": counts.get("right_first_groups_skipped", 0),
                "left_queries_avoided": counts.get("left_queries_avoided", 0),
                "left_queries_executed": counts.get("left_queries_executed", 0),
                "negative_certificate_hits": counts.get("negative_certificate_hits", 0),
                "negative_certificate_queries_avoided": counts.get("negative_certificate_queries_avoided", 0),
                "positive_witnesses_recorded": counts.get("positive_witnesses_recorded", 0),
                "bilateral_contexts": counts.get("bilateral_contexts", 0),
                "outer_edges": counts.get("outer_edges", 0),
                "minimum_bilateral_eL": (
                    minimum_bilateral_eL if minimum_bilateral_eL is not None else "NONE"
                ),
            },
        },
        "elapsed_seconds": round(elapsed, 3),
        "resource_limited_is_not_unsat": status == "UNRESOLVED_RESOURCE",
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(root / "allocation_prefilter_v1" / "allocation_prefilter_stats.csv", [{
        "case": case,
        "split_slot": split_slot,
        "status": status,
        "version_fingerprint": fingerprint,
        **prefilter_stats.values,
    }])
    write_csv(root / "two_run_local_cache_stats.csv", [{
        "case": case,
        "split_slot": split_slot,
        **pair_cache.stats(),
    }])
    write_csv(root / "performance_profile_v2.csv", [{
        "case": case,
        "split_slot": split_slot,
        "status": status,
        "allocation_index_cache_hit": index_hit,
        **timing,
        "elapsed_seconds": round(elapsed, 3),
        "groups_total": len(groups),
        "groups_done": len(done_groups),
        "prefilter_survivors": len(candidates) if "candidates" in locals() else 0,
    }])
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--split-slot", required=True, choices=sorted(SUPPORTED_SPLIT_SLOTS))
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--output-dir-name", default=None)
    args = parser.parse_args()
    summary = search_case(args.case, args.split_slot, args.root, args.time_limit, args.output_dir_name)
    report = args.root / ("tree1_C8" if "20-9-4-4" in args.case else "tree3_C8") / "gate2_v2_report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n## {summary['split_slot']} / {summary['status']}\n\n"
            f"Language: `C8.LevelB.v1` terminal-split sublanguage; allocation: `ownership.v2`; "
            f"terminal cache: `corrected.v2`. Groups done: {summary['middle_groups_done']}/"
            f"{summary['middle_groups_total']}. Resource-limited runs are not negative results.\n"
        )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
