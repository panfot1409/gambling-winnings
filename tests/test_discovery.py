"""Machine-verified earliest-continuous-start decision (P3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eth_research
from eth_research.discovery import (
    DiscoveryDecision,
    DiscoveryDecisionError,
    build_discovery_decision,
    load_discovery_decision,
    render_discovery_decision,
    verify_discovery_decision_from_raw,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
DISCOVERY_ATTEMPT = REPO_ROOT / "research/m2b/raw/coinbase/discovery-001"
DECISION_JSON = REPO_ROOT / "research/m2b/discovery_decision.json"
DECISION_MD = REPO_ROOT / "research/m2b/EARLIEST_CONTINUOUS_DECISION.md"

pytestmark = pytest.mark.skipif(
    not DISCOVERY_ATTEMPT.is_dir(), reason="committed discovery attempt not present"
)


def _raw_bytes() -> bytes:
    body = next(p for p in DISCOVERY_ATTEMPT.glob("*.json") if p.name != "acquisition_receipt.json")
    return body.read_bytes()


class TestDerivedFacts:
    def test_start_is_advanced_past_the_early_gap(self) -> None:
        decision = build_discovery_decision(REPO_ROOT)
        assert decision.first_available_open_time.date().isoformat() == "2016-05-18"
        assert [ts.date().isoformat() for ts in decision.missing_early_open_times] == [
            "2016-05-21",
            "2016-05-22",
        ]
        assert decision.chosen_start.date().isoformat() == "2016-05-23"
        assert decision.chosen_end.date().isoformat() == "2026-07-12"
        assert decision.discovery_candle_count == 257


class TestMachineVerification:
    def test_real_decision_verifies_against_the_raw_bytes(self) -> None:
        decision = build_discovery_decision(REPO_ROOT)
        verify_discovery_decision_from_raw(decision, _raw_bytes())  # must not raise

    def test_tampered_raw_bytes_are_rejected(self) -> None:
        decision = build_discovery_decision(REPO_ROOT)
        with pytest.raises(DiscoveryDecisionError, match="raw_response_sha256"):
            verify_discovery_decision_from_raw(decision, _raw_bytes() + b" ")

    def test_forged_candle_count_is_caught_against_the_bytes(self) -> None:
        decision = build_discovery_decision(REPO_ROOT)
        payload = json.loads(decision.to_json_bytes())
        payload["discovery_candle_count"] = 999
        forged = DiscoveryDecision.from_json_bytes(json.dumps(payload).encode("utf-8"))
        with pytest.raises(DiscoveryDecisionError, match="candle count"):
            verify_discovery_decision_from_raw(forged, _raw_bytes())


class TestReproducibility:
    def test_committed_json_matches(self) -> None:
        assert DECISION_JSON.read_bytes() == build_discovery_decision(REPO_ROOT).to_json_bytes()

    def test_committed_markdown_matches(self) -> None:
        rendered = render_discovery_decision(build_discovery_decision(REPO_ROOT))
        assert DECISION_MD.read_text(encoding="utf-8") == rendered

    def test_round_trips_byte_stably(self) -> None:
        decision = load_discovery_decision(DECISION_JSON)
        assert decision.to_json_bytes() == DECISION_JSON.read_bytes()


class TestStrictValidation:
    def test_missing_candle_at_or_after_start_is_rejected(self) -> None:
        payload = json.loads(DECISION_JSON.read_bytes())
        # Claim a missing candle after the chosen start — inconsistent with a
        # gap-free start.
        payload["missing_early_open_times"] = ["2016-06-01T00:00:00+00:00"]
        with pytest.raises(ValueError, match="strictly between"):
            DiscoveryDecision.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(DECISION_JSON.read_bytes())
        payload["extra"] = 1
        with pytest.raises(ValueError, match=r"unknown=\['extra'\]"):
            DiscoveryDecision.from_json_bytes(json.dumps(payload).encode("utf-8"))
