# Defect-Switch Search for the 62-Edge Fixed Core

`src/defect_switch_search.py` searches the finite tail-completion problem
extracted from the final three 62-edge hard cases. It does not rerun the full
graceful-tree solver.

The fixed core already realizes differences `{24,...,62}`. The tool assigns
the remaining labels

```text
{17,19,20,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,46,52}
```

to four paths rooted at `(54,40,53,21)`, using differences `{1,...,23}`.
The default state space is

```text
(1,s,t,u),  s>=1, t>=0, u>=0, s+t+u=22,
```

which contains 253 tail-length vectors.

## Recommended first run

From the repository root in PowerShell:

```powershell
$PY = "python"

& $PY ".\src\defect_switch_search.py" `
  --output-dir ".\results\defect_switch_62" `
  --time-limit 5 `
  --node-limit 5000000 `
  --max-attempts-per-state 3 `
  --local-rewrite-threshold 8 `
  --progress 10
```

The search starts from the three explicit certificates in the theorem notes
and explores adjacent states obtained by moving one edge from one variable
tail to another.

## Resume after interruption

Use the same settings and add `--resume`:

```powershell
& $PY ".\src\defect_switch_search.py" `
  --output-dir ".\results\defect_switch_62" `
  --time-limit 5 `
  --node-limit 5000000 `
  --max-attempts-per-state 3 `
  --local-rewrite-threshold 8 `
  --progress 10 `
  --resume
```

Solved certificates and previous attempt counts are loaded from disk. The
program refuses to overwrite an existing run unless `--resume` is supplied.

## Broader second pass

If the seed-connected frontier stops growing, scan unresolved states directly
with a larger budget:

```powershell
& $PY ".\src\defect_switch_search.py" `
  --output-dir ".\results\defect_switch_62" `
  --time-limit 30 `
  --node-limit 20000000 `
  --total-time-limit 86400 `
  --max-attempts-per-state 6 `
  --local-rewrite-threshold 8 `
  --scan-all `
  --progress 10 `
  --resume
```

`--scan-all` may discover certificates in components not yet connected to an
original seed. Such certificates are valid new seed states, but the summary
reports their connectivity separately.

## Output files

The output directory contains:

- `states.csv`: every search attempt and every verified path certificate;
- `switches.csv`: adjacent solved states, changed edges, and the rewrite
  signature grouped by edge difference;
- `summary.json`: certificate coverage, switch counts, component sizes, and
  connectivity to the original three seeds.

Important summary fields are:

```text
solved_states
seed_connected_states
local_seed_connected_states
switch_components
largest_switch_component
```

`rewrite_size` in `switches.csv` is the number of old tail edges replaced by
the transition. A row is marked `local=1` when this number is at most
`--local-rewrite-threshold`.

Complete coverage by verified certificates proves the finite 62-edge slice
through the fixed-core criterion. A large seed-connected component with a
small collection of repeated rewrite signatures is the stronger structural
outcome: those signatures are candidates for a parameterized defect-switch
lemma.

## Optional 276-state boundary

Adding `--allow-zero-middle` also includes `s=0`, increasing the state space
from 253 to 276 vectors. Use a different output directory for that run; do not
resume a 253-state log with a different state-space definition.
