"""The causal AsOfView: membership gating, prior-bars, current-open, and prefix invariance."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.information import AsOfView
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.panel import MarketPanel, build_market_panel


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _inst(symbol: str, base: str) -> InstrumentId:
    return InstrumentId(
        asset_class="crypto_spot",
        base_asset=base,
        quote_currency="USD",
        venue="synthetic",
        symbol=symbol,
        instrument_type="spot",
        price_unit="USD",
        quantity_unit=base,
        calendar_id="continuous_24_7",
    )


A = _inst("A-USD", "AAA")
B = _inst("B-USD", "BBB")


def _bars(opens: Sequence[float], closes: Sequence[float]) -> pd.DataFrame:
    open_times = pd.date_range(start="2026-07-14T00:00:00", periods=len(opens), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": open_times,
            "close_time": open_times + pd.Timedelta(hours=1),
            "open": [float(value) for value in opens],
            "high": [float(max(o, c)) for o, c in zip(opens, closes, strict=True)],
            "low": [float(min(o, c)) for o, c in zip(opens, closes, strict=True)],
            "close": [float(value) for value in closes],
            "volume": [1000.0] * len(opens),
        }
    )


def _membership() -> MembershipSchedule:
    return MembershipSchedule(
        intervals=(
            MembershipInterval(
                A, _ts("2026-07-14T00:00:00"), None, _ts("2026-07-14T00:00:00"), "listing", "test"
            ),
            MembershipInterval(
                B, _ts("2026-07-14T03:00:00"), None, _ts("2026-07-14T03:00:00"), "listing", "test"
            ),
        )
    )


def _panel(a_opens: Sequence[float], a_closes: Sequence[float]) -> MarketPanel:
    return build_market_panel(
        {
            A: _bars(a_opens, a_closes),
            B: _bars([200.0, 201.0, 202.0, 203.0], [201.0, 202.0, 203.0, 204.0]),
        }
    )


_A_OPENS = [100.0, 101.0, 102.0, 103.0]
_A_CLOSES = [101.0, 102.0, 103.0, 104.0]
_FX = FxEvidence(observations=())
_TAU = _ts("2026-07-14T02:00:00")


def test_active_universe_gates_on_membership_knowledge() -> None:
    panel = _panel(_A_OPENS, _A_CLOSES)
    membership = _membership()
    early = AsOfView.at(panel, membership, _FX, _TAU)
    assert early.active_universe == (A,)
    late = AsOfView.at(panel, membership, _FX, _ts("2026-07-14T03:00:00"))
    assert set(late.active_universe) == {A, B}


def test_current_open_only_at_exact_tau() -> None:
    view = AsOfView.at(_panel(_A_OPENS, _A_CLOSES), _membership(), _FX, _TAU)
    assert view.current_open(A) == pytest.approx(102.0)  # bar opening exactly at 02:00
    off_grid = AsOfView.at(
        _panel(_A_OPENS, _A_CLOSES), _membership(), _FX, _ts("2026-07-14T02:30:00")
    )
    assert off_grid.current_open(A) is None


def test_prior_bars_are_completed_only() -> None:
    view = AsOfView.at(_panel(_A_OPENS, _A_CLOSES), _membership(), _FX, _TAU)
    prior = view.prior_bars(A)
    # only bars closing at or before 02:00 are visible (close_times 01:00 and 02:00)
    assert list(prior["close"]) == [101.0, 102.0]
    assert prior["close_time"].max() == _ts("2026-07-14T02:00:00")


def test_future_bar_does_not_change_earlier_view() -> None:
    membership = _membership()
    short = AsOfView.at(_panel(_A_OPENS, _A_CLOSES), membership, _FX, _TAU)
    extended = AsOfView.at(_panel([*_A_OPENS, 104.0], [*_A_CLOSES, 105.0]), membership, _FX, _TAU)
    assert short.prior_bars(A).equals(extended.prior_bars(A))
    assert short.current_open(A) == extended.current_open(A)
    assert short.active_universe == extended.active_universe
    assert short.fx_rate("USD", "USD") == extended.fx_rate("USD", "USD")


def test_non_active_instrument_is_refused() -> None:
    view = AsOfView.at(_panel(_A_OPENS, _A_CLOSES), _membership(), _FX, _TAU)
    with pytest.raises(CanonicalError, match="active universe"):
        view.prior_bars(B)
    with pytest.raises(CanonicalError, match="active universe"):
        view.current_open(B)


def test_fx_rate_is_causal_same_currency_identity() -> None:
    view = AsOfView.at(_panel(_A_OPENS, _A_CLOSES), _membership(), _FX, _TAU)
    assert view.fx_rate("USD", "USD") == 1.0
