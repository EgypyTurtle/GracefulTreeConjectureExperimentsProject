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
