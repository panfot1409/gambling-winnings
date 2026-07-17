"""The universe specification: the order-stable binding identity of a research universe."""

from __future__ import annotations

import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.calendar import TradingCalendar, synthetic_weekday_calendar
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.universe import UniverseSpec

_C247 = TradingCalendar("continuous_24_7", "continuous_24_7", (), "synthetic")
_NASDAQ = synthetic_weekday_calendar("nasdaq", "2026-07-13", 5)
_CALENDARS = {"continuous_24_7": _C247, "nasdaq": _NASDAQ}

_HEX = "a" * 64
_HEX2 = "b" * 64
_HEX3 = "c" * 64
_HEX4 = "d" * 64


def _crypto() -> InstrumentId:
    return InstrumentId(
        "crypto_spot", "ETH", "USD", "synthetic", "ETH-USD", "spot", "USD", "ETH", "continuous_24_7"
    )


def _equity() -> InstrumentId:
    return InstrumentId(
        "cash_equity", "SHR", "EUR", "synthetic", "SHR-EUR", "spot", "EUR", "SHR", "nasdaq"
    )


def _spec(instruments: tuple[InstrumentId, ...]) -> UniverseSpec:
    return UniverseSpec(
        base_currency="USD",
        instruments=instruments,
        calendars=_CALENDARS,
        bar_interval_seconds=3600,
        max_staleness_seconds=90000.0,
        membership_fingerprint=_HEX,
        fx_fingerprint=_HEX2,
        corporate_action_fingerprint=_HEX3,
        rebalance_schedule_fingerprint=_HEX4,
    )


def test_universe_fingerprint_is_order_stable() -> None:
    a = _spec((_crypto(), _equity()))
    b = _spec((_equity(), _crypto()))
    assert a.fingerprint == b.fingerprint
    assert len(a.fingerprint) == 64


def test_universe_required_fx_pairs() -> None:
    spec = _spec((_crypto(), _equity()))
    assert spec.required_fx_pairs == (("EUR", "USD"),)  # crypto is USD-quoted == base


def test_universe_round_trips() -> None:
    spec = _spec((_crypto(), _equity()))
    restored = UniverseSpec.from_mapping(spec.canonical(), _CALENDARS)
    assert restored.fingerprint == spec.fingerprint


def test_universe_rejects_bad_configurations() -> None:
    with pytest.raises(CanonicalError, match="must not be empty"):
        _spec(())
    with pytest.raises(CanonicalError, match="duplicate"):
        _spec((_crypto(), _crypto()))
    orphan = InstrumentId(
        "crypto_spot",
        "BTC",
        "USD",
        "synthetic",
        "BTC-USD",
        "spot",
        "USD",
        "BTC",
        "missing_calendar",
    )
    with pytest.raises(CanonicalError, match="does not carry"):
        _spec((orphan,))


def test_universe_rejects_calendar_key_mismatch() -> None:
    # the instrument's calendar_id IS a key, but that key holds a calendar whose own id differs
    mislabelled = TradingCalendar("some_other_id", "continuous_24_7", (), "x")
    with pytest.raises(CanonicalError, match="does not match"):
        UniverseSpec(
            base_currency="USD",
            instruments=(_crypto(),),
            calendars={"continuous_24_7": mislabelled},
            bar_interval_seconds=3600,
            max_staleness_seconds=90000.0,
            membership_fingerprint=_HEX,
            fx_fingerprint=_HEX2,
            corporate_action_fingerprint=_HEX3,
            rebalance_schedule_fingerprint=_HEX4,
        )
