"""Portfolio foundation: shared validation, currency codes, and instrument identity."""

from __future__ import annotations

import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.currencies import require_currency_code, same_currency
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.validation import (
    domain_hash,
    exact_keys,
    require_non_negative_finite_float,
    require_positive_finite_float,
    require_safe_token,
)


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def test_positive_finite_float_accepts_positive_and_rejects_others() -> None:
    assert require_positive_finite_float(1.5, "x") == 1.5
    for bad in (0.0, -1.0, float("inf"), float("nan")):
        with pytest.raises(CanonicalError):
            require_positive_finite_float(bad, "x")
    with pytest.raises(CanonicalError):
        require_positive_finite_float(1, "x")  # int is not a float
    with pytest.raises(CanonicalError):
        require_positive_finite_float(True, "x")  # bool is not a float


def test_non_negative_finite_float_accepts_zero() -> None:
    assert require_non_negative_finite_float(0.0, "x") == 0.0
    assert require_non_negative_finite_float(2.0, "x") == 2.0
    with pytest.raises(CanonicalError):
        require_non_negative_finite_float(-0.1, "x")


def test_safe_token_rejects_dangerous_strings() -> None:
    assert require_safe_token("ETH-USD", "s") == "ETH-USD"
    for bad in ("", " x", "x ", "a/b", "a\\b", "..", "a..b", "a\x00b", "a\tb", "​"):
        with pytest.raises(CanonicalError):
            require_safe_token(bad, "s")
    with pytest.raises(CanonicalError):
        require_safe_token("x" * 200, "s")


def test_exact_keys_flags_unknown_and_missing() -> None:
    exact_keys({"a": 1, "b": 2}, {"a", "b"}, "obj")
    with pytest.raises(CanonicalError, match="unexpected"):
        exact_keys({"a": 1, "b": 2, "c": 3}, {"a", "b"}, "obj")
    with pytest.raises(CanonicalError, match="missing"):
        exact_keys({"a": 1}, {"a", "b"}, "obj")


def test_domain_hash_is_stable_and_kind_separated() -> None:
    payload = {"x": 1, "y": [2, 3]}
    first = domain_hash("bar", payload)
    assert first == domain_hash("bar", payload)  # stable
    assert len(first) == 64
    assert first != domain_hash("calendar", payload)  # kind-separated
    with pytest.raises(CanonicalError):
        domain_hash("bar", {"v": float("inf")})  # non-finite refused


# --------------------------------------------------------------------------- #
# currencies
# --------------------------------------------------------------------------- #
def test_currency_code_accepts_uppercase_letters() -> None:
    for code in ("USD", "EUR", "USDT", "BTC"):
        assert require_currency_code(code, "c") == code
    assert same_currency("USD", "USD")
    assert not same_currency("USD", "EUR")


def test_currency_code_rejects_malformed() -> None:
    for bad in ("usd", "Usd", "US", "U", "US1", "US-D", "US D", "TOOLONGCURRENCY"):
        with pytest.raises(CanonicalError):
            require_currency_code(bad, "c")


# --------------------------------------------------------------------------- #
# instrument identity
# --------------------------------------------------------------------------- #
def _crypto() -> InstrumentId:
    return InstrumentId(
        asset_class="crypto_spot",
        base_asset="ETH",
        quote_currency="USD",
        venue="synthetic",
        symbol="ETH-USD",
        instrument_type="spot",
        price_unit="USD",
        quantity_unit="ETH",
        calendar_id="continuous_24_7",
    )


def test_instrument_identity_round_trips_and_hashes() -> None:
    inst = _crypto()
    assert len(inst.instrument_id) == 64
    restored = InstrumentId.from_mapping(inst.canonical())
    assert restored == inst
    assert restored.instrument_id == inst.instrument_id


def test_same_symbol_different_venue_is_a_different_instrument() -> None:
    a = _crypto()
    b = InstrumentId.from_mapping({**a.canonical(), "venue": "another_venue"})
    assert a != b
    assert a.instrument_id != b.instrument_id


def test_fx_spot_requires_currency_base_distinct_from_quote() -> None:
    fx = InstrumentId(
        asset_class="fx_spot",
        base_asset="EUR",
        quote_currency="USD",
        venue="synthetic",
        symbol="EURUSD",
        instrument_type="spot",
        price_unit="USD",
        quantity_unit="EUR",
        calendar_id="continuous_24_7",
    )
    assert fx.asset_class == "fx_spot"
    with pytest.raises(CanonicalError):  # base == quote
        InstrumentId.from_mapping({**fx.canonical(), "base_asset": "USD"})


@pytest.mark.parametrize(
    "override",
    [
        {"asset_class": "futures"},
        {"instrument_type": "perpetual"},
        {"instrument_type": "future"},
        {"instrument_type": "option"},
        {"price_unit": "EUR"},  # price_unit must equal quote currency
        {"venue": "a/b"},
        {"symbol": ".."},
        {"quote_currency": "usd"},
    ],
)
def test_instrument_rejects_invalid_fields(override: dict[str, str]) -> None:
    with pytest.raises(CanonicalError):
        InstrumentId.from_mapping({**_crypto().canonical(), **override})


def test_instrument_from_mapping_rejects_unknown_and_missing_keys() -> None:
    with pytest.raises(CanonicalError):
        InstrumentId.from_mapping({**_crypto().canonical(), "extra": "x"})
    partial = _crypto().canonical()
    del partial["symbol"]
    with pytest.raises(CanonicalError):
        InstrumentId.from_mapping(partial)
