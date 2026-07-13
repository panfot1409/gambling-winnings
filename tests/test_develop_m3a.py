"""M3A experiment publisher: deterministic generation and committed reproduction."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import eth_research
from eth_research.develop_m3a import (
    EXPERIMENT_FAMILY_ID,
    REPORT_RELPATH,
    RESULTS_RELPATH,
    _committed_provenance,
    generate,
    registered_commit_from_history,
    result_bundle_sha256,
)
from eth_research.development_evaluation import load_development_results_payload

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "research/m2b/raw/coinbase" / ATTEMPT).is_dir(),
    reason="real committed acquisition not present",
)


class TestGenerate:
    # Phase 13 discipline: real research-train data is evaluated only to
    # reproduce the *registered* experiment, so both tests use the committed
    # experiment's own provenance rather than fabricated `"a"*40`/`"b"*40`
    # commits, and never publish a new real-data artifact.
    def _committed(self) -> tuple[bytes, str]:
        execution, registered, family = _committed_provenance(REPO_ROOT)
        return generate(
            REPO_ROOT,
            execution_code_commit_sha=execution,
            registered_code_commit_sha=registered,
            experiment_family_id=family,
        )

    def test_generate_is_deterministic(self) -> None:
        assert self._committed() == self._committed()

    def test_report_has_all_sections(self) -> None:
        _, report = self._committed()
        sections = re.findall(r"^## (\d+)\.", report, re.MULTILINE)
        assert sections == [str(i) for i in range(1, 22)]

    def test_family_default_is_pinned(self) -> None:
        assert EXPERIMENT_FAMILY_ID == "m3a-fixed-baseline-comparison-v1"


class TestBundleHash:
    def test_bundle_hash_is_content_addressed(self) -> None:
        a = result_bundle_sha256(b"{}", "report")
        assert a == result_bundle_sha256(b"{}", "report")
        assert a != result_bundle_sha256(b"{}", "other")
        assert a != result_bundle_sha256(b'{"x":1}', "report")


class TestCommittedArtifacts:
    """Once the real experiment is published, the committed files must
    reproduce byte-for-byte from the provenance recorded inside them."""

    def test_committed_results_reproduce(self) -> None:
        results_path = REPO_ROOT / RESULTS_RELPATH
        report_path = REPO_ROOT / REPORT_RELPATH
        if not results_path.exists():
            pytest.skip("development results not yet published")
        payload = load_development_results_payload(results_path)
        results_bytes, report_md = generate(
            REPO_ROOT,
            execution_code_commit_sha=payload["execution_code_commit_sha"],
            registered_code_commit_sha=payload["registered_code_commit_sha"],
            experiment_family_id=payload["experiment_family_id"],
        )
        assert results_bytes == results_path.read_bytes()
        assert report_md == report_path.read_text("utf-8")

    def test_registered_label_matches_protocol_freeze(self) -> None:
        results_path = REPO_ROOT / RESULTS_RELPATH
        if not results_path.exists():
            pytest.skip("development results not yet published")
        payload = load_development_results_payload(results_path)
        try:
            history = registered_commit_from_history(REPO_ROOT)
        except (RuntimeError, OSError):  # pragma: no cover - shallow CI checkout
            pytest.skip("full git history not available")
        assert payload["registered_code_commit_sha"] == history
