# V2B Findings — the single governed cross-asset one-shot (v2b_run_001)

This document records the outcome of Milestone **V2B**'s one, pre-registered, governed cross-asset
research-train evaluation, the five-auditor post-run review, and the honest forward posture. It is a
scientific record, not marketing: it makes **no** out-of-sample, forward, walk-forward-live, or live
performance claim, and it is **not** an offer to sell. V2 remains `not_sell_ready`.

## 1. What was run

V2B continues the V2 roadmap on top of the **accepted V2A negative result** (V2A nominated no ETH-only
candidate; that null stands as immutable research evidence and was independently re-accepted by four
auditors in `docs/V2A_INDEPENDENT_ACCEPTANCE_AUDIT.md`). V2B did **not** retune a rejected V2A/M3C
candidate. Instead it introduced a genuinely **new information source** — historical **BTC-USD** daily
data restricted to the already-authorized research-train window — pre-registered **two** genuinely new
cross-asset candidate families, and accounted for **cumulative** family-wise multiplicity across every
prior family plus V2B.

The one-shot (`v2b_run_001`) was executed exactly once through the append-only, hash-chained registry,
following the pre-registration committed *before* the run:

- **E — source freeze** (CI green): the §26 five-auditor pre-registration red-team fixes were committed
  and all gates went green on the frozen tree before registration.
- **R — registration** (CI green): the single `registered` event was appended (seq 0), pinning the
  protocol identity `2bdf606e…` — which binds by SHA-256 the four frozen artifacts
  (`candidate_source_freeze.json`, `joint_partition_identity.json`, `execution_scenarios.json`,
  `research_multiplicity_state.json`), the fold structure (6 OOS folds, 150 warm-up rows), and the
  nomination constants — before any candidate was evaluated on the real joint partition.
- **P — execution**: `run_one_shot` built the firewalled joint ETH/BTC partition (2221 aligned daily
  opens, 2016-05-23 … 2022-06-21 UTC, combined fingerprint `6a37a95e…`), evaluated the two candidates
  plus the pre-registered benchmarks through the *reused, accepted* M4B portfolio engine over the
  walk-forward folds, cost scenarios, latency, sensitivity neighborhood, fold-stratified block bootstrap,
  block-level Monte-Carlo sign-flip, and the cumulative multiplicity correction, applied the mechanical
  decision rule, and published the immutable results bundle. The registry now records
  `registered → started → completed`; the one-shot budget is consumed and the run can never happen again.

Governed artifacts under `research/v2b/`: `v2b_research_protocol.json`, `v2b_one_shot_budget.json`,
`v2b_research_registry.jsonl`, `v2b_results.json` (fingerprint `d0b668f4…`), `v2b_results_manifest.json`,
plus the frozen partition/candidate/scenario/multiplicity identities and the two reproduced BTC
acquisitions (`research/v2b/btc/`, `research/v2b/raw/`).

## 2. Outcome — NO cross-asset candidate nominated

**`nominated_candidate_id = null`; `eligible_candidate_ids = []`. Both candidates are ineligible.**
Nominating nobody when neither candidate clears the pre-registered bar is a valid, successful outcome of
a pre-registered program — it is the honest answer the protocol was written to be able to give.

The pre-registered nomination rule requires a candidate to clear **all seven** gates. Each candidate
clears **only one** (the strict fold majority), so both rejections are over-determined — they do not hinge
on any single threshold, nor on the multiplicity correction, nor on the Monte-Carlo gate.

| candidate | folds beat (≥4/6) | primary point | primary 95% CI | primary lower >0 | stressed >0 | latency >0 | corrected lower >0 (α=0.005) | MC supports (p≤0.005) | sensitivity all >0 | eligible |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `cross_asset_btc_confirmed_eth_trend` | 4/6 ✓ | +0.000925 | [−0.000726, +0.002617] | ✗ | ✗ | ✗ | ✗ (−0.001285) | ✗ (p=0.140) | ✗ (0/9) | **false** |
| `cross_asset_eth_btc_relative_strength_rotation` | 4/6 ✓ | +0.000518 | [−0.001118, +0.002160] | ✗ | ✗ | ✗ | ✗ (−0.001616) | ✗ (p=0.268) | ✗ (0/3) | **false** |

Both candidates fail the **primary** gate (the uncorrected paired 95% bootstrap lower bound is below
zero), which is independent of the multiplicity correction and of the Monte-Carlo gate. The null even
survives the *most lenient* reasonable test: the uncorrected one-sided p-values are 0.141 and 0.270, both
far above 0.05. Both point estimates are weakly **positive** (+0.000925, +0.000518) — a
favorable-but-insignificant read, the opposite of what a suppressed real edge would look like. The
descriptive in-sample aggregate Sharpe values (1.857 and 1.565) are *not* decision inputs; they gate no
eligibility criterion and are reported for transparency only. The standing commercial posture remains
**`not_sell_ready`**.

## 3. Independent post-run review (five red-team auditors)

Five independent, read-only auditors reviewed the executed run from distinct adversarial lenses. **All
five found NO Class A (scientific/financial) and NO Class D (governance/sealed-partition) finding, and
none required a code fix.** Each independently reproduced the committed result and re-derived the decision.

- **A — firewall & data integrity:** re-derived the joint partition from committed bytes (2221 rows, last
  open == cutoff, greatest engine-visible timestamp `2022-06-21T23:00:00Z` < seal `2022-06-22T00:00:00Z`);
  scanned the raw BTC candle bytes directly (0 rows at/after cutoff in both acquisitions); confirmed the
  1-bar causal execution shift admits no look-ahead (an extreme final-bar perturbation leaves the executed
  path byte-identical); confirmed both candidates traded actively (no silent data flattening). NO Class A,
  NO Class D.
- **B — statistical & decision integrity:** recomputed every gate boolean from the committed CI bounds and
  p-values (all match); verified the §26 block-level Monte-Carlo sign-flip fix by exact 2^18 brute-force
  enumeration (the estimator agrees to sampling noise and cannot manufacture a false pass); confirmed the
  observed statistic is produced by the identical reduction as every permuted row (the ULP-dropout
  regression is closed); confirmed the NULL does **not** hinge on the MC or the correction. NO Class A, NO
  Class D.
- **C — governance / registry / one-shot integrity:** independently recomputed the protocol fingerprint
  `2bdf606e…`, all three chain entry-hashes, and the results fingerprint `d0b668f4…` from raw bytes with a
  stdlib-only script; demonstrated the budget cannot be consumed twice (a 2nd `started`, a 2nd
  `registered`, and a `started` without `registered` are all refused) and that **no**
  `reset`/`--force`/`repair`/`rollback` code path exists. NO Class A, NO Class D.
- **D — publication / results / reproducibility:** independently recomputed `sha256(v2b_results.json)` =
  `d0b668f4…` = manifest fingerprint = manifest sha256 = registry `completed` payload; confirmed the file
  is byte-canonical (idempotent under re-canonicalisation, no wall-clock); independently re-derived
  `eligible = false` for both candidates. CLEAN.
- **E — scope / commercial honesty / firewall:** observed all three sealed access ledgers byte-empty
  (`e3b0c442…`) and confirmed via `git log` that the V2B branch never wrote them; confirmed 108 changed
  files are all in-scope with no `LICENSE`, no new tag, no `main` change, and no `research/v2a` or
  M-series artifact change; confirmed `posture: not_sell_ready`, `sell_ready: false`. CLEAN.

### Class C / observational items (recorded; none invalidate the run, none applied retroactively)

The pre-registration, the protocol identity, and the published results are immutable, and the evaluation
source is frozen at the P commit (`00e75b7`). The two published artifacts (`v2b_results.json` and its
manifest) are bound by the `completed` event's fingerprint and therefore **cannot** be edited without
invalidating the run; several other items are parity with the accepted V2A baseline or pre-existing
frozen infrastructure. They are documented here rather than retro-fitted. Full detail and disposition
reasoning are in `docs/V2B_POSTRUN_REDTEAM.md`.

- **A-C1 — upstream ETH integrity-hash touches sealed *bytes* (not values).** The frozen M2/M3A loader
  `verify_dataset_integrity_only` reconstructs and content-hashes the whole committed ETH dataset (3702
  rows = 2221 research-train + 740 development-gate + 741 final-holdout) to prove the file is untampered,
  then returns **only** the 2221 research-train rows; `guard_research_train_frame` *rejects* (never
  truncates) any frame whose latest open exceeds the cutoff. No sealed row's market value reaches any
  candidate, benchmark, engine, statistic, gate, or the decision — verified independently (loader returns
  exactly 2221 rows, last open == cutoff). This is the pre-existing, accepted integrity design used
  identically by accepted-V2A; it is a Class-C tension with the literal "parsed/hashed" wording, **not**
  the operative Class-D condition (a sealed row reaching a research consumer), and is deliberately **not**
  modified (changing frozen accepted infrastructure is out of scope).
- **B-C1 — stressed/latency CI bounds not serialized.** The results bundle stores the stressed and latency
  gate booleans but not their underlying CI bounds; they are fully determined by the bit-for-bit
  reproduction and are monotone-consistent (a heavier cost or extra lag cannot raise the lower bound above
  the already-negative primary). Transparency note only.
- **B-C2 / C-C1..C4 — cosmetics.** Exact-float tie detection in `decide_nomination` (conservative
  direction, not exercised at 0 eligible); the registry timestamp validated as a non-empty string rather
  than a strict UTC timestamp (parity with the accepted V2A reader; this run's timestamps are well-formed
  ISO-8601 Z); a `_from_line` parameter-name shadow; identical `started`/`completed` timestamps (one
  `--timestamp` passed to both; no monotonicity invariant is claimed); a belt-and-suspenders sealed-ledger
  check. None affect chain, budget, firewall, or decision integrity.
- **D-C / E-C1 — descriptive Sharpe & docstring wording.** The in-sample aggregate Sharpe appears in the
  machine bundle without an inline caveat, but every gate/eligible flag in the same object is `false` and
  the verdict frames it correctly; the publication docstring says "atomic" for a durable staged-swap +
  self-verify + fail-closed-terminal mechanism. Documentation notes only.
- **E-C2 — pre-existing inert release machinery.** `release-dry-run.yml` / `private-release-build.yml` /
  `tools/release_evidence.py` exist from prior milestones and do not fire on this branch; V2B's only touch
  is adding `research/v2b/` to a drift-check *exclusion* list. Out of scope; not activated.

## 4. Limitations (read this before drawing any conclusion)

- This is a **research-train-only** result. It is **not** out-of-sample, **not** forward, **not**
  walk-forward-live, and **not** a live claim. The development-gate, final-holdout, M2B test, and M3D
  prospective partitions were never read; their access ledgers remain byte-empty.
- The evaluation is a cost-aware, bootstrapped, multiplicity-corrected, pre-registered read on a *single*
  historical joint partition of two instruments (ETH/USD + BTC/USD). A rejected candidate is not "proven
  to have no edge"; it simply did not clear a deliberately conservative, cumulatively-corrected,
  pre-committed bar on this partition.
- The family-wise correction (Holm–Bonferroni over the 10 enumerated families, per-family α = 0.005) does
  not eliminate researcher degrees of freedom (choice of families, features, transforms), never resets
  across versions/instruments/benchmarks, and corrects only the primary nomination verdict — diagnostics
  report unadjusted intervals.
- No candidate was promoted, and nothing here changes the standing posture: **V2 is `not_sell_ready`.**

## 5. Forward posture and proposal

Because no candidate was nominated, there is nothing to hand to an independent development-gate review,
and the sealed partitions remain untouched — as they must, since a development-gate/holdout read is earned
only by a research-stage-supported candidate. The honest forward options, none of which are taken here
(they are future, separately-governed work):

1. **Design and pre-register new candidate families** under a fresh one-shot budget. The two V2B families
   (BTC-confirmed ETH trend exposure; ETH/BTC/cash long-only relative-strength rotation) are simple,
   long-only, unlevered cross-asset baselines; neither cleared the bar. New hypotheses need their own
   pre-registration and their own governed run — and, critically, the **cumulative** multiplicity budget
   still applies (it does not reset), so each additional family makes the bar stricter, not looser.
2. **Keep V2 `not_sell_ready`.** With no research-stage-supported candidate, there is no evidentiary basis
   to move the commercial posture. The buyer-evaluation boundary and the signal-only shadow platform stand
   as *capability* evidence, not as a performance claim.
3. **Do not touch the sealed partitions.** The development-gate, final-holdout, and prospective partitions
   stay sealed; they are not a retry mechanism and are not consumed by a null result.

## 6. Reproducibility

`v2b_results.json` reproduces byte-for-byte from the frozen source and the authorized joint partition
(`results_fingerprint = d0b668f45c9e1f6adfeb606e16003a4bd5649d39bb0676a444cb691ec9fe6f1f`). A **fresh
`git clone`** at the branch tip replays clean: `python -m eth_research.v2b.replay --check` prints
"V2B replay OK", `python -m eth_research.v2b.governance --repo-root .` returns `{"ok": true, "problems":
[]}`, the append-only registry chain recomputes end-to-end (`registered → started → completed`, exactly
one of each), the `completed` payload binds `d0b668f4…`, the three sealed ledgers are byte-empty, and the
full V2B test suite passes (164 tests). The read-only `v2b-replay.yml` workflow runs the same verifiers on
every push (SHA-pinned checkout, `contents: read`, no secrets) and is green on both the R and P tips; CI
additionally runs the suite on CPython 3.12 and 3.13 plus the authoritative 3.12.3.
