# Research TODO

This is the current execution order for the project. The project follows a
closed loop at every stage:

```text
enumerate a defined family
  -> search and write certificates
  -> independently verify the certificates
  -> replay and classify timeouts
  -> formulate a structural reduction or search improvement
  -> implement and test the improvement
  -> rerun the affected cases
  -> decide whether the family has reached its stopping condition
```

## 1. Finish the non-spider 5-leaf family at 65 edges

Status: **63 complete and frozen; edge 64 in progress (37.8%); 65 not started; do
not expand beyond 65 edges**.

- [x] Complete and audit edges 61--62. The final total is 8,360,608 solved
  cases after replay, with independent verification of all replay certificates.
- [x] Run and audit edge 63. Closed by alternative certificate searches: all 93
  initial hard rows solved, all new certificates independently verified. The
  cumulative total through edge 63 is 76,946,647 solved certificates with zero
  unresolved after replay.
- [ ] Finish edge 64. The frozen universe is 10,040,677 cases. The first
  cascade stage, `compressed_0.5s`, is at 3,800,064 processed (1,291,124 solved,
  2,508,940 survivors, 0 errors) with 37 verification checkpoints all passing.
  Later stages are not started.
- [ ] Resolve the edge 64 production stall before the next long run. See
  [docs/edge64_production_stall_incident.md](docs/edge64_production_stall_incident.md):
  the first attempt wedged on 2026-09-14 and wrote nothing for ~39 hours, and
  the runner's unbounded verification subprocess was the highest-severity
  defect. Resolved in the runner, but the exact wedge trigger was never
  reproduced; treat a resumed run as unproven until it passes the point where
  the previous one stopped.
- [ ] Audit edge 65 after 64 closes. Keep each layer's first-pass and replay
  logs separate.
- [ ] Record the per-edge case count, first-pass timeouts, replay time, final
  solved count, reduction coverage, and persistent-cache reuse.
- [x] Recheck the hard-pattern comparison and the 62-edge fixed-core
  constructions against the final replay certificates.
- [ ] Freeze this family after the 65-edge audit. Further work on it should
  be theorem writing or a clearly isolated algorithm experiment, not an
  automatic jump to 66+ edges.

### Operational note for long runs

The edge 64 stall was only detectable because a process was inspected by hand.
Any multi-hour run should be started with `--log-file` and monitored on the
heartbeat file's mtime. A live process whose heartbeat stops advancing is
wedged, not slow; stop it and record it rather than leaving it running.

### Reliable five-leaf observations to preserve

- Suppressing degree-2 vertices leaves exactly two non-spider skeletons:
  a degree-3/degree-4 pair and a path of three degree-3 branch vertices.
- A graceful certificate with a marked leaf at label 0 or at the maximum
  label extends along an arbitrary pendant ray. This is an unconditional
  certificate-extension theorem, not a claim that every tree has such a
  certificate.
- In the 48--50 experiment, 5,780,094 trees reduced to 2,166,443 distinct
  rooted instances; 83.49% of cases reused previous certified reductions.
- In the small ablation through 20 edges, compression reduced search nodes
  by about 88.6% and case time by about 87.7%.
- The recurring hard signature has short pendant paths together with long
  terminal paths in an unbalanced multi-branch skeleton. The apparent
  edge-count modulo-3 effect was strong for the old search order and nearly
  disappeared after pendant reduction, so it is currently treated as a
  search-state effect rather than an obstruction.
- The fixed-core and defect-switch work gives finite verified constructions
  for selected boundary cases. It does not yet give a complete theorem for
  all five-leaf trees.

## 2. Add leaf counts 6 through 20

Status: **next major line; implementation required before the first run**.

Process one leaf count at a time:

- [ ] Implement a canonical reduced-skeleton generator for exactly `k` leaves,
  beginning with `k = 6`.
- [ ] Generate all branch-degree multisets satisfying
  `sum(deg(v) - 2) = k - 2`, generate the reduced tree skeletons, and quotient
  by skeleton automorphisms.
- [ ] Assign positive lengths to reduced edges and canonicalize isomorphic
  parameter vectors.
- [ ] Generalize the current branch, compressed, rooted-certificate, and
  timeout-replay pipeline from five leaves to `k` leaves.
- [ ] Validate the generator against independently counted small cases before
  launching a long run.
- [ ] For each `k`, increase the exact edge bound until the next layer has a
  projected wall time that is too large or the timeout/replay loop stops
  producing useful algorithmic information.
- [ ] Before increasing `k`, finish replaying the current layer and publish
  the reduction statistics and the surviving hard signatures.
- [ ] Repeat for `k = 6, 7, ..., 20`; never claim that a result for one leaf
  count covers another leaf count without a proved extension theorem.

### Stopping rule for each new leaf count

Stop the current leaf-count line when at least one of the following occurs:

1. the next exact-edge layer is projected to exceed roughly one week on the
   available machine;
2. the timeout fraction keeps increasing after targeted replay and no new
   reduction is found;
3. the remaining family is dominated by a repeated certificate pattern and a
   structural theorem is more valuable than another bulk run.

At that point, freeze the data, document the bottleneck, and only then move to
the next leaf count.

## 3. Optional graph-family phase

Status: **infrastructure implemented; research family not yet selected**.

- [x] Build a generic graceful-graph input, searcher, and certificate verifier
  (`src/graceful_graph.py`).
- [x] Build a generic graceful-graph input, searcher, and certificate verifier
  (`src/graceful_graph.py`).
- [ ] First select a specific public graph-family question, such as non-cycle
  unicyclic graphs or connected cubic graphs.
- [ ] Use cycles and complete bipartite graphs only as correctness benchmarks,
  not as the main novelty target.
- [ ] Add a family generator, canonicalization, replay logs, and independent
  verification before any large graph run.
- [ ] Do not enumerate arbitrary `d`-regular graphs without a stated open
  problem and necessary-condition filters.

## Reporting rule

Every completed stage must preserve:

- the exact family definition and case count;
- the solver version and command line;
- first-pass and replay logs separately;
- an independent certificate-verification result;
- timeout structures and the algorithmic change motivated by them;
- a clear distinction between a bounded computational result, a sufficient
  reduction theorem, and a conjectural pattern.
