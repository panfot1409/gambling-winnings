"""The portfolio protocol: build, round-trip, fingerprint, policy dispatch, and validation."""

from __future__ import annotations

import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.costs import CostParameters
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.protocol import PortfolioProtocol, build_target
from eth_research.portfolio.valuation import StalenessPolicy


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

_ZERO = CostParameters(scenario="zero")
_STALE = StalenessPolicy(max_staleness_seconds=86_400.0)


def _protocol(
    policy: str, declared: tuple[tuple[InstrumentId, float], ...] = ()
) -> PortfolioProtocol:
    return PortfolioProtocol(
        base_currency="USD",
        initial_cash=1000.0,
        policy=policy,  # type: ignore[arg-type]
        cost_scenario=_ZERO,
        staleness=_STALE,
        declared_weights=declared,
    )


def test_protocol_round_trips_and_fingerprints() -> None:
    protocol = _protocol("declared_weights", ((A, 0.4), (B, 0.1)))
    assert len(protocol.fingerprint) == 64
    restored = PortfolioProtocol.from_mapping(protocol.canonical())
    assert restored == protocol
    assert restored.fingerprint == protocol.fingerprint


def test_cash_policy_dispatches_to_empty_target() -> None:
    target = build_target(_protocol("cash"), [A, B])
    assert target.weights == ()
    assert target.residual_cash_weight == 1.0


def test_equal_weight_policy_dispatches() -> None:
    target = build_target(_protocol("equal_weight"), [A, B])
    assert target.weight_for(A) == pytest.approx(0.5)
    assert target.weight_for(B) == pytest.approx(0.5)


def test_declared_weights_policy_dispatches_and_filters() -> None:
    protocol = _protocol("declared_weights", ((A, 0.4), (B, 0.1)))
    full = build_target(protocol, [A, B])
    assert full.weight_for(A) == pytest.approx(0.4)
    assert full.weight_for(B) == pytest.approx(0.1)
    # B has left the active set: its declared weight is filtered out of this event's target.
    filtered = build_target(protocol, [A])
    assert filtered.weight_for(A) == pytest.approx(0.4)
    assert filtered.weight_for(B) == 0.0


def test_declared_weights_required_only_for_that_policy() -> None:
    with pytest.raises(CanonicalError, match="non-empty"):
        _protocol("declared_weights")
    with pytest.raises(CanonicalError, match="must be empty"):
        _protocol("equal_weight", ((A, 0.5),))


def test_protocol_rejects_out_of_range_and_leveraged_declared_weights() -> None:
    with pytest.raises(CanonicalError, match="within"):
        _protocol("declared_weights", ((A, 1.5),))
    with pytest.raises(CanonicalError, match="exceeds 1"):
        _protocol("declared_weights", ((A, 0.6), (B, 0.6)))


def test_protocol_rejects_bad_policy_and_currency() -> None:
    with pytest.raises(CanonicalError, match="policy"):
        _protocol("momentum")
    with pytest.raises(CanonicalError, match="base_currency"):
        PortfolioProtocol(
            base_currency="usd",
            initial_cash=1000.0,
            policy="cash",
            cost_scenario=_ZERO,
            staleness=_STALE,
        )


def test_protocol_from_mapping_rejects_unknown_key() -> None:
    payload = _protocol("cash").canonical()
    payload["surprise"] = 1
    with pytest.raises(CanonicalError, match="unexpected key"):
        PortfolioProtocol.from_mapping(payload)
