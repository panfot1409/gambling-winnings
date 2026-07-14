# Milestone 3C — findings

One candidate, preregistered in full, executed once on the research-train
partition, and decided mechanically. The candidate did **not** clear the frozen
promotion bar.

- **Candidate:** `dual_horizon_trend_63_252_vol_target_30d_50pct` — a 63/252-day
  dual-horizon trend-consensus signal (long only when both the 63-day and the
  252-day momentum are positive) composed with the reviewed M3B 30-day / 50%
  annualized volatility target.
- **Experiment id:** `m3c-dual-horizon-trend-v1-run-001`
- **Outcome:** **`rejected_for_development_gate_promotion`**
- **Execution commit:** `59cdecea2728…`, package version `0.6.0`
- **Artifacts:** `research/m3c/candidate_results.json`, `candidate_decision.json`,
  `candidate_report.md`, `experiments/run-001/manifest.json`

## The decision (mechanical, frozen before execution)

The candidate is eligible **iff all seven** criteria pass. Two failed.

| criterion | requirement | observed | result |
| --- | --- | --- | :---: |
| P1 | primary 95% bootstrap CI lower bound > 0 (`causal_proxy_base`) | `[-0.00231, +0.00217]`, lower = `-0.00231` | **FAIL** |
| P2 | candidate marked return > buy-and-hold in ≥ 3/5 base folds | 2 / 5 | **FAIL** |
| P3 | candidate fold-median max drawdown no deeper than B&H | candidate `-23.1%` vs B&H `-61.5%` | PASS |
| P4 | candidate fold-median marked return > 0 (`causal_proxy_stressed`) | `+71.6%` | PASS |
| P5 | every candidate causal-scenario fold: terminal equity > 0, return > -1 | min equity `8115`, no ruin | PASS |
| P6 | causality / replay / archive / cross-runtime verification | verified | PASS |
| P7 | exactly one candidate, no parameter change, canonical primary | 1 candidate, bound | PASS |

The primary point estimate of the mean paired daily log-excess over buy-and-hold
is `-0.000127` with a fold-seam-aware 95% interval of `[-0.00231, +0.00217]` that
**straddles zero**, and the secondary (fragile, illustrative) Probabilistic Sharpe
is `0.458`. Neither supports promotion.

## Why it was rejected — the honest reading

The candidate is a **legitimate risk reducer that does not beat buy-and-hold on
this window.** Its per-fold, candidate-vs-B&H marked returns under
`causal_proxy_base`:

| fold | candidate | buy-and-hold | candidate wins |
| ---: | ---: | ---: | :---: |
| 0 | −14.70% | −44.98% | yes |
| 1 | +75.28% | +221.76% | no |
| 2 | +75.21% | +289.16% | no |
| 3 | +84.31% | +184.73% | no |
| 4 | −17.81% | −76.67% | yes |

The pattern is the textbook trend-following signature: the candidate **wins the two
drawdown folds** (0 and 4, cutting losses to roughly a third of B&H's) and **loses
the three strong-uptrend folds** (1, 2, 3, where it lags a market that mostly went
straight up). Over the five folds it is still solidly profitable (median marked
`+75%`) with **less than half** the drawdown of buy-and-hold (fold-median `-23%`
vs `-61%`), but it beats buy-and-hold in only 2 of 5 folds, and the day-by-day
paired excess is indistinguishable from zero. On an ETH sample this bull-heavy,
buy-and-hold is hard to beat, and the mechanical rule correctly declines to promote
a strategy whose primary edge over the comparator is not established.

**No parameter was changed to make it pass.** The candidate is retained, unchanged,
as rejected. This is the intended behavior of the governance layer: it reports the
truth rather than manufacturing a winner from an adaptively-motivated idea.

## What "rejected" (and "eligible") mean here

Even had all seven criteria passed, the result would have been **only**
`eligible_for_development_gate_review` — eligibility for an *independent* review at
the sealed development gate — never "validated", "significant", "alpha", or approval
to trade. This is a single **in-sample research-train** measurement of **one
adaptively motivated** candidate (its horizons, volatility target, costs, folds,
seed, and decision rule were all fixed before this one execution, but the *idea* was
motivated by the prior M3A/M3B trend results recorded in
`research/m3c/research_lineage.json`). Such a result cannot, on its own, establish
out-of-sample edge; the sealed development gate — never touched in M3C — is the
instrument that would. The costs are transparent deterministic liquidity proxies,
not a venue-calibrated model.

## Integrity of the run

- **Both sealed access ledgers remain byte-empty** (`development_gate_access.jsonl`
  and `test_evaluations.jsonl`, 0 bytes): the development gate and the final holdout
  were never accessed. M3C evaluated the research-train partition only.
- The registry is a clean hash chain `registered → started → completed`, and the
  `completed` event's `promotion_status` is the mechanical decision outcome.
- `python -m eth_research.m3c.replay --repo-root . --check` reports **completed**: on
  the execution host it reproduces every artifact byte-for-byte; on any other host it
  reproduces the decision and report byte-for-byte and every financial, structural, and
  cost field of the results byte-for-byte, requiring only a named handful of secondary
  statistical scalars (the bootstrap interval, the per-fold paired log-excess, the
  descriptive PSR) to agree to a tight relative tolerance — they are transcendental
  outputs (`log1p`, integer powers, `erf`) that IEEE-754 does not make cross-machine
  reproducible past a last ULP, and the reproduction is additionally required to yield
  the **identical mechanical verdict**, so the drift is provably decision-irrelevant
  (see `docs/M3C_STATISTICAL_METHOD_NOTE.md` §8).
  `python -m eth_research.m3c.verify_archive --repo-root . --deep` passes **14 checks**;
  the recovery finalizer reports `no-intent`.
- The pre-registration red team (three independent adversarial auditors) found no
  CRITICAL or HIGH defect; its findings and fixes are recorded in
  `docs/M3C_BUG_LOG.md`. The statistical method is fixed a-priori in
  `docs/M3C_STATISTICAL_METHOD_NOTE.md`.

## Reproduce

From a fresh clone on the locked runtime:

```bash
uv sync --locked --all-extras
python -m eth_research.m3c.replay --repo-root . --check          # -> completed
python -m eth_research.m3c.verify_archive --repo-root . --deep    # -> 14 checks
```
