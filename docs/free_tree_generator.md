# Free-Tree Generator Roadmap

`src/free_tree_generator.py` is the first isolated component for the
vertex-bounded route. It generates unlabeled, nonisomorphic trees layer by
layer using a simple complete augmentation rule:

```text
every tree on n+1 vertices
  -> delete a leaf
  -> obtain a tree on n vertices
```

The implementation attaches a leaf at every vertex of every previous tree and
canonicalizes the result at its one or two tree centers. Isomorphic candidates
are discarded before the next layer. It stores compact canonical shape strings
rather than retaining every adjacency list in memory.

Run the generator-only validation first:

```powershell
$PY="python"
& $PY ".\src\free_tree_generator.py" `
  --max-vertices 15 `
  --progress 1000
```

The counts should begin:

```text
1, 1, 1, 2, 3, 6, 11, 23, 47, 106, 235, 551, 1301, 3159, 7741
```

Only after this count check should the generator be connected to graceful
search. The practical order is:

```text
n <= 15: generator and verifier validation
n <= 18: first complete graceful pilot, 205,004 trees
n <= 20: first substantial complete run, 1,346,024 trees
n <= 22: optional expansion, 9,114,285 trees
```

The first solver pilot uses the streaming runner. It keeps only one vertex
layer in memory and reuses the existing SQLite pendant-extension certificates:

```powershell
& $PY ".\src\free_tree_graceful_experiment.py" `
  --max-vertices 15 `
  --time-limit 30 `
  --extension-fastpath-nodes 2000 `
  --extension-try-all-paths `
  --extension-cache-db ".\results\pendant_extension_cache.sqlite3" `
  --log ".\results\free_tree_graceful_v15.csv" `
  --progress 1000 `
  --generation-progress 0
```

The first `n <= 15` pilot processed 13,188 free trees. It solved 13,166 on
the first pass and isolated 22 timeout candidates for targeted replay. The
solver log was independently certificate-checked; all 13,166 solved rows
passed. The replay can be run separately with a larger per-tree budget and
the original log as its solved-case filter:

```powershell
& $PY ".\src\free_tree_graceful_experiment.py" `
  --max-vertices 15 `
  --time-limit 60 `
  --extension-fastpath-nodes 100000 `
  --extension-try-all-paths `
  --extension-cache-db ".\results\pendant_extension_cache.sqlite3" `
  --skip-solved-from ".\results\free_tree_graceful_v15.csv" `
  --log ".\results\free_tree_graceful_v15_replay60.csv" `
  --progress 1 `
  --generation-progress 0
```

The case name is based on the canonical free-tree code, so an interrupted run
can be resumed without relying on row numbers:

```powershell
& $PY ".\src\free_tree_graceful_experiment.py" `
  --max-vertices 20 `
  --time-limit 60 `
  --skip-solved-from ".\results\free_tree_graceful_v15.csv" `
  --extension-fastpath-nodes 2000 `
  --extension-try-all-paths `
  --extension-cache-db ".\results\pendant_extension_cache.sqlite3" `
  --log ".\results\free_tree_graceful_v20_continuation.csv" `
  --progress 5000 `
  --generation-progress 0
```

The generator itself is not yet a claim about the graceful conjecture. Every
solved row must still carry a labeling certificate and pass the independent
verifier. For larger layers, the solver should stream cases and use the
existing persistent pendant-extension certificates rather than retaining all
graphs or all labelings in RAM.
