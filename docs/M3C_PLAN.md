# Milestone 3C — Adaptive Research Governance & One Preregistered Trend-Consensus Experiment

Research-attempt lineage · one-candidate budget · paired fold-aware inference ·
deterministic replay · **sealed development gate and final holdout**.

M3C executes **exactly one** new preregistered experiment on the existing
research-train partition only. It never accesses the development gate or final
holdout. The purpose is to answer one narrow economic hypothesis honestly while
recording the project's entire adaptive research lineage — not to force a winner.

- Start branch `main` at `a7640e35c861e72413c9a0154e2ae3af0a075889`; work branch
  `claude/m3c-adaptive-research-governance`; version `0.6.0`.
- Draft PR to `main` only after implementation, preregistration, one execution,
  replay, red team, and CI are complete. **No merge, tag, or branch deletion.**

## 1. Economic hypothesis

A long-only ETH allocation that requires agreement between a **medium-horizon**
(63-day) and a **long-horizon** (252-day) positive absolute-momentum signal may
avoid some weak or counter-trend exposures, and volatility scaling to a 50% annual
budget may trim exposure in extreme-volatility regimes. This is a **conventional
trend / risk-management hypothesis**, not a claim the parameters are optimal.

## 2. Fixed candidate

`dual_horizon_trend_63_252_vol_target_30d_50pct` (the one permitted candidate,
fixed by the prompt — never replaced by something that looks better after seeing
results). At close `t`:

```
medium_positive_t  = close[t]/close[t-63]  - 1 > 0        # strict >, zero → False
long_positive_t    = close[t]/close[t-252] - 1 > 0        # strict >, zero → False
directional_t      = 1.0 if (medium_positive_t and long_positive_t) else 0.0
vol_scalar_t       = min(1.0, 0.50 / annualized_realized_vol_t)   # see §note
target_t           = directional_t * vol_scalar_t
```

Realized volatility: 30 completed close-to-close simple returns, window ending at
`close[t]`, sample std (`ddof=1`), annualized by `sqrt(365.25)`. Decision is formed
**after** `close[t]`, so it executes only at `open[t+1]`. No full-sample statistic,
no backfill, no centered window. Fixed constants: medium 63, long 252, vol lookback
30, annual target 50%, max exposure 1.0, min 0.0, drawdown breaker **disabled**,
**no turnover limiter**, shorting/leverage/borrowing forbidden, zero-momentum flat,
insufficient warm-up flat.

**Reuse note (proven, tested).** The candidate's directional signal is a new
`Strategy` emitting `directional_t`; the volatility scalar is the **reviewed M3B
`apply_volatility_target` overlay** (lookback 30, `ddof=1`, `sqrt(365.25)`, target
0.50). That overlay divides by `max(vol, 0.10)`; because the 0.10 floor sits below
the 0.50 target, the outer `min(1.0, ·)` makes it **numerically identical** to the
literal `min(1.0, 0.50/vol)` for every `vol ≥ 0` (scalar `1.0` for `vol ≤ 0.50`,
`0.50/vol` for `vol > 0.50`; `vol == 0 → 1.0` safe convention). A standing test
pins this equivalence. In the M3B engine, `signals[t]` executes at `open[t+1]` and
the overlay reads returns through `close[t]` — exactly the M3C timing. The engine,
accounting, solver, liquidity, cost model, metrics, and reconciliation are reused
**unmodified**; no new accounting engine is built.

## 3. Research-attempt lineage & historical adaptivity disclosure

`research/m3c/research_lineage.json` records every distinct **hypothesis family**,
bound to committed artifacts/hashes — not every corrective republication:

- Benchmarks (not candidate attempts): `cash`, `buy_and_hold`.
- Previously observed candidate families: `sma_20_50`, `donchian_55_20`,
  `vol_target_buy_and_hold_30d_50pct`, `vol_target_donchian_55_20_30d_50pct`.
- New M3C candidate: `dual_horizon_trend_63_252_vol_target_30d_50pct`.

M3A run-001/002/003 are **corrective reruns of one hypothesis set**, not three
discoveries; M3B's 75 cost/risk cells are **measurement cells**, not 75 discoveries.
The M3C candidate is **adaptively motivated** by earlier trend results — stated
plainly. Research-train inference alone does **not** establish out-of-sample alpha;
the sealed, independent development gate is what protects against this adaptive
history. Each entry records: lineage schema; hypothesis id; family id; canonical
fingerprint; first-eval milestone/experiment/commit; bound results hash;
parameterization; benchmark|candidate; promotion-tested?; observed/rejected/
ineligible; correction-vs-new-trial; prior-information relation; adaptivity notes.
Strict decode: unknown/missing/duplicate/forged/reordered/unsafe-path/bool-as-int/
NaN/Inf/dup-key/repaired inputs are rejected.

## 4. One-candidate research budget

`research/m3c/research_budget.json` → a strict `ResearchBudget`: milestone M3C; max
new candidate families **1**; permitted id `dual_horizon_trend_63_252_vol_target_30d_50pct`;
primary comparisons **1**; parameter searches **0**; sensitivity candidates **0**;
gate accesses **0**; holdout accesses **0**; strategy fitting **false**; post-result
parameter changes **false**; alpha **0.05**; bootstrap confidence **0.95**; decision
rule frozen before registration. The registry/orchestrator refuse a second
candidate, a re-fingerprinted candidate under the same name, changed
horizons/vol-lookback/target/costs/folds/seed/decision, a second primary comparison,
a rerun under another id, or any run after a `failed`/`started`/`completed`
lifecycle consumed the budget. **Budget is consumed at `started`** (crash/failed
included).

## 5. Data partition, folds, context

Research-train only: `2016-05-23 … 2022-06-21 UTC`, **2221 daily rows**. Exact
accepted M3A expanding-window OOS folds: initial info set **1095 rows**, **5 OOS
folds**, existing lengths/boundaries, no shuffle/overlap, gap 0, strategy fixed, no
fitting. Context: train/preceding history only, strictly before the first OOS open,
**≤ 252 bars**, no P&L, no metric contribution, exact seam validation (no
gap/overlap), no sort/repair.

## 6. Grid (benchmark grid around one candidate)

5 strategies × 3 costs × 5 folds = **75 cells**. Strategies: `cash`,
`buy_and_hold`, `donchian_55_20`, `vol_target_donchian_55_20_30d_50pct`, and the new
`dual_horizon_trend_63_252_vol_target_30d_50pct` (item 5 only is new). Costs
(unchanged from M3B): `compatibility_v1`, `causal_proxy_base`, `causal_proxy_stressed`.
Initial cash 10,000 USD independently per cell.

## 7. Primary endpoint (frozen before execution)

Under **`causal_proxy_base`** on the fixed OOS folds: does the candidate produce
positive paired **daily log-return excess over `buy_and_hold`** with a fold-seam-aware
**95%** bootstrap interval whose **lower bound > 0**? Per evaluated day
`paired_log_excess_t = log(1+cand_net_t) − log(1+bnh_net_t)` (reject any return ≤ −1
before logs). Primary statistic: mean paired daily log excess across OOS days.
Primary interval: fold-stratified moving-block bootstrap, blocks never crossing a
fold seam, fixed block length, fixed deterministic seed, ≥ 10,000 resamples,
percentile interval — method fixed before execution. No compat/stressed as alternate
primary; no switching to Sharpe/CAGR/DD/median on failure.

## 8. Promotion-eligibility rule (mechanical, frozen)

Mark `eligible_for_development_gate_review` **iff** all pass (else
`rejected_for_development_gate_promotion`):
- **P1** primary 95% lower bound > 0 (causal_proxy_base);
- **P2** candidate marked total return > B&H in ≥ 3 of 5 folds (base);
- **P3** candidate fold-median max drawdown ≤ B&H fold-median max drawdown (base);
- **P4** candidate fold-median marked total return > 0 (stressed);
- **P5** every candidate fold terminal marked equity > 0; no fold return ≤ −1; no
  accounting-invariant violation;
- **P6** every causality/replay/archive/cross-runtime check passes;
- **P7** exactly one new candidate; no parameter changed; no alternate primary
  endpoint inspected for promotion.

Eligible means **only** "eligible for independent development-gate review" — not
gate-authorized, promoted, validated, alpha-proven, holdout-ready, or approved for
trading. The decision is generated mechanically from committed results + frozen rule.

## 9. Secondary diagnostics (descriptive only; cannot rescue a failed primary)

Total return, CAGR, Sharpe, Sortino, max drawdown, turnover, fills, partial/no-fill
counts, avg exposure, fee/spread/slippage/impact totals, liquidation equity, fold
win count, fold-median/worst/best fold, daily-return vol, downside deviation, paired
excess vs Donchian baselines; plus a **Probabilistic Sharpe Ratio** diagnostic (with
an explicit fragility warning: 5 folds + adaptive history). **PBO/CSCV omitted** — 5
folds cannot support a credible combinatorial-overfitting claim (documented, not
faked). No significance claimed from one adaptive-dataset bootstrap.

## 10. Statistical implementation

Cited in `docs/M3C_STATISTICAL_METHOD_NOTE.md`. Paired return alignment; exact fold
membership; fold-stratified moving-block resampling; deterministic RNG; no block
crossing a seam; no stitching independently-reset fold portfolios into one equity
curve; no stitched CAGR/drawdown; no irregular-timestamp annualization; no IID
bootstrap as primary; undefined ratios → `null` with reason; finite-only. Verified
against an independent slow bootstrap oracle on a small fixture. A hierarchical
fold-resampling sensitivity may appear **only** as a labeled secondary robustness
diagnostic.

## 11. Registry lifecycle

`research/m3c/experiment_registry.jsonl`, strict append-only hash-chained
`registered → started → (completed|failed)`. Id `m3c-dual-horizon-trend-v1-run-001`;
family `m3c-dual-horizon-trend-v1`. `registered` binds id/family, candidate
id/fingerprint, protocol/lineage/budget paths+hashes, dataset/dossier, partition,
folds, costs, bootstrap, decision rule, runtime, source-tree fingerprint,
registration commit, execution-source commit, result paths, both sealed-ledger
hashes, package version. Single-use: registered/started/terminal once; any `started`
consumes it; no alternate/copied/symlinked registry, no second id, no overwrite
escape. No calculation before `started` is durably appended.

## 12. Publication / recovery / archive

Generalize the reviewed M3B durable `CompletionIntent` + calculation-free `recovery`
finalizer + transactional byte-readback publication + immutable per-run archive +
size-bounded replay-reconstructible execution-trace commitments. Artifacts under
`research/m3c/` (README, lineage, budget, protocol, registry, candidate_results,
candidate_report, candidate_decision, `experiments/run-001/manifest.json` +
`immutable/…`). All schemas strict (exact keys, no dup keys, no type repair, bool≠int,
finite, canonical order, safe relative paths, no symlinks, trailing newline,
deterministic JSON, byte-stable replay). Every aggregate reconciles from
fold/cell primitives before publication.

## 13. Isolated package layout

`src/eth_research/m3c/`: `validation, lineage, candidate, protocol, strategy,
statistics, results, registry, archive, publication, recovery, experiment,
orchestrator, replay, decision, cli`. Reuse M3B accounting/execution unmodified; do
not modify the M3B engine unless a genuine inherited defect is first reproduced (any
inherited fix must prove M3B run-001 byte-identical). Frozen M2B/M3A/M3B artifact
package versions untouched; older artifacts still parse and reproduce.

## 14. Tests

Causality (§7 causality tests: prefix invariance, future price/volume mutation
inertness, exact 63/252 horizons, vol-through-close[t], no same-bar fill, open[t+1]
fill, warm-up flat, zero-momentum flat, index equality, finite [0,1] target, flat
directional ⇒ 0 regardless of vol, scalar ≤ 1, zero-vol safe convention, context
strictly-before / zero-P&L, no fold-boundary backward leak, no sealed row); statistics
(hand paired diffs, block membership, seam-crossing impossibility, deterministic seed,
degenerate/all-pos/all-neg, single-obs rejection, wrong labels, reordered, dup
timestamps, future mutation, cross-runtime byte identity, slow-oracle agreement);
strict-model round-trips + malformed-input rejection; registry single-use + crash
recovery; archive/trace tamper; dual-state replay; standing disposable-clone E2E.
Independent scalar-loop oracles, not self-comparison.

## 15. Freeze → Register → CI → Execute

- **E (code freeze):** all code+tests done; no real registry event/results/report;
  ledgers empty; local gates green; push; **all branch CI green**; record E.
- **R (registration):** append exactly one `registered` event binding execution
  source E; R commit contains only the registry line (+ mechanical index/manifest,
  no run-affecting change); `git diff E..R` proves no source/protocol/strategy/
  statistic/threshold/cost/doc change; push; CI green; record R.
- **P (execution):** only after R pushed + CI-green; verify clean tree, source==E,
  registry==R, runtime, lineage/budget/protocol, ledgers empty; append `started`;
  execute once; reconcile; completion intent; transactional publish; read back;
  append `completed`; remove intent; archive. P commit contains only lifecycle
  lines + results/report/decision/archive/trace/evidence + mechanical
  indexes/manifests; no source/protocol change in E..P. On a code defect at
  execution: append `failed`, stop — do **not** patch-and-rerun under the same id;
  budget consumed.

## 16. Replay & CI

`.github/workflows/m3c-replay.yml`: authoritative CPython 3.12.3 + 3.12/3.13
compatibility; full-SHA-pinned actions; hash-pinned uv; locked sync; read-only perms;
no network/exchange host; no secrets; no contents write; no installer pipe.
Dual-state: before P verify code/protocol/lineage/budget/registered + ledgers empty
+ no results; after P rebuild from committed raw, reproduce results/report/decision
byte-for-byte, verify registry/archive/evidence + one-candidate budget + ledgers
empty + no M2B/M3A/M3B drift. Standing disposable-clone E2E restores to E/R and runs
the lifecycle without consuming the real id. CI never reruns the real completed run.

## 17. Red team (3 independent read-only auditors)

A1 causality/strategy; A2 statistics/adaptivity; A3 registry/publication/firewall.
Reproduce every finding before fixing. Classes: A exploitable research-integrity, B
reproducibility/statistical, C doc/overclaim, D financial-drift/sealed-access (D =
HARD STOP). Log `docs/M3C_BUG_LOG.md`.

## 18. Report (`candidate_report.md`) leads with the decision

States: research-train only; in-sample development evidence; one adaptive candidate;
prior related strategies already observed; no gate/holdout access; no alpha/live
claim; parameters fixed before execution; no optimization; exact promotion rule +
which components passed/failed; accept/reject mechanical; all losing folds; all cost
totals; partial/no-fill diagnostics; limitations. Never says proven/profitable/
production-ready/validated/robust/statistically-significant. A failed candidate's
rejection is visually prominent and committed unchanged. A pass says only "eligible
for independent development-gate review" and that the gate remains sealed.

## 19. Commit sequence

1 plan · 2 version 0.6.0 · 3 lineage · 4 budget · 5 candidate+causality tests ·
6 protocol+decision rule · 7 statistics · 8 results+decision models · 9 registry+
intent+publication+recovery · 10 archive+trace · 11 replay+dual-state CI · 12
pre-registration red team · 13 freeze E · 14 register R · 15 execute P · 16 post-run
red team · 17 findings · 18 terminal audit · 19 draft PR. No amend/rebase/squash/
force-push.

## 20. Hard stops

main not at the expected merge commit; dirty pre-branch tree; nonempty sealed
ledger; any accepted M2B/M3A/M3B immutable hash differs; existing replay red; a
candidate parameter must change to make it "work"; any path reaches the gate/holdout;
> 1 candidate; execution before registration is pushed+CI-green; registered ≠
execution protocol; result changes between authoritative and compatibility replay; a
cell dropped/repaired/replaced; noncausal signal; test needs current/future
volume/price/return/vol/equity; existing financial artifact changes; registry can't
prove single use; crash leaves ambiguous state not resolvable calculation-free; CI
fails unexplained; an auditor finds sealed access; the only way forward is a new
question or second candidate. On a hard stop: preserve state, deliver an incident
report, do not improvise a new candidate.
