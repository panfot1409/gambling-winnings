"""Validated OHLCV schema for historical ETH market data.

Canonical form produced by :func:`validate_ohlcv`:

* index: ``pandas.DatetimeIndex`` named ``timestamp`` with dtype
  ``datetime64[ns, UTC]`` — unique, strictly increasing, regularly spaced.
  Each timestamp is the **candle open time**; the candle spans
  ``[t, t + interval)`` and its close price is observed at
  ``t + interval``;
* columns: ``open``, ``high``, ``low``, ``close``, ``volume`` — ``float64``;
* all values finite; prices strictly positive; volume non-negative;
* ``high >= max(open, close)``, ``low <= min(open, close)``, ``high >= low``.

Validation is strict and never repairs data:

* unsorted rows are **rejected, never sorted**;
* timezone-naive timestamps are **rejected** unless ``assume_utc=True`` is
  passed explicitly; timezone-aware timestamps are converted to UTC, which
  is unambiguous;
* the candle interval must be regular: pass ``expected_interval`` to check
  against a known interval, or leave it ``None`` to infer it, which
  succeeds only when every consecutive interval agrees. Missing candles
  and irregular gaps are reported, never filled.

Timestamps in raw input must be ISO-8601 strings or datetime values; epoch
numbers are rejected here — convert them via the loader's
``timestamp_unit``, whose epoch-to-UTC interpretation is unambiguous.
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


def _ensure_utc(index: pd.DatetimeIndex, *, assume_utc: bool) -> pd.DatetimeIndex:
    """Convert an aware index to UTC; reject a naive one unless opted in."""
    if index.tz is None:
        if not assume_utc:
            raise SchemaError(
                [
                    "timestamps are timezone-naive; provide timezone-aware timestamps, "
                    "or pass assume_utc=True to interpret them as UTC explicitly"
                ]
            )
        return index.tz_localize("UTC")
    return index.tz_convert("UTC")


def _extract_index(frame: pd.DataFrame, *, assume_utc: bool) -> pd.DatetimeIndex:
    """Build a UTC index from a ``timestamp`` column or a datetime index."""
    if TIMESTAMP_COLUMN in frame.columns:
        raw = frame[TIMESTAMP_COLUMN]
        if pd.api.types.is_numeric_dtype(raw):
            raise SchemaError(
                [
                    f"column {TIMESTAMP_COLUMN!r} is numeric; epoch timestamps must be "
                    "converted first (e.g. pass timestamp_unit= to the loader)"
                ]
            )
        if pd.api.types.is_datetime64_any_dtype(raw):
            return _ensure_utc(pd.DatetimeIndex(raw), assume_utc=assume_utc)
        try:
            parsed = pd.to_datetime(raw, format="ISO8601")
        except (ValueError, TypeError) as exc:
            # Mixed offsets parse only with utc=True; they are unambiguous.
            try:
                parsed = pd.to_datetime(raw, format="ISO8601", utc=True)
            except (ValueError, TypeError):
                raise SchemaError(
                    [f"cannot parse column {TIMESTAMP_COLUMN!r} as ISO-8601 datetimes: {exc}"]
                ) from exc
        return _ensure_utc(pd.DatetimeIndex(parsed), assume_utc=assume_utc)
    if isinstance(frame.index, pd.DatetimeIndex):
        return _ensure_utc(frame.index, assume_utc=assume_utc)
    raise SchemaError(
        [f"no {TIMESTAMP_COLUMN!r} column found and the index is not a DatetimeIndex"]
    )


def _check_interval(
    index: pd.DatetimeIndex, expected_interval: str | pd.Timedelta | None, problems: list[str]
) -> None:
    """Require a regular candle interval; report gaps and irregular spacing."""
    if len(index) < 2:
        return
    spacings = index[1:] - index[:-1]
    if expected_interval is not None:
        interval = pd.Timedelta(expected_interval)
        if interval <= pd.Timedelta(0):
            raise ValueError(f"expected_interval must be positive, got {interval}")
        irregular = spacings != interval
        count = int(irregular.sum())
        if count:
            first_at = index[1:][irregular][0]
            first_spacing = spacings[irregular][0]
            problems.append(
                f"{count} irregular candle interval(s) (missing candles or gaps): "
                f"first at {first_at} with spacing {first_spacing}, expected {interval}"
            )
        return
    distinct = spacings.unique()
    if len(distinct) > 1:
        listed = ", ".join(str(d) for d in sorted(distinct)[:3])
        problems.append(
            f"irregular candle intervals: found {len(distinct)} distinct spacings "
            f"(e.g. {listed}); missing candles and gaps are rejected, never filled — "
            "fix the data or pass expected_interval to pinpoint violations"
        )


def validate_ohlcv(
    frame: pd.DataFrame,
    *,
    expected_interval: str | pd.Timedelta | None = None,
    assume_utc: bool = False,
) -> pd.DataFrame:
    """Validate ``frame`` against the strict OHLCV schema; return canonical form.

    Parameters
    ----------
    frame:
        Raw data with a ``timestamp`` column (ISO-8601 strings or datetimes)
        or a ``DatetimeIndex``. Timestamps are candle **open times**.
        Columns other than the OHLCV set are dropped from the result.
    expected_interval:
        The required candle interval (e.g. ``"1D"``, ``pd.Timedelta("1h")``).
        When ``None``, the interval is inferred, which succeeds only if every
        consecutive interval agrees.
    assume_utc:
        Explicit opt-in to interpret timezone-naive timestamps as UTC.
        Without it, naive timestamps are rejected.

    Returns
    -------
    A new frame in canonical form (see module docstring). The input is never
    modified, and rows are never reordered or filled.

    Raises
    ------
    SchemaError
        On structural problems (missing columns, unparseable or naive
        timestamps), immediately; on content problems (bad values, duplicate
        or unsorted timestamps, irregular intervals), with every detected
        problem listed.
    """
    duplicated_names = frame.columns[frame.columns.duplicated()]
    if len(duplicated_names) > 0:
        raise SchemaError([f"duplicated column name(s): {sorted(set(map(str, duplicated_names)))}"])

    index = _extract_index(frame, assume_utc=assume_utc).as_unit("ns")
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

    problems: list[str] = []
    ordering_ok = False
    if not body.index.is_unique:
        duplicates = body.index[body.index.duplicated()].unique()
        problems.append(f"{len(duplicates)} duplicated timestamp(s), first: {duplicates[0]}")
    elif not body.index.is_monotonic_increasing:
        problems.append("timestamps are not sorted chronologically; sort the data explicitly")
    else:
        ordering_ok = True

    if ordering_ok:
        _check_interval(index, expected_interval, problems)

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


def frame_interval(frame: pd.DataFrame) -> pd.Timedelta:
    """The regular candle interval of a validated frame (needs >= 2 rows)."""
    if len(frame) < 2:
        raise ValueError("need at least 2 candles to determine the interval")
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("frame index is not a DatetimeIndex; validate it first")
    return pd.Timedelta(index[1] - index[0])
