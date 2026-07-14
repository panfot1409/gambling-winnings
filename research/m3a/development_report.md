# Milestone 3A development walk-forward report (run-003, corrected inference)

## 1. Research-only disclaimer

> Research observations on historical data — **not** a profitability claim, **not** expected future returns, and **not** investment advice. No alpha is claimed; the fixed parameters were never optimized. This run corrects **methodology and publication governance only** — every per-fold financial result is bit-identical to run-002; no strategy parameter changed.

- Experiment id: `m3a-fixed-baseline-comparison-v2-run-003`
- Methodology: `walk-forward-fold-stratified-bootstrap-v2` (`research/m3a/walk_forward_protocol_v2.json`)
- Execution source-tree fingerprint: `c388601b26454af77ce4d1a9b36d707a64892aec20445a73ec89e84e3507fb77`

## 2. Data-access boundaries

| level | dates (UTC) | rows | M3A access |
| --- | --- | ---: | --- |
| research train | 2016-05-23 .. 2022-06-21 | 2221 | evaluated |
| development gate | 2022-06-22 .. 2024-06-30 | 740 | **not evaluated (forbidden)** |
| final holdout | 2024-07-01 .. 2026-07-11 | 741 | **not evaluated (forbidden)** |

- Development-gate ledger events: **0** (byte-empty). Final-holdout ledger events: **0** (byte-empty). This is fixed-rule rolling-origin OOS evaluation with expanding information sets — no estimator is fit.

## 3. Corrected fold-aware bootstrap (v2)

Run-001 and run-002 used the historical moving-block bootstrap v1, whose blocks could cross independent-reset fold seams. Run-003 uses the **primary** fold-stratified bootstrap v2 (blocks drawn strictly within a fold) and reports a **hierarchical** fold-block sensitivity bootstrap. All intervals are in-sample research diagnostics on five folds — weak evidence — and every one is reported, including inconvenient results. Intervals are of mean daily paired excess return versus buy-and-hold.

| strategy | scenario | primary 95% CI | sensitivity 95% CI |
| --- | --- | --- | --- |
| cash | base | [-0.51%, -0.00%] (point -0.27%) | [-0.76%, +0.26%] (point -0.27%) |
| sma_20_50 | base | [-0.13%, +0.17%] (point +0.02%) | [-0.20%, +0.27%] (point +0.02%) |
| donchian_55_20 | base | [-0.23%, +0.12%] (point -0.07%) | [-0.34%, +0.25%] (point -0.07%) |
| cash | stressed | [-0.51%, -0.00%] (point -0.27%) | [-0.76%, +0.26%] (point -0.27%) |
| sma_20_50 | stressed | [-0.14%, +0.16%] (point +0.02%) | [-0.20%, +0.26%] (point +0.02%) |
| donchian_55_20 | stressed | [-0.23%, +0.12%] (point -0.07%) | [-0.34%, +0.25%] (point -0.07%) |
| cash | severe | [-0.51%, -0.00%] (point -0.26%) | [-0.76%, +0.26%] (point -0.26%) |
| sma_20_50 | severe | [-0.15%, +0.16%] (point +0.01%) | [-0.21%, +0.25%] (point +0.01%) |
| donchian_55_20 | severe | [-0.24%, +0.12%] (point -0.07%) | [-0.35%, +0.25%] (point -0.07%) |

## 4. Pooled reset-OOS diagnostics (mean daily return)

| strategy | scenario | obs | mean daily | beats B&H (folds) |
| --- | --- | ---: | --- | --- |
| cash | base | 1126 | +0.00% | 40% |
| buy_and_hold | base | 1126 | +0.27% | 0% |
| sma_20_50 | base | 1126 | +0.29% | 40% |
| donchian_55_20 | base | 1126 | +0.20% | 40% |
| cash | stressed | 1126 | +0.00% | 40% |
| buy_and_hold | stressed | 1126 | +0.27% | 0% |
| sma_20_50 | stressed | 1126 | +0.29% | 40% |
| donchian_55_20 | stressed | 1126 | +0.20% | 40% |
| cash | severe | 1126 | +0.00% | 40% |
| buy_and_hold | severe | 1126 | +0.26% | 0% |
| sma_20_50 | severe | 1126 | +0.28% | 40% |
| donchian_55_20 | severe | 1126 | +0.19% | 40% |

## 5. Honest finding

Over the research-train period — an ETH bull market — buy-and-hold dominates median return; the active strategies beat buy-and-hold in a minority of folds, and every fold-aware bootstrap interval of mean daily paired excess return versus buy-and-hold straddles zero. No alpha is claimed, nothing was tuned, and losing folds and severe-cost failures are retained exactly as computed. This is in-sample development evidence, not live performance and not test performance. No candidate is promoted; the development gate and the final holdout remain sealed.

