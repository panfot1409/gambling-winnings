"""End-to-end example: buy-and-hold benchmark vs an SMA crossover on ETH data.

Runs on a local CSV/Parquet OHLCV file when a path is given, otherwise on a
deterministic synthetic series so the example works fully offline.

Usage:
    python examples/run_sma_backtest.py
    python examples/run_sma_backtest.py data/eth_daily.csv --fast 20 --slow 50
"""

from __future__ import annotations

import argparse

from eth_research.backtest import CostModel, run_backtest
from eth_research.data.load import load_ohlcv
from eth_research.data.synthetic import make_synthetic_ohlcv
from eth_research.metrics import PerformanceSummary, summarize
from eth_research.splits import chronological_split
from eth_research.strategies import BuyAndHold, MovingAverageCrossover

FORMATS = {
    "n_periods": "{:d}",
    "periods_per_year": "{:.1f}",
    "total_return": "{:+.2%}",
    "cagr": "{:+.2%}",
    "sharpe": "{:.2f}",
    "sortino": "{:.2f}",
    "max_drawdown": "{:+.2%}",
    "total_turnover": "{:.2f}",
    "num_trades": "{:d}",
}


def print_summary(summary: PerformanceSummary) -> None:
    values = summary.as_dict()
    print(summary.strategy_name)
    for key, fmt in FORMATS.items():
        print(f"  {key:<17} {fmt.format(values[key])}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "data_path",
        nargs="?",
        help="OHLCV .csv/.parquet file; omit to run on synthetic demo data",
    )
    parser.add_argument("--fast", type=int, default=20, help="fast SMA window (bars)")
    parser.add_argument("--slow", type=int, default=50, help="slow SMA window (bars)")
    parser.add_argument("--fee-bps", type=float, default=10.0, help="fee per trade, basis points")
    parser.add_argument(
        "--slippage-bps", type=float, default=5.0, help="slippage per trade, basis points"
    )
    parser.add_argument(
        "--segment",
        choices=["train", "validation", "test", "full"],
        default="validation",
        help="chronological segment to evaluate on (default: validation)",
    )
    args = parser.parse_args()

    if args.data_path:
        data = load_ohlcv(args.data_path)
        source = args.data_path
    else:
        data = make_synthetic_ohlcv(n_periods=730, seed=42)
        source = "synthetic demo data (730 daily bars, seed 42)"

    segment = data if args.segment == "full" else getattr(chronological_split(data), args.segment)

    costs = CostModel(fee_rate=args.fee_bps / 10_000, slippage_rate=args.slippage_bps / 10_000)

    print(f"Data:    {source}")
    print(
        f"Segment: {args.segment} ({len(segment)} bars, {segment.index[0]} .. {segment.index[-1]})"
    )
    print(f"Costs:   {args.fee_bps:.1f} bps fee + {args.slippage_bps:.1f} bps slippage per trade")
    print()

    for strategy in (
        BuyAndHold(),
        MovingAverageCrossover(fast_window=args.fast, slow_window=args.slow),
    ):
        print_summary(summarize(run_backtest(segment, strategy, costs)))


if __name__ == "__main__":
    main()
