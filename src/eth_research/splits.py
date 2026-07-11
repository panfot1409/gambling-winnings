"""Chronological train / validation / test splits.

Random shuffling leaks future information into training data, so splits are
strictly ordered in time: every training row precedes every validation row,
which precedes every test row.

Warm-up context: evaluating a segment may use observations that immediately
precede it, purely as indicator warm-up — validation may see trailing train
rows, test may see trailing train+validation rows. Context rows never
contribute P&L or metrics (the engine enforces this); they only let
indicators be live from the segment's first bar.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DataSplits:
    """Chronologically ordered, disjoint subsets of one OHLCV history."""

    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame

    def validation_context(self, bars: int) -> pd.DataFrame:
        """Trailing train rows to pass as warm-up context for validation runs."""
        return _trailing(self.train, bars, "train")

    def test_context(self, bars: int) -> pd.DataFrame:
        """Trailing train+validation rows to pass as warm-up context for test runs."""
        combined = pd.concat([self.train, self.validation])
        return _trailing(combined, bars, "train+validation")

    def boundaries(self) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
        """First and last timestamp of each segment, for exact reporting."""
        segments = (("train", self.train), ("validation", self.validation), ("test", self.test))
        return {name: (segment.index[0], segment.index[-1]) for name, segment in segments}


def _trailing(frame: pd.DataFrame, bars: int, label: str) -> pd.DataFrame:
    if bars < 1:
        raise ValueError(f"bars must be >= 1, got {bars}")
    if bars > len(frame):
        raise ValueError(f"requested {bars} context row(s) but {label} has only {len(frame)}")
    return frame.iloc[-bars:].copy()


def chronological_split(
    frame: pd.DataFrame,
    *,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
) -> DataSplits:
    """Split rows by position into train, validation, and test sets.

    The first ``train_fraction`` of rows becomes the training set, the next
    ``validation_fraction`` the validation set, and the remainder the test
    set. Rows are never shuffled and every subset must be non-empty.
    """
    if not 0.0 < train_fraction < 1.0:
        raise ValueError(f"train_fraction must be in (0, 1), got {train_fraction}")
    if not 0.0 < validation_fraction < 1.0:
        raise ValueError(f"validation_fraction must be in (0, 1), got {validation_fraction}")
    if train_fraction + validation_fraction >= 1.0:
        raise ValueError(
            "train_fraction + validation_fraction must be < 1 to leave rows for the test set, "
            f"got {train_fraction} + {validation_fraction}"
        )
    if not frame.index.is_unique:
        raise ValueError("frame index must be unique")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("frame must be sorted chronologically before splitting")

    n = len(frame)
    train_end = int(n * train_fraction)
    validation_end = int(n * (train_fraction + validation_fraction))
    splits = DataSplits(
        train=frame.iloc[:train_end].copy(),
        validation=frame.iloc[train_end:validation_end].copy(),
        test=frame.iloc[validation_end:].copy(),
    )
    if min(len(splits.train), len(splits.validation), len(splits.test)) == 0:
        raise ValueError(
            f"cannot split {n} row(s) into non-empty train/validation/test subsets with "
            f"fractions ({train_fraction}, {validation_fraction})"
        )
    return splits
