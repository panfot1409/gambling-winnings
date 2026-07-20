# V2A candidate design review (pre-registration, read-only)

This document is committed **before** any candidate is evaluated. It fixes the three genuinely
distinct long-only spot candidate families V2A will evaluate **exactly once** on the authorized M3A
research-train partition (2016-05-23 … 2022-06-21 UTC, 2221 daily rows), and records the economic
rationale and primary-source grounding for each. Nothing here reports a result; results exist only
after the one-shot execution, and at most one family may then be nominated
`eligible_for_development_gate_review`.

## Design discipline

- **Long-only spot only.** No shorting, leverage, borrowing, margin, or derivatives. Exposure is a
  fraction in `[0, 1]` of a single spot ETH position; the rest is uninvested cash.
- **Distinct mechanisms.** The three families use economically different signals — a trend-regime
  gate, a contrarian mean-reversion accumulator, and a trend-agnostic risk overlay — so a null
  result in one does not predetermine the others.
- **Not a relabel of the rejected M3C candidate.** The M3C candidate
  `dual_horizon_trend_63_252_vol_target_30d_50pct` was permanently
  `rejected_for_development_gate_promotion`. None of the V2A families is that candidate reparameterized:
  a machine-checkable similarity guard (bound to the M3C fingerprint) rejects any family that
  collides with it.
- **Adaptive-history honesty.** Trend and volatility ideas were explored in earlier milestones
  (M3A SMA/Donchian, M3C dual-horizon trend with volatility targeting). V2A records this lineage
  honestly; research-train inference never establishes out-of-sample edge, which is exactly why the
  strongest thing V2A can emit is a *request* for a later, independent development-gate review.
- **Pre-registration.** Each family's parameters are fixed here and frozen in code before the
  one-shot evaluation; the nomination rule (a later phase) is also pre-registered.

## Family 1 — `meanrev_zscore_accumulation` (contrarian mean reversion)

- **Mechanism.** Compute a rolling z-score of price against its own moving average. Increase spot
  exposure when the z-score is negative (oversold / price below its mean) and reduce it when the
  z-score is positive (overbought). Exposure is a bounded, monotone-decreasing function of the
  z-score, clipped to `[0, 1]`.
- **Economic rationale.** Short-horizon reversal: sharp drawdowns in a liquid asset are partially
  retraced. This is the opposite economic bet to trend following and is the family least explored in
  prior milestones.
- **Primary-source grounding.** Classic short-horizon reversal / overreaction literature
  (e.g. Jegadeesh 1990; De Bondt & Thaler 1985) adapted to a single-asset long-only accumulator.

## Family 2 — `vol_scaled_hold_drawdown_guard` (trend-agnostic risk overlay on passive hold)

- **Mechanism.** Start from full passive exposure and scale it by the ratio of a target volatility to
  trailing realized volatility (capped at 1.0, never levered above spot), then apply a drawdown
  circuit-breaker that cuts exposure once the position's peak-to-trough decline exceeds a threshold,
  restoring it as the drawdown heals. There is **no directional trend signal**.
- **Economic rationale.** Volatility control and drawdown management can improve the risk profile of
  a passive long without forecasting direction; the family isolates the risk-overlay hypothesis from
  any timing signal.
- **Primary-source grounding.** Volatility targeting / risk control literature (e.g. Moreira &
  Muir 2017 on volatility-managed exposure), restricted to long-only, never levered.

## Family 3 — `trend_regime_single_horizon` (single-horizon binary trend gate)

- **Mechanism.** Hold full spot exposure when price is above a single long-horizon moving average
  (a single trend filter), and hold cash otherwise — a binary, single-horizon participation gate.
  There is **no second horizon and no volatility-targeting overlay**, which is what distinguishes it
  from the rejected dual-horizon-plus-vol-target M3C candidate.
- **Economic rationale.** Trend persistence: participating only in established up-trends can avoid the
  deepest bear phases. The binary single-horizon form is the simplest expression of the hypothesis.
- **Primary-source grounding.** Faber (2007), *A Quantitative Approach to Tactical Asset Allocation*
  — the long-only moving-average timing rule — as a single-asset participation gate.

## What a "pass" would and would not mean

A family that meets its pre-registered research-train rule earns at most `research_stage_supported`
and, if it is the single best-qualifying family, a nomination `eligible_for_development_gate_review`.
Neither is an out-of-sample, forward, live, or profitability claim. Every family may also simply be
`research_stage_rejected`; nominating none is a valid, honest success. The development gate and final
holdout that would actually test these hypotheses out-of-sample are never touched in V2A.
