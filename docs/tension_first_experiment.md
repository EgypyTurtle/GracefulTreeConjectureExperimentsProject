# Tension-First Search Experiment

## Mathematical view

For an oriented tree with incidence matrix `B`, a vertex labeling `f`
induces the signed edge-difference vector `t = B^T f`.  This is an integer
tension.  A graceful labeling is the special case in which the absolute
entries of `t` are exactly `1,...,m` and the integrated vertex potentials are
the permutation `0,...,m`.

The experimental solver `--method tension` roots the tree at a candidate
zero-labelled vertex, forces the difference `m` onto a root edge, and then
assigns signed differences to the rooted frontier while integrating labels.
It is complete for graceful trees; it is not a nowhere-zero flow solver.

## Local benchmark

The implementation was checked on 220 random trees with 2--12 vertices and
every returned certificate was independently verified.

On a small sample of the existing five-leaf families, the method was mixed:

| family/sample | branch | ordinary diff | tension-first |
|---|---:|---:|---:|
| two-branch, 8 cases | 7/8 | 5/8 | 4/8 |
| three-branch, 6 cases | 4/6 | 4/6 | 4/6 |

One three-branch 53-edge hard pattern was solved in about 0.05 seconds by
tension-first versus about 0.11 seconds by ordinary difference search.  On
the two-branch 61--65-edge samples it was slower or timed out.  These results
do not justify changing the default solver.

## Current use

Run it explicitly on a single tree:

```powershell
& $PY ".\src\graceful_tree.py" `
  --spider 1 3 5 7 9 `
  --method tension `
  --time-limit 60
```

The next useful experiment is a paired replay of recorded hard cases, using
the same time budget for `branch`, `diff`, and `tension`.  A method should be
promoted into `hybrid` only after a stratified comparison shows a repeatable
gain by tree family, not from one successful example.
