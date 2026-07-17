"""Causal mark-to-market valuation with a staleness policy."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.bars import validate_bar_frame
from eth_research.portfolio.fx import FxEvidence, FxObservation
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.valuation import (
    StalenessPolicy,
    latest_close_as_of,
    mark_instrument,
)


def _inst(quote: str) -> InstrumentId:
    return InstrumentId(
        asset_class="cash_equity",
        base_asset="SHR",
        quote_currency=quote,
        venue="synthetic",
        symbol=f"SHR-{quote}",
        instrument_type="spot",
        price_unit=quote,
        quantity_unit="SHR",
        calendar_id="nasdaq",
    )


def _frame() -> pd.DataFrame:
    opens = pd.date_range(start="2026-07-14T00:00:00", periods=3, freq="h", tz="UTC")
    return validate_bar_frame(
        pd.DataFrame(
            {
                "open_time": opens,
                "close_time": opens + pd.Timedelta(hours=1),
                "open": [100.0, 101.0, 102.0],
                "high": [103.0, 103.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [101.0, 102.0, 103.0],
                "volume": [1000.0, 1000.0, 1000.0],
            }
        ),
        _inst("USD"),
    )


_HOUR = 3600.0
_LENIENT = StalenessPolicy(max_staleness_seconds=10 * _HOUR)


def test_latest_close_is_causal() -> None:
    frame = _frame()
    # at 02:30 the last completed bar closed at 02:00 with close 102.0
    ct, close = latest_close_as_of(frame, pd.Timestamp("2026-07-14T02:30:00", tz="UTC"))
    assert close == 102.0
    assert ct == pd.Timestamp("2026-07-14T02:00:00", tz="UTC")
    # before any bar closes -> None
    assert latest_close_as_of(frame, pd.Timestamp("2026-07-14T00:30:00", tz="UTC")) is None


def test_mark_uses_causal_close_and_fx() -> None:
    frame = _frame()
    fx = FxEvidence(observations=())
    tau = pd.Timestamp("2026-07-14T03:30:00", tz="UTC")  # last close 103.0 at 03:00
    mark = mark_instrument(frame, fx, _inst("USD"), "USD", tau, staleness=_LENIENT)
    assert mark.base_value_per_unit == 103.0  # USD base == USD quote -> fx 1.0
    assert mark.fx_rate == 1.0


def test_mark_converts_foreign_currency() -> None:
    frame = _frame()
    # 1 EUR = 1.1 USD, observed before tau
    fx = FxEvidence(
        observations=(
            FxObservation("EUR", "USD", pd.Timestamp("2026-07-14T00:00:00", tz="UTC"), 1.1, "x"),
        )
    )
    tau = pd.Timestamp("2026-07-14T03:30:00", tz="UTC")
    mark = mark_instrument(frame, fx, _inst("EUR"), "USD", tau, staleness=_LENIENT)
    # close 103 EUR * (USD per EUR = 1.1) = 113.3 USD
    assert mark.fx_rate == pytest.approx(1.1)
    assert mark.base_value_per_unit == pytest.approx(103.0 * 1.1)


def test_over_stale_mark_is_refused() -> None:
    frame = _frame()
    fx = FxEvidence(observations=())
    # last close at 03:00; a day later, with a 10h bound, the mark is over-stale
    tau = pd.Timestamp("2026-07-15T03:00:00", tz="UTC")
    with pytest.raises(CanonicalError, match="stale"):
        mark_instrument(frame, fx, _inst("USD"), "USD", tau, staleness=_LENIENT)


def test_no_causal_bar_is_an_error() -> None:
    frame = _frame()
    fx = FxEvidence(observations=())
    with pytest.raises(CanonicalError, match="no completed bar"):
        mark_instrument(
            frame,
            fx,
            _inst("USD"),
            "USD",
            pd.Timestamp("2026-07-14T00:30:00", tz="UTC"),
            staleness=_LENIENT,
        )


def test_staleness_policy_validates() -> None:
    with pytest.raises(CanonicalError):
        StalenessPolicy(max_staleness_seconds=0.0)
