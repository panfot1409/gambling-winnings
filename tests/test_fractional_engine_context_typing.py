"""Acceptance-audit reproduction: the engine boundary must raise EngineError.

Independent acceptance finding A2 (Class C): ``run_fractional_backtest`` validates
a warm-up ``context`` against the evaluation ``frame`` in ``_validate_context``,
which derives the bar interval with ``frame_interval(frame)``. When the evaluation
frame has a single row the interval is under-determined and ``frame_interval``
raises a *bare* ``ValueError('need at least 2 candles to determine the interval')``
— it leaks out of the public engine instead of the engine's typed ``EngineError``,
breaking the "every malformed segment the engine refuses raises ``EngineError``"
contract that the rest of ``_validate_context`` (and ``_require_canonical``) upholds.

The same 1-row frame runs cleanly with ``context=None`` (asserted here as a
control), so the fix only re-types the context-boundary rejection; it changes no
accept/reject decision for any multi-row segment and no financial byte.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eth_research.data.schema import validate_ohlcv
from eth_research.fractional.cost_model import COMPATIBILITY_V1
from eth_research.fractional.engine import EngineError, run_fractional_backtest
from eth_research.fractional.strategies import FractionalStrategy, RiskConfig
from eth_research.strategies.base import Strategy


def _frame(start: str, n: int) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    close = 100.0 + np.arange(n, dtype="float64")
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    vol = np.full(n, 1_000.0)
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx
    )
    return validate_ohlcv(frame, expected_interval="1D")


class _Flat(Strategy):
    @property
    def name(self) -> str:
        return "flat"

    def target_positions(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(np.zeros(len(data)), index=data.index, name="t")


def _strategy() -> FractionalStrategy:
    return FractionalStrategy("flat", _Flat(), RiskConfig(max_exposure=1.0), warmup_bars=0)


def test_one_row_frame_runs_without_a_context() -> None:
    # Control: a single-bar evaluation frame is legal on its own (interval never
    # needed), so this must NOT raise — the defect is scoped to context validation.
    result = run_fractional_backtest(
        _frame("2020-01-06", 1), _strategy(), COMPATIBILITY_V1, initial_cash=10_000.0
    )
    assert result.num_fills == 0


def test_one_row_frame_with_context_raises_engine_error_not_bare_value_error() -> None:
    # A 5-bar strictly-past, contiguous context attached to a 1-row frame forces
    # ``frame_interval(frame)`` inside ``_validate_context``; the refusal must be
    # a typed ``EngineError``, never a bare ``ValueError`` leaking from the schema.
    context = _frame("2020-01-01", 5)  # ends 2020-01-05
    one = _frame("2020-01-06", 1)  # the contiguous next bar
    with pytest.raises(EngineError):
        run_fractional_backtest(
            one, _strategy(), COMPATIBILITY_V1, initial_cash=10_000.0, context=context
        )
