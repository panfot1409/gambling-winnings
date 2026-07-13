# Milestone 3A development walk-forward report

## 1. Research-only disclaimer

> Research observations on historical data — **not** a profitability claim, **not** expected future returns, and **not** investment advice. No alpha is claimed; the fixed parameters were never optimized.

## 2. Data-access boundaries

| level | dates (UTC) | rows | M3A access |
| --- | --- | ---: | --- |
| research train | 2016-05-23 .. 2022-06-21 | 2221 | evaluated |
| development gate | 2022-06-22 .. 2024-06-30 | 740 | **not evaluated (forbidden)** |
| final holdout | 2024-07-01 .. 2026-07-11 | 741 | **not evaluated (forbidden)** |

## 3. Proof the gate and holdout were not evaluated

- Development-gate access ledger events: **0** (byte-empty).
- Final-holdout ledger events: **0** (byte-empty).
- Every strategy and backtest received only research-train rows (through 2022-06-21); the firewall rejects any later row.

## 4. Walk-forward methodology

Expanding-window walk-forward on the research-train partition: 1095 initial training rows, five contiguous OOS folds over the remaining 1126 rows (226, 225, 225, 225, 225), information gap 0 bars, context <= 55 bars, each fold reset to an independent 10,000 USD. Independent resets are a comparison device, **not** one continuously traded portfolio.

## 5. Fold table

| fold | training rows | context rows | OOS rows | OOS window |
| ---: | ---: | ---: | ---: | --- |
| 0 | 1095 | 0 | 226 | 2019-05-23 .. 2020-01-03 |
| 1 | 1321 | 0 | 225 | 2020-01-04 .. 2020-08-15 |
| 2 | 1546 | 0 | 225 | 2020-08-16 .. 2021-03-28 |
| 3 | 1771 | 0 | 225 | 2021-03-29 .. 2021-11-08 |
| 4 | 1996 | 0 | 225 | 2021-11-09 .. 2022-06-21 |

## 6. Cost scenarios

Every strategy is evaluated under all three predeclared scenarios; none is selected after seeing results. base 0.10%/0.05%, stressed 0.20%/0.10%, severe 0.50%/0.25% (fee/slippage). No frictionless scenario.

## 7. Per-fold results

Marked total return per (fold, strategy) at each cost scenario.

### Cost scenario: base

| strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| buy_and_hold | -44.95% | +221.91% | +289.30% | +184.82% | -76.66% |
| sma_20_50 | -22.32% | +110.84% | +263.56% | +118.34% | -25.92% |
| donchian_55_20 | -9.68% | +90.93% | +159.22% | +43.53% | -17.54% |

### Cost scenario: stressed

| strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| buy_and_hold | -45.03% | +221.42% | +288.72% | +184.39% | -76.69% |
| sma_20_50 | -23.02% | +109.27% | +261.93% | +116.71% | -26.58% |
| donchian_55_20 | -9.95% | +90.08% | +158.06% | +42.46% | -17.78% |

### Cost scenario: severe

| strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| buy_and_hold | -45.28% | +219.99% | +286.98% | +183.12% | -76.80% |
| sma_20_50 | -25.07% | +104.61% | +257.08% | +111.89% | -28.54% |
| donchian_55_20 | -10.75% | +87.53% | +154.60% | +39.29% | -18.52% |

## 8. Independent-fold summary


### Cost scenario: base

| strategy | median marked | median liq | worst liq fold | best marked | median Sharpe | worst maxDD | fills | frac positive | frac > B&H | frac > cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | undefined | +0.00% | 0 | 0.00 | 0.40 | 0.00 |
| buy_and_hold | +184.82% | +184.39% | -76.69% | +289.30% | 2.108 | -79.38% | 5 | 0.60 | 0.00 | 0.60 |
| sma_20_50 | +110.84% | +110.53% | -25.92% | +263.56% | 1.801 | -61.47% | 25 | 0.60 | 0.40 | 0.60 |
| donchian_55_20 | +43.53% | +43.32% | -17.54% | +159.22% | 1.163 | -41.62% | 15 | 0.60 | 0.40 | 0.60 |

### Cost scenario: stressed

| strategy | median marked | median liq | worst liq fold | best marked | median Sharpe | worst maxDD | fills | frac positive | frac > B&H | frac > cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | undefined | +0.00% | 0 | 0.00 | 0.40 | 0.00 |
| buy_and_hold | +184.39% | +183.54% | -76.76% | +288.72% | 2.106 | -79.41% | 5 | 0.60 | 0.00 | 0.60 |
| sma_20_50 | +109.27% | +108.64% | -26.58% | +261.93% | 1.789 | -61.47% | 25 | 0.60 | 0.40 | 0.60 |
| donchian_55_20 | +42.46% | +42.03% | -17.78% | +158.06% | 1.147 | -41.71% | 15 | 0.60 | 0.40 | 0.60 |

### Cost scenario: severe

| strategy | median marked | median liq | worst liq fold | best marked | median Sharpe | worst maxDD | fills | frac positive | frac > B&H | frac > cash |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | undefined | +0.00% | 0 | 0.00 | 0.40 | 0.00 |
| buy_and_hold | +183.12% | +181.00% | -76.97% | +286.98% | 2.100 | -79.50% | 5 | 0.60 | 0.00 | 0.60 |
| sma_20_50 | +104.61% | +103.08% | -28.54% | +257.08% | 1.751 | -61.47% | 25 | 0.60 | 0.40 | 0.60 |
| donchian_55_20 | +39.29% | +38.25% | -18.52% | +154.60% | 1.099 | -41.97% | 15 | 0.60 | 0.40 | 0.60 |

## 9. Pooled reset-OOS

The concatenated daily OOS return observations from the five independent folds — labelled `pooled_reset_oos`. This is **not** a continuously tradable portfolio: fold terminal equities are never multiplied as if capital carried, each fold pays its own reset entry cost, and it is not untouched-test performance.

### Cost scenario: base

| strategy | obs | mean daily | volatility | Sharpe | Sortino | worst daily | ES 5% | reset-path maxDD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | 1126 | +0.00% | 0.0000 | undefined | undefined | +0.00% | +0.00% | +0.00% |
| buy_and_hold | 1126 | +0.27% | 0.0506 | 1.009 | 1.446 | -43.32% | -11.35% | -79.38% |
| sma_20_50 | 1126 | +0.29% | 0.0416 | 1.339 | 1.942 | -43.32% | -9.93% | -62.03% |
| donchian_55_20 | 1126 | +0.20% | 0.0321 | 1.190 | 1.775 | -27.61% | -8.00% | -41.62% |

### Cost scenario: stressed

| strategy | obs | mean daily | volatility | Sharpe | Sortino | worst daily | ES 5% | reset-path maxDD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | 1126 | +0.00% | 0.0000 | undefined | undefined | +0.00% | +0.00% | +0.00% |
| buy_and_hold | 1126 | +0.27% | 0.0506 | 1.006 | 1.442 | -43.32% | -11.35% | -79.41% |
| sma_20_50 | 1126 | +0.29% | 0.0416 | 1.324 | 1.919 | -43.32% | -9.93% | -62.37% |
| donchian_55_20 | 1126 | +0.20% | 0.0322 | 1.178 | 1.756 | -27.61% | -8.01% | -41.71% |

### Cost scenario: severe

| strategy | obs | mean daily | volatility | Sharpe | Sortino | worst daily | ES 5% | reset-path maxDD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | 1126 | +0.00% | 0.0000 | undefined | undefined | +0.00% | +0.00% | +0.00% |
| buy_and_hold | 1126 | +0.26% | 0.0506 | 0.999 | 1.431 | -43.32% | -11.35% | -79.50% |
| sma_20_50 | 1126 | +0.28% | 0.0416 | 1.278 | 1.851 | -43.32% | -9.93% | -63.37% |
| donchian_55_20 | 1126 | +0.19% | 0.0322 | 1.142 | 1.699 | -27.61% | -8.04% | -41.97% |

## 10. Full-train exploratory results

The complete research-train period evaluated once, in-sample — labelled `exploratory_in_sample_full_train`. Never mixed with the walk-forward OOS results; in-sample numbers overstate what OOS delivers.

### Cost scenario: base

| strategy | marked return | liq return | CAGR | Sharpe | maxDD | fills | exposure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | undefined | +0.00% | 0 | 0.00 |
| buy_and_hold | +8003.64% | +7991.49% | +106.01% | 1.210 | -94.01% | 1 | 1.00 |
| sma_20_50 | +40393.85% | +40393.85% | +168.41% | 1.608 | -68.87% | 38 | 0.52 |
| donchian_55_20 | +11009.98% | +11009.98% | +116.98% | 1.427 | -69.62% | 26 | 0.38 |

### Cost scenario: stressed

| strategy | marked return | liq return | CAGR | Sharpe | maxDD | fills | exposure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | undefined | +0.00% | 0 | 0.00 |
| buy_and_hold | +7991.51% | +7967.25% | +105.96% | 1.210 | -94.01% | 1 | 1.00 |
| sma_20_50 | +38150.24% | +38150.24% | +165.90% | 1.597 | -69.15% | 38 | 0.52 |
| donchian_55_20 | +10585.03% | +10585.03% | +115.59% | 1.418 | -69.89% | 26 | 0.38 |

### Cost scenario: severe

| strategy | marked return | liq return | CAGR | Sharpe | maxDD | fills | exposure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | undefined | +0.00% | 0 | 0.00 |
| buy_and_hold | +7955.29% | +7894.97% | +105.81% | 1.209 | -94.01% | 1 | 1.00 |
| sma_20_50 | +32138.08% | +32138.08% | +158.53% | 1.562 | -70.59% | 38 | 0.52 |
| donchian_55_20 | +9405.23% | +9405.23% | +111.49% | 1.391 | -70.69% | 26 | 0.38 |

## 11. Bootstrap intervals

Moving-block bootstrap (`moving-block-bootstrap-v1`, seed 20260713, block 30, 5000 resamples, 95%) of the mean daily paired excess return versus buy-and-hold over the pooled reset-OOS observations. The interval describes sampling variability only; it does **not** prove alpha, is **not** annualized, and does not remove uncertainty.

### Cost scenario: base

| strategy | obs | point (mean daily excess) | 95% CI lower | median | upper |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | 1126 | -0.27% | -0.59% | -0.29% | +0.01% |
| sma_20_50 | 1126 | +0.02% | -0.15% | -0.00% | +0.17% |
| donchian_55_20 | 1126 | -0.07% | -0.28% | -0.09% | +0.11% |

### Cost scenario: stressed

| strategy | obs | point (mean daily excess) | 95% CI lower | median | upper |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | 1126 | -0.27% | -0.59% | -0.29% | +0.01% |
| sma_20_50 | 1126 | +0.02% | -0.16% | -0.01% | +0.16% |
| donchian_55_20 | 1126 | -0.07% | -0.28% | -0.09% | +0.11% |

### Cost scenario: severe

| strategy | obs | point (mean daily excess) | 95% CI lower | median | upper |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | 1126 | -0.26% | -0.59% | -0.29% | +0.01% |
| sma_20_50 | 1126 | +0.01% | -0.17% | -0.01% | +0.15% |
| donchian_55_20 | 1126 | -0.07% | -0.29% | -0.10% | +0.11% |

## 12. Comparison against buy-and-hold

The `frac > B&H` column in section 8 is the fraction of folds in which a strategy's marked return exceeded buy-and-hold in the same fold and scenario. Bootstrap intervals (section 11) whose upper bound is at or below zero indicate no evidence of positive mean excess over B&H.

## 13. Comparison against cash

The `frac > cash` column in section 8 is the fraction of folds in which a strategy's marked return exceeded the cash baseline (0%). Beating cash is a much weaker bar than beating buy-and-hold.

## 14. SMA(20/50) negative-control observations

SMA(20/50) is retained as the already-rejected negative control (it was `rejected_for_test_promotion` in Milestone 2B on the M2 validation period). Its research-train walk-forward behaviour is reported above for comparison only; nothing here revisits or overturns that rejection.

## 15. Donchian(55/20) exploratory observations

Donchian(55/20) is a fixed exploratory baseline — **not** a promoted candidate and never tuned. Its per-fold, pooled, and bootstrap results above are exploratory research-train diagnostics.

## 16. Cost fragility

Read each strategy's rows across the base -> stressed -> severe scenarios in sections 7-11: higher costs never improve identical cashflows, and a strategy that only narrowly beats a benchmark under base costs may not under severe costs. Turnover-heavy strategies degrade fastest.

## 17. Temporal instability

The per-fold table (section 7) shows how the same fixed strategy behaves very differently across the five chronological folds — evidence that a single validation period is a fragile basis for a promotion decision.

## 18. Weak and failed results (retained)

Every fold is retained, including losing folds and severe-cost failures. No fold, scenario, or strategy was dropped for being unflattering; the committed numbers stand as computed.

## 19. Multiple-testing statement

This experiment evaluates 4 strategies x 3 cost scenarios x 5 folds. With many comparisons, some favourable-looking cells are expected by chance alone; no per-cell result is treated as a discovery, and no selection was made after seeing results.

## 20. Limitations

- One venue (Coinbase Exchange), one instrument (ETH-USD spot), one daily dataset.
- Fixed parameters (SMA 20/50, Donchian 55/20); nothing tuned, and nothing should be inferred about other parameters.
- Research-train walk-forward is in-sample development evidence, not live performance and not test performance.
- Independent fold resets and the pooled reset-OOS series are diagnostics, not tradable paths.
- The bootstrap quantifies sampling variability only; it does not prove alpha or remove uncertainty.
- Costs are a simplified constant fee plus directional slippage; no spread, impact, or liquidity model.
- Computational sealing of the forbidden partitions is not epistemic sealing.

## 21. Exact next decision

No candidate is promoted here. The next step, if any, is to pre-register one candidate family and a development-gate promotion criterion, then spend exactly one recorded development-gate access — a separate, append-only process outside this milestone. The final holdout remains sealed and may be consumed at most once, only for a promoted candidate under an independent authorization.
