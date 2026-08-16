# Runbook

These commands assume PowerShell on Windows and are run from the repository
root.

## Setup

```powershell
cd path\to\GracefulTree

New-Item -ItemType Directory -Force -Path ".\results" | Out-Null
```

Use any local Python 3.10+:

```powershell
$PY = "python"
```

If you are using a managed environment with a bundled Python, set `$PY` to that
interpreter path locally. Do not commit machine-specific absolute paths.

```powershell
$PY = "path\to\python.exe"
```

## Smoke Test

```powershell
& $PY ".\src\graceful_tree.py" --five-leaf-nonspider-sweep 2 --method branch --time-limit 10 --log ".\results\five_leaf_nonspider_max2_branch.csv" --save-hardest ".\results\hardest_max2.txt" --save-failed ".\results\failed_max2.txt" --progress 10
```

Expected:

```text
checked=66, solved=66, timeouts=0
```

## Non-Spider 5-Leaf Runs

```powershell
& $PY ".\src\graceful_tree.py" --five-leaf-nonspider-sweep 6 --method branch --time-limit 10 --log ".\results\five_leaf_nonspider_max6_branch.csv" --save-hardest ".\results\hardest_five_leaf_nonspider_max6_branch.txt" --save-failed ".\results\failed_five_leaf_nonspider_max6_branch.txt" --progress 1000
```

```powershell
& $PY ".\src\graceful_tree.py" --five-leaf-nonspider-sweep 7 --method branch --time-limit 10 --log ".\results\five_leaf_nonspider_max7_branch.csv" --save-hardest ".\results\hardest_five_leaf_nonspider_max7_branch.txt" --save-failed ".\results\failed_five_leaf_nonspider_max7_branch.txt" --progress 5000
```

## Non-Spider 5-Leaf Runs by Edge Count

```powershell
& $PY ".\src\graceful_tree.py" --five-leaf-nonspider-by-edges 30 --method branch --time-limit 10 --log ".\results\five_leaf_nonspider_edges30_branch.csv" --save-hardest ".\results\hardest_five_leaf_nonspider_edges30_branch.txt" --save-failed ".\results\failed_five_leaf_nonspider_edges30_branch.txt" --progress 5000
```

Current larger graceful run:

```powershell
& $PY ".\src\graceful_tree.py" `
  --five-leaf-nonspider-by-edges 45 `
  --method branch `
  --time-limit 20 `
  --total-time-limit 604800 `
  --log ".\results\five_leaf_nonspider_edges45_branch.csv" `
  --save-hardest ".\results\hardest_five_leaf_nonspider_edges45_branch.txt" `
  --save-failed ".\results\failed_five_leaf_nonspider_edges45_branch.txt" `
  --progress 20000
```

For a new interval, prefer the constructive compression method. It first uses
proved caterpillar and pendant-extension reductions, reuses rooted base
certificates, and falls back to `branch` when no reduction certificate is found:

```powershell
& $PY ".\src\graceful_tree.py" `
  --five-leaf-nonspider-by-edges 50 `
  --min-edges 48 `
  --method compressed `
  --extension-fastpath-nodes 2000 `
  --extension-cache-size 100000 `
  --extension-cache-db ".\results\pendant_extension_cache.sqlite3" `
  --time-limit 300 `
  --total-time-limit 604800 `
  --log ".\results\five_leaf_nonspider_edges48_50_compressed.csv" `
  --save-hardest ".\results\hardest_five_leaf_nonspider_edges48_50_compressed.txt" `
  --save-failed ".\results\failed_five_leaf_nonspider_edges48_50_compressed.txt" `
  --progress 20000
```

## Generic Pendant-Path Reduction

The same reduction can be used on generic generated trees. This is useful for
lobsters, random trees, and other families whose members often contain long
terminal paths. The extra flag tests all eligible terminal paths instead of
only the historical longest-path candidate; the node and time budgets are
shared across those attempts:

```powershell
& $PY ".\src\graceful_tree.py" `
  --lobster-batch 10000 `
  --base-vertices 12 `
  --method compressed `
  --extension-try-all-paths `
  --extension-fastpath-nodes 2000 `
  --extension-cache-size 100000 `
  --extension-cache-db ".\results\pendant_extension_cache.sqlite3" `
  --time-limit 30 `
  --total-time-limit 604800 `
  --log ".\results\lobster_compressed.csv" `
  --save-hardest ".\results\hardest_lobster_compressed.txt" `
  --save-failed ".\results\failed_lobster_compressed.txt" `
  --progress 100
```

The option is also available with `--random`, `--batch`, `--edges`, and
`--spider-sweep`. It is an opt-in generalization of the existing compressed
solver, not an exhaustive enumerator for every tree family. Successful
reductions are recorded in the usual `strategy`, `reduction_base`, and
`extended_edges` columns.

For a structural coverage report, use the streaming summary command. It
reports candidate trees with eligible pendant paths separately from trees
whose logs contain verified extension certificates:

```powershell
& $PY ".\src\graceful_tree.py" `
  --summarize-reduction `
  ".\results\five_leaf_nonspider_edges48_50_compressed.csv" `
  --reduction-summary-output ".\results\reduction_48_50.csv"
```

Multiple disjoint logs can be listed. The summary does not rerun search, and
overlapping logs should not be supplied because rows are counted as given.

## Hard-Pattern Budget Comparison

To test the suspected residue-class effect, run the fixed family with bridge 2,
short paths `(1,1)`, and sorted long paths `(a,b,c)` over 47--65 edges:

```powershell
& $PY ".\src\hard_pattern_experiment.py" `
  --min-edges 47 `
  --max-edges 65 `
  --time-limit 10 `
  --total-time-limit 604800 `
  --log ".\results\hard_pattern_47_65_comparison.csv" `
  --progress 50
```

There are 4,327 cases in this interval. Each row compares ordinary `branch`
search with reduction fast paths limited to 2,000 and 20,000 rooted-base
nodes. The experiment intentionally disables the persistent certificate cache
so that the two fast-path budgets are comparable. If interrupted, rerun the
same command with `--resume`; completed case names are skipped. To summarize
an existing log without searching again:

```powershell
& $PY ".\src\hard_pattern_experiment.py" `
  --summary-only `
  --log ".\results\hard_pattern_47_65_comparison.csv"
```

The six boundary cases left by the 20,000-node comparison can be tested
without rerunning the full 4,327-case family:

```powershell
& $PY ".\src\hard_boundary_experiment.py" `
  --time-limit 60 `
  --total-time-limit 604800 `
  --low-nodes 20000 `
  --high-nodes 100000 `
  --log ".\results\hard_boundary_61_65.csv" `
  --progress 1
```

This compares ordinary branch search, one-path reduction at 20,000 and
100,000 nodes, and all-path reduction at 100,000 nodes. If interrupted, add
`--resume` to the same command. To summarize an existing targeted log without
searching again:

```powershell
& $PY ".\src\hard_boundary_experiment.py" `
  --summary-only `
  --log ".\results\hard_boundary_61_65.csv"
```

For the main solver, enable the adaptive budget during replay with:

```powershell
& $PY ".\src\graceful_tree.py" `
  --replay-unsolved ".\results\five_leaf_nonspider_edges51_55_compressed.csv" `
  --method compressed `
  --extension-adaptive-budget `
  --extension-adaptive-nodes 100000 `
  --extension-cache-db= `
  --time-limit 600 `
  --replay-log ".\results\five_leaf_nonspider_edges51_55_replay_adaptive100k.csv" `
  --progress 1
```

Rows solved by the larger budget are recorded with strategy
`pendant-extension-adaptive`; cases outside the structural signature retain
the historical budget and strategy.

The persistent cache is the SQLite file
`.\results\pendant_extension_cache.sqlite3`. It stores every successful
rooted base certificate found by `compressed`; `--extension-cache-size` only
limits the fast in-memory layer. The database is deliberately under
`results/`, which is ignored by Git because it can become large.

To recover certificates from older CSV logs after adding this feature, run
the importer once. It reconstructs the reduced rooted certificate from the
full labeling and checks its reduction hash before insertion:

```powershell
& $PY ".\src\graceful_tree.py" `
  --import-extension-cache `
    ".\results\five_leaf_nonspider_edges48_50_compressed.csv" `
    ".\results\five_leaf_nonspider_edges47_replay_compressed.csv" `
  --extension-cache-db ".\results\pendant_extension_cache.sqlite3"
```

The importer is safe to rerun: duplicate rooted certificates are ignored. It
also accepts older logs without strategy metadata. A row is inserted only when
its complete labeling can actually be reversed through the pendant-extension
lemma and the reduced tree passes verification.

Count a proposed interval before running it:

```powershell
& $PY ".\src\graceful_tree.py" `
  --count-five-leaf-nonspider-by-edges 47 `
  --min-edges 46
```

If the larger graceful run leaves timeout rows, replay them with:

```powershell
& $PY ".\src\graceful_tree.py" `
  --replay-unsolved ".\results\five_leaf_nonspider_edges45_branch.csv" `
  --method branch `
  --time-limit 300 `
  --replay-log ".\results\five_leaf_nonspider_edges45_replay300.csv" `
  --progress 10
```

If the larger graceful run is interrupted before the enumeration finishes,
resume by skipping solved rows from the partial log and writing a continuation
log. `--skip-solved-from` may be repeated when several checkpoint logs exist:

```powershell
& $PY ".\src\graceful_tree.py" `
  --five-leaf-nonspider-by-edges 47 `
  --min-edges 47 `
  --method compressed `
  --extension-fastpath-nodes 2000 `
  --extension-cache-size 100000 `
  --time-limit 300 `
  --total-time-limit 604800 `
  --skip-solved-from ".\results\five_leaf_nonspider_edges41_45_branch.csv" `
  --log ".\results\five_leaf_nonspider_edges47_continuation_compressed.csv" `
  --save-hardest ".\results\hardest_five_leaf_nonspider_edges47_continuation_compressed.txt" `
  --save-failed ".\results\failed_five_leaf_nonspider_edges47_continuation_compressed.txt" `
  --progress 20000
```

## Summarize Results

```powershell
& $PY ".\src\graceful_tree.py" --summarize-log ".\results\five_leaf_nonspider_max6_branch.csv"
```

## Verify Certificates

Solved CSV rows are certificates. Verify graceful rows with:

```powershell
& $PY ".\src\verify_certificates.py" `
  --kind graceful `
  --log ".\results\five_leaf_nonspider_edges40_branch.csv"
```

Verify antimagic rows with:

```powershell
& $PY ".\src\verify_certificates.py" `
  --kind antimagic `
  --log ".\results\antimagic_five_leaf_nonspider_edges45_fallback.csv"
```

## Replay Unsolved Cases

```powershell
& $PY ".\src\graceful_tree.py" --replay-unsolved ".\results\five_leaf_nonspider_max7_branch.csv" --method branch --time-limit 60 --replay-log ".\results\five_leaf_nonspider_max7_replay60.csv" --progress 50
```

## Antimagic Runs

```powershell
& $PY ".\src\antimagic_tree.py" --five-leaf-nonspider-by-edges 20 --time-limit 5 --log ".\results\antimagic_five_leaf_nonspider_edges20.csv" --progress 1000
```

```powershell
& $PY ".\src\antimagic_tree.py" --five-leaf-nonspider-by-edges 25 --time-limit 5 --log ".\results\antimagic_five_leaf_nonspider_edges25.csv" --progress 5000
```

Summarize:

```powershell
& $PY ".\src\antimagic_tree.py" --summarize-log ".\results\antimagic_five_leaf_nonspider_edges25.csv"
```

Run antimagic search with deterministic search first and randomized fallback
only for timeout cases:

```powershell
& $PY ".\src\antimagic_tree.py" `
  --five-leaf-nonspider-by-edges 45 `
  --time-limit 10 `
  --random-fallback-trials 6 `
  --random-fallback-time 60 `
  --random-seed 20260805 `
  --log ".\results\antimagic_five_leaf_nonspider_edges45_fallback.csv" `
  --progress 20000
```

The fallback budget is per case and is used only after the primary search
times out. The CSV includes `primary_nodes`, `fallback_nodes`,
`fallback_used`, and `random_trials_used` for post-run analysis.

Replay only the unresolved rows from an existing run:

```powershell
& $PY ".\src\antimagic_tree.py" `
  --replay-unsolved ".\results\antimagic_five_leaf_nonspider_edges40.csv" `
  --time-limit 10 `
  --random-fallback-trials 6 `
  --random-fallback-time 60 `
  --random-seed 20260805 `
  --log ".\results\antimagic_five_leaf_nonspider_edges40_fallback.csv" `
  --progress 1
```

Resume an interrupted antimagic run by skipping solved rows already present in
an earlier log and writing the remaining cases to a new continuation log:

```powershell
& $PY ".\src\antimagic_tree.py" `
  --five-leaf-nonspider-by-edges 50 `
  --time-limit 10 `
  --random-fallback-trials 6 `
  --random-fallback-time 60 `
  --random-seed 20260805 `
  --skip-solved-from ".\results\antimagic_five_leaf_nonspider_edges50_fallback.csv" `
  --log ".\results\antimagic_five_leaf_nonspider_edges50_continuation.csv" `
  --progress 20000
```

The continuation command should report a nonzero `skipped=...` count after the
first progress update.

## Next Graceful Interval: 56--57

The next incremental run contains 9,302,112 cases:

```powershell
& $PY ".\src\graceful_tree.py" `
  --five-leaf-nonspider-by-edges 57 `
  --min-edges 56 `
  --method compressed `
  --extension-adaptive-budget `
  --extension-adaptive-nodes 100000 `
  --extension-fastpath-nodes 2000 `
  --extension-cache-db ".\results\pendant_extension_cache.sqlite3" `
  --time-limit 300 `
  --total-time-limit 604800 `
  --log ".\results\five_leaf_nonspider_edges56_57_adaptive.csv" `
  --save-hardest ".\results\hardest_edges56_57_adaptive.txt" `
  --save-failed ".\results\failed_edges56_57_adaptive.txt" `
  --progress 20000
```

If the run is interrupted, retain the SQLite cache and use a continuation log
with `--skip-solved-from` rather than discarding the completed rows. Timeout
rows can then be replayed with the same adaptive options.

For the completed 56-57 run, the initial log contained 12 unsolved rows. The
following targeted replay solved them without rerunning the other 9.3 million
cases:

```powershell
& $PY ".\src\graceful_tree.py" `
  --replay-unsolved ".\results\five_leaf_nonspider_edges56_57_adaptive.csv" `
  --method compressed `
  --extension-fastpath-nodes 100000 `
  --extension-try-all-paths `
  --extension-cache-db ".\results\pendant_extension_cache.sqlite3" `
  --time-limit 60 `
  --total-time-limit 900 `
  --replay-log ".\results\replay_edges56_57_fastpath100k_allpaths.csv" `
  --progress 1
```

The replay reported `replayed=12, solved=12, still_unsolved=0`. Audit the
certificates with:

```powershell
& $PY ".\src\verify_certificates.py" `
  --log ".\results\replay_edges56_57_fastpath100k_allpaths.csv" `
  --kind graceful
```

## Completed 58--60 Replay

The first pass through edges 58--60 produced 18,275,936 rows and 28 timeout
rows. The targeted replay solved all 28:

```powershell
& $PY ".\src\graceful_tree.py" `
  --replay-unsolved ".\results\five_leaf_nonspider_edges58_60_adaptive.csv" `
  --method compressed `
  --extension-fastpath-nodes 100000 `
  --extension-try-all-paths `
  --extension-cache-db ".\results\pendant_extension_cache.sqlite3" `
  --time-limit 600 `
  --total-time-limit 14400 `
  --replay-log ".\results\replay_edges58_60_allpaths_600.csv" `
  --progress 1
```

The replay reported `replayed=28, solved=28, still_unsolved=0`. The first-pass
timeout rows used 448,244,942 search nodes in total; replay used 92,835. Keep
both logs when reporting the result.

## Current Research Loop

The next graceful-tree stages are deliberately separated:

1. Continue the five-leaf non-spider family above 60 edges only after the
   58--60 timeout structures have been recorded and classified.
2. Generalize the hard-pattern detector for the three-branch unbalanced
   structures found at 60 edges, then replay those cases with the resulting
   budget/search-order rule.
3. Continue the vertex-bounded rooted-certificate experiment beyond 13
   vertices, beginning with 14, while recording direct-search reduction and
   certificate-closure rates.
4. Connect the generic rooted certificates to fixed-leaf reduced skeletons.
   This is the route toward covering more than the current five-leaf slice;
   it is not a reason to attempt raw enumeration of every tree through 40
   vertices.

Each stage follows the same rule: enumerate a defined family, preserve a
certificate for every solved case, classify timeout structures, formulate a
reduction that can be independently checked, and only then expand the family.
