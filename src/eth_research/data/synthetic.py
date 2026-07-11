"""Deterministic synthetic OHLCV series for tests and offline examples.

Synthetic data keeps real market data (and its licensing terms) out of the
repository while still exercising the full research pipeline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from eth_research.data.schema import validate_ohlcv


def make_synthetic_ohlcv(
    n_periods: int = 500,
    *,
    freq: str = "1D",
    start: str | pd.Timestamp = "2020-01-01",
    start_price: float = 1_000.0,
    drift: float = 0.0002,
    volatility: float = 0.02,
    seed: int = 0,
) -> pd.DataFrame:
    """Simulate a geometric-random-walk OHLCV history.

    The same arguments always produce the same frame (seeded RNG).
    ``drift`` and ``volatility`` are per-period log-return moments.
    """
    if n_periods < 1:
        raise ValueError(f"n_periods must be positive, got {n_periods}")
    if start_price <= 0:
        raise ValueError(f"start_price must be positive, got {start_price}")
    if volatility < 0:
        raise ValueError(f"volatility must be non-negative, got {volatility}")

    rng = np.random.default_rng(seed)
    log_returns = rng.normal(loc=drift, scale=volatility, size=n_periods)
    close = start_price * np.exp(np.cumsum(log_returns))
    open_ = np.concatenate(([start_price], close[:-1]))
    wick = np.abs(rng.normal(loc=0.0, scale=volatility / 2.0, size=n_periods))
    high = np.maximum(open_, close) * (1.0 + wick)
    low = np.minimum(open_, close) / (1.0 + wick)
    volume = rng.lognormal(mean=10.0, sigma=0.5, size=n_periods)

    start_ts = pd.Timestamp(start)
    start_ts = start_ts.tz_localize("UTC") if start_ts.tz is None else start_ts.tz_convert("UTC")
    index = pd.date_range(start=start_ts, periods=n_periods, freq=freq)
    frame = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
    return validate_ohlcv(frame)
