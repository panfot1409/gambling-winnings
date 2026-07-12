"""Readiness over the shared gate: honest split states, read-only, test-free."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import eth_research
from conftest import GitPipeline
from eth_research import evaluation, test_readiness
from eth_research.backtest import run_backtest as real_run_backtest
from eth_research.gitcheck import tracked_tree_is_clean
from eth_research.replay_m2b import reconstruct_dataset

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"
TEST_FIRST_OPEN = pd.Timestamp("2024-07-01", tz="UTC")

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "research/m2b/raw/coinbase" / ATTEMPT).is_dir(),
    reason="real committed acquisition not present",
)

requires_clean_tree = pytest.mark.skipif(
    not tracked_tree_is_clean(REPO_ROOT),
    reason="the real-repo readiness assertions need a clean committed tree",
)


@pytest.fixture(scope="module")
def real_manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    work = tmp_path_factory.mktemp("m2b_readiness")
    return reconstruct_dataset(REPO_ROOT, ATTEMPT, work).build.manifest_path


def _synthetic_report(gp: GitPipeline) -> test_readiness.PreflightReport:
    # The fixture repo carries its own package-source copy; point the shared
    # preparation at it exactly as prepare_git does for production tests.
    from unittest import mock

    with mock.patch.object(
        test_readiness, "_running_package_root", return_value=gp.package_source_root
    ):
        return test_readiness.preflight_authorized_benchmark(
            gp.repo_root,
            gp.manifest_path,
            gp.output_dir,
            raw_chunk_dir=gp.raw_chunk_dir,
            derived_csv=gp.derived_csv,
        )


class TestRealRepoStates:
    """The honest current state: integrity-ready, fresh, and NOT test-ready."""

    @requires_clean_tree
    def test_reports_the_honest_rejected_state(self, real_manifest: Path) -> None:
        report = test_readiness.preflight_authorized_benchmark(REPO_ROOT, real_manifest)
        assert report.integrity_ready is True
        assert report.integrity_failure is None
        assert report.dossier_verified is True
        assert report.holdout_fresh is True
        assert report.promotion_decision == "rejected_for_test_promotion"
        assert report.promotion_eligible is False
        assert report.authorized_test_ready is False
        assert report.train_validation_reproducible is True
        assert report.ledger_byte_count == 0
        assert report.ledger_event_count == 0
        assert (
            report.ledger_sha256
            == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        assert report.test_row_count == 741
        assert report.test_first_open_time == "2024-07-01T00:00:00+00:00"

    @requires_clean_tree
    def test_output_carries_no_test_performance(self, real_manifest: Path) -> None:
        report = test_readiness.preflight_authorized_benchmark(REPO_ROOT, real_manifest)
        blob = report.to_json_bytes().decode("utf-8").lower()
        for forbidden in ("total_return", "cagr", "sharpe", "sortino", "equity", "pnl", "signal"):
            assert forbidden not in blob


class TestSyntheticStates:
    def test_eligible_fixture_is_authorized_test_ready(self, git_pipeline: GitPipeline) -> None:
        report = _synthetic_report(git_pipeline)
        assert report.integrity_ready is True, report.integrity_failure
        assert report.promotion_decision == "eligible_for_test_promotion"
        assert report.promotion_eligible is True
        assert report.authorized_test_ready is True

    def test_rejected_fixture_is_integrity_ready_but_not_test_ready(
        self, rejected_git_pipeline: GitPipeline
    ) -> None:
        report = _synthetic_report(rejected_git_pipeline)
        assert report.integrity_ready is True, report.integrity_failure
        assert report.holdout_fresh is True
        assert report.promotion_decision == "rejected_for_test_promotion"
        assert report.promotion_eligible is False
        assert report.authorized_test_ready is False

    def test_integrity_failure_is_reported_not_raised(self, git_pipeline: GitPipeline) -> None:
        # Tamper a committed artifact: readiness must degrade to an honest
        # integrity_ready=False report, never a crash.
        anchor = git_pipeline.repo_root / "research/m2b/frozen_dossier.json"
        anchor.write_bytes(anchor.read_bytes().replace(b"sha256:", b"sha256:", 1) + b"\n")
        report = _synthetic_report(git_pipeline)
        assert report.integrity_ready is False
        assert report.integrity_failure is not None
        assert report.authorized_test_ready is False


class TestReadOnlyAndTestFree:
    @requires_clean_tree
    def test_leaves_ledger_and_tree_byte_identical(self, real_manifest: Path) -> None:
        ledger = REPO_ROOT / "research/m2b/test_evaluations.jsonl"
        ledger_before = ledger.read_bytes()
        tree_before = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        test_readiness.preflight_authorized_benchmark(REPO_ROOT, real_manifest)
        assert ledger.read_bytes() == ledger_before == b""
        tree_after = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert tree_after == tree_before

    @requires_clean_tree
    def test_no_test_row_reaches_the_engine(
        self, real_manifest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[pd.Timestamp] = []

        def spy(data: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
            seen.append(data.index.max())
            context = kwargs.get("context")
            if context is not None and len(context) > 0:
                seen.append(context.index.max())
            return real_run_backtest(data, *args, **kwargs)

        monkeypatch.setattr(evaluation, "run_backtest", spy)
        test_readiness.preflight_authorized_benchmark(REPO_ROOT, real_manifest)
        assert seen, "the preflight must have exercised the engine on train/validation"
        assert max(seen) < TEST_FIRST_OPEN


class TestCli:
    @requires_clean_tree
    def test_informational_mode_exits_zero_for_the_honest_rejection(
        self, real_manifest: Path
    ) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "eth_research.test_readiness",
                "--repo-root",
                str(REPO_ROOT),
                "--manifest",
                str(real_manifest),
            ],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["promotion_decision"] == "rejected_for_test_promotion"
        assert payload["authorized_test_ready"] is False
        assert payload["ledger_event_count"] == 0
        assert payload["test_row_count"] == 741

    @requires_clean_tree
    def test_require_flag_exits_nonzero_for_the_rejected_candidate(
        self, real_manifest: Path
    ) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "eth_research.test_readiness",
                "--repo-root",
                str(REPO_ROOT),
                "--manifest",
                str(real_manifest),
                "--require-authorized-test-ready",
            ],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["integrity_ready"] is True
        assert payload["authorized_test_ready"] is False
