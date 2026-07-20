# V2A — commercial evidence, governed candidate program, shadow-operations platform, and buyer-evaluation foundation (plan)

**Status: research-and-operations foundation. V2A cannot and does not establish sell-readiness.**

V2A begins implementing the adopted [V2 sell-ready roadmap](./V2_SELL_READY_ROADMAP.md). It builds the
maximum useful V2 capability that can be completed **before** calendar-time forward evidence and
sealed out-of-sample authorization become the limiting factors. It is a **private**, offline,
research-and-operations milestone on `eth-research`.

This plan is committed first and does not pre-write success. The actual mechanical outcome (one
research-stage candidate nominated, or none) is recorded only after the one-shot execution.

## Governing baseline (verified in the read-only preflight)

- Repository `panfot1409/gambling-winnings`, **private**; branch `main` at
  `30e119933feb3d30cf3a890b177ea24b14ffc0da` (local == origin); working tree clean.
- Private v1.1.0 GA source = MPGA `61aa6aea6c666db71fe63d18a102e5502ccd17e7`; annotated `v1.1.0`
  still peels to MPGA; no remote `v1.1.0` (organization tag-write policy debt).
- Governed-state digest `b2077eaf18ad21f47f5978c5ced7c419a100c6ff2b89a9dd21a47f94b36bf7c2`
  reproduces; the three sealed ledgers are byte-empty
  (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`).
- M3C candidate permanently `rejected_for_development_gate_promotion`; M3D cohort `immature` and
  evaluation-unauthorized; M3E review-only and inactive with zero proposals.
- No V2 source, registry, protocol, experiment, or artifact exists prior to V2A.

## What V2A MAY do

- Build the commercial-evidence system (constitution, claims-to-evidence graph, lineage).
- Establish one tightly bounded, one-shot candidate-research budget.
- Define **up to three** genuinely distinct long-only spot candidate families **before** seeing
  results.
- Evaluate them **exactly once** on the already-authorized **M3A research-train partition**
  (2016-05-23 … 2022-06-21 UTC, 2221 daily rows).
- Nominate **at most one** candidate as `eligible_for_development_gate_review` — nothing more.
- Reject every candidate if none passes the preregistered rule (a valid successful outcome).
- Build and rehearse the **signal-only** shadow-operations platform (no network, no orders).
- Prepare, but **not activate**, a prospective forward-record workflow.
- Build buyer-evaluation and due-diligence foundations.
- Produce an honest **draft** V2A PR.

## What V2A MUST NOT do

Access the development gate; access the final holdout; use the M3D prospective cohort for strategy
evaluation; activate M3E; create a production proposal; execute real or paper orders through a
broker; add credentials, wallets, signing, leverage, shorting, borrowing, margin, or derivatives;
claim verified edge / untouched-OOS / forward / live performance; claim profitability or
sell-readiness; merge to `main`; or create a V2 tag.

## Claim-status vocabulary (V2A may emit only the first five below)

V2A-emittable: `research_only_observation`, `research_stage_supported`, `research_stage_rejected`,
`eligible_for_development_gate_review`, `not_sell_ready`.

Reserved for later, sealed, or forward milestones (V2A must **reject** any artifact claiming them):
`development_gate_supported`, `development_gate_rejected`, `final_holdout_supported`,
`final_holdout_rejected`, `forward_shadow_immature`, `forward_shadow_supported`,
`paper_record_supported`, `live_record_supported`, `sell_ready`.

## Architecture (isolated V2 namespace; accepted engines untouched)

- `src/eth_research/v2/` — research evidence: strict, claims, evidence, lineage, constitution,
  budget, candidates, protocol, partitions, regimes, costs, funding, latency, impact, capacity,
  sensitivity, bootstrap, monte_carlo, metrics, decision, results, registry, archive, publication,
  recovery, replay, experiment, orchestrator.
- `src/eth_research/v2/ops/` — signal-only shadow runtime: clock, events, feed, pipeline,
  signal_service, adapter (interfaces only), paper, risk, limits, kill_switch, checkpoint,
  reconciliation, monitoring, alerts, shadow, recovery.
- `src/eth_research/v2/buyer/` — buyer-facing projections: schema, claims_projection, redaction,
  gateway, demo, factsheet, diligence, pricing.

Strict separation is maintained between research evidence, operational shadow runtime, buyer-facing
projections, accepted historical code, and sealed-access controls. Accepted M1–M4 engines are not
modified merely to reuse V2 abstractions; V2 uses additive modules and wrappers.

## Governance rails carried into V2A

- Development version bumps to `2.0.0.dev0`; `Private :: Do Not Upload` preserved; no license added;
  the V1.1 annotated tag and release artifacts are not modified. Frozen milestone verifiers continue
  to validate their own recorded versions (via a narrowly-scoped historical-replay mode if needed),
  never by mass-editing frozen artifacts.
- The only strategy-evaluable partition is the M3A research-train partition; the development gate and
  final holdout are unreachable by strategy code (partition firewall + instrumented tests). Any
  sealed access is a Class D HARD STOP.
- A new, separate append-only hash-chained registry (`research/v2a/research_registry.jsonl`) proves
  exactly one research execution; a `started` event consumes the budget even on failure; no repair
  or reset.
- No candidate may relabel or lightly reparameterize the rejected M3C candidate
  (`dual_horizon_trend_63_252_vol_target_30d_50pct`); similarity guards enforce this.

## Phase map

0. Read-only preflight (25 checks) — no mutation until green.
1. Branch `claude/v2a-commercial-evidence-shadow-platform` + this plan + `2.0.0.dev0`.
2–6. Research core: namespace, constitution, claims graph, lineage, one-shot budget.
7–8. Candidate design review (primary-source, read-only) + scalar-oracle-first implementations.
9–16. Partition firewall, regimes, cost/latency stack, capacity, walk-forward, sensitivity,
      bootstrap + Monte Carlo.
17–21. Primary hypothesis + nomination rule, strict results schema, one-shot registry, transactional
       publication + recovery, immutable archive.
22–31. Signal-only shadow-operations platform (events, clock, pipeline, signal service, adapter
       interfaces, risk, kill switch, checkpoint/recovery, monitoring, shadow + paper runners).
32. Prepared-but-inactive forward-shadow activation package.
33–38. Buyer-facing schema + redaction + in-process gateway + synthetic demo + due-diligence
       generator + IP/ownership audit + pricing schema.
39–42. Documentation set, hygiene/prohibited-functionality gates, comprehensive tests, `v2a-replay`
       CI (SHA-pinned, contents:read, no id-token/secrets/schedule, dual-state).
43. Pre-registration adversarial review (4 independent auditors) + reproduce/fix (Class D = HARD STOP).
44–46. Source freeze `E` (CI green) → registration `R` (CI green, pristine) → one-shot execution `P`.
47–51. Mechanical decision + findings/factsheet + post-run red team (4 auditors) + fresh-clone
       byte-identical reproduction + forward-shadow activation proposal (draft-only).
52. Threat model.
55–58. Draft PR (no merge, no tag) + full local & CI gate battery + terminal audit + absolute stop.

## Terminal outcome

A reviewed, reproducible V2 research-and-operations foundation, possibly with **one** research-stage
candidate nominated for a **later** independent development-gate review. The terminal verdict is one
of: `V2A COMPLETE — ONE RESEARCH CANDIDATE NOMINATED; SEALED GATES UNTOUCHED`,
`V2A COMPLETE — NO CANDIDATE NOMINATED; SEALED GATES UNTOUCHED`, or
`V2A STOPPED — GOVERNANCE OR INTEGRITY HARD STOP`. V2A never claims edge, OOS, forward, live,
profitable, sell-ready, or production-ready. The PR is left open and draft; nothing is merged or
tagged; the next milestone is decided only after independent review.
