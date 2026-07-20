"""V2B §19 — the pre-registered walk-forward out-of-sample fold structure over the joint partition.

The candidates carry **fixed** pre-registered parameters (no fitting), so the folds are not a
train/test split for hyper-parameter search; they are contiguous out-of-sample sub-periods used to
*stratify* the reused fold-stratified moving-block bootstrap (``eth_research.m3c.statistics``) so a
single lucky regime cannot carry a candidate. A leading warm-up block (longer than the longest
candidate lookback) is excluded from evaluation entirely — a candidate is flat there by
construction, and scoring that flat stretch would be neither a signal nor a fair comparison.

The structure is a pure function of the partition length and the frozen constants below, so it is
byte-reproducible and identical in the machinery tests and the one-shot run.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from eth_research.v2.strict import V2ValidationError

FOLDS_SCHEMA_VERSION: int = 1

#: Leading bars excluded from evaluation. Longer than the longest candidate lookback (100) so every
#: evaluated bar sees a fully-formed signal, with margin.
WARMUP_ROWS: int = 150
#: The number of contiguous out-of-sample folds the post-warm-up window is split into.
OOS_FOLD_COUNT: int = 6
#: The exact research-train row count (the firewalled joint partition).
EXPECTED_ROWS: int = 2221


class V2BFoldError(V2ValidationError):
    """The V2B fold structure could not be built from the given index."""


@dataclass(frozen=True, slots=True)
class V2BFold:
    """One contiguous out-of-sample fold: a half-open row range ``[start, stop)`` of the index."""

    fold_index: int
    start: int  # inclusive row position into the full partition index
    stop: int  # exclusive
    first_open: pd.Timestamp
    last_open: pd.Timestamp

    @property
    def row_count(self) -> int:
        return self.stop - self.start


def build_oos_folds(index: pd.DatetimeIndex) -> tuple[V2BFold, ...]:
    """The frozen out-of-sample folds: split ``index[WARMUP_ROWS:]`` into ``OOS_FOLD_COUNT`` pieces.

    The split is as even as possible with the remainder spread over the leading folds (a fixed,
    deterministic rule). Every fold is non-empty; the union of folds is exactly ``index[WARMUP:]``;
    folds are contiguous and disjoint.
    """
    n = len(index)
    if n != EXPECTED_ROWS:
        raise V2BFoldError(f"expected {EXPECTED_ROWS} rows, got {n}")
    evaluable = n - WARMUP_ROWS
    if evaluable < OOS_FOLD_COUNT:
        raise V2BFoldError("too few evaluable rows for the fold count")
    base, extra = divmod(evaluable, OOS_FOLD_COUNT)
    folds: list[V2BFold] = []
    cursor = WARMUP_ROWS
    for fold_index in range(OOS_FOLD_COUNT):
        size = base + (1 if fold_index < extra else 0)
        start, stop = cursor, cursor + size
        folds.append(
            V2BFold(
                fold_index=fold_index,
                start=start,
                stop=stop,
                first_open=pd.Timestamp(index[start]),
                last_open=pd.Timestamp(index[stop - 1]),
            )
        )
        cursor = stop
    if cursor != n:
        raise V2BFoldError("internal: folds did not cover the evaluable window exactly")
    return tuple(folds)


def series_by_fold(series: pd.Series, folds: tuple[V2BFold, ...]) -> dict[int, pd.Series]:
    """Slice a full-partition per-event series into ``{fold_index: fold slice}`` (row positions).

    ``series`` must be indexed by the full partition timeline; each fold's slice is
    ``series.iloc[fold.start:fold.stop]`` so the fold membership is exactly the frozen row ranges.
    """
    out: dict[int, pd.Series] = {}
    for fold in folds:
        out[fold.fold_index] = series.iloc[fold.start : fold.stop]
    return out


def fold_structure_summary(index: pd.DatetimeIndex) -> dict[str, object]:
    """A canonical, byte-reproducible summary of the frozen fold structure."""
    folds = build_oos_folds(index)
    return {
        "schema_version": FOLDS_SCHEMA_VERSION,
        "warmup_rows": WARMUP_ROWS,
        "oos_fold_count": OOS_FOLD_COUNT,
        "expected_rows": EXPECTED_ROWS,
        "folds": [
            {
                "fold_index": fold.fold_index,
                "start": fold.start,
                "stop": fold.stop,
                "row_count": fold.row_count,
                "first_open": pd.Timestamp(fold.first_open).isoformat().replace("+00:00", "Z"),
                "last_open": pd.Timestamp(fold.last_open).isoformat().replace("+00:00", "Z"),
            }
            for fold in folds
        ],
    }
