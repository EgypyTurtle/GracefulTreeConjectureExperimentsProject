# Graceful Tree and Graph Labeling Experiments

Certificate-producing search experiments for graceful and antimagic labelings.
The main research object is the Graceful Tree Conjecture, with emphasis on
bounded non-spider five-leaf trees. A separate generic edge-set solver is
included as infrastructure for a future, explicitly chosen graph-family
problem.

## Scope

For a graph with `m` edges, a graceful labeling is an injective vertex
labeling by values in `0..m` whose absolute edge differences are exactly
`1..m`.

The Graceful Tree Conjecture asks whether every finite tree is graceful. This
repository does not claim to prove it. It records bounded,
certificate-checked computations and the structural reductions used to make
those computations practical.

The two search layers are deliberately separate:

```text
tree family generator -> tree-specific solver and reductions
graph family generator -> generic edge-set solver
```

The tree solver is the primary tool for the current project. The generic graph
solver is reusable infrastructure; it does not replace tree-specific
algorithms.

## Current Status

### Graceful non-spider five-leaf trees

The complete non-spider five-leaf family is covered through 62 edges after
targeted replay of timeout cases:

```text
edge range       cases        final solved     final unresolved
<=45             7,543,822    7,543,822        0
46               1,293,708    1,293,708        0
47               1,479,482    1,479,482        0
48-50            5,780,094    5,780,094        0
51-55           15,800,487   15,800,487        0
56               4,396,261    4,396,261        0
57               4,905,851    4,905,851        0
58               5,463,653    5,463,653        0
59               6,073,447    6,073,447        0
60               6,738,836    6,738,836        0
61                 107,619      107,619        0
62               8,252,989    8,252,989        0
```

Cumulative status through 62 edges:

```text
67,836,249 solved certificates
0 unresolved after replay
```

The final five 62-edge cases were recovered by three independent replay
strategies: 12 by a 600-second compressed replay, 2 by a longer branch replay,
and 3 by a difference-search replay. The independent verifier reported
`bad=0` on all three replay logs. Edge 63 is the next unstarted layer and
contains 9,110,398 cases.

Other recorded experiments:

```text
5-leg spiders, max leg <=15:        11,628 / 11,628 solved
5-leg spiders, max leg 16-20:       29,286 / 30,876 solved in the recorded run
antimagic 5-leaf trees, edges <=50: 16,097,106 / 16,097,106 solved
rooted types through 13 vertices:   20,299 processed, 0 unresolved
```

The spider line is primarily solver validation because important spider
subfamilies already have theoretical coverage. The non-spider five-leaf line
is the main source of algorithmic and structural data.

See [docs/current_results.md](docs/current_results.md) and
[docs/technical_report.md](docs/technical_report.md) for the detailed public
accounting.

## Research Workflow

Each family follows this loop:

```text
define and enumerate a family
  -> search and write explicit certificates
  -> independently verify solved rows
  -> replay timeout cases
  -> classify hard structures
  -> formulate a reduction or search improvement
  -> implement and test the improvement
  -> rerun affected cases
  -> stop or expand only after the bottleneck is understood
```

The current order is:

1. Finish the five-leaf non-spider line through 65 edges.
2. Implement a canonical reduced-skeleton generator for 6--20 leaves.
3. Only then select a specific non-tree graph-family question for the generic
   graph solver, rather than enumerating arbitrary regular graphs.

See [TODO.md](TODO.md) and
[docs/research_roadmap.md](docs/research_roadmap.md).

## Requirements

Python 3.10 or newer is sufficient; only the standard library is required.

```powershell
python src/graceful_tree.py --help
python src/graceful_graph.py --help
python src/antimagic_tree.py --help
python src/verify_certificates.py --help
```

## Tree Search

Solve one spider:

```powershell
python src/graceful_tree.py --spider 7 8 10 10 10 --method spider --time-limit 30
```

Run the next exact edge layer with the compressed solver:

```powershell
python src/graceful_tree.py `
  --five-leaf-nonspider-by-edges 63 `
  --min-edges 63 `
  --method compressed `
  --extension-adaptive-budget `
  --extension-adaptive-nodes 100000 `
  --extension-fastpath-nodes 2000 `
  --extension-cache-size 100000 `
  --extension-cache-db results/pendant_extension_cache.sqlite3 `
  --compact-log `
  --time-limit 300 `
  --total-time-limit 604800 `
  --log results/five_leaf_nonspider_edges63_adaptive_compact.csv `
  --save-hardest results/hardest_edges63_adaptive.txt `
  --save-failed results/failed_edges63_adaptive.txt `
  --progress 20000
```

Summarize or replay only unsolved rows:

```powershell
python src/graceful_tree.py `
  --summarize-log results/five_leaf_nonspider_edges63_adaptive_compact.csv

python src/graceful_tree.py `
  --replay-unsolved results/five_leaf_nonspider_edges63_adaptive_compact.csv `
  --method compressed `
  --time-limit 600 `
  --extension-adaptive-budget `
  --extension-adaptive-nodes 300000 `
  --extension-cache-db results/pendant_extension_cache.sqlite3 `
  --replay-log results/five_leaf_nonspider_edges63_replay.csv `
  --progress 1
```

Independently verify a solved CSV:

```powershell
python src/verify_certificates.py `
  --kind graceful `
  --log results/five_leaf_nonspider_edges40_branch.csv
```

## Tree Families and Methods

After suppressing degree-2 vertices, every non-spider five-leaf tree has one
of two reduced skeletons:

```text
degree 3 branch -- degree 4 branch
degree 3 branch -- degree 3 branch -- degree 3 branch
```

The current CLI is intentionally specialized to five leaves. The planned
6--20 leaf line needs a new canonical reduced-skeleton generator; changing a
number in the five-leaf option would not be correct.

The tree solver provides `exact`, `diff`, `spider`, `branch`,
`tension`, `compressed`, `heuristic`, and `hybrid` methods. The
compressed method uses caterpillar constructions, extremal pendant-ray
extension, rooted certificate reuse, and branch fallback.

The 48--50 run reduced 5,780,094 raw trees to 2,166,443 distinct rooted
instances. A through-20 ablation reduced search nodes by about 88.6% and case
time by about 87.7%. Observed hard cases concentrate around unbalanced
multi-branch skeletons with short pendant paths and long terminal paths. The
earlier modulo-3 runtime effect largely disappears after rooted reduction and
is currently treated as a search-state effect, not an obstruction.

Detailed structural theorem drafts and proof-status notes are intentionally
kept in the local research workspace while the computational campaign is
ongoing. They are not part of the public repository yet.

## Generic Arbitrary-Graph Search

`src/graceful_graph.py` accepts any simple undirected edge set, including
cyclic and disconnected graphs, without assuming `m = n - 1`. It is a
family-independent baseline, not the current Graceful Tree Conjecture solver.

An edge file contains one edge per line. The repository includes
`examples/k33.edges`, a complete bipartite `K_3,3` example:

```powershell
python src/graceful_graph.py `
  --edges examples/k33.edges `
  --time-limit 60 `
  --show-edges
```

If isolated vertices are present, pass `--vertices N`; otherwise vertices are
inferred from edge endpoints. For `m` edges, the generic verifier checks
distinct labels in `0..m` and exact differences `1..m`; it does not require
every label in that interval to be used. It rejects `n > m + 1` immediately.

Without a time, node, or candidate limit, the difference search is exhaustive.
`--candidate-limit` is a heuristic cutoff and must not be used for an
exhaustive claim. It will usually be slower than the tree solver because it
does not have tree-specific branch ordering, pendant reductions, or rooted
tension integration.

Graph-family generators should import the solver instead of starting a new
process for every case:

```python
from graceful_graph import solve_graceful_graph, verify_graceful_labeling

labels, stats = solve_graceful_graph(n, edges, time_limit=60)
if labels is not None:
    assert verify_graceful_labeling(n, edges, labels)
```

More details are in [docs/generic_graph_solver.md](docs/generic_graph_solver.md).

## Certificates, Documentation, and Data

Tree and antimagic batch tools write case names, graph data, certificates, and
search statistics to CSV. `src/verify_certificates.py` checks solved rows
without invoking the search algorithm. The generic solver verifies a single
certificate before printing it.

Key documents:

- [TODO.md](TODO.md): tasks and stopping rules;
- [docs/current_results.md](docs/current_results.md): numerical summary;
- [docs/technical_report.md](docs/technical_report.md): technical report;
- [docs/runbook.md](docs/runbook.md): replay and recovery commands;
- [docs/research_roadmap.md](docs/research_roadmap.md): execution plan;
- [docs/paper_outline.md](docs/paper_outline.md): article outline.

Full CSV logs and the SQLite cache remain local because they can reach multiple
gigabytes. The GitHub version contains source code, tests, reproducible
commands, small examples, and compact summaries. Commands use paths relative to
the repository root; no machine-specific absolute paths are required.

## Tests and License

```powershell
python -m unittest discover -s tests -v
```

The test suite covers tree compression, replay reconstruction, hard-pattern
experiments, rooted certificates, free-tree prototypes, and the generic graph
solver.

See [LICENSE](LICENSE).
