"""The committed run-001 legacy completion audit re-derives and stays honest."""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research
from eth_research.fractional.legacy_completion_audit import (
    FRACTIONAL_LEGACY_AUDIT_RELPATH,
    LegacyCompletionAuditError,
    build_legacy_completion_audit,
    render_legacy_completion_audit,
    verify_legacy_completion_audit,
)
from eth_research.fractional.protocol import RUN_001_EXPERIMENT_ID
from eth_research.fractional.registry import M3B_REGISTRY_RELPATH, read_registry

REPO = Path(eth_research.__file__).resolve().parents[2]


def test_committed_audit_verifies() -> None:
    checks = verify_legacy_completion_audit(REPO)
    assert checks == (
        "legacy_audit_canonical",
        "legacy_audit_rederives",
        "run001_has_no_completion_intent",
        "published_run_replays",
    )


def test_committed_bytes_match_rendered() -> None:
    committed = (REPO / FRACTIONAL_LEGACY_AUDIT_RELPATH).read_bytes()
    assert committed == render_legacy_completion_audit(REPO)


def test_recorded_digests_match_the_completed_event() -> None:
    record = build_legacy_completion_audit(REPO)
    completed = [
        e
        for e in read_registry(REPO / M3B_REGISTRY_RELPATH)
        if e.experiment_id == RUN_001_EXPERIMENT_ID
    ][-1]
    assert record["results_json_sha256"] == completed.results_json_sha256
    assert record["report_markdown_sha256"] == completed.report_markdown_sha256
    assert record["result_bundle_sha256"] == completed.result_bundle_sha256
    assert record["completion_intent_present"] is False


def test_missing_audit_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(LegacyCompletionAuditError, match="missing or not a file"):
        verify_legacy_completion_audit(tmp_path)
