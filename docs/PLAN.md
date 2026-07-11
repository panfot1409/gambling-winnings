# Implementation Plan — ETH Trading Algorithm Research

_Last updated: 2026-07-11 (revised after the Milestone 1 correctness
remediation — see [REMEDIATION.md](REMEDIATION.md))_

## 1. Purpose

A clean, research-only Python codebase for developing and evaluating trading
algorithms on historical Ethereum (ETH) market data. The goal is honest,
reproducible strategy research: realistic costs, strict chronology, and
metrics that make weak strategies look weak.

## 2. Non-goals (hard exclusions, all milestones)

The following are deliberately **out of scope** at every milestone:

- No live or paper trading against real venues.
- No exchange connectivity, API keys, or authentication of any kind.
- No wallet integration, on-chain transactions, or custody of funds.
- No leverage, margin, short selling, or derivatives — positions are
  0–100% of equity, long-only.
- No order routing or execution infrastructure.

The package must never gain a code path that can move money. The backtest
engine enforces the constraint structurally: targets must be exactly binary
`{0, 1}` (cash / fully long), cash can never go materially negative, and
ETH quantity can never go negative — no borrowing, no hidden leverage.

## 3. Guiding principles

1. **No look-ahead.** A signal at bar `t` may use bars `≤ t` only; the
   engine executes it at the open of bar `t + 1`. Regression tests enforce
   this, including that the `close[t] -> open[t+1]` gap cannot be captured.
2. **Costs are first-class.** Every backtest applies fees and directional
   slippage by default; frictionless runs must be requested explicitly.
3. **Chronological evaluation.** Train → validation → test, ordered in time,
   never shuffled. The test set is reserved for final evaluations.
4. **Reproducibility.** Deterministic seeds, typed code, pure functions,
   pinned tool configuration.
5. **Small and legible.** Plain pandas/NumPy over frameworks; every module
   documents its conventions.

## 4. Architecture

```
src/eth_research/
    data/
        schema.py      # strict OHLCV schema -> canonical frame format
        load.py        # CSV / Parquet -> validated frame
        synthetic.py   # deterministic synthetic OHLCV for tests/examples
    splits.py          # chronological splits + warm-up context helpers
    strategies/
        base.py        # Strategy interface + timing contract
        buy_and_hold.py
        moving_average.py
    backtest.py        # bar-by-bar portfolio engine: open fills, fees, ledger
    metrics.py         # equity-curve metrics + performance summary
```

Data flow: `load → validate → split → strategy signals → backtest → metrics`.

### Conventions

- Timestamps are candle **open times**, timezone-aware **UTC**
  (`datetime64[ns, UTC]`); the index is unique, strictly increasing, and
  regularly spaced. Validation rejects unsorted data (never sorts), rejects
  naive timestamps unless `assume_utc=True`, and rejects missing candles
  and irregular gaps (never fills them).
- Execution: the target decided from data through `close[t-1]` fills at
  `open[t]` — buys at `open[t] * (1 + slippage_rate)`, sells at
  `open[t] * (1 - slippage_rate)`, fee = fill notional × `fee_rate`.
  Equity is marked at `close[t]` as `cash + quantity × close[t]`.
- Accounting is exact long/cash bookkeeping with an immutable fill ledger.
  Targets are binary `{0, 1}` in Milestone 1 — no fractional weights until
  fractional rebalancing is implemented exactly.
- Buy-and-hold enters **ex ante at the first available open** (tested).
- Warm-up context: validation may see trailing train rows and test may see
  trailing train/validation rows for indicator warm-up only — zero P&L.
- Terminal positions are marked to market at the last close, never
  force-liquidated; a hypothetical liquidation value is reported.
- Metrics derive from the reconciled equity curve; CAGR uses the recorded
  start/end times; Sharpe/Sortino annualize only from the validated regular
  interval or an explicit setting. Annualization uses **365.25 days** per
  year (crypto trades continuously; 252-day equity conventions do not
  apply). Turnover = traded notional / initial cash; trade count =
  executed fills.

## 5. Milestone 1 — Foundations (this milestone)

Deliverables, each with tests:

| #  | Deliverable                                                                | Where                        |
|----|----------------------------------------------------------------------------|------------------------------|
| 1  | Scaffolding: Python 3.12+, src layout, pytest, ruff, mypy (strict)         | `pyproject.toml`             |
| 2  | Strict OHLCV schema: candle-open timestamps, UTC, no silent sorting, regular-interval/gap rejection, aggregated error reporting | `data/schema.py` |
| 3  | Historical data loading from CSV and Parquet (incl. unambiguous epoch timestamps) | `data/load.py`         |
| 4  | Deterministic synthetic OHLCV generator (keeps market data out of the repo) | `data/synthetic.py`         |
| 5  | Chronological train/validation/test splits + warm-up context helpers       | `splits.py`                  |
| 6  | Buy-and-hold benchmark with explicit ex-ante first-open entry              | `strategies/buy_and_hold.py` |
| 7  | Simple moving-average (SMA) crossover strategy, fixed parameters           | `strategies/moving_average.py` |
| 8  | Bar-by-bar portfolio engine: next-open fills, directional slippage, fee on notional, cash/ETH ledger, no-leverage invariants | `backtest.py` |
| 9  | Equity-curve metrics: total return, CAGR (recorded start/end), Sharpe, Sortino, max drawdown, notional turnover, fill count | `metrics.py` |
| 10 | Look-ahead bias regression tests (prefix invariance, future mutation, gap non-capture, split chronology, context leakage) | `tests/test_lookahead.py`, `tests/test_context.py` |
| 11 | End-to-end example script and usage docs                                   | `examples/`                  |
| 12 | CI (GitHub Actions, Python 3.12 + 3.13) installing from a frozen `uv.lock` (lock/pyproject drift fails the build) | `.github/workflows/ci.yml`, `uv.lock` |

Explicitly deferred from Milestone 1: parameter optimization, machine
learning, plotting, CLI, walk-forward analysis, fractional position
weights.

## 6. Milestone 2A — Dataset provenance and quality

Detailed plan: [M2A_PLAN.md](M2A_PLAN.md). An offline layer that turns a
user-supplied local ETH OHLCV file into an audited, fingerprinted canonical
dataset:

- Versioned dataset identity and manifest: base/quote asset, exact symbol,
  venue, spot market type, candle interval, UTC open-time convention,
  source description, raw-file SHA-256, deterministic content fingerprint,
  row count, first/last candle, manifest schema version, package version.
- Offline quality audit that *reports and never repairs*: duplicates,
  ordering problems, missing candles, missing/non-finite/non-positive
  values, OHLC violations, zero-volume candles and runs, extreme returns
  and suspicious ranges — with exact counts and first examples.
- Deterministic canonical builder: local CSV/Parquet in, canonical Parquet
  + JSON manifest + quality report out; atomic writes; explicit overwrite
  opt-in; artifacts under git-ignored `data/`; verification-on-read that
  detects tampering and data/manifest mismatches. No network access.

## 7. Milestone 2B — Real ETH data, frozen and benchmarked

- Acquire one real ETH OHLCV history (documented manual/offline
  acquisition), freeze it through the 2A pipeline, and record its manifest
  fingerprints.
- Run the existing buy-and-hold benchmark and SMA baseline on it through
  the untouched Milestone 1 engine; publish the resulting report.
- Test-set discipline bookkeeping: the test segment is evaluated once and
  the evaluation is recorded.

## 8. Later milestones

- Walk-forward evaluation (rolling train/validate windows) on top of the
  static split.
- Parameter grid evaluation restricted to train/validation, with explicit
  "test set touched once" bookkeeping. Still no automated optimizers.
- Fractional position weights with exact rebalancing accounting (removes
  the Milestone 1 binary-target restriction).
- Multi-symbol support (validated `symbol` metadata beyond the single-ETH
  manifest identity).
- Richer cost model: bid/ask spread term and a simple volume-participation
  impact term.
- Additional baselines: momentum, mean reversion, volatility targeting.
- Coverage threshold in CI.
- Small CLI entry point (`eth-research backtest ...`).

## 9. Milestone 3 — Statistical robustness

- Block-bootstrap confidence intervals for Sharpe/CAGR.
- Deflated Sharpe ratio and multiple-testing awareness for strategy families.
- Regime slicing (bull/bear/high-vol) of results.
- Markdown/HTML tearsheet reports comparing strategies against the
  buy-and-hold benchmark.

## 10. Milestone 4 — Optional machine learning (gated)

Only after Milestones 2A/2B–3 are in place:

- Feature pipeline with the same no-look-ahead contract as strategies.
- Purged and embargoed time-series cross-validation.
- Simple, inspectable models first (regularized linear, small trees).
- Leakage tests extended to the feature layer.

## 11. Testing strategy

- **Unit tests** per module, including aggregated schema error reporting.
- **Hand-calculated ledger tests**: fills, fees, cash, and equity are
  checked against numbers worked out by hand from the documented rules on
  clean price paths — not against a second implementation of the same
  formulas.
- **Look-ahead guards**:
  - prefix invariance — signals and engine results on `data[:t]` equal the
    first `t` results on full data, bit for bit;
  - future mutation — rewriting bars after `t` cannot change signals,
    fills, or equity at or before `t`;
  - execution timing — a "perfect foresight" strategy that knows each
    bar's direction at its close captures at most one intrabar move
    (fills happen at the next open), and an overnight gap after a signal
    can never be captured;
  - splits are chronologically ordered, disjoint, and complete; warm-up
    context affects signals only, never P&L.
- **Determinism**: synthetic data generation is seed-stable.

## 12. Quality gates

All of the following must pass before merging:

```
ruff format --check .
ruff check .
mypy
pytest
```

## 13. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Look-ahead bias | Engine-enforced execution lag; regression tests in `tests/test_lookahead.py` |
| Overfitting | Chronological splits now; walk-forward + test-set discipline in M2; no optimizers in M1 |
| Understated costs | Non-zero default fee/slippage; frictionless runs are opt-in |
| Bad input data | Strict schema validation with aggregated, actionable error messages |
| Convention drift | Conventions documented in module docstrings and README; typed interfaces |
