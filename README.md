# ETH Trading Research

A research-only Python toolkit for developing and evaluating Ethereum (ETH)
trading algorithms on historical OHLCV data.

> **Research only — by design.** This project contains **no** live trading,
> **no** exchange connectivity or API authentication, **no** wallet
> integration, and **no** leverage, margin, or short selling. It loads
> historical data from local files and evaluates strategies offline. Nothing
> here places orders or touches funds, and the backtest engine rejects
> anything other than binary long/cash targets.

## Requirements

- Python 3.12+

## Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]" -c constraints.txt
```

(`constraints.txt` pins the verified dependency versions; drop `-c` for a
floating install.)

## Quickstart

Run the end-to-end example — buy-and-hold benchmark vs an SMA crossover,
with fees and directional slippage, on a chronological validation segment
with indicator warm-up context:

```bash
python examples/run_sma_backtest.py                              # synthetic demo data
python examples/run_sma_backtest.py data/eth_daily.csv           # your own OHLCV file
python examples/run_sma_backtest.py --fast 10 --slow 30 --segment test
```

Typical output:

```
Split boundaries (candle open times):
  train      2020-01-01 00:00:00+00:00 .. 2021-03-13 00:00:00+00:00
  validation 2021-03-14 00:00:00+00:00 .. 2021-08-06 00:00:00+00:00
  test       2021-08-07 00:00:00+00:00 .. 2021-12-30 00:00:00+00:00

Data:    synthetic demo data (730 daily bars, seed 42)
Segment: validation (146 bars)
Context: 50 warm-up bars (signals only, no P&L)
Costs:   10.0 bps fee + 5.0 bps slippage per fill

buy_and_hold
  window            2021-03-14 00:00:00+00:00 .. 2021-08-07 00:00:00+00:00
  n_periods         146
  initial_equity    10,000.00
  terminal_equity   9,477.02
  total_return      -5.23%
  sharpe            -0.16
  max_drawdown      -22.44%
  num_trades        1
  ...
```

Or from Python:

```python
from eth_research.backtest import CostModel, run_backtest
from eth_research.data import load_ohlcv
from eth_research.metrics import summarize
from eth_research.splits import chronological_split
from eth_research.strategies import BuyAndHold, MovingAverageCrossover

data = load_ohlcv("data/eth_daily.csv")  # strict: sorted, regular, tz-aware
splits = chronological_split(data)       # 60% train / 20% validation / 20% test

result = run_backtest(
    splits.validation,
    MovingAverageCrossover(fast_window=20, slow_window=50),
    CostModel(fee_rate=0.001, slippage_rate=0.0005),
    initial_cash=10_000.0,
    context=splits.validation_context(50),  # indicator warm-up only, no P&L
)
print(summarize(result))
print(result.fills)  # immutable trade ledger
```

## Data format

`load_ohlcv` reads `.csv`, `.parquet`, or `.pq` files with one row per
completed candle:

| column      | type                                                  |
|-------------|-------------------------------------------------------|
| `timestamp` | candle **open time**, ISO-8601 datetime with timezone |
| `open`      | float, > 0                                            |
| `high`      | float, >= max(open, close)                            |
| `low`       | float, <= min(open, close)                            |
| `close`     | float, > 0                                            |
| `volume`    | float, >= 0                                           |

Validation is strict and never repairs data:

- unsorted rows are **rejected, never sorted**;
- timezone-naive timestamps are rejected unless you opt in explicitly with
  `assume_utc=True`; epoch timestamps (`timestamp_unit="ms"`, …) are
  unambiguous UTC and need no opt-in;
- the candle interval must be regular — pass `expected_interval="1D"` to
  check against a known interval, or let it be inferred, which succeeds
  only when every spacing agrees; **missing candles and gaps are rejected,
  never filled**;
- all problems in a file are reported together.

Data files live in the git-ignored `data/` directory — market data is never
committed.

## Conventions

- **Timestamps are candle open times**, UTC (`datetime64[ns, UTC]`); a
  candle spans `[t, t + interval)`.
- **Execution.** The target decided from data through `close[t-1]` fills at
  `open[t]`: buys at `open[t] * (1 + slippage_rate)`, sells at
  `open[t] * (1 - slippage_rate)`; fee = fill notional × `fee_rate`. Equity
  is marked at `close[t]`. A signal derived from `close[t]` can never fill
  at that close or capture the `close[t] -> open[t+1]` gap.
- **Accounting.** Exact long/cash bookkeeping: cash balance and ETH
  quantity per bar, an immutable fill ledger, and
  `equity = cash + quantity * close`. Cash can never go materially
  negative, quantity never negative — no borrowing, no hidden leverage.
- **Targets are binary {0, 1}** (cash / fully long) in Milestone 1;
  fractional weights are not offered because fractional rebalancing is not
  implemented.
- **Buy-and-hold enters ex ante** at the first available open, using no
  observed data (tested behaviour, not an accident of implementation).
- **Warm-up context.** Validation may use trailing train rows and test may
  use trailing train/validation rows as indicator context — signals only,
  zero P&L contribution; a signal from the final context close may fill at
  the first evaluation open.
- **Terminal policy.** Final positions are marked to market at the last
  close, never force-liquidated; the hypothetical liquidation value (sell
  at the last close with slippage and fee) is reported as
  `terminal_liquidation_equity`.
- **Metrics** derive from the reconciled equity curve. Total return =
  terminal / initial − 1; CAGR uses the recorded start (first open) and end
  (last close) times; Sharpe/Sortino annualize only from the validated
  regular interval (365.25-day year) or an explicit `periods_per_year`.
  Turnover = total traded notional / initial cash; trade count = executed
  fills. Invalid (non-positive) equity is rejected.
- **Costs are on by default** — frictionless runs require an explicit
  `CostModel(0.0, 0.0)`.

## Project layout

```
src/eth_research/
    data/           # strict OHLCV schema, CSV/Parquet loaders, synthetic generator
    splits.py       # chronological splits + warm-up context helpers
    strategies/     # Strategy interface, buy-and-hold, SMA crossover
    backtest.py     # bar-by-bar portfolio engine: open fills, fees, ledger
    metrics.py      # equity-curve metrics: return, CAGR, Sharpe, Sortino, drawdown
tests/              # unit, hand-calculated ledger, and look-ahead regression tests
examples/           # runnable end-to-end example
docs/PLAN.md        # milestone plan
docs/REMEDIATION.md # Milestone 1 correctness remediation record
```

## Development

```bash
pytest                    # run the test suite
ruff format --check .     # formatting
ruff check .              # lint
mypy src tests examples   # strict type checking
```

## Roadmap

See [docs/PLAN.md](docs/PLAN.md) for the milestone plan and
[docs/REMEDIATION.md](docs/REMEDIATION.md) for the Milestone 1 correctness
remediation record.
