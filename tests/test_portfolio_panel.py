"""The immutable, order-stable market panel over asynchronous calendars."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.panel import build_market_panel


def _inst(symbol: str, base: str, calendar: str) -> InstrumentId:
    return InstrumentId(
        asset_class="crypto_spot",
        base_asset=base,
        quote_currency="USD",
        venue="synthetic",
        symbol=symbol,
        instrument_type="spot",
        price_unit="USD",
        quantity_unit=base,
        calendar_id=calendar,
    )


def _frame(start: str, periods: int, freq: str) -> pd.DataFrame:
    opens = pd.date_range(start=start, periods=periods, freq=freq, tz="UTC")
    step = pd.Timedelta("1" + freq)
    return pd.DataFrame(
        {
            "open_time": opens,
            "close_time": opens + step,
            "open": [100.0] * periods,
            "high": [101.0] * periods,
            "low": [99.0] * periods,
            "close": [100.5] * periods,
            "volume": [1_000.0] * periods,
        }
    )


A = _inst("A-USD", "AAA", "continuous_24_7")
B = _inst("B-USD", "BBB", "nasdaq")


def test_panel_builds_and_fingerprints() -> None:
    panel = build_market_panel({A: _frame("2026-07-14", 4, "h"), B: _frame("2026-07-14", 3, "D")})
    assert len(panel.instruments) == 2
    assert len(panel.fingerprint) == 64


def test_panel_fingerprint_is_order_independent() -> None:
    frame_a = _frame("2026-07-14", 4, "h")
    frame_b = _frame("2026-07-14", 3, "D")
    first = build_market_panel({A: frame_a, B: frame_b}).fingerprint
    second = build_market_panel({B: frame_b, A: frame_a}).fingerprint
    assert first == second


def test_panel_supports_asynchronous_calendars() -> None:
    # A trades hourly 24/7, B trades daily on a weekday calendar — different timestamps coexist
    panel = build_market_panel(
        {A: _frame("2026-07-14T00:00:00", 6, "h"), B: _frame("2026-07-14", 2, "D")}
    )
    assert len(panel.frame(A)) == 6
    assert len(panel.frame(B)) == 2


def test_panel_frame_is_a_defensive_copy() -> None:
    panel = build_market_panel({A: _frame("2026-07-14", 4, "h")})
    got = panel.frame(A)
    got.loc[0, "open"] = -999.0
    assert panel.frame(A).loc[0, "open"] == 100.0  # mutation did not leak back


def test_panel_rejects_empty_and_missing_and_duplicate() -> None:
    with pytest.raises(CanonicalError, match="at least one"):
        build_market_panel({})
    panel = build_market_panel({A: _frame("2026-07-14", 4, "h")})
    with pytest.raises(CanonicalError, match="no frame"):
        panel.frame(B)
