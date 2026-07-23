# V2 Fable 5 Full-System Adversarial Audit — Plan of Record

This is the plan for the **Fable 5 full-system adversarial audit** of the merged V2 platform: the
exhaustive pre-paper bug sweep that must complete before any paper/shadow trading can be considered.
It audits, remediates, and freezes; it does **not** start paper trading, does not activate
prospective collection, and does not create, select, or evaluate any strategy candidate.

## Critical scientific fact (governs everything below)

V2A and V2B produced **valid governed null results**: zero candidates nominated, zero candidates
eligible for paper-trading promotion (`research/v2a/results.json` → `nominated_candidate_id: null`;
`research/v2b/v2b_results.json` → `nominated_candidate_id: null`, `eligible_candidate_ids: []`).
V2C evaluated **no strategy** — it qualified offline operations with a synthetic cash-control target
only. Therefore this audit must not create, relabel, resurrect, reinterpret, or select a paper
candidate; must not loosen any historical decision rule; must not read sealed partitions to search
for a candidate; and must not treat operational qualification or "implementation-complete" as
evidence of edge. If no independently valid pre-existing eligible candidate exists — and none does —
`paper_activation_ready` remains **false**. A hardened, audited platform with paper trading still
blocked by the absence of an eligible strategy is the **expected successful outcome**.

## Accepted baseline (verified in Phase 0, not assumed)

| Item | Value |
|------|-------|
| `main` = V2C merge (MV2C) | `09fc9c0204a3cd71e0c7c84ba9dd605b9a5f811b` (parents `6e0d60e`, `d794206`; tree `3bf6e57d…`) |
| V2C accepted head | `d7942065a8c21f1be9634cd15089b4e9e0d7ed97` |
| V2C `oq_result.json` | `739cec5dca07b984d6fb624384e490dcab7722c5341053790d5ba8cd1945b897` |
| V2C result bundle | `e52308a0ffd048ffe4283b51b052fd65e2aab4a37156e53952c16354a9dcb525` |
| OQ registry | `9a16252f…` — `registered → started → completed`, verdict `qualified` |
| Sealed ledgers ×3 | 0 bytes each, sha256 `e3b0c442…b855` |
| Version / runtime | `2.0.0.dev2` / CPython 3.12.3 (`.venv`; bare python is 3.11 and non-authoritative) |
| Repository | private; prospective collection inactive; 0 production proposals |
| Nominations | zero (V2A null, V2B null); `sell_ready` derived **false**; no paper/live record; no LICENSE/public release |
| Baseline battery at this exact tree | local: 3694 passed / 12 skipped / 0 failed; CI: 13/13 workflows success on `09fc9c0` |
| Governed-tree fingerprint | 215 files under `research/ governance/ release/`; list-hash `fae2990f…0d92` (session snapshot) |

## Scope

Everything merged on `main`: research/simulation engines (M2A→V2C), governance/provenance machinery,
security/supply-chain/workflow surfaces, process isolation and the buyer boundary, the operational
platform (publication, recovery, SLO, resource, crash campaigns), private distribution, documentation
claims, and the readiness derivations. Five independent primary auditors (scientific; governance;
security; operations; buyer) plus a cross-auditor challenge round.

## Exclusions (hard)

- No new candidate research; no strategy evaluation; no sealed-partition or M3D prospective access.
- No re-run of any consumed one-shot (M2B test eval, M3A/M3B/M3C runs, V2A/V2B experiments, V2C OQ).
- No paper/shadow trading; no prospective activation; no broker/exchange connectivity; no order
  routing; no live capital. The synthetic catastrophe rehearsal is not paper trading.
- No tag, release, LICENSE, public publication, merge, or undraft.
- No mutation of any accepted governed artifact; append-only errata for immutable-document errors.

## Trust and data-flow boundaries under attack

1. **Sealed-partition boundary** — the three byte-empty ledgers and the untouched holdout/prospective
   values; no read path may open them outside their (never-triggered) governed protocols.
2. **One-shot / registry boundary** — hash-chained registries, one-shot budgets, freezes,
   supersessions, activation anchors, completion intents, immutable archives.
3. **Process boundary** — the buyer harness (`-I -S -B`, minimal env), child lifecycle, framing.
4. **Filesystem boundary** — path confinement, symlink/traversal refusal, closed output sets,
   write-once publication, calculation-free recovery.
5. **Network boundary** — no runtime network clients; workflows read-only, SHA-pinned, secretless.
6. **Buyer-evaluation boundary** — approved outputs only; no source/introspection/traceback leakage.
7. **Prospective-evidence boundary** — inactive; only a read-only probe workflow exists on `main`;
   the update workflow ships as an `.inactive` template.
8. **Claims boundary** — every factual claim in docs/reports/PR bodies maps to generated evidence.

## Failure taxonomy / severity

- **Class A** — scientific, accounting, financial, evidence, or claim-integrity defect.
- **Class B** — security, governance, provenance, lifecycle, or buyer-boundary defect.
- **Class C** — defense-in-depth, diagnostics, documentation, test-strength, usability defect.
- **Class D** — sealed-partition access, immutable accepted-result drift, one-shot corruption,
  public exposure, or uncontrolled-exposure capability. **Any Class D finding is a hard stop.**

Severity: Critical / High / Medium / Low, judged by exploitability and impact on scientific truth,
governed state, or a future paper run.

## Evidence and remediation rules

1. Every claimed defect is independently reproduced before it is fixed.
2. A failing regression test lands before or alongside each fix.
3. Verifiers are never weakened to make an attack disappear.
4. Accepted immutable results are never mutated; consumed one-shots are never re-run.
5. If qualification-defining code must change, the old OQ is not claimed to certify the new code;
   the coverage boundary is recorded and synthetic, non-one-shot regression qualification is used.
6. Commits are small, append-only, and independently green.
7. A Class A defect that invalidates accepted results is a hard stop unless the honest result can be
   preserved and explicitly invalidated without re-run.

## Phases

0. Read-only preflight (complete — see baseline table).
1. This plan + a fail-closed machine-readable system inventory
   (`governance/v2/fable5_system_inventory.json`, builder/verifier in
   `eth_research.v2.fable5.inventory`). The inventory fails closed on missing components, extra
   unclassified components, symlinks, path traversal, duplicate normalized paths, unexpected
   executables, ungoverned workflow additions, unregistered CLI surfaces, and public-API drift.
2. Five independent primary auditors (parallel, read-only, disposable clones, forbidden from
   trusting each other): (1) scientific/numerical/accounting/data integrity; (2) governance/
   provenance/immutability/exactly-once; (3) security/supply-chain/isolation/IP; (4) operations/
   reliability/recovery/risk controls; (5) buyer diligence/API boundary/commercial honesty/
   sell-ready derivation.
3. Cross-auditor challenge round (1→2→3→4→5→1); the primary agent resolves all disagreements.
4. Finding reproduction + remediation (`docs/V2_FABLE5_BUG_LOG.md`), failing-test-first.
5. System-wide standing adversarial test matrix (see the enumerated matrix in the milestone spec).
6. Synthetic catastrophe rehearsal (disposable, zero-exposure, no network, not paper trading).
7. Paper-readiness gate: pure machine-readable derivation, no forcing literal; expected state
   `eligible_paper_candidate_present=false → paper_activation_authorized=false`,
   `paper_trading_active=false`, `sell_ready=false`; gap report `docs/V2_PAPER_READINESS_GAP.md`.
8. Fable 5 audit freeze: `governance/v2/fable5_system_inventory.json`, `fable5_audit_manifest.json`,
   `fable5_findings.json`, `fable5_remediation_state.json`, `paper_readiness_state.json`,
   `fable5_source_freeze.json` (commit-SHA circularity resolved with a source-freeze commit plus an
   artifact-only anchor if needed).
9. `.github/workflows/v2-fable5-replay.yml` — read-only, `contents: read`, no secrets/uploads/OIDC,
   SHA-pinned, 3.12 authoritative + 3.13 compat, asserts `paper_activation_authorized == false`,
   `paper_trading_active == false`, `sell_ready == false`, fresh/shallow-clone safe.
10. Documentation set + ≥250-item terminal audit (`docs/V2_FABLE5_TERMINAL_AUDIT.md`).
11. Terminal battery (all gates, full pytest with exact counts, all historical verifiers, fresh +
    shallow clones, distribution double-build + scanner).
12. Exactly one draft PR to `main` (kept draft); monitor all required CI to terminal; report URLs.

## Hard stops

Sealed-partition read; sealed-ledger change; accepted immutable drift; one-shot re-run; candidate
creation/evaluation/relabel; paper/shadow start; prospective activation; order egress; secret or
private-artifact exposure; uncontrolled-exposure capability in an implemented path; governance
weakened to pass; accepted results not independently reconstructable.

## Terminal verdicts (verbatim)

- Expected (no candidate): `FABLE 5 V2 FULL-SYSTEM AUDIT COMPLETE — PLATFORM HARDENED AND
  INDEPENDENTLY VERIFIED; NO ELIGIBLE PAPER-TRADING CANDIDATE EXISTS; PAPER ACTIVATION REMAINS
  BLOCKED; PROSPECTIVE COLLECTION INACTIVE; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY`
- Conditional (only with an independently proven pre-existing eligible candidate — none exists):
  `FABLE 5 V2 FULL-SYSTEM AUDIT COMPLETE — PLATFORM HARDENED AND INDEPENDENTLY VERIFIED;
  PAPER-RELEASE CANDIDATE FROZEN BUT NOT ACTIVATED; PROSPECTIVE COLLECTION INACTIVE; ALL SEALED
  PARTITIONS UNTOUCHED; V2 NOT SELL-READY`
- Hard stop: `FABLE 5 V2 AUDIT STOPPED — SCIENTIFIC, GOVERNANCE, SECURITY, IMMUTABILITY, OR
  UNCONTROLLED-EXPOSURE INTEGRITY COULD NOT BE ESTABLISHED; PAPER TRADING NOT AUTHORIZED; V2 NOT
  SELL-READY`
