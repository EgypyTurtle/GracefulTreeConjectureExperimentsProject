# Graceful Tree Labeling Experiments

Computational experiments for graceful and antimagic labelings of trees, with
emphasis on spider trees and bounded non-spider 5-leaf trees.

A graceful labeling of a tree with `m` edges assigns distinct vertex labels from
`0..m` so that the absolute differences on the edges are exactly `1..m`.

This repository contains:

- A standalone Python search tool: `src/graceful_tree.py`.
- A standalone antimagic search tool: `src/antimagic_tree.py`.
- Dedicated search methods for spider trees and branch-structured trees.
- Reproducible command lines for the experiments.
- A technical report summarizing the current computations.

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

Antimagic non-spider 5-leaf trees:
  edges <= 10: 100 / 100 solved
  edges <= 20: 20119 / 20119 solved
  edges <= 25: 104885 / 104885 solved
  edges <= 35: 1225773 / 1225773 solved
  edges <= 40: 3224679 / 3224679 solved
  edges <= 45: 7543822 / 7543822 solved
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

Run the antimagic case study on non-spider 5-leaf trees with at most 20 edges:

```bash
python src/antimagic_tree.py \
  --five-leaf-nonspider-by-edges 20 \
  --time-limit 5 \
  --log results/antimagic_five_leaf_nonspider_edges20.csv \
  --progress 1000
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
- `heuristic`: randomized local search.
- `hybrid`: tries structural methods and then generic methods.

The `branch` method is the key method for the non-spider 5-leaf computations.
It fixes label `0` at a branch vertex, then assigns large edge differences
while expanding through already labeled branch structure.

## Report

See [docs/technical_report.md](docs/technical_report.md) for the current
technical summary, known-result context, and experiment status.

## Data Policy

Full CSV logs can become large. This repository keeps a small example CSV under
`examples/`. For larger runs, generate logs locally using the commands above or
publish compressed result archives separately.

The current antimagic workflow uses a deterministic search followed by a
randomized fallback only for timeout cases. On the `edges <= 40` hard cases,
this resolved all five initial timeouts and reduced the observed search from
millions of deterministic nodes to a few hundred randomized nodes in the
successful trials.

The same workflow has now solved all `7,543,822` non-spider five-leaf trees
with at most 45 edges. The run used randomized fallback on 552 cases and had
no final timeouts.
