# ETH benchmark report

> Research observations on historical data — **not** expected future returns, and not investment advice. A positive number here is not a profitability claim.

## Dataset

- Instrument: ETH/USD ('ETH-USD') — spot on 'coinbase-exchange'
- Candle interval: 1 days 00:00:00 (open-time timestamps, UTC)
- Rows: 3702 (2016-05-23T00:00:00+00:00 .. 2026-07-11T00:00:00+00:00)
- Content fingerprint: `sha256:273f89eb07ae882784e40c2bc2ef2be5db93ddb3efa7de6270880ad1b7dd5718`
- Manifest SHA-256: `58ec9cb9940f76c991db92696e0a72df3365fa2b5d31305fa25f15468ac7b4fd`
- Dataset lock SHA-256: `6ccd3698f71b25b9cfbab758caeeb4150b2ca257df4f4acedd985da249462a4d`
- Quality report SHA-256: `b167df002768469bd5fb17c5a6588edc2c98e3ce910a0995187e1f68ed14f07a`
- Acquisition evidence SHA-256: `27ba6a6013fab67c02361bc3e2b43a761fa5ac0310556d7557859bdcbbbd2d0b`

## Quality warnings

| code | count | first examples |
| --- | ---: | --- |
| `extreme_ranges` | 50 | 2016-06-17 00:00:00+00:00: 39.30%; 2016-06-18 00:00:00+00:00: 36.70%; 2016-08-02 00:00:00+00:00: 42.48% |
| `extreme_returns` | 10 | 2016-06-17 00:00:00+00:00: -25.44%; 2016-06-18 00:00:00+00:00: -25.62%; 2017-03-16 00:00:00+00:00: +28.92% |

Warnings are reported, inspected, and explained — never removed; the audit never repairs data.

## Protocol

- Protocol SHA-256: `a75a9cf508ead459976060ab7518c4e382ecb95e54cc0ee36ec0ff9281f26a81`
- Pre-registered code commit: `b89627463775bf32698effb5adea1270a5927890`
- Split: 60% train / 20% validation / 20% test, chronological, positional floor semantics.
- Strategies: buy-and-hold (ex-ante entry at the first evaluated open) and SMA crossover (fast 20, slow 50) — fixed, never tuned.
- Costs: 10 bps fee plus 5 bps directional slippage per fill.
- Initial cash: 10,000.00 USD **per segment** — each segment starts independently with the same initial cash and pays its own entry costs; segment equity curves are never stitched into a continuous portfolio.
- SMA warm-up context: 50 preceding bars (signals only, no P&L); buy-and-hold uses none.
- Terminal positions are marked to market; hypothetical liquidation equity is reported separately.
- Annualization: 365.25-day year derived from the candle interval; risk-free rate 0.

## Split boundaries

| segment | first open | last open | bars |
| --- | --- | --- | ---: |
| train | 2016-05-23T00:00:00+00:00 | 2022-06-21T00:00:00+00:00 | 2221 |
| validation | 2022-06-22T00:00:00+00:00 | 2024-06-30T00:00:00+00:00 | 740 |
| test | 2024-07-01T00:00:00+00:00 | 2026-07-11T00:00:00+00:00 | 741 |

## Results

| strategy | segment | bars | total return | CAGR | Sharpe | Sortino | max drawdown | terminal equity | liquidation equity | traded notional | turnover | fills |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| buy_and_hold | train | 2221 | +8003.64% | +106.01% | 1.210 | 1.865 | -94.01% | 810,364.14 | 809,148.99 | 9,990.01 | 0.999 | 1 |
| buy_and_hold | validation | 740 | +204.67% | +73.30% | 1.182 | 1.834 | -44.58% | 30,466.95 | 30,421.27 | 9,990.01 | 0.999 | 1 |
| sma_20_50 | train | 2221 | +40393.85% | +168.41% | 1.608 | 2.617 | -68.87% | 4,049,384.65 | 4,049,384.65 | 47,280,489.99 | 4728.049 | 38 |
| sma_20_50 | validation | 740 | +1.48% | +0.73% | 0.252 | 0.366 | -45.28% | 10,147.64 | 10,147.64 | 153,405.97 | 15.341 | 18 |

### SMA (20/50) versus buy-and-hold, after costs

The difference column is the arithmetic gap between the two return percentages, in percentage points (pp) — not a ratio and not a percentage of buy-and-hold.

| segment | buy-and-hold return | SMA return | difference (pp) |
| --- | ---: | ---: | ---: |
| train | +8003.64% | +40393.85% | +32390.21 pp |
| validation | +204.67% | +1.48% | -203.19 pp |

## Test-set discipline

The test segment has **not** been evaluated: these are train and validation observations only.

## Limitations

- One venue (Coinbase Exchange) and one instrument (ETH-USD spot).
- One daily dataset; no intraday behaviour is observed.
- One fixed SMA parameterization (20/50); nothing was tuned, and nothing should be inferred about other parameters.
- Costs are a simplified constant: proportional fee plus constant directional slippage; there is no spread, impact, or liquidity model.
- Drawdown is measured on close-marked equity and misses intrabar troughs.
- Annualized Sharpe/Sortino assume serially independent per-bar returns.
- Historical results are research observations, not evidence of future profitability.

## Provenance and authoritative runtime

- Authoritative benchmark runtime: CPython 3.12.3 (cpython-312, Linux/x86_64); numpy 2.5.1, pandas 3.0.3, pyarrow 25.0.0.
- Runtime contract SHA-256: `ea9d6fabed37e533496688be16f384ab0b1e1cb5c9e6e8d407d64f40c7e4e9bd`
- Acquisition request-plan SHA-256: `f8f77ddbd226287e3561cd169de0b4fada090d66bd6a09d70e045f6b786ebf83`
- Raw acquisition: attempt `coinbase-eth-usd-001`, 13 public GET response(s), workflow run `29180786118`, source commit `22d4bd9b41260e095a49ba1a619814d0b2476202`.
- Windows: 13 over [2016-05-23, 2026-07-12).

## Test-set status

Train and validation are now observed; the **test** segment remains unobserved by any strategy or backtest code. Its boundaries above are mechanical (timestamps only) — no test price, return, or performance figure appears anywhere in this dossier. The one-time test evaluation is still pending independent authorization, and the append-only test-access ledger remains byte-empty.
