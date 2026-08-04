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

## Summarize Results

```powershell
& $PY ".\src\graceful_tree.py" --summarize-log ".\results\five_leaf_nonspider_max6_branch.csv"
```

## Replay Unsolved Cases

```powershell
& $PY ".\src\graceful_tree.py" --replay-unsolved ".\results\five_leaf_nonspider_max7_branch.csv" --method branch --time-limit 60 --replay-log ".\results\five_leaf_nonspider_max7_replay60.csv" --progress 50
```

