"""The long-only target contract, the reference allocation policies, and the tolerances."""

from __future__ import annotations

import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.targets import (
    PortfolioTarget,
    cash_target,
    declared_weights_target,
    equal_weight_target,
)
from eth_research.portfolio.tolerances import DEFAULT_TOLERANCES, PortfolioTolerances


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
C = _inst("C-USD", "CCC")


# --------------------------------------------------------------------------- #
# tolerances
# --------------------------------------------------------------------------- #
def test_tolerances_defaults_and_validation() -> None:
    assert DEFAULT_TOLERANCES.weight == 1e-9
    assert DEFAULT_TOLERANCES.max_iterations == 100
    with pytest.raises(ValueError, match="positive float"):
        PortfolioTolerances(cash=0.0)
    with pytest.raises(ValueError, match="max_iterations"):
        PortfolioTolerances(max_iterations=0)


# --------------------------------------------------------------------------- #
# target contract
# --------------------------------------------------------------------------- #
def test_target_orders_canonically_and_computes_residual() -> None:
    target = PortfolioTarget(weights=((B, 0.5), (A, 0.2)))
    # canonically ordered by instrument_id hash, independent of input order
    assert target.instruments == tuple(sorted((A, B), key=lambda i: i.instrument_id))
    assert target.gross_weight == pytest.approx(0.7)
    assert target.residual_cash_weight == pytest.approx(0.3)
    assert target.weight_for(A) == pytest.approx(0.2)
    assert target.weight_for(C) == 0.0


def test_target_round_trips() -> None:
    target = PortfolioTarget(weights=((A, 0.25), (B, 0.25)))
    restored = PortfolioTarget.from_mapping(target.canonical())
    assert restored == target
    assert restored.fingerprint == target.fingerprint


def test_target_rejects_leverage_and_negatives_and_duplicates() -> None:
    with pytest.raises(CanonicalError):  # gross > 1
        PortfolioTarget(weights=((A, 0.6), (B, 0.6)))
    with pytest.raises(CanonicalError):  # negative weight
        PortfolioTarget(weights=((A, -0.1),))
    with pytest.raises(CanonicalError):  # weight > 1
        PortfolioTarget(weights=((A, 1.5),))
    with pytest.raises(CanonicalError):  # duplicate instrument
        PortfolioTarget(weights=((A, 0.1), (A, 0.2)))


def test_target_require_subset_of_active() -> None:
    target = PortfolioTarget(weights=((A, 0.5),))
    target.require_subset_of([A, B])  # ok
    with pytest.raises(CanonicalError):
        target.require_subset_of([B, C])


def test_full_allocation_within_tolerance_is_allowed() -> None:
    # three equal weights sum to just under 1 in binary64; must be accepted
    target = equal_weight_target([A, B, C])
    assert target.gross_weight <= 1.0 + DEFAULT_TOLERANCES.weight
    assert target.residual_cash_weight >= -DEFAULT_TOLERANCES.weight


# --------------------------------------------------------------------------- #
# reference policies
# --------------------------------------------------------------------------- #
def test_cash_policy_allocates_nothing() -> None:
    target = cash_target([A, B])
    assert target.weights == ()
    assert target.residual_cash_weight == 1.0


def test_equal_weight_policy() -> None:
    target = equal_weight_target([A, B, C])
    assert len(target.weights) == 3
    for _, weight in target.weights:
        assert weight == pytest.approx(1.0 / 3.0)
    assert equal_weight_target([]).weights == ()


def test_declared_weights_policy() -> None:
    target = declared_weights_target([A, B, C], {A: 0.4, B: 0.1})
    assert target.weight_for(A) == pytest.approx(0.4)
    assert target.weight_for(B) == pytest.approx(0.1)
    assert target.weight_for(C) == 0.0
    with pytest.raises(CanonicalError):  # declares an instrument not in active
        declared_weights_target([A], {B: 0.5})
