# A Vertex-Bounded Route Toward 40 Vertices

## What the bound actually means

The statement "all trees with at most 40 vertices" is much larger than the
current five-leaf experiment.  The number of nonisomorphic trees with exactly
40 vertices is

```text
363,990,257,783,343
```

The total for 36 through 40 vertices is

```text
566,113,098,614,623
```

Those numbers make direct enumeration and labeling search the wrong first
algorithm.  Even a hypothetical million cases per second would still take
years for the 36--40 block, before accounting for hard cases.

The current five-leaf generator is a useful controlled slice, not an
all-trees verifier.  Its exact count through 39 edges (40 vertices) is
2,685,213 non-spider cases.  That is already a substantial computational
result, but it is only a small fraction of all trees.

## Structural stratification by leaves

Suppress every degree-2 vertex of a tree.  If the tree has `L` leaves, the
resulting homeomorphically irreducible skeleton satisfies

```text
sum over branch vertices (degree - 2) = L - 2.
```

Consequently there are only finitely many skeletons for fixed `L`; the full
family is obtained by assigning positive lengths to the skeleton edges.  The
number of length vectors is polynomial in the vertex bound for fixed `L`.

This suggests a practical route:

1. Use the known small-leaf theorems and direct constructions where available.
2. Complete the five-leaf slice, including both spider and non-spider
   skeletons, with certificate-producing reductions.
3. Add six-leaf skeletons only after their reduced parameter space has a
   generator and an independent verifier.
4. Treat larger leaf counts as separate strata rather than pretending that a
   five-leaf result covers all trees.

## The new experiment: vertex gap certificates

`src/rooted_extension_experiment.py` implements a broader, local certificate
than the current pendant-path rule.

Suppose a tree `T` has `m` edges and a graceful labeling `f`.  To attach a new
leaf at a chosen vertex `v`, choose a gap `g` in `0..m+1`, shift every old
label at least `g` upward by one, and give the new leaf label `g`.  If the
resulting edge differences are `1..m+1`, the operation is a checked extension
certificate.

The experiment generates every rooted tree type in a small vertex layer.  It
solves a parent once, tries every attachment vertex and every gap, and stores a
verified child labeling.  A later occurrence of that rooted child is then
processed without another search.  This is a sufficient certificate mechanism;
failure to find a gap is not a counterexample and is not a proof of
non-gracefulness.

Run the first benchmark with:

```powershell
$PY="python"
& $PY ".\src\rooted_extension_experiment.py" `
  --max-vertices 10 `
  --time-limit 2 `
  --progress 100 `
  --csv ".\results\rooted_extension_v10.csv"
```

The program reports, per vertex layer:

```text
rooted_types
extension_reused
direct_solved
timeouts_or_unsolved
next_certified_before_search
```

The first meaningful metric is the fraction of rooted types processed by
extension certificates rather than fresh search.  A second benchmark at 11 or
12 vertices can show whether the reuse rate grows with the layer.  It should
be run separately from the long five-leaf process because it has no reason to
use or modify the pendant-extension SQLite database.

## Initial benchmark

The prototype was run through 12 vertices with a five-second per-shape search
budget.  It generated the standard rooted-tree counts and found no timeout:

```text
vertices   rooted types   extension reused   direct search
1                 1                 1              0
2                 1                 1              0
3                 2                 2              0
4                 4                 4              0
5                 9                 9              0
6                20                19              1
7                48                44              4
8               115               109              6
9               286               270             16
10              719               674             45
11             1842              1723            119
12             4766              4430            336
```

Across all layers through 12 vertices this is 7813 rooted types, of which
7286 (93.3 percent) were handled by a stored extension certificate and 527
needed direct search.  In the separate through-10 comparison, direct search
would make 1205 solver calls; the closure run made 72.  The recorded runtime
fell from about 1.99 seconds to about 0.58 seconds on the same machine and
Python runtime.  These are prototype measurements, not an asymptotic bound.

The fast filter is exact for the proposed one-step operation.  After a gap is
inserted, the old edges must already have distinct differences in
`1..m+1`, with one value missing; the new leaf edge must have precisely that
missing value.  Only then does the code construct the canonical child and run
the independent full verifier.

## Relation to the existing reduction

The existing pendant-path theorem is stronger when it applies: one extremal
leaf certificate proves an arbitrary number of repeated extensions along the
same pendant path.  The new gap certificate is more general because it can
attach a leaf at any vertex, but in its present form it is only a one-step
certificate.  The next mathematical target is to detect when a gap remains
valid under repeated extensions; that would turn this experiment into a
multi-step closure rule.

The immediate engineering target is therefore not a raw all-tree run to 40.
It is to persist these generic rooted certificates and connect them to the
fixed-leaf skeleton generator.  For five leaves this can be tested against the
existing 2.7 million-case edge-bounded family.  For six leaves it gives a
controlled next stratum.  Only after those tests should a free-tree generator
be introduced; the 566-trillion-tree 36--40 block cannot be made practical by
faster backtracking alone.

## Literature boundary

Wenjie Fang's arXiv paper gives the formal computational result through 35
vertices.  A later personal report claims a computation through 39 vertices,
while survey and secondary sources describe 40-vertex programming-model
experiments with less precise scope.  These should not be conflated with a
published proof of the Graceful Tree Conjecture or with an exhaustive public
certificate set through 40 vertices.

The relevant references are:

- <https://arxiv.org/abs/1003.3045>
- <https://fwjmath.wordpress.com/2012/12/04/every-tree-with-at-most-39-vertices-is-graceful/>
- <https://mathworld.wolfram.com/GracefulTreeTheorem.html>
- <https://oeis.org/A000055/b000055.txt>
