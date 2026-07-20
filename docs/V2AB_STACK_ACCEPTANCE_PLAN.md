# V2A–V2B Stack Acceptance Plan

This plan freezes the scope, method, and terminal semantics of the **independent stacked acceptance,
negative-evidence closure, legacy-research moratorium, commercial-truth audit, and merge-readiness proof**
for Milestones V2A and V2B. It is authored on the accepted V2B terminal state and is **read-only and
result-neutral** with respect to every accepted scientific and financial artifact. It adds no performance
claim: both governed V2 research programs produced **null** results and V2 remains `not_sell_ready`.

All work proceeds append-only on `claude/v2b-cross-asset-research-reset`. The V2A branch, `main`, every
immutable result, both nomination decisions, and both draft PRs' merge state are **not** modified.

## 1. Accepted SHAs (independently resolved at §0)

| ref | full SHA | note |
|---|---|---|
| `main` | `30e119933feb3d30cf3a890b177ea24b14ffc0da` | == `origin/main`; private V1.1 GA + V2 roadmap; untouched by V2A/V2B |
| V2A head `claude/v2a-commercial-evidence-shadow-platform` | `d437dafd67047470eae2c88fb14f0d8db6bf7091` | PR #16 (base `main`); merge-base of V2B |
| V2B head `claude/v2b-cross-asset-research-reset` | `5798610389af0905331fc5da20f54f4b8f7930fb` | PR #17 (base V2A); acceptance work descends from here |

PR #16: open, draft, unmerged, base `main`. PR #17: open, draft, unmerged, base V2A head, head V2B head.

## 2. Expected immutable hashes (frozen; the acceptance verifiers must reproduce these)

| identity | value |
|---|---|
| sealed-ledger empty (×3) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| V2A results | `6327de21759c21a97c8b1ee9c14782bb36534c8d968d6792eba54b7c9c58cbca` |
| V2B results | `d0b668f45c9e1f6adfeb606e16003a4bd5649d39bb0676a444cb691ec9fe6f1f` |
| V2B protocol identity | `2bdf606e24b6715442c5e3f0b14c16c11acac66d30f9d7774a16a82b20cf61f7` |
| V2B combined partition | `6a37a95e1f1faeb182834fce2b52d97b4e56f133a9a1fe9892dddf32087191e4` |
| V2B BTC dataset | `6896e6146d747d3b24295e07371eb8a1b8db4f7d8dbe991f2a797a720c1a39ce` |
| ETH dataset (M2) | `sha256:60aa988e9db786db5723c925abc794463c23ff701791173b745196c7a8b12033` |
| V2B research-family catalog | `3b5596955856a994160a3e062e07c7f24050d39ab0188b2b3747009cfeaf987a` |

- **V2A**: registry `started(seq 0) → completed(seq 1)` for `run_001`; V2A "registration" is its committed
  `research/v2a/pre_registration.json` (V2A predates the explicit `registered` registry event that V2B
  introduced). Three evaluated candidate families
  (`meanrev_zscore_accumulation`, `vol_scaled_hold_drawdown_guard`, `trend_regime_single_horizon`); zero
  eligible; `nominated_candidate_id = null`. *(The V2A PR #16 body and `V2A_FINDINGS.md` prose say
  "genesis → started → completed"; the actual accepted registry has two events, `started → completed`.
  The V2A branch files are immutable and not edited; PR #16's body is corrected in §21.)*
- **V2B**: registry `registered(seq 0) → started(seq 1) → completed(seq 2)` for `v2b_run_001`; two
  evaluated candidate families (`cross_asset_btc_confirmed_eth_trend`,
  `cross_asset_eth_btc_relative_strength_rotation`); zero eligible; `nominated_candidate_id = null`;
  per-family α = 0.005 = 0.05 / 10; each candidate passes only the strict-fold-majority gate (1 of 7) and
  independently fails the uncorrected primary 95% condition.

## 3. Audit scope

Independent, adversarial acceptance of the *stacked* V2A→V2B state for human merge review. In scope:
result reconstruction from primitive evidence; a complete immutable freeze table; BTC acquisition +
raw→result provenance; cumulative research-family enumeration; a permanent legacy-research moratorium;
a negative-evidence index + synthesis; a research-debt register; a commercial-truth pack + readiness
derivation; operational-platform and buyer-boundary acceptance; five independent auditors; a disposable
stacked merge simulation; PR-body correction; CI/replay hardening; a full local battery; final CI; and a
≥150-item terminal acceptance audit.

## 4. Auditor roles (§19)

1. **V2A scientific null** — primitive evidence, four criteria, no nomination, report honesty, no sealed access.
2. **V2B scientific null** — primitive evidence, multiplicity, seven gates, no nomination, lenient uncorrected diagnostic, no sealed access.
3. **BTC acquisition / provenance** — governance amendment, authorization, two acquisitions, canonical equality, workflow retirement, raw→result graph.
4. **Governance / security / operations / buyer** — registries, budgets, moratorium, workflows, network prohibition, shadow controls, buyer redaction, claims.
5. **Stacked merge mechanics & historical neutrality** — ancestry, patch identity, merge simulation, frozen artifacts, ledgers, version behavior, CI topology.

Auditors are strictly read-only, use scratch reproductions only, classify findings Class A/B/C/D, and
report clean when clean. Every finding is reproduced by the orchestrator before any fix.

## 5. Independent-oracle requirements (§5–§6)

Each acceptance oracle reconstructs a milestone's decision from **committed primitive evidence + the frozen
protocol only**. It must **not** call the audited milestone's own decision/report/nomination/claims helper
and must **not** treat a cached decision field as authoritative. Separate implementations are required for
interval inclusion, fold-win counting, gate conjunction, multiplicity threshold, tie behavior, and
nomination cardinality. No new strategy result is computed — reconstruction only, from immutable evidence.
Each oracle carries the full adversarial mutation matrix specified in §5/§6.

## 6. Merge-simulation & patch-identity method (§20)

Disposable clone only; live PR bases are never altered. With M0 = `main`, A = V2A head, B = V2B acceptance
head: build a true two-parent merge S1 = merge(A into M0) and verify `tree(S1) == tree(A)`; compute the
V2B patch `A..B` and verify patch identity as `S1...B`; build S2 = merge(B into S1) and verify
`tree(S2) == tree(B)`; verify every A and B commit is an ancestor of S2, with no duplicate/missing commits
and no squash/rebase dependency; run the full acceptance battery on S2; re-verify all frozen hashes and
sealed ledgers. Any tree-identity or patch-identity failure is a hard stop (no live merge is attempted).

## 7. Research-moratorium semantics (§10)

The legacy historical partitions (M3/V2A/V2B ETH+BTC history) are **closed to further candidate-nomination
research**. `research/v2/research_partition_closure.json` binds the partition identities, historical
experiments, cumulative family catalog, and negative-evidence index, with status
`closed_to_new_candidate_nomination_research`. Allowed: byte verification, historical replay, regression,
independent reconstruction, documentation, integrity hashing, compatibility testing, accepted-result
rendering, calculation-free recovery. Forbidden: evaluating a new/modified candidate, adding a primary
configuration, changing a threshold, opening a new budget on the closed partition, or claiming "freshness"
via a new version/benchmark/re-combination. Enforcement precedes candidate calculation, engine invocation,
a registry `started` append, and result publication, gated by an unforgeable `HistoricalReplayAuthorization`
constructible only by approved replay entry points. This is a **post-run** governance addition and is
documented as such; it does not claim to have existed before V2A/V2B execution.

## 8. Commercial-truth requirements (§14–§15)

Every buyer-facing or internal commercial statement must trace to structured evidence and reflect both
null results: two governed V2 programs completed, five V2 candidates evaluated, zero nominated, no
gate/holdout access, no forward record, no validated edge; offline platform only; no live adapter; buyer
interface is a reference boundary; no license; IP transferability unresolved; `sell_ready = false`. An
adversarial sales-material scanner fails on unsupported superlatives (proven/validated alpha, profitable,
market-beating, production/deployment/sell-ready, live-tested, out-of-sample-proven, guaranteed, low-risk),
except inside clearly-quoted false-claim examples. A forged result, removed limitation, or toggled field
must not be able to make `sell_ready` true.

## 9. Hard stops (§2)

Stop immediately, preserve evidence, and report if: any sealed row reaches a candidate/engine/metric/
report/new analysis; a sealed ledger changes; a V2A/V2B result or registry event changes; the BTC/ETH
frozen datasets drift; a candidate is re-executed or a new candidate is evaluated; a prior failed criterion
is reinterpreted; the cumulative family count is reduced; a rejected family is relabeled untested; a new
result is presented as out-of-sample; a merge simulation differs from the accepted branch tree; a deep
provenance forgery passes; the BTC-acquisition governance amendment cannot be reconciled with the final
no-write-workflow state; `sell_ready` becomes true; or a public-publication path appears. A Class-A
(scientific-integrity) or Class-D (sealed/governance) defect invalidates merge readiness.

## 10. Permitted fix classes (§1)

Result-neutral fixes only, and only if every immutable result and lifecycle hash is unchanged. Corrections
use a **new** verifier, a **new** generated summary, an **append-only** annotation, a **hash-bound**
erratum, or an **invalidation record** — never an in-place edit of an immutable report or result.

## 11. Terminal verdicts (§26 — exactly one)

- Accepted: `V2A–V2B STACK ACCEPTED FOR HUMAN MERGE REVIEW — TWO VALID GOVERNED NULL RESULTS; ZERO
  NOMINATED CANDIDATES; LEGACY RESEARCH PARTITIONS CLOSED; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT
  SELL-READY`.
- Result-invalidating defect: `V2A–V2B STACK REJECTED — SCIENTIFIC OR GOVERNANCE DEFECT; NO MERGE
  AUTHORIZED`.
- Merge topology / neutrality failure: `V2A–V2B STACK STOPPED — MERGE IDENTITY OR HISTORICAL-NEUTRALITY
  FAILURE`.

## 12. Absolute stop (§27)

At the terminal state both PRs stay open and draft; no merge, undraft, retarget, tag, release, LICENSE,
data acquisition, workflow activation, strategy evaluation, experiment-event append, new research budget,
gate/holdout access, prospective inspection, M3E activation, V2C start, branch deletion, or history
rewrite. The only next action, if accepted, is a **separately-authorized** human true-merge sequence
(merge #16 → verify → retarget #17 → verify patch identity → merge #17 → verify tree/replays/ledgers → no
tag). This document is committed before any substantive acceptance change.
