# ETH Trading Research

A research-only Python toolkit for developing and evaluating Ethereum (ETH)
trading algorithms on historical OHLCV data.

> **Research only — by design.** This project contains **no** live trading,
> **no** exchange connectivity or API authentication, **no** wallet
> integration, and **no** leverage, margin, or short selling. It loads
> historical data from local files and evaluates strategies offline. Nothing
> here places orders or touches funds, and the backtest engine rejects
> leveraged positions.

## Requirements

- Python 3.12+

## Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quickstart

Run the end-to-end example — buy-and-hold benchmark vs an SMA crossover,
with fees and slippage, on a chronological validation segment:

```bash
python examples/run_sma_backtest.py                              # synthetic demo data
python examples/run_sma_backtest.py data/eth_daily.csv           # your own OHLCV file
python examples/run_sma_backtest.py --fast 10 --slow 30 --segment test
```

Typical output:

```
Data:    synthetic demo data (730 daily bars, seed 42)
Segment: validation (146 bars, 2021-03-14 00:00:00+00:00 .. 2021-08-06 00:00:00+00:00)
Costs:   10.0 bps fee + 5.0 bps slippage per trade

buy_and_hold
  n_periods         146
  total_return      -4.00%
  sharpe            -0.08
  max_drawdown      -22.44%
  ...
```

Or from Python:

```python
from eth_research.backtest import CostModel, run_backtest
from eth_research.data import load_ohlcv
from eth_research.metrics import summarize
from eth_research.splits import chronological_split
from eth_research.strategies import BuyAndHold, MovingAverageCrossover

data = load_ohlcv("data/eth_daily.csv")
splits = chronological_split(data)  # 60% train / 20% validation / 20% test

result = run_backtest(
    splits.validation,
    MovingAverageCrossover(fast_window=20, slow_window=50),
    CostModel(fee_rate=0.001, slippage_rate=0.0005),
)
print(summarize(result))
```

## Data format

`load_ohlcv` reads `.csv`, `.parquet`, or `.pq` files with one row per
completed bar:

| column      | type                                   |
|-------------|----------------------------------------|
| `timestamp` | ISO-8601 datetime (naive = assumed UTC) |
| `open`      | float, > 0                             |
| `high`      | float, >= max(open, close)             |
| `low`       | float, <= min(open, close)             |
| `close`     | float, > 0                             |
| `volume`    | float, >= 0                            |

Files with epoch timestamps load via
`load_ohlcv(path, timestamp_unit="ms")`. Every load is validated against the
schema; all problems in a file are reported together. Data files live in the
git-ignored `data/` directory — market data is never committed.

## Conventions

- **UTC everywhere.** Validated frames use a `datetime64[ns, UTC]` index.
- **Close-to-close returns.** `r_t = close_t / close_{t-1} - 1`.
- **One-bar execution lag.** A signal computed at bar `t` is held during bar
  `t+1`; strategies cannot trade on the bar they just observed.
- **Costs by default.** `(fee_rate + slippage_rate) × |Δposition|` per
  trade; frictionless runs require an explicit `CostModel(0.0, 0.0)`.
- **Long-only, unlevered.** Positions are fractions of equity in `[0, 1]`;
  the engine rejects anything else.
- **365.25-day years** for annualization (crypto trades continuously).

## Project layout

```
src/eth_research/
    data/           # OHLCV schema, CSV/Parquet loaders, synthetic generator
    splits.py       # chronological train/validation/test splits
    strategies/     # Strategy interface, buy-and-hold, SMA crossover
    backtest.py     # vectorized engine: execution lag, fees, slippage
    metrics.py      # total return, CAGR, Sharpe, Sortino, drawdown, turnover
tests/              # unit, oracle, and look-ahead-bias regression tests
examples/           # runnable end-to-end example
docs/PLAN.md        # milestone plan
```

## Development

```bash
pytest                    # run the test suite
ruff format --check .     # formatting
ruff check .              # lint
mypy                      # type checking
```

## Roadmap

See [docs/PLAN.md](docs/PLAN.md) for the milestone plan. Milestone 1
(foundations: validated data schema, loaders, chronological splits,
benchmark + SMA strategies, cost-aware backtesting, metrics, and
look-ahead-bias tests) is implemented on this branch.
