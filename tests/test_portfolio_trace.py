"""The size-bounded trace commitment: hash chain, bounded samples, strict parse, tamper checks."""

from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from eth_research.api.serialization import (
    CanonicalError,
    canonical_json_bytes,
    strict_load_canonical,
)
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.costs import CostParameters
from eth_research.portfolio.engine import PortfolioRunResult, run_portfolio_simulation
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.trace import (
    DEFAULT_MAX_SAMPLES,
    TraceCommitment,
    build_trace_commitment,
    verify_trace_commitment,
)
from eth_research.portfolio.valuation import StalenessPolicy

_CAL_ID = "continuous_24_7"
_CALS = {_CAL_ID: TradingCalendar(_CAL_ID, _CAL_ID, (), "test")}
_FX = FxEvidence(observations=())


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


_A = InstrumentId("crypto_spot", "AAA", "USD", "synthetic", "A-USD", "spot", "USD", "AAA", _CAL_ID)
_PROTOCOL = PortfolioProtocol(
    base_currency="USD",
    initial_cash=1000.0,
    policy="equal_weight",
    cost_scenario=CostParameters(scenario="zero"),
    staleness=StalenessPolicy(max_staleness_seconds=1_000_000.0),
)


def _run(n_events: int) -> PortfolioRunResult:
    """A single-asset run over ``n_events`` hourly rebalances on a flat-priced panel."""
    from eth_research.portfolio.panel import build_market_panel

    opens = pd.date_range("2026-07-14T00:00:00", periods=n_events, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open_time": opens,
            "close_time": opens + pd.Timedelta(hours=1),
            "open": [100.0] * n_events,
            "high": [100.0] * n_events,
            "low": [100.0] * n_events,
            "close": [100.0] * n_events,
            "volume": [1000.0] * n_events,
        }
    )
    membership = MembershipSchedule(
        intervals=(
            MembershipInterval(
                _A, _ts("2026-07-14T00:00:00"), None, _ts("2026-07-14T00:00:00"), "listing", "test"
            ),
        )
    )
    schedule = RebalanceSchedule(timestamps=tuple(opens))
    return run_portfolio_simulation(
        _PROTOCOL, build_market_panel({_A: frame}), membership, _FX, schedule, calendars=_CALS
    )


def test_build_then_verify_passes() -> None:
    run = _run(5)
    commitment = build_trace_commitment(run)
    verify_trace_commitment(commitment, run)
    assert commitment.event_count == 5
    assert commitment.first is not None
    assert commitment.first.index == 0
    assert commitment.last is not None
    assert commitment.last.index == 4
    assert len(commitment.chain_hash) == 64


def test_commitment_is_deterministic() -> None:
    a = build_trace_commitment(_run(7))
    b = build_trace_commitment(_run(7))
    assert a.commitment_id == b.commitment_id
    assert a.canonical() == b.canonical()


def test_round_trips_through_strict_canonical_json() -> None:
    commitment = build_trace_commitment(_run(9))
    raw = canonical_json_bytes(commitment.canonical())
    restored = TraceCommitment.from_mapping(strict_load_canonical(raw, "trace_commitment"))
    assert restored == commitment
    assert restored.commitment_id == commitment.commitment_id


def test_samples_are_bounded_but_chain_covers_every_event() -> None:
    n = DEFAULT_MAX_SAMPLES * 2 + 3  # comfortably over the sample cap
    run = _run(n)
    commitment = build_trace_commitment(run)
    assert commitment.event_count == n
    assert len(commitment.samples) <= DEFAULT_MAX_SAMPLES  # samples are bounded
    assert commitment.first is not None
    assert commitment.first.index == 0
    assert commitment.last is not None
    assert commitment.last.index == n - 1
    # the O(1) chain still binds the whole sequence: the full run verifies.
    verify_trace_commitment(commitment, run)


def test_sampling_endpoints_are_included_and_ascending() -> None:
    commitment = build_trace_commitment(_run(200))
    indices = [sample.index for sample in commitment.samples]
    assert indices == sorted(set(indices))  # strictly ascending, distinct
    assert indices[0] == 0
    assert indices[-1] == 199


def test_verify_rejects_a_run_with_a_different_length() -> None:
    commitment = build_trace_commitment(_run(6))
    with pytest.raises(CanonicalError, match="event_count does not match"):
        verify_trace_commitment(commitment, _run(7))


def test_verify_rejects_a_run_with_different_values() -> None:
    # Same number of events, but a different price path -> a different chain and endpoints.
    commitment = build_trace_commitment(_run(6))
    from eth_research.portfolio.panel import build_market_panel

    opens = pd.date_range("2026-07-14T00:00:00", periods=6, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open_time": opens,
            "close_time": opens + pd.Timedelta(hours=1),
            "open": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
            "high": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
            "low": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
            "close": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
            "volume": [1000.0] * 6,
        }
    )
    membership = MembershipSchedule(
        intervals=(
            MembershipInterval(
                _A, _ts("2026-07-14T00:00:00"), None, _ts("2026-07-14T00:00:00"), "listing", "test"
            ),
        )
    )
    moving = run_portfolio_simulation(
        _PROTOCOL,
        build_market_panel({_A: frame}),
        membership,
        _FX,
        RebalanceSchedule(timestamps=tuple(opens)),
        calendars=_CALS,
    )
    with pytest.raises(CanonicalError, match="chain hash does not match"):
        verify_trace_commitment(commitment, moving)


def test_verify_rejects_a_tampered_chain_hash() -> None:
    run = _run(5)
    commitment = build_trace_commitment(run)
    tampered = dataclasses.replace(commitment, chain_hash="0" * 64)
    with pytest.raises(CanonicalError, match="chain hash does not match"):
        verify_trace_commitment(tampered, run)


def test_from_mapping_rejects_a_bumped_event_count() -> None:
    # Bumping the count but not the endpoints breaks the "last.index == count - 1" invariant.
    commitment = build_trace_commitment(_run(5))
    payload = commitment.canonical()
    payload["event_count"] = payload["event_count"] + 1
    with pytest.raises(CanonicalError, match="index must be event_count"):
        TraceCommitment.from_mapping(payload)


def test_from_mapping_rejects_null_endpoints_on_a_nonempty_trace() -> None:
    commitment = build_trace_commitment(_run(4))
    payload = commitment.canonical()
    payload["first"] = None
    with pytest.raises(CanonicalError, match="endpoints must be present"):
        TraceCommitment.from_mapping(payload)


def test_from_mapping_rejects_a_mis_ordered_sample() -> None:
    commitment = build_trace_commitment(_run(6))
    payload = commitment.canonical()
    # Point the second sample back at the first index so they are no longer strictly increasing
    # (the sample count is unchanged, so the "more samples than events" guard is not what trips).
    payload["samples"][1]["index"] = payload["samples"][0]["index"]
    with pytest.raises(CanonicalError, match="strictly increasing"):
        TraceCommitment.from_mapping(payload)


def test_from_mapping_rejects_an_out_of_range_sample_index() -> None:
    commitment = build_trace_commitment(_run(4))
    payload = commitment.canonical()
    payload["samples"][-1]["index"] = 999  # beyond event_count
    with pytest.raises(CanonicalError, match="out of range"):
        TraceCommitment.from_mapping(payload)


def test_from_mapping_rejects_an_unknown_schema_version() -> None:
    commitment = build_trace_commitment(_run(3))
    payload = commitment.canonical()
    payload["schema_version"] = 999
    with pytest.raises(CanonicalError, match="schema_version"):
        TraceCommitment.from_mapping(payload)


def test_empty_trace_parses_and_has_null_endpoints() -> None:
    # A zero-event trace: null endpoints, empty samples, a chain over nothing.
    empty = TraceCommitment(
        schema_version=1,
        event_count=0,
        chain_hash="a" * 64,
        first=None,
        last=None,
        samples=(),
    )
    restored = TraceCommitment.from_mapping(empty.canonical())
    assert restored.event_count == 0
    assert restored.first is None
    assert restored.last is None
    assert restored.samples == ()
