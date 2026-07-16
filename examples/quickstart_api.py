"""Offline quickstart for the public API.

Generates a deterministic synthetic dataset, splits it chronologically, runs a binary
backtest on the validation segment with a warm-up context, and prints a couple of metrics.
No network, no files, no credentials.
"""

from __future__ import annotations

from eth_research.api import (
    ChronologicalSplitSpec,
    CostSpec,
    StrategySpec,
    chronological_split,
    generate_synthetic_dataset,
    run_binary_backtest,
)


def main() -> None:
    dataset = generate_synthetic_dataset(n_periods=400, seed=0)
    splits = chronological_split(dataset, ChronologicalSplitSpec())
    result = run_binary_backtest(
        splits.validation,
        StrategySpec.create("moving_average_crossover", fast_window=10, slow_window=30),
        CostSpec("base"),
        context=splits.validation_context(30),
    )
    metrics = result.metric_map()
    print(f"run engine: {result.run_spec.engine}")
    print(f"terminal equity: {metrics['terminal_equity']}")
    print(f"total return: {metrics['total_return']}")
    print(f"result sha256: {result.result_sha256}")


if __name__ == "__main__":
    main()
