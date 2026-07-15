# Milestone 3C — Independent Acceptance & Numerical Replay-Contract Closure — Plan

Read-only preflight recorded before any change. This plan governs an acceptance and
hardening pass over the **verifier, tests, CI, and non-immutable documentation** of the
one completed M3C run. It changes **no** immutable financial artifact, appends **no**
registry event, re-executes **no** candidate, and accesses **neither** sealed partition.

## 0. Verified starting state (read-only)

- Branch: `claude/m3c-adaptive-research-governance`; final HEAD **`5cdcd4a`**.
  - Note: the fresh container had checked the local branch out at an early ancestor
    (`2ba7cbc`); `git ls-remote` showed origin already at `5cdcd4a`. The local branch
    was brought to origin by a **pure `--ff-only` fast-forward** (`2ba7cbc` is an
    ancestor of `5cdcd4a`). No history was rewritten, reset, or force-pushed; local ==
    origin == `5cdcd4a`, tree clean.
- PR **#6** → base `main`: `state=open`, `draft=true`, `merged=false`, head `5cdcd4a`.
- Ten workflow runs at `5cdcd4a` (CI / M2B / M3A / M3B / M3C Replay, push + PR events):
  **all `success`**.
- Sealed ledgers byte-empty (both SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`):
  `research/m3a/development_gate_access.jsonl`, `research/m2b/test_evaluations.jsonl`.
- M3C registry lifecycle: exactly `registered → started → completed`; one experiment id
  `m3c-dual-horizon-trend-v1-run-001`; one candidate
  `dual_horizon_trend_63_252_vol_target_30d_50pct`; completed `promotion_status =
  rejected_for_development_gate_promotion`. No second candidate / experiment / retry /
  failed / run-002 / alternative budget.
- Budget: `max_new_candidate_families=1`, `permitted_primary_comparisons=1`,
  `development_gate_accesses_permitted=0`, `final_holdout_accesses_permitted=0`,
  `parameter_searches_permitted=0`, `strategy_fitting_permitted=false`,
  fingerprint `d45d3bdf7a3dca7003e8382995e5a350d0c9e61edf47e87e294d151070f4cae6`.
- Decision: `P1=False, P2=False, P3=True, P4=True, P5=True, P6=True, P7=True` →
  rejected. Bootstrap point `-0.00012686998005055427`, 95% CI
  `[-0.002305602394720637, +0.002169364466966667]` (straddles zero, lower ≤ 0).
  Candidate beats buy-and-hold in exactly **2/5** folds.
- Immutable artifact SHA-256 (recorded for before/after comparison):
  - `candidate_results.json`  `4db76efb923bc209e4354afabad897ea084ea2bbafb9e0f11b0a4a49961e00fc`
  - `candidate_decision.json` `f1b76101f2bb137036fd7b78c9d7ef2ad7a085b0e605ba0552bff939a9bdbc55`
  - `candidate_report.md`     `f0e776aecec3d91f3af5288bc54eaf9d4731c72516fd1075ffb8b5ef0d260e54`
  - `run-001/manifest.json`   `1fdf1f779732f48218aed8a9e851c8b1aa49bf73cb32b0e3233fe3d4dd4e7d47`
  - `experiment_registry.jsonl` `d31ceff78e7901095634a39ee3d2a45ea5d05070fcb92354172f3915916d46eb`
  - `research_budget.json`    `81706025850427f35aee70fcc1d135faa7ef68a9b4b48ee481ace5b7b47405af`
  - `protocol.json`           `86f2245cc3621bac85c80fa9b87ab3e0b87cc3d8ef7ff2dd00b4188b01c86be9`
  - `research_lineage.json`   `57cfd3a3aa180ab5c3b68b0da0cd11f0fcc99b3ea46f3c31b829e81f5e919f40`
- Lifecycle commit SHAs (from history, not prose): plan `f8d8096`; version `7869c5f`;
  freeze E `f79ce96`; register R `00fe212`; execute+publish P `c0e47b1`; findings
  `71aea1f`; post-run verifier `bf06427`; terminal audit `5cdcd4a`.
- Baselines: Python `3.12.3`; `ruff check` clean; `ruff format --check` clean (212
  files); `mypy src tests examples` clean (211 files); `uv lock --check` ok; `git diff
  --check` clean; M2B replay exit 0; M3A replay exit 0 + recovery `no-intent`; M3B
  `replay --check` completed + deep archive + recovery `no-intent`; M3C `replay --check`
  completed + `verify_archive --deep` (14 checks) + recovery `no-intent`. Full pytest:
  recorded at checkpoints.

## 1. What is being fixed (defects in the prior first-cut numerical contract)

The prior fix (`bf06427`) is directionally right — every financial field is exact, only
transcendental-derived statistical scalars are tolerated, and the verdict is re-checked
— but the *tolerance* and *allowlist* are too loose and the *docs* overclaim. Concrete
defects to reproduce (failing test first) then fix:

- **N1** — the docs say "four named scalars"; the predicate actually admits **12**
  leaves for the five-fold result: 7 fixed (`bootstrap.point_estimate/ci_lower/ci_upper`,
  `psr_diagnostic.observed_sharpe/skewness/kurtosis/psr`) + 5 per-fold
  `paired_comparisons[i].mean_daily_paired_log_excess`.
- **N2** — `math.isclose(rel_tol=1e-9, abs_tol=1e-12)` is *not* a last-ULP bound. Near
  `point_estimate` (~1.3e-4) the abs floor admits ~3.7e7 ULPs; near the fold-0 mean
  (~1.9e-3) the rel tol admits ~8.9e6 ULPs. Multi-million-ULP mutations classify as
  "tolerated" today.
- **N3** — the fold predicate matches **any** list index of the right shape, not only
  the exact expected fold indices 0..4.
- **N4** — the docs conflate transcendental functions (`log1p`, `erf`) with integer
  powers (not transcendental) and with percentile interpolation / floating reductions.
- **N5** — comparing "1e-9 relative tolerance" to the *magnitude* of the P1 threshold is
  dimensionally meaningless; remove it.
- **N6** — `verify_published_run` re-derives decision/report from the *committed* result
  object (Contract C). That does not prove raw-data → cross-machine reproduced result →
  rendered-report byte identity (Contract D).

## 2. Corrected contract (what will be built)

- **Exact finite-binary64 ULP distance** helper (`float` only; reject bool/int/Decimal/
  str/None; reject NaN/±Inf; monotonic ordering; signed-zero explicit; negatives
  correct; no rel/abs fallback). Fixed cap **`MAX_REPLAY_ULPS = 8`** (observed drift is
  1–2 ULPs; 8 gives bounded headroom). Raise only to ≤32 with committed workflow
  evidence and cap/cap+1 tests, never higher.
- Per tolerated field require **all**: exact approved JSON path; exact `float` type; both
  finite; same sign when committed ≠ 0; no zero crossing; ULP distance ≤ cap;
  independently re-derived criterion vector identical; final status exactly
  `rejected_for_development_gate_promotion`.
- **Structurally-exact allowlist** derived from the strict result schema: the fixed
  statistical paths that independent review confirms can vary, plus exactly
  `paired_comparisons[0..4].mean_daily_paired_log_excess`; no index outside 0..4, no
  wildcard, no similarly-named field elsewhere. Classify each candidate path A/B/C and
  prefer exact comparison for class C. Mutation tests for every permitted and adjacent
  unpermitted leaf (1/2/cap/cap+1 ULP, sign flip, zero cross, ±0, NaN/Inf, bool/int,
  deleted/extra field, wrong length, fold index 5, reordered folds, 1-ULP financial
  mutation, hash/decision/status mutation, criterion-vector mutation) — all non-approved
  cases hard-fail.
- **Separate contracts**: A financial/structural raw replay (exact); B bounded
  statistical replay (≤ cap ULPs, guarded); C committed-artifact consistency; **D**
  reproduced-report rendering (render from the *reproduced* result, compare to committed
  report; prove byte-identical on 3.12/3.13 and enforce, else add a strict semantic
  comparison and describe the limit honestly). Decision re-derived from reproduced
  results with no tolerance on booleans/status.
- CI annotation prints, per tolerated field: path, committed, reproduced, abs delta,
  exact ULP distance, configured cap, and whether it feeds any promotion criterion.
  Language: "bounded ULP variation", never "last-ULP identical" when cap > 1.

## 3. Independent verification to add (test-only, no production-helper reuse)

- Independent statistical oracle from committed return evidence: strict `(fold, ts)`
  alignment (no positional fallback), `log1p` paired excess, per-fold and pooled counts,
  point estimate, 2/5 fold wins, slow obviously-correct fold-stratified moving-block
  bootstrap (no seam crossing, preserved counts, seed 20260714, 20000 resamples,
  95%/2.5–97.5 percentile), exact integer block-length rule, straddle-zero, P1 fail,
  P2–P7 recompute, full criterion vector + rejection, PSR secondary-only.
- Causality/context/fold-isolation future-mutation oracle for the candidate; one-candidate
  budget + registry-lifecycle refusal-path inertness; sealed-partition firewall sentinels
  across every loader/strategy/engine/reducer/renderer/statistics path; strict
  decode-not-repair parser adversarial matrix; publication/recovery/archive failure
  injection and binding.
- Explicitly pin the percentile interpolation method and the block-length integer rule
  in production and prove committed output is unchanged.

## 4. Process, prohibitions, hard stops

- Small append-only commits (no amend/squash/rebase/reset/force-push); fast-forward push
  only; targeted tests during work, full battery at major checkpoints and final HEAD.
- Three independent **read-only** auditors after the contract corrections; reproduce
  every finding myself (failing test → root cause → minimal fix → tests → replay-neutral
  proof → bug-log → commit).
- **Absolute prohibitions**: no re-execution, no new authorization/registry event, no
  run-002/second candidate, no parameter/strategy change, no gate/holdout access, no
  ledger/immutable-artifact mutation, no silent erratum, no optimization/search/ML/
  leverage/short/exchange/live-trading, no merge/undraft/tag/branch-delete/history
  rewrite.
- **Hard stops**: nonempty sealed ledger; re-executed candidate; drifted immutable
  financial artifact; lifecycle other than the accepted one-shot; any sealed price/
  return/signal/fill/metric access; any Class A (financial/scientific) or Class D
  (sealed-access/budget/protocol) finding — stop and report with evidence, cross no
  boundary.

## 5. Deliverables

Corrected verifier + exact ULP contract + structural allowlist + Contract D; independent
oracle and adversarial suites; hardened M3C CI; corrected docs
(`M3C_STATISTICAL_METHOD_NOTE.md`, `M3C_BUG_LOG.md`, `M3C_FINDINGS.md`,
`M3C_TERMINAL_AUDIT.md`, README, docstrings, PR #6 body);
`docs/M3C_INDEPENDENT_ACCEPTANCE_AUDIT.md` with one of: ACCEPTED FOR HUMAN REVIEW —
CANDIDATE REJECTED / REJECTED — REMEDIATION REQUIRED / HARD STOP. Final-head CI green;
PR #6 remains open + draft (never merged, never tagged).
