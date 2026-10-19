# Completed k=14 search: provisional computational artifact

Status: original server records retrieved and integrity checked on 2026-10-19;
initial-frontier and refinement layers independently replayed in Python.
External mathematical/implementation review and full DFS replay remain pending.

## Observation

An optimized implementation of the extension search of Hegde, Sandeep and
Shashank completed its k=14 run without reporting a counterexample. The final
checkpoint reports 18,060/18,060 completed tasks, 1,435,716,298 pending-vertex
search states, 1,435,716,297 accepted graphs and 3,586,981,712 neighbor-subset
tests. Counts are labelled search-tree occurrences, not nonisomorphic graphs.

The operator reported 58,270.2 seconds (16 h 11 m 10.2 s) for the final process,
with 474,085.13 user CPU seconds, 25.61 system CPU seconds and a peak resident
set of 53,600 KiB (52.34 MiB). The process exited with status zero. Statistics
include earlier completed checkpoint work; the final process's elapsed time
does not include earlier runs, interrupted work or refinement time.

The reported machine is a dual Xeon Gold 5218 with 32 physical cores total,
64 logical CPUs and approximately 125 GiB RAM, running Ubuntu with GCC 9.4.
The final search requested 16 worker threads and affinity to logical CPUs
0..15 on socket 0. The timing transcript alone does not verify affinity.

The maximum encountered order was 72. This is a property of this generated
search tree, not an enumeration of all graphs on at most 72 vertices, nor a
general lower bound of 73 vertices for counterexamples.

`audit_digest=0` means the optional accepted-graph fingerprint was disabled.
It is not a failure indicator and is not an independent proof certificate.
See `results/k14_reported.json` for the transcribed, machine-readable record.

## Mathematical scope

The target is a finite simple graph of minimum degree at least 3 having no
cycle whose length is a power of two. For a fixed k the search uses the
P_k-free extension reduction from:

Anand Shripad Hegde, R. B. Sandeep and P. Shashank,
*Erdos-Gyarfas conjecture on graphs without long induced paths*,
arXiv:2410.22842v2 (2025), <https://arxiv.org/html/2410.22842v2>.

That paper establishes the P_13-free case and reports its parallel k=14 run
ending out of memory. The conjecture for all finite graphs is not resolved by
the present computation. The program forbids all relevant power-of-two cycle
lengths, not only 4 and 8.

If the implementation preserves the reduction's full search scope, the
checkpoint/refinement chain is complete, and the previous k=3..13 results are
validated, this run supports extending the computational conclusion to
P_14-free graphs. This implication is the intended target for review; it is
not presented here as an independently certified theorem or a priority claim.

## Implementation and testing

The implementation uses word adjacency masks, mutation/rollback, cached
incompatible neighbor pairs, exact-path meet-in-the-middle checks, multiple
word fallbacks above 64 vertices, and persistent prefix tasks. Offline
refinement expands only unfinished tasks and carries forward completed work.
Degree-3 structural conjectures/results are not used to discard partial graphs.

Before the reported large run, tests compared small-k accepted-state counts
and graph fingerprints with the original implementation, exercised 64-bit
boundaries and forced process death/restart. These tests are evidence for
correctness; they do not establish the correctness of every large-run branch.

The independent Python checkpoint audit checked the original saved graph
formats, completion fingerprints, conservation equations, summary statistics
and refinement parent-child relations. Python replay independently reproduced
the 16,695-task initial frontier and the refinement of 10,426 parents into
18,060 tasks. Neither operation replays all
1.4 billion search states or establishes every DFS exclusion.

Post-run tests added 78,895 checks on randomly labelled forests with 65..130
vertices, comparing induced paths against the original implementation and
pair checks against independent BFS distances. These controls exercise the
multiple-word representation. An additional 2,340 controls cover padded,
randomly relabelled cyclic cores and large rings, using an adjacency-list
simple-path oracle. All 81,235 comparisons passed. They do not independently
verify every graph or every pruning decision reached during the large run.

## Evidence and remaining review

1. Completed: original logs, manifests, completion records, exact source and
   server binary collected; outer and all member SHA-256 checks passed.
2. Completed: original and refined checkpoints audited; initial frontier and
   refinement layers independently replayed. Reports are in `results/`.
3. Independently examine all pruning arguments and the above-64-vertex path
   and adjacency implementations; add adverse controls and independent replay.
4. Publish source, reports and the fixed raw archive. Separate observations,
   integrity checks, implementation review and any eventual theorem claim.

See `publication/VERIFICATION.md` for reproducible audit commands and the
artifact identity. The archive was collected after the run, not frozen before
it; matching source bytes and archived binary hashes do not independently
prove the binary was compiled from those sources before execution.

## Attribution and AI use

The extension reduction and baseline code are due to Hegde, Sandeep and
Shashank. Their original MIT notice is retained in `reference/LICENSE`.
The experimental implementation, tests and documentation were developed with
substantial assistance from OpenAI Codex. The operator supplied computation,
logs and research direction. AI-generated code/text and internal regression
tests are not independent external review.
