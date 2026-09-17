# Compressed Solver: Per-Case Throughput Optimization

Date: 2026-09-17

## What actually limits the stage

Stage 1 of the edge 64 cascade runs the compressed method over 10,040,677 cases,
so its cost is dominated by **per-case work**, not by a few pathological
searches. Measurement corrected an early wrong assumption here:

- A 600-case sample of the stall region contained only **one** case that
  exhausted the 0.5 s budget. The tail is rare.
- The base difference search runs at roughly 32,000 nodes/s, about 31 us per
  node. Node count per case is small for the overwhelming majority.

So the wins come from removing per-case overhead and from making the existing
node expansion cheaper. Nothing here changes which cases are solvable.

## Adopted: the persistent certificate cache was pure cost

`open_pendant_extension_cache()` runs once per case and starts with
`Path(path).resolve()`, which measured **232 us per call** on this machine.
Function-level profiling of 2,999 cases put `nt._getfinalpathname` at
**0.725 s of 3.76 s total -- 19% of all runtime** -- making it the single most
expensive thing in the profile.

What it bought was nothing. A 400-case cold run of the compressed stage recorded
**zero cache hits**: every solve came from the strategy itself, never from the
cache. The stored certificates are keyed by reduced rooted skeleton, and although
skeletons do recur, the extremal-extension rebuild does not accept the cached
base for the later trees, so the lookup misses and the search runs anyway.

The costs were real and compounding: a SQLite round trip per case, cache files
that grew past 1 GB, and that path resolution. The disk cache is now opt-in
(`extension_persistent_cache`, default `False`); the in-memory cache, which is a
plain dict lookup with no such overhead, stays on.

## Adopted: feasibility asked the expensive question

`feasible_remaining(next_d)` asks only whether *any* legal move exists. It
answered by calling `candidate_moves`, which enumerates every legal move,
computes placement/partness/extremeness scores for each, and sorts the list. It
is called once per explored move, so on hard cases the same full enumeration was
rebuilt for every sibling.

It now shares one scan with the branching path and stops at the first legal move
when only existence is needed. The answer is unchanged -- "some move exists" is
the same predicate either way -- so the explored tree is identical; only the cost
of asking changes.

## Measured effect

Same cases, same node counts, all certificates verified, each variant in its own
process (the in-memory cache is module state, and letting it survive between
variants silently makes the second variant look orders of magnitude faster).

Isolating the two changes, 400 cases at manifest offset 3,825,152:

```text
variant                     solved     wall     mean      p95    nodes/s
baseline (production)       400/400   14.31s   35.8ms  125ms     30,411
+ early-exit feasibility    400/400    9.88s   24.7ms   83ms     44,035
+ persistent cache off      400/400    8.40s   21.0ms   74ms     51,818
```

Nodes were identical at 435,209 in all three, confirming the search behaviour did
not change. Attribution: **1.45x** from the feasibility fix, a further **1.18x**
from dropping the dead cache, **1.70x** together.

Held-out region (offset 1,500,000, production `run_one` path, 500 cases):

```text
                 wall     mean     p95     nodes      solved
baseline       14.17s   28.3ms  100.7ms  399,445    500/500
optimized      10.76s   21.5ms   78.6ms  399,445    500/500
```

Representative whole-universe sample, every 8,367th case (1,200 cases spanning
all 10M, `run_one` path):

```text
              solved  survivors     wall     mean      p50      p95
baseline     1196/1200     4       44.38s   37.0ms   16.1ms   143.9ms
optimized    1197/1200     3       33.78s   28.2ms   11.8ms   107.0ms
```

**1.31x faster, ~25% lower latency, and one case more solved** -- the extra solve
is a timing boundary effect, since a case that finishes sooner is less likely to
be cut off by the deadline. Total nodes moved by +0.9%, within noise.

## Investigated and rejected: move ordering

Move ordering is the textbook lever on node count, and a first test looked
spectacular. On 300 cases at offset 3,825,152, restricting to the branch search
with a fixed 20,000-node budget:

```text
ordering        solved   total nodes   nodes/solved
default         248/300    1,162,192       4,686
placement       257/300    1,426,266       5,550
branch_first    295/300      679,493       2,303
edge_index      256/300    1,374,834       5,370
extremeness     121/300    3,075,504      25,417
```

`branch_first` looked like a 1.7x win. It is not, and the reason is worth
recording: the manifest is ordered by structure, so a single contiguous sample
is not representative. Testing the same comparison on another region reversed the
ranking (`placement` won there), and the decisive test -- a uniform stride across
the whole universe -- showed **no ordering beats the historical default**:

```text
whole-universe stride sample, compressed path, 1200 cases
default        solved=1199/1200  nodes=1,226,958  wall=33.44s
branch_first   solved=1198/1200  nodes=1,250,369  wall=34.87s
```

The ordering is now selectable (`move_order` on the branch search,
`extension_move_order` / `branch_move_order` in options) because the local
variation is real and may matter for targeted reruns, but **the default is
unchanged**. Selecting an ordering from a single region's measurement would have
made the production run slower.

## Open issue: a MemoryError under the `placement` ordering

While sweeping orderings across regions, `placement` raised `MemoryError` inside
`candidate_moves` on one case, after an unknown number of nodes. It did not
reproduce in the regions that were re-run, and the exact case was not captured.

The search's `max_nodes` budget caps *explored* nodes, but a single expansion
still materialises the full candidate list for one difference, so a node whose
candidate list is pathologically large can allocate far more than the node budget
suggests. This is a robustness gap in the guard, not a correctness bug.

It does not affect the adopted changes, since `default` ordering is what
production runs. `placement` should not be selected for a production run until
this is reproduced and bounded.

## Reproduce

```powershell
# isolate the two adopted changes
python src/diag_ab_run.py --solver-root ..\_baseline_wt --label base_cache --start 3825152 --count 400 --out results/_diag/a.json
python src/diag_ab_run.py --solver-root ..\_baseline_wt --label base_nocache --disable-persistent-cache --start 3825152 --count 400 --out results/_diag/b.json
python src/diag_ab_run.py --solver-root . --label optimized --disable-persistent-cache --start 3825152 --count 400 --out results/_diag/c.json

# ordering sweep across disjoint regions
python src/diag_move_order_multi.py --regions 10 --per-region 120 --nodes 20000

# one ordering per process, compressed path
python src/diag_compressed_order.py --order default      --start 0 --count 1200 --stride 8367 --out results/_diag/u_default.json
python src/diag_compressed_order.py --order branch_first --start 0 --count 1200 --stride 8367 --out results/_diag/u_bf.json
```

`..\_baseline_wt` is a git worktree pinned at the pre-optimization revision.
