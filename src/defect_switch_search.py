#!/usr/bin/env python3
"""Search fixed-core tail certificates and build a defect-switch state graph."""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOTS = (54, 40, 53, 21)
UNUSED_LABELS = (
    17,
    19,
    20,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    46,
    52,
)
UNUSED_DIFFERENCES = tuple(range(1, 24))
TAIL_NAMES = ("left", "middle", "right_1", "right_2")

State = tuple[int, int, int, int]
Paths = tuple[tuple[int, ...], ...]
Edge = tuple[int, int]


SEED_WORDS: dict[State, tuple[tuple[int, ...], ...]] = {
    (1, 1, 11, 10): (
        (-19,),
        (-20,),
        (-23, 22, -21, -14, 12, -10, 5, 2, 8, 3, 9),
        (18, -17, 16, -15, 13, -11, 7, -4, -1, 6),
    ),
    (1, 5, 5, 12): (
        (-17,),
        (-23, 22, -20, 19, -18),
        (-21, -8, 2, 7, -4),
        (10, 15, 6, -16, -14, 13, -12, 11, -9, 5, -3, 1),
    ),
    (1, 5, 11, 6): (
        (-17,),
        (-23, 22, -20, 19, -18),
        (-21, -5, 9, 16, -6, -15, -7, 4, -2, 3, 1),
        (14, -13, 12, -11, 10, -8),
    ),
}


@dataclass(frozen=True)
class SearchResult:
    paths: Paths | None
    status: str
    nodes: int
    elapsed: float
    memo_entries: int


class SearchStopped(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def state_name(state: State) -> str:
    return "-".join(map(str, state))


def words_to_paths(
    roots: Sequence[int], words: Sequence[Sequence[int]]
) -> Paths:
    paths: list[tuple[int, ...]] = []
    for root, word in zip(roots, words, strict=True):
        current = root
        labels = [root]
        for signed_difference in word:
            current += signed_difference
            labels.append(current)
        paths.append(tuple(labels))
    return tuple(paths)


def signed_words(paths: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    return tuple(
        tuple(path[index] - path[index - 1] for index in range(1, len(path)))
        for path in paths
    )


def path_edges(paths: Sequence[Sequence[int]]) -> frozenset[Edge]:
    return frozenset(
        tuple(sorted((path[index - 1], path[index])))
        for path in paths
        for index in range(1, len(path))
    )


def verify_tail_certificate(
    roots: Sequence[int],
    labels: Sequence[int],
    differences: Sequence[int],
    lengths: Sequence[int],
    paths: Sequence[Sequence[int]],
) -> tuple[bool, str]:
    if len(paths) != len(roots) or len(lengths) != len(roots):
        return False, "wrong path count"

    new_labels: list[int] = []
    used_differences: list[int] = []
    for index, (root, length, path) in enumerate(
        zip(roots, lengths, paths, strict=True)
    ):
        if not path or path[0] != root:
            return False, f"path {index} has the wrong root"
        if len(path) != length + 1:
            return False, f"path {index} has the wrong length"
        new_labels.extend(path[1:])
        used_differences.extend(
            abs(path[position] - path[position - 1])
            for position in range(1, len(path))
        )

    if len(new_labels) != len(set(new_labels)):
        return False, "a new vertex label is repeated"
    if set(new_labels) != set(labels):
        return False, "new labels do not partition the unused-label set"
    if len(used_differences) != len(set(used_differences)):
        return False, "an edge difference is repeated"
    if set(used_differences) != set(differences):
        return False, "edge differences do not partition the unused set"
    return True, "ok"


def all_states(allow_zero_middle: bool = False) -> list[State]:
    states: list[State] = []
    minimum_middle = 0 if allow_zero_middle else 1
    for middle in range(minimum_middle, 23):
        for right_1 in range(23 - middle):
            right_2 = 22 - middle - right_1
            states.append((1, middle, right_1, right_2))
    return states


def neighboring_states(
    state: State, valid_states: set[State]
) -> list[tuple[State, int, int]]:
    neighbors: list[tuple[State, int, int]] = []
    for source in range(1, 4):
        if state[source] == 0:
            continue
        for target in range(1, 4):
            if source == target:
                continue
            candidate = list(state)
            candidate[source] -= 1
            candidate[target] += 1
            next_state = tuple(candidate)
            if next_state in valid_states:
                neighbors.append((next_state, source, target))
    return sorted(neighbors)


def solve_tail_packing(
    roots: Sequence[int],
    labels: Sequence[int],
    differences: Sequence[int],
    lengths: Sequence[int],
    *,
    time_limit: float | None,
    node_limit: int | None,
    memo_limit: int,
    preferred_edges: Iterable[Edge] = (),
    random_seed: int = 0,
) -> SearchResult:
    if sum(lengths) != len(labels) or len(labels) != len(differences):
        raise ValueError("tail lengths, labels, and differences must have equal size")

    label_values = tuple(labels)
    difference_bits = {value: 1 << index for index, value in enumerate(differences)}
    preferred = {tuple(sorted(edge)) for edge in preferred_edges}
    paths = [[root] for root in roots]
    remaining = list(lengths)
    memo: set[tuple[tuple[int, ...], tuple[int, ...], int, int]] = set()
    started = time.perf_counter()
    nodes = 0
    rng = random.Random(random_seed)

    def check_budget() -> None:
        if node_limit is not None and nodes >= node_limit:
            raise SearchStopped("node_limit")
        if time_limit is not None and time.perf_counter() - started >= time_limit:
            raise SearchStopped("time_limit")

    def legal_moves(path_index: int, label_mask: int, difference_mask: int):
        current = paths[path_index][-1]
        moves: list[tuple[int, int, int, int]] = []
        for label_index, label in enumerate(label_values):
            label_bit = 1 << label_index
            if label_mask & label_bit:
                continue
            difference = abs(current - label)
            difference_bit = difference_bits.get(difference)
            if difference_bit is None or difference_mask & difference_bit:
                continue

            onward = 0
            if remaining[path_index] > 1:
                for next_index, next_label in enumerate(label_values):
                    if next_index == label_index or label_mask & (1 << next_index):
                        continue
                    next_difference = abs(label - next_label)
                    next_bit = difference_bits.get(next_difference)
                    if next_bit is not None and not (
                        difference_mask & next_bit or next_bit == difference_bit
                    ):
                        onward += 1
            edge = tuple(sorted((current, label)))
            moves.append(
                (
                    0 if edge in preferred else 1,
                    onward,
                    rng.randrange(1 << 30),
                    label_index,
                )
            )
        moves.sort()
        return moves

    def search(label_mask: int, difference_mask: int) -> Paths | None:
        nonlocal nodes
        nodes += 1
        if nodes & 1023 == 0:
            check_budget()
        if not any(remaining):
            return tuple(tuple(path) for path in paths)

        key = (
            tuple(path[-1] for path in paths),
            tuple(remaining),
            label_mask,
            difference_mask,
        )
        if key in memo:
            return None

        choices: list[
            tuple[int, int, list[tuple[int, int, int, int]], int]
        ] = []
        for path_index, count in enumerate(remaining):
            if count == 0:
                continue
            moves = legal_moves(path_index, label_mask, difference_mask)
            if not moves:
                if len(memo) < memo_limit:
                    memo.add(key)
                return None
            choices.append((len(moves), -count, moves, path_index))
        _, _, moves, path_index = min(choices, key=lambda item: item[:2])

        current = paths[path_index][-1]
        remaining[path_index] -= 1
        try:
            for _, _, _, label_index in moves:
                label = label_values[label_index]
                difference = abs(current - label)
                paths[path_index].append(label)
                result = search(
                    label_mask | (1 << label_index),
                    difference_mask | difference_bits[difference],
                )
                if result is not None:
                    return result
                paths[path_index].pop()
        finally:
            remaining[path_index] += 1

        if len(memo) < memo_limit:
            memo.add(key)
        return None

    try:
        solution = search(0, 0)
        status = "solved" if solution is not None else "exhausted"
    except SearchStopped as stopped:
        solution = None
        status = stopped.reason
    elapsed = time.perf_counter() - started
    return SearchResult(solution, status, nodes, elapsed, len(memo))


def switch_details(source: Paths, target: Paths) -> dict[str, object]:
    source_edges = path_edges(source)
    target_edges = path_edges(target)
    removed = sorted(source_edges - target_edges)
    added = sorted(target_edges - source_edges)
    source_by_difference = {
        abs(left - right): (left, right) for left, right in source_edges
    }
    target_by_difference = {
        abs(left - right): (left, right) for left, right in target_edges
    }
    signature = []
    for difference in sorted(source_by_difference):
        old_edge = source_by_difference[difference]
        new_edge = target_by_difference[difference]
        if old_edge != new_edge:
            signature.append([difference, list(old_edge), list(new_edge)])
    return {
        "shared_edges": len(source_edges & target_edges),
        "rewrite_size": len(removed),
        "removed_edges": removed,
        "added_edges": added,
        "signature": signature,
    }


STATE_FIELDS = [
    "state",
    "left",
    "middle",
    "right_1",
    "right_2",
    "status",
    "verified",
    "source_state",
    "attempt",
    "nodes",
    "memo_entries",
    "elapsed_seconds",
    "paths",
    "signed_words",
]

SWITCH_FIELDS = [
    "source_state",
    "target_state",
    "moved_from",
    "moved_to",
    "shared_edges",
    "rewrite_size",
    "local",
    "removed_edges",
    "added_edges",
    "signature",
]


def open_csv_append(path: Path, fieldnames: list[str]):
    needs_header = not path.exists() or path.stat().st_size == 0
    stream = path.open("a", encoding="utf-8", newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    if needs_header:
        writer.writeheader()
        stream.flush()
    return stream, writer


def load_state_log(path: Path) -> tuple[dict[State, Paths], dict[State, int]]:
    solutions: dict[State, Paths] = {}
    attempts: dict[State, int] = {}
    if not path.exists():
        return solutions, attempts
    with path.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            state = tuple(int(row[name]) for name in ("left", "middle", "right_1", "right_2"))
            if row.get("attempt"):
                attempts[state] = max(attempts.get(state, 0), int(row["attempt"]))
            if row.get("status") == "solved" and row.get("verified") == "1":
                paths = tuple(tuple(path) for path in json.loads(row["paths"]))
                ok, reason = verify_tail_certificate(
                    ROOTS, UNUSED_LABELS, UNUSED_DIFFERENCES, state, paths
                )
                if not ok:
                    raise ValueError(f"invalid resumed certificate {state}: {reason}")
                solutions[state] = paths
    return solutions, attempts


def load_switch_log(
    path: Path,
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    if not path.exists():
        return set(), set()
    with path.open("r", encoding="utf-8", newline="") as stream:
        keys: set[tuple[str, str]] = set()
        local_keys: set[tuple[str, str]] = set()
        for row in csv.DictReader(stream):
            key = (row["source_state"], row["target_state"])
            keys.add(key)
            if row.get("local") == "1":
                local_keys.add(key)
        return keys, local_keys


def graph_coverage(
    solutions: dict[State, Paths],
    switch_keys: set[tuple[str, str]],
    local_switch_keys: set[tuple[str, str]],
) -> dict[str, object]:
    solved_names = {state_name(state) for state in solutions}

    def component_data(edges: set[tuple[str, str]]):
        adjacency = {name: set() for name in solved_names}
        for left, right in edges:
            if left in adjacency and right in adjacency:
                adjacency[left].add(right)
                adjacency[right].add(left)

        unseen = set(adjacency)
        component_sizes: list[int] = []
        seed_connected: set[str] = set()
        seed_names = {
            state_name(state) for state in SEED_WORDS if state_name(state) in adjacency
        }
        while unseen:
            start = min(unseen)
            component = {start}
            queue = deque([start])
            unseen.remove(start)
            while queue:
                current = queue.popleft()
                for neighbor in adjacency[current]:
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        component.add(neighbor)
                        queue.append(neighbor)
            component_sizes.append(len(component))
            if component & seed_names:
                seed_connected.update(component)
        component_sizes.sort(reverse=True)
        return component_sizes, seed_connected

    component_sizes, seed_connected = component_data(switch_keys)
    local_component_sizes, local_seed_connected = component_data(local_switch_keys)
    return {
        "switch_components": len(component_sizes),
        "largest_switch_component": component_sizes[0] if component_sizes else 0,
        "seed_connected_states": len(seed_connected),
        "local_switch_components": len(local_component_sizes),
        "largest_local_switch_component": local_component_sizes[0]
        if local_component_sizes
        else 0,
        "local_seed_connected_states": len(local_seed_connected),
    }


def state_row(
    state: State,
    status: str,
    paths: Paths | None,
    *,
    source_state: State | None,
    attempt: int,
    nodes: int,
    memo_entries: int,
    elapsed: float,
) -> dict[str, object]:
    verified = 0
    if paths is not None:
        verified = int(
            verify_tail_certificate(
                ROOTS, UNUSED_LABELS, UNUSED_DIFFERENCES, state, paths
            )[0]
        )
    return {
        "state": state_name(state),
        "left": state[0],
        "middle": state[1],
        "right_1": state[2],
        "right_2": state[3],
        "status": status,
        "verified": verified,
        "source_state": "" if source_state is None else state_name(source_state),
        "attempt": attempt,
        "nodes": nodes,
        "memo_entries": memo_entries,
        "elapsed_seconds": f"{elapsed:.6f}",
        "paths": "" if paths is None else json.dumps(paths, separators=(",", ":")),
        "signed_words": ""
        if paths is None
        else json.dumps(signed_words(paths), separators=(",", ":")),
    }


def write_summary(
    path: Path,
    *,
    total_states: int,
    solutions: dict[State, Paths],
    attempts: dict[State, int],
    switch_keys: set[tuple[str, str]],
    local_switch_keys: set[tuple[str, str]],
    started: float,
) -> None:
    payload = {
        "fixed_core_edges": 39,
        "tail_edges": 23,
        "roots": ROOTS,
        "unused_labels": UNUSED_LABELS,
        "unused_differences": UNUSED_DIFFERENCES,
        "total_states": total_states,
        "solved_states": len(solutions),
        "unresolved_states": total_states - len(solutions),
        "states_attempted": len(attempts),
        "switches": len(switch_keys),
        "local_switches": len(local_switch_keys),
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }
    payload.update(graph_coverage(solutions, switch_keys, local_switch_keys))
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    states_path = output_dir / "states.csv"
    switches_path = output_dir / "switches.csv"
    summary_path = output_dir / "summary.json"
    if not args.resume and (states_path.exists() or switches_path.exists()):
        raise SystemExit(
            f"output already exists under {output_dir}; use --resume or a new directory"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    valid = all_states(args.allow_zero_middle)
    valid_set = set(valid)
    solutions, attempts = load_state_log(states_path) if args.resume else ({}, {})
    if args.resume:
        switch_keys, local_switch_keys = load_switch_log(switches_path)
    else:
        switch_keys, local_switch_keys = set(), set()
    state_stream, state_writer = open_csv_append(states_path, STATE_FIELDS)
    switch_stream, switch_writer = open_csv_append(switches_path, SWITCH_FIELDS)
    started = time.perf_counter()
    searches = 0

    def add_switch(
        source_state: State,
        target_state: State,
        moved_from: int,
        moved_to: int,
    ) -> None:
        key = (state_name(source_state), state_name(target_state))
        reverse_key = (key[1], key[0])
        if key in switch_keys or reverse_key in switch_keys:
            return
        details = switch_details(solutions[source_state], solutions[target_state])
        is_local = int(details["rewrite_size"] <= args.local_rewrite_threshold)
        switch_writer.writerow(
            {
                "source_state": key[0],
                "target_state": key[1],
                "moved_from": TAIL_NAMES[moved_from],
                "moved_to": TAIL_NAMES[moved_to],
                "shared_edges": details["shared_edges"],
                "rewrite_size": details["rewrite_size"],
                "local": is_local,
                "removed_edges": json.dumps(details["removed_edges"], separators=(",", ":")),
                "added_edges": json.dumps(details["added_edges"], separators=(",", ":")),
                "signature": json.dumps(details["signature"], separators=(",", ":")),
            }
        )
        switch_stream.flush()
        switch_keys.add(key)
        if is_local:
            local_switch_keys.add(key)

    try:
        for seed_state, words in SEED_WORDS.items():
            if seed_state not in valid_set or seed_state in solutions:
                continue
            paths = words_to_paths(ROOTS, words)
            ok, reason = verify_tail_certificate(
                ROOTS, UNUSED_LABELS, UNUSED_DIFFERENCES, seed_state, paths
            )
            if not ok:
                raise RuntimeError(f"invalid built-in seed {seed_state}: {reason}")
            solutions[seed_state] = paths
            state_writer.writerow(
                state_row(
                    seed_state,
                    "solved",
                    paths,
                    source_state=None,
                    attempt=0,
                    nodes=0,
                    memo_entries=0,
                    elapsed=0.0,
                )
            )
            state_stream.flush()

        for source_state in sorted(solutions):
            for target_state, moved_from, moved_to in neighboring_states(
                source_state, valid_set
            ):
                if target_state in solutions:
                    add_switch(source_state, target_state, moved_from, moved_to)

        if args.seed_only:
            write_summary(
                summary_path,
                total_states=len(valid),
                solutions=solutions,
                attempts=attempts,
                switch_keys=switch_keys,
                local_switch_keys=local_switch_keys,
                started=started,
            )
            print(f"seed certificates verified: {len(solutions)}")
            print(f"output: {output_dir}")
            return 0

        queue = deque(sorted(solutions))
        processed_sources: set[State] = set()
        attempted_pairs: set[tuple[State, State]] = set()

        def limits_reached() -> bool:
            if args.max_searches is not None and searches >= args.max_searches:
                return True
            return bool(
                args.total_time_limit is not None
                and time.perf_counter() - started >= args.total_time_limit
            )

        def attempt_target(target: State, source: State | None) -> bool:
            nonlocal searches
            if target in solutions or attempts.get(target, 0) >= args.max_attempts_per_state:
                return False
            if limits_reached():
                return False
            attempt = attempts.get(target, 0) + 1
            attempts[target] = attempt
            searches += 1
            preferred = () if source is None else path_edges(solutions[source])
            state_code = target[1] * 10000 + target[2] * 100 + target[3]
            result = solve_tail_packing(
                ROOTS,
                UNUSED_LABELS,
                UNUSED_DIFFERENCES,
                target,
                time_limit=args.time_limit,
                node_limit=args.node_limit,
                memo_limit=args.memo_limit,
                preferred_edges=preferred,
                random_seed=args.random_seed + state_code + attempt * 1000003,
            )
            paths = result.paths
            if paths is not None:
                ok, reason = verify_tail_certificate(
                    ROOTS, UNUSED_LABELS, UNUSED_DIFFERENCES, target, paths
                )
                if not ok:
                    raise RuntimeError(f"solver produced an invalid certificate: {reason}")
                solutions[target] = paths
            state_writer.writerow(
                state_row(
                    target,
                    result.status,
                    paths,
                    source_state=source,
                    attempt=attempt,
                    nodes=result.nodes,
                    memo_entries=result.memo_entries,
                    elapsed=result.elapsed,
                )
            )
            state_stream.flush()
            if paths is not None:
                queue.append(target)
                for neighbor, moved_from, moved_to in neighboring_states(target, valid_set):
                    if neighbor in solutions:
                        add_switch(target, neighbor, moved_from, moved_to)
            if args.progress and (searches == 1 or searches % args.progress == 0):
                elapsed = time.perf_counter() - started
                print(
                    f"searches={searches}, solved_states={len(solutions)}/{len(valid)}, "
                    f"switches={len(switch_keys)}, elapsed={elapsed:.1f}s",
                    flush=True,
                )
            return paths is not None

        while not limits_reached():
            while queue and not limits_reached():
                source = queue.popleft()
                if source in processed_sources:
                    continue
                processed_sources.add(source)
                for target, _, _ in neighboring_states(source, valid_set):
                    pair = (source, target)
                    if target in solutions or pair in attempted_pairs:
                        continue
                    attempted_pairs.add(pair)
                    attempt_target(target, source)
                    if limits_reached():
                        break

            if not args.scan_all or limits_reached():
                break
            target = next(
                (
                    state
                    for state in valid
                    if state not in solutions
                    and attempts.get(state, 0) < args.max_attempts_per_state
                ),
                None,
            )
            if target is None:
                break
            attempt_target(target, None)

        write_summary(
            summary_path,
            total_states=len(valid),
            solutions=solutions,
            attempts=attempts,
            switch_keys=switch_keys,
            local_switch_keys=local_switch_keys,
            started=started,
        )
    finally:
        state_stream.close()
        switch_stream.close()

    elapsed = time.perf_counter() - started
    print(
        f"complete: solved_states={len(solutions)}/{len(valid)}, "
        f"switches={len(switch_keys)}, searches={searches}, elapsed={elapsed:.3f}s"
    )
    print(f"states: {states_path}")
    print(f"switches: {switches_path}")
    print(f"summary: {summary_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="results/defect_switch_62")
    parser.add_argument("--time-limit", type=float, default=2.0)
    parser.add_argument("--node-limit", type=int, default=2_000_000)
    parser.add_argument("--total-time-limit", type=float)
    parser.add_argument("--memo-limit", type=int, default=500_000)
    parser.add_argument("--max-attempts-per-state", type=int, default=3)
    parser.add_argument("--max-searches", type=int)
    parser.add_argument("--local-rewrite-threshold", type=int, default=8)
    parser.add_argument("--random-seed", type=int, default=20260820)
    parser.add_argument("--progress", type=int, default=10)
    parser.add_argument("--scan-all", action="store_true")
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--allow-zero-middle", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
