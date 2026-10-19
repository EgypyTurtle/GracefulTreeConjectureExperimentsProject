# eg-k14-artifact-v0.1.0-rc1

Preliminary research artifact: completed k=14 Erdos-Gyarfas extension search.

Original server records contain 18,060 completed prefix tasks and no candidate
counterexample, with 1,435,716,298 search states. Final-process wall time was
58,270.2 s; peak RSS was 53,600 KiB. Earlier completed work was reused, so this
is not a from-scratch total campaign timing.

This artifact contains:

- the exact C++ source, build commands, baseline attribution and tests;
- `publication/RESULT_NOTE.md` and `results/k14_reported.json`;
- the 1.9 MB original-server archive and SHA-256 sidecar under `data/k14/`;
- passed integrity, initial-frontier replay and refinement-replay reports.

Review status: provisional. No full independent DFS replay, formal certificate,
peer review, proof of the unrestricted conjecture, or first-result claim is
asserted. `max_n=72` is not an exhaustive 72-vertex graph census.

Public title: **Completed k=14 search for the Erdos-Gyarfas conjecture:
provisional computational artifact**.

Artifact SHA-256:
`8a814c86d59797a0ee8061e73e11f748c6f71e5d00506b2b8542e478839ed1c5`.
The archive was collected after the run; it is not a pre-run source freeze.
The public software author handle is EgypyTurtle. Original baseline notices
are retained. See `publication/VERIFICATION.md` for audit limits and commands.
