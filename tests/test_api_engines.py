"""Public dataset/strategy/backtest/receipt behaviour, determinism, and engine compatibility."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from eth_research import api
from eth_research.backtest import run_backtest
from eth_research.costs import cost_scenario
from eth_research.fractional.cost_model import SCENARIOS_BY_NAME
from eth_research.fractional.engine import run_fractional_backtest as _internal_fractional
from eth_research.fractional.metrics import compute_fractional_metrics
from eth_research.fractional.strategies import STRATEGIES_BY_NAME
from eth_research.metrics import periods_per_year_from_interval, summarize
from eth_research.strategies import MovingAverageCrossover

# --------------------------------------------------------------------------- #
# datasets                                                                    #
# --------------------------------------------------------------------------- #


def test_synthetic_dataset_is_deterministic() -> None:
    a = api.generate_synthetic_dataset(n_periods=200, seed=11)
    b = api.generate_synthetic_dataset(n_periods=200, seed=11)
    assert a.fingerprint == b.fingerprint
    c = api.generate_synthetic_dataset(n_periods=200, seed=12)
    assert a.fingerprint != c.fingerprint
    assert a.report.is_valid


def test_validate_dataset_rejects_non_dataframe_and_bad_schema() -> None:
    with pytest.raises(api.DatasetError):
        api.validate_dataset([1, 2, 3], api.DatasetSpec(interval_seconds=86400))  # type: ignore[arg-type]
    bad = pd.DataFrame({"open": [1.0], "close": [1.0]})  # missing columns + index
    with pytest.raises(api.DatasetSchemaError):
        api.validate_dataset(bad, api.DatasetSpec(interval_seconds=86400))


def test_chronological_split_sizes_and_context() -> None:
    ds = api.generate_synthetic_dataset(n_periods=500, seed=1)
    split = api.chronological_split(ds, api.ChronologicalSplitSpec(0.6, 0.2))
    assert split.train.row_count == 300
    assert split.validation.row_count == 100
    assert split.test.row_count == 100
    ctx = split.validation_context(20)
    assert ctx.row_count == 20


def test_split_rejects_tiny_dataset() -> None:
    # Two rows leave an empty validation segment under a 60/20/20 split.
    ds = api.generate_synthetic_dataset(n_periods=2, seed=1)
    with pytest.raises(api.DatasetError):
        api.chronological_split(ds, api.ChronologicalSplitSpec(0.6, 0.2))


# --------------------------------------------------------------------------- #
# strategies                                                                  #
# --------------------------------------------------------------------------- #


def test_build_binary_strategies() -> None:
    assert api.build_binary_strategy(api.StrategySpec("buy_and_hold")).name == "buy_and_hold"
    assert api.build_binary_strategy(api.StrategySpec("cash")).name == "cash"
    mac = api.build_binary_strategy(
        api.StrategySpec.create("moving_average_crossover", fast_window=5, slow_window=20)
    )
    assert mac.name == "sma_5_20"
    don = api.build_binary_strategy(api.StrategySpec("donchian_channel"))
    assert don.name == "donchian_55_20"


def test_build_binary_strategy_rejects_bad_specs() -> None:
    with pytest.raises(api.StrategyError):
        api.build_binary_strategy(api.StrategySpec("no_such_strategy"))
    with pytest.raises(api.StrategyError):
        api.build_binary_strategy(api.StrategySpec.create("buy_and_hold", window=5))
    with pytest.raises(api.StrategyError):
        api.build_binary_strategy(
            api.StrategySpec.create("moving_average_crossover", fast_window=50, slow_window=20)
        )


def test_build_fractional_strategies() -> None:
    for name in api.FRACTIONAL_STRATEGY_KINDS:
        assert api.build_fractional_strategy(api.StrategySpec(name)).name == name
    with pytest.raises(api.StrategyError):
        api.build_fractional_strategy(api.StrategySpec("no_such"))
    with pytest.raises(api.StrategyError):
        api.build_fractional_strategy(api.StrategySpec.create("cash", window=5))


# --------------------------------------------------------------------------- #
# backtests: determinism + unknown scenarios                                  #
# --------------------------------------------------------------------------- #


def test_binary_backtest_is_deterministic_and_roundtrips() -> None:
    ds = api.generate_synthetic_dataset(n_periods=250, seed=5)
    args = (ds, api.StrategySpec("buy_and_hold"), api.CostSpec("base"))
    r1 = api.run_binary_backtest(*args)
    r2 = api.run_binary_backtest(*args)
    assert r1.to_json_bytes() == r2.to_json_bytes()
    assert (
        api.ResearchResult.from_json_bytes(r1.to_json_bytes()).to_json_bytes() == r1.to_json_bytes()
    )


def test_fractional_backtest_is_deterministic() -> None:
    ds = api.generate_synthetic_dataset(n_periods=250, seed=5)
    args = (ds, api.StrategySpec("buy_and_hold"), api.CostSpec("compatibility_v1"))
    assert (
        api.run_fractional_backtest(*args).to_json_bytes()
        == api.run_fractional_backtest(*args).to_json_bytes()
    )


def test_unknown_cost_scenario_is_configuration_error() -> None:
    ds = api.generate_synthetic_dataset(n_periods=60, seed=1)
    with pytest.raises(api.ConfigurationError):
        api.run_binary_backtest(ds, api.StrategySpec("cash"), api.CostSpec("compatibility_v1"))
    with pytest.raises(api.ConfigurationError):
        api.run_fractional_backtest(ds, api.StrategySpec("cash"), api.CostSpec("base"))


# --------------------------------------------------------------------------- #
# compatibility: public metrics are scalar-identical to the internal engines  #
# --------------------------------------------------------------------------- #


def test_binary_metrics_match_internal_engine_exactly() -> None:
    ds = api.generate_synthetic_dataset(n_periods=300, seed=3)
    internal = summarize(
        run_backtest(
            ds.frame,
            MovingAverageCrossover(fast_window=10, slow_window=30),
            costs=cost_scenario("base").cost_model(),
        )
    )
    public = api.run_binary_backtest(
        ds,
        api.StrategySpec.create("moving_average_crossover", fast_window=10, slow_window=30),
        api.CostSpec("base"),
    ).metric_map()
    assert public["total_return"] == internal.total_return
    assert public["cagr"] == internal.cagr
    assert public["sharpe"] == internal.sharpe
    assert public["sortino"] == internal.sortino
    assert public["max_drawdown"] == internal.max_drawdown
    assert public["turnover"] == internal.turnover
    assert public["num_trades"] == internal.num_trades
    assert public["terminal_equity"] == internal.terminal_equity


def test_fractional_metrics_match_internal_engine_exactly() -> None:
    ds = api.generate_synthetic_dataset(n_periods=300, seed=3)
    result = _internal_fractional(
        ds.frame, STRATEGIES_BY_NAME["donchian_55_20"], SCENARIOS_BY_NAME["causal_proxy_base"]
    )
    ppy = periods_per_year_from_interval(pd.Timedelta(seconds=ds.interval_seconds))
    internal = compute_fractional_metrics(result, periods_per_year=ppy)
    public = api.run_fractional_backtest(
        ds, api.StrategySpec("donchian_55_20"), api.CostSpec("causal_proxy_base")
    ).metric_map()
    assert public["total_return"] == internal.total_return
    assert public["annualized_return"] == internal.annualized_return
    assert public["annualized_volatility"] == internal.annualized_volatility
    assert public["max_drawdown"] == internal.max_drawdown
    assert public["num_fills"] == internal.num_fills
    assert public["turnover"] == internal.turnover
    assert public["total_fees"] == internal.total_fees
    assert public["terminal_equity"] == internal.terminal_equity


# --------------------------------------------------------------------------- #
# receipts                                                                     #
# --------------------------------------------------------------------------- #


def test_receipt_build_verify_and_run_id_determinism() -> None:
    ds = api.generate_synthetic_dataset(n_periods=120, seed=2)
    result_bytes = api.run_binary_backtest(
        ds, api.StrategySpec("buy_and_hold"), api.CostSpec("base")
    ).to_json_bytes()
    report_bytes = b"# report\n"
    config_bytes = b'{\n  "x": 1\n}\n'
    receipt = api.build_receipt(result_bytes, report_bytes=report_bytes, config_bytes=config_bytes)
    # verifies against the exact artifacts
    api.verify_run_receipt(
        receipt, result_bytes=result_bytes, report_bytes=report_bytes, config_bytes=config_bytes
    )
    # run_id recomputes from the same inputs
    again = api.build_receipt(result_bytes, report_bytes=report_bytes, config_bytes=config_bytes)
    assert receipt.run_id == again.run_id
    # receipt itself round-trips
    assert api.RunReceipt.from_json_bytes(receipt.to_json_bytes()) == receipt


def test_receipt_detects_every_tamper() -> None:
    ds = api.generate_synthetic_dataset(n_periods=120, seed=2)
    result_bytes = api.run_binary_backtest(
        ds, api.StrategySpec("cash"), api.CostSpec("base")
    ).to_json_bytes()
    report_bytes = b"# report\n"
    receipt = api.build_receipt(result_bytes, report_bytes=report_bytes)
    # tampered result
    with pytest.raises(api.ReceiptVerificationError):
        api.verify_run_receipt(
            receipt, result_bytes=result_bytes[:-2] + b"7\n", report_bytes=report_bytes
        )
    # missing report that the receipt binds
    with pytest.raises(api.ReceiptVerificationError):
        api.verify_run_receipt(receipt, result_bytes=result_bytes)
    # unexpected config that the receipt does not bind
    with pytest.raises(api.ReceiptVerificationError):
        api.verify_run_receipt(
            receipt, result_bytes=result_bytes, report_bytes=report_bytes, config_bytes=b"x\n"
        )


def test_forged_receipt_field_is_rejected() -> None:
    ds = api.generate_synthetic_dataset(n_periods=120, seed=2)
    result_bytes = api.run_binary_backtest(
        ds, api.StrategySpec("cash"), api.CostSpec("base")
    ).to_json_bytes()
    receipt = api.build_receipt(result_bytes)
    # A receipt whose bound inputs no longer match the result it points at is rejected.
    forged = dataclasses.replace(receipt, initial_cash=99.0)
    with pytest.raises(api.ReceiptVerificationError):
        api.verify_run_receipt(forged, result_bytes=result_bytes)
