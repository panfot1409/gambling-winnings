"""Validated OHLCV schema for historical ETH market data.

Canonical form produced by :func:`validate_ohlcv`:

* index: ``pandas.DatetimeIndex`` named ``timestamp`` with dtype
  ``datetime64[ns, UTC]`` — unique, strictly increasing; each row is a
  completed bar;
* columns: ``open``, ``high``, ``low``, ``close``, ``volume`` — ``float64``;
* all values finite; prices strictly positive; volume non-negative;
* ``high >= max(open, close)``, ``low <= min(open, close)``, ``high >= low``.

Timestamps in raw input must be ISO-8601 strings or datetime values; epoch
numbers are rejected (convert them first, e.g. via the loader's
``timestamp_unit``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")
TIMESTAMP_COLUMN: str = "timestamp"


class SchemaError(ValueError):
    """A data frame does not conform to the OHLCV schema.

    Content problems are collected in :attr:`problems` so a bad file can be
    fixed in one pass instead of one error at a time.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("OHLCV schema validation failed: " + "; ".join(self.problems))


def _extract_utc_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
    """Build a UTC index from a ``timestamp`` column or a datetime index."""
    if TIMESTAMP_COLUMN in frame.columns:
        raw = frame[TIMESTAMP_COLUMN]
        if pd.api.types.is_numeric_dtype(raw):
            raise SchemaError(
                [
                    f"column {TIMESTAMP_COLUMN!r} is numeric; convert epoch values to "
                    "datetimes first (e.g. pass timestamp_unit= to the loader)"
                ]
            )
        try:
            return pd.DatetimeIndex(pd.to_datetime(raw, utc=True, format="ISO8601"))
        except (ValueError, TypeError) as exc:
            raise SchemaError(
                [f"cannot parse column {TIMESTAMP_COLUMN!r} as datetimes: {exc}"]
            ) from exc
    if isinstance(frame.index, pd.DatetimeIndex):
        index = frame.index
        return index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    raise SchemaError(
        [f"no {TIMESTAMP_COLUMN!r} column found and the index is not a DatetimeIndex"]
    )


def validate_ohlcv(frame: pd.DataFrame, *, sort: bool = True) -> pd.DataFrame:
    """Validate ``frame`` against the OHLCV schema and return its canonical form.

    Parameters
    ----------
    frame:
        Raw data with a ``timestamp`` column (ISO-8601 strings or datetimes)
        or a ``DatetimeIndex``. Naive timestamps are assumed to be UTC.
        Columns other than the OHLCV set are dropped from the result.
    sort:
        When true (the default), rows are sorted chronologically before
        validation; when false, out-of-order rows are reported as an error.

    Returns
    -------
    A new frame in canonical form (see module docstring). The input is never
    modified.

    Raises
    ------
    SchemaError
        On structural problems (missing columns, unparseable timestamps),
        immediately; on content problems (bad values, duplicate timestamps),
        with every detected problem listed.
    """
    duplicated_names = frame.columns[frame.columns.duplicated()]
    if len(duplicated_names) > 0:
        raise SchemaError([f"duplicated column name(s): {sorted(set(map(str, duplicated_names)))}"])

    index = _extract_utc_index(frame).as_unit("ns")
    body = frame.drop(columns=[TIMESTAMP_COLUMN], errors="ignore").copy()
    body.index = index

    missing = [column for column in OHLCV_COLUMNS if column not in body.columns]
    if missing:
        raise SchemaError([f"missing required column(s): {missing}"])
    if len(body) == 0:
        raise SchemaError(["frame is empty"])
    missing_timestamps = int(pd.isna(index).sum())
    if missing_timestamps:
        raise SchemaError([f"{missing_timestamps} missing timestamp(s) (NaT)"])

    body = body[list(OHLCV_COLUMNS)]
    try:
        body = body.astype(float)
    except (TypeError, ValueError) as exc:
        raise SchemaError([f"OHLCV columns must be numeric: {exc}"]) from exc

    if sort and not body.index.is_monotonic_increasing:
        body = body.sort_index()

    problems: list[str] = []
    if not body.index.is_unique:
        duplicates = body.index[body.index.duplicated()].unique()
        problems.append(f"{len(duplicates)} duplicated timestamp(s), first: {duplicates[0]}")
    elif not body.index.is_monotonic_increasing:
        problems.append("timestamps are not sorted chronologically (pass sort=True to sort)")

    finite = np.isfinite(body.to_numpy())
    if not finite.all():
        bad_columns = [
            column for position, column in enumerate(OHLCV_COLUMNS) if not finite[:, position].all()
        ]
        problems.append(f"non-finite values (NaN/inf) in column(s): {bad_columns}")
    else:
        for column in PRICE_COLUMNS:
            if (body[column] <= 0).any():
                problems.append(f"non-positive prices in column {column!r}")
        max_open_close = body[["open", "close"]].max(axis=1)
        min_open_close = body[["open", "close"]].min(axis=1)
        high_violations = int((body["high"] < max_open_close).sum())
        if high_violations:
            problems.append(f"high < max(open, close) on {high_violations} row(s)")
        low_violations = int((body["low"] > min_open_close).sum())
        if low_violations:
            problems.append(f"low > min(open, close) on {low_violations} row(s)")
        if (body["high"] < body["low"]).any():
            problems.append("high < low on some row(s)")
        if (body["volume"] < 0).any():
            problems.append("negative values in column 'volume'")

    if problems:
        raise SchemaError(problems)

    body.index.name = TIMESTAMP_COLUMN
    return body
