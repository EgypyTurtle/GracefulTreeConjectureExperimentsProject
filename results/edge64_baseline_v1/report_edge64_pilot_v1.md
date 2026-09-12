# Edge64 baseline pilot

## Universe

The exact edge64 five-leaf non-spider universe contains **10,040,677** cases:

```text
fiveleaf2e = 686,301
fiveleaf3e = 9,354,376
growth vs edge63 = 10.2112%
```

The canonicalization and end-order reduction match the edge63 generator. The
count is inside the pre-registered planning range of 9.8M--10.2M.

## Pilot

The representative pilot contains **200,000** deterministic stratified cases
across 54 strata. It used the existing solver stack with explicit 0.25-second
budgets per tier:

```text
Tier 0 input / solved / unresolved = 200,000 / 189,608 / 10,392
Tier 1 input / solved / unresolved = 10,392 / 1,134 / 9,258
Tier 2 input / solved / residual   = 9,258 / 4,565 / 4,693
errors                            = 0
```

Rates:

```text
Tier 0 initial hard rate = 5.196%
Tier 1 residual rate     = 4.629%
bounded Tier 2 residual  = 2.3465%
```

“Bounded Tier 2 residual” means unresolved after the explicit 0.25-second
Tier 2 budget. It is a planning diagnostic, not an exhaustive mathematical
residual count.

## Verification

The pilot produced 195,307 certificates. Independent verification passed for
all 195,307 certificates, with zero errors.

## Hardness signal

The residuals are concentrated in short-bridge strata and several three-branch
strata, with both central-tail parities represented. The largest residual
strata are recorded in `hard_pattern_summary.json` and `hardness_census.csv`.
The edge63 short-bridge diagnostic partially reappears, but the pilot does not
yet establish a universal hard pattern or a theorem.

## Planning result

The bounded pilot projects approximately **235,604** cases remaining after the
same bounded Tier 2 budget. The node-work projection is **0.992x** the recorded
edge63 baseline, but this comparison is planning telemetry only because the
pilot uses bounded tier budgets rather than the historical edge63 run protocol.

Classification: **EDGE64_NEW_DIFFICULTY**.
Recommended next mode: **STRUCTURAL_STUDY_FIRST** before a full ten-million-case
production run. The next study should target the residual tail and solver
strategy, not reopen the frozen edge63 C8 theorem-search line.

Edge63 remains frozen; this pilot does not alter its logs.
