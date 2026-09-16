"""Allocation utilities for the C8 exactly-one-split language.

An allocation is an ordered partition of 1..63 into eight nonempty
consecutive runs.  Six path slots own one run and one selected path slot owns
the two runs.  The two runs of the split path are ordered by their position
on the difference axis; they are not treated as two independent graph paths.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from typing import Iterable

from edge63_displacement_first_compact import EDGE_COUNT, PATHS, path_lengths


LANGUAGE_VERSION = "C8.LevelB.v1"
ALLOCATION_DEDUP_VERSION = "ownership.v2"


def split_tokens(split_slot: str) -> tuple[str, ...]:
    if split_slot not in PATHS:
        raise ValueError(split_slot)
    return tuple(f"{split_slot}__run_{index}" for index in (1, 2))


def allocation_from_tokens(
    path_lengths_map: dict[str, int],
    split_slot: str,
    first_run_length: int,
    token_order: tuple[str, ...],
) -> dict[str, object]:
    split_length = path_lengths_map[split_slot]
    if not 1 <= first_run_length < split_length:
        raise ValueError("invalid split length")
    second_run_length = split_length - first_run_length
    run_lengths = {path: path_lengths_map[path] for path in PATHS if path != split_slot}
    run_lengths.update({split_tokens(split_slot)[0]: first_run_length, split_tokens(split_slot)[1]: second_run_length})
    start = 1
    blocks: dict[str, tuple[tuple[int, int], ...]] = defaultdict(tuple)
    for token in token_order:
        length = run_lengths[token]
        block = (start, start + length - 1)
        if token.startswith(split_slot + "__run_"):
            blocks[split_slot] = (*blocks[split_slot], block)
        else:
            blocks[token] = (block,)
        start += length
    if start != EDGE_COUNT + 1:
        raise ValueError("path lengths do not sum to edge count")
    return {
        "split_slot": split_slot,
        "split_lengths": (first_run_length, second_run_length),
        "run_order": token_order,
        "blocks": dict(blocks),
    }


def iter_allocations(values: tuple[int, ...], split_slot: str) -> Iterable[dict[str, object]]:
    """Yield every raw C8 allocation for one split slot."""
    lengths = path_lengths(values)
    tokens = [path for path in PATHS if path != split_slot]
    split_a, split_b = split_tokens(split_slot)
    tokens.extend((split_a, split_b))
    # For equal split lengths, only swapping the two runs owned by the split
    # path is a duplicate.  The other path slots remain distinguishable even
    # when their lengths happen to agree, so the full ownership map belongs in
    # the deduplication key.
    seen_equal_split_allocations: set[tuple] = set()
    for first_length in range(1, lengths[split_slot]):
        for token_order in itertools.permutations(tokens):
            allocation = allocation_from_tokens(lengths, split_slot, first_length, token_order)
            if first_length * 2 == lengths[split_slot]:
                block_map = allocation["blocks"]
                allocation_key = tuple(
                    (path, tuple(sorted(block_map[path])) if path == split_slot else tuple(block_map[path]))
                    for path in PATHS
                )
                if allocation_key in seen_equal_split_allocations:
                    continue
                seen_equal_split_allocations.add(allocation_key)
            yield allocation


def allocation_count(values: tuple[int, ...], split_slot: str) -> int:
    lengths = path_lengths(values)
    split_length = lengths[split_slot]
    equal_split_correction = 20160 if split_length % 2 == 0 else 0
    return (split_length - 1) * 40320 - equal_split_correction


def allocation_summary(values: tuple[int, ...], split_slot: str) -> dict[str, object]:
    lengths = path_lengths(values)
    return {
        "split_slot": split_slot,
        "split_path_length": lengths[split_slot],
        "split_length_choices": lengths[split_slot] - 1,
        "run_order_count_per_split": 40320,
        "equal_split_run_order_count": 20160,
        "raw_C8_allocations": allocation_count(values, split_slot),
        "automorphism_quotient": "not applied",
        "language": LANGUAGE_VERSION,
        "allocation_dedup_version": ALLOCATION_DEDUP_VERSION,
    }


def allocation_order_text(allocation: dict[str, object]) -> str:
    return ",".join(str(token) for token in allocation["run_order"])


def block_texts(allocation: dict[str, object]) -> dict[str, str]:
    return {
        path: ";".join(f"{start}-{end}" for start, end in blocks)
        for path, blocks in allocation["blocks"].items()
    }
