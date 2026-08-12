# Current Computational Results

Date: 2026-08-12

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
