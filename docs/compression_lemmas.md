# Constructive Compression for Five-Leaf Trees

This note records the proved reductions and the experimental conjecture behind
the `compressed` graceful-labeling method. The reductions produce complete
labeling certificates; they do not merely omit cases because a search heuristic
expects them to be easy.

## 1. Caterpillar alpha-labeling

Let the spine of a caterpillar be `v_0,...,v_k`. Put the vertices in the two
bipartition classes into the following orders while walking from left to right:

- low order: an even spine vertex, then the leaves of the next odd spine vertex;
- high order: the leaves of an even spine vertex, then the next odd spine vertex.

If `r(a)` and `s(b)` are the zero-based positions of adjacent vertices in the
low and high orders, respectively, the edge values `r(a)+s(b)` are exactly
`0,...,m-1`. This follows directly by scanning the pendant-edge blocks and the
spine edges from left to right.

Assign

```text
f(a) = r(a)
f(b) = m - s(b)
```

to low and high vertices. The labels are exactly `0,...,m`, the two
bipartition classes are separated, and every edge difference is

```text
m - (r(a) + s(b)).
```

Hence the differences are exactly `1,...,m`. This is the standard linear-time
alpha-labeling of a caterpillar. The implementation first recognizes the
caterpillar and then constructs and verifies this labeling without search.

For the non-spider five-leaf family through 45 edges, this applies directly to
67,550 cases.

## 2. Extremal pendant-path extension

### Lemma

Let `T` have `m` edges and a graceful labeling in which a selected leaf has
label `0` or `m`. Extending that leaf by one new edge produces another graceful
tree whose new leaf again has an extremal label.

### Proof

If the old leaf has label `0`, keep all old labels and give the new leaf label
`m+1`. The old differences remain `1,...,m`, and the new difference is `m+1`.

If the old leaf has label `m`, add one to every old label and give the new leaf
label `0`. Old differences are unchanged, the attachment vertex now has label
`m+1`, and the new difference is `m+1`.

The new leaf is extremal in either case, so the operation can be repeated.

### Corollary

Fix every reduced-segment length of a tree except one pendant segment. If the
length-one base case has a graceful labeling in which that pendant leaf is
extremal, every positive length of that segment is graceful. One rooted base
certificate therefore proves an infinite ray in the segment-length parameter
space.

## 3. Compressed search

The `compressed` method applies the following certificate-producing pipeline:

```text
recognize a caterpillar
  -> use the direct alpha-labeling
otherwise choose a longest pendant path
  -> shorten it to one edge
  -> search the smaller rooted base with the retained leaf fixed at 0
  -> rebuild the removed path by the extension lemma
  -> verify the final certificate
otherwise
  -> fall back to the full branch-oriented search
```

Rooted base trees are canonicalized by an AHU-style tree code. A successful
rooted certificate is cached and reused for every isomorphic base tree. The
fast in-memory cache is bounded, while the complete set of successful rooted
certificates can be persisted in a SQLite database and reused across runs.
New CSV logs record the successful `strategy`, the hashed `reduction_base`, and
the number of `extended_edges`, so cache hits remain auditable.

This separates two different limits: `--extension-cache-size` controls only
RAM, while `--extension-cache-db` controls the persistent certificate store.
The latter removes the old failure mode in which certificates discovered at
edges 45--47 vanished when the Python process ended.

## 4. Complete ablation through 20 edges

All 20,119 non-spider five-leaf trees with at most 20 edges were rerun with the
compressed method. Every emitted certificate passed the independent verifier.

```text
strategy                         cases
caterpillar                       1884
pendant-extension                 5965
pendant-extension-cache          12128
pendant-extension+branch           142
total                            20119
```

Comparison with the original branch run:

```text
metric                    branch       compressed      reduction
search nodes             3,822,923        435,073          8.79x
sum of case seconds          51.779          6.365          8.13x
```

The 14,012 caterpillar or cache-hit cases required no backtracking search in
the compressed run. Another 5,965 cases searched only a smaller rooted base.

## 5. Experimental rooted-leaf phenomenon

The extension lemma is proved. The availability of an extremal-leaf base
labeling is currently experimental.

Constrained searches gave the following observations:

```text
all cases through 14 edges: 1323 / 1371 succeeded for every one of five leaves
random 20-edge sample:       299 / 300 succeeded for every one of five leaves
random 30-edge sample:       299 / 300 succeeded for every one of five leaves
random 45-edge sample:       150 / 150 succeeded for every one of five leaves
```

These are positive certificate results, not a proof that the remaining rooted
instances lack such labelings. The connected difference search used in this
experiment is a sufficient certificate finder, not a complete decision
procedure for every prescribed root.

A useful proof target suggested by the data is therefore:

> Find structural conditions under which a prescribed pendant leaf of a
> non-spider five-leaf tree admits label 0 in a graceful labeling.

Any condition covering a full-dimensional region of the reduced-length
parameters, combined with the extension lemma, converts infinitely many large
instances into finitely many rooted boundary cases.

## 6. Edge-47 timeout pattern

The interrupted 46-47 edge branch run produced four 300-second timeouts:

```text
fiveleaf2e-47-2-1-1-11-13-19
fiveleaf2e-47-2-1-1-11-15-17
fiveleaf2e-47-2-1-1-13-13-17
fiveleaf2e-47-2-1-1-13-15-15
```

All four have the same reduced shape: a two-branch five-leaf tree with bridge
length 2, two pendant paths of length 1 on one branch, and three long pendant
paths on the other branch. Direct branch search sees these as hard because the
large differences can be arranged in many nearly symmetric ways along the long
paths.

Replaying the four cases with `--method compressed` solved all of them by the
proved pendant-extension reduction:

```text
case                                      branch nodes   compressed nodes
fiveleaf2e-47-2-1-1-11-13-19              18,494,695                472
fiveleaf2e-47-2-1-1-11-15-17              18,841,595                559
fiveleaf2e-47-2-1-1-13-13-17              19,376,388                344
fiveleaf2e-47-2-1-1-13-15-15              19,261,776                463
```

The resulting certificates were independently verified. This is the current
best example of the project's main loop: use brute-force timeouts to identify a
structural hard pattern, then replace the hard search by a certificate-producing
reduction.
