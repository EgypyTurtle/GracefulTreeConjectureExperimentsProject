# Erdos-Gyarfas search v2

This is a standalone improvement of the public search at
<https://github.com/rbsandeep/Erdos-Gyarfas>, associated with
<https://arxiv.org/abs/2410.22842>. The original serial files and their MIT
license are included under `reference/`. They are compiled with explicit
source lists so the two executables cannot accidentally share a `main`.

The target is a finite simple graph of minimum degree at least 3 without any
simple cycle of length 4, 8, 16, 32, etc. For a fixed k, this search follows the
paper's pending-newest-vertex extension rule. A single k run is one part of
the paper's verification: the P_t-free statement needs all runs 3 <= k <= t.
No general termination or time bound is asserted for k >= 14.

## Artifact-checked k=14 completion (provisional)

Original server records corroborate a complete k=14 run: 18,060/18,060 tasks,
1,435,716,298 search states, final-process elapsed time 58,270.2 s,
peak RSS 53,600 KiB and exit status 0, without a candidate counterexample.
This includes earlier checkpoint work; it is not total campaign wall time.
The 24,374-file server archive and all member checksums were checked locally.
Independent Python replay reproduced the entire initial frontier (16,695
tasks), and the refinement of 10,426 unfinished parents into 18,060 tasks.
All completed-task records, carried statistics and final summary agree.
This is an internal artifact audit, not independent external review or a
full replay of the 1.4 billion states. This is not a claim to resolve
the unrestricted conjecture or an enumeration of all graphs of order <=72.

See [the result note](publication/RESULT_NOTE.md),
[the reported data](results/k14_reported.json) and
[release draft](publication/RELEASE_NOTES.md).

The fixed raw archive is under `data/k14/` in the public repository; no
24,000-file unpacked checkpoint tree is committed. See
[the verification account](publication/VERIFICATION.md) for commands, hashes
and the exact limits of the checks. Search and refinement sources are
byte-identical to the collected server sources.

## Next experiment: k=15 on CPU0

On the existing server project (not the parent original checkout):

```bash
cd /home/dell/math-search/Erdos-Gyarfas/erdos-gyarfas-v2
bash run_cpu0.sh 15
tmux attach -t eg-k15-cpu0
```

The launcher must first be transferred to that directory. From the local
PowerShell project folder: `./tools/Start-K15.ps1 -Server YOUR_SERVER`.
It uploads only the launcher; it does not change the existing search binary.
The launcher validates that logical CPUs 0..15 all belong to socket 0, uses
16 threads with inherited affinity, logs source/binary hashes and the CPU
mask, and starts/resumes `checkpoints/k15-d5-cpu0` (depth 5, cap 200,000).
It has no time limit and never starts k=16 automatically.

No k=15 completion time or termination is promised. The k=14/k=13 state-count
ratio was about 399, but is not a valid prediction of k=15 runtime. Observe
the first day and review any long-running tail before deciding on deeper
refinement. Never treat the percentage of prefix tasks as elapsed-work
percentage. Repeatedly stopping a single huge task discards its unfinished
internal DFS work. Keep k=14 evidence immutable.

## Improvements

* Bit masks iterate actual neighbors and reject induced-path chords with bit
  operations. Graphs above 64 vertices use a multiple-word fallback.
* Mutation/rollback replaces a whole-graph copy per neighbor subset.
* Residual reachability and component-size bounds reject exact-length paths
  that cannot reach the target or cannot use enough remaining vertices.
  An induced-path extension also stops if too few eligible vertices remain.
* A forbidden cycle through the newest vertex x uses exactly two neighbors
  u,v of x. Deleting x leaves a simple u-v path in the fixed old core of length
  2^j-2. These pair conflicts are cached for the lifetime of this extension.
  Neighbor subsets are independent sets of that conflict graph: a conflicting
  pair eliminates every superset containing it, without a full cycle scan.
* For 32-or-longer cycles on graphs of at most 64 vertices, exact paths use
  meet-in-the-middle: two simple half-paths must meet at one vertex with no
  other common vertices. At most 131,072 left half-paths are stored per check;
  an overflow falls back to exact DFS. Larger graphs retain exact DFS.
* `--split-depth` really splits that many extension layers. Whole frontier
  tasks go to a shared queue. The task limit retains a shallower whole layer
  rather than dropping any branches; by default at most 20,000 tasks are kept.
* Completed tasks are synced, then atomically published. A restart reuses the
  saved frontier and done records. OS file locking prevents simultaneous use
  of one checkpoint directory and releases automatically after a crash.
* A flushed progress line is printed every 10 seconds during worker search.
  SIGINT/SIGTERM/time limits yield `incomplete`, never `complete`.

This version does not enable the old `guided` score: reordering all branches
did not help exhaustive no-counterexample runs. Degree-3 ratios are not used
as unsafe filters on partial graphs. The pair-conflict pruning above follows
directly from the cycle structure, independently of recent preprint claims.

## Server build and verification

Use a new folder next to your existing checkout; existing logs need not be moved.
The archive contains this folder, without binaries or old run data.

```bash
cd ~/math-search
unzip erdos-gyarfas-v2.zip
cd erdos-gyarfas-v2
make -j4
make test
```

Dependencies: g++ with C++17 support (GCC 9.4 works with these language/API
features), POSIX threads, make and Python 3.8+. No external Python packages.
The packaged code is compiled/tested on Windows with MinGW; Linux-specific
flock/fsync and the shell launcher should also be checked with `make test` on
your server before a large run.

The tests compare induced paths and pair conflicts against independent
set-adjacency checks; compare accepted-state counts and 64-bit unordered graph
fingerprints with the original algorithm for k=3..10 and k=11 on restart;
vary threads, split depth and task caps; and kill/restart a real process.
Fingerprint agreement is regression evidence, not a formal proof or a
collision-free comparison of every graph.

## Run and resume

After `make test`, first benchmark k=11 and k=12:

```bash
python3 tools/benchmark.py --k 11 12 --threads 1 8 32 --report logs_benchmark.json
```

The reference k=12 may take about 21 minutes on the server, as previously
measured. The benchmark always uses fresh checkpoints, so it measures real
work rather than returning an already completed result.

Run k=13 once with the new version to compare against the completed reference
run (12h 53m 23.63s on the user's server):

```bash
tmux new -s eg-v2
bash run.sh 13 32 3
```

Detach: Ctrl+B, then D. Reattach: `tmux attach -t eg-v2`.
The same command after a reboot automatically resumes:

```bash
cd ~/math-search/erdos-gyarfas-v2
bash run.sh 13 32 3
```

Only completed tasks are reused. Work within an unfinished task is repeated.
Frontier generation is not checkpointed midway; it is redone if interrupted.
Local disk is recommended for the checkpoint directory. Logs contain each
run's elapsed time; resumed summary counts include earlier completed tasks,
but `seconds_this_run` covers only the current process.

After k=13 succeeds and its timings/resources are inspected, a bounded k=14
pilot can be started without claiming completion if it stops early:

```bash
./out/eg_search --k 14 --threads 32 --split-depth 3 \
  --checkpoint checkpoints/k14-d3 --time-limit 3600 --progress 10
```

Repeat the same command to give pending tasks another hour, or omit
`--time-limit` to continue. There is no guarantee that k=14 terminates.
For a task that remains too large, splitting more deeply requires a new
checkpoint directory; old depth-3 task IDs cannot be reused as depth-4 IDs.

## CLI and exit status

### Refine an existing partial checkpoint

`eg_refine` expands one extension layer of unfinished tasks into a new
checkpoint. Completed tasks are not re-searched: their statistics and audit
fingerprints are carried into the new manifest. The source checkpoint remains
available. The new directory starts with different task units and `reused=0`;
the preserved old work is recorded in `refinement.txt` and the initial totals.

```bash
make out/eg_refine
./out/eg_refine --from checkpoints/k14-d4 \
  --to checkpoints/k14-d5-refined --task-limit 200000
bash run_checkpoint.sh checkpoints/k14-d5-refined 8
```

The launcher reads k, depth, task limit and audit mode from the saved manifest.
Its optional third argument is a time limit in seconds; the default is 0
(unlimited). Prefer a long continuous run when a task exceeds an hour: every
time-limit stop discards the unfinished task's internal DFS work.

Refinement reserves one slot for every remaining parent, so a capped split
keeps those parents rather than losing their branches. `expanded` and
`retained` report the outcome. Repeating refinement into another new directory
is supported. A stopped/failed refinement does not publish a runnable manifest;
retry with a fresh destination. A source lock prevents refinement during a run.
It does not recover internal DFS work from a previously interrupted task.

The tool verifies the frontier conservation equation
`accepted + 1 - states = pending task count` before and after refinement.
Tests cover partial/completed checkpoints, repeated/capped splitting, original
checkpoint preservation, and reference graph-fingerprint agreement.

### Search options

```text
--k K                required, at least 3
--threads T          default 8; server launcher default 32
--split-depth D      default 3; 0 gives one serial-search task
--task-limit N       default 20000, frontier cap
--checkpoint DIR     task manifest + done records + summaries
--progress SECONDS   default 10
--time-limit SECONDS optional, no limit by default
--audit              expensive accepted-graph fingerprint for validation
```

Exit 0 = all saved tasks exhausted with no candidate; 100 = candidate saved;
130 = interrupted; 3 = incomplete because of time limit; 2 = error. Shell
pipelines must use `set -o pipefail`, as `run.sh` does, so tee cannot hide a
failed/interrupted search. A limit is checked between search operations and
periodically inside path DFS; startup frontier generation can exceed it.

Candidate verification (not required for ordinary empty searches):

```bash
python3 tools/verify_candidate.py checkpoints/k14-d3/candidate.txt --pk 14
```

Inspecting startup files is not enough to claim exhaustive verification. Use
the final `complete:` line / `summary.txt`, exit status and the validation
results together. Stop/error runs preserve completed tasks without claiming a
negative result. No speedup is guaranteed from core count alone.
