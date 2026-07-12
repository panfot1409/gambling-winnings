"""Read-only holdout-readiness preflight: safe, non-mutating, test-free (P6)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import eth_research
from eth_research import evaluation, test_readiness
from eth_research.backtest import run_backtest as real_run_backtest
from eth_research.replay_m2b import reconstruct_dataset

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
ATTEMPT = "coinbase-eth-usd-001"
TEST_FIRST_OPEN = pd.Timestamp("2024-07-01", tz="UTC")

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "research/m2b/raw/coinbase" / ATTEMPT).is_dir(),
    reason="real committed acquisition not present",
)


@pytest.fixture(scope="module")
def real_manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    work = tmp_path_factory.mktemp("m2b_readiness")
    return reconstruct_dataset(REPO_ROOT, ATTEMPT, work).build.manifest_path


def _tracked_tree_digest() -> str:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


class TestReadinessFacts:
    def test_reports_safe_readiness_facts(self, real_manifest: Path) -> None:
        report = test_readiness.preflight_authorized_benchmark(REPO_ROOT, real_manifest)
        assert report.head_sha
        assert report.package_version == eth_research.__version__
        assert report.provenance_graph_ok
        assert report.ledger_byte_count == 0
        assert report.ledger_event_count == 0
        assert (
            report.ledger_sha256
            == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        assert report.test_row_count == 741
        assert report.test_first_open_time == "2024-07-01T00:00:00+00:00"
        assert report.test_content_fingerprint is not None
        assert report.test_content_fingerprint.startswith("sha256:")

    def test_output_carries_no_test_performance(self, real_manifest: Path) -> None:
        report = test_readiness.preflight_authorized_benchmark(REPO_ROOT, real_manifest)
        blob = report.to_json_bytes().decode("utf-8").lower()
        for forbidden in ("total_return", "cagr", "sharpe", "sortino", "equity", "pnl", "signal"):
            assert forbidden not in blob


class TestReadOnlyAndTestFree:
    def test_leaves_ledger_and_tree_byte_identical(self, real_manifest: Path) -> None:
        ledger = REPO_ROOT / "research/m2b/test_evaluations.jsonl"
        ledger_before = ledger.read_bytes()
        tree_before = _tracked_tree_digest()
        test_readiness.preflight_authorized_benchmark(REPO_ROOT, real_manifest)
        assert ledger.read_bytes() == ledger_before == b""
        assert _tracked_tree_digest() == tree_before

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
        # Every bar handed to the engine is strictly before the first test open.
        assert max(seen) < TEST_FIRST_OPEN


class TestCli:
    def test_cli_emits_deterministic_ready_json(self, real_manifest: Path) -> None:
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
        # ready is 0, not-ready is 1; either way stdout is valid deterministic JSON.
        assert result.returncode in (0, 1)
        payload = json.loads(result.stdout)
        assert payload["ledger_event_count"] == 0
        assert payload["test_row_count"] == 741
