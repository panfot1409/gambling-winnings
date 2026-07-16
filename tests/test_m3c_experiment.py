"""M3C fold-frame construction, common-context equality, and no-context-P&L.

Read-only: reconstructs the research-train partition offline (research-train rows
only — no sealed partition is ever touched) and exercises a few fold-0 cells.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import eth_research
from eth_research.data.schema import validate_ohlcv
from eth_research.fractional.cost_model import COMPATIBILITY_V1
from eth_research.fractional.dataset import verify_dataset_integrity_only
from eth_research.fractional.engine import run_fractional_backtest
from eth_research.fractional.strategies import STRATEGIES_BY_NAME
from eth_research.m3c.candidate import M3C_MAX_CONTEXT_BARS, build_candidate_strategy
from eth_research.m3c.experiment import build_m3c_fold_frames
from eth_research.m3c.strategy import DualHorizonTrend
from eth_research.walkforward import (
    WALK_FORWARD_PROTOCOL_RELPATH,
    WalkForwardProtocol,
    load_walk_forward_protocol,
)

REPO = Path(eth_research.__file__).resolve().parents[2]


def _research_train() -> pd.DataFrame:
    return verify_dataset_integrity_only(REPO).research_train


def _wf() -> WalkForwardProtocol:
    return load_walk_forward_protocol(REPO / WALK_FORWARD_PROTOCOL_RELPATH)


def test_five_folds_with_252_context_on_the_accepted_boundaries() -> None:
    rt, wf = _research_train(), _wf()
    frames = build_m3c_fold_frames(rt, wf)
    assert len(frames) == 5
    for ff, fold in zip(frames, wf.folds, strict=True):
        assert len(ff.context) == min(M3C_MAX_CONTEXT_BARS, fold.training_row_count) == 252
        assert ff.oos.index[0] == fold.oos_first_open_time
        assert ff.oos.index[-1] == fold.oos_last_open_time
        assert ff.context.index[-1] < ff.oos.index[0]  # strictly before, no overlap
        # context rows are research-train rows strictly inside the training window
        assert ff.context.index[0] >= rt.index[0]


def test_mutating_context_older_than_the_lookback_changes_only_the_candidate() -> None:
    # Equal information availability, correct lookbacks: every OOS bar has >= 252 prior
    # bars, so mutating the *oldest* context rows (well beyond Donchian's 55-bar reach
    # from any OOS bar) cannot change Donchian, but the 252-day candidate — whose first
    # OOS bar reaches back to the very first context row — is changed.
    rt, wf = _research_train(), _wf()
    fold0 = build_m3c_fold_frames(rt, wf)[0]
    donchian = STRATEGIES_BY_NAME["donchian_55_20"]
    candidate = build_candidate_strategy()

    ctx = fold0.context.copy()
    old = ctx.iloc[:150].copy()  # rows 0..149: >55 bars before the first OOS decision
    for col in ("open", "high", "low", "close"):
        old[col] = old[col] * 1.5  # scale OHLC together (stays valid OHLCV)
    mutated_ctx = pd.concat([old, ctx.iloc[150:]])

    d_base = run_fractional_backtest(fold0.oos, donchian, COMPATIBILITY_V1, context=fold0.context)
    d_mut = run_fractional_backtest(fold0.oos, donchian, COMPATIBILITY_V1, context=mutated_ctx)
    assert d_base.equity.equals(d_mut.equity)  # older context is outside Donchian's reach

    c_base = run_fractional_backtest(fold0.oos, candidate, COMPATIBILITY_V1, context=fold0.context)
    c_mut = run_fractional_backtest(fold0.oos, candidate, COMPATIBILITY_V1, context=mutated_ctx)
    assert not c_base.equity.equals(c_mut.equity)  # the 252-day candidate does reach it


def test_the_same_context_frame_serves_every_strategy_and_creates_no_pnl() -> None:
    rt, wf = _research_train(), _wf()
    fold0 = build_m3c_fold_frames(rt, wf)[0]
    # The candidate and a benchmark receive the identical context index (one frame).
    candidate = build_candidate_strategy()
    cash = STRATEGIES_BY_NAME["cash"]
    r_cand = run_fractional_backtest(fold0.oos, candidate, COMPATIBILITY_V1, context=fold0.context)
    r_cash = run_fractional_backtest(fold0.oos, cash, COMPATIBILITY_V1, context=fold0.context)
    # Context is warm-up only: equity is one value per OOS bar, none per context bar.
    assert len(r_cand.equity) == len(fold0.oos)
    assert r_cand.equity.index.equals(fold0.oos.index)
    # Cash creates no P&L at all — equity stays exactly at the initial cash.
    assert bool((r_cash.equity.to_numpy() == r_cash.initial_cash).all())


def test_composed_candidate_target_is_directional_times_vol_and_stays_in_unit_range() -> None:
    rt, wf = _research_train(), _wf()
    fold0 = build_m3c_fold_frames(rt, wf)[0]
    candidate = build_candidate_strategy()
    result = run_fractional_backtest(fold0.oos, candidate, COMPATIBILITY_V1, context=fold0.context)
    # Independent directional signal over the full (context + OOS) frame.
    full = candidate.signal.target_positions(pd.concat([fold0.context, fold0.oos])).to_numpy()
    context_bars = len(fold0.context)
    for t, bar in enumerate(result.bars):
        assert 0.0 <= bar.executable_target <= 1.0  # unit range
        directional = full[context_bars + t - 1] if context_bars + t - 1 >= 0 else 0.0
        if directional == 0.0:
            # flat directional ⇒ zero target regardless of volatility
            assert bar.executable_target == 0.0
        else:
            # long directional ⇒ target is the vol scalar min(1, 0.5/vol) ≤ 1
            assert bar.executable_target > 0.0
            assert bar.volatility_scale is not None
            assert bar.executable_target == pytest.approx(bar.volatility_scale)


def test_flat_directional_run_holds_only_cash() -> None:
    # A strictly-decreasing synthetic frame makes both momenta negative ⇒ always flat;
    # the composed candidate must then never fill and hold its initial cash.
    n = 400
    close = 200.0 * (0.999 ** np.arange(n))
    idx = pd.date_range("2016-01-01", periods=n, freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=idx,
    )
    frame = validate_ohlcv(frame, expected_interval="1D")
    context, oos = frame.iloc[:300], frame.iloc[300:]
    result = run_fractional_backtest(
        oos, build_candidate_strategy(), COMPATIBILITY_V1, context=context
    )
    assert DualHorizonTrend().target_positions(frame).to_numpy().sum() == 0.0  # all flat
    assert result.num_fills == 0
    assert bool((result.equity.to_numpy() == result.initial_cash).all())
