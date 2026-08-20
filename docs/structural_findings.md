# Structural Findings From the Large Runs

This note separates proved statements from observations in the large
five-leaf non-spider experiments. The computational data suggests useful
families and algorithms, but it does not by itself prove the Graceful Tree
Conjecture.

## 1. A proved ray-extension theorem

Let a tree have a terminal pendant path, and shorten that path until only one
edge remains. If the shortened rooted tree has a graceful labeling in which
the retained leaf has label 0 or the maximum label, then every positive length
of that pendant path is graceful. The proof is the repeated operation

```text
extremal leaf with label 0  -> add a new leaf with the new maximum label
extremal leaf with label m  -> shift old labels by 1 and add a new leaf with 0
```

The old differences remain unchanged and the new edge realizes the new
maximum difference. This theorem is independent of the number of leaves and
is implemented by the `compressed` solver.

The important interpretation is that one verified rooted base certificate is
not evidence for one large tree only. It certifies an entire one-parameter ray
of trees obtained by lengthening the selected pendant segment.

## 2. A concrete certified infinite family

Use the two-branch five-leaf notation

```text
T(b; s1,s2; a,b2,c)
```

for bridge length `b`, two pendant lengths on one branch, and three pendant
lengths on the other branch. The boundary experiment contained

```text
T(2; 1,1; 11,23,c),  c = 23,24,25,26,27.
```

All five cases reduced to the same rooted base certificate
`7beccc3fae7b9b1e`. The shortening removed `c-1` edges, so the base is the
fixed tree

```text
T(2; 1,1; 11,23,1).
```

Once that base certificate is independently verified, the extension theorem
certifies the whole ray `T(2;1,1;11,23,c)` for every positive integer `c`, not
just the values 23--27 tested in the boundary experiment. This is a genuine
infinite-family result obtained from one finite certificate.

The sixth boundary case, `T(2;1,1;9,26,26)`, used a second rooted base
certificate. Thus six apparently hard cases collapsed to two rooted cores.

The broader controlled family contained 4,327 cases and only 310 distinct
20,000-node reduction bases. For every fixed pair `(a,b)` in
`T(2;1,1;a,b,c)`, the tested values of `c` used one base `B_(a,b)` rather
than a base depending on `c`. In particular, 154 bases were seen across the
full 47--65 edge interval. This is strong evidence that the third pendant
length is being correctly treated as an extension coordinate.

## 3. What the timeout data says

The same pattern appears repeatedly:

```text
51--55 initial timeouts: 20
adaptive rooted replay: 19 solved by pendant reduction
full-search fallback:   1

58--60 initial timeouts: 28
targeted replay:         28 solved
replay node range:       2,020--5,343
```

The old searches used roughly 10--21 million nodes per timeout. The replay
searches used only a few thousand nodes. This strongly supports the
interpretation that these are search-budget and search-order failures, not
evidence for non-gracefulness.

For the six controlled boundary cases, a 20,000-node rooted budget solved
none, while a 100,000-node budget solved all six. The successful one-path and
all-path runs used the same rooted base and the same node count. Therefore the
remaining difficulty there was the rooted-base budget, not failure to choose
the correct pendant path.

## 4. The mod-3 effect is algorithmic evidence, not a graph obstruction

In the controlled 4,327-case family, ordinary branch search had:

```text
edge mod 3 = 0: 1 failure out of 1,338
edge mod 3 = 1: 1 failure out of 1,392
edge mod 3 = 2: 210 failures out of 1,597
```

After pendant reduction, the 20,000-node run solved 4,321 cases, and the six
remaining cases all solved with the 100,000-node replay. Reduced runtimes were
approximately uniform across residue classes.

The same rooted certificate also covers consecutive total edge counts with
different residues modulo 3. Thus the data gives no evidence for a mod-3
obstruction in the tree family. The effect is best understood as a feature of
the ordinary branch solver's state space and ordering.

## 5. The strongest reasonable conjectural next step

The experiments suggest the following restricted conjecture, which is not yet
proved:

> Every five-leaf non-spider tree with a nontrivial terminal pendant path has
> at least one terminal pendant path whose shortened rooted base admits a
> graceful certificate with the retained leaf extremal.

If true, every such tree is covered by a one-step pendant reduction. A stronger
recursive version would reduce several pendant coordinates and leave only a
finite boundary set of rooted skeletons.

The current data does not justify claiming this conjecture. A nonzero fraction
of first-pass cases still enters `pendant-extension+branch`,
`pendant-extension-adaptive`, or full fallback search. Those rows show that
the current certificate finder has not yet proved the required rooted
certificate within its budget; they do not show that the certificate does not
exist.

There is also a basic coverage boundary that must be stated explicitly. The
smallest two-branch five-leaf tree has terminal lengths `(1,1,1,1,1)` and no
terminal pendant path of length at least 2. It is graceful, but it cannot be
covered by the pendant-shortening rule. Thus the candidate conjecture must
exclude trees with no eligible terminal path; this is a limitation of the
reduction mechanism, not a counterexample to graceful labeling.

The later 56--60 timeout replays suggest a second hard band: three-branch
trees with internal bridge pairs mostly of the form `(3,k)` for
`k=18,...,24`. Those 28 replay cases had almost no repeated rooted bases, so
this band is not yet a theorem-producing ray family. It is the right place to
look for a new certificate coordinate or a different rooted construction.

## 6. What would turn this into a theorem-producing computation

The next useful analysis is to group every solved case by its canonical rooted
base code and measure how many independent length vectors each base covers.
The target table is:

```text
rooted base code | number of covered length vectors | edge range | verified label
```

This can reveal multi-point rays, rectangular regions, or eventually
multi-coordinate closure rules. A proof-quality result would then consist of:

1. a finite list of rooted base certificates;
2. a formally stated extension rule for each parameter direction;
3. a coverage argument showing which length vectors are covered;
4. an independently checkable certificate verifier.

At present, the strongest established conclusion is therefore:

```text
large hard-case clusters are repeatedly collapsing to small rooted bases;
the pendant-extension rule converts those bases into infinite certified rays;
the mod-3 timeout pattern belongs to the search procedure, not to an observed
graceful-labeling obstruction.
```

## 7. Why a multi-path theorem needs new data

One graceful labeling has a unique label 0 and a unique maximum label. The
current extension proof can therefore advance one selected terminal path, but
it does not automatically preserve an extremal endpoint on a second path.
Trying every eligible path is an algorithmic union of one-path certificates,
not a simultaneous multi-path theorem.

A sound future abstraction is a finite-state certificate transition system:

```text
state = which marked terminal endpoints are currently extremal
transition = one valid pendant extension
region = a certified path or cycle scheme in this finite state graph
```

For five terminal paths there are at most `3^5 = 243` coarse endpoint-status
states. This can produce auditable one-dimensional rays and, if genuine
closed independent transitions appear, higher-dimensional semilinear regions.
The state system must retain the marked rooted certificate, not only the
16-character reduction hash, because one base can have multiple labelings with
different extremal endpoints.

There is an important restriction on this idea. Under the present extension
proof, after extending path `i`, the new endpoint of path `i` is the unique
new extremal endpoint, while other old endpoints that had label 0 or the old
maximum generally become non-extremal. Thus a single labeling naturally gives
one ray, not an independent multi-dimensional rectangle. A genuine
two-dimensional region would require either a new certificate variant after
each transition or a stronger gap-extension lemma.

## 8. A closed-form five-leaf family

There is a second kind of reduction that does not require a rooted search.
Let `T(q;1,1;1,1,1)` be the two-branch five-leaf tree whose branch vertices
are joined by a path of length `q >= 1`, with all five terminal arms of
length one. Writing `q = 2r+1` or `q = 2r`, an alternating labeling of the
bridge gives the difference blocks

```text
left leaf edges       {1,2}
bridge path           {3,...,q+2}
right leaf edges      {q+3,...,q+5}
```

The vertex labels are exactly `0,...,q+5`; hence this is a proved infinite
family, not merely a batch observation. The implementation recognizes this
family in linear time as `unit-arm-construction`, before any search. The
closed form is covered by tests for `q = 1,...,30`.

This construction is more useful operationally than a generic modular
filter: the modular and parity conditions found in the agent audit are
necessary but not sufficient. A candidate can pass those weak checks while
repeating actual absolute differences. They should therefore remain
diagnostics or pruning conditions, not acceptance rules.
