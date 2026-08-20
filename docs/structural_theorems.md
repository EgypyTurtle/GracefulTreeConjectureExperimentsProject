# Structural Theorems for Five-Leaf Trees

This note records the structural part of the graceful-labeling project. It
separates proved statements from computational observations and conjectural
templates. The goal is to identify the reductions that could turn an infinite
family of trees into a finite collection of rooted certificates.

Throughout, a tree with `m` edges is called graceful if it has an injective
labeling `f: V(T) -> {0,...,m}` whose edge differences are exactly
`{1,...,m}`.

Statements marked **Theorem** have elementary proofs below. Statements marked
**Candidate** are suggested by the experiments and are not established.

## 1. The branch-skeleton classification

For a tree `T`, let `L(T)` be the number of leaves. Suppress every vertex of
degree 2. The resulting tree is the reduced branch skeleton of `T`; its edges
are assigned the positive lengths of the paths that were suppressed.

### Theorem 1 (branch-degree identity)

For every tree with at least two vertices,

```text
sum(deg(v) - 2, over vertices with deg(v) >= 3) = L(T) - 2.
```

### Proof

The handshaking identity gives `sum deg(v) = 2(|V(T)|-1)`. Subtracting 2
from every vertex and separating leaves, degree-2 vertices, and branch
vertices gives

```text
(-1)L(T) + sum(deg(v)-2, over branch vertices) = -2.
```

Rearranging proves the claim.

### Corollary 1 (complete five-leaf skeleton list)

If `T` has exactly five leaves, then its reduced branch skeleton is exactly one
of the following three types:

1. one branch vertex of degree 5; this is a five-leg spider;
2. two branch vertices of degrees 3 and 4, joined by one reduced edge;
3. three branch vertices of degree 3, joined in a path.

### Proof

Theorem 1 says that the positive integers `deg(v)-2` at branch vertices sum
to `3`. The only partitions of `3` are

```text
3,   2+1,   1+1+1.
```

These give the three cases above. A reduced tree with three branch vertices
must connect them in a path.

This classification is complete: there is no fourth five-leaf skeleton hidden
from the enumerator.

## 2. Canonical parameterizations

The two non-spider skeletons can be parameterized without loss of information.
All lengths below are positive integers.

### Type 2: two branch vertices

Write

```text
T2(q; a1,a2; b1,b2,b3)
```

for the tree whose degree-3 and degree-4 branch vertices are joined by a path
of length `q`, with terminal path lengths `a1,a2` at the degree-3 vertex and
`b1,b2,b3` at the degree-4 vertex. Impose

```text
a1 <= a2,    b1 <= b2 <= b3.
```

Its edge count is

```text
q + a1 + a2 + b1 + b2 + b3.
```

### Type 3: three branch vertices

Write

```text
T3(p,q; a1,a2; c; d1,d2)
```

for the tree whose three degree-3 branch vertices form a path. The two
reduced bridge lengths are `p` and `q`; the two terminal lengths at the left
end are `a1,a2`; the single terminal length at the middle branch vertex is
`c`; and the two terminal lengths at the right end are `d1,d2`. Impose

```text
a1 <= a2,    d1 <= d2,
(a1,a2,p) <=lex (d1,d2,q).
```

Its edge count is

```text
p + q + a1 + a2 + c + d1 + d2.
```

The lexicographic condition removes the reflection duplicate. Thus every
non-spider five-leaf tree occurs exactly once in one of the `T2` or `T3`
parameterizations.

## 3. The extremal-leaf ray theorem

The main structural reduction used by the program is independent of the
number of leaves.

### Definition 2 (rooted graceful certificate)

Let `R` be a tree with `m` edges and let `x` be a leaf of `R`. A rooted
graceful certificate for `(R,x)` is a graceful labeling `f` of `R` such that

```text
f(x) = 0 or f(x) = m.
```

The two cases are equivalent by complementing every label `f(v)` to `m-f(v)`.

### Theorem 2 (extremal-leaf ray extension)

Suppose `(R,x)` has a rooted graceful certificate. For every `k >= 0`, let
`R_k` be obtained from `R` by extending the leaf `x` by `k` new edges. Then
`R_k` is graceful.

### Proof

It is enough to treat the case `f(x)=0`. Suppose the current tree has `m`
edges and the marked endpoint has label 0. Attach one new leaf to it and give
the new leaf label `m+1`. The old edge differences remain
`{1,...,m}`, while the new edge contributes `m+1`.

The new endpoint has the maximum label. Before the next extension, complement
all labels in the current tree. This preserves every absolute edge difference
and changes the marked endpoint label back to 0. Repeat the construction.

After `k` steps, every new edge contributes one new maximum difference, so the
edge differences are exactly `{1,...,m+k}`.

### Corollary 2 (one-coordinate reduction)

Fix all parameters of a reduced skeleton except one terminal path length. If
the member with that length equal to 1 has a rooted graceful certificate at the
retained endpoint, then every positive value of that length is graceful.

For example, if `T2(q;a1,a2;b1,b2,1)` has a certificate at the endpoint of the
third `b`-arm, then every tree

```text
T2(q;a1,a2;b1,b2,k),  k >= 1,
```

is graceful.

This is an infinite-family theorem obtained from one finite certificate.

## 4. Finite-boundary principle

The ray theorem gives a precise answer to the question of when an infinite
family can be reduced to finitely many cases.

### Theorem 3 (finite rooted-boundary criterion)

Let a family of trees be parameterized by vectors `lambda` of positive integer
path lengths. Assume there is a finite set `B` of parameter vectors such that
every parameter vector can be transformed into some vector in `B` by a finite
sequence of shortening operations, where each shortening removes edges from a
single terminal path and leaves a rooted graceful certificate at the retained
endpoint.

Then every tree in the family is graceful if every tree indexed by `B` is
graceful with the required rooted certificates.

### Proof

Reverse the shortening sequence. Each reversed step is a terminal-path
extension. Theorem 2 preserves gracefulness at every step. Since the sequence
ends at a member of `B`, the result follows by induction on the number of
reversed steps.

The theorem is conditional on the existence of the rooted certificates. It
does not assert that every tree has one.

### Interpretation

This gives a rigorous finite-reduction program:

```text
infinite parameter family
        |
        v
finite rooted boundary certificates
        |
        v
all longer terminal paths
```

The difficult mathematical step is not the extension itself. It is proving
that every parameter vector reaches the finite boundary through valid rooted
certificates.

## 5. Why one path is proved but several paths are not

Theorem 2 extends one selected terminal path at a time. A single graceful
labeling has one label 0 and one label equal to the current maximum, so after
extending one path the old extremal endpoint is no longer automatically
extremal.

Therefore the following statement does **not** follow from Theorem 2:

```text
If a tree has two long terminal paths, independently extend both paths from
one rooted certificate.
```

To obtain a genuine multi-coordinate theorem, one would need a family of
certificates carrying extra endpoint information, for example a finite state
record of which marked endpoints can be made extremal after each extension.
The present data supports one-dimensional rays, but does not yet prove a
two-dimensional rectangle of path lengths.

## 6. The boundary family suggested by the final hard cases

The last three 62-edge cases all have the form

```text
T3(2,1; 1,4; c; d,e),
```

with

```text
(c,d,e) = (14,17,23), (18,11,25), (18,17,19),
c + d + e = 54.
```

The `diff` solver found graceful labelings in which the canonical branch
vertices receive labels

```text
2, 0, 62,
```

and the internal vertex of the length-2 bridge receives label `61`. This is
the same anchored skeleton in all three certificates.

### Candidate 1 (anchored three-branch template)

For the family `T3(2,1;1,4;c;d,e)`, there may be a uniform construction in
which the three branch vertices receive `2,0,m` and the intermediate bridge
vertex receives `m-1`, where `m` is the total number of edges.

This is only a candidate template. Three examples are not enough to establish
it for arbitrary `c,d,e`, and the remaining labels still require an explicit
formula whose edge differences are pairwise distinct.

The value of the observation is structural: it identifies a possible fixed
central scaffold and leaves only the three terminal path coordinates to be
solved by a sequence construction.

## 7. Fixed-core and low-difference tail completion

The three final 62-edge cases reveal a more precise object than a common
choice of labels at the branch vertices. They share a fixed labeled core.
The following notation makes that observation testable.

### Definition 3 (path word)

Let a rooted path start at a vertex with label `x`. A signed difference word

```text
(epsilon_1 d_1, ..., epsilon_r d_r),
epsilon_i in {+1,-1},
```

defines successive labels by

```text
x_0 = x,
x_j = x + sum(i=1..j) epsilon_i d_i.
```

It is a valid path word for a graceful labeling if all labels `x_j` lie in
`{0,...,m}`, are pairwise distinct, and the absolute differences on the path
are exactly `d_1,...,d_r`. If several path words have disjoint new labels and
disjoint difference sets, they can be concatenated at their prescribed roots.
The resulting union is a graceful labeling of the whole tree.

This is elementary, but it separates the construction into two independent
checks: a difference partition and a partial-sum collision check.

### Lemma 4 (alternating interval packet)

For integers `a` and `k >= 1`, define

```text
w_0 = a,
w_(2j-1) = a + k - j + 1,
w_(2j)   = a + j,
```

whenever the displayed index is at most `k`. Then

```text
(w_0,w_1,...,w_k)
```

is a graceful path packet on the interval `{a,...,a+k}`: its consecutive
absolute differences are `k,k-1,...,1`.

Indeed, the two successive jumps around each pair are

```text
|w_(2j-1)-w_(2j-2)| = k-2j+2,
|w_(2j)-w_(2j-1)|   = k-2j+1.
```

This is the basic closed formula behind the usual alternating high-low
labeling of a path. It suggests viewing the present hard cases as a
*defected Walecki packing*: the unused-label set has the exact form

```text
U = {17,...,39} minus {18,21}, plus {46,52}.
```

Thus the interval packet is almost available, and the only obstruction to a
direct interval formula is the replacement of two internal labels by two
large exceptional labels. The four rooted tails must absorb these two
defects while simultaneously preserving the difference partition. The three
explicit certificates below can be viewed as three successful defect
switches.

### Why the pure interval packet cannot work

There is a useful obstruction hidden in this decomposition. The standard
packet rooted at 21 on the interval `{22,...,39}` is

```text
21,39,22,38,23,37,24,36,25,35,26,34,27,33,28,32,29,31,30,
```

and it consumes all differences `{1,...,18}`. If this packet were used as
one complete tail, the labels left for the other three tails would be

```text
{17,19,20,46,52},
```

and the remaining differences would be `{19,20,21,22,23}`. The one-edge
tail rooted at 54 could then use only differences

```text
|54-{17,19,20,46,52}| = {37,35,34,8,2},
```

which is disjoint from `{19,20,21,22,23}`. Consequently, the pure interval
Walecki packet is impossible in the fixed-core problem. At least one of the
two missing interval labels must be exchanged with an exceptional label
before the interval packet is completed.

This gives a genuine necessary condition for any formula based on this core:
it must contain a nontrivial defect switch. The exceptional labels are not a
cosmetic artifact of the three solver outputs.

### Defect-switch formalism

Let a tail state be the tuple

```text
(lengths; roots; unused-label set; unused-difference set).
```

A defect switch is an explicit replacement of the path words in one tail
state by path words in another state such that:

1. the roots remain the prescribed core endpoints;
2. the new path lengths are the target lengths;
3. the new labels partition the target unused-label set;
4. the new absolute differences partition the target unused-difference set.

The verification of a switch is finite: it is just a check of partial sums,
label disjointness, and difference disjointness. Therefore a finite switch
library would yield a genuine structural theorem. Namely, if every admissible
tail vector `(1,s,t,u)` can be connected to one of finitely many seed states
by switches from the library, then every corresponding tree is gracefully
labeled by the fixed core plus the transported tail words.

The three explicit tail tables below are seed states for this program. They
are not yet a switch library, because no formula has been proved that moves
from an arbitrary `(s,t,u)` to one of them. The missing mathematical object
is therefore sharply identified: a finite collection of local path-word
rewrites that transports one edge at a time between the four tails.

### Observed fixed core at 62 edges

For the three cases

```text
T3(2,1;1,4;14;17,23),
T3(2,1;1,4;18;11,25),
T3(2,1;1,4;18;17,19),
```

the following labeled path packets occur in all three certificates. The
first entry in each packet is the already labeled root branch vertex.

```text
bridge:      (2, 61, 0)
left-short:  (2, 57)
left-long:   (2, 59, 7, 54)
middle:      (0, 60, 10, 45, 1, 44, 3, 43, 11, 42, 14, 41, 16, 40)
right-1:     (62, 4, 58, 5, 56, 8, 53)
right-2:     (62, 6, 55, 9, 51, 12, 50, 13, 49, 15, 48, 18, 47, 21)
```

The core has 39 edges and its edge-difference set is exactly

```text
{24,25,...,62}.
```

The four remaining terminal tails start at labels

```text
54, 40, 53, 21,
```

and have lengths

```text
(1, c-13, d-6, e-13).
```

For the three observed cases these length vectors are respectively

```text
(1,1,11,10), (1,5,5,12), (1,5,11,6),
```

and each sums to 23. The unused vertex labels are

```text
U = {17,19,20,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,46,52},
```

while the unused differences are exactly `{1,...,23}`.

Thus these three certificates have the same algebraic shape:

```text
fixed core:  39 edges, differences 24..62
tail packet: 23 edges, differences 1..23
```

The vertex numbering changes with `(c,d,e)`, but the labeled path packets do
not. This is a structural observation extracted from the certificates, not
an assumption built into the solver.

### Proposition 1 (fixed-core tail-completion criterion)

For a parameter vector `(c,d,e)` in this anchored family, suppose the four
tail paths have lengths `(1,s,t,u)` with `s>=1`, `t,u>=0`, and
`s+t+u=22`. If there are four path
words, rooted at `(54,40,53,21)`, whose new labels partition `U` and whose
absolute differences partition `{1,...,23}`, then adjoining those words to
the fixed core gives a graceful labeling of the corresponding 62-edge tree.

This is a direct theorem: it follows from Definition 3 and the displayed
core certificate. It is useful because the original 62-edge search is
replaced by a small low-difference path-packing problem.

The converse is deliberately not claimed. A graceful labeling of the tree
need not use this core, so failure of this particular tail-packing problem
would not imply that the tree is non-graceful.

### Preliminary tail experiment

A bounded tail-only search tested all 253 nonnegative compositions generated
by `s+t+u=22` with the first tail fixed at length 1. It found 107 completions
within the short per-composition limit. The other 146 were search failures or
timeouts, not certified impossibilities. Therefore the experiment supports
the fixed-core mechanism as a useful construction family, but does not yet
prove that the core covers the entire parameter triangle.

### Explicit tail words for the three certificates

For the three observed parameter vectors, the tail words can be written
explicitly. A word such as `(-23,+22,-21)` means that the path starts at its
root and successively adds `-23`, then `+22`, then `-21` to the current
label. The resulting label sequence is therefore determined by the root and
the word.

```text
(c,d,e) = (14,17,23):
  root 54: (-19)
  root 40: (-20)
  root 53: (-23,+22,-21,-14,+12,-10,+5,+2,+8,+3,+9)
  root 21: (+18,-17,+16,-15,+13,-11,+7,-4,-1,+6)

(c,d,e) = (18,11,25):
  root 54: (-17)
  root 40: (-23,+22,-20,+19,-18)
  root 53: (-21,-8,+2,+7,-4)
  root 21: (+10,+15,+6,-16,-14,+13,-12,+11,-9,+5,-3,+1)

(c,d,e) = (18,17,19):
  root 54: (-17)
  root 40: (-23,+22,-20,+19,-18)
  root 53: (-21,-5,+9,+16,-6,-15,-7,+4,-2,+3,+1)
  root 21: (+14,-13,+12,-11,+10,-8)
```

In each row the absolute values of all four words form a disjoint partition
of `{1,...,23}`. Their partial sums produce exactly the unused labels in
`U`. These are genuine closed finite formulas for the three hard cases, but
they also show the remaining difficulty: the words are rearranged when the
tail-length vector changes. A theorem for a parameter region would need a
rule that generates the sign words from `(s,t,u)`, together with a proof of
the no-collision and partition conditions.

The next mathematical target is a closed-form description of the four path
words. In the notation above, this means specifying four sign sequences whose
partial sums are collision-free and whose absolute values partition
`{1,...,23}`. Until such sequences are found for a full parameter region,
the fixed-core statement should be presented as a verified construction
template, not as a complete family theorem.

## 8. Candidate reduction conjecture

The experiments motivate the following restricted conjecture.

### Candidate 2 (one-ray cover conjecture)

Every non-spider five-leaf tree with at least one terminal path of length at
least 2 has some terminal path whose one-edge shortening admits a rooted
graceful certificate at the retained endpoint.

If true, Theorem 2 would reduce every such tree to a finite collection of
shortened rooted cores. The trees with all terminal paths of length 1 would be
the finite boundary exceptions for this mechanism.

This candidate is stronger than the observed computational data. A timeout of
the rooted-base search is not a counterexample, but neither is it a proof of a
rooted certificate. The final three cases were solved by a direct difference
search and therefore do not, by themselves, validate Candidate 2.

## 9. What can honestly be claimed now

The strongest structural claims currently supported by proofs are:

1. five-leaf trees have exactly three reduced skeleton types;
2. each terminal path with an extremal rooted certificate generates an
   infinite graceful ray;
3. a finite rooted boundary with valid shortening certificates would imply
   gracefulness of the entire associated infinite family.

The strongest experiment-induced claim is narrower:

```text
The 62-edge hard boundary is not a single obstruction pattern. Its last
three cases share a central anchored labeling, and the difference-based search
finds all three rapidly after the branch search exhausts more than 317 million
nodes.
```

This is evidence for a new construction mechanism, not yet a theorem for an
infinite family.

For a paper, the natural structural contribution is therefore the pair

```text
finite rooted-boundary criterion + explicit five-leaf skeleton classification,
```

followed by the anchored-template conjecture as the next open construction
problem. The computational range then serves as evidence that the proposed
boundary mechanism is targeting the right structures, rather than being the
main mathematical claim.
