# Validation evidence

Host: Windows x86-64, MSYS2 UCRT64 GCC 16.2.0, C++17 / -O3.
The server's GCC 9.4 / Linux build must run `make test` separately.

## Correctness regression

`out/kernels` passes 58,847 checks, including:

- all 1,024 labelled graphs on 5 vertices;
- 1,200 seeded random graphs on 6..12 vertices;
- induced-path checks against the original set-adjacency implementation;
- pair incompatibility against an independent exact old-core path traversal;
- meet-in-the-middle vs direct DFS for exact paths, including negative cases;
- 63/64/65/127/128/129 vertex boundary cases and C32/C64 pair checks.

`tests/test_verifier.py` passes its three test methods for cycle witnesses,
induced-path chords and malformed/complete graph input.

`tools/regression.py` passes:

- k=3..10: accepted-state count and unordered graph fingerprint agreement with
  the original search, for split depths 0/1/3 and thread counts 1/4;
- completed-checkpoint reuse and capped frontier fallback;
- k=11: abrupt process kill followed by recovery with a different thread count;
  the final accepted-state fingerprint agrees with the original search;
- time-limit interruption returns incomplete;
- changed checkpoint parameters are rejected;
- a corrupt completion-record fingerprint is rejected.

The machine-readable report is `local_validation.json`. Hash agreement is
regression evidence, not a collision-free proof.

## Performance evidence

`local_benchmark.json` records same-host end-to-end runs, including checkpoint
durability work. These are single runs, not statistically controlled repeated
benchmarks, and do not predict the user's Xeon server directly.

The exploratory k=12 v2 run completed with 228,536 pending-vertex states and
228,535 accepted graphs, with maximum graph order 44. It was not cross-checked
against a fresh original k=12 execution on this host.

The exploratory k=13 run created 3,500 depth-3 tasks. At the 30-second limit,
3,498 tasks were complete and the program reported `incomplete`. A subsequent
run correctly loaded `reused=3498 pending=2`. Both remaining tasks were still
unfinished after further bounded tests. No claim of a completed v2 k=13 run
or of k=14 verification is made here. The user's original k=13 run was already
completed on the server, as recorded in the conversation/run instructions.

The two long-running tasks show a remaining static-frontier load imbalance.
A deeper split uses a new checkpoint directory and can reduce it, subject to
the frontier task limit. This build does not checkpoint individual DFS stack
frames or dynamically subdivide an already-running task.

## Offline pending-task refinement

`tests/test_refine.py` checks a deliberately partial checkpoint against the
original k=10 reference graph fingerprint, through two successive refinements.
It also verifies a capped mixed-depth frontier, a fully completed source,
source-file preservation, and rejection of in-place/existing destinations.
The machine-readable report is `refinement_validation.json`.

`eg_refine` adds offline subdivision of pending tasks without restarting
completed work; it does not add DFS-stack checkpoints inside a running task.

## Post-run release-preparation checks (2026-10-19)

`tests/wide_oracles.cpp` passes 78,895 additional comparisons on seeded,
randomly labelled forests with 65..130 vertices. Induced paths are compared
with the original set-adjacency implementation; pair incompatibility is
compared with unique-path distances from an independent BFS oracle. Forests
exercise multiple adjacency words and negative as well as positive pair
checks. They do not cover every cyclic graph reached in the large run.

`tests/test_audit.py` passes four tests: independent Python refinement replay,
corrupt completion/summary rejection, archive checksums and whitelist,
and relocated-checkpoint ancestry. The collection script includes no SSH
credentials or arbitrary home-directory files and performs no public upload.

The reported server k=14 completion is recorded separately in
`results/k14_reported.json`. Original server files have not yet been retrieved
to this local workspace. The independent checkpoint audit and split-layer
replay on that actual large-run artifact therefore remain pending. No full
independent replay of its DFS search has been completed.
