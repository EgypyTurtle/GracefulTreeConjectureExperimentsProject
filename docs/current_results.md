# Current Computational Results

Date: 2026-08-20

This page records the current public status of the graceful-labeling
experiments. It focuses on the computational reduction and acceleration
pipeline; it is not a complete presentation of the underlying proofs.

## Scope

The main family is the family of non-spider trees with exactly five leaves.
After suppressing degree-2 vertices, there are two reduced skeletons:

```text
two-branch:    degree 3 branch -- degree 4 branch
three-branch:  degree 3 branch -- degree 3 branch -- degree 3 branch
```

Each reduced edge receives a positive integer length. Isomorphic parameter
duplicates are removed by sorting symmetric branches.

## Graceful Results

The current exact-edge results are:

```text
range       cases       solved       unresolved
<=45        7,543,822   7,543,822    0
46          1,293,708   1,293,708    0
47          1,479,482   1,479,482    0
48-50       5,780,094   5,780,094    0
51-55      15,800,487  15,800,467   20 initial timeouts
56          4,396,261   4,396,259    2 initial timeouts
57          4,905,851   4,905,841   10 initial timeouts
```

Thus the current combined status through 50 edges is:

```text
16,097,106 cases enumerated
16,097,106 solved
0 unresolved
```

The two initial 47-edge timeout cases were replayed separately and both
solved. They are included in the final solved total rather than being silently
omitted.

The 51-55 bulk pass produced 20 timeout rows. The replay log
`five_leaf_nonspider_edges51_55_replay_adaptive100k.csv` solved all 20, and an
independent verifier reported `checked_solved=20, bad=0`. Thus the combined
covered result through 55 edges is:

```text
cases covered after replay: 31,897,593
solved certificates:        31,897,593
unresolved after replay:              0
```

The initial bulk log and the timeout replay are kept as separate artifacts so
that the first-pass timeout count remains auditable.

The 56-57 bulk pass enumerated all 9,302,112 expected cases. It left 12
timeouts, all recorded with the ordinary `pendant-extension+branch` fallback;
the opt-in adaptive signature did not classify these boundary cases. A
targeted replay with a 100,000-node rooted-base budget and all eligible pendant
paths solved all 12. The replay log is
`replay_edges56_57_fastpath100k_allpaths.csv`, and the independent verifier
reported `checked_solved=12, bad=0`. The per-edge breakdown was:

```text
edge count   cases       first pass solved   replayed timeouts   final solved
56           4,396,261   4,396,259          2                   4,396,261
57           4,905,851   4,905,841         10                  4,905,851
total        9,302,112   9,302,100         12                  9,302,112
```

Across the 56-57 log, 4,892,747 distinct rooted reduction bases were recorded.
The replay certificates needed only about 2,000--3,100 search nodes each,
which identifies the first-pass timeouts as a budget/search-order issue rather
than evidence of a counterexample. Including the earlier replayed ranges, the
current covered total through 57 edges is:

```text
cases covered after replay: 41,199,705
solved certificates:        41,199,705
unresolved after replay:              0
```

## Reduction and Reuse

The computation used previously certified structural cases to reduce later
trees before searching them. The reduction is certificate-producing: every
case still receives a complete labeling when it is solved, but many cases no
longer require an independent full-size search.

For the 48-50 run, the raw family contained 5,780,094 trees but only
2,166,443 distinct reduced rooted instances were recorded. This removes
3,613,651 repeated instances, or approximately 62.5% of the original
independent problems.

The work distribution was:

```text
previous certified reductions reused       4,825,696   83.49%
direct constructive cases                      24,289    0.42%
new reduced-instance searches                 765,534   13.24%
full-search fallback cases                    164,575    2.85%
total                                       5,780,094  100.00%
```

The table is intentionally stated at the level of computational work rather
than implementation details. It shows how the structural reduction changes
the effective search workload while preserving a certificate for every case.

## Hard-Pattern Findings

A controlled family of 4,327 two-branch five-leaf trees was tested over 47--65
edges with bridge length 2, two unit pendant paths, and three variable long
paths. Ordinary branch search solved 4,115 cases, while 20,000-node pendant
reduction solved 4,321. The six remaining cases were solved by a targeted
100,000-node rooted-base replay. All-paths reduction gave no improvement over
the longest-path choice on those six cases.

The ordinary branch solver showed a strong residue-class effect:

```text
edge mod 3 = 0: 1337 / 1338 solved
edge mod 3 = 1: 1391 / 1392 solved
edge mod 3 = 2: 1387 / 1597 solved
```

After pendant reduction, the average time was approximately 0.02 seconds per
case in all three residue classes. This supports the interpretation that the
observed mod-3 effect is a search-order/state-space artifact, not evidence of
a graceful-labeling obstruction.

The six boundary cases required 24,002 or 25,435 rooted-base nodes. The main
solver now supports the opt-in `--extension-adaptive-budget` rule, which raises
the budget to 100,000 for the observed five-leaf signature. This is an
algorithmic heuristic backed by the experiments, not a new mathematical
theorem.

## Runtime Comparison

The 48-50 compressed run took approximately 4 hours 56 minutes of wall time.
The sum of per-case elapsed times was approximately 4.72 hours. All 5,780,094
rows were solved, and the search program verified each produced labeling before
writing the solved row.

For a controlled small-scale ablation through 20 edges, the recorded totals
were:

```text
method       search nodes   case seconds
branch          3,822,923       51.779
compressed        435,073        6.365
```

The compressed method reduced search nodes by approximately 88.6% and case
time by approximately 87.7%, an observed speedup of about 8.1x.

The old branch logs at 46-47 edges provide an additional contextual baseline,
but they are not a same-range ablation against 48-50. A direct branch run of
the complete 48-50 interval was not performed because it would duplicate a
large amount of expensive search.

## Audit Status

The large 48-50 CSV is kept locally and is excluded from Git because of its
size. The search-time verifier accepted every solved row during generation. An
independent verifier pass over the first 100,000 rows reported `bad=0`; a full
standalone pass over the multi-gigabyte log was not completed within a
five-minute check window.

The SQLite certificate database is also a local accelerator and is not part
of the source distribution. The reproducible source, commands, summaries, and
verification tools are the intended GitHub artifacts.

## Interpretation

These are bounded computational verification results for a structured family,
not a proof of the Graceful Tree Conjecture. The main algorithmic result is the
iterative workflow: timeout patterns motivate structural reductions, successful
rooted certificates are persisted, and later edge ranges reuse the accumulated
certificate database.

## Results Through 60 Edges

The 58--60 edge run contained exactly 18,275,936 cases:

```text
edge count   cases       first pass solved   replayed timeouts   final solved
58           5,463,653   5,463,653          0                   5,463,653
59           6,073,447   6,073,446          1                   6,073,447
60           6,738,836   6,738,809         27                   6,738,836
total       18,275,936  18,275,908         28                  18,275,936
```

All 28 first-pass timeout rows were solved by the targeted replay using all
eligible pendant paths and the persistent rooted-certificate database. The
replay used only the `pendant-extension` strategy for all 28 cases.

The first-pass timeout rows accumulated 448,244,942 search nodes. The replay
used 92,835 nodes in total, a measured node reduction of approximately
4,828x. The original rows each had a 300-second limit, while the replay took
approximately 1.81 seconds in total, so the upper-bound wall-time comparison
is approximately 4,652x. This compares the original timeout budget with the
targeted replay; it is not a claim that a full first-pass run would always
consume every timeout budget in another environment.

The final covered total through 60 edges is therefore:

```text
cases covered after replay: 59,475,641
solved certificates:        59,475,641
unresolved after replay:              0
```

The primary log and replay log remain separate so that the distinction between
first-pass search and targeted certificate recovery is auditable:

```text
results/five_leaf_nonspider_edges58_60_adaptive.csv
results/replay_edges58_60_allpaths_600.csv
```

## Results Through 62 Edges

The 61--62 continuation was interrupted before edge 63 and was recovered from
the first-pass and compact recovery logs. The exact layer counts are:

```text
edge count   cases       recovery/replay status                 final solved
61             107,619   all recovery rows solved                  107,619
62           8,252,989   17 final timeouts replayed by 3 methods  8,252,989
total        8,360,608                                           8,360,608
```

The 17 remaining 62-edge cases were split across the replay logs as follows:

```text
replay                               solved   still unresolved   verifier bad
edges62_timeout_replay600.csv          12             5                0
edges62_timeout_replay1800_branch.csv   2             3                0
edges62_timeout_replay_diff600...       3             0                0
```

The final three cases were solved by difference search after the compressed and
long branch replays. The independent verifier checked all 17 replay
certificates with `bad=0`. Combining this interval with the completed range
through 60 gives:

```text
cases covered after replay: 67,836,249
solved certificates:        67,836,249
unresolved:                          0
```

Edge 63 has not started. Its exact non-spider five-leaf layer contains
9,110,398 cases. The next run should use a compact log because the local full
CSV and SQLite cache together are large.

## Generic Graph Search Layer

`src/graceful_graph.py` is a separate baseline solver for an arbitrary simple
undirected edge set. It does not assume a tree, connectedness, or `m=n-1` and
checks the ordinary graceful-labeling definition for graphs with unused labels
in `0..m`. It is tested on cyclic, disconnected, and label-pool boundary
cases.

This layer is useful infrastructure, not a new claim about the Graceful Tree
Conjecture. The current research line remains tree-specific. A future graph
experiment must first choose a public graph-family question, such as a
unicyclic or connected-cubic family, and then add a family generator that
calls the generic solver.

## Vertex-Bounded Certificate Experiment

The separate `rooted_extension_experiment.py` prototype tests a different
route toward vertex-bounded verification. It generates rooted tree types,
searches a parent only when necessary, and verifies one-leaf gap-extension
certificates for later rooted types.

Through 13 vertices it processed 20,299 rooted types:

```text
extension certificates reused: 18,908
direct searches:                1,391
timeouts or unsolved:               0
reuse rate:                     93.15%
```

This is evidence for a reusable certificate mechanism, not an exhaustive
verification of all free trees through 40 vertices. The all-tree vertex bound
must still be approached through leaf-count strata and finite reduced
skeletons; raw enumeration of every tree through 40 vertices is not practical.
