"""Full-scope exact closure runner for Tree1 C8 left_leaf_2.

This runner owns only coverage indexing and exact table/family semantic
processing. It reuses the existing native geometry backend and the existing
Python semantic evaluator. It never invokes the sequential left runner.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from edge63_C8_collision_signature import _family_id, _process_family
from edge63_C8_compiled_terminal_index import CompiledTerminalPairIndex
from edge63_C8_left_negative_cert_cache import canonical_family_key
from edge63_C8_middle_group_cache import canonical_json
from edge63_C8_native_geometry_cache import NativeCompiledGeometryCache
from edge63_C8_outer_zero_audit import _audit_source
from edge63_C8_two_run_cache import PersistentTwoRunCache
from edge63_C8_displacement_first import values_for_case
from edge63_C8_middle_group_cache import PersistentMiddleGroupCache


CASE = "fiveleaf3e-63-3-21-2-20-9-4-4"
SLOT = "left_leaf_2"
LANGUAGE = "C8.LevelB.v1"
OWNERSHIP = "ownership.v2"
TERMINAL_CACHE = "corrected.v2"

ROOT_REL = Path("tree1_C8") / "left_leaf_2_full_slot_closure_v1"
INDEX_NAME = "full_slot_query_index.sqlite"
TABLE_FIELDS = (
    "table_key",
    "table_key_payload",
    "intervals_a",
    "intervals_b",
    "table_status",
    "active_queries",
)


def _versions() -> dict[str, str]:
    return {
        "two_run_language": LANGUAGE,
        "allocation_dedup_version": OWNERSHIP,
        "terminal_pair_cache_version": TERMINAL_CACHE,
    }


def _json_intervals(raw: str) -> tuple[tuple[int, int], ...]:
    return tuple(tuple(int(value) for value in part) for part in json.loads(raw))


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _manifest_rows(root: Path) -> list[dict[str, str]]:
    path = root / "tree1_C8" / "left_leaf_2_exact_v3" / "frontier_directed_v1" / "table_completion_manifest.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _worklist_path(root: Path) -> Path:
    return root / "tree1_C8" / "left_leaf_2_exact_v3" / "full_right_support_v1" / "right_supported_residual_worklist_full.csv"


def _db_path(out: Path) -> Path:
    return out / INDEX_NAME


def _init_db(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tables_expected (
            table_key TEXT PRIMARY KEY,
            table_key_payload TEXT NOT NULL,
            intervals_a TEXT NOT NULL,
            intervals_b TEXT NOT NULL,
            table_status TEXT NOT NULL,
            active_queries INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS families (
            family_id TEXT PRIMARY KEY,
            table_key TEXT NOT NULL,
            family_key TEXT NOT NULL,
            raw_rows INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_families_table ON families(table_key);
        CREATE TABLE IF NOT EXISTS queries (
            family_id TEXT NOT NULL,
            occupied_json TEXT NOT NULL,
            group_id TEXT NOT NULL,
            context_id INTEGER NOT NULL,
            residual_index INTEGER NOT NULL,
            residual_signature TEXT NOT NULL,
            PRIMARY KEY (family_id, occupied_json)
        );
        CREATE INDEX IF NOT EXISTS idx_queries_family ON queries(family_id);
        CREATE TABLE IF NOT EXISTS table_state (
            table_key TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            outcome TEXT,
            rows_seen INTEGER NOT NULL DEFAULT 0,
            family_count INTEGER NOT NULL DEFAULT 0,
            exact_query_count INTEGER NOT NULL DEFAULT 0,
            empty_queries INTEGER NOT NULL DEFAULT 0,
            positive_queries INTEGER NOT NULL DEFAULT 0,
            local_behavior_count INTEGER,
            minimum_kappa INTEGER,
            best_pre_outer_span INTEGER,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS family_state (
            family_id TEXT PRIMARY KEY,
            table_key TEXT NOT NULL,
            status TEXT NOT NULL,
            behavior_count INTEGER NOT NULL DEFAULT 0,
            exact_query_count INTEGER NOT NULL DEFAULT 0,
            empty_queries INTEGER NOT NULL DEFAULT 0,
            positive_queries INTEGER NOT NULL DEFAULT 0,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS semantic_results (
            family_id TEXT NOT NULL,
            occupied_json TEXT NOT NULL,
            semantic_signature_id TEXT NOT NULL,
            blocked_mask_hex TEXT NOT NULL,
            allowed_mask_hex TEXT NOT NULL,
            allowed_count INTEGER NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (family_id, occupied_json)
        );
        CREATE INDEX IF NOT EXISTS idx_semantic_positive ON semantic_results(status);
        CREATE TABLE IF NOT EXISTS positive_sources (
            family_id TEXT NOT NULL,
            occupied_json TEXT NOT NULL,
            group_id TEXT NOT NULL,
            context_id INTEGER NOT NULL,
            residual_index INTEGER NOT NULL,
            residual_signature TEXT NOT NULL,
            PRIMARY KEY (family_id, occupied_json, group_id, context_id, residual_index)
        );
        CREATE TABLE IF NOT EXISTS outer_results (
            family_id TEXT NOT NULL,
            occupied_json TEXT NOT NULL,
            group_id TEXT NOT NULL,
            context_id INTEGER NOT NULL,
            residual_index INTEGER NOT NULL,
            status TEXT NOT NULL,
            outer_edges INTEGER NOT NULL DEFAULT 0,
            minimum_outer_edge_span INTEGER,
            minimum_pre_outer_span INTEGER,
            minimum_kappa INTEGER,
            error TEXT
        );
        """
    )
    db.commit()


def _build_index(root: Path, out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    target = _db_path(out)
    if target.exists():
        with sqlite3.connect(target) as db:
            _init_db(db)
            complete = db.execute("SELECT value FROM meta WHERE key='index_status'").fetchone()
            if complete and complete[0] == "COMPLETE":
                return _index_stats(db)
        target.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            target.with_name(target.name + suffix).unlink(missing_ok=True)

    manifest = _manifest_rows(root)
    by_intervals_b = {}
    with sqlite3.connect(target) as db:
        _init_db(db)
        db.executemany(
            "INSERT INTO tables_expected(table_key,table_key_payload,intervals_a,intervals_b,table_status,active_queries) VALUES(?,?,?,?,?,0)",
            [
                (
                    row["table_key"],
                    row["table_key_payload"],
                    row["intervals_a"],
                    row["intervals_b"],
                    row.get("table_status", ""),
                )
                for row in manifest
            ],
        )
        for row in manifest:
            by_intervals_b[row["intervals_b"]] = row["table_key"]

        worklist = _worklist_path(root)
        rows_seen = 0
        family_raw_counts: Counter[str] = Counter()
        family_insert = []
        query_insert = []
        started = time.perf_counter()
        with worklist.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                pair = json.loads(row["left_two_run_interval_pair"])
                intervals_a = tuple(tuple(int(v) for v in part) for part in pair[0])
                intervals_b = tuple(tuple(int(v) for v in part) for part in pair[1])
                intervals_b_json = json.dumps([list(part) for part in intervals_b], separators=(",", ":"))
                table_key = by_intervals_b.get(intervals_b_json)
                if table_key is None:
                    raise RuntimeError(f"worklist interval has no expected table: {intervals_b_json}")
                frame = json.loads(row["left_root_frame"])
                family_key = canonical_family_key(
                    intervals_a,
                    intervals_b,
                    int(frame["left_shift"]),
                    int(row["middle_min"]),
                    int(row["middle_max"]),
                    True,
                )
                family_id = _family_id(family_key)
                family_raw_counts[family_id] += 1
                family_insert.append((family_id, table_key, family_key))
                occupied = json.dumps(
                    sorted(int(value) for value in json.loads(row["occupied_left_offset_set"])),
                    separators=(",", ":"),
                )
                query_insert.append((
                    family_id,
                    occupied,
                    row["group_id"],
                    int(row["context_id"]),
                    int(row["residual_index"]),
                    row["residual_signature"],
                ))
                rows_seen += 1
                if len(query_insert) >= 50000:
                    db.executemany(
                        "INSERT OR IGNORE INTO families(family_id,table_key,family_key) VALUES(?,?,?)",
                        family_insert,
                    )
                    db.executemany(
                        "INSERT OR IGNORE INTO queries(family_id,occupied_json,group_id,context_id,residual_index,residual_signature) VALUES(?,?,?,?,?,?)",
                        query_insert,
                    )
                    db.commit()
                    family_insert.clear()
                    query_insert.clear()
        if family_insert:
            db.executemany(
                "INSERT OR IGNORE INTO families(family_id,table_key,family_key) VALUES(?,?,?)",
                family_insert,
            )
        if query_insert:
            db.executemany(
                "INSERT OR IGNORE INTO queries(family_id,occupied_json,group_id,context_id,residual_index,residual_signature) VALUES(?,?,?,?,?,?)",
                query_insert,
            )
        db.executemany(
            "UPDATE families SET raw_rows=? WHERE family_id=?",
            [(count, family_id) for family_id, count in family_raw_counts.items()],
        )
        db.execute(
            "UPDATE tables_expected SET active_queries=(SELECT COUNT(*) FROM families f JOIN queries q ON q.family_id=f.family_id WHERE f.table_key=tables_expected.table_key)"
        )
        db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('index_status','COMPLETE')")
        db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('worklist_rows',?)", (str(rows_seen),))
        db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('manifest_tables',?)", (str(len(manifest)),))
        db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('built_seconds',?)", (str(time.perf_counter() - started),))
        db.commit()
        return _index_stats(db)


def _index_stats(db: sqlite3.Connection) -> dict[str, Any]:
    def one(sql: str) -> int:
        return int(db.execute(sql).fetchone()[0])
    return {
        "status": db.execute("SELECT value FROM meta WHERE key='index_status'").fetchone()[0],
        "worklist_rows": one("SELECT value FROM meta WHERE key='worklist_rows'"),
        "tables": one("SELECT COUNT(*) FROM tables_expected"),
        "families": one("SELECT COUNT(*) FROM families"),
        "distinct_exact_queries": one("SELECT COUNT(*) FROM queries"),
        "family_raw_rows": one("SELECT COALESCE(SUM(raw_rows),0) FROM families"),
    }


def _native_cache(root: Path, out: Path) -> NativeCompiledGeometryCache:
    production = root / "native_engine_v1" / "production_full_v1" / "native_tables"
    executable = production / "edge63_C8_table_engine.exe"
    source_root = production if production.exists() else None
    return NativeCompiledGeometryCache(
        root,
        CASE,
        SLOT,
        executable=executable if executable.exists() else None,
        cache_root=out / "native_tables",
        source_root=source_root,
    )


class _NoopClearDict(dict):
    """Keep a worker's table object resident across family evaluations."""

    def clear(self) -> None:
        return None


class _StickyGeometryCache:
    """Read-through wrapper whose table lifetime is one semantic worker."""

    def __init__(self, base: NativeCompiledGeometryCache):
        self.base = base
        self.backend_name = getattr(base, "backend_name", "native")
        self.mem = _NoopClearDict()

    def get(self, intervals: tuple[tuple[int, int], ...], role: str = "terminal"):
        return self.base.get(intervals, role)

    def __getattr__(self, name: str):
        return getattr(self.base, name)


def _compile_one(payload: tuple[str, str, str, str]) -> dict[str, Any]:
    root_text, out_text, table_key, intervals_b = payload
    root = Path(root_text)
    out = Path(out_text)
    intervals = _json_intervals(intervals_b)
    cache = _native_cache(root, out)
    started = time.perf_counter()
    compiled = cache.get(intervals, "terminal")
    path = cache._path(intervals, "terminal")
    return {
        "table_key": table_key,
        "intervals_b": intervals_b,
        "behavior_count": len(compiled.records),
        "compile_seconds": round(time.perf_counter() - started, 6),
        "checksum": compiled.checksum,
        "cache_bytes": path.stat().st_size if path.exists() else 0,
        "status": "COMPILED",
        **_versions(),
    }


def _ensure_runtime_tables(db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT OR IGNORE INTO table_state(table_key,status) SELECT table_key,'PENDING' FROM tables_expected"
    )
    db.commit()


def _family_rows(db: sqlite3.Connection, table_key: str) -> list[tuple[str, str]]:
    return list(db.execute(
        "SELECT family_id,family_key FROM families WHERE table_key=? ORDER BY family_id",
        (table_key,),
    ))


def _query_rows(db: sqlite3.Connection, family_id: str) -> list[dict[str, Any]]:
    return [
        {
            "occupied_values_parsed": frozenset(int(value) for value in json.loads(row[0])),
            "occupied_json": row[0],
            "source": {
                "group_id": row[1],
                "context_id": int(row[2]),
                "residual_index": int(row[3]),
                "residual_signature": row[4],
            },
        }
        for row in db.execute(
            "SELECT occupied_json,group_id,context_id,residual_index,residual_signature FROM queries WHERE family_id=? ORDER BY occupied_json",
            (family_id,),
        )
    ]


def _evaluate_table(root: Path, out: Path, db: sqlite3.Connection, table_key: str, compile_row: dict[str, Any]) -> dict[str, Any]:
    table_row = db.execute(
        "SELECT table_key_payload,intervals_b,active_queries FROM tables_expected WHERE table_key=?",
        (table_key,),
    ).fetchone()
    intervals_b = _json_intervals(table_row[1])
    cache = _native_cache(root, out)
    index = CompiledTerminalPairIndex(root, CASE, SLOT, geometry_cache=cache)
    pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
    total_queries = 0
    total_empty = 0
    total_positive = 0
    total_families = 0
    behavior_count = len(cache.get(intervals_b, "terminal").records)
    family_summaries = []
    semantic_rows = []
    for family_id, family_key in _family_rows(db, table_key):
        state = db.execute("SELECT status FROM family_state WHERE family_id=?", (family_id,)).fetchone()
        if state and state[0] == "SEMANTIC_DONE":
            continue
        rows = _query_rows(db, family_id)
        query_rows = [{"occupied_values_parsed": item["occupied_values_parsed"]} for item in rows]
        signatures, _effect, details = _process_family(pair_cache, index, family_key, query_rows, {})
        family_query_count = len(rows)
        family_empty = sum(int(sig["query_count"]) for sig in signatures if int(sig["allowed_count"]) == 0)
        family_positive = family_query_count - family_empty
        total_queries += family_query_count
        total_empty += family_empty
        total_positive += family_positive
        total_families += 1
        family_summaries.append((family_id, table_key, "SEMANTIC_DONE", int(details["behaviors"]), family_query_count, family_empty, family_positive, None))
        for effect_row in details["query_effect_rows"]:
            occupied_json = effect_row["occupied_values"]
            semantic_rows.append((
                family_id,
                occupied_json,
                effect_row["semantic_signature_id"],
                effect_row["blocked_mask_hex"],
                effect_row["allowed_mask_hex"],
                int(effect_row["allowed_count"]),
                "POSITIVE" if int(effect_row["allowed_count"]) > 0 else "EMPTY",
            ))
        if len(semantic_rows) >= 50000:
            db.executemany(
                "INSERT OR REPLACE INTO semantic_results(family_id,occupied_json,semantic_signature_id,blocked_mask_hex,allowed_mask_hex,allowed_count,status) VALUES(?,?,?,?,?,?,?)",
                semantic_rows,
            )
            db.executemany(
                "INSERT OR REPLACE INTO family_state(family_id,table_key,status,behavior_count,exact_query_count,empty_queries,positive_queries,error) VALUES(?,?,?,?,?,?,?,?)",
                family_summaries,
            )
            db.commit()
            semantic_rows.clear()
            family_summaries.clear()
    if semantic_rows:
        db.executemany(
            "INSERT OR REPLACE INTO semantic_results(family_id,occupied_json,semantic_signature_id,blocked_mask_hex,allowed_mask_hex,allowed_count,status) VALUES(?,?,?,?,?,?,?)",
            semantic_rows,
        )
    if family_summaries:
        db.executemany(
            "INSERT OR REPLACE INTO family_state(family_id,table_key,status,behavior_count,exact_query_count,empty_queries,positive_queries,error) VALUES(?,?,?,?,?,?,?,?)",
            family_summaries,
        )
    db.commit()
    outcome = "LOCAL_EMPTY" if behavior_count == 0 else ("ALL_QUERIES_EMPTY" if total_positive == 0 else "HAS_BILATERAL_OUTER_ZERO")
    db.execute(
        "INSERT OR REPLACE INTO table_state(table_key,status,outcome,rows_seen,family_count,exact_query_count,empty_queries,positive_queries,local_behavior_count,error) VALUES(?,?,?,?,?,?,?,?,?,NULL)",
        (table_key, "SEMANTIC_DONE", outcome, 0, total_families, total_queries, total_empty, total_positive, behavior_count),
    )
    db.commit()
    return {
        "table_key": table_key,
        "status": "SEMANTIC_DONE",
        "outcome": outcome,
        "family_count": total_families,
        "exact_query_count": total_queries,
        "empty_queries": total_empty,
        "positive_queries": total_positive,
        "local_behavior_count": behavior_count,
        "compile_seconds": compile_row.get("compile_seconds"),
        "compile_behavior_count": compile_row.get("behavior_count"),
        **_versions(),
    }


def _table_part_path(out: Path, table_key: str) -> Path:
    return out / "table_parts" / f"{table_key}.jsonl"


def _evaluate_table_part(payload: tuple[str, str, str, str, dict[str, Any]]) -> dict[str, Any]:
    """Evaluate one table in an isolated worker and publish an atomic JSONL part."""
    root_text, out_text, db_path_text, table_key, compile_row = payload
    root = Path(root_text)
    out = Path(out_text)
    db_path = Path(db_path_text)
    target = _table_part_path(out, table_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    total_queries = 0
    total_empty = 0
    total_positive = 0
    total_families = 0
    behavior_count = int(compile_row.get("behavior_count", 0))
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            table_row = db.execute(
                "SELECT intervals_b FROM tables_expected WHERE table_key=?",
                (table_key,),
            ).fetchone()
            if table_row is None:
                raise RuntimeError(f"missing table metadata: {table_key}")
            intervals_b = _json_intervals(table_row[0])
            cache = _StickyGeometryCache(_native_cache(root, out))
            index = CompiledTerminalPairIndex(root, CASE, SLOT, geometry_cache=cache)
            pair_cache = PersistentTwoRunCache(root, CASE, SLOT)
            behavior_count = len(cache.get(intervals_b, "terminal").records)
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                for family_id, family_key in _family_rows(db, table_key):
                    state = db.execute(
                        "SELECT status FROM family_state WHERE family_id=?",
                        (family_id,),
                    ).fetchone()
                    if state and state[0] == "SEMANTIC_DONE":
                        continue
                    rows = _query_rows(db, family_id)
                    query_rows = [{"occupied_values_parsed": item["occupied_values_parsed"]} for item in rows]
                    signatures, _effect, details = _process_family(pair_cache, index, family_key, query_rows, {})
                    family_query_count = len(rows)
                    family_empty = sum(
                        int(sig["query_count"])
                        for sig in signatures
                        if int(sig["allowed_count"]) == 0
                    )
                    family_positive = family_query_count - family_empty
                    total_queries += family_query_count
                    total_empty += family_empty
                    total_positive += family_positive
                    total_families += 1
                    handle.write(json.dumps({
                        "type": "family",
                        "family_id": family_id,
                        "table_key": table_key,
                        "status": "SEMANTIC_DONE",
                        "behavior_count": int(details["behaviors"]),
                        "exact_query_count": family_query_count,
                        "empty_queries": family_empty,
                        "positive_queries": family_positive,
                    }, separators=(",", ":")) + "\n")
                    for effect_row in details["query_effect_rows"]:
                        allowed_count = int(effect_row["allowed_count"])
                        handle.write(json.dumps({
                            "type": "semantic",
                            "family_id": family_id,
                            "occupied_json": effect_row["occupied_values"],
                            "semantic_signature_id": effect_row["semantic_signature_id"],
                            "blocked_mask_hex": effect_row["blocked_mask_hex"],
                            "allowed_mask_hex": effect_row["allowed_mask_hex"],
                            "allowed_count": allowed_count,
                            "status": "POSITIVE" if allowed_count > 0 else "EMPTY",
                        }, separators=(",", ":")) + "\n")
                summary = {
                    "type": "summary",
                    "table_key": table_key,
                    "status": "SEMANTIC_DONE",
                    "family_count": total_families,
                    "exact_query_count": total_queries,
                    "empty_queries": total_empty,
                    "positive_queries": total_positive,
                    "local_behavior_count": behavior_count,
                    "compile_seconds": compile_row.get("compile_seconds"),
                    "compile_behavior_count": compile_row.get("behavior_count"),
                    **_versions(),
                }
                handle.write(json.dumps(summary, separators=(",", ":")) + "\n")
        os.replace(tmp, target)
        return summary
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _merge_table_part(db: sqlite3.Connection, part_path: Path) -> dict[str, Any]:
    family_rows = []
    semantic_rows = []
    summary = None
    with part_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            kind = row.get("type")
            if kind == "family":
                family_rows.append((
                    row["family_id"], row["table_key"], row["status"],
                    int(row["behavior_count"]), int(row["exact_query_count"]),
                    int(row["empty_queries"]), int(row["positive_queries"]), None,
                ))
            elif kind == "semantic":
                semantic_rows.append((
                    row["family_id"], row["occupied_json"], row["semantic_signature_id"],
                    row["blocked_mask_hex"], row["allowed_mask_hex"],
                    int(row["allowed_count"]), row["status"],
                ))
            elif kind == "summary":
                summary = row
    if summary is None:
        raise RuntimeError(f"table part has no summary: {part_path}")
    if family_rows:
        db.executemany(
            "INSERT OR REPLACE INTO family_state(family_id,table_key,status,behavior_count,exact_query_count,empty_queries,positive_queries,error) VALUES(?,?,?,?,?,?,?,?)",
            family_rows,
        )
    if semantic_rows:
        db.executemany(
            "INSERT OR REPLACE INTO semantic_results(family_id,occupied_json,semantic_signature_id,blocked_mask_hex,allowed_mask_hex,allowed_count,status) VALUES(?,?,?,?,?,?,?)",
            semantic_rows,
        )
    table_key = summary["table_key"]
    family_count = int(db.execute(
        "SELECT COUNT(*) FROM families WHERE table_key=?", (table_key,)
    ).fetchone()[0])
    exact_query_count = int(db.execute(
        "SELECT COUNT(*) FROM queries q JOIN families f ON f.family_id=q.family_id WHERE f.table_key=?",
        (table_key,),
    ).fetchone()[0])
    empty_queries, positive_queries = db.execute(
        "SELECT COALESCE(SUM(empty_queries),0), COALESCE(SUM(positive_queries),0) FROM family_state WHERE table_key=? AND status='SEMANTIC_DONE'",
        (table_key,),
    ).fetchone()
    empty_queries = int(empty_queries or 0)
    positive_queries = int(positive_queries or 0)
    outcome = "LOCAL_EMPTY" if int(summary["local_behavior_count"]) == 0 else (
        "ALL_QUERIES_EMPTY" if positive_queries == 0 else "HAS_BILATERAL_OUTER_ZERO"
    )
    db.execute(
        "INSERT OR REPLACE INTO table_state(table_key,status,outcome,rows_seen,family_count,exact_query_count,empty_queries,positive_queries,local_behavior_count,error) VALUES(?,?,?,?,?,?,?,?,?,NULL)",
        (
            table_key, "SEMANTIC_DONE", outcome, 0, family_count,
            exact_query_count, empty_queries, positive_queries,
            int(summary["local_behavior_count"]),
        ),
    )
    db.commit()
    return {
        "table_key": table_key,
        "status": "SEMANTIC_DONE",
        "outcome": outcome,
        "family_count": family_count,
        "exact_query_count": exact_query_count,
        "empty_queries": empty_queries,
        "positive_queries": positive_queries,
        "local_behavior_count": int(summary["local_behavior_count"]),
        "compile_seconds": summary.get("compile_seconds"),
        "compile_behavior_count": summary.get("compile_behavior_count"),
        **_versions(),
    }


def _run_semantic(root: Path, out: Path, chunk_size: int, workers: int, max_tables: int | None = None) -> dict[str, Any]:
    db_path = _db_path(out)
    with sqlite3.connect(db_path) as db:
        _init_db(db)
        _ensure_runtime_tables(db)
        pending = [
            row[0] for row in db.execute(
                "SELECT table_key FROM table_state WHERE status!='SEMANTIC_DONE' ORDER BY (SELECT active_queries FROM tables_expected WHERE table_key=table_state.table_key) DESC, table_key"
            )
        ]
    if max_tables is not None:
        pending = pending[:max(0, int(max_tables))]
    completed = 0
    errors = 0
    checkpoint_rows = []
    for start in range(0, len(pending), chunk_size):
        chunk = pending[start:start + chunk_size]
        payloads = []
        with sqlite3.connect(db_path) as db:
            for table_key in chunk:
                row = db.execute("SELECT intervals_b FROM tables_expected WHERE table_key=?", (table_key,)).fetchone()
                payloads.append((str(root), str(out), table_key, row[0]))
        compile_rows: dict[str, dict[str, Any]] = {}
        compile_errors = {}
        with ProcessPoolExecutor(max_workers=max(1, min(4, workers))) as pool:
            futures = {pool.submit(_compile_one, payload): payload[2] for payload in payloads}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    compile_rows[key] = future.result()
                except Exception as exc:
                    compile_errors[key] = repr(exc)
        semantic_payloads = [
            (str(root), str(out), str(db_path), table_key, compile_rows[table_key])
            for table_key in chunk
            if table_key not in compile_errors
        ]
        semantic_results: dict[str, dict[str, Any]] = {}
        semantic_errors: dict[str, str] = {}
        with ProcessPoolExecutor(max_workers=max(1, min(4, workers))) as pool:
            futures = {
                pool.submit(_evaluate_table_part, payload): payload[3]
                for payload in semantic_payloads
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    semantic_results[key] = future.result()
                except Exception as exc:
                    semantic_errors[key] = repr(exc)
        with sqlite3.connect(db_path) as db:
            _init_db(db)
            for table_key in chunk:
                if table_key in compile_errors:
                    errors += 1
                    db.execute("UPDATE table_state SET status='ERROR',error=? WHERE table_key=?", (compile_errors[table_key], table_key))
                    continue
                if table_key in semantic_errors:
                    errors += 1
                    db.execute("UPDATE table_state SET status='ERROR',error=? WHERE table_key=?", (semantic_errors[table_key], table_key))
                    continue
                try:
                    result = _merge_table_part(db, _table_part_path(out, table_key))
                    checkpoint_rows.append(result)
                    completed += 1
                except Exception as exc:
                    errors += 1
                    db.execute("UPDATE table_state SET status='ERROR',error=? WHERE table_key=?", (repr(exc), table_key))
            db.commit()
        _atomic_json(out / f"checkpoint_{completed:06d}.json", {
            "tables_closed": completed,
            "tables_total": len(pending),
            "errors": errors,
            "last_chunk_size": len(chunk),
            "frontier_status": "PENDING_OUTER_AUDIT",
            **_versions(),
        })
        _write_checkpoint_csv(out, checkpoint_rows)
        if errors:
            raise RuntimeError(f"full closure semantic errors: {errors}")
    return {"tables_closed": completed, "tables_total": len(pending), "errors": errors}


def _write_checkpoint_csv(out: Path, rows: list[dict[str, Any]]) -> None:
    path = out / "semantic_checkpoint_results.csv"
    fields = [
        "table_key", "status", "outcome", "family_count", "exact_query_count",
        "empty_queries", "positive_queries", "local_behavior_count",
        "compile_seconds", "compile_behavior_count",
        "two_run_language", "allocation_dedup_version", "terminal_pair_cache_version",
    ]
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def _build_ledger_exports(root: Path, out: Path) -> dict[str, Any]:
    db_path = _db_path(out)
    with sqlite3.connect(db_path) as db:
        tables = int(db.execute("SELECT COUNT(*) FROM tables_expected").fetchone()[0])
        table_done = int(db.execute("SELECT COUNT(*) FROM table_state WHERE status='SEMANTIC_DONE'").fetchone()[0])
        families = int(db.execute("SELECT COUNT(*) FROM families").fetchone()[0])
        family_done = int(db.execute("SELECT COUNT(*) FROM family_state WHERE status='SEMANTIC_DONE'").fetchone()[0])
        queries = int(db.execute("SELECT COUNT(*) FROM queries").fetchone()[0])
        semantic_done = int(db.execute("SELECT COUNT(*) FROM semantic_results").fetchone()[0])
        positives = int(db.execute("SELECT COUNT(*) FROM semantic_results WHERE status='POSITIVE'").fetchone()[0])
        _atomic_json(out / "full_slot_coverage_verification.json", {
            "status": "PASS" if table_done == tables and family_done == families and semantic_done == queries else "INCOMPLETE",
            "expected_tables": tables,
            "closed_tables": table_done,
            "expected_families": families,
            "closed_families": family_done,
            "expected_distinct_queries": queries,
            "semantic_results": semantic_done,
            "positive_exact_queries": positives,
            "right_census_groups": 11808,
            "right_errors": 0,
            "outer_audit": "PENDING",
            "full_slot_claim": False,
            **_versions(),
        })
        with (out / "full_slot_certificate_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["family_id","table_key","status","behavior_count","exact_query_count","empty_queries","positive_queries"])
            for row in db.execute("SELECT family_id,table_key,status,behavior_count,exact_query_count,empty_queries,positive_queries FROM family_state ORDER BY family_id"):
                writer.writerow(row)
        with (out / "full_slot_ledger.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["family_id","table_key","occupied_json","semantic_signature_id","allowed_count","status"])
            for row in db.execute(
                "SELECT s.family_id,f.table_key,s.occupied_json,s.semantic_signature_id,s.allowed_count,s.status FROM semantic_results s JOIN families f ON f.family_id=s.family_id ORDER BY s.family_id,s.occupied_json"
            ):
                writer.writerow(row)
        return {"tables": tables, "closed_tables": table_done, "families": families, "closed_families": family_done, "queries": queries, "semantic_done": semantic_done, "positive_exact_queries": positives}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/edge63_two_interval_gate2"))
    parser.add_argument("--build-index", action="store_true")
    parser.add_argument("--run-semantic", action="store_true")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=16)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-tables", type=int)
    args = parser.parse_args()
    root = args.root
    out = root / ROOT_REL
    out.mkdir(parents=True, exist_ok=True)
    if args.build_index:
        print(json.dumps({"index": _build_index(root, out)}, indent=2))
    if args.run_semantic:
        print(json.dumps({"semantic": _run_semantic(root, out, max(1, args.chunk_size), max(1, min(4, args.workers)), args.max_tables)}, indent=2))
    if args.export:
        print(json.dumps({"export": _build_ledger_exports(root, out)}, indent=2))
    if not (args.build_index or args.run_semantic or args.export):
        print(json.dumps({"index": _index_stats(sqlite3.connect(_db_path(out)))}, indent=2))


if __name__ == "__main__":
    main()
