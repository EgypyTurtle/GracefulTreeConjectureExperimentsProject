# Edge 63 Public Status

Date: 2026-09-05

## Exhaustive family result

The edge-63 non-spider five-leaf enumeration contains 9,110,398 cases. The
main search solved 9,110,305 cases and initially left 93 hard rows. Alternative
certificate searches solved the remaining 93 rows. All new certificates passed
an independent verifier.

```text
cases:       9,110,398
certificates: 9,110,398
unresolved:  0
```

This is a finite computational result for the declared five-leaf family. It is
not a proof of the Graceful Tree Conjecture.

## Structural probe

A separate single-interval construction experiment used the three-branch
skeleton, seven maximal paths, one consecutive difference interval per path,
and the complete Level-B local behavior language.

```text
fiveleaf3e-63-3-21-2-20-9-4-4   UNSAT_EXHAUSTIVE
fiveleaf3e-63-3-5-4-20-1-14-16  SAT_VERIFIED
```

The first result has exact minimum relative-offset span 66, so its
single-interval language misses the label window by 3. This does not show that
the tree is non-graceful; the unrestricted tree already has a graceful
certificate. The second case has a verified single-interval certificate with
span 63. Together they indicate a parameter-dependent span frontier rather
than a uniform obstruction.

The verified second-case example is kept in
`examples/edge63_single_interval_case2.txt`. Raw search logs, generated CSV
files, checkpoints, and exploratory implementation files remain local and are
intentionally not part of the public repository.

## Proof status

The structural probe uses the following proved local statements:

- translated-offset collision is equivalent to avoiding a fixed integer
  difference set;
- distinct relative offsets with span at most `E` can be translated into
  labels `0..E`;
- seven consecutive path blocks give a graceful labeling when their recovered
  offsets are distinct and fit the span budget.

These lemmas concern the construction language above. They are not a general
graceful-labeling theorem for all trees.
