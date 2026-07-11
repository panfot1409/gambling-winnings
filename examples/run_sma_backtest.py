"""End-to-end example: buy-and-hold benchmark vs an SMA crossover on ETH data.

Runs on a local CSV/Parquet OHLCV file when a path is given, otherwise on a
deterministic synthetic series so the example works fully offline. When
evaluating the validation or test segment, trailing rows from the preceding
segments are passed to the engine as indicator warm-up context (signals
only — they contribute no P&L).

Usage:
    python examples/run_sma_backtest.py
    python examples/run_sma_backtest.py data/eth_daily.csv --fast 20 --slow 50
"""

from __future__ import annotations

import argparse

import pandas as pd

from eth_research.backtest import CostModel, run_backtest
from eth_research.data.load import load_ohlcv
from eth_research.data.synthetic import make_synthetic_ohlcv
from eth_research.metrics import PerformanceSummary, summarize
from eth_research.splits import chronological_split
from eth_research.strategies import BuyAndHold, MovingAverageCrossover

FORMATS = {
    "n_periods": "{:d}",
    "periods_per_year": "{:.1f}",
    "initial_equity": "{:,.2f}",
    "terminal_equity": "{:,.2f}",
    "total_return": "{:+.2%}",
    "cagr": "{:+.2%}",
    "sharpe": "{:.2f}",
    "sortino": "{:.2f}",
    "max_drawdown": "{:+.2%}",
    "total_traded_notional": "{:,.2f}",
    "turnover": "{:.2f}",
    "num_trades": "{:d}",
}


def print_summary(summary: PerformanceSummary) -> None:
    values = summary.as_dict()
    print(summary.strategy_name)
    print(f"  window            {summary.start_time} .. {summary.end_time}")
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
    parser.add_argument("--fee-bps", type=float, default=10.0, help="fee per fill, basis points")
    parser.add_argument(
        "--slippage-bps", type=float, default=5.0, help="directional slippage, basis points"
    )
    parser.add_argument(
        "--initial-cash", type=float, default=10_000.0, help="cash committed at the first open"
    )
    parser.add_argument(
        "--segment",
        choices=["train", "validation", "test", "full"],
        default="validation",
        help="chronological segment to evaluate on (default: validation)",
    )
    parser.add_argument(
        "--warmup-bars",
        type=int,
        default=None,
        help="preceding rows passed as indicator warm-up context "
        "(default: the slow SMA window; 0 disables)",
    )
    parser.add_argument(
        "--assume-utc",
        action="store_true",
        help="interpret timezone-naive file timestamps as UTC (explicit opt-in)",
    )
    args = parser.parse_args()

    if args.data_path:
        data = load_ohlcv(args.data_path, assume_utc=args.assume_utc)
        source = args.data_path
    else:
        data = make_synthetic_ohlcv(n_periods=730, seed=42)
        source = "synthetic demo data (730 daily bars, seed 42)"

    context: pd.DataFrame | None = None
    if args.segment == "full":
        segment = data
    else:
        splits = chronological_split(data)
        print("Split boundaries (candle open times):")
        for name, (first, last) in splits.boundaries().items():
            print(f"  {name:<10} {first} .. {last}")
        print()
        segment = getattr(splits, args.segment)
        warmup = args.slow if args.warmup_bars is None else args.warmup_bars
        if warmup > 0:
            if args.segment == "validation":
                context = splits.validation_context(min(warmup, len(splits.train)))
            elif args.segment == "test":
                preceding = len(splits.train) + len(splits.validation)
                context = splits.test_context(min(warmup, preceding))

    costs = CostModel(fee_rate=args.fee_bps / 10_000, slippage_rate=args.slippage_bps / 10_000)

    print(f"Data:    {source}")
    print(f"Segment: {args.segment} ({len(segment)} bars)")
    print(f"Context: {0 if context is None else len(context)} warm-up bars (signals only, no P&L)")
    print(f"Costs:   {args.fee_bps:.1f} bps fee + {args.slippage_bps:.1f} bps slippage per fill")
    print("Terminal positions are marked to market at the last close, not liquidated.")
    print()

    for strategy in (
        BuyAndHold(),
        MovingAverageCrossover(fast_window=args.fast, slow_window=args.slow),
    ):
        result = run_backtest(
            segment, strategy, costs, initial_cash=args.initial_cash, context=context
        )
        print_summary(summarize(result))


if __name__ == "__main__":
    main()
