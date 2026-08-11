# Current Computational Results

Date: 2026-08-11

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
47          1,479,482   1,479,480    2
48-50       5,780,094   5,780,094    0
```

Thus the current combined status through 50 edges is:

```text
16,097,106 cases enumerated
16,097,104 solved
2 unresolved
```

The two unresolved 47-edge cases are retained as explicit hard cases rather
than being silently omitted.

## Reduction and Reuse

The `compressed` method applies the structural reductions operationally:

```text
caterpillar construction
  -> pendant-path reduction
  -> rooted certificate lookup
  -> extremal pendant-path extension
  -> reduced-base search only on cache misses
  -> branch fallback for the remaining hard cases
```

For the 48-50 run, the raw family contained 5,780,094 trees but only
2,166,443 distinct rooted reduction bases were recorded. This is a reduction
of 3,613,651 equivalent base problems, or approximately 62.5% fewer distinct
rooted instances.

The strategy distribution was:

```text
pendant-extension-disk-cache       4,625,696   80.03%
pendant-extension-cache              200,000    3.46%
caterpillar                           24,289    0.42%
pendant-extension                    765,534   13.24%
pendant-extension+branch             164,575    2.85%
total                               5,780,094  100.00%
```

The disk-cache and memory-cache rows were solved by reusing rooted
certificates and extending them. The `pendant-extension` rows searched a
smaller rooted base. Only the final `pendant-extension+branch` category used
the full branch-oriented fallback.

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
