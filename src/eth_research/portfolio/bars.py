"""A canonical multi-asset OHLCV bar frame and its content fingerprint.

A bar frame is a :class:`pandas.DataFrame` of completed candles for exactly one
:class:`~eth_research.portfolio.identity.InstrumentId`. :func:`validate_bar_frame` returns a fresh,
canonical copy after enforcing a strict, fail-closed contract: exactly the required columns,
timezone-aware UTC ``open_time``/``close_time`` with ``open_time < close_time`` per row, a strictly
increasing ``open_time`` across rows (no duplicates, never auto-sorted), positive finite OHLC
values that bracket correctly (``low <= min(open, close)``, ``high >= max(open, close)``,
``low <= high``), and a non-negative finite ``volume``. Nothing is repaired, gap-filled, or
mutated in place. :func:`bar_frame_fingerprint` binds the instrument identity and every canonical
row into a domain-separated hash so two frames reconcile exactly iff they carry the same bars.
"""

from __future__ import annotations

import pandas as pd

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio._time import iso_utc
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.validation import (
    domain_hash,
    require_non_negative_finite_float,
    require_positive_finite_float,
)

__all__ = ["BAR_COLUMNS", "bar_frame_fingerprint", "validate_bar_frame"]

#: The exact, ordered column contract of a canonical bar frame.
BAR_COLUMNS = ("open_time", "close_time", "open", "high", "low", "close", "volume")
_PRICE_COLUMNS = ("open", "high", "low", "close")


def validate_bar_frame(
    frame: pd.DataFrame, instrument: InstrumentId, *, allow_extra: bool = False
) -> pd.DataFrame:
    """Return a fresh, canonical copy of ``frame`` after enforcing the strict bar contract.

    ``allow_extra`` permits (and drops) columns beyond :data:`BAR_COLUMNS`; by default any extra
    column is rejected. The caller's frame is never mutated. Every violation raises
    :class:`CanonicalError` naming the instrument's symbol.
    """
    if not isinstance(instrument, InstrumentId):
        raise CanonicalError("bar_frame: expected an InstrumentId")
    if not isinstance(frame, pd.DataFrame):
        raise CanonicalError(f"bar_frame[{instrument.symbol}]: expected a pandas DataFrame")
    symbol = instrument.symbol

    columns = list(frame.columns)
    if len(columns) != len(set(columns)):
        raise CanonicalError(f"bar_frame[{symbol}]: duplicate column labels are not allowed")
    missing = [name for name in BAR_COLUMNS if name not in columns]
    if missing:
        raise CanonicalError(f"bar_frame[{symbol}]: missing required column(s) {missing}")
    if not allow_extra:
        extra = [name for name in columns if name not in BAR_COLUMNS]
        if extra:
            raise CanonicalError(f"bar_frame[{symbol}]: unexpected column(s) {extra}")

    row_count = len(frame)
    if row_count == 0:
        raise CanonicalError(f"bar_frame[{symbol}]: must contain at least one bar")

    open_times = _utc_column(frame, "open_time", symbol)
    close_times = _utc_column(frame, "close_time", symbol)
    prices = {name: list(frame[name]) for name in _PRICE_COLUMNS}
    volumes = list(frame["volume"])

    canonical_prices: dict[str, list[float]] = {name: [] for name in _PRICE_COLUMNS}
    canonical_volume: list[float] = []
    for row in range(row_count):
        if row > 0 and not open_times[row - 1] < open_times[row]:
            raise CanonicalError(
                f"bar_frame[{symbol}]: open_time must be strictly increasing (row {row})"
            )
        if not open_times[row] < close_times[row]:
            raise CanonicalError(
                f"bar_frame[{symbol}]: open_time must be before close_time (row {row})"
            )
        open_v = require_positive_finite_float(prices["open"][row], f"bar_frame[{symbol}].open")
        high_v = require_positive_finite_float(prices["high"][row], f"bar_frame[{symbol}].high")
        low_v = require_positive_finite_float(prices["low"][row], f"bar_frame[{symbol}].low")
        close_v = require_positive_finite_float(prices["close"][row], f"bar_frame[{symbol}].close")
        if low_v > min(open_v, close_v):
            raise CanonicalError(
                f"bar_frame[{symbol}]: low must be <= min(open, close) (row {row})"
            )
        if high_v < max(open_v, close_v):
            raise CanonicalError(
                f"bar_frame[{symbol}]: high must be >= max(open, close) (row {row})"
            )
        if low_v > high_v:
            raise CanonicalError(f"bar_frame[{symbol}]: low must be <= high (row {row})")
        volume_v = require_non_negative_finite_float(volumes[row], f"bar_frame[{symbol}].volume")
        canonical_prices["open"].append(float(open_v))
        canonical_prices["high"].append(float(high_v))
        canonical_prices["low"].append(float(low_v))
        canonical_prices["close"].append(float(close_v))
        canonical_volume.append(float(volume_v))

    return pd.DataFrame(
        {
            "open_time": pd.Series(open_times, dtype="datetime64[ns, UTC]"),
            "close_time": pd.Series(close_times, dtype="datetime64[ns, UTC]"),
            "open": canonical_prices["open"],
            "high": canonical_prices["high"],
            "low": canonical_prices["low"],
            "close": canonical_prices["close"],
            "volume": canonical_volume,
        }
    )


def _utc_column(frame: pd.DataFrame, name: str, symbol: str) -> list[pd.Timestamp]:
    """The named column as UTC :class:`Timestamp` values (rejects naive or non-datetime dtype)."""
    column = frame[name]
    if not isinstance(column.dtype, pd.DatetimeTZDtype):
        raise CanonicalError(f"bar_frame[{symbol}]: {name} must be timezone-aware UTC timestamps")
    converted = column.dt.tz_convert("UTC")
    values = list(converted)
    if any(pd.isna(value) for value in values):
        raise CanonicalError(f"bar_frame[{symbol}]: {name} must not contain missing timestamps")
    return values


def bar_frame_fingerprint(frame: pd.DataFrame, instrument: InstrumentId) -> str:
    """A domain-separated content hash binding ``instrument`` and every canonical bar of ``frame``.

    Validates (and canonicalizes) ``frame`` first, so the fingerprint of a raw frame equals that of
    its canonical copy and reflects only the bar contents, not incidental dtype or index details.
    """
    canonical = validate_bar_frame(frame, instrument)
    open_times = list(canonical["open_time"])
    close_times = list(canonical["close_time"])
    opens = list(canonical["open"])
    highs = list(canonical["high"])
    lows = list(canonical["low"])
    closes = list(canonical["close"])
    volumes = list(canonical["volume"])
    rows = [
        [
            iso_utc(open_times[row]),
            iso_utc(close_times[row]),
            float(opens[row]),
            float(highs[row]),
            float(lows[row]),
            float(closes[row]),
            float(volumes[row]),
        ]
        for row in range(len(canonical))
    ]
    return domain_hash("bar_frame", {"instrument_id": instrument.instrument_id, "rows": rows})
