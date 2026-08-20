# Active Research Roadmap

This file is the execution sheet for the next project cycle. It is more
specific than the paper outline and is intended to be updated after each
completed run.

## Current phase: close the five-leaf line at 65 edges

The current family is the complete non-spider five-leaf family. Its reduced
skeletons are:

```text
degree 3 -- degree 4
degree 3 -- degree 3 -- degree 3
```

Each reduced edge receives a positive length, with symmetric parameters
canonicalized. The target is the finite range through 65 edges. The project
does not automatically continue this family to 66 or higher edges.

### Current audit checklist

1. Edges 61--62 are complete after replay: 107,619 and 8,252,989 cases,
   respectively, with no unresolved rows.
2. Run edge 63, then edge 64 and edge 65 as separate compact-log layers.
3. Use the summary command on each log and compare the case counts with the
   exact enumerator.
4. Replay only rows whose final status is still unsolved or whose certificate
   has not yet passed independent verification.
5. Keep the first-pass and replay CSV files separate. Combine their results
   in the report, rather than concatenating files and losing provenance.
6. Record the 61, 62, 63, 64, and 65 edge totals separately.

Run the following commands from the repository root:

```powershell
$PY = "python"
```

Count the expected family layers:

```powershell
& $PY ".\src\graceful_tree.py" `
  --count-five-leaf-nonspider-by-edges 65 `
  --min-edges 61
```

Summarize an existing log without rerunning it:

```powershell
& $PY ".\src\graceful_tree.py" `
  --summarize-log ".\results\five_leaf_nonspider_edges61_65_adaptive.csv"
```

Replay an existing compact recovery log only when it still contains unsolved
rows:

```powershell
& $PY ".\src\graceful_tree.py" `
  --replay-unsolved ".\results\five_leaf_nonspider_edges61_65_recovery_compact.csv" `
  --method compressed `
  --time-limit 600 `
  --extension-fastpath-nodes 100000 `
  --extension-cache-size 100000 `
  --extension-cache-db ".\results\pendant_extension_cache.sqlite3" `
  --replay-log ".\results\five_leaf_nonspider_edges61_65_final_replay.csv" `
  --progress 1
```

The exact filenames above are templates: use the actual first-pass and
recovery files present in `results`. Do not rerun a completed layer merely to
produce a second copy of the same certificates.

## What the five-leaf data currently says

The strongest reusable statements are structural and conditional:

- the two reduced non-spider skeletons are a complete classification;
- extremal-label pendant-ray extension is valid for any tree once the marked
  rooted certificate exists;
- rooted certificates can be persisted and reused across larger edge ranges;
- the recurring timeout pattern is concentrated in a small set of short-path
  and long-path signatures, especially in unbalanced three-branch cases;
- the old modulo-3 runtime effect is substantially reduced by the rooted
  certificate path;
- selected 62-edge hard cases admit explicit fixed-core/path-word
  constructions and verified defect switches.

The data does **not** currently justify any of the following claims:

- every five-leaf tree has a certificate of the same rooted type;
- every tree with a long terminal path reduces to a smaller graceful tree;
- a timeout is evidence of non-gracefulness;
- the bounded computation proves the Graceful Tree Conjecture.

## Next implementation: arbitrary leaf count

The current CLI is specialized to five leaves. Before running six-leaf trees,
implement a new generator and command family rather than passing a new number
to the five-leaf option.

The intended interface is:

```text
--k-leaf-nonspider-by-edges K MAX_EDGES
```

or an equivalent interface with an explicit minimum edge count. The generator
must:

1. enumerate branch-degree partitions satisfying
   `sum(deg(v)-2) = K-2`;
2. generate non-isomorphic reduced tree skeletons;
3. attach positive subdivision lengths;
4. canonicalize all skeleton symmetries;
5. emit a stable case name that can be replayed after interruption.

The solver layer should reuse the existing generic graph representation, but
the reduction layer must be conservative: a certificate is reused only when
the rooted shape and the required extremal-label condition both match.

For `K = 6`, the first run should be a small exact-edge smoke test. Only after
the generator count, certificate verifier, and replay path agree should the
edge bound be increased. Then repeat the same cycle for `K = 7` through `20`.

## Generic graph solver (implemented)

The first generic solver is now available as `src/graceful_graph.py`. It takes
an arbitrary simple undirected edge list and searches the ordinary graceful
labeling constraints without assuming `m = n - 1`, acyclicity, or connectedness.
Its certificate verifier accepts injective labels from `0..m`, rather than
requiring every label in that interval to be used. The latter distinction is
necessary for graphs with more edges than vertices minus one.

The generic solver will usually be slower than the tree solver. It loses the
tree-only branch ordering, pendant-path reduction, and rooted extension
certificates. The slowdown is the intended architectural tradeoff: graph
families can now supply only an edge set and do not need to duplicate the
labeling search. The first implementation is a complete difference search
unless an explicit time, node, or candidate cutoff is supplied.

## Optional later phase: a selected graph-family question

The generic solver is implemented, but it should not trigger an automatic run
over arbitrary regular graphs. After the leaf-family work, select one public
question first. The two most natural candidates are the unicyclic-graph
conjecture (excluding the known non-graceful cycle cases) and the conjecture
that every connected cubic graph is graceful. Cycles and complete bipartite
graphs are regression benchmarks, not the main novelty target.

## Required record for every phase

Each phase gets a separate results prefix and must record:

```text
family definition
exact case count
first-pass solved / timeout count
replay solved / unresolved count
search nodes and wall time
reduction coverage and cache reuse
hard-pattern summary
independent certificate-verification result
```

The phase advances only after the timeout cases have either been solved by a
reproducible replay or clearly documented as unresolved, and after the next
algorithmic improvement has been tested on the affected pattern.
