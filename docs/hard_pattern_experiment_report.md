# Hard-Pattern Budget Comparison

## Family

The experiment fixes the two-branch five-leaf skeleton with

```text
bridge = 2
short pendant paths = (1, 1)
long pendant paths = (a, b, c), a <= b <= c
```

The total edge count is `4 + a + b + c`. All triples with total edge count
47 through 65 were tested, giving 4,327 non-isomorphic cases.

Each tree was tested independently with:

1. ordinary branch-oriented search;
2. pendant reduction with a 2,000-node rooted-base budget;
3. pendant reduction with a 20,000-node rooted-base budget.

The persistent certificate cache was disabled for this comparison. Every
successful output was verified by the program's graceful-labeling verifier.

## Aggregate Results

```text
method             solved       total       success rate   time        nodes
branch             4115         4327        95.1005%       3812.933 s  232641934
reduction-2000     3418         4327        78.9924%         49.352 s    3703657
reduction-20000    4321         4327        99.8613%         87.215 s    6515890
```

Relative to ordinary branch search, the 20,000-node reduction run used about
43.7 times less total time and 35.7 times fewer search nodes. The 2,000-node
run is too small for this family: it leaves 909 cases unresolved. Increasing
the rooted-base budget by a factor of ten reduces that to 6.

## Residue-Class Comparison

```text
edge mod 3   cases   branch solved   branch time/case   reduction-20000 solved   reduction time/case
0            1338    1337            0.292 s            1337                     0.0192 s
1            1392    1391            0.342 s            1390                     0.0210 s
2            1597    1387            1.845 s            1594                     0.0203 s
```

The `mod 3 = 2` branch failure rate is 13.15%, compared with less than 0.1%
for the other two residue classes. Its average branch runtime is about five
to six times larger. The reduction method removes this separation: its
per-case runtime is approximately 0.02 seconds in all three classes, and its
success rate is above 99.8% in every class.

This is strong evidence that the observed mod-3 effect belongs to the current
branch-search state space or ordering, rather than to an obstruction to
graceful labeling. It is not, by itself, a mathematical theorem about all
trees.

## Remaining 20,000-Node Cases

Six cases did not obtain a rooted certificate within 20,000 nodes:

```text
hardpattern2e-61-2-1-1-11-23-23
hardpattern2e-62-2-1-1-11-23-24
hardpattern2e-63-2-1-1-11-23-25
hardpattern2e-64-2-1-1-11-23-26
hardpattern2e-65-2-1-1-9-26-26
hardpattern2e-65-2-1-1-11-23-27
```

They share the same structural signature as the earlier hard cases: a bridge
of length 2, two pendant paths of length 1, and three strongly unbalanced long
paths. Four cases form the ray `(11,23,c)` for `c=23,...,26`, with a fifth
continuation at `c=27`; the remaining case is `(9,26,26)`.

The fastpath reached exactly its 20,000-node budget on all six. This means
that they are not evidence of non-gracefulness. They are the next rooted-base
search boundary and should be replayed with either all eligible pendant paths,
a larger rooted-base budget, or a specialized search order.

## Conclusion

The experiment supports three algorithmic conclusions:

1. The `mod 3 = 2` phenomenon is a real diagnostic signature of the current
   branch solver on this family.
2. It is almost completely absent after pendant-path reduction, so it is not
   currently evidence for a structural graceful-labeling obstruction.
3. A 20,000-node rooted-base budget is a much better default for this hard
   family than 2,000 nodes, but the reduction is not yet complete: six
   boundary cases remain.

The next controlled experiment should target only those six cases, trying all
eligible pendant paths and then increasing the rooted-base budget. No need to
rerun the 4,327-case comparison.

## Targeted Boundary Replay

The six remaining cases were then tested with four methods:

```text
ordinary branch, time limit 60 seconds
one-path reduction, 20,000 rooted-base nodes
one-path reduction, 100,000 rooted-base nodes
all-path reduction, 100,000 rooted-base nodes
```

The result was:

```text
method             solved   total   time
branch             4        6       145.192 s
reduction-20000    0        6         1.733 s
reduction-100000   6        6         2.072 s
all-paths-100000   6        6         2.127 s
```

The successful one-path searches used 24,002 or 25,435 nodes. The all-path
run produced the same successful path and the same node count in every case.
Thus, for this boundary family, the previous failures were caused by a
fastpath budget threshold near 20,000 nodes, not by choosing the wrong pendant
path. Increasing the budget to 100,000 solves all six in about two seconds of
aggregate reduction time.

This suggests an adaptive policy: retain the cheap 2,000-node attempt for
ordinary cases, increase the rooted-base budget when the structural signature
is `bridge=2`, two short pendant paths, and three strongly unbalanced long
paths, and reserve all-path search for cases where the larger single-path
budget still fails.
