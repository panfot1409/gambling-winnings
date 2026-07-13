"""Offline M2B replay: real-data reproducibility + failure injection.

The happy-path test reconstructs the frozen dataset from the committed raw
bytes and checks it against the committed metadata (the fresh-clone
reproducibility contract). The failure tests copy the committed plan + raw
into a temp repo and corrupt one link at a time.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.data.acquisition_plan import build_acquisition_plan
from eth_research.data.coinbase import AcquisitionError
from eth_research.replay_m2b import (
    check_against_committed,
    reconstruct_dataset,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"
RAW_REL = f"research/m2b/raw/coinbase/{ATTEMPT}"
PLAN_REL = "research/m2b/acquisition_request_plan.json"

_committed_raw = REPO_ROOT / RAW_REL
pytestmark = pytest.mark.skipif(
    not _committed_raw.is_dir(), reason="real committed acquisition not present"
)


def _copy_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / RAW_REL).parent.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / RAW_REL, repo / RAW_REL)
    (repo / "research" / "m2b" / "acquisition_request_plan.json").write_bytes(
        (REPO_ROOT / PLAN_REL).read_bytes()
    )
    return repo


class TestRealReproducibility:
    def test_reconstruct_matches_committed_metadata(self, tmp_path: Path) -> None:
        result = reconstruct_dataset(REPO_ROOT, ATTEMPT, tmp_path / "work")
        assert result.build.manifest.row_count == 3702
        checks = check_against_committed(REPO_ROOT, result)
        assert all(checks.values()), checks

    def test_reconstruction_is_deterministic(self, tmp_path: Path) -> None:
        a = reconstruct_dataset(REPO_ROOT, ATTEMPT, tmp_path / "a")
        b = reconstruct_dataset(REPO_ROOT, ATTEMPT, tmp_path / "b")
        # derived CSV bytes and evidence bytes are byte-identical run to run
        assert a.derived_csv.read_bytes() == b.derived_csv.read_bytes()
        assert a.evidence_bytes == b.evidence_bytes
        assert a.build.manifest.content_fingerprint == b.build.manifest.content_fingerprint


class TestReplayFailureInjection:
    def test_mutated_raw_chunk_is_rejected(self, tmp_path: Path) -> None:
        repo = _copy_repo(tmp_path)
        chunk = next(iter((repo / RAW_REL).glob("coinbase-eth-usd-1d_*.json")))
        chunk.write_bytes(chunk.read_bytes().replace(b"0", b"9", 1))
        with pytest.raises(AcquisitionError, match="does not match the receipt SHA-256"):
            reconstruct_dataset(repo, ATTEMPT, tmp_path / "work")

    def test_missing_raw_body_is_rejected(self, tmp_path: Path) -> None:
        repo = _copy_repo(tmp_path)
        chunk = next(iter((repo / RAW_REL).glob("coinbase-eth-usd-1d_*.json")))
        chunk.unlink()
        with pytest.raises(AcquisitionError, match=r"missing from|does not match"):
            reconstruct_dataset(repo, ATTEMPT, tmp_path / "work")

    def test_receipt_plan_mismatch_is_rejected(self, tmp_path: Path) -> None:
        repo = _copy_repo(tmp_path)
        # overwrite the plan with a different (shorter) one so its SHA no longer
        # matches the committed receipt's plan_sha256
        import pandas as pd

        other = build_acquisition_plan(
            overall_start=pd.Timestamp("2016-05-23", tz="UTC"),
            overall_end=pd.Timestamp("2016-06-01", tz="UTC"),
        )
        (repo / PLAN_REL).write_bytes(other.to_json_bytes())
        with pytest.raises(AcquisitionError, match=r"plan_sha256 .* does not match|no response"):
            reconstruct_dataset(repo, ATTEMPT, tmp_path / "work")
