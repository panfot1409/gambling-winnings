"""Strict, symmetric v2 methodology / protocol artifact (Phase 11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eth_research
from eth_research.data.provenance import sha256_file
from eth_research.methodology_v2 import (
    METHODOLOGY_PROTOCOL_V2_RELPATH,
    RESULTS_SCHEMA_VERSION_V2,
    RETURN_EVIDENCE_SCHEMA_VERSION,
    MethodologyProtocolV2,
    build_methodology_v2,
    load_methodology_v2,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


class TestCommittedArtifact:
    def test_committed_bytes_reproduce_and_parse(self) -> None:
        committed = REPO_ROOT / METHODOLOGY_PROTOCOL_V2_RELPATH
        # The methodology content is version-independent: rebuild with the
        # committed recorded version so a later package bump stays byte-identical.
        loaded = load_methodology_v2(committed)
        rebuilt = build_methodology_v2(package_version=loaded.package_version)
        assert committed.read_bytes() == rebuilt.to_json_bytes()
        assert loaded == rebuilt

    def test_binds_the_frozen_v1_protocol_by_hash(self) -> None:
        m = build_methodology_v2()
        v1_sha = sha256_file(REPO_ROOT / m.base_walk_forward_protocol_path)
        assert m.base_walk_forward_protocol_sha256 == v1_sha


class TestSymmetry:
    def test_round_trip(self) -> None:
        m = build_methodology_v2()
        assert MethodologyProtocolV2.from_json_bytes(m.to_json_bytes()) == m

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(build_methodology_v2().to_json_bytes())
        payload["surprise"] = 1
        with pytest.raises(ValueError, match="keys do not match"):
            MethodologyProtocolV2.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_missing_key_is_rejected(self) -> None:
        payload = json.loads(build_methodology_v2().to_json_bytes())
        del payload["methodology_id"]
        with pytest.raises(ValueError, match="keys do not match"):
            MethodologyProtocolV2.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestPins:
    def test_primary_and_sensitivity_bootstrap_are_pinned(self) -> None:
        m = build_methodology_v2()
        assert m.primary_bootstrap_algorithm == "fold-stratified-moving-block-bootstrap-v2"
        assert m.sensitivity_bootstrap_algorithm == "hierarchical-fold-block-bootstrap-v1"
        assert m.sensitivity_bootstrap_seed == m.primary_bootstrap_seed + 1

    def test_wrong_primary_algorithm_is_rejected(self) -> None:
        payload = json.loads(build_methodology_v2().to_json_bytes())
        payload["primary_bootstrap_algorithm"] = "moving-block-bootstrap-v1"
        with pytest.raises(ValueError, match="primary_bootstrap_algorithm is pinned"):
            MethodologyProtocolV2.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_forged_v1_binding_is_rejected(self) -> None:
        payload = json.loads(build_methodology_v2().to_json_bytes())
        payload["base_walk_forward_protocol_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="does not match the frozen v1 protocol"):
            MethodologyProtocolV2.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_schema_versions_match_owning_modules(self) -> None:
        # The methodology's artifact-version pins must equal the authoritative
        # constants so the pin cannot silently drift.
        from eth_research.experiment_registry import REGISTRY_SCHEMA_VERSION_V2

        m = build_methodology_v2()
        assert m.registry_schema_version == REGISTRY_SCHEMA_VERSION_V2
        assert m.results_schema_version == RESULTS_SCHEMA_VERSION_V2 == 2
        assert m.return_evidence_schema_version == RETURN_EVIDENCE_SCHEMA_VERSION == 1
