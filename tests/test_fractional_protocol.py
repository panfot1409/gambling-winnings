"""The frozen Milestone 3B fractional pre-registration protocol."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eth_research
from eth_research.data.provenance import sha256_file
from eth_research.fractional.protocol import (
    EXPERIMENT_FAMILY,
    FRACTIONAL_PROTOCOL_RELPATH,
    FractionalProtocol,
    ProtocolError,
    build_fractional_protocol,
    load_fractional_protocol,
)
from eth_research.walkforward import WALK_FORWARD_PROTOCOL_RELPATH

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
PROTOCOL_PATH = REPO_ROOT / FRACTIONAL_PROTOCOL_RELPATH


class TestCommittedProtocol:
    def test_committed_bytes_recompute(self) -> None:
        committed = PROTOCOL_PATH.read_bytes()
        # Version-independent: rebuild with the recorded version so a later bump
        # leaves the committed protocol byte-identical.
        recorded = load_fractional_protocol(PROTOCOL_PATH).package_version
        rebuilt = build_fractional_protocol(REPO_ROOT, package_version=recorded).to_json_bytes()
        assert committed == rebuilt

    def test_round_trips_byte_stably(self) -> None:
        protocol = load_fractional_protocol(PROTOCOL_PATH)
        assert protocol.to_json_bytes() == PROTOCOL_PATH.read_bytes()
        assert FractionalProtocol.from_json_bytes(protocol.to_json_bytes()) == protocol

    def test_pins_the_experiment_shape(self) -> None:
        p = load_fractional_protocol(PROTOCOL_PATH)
        assert p.experiment_family == EXPERIMENT_FAMILY
        assert p.experiment_cells == 75
        assert len(p.strategies) == 5
        assert [s.name for s in p.cost_scenarios] == [
            "compatibility_v1",
            "causal_proxy_base",
            "causal_proxy_stressed",
        ]
        assert p.oos_fold_count == 5
        assert p.initial_cash == 10_000.0
        assert p.bootstrap == "none"
        assert p.drawdown_breaker_enabled is False

    def test_binds_committed_folds_and_partition(self) -> None:
        p = load_fractional_protocol(PROTOCOL_PATH)
        assert p.walk_forward_protocol_sha256 == sha256_file(
            REPO_ROOT / WALK_FORWARD_PROTOCOL_RELPATH
        )
        assert p.development_partition_sha256 == sha256_file(
            REPO_ROOT / "research/m3a/development_partition.json"
        )
        assert p.frozen_m2_dossier_sha256 == sha256_file(
            REPO_ROOT / "research/m2b/frozen_dossier.json"
        )


class TestStrictParsing:
    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["surprise"] = 1
        with pytest.raises(ProtocolError, match="keys do not match"):
            FractionalProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_tampered_cell_count_is_rejected(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["experiment_cells"] = 60
        with pytest.raises(ProtocolError, match="experiment_cells"):
            FractionalProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_enabling_drawdown_breaker_is_rejected(self) -> None:
        payload = json.loads(PROTOCOL_PATH.read_bytes())
        payload["drawdown_breaker_enabled"] = True
        with pytest.raises(ProtocolError, match="drawdown breaker is disabled"):
            FractionalProtocol.from_json_bytes(json.dumps(payload).encode("utf-8"))
