"""Currency / FX evidence: causal ``rate_as_of``, inverse, and predeclared triangulation."""

from __future__ import annotations

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.fx import FxEvidence, FxObservation


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _obs(base: str, quote: str, time: str, rate: float) -> FxObservation:
    return FxObservation(
        base_currency=base,
        quote_currency=quote,
        observed_time=_ts(time),
        rate=rate,
        source="synthetic",
    )


# --------------------------------------------------------------------------- #
# observation construction and validation
# --------------------------------------------------------------------------- #
def test_observation_round_trips_and_rejects_bad_fields() -> None:
    obs = _obs("EUR", "USD", "2026-01-01T00:00:00", 1.1)
    assert FxObservation.from_mapping(obs.canonical()) == obs
    with pytest.raises(CanonicalError, match="must differ from quote_currency"):
        _obs("USD", "USD", "2026-01-01T00:00:00", 1.0)
    with pytest.raises(CanonicalError, match="positive finite"):
        _obs("EUR", "USD", "2026-01-01T00:00:00", 0.0)
    with pytest.raises(CanonicalError, match="positive finite"):
        _obs("EUR", "USD", "2026-01-01T00:00:00", -1.0)
    with pytest.raises(CanonicalError, match="timezone-aware"):
        FxObservation(
            base_currency="EUR",
            quote_currency="USD",
            observed_time=pd.Timestamp("2026-01-01T00:00:00"),  # naive
            rate=1.1,
            source="synthetic",
        )


# --------------------------------------------------------------------------- #
# rate_as_of: causal, most-recent-not-future, inverse, same-currency, missing
# --------------------------------------------------------------------------- #
def test_rate_as_of_is_most_recent_and_never_future() -> None:
    evidence = FxEvidence(
        observations=(
            _obs("EUR", "USD", "2026-01-01T00:00:00", 1.10),
            _obs("EUR", "USD", "2026-01-05T00:00:00", 1.20),
            _obs("EUR", "USD", "2026-01-10T00:00:00", 1.30),
        )
    )
    # before any observation: missing (no past rate)
    with pytest.raises(CanonicalError, match="no rate"):
        evidence.rate_as_of("EUR", "USD", _ts("2025-12-31T00:00:00"))
    # exactly on an observation time is usable (observed_time <= tau)
    assert evidence.rate_as_of("EUR", "USD", _ts("2026-01-01T00:00:00")) == pytest.approx(1.10)
    # between observations: the most recent past one, never the future one
    assert evidence.rate_as_of("EUR", "USD", _ts("2026-01-07T00:00:00")) == pytest.approx(1.20)
    assert evidence.rate_as_of("EUR", "USD", _ts("2026-01-09T23:59:59")) == pytest.approx(1.20)
    assert evidence.rate_as_of("EUR", "USD", _ts("2026-01-10T00:00:00")) == pytest.approx(1.30)


def test_rate_as_of_same_currency_is_one() -> None:
    evidence = FxEvidence(observations=())
    assert evidence.rate_as_of("USD", "USD", _ts("2026-01-01T00:00:00")) == 1.0


def test_rate_as_of_uses_explicit_inverse() -> None:
    evidence = FxEvidence(observations=(_obs("EUR", "USD", "2026-01-01T00:00:00", 1.25),))
    # direct EUR->USD
    assert evidence.rate_as_of("EUR", "USD", _ts("2026-01-02T00:00:00")) == pytest.approx(1.25)
    # inverse USD->EUR = 1 / 1.25 = 0.8
    assert evidence.rate_as_of("USD", "EUR", _ts("2026-01-02T00:00:00")) == pytest.approx(0.8)


def test_rate_as_of_missing_pair_raises() -> None:
    evidence = FxEvidence(observations=(_obs("EUR", "USD", "2026-01-01T00:00:00", 1.25),))
    with pytest.raises(CanonicalError, match="no rate"):
        evidence.rate_as_of("GBP", "USD", _ts("2026-01-02T00:00:00"))


# --------------------------------------------------------------------------- #
# triangulation: only when predeclared
# --------------------------------------------------------------------------- #
def test_rate_as_of_does_not_triangulate_without_declaration() -> None:
    # EUR->USD and USD->JPY both present, but EUR->JPY is neither direct nor inverse
    evidence = FxEvidence(
        observations=(
            _obs("EUR", "USD", "2026-01-01T00:00:00", 1.10),
            _obs("USD", "JPY", "2026-01-01T00:00:00", 150.0),
        )
    )
    with pytest.raises(CanonicalError, match="no rate"):
        evidence.rate_as_of("EUR", "JPY", _ts("2026-01-02T00:00:00"))


def test_predeclared_triangulation_computes_product_causally() -> None:
    evidence = FxEvidence(
        observations=(
            _obs("EUR", "USD", "2026-01-01T00:00:00", 1.10),
            _obs("USD", "JPY", "2026-01-01T00:00:00", 150.0),
            # a later EUR->USD that must NOT be used for an earlier tau
            _obs("EUR", "USD", "2026-01-10T00:00:00", 2.00),
        ),
        triangulation={("EUR", "JPY"): "USD"},
    )
    # 1.10 (USD per EUR) * 150.0 (JPY per USD) = 165.0 JPY per EUR
    assert evidence.rate_as_of("EUR", "JPY", _ts("2026-01-05T00:00:00")) == pytest.approx(165.0)
    # after the later EUR->USD observation: 2.00 * 150.0 = 300.0
    assert evidence.rate_as_of("EUR", "JPY", _ts("2026-01-11T00:00:00")) == pytest.approx(300.0)


def test_predeclared_triangulation_leg_may_use_inverse() -> None:
    evidence = FxEvidence(
        observations=(
            _obs("USD", "EUR", "2026-01-01T00:00:00", 0.8),  # inverse of EUR->USD
            _obs("USD", "JPY", "2026-01-01T00:00:00", 150.0),
        ),
        triangulation={("EUR", "JPY"): "USD"},
    )
    # EUR->USD via inverse of USD->EUR = 1/0.8 = 1.25; then *150 = 187.5
    assert evidence.rate_as_of("EUR", "JPY", _ts("2026-01-02T00:00:00")) == pytest.approx(187.5)


def test_predeclared_triangulation_missing_leg_raises() -> None:
    evidence = FxEvidence(
        observations=(
            _obs("EUR", "USD", "2026-01-01T00:00:00", 1.10),
            # USD->JPY only exists AFTER the query tau
            _obs("USD", "JPY", "2026-01-10T00:00:00", 150.0),
        ),
        triangulation={("EUR", "JPY"): "USD"},
    )
    with pytest.raises(CanonicalError, match="no causal rate"):
        evidence.rate_as_of("EUR", "JPY", _ts("2026-01-05T00:00:00"))


def test_triangulation_rejects_degenerate_declarations() -> None:
    with pytest.raises(CanonicalError, match="pivot must differ"):
        FxEvidence(observations=(), triangulation={("EUR", "JPY"): "EUR"})
    with pytest.raises(CanonicalError, match="base must differ from its quote"):
        FxEvidence(observations=(), triangulation={("EUR", "EUR"): "USD"})


# --------------------------------------------------------------------------- #
# evidence invariants, fingerprint, round trip
# --------------------------------------------------------------------------- #
def test_evidence_rejects_duplicate_timestamp_for_a_pair() -> None:
    with pytest.raises(CanonicalError, match="ascending"):
        FxEvidence(
            observations=(
                _obs("EUR", "USD", "2026-01-01T00:00:00", 1.10),
                _obs("EUR", "USD", "2026-01-01T00:00:00", 1.20),
            )
        )


def test_evidence_orders_observations_and_fingerprint_is_order_independent() -> None:
    forward = FxEvidence(
        observations=(
            _obs("EUR", "USD", "2026-01-01T00:00:00", 1.10),
            _obs("EUR", "USD", "2026-01-05T00:00:00", 1.20),
        )
    )
    shuffled = FxEvidence(
        observations=(
            _obs("EUR", "USD", "2026-01-05T00:00:00", 1.20),
            _obs("EUR", "USD", "2026-01-01T00:00:00", 1.10),
        )
    )
    assert forward.fingerprint == shuffled.fingerprint
    assert forward == shuffled


def test_evidence_round_trips_with_triangulation() -> None:
    evidence = FxEvidence(
        observations=(
            _obs("EUR", "USD", "2026-01-01T00:00:00", 1.10),
            _obs("USD", "JPY", "2026-01-01T00:00:00", 150.0),
        ),
        triangulation={("EUR", "JPY"): "USD"},
    )
    restored = FxEvidence.from_mapping(evidence.canonical())
    assert restored == evidence
    assert restored.fingerprint == evidence.fingerprint


def test_evidence_fingerprint_is_content_sensitive() -> None:
    base = FxEvidence(observations=(_obs("EUR", "USD", "2026-01-01T00:00:00", 1.10),))
    changed = FxEvidence(observations=(_obs("EUR", "USD", "2026-01-01T00:00:00", 1.11),))
    assert base.fingerprint != changed.fingerprint


def test_evidence_from_mapping_rejects_unknown_keys() -> None:
    payload = FxEvidence(observations=()).canonical()
    with pytest.raises(CanonicalError, match="unexpected"):
        FxEvidence.from_mapping({**payload, "extra": []})
