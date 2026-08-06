# Runbook

These commands assume PowerShell on Windows.

## Setup

```powershell
cd "C:\Users\56257\Documents\Codex\2026-07-31\new-chat\graceful-tree-labeling-experiments"

New-Item -ItemType Directory -Force -Path ".\results" | Out-Null
```

Use the bundled Python from Codex:

```powershell
$PY = "C:\Users\56257\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
```

Or use any local Python 3.10+:

```powershell
$PY = "python"
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

## Summarize Results

```powershell
& $PY ".\src\graceful_tree.py" --summarize-log ".\results\five_leaf_nonspider_max6_branch.csv"
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
