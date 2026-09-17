# Edge64 Full Production Stall — Incident Record

Date: 2026-09-16

## Summary

The first full edge64 production attempt stopped making progress on
2026-09-14 at 23:45 and was discovered on 2026-09-16 as a Python process that
had burned roughly one full CPU core for about 15.6 hours while writing **zero
bytes**. The run is resumable from its own batch checkpoints; no certificate
data was lost.

## Observed state at discovery

```text
stage                     compressed_0.5s  (1 of 9)
processed                 3,800,064 / 10,040,677  (37.8%)
solved                    3,734,655   (98.28%)
survivors                    65,409
errors                    0
nodes                     3,890,199,289
throughput                27,823 nodes/s over 139,818 s
verified checkpoints      37, all PASS (bad = 0)
pending survivors file    18,744,138 bytes
```

### Correction to the first report of this incident

The figures above come from the authoritative per-checkpoint CSV,
`checkpoint_progress.csv`, and were re-derived independently by counting the
`solved` column of all 7,471 stored batch files: 3,759,475 solved out of
3,825,152 cases, a 98.28% solve rate, consistent with the CSV.

The first report of this incident instead quoted `solved = 1,291,124` and
`survivors = 2,508,940`, read from `stage_progress/compressed_0.5s.json`
without cross-checking. That JSON is a *stale* artifact: the production run had
been resumed from these same batch files under an earlier, differently
configured attempt, and the stage-progress file carried that attempt's counters
forward. `checkpoint_progress.csv` appends one row per checkpoint instead of
overwriting, so it retained the true progression and supersedes the JSON. Both
figures are corrected here and in every document that quoted them.

This is not only bookkeeping. The stale survivor count implied that each later
cascade stage would reprocess millions of cases, which inflated the projected
storage and runtime for the remaining run by more than an order of magnitude.
The real survivor rate after stage 1 is about 1.7%, not 66%.

The stalled process:

```text
PID 20028, python.exe 3.14.2
started        2026-09-15 23:07:17
CPU consumed   55,414 s against 56,105 s elapsed  (~98.7% of one core)
working set    23 MB
```

## Evidence that this was a wedge, not slow progress

Three independent counters were sampled over 45 seconds:

```text
metric                                  change
batch result files (7,483)                   0
pending survivors temp file (403,087,546 B)   0
sqlite cache WAL (5,108,832 B)                0
```

Disk timestamps confirm the last write of any kind was 2026-09-14 23:45:12,
about 39 hours before discovery.

## Where it stopped

`case_results/compressed_0.5s/` holds **7,471 contiguous** batch files with no
gaps, from `batch_000000000_000000512.csv` through
`batch_003824640_003825152.csv`. The survivor count in the pending file
(2,508,940) reproduces exactly at the last checkpoint, so the stall occurred
while recomputing the **next** batch, `batch_003825152_003825664.csv`, which was
never written.

## Ruled out

Each suspect was tested rather than assumed:

```text
suspect                         test                            result
hard/pathological case          replay all 512 cases of the     all solved,
                                unwritten batch                 max 0.045 s
corrupt certificate cache       open the 398 MB worker cache    quick_check ok,
                                read-only                      1,164,800 rows
hanging verifier                run edge64_full_production_     PASS in 3.6 s
                                verify.py on checkpoint 37      (99,204 certs)
solver time-limit regression    budget 0.5 s honoured           no overrun
```

The unwritten batch replays in under 50 ms per case, so the stall is not a
property of those inputs.

## Contributing defects found in the runner

Reviewing `src/edge64_full_production.py` while the evidence above was being
collected surfaced four defects, all independent of the exact wedge trigger:

1. `verify_checkpoint()` called `subprocess.run(...)` with **no timeout**. The
   parent blocks on that child, so one stuck verifier silently stalls the whole
   production run with no output. This is the highest-severity defect.
2. `ProcessPoolExecutor(...)` was constructed **outside** the `try/finally` that
   owns it, so a failure there skipped pool teardown entirely.
3. The pool was driven with `chunksize=1` over 512-case batches — 19,610
   round trips per stage — so per-task IPC cost dominated the common case, in
   which most cases solve in milliseconds.
4. The `solved` flag was compared against the literal `"1"` while freshly
   computed rows carry it as an `int`, so the pending-survivor filter admitted
   every case, the solved counter stayed at 0, and the per-checkpoint
   certificate gate never fired. Found later, during sharded-run validation; see
   [edge64_stage1_sharding.md](edge64_stage1_sharding.md). This is a plausible
   but unproven contributor to the wedge itself: a pending file far larger than
   the true survivor count is a plausible way to run the process into trouble.

## Reproduction constraint

`ProcessPoolExecutor` cannot start in the restricted execution environment used
for this investigation: `multiprocessing.Pipe` fails with
`PermissionError: [WinError 5]` from `_winapi.CreateFile` on the wakeup pipe.
That is an environment limitation, not a repository bug, but it means the
pool path cannot be exercised there at all — which is why the sequential mode
below matters for resumability.

## Repairs applied

```text
defect                          repair
unbounded verifier wait         bounded subprocess timeout,
                                max(600 s, 1 ms per certificate); a timeout is
                                recorded as FAIL and raises, it is not ignored
pool outside try/finally        pool created on one line, shutdown guarded by
                                `if pool is not None` inside the finally block
per-task IPC overhead           new --chunk-size (cases per pool round trip)
restricted-environment resume   new --workers 0 (or any value < 1) runs the
                                stage in-process with no multiprocessing
silent stalls                   new --log-file appends one heartbeat line per
                                batch, so progress is visible without waiting
                                for a 100,000-case checkpoint
solved-flag type mismatch       one is_solved() helper used by the survivor
                                filter, the solved counter, and the checkpoint
                                certificate gate
single-core ceiling             new --shard-index/--shard-count split a stage
                                across independent processes with no shared
                                state and no IPC, plus --merge-shards to
                                restore manifest order for the next stage
```

`src/diag_stuck_batch.py` is retained as the replay harness used to test the
unwritten batch.

## Status after the incident

```text
edge64 compressed_0.5s      37.8% complete, resumable, 7,471 batches intact
edge64 later stages         not started
edge63 C8 line              frozen, unaffected
final_status.json           not written (run never completed)
```

The previous attempt's `pending/after_compressed_0.5s.csv.tmp` is rebuilt from
the batch files on the next resume, so its loss is recoverable by construction.

## Storage finding: one malformed cache

A corruption sweep of all 102 SQLite databases under `results/` found exactly
one bad file:

```text
production_extension_compressed_32888.sqlite3   191 MB   MALFORMED
```

`PRAGMA quick_check` fails on the **main database**, not merely on its WAL, so
the file was already damaged before the process was stopped. The file is a
per-PID, disposable certificate cache — a cache miss only costs recomputation,
and no future worker reuses it — so it is not a correctness threat and has been
removed. Every other database reports `ok`.

The volume is a plausible contributing factor and is worth treating as the
leading hypothesis for the original wedge:

```text
D:\   652.9 GB total, 70.0 GB free (10.7%)  [after removing the bad cache]
results/  82.76 GB
```

A `disk full` error during a WAL append or an atomic batch write would abort the
run without necessarily printing anything, which matches the observed profile
(no writes for 39 hours, no `final_status.json`, no stdout). The exact trigger
was not reproduced, so this remains a hypothesis rather than an established
cause.

## Disk budget for the remaining run

Measured from the first stage at 3,800,064 processed cases:

```text
component                                  size      per case
batch result csv  (7,471 files)          1.164 GB    0.116 kB
verification checkpoints (37 files)      0.766 GB    0.079 kB per solved
                                          (99,204 certs each, ~2% coverage)
sqlite certificate caches (per worker)   0.97 GB     0.106 kB
```

Only the first two scale with stage input. The sqlite caches are per-worker
files that a sequential resume does not create at all, so a stage costs roughly
`input_cases * 0.20 kB`. Scaling the first stage to the full universe gives
about 2.0 GB.

Each later stage takes as input only the previous stage's survivors. With the
corrected 1.71% survivor rate after stage 1, and the per-budget survival rates
measured by the 200,000-case pilot (0.5 s → 32.9%, 1 s → 23.7%, 2 s → 13.0%,
5 s → 7.7%), the cascade shrinks very quickly:

```text
stage                  input cases    projected
compressed_0.5s         10,040,677       2.0 GB
compressed_1s              171,600       0.03 GB
compressed_2s               56,500       0.01 GB
compressed_5s                7,300       0.01 GB
diff_1s                      1,700       0.01 GB
tension_1s                     500       0.01 GB
hybrid_1s                      100       0.01 GB
branch_1s                       30       0.01 GB
compressed_30s_fallback         10       0.01 GB
                        ------------------------
                        total            ~2.1 GB
```

An earlier revision of this section projected ~7.5 GB and stages of millions of
cases each, because it was driven by the stale survivor count. That was wrong by
roughly a factor of 40; the corrected figure is about **2.1 GB for the entire
remaining cascade**.

Projection, not a measurement: stages 2--9 are extrapolated and will differ. The
pending survivor file grows to roughly 19 MB per 3.8 M cases of stage input.

Against ~70 GB free this is comfortable. The malformed cache recorded above
still shows the volume can produce write damage, so keeping headroom is
worthwhile, but space is no longer a constraint on finishing this layer.

## Recommended resume command

Sequential mode avoids the multiprocessing transport entirely and, with the
measured 0.5 s budget, costs roughly one core:

```powershell
python src/edge64_full_production.py `
  --workers 0 `
  --batch-size 512 `
  --log-file results/edge64_full_production_v1/production_heartbeat.log
```

Watch the heartbeat file rather than the process. A resume prints one line per
batch; if its mtime stops advancing while the process is alive, the run is
wedged and should be stopped and reported instead of left running.

The pool path remains available (`--workers 2 --chunk-size 16`) for machines
where `ProcessPoolExecutor` is usable and two cores are wanted.
