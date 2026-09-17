# Compressed-Method Extension Budget — Optimization Record

Date: 2026-09-17

## Finding

The compressed method first reduces a pendant path to a single edge, searches a
graceful labeling of that smaller rooted base, and then rebuilds the original
tree by extremal extension. The base search was capped at
`extension_fastpath_nodes = 2_000`.

That cap was set far below the cost of what happens when it fails. On failure
the method falls through to `solve_graceful_branch_differences`, a full
difference search that is allowed to consume the rest of the case budget.
Measured on three disjoint samples drawn from the edge 64 universe:

```text
sample                         cases   branch fallbacks   fallback share of nodes
offset 3,825,152 (stall tail)  1,000   119               51%
offset 1,500,000                 400    see below         see below
offset 2,600,000                 400     5                ~89% at 5k
```

The fallback is the expensive path, and it was being reached by cases that a
slightly larger bounded base search solves outright.

## Measurement

`src/diag_ablate_compressed.py` ablates the knob on a fixed sample;
`src/diag_profile_stage.py` measures the full compressed stage; and
`src/compare_profiles.py` diffs two captured profiles.

Held-out region, 500 cases at manifest offset 4,000,000, cold certificate cache:

```text
metric                      2,000 nodes    20,000 nodes     change
solved                         495/500         499/500        +4
survivors                            5               1       -80%
cases burning the full 0.5 s         5               1       -80%
wall                           23.24 s         19.07 s      -18%
mean latency                   46.46 ms        38.11 ms      -18%
p90 latency                   106.33 ms       88.87 ms      -16%
p99 latency                   501.44 ms      224.41 ms      -55%
branch fallback nodes          236,791          10,359      -96%
```

Strategy mix moved from `pendant-extension 440 / +branch 59` to
`pendant-extension 498 / +branch 1`.

The same direction reproduced on two further disjoint samples:

```text
region                       2,000      5,000     10,000     20,000
offset 3,825,152, 500 cases  491/500      --        --       500/500
offset 1,500,000, 400 cases  baseline     399       400/400      --
offset 2,600,000, 400 cases      --      400/400    399/400   400/400
```

## Why raising the cap is faster, not slower

The counter-intuitive part is that a *larger* search budget reduced wall time.
The reason is that the two paths have very different costs:

- a base search that succeeds returns immediately and stops the case;
- a base search that fails hands off to a fallback that runs to the end of the
  0.5 s budget far more often.

`all_paths_nodes_20k_cache0` visited 212,767 nodes on region A and solved all
500 cases in 8.16 s, while the 2,000-node baseline visited roughly the same
238,287 nodes but needed 12.63 s and solved 491. Total node count stayed flat
while solve rate rose, so the extra nodes go into bases that terminate early
instead of into fallbacks that terminate at the deadline.

`extension_try_all_paths` was also ablated and had no measurable effect
(490/500 vs 491/500 on region A). It is left `False`; trying every pendant path
is not where the win is.

## Change applied

`src/edge64_baseline.py`, `options()`:

```text
extension_fastpath_nodes   2_000  ->  20_000
```

`run_one` rebuilds `options()` for every case, so this takes effect
immediately, including inside an already-running production process.

## Methodological caveat

Because `run_one` reads `options()` per case, editing the default while a stage
is running makes that stage **heterogeneous**: batches computed before the edit
used 2,000 nodes and batches after it use 20,000. That does not affect
certificate validity — every solved row still carries an independently verified
graceful labeling — but it does mean the stage was not produced under a single
frozen configuration.

The repository's reporting rule asks for the solver version and command line to
be preserved per run. A stage that spans this edit cannot satisfy that as a
single run. The options are therefore:

```text
continue   accept a heterogeneous stage; the 20,000-node setting applies from
           batch 003833344_003833856 onward. Fastest to a completed layer.
restart    clear case_results/compressed_0.5s batch output and rerun with the
           frozen 20,000-node configuration. Costs the ~3.5 h batch replay
           again, but yields one uniform configuration for the layer.
```

No certificates are at risk either way; this is a provenance question, not a
correctness one.
