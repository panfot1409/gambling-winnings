# M3D Multiplicity Note — Descriptive Honesty, Not a Correction

`research/m3d/research_multiplicity.jsonl` is an append-only, hash-chained ledger
of every distinct **research degree of freedom** already exercised across
Milestones 2B, 3A, 3B, and 3C. Its purpose is honesty about adaptivity — making
the total surface of researcher choices visible — **not** a retroactive
multiple-testing correction.

## What it records

Each line (after a genesis sentinel) is one degree of freedom, in one of eight
dimensions, with its originating milestone, first-seen commit, role, and status:

- **strategy_specification** — the 8 strategies exposed (cash, buy-and-hold,
  moving_average_crossover(20,50), sma_20_50, donchian_55_20, the two
  volatility-targeted overlays, and the one dual-horizon-trend candidate). Each
  identifier's parameter tuple is the specification; a repeated use of the same
  specification is recorded, never collapsed.
- **cost_scenario** — every cost scenario (M3A base/stressed/severe; M3B/M3C
  compatibility_v1/causal_proxy_base/causal_proxy_stressed).
- **risk_overlay** — the volatility-target overlay and the declared-but-disabled
  drawdown breaker.
- **data_partition** — the exercised partitions (m2b_train, m2b_validation,
  research_train). Sealed partitions are catalogued in the data-use ledger.
- **endpoint_statistic** — the primary inferential endpoints (M3A mean OOS excess
  return; M3C mean daily paired log-excess) and descriptive diagnostics (PSR,
  benchmark metrics, fractional accounting metrics).
- **bootstrap_method** — the fold-stratified moving-block bootstrap variants.
- **decision_criterion_set** — the M3A development comparison rule and the M3C
  seven-part promotion rule.
- **experiment** — every registered experiment id (M2B train/validation
  benchmark; M3A run-001/002/003; M3B run-001; M3C run-001).

## Why it is descriptive, not confirmatory

Recording that many specifications, endpoints, and experiments were examined does
**not** retroactively make any prior inference confirmatory, and it does not
"correct" a p-value. Prior milestones each drew at most an in-sample,
research-train measurement whose only possible outcome was eligibility for an
independent review — and the one candidate that reached that gate (M3C's
dual-horizon trend) was **mechanically rejected**. The ledger simply prevents the
opposite failure: silently forgetting the losing ideas and the breadth of the
search, which is how an honest-looking single result hides a large multiplicity.

## Integrity guarantees

- **Anti-orphan:** the strategy and cost-scenario members are derived from the
  committed specification catalog, and the experiment members from the committed
  registries, so `verify_research_multiplicity` fails if any catalogued strategy,
  cost scenario, endpoint, or registered experiment is missing.
- **No forgetting:** there is no deletion or truncation tool; the ledger is
  append-only and rebuilt in full, then compared byte-for-byte.
- **Benchmarks are distinguished from candidates:** cash and buy-and-hold carry
  `role=benchmark`; only the dual-horizon-trend specification carries
  `role=candidate`, `status=rejected_for_development_gate_promotion`.

M3D adds **no** new degree of freedom: it evaluates, ranks, tunes, and promotes
nothing. The ledger's final state is the honest inventory of a research program
that has been closed to new candidate research on its exhausted training data.
