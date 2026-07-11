"""Load historical OHLCV data from local CSV or Parquet files."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd

from eth_research.data.schema import TIMESTAMP_COLUMN, validate_ohlcv

TimestampUnit = Literal["s", "ms", "us", "ns"]


def load_ohlcv(
    path: str | Path,
    *,
    timestamp_unit: TimestampUnit | None = None,
    assume_utc: bool = False,
    expected_interval: str | pd.Timedelta | None = None,
    allow_extra_columns: bool = False,
) -> pd.DataFrame:
    """Load one OHLCV history from a ``.csv``/``.parquet`` file and validate it.

    Parameters
    ----------
    path:
        File to load; the format is chosen by extension
        (``.csv``, ``.parquet``, or ``.pq``).
    timestamp_unit:
        Set when the file stores timestamps as epoch numbers (for example
        ``"ms"`` for millisecond exchange dumps). Epoch timestamps are
        interpreted as UTC, which is unambiguous, so ``assume_utc`` is not
        required for them.
    assume_utc:
        Explicit opt-in to interpret timezone-naive textual timestamps as
        UTC; without it, naive timestamps are rejected — even single naive
        values mixed among timezone-aware ones.
    expected_interval:
        Required candle interval (e.g. ``"1D"``); when ``None`` the interval
        is inferred and must be identical between every consecutive candle.
    allow_extra_columns:
        Explicit opt-in to drop columns outside the OHLCV set; without it,
        unexpected columns are rejected by name.

    Returns
    -------
    The canonical OHLCV frame; see
    :func:`eth_research.data.schema.validate_ohlcv`. Rows are never
    reordered: an unsorted file is rejected.
    """
    file = Path(path)
    suffix = file.suffix.lower()
    if suffix == ".csv":
        # Round-trip parsing: the loaded doubles are exactly the doubles the
        # file denotes, matching the canonical dataset builder (the default
        # parser can be several ulps off, which would let the same file
        # load differently here than through build_canonical_dataset).
        raw = pd.read_csv(file, float_precision="round_trip")
    elif suffix in {".parquet", ".pq"}:
        raw = pd.read_parquet(file)
    else:
        raise ValueError(
            f"unsupported data file extension {suffix!r} for {file.name!r}; "
            "expected .csv, .parquet, or .pq"
        )
    if timestamp_unit is not None and TIMESTAMP_COLUMN in raw.columns:
        raw[TIMESTAMP_COLUMN] = pd.to_datetime(raw[TIMESTAMP_COLUMN], unit=timestamp_unit, utc=True)
    return validate_ohlcv(
        raw,
        expected_interval=expected_interval,
        assume_utc=assume_utc,
        allow_extra_columns=allow_extra_columns,
    )
