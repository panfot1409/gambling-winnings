"""Corporate actions: per-type field rules, causal ordering, and hand-checked adjustments."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.corporate_actions import (
    ACTION_TYPES,
    CorporateAction,
    CorporateActionSet,
)
from eth_research.portfolio.identity import InstrumentId


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _inst(symbol: str = "ETH-USD", base: str = "ETH") -> InstrumentId:
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


ETH = _inst("ETH-USD", "ETH")
BTC = _inst("BTC-USD", "BTC")


def _split(ratio: float | None = 2.0, *, action_id: str = "s1") -> CorporateAction:
    return CorporateAction(
        instrument=ETH,
        action_id=action_id,
        action_type="split",
        knowledge_time=_ts("2026-01-01T00:00:00"),
        effective_time=_ts("2026-01-05T00:00:00"),
        payment_time=None,
        ratio=ratio,
        cash_amount=None,
        currency=None,
        source="synthetic",
    )


def _dividend(
    *,
    cash_amount: float | None = 0.5,
    currency: str | None = "USD",
    payment: str | None = "2026-01-10T00:00:00",
    ratio: float | None = None,
    action_id: str = "d1",
) -> CorporateAction:
    return CorporateAction(
        instrument=ETH,
        action_id=action_id,
        action_type="cash_dividend",
        knowledge_time=_ts("2026-01-01T00:00:00"),
        effective_time=_ts("2026-01-05T00:00:00"),
        payment_time=None if payment is None else _ts(payment),
        ratio=ratio,
        cash_amount=cash_amount,
        currency=currency,
        source="synthetic",
    )


# --------------------------------------------------------------------------- #
# hand-checked adjustments
# --------------------------------------------------------------------------- #
def test_split_hand_values() -> None:
    action = _split(ratio=2.0)
    assert action.ratio is not None
    # a 2-for-1 split: quantity * ratio, price / ratio
    quantity, price = 10.0, 100.0
    assert quantity * action.ratio == pytest.approx(20.0)
    assert price / action.ratio == pytest.approx(50.0)
    assert action.cash_amount is None
    assert action.currency is None
    assert action.payment_time is None


def test_reverse_split_hand_values() -> None:
    action = CorporateAction(
        instrument=ETH,
        action_id="r1",
        action_type="reverse_split",
        knowledge_time=_ts("2026-01-01T00:00:00"),
        effective_time=_ts("2026-01-05T00:00:00"),
        payment_time=None,
        ratio=0.2,
        cash_amount=None,
        currency=None,
        source="synthetic",
    )
    assert action.ratio is not None
    # a 1-for-5 reverse split (ratio 0.2): quantity * 0.2, price / 0.2
    quantity, price = 10.0, 100.0
    assert quantity * action.ratio == pytest.approx(2.0)
    assert price / action.ratio == pytest.approx(500.0)


def test_cash_dividend_hand_values() -> None:
    action = _dividend(cash_amount=0.5)
    assert action.cash_amount is not None
    # per-share dividend of 0.5 over 10 shares pays 5.0
    shares = 10.0
    assert shares * action.cash_amount == pytest.approx(5.0)
    assert action.currency == "USD"
    assert action.payment_time == _ts("2026-01-10T00:00:00")


# --------------------------------------------------------------------------- #
# per-type field rejections
# --------------------------------------------------------------------------- #
def test_split_field_rules() -> None:
    with pytest.raises(CanonicalError, match="ratio is required"):
        _split(ratio=None)
    with pytest.raises(CanonicalError, match="ratio must be > 1"):
        _split(ratio=1.0)
    with pytest.raises(CanonicalError, match="ratio must be > 1"):
        _split(ratio=0.5)
    with pytest.raises(CanonicalError, match="must be null"):
        CorporateAction(
            instrument=ETH,
            action_id="s2",
            action_type="split",
            knowledge_time=_ts("2026-01-01T00:00:00"),
            effective_time=_ts("2026-01-05T00:00:00"),
            payment_time=None,
            ratio=2.0,
            cash_amount=1.0,  # cash fields forbidden for a split
            currency="USD",
            source="synthetic",
        )


def test_reverse_split_ratio_must_be_in_open_unit_interval() -> None:
    def _reverse(ratio: float) -> CorporateAction:
        return CorporateAction(
            instrument=ETH,
            action_id="r2",
            action_type="reverse_split",
            knowledge_time=_ts("2026-01-01T00:00:00"),
            effective_time=_ts("2026-01-05T00:00:00"),
            payment_time=None,
            ratio=ratio,
            cash_amount=None,
            currency=None,
            source="synthetic",
        )

    with pytest.raises(CanonicalError, match="must be in"):
        _reverse(1.0)
    with pytest.raises(CanonicalError, match="must be in"):
        _reverse(2.0)
    with pytest.raises(CanonicalError, match="positive finite"):
        _reverse(0.0)


def test_cash_dividend_field_rules() -> None:
    with pytest.raises(CanonicalError, match="cash_amount is required"):
        _dividend(cash_amount=None)
    with pytest.raises(CanonicalError, match="cash_amount must be > 0"):
        _dividend(cash_amount=0.0)
    with pytest.raises(CanonicalError, match="currency is required"):
        _dividend(currency=None)
    with pytest.raises(CanonicalError, match="payment_time is required"):
        _dividend(payment=None)
    with pytest.raises(CanonicalError, match="ratio must be null"):
        _dividend(ratio=2.0)
    with pytest.raises(CanonicalError, match="payment_time must be >= effective_time"):
        _dividend(payment="2026-01-04T00:00:00")  # before effective_time


def test_delisting_cash_out_field_rules() -> None:
    def _delist(
        *,
        cash_amount: float | None = 3.0,
        currency: str | None = "USD",
        payment: str | None = "2026-01-06T00:00:00",
    ) -> CorporateAction:
        return CorporateAction(
            instrument=ETH,
            action_id="x1",
            action_type="delisting_cash_out",
            knowledge_time=_ts("2026-01-01T00:00:00"),
            effective_time=_ts("2026-01-05T00:00:00"),
            payment_time=None if payment is None else _ts(payment),
            ratio=None,
            cash_amount=cash_amount,
            currency=currency,
            source="synthetic",
        )

    # a zero cash-out is allowed (>= 0)
    assert _delist(cash_amount=0.0).cash_amount == 0.0
    with pytest.raises(CanonicalError, match="cash_amount is required"):
        _delist(cash_amount=None)
    with pytest.raises(CanonicalError, match="currency is required"):
        _delist(currency=None)
    with pytest.raises(CanonicalError, match="payment_time is required"):
        _delist(payment=None)


def test_knowledge_time_must_not_be_after_effective_time() -> None:
    with pytest.raises(CanonicalError, match="not be after effective_time"):
        CorporateAction(
            instrument=ETH,
            action_id="k1",
            action_type="split",
            knowledge_time=_ts("2026-01-06T00:00:00"),  # after effective
            effective_time=_ts("2026-01-05T00:00:00"),
            payment_time=None,
            ratio=2.0,
            cash_amount=None,
            currency=None,
            source="synthetic",
        )


def test_action_type_vocabulary_and_rejection() -> None:
    assert set(ACTION_TYPES) == {"split", "reverse_split", "cash_dividend", "delisting_cash_out"}
    with pytest.raises(CanonicalError, match="expected one of"):
        CorporateAction(
            instrument=ETH,
            action_id="bad",
            action_type="merger",
            knowledge_time=_ts("2026-01-01T00:00:00"),
            effective_time=_ts("2026-01-05T00:00:00"),
            payment_time=None,
            ratio=None,
            cash_amount=None,
            currency=None,
            source="synthetic",
        )


# --------------------------------------------------------------------------- #
# round trip
# --------------------------------------------------------------------------- #
def test_each_action_type_round_trips() -> None:
    delist = CorporateAction(
        instrument=BTC,
        action_id="x9",
        action_type="delisting_cash_out",
        knowledge_time=_ts("2026-01-01T00:00:00"),
        effective_time=_ts("2026-01-05T00:00:00"),
        payment_time=_ts("2026-01-06T00:00:00"),
        ratio=None,
        cash_amount=42.0,
        currency="USD",
        source="synthetic",
    )
    for action in (_split(), _dividend(), delist):
        assert CorporateAction.from_mapping(action.canonical()) == action


def test_from_mapping_rejects_unknown_keys() -> None:
    with pytest.raises(CanonicalError, match="unexpected"):
        CorporateAction.from_mapping({**_split().canonical(), "extra": 1})


# --------------------------------------------------------------------------- #
# CorporateActionSet
# --------------------------------------------------------------------------- #
def test_set_rejects_duplicate_action_id() -> None:
    with pytest.raises(CanonicalError, match="duplicate action_id"):
        CorporateActionSet(actions=(_split(action_id="dup"), _dividend(action_id="dup")))


def test_actions_for_filters_by_instrument() -> None:
    on_btc = CorporateAction(
        instrument=BTC,
        action_id="b1",
        action_type="split",
        knowledge_time=_ts("2026-01-01T00:00:00"),
        effective_time=_ts("2026-01-05T00:00:00"),
        payment_time=None,
        ratio=3.0,
        cash_amount=None,
        currency=None,
        source="synthetic",
    )
    action_set = CorporateActionSet(actions=(_split(action_id="e1"), on_btc))
    eth_actions = action_set.actions_for(ETH)
    assert len(eth_actions) == 1
    assert eth_actions[0].action_id == "e1"
    assert action_set.actions_for(BTC)[0].action_id == "b1"


def test_known_by_is_causal() -> None:
    early = _split(action_id="early")  # knowledge 2026-01-01
    late = CorporateAction(
        instrument=ETH,
        action_id="late",
        action_type="split",
        knowledge_time=_ts("2026-02-01T00:00:00"),
        effective_time=_ts("2026-02-05T00:00:00"),
        payment_time=None,
        ratio=2.0,
        cash_amount=None,
        currency=None,
        source="synthetic",
    )
    action_set = CorporateActionSet(actions=(early, late))
    known = action_set.known_by(_ts("2026-01-15T00:00:00"))
    assert len(known) == 1
    assert known[0].action_id == "early"
    assert len(action_set.known_by(_ts("2026-03-01T00:00:00"))) == 2


def test_set_fingerprint_order_independent_stable_and_sensitive() -> None:
    a = _split(action_id="a")
    b = _dividend(action_id="b")
    forward = CorporateActionSet(actions=(a, b))
    reversed_order = CorporateActionSet(actions=(b, a))
    assert forward.fingerprint == reversed_order.fingerprint  # canonical order
    assert CorporateActionSet.from_mapping(forward.canonical()).fingerprint == forward.fingerprint
    changed = CorporateActionSet(actions=(_split(action_id="a", ratio=3.0), b))
    assert changed.fingerprint != forward.fingerprint
