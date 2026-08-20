# Structural Method Registry

This registry records the status of distinct structural approaches. A method
is marked as proved only when its certificate can be checked independently;
large positive experiments are recorded as evidence, not as proof.

| Method family | Object being studied | Current status | Exact remaining gap |
|---|---|---|---|
| Extremal pendant extension | One terminal path and a rooted graceful base | **Proved** | Does not cover trees whose terminal lengths are all 1; does not automatically extend two paths at once |
| Parameter-ray clustering | Fixed `(a,b)` and variable pendant length `c` in `T(2;1,1;a,b,c)` | **Certified for each stored base** | Need a complete list or formula for all base certificates |
| Rooted certificate cache | Canonical marked rooted bases | **Operationally verified** | A hash is not a mathematical classification; preserve full marked codes for a proof table |
| Branch residue analysis | Ordinary search state space by edge count mod 3 | **Diagnostic only** | No graph-theoretic obstruction has been established |
| Multi-path transition system | Sequences of certificates with changing marked paths | **Blocked under the current lemma** | After one extension, other extremal endpoints generally cease to be extremal |
| Gap-extension certificates | Arbitrary leaf attachment with label insertion | **Local sufficient rule** | No global closure theorem; failures are not non-gracefulness proofs |
| Explicit Skolem/Rosa formulas | Closed label formulas for fixed skeleton families | **Open in this project** | Need a formula with an injectivity and complete-difference proof |
| Modular/degree obstruction | Necessary conditions from degree and parity data | **No obstruction found** | Must produce a genuine forbidden family or a certified pruning invariant |
| Boundary skeletons | All terminal lengths equal 1 | **Outside pendant reduction** | Need separate direct construction or a second reduction rule |
| Unit-arm two-branch construction | `T(q;1,1;1,1,1)`, `q >= 1` | **Proved closed form** | Does not cover other terminal-length vectors or the three-branch skeleton |
| Tension-first search | Signed edge differences integrated from a rooted zero | **Exact experimental solver** | Mixed performance; no repeatable advantage over branch/diff yet |
| Modular/parity filters | Residue and odd-cut necessary conditions | **Necessary only** | Weak conditions can pass while actual differences repeat |

## Current theorem-level statement

For any tree `R` with a marked leaf `x`, if `R` has a graceful labeling with
`x` labeled `0` or `|E(R)|`, then every tree obtained by repeatedly extending
`x` by pendant edges is graceful. This is the only general extension theorem
currently justified here.

## Current data-level statement

In the controlled family `T(2;1,1;a,b,c)` over 47--65 edges, 4,327 cases
collapsed to 310 rooted reduction bases. For fixed `(a,b)`, the observed `c`
values shared a base, giving certified one-dimensional rays. The six hardest
boundary cases used only two rooted bases after the larger replay budget.

## Anti-overclaim rules

1. A `pendant-extension+branch` row is a solved tree, not a proof that the
   tree has an extremal rooted certificate.
2. A timeout is not a failed labeling and not a counterexample.
3. Trying all eligible paths is a union of one-path searches, not a
   multi-path extension theorem.
4. A reduction hash groups computational instances but is not by itself a
   canonical mathematical invariant.
