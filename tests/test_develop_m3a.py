"""M3A experiment publisher: deterministic generation and v1 archive reproduction."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import eth_research
from eth_research.develop_m3a import (
    EXPERIMENT_FAMILY_ID,
    generate,
    registered_commit_from_history,
    result_bundle_sha256,
)
from eth_research.development_evaluation import load_development_results_payload

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"

# develop_m3a is the v1 publisher; it reproduces the v1 experiment run-002
# byte-for-byte. Once run-003 completes, the compatibility alias
# (research/m3a/development_results.json) migrates to schema v2, so these v1
# reproduction checks read run-002's own immutable archive instead of the alias.
# (v2 reproduction is proven by test_replay_m3a_v2 and the e2e orchestrator.)
RUN002_ID = "m3a-fixed-baseline-comparison-v1-run-002"
RUN002_ARCHIVE = REPO_ROOT / "research/m3a/experiments" / RUN002_ID
RUN002_RESULTS = RUN002_ARCHIVE / "development_results.json"
RUN002_REPORT = RUN002_ARCHIVE / "development_report.md"

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "research/m2b/raw/coinbase" / ATTEMPT).is_dir(),
    reason="real committed acquisition not present",
)


def _run002_provenance() -> tuple[str, str, str]:
    """(execution commit, registered commit, family) from run-002's v1 archive."""
    payload = load_development_results_payload(RUN002_RESULTS)
    return (
        payload["execution_code_commit_sha"],
        payload["registered_code_commit_sha"],
        payload["experiment_family_id"],
    )


class TestGenerate:
    # Phase 13 discipline: real research-train data is evaluated only to
    # reproduce the *registered* experiment, so both tests use the committed
    # experiment's own provenance rather than fabricated `"a"*40`/`"b"*40`
    # commits, and never publish a new real-data artifact.
    def _committed(self) -> tuple[bytes, str]:
        execution, registered, family = _run002_provenance()
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
    """The committed v1 experiment (run-002) reproduces byte-for-byte from the
    provenance recorded inside its own immutable archive."""

    def test_committed_results_reproduce(self) -> None:
        payload = load_development_results_payload(RUN002_RESULTS)
        # Reproducing the committed v1 experiment binds the version it recorded,
        # so a later package bump leaves run-002's bytes byte-identical.
        results_bytes, report_md = generate(
            REPO_ROOT,
            execution_code_commit_sha=payload["execution_code_commit_sha"],
            registered_code_commit_sha=payload["registered_code_commit_sha"],
            experiment_family_id=payload["experiment_family_id"],
            package_version=payload["package_version"],
        )
        assert results_bytes == RUN002_RESULTS.read_bytes()
        assert report_md == RUN002_REPORT.read_text("utf-8")

    def test_registered_label_matches_protocol_freeze(self) -> None:
        payload = load_development_results_payload(RUN002_RESULTS)
        try:
            history = registered_commit_from_history(REPO_ROOT)
        except (RuntimeError, OSError):  # pragma: no cover - shallow CI checkout
            pytest.skip("full git history not available")
        assert payload["registered_code_commit_sha"] == history
