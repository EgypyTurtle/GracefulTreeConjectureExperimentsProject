# Graceful Tree Computation Technical Report

Date: 2026-08-04

## 1. Problem

A graceful labeling of a tree with `m` edges is an injective vertex labeling by
the integers `0,1,...,m` such that the absolute differences along the `m` edges
are exactly `1,2,...,m`.

The Graceful Tree Conjecture says that every finite tree has such a labeling.
The conjecture remains open in the standard literature, although many important
families are known to be graceful.

## 2. Known Theoretical Coverage Relevant to This Project

The following families should be treated as already covered by known results:

- Paths.
- Caterpillars.
- Symmetrical trees.
- Trees with fewer than 5 leaves.
- Trees of diameter less than 8.
- Several special lobster families, including firecrackers and bananas.
- Spiders with 3 or 4 legs.
- Spiders whose leg lengths differ by at most 1.
- Spiders with at most 5 legs, by Panpa, Imnang, and Wasuanankul (2025).

Therefore the 5-leg spider computations below are useful as solver validation
and heuristic data, but they are not a new theorem about graceful trees.

## 3. Solver Evolution

The initial solver used generic graceful-labeling backtracking. It was then
extended with several methods:

- `exact`: direct vertex-label search.
- `diff`: search by assigning edge differences.
- `heuristic`: randomized local search.
- `hybrid`: tries structural and generic strategies.
- `spider`: a dedicated spider solver.

The most important implementation improvement was `--method spider`. It fixes
the spider center at label `0`, assigns large edge differences near the center,
and searches by extending leg frontiers. This turned some apparently hard cases
into very small searches.

Example:

```text
spider-7-8-10-10-10
hybrid: no labeling found after 1800s and 19,434,629 search nodes
spider: solved in 46 search nodes
```

## 4. Completed 5-Leg Spider Computations

All spider cases are counted as nondecreasing leg-length multisets
`spider-a-b-c-d-e`.

### Maximum Leg <= 10

```text
cases = C(14,5) = 2002
solved = 2002
timeouts = 0
method = spider
```

### Maximum Leg <= 11

```text
cases = C(15,5) = 3003
solved = 3003
timeouts = 0
method = spider
```

### Maximum Leg 12-15

```text
cases = C(19,5) - C(15,5) = 8625
final solved = 8625
final timeouts = 0
```

Run sequence:

```text
1. spider / long / extreme / 10s: solved 8556, left 69
2. replay / long / extreme / 60s: solved 53, left 16
3. replay / long / extreme / 300s: solved 14, left 2
4. replay / short / extreme / 30s: solved 2, left 0
```

The final two hard cases solved by short-leg-first ordering were:

```text
spider-12-14-14-15-15
spider-14-14-14-15-15
```

### Maximum Leg 16-20

```text
cases = C(24,5) - C(19,5) = 30876
first sweep solved = 28150
first sweep timeouts = 2726
```

The first sweep used:

```text
--method spider
--spider-order short
--spider-label-order extreme
--time-limit 10
```

The replay of the 2726 timeouts used:

```text
--method spider
--spider-order long
--spider-label-order extreme
--time-limit 30
```

Replay result:

```text
replayed = 2726
newly solved = 1136
still unsolved = 1590
```

Combined status for maximum leg 16-20:

```text
total cases = 30876
solved = 29286
timeouts = 1590
completion = 94.85%
```

Remaining timeouts by maximum leg:

```text
max leg 16: 25
max leg 17: 76
max leg 18: 208
max leg 19: 414
max leg 20: 867
```

Representative hard cases:

```text
spider-7-16-17-17-20
spider-6-13-17-17-20
spider-7-17-17-17-20
spider-6-17-17-17-20
spider-10-16-17-17-20
spider-10-15-16-16-19
spider-7-15-16-16-19
spider-7-16-16-16-19
spider-9-16-17-17-20
spider-9-16-16-16-19
```

## 5. Interpretation

The 5-leg spider family is now considered a solved theoretical family, so
continuing to `max leg 20-30` is not an efficient use of computation if the goal
is to approach unknown territory.

The useful byproduct is algorithmic:

- Dedicated spider structure is vastly better than generic backtracking.
- Short-leg-first and long-leg-first orderings have complementary blind spots.
- The remaining hard cases are good benchmark instances for future heuristic
  development.

## 6. Next Target: Non-Spider 5-Leaf Trees

A 5-leaf tree has exactly five degree-1 vertices. A 5-leg spider is the special
case with one branch vertex of degree 5. A non-spider 5-leaf tree has more than
one branch vertex.

After suppressing all degree-2 vertices, every non-spider 5-leaf tree has one
of two reduced skeletons:

```text
Type 2-branch: branch degrees 3 and 4
Type 3-branch: three branch vertices of degree 3 arranged in a path
```

The new program entry point enumerates these skeletons and subdivides every
reduced edge by a positive length bounded by `MAX_SEGMENT`.

Small smoke test:

```text
MAX_SEGMENT = 2
cases = 66
solved = 66
timeouts = 0
```

Subsequent non-spider 5-leaf sweep results:

```text
MAX_SEGMENT = 3
cases = 693
solved = 693
timeouts = 0

MAX_SEGMENT = 4
cases = 4080
initial solved = 4079
replay solved = 1
final solved = 4080
timeouts = 0

MAX_SEGMENT = 5
cases = 16875
initial solved = 16778
first replay solved = 75
branch replay solved = 22
final solved = 16875
timeouts = 0
```

The hard cases for `MAX_SEGMENT = 5` were all three-branch skeletons. Most had
internal bridge lengths `(4,1)` and several leaf segments of length `5`. A new
`branch` method was added for these cases. It fixes label `0` at a branch
vertex and assigns edge differences from large to small while keeping the
search connected to already labeled branch structure. This solved the final
22 cases in `0.053s`.

The `branch` method should be described cautiously: it is not a proved
constructive algorithm for all non-spider 5-leaf trees. It is a specialized
branch-oriented search heuristic implemented for these experiments. The method
combines standard graceful-labeling search ideas, including fixing label `0` at
a structurally important vertex, placing large edge differences first, and
expanding along the reduced branch structure. In these computations, it
substantially outperformed the earlier generic hybrid search on the hard
three-branch cases.

Additional branch-method results:

```text
MAX_SEGMENT = 6
cases = 55062
solved = 55062
timeouts = 0

MAX_SEGMENT = 7
cases = 151606
solved = 151606
timeouts = 0
hardest = fiveleaf3-2-6-6-7-6-7-7
hardest nodes = 25530
hardest elapsed = 0.519785s
```

For article-style reporting, an edge-count-bounded enumeration is now available:

```text
--five-leaf-nonspider-by-edges M
```

This enumerates all non-spider 5-leaf trees with at most `M` edges, which is a
more natural formulation than bounding every reduced-edge segment separately.
Reference sizes:

```text
edges <= 10: 100 cases
edges <= 15: 2319 cases
edges <= 20: 20119 cases
edges <= 25: 104885 cases
edges <= 30: 399052 cases
edges <= 35: 1225773 cases
edges <= 40: 3224679 cases
```

Completed edge-count-bounded run:

```text
edges <= 30
cases = 399052
method = branch
solved = 399052
timeouts = 0
hardest = fiveleaf2e-30-6-2-19-1-1-1
hardest nodes = 139060
hardest elapsed = 1.755366s
total wall time reported by user ~= 2500s
```

Completed edge-count-bounded run:

```text
edges <= 35
cases = 1225773
method = branch
initial solved = 1225772
initial timeouts = 1
replay solved = 1
final solved = 1225773
final timeouts = 0
timeout/replay case = fiveleaf2e-35-2-1-1-9-11-11
replay nodes = 717624
replay elapsed = 11.020516s
```

Completed edge-count-bounded run:

```text
edges <= 40
cases = 3224679
method = branch
initial solved = 3224678
initial timeouts = 1
replay solved = 1
final solved = 3224679
final timeouts = 0
timeout/replay case = fiveleaf2e-35-2-1-1-9-11-11
replay nodes = 717624
replay elapsed = 11.013337s
```

This family is a better next computational target than larger 5-leg spiders.
