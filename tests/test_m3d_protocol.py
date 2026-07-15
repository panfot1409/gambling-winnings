"""Tests for the M3D prospective protocol and the empty evaluation ledger."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from eth_research.m3d import _upstream as up
from eth_research.m3d.protocol import (
    EVALUATION_LEDGER_PATH,
    PROTOCOL_PATH,
    ProspectiveCohortProtocol,
    build_prospective_protocol,
    require_prospective_evaluation_ledger_empty,
    verify_prospective_protocol,
)

_REPO = Path(__file__).resolve().parents[1]


def _built() -> dict[str, Any]:
    return copy.deepcopy(build_prospective_protocol(_REPO).document)


def test_build_is_deterministic_and_committed_matches() -> None:
    a = build_prospective_protocol(_REPO).to_json_bytes()
    b = build_prospective_protocol(_REPO).to_json_bytes()
    assert a == b
    assert (_REPO / PROTOCOL_PATH).read_bytes() == a
    verify_prospective_protocol(_REPO)


def test_cohort_start_is_one_day_after_final_m2b_candle() -> None:
    doc = _built()
    assert doc["cohort_start"] == "2026-07-12T00:00:00Z"
    assert doc["relationship_to_m2b"]["final_m2b_candle_open"] == "2026-07-11T00:00:00Z"
    assert doc["relationship_to_m2b"]["zero_overlap"] is True


def test_maturity_is_365_and_does_not_authorize_evaluation() -> None:
    maturity = _built()["maturity"]
    assert maturity["minimum_maturity_row_count"] == 365
    assert maturity["minimum_consecutive_daily_candles"] == 365
    assert maturity["nominal_maturity_last_open"] == "2027-07-11T00:00:00Z"
    assert maturity["nominal_maturity_exclusive_end"] == "2027-07-12T00:00:00Z"
    assert maturity["maturity_authorizes_evaluation"] is False


def test_protocol_names_no_candidate() -> None:
    assert up.M3C_CANDIDATE_ID not in (_REPO / PROTOCOL_PATH).read_text()


def test_from_mapping_rejects_maturity_authorizing_evaluation() -> None:
    doc = _built()
    doc["maturity"]["maturity_authorizes_evaluation"] = True
    with pytest.raises(ValueError, match="must be exactly"):
        ProspectiveCohortProtocol.from_mapping(doc)


def test_from_mapping_rejects_changed_cohort_start() -> None:
    doc = _built()
    doc["cohort_start"] = "2026-07-11T00:00:00Z"  # would overlap M2B
    with pytest.raises(ValueError, match="must be exactly"):
        ProspectiveCohortProtocol.from_mapping(doc)


def test_from_mapping_rejects_lowered_maturity() -> None:
    doc = _built()
    doc["maturity"]["minimum_maturity_row_count"] = 30
    with pytest.raises(ValueError, match="must be exactly"):
        ProspectiveCohortProtocol.from_mapping(doc)


def test_from_mapping_rejects_smuggled_candidate_identifier() -> None:
    doc = _built()
    doc["source"]["documentation_url"] = f"https://x/{up.M3C_CANDIDATE_ID}"
    with pytest.raises(ValueError, match="must not name any strategy/candidate"):
        ProspectiveCohortProtocol.from_mapping(doc)


def test_from_mapping_rejects_unknown_key() -> None:
    doc = _built()
    doc["surprise"] = 1
    with pytest.raises(ValueError, match="unknown keys"):
        ProspectiveCohortProtocol.from_mapping(doc)


def test_evaluation_ledger_is_byte_empty() -> None:
    facts = require_prospective_evaluation_ledger_empty(_REPO)
    assert facts["byte_count"] == 0
    assert facts["event_count"] == 0
    assert facts["sha256"] == up.EMPTY_SHA256


def test_evaluation_ledger_nonempty_is_hard_stop() -> None:
    path = _REPO / EVALUATION_LEDGER_PATH
    original = path.read_bytes()
    try:
        path.write_bytes(b'{"evaluated": true}\n')
        with pytest.raises(ValueError, match="HARD STOP"):
            require_prospective_evaluation_ledger_empty(_REPO)
    finally:
        path.write_bytes(original)
