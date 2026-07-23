# V2 Paper-Readiness Gap Report

**What this document is.** A scientifically honest statement of *why paper trading cannot yet
begin*, and *exactly what would have to happen first* — derived from the committed state of the
merged V2 platform (`main` = `09fc9c0`, the V2C merge MV2C) as audited by the Fable 5 full-system
adversarial audit on branch `claude/v2-fable5-full-system-audit`.

**The controlling fact.** Accepted V2 has **zero nominated strategy candidates**. V2A and V2B were
both run once, under pre-registered one-shot budgets, and both returned governed **null results**:

| Artifact | Field | Value |
|----------|-------|-------|
| `research/v2a/results.json` | `decision.nominated_candidate_id` | `null` (all three outcomes `nominated=false`) |
| `research/v2b/v2b_results.json` | `result.decision.nominated_candidate_id` | `null` |
| `research/v2b/v2b_results.json` | `result.decision.eligible_candidate_ids` | `[]` |

V2C evaluated **no** strategy at all — it qualified the *offline operational platform* (a virtual-time
operational-qualification run), not a trading edge. So there is nothing to paper-trade. This is not a
platform failure; it is the correct, recorded outcome of two honest experiments that did not find an
edge. **A hardened, audited platform with paper trading still blocked by the absence of an eligible
strategy is a successful audit outcome, not a failure.**

The machine-readable gate that encodes all of this is
`eth_research.v2.fable5.paper_readiness.derive_paper_readiness`, exposed as
`governance/v2/paper_readiness_state.json` and re-checked by `python -m eth_research.v2.fable5
verify-paper`. It is a **pure derivation from committed bytes** with *no forcing literal*: no
environment variable, CLI flag, monkeypatchable setting, or alternate builder can flip
`paper_activation_authorized`, `paper_trading_active`, or `sell_ready` to true. The load-bearing gate,
`eligible_paper_candidate_present`, is read directly from the V2A/V2B decision artifacts above, so it
derives **false** and can only change if a genuine, separately-governed nomination is produced.

## The paper-activation gate vector (current derived state)

`derive_paper_readiness` computes eleven gates; paper activation is authorized only if **all** hold.

| Gate | Derives | Blocked by |
|------|---------|------------|
| `platform_audit_complete` | **true** once the Fable 5 remediation state is frozen | — (met on this audit branch after freeze) |
| `platform_hardened` | **true** once remediation resolves all findings with zero unresolved Class A/B/D | — (met; see below) |
| `no_unresolved_class_abd_finding` | **true** | — (zero Class A/B/D found) |
| `eligible_paper_candidate_present` | **false** | **no nominated candidate exists** (V2A/V2B null) |
| `candidate_lineage_valid` | **false** | no candidate to have lineage |
| `strategy_specification_immutable` | **false** | no candidate spec to freeze |
| `paper_release_candidate_frozen` | **false** | no candidate + no release freeze artifact |
| `paper_duration_and_success_criteria_preregistered` | **false** | no pre-registered paper protocol |
| `human_activation_approval_recorded` | **false** | no human activation approval on file |
| `sealed_partitions_untouched` | **true** | — (all three sealed ledgers byte-empty) |
| `repository_private` | **true** | — (`Private :: Do Not Upload`; no license) |

Derived outputs: `paper_activation_authorized = false`, `paper_trading_active = false`,
`sell_ready = false`. Eight of eleven gates are unmet, and **the first unmet gate is the scientific
one** — everything downstream of it (`candidate_lineage_valid`, `strategy_specification_immutable`,
`paper_release_candidate_frozen`, the pre-registered paper protocol) is structurally false because
there is no candidate to attach it to. That ordering is deliberate: the gap is not a missing
signature or a checkbox, it is a **missing edge**.

## What must happen before paper trading can honestly begin

The gaps fall into five distinct categories. They are *not* interchangeable, and none of them may be
satisfied by relabeling, loosening a historical decision rule, or reinterpreting an existing null
result as a candidate.

### 1. Missing candidate evidence (the blocking gap — scientific)

There is **no eligible strategy**. To create one honestly requires a *new*, separately-authorized
research milestone that:

- forms and pre-registers a hypothesis **before** touching any sealed/holdout data, under the
  existing multiplicity / alpha-spending budget (the V2B cumulative research-memory ledger and
  anti-relabel verifier already guard against reusing a spent hypothesis or renaming a rejected one);
- brings **genuinely new information** (per the V2B new-information requirement) — a re-run of an
  already-evaluated candidate on already-consumed data is not new evidence and cannot nominate;
- passes the pre-registered nomination rule mechanically, producing a decision artifact with a
  non-null `nominated_candidate_id` and a valid lineage back to raw data.

Until such an artifact exists and is independently reconstructed by its oracle,
`eligible_paper_candidate_present` **must** remain false. This milestone does not exist yet and is
**not** authorized by the current directive. Inventing a candidate to turn this gate true is
explicitly out of scope and would be scientific misconduct.

### 2. Missing forward record (out-of-sample evidence)

Even with a nominated candidate, paper trading is the *mechanism that produces* forward evidence — it
is not itself proof of edge. The sell-readiness derivation (`ReadinessInputs.current()`) separately
requires `forward_evidence_exists` and `live_record_exists`, both currently false. A paper run must
therefore be **pre-registered with a fixed duration and success/failure criteria** *before* it
starts (the `paper_duration_and_success_criteria_preregistered` gate), so its result cannot be
re-interpreted after the fact. No such forward or live record exists today, and none may be
manufactured.

### 3. Missing legal / commercial approvals (governance, human-gated)

`paper_activation_authorized` requires `human_activation_approval_recorded` — an explicit, on-file
human decision to begin paper trading a specific frozen candidate under a specific protocol. Beyond
the paper gate, `sell_ready` additionally requires `license_granted`,
`human_authorization`, and `security_legal_review_passed`, all of which are external human/legal
gates this repository deliberately cannot self-satisfy (there is no `license` field or classifier;
the repo is marked private). These are **not** engineering tasks and cannot be closed by code.

### 4. Platform bugs (engineering — resolved)

The Fable 5 audit found **zero Class A (scientific), Class B (governance/security), or Class D
(sealed-state / immutable-drift / uncontrolled-exposure) defects**. The genuine findings were all
Class C (defense-in-depth / robustness), reproduced failing-test-first and fixed forward:

- **F5-C1** — the sales-honesty scanner failed *open* on a distant / cross-clause negator; the
  negation window was tightened to same-clause scope. (Fixed.)
- **F5-C2** — the fractional engine's *hypothetical* terminal liquidation crashed on a collapsed
  trailing-liquidity frame; it now prices that mark impact-free, mirroring the active-fill contract.
  (Fixed; no committed run is affected — real daily dollar-volume is strictly positive.)

Neither touches a sealed value, a frozen governed artifact, or any accepted V2A/V2B/V2C result; all
replay/oracle verifiers reproduce byte-identically after the fixes. See `docs/V2_FABLE5_BUG_LOG.md`.
This category is **closed** — it is not what blocks paper trading.

### 5. Accepted limitations (documented, by design — will not be "fixed" here)

- **No `failed` OQ terminal-event producer (F5-N1).** The V2C OQ registry defines a `failed`
  terminal event but no code path appends one, because the OQ execution surface is *frozen* (OQ-E2).
  The committed OQ run *completed*; the failure path is reserved for a future live/paper run and must
  be added to *new*, separately-frozen orchestration when a real run can fail — not retrofitted into
  frozen code.
- **Keyless registry integrity (re-affirmed).** The OQ registry `entry_hash` is an unkeyed sha256
  over public body fields: tamper-**evidence** against editing existing lines, not authenticity
  against a writer with filesystem access forging a byte-valid line. Disclosed in
  `docs/V2C_SECURITY.md` (finding F-6); delegated to human review of signed git history. A real
  paper/live deployment should upgrade this to a keyed/signed chain.
- **Paragraph-scoped honesty-scanner example marker (F5-C1 note).** A deliberate, author-controlled
  exemption over the project's own committed spec text; not an adversarial-input boundary.

## What this report does **not** authorize

Consistent with the standing constraints: this document does **not** create, relabel, resurrect,
reinterpret, or select a paper candidate; does not loosen any historical decision rule; does not
access any sealed partition to search for a candidate; does not treat the platform's operational
qualification as evidence of edge; and does not treat "implementation-complete" as "strategy-ready."
Because no independently valid, pre-existing eligible candidate exists, `paper_activation_ready`
(a.k.a. `paper_activation_authorized`) **remains false**, and paper/shadow trading **does not begin**.

## Honest terminal state

The platform is hardened and independently verified. Paper trading is blocked — correctly — by the
**absence of an eligible strategy**, not by any unresolved platform defect. The only path forward
that could ever set these gates true is a new, separately-authorized research milestone that
legitimately nominates a candidate, followed by pre-registered forward evidence and the external
human/legal approvals — none of which is in scope here.
