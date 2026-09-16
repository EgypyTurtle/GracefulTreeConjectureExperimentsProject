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
solved                    1,291,124
survivors                 2,508,940
errors                    0
nodes                     3,890,199,289
throughput                27,823 nodes/s over 139,818 s
verified checkpoints      37, all PASS (bad = 0)
pending survivors file     403,087,546 bytes, 2,508,940 rows
```

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
collected surfaced three defects, all independent of the exact wedge trigger:

1. `verify_checkpoint()` called `subprocess.run(...)` with **no timeout**. The
   parent blocks on that child, so one stuck verifier silently stalls the whole
   production run with no output. This is the highest-severity defect.
2. `ProcessPoolExecutor(...)` was constructed **outside** the `try/finally` that
   owns it, so a failure there skipped pool teardown entirely.
3. The pool was driven with `chunksize=1` over 512-case batches — 19,610
   round trips per stage — so per-task IPC cost dominated the common case, in
   which most cases solve in milliseconds.

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
