# Milestone 3C — Statistical Method Note

This note fixes, **before code freeze E and before any candidate output is
calculated**, the exact estimator, resampling scheme, and secondary diagnostics used
to answer the one preregistered M3C question, with primary-literature citations. All
constants are a-priori and independent of any observed strategy result.

## 1. Primary endpoint (frozen)

Under the `causal_proxy_base` cost scenario, on the fixed research-train walk-forward
OOS folds, for the candidate `dual_horizon_trend_63_252_vol_target_30d_50pct` vs the
`buy_and_hold` comparator, for each evaluated candidate OOS day `t`:

```
paired_log_excess_t = log1p(candidate_net_return_t) − log1p(buy_and_hold_net_return_t)
```

Any net return `≤ −1` is rejected before the logarithm (an all-capital loss cannot be
log-transformed). Observations are aligned **exactly by (fold, timestamp)** — the
candidate and buy-and-hold daily returns within a fold must carry the identical
timestamp index; a mismatch is a hard error, never a positional fallback.

**Primary statistic:** the mean paired daily log-excess, pooled across all OOS days.

**Promotion-relevant condition (P1):** the two-sided 95% bootstrap interval's lower
bound is strictly `> 0`.

Log returns are used because they are additive across time and because a paired
*log* excess is symmetric and finite whenever both gross returns are positive — the
appropriate scale for comparing two long-only equity processes day by day.

## 2. Primary interval — fold-stratified moving-block bootstrap

Daily returns are serially dependent and the five OOS folds are *independently reset*
portfolios (each fold restarts from 10,000 USD with no carry-over), so neither an IID
bootstrap nor a single stitched equity curve is valid. We use a **fold-stratified
moving-block bootstrap**:

- Resampling is done **within each fold only**, so a block never crosses an
  independently-reset fold seam.
- Blocks are **circular moving blocks** (Politis & Romano, 1992, "A circular
  block-resampling procedure for stationary data") of a fixed length that preserves
  short-range daily dependence.
- **Block length** per fold is the committed a-priori rule `L = floor(n**(1/3))` of
  that fold's observation count `n` — the standard `n^{1/3}` optimal-rate order for
  block bootstraps of the mean (Hall, Horowitz & Jing, 1995, "On blocking rules for
  the bootstrap with dependent data", *Biometrika* 82(3)). For the ~225-day folds
  this gives `L = 6`. The rule depends only on fold length, never on any observed
  return.
- Each fold keeps its **exact observation count** in every resample.
- The resampled per-fold contributions are **pooled only for the mean statistic**. No
  stitched equity curve, CAGR, drawdown, or annualized figure is ever bootstrapped.
- **Deterministic RNG:** NumPy `default_rng` (PCG64) seeded with `20260714`; folds are
  visited in a fixed order so the draw sequence — and therefore the interval — is
  byte-reproducible across the 3.12/3.13 runtimes.
- **Resamples:** `20,000`. **Interval:** two-sided 95% percentile
  (2.5th / 97.5th percentiles of the resampled means).

An independent, deliberately-naive per-observation reference bootstrap
(`slow_reference_bootstrap`) is used in tests to confirm the vectorized implementation.
The pooled point estimate is exact (not resampled), so the fast and slow
implementations agree on it to machine precision and agree on the interval to within
Monte-Carlo error.

## 3. Secondary diagnostic — Probabilistic Sharpe Ratio (PSR)

Reported **descriptively only**; it never affects the promotion decision. PSR (Bailey
& López de Prado, 2012, "The Sharpe Ratio Efficient Frontier", *Journal of Risk* 15(2))
estimates the probability that the true Sharpe ratio of a return series exceeds a
benchmark `SR*` under a non-normal (skew/kurtosis-adjusted) estimator:

```
PSR(SR*) = Φ( (SR_hat − SR*) · sqrt(N − 1) / sqrt(1 − γ3·SR_hat + (γ4 − 1)/4 · SR_hat²) )
```

- `SR_hat` = sample Sharpe of the per-day paired log-excess (mean / sample std, `ddof=1`);
- `SR*` = 0 (probability the true excess Sharpe is positive);
- `N` = number of paired daily observations;
- `γ3` = standardized third moment (skewness), `γ4` = standardized fourth moment
  (kurtosis), both computed on the standardized series (non-bias-corrected moments,
  as in the estimator's derivation);
- `Φ` = standard normal CDF.

**Serial-dependence limitation:** PSR assumes IID observations. Daily returns are not
IID, so PSR here is an *optimistic, illustrative* figure, not an inferential claim. It
is secondary precisely because the primary interval (§2) is the dependence-aware test.

## 4. Deflated Sharpe Ratio — omitted, on purpose

The Deflated Sharpe Ratio (Bailey & López de Prado, 2014, "The Deflated Sharpe Ratio",
*Journal of Portfolio Management* 40(5)) deflates PSR by the number of independent
trials. A faithful DSR needs an explicit, defensible trial-count model. Our lineage
(`research/m3c/research_lineage.json`) records **five** distinct candidate families
across M3A/M3B/M3C, but these were not an i.i.d. search over a known configuration
space, and mapping this adaptive history to an effective trial count `N` would be a
guess. A fabricated-precision DSR would be **worse than no number**, so DSR is
deliberately **not implemented**. The honest statement is qualitative: the candidate
is adaptively motivated, so even a passing primary is only eligibility for independent
gate review.

## 5. PBO / CSCV — omitted, on purpose

The Probability of Backtest Overfitting via Combinatorially-Symmetric Cross-Validation
(Bailey, Borwein, López de Prado & Zhu, 2017, "The Probability of Backtest
Overfitting", *Journal of Computational Finance* 20(4)) requires partitioning many
performance observations into a large number of combinatorial train/test splits. With
only **five** folds the number of usable splits is far too small for a credible PBO
estimate; computing one would invite over-interpretation of noise. PBO/CSCV is
therefore **not implemented**, and this omission is documented rather than faked.

## 6. Multiple-testing honesty

No familywise-significance claim is made across the full adaptive project history. The
primary bootstrap interval is a single, dependence-aware statement about one candidate
on one research-train dataset chosen after seeing related trend results. It cannot, on
its own, establish out-of-sample alpha; the sealed, independent development gate — not
touched in M3C — is the instrument that would. A passing primary yields **only**
`eligible_for_development_gate_review`, never "validated", "significant", or "alpha".

## 7. Constants (recorded in `research/m3c/protocol.json`)

| constant | value |
| --- | --- |
| primary scenario | `causal_proxy_base` |
| primary comparator | `buy_and_hold` |
| primary statistic | mean paired daily log-excess |
| bootstrap algorithm | `fold-stratified-moving-block-v1` |
| block-length rule | `floor(n**(1/3))` per fold |
| bootstrap seed | `20260714` |
| resamples | `20000` |
| interval | two-sided 95% percentile |
| decision alpha | `0.05` |

## 8. Cross-machine numerical reproducibility (post-run, empirically observed)

IEEE-754 mandates *correctly-rounded* results only for `+ - * /` and `sqrt`. It does
**not** mandate correct rounding for the transcendental library functions, so a
conforming `log1p`, integer power (`x**3`, `x**4`), or `erf` may return a value whose
last unit-in-the-last-place (ULP) differs between libm builds and CPU
microarchitectures (the "table-maker's dilemma"). This is a property of portable
floating point, not a defect.

Every **financial** figure in `candidate_results.json` is produced by the reviewed
M3B backtest engine, which reproduces byte-for-byte across machines — the green
`m3b-replay` CI on independent GitHub runners is the standing proof. The **only**
result fields that carry a transcendental in their derivation are the M3C-new
secondary statistics:

| field(s) | transcendental path |
| --- | --- |
| `bootstrap.point_estimate` / `ci_lower` / `ci_upper` | `np.log1p` (paired excess) → mean / percentile |
| `paired_comparisons[*].mean_daily_paired_log_excess` | `np.log1p` |
| `psr_diagnostic.observed_sharpe` / `skewness` / `kurtosis` | `np.log1p` series → integer-power moments |
| `psr_diagnostic.psr` | `math.erf` |

Empirically, the values committed by the one execution (on its host) and the values a
fresh clone recomputes on a different host agree to roughly `1e-13` relative — a last
ULP or two. The replay (`eth_research.m3c.replay`) therefore enforces the honest
reproducibility contract:

- **every** financial, structural, provenance, and cost field must reproduce
  **byte-for-byte**, on any machine;
- the named statistical scalars above must agree to a tight relative tolerance
  (`1e-9`, with a `1e-12` absolute floor) — about six orders of magnitude tighter than
  the P1 decision threshold, whose magnitude is ~`2.3e-3`;
- any other difference, or a statistical scalar exceeding that tolerance, **fails
  closed** (the replay lists the exact offending fields as a CI annotation);
- and the raw-data reproduction must re-derive the **identical mechanical promotion
  verdict** (the same per-criterion pass/fail vector), so the tolerated drift is proven
  decision-irrelevant, not merely small.

The decision and the human-readable report are byte-unaffected regardless: the report
prints these statistics at `.6g` (six significant figures, far coarser than the
~13th-figure drift), and the mechanical decision depends only on the **sign** of
`bootstrap.ci_lower` (P1), which is `-2.3e-3` — nine orders of magnitude from a sign
flip. On the execution host itself, the orchestrator's independent second rebuild (the
P6 determinism gate) still requires bit-for-bit identical output, so same-host
non-determinism remains a hard failure.

This is deliberately a *stronger* honesty posture than a blanket "bit-identical on all
hardware" claim, which no numerically-literate reviewer would accept for `erf` or
`log1p`. The discovery and its resolution are recorded in `docs/M3C_BUG_LOG.md`.
