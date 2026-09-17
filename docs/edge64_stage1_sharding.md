# Edge64 Stage-1 Sharding and the `solved` Flag Defect

Date: 2026-09-17

## Why sharding

Stage 1 of the edge 64 cascade is a full pass over 10,040,677 cases, and it is
by far the dominant cost of the layer. The later eight stages together are
projected at roughly 100,000 case attempts, because only about 1.7% of cases
survive each budget tier.

The machine has 16 logical processors, but the runner could use exactly one of
them. `ProcessPoolExecutor` is unusable in the restricted execution environment
used here: `multiprocessing.Pipe` fails with `PermissionError: [WinError 5]`
from `_winapi.CreateFile` when it tries to create the executor's wakeup pipe.
`--workers 0` therefore ran the whole stage single-process, which projects to
about five days for stage 1.

Sharding sidesteps the transport entirely. `--shard-index i --shard-count n`
makes a process handle only input positions `p` with `p % n == i`. Independent
shards share no mutable state and need no communication: each has its own
worker pool, its own per-PID certificate cache, its own heartbeat, its own
checkpoint journal, and its own batch files. Batch boundary indices stay in
whole-manifest coordinates, so the union of the shard outputs is identical to an
unsharded result set.

Measured on a uniform sample, one shard sustains about 17 cases/s. Twelve shards
project to roughly 14--20 hours for stage 1 instead of ~5 days.

Stride sharding is used rather than contiguous blocks because the manifest is
ordered by structure and difficulty varies strongly along it; striding spreads
every shard across the whole difficulty range, which balances load. The cost is
weaker disk locality, which measured as acceptable.

### Merge step

Shards write their survivor files in their own order, so concatenating them
would reorder the next stage's input. `--merge-shards N` re-streams the stage
input and re-emits only surviving rows in manifest order, and it fails loudly if
the shard files do not sum to the same number of survivors. This is required
before the conductor can advance to stage 2.

## The `solved` flag defect

Result rows reach the runner in two shapes. A freshly computed row carries
`solved` as an `int`; a row read back from a batch CSV carries it as a `str`.
Three call sites compared the value against the literal `"1"`:

```text
site                                   consequence when the value was int 1
pending-survivor filter                every case written as a survivor
total_solved accumulation              counter pinned at 0
verify_checkpoint certificate filter   checkpoint pre-verification skipped
```

The comparison is a tagged-union mistake, not a subtle one, and it was present
in the original commit for this runner. It was found while validating the
sharded path: a shard reported `solved=0` for a batch whose stored result file
contained 512 rows with `solved=1`.

All three sites now go through one `is_solved()` helper, which accepts `int`,
`str`, and `bool` forms.

### What it did and did not cause

It is worth being precise, because it is tempting to over-claim.

- It is **known** to have broken the pending-survivor filter and the solved
  counter on any freshly computed batch, and to have disabled the per-checkpoint
  certificate gate.
- Certificate validity was never at risk. The gate it skipped was a
  pre-verification convenience; the stored certificates were independently
  verified at the end of the run and passed, and re-verifying checkpoint 37
  under the current verifier still reports `bad = 0` on 99,204 certificates.
- It is **plausibly** related to the 2026-09-14 stall, but not established. The
  one direct measurement of the pre-stall pending file recorded 403,087,546
  bytes, which is consistent with roughly 2.5 M rows and therefore with the
  filter failing, and a pending file far larger than the true survivor count is
  a plausible way to run a long-lived process into trouble. A later resume left
  a pending file of 18,744,138 bytes at the same checkpoint, which is consistent
  with the filter working. The two observations disagree, the wedge itself was
  never reproduced, and the honest status is "contributing factor, unproven".

## Startup races under sharded launch

Two defects only appear when N processes start together, and both cost shards
before they were fixed:

1. Every process wrote the same `production_1056_manifest.json` through a shared
   `.tmp` path, so one shard saw `PermissionError` writing it and another saw
   `WinError 32` renaming it. The write is informational and is now non-fatal.
2. Every process independently re-derived the manifest digests, which means
   streaming a 1.6 GB CSV twice per shard. `build_immutable_manifest()` now
   returns the recorded metadata when the frozen manifest and its meta file are
   already present.

## Operational notes

A sharded run needs a single supervisor. The working procedure is:

```powershell
foreach ($i in 0..11) {
  Start-Process python -NoNewWindow -ArgumentList `
    'src/edge64_full_production.py','--workers','0','--batch-size','512',`
    '--shard-index',"$i",'--shard-count','12',`
    '--log-file',"results/edge64_full_production_v1/heartbeat.shard$('{0:D2}' -f $i).log"
}
```

Monitor with `python src/diag_shard_status.py`, which reads the per-shard
heartbeats and reports per-shard and aggregate progress plus a staleness
warning. A shard whose heartbeat stops advancing while its process is alive is
wedged, not slow.

Resource cost per shard is small: about 34 MB resident and one core. Twelve
shards together measured ~563 MB and ~73% of total CPU on the 16-core machine;
memory was never the constraint.

## Status

The sharded stage-1 run was paused on 2026-09-17 at 65,536 / 10,040,677 cases
(0.65%), solve rate 99.84%, with 128 batch files on disk. All shard processes
were stopped on request, not by a fault. Batch files are written atomically, so
none is partial, and a restart resumes from them without redoing work.

Stage 1 still needs roughly 20--40 hours of wall time with 12 shards, and it will
be slower per case in the hard tail than the 0.65% sampled so far suggests.
