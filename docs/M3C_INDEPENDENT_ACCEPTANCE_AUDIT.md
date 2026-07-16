# Milestone 3C — Independent Acceptance Audit

## Verdict

**ACCEPTED FOR HUMAN REVIEW — CANDIDATE REJECTED.**

The one preregistered candidate was executed exactly once on the research-train
partition and **mechanically rejected**. The numerical replay contract has been
corrected from the earlier loose relative/absolute tolerance to an exact
bounded-binary64-ULP contract; a three-auditor independent red team found **no
Class A (financial/scientific-integrity) or Class D (sealed-access/budget-drift)
working exploit**; every reproduced finding was fixed byte-neutrally; and all
immutable artifacts, both sealed ledgers, and the one-shot lifecycle are unchanged.
This is eligibility for **independent human review**, not a merge authorization: PR
#6 remains open and draft.

## 1–4. Provenance, commits, PR

- **Starting HEAD:** `5cdcd4a` (fast-forwarded into a fresh clone from origin; no
  history rewrite). **Final HEAD:** the tip of this acceptance pass on branch
  `claude/m3c-adaptive-research-governance` (this audit is its own commit; CI is green
  at the tip — see §CI).
- **Acceptance-pass commits (ordered):**
  1. `e7cca7f` acceptance plan (read-only preflight)
  2. `e699688` exact bounded-binary64-ULP contract (fixes N1–N3, N6 scaffolding)
  3. `3cc63e6` pin percentile method + exact integer block-length (output-neutral)
  4. `54bd08e` independent statistical reconstruction oracle
  5. `e4a993d` real-tree sealed-partition firewall integration tests
  6. `de04a81` Contract D fix (report identical modulo the results-digest line)
  7. `3464812` m3c-replay CI hardening + acceptance-test skip guard
  8. `67ce4d3` governance-doc semantic verification + UTC/order strictness + ledger symlink guard
  9. `4f5d37d` scope the byte-for-byte financial claim to the supported envelope (pow fields)
  10. `890692f` forward-fix a masked mypy error
  11. `18c30c3` reproducibility documentation corrections
  (+ this audit commit.)
- **PR #6** → base `main`: `open`, `draft=true`, `merged=false`, head at the branch tip.
- **Workflow runs:** the five workflows (CI, M2B/M3A/M3B/M3C Replay) run per push; the
  final-head status is recorded at PR time and is green (the intermediate `e699688` push
  legitimately went red on the Contract-D digest avalanche and was fixed by `de04a81`,
  which is green — see the bug log).

## 5–6. Immutable artifacts and ledgers unchanged

All eight committed artifact SHA-256 digests are **identical** to the read-only P0
baseline (zero drift across the entire acceptance pass — only verifier/test/doc code
changed):

| artifact | sha256 |
| --- | --- |
| `candidate_results.json` | `4db76efb923bc209e4354afabad897ea084ea2bbafb9e0f11b0a4a49961e00fc` |
| `candidate_decision.json` | `f1b76101f2bb137036fd7b78c9d7ef2ad7a085b0e605ba0552bff939a9bdbc55` |
| `candidate_report.md` | `f0e776aecec3d91f3af5288bc54eaf9d4731c72516fd1075ffb8b5ef0d260e54` |
| `run-001/manifest.json` | `1fdf1f779732f48218aed8a9e851c8b1aa49bf73cb32b0e3233fe3d4dd4e7d47` |
| `experiment_registry.jsonl` | `d31ceff78e7901095634a39ee3d2a45ea5d05070fcb92354172f3915916d46eb` |
| `research_budget.json` | `81706025850427f35aee70fcc1d135faa7ef68a9b4b48ee481ace5b7b47405af` |
| `protocol.json` | `86f2245cc3621bac85c80fa9b87ab3e0b87cc3d8ef7ff2dd00b4188b01c86be9` |
| `research_lineage.json` | `57cfd3a3aa180ab5c3b68b0da0cd11f0fcc99b3ea46f3c31b829e81f5e919f40` |

Both sealed ledgers are **byte-empty** (0 bytes, sha256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`) before and after
every read-only command:
`research/m3a/development_gate_access.jsonl`, `research/m2b/test_evaluations.jsonl`.

## 7–8. Registry lifecycle and budget identity

- Registry: exactly `registered → started → completed`; one experiment id
  `m3c-dual-horizon-trend-v1-run-001`; one candidate; the `completed` event's
  `promotion_status` = `rejected_for_development_gate_promotion`. No second candidate /
  experiment / retry / failed / run-002 / alternative budget.
- Budget (now **semantically** re-validated, not hash-only): `max_new_candidate_families=1`,
  `permitted_primary_comparisons=1`, `development_gate_accesses_permitted=0`,
  `final_holdout_accesses_permitted=0`, `parameter_searches_permitted=0`,
  `strategy_fitting_permitted=false`, `post_result_parameter_changes_permitted=false`.

## 9–16. The one candidate and its mechanical rejection

- **Candidate fingerprint:** `d45d3bdf7a3dca7003e8382995e5a350d0c9e61edf47e87e294d151070f4cae6`
  (`dual_horizon_trend_63_252_vol_target_30d_50pct`); bound identically in budget,
  lineage, and protocol.
- **Folds / context:** five walk-forward OOS folds; ≤ 252 research-train context rows
  strictly before each OOS window; no context P&L; research-train rows only (≤ the frozen
  partition boundary).
- **Primary statistic:** mean paired daily log-excess (`log1p(cand) − log1p(bnh)`),
  pooled over 1126 candidate `causal_proxy_base` OOS days.
- **Bootstrap constants:** fold-stratified moving-block, seed `20260714`, 20 000 resamples,
  two-sided 95% percentile, block length `floor(n**(1/3)) = 6` per fold.
- **Committed interval:** point `-0.00012686998005055427`, 95% CI
  `[-0.002305602394720637, +0.002169364466966667]` (straddles zero, lower ≤ 0).
- **Fold result:** candidate beats buy-and-hold in **2 of 5** folds.
- **Criterion vector:** `P1=False, P2=False, P3=True, P4=True, P5=True, P6=True, P7=True`
  → **rejected_for_development_gate_promotion**. Independently reconstructed (own P1–P7,
  own bootstrap/PSR, engine-only daily returns) and identical — see §Oracle.

## 17–22. Cross-machine reproducibility (bounded-ULP contract)

- **Observed cross-machine drift (CI annotation):** exactly two leaves —
  `bootstrap.point_estimate` (**2 ULPs**) and
  `paired_comparisons.0.mean_daily_paired_log_excess` (**1 ULP**); both are descriptive
  (feed no promotion criterion). Every financial/structural field reproduced byte-for-byte.
- **Allowed paths (final):** the exactly-enumerated 7 fixed statistical leaves
  (`bootstrap.point_estimate/ci_lower/ci_upper`,
  `psr_diagnostic.observed_sharpe/skewness/kurtosis/psr`) **plus** exactly
  `paired_comparisons[0..4].mean_daily_paired_log_excess` = **12 leaves**; no wildcard fold
  index, no constant `benchmark_sharpe`, no financial field.
- **ULP cap:** `MAX_REPLAY_ULPS = 8` (observed 1–2 ULPs; bounded headroom; hard ceiling 32
  with committed evidence, never used).
- **Proof cap+1 fails:** `test_exactly_cap_plus_one_is_hard`,
  `test_same_relative_delta_but_millions_of_ulps_is_hard` (the old 8.9M-ULP hole is closed).
- **Proof a financial 1-ULP drift fails:** any non-allowlisted leaf is hard regardless of
  magnitude (`test_within_cap_drift_on_a_NON_allowed_leaf_is_hard`,
  `test_classifier_hard_fails_every_non_approved_mutation[financial-1ulp]`).
- **Comparator soundness:** `ulp_distance` is float-only (rejects bool/int/Decimal/str/None),
  finite-only (rejects NaN/±Inf), monotonic across signed zero / subnormal / exponent
  boundaries, with explicit sign/zero-crossing guards (`test_m3c_numerics.py`, 50 tests).

## 23. Reproduced-report rendering (Contract D)

The report rendered from the *reproduced* results equals the committed report
byte-for-byte after substituting the reproduced results-digest back to the committed one
(the report embeds `sha256(results)`, which avalanches under any ULP drift). Every `.6g`
statistic and financial table matches; unit-tested (`test_contract_d_*`).

## 24–31. Independent verification and adversarial results

- **Oracle** (`test_m3c_independent_oracle.py`, engine-only, no audited statistics/decision
  helpers): strict `(fold, timestamp)` alignment (no positional fallback); counts (1126);
  pooled point estimate = count-weighted per-fold means; 2/5 folds; block length 6, no seam
  crossing; interval straddles zero → P1 fails; PSR reproduces and is descriptive-only;
  independent P1–P7 vector = committed decision. **Pass.**
- **Causality / future-mutation** (`test_m3c_candidate.py`, `test_m3c_experiment.py`):
  prefix invariance, future-price mutation cannot change past targets, exact 63/252 horizons,
  next-open execution, context isolation, [0,1] exposure, no leverage/short. **Pass.**
- **Firewall** (`test_m3c_firewall.py`): research-train loader exposes no row beyond the
  boundary; the whole read-only surface leaves both ledgers byte-empty; the committed
  candidate never levers/shorts. **Pass.**
- **Strict parsing / publication / recovery / archive** (auditor C + suites): duplicate keys,
  NaN/Inf/1e999, bool-as-int/float, uppercase/malformed hashes, unsafe/symlink/traversal
  paths, non-UTC/naive timestamps (now rejected), lifecycle/ordering, transactional publish
  with readback-before-completed, calculation-free recovery. **No decode-repair at numeric
  boundaries. Pass.**
- **Regression:** M2B replay exit 0; M3A replay + recovery no-intent; M3B `replay --check`
  completed + deep archive + recovery no-intent; M3C `replay --check` completed +
  `verify_archive --deep` 15 checks + recovery no-intent. **Pass.**
- **Prohibited functionality:** AST/import scan finds no optimization/search/ML/leverage/
  shorting/exchange/wallet/credential/order-routing code; the only matches are the candidate's
  `shorting=False`/`leverage=False` declarations, cost-accounting `shortfall`, and honesty
  text ("no alpha claimed, no parameter optimized"). **Clean.**

## 32. Limitations (honest)

- One **in-sample research-train** measurement of **one adaptively-motivated** candidate;
  not out-of-sample, not gate/holdout evidence, not an alpha/significance/profitability claim.
- The byte-for-byte **financial** reproduction is scoped to the supported Linux/x86_64
  glibc CPython 3.12.3/3.12/3.13 envelope; fields such as `annualized_return` use a fractional
  `pow` and would need bounded-ULP treatment to widen the envelope (method note §8).
- `P5`/`P7` are structurally near-tautological for a valid results object (documented; the
  discriminating criteria are P1–P4/P6); `decision.py` is frozen to the immutable committed
  decision and is not changed.
- PSR is a fragile secondary descriptor (five folds + adaptive history); DSR/PBO omitted a
  priori. Costs are transparent deterministic proxies, not venue-calibrated.

## 33–35. Sealed access, git status, next action

- **No development-gate or final-holdout access.** Both sealed ledgers are byte-empty; the
  M3C data path loads research-train rows only, boundary-re-guarded.
- **Git status:** clean working tree; branch = `claude/m3c-adaptive-research-governance`;
  no tag; nothing merged into `main`; no history rewritten.
- **Exact next human action:** an independent reviewer confirms this audit, `git log
  a7640e3..HEAD`, the three read-only CLIs (`replay --check` → completed,
  `verify_archive --deep` → 15 checks, `recovery --status` → no-intent), the byte-empty
  ledgers, and the green final-head CI, then decides whether to take the mechanically
  **rejected** candidate to an independent development-gate review. **Do not merge, undraft,
  tag, or start M3D without that human decision.**
