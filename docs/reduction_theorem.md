# Complete Pendant-Path Reduction Theorem

This document gives the exact scope of the reduction implemented by
`--method compressed`. It is a complete theorem about this reduction rule,
not a claim that every graceful tree has such a reduction.

## Definitions

Let `T` be a tree. A terminal pendant path is a path

```text
v_0 - v_1 - ... - v_k,  k >= 2,
```

where `v_0` is the first vertex of degree different from 2 when walking from
the leaf `v_k`, the internal vertices have degree 2, and `v_k` is a leaf.
Shorten this path by deleting `v_2,...,v_k`. The resulting tree is `R`, and
`v_1` is its marked leaf. The original tree is obtained from `R` by extending
the marked leaf by `k-1` edges.

Call `(R, v_1)` a rooted graceful certificate if `R` has a graceful labeling
in which `v_1` has label 0 or `|E(R)|`. Complementing every label exchanges
these two cases, so the implementation searches with the marked leaf fixed
at 0.

## Theorem

If `(R, v_1)` has a rooted graceful certificate, then every tree obtained by
extending `v_1` by any positive number of new pendant edges is graceful.

More precisely, if `R` has `m` edges and `v_1` has label 0, add a new leaf with
label `m+1`. The old edge differences remain `1,...,m`, and the new edge has
difference `m+1`. The new leaf is again extremal, so the construction repeats.
If the marked leaf has label `m`, shift all old labels by 1 and give the new
leaf label 0. The same argument applies.

Therefore, for a fixed tree `T`, the following statement is complete for the
single-pendant-path rule:

```text
T is covered by this rule
  iff some terminal pendant path of T has a shortened rooted base
     with a rooted graceful certificate.
```

The forward direction here means “covered by this rule”, not merely
“graceful”. A graceful tree may exist without being covered by this particular
certificate mechanism.

## What Can Be Counted

For a finite enumerated family `F`, the program distinguishes four quantities:

```text
structurally_eligible
    trees with at least one terminal pendant path of length >= 2;

extension_success
    trees whose log contains a verified pendant-extension certificate;

direct_constructive
    trees solved by the direct caterpillar construction;

unique_reduction_bases
    distinct rooted base codes appearing in the log.
```

`structurally_eligible` is a candidate count, not a proof count. The certified
count is `extension_success`. A tree can have several eligible paths, so the
number of eligible paths can exceed the number of trees. The `--extension-
try-all-paths` option computes the union over all such paths using one shared
search budget.

The summary command is:

```powershell
& $PY ".\src\graceful_tree.py" `
  --summarize-reduction `
  ".\results\five_leaf_nonspider_edges48_50_compressed.csv" `
  --reduction-summary-output ".\results\reduction_48_50.csv"
```

Several disjoint logs may be supplied after `--summarize-reduction`. Do not
pass overlapping logs unless duplicate rows are intended. The command streams
the CSV and does not search or modify certificates.

## Structural Scope

The theorem applies independently of the number of leaves. It can therefore
be used for spiders with long legs, lobster instances that contain terminal
degree-2 chains, random trees, caterpillar extensions, and arbitrary trees
provided through an edge list. The current repository has a complete
enumerator and large exhaustive data set only for the non-spider five-leaf
family.

The theorem does not cover an internal bridge subdivision automatically. A
future multi-path or bridge-composition theorem would need additional label
compatibility conditions; those conditions do not follow from the
single-extremal-leaf lemma.
