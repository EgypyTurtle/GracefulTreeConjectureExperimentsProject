# Paper Outline

Working title:

```text
A Certificate-Producing Search Framework for Graceful and Antimagic Labelings
of Non-Spider Five-Leaf Trees
```

## Abstract

We present a certificate-producing search framework for graceful and antimagic
labelings of bounded non-spider five-leaf trees. The framework enumerates the
family through reduced skeleton parameters, searches for labelings using
branch-aware orderings, writes explicit labeling certificates, and independently
verifies solved rows from the resulting CSV logs. Timeout cases are not treated
only as failures; they drive an iterative refinement loop in which hard
patterns are replayed, classified, and used to adjust the search strategy.

## 1. Introduction

- Graceful Tree Conjecture: every finite tree is graceful.
- Antimagic labeling conjecture for connected graphs, and the tree case.
- Computational role: certificate-producing bounded verification, not proof of
  the full conjectures.
- Main contribution: an algorithmic search-and-replay framework for a natural
  infinite family, non-spider five-leaf trees.

## 2. The Five-Leaf Family

After suppressing degree-2 vertices, non-spider five-leaf trees have two
reduced skeletons:

```text
two-branch:    degree 3 branch -- degree 4 branch
three-branch:  degree 3 branch -- degree 3 branch -- degree 3 branch
```

Each reduced edge is assigned a positive integer length. Isomorphic duplicates
are avoided by sorting symmetric leaf-length tuples and by applying a canonical
orientation condition in the three-branch case.

## 3. Certificate Format

For each solved tree, the program emits:

- the case name encoding the reduced skeleton and segment lengths,
- the edge list,
- a graceful vertex-label certificate or antimagic edge-label certificate,
- search statistics.

The verifier `src/verify_certificates.py` checks the certificate without using
the search routine. This separates the certificate audit from the search
heuristic.

## 4. Graceful Search

The graceful solver uses several modes:

- direct vertex-label backtracking,
- edge-difference backtracking,
- spider-specific frontier search,
- branch-oriented difference search,
- constructive compression by caterpillar alpha-labeling and extremal
  pendant-path extension,
- hybrid fallbacks.

For non-spider five-leaf trees, the branch-oriented method fixes a branch
vertex at label 0 and assigns large edge differences while expanding through
already labeled branch structure.

The compressed method uses a proved rooted reduction: a graceful base whose
selected leaf is extremal generates every longer version of that pendant
segment. Rooted base certificates are canonicalized and reused across
isomorphic cases. A complete run through 20 edges reduced search nodes from
3,822,923 to 435,073 while independently verifying all 20,119 certificates.

The later 51--55 run added an opt-in adaptive fastpath for a recurrent hard
signature. The initial pass covered 15,800,487 trees and left 20 timeout rows;
a targeted replay solved all 20. In a separate 4,327-case controlled family,
the apparent `edges mod 3 = 2` difficulty was strong for ordinary branch
search but almost disappeared after pendant reduction. A 100,000-node
rooted-base budget solved the six remaining boundary cases.

## 5. Antimagic Search

The antimagic solver labels edges by a permutation of `1..m` and checks that
induced vertex sums are distinct. The current algorithm uses:

- deterministic branch-first edge ordering,
- conflict checks when vertex sums become final,
- interval-style pruning for possible future sums,
- randomized fallback trials only after a primary timeout.

The fallback mechanism is part of the algorithmic framework: it converts
search-order sensitivity into a reproducible hard-case treatment.

## 6. Iterative Hard-Pattern Loop

The computational protocol is:

```text
expand a bounded five-leaf family
  -> emit certificates for solved cases
  -> replay unresolved rows with larger or different budgets
  -> classify timeout cases by reduced skeleton parameters
  -> modify search order, pruning, or fallback strategy
  -> rerun the timeout set
```

The process stops for the current family when several rounds of targeted
optimization no longer reduce unresolved cases or produce new structural
information.

## 7. Current Results

Current graceful non-spider five-leaf verification:

```text
edges <= 30: 399052 / 399052 solved
edges <= 35: 1225773 / 1225773 solved
edges <= 40: 3224679 / 3224679 solved
edges <= 45: 7543822 / 7543822 solved
edges = 46: 1293708 / 1293708 solved
edges = 47: 1479482 / 1479482 solved
edges = 48-50: 5780094 / 5780094 solved
edges = 51-55: 15800487 enumerated; 20 initial timeouts; 20 solved by replay
```

The compressed 48-50 run enumerated 5,780,094 trees but produced only
2,166,443 distinct rooted reduction bases. The run completed without a
timeout in approximately 4 hours 56 minutes. This version reports the
operational reduction and speedup; detailed proof notes are deferred.

Current antimagic non-spider five-leaf verification:

```text
edges <= 35: 1225773 / 1225773 solved
edges <= 40: 3224679 / 3224679 solved
edges <= 45: 7543822 / 7543822 solved
edges <= 50: 16097106 / 16097106 solved
```

Ongoing runs should be added only after certificate verification.

## 8. Hard Cases and Algorithmic Lessons

This section should list:

- initial timeout cases,
- their reduced skeleton parameters,
- which replay or fallback solved them,
- which search modification was motivated by them,
- whether the pattern reappeared at larger edge bounds.

## 9. Reproducibility

- Python version.
- Exact command lines.
- Git commit hash.
- Log files or compressed result archives.
- Certificate verification command.

## 10. Limitations

- These are bounded computational verifications, not proofs of the full
  conjectures.
- The non-spider five-leaf family is natural but narrow.
- Randomized fallback is reproducible by seed but still heuristic.
- Larger leaf counts have higher-dimensional parameter spaces and should be
  treated as a later phase.
