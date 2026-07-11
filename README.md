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
