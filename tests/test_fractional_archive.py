"""The immutable fractional artifact manifest model + bundle digest."""

from __future__ import annotations

import json

import pytest

from eth_research.fractional.archive import (
    FRACTIONAL_MANIFEST_SCHEMA_VERSION,
    ArchiveError,
    FractionalArtifactManifest,
    bundle_sha256,
)
from eth_research.fractional.protocol import EXPERIMENT_FAMILY, RUN_001_EXPERIMENT_ID
from eth_research.fractional.results import FRACTIONAL_REPORT_RELPATH, FRACTIONAL_RESULTS_RELPATH


def _manifest() -> FractionalArtifactManifest:
    return FractionalArtifactManifest(
        manifest_schema_version=FRACTIONAL_MANIFEST_SCHEMA_VERSION,
        experiment_id=RUN_001_EXPERIMENT_ID,
        experiment_family=EXPERIMENT_FAMILY,
        package_version="0.5.0",
        results_path=FRACTIONAL_RESULTS_RELPATH,
        results_sha256="1" * 64,
        report_path=FRACTIONAL_REPORT_RELPATH,
        report_sha256="2" * 64,
        bundle_sha256="3" * 64,
        registered_event_sha256="4" * 64,
        started_event_sha256="5" * 64,
    )


class TestBundle:
    def test_bundle_is_hash_of_concatenation(self) -> None:
        from eth_research.data.provenance import sha256_bytes

        assert bundle_sha256(b"aa", b"bb") == sha256_bytes(b"aabb")

    def test_bundle_is_order_sensitive(self) -> None:
        assert bundle_sha256(b"a", b"bb") != bundle_sha256(b"aa", b"b")


class TestManifest:
    def test_round_trips_byte_stably(self) -> None:
        manifest = _manifest()
        raw = manifest.to_json_bytes()
        assert FractionalArtifactManifest.from_json_bytes(raw).to_json_bytes() == raw
        assert FractionalArtifactManifest.from_json_bytes(raw) == manifest

    def test_is_canonical(self) -> None:
        raw = _manifest().to_json_bytes()
        assert raw.endswith(b"\n")
        reencoded = (json.dumps(json.loads(raw), sort_keys=True, indent=2) + "\n").encode("utf-8")
        assert raw == reencoded

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(_manifest().to_json_bytes())
        payload["surprise"] = 1
        with pytest.raises(ArchiveError, match="keys do not match"):
            FractionalArtifactManifest.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_wrong_family_is_rejected(self) -> None:
        payload = json.loads(_manifest().to_json_bytes())
        payload["experiment_family"] = "other-family"
        with pytest.raises(ArchiveError, match="experiment family"):
            FractionalArtifactManifest.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_foreign_results_path_is_rejected(self) -> None:
        payload = json.loads(_manifest().to_json_bytes())
        payload["results_path"] = "research/m3b/somewhere_else.json"
        with pytest.raises(ArchiveError, match="results_path must be"):
            FractionalArtifactManifest.from_json_bytes(json.dumps(payload).encode("utf-8"))

    def test_non_hex_digest_is_rejected(self) -> None:
        payload = json.loads(_manifest().to_json_bytes())
        payload["bundle_sha256"] = "not-a-hash"
        with pytest.raises(Exception, match="bundle_sha256"):
            FractionalArtifactManifest.from_json_bytes(json.dumps(payload).encode("utf-8"))
