# V2A Architecture

V2A adds three cooperating but independently-bounded subsystems on top of the accepted research
stack, all under package version `2.0.0.dev0`. None of them relaxes any accepted guarantee; each is
strict (decode-never-repair), frozen, hashable, and free of wall-clock nondeterminism.

## 1. Research core — `eth_research.v2`

The scientific centre. It reuses the accepted fractional engine, walk-forward, cost model, and
fold-stratified bootstrap; it never re-implements them.

- **constitution** — the emittable claim-status vocabulary and the standing `not_sell_ready` posture.
- **candidates** — three pre-registered ETH/USD candidate families, distinct from the M3C-rejected
  candidate, each with a scalar oracle.
- **protocol** — the pre-registration: folds, primary + stressed cost scenarios, bootstrap seed /
  resamples / confidence, benchmark, and the `NominationCriteria`. Hash-pinned.
- **partitions** — the firewalled research-train loader; sealed partitions are unreachable.
- **evaluator / decision** — reduce each candidate to evidence (bootstrap on primary and stressed)
  and apply the rule: at most one candidate, the single strictly-best supported qualifier, is
  nominated `eligible_for_development_gate_review`; ties nominate nobody.
- **results / registry / publication / orchestrator** — the immutable results record, the append-only
  hash-chained one-shot registry (a `started` consumes the budget forever), transactional
  publication under `research/v2a/`, and `run_one_shot` — the single governed sequence.
- **replay** — the offline `--check` verifier for the whole stack (see the runbook).

## 2. Shadow-operations platform — `eth_research.shadow`

Signal-only. It observes what a live operator *would* see without acting. Three non-live modes only
(`synthetic_demo` / `historical_shadow` / `paper_simulation`); any live/production/real-money mode is
rejected fail-closed. Pipeline: as-of clock (no look-ahead) → market-data envelope → signal envelope
→ risk-limit engine → latching kill switch → paper accounting → append-only journal, with pure
monitoring and deterministic checkpoint/recovery, driven by a deterministic runner and inspected by a
read-only CLI. No network, no orders, no credentials, no money.

## 3. Buyer-evaluation boundary — `eth_research.buyer`

Everything a prospective buyer may see, behind a fail-closed redaction gate. `redaction` refuses
secrets, embedded source, and raw/sealed data; `contract` states what is offered vs withheld;
`claims` / `scorecard` / `factsheet` carry only honest, constitution-validated, research-stage
statements; `diligence` assembles a source-free bundle and refuses it on any redaction violation;
`gateway` is a no-network reference door that serves only redacted artifacts and refuses every
withheld item.

## Invariants that hold across all three

- No network / exchange / wallet imports anywhere (AST hygiene gate over `src`, `tests`, `examples`).
- The three sealed access ledgers stay byte-empty (`research/m3a`, `research/m2b`, `research/m3d`).
- The governed experiment runs at most once; the registry makes that mechanical.
- The standing posture is `not_sell_ready`; nothing is an out-of-sample, forward, or live claim.
