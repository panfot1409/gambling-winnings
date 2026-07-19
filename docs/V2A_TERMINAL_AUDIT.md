# V2A Terminal Acceptance Audit

Independent, read-only acceptance record for **Milestone V2A** (commercial-evidence research core +
signal-only shadow platform + buyer-evaluation boundary) on the private `eth-research` package. Every
item below was verified against the committed source, the committed governed artifacts, the offline
replay verifier, four independent post-run auditors, and a fresh-clone reproduction. This audit adds
**no** performance claim: the one governed run produced a **null** result and V2 remains
`not_sell_ready`.

- Package / version: `eth-research` **2.0.0.dev0** (V2A dev line; version unchanged by the run).
- Branch: `claude/v2a-commercial-evidence-shadow-platform`.
- Draft PR: **#16** to `main` (review only; no merge is performed).
- Governed run: `run_001`; **NO candidate nominated**.
- Key fingerprints — results `6327de21…`, pre-registration `51b58845…`, research-train
  `sha256:60aa988e…`, protocol `2854a806…`, constitution `ebdd6dd4…`, budget `b9cb17cc…`, contract
  `00ed9b33…`; sealed-ledger empty `e3b0c442…`; pre-GA governed baseline `b2077eaf…`.

## A. Milestone framing & scope

1. V2A is a research-and-evidence milestone, not a commercialization: it produces at most one
   *research-stage* nomination for independent development-gate review, never a sell decision.
2. The standing commercial posture is `not_sell_ready` throughout (`v2/constitution.py` `STANDING_POSTURE`).
3. Only reused, accepted engines are used for evaluation (`fractional`, `m3c.experiment`,
   `m3c.statistics`, `walkforward`, `metrics`); no accepted engine was modified.
4. All new code lives under `eth_research.v2`, `eth_research.shadow`, and `eth_research.buyer`;
   accepted milestones (M2B–M4B, GA, private-GA) are untouched by evaluation logic.
5. The three sealed partitions (development_gate, final_holdout, M3D prospective) are out of scope and
   were not read.
6. No license was added; commercialization remains gated on separate human authorization (verified: no
   `license` field in `pyproject.toml`, no `LICENSE`/`COPYING` file).

## B. The E → R → P governed sequence

7. **E (source freeze):** the §29 pre-registration red-team fixes were committed (`4c8675f`) and CI
   went fully green (readiness, checks 3.12, checks 3.13, authoritative-runtime) before registration.
8. **R (registration):** `research/v2a/pre_registration.json` was committed *pristine* — registry and
   results absent — pinning the protocol/candidate/constitution/budget/contract fingerprints before any
   candidate ran; CI green on the R tip (`1b45080`).
9. **P (execution):** `run_one_shot('.', 'run_001', …)` ran exactly once (`0e7b4cb`), loading the
   firewalled research-train, evaluating, applying the decision rule, and publishing.
10. The E→R→P ordering is enforced by git history: R commits precede the P commit, and the P commit only
    adds `research_registry.jsonl` / `results.json` / `results_manifest.json`.
11. The registration was committed **before** the evaluation could have been known (pre-registration is
    a pure function of the frozen source; it contains no result).
12. `run_one_shot` appends `started` to the registry *before* any evaluation, consuming the one-shot
    budget up front (`v2/orchestrator.py`).
13. On success it publishes results, then appends `completed` binding the results fingerprint.
14. On any failure between evaluate and publish it appends `failed` and re-raises (budget stays
    consumed) — proven by `tests/test_v2_orchestrator.py`.
15. The run used the deterministic, side-effect-free `execute_evaluation`; the synthetic full-pipeline
    rehearsal (a `@slow` test) exercised the same engine path beforehand without peeking at real prices.
16. `started_at`/`completed_at` are explicit inputs (no wall-clock in the computation), so the run is
    deterministic and the results reproduce byte-for-byte.
17. The registry file did not exist before P (pristine) and holds exactly `genesis → started →
    completed` after P.
18. The one-shot budget `MAX_RESEARCH_EXECUTIONS = 1` is enforced on append and on read.
19. No CLI/console-script/`__main__` wires `run_one_shot`, so nothing committed can re-invoke it.
20. Each E/R/P checkpoint reached CI-green on the branch before the next was taken.

## C. The one-shot outcome (honest null)

21. `nominated_candidate_id = null`; the decision nominates nobody.
22. All three candidates are `research_stage_rejected` — a valid, successful outcome of a pre-registered
    program.
23. `meanrev_zscore_accumulation`: 2/5 folds beat benchmark, primary point −0.001581, 95% CI
    [−0.003952, +0.000789], lower ≤ 0, stressed not robust, Sharpe +0.157.
24. `vol_scaled_hold_drawdown_guard`: 2/5 folds, primary point −0.000396, CI [−0.002253, +0.001564],
    lower ≤ 0, stressed not robust, Sharpe +1.018.
25. `trend_regime_single_horizon`: 2/5 folds, primary point +0.000145, CI [−0.001291, +0.001639],
    lower ≤ 0, stressed not robust, Sharpe +1.095.
26. The pre-registered `NominationCriteria` require ≥ 3 folds beating benchmark; all three got 2/5 →
    `folds_beating_benchmark = false`.
27. Each requires the primary bootstrap lower bound > 0; all three are ≤ 0 → `primary_lower_above_zero =
    false`.
28. Each requires stressed robustness; all three fail → `stressed_robustness = false`.
29. Each passes `positive_sharpe = true`, so each fails exactly the other three criteria — the rejection
    is over-determined.
30. No candidate is a relabel of the permanently-rejected M3C candidate
    (`assert_distinct_from_rejected_m3c`).
31. The evaluation covers exactly the three pre-registered candidate ids and the benchmark; the decision
    covers the same set (`_assert_results_invariants`).
32. The decision emits no reserved/non-emittable status (`assert_no_reserved_status`); every status is
    within the constitution vocabulary.

## D. Pre-registration & immutability

33. `research/v2a/pre_registration.json` parses strictly and re-asserts every pin against the current
    (frozen) source (`v2/preregistration.py` `V2APreRegistration.parse`).
34. Its `protocol_fingerprint` equals `ResearchProtocol.current().fingerprint()` (`2854a806…`).
35. Its `constitution_fingerprint` equals `CommercialEvidenceConstitution.current().fingerprint()`
    (`ebdd6dd4…`).
36. Its `budget_fingerprint` equals `OneShotResearchBudget.current().fingerprint()` (`b9cb17cc…`).
37. Its `contract_fingerprint` equals `EvaluationContract.current().fingerprint()` (`00ed9b33…`).
38. Its `candidate_fingerprints` equal the three `CandidateSpecification.fingerprint()` values
    (`55e21c33 / c5d54b7c / 54eb7fa8`).
39. Its `run_id` is `run_001` and `package_version` is `2.0.0.dev0`.
40. The pre-registration reproduces byte-for-byte (pure function of the frozen source); its own
    fingerprint is `51b58845…`.
41. A tampered pre-registration is rejected (`test_v2_preregistration.py` drift test).
42. The pre-registration is immutable after R; the run was evaluated against exactly these pins.

## E. Registry & one-shot budget

43. `research/v2a/research_registry.jsonl` is an append-only hash chain: first `prev_hash = "0"*64`,
    each `prev_entry_hash` equals the prior `entry_hash`, each `entry_hash` recomputes, `seq` = index.
44. `verify_registry` returns `[]`; the chain is sound.
45. The chain is `started(run_001, seq 0) → completed(run_001, seq 1)`.
46. The `completed` event payload binds `results_fingerprint = 6327de21…`.
47. A second `started` (any run_id) is refused on append — verified empirically by the governance
    auditor on a scratch copy (`RegistryError: … one-shot research budget is consumed`).
48. Lifecycle is enforced on read (`_assert_lifecycle`): a terminal requires a prior `started` for the
    same run; ≤ 1 terminal per run; hash-valid forged chains that violate this are rejected.
49. `append_event` holds an exclusive `flock` over read+check+write (TOCTOU close) and fsyncs before
    unlock.
50. Only `append_event` writes the registry (append mode `ab`); no truncate/unlink/replace path exists.
51. `run_one_shot` appends `started` as its first registry action, so it can never re-reach evaluation.
52. The budget is now permanently consumed; the run cannot happen again through any committed code path.

## F. Publication & reproducibility

53. `research/v2a/results.json` is strict canonical (sorted keys, indented, no NaN/Inf, single trailing
    newline, no wall-clock).
54. `parse_results` round-trips it and re-asserts its invariants; `fingerprint()` = `6327de21…`.
55. `research/v2a/results_manifest.json` binds `results_sha256` = sha256(results bytes) and
    `results_fingerprint` = `6327de21…`.
56. The manifest `nominated_candidate_id` is `null`, agreeing with the decision.
57. `verify_publication('.')` returns `[]`.
58. A pure deterministic recompute (`execute_evaluation` + `build_results`) reproduces `6327de21…`
    byte-for-byte with **no** registry side effect — confirmed by the reproducibility auditor.
59. `replay._check_preregistration` binds the published results to the pre-registration
    fingerprint-for-fingerprint (protocol/constitution/budget/candidate/run_id).
60. `python -m eth_research.v2.replay --check` prints "V2A replay OK" (exit 0).
61. **Fresh-clone reproduction:** a clean `git clone` at the branch tip replays "V2A replay OK" and a
    full deterministic re-evaluation from the committed raw data reproduces `6327de21…` (recomputed =
    published = expected), `nominated=None`.
62. Cross-runtime: CI runs the suite + `replay --check` on CPython 3.12, 3.13, and the authoritative
    3.12.3, all green.

## G. Sealed-partition firewall & data isolation

63. The three sealed access ledgers are exactly 0 bytes with SHA-256 `e3b0c442…`:
    `research/m3a/development_gate_access.jsonl`, `research/m2b/test_evaluations.jsonl`,
    `research/m3d/prospective_evaluations.jsonl`.
64. The run's only writers are the registry and the publication under `research/v2a/`; no sealed ledger
    is written.
65. `load_research_train_only` reuses `verify_dataset_integrity_only` + `guard_research_train_frame` and
    returns only the research-train frame.
66. The frame is the ≤-boundary slice at `last_open = 2022-06-21`; sealed rows (development_gate ≥
    2022-06-22, final_holdout ≥ 2024-07-01) are excluded structurally.
67. Four independent layers defend the boundary: content-fingerprint binding, the reviewed boundary
    guard (rejects, never truncates), pinned row count/first/last, and manifest cross-check.
68. `results.json` `research_train_fingerprint = sha256:60aa988e…` equals the committed partition's
    research-train content fingerprint; row count 2221; first 2016-05-23; last 2022-06-21.
69. The name-gate `require_research_train_partition` rejects development_gate / final_holdout /
    prospective and allows only `research_train`.
70. The M3D prospective cohort is never loaded in `v2/` at all.
71. `git status` is clean post-run; no sealed/tracked file was modified by the run.
72. The `v2a-replay` workflow asserts the three ledgers are byte-empty (`[ -s ]` + sha256) on every
    push, before and after.

## H. Scientific integrity

73. The run honored the pre-registration exactly — every fingerprint matches (scientific auditor).
74. The no-nomination decision is mechanically correct, confirmed three independent ways (by-hand
    criteria, re-run of `decide()`, byte-exact re-evaluation).
75. The reused fold-stratified moving-block bootstrap is deterministic (seed 20260719, 20000 resamples,
    fixed 2.5/97.5 percentiles, explicit linear interpolation), drawn within-fold (no seam crossing).
76. The evaluator refuses a protocol whose `bootstrap_confidence` differs from the reused engine's fixed
    0.95 (Sci-C1 guard), so the reported interval cannot be mislabelled.
77. The stressed cost scenario is genuinely more punitive than the primary (higher fees/spread/slippage,
    tighter liquidity) — a real robustness stress.
78. `periods_per_year` derives from the reviewed `frame_interval` helper → 365.25 (daily).
79. Candidates, seed, and the decision rule are all pre-registered and fingerprint-pinned, so there is
    no look-ahead / peeking / data-snooping channel.
80. The vol-scaled candidate re-asserts the reused engine's `VOLATILITY_LOOKBACK`/
    `ANNUAL_VOLATILITY_TARGET` equal its pinned spec (Sci-C2 guard).
81. Each candidate's scalar oracle proves the vectorized signal at bar t depends only on closes ≤ t
    (causality), covered by the candidate causality tests.
82. `decide()` implements at-most-one nomination / strictly-highest primary point estimate / ties → none
    (`v2/decision.py`), with invariants re-asserted on build and parse.

## I. Post-run red team (four independent auditors)

83. Four independent read-only auditors reviewed the executed run from distinct lenses.
84. Scientific-integrity auditor: **NO CLASS A FINDING** — outcome correct and over-determined.
85. Governance/one-shot-budget auditor: **NO CLASS D FINDING** — chain sound, budget irreversibly
    consumed, lifecycle enforced.
86. Sealed-partition-firewall auditor: **NO CLASS D FINDING — ALL SEALED PARTITIONS UNTOUCHED**.
87. Reproducibility/publication auditor: **REPRODUCES EXACTLY** — no Class A/B/C finding.
88. No auditor required a code fix; the run stands as a valid, reproducible, pre-registered null result.
89. The Class C / observational items (walk-forward transitive binding PR-C1; aggregate-Sharpe fold-seam
    PR-C2; cosmetic `assert` PR-C3; the unused `walk_forward_protocol_v2.json`) are documented in
    `docs/V2A_FINDINGS.md` §3 and `docs/V2A_BUG_LOG.md` §48; none invalidates the run.
90. The Class C items are **not** applied retroactively — the pre-registration and results are immutable
    and the evaluation source is frozen at the P commit.

## J. Shadow platform (signal-only)

91. The shadow platform has exactly three non-live modes (synthetic_demo, historical_shadow,
    paper_simulation); any live/production/real-money mode is rejected fail-closed
    (`require_shadow_mode`).
92. `run_shadow` re-validates the mode at entry (Sh-C1) even for a directly-built config.
93. The only concrete execution adapter is `PaperExecutionAdapter` (records intents, routes nothing);
    the runner refuses any adapter whose channel is not on the reviewed non-routing allowlist (Sh-C2).
94. There is no live adapter and one cannot be added without tripping the AST no-network hygiene gate.
95. The as-of clock is monotonic and forbids look-ahead (`require_visible`); the runner advances it per
    bar.
96. The risk-limit engine clamps exposure; a hard breach trips the latching kill switch; a drawdown
    breach is evaluated on the held book *before* any fill (Sh-C4); staleness is monitored per bar
    (Sh-C3).
97. The shadow journal is an append-only hash chain; a re-run is byte-identical; the CLI verifies a
    journal + checkpoint offline.

## K. Buyer-evaluation boundary

98. The redaction scanner rejects secrets, embedded source, and raw/sealed tabular data — including
    source smuggled inside JSON string values (B1) — while passing honest governance prose.
99. The evaluation contract offers only redacted, source-free artifacts and explicitly withholds source,
    both sealed partitions, credentials, live/paper access, and the ability to run the governed
    experiment.
100. The contract / claims catalogue / scorecard / factsheet round-trip strictly and re-assert their
     fixed definitions; a drifted artifact is rejected (C1/C2).
101. The diligence bundle assembles source-free and every assembled artifact carries zero redaction
     violations.
102. The reference gateway serves only redacted artifacts, refuses every withheld item, fails closed
     when the redaction policy is not satisfied, and refuses a drifted contract (C3).
103. The commercial-readiness scorecard rates `commercial_readiness = absent` and overall posture
     `not_sell_ready`.
104. The legal drafts (NDA, eval-license, IP-readiness, pricing options) are DRAFT only; no license is
     conferred.

## L. Prohibited-functionality & governance gates

105. No network reach: the AST no-import hygiene gate over source/tests/examples forbids network client
     libraries (`tests/test_repo_hygiene.py`).
106. No order placement / money movement: only the paper adapter exists; no live routing path.
107. No live/production mode: `FORBIDDEN_LIVE_MODES` rejected fail-closed at the shadow boundary.
108. Workflow security (repository-wide): no `contents: write`, no secrets, no `id-token`, SHA-pinned
     actions, host allowlist, no artifact upload except the allowlisted private builder
     (`tests/test_workflow_security.py`, `tests/test_private_workflow_security.py`).
109. The `v2a-replay` workflow is read-only (`contents: read`), SHA-pinned, runs the verifier + the v2 /
     shadow / buyer suites, and asserts the sealed ledgers byte-empty.
110. No license field / classifier / `LICENSE` file was added (human commercialization gate respected).
111. The version stayed `2.0.0.dev0` (no release version bump).
112. The prohibited-gate tests pass (repo hygiene, workflow security, private workflow security, shadow
     platform).

## M. Reused-engine neutrality

113. The §29 red-team fixes changed **no** pre-registered fingerprint (protocol / candidate /
     constitution / contract / claims / scorecard / factsheet stable) — verified by the round-trip tests.
114. The evaluator calls the accepted `compute_m3c_cell_runs` with V2A's strategies + the two
     `causal_proxy` cost scenarios; each cell is reconciled before use.
115. No accepted engine file (`fractional`, `m3c`, `walkforward`, `metrics`) was modified for V2A.
116. The reused bootstrap's fixed 95% interval is asserted for coherence, not reparameterized.
117. Candidate risk overlays come only from the reviewed `RiskConfig` surface (long-only, unlevered).
118. The reused walk-forward protocol (`research/m3a/walk_forward_protocol.json`) forces the unique
     expanding 5-fold structure; each fold's OOS timestamps are cross-checked against the fingerprinted
     research-train.

## N. CI, hygiene & accepted-stack neutrality

119. The post-v1.1.0 `research/v2a/` layer is excluded from the v1.1.0 governed-neutrality baseline and
     the M3C–M3E stack freeze table (same basis as the M3F/M4A/M4B layer exclusions); the baseline still
     reproduces `b2077eaf…` byte-for-byte.
120. Adding the `research/v2a/` artifacts left every accepted-stack snapshot valid (verified by the two
     previously-failing tests now passing).
121. `uv.lock` matches `pyproject.toml`; the environment is hash-pinned (uv 0.8.17).
122. `ruff` (line-length 100) and `mypy --strict` (over `src`, `tests`, `examples`) are clean.
123. The secret scanner and private-key hygiene tests pass over the whole tree (fake fixtures are
     assembled at runtime; the private-key detector source uses `-{5}BEGIN`).
124. The `v2a-replay.yml` workflow file is in the known-workflow allowlist.
125. CI on the E, R, and P/terminal tips reached full green (readiness, checks 3.12, checks 3.13,
     authoritative-runtime).
126. Every commit is authored `Claude <noreply@anthropic.com>` and SSH-signed (a `gpgsig` header is
     present; local verification shows `N` only because no `allowedSignersFile` is configured — GitHub
     verifies them).

## O. Documentation & honesty

127. `docs/V2A_FINDINGS.md` records the honest null outcome, the per-candidate criteria table, the four
     auditors, the Class C observations, the limitations, and the forward posture.
128. `docs/V2A_BUG_LOG.md` records the §29 pre-registration fixes and the §48 post-run red-team results.
129. `docs/V2A_THREAT_MODEL.md` carries the T1–T11 controls plus the post-run T12–T14 confirmation.
130. The findings make no out-of-sample / forward / live claim and state plainly that the result is
     research-train-only and in-sample.
131. The forward proposal is honest: a new hypothesis needs a fresh, separately-governed pre-registration;
     V2 stays `not_sell_ready`; the sealed partitions are not a retry mechanism.
132. No document overstates the result or implies sell-readiness.

## P. Terminal gates

133. **Terminal full battery:** the entire test suite passes on a clean tree at the pre-audit tip
     `36de60a` — `PYTEST_EXIT=0`, every selected test green (1 skipped), no failures or errors. CI
     re-runs this same suite on every pushed tip.
134. **Final CI:** the code-bearing tips through §52 (`36de60a`) reached full CI-green (readiness,
     checks 3.12, checks 3.13, authoritative-runtime, and the read-only `v2a-replay`). This finalizing
     commit changes only `docs/V2A_TERMINAL_AUDIT.md`; its CI is verified green after push and reported
     in the handoff.
135. **Draft PR:** a single draft PR (**#16**) is opened to `main` (head
     `claude/v2a-commercial-evidence-shadow-platform`); it is for review only and **no merge is
     performed**.
136. The working tree is clean and the branch is `claude/v2a-commercial-evidence-shadow-platform`.
137. All governed artifacts under `research/v2a/` are committed and verify clean.
138. This audit is read-only over the committed state; it introduces no code change.

## Q. Terminal verdict

**V2A COMPLETE — NO CANDIDATE NOMINATED; ALL SEALED PARTITIONS UNTOUCHED; V2 NOT SELL-READY.**

The single pre-registered, governed one-shot executed exactly once and, applying the mechanical
decision rule, nominated no candidate — a valid, honest, over-determined null result that reproduces
byte-for-byte. Four independent post-run auditors found no scientific (Class A) and no governance/sealed
(Class D) issue. The development-gate and final-holdout partitions were never read and their access
ledgers remain byte-empty. No license was added and the commercial posture stays `not_sell_ready`.
