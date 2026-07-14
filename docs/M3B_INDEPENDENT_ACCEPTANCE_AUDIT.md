# Milestone 3B — Independent Acceptance Audit

**Verdict: ACCEPTED FOR HUMAN REVIEW.**

An independent, adversarial, read-first acceptance review of the completed M3B
trust-boundary closure. No new research, no new experiment, no development-gate or
final-holdout access, no merge. Three genuine defects were found (one Class B, two
Class C); each was reproduced with a failing/guarding test, minimally fixed in its
own commit, proven to leave the published run-001 financials byte-identical, and
logged. No Class-A (exploitable accounting / causality / recovery / archive /
authorization) and no Class-D (financial drift / sealed access / protocol
violation) defect was found. The stacked PR#4→PR#5 merge simulates cleanly and the
full local CI gate battery is green.

- Audited starting HEAD: `016368300d387d70a93c8658c2adecf7c5f0d226` (`0163683`).
- Acceptance HEAD (this audit's commits): `e6442bc` on
  `claude/m3b-fractional-risk-engine` (PR #5, open + draft).
- PR #5 base: `claude/m3a-development-research-lab` (`b3c261b5`) — not retargeted.
- Run-001 financials unchanged: the `0163683..HEAD` diff touches **no**
  `research/` artifact (src/tests/docs only); `replay --check` stays byte-identical.

---

## 1. Discipline honored

| Constraint | Status |
| --- | --- |
| No new research / experiment / run-002 | honored — no experiment executed |
| No development-gate or final-holdout access | honored — both ledgers verified byte-empty before and after; no sealed row read |
| A defect is fixed only after a failing test reproduces it | honored — A1/A2 have failing-first reproductions; A3 (overclaim, no failing test possible) is doc + standing guard only |
| Run-001 financials byte-identical (HARD STOP on drift) | honored — no `research/` byte changed; `replay --check` green throughout |
| No merge / undraft / retarget / tag / branch-delete / history-rewrite | honored — PR #5 left open + draft; merge only *simulated* in a disposable clone |

## 2. Preflight (A) — read-only

Verified at `0163683`: clean tree, local tip == remote tip, both sealed ledgers 0
bytes (`e3b0c442…855`), registry lifecycle exactly registered→started→completed for
the single run-001 id (no run-002), the five M3B immutable digests at their frozen
values, no M2B/M3A immutable artifact touched vs. the PR#5 base, base `b3c261b5` an
ancestor of HEAD, and no tag containing the M3B freeze/registration/execution
commits. **GitHub-side live re-check (PR/CI run conclusions) was blocked** by
GitHub MCP token expiry in this non-interactive session; CI is instead re-verified
exhaustively and locally (§6), and the git preflight proves local == remote at the
audited head.

## 3. Baseline (B) — one reviewed fixture

`tests/test_m3b_acceptance_baseline.py` pins, in one reviewed place, the SHA-256 of
each of the five immutable run-001 artifacts, the byte-emptiness of both sealed
ledgers, the exact registry lifecycle, and the exact 75-cell grid identity
(5 strategies × 3 cost scenarios × 5 folds, no duplicate cell). Any future drift of
a financial artifact, a sealed ledger, or the lifecycle now fails loudly.

## 4. Independent verification (C–L)

Reconstructed from source and independent oracles — never trusted because a claim
appears in the PR body, terminal audit, bug log, or tests.

- **C — 75-cell financial reconstruction.** Byte-for-byte replay + deep archive
  verify (25 checks) re-run the whole grid and re-derive the execution-trace
  commitments; the 15 cash cells are trivially correct; the single declared
  cost-monotonicity inversion set was independently rederived and matches exactly.
- **D — strict decode-not-repair.** Every `from_json_bytes` was traced. The one gap
  (protocol parser) is finding **A1**, fixed. Independently corroborated that the
  results / registry / manifest / annotation / erratum / completion-intent parsers
  reject dup-keys, NaN/Inf/`1e999`, and bool/coercion, and that valid run-001 bytes
  still round-trip byte-identically.
- **E — accounting/solver red team.** 6,000 randomized production-cost solves: never
  a lying `converged`, never negative cash/quantity or out-of-`[0,1]` weight,
  honest partials at constraints; funding identities and finiteness-before-sign
  guards hold; reconciliation re-derives each bar from the previous bar + fill.
- **F — engine causality/boundary.** One-bar causality (only `open[t]` of bar `t` is
  consumed pre-fill), prefix-invariance, strict `< as_of` liquidity slice, and
  signal index-equality refusal all hold. The one boundary gap (bare `ValueError`
  on a 1-row frame + context) is finding **A2**, fixed.
- **G — crash-recovery.** `recovery` imports only hashing + registry + completion
  (calculation-free); `finalize` re-runs chain sequencing, so a concurrent second
  finalizer, a wrong anchor, a stale/forged/other-run intent, or a symlinked
  artifact cannot double-append or finalize an unpublished run; the orchestrator
  refuses to record `failed` for a durably-published run.
- **H — archive-v2.** Anchored to the hash-chained registry `completed` event, not
  only the mutable manifest: a coordinated singleton+copy+manifest+record tamper
  with the registry untouched is caught; missing/symlinked copies rejected.
- **I — execution-trace commitments.** Total over all 20 `BarRecord` fields,
  deterministic (incl. `None`/`±inf`/`-0.0`/`Side` literal), and required to replay
  byte-for-byte with a fresh committed-results binding.
- **J — erratum completeness.** `derive_monotonicity_counterexamples` is recomputed
  from the committed results and required equal at full precision; the adjacent-pair
  strict-`>` scan over the friction order neither under- nor over-counts; the
  overbroad statement is verbatim-pinned and mandatory.
- **K — sealed-partition firewall.** Poison-spy verification confirms no
  development-gate / final-holdout row enters signal, liquidity, or volatility; both
  ledgers hashed byte-empty before and after the whole audit.
- **L — prohibited functionality / supply chain.** AST import scan across
  `src`+`tests`+`examples` found zero network / exchange / wallet / signing / ML
  imports; CI is `contents: read`, every `uses:` SHA-pinned, uv installed via a
  `--require-hashes` wheel (no piped installer), no secrets / force-push / PR-write.

## 5. Findings

| # | area | class | status |
| --- | --- | --- | --- |
| A1 | `protocol.py` parser repaired parsed values via `int()/float()/str()/bool()` instead of decoding (R4 gap on the protocol model) | **B** (strictness/repro) | **fixed** `8ec5a46` — routed through the strict `require_*` surface; run-001 protocol still round-trips byte-identically |
| A2 | engine context boundary leaked a bare `ValueError` (1-row frame + context) instead of `EngineError` | **C** (error-typing) | **fixed** `060499c` — interval determination re-typed to `EngineError`; no multi-row segment changes accept/reject |
| A3 | report renderer docstring overclaimed "computes nothing new" while Section 2's partition table is fixed literals | **C** (overclaim/doc) | **fixed** `e6442bc` — docstring made honest; standing guard pins the research-train count to `RESEARCH_TRAIN_ROWS` and asserts the sealed partitions are shown forbidden; rendering logic unchanged (report byte-identical) |

**Minor observations (not defects; no code change).**
- `metrics.num_partial_fills` counts partial *bars* (incl. capped no-fill), a naming
  imprecision, not a miscount.
- `verify_artifact_annotations` passes vacuously on an empty/absent annotation
  registry — inherent to a git-anchored append-only log; every annotated artifact is
  still independently required and verified, and the erratum is mandatory.
- The standing hygiene import gate AST-scans only `fractional/*.py`; an independent
  scan of `src`+`tests`+`examples` was clean.

## 6. Final gates (Q) — all green locally

| gate | result |
| --- | --- |
| `python --version` | 3.12.3 |
| `uv lock --check` | resolved, no update |
| `ruff check .` | all checks passed |
| `ruff format --check .` | 183 files formatted |
| `mypy src tests examples` | success, no issues (182 files) |
| `git diff --check` | clean |
| `pytest --durations=30` | **1590 passed**, exit 0 (no test exceeds 30s) |
| `fractional.replay --check` | `results_reproduced, report_reproduced, archive_verified` |
| `fractional.verify_run_archive --deep` | 25/25 checks, exit 0 |
| `fractional.recovery --status` | `no-intent; nothing to finalize` |
| `develop_m3a --check` (merged-main M3A gate) | reproducible, exit 0 |

## 7. Test discipline (O)

Exactly **one** full `pytest --durations=30` suite was run for acceptance (within
the ≤2 budget); the fix loops used only small targeted subsets, and a
`--collect-only` pass (no execution) counted 1590 tests. Result: **1590 passed,
exit 0**.

**No test exceeds 30s** — the slowest is 29.39s. The ten slowest are all legitimate
heavy integration tests, not pathological:

| seconds | test | why it is heavy |
| --- | --- | --- |
| 29.39 | `test_m3a_orchestrator_e2e … test_full_production_lifecycle` | runs the whole M3A production lifecycle end-to-end |
| 14.64 | `test_fractional_orchestrator … test_replay_verification_passes` (setup) | builds a full run then replays it |
| 14.07 | `test_fractional_recovery … test_recovers_calculation_free…` (setup) | builds + crash-injects a full publish |
| 12.32 | `test_fractional_verify_run_archive … test_deep_verification_adds_the_replay_check` | deep verify replays the execution trace |
| 11.96 | `test_fractional_execution_trace … test_commitments_replay_byte_for_byte` | re-derives all 75 cells' trace commitments |
| 11.91 | `test_fractional_recovery … test_recovers_calculation_free…` (call) | finalizes + re-verifies the recovered run |
| 11.79 | `test_fractional_orchestrator … test_completed_state_replays_byte_for_byte` | full run + byte replay |
| 9.50 | `test_fractional_experiment … test_produces_the_full_75_cell_grid` (setup) | executes the full 75-cell grid |
| 9.35 | `test_fractional_experiment … test_is_deterministic` | executes the grid twice |
| 8.70 | `test_m3a_run003_redteam … test_tampered_immutable_archive_is_rejected` | rebuilds the run then tampers |

Each re-runs the orchestrator, replays a published run, or re-derives the trace
commitments — inherently O(grid) work that is the point of the test. None is slow
for an avoidable reason.

## 8. Stacked-PR merge readiness (M)

Simulated in a disposable clone only — **no outward-facing operation**. The stack is
linear: `main` (`ed53eb2`) ⊂ `m3a` (`b3c261b`) ⊂ `m3b` (`e6442bc`).

1. `git checkout main && git merge --no-ff m3a` → **clean** (no conflict, no
   unmerged path).
2. (PR #5 retargets to `main`.) `git merge --no-ff m3b` → **clean**.
3. Proof: the merged-main working tree is **byte-identical** to the `m3b` branch
   tree (`git diff m3b <merged-main>` is empty), so the green gates on the `m3b`
   branch (§6) are exactly the post-merge `main` gates.

**Exact human-controlled sequence (for a human to run; not run here):**
1. Merge PR #4 (`claude/m3a-development-research-lab` → `main`).
2. Merge PR #5 (`claude/m3b-fractional-risk-engine`; GitHub auto-retargets its base
   to `main` once PR #4 merges) → `main`.
3. Tag/release per the repository's convention (e.g. `v0.5.0` for M3B) **after** the
   merged `main` CI is green.
4. Delete the merged feature branches if desired.

## 9. Handoff checklist (27 items)

1. Verdict: **ACCEPTED FOR HUMAN REVIEW**. ▢ human sign-off required before merge.
2. Audited HEAD `0163683`; acceptance HEAD `e6442bc`; five acceptance commits.
3. Run-001 financials byte-identical — `0163683..HEAD` touches no `research/` file.
4. Both sealed ledgers 0 bytes / `e3b0c442…855`, before and after.
5. Registry lifecycle registered→started→completed, one run id, no run-002.
6. Five M3B immutable digests at frozen values (baseline fixture pins them).
7. A1 (Class B) fixed `8ec5a46` — protocol strict parse + 6-case reproduction.
8. A2 (Class C) fixed `060499c` — engine boundary re-typed to `EngineError`.
9. A3 (Class C) fixed `e6442bc` — report boundary honesty + standing guard.
10. No Class-A defect found (accounting / causality / recovery / archive / authz).
11. No Class-D incident (no drift / sealed access / protocol violation).
12. Three minor non-defect observations recorded, no code change.
13. `replay --check` byte-identical throughout.
14. `verify_run_archive --deep` 25/25, exit 0.
15. `recovery --status` no pending intent.
16. `develop_m3a --check` green (merged-main M3A gate).
17. `ruff check .` / `ruff format --check .` clean.
18. `mypy src tests examples` clean.
19. `uv lock --check` clean; `git diff --check` clean.
20. `pytest --durations=30` — see §6/§7.
21. Stacked merge PR#4→PR#5 simulates clean; merged-main tree == m3b tree.
22. Exact human merge/tag sequence recorded (§8).
23. PR #5 left **open + draft**; base not retargeted; no tag created.
24. No M3C / run-002 / gate / holdout / promotion / tuning performed.
25. Findings + reproductions logged in `docs/M3B_BUG_LOG.md` (A1–A3).
26. **Limitation:** GitHub PR/CI live conclusions not re-queried (MCP token expired);
    CI reproduced locally; local == remote at the audited head.
27. Recommended next human step: review the five acceptance commits, run branch CI,
    then execute the §8 merge/tag sequence.

## 10. Absolute stop

No M3C, no run-002, no development-gate or final-holdout access, no promotion or
tuning, no merge / undraft / retarget, no tag, no branch deletion, no history
rewrite. PR #5 stays open and draft pending human review.
