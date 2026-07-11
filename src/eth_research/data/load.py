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
    sort: bool = True,
) -> pd.DataFrame:
    """Load one OHLCV history from a ``.csv``/``.parquet`` file and validate it.

    Parameters
    ----------
    path:
        File to load; the format is chosen by extension
        (``.csv``, ``.parquet``, or ``.pq``).
    timestamp_unit:
        Set when the file stores timestamps as epoch numbers (for example
        ``"ms"`` for millisecond exchange dumps); they are converted to UTC
        datetimes before validation.
    sort:
        Sort rows chronologically before validating (default true).

    Returns
    -------
    The canonical OHLCV frame; see
    :func:`eth_research.data.schema.validate_ohlcv`.
    """
    file = Path(path)
    suffix = file.suffix.lower()
    if suffix == ".csv":
        raw = pd.read_csv(file)
    elif suffix in {".parquet", ".pq"}:
        raw = pd.read_parquet(file)
    else:
        raise ValueError(
            f"unsupported data file extension {suffix!r} for {file.name!r}; "
            "expected .csv, .parquet, or .pq"
        )
    if timestamp_unit is not None and TIMESTAMP_COLUMN in raw.columns:
        raw[TIMESTAMP_COLUMN] = pd.to_datetime(raw[TIMESTAMP_COLUMN], unit=timestamp_unit, utc=True)
    return validate_ohlcv(raw, sort=sort)
