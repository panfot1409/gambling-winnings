# V2B cumulative research-memory & anti-relabel method

`eth_research.v2b.research_memory` is the project's immutable, cumulative memory of **every
strategy family ever evaluated**. Its purpose is to stop research-level overfitting: trying
renamed "new" strategies on the same ETH history until one passes. A family that has been
evaluated counts permanently; a rejected family stays rejected for the same hypothesis/partition
unless genuinely new external evidence justifies a separately-documented revision — which V2B does
not do.

## The family identity

`ResearchFamilyIdentity` is a frozen record of the *semantic* essence of a strategy family, bound
by 15 fields: `signal_family`, `signal_source`, `input_instruments`, `executed_instruments`,
`horizon_structure`, `threshold_structure`, `allocation_structure`, `risk_overlay`,
`volatility_overlay`, `drawdown_overlay`, `cost_model_family`, `context_requirement`, `benchmark`,
`primary_endpoint`, and `partition`. The fingerprint is `sha256` over the canonical identity.

A family **cannot become "new"** merely by changing its display name, class name, module path,
experiment id, package version, serialization order, description, a wrapper function, an output
scaling, default-parameter syntax, or a horizon by an immaterial amount. `signal_family` is
validated through a canonical-plus-alias map (`FAMILY_SIMILARITY_POLICY`), so aliases such as
`twin_horizon_trend → dual_horizon_trend`, `weighted_threshold_moving_average →
moving_average_crossover`, and `rolling_extrema_breakout → donchian_breakout` collapse to the same
canonical family. Cosmetic attributes are excluded from identity.

## The cumulative catalog

`RESEARCH_FAMILY_CATALOG` binds ten families, sorted by fingerprint and all distinct:

| Milestone | Family | Role |
|---|---|---|
| — | cash | benchmark |
| — | buy-and-hold | benchmark |
| M3A | SMA crossover | candidate (rejected) |
| M3A | Donchian breakout | candidate (rejected) |
| M3B | volatility-target (×2 variants) | candidate (rejected) |
| M3C | dual-horizon trend | candidate (rejected) |
| V2A | mean-reversion | candidate (rejected) |
| V2A | volatility-scaled | candidate (rejected) |
| V2A | trend | candidate (rejected) |

`historical_candidate_family_count()` = **8** (the two benchmarks are excluded from the candidate
count). This is the number the multiplicity policy uses as its cumulative denominator base.

## Fail-closed governance checks

- `assert_family_is_new(identity)` — a declared V2B family whose fingerprint (canonical or via the
  alias policy) matches any catalogued family is rejected.
- `assert_not_reviving_rejected(identity)` — a rejected M3C/V2A family cannot re-enter under a new
  name; the `rejected_family_index.json` binds every prior rejection.
- `assert_declared_families_distinct(identities)` — the declared V2B set must be mutually distinct
  (no candidate split into aliases, no two collapsed after seeing results).

The adversarial suite exercises every relabel route: a V2A family renamed; M3C wrapped in another
function; SMA expressed as weighted thresholds; Donchian as rolling extrema under aliases; a
volatility overlay moved into the engine; a parameter shifted by one day; a family moved to a new
module; a benchmark relabelled as a candidate; a candidate split into aliases; multiple candidates
collapsed after results. Each must be caught (fail-closed).

## Committed, byte-reproducible artifacts

`verify_research_memory` re-derives five artifacts byte-for-byte from the catalog: the family
catalog, the family-similarity policy, the rejected-family index, the append-only hash-chained
research-exposure ledger, and the research-memory state. Any drift fails closed.

## Honest limitation

Semantic identity is a strong deterrent, not a proof of novelty. It cannot certify that a genuinely
distinct fingerprint corresponds to a genuinely distinct *idea*; it guarantees only that the
enumerated relabel routes and the recorded history are accounted for. Novelty of the two V2B
candidate families is additionally argued from the literature (`docs/V2B_HYPOTHESIS_REVIEW.md`) and
the distinctness matrix in `tests/test_v2b_candidates.py`.
