# V2B Terminal Acceptance Audit

Independent, read-only acceptance record for **Milestone V2B** (cross-asset research reset on the accepted
V2A null: a genuinely new BTC information source, cumulative family-wise multiplicity, ≤ 2 pre-registered
cross-asset candidate families, and exactly one governed research-train execution) on the private
`eth-research` package. Every item below was verified against the committed source, the committed governed
artifacts, the offline replay verifier, five independent post-run auditors, and a fresh-clone
reproduction. This audit adds **no** performance claim: the one governed run produced a **null** result and
V2 remains `not_sell_ready`.

- Package / version: `eth-research` **2.0.0.dev1** (V2B dev line; V2A froze at `2.0.0.dev0`).
- Branch: `claude/v2b-cross-asset-research-reset`, tip `00e75b7`, stacked on the accepted V2A tip
  `d437daf`.
- Draft PR: stacked, `base: claude/v2a-commercial-evidence-shadow-platform`,
  `head: claude/v2b-cross-asset-research-reset` (review only; **no merge / undraft / retarget**).
- Governed run: `v2b_run_001`; **NO cross-asset candidate nominated**.
- Key fingerprints — results `d0b668f4…`, protocol identity `2bdf606e…`, combined partition `6a37a95e…`,
  aligned timestamps `6be3a46a…`, BTC dataset `6896e614…`, ETH content `219aaa35…`, research-family
  catalog `3b559695…`; sealed-ledger empty `e3b0c442…`.

## A. Milestone framing & scope

1. V2B is a research-and-evidence milestone, not a commercialization: its best possible outcome is at most
   **one** research-stage nomination handed to an independent development-gate review — never a sell
   decision.
2. The standing commercial posture is `not_sell_ready` throughout, and `sell_ready` is `false` in
   `research/v2b/buyer_evidence.json`.
3. V2B builds on the **accepted V2A negative result** as an immutable base; it does not retune, revive, or
   relabel any rejected V2A or M3C candidate.
4. Only reused, accepted engines are used for evaluation (`portfolio` (M4B), `m3c.statistics`,
   `walkforward`, `metrics`, `fractional.risk`); no accepted engine was modified.
5. All new code lives under `eth_research.v2b`; the accepted V2A / M-series / GA / private-GA layers are
   untouched by evaluation logic.
6. The sealed partitions (development_gate, final_holdout, M2B test, M3D prospective, M3E machinery, every
   observation after the research cutoff) are out of scope and were not read.
7. No license was added; commercialization remains gated on separate human authorization (verified: no
   `license` field/classifier in `pyproject.toml`, no `LICENSE`/`COPYING` file).
8. The active version advanced only the dev line (`2.0.0.dev0` → `2.0.0.dev1`); no release version bump, no
   GitHub Release, no PyPI/TestPyPI publication.

## B. The E → R → P governed sequence

9. **E (source freeze):** the §26 five-auditor pre-registration red-team fixes (statistics ULP bug,
   gate-6 resolution floor, governance strictness) were committed (`8bca11f`) and the full battery went
   green on the frozen tree before registration.
10. **R (registration):** the single `registered` event was appended (`21cdd11`) pinning the protocol
    identity `2bdf606e…` before any candidate ran on the real joint partition; CI green on the R tip.
11. **P (execution):** `run_one_shot('.')` ran exactly once (`00e75b7`), building the firewalled joint
    partition, evaluating, applying the decision rule, and publishing.
12. The E→R→P ordering is enforced by git history: the R commit appends only `registered`; the P commit
    appends `started` + `completed` and the published `v2b_results.json` / `v2b_results_manifest.json`.
13. The registration was committed **before** the evaluation could have been known (the protocol identity
    is a pure function of the frozen artifacts; it contains no result).
14. `execute` appends `started` to the registry *before* any evaluation, permanently consuming the
    one-shot budget up front.
15. On success it publishes results, then appends `completed` binding the results fingerprint; on any
    failure between run and publish it appends `failed` and re-raises (budget stays consumed).
16. Timestamps are explicit inputs to the drivers (only the CLI wrapper may read a wall clock, and only
    when `--timestamp` is omitted), so the computation is deterministic and reproduces byte-for-byte.
17. The registry holds exactly `registered(seq 0) → started(seq 1) → completed(seq 2)` after P.
18. The one-shot budget `max_research_executions = 1` is enforced on append and on read; a second
    `started` is refused through every path.
19. `run_one_shot` is pure (no registry/publish side effects); only `execute` drives the governed
    boundary, and nothing committed re-invokes it automatically.
20. Each E/R checkpoint reached CI-green on the branch before the next was taken.

## C. The one-shot outcome (honest null)

21. `nominated_candidate_id = null`; `eligible_candidate_ids = []`; the decision nominates nobody.
22. Both candidates are ineligible — a valid, successful outcome of a pre-registered program.
23. `cross_asset_btc_confirmed_eth_trend`: 4/6 folds beat benchmark, primary point +0.000925, 95% CI
    [−0.000726, +0.002617], primary lower ≤ 0, stressed/latency not robust, corrected one-sided lower
    −0.001285, MC p 0.140, sensitivity 0/9, aggregate Sharpe 1.857.
24. `cross_asset_eth_btc_relative_strength_rotation`: 4/6 folds, primary point +0.000518, 95% CI
    [−0.001118, +0.002160], primary lower ≤ 0, stressed/latency not robust, corrected one-sided lower
    −0.001616, MC p 0.268, sensitivity 0/3, aggregate Sharpe 1.565.
25. The pre-registered rule requires **all seven** gates: `primary_lower_above_zero`,
    `stressed_lower_above_zero`, `latency_lower_above_zero`, `corrected_lower_above_zero`, `mc_supports`,
    `sensitivity_all_above_zero`, `strict_fold_majority`.
26. Each candidate clears **only** `strict_fold_majority`; it fails the other six — the rejection is
    over-determined and does not hinge on any single threshold.
27. Both fail the **primary** uncorrected 95% lower-bound gate, which is independent of the multiplicity
    correction and of the Monte-Carlo gate.
28. The null survives the most lenient reasonable test: uncorrected one-sided p-values 0.141 and 0.270,
    both far above 0.05.
29. Both point estimates are weakly **positive** — a favorable-but-insignificant read, the opposite of a
    suppressed real edge.
30. Neither candidate is a relabel of a permanently-rejected M3C/V2A candidate (distinctness enforced by
    the candidate-source freeze + research-memory anti-relabel verifier).
31. The evaluation covers exactly the two pre-registered candidate ids plus the pre-registered benchmarks;
    the decision covers the same set.
32. The mechanical decision emits no reserved status: `reason = "no candidate cleared every gate"`,
    `tie_behavior = highest_primary_point_estimate_else_none` (ties → none, not exercised at 0 eligible).
33. The descriptive in-sample aggregate Sharpe values gate no eligibility criterion; they are reported for
    transparency only and are not decision inputs.

## D. Protocol identity & immutability

34. `research/v2b/v2b_research_protocol.json` pins `protocol_fingerprint = 2bdf606e…`.
35. The identity binds exactly four artifact SHA-256s: `candidate_source_freeze.json` (`d0203d8c…`),
    `joint_partition_identity.json` (`b5f32369…`), `execution_scenarios.json` (`fe94df97…`),
    `research_multiplicity_state.json` (`df97daa7…`).
36. It also binds the fold structure (`oos_fold_count = 6`, `warmup_rows = 150`) and the nomination
    constants (`tie_behavior = highest_primary_point_estimate_else_none`).
37. `protocol_fingerprint(repo_root)` recomputes `2bdf606e…` from the committed artifacts, and the protocol
    file reproduces byte-for-byte (independently confirmed by a stdlib-only recompute).
38. `verify_protocol_identity` passes; the protocol identity is immutable after R and the run was evaluated
    against exactly these pins.
39. `verify_registry_bound` confirms every registry event's `protocol_fingerprint` equals the recomputed
    `2bdf606e…`.
40. The candidate source was frozen **before** any real BTC byte entered the branch (candidate distinctness
    matrix + BTC information-dependence: missing BTC → refusal, no ETH-only fallback).
41. The pre-registration red team (§26, five independent auditors) closed every Class A/D before E; the one
    genuine Class A (the Monte-Carlo sign-flip ULP dropout) was fixed and re-verified by brute force.

## E. Registry & one-shot budget

42. `research/v2b/v2b_research_registry.jsonl` is an append-only hash chain: first
    `prev_entry_hash = "0"*64`, each `prev_entry_hash` equals the prior `entry_hash`, each `entry_hash`
    recomputes, `seq` = index.
43. The governance verifier returns `{"ok": true, "problems": []}`; the chain is sound.
44. The chain is `registered(v2b_run_001, seq 0) → started(seq 1) → completed(seq 2)`.
45. The `completed` event payload binds `results_fingerprint = d0b668f4…`.
46. A second `started`, a second `registered`, and a `started` without a prior `registered` are each
    refused — demonstrated empirically on scratch copies by the governance auditor.
47. Lifecycle is enforced on read (`_assert_lifecycle`, `MAX_REGISTERED = 1`, `MAX_STARTED = 1`) as well as
    on append.
48. The budget declares `consume_on_start: true`, `allow_repair_or_reset: false`,
    `max_research_executions: 1`; `verify_budget` passes.
49. No `reset`/`--force`/`repair`/`rollback` function exists anywhere in `v2b`, `v2.registry`, or
    `v2.budget` (grep-confirmed by the governance auditor).
50. `register()` refuses a non-empty registry; `execute()` refuses a second `started`; re-running requires
    destroying committed evidence out-of-band (recorded and refused by git history + the no-reset policy).
51. The budget is now permanently consumed; the run cannot happen again through any committed code path.
52. Two acknowledged trust boundaries (L1 unkeyed-hash wholesale re-chain; L2 out-of-band delete+rerun) are
    documented in-code, git-history-anchored, and non-invalidating for this run.

## F. Publication & reproducibility

53. `research/v2b/v2b_results.json` is strict canonical (sorted keys, no NaN/Inf, single trailing newline,
    no wall-clock); its 5 keys are exactly the results schema.
54. `summarize_committed` navigates it strictly; its canonical fingerprint is `d0b668f4…`.
55. `research/v2b/v2b_results_manifest.json` binds `results_sha256` = sha256(results bytes) = `d0b668f4…`
    and `results_fingerprint` = `d0b668f4…`; the file is byte-canonical, so the two coincide by
    construction.
56. The manifest `nominated_candidate_id` is `null` and its `verdict` agree with the decision.
57. `verify_publication('.')` returns `[]`; a tampered results file or a stale manifest is detected
    (sha/fingerprint mismatch), and `publish_results` re-runs `verify_publication` and fails closed.
58. The results fingerprint agrees across four independent sources: the results doc, the manifest
    fingerprint, the manifest sha256, and the registry `completed` payload — all `d0b668f4…`.
59. `python -m eth_research.v2b.replay --check` prints "V2B replay OK" (exit 0): design invariants, sealed
    ledgers, registry chain/lifecycle/binding, and the published-run fingerprint binding all verify.
60. **Fresh-clone reproduction:** a clean `git clone` at the branch tip replays "V2B replay OK", governance
    `{"ok": true, "problems": []}`, the fingerprint chain to `d0b668f4…`, `nominated = None`, sealed
    ledgers byte-empty, and the full V2B suite (164 tests) passes.
61. Cross-runtime: the read-only `v2b-replay.yml` runs the verifier + suite on the authoritative CPython
    3.12.3; the main CI runs the suite on CPython 3.12 and 3.13. All green on R and P.

## G. Sealed-partition firewall & data isolation

62. The three sealed access ledgers are exactly 0 bytes with SHA-256 `e3b0c442…`:
    `research/m3a/development_gate_access.jsonl`, `research/m2b/test_evaluations.jsonl`,
    `research/m3d/prospective_evaluations.jsonl`.
63. `git log` over `base..HEAD` touching those paths is empty — the V2B branch never wrote a sealed ledger.
64. The joint partition is the aligned ≤-cutoff slice: 2221 rows, first `2016-05-23T00:00:00Z`, last open
    `2022-06-21T00:00:00Z` == `research_cutoff_last_open`, `no_row_at_or_after_cutoff: true`.
65. The greatest engine-visible timestamp is the last close = open + 23h = `2022-06-21T23:00:00Z`, strictly
    `<` the seal `2022-06-22T00:00:00Z` — verified by `_assert_firewall` on the run path.
66. Both raw BTC acquisitions are 2221 rows over the exact window; a direct byte scan finds **0** epochs
    at/after the cutoff and 0 pre-window; `parse_candles_body` hard-rejects any at/after-cutoff row.
67. The two BTC acquisitions (genesis + audit) reproduce identical canonical candles from **distinct**
    `workflow_run_id` and `source_commit` — independent corroboration, not a single fetch.
68. The evaluation, candidates, engine, folds, statistics, sensitivity, and decision provably saw only the
    2221-row research-train joint panel (candidates traded actively; no silent flattening).
69. The upstream ETH integrity loader content-hashes the full committed dataset for tamper-detection but
    returns **only** the 2221 research-train rows; `guard_research_train_frame` rejects any frame exceeding
    the cutoff — no sealed row's value reaches any research consumer (Class-C A-C1, fully dispositioned in
    `docs/V2B_POSTRUN_REDTEAM.md`).
70. The M3D prospective cohort and M3E machinery are never loaded in `v2b`.
71. `git status` is clean post-run; no sealed/tracked file was modified by the run.
72. The `v2b-replay.yml` workflow asserts the three ledgers byte-empty (`[ -s ]` + sha256) on every push.

## H. Scientific integrity

73. The run honored the pre-registration exactly — every fingerprint matches (all five auditors).
74. The no-nomination decision is mechanically correct, confirmed independently (by-hand gate application,
    re-derivation of `all(gates)`, and a byte-exact reproduction of the results).
75. The reused fold-stratified moving-block bootstrap is deterministic (`M3C_BOOTSTRAP_SEED = 20260714`,
    20000 resamples, fixed percentiles), drawn within-fold (no seam crossing), replicating the accepted
    M3C statistic bit-for-bit.
76. The Monte-Carlo sign-flip is block-level (`MC_SIGN_FLIP_SEED = 20260721`, 20000 resamples,
    `block_length = floor(n**(1/3))`); the observed statistic is produced by the identical reduction as
    every permuted row (the §26 ULP-dropout regression is closed).
77. The MC estimator was validated by exact 2^18 brute-force enumeration (agreement to sampling noise); it
    is the conservative Phipson–Smyth `(#≥obs + 1)/(N+1)` permutation p-value and cannot manufacture a
    false pass; its resolution floor `≈ 5e-5 < 0.005` keeps the gate crossable.
78. The corrected bootstrap reconciles bit-for-bit with the primary endpoint; `corrected_one_sided_lower ≤
    ci95_lower` (a more-extreme tail) for both candidates.
79. Costs are charged once per event at a shared linear rate symmetrically to candidate and benchmark; the
    ETH buy-and-hold benchmark incurs zero turnover and is not over-charged.
80. Candidate vs benchmark returns are sliced by identical per-fold `iloc` ranges with an alignment assert
    that raises on any timestamp mismatch rather than silently mispairing.
81. Candidates, seeds, folds, cost scenarios, sensitivity neighborhood, and the decision rule are all
    pre-registered and fingerprint-pinned — no look-ahead / peeking / data-snooping channel exists.
82. Each candidate's scalar oracle proves the vectorized signal at bar t depends only on data ≤ t
    (causality), and the 1-bar execution latency admits no last-bar leakage (metamorphic test).

## I. Post-run red team (five independent auditors)

83. Five independent read-only auditors reviewed the executed run from distinct lenses; each reproduced the
    result independently.
84. **A — firewall & data:** NO Class A, NO Class D — partition/BTC window/look-ahead/sealed all clean.
85. **B — statistics & decision:** NO Class A, NO Class D — gates faithful, MC fix correct, NULL does not
    hinge on MC or correction.
86. **C — governance / registry / one-shot:** CLEAN — chain sound, budget consumed exactly once and not
    re-runnable/resettable, bindings real.
87. **D — publication / results / reproducibility:** CLEAN — fingerprint chain recomputed independently,
    NULL genuine, no over-claim.
88. **E — scope / commercial honesty / firewall:** CLEAN — sealed ledgers byte-empty, all changes
    in-scope, `not_sell_ready` preserved.
89. No auditor required a code fix; the run stands as a valid, reproducible, pre-registered null result.
90. The Class C / observational items (A-C1 firewall integrity-hash; B-C1 unstored stressed/latency bounds;
    B-C2/C-C1..C4 cosmetics; D-C1 docstring wording; D-C2 correct-by-construction; E-C1 descriptive Sharpe;
    E-C2 pre-existing inert release machinery) are recorded in `docs/V2B_FINDINGS.md` §3 and
    `docs/V2B_POSTRUN_REDTEAM.md`; none invalidates the run.
91. The Class C items are **not** applied retroactively — the protocol identity and the published results
    are immutable and the evaluation source is frozen at the P commit.

## J. New information source & cross-asset design (BTC)

92. The new information source is historical **BTC-USD** daily data, restricted to the exact matching
    research-train window `[2016-05-23T00:00:00Z, 2022-06-22T00:00:00Z)` — no context row before the start,
    no row at/after the end, no forming candle.
93. BTC was acquired via a temporary hardened one-shot workflow (`contents: write` only, no `id-token`/
    secrets, SHA-pinned, no overwrite, fast-forward-only bot commit), then the workflow was retired.
94. Two independent acquisitions (genesis + audit) reproduce identical canonical candles; the joint
    partition identity binds `btc_dataset_fingerprint 6896e614…` and `btc_content_fingerprint 80071ef7…`.
95. The joint partition is built internally from committed manifests/locks (caller frames untrusted),
    aligned on exact shared daily opens (`alignment_policy = exact_shared_daily_opens`), USD base, daily
    calendar.
96. The candidate families genuinely depend on BTC information: a candidate-distinctness matrix separates
    them from M3A/M3B/M3C/V2A, and a BTC information-dependence test forces refusal when BTC is absent (no
    ETH-only fallback).
97. The reused M4B portfolio engine runs a long-only ETH/BTC/cash program (gross ≤ 1, no short, no
    leverage, no FX/corp-action); pre-registered benchmarks include cash, ETH buy-and-hold, BTC
    buy-and-hold, and static 50/50.

## K. Cumulative multiplicity & nomination rule

98. `research/v2b/research_multiplicity_state.json` declares `total_family_count = 10` = 8 historical
    families + 2 V2B, `correction_method = holm_bonferroni_familywise`, `cumulative_alpha_budget = 0.05`.
99. The per-family corrected alpha is `0.05 / 10 = 0.005` (`corrected_per_family_alpha = 0.005`,
    `corrected_one_sided_confidence = 0.995`).
100. The eight historical families are the enumerated prior candidate families (M3A × 2, M3B × 2, M3C × 1,
     V2A × 3); the two passive benchmarks are correctly excluded from the family count.
101. The budget declares `no_reset: true` — a new package version, the addition of BTC, or a changed
     benchmark does not refresh alpha (recorded as a limitation).
102. The multiplicity correction applies only to the primary nomination verdict; diagnostics report
     unadjusted intervals (recorded limitation).
103. The nomination rule is stringent: a candidate must clear all seven gates; at most one nomination; none
     if neither passes; ties → none.
104. Both candidates fail the correction gate (`corrected_lower_above_zero = false`) *and* the primary gate
     independently, so the null is robust to the exact correction denominator.

## L. Shadow platform & buyer-evaluation boundary

105. The shadow extension is multi-asset (ETH/BTC/cash) but **signal-only**: no network, no orders, no
     credentials, no money; the shadow evidence records prohibition constants (`no_credentials`,
     `no_leverage_or_shorting`).
106. The buyer-evidence update preserves every prior negative limitation and keeps `sell_ready: false`,
     `posture: not_sell_ready`.
107. The buyer factsheet headlines state plainly: pre-registered protocol, exactly one governed execution,
     sealed partitions never read, signal-only shadow, `not_sell_ready`.
108. The V2B limitations list explicitly frames a nomination (had there been one) as *not* validation,
     forward evidence, deployment readiness, capacity, or a performance claim — and there was none.
109. No legal/license artifact confers any right; nothing here is an offer to sell.

## M. Prohibited-functionality & governance gates

110. No network reach, no order placement, no money movement, no live/production mode, no
     credentials/wallets/signing/leverage/margin/shorts/derivatives — confirmed by the scope auditor over
     the whole `v2b` tree (only benign prohibition constants and economics prose match forbidden tokens).
111. Workflow security (repository-wide) holds: the retired BTC acquisition workflow is gone; the only new
     workflow is the read-only `v2b-replay.yml` (`contents: read`, SHA-pinned, no secrets, no `id-token`,
     no artifact upload).
112. `v2b-replay.yml` is in the closed `KNOWN_WORKFLOW_FILES` allowlist (the CI-caught allowlist fix
     `34eb79a` closed this before P).
113. No license field/classifier/`LICENSE` file was added (human commercialization gate respected); the
     version stayed on the dev line.
114. The repo-hygiene, workflow-security, private-workflow-security, secret-scanner, and repo-hygiene tests
     pass over the whole tree.

## N. Reused-engine neutrality

115. The reused engines (`portfolio` (M4B), `m3c.statistics`, `walkforward`, `metrics`, `fractional.risk`,
     `v2` governance scaffold) were used unmodified; the zero-cost engine reconciliation matches the
     accepted M4B engine bit-for-bit.
116. No accepted engine file was modified for V2B; V2B's only touch to shared `v2` modules pins
     `V2A_PACKAGE_VERSION = "2.0.0.dev0"` so the accepted V2A results do not drift under the dev1 bump
     (protective, not a V2A result change).
117. The `research/v2a/**` diff over `base...HEAD` is empty; no V2A governed artifact was changed.
118. The reused bootstrap's fixed 95% interval and the risk overlays (long-only, unlevered) are asserted
     for coherence, not reparameterized.

## O. CI, hygiene & accepted-stack neutrality

119. The `base...HEAD` diff is 108 files, +10947/−41, all in-scope (new `v2b` modules, `test_v2b_*`, docs,
     `research/v2b/**`, the read-only workflow, version-bump propagation, and strengthened
     security/hygiene tests).
120. `main` is unchanged (`origin/main == main == 30e1199…`); the tag set (`v0.2.0 … v1.1.0`) is unchanged
     — no V2B tag was created.
121. `uv.lock` matches `pyproject.toml`; the environment is hash-pinned (uv 0.8.17, CPython 3.12.3
     authoritative).
122. `ruff check`, `ruff format --check`, and `mypy --strict` (over `src`, `tests`, `examples`) are clean.
123. The `research/v2b/` layer is added to the drift-check exclusion list (same basis as prior post-baseline
     milestone-layer exclusions); accepted-stack snapshots and the governed-neutrality baseline remain
     valid.
124. CI on the R (`21cdd11`) and P (`00e75b7`) tips reached full green: **CI**, **V2B Replay**, and
     **M3F Replay** all `success`.
125. This finalizing documentation commit changes only `docs/V2B_*.md`; its CI is verified green after push
     and reported in the terminal handoff.

## P. Documentation & honesty

126. `docs/V2B_FINDINGS.md` records the honest null outcome, the per-candidate seven-gate table, the five
     auditors, the Class C observations, the limitations, and the forward posture.
127. `docs/V2B_POSTRUN_REDTEAM.md` records the five-auditor method, per-auditor verdicts, the full firewall
     A-C1 disposition, the L1/L2 trust boundaries, the Class C register, and the fresh-clone reproduction.
128. `docs/V2B_PREREGISTRATION_BUGLOG.md`, `docs/V2B_METHOD.md`, `docs/V2B_GOVERNANCE.md`,
     `docs/V2B_MULTIPLICITY_METHOD.md`, `docs/V2B_RESEARCH_MEMORY_METHOD.md`,
     `docs/V2B_HYPOTHESIS_REVIEW.md`, `docs/V2B_ACQUISITION.md`, and `docs/V2B_COMMERCIAL_EVIDENCE.md`
     document the pre-run method, governance, and evidence.
129. The findings make no out-of-sample / forward / walk-forward-live / live claim and state plainly that
     the result is research-train-only and in-sample.
130. The forward proposal is honest: a new hypothesis needs a fresh, separately-governed pre-registration;
     the cumulative multiplicity budget still applies and does not reset; V2 stays `not_sell_ready`; the
     sealed partitions are not a retry mechanism.
131. No document overstates the result or implies sell-readiness.

## Q. Terminal gates

132. **Terminal full battery:** the full V2B suite passes on a fresh clone at the P tip (164 tests); CI
     re-runs the same suite (plus the whole repository suite) on every pushed tip.
133. **Final CI:** the code-bearing tips through P (`00e75b7`) reached full CI-green (CI, V2B Replay,
     M3F Replay).
134. **Draft PR:** a single stacked draft PR is opened with `base: claude/v2a-commercial-evidence-shadow-
     platform`, `head: claude/v2b-cross-asset-research-reset`; it is for review only and is **not** merged,
     undrafted, or retargeted.
135. The working tree is clean and the branch is `claude/v2b-cross-asset-research-reset`.
136. All governed artifacts under `research/v2b/` are committed and verify clean.
137. This audit is read-only over the committed state; it introduces no code change.

## R. Terminal verdict

**V2B COMPLETE — NO CROSS-ASSET CANDIDATE NOMINATED; CUMULATIVE NEGATIVE EVIDENCE PRESERVED; ALL SEALED
PARTITIONS UNTOUCHED; V2 NOT SELL-READY.**

The single pre-registered, governed cross-asset one-shot executed exactly once and, applying the mechanical
seven-gate decision rule under a cumulative family-wise multiplicity correction (per-family α = 0.005),
nominated no candidate — a valid, honest, over-determined null result that reproduces byte-for-byte
(`d0b668f4…`). A genuinely new BTC information source was introduced under a strict firewall, and both
candidates failed the primary uncorrected gate independently of the correction and the Monte-Carlo gate.
Five independent post-run auditors found no scientific (Class A) and no governance/sealed (Class D) issue;
every surviving item is Class C and documented, not applied retroactively. The development-gate,
final-holdout, M2B test, and M3D prospective partitions were never read and their access ledgers remain
byte-empty. No license was added, no tag was created, `main` is untouched, the one-shot budget is
permanently consumed, and the commercial posture stays `not_sell_ready`.
