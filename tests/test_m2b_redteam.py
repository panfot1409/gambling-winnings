"""Active red-team on the real acquisition -> freeze -> replay boundary.

Beyond the per-component failure tests, these attack the *chain*: the frozen
committed lock and evidence must anchor integrity even when raw bytes and
their receipt are tampered together, and the replay must never touch the
ledger.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.data.coinbase import AcquisitionError
from eth_research.data.provenance import sha256_bytes
from eth_research.replay_m2b import check_against_committed, reconstruct_dataset

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"
RAW_REL = f"research/m2b/raw/coinbase/{ATTEMPT}"

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / RAW_REL).is_dir(), reason="real committed acquisition not present"
)


def _clone_frozen(tmp_path: Path) -> Path:
    """Copy the committed plan + raw + frozen metadata into a temp repo."""
    repo = tmp_path / "repo"
    m2b = repo / "research" / "m2b"
    (m2b / "raw" / "coinbase").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / RAW_REL, repo / RAW_REL)
    for name in (
        "acquisition_request_plan.json",
        "acquisition_evidence.json",
        "dataset_lock.json",
    ):
        (m2b / name).write_bytes((REPO_ROOT / "research" / "m2b" / name).read_bytes())
    return repo


class TestChainTamper:
    def test_joint_raw_and_receipt_tamper_is_caught_by_committed_lock(self, tmp_path: Path) -> None:
        # Mutate a real candle AND update the receipt SHA so the per-file hash
        # check passes; the reconstruction is internally consistent but its
        # fingerprint/evidence no longer match the committed frozen metadata.
        repo = _clone_frozen(tmp_path)
        raw_dir = repo / RAW_REL
        chunk = sorted(raw_dir.glob("coinbase-eth-usd-1d_*.json"))[0]
        original = chunk.read_bytes()
        # flip a digit in the body so a candle value changes
        idx = original.find(b"1")
        assert idx != -1
        tampered = original[:idx] + b"9" + original[idx + 1 :]
        assert tampered != original
        chunk.write_bytes(tampered)

        receipt_path = raw_dir / "acquisition_receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        for response in receipt["responses"]:
            if response["filename"] == chunk.name:
                response["sha256"] = sha256_bytes(tampered)
                response["byte_length"] = len(tampered)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

        # The reconstruction may succeed (internally consistent) or fail on the
        # continuity/window checks; either way the committed lock must reject it.
        try:
            result = reconstruct_dataset(repo, ATTEMPT, tmp_path / "work")
        except AcquisitionError:
            return  # tamper broke daily continuity — already refused
        checks = check_against_committed(repo, result)
        assert not checks["evidence_bytes_match"]
        assert not checks["lock_content_fingerprint"]

    def test_replay_does_not_touch_the_committed_ledger(self, tmp_path: Path) -> None:
        ledger = REPO_ROOT / "research" / "m2b" / "test_evaluations.jsonl"
        before = ledger.read_bytes()
        reconstruct_dataset(REPO_ROOT, ATTEMPT, tmp_path / "work")
        assert ledger.read_bytes() == before == b""

    def test_reversed_chunk_is_rejected(self, tmp_path: Path) -> None:
        # A response whose rows are neither strictly ascending nor descending
        # (shuffled) must be refused, never reordered.
        repo = _clone_frozen(tmp_path)
        raw_dir = repo / RAW_REL
        chunk = sorted(raw_dir.glob("coinbase-eth-usd-1d_*.json"))[0]
        rows = json.loads(chunk.read_bytes())
        assert len(rows) > 3
        rows[0], rows[2] = rows[2], rows[0]  # shuffle -> not monotonic
        chunk.write_bytes(json.dumps(rows).encode("ascii"))
        receipt_path = raw_dir / "acquisition_receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        new = chunk.read_bytes()
        for response in receipt["responses"]:
            if response["filename"] == chunk.name:
                response["sha256"] = sha256_bytes(new)
                response["byte_length"] = len(new)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with pytest.raises(AcquisitionError):
            reconstruct_dataset(repo, ATTEMPT, tmp_path / "work")
