"""Deterministic synthetic performance diagnostics with broad regression budgets.

These are not micro-benchmarks; the budgets are deliberately loose and only catch
catastrophic (super-linear) complexity regressions and unbounded output growth.
"""

from __future__ import annotations

import time

from eth_research import api


def test_validation_and_fingerprint_scale_to_50k_bars() -> None:
    start = time.perf_counter()
    dataset = api.generate_synthetic_dataset(n_periods=50_000, seed=0)
    elapsed = time.perf_counter() - start
    assert dataset.row_count == 50_000
    assert dataset.fingerprint.startswith("sha256:")
    assert elapsed < 30.0, f"50k-bar generate+validate+fingerprint took {elapsed:.1f}s"


def test_binary_backtest_scales_to_10k_bars() -> None:
    dataset = api.generate_synthetic_dataset(n_periods=10_000, seed=0)
    start = time.perf_counter()
    result = api.run_binary_backtest(
        dataset,
        api.StrategySpec.create("moving_average_crossover", fast_window=20, slow_window=50),
        api.CostSpec("base"),
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 30.0, f"10k-bar binary backtest took {elapsed:.1f}s"
    # the result artifact is small and bounded regardless of input length
    assert len(result.to_json_bytes()) < 50_000


def test_fractional_backtest_scales_to_10k_bars() -> None:
    dataset = api.generate_synthetic_dataset(n_periods=10_000, seed=0)
    start = time.perf_counter()
    result = api.run_fractional_backtest(
        dataset, api.StrategySpec("donchian_55_20"), api.CostSpec("causal_proxy_base")
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 60.0, f"10k-bar fractional backtest took {elapsed:.1f}s"
    assert len(result.to_json_bytes()) < 50_000
