"""The one new Milestone 3C candidate signal: dual-horizon trend consensus.

The directional signal requires agreement between a medium-horizon (63-day) and a
long-horizon (252-day) *positive absolute momentum*; it emits a binary target
(``0.0``/``1.0``). The 50%-annual volatility scaling is **not** applied here — it is
the reviewed M3B ``apply_volatility_target`` overlay, attached via ``RiskConfig`` in
:mod:`eth_research.m3c.candidate`, so the candidate reuses the audited engine.

Causality (mirrors the ``Strategy`` contract): the value at row ``t`` is decided
after observing ``close[t]`` and the engine executes it at ``open[t+1]``. Each
momentum uses only ``close[t]`` and a strictly earlier close (``close[t-63]`` /
``close[t-252]``); rows with insufficient warm-up history are flat; exactly-zero
momentum (strict ``>``) is flat. No future row, no same-bar close beyond ``t``, and
no full-sample statistic is read.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from eth_research.strategies.base import Strategy

MEDIUM_HORIZON: int = 63
LONG_HORIZON: int = 252


class DualHorizonTrend(Strategy):
    """Long ETH only when medium- and long-horizon absolute momentum are both > 0."""

    initial_target = 0  # data-driven: flat at the first evaluated open (no warm-up)

    def __init__(self, *, medium_horizon: int = MEDIUM_HORIZON, long_horizon: int = LONG_HORIZON):
        for label, value in (("medium_horizon", medium_horizon), ("long_horizon", long_horizon)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{label} must be an int, got {value!r}")
            if value <= 0:
                raise ValueError(f"{label} must be positive, got {value!r}")
        if medium_horizon >= long_horizon:
            raise ValueError(
                f"medium_horizon ({medium_horizon}) must be < long_horizon ({long_horizon})"
            )
        self._medium = medium_horizon
        self._long = long_horizon

    @property
    def name(self) -> str:
        return "dual_horizon_trend"

    @property
    def medium_horizon(self) -> int:
        return self._medium

    @property
    def long_horizon(self) -> int:
        return self._long

    def target_positions(self, data: pd.DataFrame) -> pd.Series:
        if "close" not in data.columns:
            raise ValueError("dual_horizon_trend requires a 'close' column")
        close = data["close"].to_numpy(dtype="float64")
        n = close.size
        if not np.isfinite(close).all() or (close <= 0.0).any():
            raise ValueError("dual_horizon_trend requires finite positive closes")
        target = np.zeros(n, dtype="float64")
        # The long horizon dominates: close[t-252] exists only for t >= long, which
        # also guarantees close[t-63] exists. Before then the target is flat.
        if n > self._long:
            t = np.arange(self._long, n)
            medium_positive = (close[t] / close[t - self._medium] - 1.0) > 0.0
            long_positive = (close[t] / close[t - self._long] - 1.0) > 0.0
            target[t] = np.where(medium_positive & long_positive, 1.0, 0.0)
        return pd.Series(target, index=data.index, name="target")
