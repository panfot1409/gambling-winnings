"""V2B §19 walk-forward folds, causal candidate wiring, evaluation, and causal regimes.

These exercise the evaluation *machinery* on a deterministic synthetic joint panel — never the real
research-train (that is the one-shot run). The load-bearing property is causality: a candidate's
executed weight at bar ``t`` must depend only on closes strictly before ``open[t]``.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from eth_research.v2b import evaluation as ev
from eth_research.v2b import folds as fld
from eth_research.v2b import regimes as rg
from eth_research.v2b.candidates import CANDIDATE_A, CANDIDATE_B, WEIGHT_BTC, WEIGHT_ETH
from eth_research.v2b.scenarios import COST_SCENARIOS, PRIMARY_COST, STRESSED_COST


def _synthetic_panel(rows: int = fld.EXPECTED_ROWS) -> pd.DataFrame:
    """A deterministic joint ETH/BTC daily panel (seeded random walk; test fixture, not real)."""
    rng = np.random.default_rng(20260719)
    index = pd.date_range("2016-05-23", periods=rows, freq="D", tz="UTC")
    eth = 10.0 * np.cumprod(1.0 + rng.normal(0.0008, 0.03, rows))
    btc = 450.0 * np.cumprod(1.0 + rng.normal(0.0006, 0.025, rows))
    frame = {}
    for name, close in (("eth", eth), ("btc", btc)):
        frame[f"{name}_open"] = close * 0.999
        frame[f"{name}_high"] = close * 1.02
        frame[f"{name}_low"] = close * 0.98
        frame[f"{name}_close"] = close
        frame[f"{name}_volume"] = np.full(rows, 1_000.0)
    return pd.DataFrame(frame, index=index)


def _bump_final_close(panel: pd.DataFrame, factor: float) -> pd.DataFrame:
    """Multiply only the final ETH and BTC close by ``factor`` (leaves every earlier bar intact)."""
    bumped = panel.copy()
    for col in ("eth_close", "btc_close"):
        values = bumped[col].to_numpy(dtype=float).copy()
        values[-1] *= factor
        bumped[col] = values
    return bumped


def test_folds_cover_the_post_warmup_window_contiguously() -> None:
    index = pd.DatetimeIndex(_synthetic_panel().index)
    folds = fld.build_oos_folds(index)
    assert len(folds) == fld.OOS_FOLD_COUNT
    assert folds[0].start == fld.WARMUP_ROWS
    assert folds[-1].stop == fld.EXPECTED_ROWS
    # Contiguous and disjoint: each fold starts where the previous stopped.
    for prev, nxt in pairwise(folds):
        assert nxt.start == prev.stop
    total = sum(f.row_count for f in folds)
    assert total == fld.EXPECTED_ROWS - fld.WARMUP_ROWS


def test_series_by_fold_matches_row_ranges() -> None:
    panel = _synthetic_panel()
    index = pd.DatetimeIndex(panel.index)
    folds = fld.build_oos_folds(index)
    series = pd.Series(np.arange(len(index), dtype=float), index=index)
    by_fold = fld.series_by_fold(series, folds)
    for fold in folds:
        got = by_fold[fold.fold_index].to_numpy()
        assert got[0] == fold.start
        assert got[-1] == fold.stop - 1


def test_executed_path_is_the_signal_shifted_one_bar() -> None:
    panel = _synthetic_panel()
    raw = ev.candidate_raw_weights(CANDIDATE_A, panel)
    executed = ev.candidate_execution_path(CANDIDATE_A, panel)
    assert float(executed[WEIGHT_ETH].iloc[0]) == 0.0  # first bar flat (no prior signal)
    assert float(executed[WEIGHT_BTC].iloc[0]) == 0.0
    # Executed weight at t equals the raw signal at t-1 (a strict one-bar causal shift).
    assert np.allclose(executed[WEIGHT_ETH].to_numpy()[1:], raw[WEIGHT_ETH].to_numpy()[:-1])


def test_no_look_ahead_perturbing_the_last_close_changes_nothing_earlier() -> None:
    panel = _synthetic_panel()
    baseline = ev.candidate_execution_path(CANDIDATE_B, panel)
    bumped = _bump_final_close(panel, 1.5)
    perturbed = ev.candidate_execution_path(CANDIDATE_B, bumped)
    # Every executed weight strictly before the final bar is unchanged: the rule cannot see the
    # future close it would otherwise leak through.
    assert np.array_equal(
        baseline[WEIGHT_ETH].to_numpy()[:-1], perturbed[WEIGHT_ETH].to_numpy()[:-1]
    )
    assert np.array_equal(
        baseline[WEIGHT_BTC].to_numpy()[:-1], perturbed[WEIGHT_BTC].to_numpy()[:-1]
    )


@pytest.mark.parametrize("spec", [CANDIDATE_A, CANDIDATE_B])
def test_evaluate_candidate_produces_full_evidence(spec: object) -> None:
    panel = _synthetic_panel()
    folds = fld.build_oos_folds(pd.DatetimeIndex(panel.index))
    result = ev.evaluate_candidate(
        spec,  # type: ignore[arg-type]
        panel,
        folds,
        primary_cost=COST_SCENARIOS[PRIMARY_COST],
        stressed_cost=COST_SCENARIOS[STRESSED_COST],
    )
    assert result.benchmark == "eth_buy_and_hold"
    assert result.fold_count == fld.OOS_FOLD_COUNT
    assert 0 <= result.folds_beating_benchmark <= fld.OOS_FOLD_COUNT
    assert result.primary_ci_lower <= result.primary_point_estimate <= result.primary_ci_upper
    assert isinstance(result.primary_lower_above_zero, bool)
    assert np.isfinite(result.aggregate_sharpe)


def test_regime_is_causal_and_lagged() -> None:
    panel = _synthetic_panel()
    regime = rg.causal_btc_trend_regime(panel, lookback=50)
    # The first `lookback` bars have no full lagged window -> warmup.
    assert (regime.iloc[:50] == rg.REGIME_WARMUP).all()
    # Perturbing the final close cannot change any earlier regime label (labels use close[t-1]).
    bumped = _bump_final_close(panel, 2.0)
    perturbed = rg.causal_btc_trend_regime(bumped, lookback=50)
    assert list(regime.to_numpy()[:-1]) == list(perturbed.to_numpy()[:-1])


def test_regime_paired_means_reports_present_regimes() -> None:
    panel = _synthetic_panel()
    regime = rg.causal_btc_trend_regime(panel, lookback=50)
    cand = ev.candidate_net_returns(CANDIDATE_A, panel, COST_SCENARIOS[PRIMARY_COST])
    bench = ev.benchmark_net_returns(panel, "eth_buy_and_hold", COST_SCENARIOS[PRIMARY_COST])
    means = rg.regime_paired_means(cand.net_return_series(), bench.net_return_series(), regime)
    assert set(means).issubset(set(rg.REGIME_LABELS))
    for stats in means.values():
        assert stats["observation_count"] > 0
        assert np.isfinite(stats["mean_paired_log_excess"])
