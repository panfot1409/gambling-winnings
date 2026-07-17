"""Batch/streaming equivalence and strict checkpoint/resume: byte-identity and tamper guards."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.corporate_actions import CorporateAction, CorporateActionSet
from eth_research.portfolio.costs import CostParameters
from eth_research.portfolio.engine import (
    EventRecord,
    PortfolioRunResult,
    run_portfolio_simulation,
)
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.panel import MarketPanel, build_market_panel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.streaming import (
    PortfolioCheckpoint,
    resume_portfolio_simulation,
    stream_portfolio_simulation,
)
from eth_research.portfolio.valuation import StalenessPolicy

_FX = FxEvidence(observations=())
_CAL = {"continuous_24_7": TradingCalendar("continuous_24_7", "continuous_24_7", (), "test")}
_STALE = StalenessPolicy(max_staleness_seconds=1_000_000.0)


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _inst(symbol: str, base: str) -> InstrumentId:
    return InstrumentId(
        "crypto_spot", base, "USD", "synthetic", symbol, "spot", "USD", base, "continuous_24_7"
    )


A = _inst("A-USD", "AAA")
B = _inst("B-USD", "BBB")


def _moving(opens: Sequence[float], closes: Sequence[float]) -> pd.DataFrame:
    t = pd.date_range("2026-07-14T00:00:00", periods=len(opens), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": t,
            "close_time": t + pd.Timedelta(hours=1),
            "open": [float(o) for o in opens],
            "high": [float(max(o, c)) for o, c in zip(opens, closes, strict=True)],
            "low": [float(min(o, c)) for o, c in zip(opens, closes, strict=True)],
            "close": [float(c) for c in closes],
            "volume": [1000.0] * len(opens),
        }
    )


def _membership(instruments: Sequence[InstrumentId]) -> MembershipSchedule:
    return MembershipSchedule(
        intervals=tuple(
            MembershipInterval(
                i, _ts("2026-07-14T00:00:00"), None, _ts("2026-07-14T00:00:00"), "listing", "test"
            )
            for i in instruments
        )
    )


_SCHEDULE = RebalanceSchedule(
    timestamps=(
        _ts("2026-07-14T00:00:00"),
        _ts("2026-07-14T01:00:00"),
        _ts("2026-07-14T02:00:00"),
        _ts("2026-07-14T03:00:00"),
    )
)


def _panel() -> MarketPanel:
    return build_market_panel(
        {
            A: _moving([100.0, 105.0, 103.0, 108.0, 110.0], [105.0, 103.0, 108.0, 110.0, 112.0]),
            B: _moving([50.0, 52.0, 55.0, 53.0, 57.0], [52.0, 55.0, 53.0, 57.0, 60.0]),
        }
    )


def _protocol() -> PortfolioProtocol:
    return PortfolioProtocol(
        base_currency="USD",
        initial_cash=1000.0,
        policy="equal_weight",
        cost_scenario=CostParameters(scenario="zero"),
        staleness=_STALE,
    )


def _batch() -> PortfolioRunResult:
    return run_portfolio_simulation(
        _protocol(), _panel(), _membership([A, B]), _FX, _SCHEDULE, calendars=_CAL
    )


def _pairs() -> list[tuple[EventRecord, PortfolioCheckpoint]]:
    return list(
        stream_portfolio_simulation(
            _protocol(), _panel(), _membership([A, B]), _FX, _SCHEDULE, calendars=_CAL
        )
    )


def test_streaming_reproduces_batch_events() -> None:
    batch = _batch()
    streamed = [record for record, _cp in _pairs()]
    assert [r.canonical() for r in streamed] == [e.canonical() for e in batch.events]
    assert streamed[-1].state_fingerprint == batch.final_state_fingerprint


def test_resume_is_byte_identical_to_batch() -> None:
    batch = _batch()
    pairs = _pairs()
    checkpoint = pairs[1][1]  # after event index 1 -> next_event_index == 2
    resumed = resume_portfolio_simulation(
        checkpoint, _protocol(), _panel(), _membership([A, B]), _FX, _SCHEDULE, calendars=_CAL
    )
    assert resumed.canonical_result == batch.canonical()
    assert resumed.result_fingerprint == batch.result_fingerprint
    assert [e.canonical() for e in resumed.tail_events] == [e.canonical() for e in batch.events[2:]]


def test_resume_from_final_checkpoint_has_empty_tail() -> None:
    batch = _batch()
    pairs = _pairs()
    final_checkpoint = pairs[-1][1]  # next_event_index == len(events)
    resumed = resume_portfolio_simulation(
        final_checkpoint, _protocol(), _panel(), _membership([A, B]), _FX, _SCHEDULE, calendars=_CAL
    )
    assert resumed.tail_events == ()
    assert resumed.canonical_result == batch.canonical()


def test_checkpoint_round_trips_through_strict_json() -> None:
    checkpoint = _pairs()[2][1]
    payload = json.loads(json.dumps(checkpoint.canonical(), allow_nan=False))
    restored = PortfolioCheckpoint.from_mapping(payload)
    assert restored.checkpoint_hash == checkpoint.checkpoint_hash
    assert restored.canonical() == checkpoint.canonical()


def test_tampered_holding_is_rejected() -> None:
    payload = _pairs()[2][1].canonical()
    payload["base_cash"] = payload["base_cash"] + 10.0  # mutate state, leave the hash stale
    with pytest.raises(CanonicalError, match="tampered"):
        PortfolioCheckpoint.from_mapping(payload)


def test_unknown_checkpoint_key_is_rejected() -> None:
    payload = _pairs()[1][1].canonical()
    payload["surprise"] = 1
    with pytest.raises(CanonicalError, match="unexpected key"):
        PortfolioCheckpoint.from_mapping(payload)


def test_resume_rejects_substituted_evidence() -> None:
    checkpoint = _pairs()[1][1]
    other_protocol = PortfolioProtocol(
        base_currency="USD",
        initial_cash=2000.0,  # different initial cash -> different protocol fingerprint
        policy="equal_weight",
        cost_scenario=CostParameters(scenario="zero"),
        staleness=_STALE,
    )
    with pytest.raises(CanonicalError, match="does not match the supplied evidence"):
        resume_portfolio_simulation(
            checkpoint,
            other_protocol,
            _panel(),
            _membership([A, B]),
            _FX,
            _SCHEDULE,
            calendars=_CAL,
        )


def test_resume_rejects_substituted_calendars() -> None:
    # Trading calendars govern tradability, so resuming a checkpoint captured under one calendar
    # against a different one (same id, different source -> different fingerprint) is a materially
    # different run. The checkpoint binds a calendars fingerprint and must reject the substitution,
    # exactly as it rejects a substituted protocol / panel / membership / schedule / FX.
    checkpoint = _pairs()[1][1]
    other_cal = {
        "continuous_24_7": TradingCalendar("continuous_24_7", "continuous_24_7", (), "other")
    }
    with pytest.raises(CanonicalError, match="does not match the supplied evidence"):
        resume_portfolio_simulation(
            checkpoint,
            _protocol(),
            _panel(),
            _membership([A, B]),
            _FX,
            _SCHEDULE,
            calendars=other_cal,
        )


def test_stream_fails_closed_on_in_window_corporate_action() -> None:
    actions = CorporateActionSet(
        actions=(
            CorporateAction(
                instrument=A,
                action_id="split-1",
                action_type="split",
                knowledge_time=_ts("2026-07-14T00:00:00"),
                effective_time=_ts("2026-07-14T02:00:00"),
                payment_time=None,
                ratio=2.0,
                cash_amount=None,
                currency=None,
                source="test",
            ),
        )
    )
    with pytest.raises(CanonicalError, match="does not apply corporate actions"):
        list(
            stream_portfolio_simulation(
                _protocol(),
                _panel(),
                _membership([A, B]),
                _FX,
                _SCHEDULE,
                calendars=_CAL,
                corporate_actions=actions,
            )
        )
