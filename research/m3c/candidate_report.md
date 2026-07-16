# Milestone 3C candidate report (run-001)

## 1. Decision

> ## REJECTED FOR DEVELOPMENT-GATE PROMOTION
>
> The candidate did **not** satisfy the frozen promotion rule and is retained, unchanged, as rejected. No parameter is altered to make it pass. The development gate and the final holdout remain sealed and were never accessed.

- Experiment id: `m3c-dual-horizon-trend-v1-run-001`
- Experiment family: `m3c-dual-horizon-trend-v1`
- Decision outcome: `rejected_for_development_gate_promotion`
- Recorded package version: `0.6.0`
- Registered code commit: `59cdecea27284535e83f12b1c2430998ead1f92e`
- Execution code commit: `59cdecea27284535e83f12b1c2430998ead1f92e`
- Committed results digest: `4db76efb923bc209e4354afabad897ea084ea2bbafb9e0f11b0a4a49961e00fc`

### Promotion rule (frozen before execution) and per-criterion outcome

The decision is generated mechanically from the committed results and the frozen rule: the candidate is eligible **iff all seven criteria pass**, else it is rejected.

| criterion | requirement | observed | pass |
| --- | --- | --- | :---: |
| P1 | primary 95% bootstrap lower bound > 0 (causal_proxy_base) | ci_lower=-0.0023056 | FAIL |
| P2 | candidate marked total return > buy_and_hold in >= 3 of 5 folds (base) | 2/5 folds | FAIL |
| P3 | candidate fold-median max drawdown no deeper than buy_and_hold (base) | candidate=-0.230979, buy_and_hold=-0.614699 | PASS |
| P4 | candidate fold-median marked total return > 0 (causal_proxy_stressed) | median=0.715681 | PASS |
| P5 | every candidate causal-scenario fold terminal equity > 0 and return > -1 | min_terminal_equity=8115.34, no_ruin=true | PASS |
| P6 | all causality/replay/archive/cross-runtime verification checks pass | verification_passed=true | PASS |
| P7 | exactly one new candidate; no parameter change; no alternate primary | candidate_count=1, primary=causal_proxy_base/buy_and_hold, lineage_budget_protocol_bound=true | PASS |

## 2. Research-only framing

> These are observations on the **research-train** partition only — in-sample development evidence for a **single, adaptively motivated** candidate whose horizons, volatility target, costs, folds, seed, and decision rule were all fixed before this one execution. Prior related trend strategies (SMA, Donchian, volatility-target variants) were already observed, so this candidate is adaptively motivated and its research-train result is **not** out-of-sample evidence. **No alpha is claimed**, nothing was tuned or optimized, and no cost figure is venue-calibrated. The independent development gate — the safeguard against this adaptive history — was never accessed, and this engine cannot move money.

## 3. Data-access boundaries

| level | rows | M3C access |
| --- | ---: | --- |
| research train | 2221 | evaluated (OOS folds only) |
| development gate | n/a | **sealed — never accessed** |
| final holdout | n/a | **sealed — never accessed** |

- Development-gate ledger events: **0**. Final-holdout ledger events: **0**. Research-train content fingerprint: `sha256:60aa988e9db786db5723c925abc794463c23ff701791173b745196c7a8b12033`.

## 4. Primary endpoint (frozen)

Under `causal_proxy_base`, mean paired daily log-return excess of the candidate over `buy_and_hold`, with a fold-seam-aware 95% moving-block bootstrap (fold-stratified-moving-block-v1, seed 20260714, 20000 resamples, 1126 paired OOS days).

- Point estimate: `-0.00012687`; 95% interval: `[-0.0023056, 0.00216936]`; lower bound above zero: **False**.
- Per-fold candidate vs buy-and-hold (marked total return, causal_proxy_base):

| fold | OOS days | candidate | buy_and_hold | mean daily log-excess | candidate wins |
| ---: | ---: | ---: | ---: | ---: | :---: |
| 0 | 226 | -14.70% | -44.98% | 0.00193979 | yes |
| 1 | 225 | +75.28% | +221.76% | -0.00269959 | no |
| 2 | 225 | +75.21% | +289.16% | -0.00354678 | no |
| 3 | 225 | +84.31% | +184.73% | -0.00193302 | no |
| 4 | 225 | -17.81% | -76.67% | 0.00559606 | yes |

## 5. Per-(strategy, scenario) aggregates over the five folds

### compatibility_v1

| strategy | median marked | median liquidation | median drawdown | worst drawdown | median Sharpe | median turnover | +folds | > B&H |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | n/a | 0.00x | 0% | 40% |
| buy_and_hold | +184.82% | +184.39% | -61.47% | -79.38% | 2.108 | 1.00x | 60% | 0% |
| donchian_55_20 | +81.61% | +81.33% | -32.94% | -41.62% | 1.647 | 3.15x | 80% | 40% |
| vol_target_donchian_55_20_30d_50pct | +59.60% | +59.42% | -19.14% | -24.76% | 1.959 | 4.31x | 80% | 40% |
| dual_horizon_trend_63_252_vol_target_30d_50pct | +75.76% | +75.59% | -23.07% | -27.94% | 2.014 | 7.46x | 60% | 40% |

### causal_proxy_base

| strategy | median marked | median liquidation | median drawdown | worst drawdown | median Sharpe | median turnover | +folds | > B&H |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | n/a | 0.00x | 0% | 40% |
| buy_and_hold | +184.73% | +184.22% | -61.47% | -79.39% | 2.107 | 1.00x | 60% | 0% |
| donchian_55_20 | +81.33% | +81.01% | -32.99% | -41.63% | 1.644 | 3.15x | 80% | 40% |
| vol_target_donchian_55_20_30d_50pct | +59.40% | +59.19% | -19.14% | -24.83% | 1.954 | 4.30x | 80% | 40% |
| dual_horizon_trend_63_252_vol_target_30d_50pct | +75.21% | +75.02% | -23.10% | -28.08% | 2.002 | 7.45x | 60% | 40% |

### causal_proxy_stressed

| strategy | median marked | median liquidation | median drawdown | worst drawdown | median Sharpe | median turnover | +folds | > B&H |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | n/a | 0.00x | 0% | 40% |
| buy_and_hold | +184.21% | +183.16% | -61.47% | -79.42% | 2.105 | 1.00x | 60% | 0% |
| donchian_55_20 | +79.66% | +79.01% | -33.26% | -41.74% | 1.625 | 3.16x | 80% | 40% |
| vol_target_donchian_55_20_30d_50pct | +58.09% | +57.66% | -19.36% | -25.24% | 1.924 | 4.29x | 80% | 40% |
| dual_horizon_trend_63_252_vol_target_30d_50pct | +71.57% | +71.20% | -23.29% | -28.59% | 1.937 | 7.40x | 60% | 40% |

## 6. Full fold grid (marked total return) — every losing fold retained

### compatibility_v1

| strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| buy_and_hold | -44.95% | +221.91% | +289.30% | +184.82% | -76.66% |
| donchian_55_20 | +10.15% | +90.93% | +184.93% | +81.61% | -31.68% |
| vol_target_donchian_55_20_30d_50pct | +7.97% | +91.09% | +82.48% | +59.60% | -23.17% |
| dual_horizon_trend_63_252_vol_target_30d_50pct | -14.49% | +75.76% | +75.87% | +84.75% | -17.65% |

### causal_proxy_base

| strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| buy_and_hold | -44.98% | +221.76% | +289.16% | +184.73% | -76.67% |
| donchian_55_20 | +10.06% | +90.67% | +184.61% | +81.33% | -31.76% |
| vol_target_donchian_55_20_30d_50pct | +7.91% | +90.86% | +82.25% | +59.40% | -23.25% |
| dual_horizon_trend_63_252_vol_target_30d_50pct | -14.70% | +75.28% | +75.21% | +84.31% | -17.81% |

### causal_proxy_stressed

| strategy | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |
| buy_and_hold | -45.10% | +218.90% | +288.39% | +184.21% | -76.71% |
| donchian_55_20 | +9.59% | +91.35% | +182.92% | +79.66% | -32.26% |
| vol_target_donchian_55_20_30d_50pct | +7.56% | +89.55% | +80.73% | +58.09% | -23.79% |
| dual_horizon_trend_63_252_vol_target_30d_50pct | -15.62% | +72.74% | +71.57% | +81.49% | -18.85% |

## 7. Modeled cost and fill diagnostics (candidate)

| scenario | fold | fees | spread | base slippage | liquidity impact | total | fills | partial | no-fill |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| compatibility_v1 | 0 | 55.76 | 0.00 | 27.88 | 0.00 | 83.64 | 75 | 0 | 0 |
| compatibility_v1 | 1 | 74.65 | 0.00 | 37.32 | 0.00 | 111.97 | 91 | 0 | 0 |
| compatibility_v1 | 2 | 105.42 | 0.00 | 52.71 | 0.00 | 158.13 | 200 | 0 | 0 |
| compatibility_v1 | 3 | 112.74 | 0.00 | 56.37 | 0.00 | 169.11 | 184 | 0 | 0 |
| compatibility_v1 | 4 | 61.80 | 0.00 | 30.90 | 0.00 | 92.70 | 68 | 0 | 0 |
| causal_proxy_base | 0 | 55.70 | 13.92 | 27.85 | 9.16 | 106.63 | 75 | 0 | 0 |
| causal_proxy_base | 1 | 74.54 | 18.63 | 37.27 | 9.07 | 139.51 | 91 | 0 | 0 |
| causal_proxy_base | 2 | 105.20 | 26.30 | 52.60 | 9.68 | 193.78 | 200 | 0 | 0 |
| causal_proxy_base | 3 | 112.60 | 28.15 | 56.30 | 3.37 | 200.42 | 184 | 0 | 0 |
| causal_proxy_base | 4 | 61.74 | 15.44 | 30.87 | 1.79 | 109.84 | 68 | 0 | 0 |
| causal_proxy_stressed | 0 | 102.93 | 25.73 | 51.46 | 22.05 | 202.17 | 77 | 3 | 0 |
| causal_proxy_stressed | 1 | 147.94 | 36.98 | 73.96 | 26.96 | 285.85 | 91 | 0 | 0 |
| causal_proxy_stressed | 2 | 208.01 | 52.00 | 104.00 | 28.63 | 392.64 | 200 | 0 | 0 |
| causal_proxy_stressed | 3 | 223.40 | 55.85 | 111.69 | 10.00 | 400.94 | 184 | 0 | 0 |
| causal_proxy_stressed | 4 | 122.73 | 30.68 | 61.36 | 5.32 | 220.09 | 68 | 0 | 0 |

## 8. Secondary Probabilistic Sharpe diagnostic (fragile)

> The Probabilistic Sharpe Ratio below is a **fragile secondary** descriptor only: five folds plus an adaptive research history cannot support a credible overfitting claim, and it **cannot** rescue a failed primary or add any inferential weight.

- Observed daily paired-excess Sharpe: `-0.00316263` (benchmark `0`, n = 1126); skewness `2.67363`, kurtosis `41.3619`; PSR `0.457939`.

## 9. Limitations

- One in-sample research-train execution of one adaptively motivated candidate; not live, test, or gate performance.
- The costs are transparent deterministic proxies driven by lagged liquidity, not a venue-calibrated model, and make no empirical-accuracy claim.
- A single fold-seam-aware bootstrap on an adaptive dataset carries no significance claim; only the independent, sealed development gate can address the adaptive history.
- Eligibility, if any, means only that an independent development-gate review may consider the candidate; it is not promotion, not an alpha claim, and not approval to trade.

