# Milestone 2B — Pre-Holdout Fortress, Provenance V2, and Scientific Decision Gate

> **Superseded in part.** This document records the pre-holdout fortress
> milestone as executed. The follow-up closure
> (`docs/M2B_FINAL_CLOSURE.md`) later replaced the additive
> `provenance_v2.json` anchor with the single `frozen_dossier.json` graph
> manifest (schema v3, verified semantically and enforced inside the
> production gate), corrected the commit terminology
> (`protocol_registration_commit_sha` = `b89627463775bf32698effb5adea1270a5927890`
> vs. the runtime `authorized_evaluation_code_commit_sha`), and executed
> the independent reacquisition audit-002. Where this file says a graph
> "authenticates" artifacts, read: hash-bound and tamper-evident within
> this repository — there is no signing key and no external attestation.


The real Coinbase ETH-USD dataset is frozen and independently replayable
(3702 gap-free daily candles, 2016-05-23 .. 2026-07-11, content fingerprint
`sha256:273f89eb…dd5718`). Before the one-time test holdout can ever be
opened, this milestone closes a set of trust-boundary defects, upgrades the
provenance chain to a single authenticated graph, machine-verifies the
earliest-continuous decision, hardens and then retires the acquisition
workflow, adds a shared read-only readiness preflight, and records the
scientific decision to reject the fixed SMA(20/50) specification without
consuming the test set.

The test set is **not** evaluated in this milestone. The append-only ledger
`research/m2b/test_evaluations.jsonl` stays byte-empty. No financial
parameter changes. Starting HEAD `15da401338a37037482575618bf1f068f8dd4b45`.

## Defect table

| id | severity | defect | reproduced |
| --- | --- | --- | --- |
| P0 | critical | Test access is consumed only for one exact `(dataset_lock_sha256, protocol_sha256)` pair, so a protocol/lock/version/schema/metadata change or a new evaluation id restores "freshness" — the same candles could be evaluated again. | `SAME_DATASET_DIFFERENT_PROTOCOL_SEEN_AS_CONSUMED = False` |
| P1 | high | The dataset lock does not authenticate the acquisition receipt or the dossier's provenance facts; `workflow_run_id`, `source_commit`, `curl_version`, `runner`, `user_agent`, and per-response `byte_length` can be forged while every replay/lock check stays true. | `FORGED_RECEIPT_ACCEPTED = True` |
| P2 | high | The acquisition sidecar is parsed with permissive `json.loads`, so a duplicate `http_code` key laundered a 500 into a 200. | `SIDECAR_DUP_KEY_LAST_WINS = 200` |
| P3 | high | The earliest-continuous start decision is a Markdown assertion, not machine-verified from the discovery raw bytes. | documented-only |
| P4 | high | The acquisition workflow checks out a moving branch ref while recording `github.sha`, computes an unused `head_before`, can overwrite an existing attempt directory, installs uv via mutable `curl | sh`, and keeps `contents: write` after the freeze. | inspection |
| P5 | high | The canonical `manifest`/`quality_report` JSON are not tracked, so the dossier's identity rests on regeneration alone with no committed byte anchor beyond the lock's hashes. | inspection |
| P6 | medium | There is no read-only readiness preflight sharing the evaluator's preparation; a real run's prerequisites cannot be verified without risking the holdout. | inspection |
| P7 | medium | The completed ledger event records only a single results hash; there is no result-bundle (JSON + Markdown) binding. | inspection |
| P8 | medium | Report wording ("SMA fails to generalize", percentage differences shown as `%`) overclaims and mislabels percentage-point gaps. | inspection |
| P9 | low | No recorded scientific decision governs whether the fixed SMA is promoted to the test set; the milestone-completion pressure itself is a risk to the holdout. | inspection |

## Threat model

A single researcher with full local write access and repository push rights,
who may (accidentally or under milestone pressure) try to: re-open the
consumed holdout by mutating non-test metadata; forge provenance facts shown
in the dossier; launder a bad acquisition response; move the start date to a
convenient value; overwrite frozen raw data; or tune the strategy after
seeing validation. Out of scope (documented, not defended): deliberate
in-memory monkeypatching of the running interpreter; remote/CI compromise;
concurrent independent clones; deliberate git history rewrites.

## Schema migrations (all strict, shared construct/parse invariant path)

- **LedgerEvent v2** — adds `holdout_id`, `test_content_fingerprint`,
  `runtime_contract_sha256`, `symbol`, `venue`, `candle_interval`,
  `test_row_count`, `results_json_sha256`, `report_markdown_sha256`,
  `result_bundle_sha256`. The production ledger is empty, so v2 is adopted
  before the first real event; there is no v1↔v2 migration of existing rows.
- **DatasetLock v2** — adds `selected_attempt_id`,
  `acquisition_request_plan_sha256`, `acquisition_receipt_sha256`,
  `raw_bundle_fingerprint`, `dataset_manifest_sha256`,
  `runtime_contract_sha256`, `holdout_identity_sha256`,
  `discovery_decision_sha256` on top of the v1 identity/hash fields.
- **BenchmarkProtocol v2** — binds the DatasetLock v2 hash plus the runtime,
  holdout, plan, receipt, evidence, raw-bundle, manifest, and quality hashes;
  the financial pins (buy-and-hold + SMA 20/50, 60/20/20, USD 10,000/segment,
  fee 0.001, slippage 0.0005, next-open, no forced liquidation, rf 0, metric
  set) are unchanged.
- **BenchmarkResults v2** — echoes the full provenance chain and the holdout
  identity; construction and parsing share all checks.

## Holdout identity design

`HoldoutIdentity` is a strict immutable model of *what the holdout is*: asset
identity, interval, dataset + test content fingerprints, test open bounds,
test row count, split semantics and fractions, and a fingerprint-algorithm
id. The **test content fingerprint** is domain-separated
(`eth-research holdout-v1\n` || canonical identity || canonical validated
test OHLCV) and is an **integrity** operation only: it may read/hash test
candle values but must never generate a signal, instantiate a test strategy,
run the engine, compute returns/P&L/metrics, plot, or expose test values.
The only permissible pre-authorization test outputs are the opaque
fingerprint, row count, first/last timestamp, interval, and identity.

## Provenance-v2 graph

One `verify_provenance_graph(...)` returns a structured result and always
runs the *complete* chain (no silently-optional partial checks):

```
request_plan ─┐
receipt ──────┼─▶ raw_bundle_fingerprint ─▶ evidence ─▶ derived CSV ─▶ manifest ─▶ quality
              │                                                            │
discovery_decision ───────────────────────────────────────────────────────┤
runtime_contract ──────────────────────────────────────────────────────────┤
                                                                            ▼
                                                              DatasetLock v2 ─▶ HoldoutIdentity
                                                                            │
                                                              Protocol v2 ◀──┘ ─▶ Results v2
```

Package version is threaded plan→receipt→evidence→lock→protocol→running, and
every cross-field equality in Section C6 is asserted. A raw-bundle
fingerprint (`eth-research raw-bundle-v1\n` over canonical
`ordinal|filename|byte_length|raw_sha256`) authenticates the exact raw files.

## Acquisition-workflow retirement design

The acquisition workflow is first hardened (SHA-pinned `astral-sh/setup-uv`,
checkout `${{ github.sha }}` with a HEAD assertion, refuse a pre-existing
attempt directory, no overwrite, no force push, artifact backup via a
SHA-pinned action, write permission only on the acquire job). After one
authorized **integrity-only** reacquisition (`coinbase-eth-usd-audit-002`,
unchanged plan) confirms the canonical candle content is bit-identical, the
write-capable, Coinbase-contacting workflow is **removed** from the final
tree (its history and run ids preserved in docs). Final-HEAD tests prove no
workflow has `contents: write` and no workflow can contact Coinbase; future
acquisition requires a new reviewed workflow commit.

## Real readiness-preflight design

`eth_research.test_readiness` / `preflight_authorized_benchmark(...)` shares
one preparation implementation with the authorized evaluator (28-step
sequence: repo/HEAD/source-binding/clean-tree/runtime/lockfiles → plan →
receipt → raw-bundle → evidence → discovery decision → attestation →
manifest → quality → dataset → lock v2 → holdout → protocol v2 → graph →
canonical ledger → strict history → no conflicting holdout → no existing
outputs → train/validation regeneration → split bounds → holdout fingerprint
→ fixed parameters). It runs entirely before any ledger mutation, emits only
safe integrity facts (never test prices/returns/signals/metrics), and is
proven — by instrumenting `Strategy.target_positions`, `run_backtest`,
`summarize`, the metric functions, and the renderer — to touch no test row
and leave the ledger/tree byte-identical. The real evaluator re-runs the
same preparation (never trusting a cached preflight object) before appending
`started`.

## Result-publication design

Completed events record `results_json_sha256`, `report_markdown_sha256`, and
a domain-separated `result_bundle_sha256` over both files. Publication
precomputes both byte blobs, publishes transactionally (Markdown then the
authoritative JSON), reads them back and verifies hashes/model agreement, and
only then appends `completed`; any failure after `started` leaves the holdout
consumed. `overwrite` never bypasses a consumed holdout.

## Scientific validation decision

A strict `ResearchDecision` records, with the decision criterion fixed before
any test access: SMA(20/50) `rejected_for_test_promotion` because it
materially underperformed buy-and-hold in validation; parameter changes made:
none; test accessed: false. The pre-registered protocol is preserved as an
honest record. Buy-and-hold is a benchmark, not an alpha claim. No parameter
search begins here. Report wording is corrected to "materially underperformed
buy-and-hold in the validation period" and percentage-point gaps are labelled
as such; all numbers are preserved bit-for-bit.

## Red-team plan

Attack holdout laundering (protocol/lock/schema/version/eval-id/wording
changes; overlap/containment/one-day/same-dates-different-venue;
started/failed/completed priors; second clone), provenance forgery (every
receipt field; reorder; duplicate ordinal; joint plan+receipt, raw+receipt,
evidence+lock, manifest+lock, runtime+protocol; discovery decision; alternate
canonical path), runtime/source (foreign checkout, site-packages, same
version/different code, shadow module, symlink, wrong patch/deps, modified
lockfiles, monkeypatch — documenting the in-memory limitation), test leakage
(context→train, row→strategy/engine, metric during preflight, renderer reads
test, exception logs test, warnings leak performance, helper evaluates all
splits, compat replay evaluates test), and workflow/publication (duplicate
sidecar keys, branch movement, attempt overwrite, partial commit, action-tag
substitution, mutable installer, output collision, write/rename/verify
failures, short write, second completion). Each new bug: failing test → root
cause → focused fix → re-gate → audit entry.

## Commit plan

1. Plan (this file). 2. Ledger consumption holdout-based. 3. Holdout identity
+ overlap protection. 4. Bind plan/receipt/raw-bundle. 5. Track
manifest/quality. 6. Lock+protocol v2. 7. Results+ledger publication v2.
8. Machine-verify discovery decision. 9. Strict sidecar. 10. Harden
acquisition workflow. 11. Independent integrity reacquisition. 12. Retire
write-capable workflow. 13. Shared readiness preflight. 14. Validation
rejection decision. 15. Percentage-point/wording fixes. 16. Red-team the
sealed boundary. 17. Docs + release-candidate status. No squash/amend/rebase/
force-push/merge/tag; bot acquisition commits preserved.

## Rollback behavior

Every publication/migration is transactional and offline: schema writes are
atomic; the reacquisition stages outside the tracked tree and publishes a
completeness marker last; a failed integrity comparison stops with the
discrepancy and never replaces canonical data; the ledger is never repaired.

## Milestone outcome (status)

| id | status | how |
| --- | --- | --- |
| P0 | closed | `HoldoutIdentity` + ledger v2 + `find_holdout_conflicts` (identity/dataset-fp/test-fp/overlap); legacy `(lock, protocol)` path removed. |
| P1 (receipt/graph) | closed | additive `provenance_v2.json` + `verify_provenance_graph` authenticates the receipt, raw-bundle fingerprint, and every artifact; forging any receipt field breaks the anchor. |
| P1 (discovery) | closed | `DiscoveryDecision` re-derived and verified from the raw discovery bytes; Markdown rendered from the model. |
| P1 (sidecar) | closed | strict `_SidecarRecord` via the shared decoder; dup-key/stringified/non-UTC/etc. rejected. |
| P1 (workflow) | closed (final closure) | write-capable workflow **retired** (F3). The integrity-only reacquisition (F2, `coinbase-eth-usd-audit-002`) was later **executed** through a temporary hardened one-shot GitHub Actions workflow — run 29206830064 — with a `canonical_content_match`; the temporary workflow was retired again immediately (see `docs/M2B_FINAL_CLOSURE.md` and `research/m2b/reacquisition_audit.json`). |
| P5 | closed | `dataset_manifest.json` + `quality_report.json` tracked as byte anchors bound to the lock. |
| P6 | closed | shared read-only `test_readiness` preflight; proven test-free and non-mutating. |
| P7 | closed | verify-after-publish before `completed`; overwrite never bypasses a consumed holdout; result-bundle hash. |
| P8 | closed | return-gap differences relabelled percentage points; numbers preserved bit-for-bit. |
| P9 | closed | strict `ResearchDecision`: SMA(20/50) `rejected_for_test_promotion`, `test_accessed=false`, parameter changes none. |

Two deliberate deviations from the sketched design, both keeping every gate
green: (1) provenance v2 is delivered as an **additive** graph anchor
(`provenance_v2.json` + `verify_provenance_graph`) rather than a
`DatasetLock`/`Protocol`/`Results` schema-version bump — it authenticates
the same facts (receipt, plan, raw-bundle, runtime, holdout, discovery,
manifest, quality, lock, protocol) and closes the forged-receipt exploit
without a destabilising cascade through the frozen committed artifacts;
(2) at the time of this milestone the acquisition workflow was retired
straight to its sealed end state and the reacquisition (F2) was recorded as
not performed. That deferral was based on an insufficient claim (direct
container egress denial), and the **final closure corrected it**: audit-002
was executed through GitHub Actions (run 29206830064) and matched the
canonical content bit-for-bit — see `docs/M2B_FINAL_CLOSURE.md`.

The one-time test set was **not** evaluated. Test execution is deferred
because validation already supplied enough evidence to reject the fixed
SMA(20/50) specification; the holdout stays sealed for genuinely new,
pre-registered, non-overlapping future research.

## Exact stop conditions

Stop and report (no test access, no overclaim) if: the starting state
differs; the reacquisition's canonical candle content differs from the
frozen dataset; raw aggregate would exceed the cap; a provenance-graph or
readiness check cannot be satisfied; or any gate/CI job is red. The milestone
ends at a **draft** PR with the holdout sealed and untouched; the one-time
test evaluation is deferred because validation already rejected the SMA
specification. Do not run the real test, merge, tag v0.3.0, or delete the
branch.
