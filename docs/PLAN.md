# Implementation Plan — ETH Trading Algorithm Research

_Last updated: 2026-07-11_

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
engine enforces the no-leverage constraint by rejecting positions outside
`[0, 1]`.

## 3. Guiding principles

1. **No look-ahead.** A signal at bar `t` may use bars `≤ t` only; the
   engine executes it on bar `t + 1`. Regression tests enforce this.
2. **Costs are first-class.** Every backtest applies fees and slippage by
   default; frictionless runs must be requested explicitly.
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
        schema.py      # validated OHLCV schema -> canonical frame format
        load.py        # CSV / Parquet -> validated frame
        synthetic.py   # deterministic synthetic OHLCV for tests/examples
    splits.py          # chronological train/validation/test splits
    strategies/
        base.py        # Strategy interface + timing contract
        buy_and_hold.py
        moving_average.py
    backtest.py        # vectorized engine: execution lag, fees, slippage
    metrics.py         # return/risk metrics + performance summary
```

Data flow: `load → validate → split → strategy signals → backtest → metrics`.

### Conventions

- Timestamps are timezone-aware **UTC**; each row is a completed bar and the
  index is unique and strictly increasing.
- Returns are **close-to-close** simple returns.
- Positions are fractions of equity in `[0, 1]` (0 = cash, 1 = fully long).
- Costs are proportional: `(fee_rate + slippage_rate) × |Δposition|`,
  charged in the bar where the trade settles.
- Annualization uses **365.25 days** per year (crypto trades continuously;
  252-day equity conventions do not apply).

## 5. Milestone 1 — Foundations (this milestone)

Deliverables, each with tests:

| #  | Deliverable                                                                | Where                        |
|----|----------------------------------------------------------------------------|------------------------------|
| 1  | Scaffolding: Python 3.12+, src layout, pytest, ruff, mypy (strict)         | `pyproject.toml`             |
| 2  | Validated OHLCV schema: UTC index, positive prices, OHLC consistency, aggregated error reporting | `data/schema.py` |
| 3  | Historical data loading from CSV and Parquet (incl. epoch timestamps)      | `data/load.py`               |
| 4  | Deterministic synthetic OHLCV generator (keeps market data out of the repo) | `data/synthetic.py`         |
| 5  | Chronological train/validation/test splits                                 | `splits.py`                  |
| 6  | Buy-and-hold benchmark                                                      | `strategies/buy_and_hold.py` |
| 7  | Simple moving-average (SMA) crossover strategy, fixed parameters           | `strategies/moving_average.py` |
| 8  | Vectorized backtester: one-bar execution lag, fees, slippage, no-leverage guard | `backtest.py`           |
| 9  | Metrics: total return, CAGR, Sharpe, Sortino, max drawdown, turnover, trade count | `metrics.py`          |
| 10 | Look-ahead bias regression tests (prefix invariance, future perturbation, execution lag, split chronology) | `tests/test_lookahead.py` |
| 11 | End-to-end example script and usage docs                                   | `examples/`                  |

Explicitly deferred from Milestone 1: parameter optimization, machine
learning, plotting, CLI, CI, walk-forward analysis.

## 6. Milestone 2 — Evaluation hardening

- Walk-forward evaluation (rolling train/validate windows) on top of the
  static split.
- Parameter grid evaluation restricted to train/validation, with explicit
  "test set touched once" bookkeeping. Still no automated optimizers.
- Warm-up carry-in: give strategies trailing history before a segment so
  indicators are live from the segment's first bar.
- Data-quality report: gaps, duplicate/irregular spacing, outlier bars,
  zero-volume runs.
- Richer cost model: bid/ask spread term and a simple volume-participation
  impact term.
- Additional baselines: momentum, mean reversion, volatility targeting.
- CI (GitHub Actions): ruff + mypy + pytest on push; coverage threshold.
- Small CLI entry point (`eth-research backtest ...`).

## 7. Milestone 3 — Statistical robustness

- Block-bootstrap confidence intervals for Sharpe/CAGR.
- Deflated Sharpe ratio and multiple-testing awareness for strategy families.
- Regime slicing (bull/bear/high-vol) of results.
- Markdown/HTML tearsheet reports comparing strategies against the
  buy-and-hold benchmark.

## 8. Milestone 4 — Optional machine learning (gated)

Only after Milestones 2–3 are in place:

- Feature pipeline with the same no-look-ahead contract as strategies.
- Purged and embargoed time-series cross-validation.
- Simple, inspectable models first (regularized linear, small trees).
- Leakage tests extended to the feature layer.

## 9. Testing strategy

- **Unit tests** per module, including aggregated schema error reporting.
- **Oracle tests**: the vectorized engine is checked bar-by-bar against a
  hand-written Python loop on small handcrafted price paths.
- **Look-ahead guards**:
  - prefix invariance — signals on `data[:t]` equal signals on full data;
  - future perturbation — changing bars after `t` cannot change signals at
    or before `t`;
  - execution lag — a "perfect foresight" strategy that knows each bar's
    return as it closes must still lose on an alternating series, because
    the engine defers execution by one bar;
  - splits are chronologically ordered, disjoint, and complete.
- **Determinism**: synthetic data generation is seed-stable.

## 10. Quality gates

All of the following must pass before merging:

```
ruff format --check .
ruff check .
mypy
pytest
```

## 11. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Look-ahead bias | Engine-enforced execution lag; regression tests in `tests/test_lookahead.py` |
| Overfitting | Chronological splits now; walk-forward + test-set discipline in M2; no optimizers in M1 |
| Understated costs | Non-zero default fee/slippage; frictionless runs are opt-in |
| Bad input data | Strict schema validation with aggregated, actionable error messages |
| Convention drift | Conventions documented in module docstrings and README; typed interfaces |
