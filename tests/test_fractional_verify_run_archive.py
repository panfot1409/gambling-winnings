"""The comprehensive M3B run-archive verifier proves the whole closure surface."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import eth_research
from eth_research.fractional.archive_v2 import ArchiveV2Error
from eth_research.fractional.verify_run_archive import (
    M3BRunArchiveError,
    main,
    verify_m3b_run_archive,
)

REPO = Path(eth_research.__file__).resolve().parents[2]
_ARCHIVED_RESULTS = "research/m3b/experiments/run-001/immutable-v2/fractional_results.json"
_GATE_LEDGER = "research/m3a/development_gate_access.jsonl"


def _copy_repo_subset(tmp_path: Path) -> Path:
    shutil.copytree(REPO / "research" / "m3b", tmp_path / "research" / "m3b")
    for ledger in (_GATE_LEDGER, "research/m2b/test_evaluations.jsonl"):
        path = tmp_path / ledger
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    return tmp_path


def test_full_verification_passes_with_24_checks() -> None:
    checks = verify_m3b_run_archive(REPO)
    assert len(checks) == 24
    assert checks[0] == "experiment_id_recognized"
    for expected in (
        "registry_lifecycle_complete",
        "archive_v2_rederives",
        "annotation_chain_intact",
        "report_errata_verified",
        "trace_commitments_present_and_bind_results",
        "no_pending_completion_intent",
        "development_gate_ledger_byte_empty",
        "final_holdout_ledger_byte_empty",
    ):
        assert expected in checks


def test_unknown_experiment_id_is_rejected() -> None:
    with pytest.raises(M3BRunArchiveError, match="only"):
        verify_m3b_run_archive(REPO, "m3b-fractional-execution-risk-v1-run-999")


def test_cli_exits_zero() -> None:
    assert main(["--repo-root", str(REPO)]) == 0


def test_nonempty_sealed_ledger_fails_verification(tmp_path: Path) -> None:
    root = _copy_repo_subset(tmp_path)
    (root / _GATE_LEDGER).write_bytes(b"tampered\n")
    with pytest.raises(M3BRunArchiveError, match="byte-empty"):
        verify_m3b_run_archive(root)


def test_tampered_archive_copy_fails_verification(tmp_path: Path) -> None:
    root = _copy_repo_subset(tmp_path)
    victim = root / _ARCHIVED_RESULTS
    victim.write_bytes(victim.read_bytes() + b" ")
    with pytest.raises(ArchiveV2Error):
        verify_m3b_run_archive(root)


@pytest.mark.slow
def test_deep_verification_adds_the_replay_check() -> None:
    checks = verify_m3b_run_archive(REPO, deep=True)
    assert len(checks) == 25
    assert "trace_commitments_replay_byte_for_byte" in checks
