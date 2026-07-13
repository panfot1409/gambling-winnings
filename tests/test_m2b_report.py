"""Train/validation dossier: reproducibility + proof the test set is untouched."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import eth_research
from eth_research import evaluation, m2b_report
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
    work = tmp_path_factory.mktemp("m2b_dataset")
    result = reconstruct_dataset(REPO_ROOT, ATTEMPT, work)
    return result.build.manifest_path


def _commit() -> str:
    # The recorded provenance commit, read from the committed results (no git
    # history needed, so this works on shallow CI checkouts too).
    return m2b_report.committed_protocol_registration_commit(REPO_ROOT)


class TestReproducibility:
    def test_generated_matches_committed(self, real_manifest: Path) -> None:
        results_bytes, report_md = m2b_report.generate(
            REPO_ROOT, real_manifest, protocol_registration_commit_sha=_commit()
        )
        committed_results = (REPO_ROOT / m2b_report.RESULTS_RELPATH).read_bytes()
        committed_report = (REPO_ROOT / m2b_report.REPORT_RELPATH).read_text(encoding="utf-8")
        assert results_bytes == committed_results
        assert report_md == committed_report

    def test_generation_is_deterministic(self, real_manifest: Path) -> None:
        commit = _commit()
        a = m2b_report.generate(REPO_ROOT, real_manifest, protocol_registration_commit_sha=commit)
        b = m2b_report.generate(REPO_ROOT, real_manifest, protocol_registration_commit_sha=commit)
        assert a == b

    def test_results_round_trip(self, real_manifest: Path) -> None:
        from eth_research.protocol import BenchmarkResults

        results_bytes, _ = m2b_report.generate(
            REPO_ROOT, real_manifest, protocol_registration_commit_sha=_commit()
        )
        assert BenchmarkResults.from_json_bytes(results_bytes).to_json_bytes() == results_bytes


class TestTestSetIsUntouched:
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
        commit = "0" * 40
        m2b_report.build_results(REPO_ROOT, real_manifest, protocol_registration_commit_sha=commit)
        assert seen, "the spy must have observed backtest calls"
        # every bar (data or warm-up context) handed to the engine is strictly
        # before the first test open — the test segment never reached a strategy
        assert max(seen) < TEST_FIRST_OPEN

    def test_report_reports_no_test_performance(self, real_manifest: Path) -> None:
        _, report_md = m2b_report.generate(
            REPO_ROOT, real_manifest, protocol_registration_commit_sha=_commit()
        )
        assert "has **not** been evaluated" in report_md
        # the results table has train and validation rows only, never a test row
        result_rows = [
            line
            for line in report_md.splitlines()
            if line.startswith("| buy_and_hold |") or line.startswith("| sma_20_50 |")
        ]
        assert result_rows
        assert all("| test |" not in row for row in result_rows)

    def test_ledger_untouched_by_generation(self, real_manifest: Path) -> None:
        ledger = REPO_ROOT / "research/m2b/test_evaluations.jsonl"
        before = ledger.read_bytes()
        m2b_report.build_results(
            REPO_ROOT, real_manifest, protocol_registration_commit_sha="0" * 40
        )
        assert ledger.read_bytes() == before == b""
