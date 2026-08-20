# Generic Graceful-Graph Solver

`src/graceful_graph.py` is the family-independent search layer. It accepts a
simple undirected graph as an edge list and does not assume that the graph is
a tree, connected, or acyclic.

## Input format

Create a text file with one edge per line:

```text
0 3
0 4
1 3
1 4
2 3
2 4
```

Blank lines and text after `#` are ignored. Duplicate edges and self-loops
are rejected. If the file omits isolated vertices, pass `--vertices N` to
retain the full vertex set `0..N-1`.

## Run one graph

From the repository root:

```powershell
$PY = "python"
& $PY ".\src\graceful_graph.py" `
  --edges ".\examples\my_graph.edges" `
  --time-limit 60 `
  --show-edges
```

Without a time or node limit, the difference search is exhaustive. A result
with a label list is checked internally before it is printed. A timeout is
reported separately from an exhausted search; neither is a proof of
non-gracefulness unless the search was exhaustive.

## Definition used by the solver

For `m` edges, the solver searches for distinct vertex labels in `0..m` such
that the edge differences are exactly `1..m`. Unlike the tree verifier, it
does not require all labels `0..m` to be used: a graph with more edges than
vertices has unused labels. It rejects immediately when `n > m + 1`, since an
injective label assignment is then impossible.

## Search and performance

The search assigns differences from `m` down to `1`. The edge carrying `m`
must join labels `0` and `m`, so every possible edge is tried as that anchor;
global label complementation removes the duplicate orientation. Later moves
propagate labels through already constrained endpoints and check every edge
cycle when both endpoints become labeled.

This is deliberately more general and usually slower than
`src/graceful_tree.py`:

- it cannot use `m = n - 1`;
- it cannot use tree-rooted tension integration as the only representation;
- it has no pendant-path or caterpillar reduction unless a graph family adds
  a separately proved reduction;
- cycles create consistency constraints that are absent from trees.

The generic layer is therefore a reusable baseline, not a replacement for
the optimized tree solver. The intended architecture is:

```text
graph-family generator
  -> canonical edge set
  -> solve_graceful_graph(n, edges)
  -> verify_graceful_labeling(n, edges, labels)
```

The optional `--candidate-limit` is a heuristic cutoff. It can help explore a
hard graph quickly, but runs using it must not be reported as exhaustive.
