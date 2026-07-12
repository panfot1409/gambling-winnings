# Milestone 2B — Absolute Final Fortress Closure

Starting HEAD `8fc1cad89f0bc8533644150c17e7c35ce55e606f`; draft PR #3 open.
The one-time test ledger stays byte-empty throughout (0 bytes, SHA-256
`e3b0c442…b7852b855`). Permitted holdout operations remain integrity-only
(schema validation, mechanical splitting, counts/bounds, opaque
domain-separated fingerprints, provenance comparison); no strategy, signal,
backtest, fill, return, metric, plot, or price summary may touch the test
segment, and a spy proves no test row reaches the engine.

## Defect reproductions (executed against starting HEAD)

| id | defect | executed evidence |
| --- | --- | --- |
| B1 | `verify_provenance_graph` is not a production gate: `evaluation.py` never references it. | On a committed synthetic repo with a **forged receipt**, the graph verifier fails (cannot even load an anchor) yet `_run_bound_benchmark` appended `started`+`completed` and evaluated test rows (spies on `append_event`/`run_backtest`; max engine bar = the synthetic test end). |
| B2 | Readiness and production assemble their checks independently and disagree. | Divergence table: provenance graph — readiness ✅ / production ❌; holdout recomputation — neither; decision consultation — neither. Current readiness reports `ready: true` on the real repo although the committed decision is `rejected_for_test_promotion`. |
| B3 | The graph hashes `holdout_identity.json` but never recomputes it from the verified dataset+protocol. | Forged `test_content_fingerprint` (bounds unchanged) + regenerated anchor → `verify_provenance_graph(...).ok == True`. |
| B4 | The scientific rejection is not enforced operationally. | The synthetic production run above consulted **no** `ResearchDecision` anywhere; a valid authorization proceeds to `started` regardless of the committed rejection. |
| B5 | The graph overclaims completeness: `train_validation_results.json`, `train_validation_report.md`, `validation_decision.json`/`.md`, and the discovery plan/receipt/raw chain are not bound. | Mutated train/val results + decision in a clone → `graph.ok == True`. |
| B6 | Terminology: the evaluator labels the execution-time HEAD `pre_registered_commit_sha`; the actual protocol-registration commit is `b89627463775bf32698effb5adea1270a5927890`. A commit chosen at execution time is an authorized evaluation code revision, not a registration revision. | Field inspection of `BenchmarkResults`/renderer/ledger. |
| B7 | Independent reacquisition was not *attempted*: direct container egress is denied, but GitHub Actions reached Coinbase in runs 29180702904 and 29180786118, so container denial is not evidence Actions cannot. | Recorded; audit-002 is attempted through Actions in this milestone. |

## Target architecture

One side-effect-free preparation function,
`prepare_authorized_evaluation(...)`, becomes the **sole** implementation of
every pre-ledger verification. It returns a frozen `PreparedEvaluation`
context (verified models, hashes, recomputed holdout identity, conflict
results, scientific eligibility). `run_authorized_benchmark` and the
readiness command both call exactly this function; readiness in read-only
mode never appends or publishes. Production-only, after preparation:
confirm the explicit token, confirm scientific eligibility, append
`started`, and only then let any test signal exist.

The additive provenance-v2 anchor is superseded by one strict
`FrozenResearchDossier` manifest (provenance schema v3, no second competing
graph file) binding the discovery chain (plan/receipt/raw fingerprint/
decision JSON+MD), the primary acquisition chain, the independent audit
acquisition (explicit status object until audit-002 lands, then the full
record), the dataset chain (derived SHA, fingerprint, manifest, quality,
lock), runtime/protocol (+ the protocol-registration commit identity), and
the holdout/development evidence (holdout identity, train/val results +
report, decision JSON+MD). The verifier checks graph semantics, not just
hashes — including recomputing the holdout identity from the verified
dataset+protocol and requiring exact byte equality with the committed file,
regenerating train/val results/report/decision and requiring byte equality,
and re-verifying the discovery decision from raw. Evidence is described as
hash-bound / tamper-evident, never "cryptographically authenticated".

The empty ledger migrates to schema v3, adding `frozen_dossier_sha256`,
`holdout_identity_sha256`, `validation_decision_sha256`,
`train_validation_results_sha256`, `protocol_registration_commit_sha`, and
`authorized_evaluation_code_commit_sha` (replacing `code_commit_sha`).
Results rename `pre_registered_commit_sha` →
`protocol_registration_commit_sha` and add a nullable
`authorized_evaluation_code_commit_sha` (required iff test segments exist);
train/validation numerical values are preserved bit-for-bit.

## Exact invariants

1. Production and readiness share one preparation path; a check added to it
   affects both (architectural test).
2. A forged receipt (or any dossier artifact mutation) stops the production
   evaluator before any ledger append.
3. The committed holdout identity must recompute exactly from the verified
   dataset + protocol (byte equality).
4. `rejected_for_test_promotion` makes production refuse before any ledger
   append, strategy, signal, or backtest — even with a valid authorization.
5. Rebuilding the decision from the committed results reproduces the
   committed bytes exactly and remains rejected; editing `rejected` →
   `eligible` breaks byte-equality and derivation determinism.
6. Readiness reports the honest split state: `integrity_ready: true`,
   `holdout_fresh: true`, `promotion_decision: rejected_for_test_promotion`,
   `promotion_eligible: false`, `authorized_test_ready: false` — and CI
   treats that as success, not breakage.
7. The ledger stays 0 bytes / 0 events / empty SHA at every commit.
8. Canonical dataset bytes, fingerprints, and train/validation numbers never
   change.

## Test plan

Failing-first regression tests for every defect above (red forms executed
against starting HEAD, recorded here; committed together with each fix,
unweakened): production-refuses-forged-receipt; production-refuses-rejected-
decision before `started` with ledger byte-identical and zero
strategy/engine construction (spies); architectural shared-gate test;
holdout-recomputation mismatch tests (fingerprint, row count, bounds,
fractions, interval, venue/symbol, modified synthetic test candle);
dossier-completeness mutation tests for every newly bound artifact; ledger
v3 construct/parse/sequence tests; eligible-fixture guarded path still
reaches `started`→`completed` (proving the gate keys on the decision).
The synthetic fixture gains a complete dossier (plan, receipt, plan-named
raw bodies, discovery chain, manifest/quality anchors, holdout identity,
train/val results+report, derived decision, dossier manifest) with an
`eligible` variant (validation downtrend ⇒ SMA ≥ buy-and-hold) for
post-authorization machinery tests and the default-derived `rejected`
variant for refusal tests.

## Reacquisition design (audit-002)

One temporary, narrowly scoped GitHub Actions workflow performs a single
integrity-only reacquisition, `attempt_id = coinbase-eth-usd-audit-002`,
from the unchanged canonical request plan. Threat model and controls:
exact repo+branch guards; push-bootstrap trigger restricted to one
committed trigger path; concurrency group; `contents: write` on the single
acquisition job only; no PR trigger, secrets, or exchange credentials; the
one public candles endpoint host/path only; SHA-pinned actions; no
`curl | sh` (uv is fetched as a version-pinned artifact, verified, and
executed — or the job fails); checkout of the exact triggering
`github.sha` with an asserted HEAD equality; refusal of a pre-existing
attempt directory; staging in `$RUNNER_TEMP` with offline strict validation
(sidecars via the strict decoder) before publication; per-body and
aggregate caps; a pre-push assertion that the remote branch still equals
the triggering SHA; an exact staged-path allowlist inspected before the bot
commit; fast-forward push only; bodies never logged. Comparison policy:
raw bytes may differ; canonical parsed OHLCV content must be bit-identical
(`canonical_content_match` enum) — any difference stops the milestone,
replaces nothing, and is reported as timestamps/fields only. On success a
strict `reacquisition_audit.json` binds both plan/receipt/raw-bundle
hashes, derived CSV hashes, content fingerprints, row counts and bounds,
the run id and source commit, and the explicit statement that canonical
data was not replaced; the dossier manifest then binds the audit chain and
the temporary workflow + trigger are removed again (retirement re-asserted
by tests). If Actions genuinely cannot reach Coinbase, the failing run URL
and step are recorded instead — no bare container-egress claim.

## Commit plan

1 plan (this file) · 2 shared preparation path + fixture dossier overhaul ·
3 scientific eligibility fail-closed (+ readiness states) · 4 terminology
(results v2) · 5 ledger v3 · 6 FrozenResearchDossier manifest + verifier ·
7 red-team extension · 8 audit-002 workflow + trigger · 9 (bot) audit raw ·
10 comparison artifact + dossier binding · 11 retire workflow again ·
12 docs + PR body. Small commits; no amend/squash/rebase/force-push/merge/
tag; intermediate safe checkpoints pushed (never while the acquisition
workflow may be pushing).

## Stop conditions

Stop immediately, without test access, if: the starting state differs;
audit-002 canonical content differs; the complete dossier cannot verify;
the committed holdout identity does not recompute exactly; any test row
reaches a strategy or engine; the ledger changes; any gate or final CI
stays red. Never: run the real authorized benchmark, override the rejected
decision, generate a test report, tune parameters, replace canonical data,
merge PR #3, mark it ready for review, or tag v0.3.0.
