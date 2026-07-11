"""Tests for chronological train/validation/test splits."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd
import pytest

from eth_research.splits import chronological_split


def test_default_split_sizes(synthetic_daily: pd.DataFrame) -> None:
    splits = chronological_split(synthetic_daily)
    assert len(splits.train) == 240
    assert len(splits.validation) == 80
    assert len(splits.test) == 80


def test_custom_fractions(synthetic_daily: pd.DataFrame) -> None:
    splits = chronological_split(synthetic_daily, train_fraction=0.5, validation_fraction=0.25)
    assert len(splits.train) == 200
    assert len(splits.validation) == 100
    assert len(splits.test) == 100


def test_split_is_chronological_and_disjoint(synthetic_daily: pd.DataFrame) -> None:
    splits = chronological_split(synthetic_daily)
    assert splits.train.index.max() < splits.validation.index.min()
    assert splits.validation.index.max() < splits.test.index.min()
    assert len(splits.train.index.intersection(splits.validation.index)) == 0
    assert len(splits.validation.index.intersection(splits.test.index)) == 0
    assert len(splits.train.index.intersection(splits.test.index)) == 0


def test_split_covers_every_row_in_order(synthetic_daily: pd.DataFrame) -> None:
    splits = chronological_split(synthetic_daily)
    recombined = pd.concat([splits.train, splits.validation, splits.test])
    pd.testing.assert_frame_equal(recombined, synthetic_daily, check_freq=False)


def test_splits_are_independent_copies(synthetic_daily: pd.DataFrame) -> None:
    splits = chronological_split(synthetic_daily)
    original_value = float(synthetic_daily.iloc[0]["close"])
    close_location = splits.train.columns.get_loc("close")
    assert isinstance(close_location, int)
    splits.train.iloc[0, close_location] = -1.0
    assert float(synthetic_daily.iloc[0]["close"]) == original_value


@pytest.mark.parametrize(
    ("train_fraction", "validation_fraction", "match"),
    [
        (0.0, 0.2, "train_fraction"),
        (1.0, 0.2, "train_fraction"),
        (0.6, 0.0, "validation_fraction"),
        (0.6, 1.0, "validation_fraction"),
        (0.8, 0.2, "test set"),
        (0.9, 0.3, "test set"),
    ],
)
def test_invalid_fractions_rejected(
    synthetic_daily: pd.DataFrame,
    train_fraction: float,
    validation_fraction: float,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        chronological_split(
            synthetic_daily,
            train_fraction=train_fraction,
            validation_fraction=validation_fraction,
        )


def test_too_few_rows_rejected(
    frame_from_closes: Callable[[Sequence[float]], pd.DataFrame],
) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        chronological_split(frame_from_closes([100.0, 101.0]))


def test_unsorted_frame_rejected(synthetic_daily: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="sorted"):
        chronological_split(synthetic_daily.iloc[::-1])


def test_duplicate_index_rejected(synthetic_daily: pd.DataFrame) -> None:
    duplicated = synthetic_daily.iloc[[0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]]
    with pytest.raises(ValueError, match="unique"):
        chronological_split(duplicated)
