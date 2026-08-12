# Graceful Tree Labeling Algorithmic Search

Certificate-producing search algorithms for graceful and antimagic labelings of
trees, with emphasis on bounded non-spider 5-leaf trees.

A graceful labeling of a tree with `m` edges assigns distinct vertex labels from
`0..m` so that the absolute differences on the edges are exactly `1..m`.

This repository contains:

- A standalone Python search tool: `src/graceful_tree.py`.
- A standalone antimagic search tool: `src/antimagic_tree.py`.
- An independent CSV certificate verifier: `src/verify_certificates.py`.
- Dedicated search methods for spider trees and branch-structured trees.
- Constructive compression using caterpillar alpha-labelings, extremal
  pendant-path extension, and rooted-certificate reuse.
- Reproducible command lines for expanding bounded tree families.
- A technical report summarizing algorithms, certificates, and current results.

The intended workflow is algorithmic rather than just enumerative:

```text
expand a bounded 5-leaf family
  -> solve each case and emit a certificate
  -> replay and analyze timeout cases
  -> redesign the search order or fallback around the hard pattern
  -> repeat until the current family stops producing useful algorithmic data
```

For solved rows, the CSV log contains the tree and a labeling certificate. The
verifier checks those rows without using the search algorithm.

## Highlights

The current computations include:

```text
5-leg spider trees:
  max leg <= 15: fully solved computationally
  max leg 16-20: 29286 / 30876 solved before stopping this line

Non-spider 5-leaf trees:
  max segment <= 3: 693 / 693 solved
  max segment <= 4: 4080 / 4080 solved
  max segment <= 5: 16875 / 16875 solved
  max segment <= 6: 55062 / 55062 solved
  max segment <= 7: 151606 / 151606 solved
  edges <= 30: 399052 / 399052 solved
  edges <= 35: 1225773 / 1225773 solved
  edges <= 40: 3224679 / 3224679 solved
  edges <= 45: 7543822 / 7543822 solved
  edges = 46: 1293708 / 1293708 solved
  edges = 47: 1479482 / 1479482 solved
  edges = 48-50: 5780094 / 5780094 solved
  edges = 51-55: 15800467 / 15800487 solved in initial pass
  edges = 51-55: 20 / 20 timeout cases solved by adaptive replay
  cumulative through 55: 31897593 covered after replay

Antimagic non-spider 5-leaf trees:
  edges <= 10: 100 / 100 solved
  edges <= 20: 20119 / 20119 solved
  edges <= 25: 104885 / 104885 solved
  edges <= 35: 1225773 / 1225773 solved
  edges <= 40: 3224679 / 3224679 solved
  edges <= 45: 7543822 / 7543822 solved
  edges <= 50: 16097106 / 16097106 solved
```

The 5-leg spider family is already covered by known theoretical results, so
the more interesting current direction is the non-spider 5-leaf family and
hard-pattern behavior in labeling search.

## Requirements

Python 3.10 or newer is enough. The tool uses only the Python standard library.

Check the CLI:

```bash
python src/graceful_tree.py --help
python src/antimagic_tree.py --help
python src/verify_certificates.py --help
```

## Examples

Solve one spider tree:

```bash
python src/graceful_tree.py --spider 7 8 10 10 10 --method spider --time-limit 30
```

Sweep all non-spider 5-leaf trees whose reduced-edge segment lengths are at
most 6:

```bash
python src/graceful_tree.py \
  --five-leaf-nonspider-sweep 6 \
  --method branch \
  --time-limit 10 \
  --log results/five_leaf_nonspider_max6_branch.csv \
  --save-hardest results/hardest_five_leaf_nonspider_max6_branch.txt \
  --save-failed results/failed_five_leaf_nonspider_max6_branch.txt \
  --progress 1000
```

Summarize a CSV log:

```bash
python src/graceful_tree.py --summarize-log results/five_leaf_nonspider_max6_branch.csv
```

Verify graceful certificates from a CSV log:

```bash
python src/verify_certificates.py \
  --kind graceful \
  --log results/five_leaf_nonspider_edges40_branch.csv
```

Run the antimagic case study on non-spider 5-leaf trees with at most 20 edges:

```bash
python src/antimagic_tree.py \
  --five-leaf-nonspider-by-edges 20 \
  --time-limit 5 \
  --log results/antimagic_five_leaf_nonspider_edges20.csv \
  --progress 1000
```

Verify antimagic certificates from a CSV log:

```bash
python src/verify_certificates.py \
  --kind antimagic \
  --log results/antimagic_five_leaf_nonspider_edges45_fallback.csv
```

Sweep all non-spider 5-leaf trees with at most 30 edges:

```bash
python src/graceful_tree.py \
  --five-leaf-nonspider-by-edges 30 \
  --method branch \
  --time-limit 10 \
  --log results/five_leaf_nonspider_edges30_branch.csv \
  --save-hardest results/hardest_five_leaf_nonspider_edges30_branch.txt \
  --save-failed results/failed_five_leaf_nonspider_edges30_branch.txt \
  --progress 5000
```

Run the constructive compression method on a new edge interval:

```bash
python src/graceful_tree.py \
  --five-leaf-nonspider-by-edges 47 \
  --min-edges 46 \
  --method compressed \
  --time-limit 300 \
  --log results/five_leaf_nonspider_edges46_47_compressed.csv \
  --progress 20000
```

The same pendant-path reduction is available for generic input families; it
is not restricted to the five-leaf enumerator. For example, this runs a small
lobster batch and lets each tree try all eligible terminal paths under one
shared budget:

```bash
python src/graceful_tree.py \
  --lobster-batch 10000 \
  --base-vertices 12 \
  --method compressed \
  --extension-try-all-paths \
  --extension-cache-db results/pendant_extension_cache.sqlite3 \
  --time-limit 30 \
  --log results/lobster_compressed.csv \
  --progress 100
```

## Tree Families

### Spider Trees

A spider tree has one branch vertex and several legs. For example:

```text
spider-20-20-20-20-20
```

means a 5-leg spider with five legs of length 20. It has `100` edges and
`101` vertices.

### Non-Spider 5-Leaf Trees

A non-spider 5-leaf tree has exactly five leaves and more than one branch
vertex. After suppressing degree-2 vertices, there are two reduced skeletons:

```text
two-branch:    degree 3 branch -- degree 4 branch
three-branch:  degree 3 branch -- degree 3 branch -- degree 3 branch
```

The option `--five-leaf-nonspider-sweep N` enumerates these reduced skeletons
and subdivides every reduced edge by a positive length at most `N`.

The option `--five-leaf-nonspider-by-edges M` instead enumerates the same
family with total edge count at most `M`. This is usually the cleaner statement
for reports and articles.

## Search Methods

- `exact`: direct backtracking over vertex labels.
- `diff`: backtracking by edge differences from large to small.
- `spider`: spider-specific difference search.
- `branch`: branch-oriented difference search for multi-branch trees.
- `compressed`: caterpillar construction, rooted pendant-path reduction,
  cached base certificates, and `branch` fallback.
- `heuristic`: randomized local search.
- `hybrid`: tries structural methods and then generic methods.

The `branch` method is the key method for the non-spider 5-leaf computations.
It fixes label `0` at a branch vertex, then assigns large edge differences
while expanding through already labeled branch structure.

The `compressed` method turns one extremal-leaf base certificate into
certificates for longer pendant paths. New logs record `strategy`,
`reduction_base`, and `extended_edges` so the reduction chain remains
auditable. By default, rooted certificates are also persisted in
`results/pendant_extension_cache.sqlite3`; the in-memory cache is only a
speed layer and is limited by `--extension-cache-size`. See
[docs/current_results.md](docs/current_results.md) for the current reduction
statistics and the complete `edges <= 20` ablation. Detailed proof notes are
intentionally not part of this snapshot.

The reduction itself is a sufficient certificate rule for any tree containing
an eligible pendant path: if the shortened rooted tree has a certificate with
the retained leaf at an extremal label, the path can be rebuilt one edge at a
time. The five-leaf non-spider family is only the first family for which this
repository has an exhaustive enumerator and a large systematic data set. The
generic sources (`--edges`, `--random`, `--batch`, `--lobster-batch`, and
`--spider-sweep`) already use the same compressed solver. The optional
`--extension-try-all-paths` flag asks it to test every eligible pendant path;
without that flag the historical longest-path fast path is preserved.

This does not claim that every graceful tree must reduce in this way. Trees
whose useful extension is an internal bridge subdivision, or whose available
certificate does not put the retained leaf at an extremal label, need a
different composition lemma or a fallback search.

The exact scope of this rule and the distinction between structural candidates
and verified certificates are documented in
[docs/reduction_theorem.md](docs/reduction_theorem.md). Reduction coverage can
be aggregated from one or more CSV logs without rerunning the solver:

```bash
python src/graceful_tree.py \
  --summarize-reduction results/five_leaf_nonspider_edges48_50_compressed.csv \
  --reduction-summary-output results/reduction_48_50.csv
```

The controlled hard-pattern comparison is implemented in
`src/hard_pattern_experiment.py`. It fixes a two-branch tree with bridge 2,
two pendant paths of length 1, and three sorted long paths `(a,b,c)`. The
experiment compares ordinary branch search with 2,000-node and 20,000-node
pendant-reduction fast paths, while recording edge count modulo 3.
The completed comparison is summarized in
[docs/hard_pattern_experiment_report.md](docs/hard_pattern_experiment_report.md).
The six remaining boundary cases have a separate targeted experiment in
`src/hard_boundary_experiment.py`.
That replay solved all six with a 100,000-node rooted-base budget; all-paths
search did not improve on the single longest-path choice.

The main solver now has an opt-in adaptive budget for this observed pattern:
`--extension-adaptive-budget` raises the rooted-base budget to
`--extension-adaptive-nodes` (100,000 by default) only when the tree matches
the structural signature: five leaves, two or three branch vertices, at least
two terminal paths of length at most 3, and three remaining terminal paths of
length at least 9. The default compressed behavior is unchanged.

Recoverable certificates from older compressed CSV logs can be imported with
`--import-extension-cache`; this lets later runs reuse certificates after a
restart. The importer validates the recovered rooted certificate before
inserting it, so it can also extract compatible certificates from older logs
that do not record a search strategy.

The latest compressed 48-50 run enumerated 5,780,094 trees but recorded only
2,166,443 distinct rooted reduction bases. The run completed with no timeout,
and took about 4 hours 56 minutes. See
[docs/current_results.md](docs/current_results.md) for the strategy breakdown
and the comparison with the uncompressed branch search.

The subsequent 51-55 run enumerated 15,800,487 trees. Its initial pass left
20 timeout rows; a targeted adaptive replay solved all 20, and all 20 replay
certificates passed the independent verifier. The adaptive rule raises the
rooted-base budget only for a recurring five-leaf hard signature, leaving the
historical default unchanged for other trees.

For antimagic labeling, the current framework uses deterministic branch-first
edge-label search and, only after a primary timeout, randomized fallback trials.
This makes timeouts useful diagnostic objects: when a case is hard, it is
replayed, structurally classified, and used to tune the next search order.

## Certificates

The search tools write CSV rows containing:

```text
case name
vertex count
edge list
labeling certificate
search statistics
```

For graceful rows, the certificate is a list of vertex labels. For antimagic
rows, the certificate is a list of edge labels in the same order as the edge
list. `src/verify_certificates.py` independently checks solved rows and ignores
unsolved rows, so partial logs from interrupted long runs can still be audited.

## Report

See [docs/technical_report.md](docs/technical_report.md) for the current
technical summary, known-result context, and experiment status.
The concise public result summary is in
[docs/current_results.md](docs/current_results.md).
Detailed constructive proof notes are being kept for a later revision.

## Data Policy

The GitHub version contains source code, reproducible commands, tests, and
compact result summaries. Generated search data is kept locally:

- Full CSV logs under `results/` are ignored because they can reach multiple
  gigabytes.
- The persistent certificate database under `results/` is a local accelerator
  and is not part of the source distribution.
- Temporary hardest/failed edge lists are also excluded.
- Small hand-picked examples may be placed under `examples/`.

The current graceful computation through 50 edges contains
`16,097,106 / 16,097,106` solved cases. The separate antimagic computation
through 50 edges also contains `16,097,106` valid solved rows. The numerical
summaries in `docs/current_results.md` are the public record for the larger
local runs.
