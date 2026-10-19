# k=14 artifact audit, 2026-10-19

The original server archive is preserved unchanged:
`data/k14/eg_k14_20261019T071359Z_7f7a4c1a.tar.gz` (1,917,186 bytes).

SHA-256: `8a814c86d59797a0ee8061e73e11f748c6f71e5d00506b2b8542e478839ed1c5`.
All 24,374 archive members match their internal inventory/checksums.
The collected source matches the public source byte for byte:

| File | SHA-256 |
| --- | --- |
| search.cpp | 4082dde09fd354c309e2b194a6fa4307d30f54f3bab02f4a88e11fdcd2f32adc |
| refine.cpp | 74f7766fd0c46fcc67e91bcda415f21892fd4ba38cb49a3883d27a238085b6f9 |

## Checks completed

- Recomputed every completion-record manifest fingerprint, task ID and
  conservation equation. The final 18,060 tasks are complete, no candidate
  file exists, and all aggregate counts match the final summary and raw log.
- Verified that refinement carried all 6,269 finished source tasks forward.
  Re-enumerated all 10,426 unfinished parents in a separate Python set-based
  implementation: their child multiset is exactly the saved 18,060 tasks.
- Independently regenerated the four initial extension layers, obtaining the
  exact saved 16,695-task frontier and generation counters. This checks the
  initial manifest too, not only its relation to the refined checkpoint.
- Reran small-k reference state/fingerprint comparisons, interruption/resume,
  capped and repeated refinement, corrupt-record rejection and audit tests.
  Independent wide-word controls include 78,895 forest comparisons and 2,340
  cyclic-core/ring comparisons. See `tests/release_validation.json`.

The reasoning behind the cycle pruning was inspected: a new forbidden cycle
must use two neighbors of the pending vertex; removing it leaves a simple
path of length `2^j-2` in the immutable core. A conflicting pair can therefore
exclude all supersets. The induced-path search checks chords; reachability,
eligible-vertex bounds and the meet-in-the-middle intersection rule only
exclude impossible paths. Half-path memory overflow falls back to exact DFS,
not a negative answer. No unproved degree-distribution rule is used.

## Reproduce

From this subproject folder, with Python 3.8+ (no third-party packages):

```bash
python3 tools/unpack_artifact.py \
  data/k14/eg_k14_20261019T071359Z_7f7a4c1a.tar.gz artifacts/k14-unpacked
python3 tools/audit_initial_frontier.py \
  artifacts/k14-unpacked/checkpoints/k14-d4/tasks.txt
python3 tools/audit_checkpoint.py --project-root artifacts/k14-unpacked \
  --checkpoint checkpoints/k14-d5-refined --replay-refinement
make -j4
make test
```

The extraction directory must not already exist. Independent Python split
replay took about 41 seconds for the initial layers and 288 seconds for the
record/refinement audit on the local audit machine; these are not server
search timings. `results/k14_initial_frontier_audit.json` and
`results/k14_checkpoint_audit.json` contain the actual reports.

## What remains unverified

This is internal checking using a different implementation for frontier
generation, not independent external peer review. The full 1,435,716,298-state
search has not been independently rerun. Counters and task fingerprints alone
cannot prove that every internal DFS exclusion was correct. The optional
accepted-graph digest was disabled in the large run. This record has no
formal proof certificate, novelty claim or unrestricted-conjecture proof.

The archive was collected after the computation. It preserves the binary
and source then present, but no pre-run, independently witnessed build/source
freeze exists. The requested CPU0 affinity was not independently captured
during k=14. Run wall time is only the final process (58,270.2 s), not the
sum of interrupted runs and refinement. `max_n=72` describes this extension
tree, not a census of all graphs through 72 vertices.
