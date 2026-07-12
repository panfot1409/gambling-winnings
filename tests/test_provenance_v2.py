"""Provenance-v2 graph: the receipt is now authenticated (P1)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.data.acquisition_plan import load_acquisition_receipt
from eth_research.provenance_v2 import (
    ProvenanceV2,
    ProvenanceV2Error,
    build_provenance_v2,
    load_provenance_v2,
    raw_bundle_fingerprint,
    verify_provenance_graph,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ANCHOR = REPO_ROOT / "research/m2b/provenance_v2.json"
ATTEMPT_REL = "research/m2b/raw/coinbase/coinbase-eth-usd-001"

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / ATTEMPT_REL).is_dir(), reason="canonical acquisition not present"
)


@pytest.fixture
def cloned_root(tmp_path: Path) -> Path:
    """A tamperable copy of the committed research/ tree."""
    shutil.copytree(REPO_ROOT / "research", tmp_path / "research")
    return tmp_path


def _tamper_json(path: Path, **changes: object) -> None:
    payload = json.loads(path.read_bytes())
    payload.update(changes)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class TestGraphAnchor:
    def test_committed_anchor_matches_build(self) -> None:
        assert ANCHOR.read_bytes() == build_provenance_v2(REPO_ROOT).to_json_bytes()

    def test_round_trips_byte_stably(self) -> None:
        anchor = load_provenance_v2(ANCHOR)
        assert anchor.to_json_bytes() == ANCHOR.read_bytes()

    def test_full_graph_verifies(self) -> None:
        result = verify_provenance_graph(REPO_ROOT)
        assert result.ok, result.errors
        assert len(result.checks) >= 20

    def test_unknown_key_is_rejected(self) -> None:
        payload = json.loads(ANCHOR.read_bytes())
        payload["extra"] = 1
        with pytest.raises(ValueError, match=r"unknown=\['extra'\]"):
            ProvenanceV2.from_json_bytes(json.dumps(payload).encode("utf-8"))


class TestForgedReceiptIsCaught:
    """The reproduced FORGED_RECEIPT_ACCEPTED exploit: forging any receipt
    field now breaks the anchor, because the anchor pins the receipt SHA."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("workflow_run_id", "00000000000"),
            ("source_commit", "0" * 40),
            ("curl_version", "curl 9.9.9"),
            ("runner", "attacker-laptop"),
        ],
    )
    def test_forged_receipt_metadata_breaks_the_graph(
        self, cloned_root: Path, field: str, value: str
    ) -> None:
        receipt_path = cloned_root / ATTEMPT_REL / "acquisition_receipt.json"
        _tamper_json(receipt_path, **{field: value})
        result = verify_provenance_graph(cloned_root)
        assert not result.ok
        assert any("acquisition_receipt_sha256" in err for err in result.errors)

    def test_forged_byte_length_is_caught_by_the_raw_bundle(self, cloned_root: Path) -> None:
        receipt_path = cloned_root / ATTEMPT_REL / "acquisition_receipt.json"
        payload = json.loads(receipt_path.read_bytes())
        payload["responses"][0]["byte_length"] = payload["responses"][0]["byte_length"] + 1
        receipt_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        # The receipt SHA changes (anchor mismatch) AND the raw-bundle re-check
        # would reject the wrong length directly.
        receipt = load_acquisition_receipt(receipt_path)
        with pytest.raises(ProvenanceV2Error, match="byte_length"):
            raw_bundle_fingerprint(receipt, cloned_root / ATTEMPT_REL)


class TestCrossChecks:
    @pytest.mark.parametrize(
        ("relpath", "changes", "expected"),
        [
            ("research/m2b/dataset_lock.json", {"package_version": "9.9.9"}, "version_chain"),
            ("research/m2b/protocol.json", {"package_version": "9.9.9"}, "version_chain"),
        ],
    )
    def test_tampering_an_artifact_breaks_the_graph(
        self, cloned_root: Path, relpath: str, changes: dict[str, object], expected: str
    ) -> None:
        _tamper_json(cloned_root / relpath, **changes)
        result = verify_provenance_graph(cloned_root)
        assert not result.ok
        # The bytes changed (anchor mismatch) and, for a version bump, the chain.
        joined = " ".join(result.errors)
        assert "sha256" in joined or expected in joined

    def test_raise_for_status_raises_on_failure(self, cloned_root: Path) -> None:
        _tamper_json(cloned_root / "research/m2b/dataset_lock.json", package_version="9.9.9")
        with pytest.raises(ProvenanceV2Error, match="provenance graph verification failed"):
            verify_provenance_graph(cloned_root).raise_for_status()


class TestRawBundleFingerprint:
    def test_is_deterministic(self) -> None:
        receipt = load_acquisition_receipt(REPO_ROOT / ATTEMPT_REL / "acquisition_receipt.json")
        first = raw_bundle_fingerprint(receipt, REPO_ROOT / ATTEMPT_REL)
        second = raw_bundle_fingerprint(receipt, REPO_ROOT / ATTEMPT_REL)
        assert first == second
        assert first.startswith("sha256:")
