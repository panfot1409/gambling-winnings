# V2A Findings — the single governed one-shot (run_001)

This document records the outcome of the V2A commercial-evidence research program's one, pre-registered,
governed research-train evaluation, the post-run independent review, and the honest forward posture.
It is scientific record, not marketing: it makes **no** out-of-sample, forward, or live performance
claim, and it is **not** an offer to sell.

## 1. What was run

The V2A one-shot (`run_001`) was executed exactly once through the append-only, hash-chained registry,
following the pre-registration committed *before* the run:

- **E — source freeze** (CI green): all gates green on the frozen tree.
- **R — registration** (CI green, pristine): `research/v2a/pre_registration.json` committed, pinning by
  fingerprint the protocol, the three candidate specifications, the constitution, the one-shot budget,
  and the buyer contract — before any candidate was evaluated on the real partition.
- **P — execution**: `run_one_shot` loaded the firewalled research-train (2221 rows, 2016-05-23 …
  2022-06-21 UTC, content fingerprint `sha256:60aa988e…`), evaluated the three candidates plus the
  passive buy-and-hold benchmark through the *reused, accepted* fractional engine over the pre-registered
  walk-forward folds and cost scenarios, applied the mechanical decision rule, and published immutable
  results. The registry now records `genesis → started → completed`; the one-shot budget is consumed and
  the run can never happen again.

Governed artifacts under `research/v2a/`: `pre_registration.json`, `research_registry.jsonl`,
`results.json` (fingerprint `6327de21…`), `results_manifest.json`.

## 2. Outcome — NO candidate nominated

**`nominated_candidate_id = null`. All three candidates are `research_stage_rejected`.** Rejecting every
candidate when none clears the pre-registered bar is a valid, successful outcome of a pre-registered
program — it is the honest answer the protocol was written to be able to give.

The pre-registered `NominationCriteria` require **all** of: (i) beat the benchmark in ≥ 3 of the 5 OOS
folds; (ii) the fold-stratified 95% bootstrap of paired log-excess return has its lower bound above 0;
(iii) that lower-bound criterion also holds under the stressed cost scenario; (iv) annualized Sharpe > 0.

| candidate | folds beat (need ≥3) | primary point | primary 95% CI | primary lower >0 | stressed robust | Sharpe >0 | status |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|--------|
| `meanrev_zscore_accumulation`   | 2/5 ✗ | −0.001581 | [−0.003952, +0.000789] | ✗ | ✗ | ✓ | research_stage_rejected |
| `vol_scaled_hold_drawdown_guard`| 2/5 ✗ | −0.000396 | [−0.002253, +0.001564] | ✗ | ✗ | ✓ | research_stage_rejected |
| `trend_regime_single_horizon`   | 2/5 ✗ | +0.000145 | [−0.001291, +0.001639] | ✗ | ✗ | ✓ | research_stage_rejected |

Each candidate **fails 3 of the 4 criteria** (it passes only positive Sharpe), so the rejection is
over-determined: it does not hinge on any single threshold. Even `trend_regime_single_horizon` — the only
candidate with a positive primary point estimate and the highest aggregate Sharpe (1.09) — fails on folds
(2/5), on the primary CI lower bound (below 0), and on stressed robustness. The standing commercial
posture remains **`not_sell_ready`**.

## 3. Independent post-run review (four red-team auditors)

Four independent, read-only auditors reviewed the executed run from distinct lenses. **All four found NO
Class A (scientific/financial) and NO Class D (governance/sealed-partition) finding, and required no fix.**

- **Scientific integrity** — the run honored the pre-registration exactly (every fingerprint matches);
  the no-nomination outcome is mechanically correct, confirmed three ways (by-hand criteria application,
  re-running `decide()`, and a full byte-exact re-evaluation from the real research-train); the reused
  bootstrap is deterministic and drawn within-fold; the stressed scenario is genuinely more punitive; no
  look-ahead / peeking / snooping channel exists (candidates, seed, and rule are all pre-registered and
  fingerprint-pinned).
- **Governance / one-shot budget** — the registry is a sound append-only hash chain; the budget is
  consumed and irreversible (a second `started` is empirically refused through every path); lifecycle is
  enforced on both append and read; the `completed` event binds the exact published fingerprint.
- **Sealed-partition firewall** — the three sealed access ledgers are byte-empty
  (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`); the run read only research-train;
  the development-gate and final-holdout partitions (and the M3D prospective cohort) are structurally
  unreachable from the evaluation path.
- **Reproducibility / publication** — `results.json` is strict canonical (no wall-clock), the manifest
  and registry bind it correctly, it matches the pre-registration fingerprint-for-fingerprint, and a pure
  deterministic recompute reproduces `6327de21…` **byte-for-byte** with no side effects.

### Class C / observational items (recorded; none invalidate the run, none applied retroactively)

The pre-registration and results are immutable and the evaluation source is frozen at the P commit, so
these are documented rather than retro-fitted:

- **C1 — walk-forward traceability.** The walk-forward protocol
  (`research/m3a/walk_forward_protocol.json`) is bound to the V2A governance chain only *transitively* (no
  explicit WF fingerprint field in the pre-registration). This is **not exploitable**: the protocol pins
  rows = 2221 and folds = 5, `WalkForwardProtocol` mechanically forces the unique expanding structure,
  each fold's OOS timestamps are cross-checked against the fingerprinted research-train, and the WF file
  itself pins `research_train_content_fingerprint = 60aa988e…`. Exactly one valid WF protocol exists for
  this data. A future run should pin an explicit WF fingerprint in the pre-registration for *direct*
  traceability.
- **C2 — aggregate Sharpe across fold seams (disclosed, non-pivotal).** `aggregate_sharpe` concatenates
  per-fold marked returns across independent-cash folds, ignoring seams. It gates only `positive_sharpe`,
  which all three candidates pass — so it is not decision-pivotal here (they are rejected on the other
  three criteria).
- **C3 — cosmetic.** One bare `assert isinstance(...)` type guard in `decision.py` (stripped under
  `python -O`); the caller always passes the correct type.
- **Dead artifact.** `research/m3a/walk_forward_protocol_v2.json` (`folds=[]`) is an unused M3A-era
  artifact; the V2A orchestrator loads `walk_forward_protocol.json` and never references `_v2`.

## 4. Limitations (read this before drawing any conclusion)

- This is a **research-train-only** result. It is **not** out-of-sample, **not** forward, and **not** a
  live claim. The development-gate and final-holdout partitions were never read.
- The evaluation is a cost-aware, bootstrapped, pre-registered read on a *single* historical partition of
  one instrument (ETH/USD). A rejected candidate is not "proven to have no edge"; it simply did not clear
  a deliberately conservative, pre-committed bar on this partition.
- No candidate was promoted, and nothing here changes the standing posture: **V2 is `not_sell_ready`.**

## 5. Forward posture and proposal

Because no candidate was nominated, there is nothing to hand to an independent development-gate review,
and the sealed partitions remain untouched — as they must, since a development-gate/holdout read is
earned only by a research-stage-supported candidate. The honest forward options, none of which are taken
here (they are future, separately-governed work):

1. **Design and pre-register new candidate families** under a fresh one-shot budget. The current families
   (mean-reversion z-score, always-long vol-scaled with a drawdown guard, single-horizon trend gate) are
   simple, long-only, unlevered baselines; none cleared the bar. New hypotheses would need their own
   pre-registration and their own governed run — the research-train budget discipline (M3D) still applies.
2. **Keep V2 `not_sell_ready`.** With no research-stage-supported candidate, there is no evidentiary basis
   to move the commercial posture. The buyer-evaluation boundary (contract, redacted diligence bundle,
   fail-closed gateway) and the signal-only shadow platform stand as *capability* evidence, not as a
   performance claim.
3. **Do not touch the sealed partitions.** The development-gate and final-holdout partitions stay sealed;
   they are not a retry mechanism and are not consumed by a null result.

## 6. Reproducibility

`results.json` reproduces byte-for-byte from the frozen source and the authorized research-train
(`results_fingerprint = 6327de21759c21a97c8b1ee9c14782bb36534c8d968d6792eba54b7c9c58cbca`). The offline
verifier `python -m eth_research.v2.replay --check` replays the whole stack clean: the design-invariant
fingerprints round-trip, the pre-registration matches the frozen source, the registry chain is sound and
within its one-shot budget, the published results match the pre-registration fingerprint-for-fingerprint,
and the three sealed ledgers are byte-empty. The `v2a-replay` workflow runs the same verifier on every
push (SHA-pinned checkout, `contents: read`, no secrets), and the results are cross-runtime reproducible
(CI runs the suite on CPython 3.12 and 3.13 plus the authoritative 3.12.3).
