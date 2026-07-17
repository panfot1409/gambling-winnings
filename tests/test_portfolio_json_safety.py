"""Consolidated JSON / file safety for the M4B artifact set (Milestone 4B, §36).

Every M4B canonical artifact is symmetric (``canonical()`` round-trips through the strict decoder
and ``from_mapping`` byte-for-byte) and every read goes through the accepted strict decoder, which
enforces a size ceiling, a mandatory trailing newline, UTF-8, and rejects duplicate keys and
non-finite numbers. This module proves those guarantees uniformly across the four public artifacts
— the universe, result, trace commitment, and checkpoint — rather than one model at a time.
"""

from __future__ import annotations

import pytest

from eth_research.api.serialization import (
    CanonicalError,
    canonical_json_bytes,
    strict_load_canonical,
)
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.reference import (
    ReferenceUniverse,
    build_reference_universe,
    reference_protocol,
)
from eth_research.portfolio.result import PortfolioResult, build_portfolio_result
from eth_research.portfolio.streaming import PortfolioCheckpoint, stream_portfolio_simulation
from eth_research.portfolio.trace import TraceCommitment
from eth_research.portfolio.universe import UniverseSpec

_SECONDS_PER_YEAR = 365.25 * 24.0 * 3600.0


def _reference() -> ReferenceUniverse:
    return build_reference_universe()


def _result(reference: ReferenceUniverse) -> PortfolioResult:
    run = run_portfolio_simulation(
        reference_protocol(),
        reference.panel,
        reference.membership,
        reference.fx,
        reference.run_schedule,
        calendars=reference.calendars,
        corporate_actions=reference.corporate_actions,
    )
    ppy = _SECONDS_PER_YEAR / reference.universe_spec.bar_interval_seconds
    metrics = compute_portfolio_metrics(run, periods_per_year=ppy)
    return build_portfolio_result(run, metrics, reference.universe_spec)


def _first_checkpoint(reference: ReferenceUniverse) -> PortfolioCheckpoint:
    for _event, checkpoint in stream_portfolio_simulation(
        reference_protocol(),
        reference.panel,
        reference.membership,
        reference.fx,
        reference.run_schedule,
        calendars=reference.calendars,
        corporate_actions=reference.corporate_actions,
    ):
        return checkpoint
    raise AssertionError("the reference run produced no checkpoint")


# --------------------------------------------------------------------------- #
# symmetric canonical round-trip across every public artifact
# --------------------------------------------------------------------------- #
def test_universe_round_trips_through_strict_decoder() -> None:
    reference = _reference()
    spec = reference.universe_spec
    raw = canonical_json_bytes(spec.canonical())
    restored = UniverseSpec.from_mapping(
        strict_load_canonical(raw, "universe"), reference.calendars
    )
    assert restored.canonical() == spec.canonical()
    assert restored.fingerprint == spec.fingerprint


def test_result_round_trips_through_strict_decoder() -> None:
    result = _result(_reference())
    raw = canonical_json_bytes(result.canonical())
    restored = PortfolioResult.from_mapping(strict_load_canonical(raw, "result"))
    assert restored.canonical() == result.canonical()
    assert restored.result_id == result.result_id


def test_trace_round_trips_through_strict_decoder() -> None:
    trace = _result(_reference()).trace_commitment
    raw = canonical_json_bytes(trace.canonical())
    restored = TraceCommitment.from_mapping(strict_load_canonical(raw, "trace_commitment"))
    assert restored.canonical() == trace.canonical()
    assert restored.commitment_id == trace.commitment_id


def test_checkpoint_round_trips_through_strict_decoder() -> None:
    checkpoint = _first_checkpoint(_reference())
    raw = canonical_json_bytes(checkpoint.canonical())
    restored = PortfolioCheckpoint.from_mapping(strict_load_canonical(raw, "portfolio_checkpoint"))
    assert restored.canonical() == checkpoint.canonical()


# --------------------------------------------------------------------------- #
# the strict read boundary — every M4B file read goes through this decoder
# --------------------------------------------------------------------------- #
def test_read_boundary_rejects_duplicate_keys() -> None:
    # A duplicated object key (which stdlib json would silently keep the last of) is rejected.
    with pytest.raises(CanonicalError, match="duplicate"):
        strict_load_canonical(b'{\n  "a": 1,\n  "a": 2\n}\n', "dup")


def test_read_boundary_requires_a_trailing_newline() -> None:
    result = _result(_reference())
    raw = canonical_json_bytes(result.canonical())
    assert raw.endswith(b"\n")
    with pytest.raises(CanonicalError):
        strict_load_canonical(raw.rstrip(b"\n"), "result")


def test_read_boundary_rejects_non_finite_numbers() -> None:
    poisoned = b'{\n  "value": Infinity\n}\n'
    with pytest.raises(CanonicalError):
        strict_load_canonical(poisoned, "poisoned")
    poisoned_nan = b'{\n  "value": NaN\n}\n'
    with pytest.raises(CanonicalError):
        strict_load_canonical(poisoned_nan, "poisoned")


def test_read_boundary_rejects_oversize_payloads() -> None:
    huge = b'{\n  "blob": "' + b"a" * (5 * 1024 * 1024) + b'"\n}\n'
    with pytest.raises(CanonicalError, match="ceiling"):
        strict_load_canonical(huge, "huge")


# --------------------------------------------------------------------------- #
# exact-key strictness on the artifact parsers (no unknown keys admitted)
# --------------------------------------------------------------------------- #
def test_result_parser_rejects_an_unknown_key() -> None:
    payload = _result(_reference()).canonical()
    payload["surprise"] = 1
    with pytest.raises(CanonicalError):
        PortfolioResult.from_mapping(payload)


def test_trace_parser_rejects_an_unknown_key() -> None:
    payload = _result(_reference()).trace_commitment.canonical()
    payload["surprise"] = 1
    with pytest.raises(CanonicalError):
        TraceCommitment.from_mapping(payload)
