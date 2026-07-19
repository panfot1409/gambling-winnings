"""The candidate source freeze binds the frozen candidate set + source before real BTC."""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.v2b import candidate_source_freeze as csf
from eth_research.v2b.candidates import V2B_CANDIDATES

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def test_committed_freeze_reproduces_from_live_source() -> None:
    csf.verify_candidate_source_freeze(REPO_ROOT)
    committed = (REPO_ROOT / csf.CANDIDATE_SOURCE_FREEZE_RELPATH).read_bytes()
    fresh = csf.render_candidate_source_freeze_bytes(csf.build_candidate_source_freeze(REPO_ROOT))
    assert committed == fresh


def test_freeze_binds_exactly_the_two_candidates() -> None:
    freeze = csf.build_candidate_source_freeze(REPO_ROOT)
    assert freeze["candidate_count"] == 2
    ids = [c["candidate_id"] for c in freeze["candidates"]]
    assert ids == [s.candidate_id for s in V2B_CANDIDATES]
    for record, spec in zip(freeze["candidates"], V2B_CANDIDATES, strict=True):
        assert record["identity_fingerprint"] == spec.identity.fingerprint()
        assert record["spec_fingerprint"] == spec.fingerprint()
        assert record["fixed_parameters"] == dict(sorted(spec.fixed_parameters.items()))
    assert freeze["frozen_before_real_btc"] is True


def test_freeze_records_candidate_and_hypothesis_source_hashes() -> None:
    freeze = csf.build_candidate_source_freeze(REPO_ROOT)
    assert set(freeze["frozen_source_sha256"]) == {
        "src/eth_research/v2b/candidates.py",
        "src/eth_research/v2b/multiplicity.py",
        "src/eth_research/v2b/research_memory.py",
    }
    for digest in freeze["frozen_source_sha256"].values():
        assert len(digest) == 64
    assert len(freeze["hypothesis_review_sha256"]) == 64


def test_verify_detects_source_drift(tmp_path: Path) -> None:
    # A clone whose candidate source is mutated after the freeze must fail verification.
    committed = (REPO_ROOT / csf.CANDIDATE_SOURCE_FREEZE_RELPATH).read_bytes()
    clone = tmp_path / "repo"
    (clone / "research/v2b").mkdir(parents=True)
    (clone / "src/eth_research/v2b").mkdir(parents=True)
    (clone / "docs").mkdir()
    (clone / csf.CANDIDATE_SOURCE_FREEZE_RELPATH).write_bytes(committed)
    for rel in (*csf._FROZEN_SOURCE_RELPATHS, csf._HYPOTHESIS_REVIEW_RELPATH):
        (clone / rel).write_bytes((REPO_ROOT / rel).read_bytes())
    # Untouched clone verifies.
    csf.verify_candidate_source_freeze(clone)
    # Mutating a frozen source file breaks the freeze.
    target = clone / "src/eth_research/v2b/candidates.py"
    target.write_bytes(target.read_bytes() + b"\n# post-freeze edit\n")
    with pytest.raises(csf.CandidateSourceFreezeError, match="does not reproduce"):
        csf.verify_candidate_source_freeze(clone)


def test_read_bytes_refuses_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"x")
    root = tmp_path / "repo"
    (root / "src/eth_research/v2b").mkdir(parents=True)
    link = root / "src/eth_research/v2b/candidates.py"
    link.symlink_to(outside)
    with pytest.raises(csf.CandidateSourceFreezeError, match="symlink"):
        csf._read_bytes(root, "src/eth_research/v2b/candidates.py")
