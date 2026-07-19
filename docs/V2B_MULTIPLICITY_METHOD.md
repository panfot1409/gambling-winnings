# V2B cumulative multiplicity & alpha-spending method

Preregistered **before any V2B result exists** (`eth_research.v2b.multiplicity`,
`research/v2b/research_multiplicity_state.json`). V2A returned a null; the danger now is
spending a fresh 5% every time a "new" family is tried until one clears by chance. This policy
accounts for the project's **cumulative** research exposure and derives the conservative
per-family threshold the V2B primary nomination test must clear.

## The policy

| Field | Value |
|---|---|
| Correction | Holm-Bonferroni, family-wise, over the cumulative family count |
| Cumulative α budget (whole program) | **0.05** (fixed; never reset) |
| Historical candidate-family count | **8** (M3A SMA + Donchian; M3B vol-target ×2; M3C dual-horizon; V2A meanrev + vol-scaled + trend) |
| V2A candidate families | 3 |
| V2B maximum new families | **2** (milestone §8) |
| Total families (correction denominator) | **10** |
| Corrected per-family α (rank-1 bound) | **0.005** = 0.05 / 10 |
| Corrected one-sided bootstrap confidence | **0.995** |
| Tie behaviour | highest primary point estimate, else nominate none |
| Reset | **never** |

Benchmark-only families (cash, buy-and-hold) are catalogued but do **not** count toward the
candidate-family denominator — a benchmark is never a nominatable candidate. The historical count
is derived from the cumulative research-memory catalog
(`eth_research.v2b.research_memory.RESEARCH_FAMILY_CATALOG`), not hard-coded, so the denominator
cannot silently drift from the recorded research history.

## Why Holm-Bonferroni, and what "rank-1 bound" means

Holm-Bonferroni is a step-down family-wise procedure: sorted p-values are compared against
`α/(m)`, `α/(m-1)`, …, `α/1`. The **most conservative** comparison — the one the first (smallest)
p-value must pass — is the rank-1 Bonferroni level `α/m` with `m = 10`, i.e. **0.005**. V2B freezes
exactly that single-threshold bound as the primary requirement, so a nominated candidate must be
significant at a level that already accounts for both V2B's ≤ 2 families *and* the eight prior
families. Using the rank-1 bound (rather than the looser step-down levels for later ranks) is a
deliberately conservative pre-registration: it never *understates* the multiplicity burden.

## Invariants (fail-closed)

- The α budget does **not** reset because the package version changed, because BTC was added, or
  because the benchmark changed.
- There is **no** separate uncorrected test per fold; folds feed one corrected primary verdict.
- Diagnostics (regimes, sensitivity neighbours, alternative cost scenarios) report their own
  **unadjusted** intervals and are never promoted to fresh hypothesis tests.
- The published result reports both the unadjusted diagnostic interval **and** the corrected
  primary threshold/verdict, the number of families counted, and the α allocated.
- No p-hacking through alternative bootstrap variants: one preregistered fold-stratified
  moving-block bootstrap, fixed seed, fixed resample count, pinned percentile method.

## Honest limitations

This is a **frequentist** family-wise correction applied to *adaptively developed* research. It
bounds the family-wise false-positive rate **given the enumerated families**. It does **not**
eliminate researcher degrees of freedom — the choice of which families, features, and transforms
to try is not captured by any `m`. A passing corrected threshold is necessary, not sufficient, for
belief in an edge; it earns only an independent development-gate review, never a claim of validated
profit. The policy is conservative by construction and is disclosed here rather than presented as a
complete remedy for data-snooping.

## §6 — the new-information requirement

A V2B candidate is eligible **only** because it consumes a genuinely new input, BTC-USD. The frozen
`NEW_INFORMATION_REQUIREMENT` demands, for every V2B candidate identity: `btc` in the input
instruments; `context_requirement == "cross_asset_required"`; **no** ETH-only fallback; missing BTC
evidence yields *refuse / no signal*; and the candidate must be prefix-sensitive to BTC and inert
to future BTC values. `assert_uses_new_information` enforces the first two fail-closed at
registration; the causal properties are proven on synthetic panels in `tests/test_v2b_candidates.py`
(a constant/permuted/removed BTC input must change — or refuse — the decisions, never silently fall
back to a rejected ETH-only rule).
