# M3D Research-Train Exhaustion

The research-train partition — the in-sample data over which the M2B benchmarks
and the M3A/M3B/M3C development research were conducted — is treated as
**exhausted for new candidate research**. The machine-readable decision is
`research/m3d/research_train_exhaustion.json`; this is its prose companion.

## Why exhaustion

Across M2B, M3A, M3B, and M3C the research program examined a broad surface of
specifications, cost scenarios, risk overlays, endpoints, bootstrap methods, and
decision rules on the same research-train data (catalogued in
`research/m3d/research_specification_catalog.json` and, as degrees of freedom, in
`research/m3d/research_multiplicity.jsonl`). One candidate reached the development
gate — M3C's dual-horizon trend specification — and was **mechanically rejected**.
Continuing to search that same in-sample data would accumulate hidden multiplicity
and adaptive-overfitting risk without any independent confirmation. Declaring the
partition exhausted closes it to new candidate research and makes future evidence
depend on genuinely out-of-sample data.

## What exhaustion forbids and allows

- **Forbidden** on the research-train partition: proposing, tuning, ranking,
  selecting, or promoting any new candidate; any new performance measurement whose
  purpose is candidate discovery. The `require_operation_allowed` guard fails closed
  on such operations, resolved by partition fingerprint.
- **Allowed**: integrity checks, replay, and provenance verification that compute
  no strategy signal, return, or metric.

## Relationship to the prospective cohort

Exhaustion motivates the prospective facility: because the training data is closed,
any future review must use the strictly non-overlapping prospective cohort
(`docs/M3D_PROSPECTIVE_PROTOCOL.md`). That cohort is currently **immature** (3 of a
required 365 observations) and, even at maturity, would not be evaluation
authorized within M3D — a future review would be a separate, separately
pre-registered milestone.

## Honesty, not correction

Declaring exhaustion does not retroactively make any prior inference confirmatory
and does not "correct" a p-value. Each prior milestone drew at most an in-sample,
research-train measurement whose only possible outcome was eligibility for an
independent review; the one candidate that reached that gate was rejected.
Exhaustion simply records that the search on this data is closed and prevents the
opposite failure — silently continuing to mine exhausted data.
