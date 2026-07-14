# Milestone 3B fractional execution-risk report (run-001)

## 1. Research-only disclaimer

> Research observations on historical data — **not** a profitability claim, **not** expected future returns, and **not** investment advice. No alpha is claimed and nothing was optimized: the five strategies, three cost scenarios, and every tolerance were fixed and pre-registered before this single execution. The spread, slippage, and market-impact terms are transparent deterministic proxies driven by lagged liquidity — they are **not** venue-calibrated and make no empirical accuracy claim. This engine cannot and does not move money.

- Experiment id: `m3b-fractional-execution-risk-v1-run-001`
- Experiment family: `m3b-fractional-execution-risk-v1`
- Recorded package version: `0.5.0`
- Registered code commit: `2628440329a212cf0d2de16938161820e56b0a6a`
- Execution code commit: `2628440329a212cf0d2de16938161820e56b0a6a`
- Execution source-tree fingerprint: `65c1be77d264446038a85a7123e8810a8394a57ed5bda786039809817f9738ac`
- Pre-registered protocol: `research/m3b/fractional_protocol.json`
- Protocol digest: `9c1e00eca5e8e58ce88e05d0b4ccdb71b34f798afe72cda3e9c88dee5641d4b6`

## 2. Data-access boundaries

| level | dates (UTC) | rows | M3B access |
| --- | --- | ---: | --- |
| research train | 2016-05-23 .. 2022-06-21 | 2221 | evaluated |
| development gate | 2022-06-22 .. 2024-06-30 | 740 | **not evaluated (forbidden)** |
| final holdout | 2024-07-01 .. 2026-07-11 | 741 | **not evaluated (forbidden)** |

- Development-gate ledger events: **0** (byte-empty). Final-holdout ledger events: **0** (byte-empty). Only the five research-train rolling-origin OOS folds are evaluated; no estimator is fit and no parameter is selected on any observed output.
- Research-train content fingerprint: `sha256:60aa988e9db786db5723c925abc794463c23ff701791173b745196c7a8b12033`

## 3. Execution model

Each cell is a fractional long-only cash/ETH backtest. Orders execute at the **next** bar's reference open (decision at bar `t` fills at `open[t]`), liquidity is estimated only from rows strictly before the fill bar (no same-bar volume), and a deterministic partial fill applies when the target exceeds the participation cap. Costs decompose into explicit fee, half-spread, base slippage, and lagged-liquidity market-impact terms. `compatibility_v1` reproduces the binary Milestone 3A engine bit-for-bit; `causal_proxy_base` and `causal_proxy_stressed` add the causal liquidity/impact overlay at two severities. Returns are shown both marked to the final close and after a modeled terminal liquidation.

## 4. Per-(strategy, scenario) aggregates over the five folds

### compatibility_v1

| strategy | median marked | median liquidation | worst drawdown | median Sharpe | median turnover | median exposure | +folds | > B&H | > cash |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | n/a | 0.00x | 0% | 0% | 40% | 0% |
| buy_and_hold | +184.82% | +184.39% | -79.38% | 2.108 | 1.00x | 100% | 60% | 0% | 60% |
| donchian_55_20 | +43.53% | +43.32% | -41.62% | 1.163 | 2.40x | 50% | 60% | 40% | 60% |
| vol_target_buy_and_hold_30d_50pct | +123.64% | +123.38% | -65.26% | 2.732 | 5.77x | 61% | 60% | 40% | 60% |
| vol_target_donchian_55_20_30d_50pct | +44.33% | +44.17% | -22.38% | 1.610 | 4.31x | 30% | 60% | 40% | 60% |

### causal_proxy_base

| strategy | median marked | median liquidation | worst drawdown | median Sharpe | median turnover | median exposure | +folds | > B&H | > cash |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | n/a | 0.00x | 0% | 0% | 40% | 0% |
| buy_and_hold | +184.73% | +184.22% | -79.39% | 2.107 | 1.00x | 100% | 60% | 0% | 60% |
| donchian_55_20 | +43.32% | +43.06% | -41.63% | 1.160 | 2.40x | 50% | 60% | 40% | 60% |
| vol_target_buy_and_hold_30d_50pct | +123.41% | +123.11% | -65.30% | 2.728 | 5.77x | 61% | 60% | 40% | 60% |
| vol_target_donchian_55_20_30d_50pct | +44.16% | +43.96% | -22.42% | 1.605 | 4.30x | 30% | 60% | 40% | 60% |

### causal_proxy_stressed

| strategy | median marked | median liquidation | worst drawdown | median Sharpe | median turnover | median exposure | +folds | > B&H | > cash |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | n/a | 0.00x | 0% | 0% | 40% | 0% |
| buy_and_hold | +184.21% | +183.16% | -79.42% | 2.105 | 1.00x | 100% | 60% | 0% | 60% |
| donchian_55_20 | +42.01% | +41.49% | -41.74% | 1.141 | 2.40x | 50% | 60% | 40% | 60% |
| vol_target_buy_and_hold_30d_50pct | +121.87% | +121.26% | -65.59% | 2.703 | 5.75x | 61% | 60% | 40% | 60% |
| vol_target_donchian_55_20_30d_50pct | +42.99% | +42.60% | -22.66% | 1.575 | 4.29x | 30% | 60% | 40% | 60% |

## 5. Full fold grid (marked total return)

Every one of the 75 (strategy, scenario, fold) cells, shown as computed. Fold windows are the pre-registered rolling-origin OOS segments; losing folds are retained verbatim.

### compatibility_v1

| strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| buy_and_hold | -44.95% | +221.91% | +289.30% | +184.82% | -76.66% |
| donchian_55_20 | -9.68% | +90.93% | +159.22% | +43.53% | -17.54% |
| vol_target_buy_and_hold_30d_50pct | -31.49% | +165.04% | +127.76% | +123.64% | -63.03% |
| vol_target_donchian_55_20_30d_50pct | -6.17% | +91.09% | +79.74% | +44.33% | -16.05% |

### causal_proxy_base

| strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| buy_and_hold | -44.98% | +221.76% | +289.16% | +184.73% | -76.67% |
| donchian_55_20 | -9.75% | +90.67% | +158.94% | +43.32% | -17.58% |
| vol_target_buy_and_hold_30d_50pct | -31.59% | +164.63% | +127.48% | +123.41% | -63.08% |
| vol_target_donchian_55_20_30d_50pct | -6.22% | +90.86% | +79.53% | +44.16% | -16.10% |

### causal_proxy_stressed

| strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| buy_and_hold | -45.10% | +218.90% | +288.39% | +184.21% | -76.71% |
| donchian_55_20 | -10.12% | +91.35% | +157.41% | +42.01% | -17.89% |
| vol_target_buy_and_hold_30d_50pct | -32.19% | +162.33% | +125.63% | +121.87% | -63.39% |
| vol_target_donchian_55_20_30d_50pct | -6.48% | +89.55% | +78.18% | +42.99% | -16.46% |

## 6. Honest reading

This is a single in-sample research-train execution, not live or test performance. The cost scenarios shrink net return monotonically in the modeled frictions, the vol-target strategies trade more and pay more, and buy-and-hold is hard to beat over this ETH bull-market window — every cell, including the unflattering ones, is reported. No alpha is claimed, nothing was tuned, no cell was dropped, no bootstrap or significance test was run, and no candidate is promoted. The development gate and the final holdout remain sealed and byte-empty.

