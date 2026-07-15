# Milestone 3C — pre-registration red-team bug log

Three independent adversarial auditors reviewed the frozen M3C code **before** the
single-use experiment id `m3c-dual-horizon-trend-v1-run-001` was consumed. Each was
read-only, confirmed hypotheses against throwaway temp directories, and never
touched the real research tree, ledgers, registry, or git. This log records every
finding and its disposition.

Overall: **no CRITICAL or HIGH code defect** was found. The statistics/causality
layer and the core provenance machinery were confirmed sound by execution. Four
genuine hardening items (one decision-layer, three provenance-layer) were fixed;
the remainder are documented, pre-registered design choices or the accepted
git-anchored threat model.

## Auditor A — statistics, causality, determinism

**Verdict: no genuine defect in any of six attack categories; all CONFIRMED sound.**

- Look-ahead / causality — SOUND. `DualHorizonTrend` sets `target[t]` from
  `close[t]/close[t-63]` and `close[t]/close[t-252]`; warm-up (`t<252`) flat;
  mutating a future close changed only targets at indices `>= k`; the engine
  executes `signals[t-1]` at `open[t]` (decision at close `t` → fill at open `t+1`);
  the volatility overlay uses only closes through `t-1`.
- Fold-seam bootstrap — SOUND. No block crosses a fold seam (verified with distinct
  per-fold constants: every resample mean equals the exact pooled mean); circular
  moving-block indexing correct; per-fold observation count preserved; per-day
  pooled weighting matches the method note; `block_length = floor(n**(1/3))`
  verified exact for all `n` in `[1, 100000]` including every exact cube.
- Determinism — SOUND. Byte-reproducible; strict `(fold, timestamp)` pairing, never
  positional; `paired_log_excess` rejects non-finite and `<= -1`.
- PSR — SOUND. Recomputed independently to 0.0 difference; faithful to Bailey &
  López de Prado (2012); zero-variance rejected; denominator floored.
- Trace commitment — SOUND. Binds all 20 `BarRecord` fields; deterministic; a 1e-9
  equity change flips the digest; no collision path.
- 252-bar context — SOUND. Exactly 252 rows immediately before OOS, strictly in the
  past, identical for all five strategies; research-train only.

Documented non-defects (pre-registered methodology, not bugs): the candidate is
structurally flat on OOS day 0 of each fold (causally correct; ~5 of 1126 days);
calendar-consecutive folds ignore cross-seam serial dependence at 4 boundaries
(pre-committed in the method note §2); the PSR moment convention matches the note;
and cross-version reproducibility, verified on 3.12, is exercised on **both** 3.12
and 3.13 by the `m3c-replay` CI matrix.

**Action: none required.**

## Auditor B — decision, results, report

**Verdict: mechanically sound and scientifically honest; no CRITICAL/HIGH.**

Confirmed CLEAN: the P3 drawdown direction (candidate signed median `>=` B&H, i.e.
no deeper — no sign error); the additive cost decomposition and the exact
`compatibility_v1` split (spread and impact = 0); grid completeness and exact
aggregate re-derivation; paired-comparison consistency and the bootstrap
observation-count binding; and report honesty (no overclaiming words on either the
eligible or rejected path, every losing fold retained, deterministic).

- **B1 (MEDIUM) — FIXED.** `render_m3c_report` printed `decision.results_sha256` as
  the "committed results digest" without confirming the decision was derived from
  the results being rendered, so a mismatched (results, decision) pair could render
  a misleading report. **Fix:** `render_m3c_report` now refuses a decision whose
  `results_sha256` / `protocol_sha256` do not match the results (commit `9a2265a`,
  test `test_report_rejects_a_decision_not_coupled_to_the_results`). Defense in
  depth beyond the replay verifier, which already re-derives and re-renders.
- **B2 (LOW) — accepted.** `CandidateDecision` parse re-checks only internal
  consistency (outcome == all criteria pass), not re-derivation from results (it has
  no results at parse time). The trust boundary `rederive_committed_decision`
  re-runs the frozen rule and requires byte-equality in the replay CI, so a forged
  decision is caught before merge.
- **B3–B7 (LOW / informational) — accepted.** P5/P7 are structurally always-true for
  any valid `M3CResults` (documented; only P1/P2/P3/P4/P6 discriminate); P5 scopes to
  the causal scenarios (grid validation already guarantees positive terminal equity
  for the compat cells); `average_requested_exposure` is the risk-approved target
  (JSON diagnostic only, not a decision input); the report restates the frozen
  `2221`-row partition (a restatement of the sealed definition, mirroring M3B); and
  the `compatibility_v1` impact term may be a ~1e-12 float-noise residual that rounds
  to `0.00` (within tolerance).

## Auditor C — provenance and lifecycle

**Verdict: the core machinery is genuinely fail-closed and tamper-evident** (hash
chain, single-use lifecycle, sealed-ledger/source binding, crash-recovery ordering,
and rollback-safe publication all CONFIRMED by execution). Three checkpoint-binding
weaknesses were fixed; the freeze step was the expected operational next step.

- **H1 (HIGH) — resolved operationally.** The freeze outputs (`protocol.json` + the
  empty `experiment_registry.jsonl`) were not yet committed, so `m3c-replay` was red
  and `register` could not run. This is the code-freeze E step, performed after the
  red team cleared (see the freeze commit); not a logic defect.
- **M1 (MEDIUM) — FIXED.** The registered checkpoint re-checked protocol/lineage/
  budget digests but not the development partition or frozen dossier, so a stale or
  tampered partition could ride a green `registered` checkpoint. **Fix:**
  `_require_registration_binds_inputs` now binds all five recorded inputs (commit
  `1a2a933`).
- **M2 (MEDIUM) — FIXED.** The completed checkpoint never re-bound lineage/budget/
  protocol files to the recorded digests (they were pulled from the registered
  event, not re-read), so they could be edited post-completion with CI green.
  **Fix:** `verify_published_run` now re-binds all five inputs
  (`committed_inputs_match_registration`, commit `1a2a933`); partition and dossier
  are additionally re-derived by the offline dataset reconstruction.
- **M3 (MEDIUM) — FIXED.** An honestly-recorded `failed` terminal state was rejected
  by the tri-state as "mid-lifecycle", which would brick CI red with a spent id.
  **Fix:** `check_replay` now accepts `registered → started → failed` as a real,
  green committed checkpoint with no artifacts (commit `1a2a933`,
  `test_failed_is_a_green_committed_checkpoint`).
- **L1 (LOW) — accepted.** `recovery.finalize` finalizes on the intent's
  cross-binding + artifact presence, not a full `verify_published_run` (which cannot
  run before the `completed` event exists). The calculation-free contract is the
  point; full archive verification runs in CI after the append. A tampered intent
  requires local write access and only bricks the id (loud), never produces a green
  fraud.
- **L2 (LOW) — accepted (threat model).** The hash chain is re-forgeable with
  registry write access; tamper-evidence rests on the git-committed history as the
  external anchor, exactly as `gitcheck` documents. Within a committed state the
  chain is tight (single-byte edits, truncation, duplicate/out-of-order/identity
  drift all detected).
- **L3 (LOW) — accepted (fail-closed).** A hard crash between the `started` append
  and a completed publish leaves `[registered, started]` with no liveness recovery;
  `execute` refuses any non-`[registered]` state. This is deliberate fail-closed
  behavior; the recovery finalizer covers only a fully-published crash. With M3, an
  operator can instead record `failed` to reach a green terminal state.

## Post-fix verification

After applying B1 and M1/M2/M3: `ruff` + `mypy` clean across the M3C package; the
full M3C test suite is green (including the new coupling and replay tests); and the
disposable-clone end-to-end rehearsal reproduces the run byte-for-byte with
`verify_archive --deep` reporting 14 checks. The candidate's mechanical outcome is
unchanged and honest: `rejected_for_development_gate_promotion`.

## Post-run finding — cross-machine transcendental reproducibility (fixed)

**Discovered after publication**, when `m3c-replay` went red on the `completed`
checkpoint while every local check — a fresh, CI-identical clone included — stayed
green.

- **Symptom.** `replay --check` reproduced the committed `candidate_results.json`
  byte-for-byte on the execution host but not on the GitHub runners. The freeze
  (pristine) and register (registered) checkpoints, which reproduce nothing, stayed
  green; only the `completed` checkpoint — the one that rebuilds results from raw
  data — failed, on all three runners (authoritative 3.12.3 and compat 3.12 / 3.13).
- **Root cause (portable-FP property, not a defect).** IEEE-754 does not mandate
  correctly-rounded transcendentals, so `np.log1p`, integer powers, and `math.erf`
  legitimately differ by a last ULP across libm builds / CPU microarchitectures.
  Ruled out as causes, each byte-identical locally: SIMD dispatch
  (`NPY_DISABLE_CPU_FEATURES`), `PYTHONHASHSEED`, and interpreter version; the
  numerical stack is lockfile-pinned. The shared M3B engine reproduces byte-for-byte
  on the same runners (green `m3b-replay`), which localises the drift to exactly the
  four M3C-new statistical scalars that carry a transcendental — the fold-seam-aware
  bootstrap interval, the per-fold paired daily log-excess, and the descriptive PSR.
- **Fix (no re-execution; the single-use id stays spent).** `check_replay` now
  compares the raw-data rebuild to the committed results field by field: every
  financial, structural, provenance, and cost field must be **byte-for-byte**; the
  named statistical scalars must agree to `1e-9` relative (with a `1e-12` absolute
  floor); and **any** other difference — or a statistical scalar beyond tolerance —
  fails closed with the offending fields listed as a CI annotation. The reproduction
  must additionally re-derive the **identical mechanical verdict** (the same
  per-criterion pass/fail vector), proving the tolerated drift cannot move a
  promotion criterion. The decision and report still reproduce byte-for-byte (they
  read the committed results and print statistics at `.6g`), and the execution-host
  P6 determinism gate still demands bit-identical output. See
  `docs/M3C_STATISTICAL_METHOD_NOTE.md` §8, `tests/test_m3c_replay.py`
  (`test_reproduction_*`), and the corrected reproducibility wording across the
  findings, terminal audit, README, and CI comment.
- **Outcome unchanged.** The mechanical verdict is still
  `rejected_for_development_gate_promotion`; the observed cross-host drift is ~`1e-13`
  relative, ~10 orders of magnitude from flipping P1's sign.

## Independent acceptance — numerical replay-contract closure

A later independent-acceptance pass audited the post-run fix above and found the
`math.isclose(rel_tol=1e-9, abs_tol=1e-12)` gate — while directionally right — far too
loose and imprecise. Six defects (N1–N6) were reproduced with tests, then fixed by the
exact bounded-binary64-ULP contract (`eth_research.m3c.numerics`, commit `e699688`; the
1e-9 gate described in the previous section is **superseded**).

- **N1 (MEDIUM) — FIXED.** The docs said "four named scalars"; the predicate actually
  admitted **12** leaves for the five-fold result (7 fixed + 5 per-fold means).
  *Fix:* an exactly-enumerated allowlist; `test_allowlist_is_structurally_exact`.
- **N2 (HIGH) — FIXED.** `isclose(1e-9, 1e-12)` was not a last-ULP bound: reproduced
  with tests to admit **36,893,488 ULPs** around `point_estimate` and **8,945,706**
  around the fold-0 mean; a 1,000,000-ULP mutation classified as tolerated. *Fix:* an
  exact integer ULP distance with `MAX_REPLAY_ULPS = 8`; `test_same_relative_delta_but_
  millions_of_ulps_is_hard`, `test_exactly_cap_plus_one_is_hard`.
- **N3 (MEDIUM) — FIXED.** The fold predicate matched any list index (fold 5, 99, …),
  not only 0..4. *Fix:* the allowlist enumerates `paired_comparisons[0..OOS_FOLD_COUNT-1]`
  exactly; `test_classifier_hard_fails_every_non_approved_mutation[fold-index-5]`.
- **N4 (LOW) — FIXED.** The docs conflated transcendentals (`log1p`, `erf`) with integer
  powers (not transcendental) and percentile interpolation / reductions (which only
  propagate the upstream variation). *Fix:* corrected §8 and the module docstrings.
- **N5 (LOW) — FIXED.** Comparing a "1e-9 relative tolerance" to the *magnitude* of the
  P1 threshold was dimensionally meaningless. *Fix:* removed; acceptance is now an
  integer ULP cap, and the decision's robustness is stated separately as the sign of
  `ci_lower` being `-2.3e-3`.
- **N6 (MEDIUM) — FIXED.** `verify_published_run` proves committed-artifact consistency
  (Contract C) but not raw-data → reproduced-results → rendered-report identity.
  *Fix:* added Contract D (render from the reproduced results); `check_replay` now
  separates Contracts A/B/C/D. See below for the Contract-D correction.

**Contract D — results-digest avalanche (found by CI, FIXED, commit `de04a81`).** The
first cut of Contract D required the report rendered from the reproduced results to be
byte-identical to the committed report. That passed locally (same-host repro has zero
drift) but failed on all three runners: the report embeds `sha256(results)` as a
provenance digest (e.g. committed `4db76efb…` vs reproduced `63d7fa6d…`), and that SHA
avalanches under the 1–2 ULP statistical drift, so the digest line legitimately differs.
*Fix:* Contract D is now a semantic comparison — substitute the reproduced results-digest
back to the committed one and require exact byte-equality of every other byte (every `.6g`
statistic and financial table). Named `report_reproduced_modulo_results_digest`, not
"byte-reproduced". Unit-tested (`test_contract_d_*`) so the drift path is covered locally.

Two output-neutral hygiene changes accompanied the contract (commit `3cc63e6`, verified
byte-identical by `replay --check`): `np.percentile(..., method="linear")` is pinned
explicitly, and `block_length` uses an exact integer floor-cube-root instead of
`int(n**(1/3) + 1e-9)` (proven to agree across `[1,100000]` and on the real fold sizes).

**Outcome unchanged.** The mechanical verdict remains
`rejected_for_development_gate_promotion`; no immutable artifact, ledger, or lifecycle
event was changed, and the single-use run was not re-executed.

## Independent-acceptance red team (three more auditors)

After the numerical-contract correction, three further independent read-only auditors
re-attacked the whole surface. **No Class A (financial/scientific-integrity) or Class D
(sealed-access/budget-drift) working exploit** was found; every concrete control
(byte-empty ledgers, single-use id, candidate fingerprint, next-open causality,
fold isolation, decision re-derivation) held. Their real findings were reproduced and
fixed; the rest are documented non-defects. Full detail in
`docs/M3C_INDEPENDENT_ACCEPTANCE_AUDIT.md`.

| id | severity | finding | disposition |
| --- | --- | --- | --- |
| A-F1 | B | `annualized_return` is fractional-`pow`-derived (non-CR transcendental) yet Contract-A byte-exact; robust only on the homogeneous supported envelope | **scoped + documented** (method note §8, numerics docstring, test); not loosened — within the tested Linux/x86_64 glibc envelope it reproduces byte-for-byte |
| A-F4 | C | numerics allowlist keys `paired_comparisons` by position, but the model left fold order unpinned | **FIXED** — results require folds 0..4 in ascending serialized order |
| A-F2 / A-F3 | C | P7 (and P5's `min_equity`) are structurally non-discriminating | **accepted (documented)** — already noted in the pre-registration log; `decision.py` is bound to the immutable committed decision and cannot change |
| B-F1 / C-F1 | B (→D-adjacent) | `research_budget.json` / `research_lineage.json` bound by SHA only; governance invariants never semantically verified | **FIXED** — `verify_published_run` now parses both strictly and requires byte-equality with the one canonical `build_research_budget()` / `build_m3c_lineage()` (new check `governance_documents_are_canonical`) |
| C-F2 | B | fold-cell timestamp parse was decode-and-repair (accepted naive / non-UTC) | **FIXED** — `require_utc_timestamp` |
| C-F3 | D | registry `event_time_utc` accepted a non-UTC offset | **FIXED** — `require_utc_timestamp` |
| C-F4 | C | shallow verifier didn't bind `results.protocol_sha256` to the registered protocol | **FIXED** — explicit binding added |
| B-F2 | C | replay ledger check lacked the orchestrator's symlink guard | **FIXED** — symlink / non-regular-file rejected |
| B-F3 | C | `build_m3c_fold_frames` has no explicit boundary re-guard (safe by construction) | **accepted** — the only data source is the boundary-guarded research-train loader; noted as defense-in-depth |
| C-F5 | C | `recovery.finalize` doesn't re-run `verify_published_run` after appending | **accepted** — finalize is deliberately calculation-free; CI replay/verify is the safety net (documented) |

Every fix was proven byte-neutral (`replay --check` still reproduces the committed run;
`verify_archive --deep` reports 15 checks) and touches no immutable artifact, ledger, or
lifecycle event.
