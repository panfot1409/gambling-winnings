# eth-research V2 — sell-ready roadmap

**This is a roadmap-only document. It plans V2; it does not begin V2.** No implementation, no
strategy evaluation, no access to any sealed partition or untouched holdout, and no change to any
package, workflow, governed research artifact, or ledger accompanies this document. The only change
in the branch that introduces this file is this Markdown file itself.

## 0. Baseline and framing

- **V1.1 (today) = a hardened, private research foundation.** It is a governed, reproducible,
  offline research toolkit: a strict data-provenance and firewall discipline, a walk-forward
  evaluation program with pre-registration and sealed holdouts, deterministic packaging, and a
  private, access-controlled v1.1.0 general-availability release (recorded on `main`). It is **not**
  a product, **not** a proven-profitable trading system, and makes **no** live-edge claim.
- **V2.0 (goal) = an independently validated, operationally deployable, commercially packaged
  system.** V2 turns the foundation into something a qualified buyer can evaluate, run, and license —
  *if and only if* new evidence earns each claim.
- The distance from V1.1 to V2.0 is mostly **evidence and operations**, not code volume. See §7.

## 1. The three pillars

V2.0 requires all three, independently:

1. **Verified performance** — out-of-sample, pre-registered, independently reproducible results with
   honest uncertainty and cost modeling. Not backtests presented as returns; forward-evaluated,
   multiplicity-controlled evidence with explicit assumptions.
2. **Operational deployment** — the system runs as a reliable, observable, recoverable service on a
   defined runtime, with data ingestion, scheduling, monitoring, alerting, and documented runbooks —
   distinct from a research script.
3. **Buyer-ready packaging** — a commercial wrapper a qualified buyer can assess and adopt:
   documentation, support model, security/compliance posture, evaluation boundary, and contracts
   drafted by qualified counsel.

A gap in any pillar means **not sell-ready**, regardless of the other two.

## 2. Phases V2A – V2RC

Each phase is gated: it does not start until the prior phase's exit gate passes, and it changes the
governed research record only through the existing pre-registration + sealed-holdout discipline.

| Phase | Name | Purpose | Exit gate (summary) |
| --- | --- | --- | --- |
| **V2A** | Evidence design | Pre-register the forward-evaluation program: hypotheses, universes, costs, decision rules, multiplicity budget, and the exact holdout-access protocol. **No holdout is touched.** | An independently reviewed pre-registration exists; no result computed. |
| **V2B** | Operational scaffold | Build the deployment surface (ingestion, scheduling, monitoring, recovery) against **synthetic/dev data only**; no research edge involved. | The scaffold runs end-to-end on synthetic data with observability + recovery drills. |
| **V2C** | Forward evaluation | Execute the pre-registered program on genuinely forward data as it matures; consume sealed holdout only per the V2A protocol, once. | Results are computed, reproduced, and archived; claims classified per §4. |
| **V2D** | Independent validation | A qualified independent party reproduces the evidence and the operational claims from source + provenance. | Independent reproduction matches within the declared tolerance; validation report issued. |
| **V2E** | Commercial packaging | Documentation, support model, security/compliance review, evaluation boundary (§5), pricing/commercial models (§6), and counsel-drafted contracts. | Buyer-facing package assembled; legal review complete. |
| **V2RC** | Release candidate | Freeze; run the full sell-ready hard-gate battery (§3); produce a truthful claims dossier. | **All** sell-ready hard gates pass; no gate waived. |

Forward evaluation (V2C/V2D) is **calendar-bound**: it cannot be accelerated by writing more code
(see §7). Its pace is set by how much genuinely out-of-sample data has accrued.

## 3. Sell-ready hard gates (all must pass; none waivable)

1. **Governance intact** — the V1.1 invariants still hold: governed research digest reproduces,
   sealed ledgers byte-empty, firewall enforced, no untouched holdout accessed outside its
   pre-registered protocol.
2. **Pre-registered evidence** — every performance claim traces to a pre-registration that predates
   the evaluation, with multiplicity controlled and assumptions stated.
3. **Independent reproduction** — a party other than the author reproduces both the numbers and the
   operational behavior from committed source + provenance.
4. **Honest uncertainty** — results carry confidence intervals, cost/slippage assumptions, capacity
   limits, and regime caveats; no point-estimate return is presented without them.
5. **Operational reliability** — the deployment meets defined SLOs in a staging environment, with
   monitoring, alerting, and a rehearsed recovery/rollback runbook.
6. **Security & compliance posture** — dependency/supply-chain review, secret hygiene, access
   control, and a documented data-handling policy; privacy of the repository and IP preserved.
7. **Evaluation boundary** — a hosted black-box evaluation path exists (§5) so a buyer can assess
   without receiving the source or the sealed research data.
8. **Truthful claims dossier** — every buyer-facing claim maps to its evidence tier (§4); nothing is
   labeled "proven profitable live" unless §4-D evidence exists.
9. **Legal readiness** — license/eval/commercial agreements drafted and reviewed by qualified
   counsel (not by this project or this document).

## 4. Claims taxonomy (what may be said, and the evidence each tier requires)

| Tier | Claim class | Minimum evidence |
| --- | --- | --- |
| **A** | "Reproducible research toolkit" | V1.1 as it stands: deterministic build, governed provenance, reproducible artifacts. *(Available today.)* |
| **B** | "Backtested / in-sample characteristics" | Documented historical simulation with full assumptions; explicitly labeled non-predictive. |
| **C** | "Forward / out-of-sample validated" | Pre-registered forward evaluation (V2C) + independent reproduction (V2D), multiplicity-controlled, with uncertainty. |
| **D** | "Proven profitable in live deployment" | A live, capital-at-risk track record over a material period with audited, reconciled statements. **This is the highest bar and is NOT a coding deliverable.** |

**Sell-ready = up to Tier C plus the operational and packaging pillars. It is explicitly NOT Tier D.**
"Sell-ready" means a buyer can responsibly evaluate and license the system on honest, validated
evidence — it does **not** mean the system is proven profitable in live trading. Conflating the two
is prohibited.

## 5. Hosted black-box evaluation boundary

To let a qualified buyer evaluate without handing over the IP or the sealed research data:

- The buyer interacts with a **hosted evaluation endpoint** that accepts allowed inputs and returns
  only the evaluation outputs and evidence — never source, never raw research data, never sealed
  holdout contents.
- The evaluation runs the **frozen, pre-registered** program; it cannot be steered to fish for a
  better-looking result (that would violate §3.2).
- The boundary is a **disclosure control, not a security guarantee against a determined buyer**:
  black-box hosting limits casual copying but does not fully conceal the underlying logic, and
  **containers do not fully conceal Python IP** (see §7). Legal protection (contracts, §9) carries
  the weight that technical measures cannot.

## 6. Commercial models (options to be chosen with counsel)

- **Source license** (private, per-seat or per-org) — maximum buyer control, weakest IP protection;
  requires the strongest contractual terms.
- **Hosted service / managed deployment** — the system runs as an operated service; the buyer gets
  results and operational access, not the source. Best IP protection; highest operational burden.
- **Evaluation-then-license** — a time-boxed black-box evaluation (§5) precedes any license.
- **Diligence data-room** — controlled disclosure to a serious buyer under NDA, with counsel.

Pricing, term, exclusivity, warranty, and liability are **commercial and legal decisions for the
owner and qualified counsel**, not for this roadmap.

## 7. Non-negotiable constraints (carried from V1.1 governance)

1. **The rejected M3C candidate remains rejected.** V2 does not resurrect it; any future candidate is
   a new, separately pre-registered hypothesis.
2. **V2 must earn every edge claim through new, pre-registered evidence.** No existing artifact is
   re-labeled as forward-validated.
3. **No untouched holdout is accessed merely to accelerate the roadmap.** Sealed partitions are
   consumed only per their pre-registered protocol, once, at the designed time.
4. **Forward-evidence maturity cannot be replaced by additional coding.** More features do not create
   out-of-sample track record; only the passage of genuinely forward time does. Engineering can make
   the system deployable; it cannot manufacture Tier-C or Tier-D evidence.
5. **Containers do not fully conceal Python IP.** Bytecode and images can be inspected/decompiled;
   treat technical obfuscation as friction, not protection, and rely on legal terms (§9).
6. **Legal contracts require qualified counsel.** Nothing here is legal advice; every agreement is
   drafted/reviewed by a qualified professional before use.
7. **No V2 implementation begins in this change.** This document is the plan; building starts only
   under a separate, explicitly authorized effort, phase by phase, behind the gates above.

## 8. What this document is not

- Not an authorization to start building V2.
- Not a claim that any edge exists.
- Not a claim that v1.1.0 is public, profitable, or independently validated.
- Not legal, financial, or investment advice.
