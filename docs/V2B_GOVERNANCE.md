# V2B one-shot governance

Preregistered **before any V2B result exists** (`eth_research.v2b.governance`, plus the reused
`eth_research.v2.budget` and `eth_research.v2.registry`). The whole cross-asset research program is
executed **exactly once**; this document is the governance that makes "executed exactly once"
tamper-evident and irreversible.

## The one-shot budget

`research/v2b/v2b_one_shot_budget.json` is the reused accepted `OneShotResearchBudget`, re-asserted
from committed bytes:

| Field | Value |
|---|---|
| `max_candidate_families` | 3 (V2B declares at most 2) |
| `max_research_executions` | **1** |
| `consume_on_start` | **true** — a `started` spends the budget even if the run later fails |
| `allow_repair_or_reset` | **false** — no second attempt, no repair, no reset |

`verify_budget` fails closed if the committed bytes drift from the fixed discipline.

## The protocol identity

`research/v2b/v2b_research_protocol.json` binds the whole frozen research design into one
`protocol_fingerprint`, computed over the SHA-256 of each committed input:

- the candidate source freeze (`research/v2b/candidate_source_freeze.json`),
- the aligned partition identity (`research/v2b/joint_partition_identity.json`),
- the execution scenarios (`research/v2b/execution_scenarios.json`),
- the cumulative multiplicity state (`research/v2b/research_multiplicity_state.json`),

plus the fold structure and nomination constants. Any change to any of those artifacts changes the
fingerprint, so a registry entry can never silently belong to a different design. Every registry
event carries this fingerprint.

## The append-only, hash-chained registry

`research/v2b/v2b_research_registry.jsonl` reuses the accepted `RegistryEvent` serialization and
SHA-256 chaining unchanged, adding only the `registered` precursor state. The lifecycle is:

```
registered  ->  started  ->  completed | failed
   (R)            (P)              (P)
```

- **R** appends exactly one `registered` event — governance only, no research. `tree(E) == tree(R)`
  except for the registry ledger.
- **P** appends `started` (consuming the budget), runs the fail-closed orchestrator once, applies
  the mechanical nomination decision, publishes a closed immutable archive, and appends a single
  terminal (`completed` on a valid result, `failed` otherwise).

The lifecycle is re-asserted on every read, so a hash-valid but hand-forged chain is still rejected.
Fail-closed guards, each covered by a test:

- a **second `started`** — rejected (the one-shot budget is spent);
- a `started` with **no prior `registered`** — rejected;
- a terminal with **no prior `started`** — rejected;
- a **second terminal** for a run — rejected;
- a **second `registered`** — rejected;
- a **byte-level tamper** of any event — detected (the recomputed `entry_hash` no longer matches).

Appends are serialized behind an exclusive advisory lock and fsync'd, so two concurrent writers
cannot both begin the governed run.

## What one-shot governance does not permit

No reset, no repair, no second execution, no reviving a rejected candidate under a new name, no
re-running V2B, no changing a frozen artifact, no merging/undrafting/retargeting the draft PR, no
tagging, and no modifying `main`. The repository and every acquisition artifact stay private.
