"""Benchmark evaluator: reconciliation, test discipline, reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import eth_research
import eth_research._atomic
from conftest import CoinbasePipeline, build_coinbase_pipeline
from eth_research import evaluation
from eth_research.backtest import run_backtest as real_run_backtest
from eth_research.data.builder import LoadedDataset, load_canonical_dataset
from eth_research.data.lock import DatasetLock, DatasetLockError, build_dataset_lock
from eth_research.data.provenance import sha256_bytes
from eth_research.evaluation import (
    EVALUATION_CONFIRM_TOKEN,
    EvaluationError,
    OneTimeTestAuthorization,
    build_benchmark_results,
    evaluate_train_validation,
    publish_benchmark_reports,
    render_benchmark_markdown,
    run_authorized_benchmark,
    split_boundaries,
)
from eth_research.ledger import LedgerEvent, append_event, read_ledger
from eth_research.protocol import BenchmarkProtocol, build_benchmark_protocol

DAY = pd.Timedelta(days=1)
START = pd.Timestamp("2024-01-01", tz="UTC")
T0 = pd.Timestamp("2026-07-11T20:00:00+00:00")


def make_lock(pipeline: CoinbasePipeline) -> DatasetLock:
    return build_dataset_lock(
        pipeline.build.manifest,
        manifest_sha256=pipeline.manifest_sha256,
        acquisition_evidence_sha256=pipeline.evidence_sha256,
    )


def make_protocol(pipeline: CoinbasePipeline) -> BenchmarkProtocol:
    return build_benchmark_protocol(make_lock(pipeline), package_version=eth_research.__version__)


def load_dataset(pipeline: CoinbasePipeline) -> LoadedDataset:
    return load_canonical_dataset(pipeline.build.manifest_path)


def make_authorization(evaluation_id: str = "m2b-synthetic-eval-001") -> OneTimeTestAuthorization:
    return OneTimeTestAuthorization(
        evaluation_id=evaluation_id,
        reason="synthetic fixture end-to-end exercise of the guarded path",
        code_commit_sha="c" * 40,
        confirm_token=EVALUATION_CONFIRM_TOKEN,
    )


def make_clock() -> Any:
    state = {"n": 0}

    def tick() -> pd.Timestamp:
        state["n"] += 1
        return T0 + pd.Timedelta(minutes=state["n"])

    return tick


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    path = tmp_path / "test_evaluations.jsonl"
    path.write_bytes(b"")
    return path


class TestTrainValidation:
    def test_returns_four_canonical_segments(self, coinbase_pipeline: CoinbasePipeline) -> None:
        segments = evaluate_train_validation(
            load_dataset(coinbase_pipeline), make_protocol(coinbase_pipeline)
        )
        assert [(entry.strategy, entry.segment) for entry in segments] == [
            ("buy_and_hold", "train"),
            ("buy_and_hold", "validation"),
            ("sma_20_50", "train"),
            ("sma_20_50", "validation"),
        ]
        assert [entry.context_bars for entry in segments] == [0, 0, 0, 50]

    def test_is_deterministic_across_repeated_runs(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        dataset = load_dataset(coinbase_pipeline)
        protocol = make_protocol(coinbase_pipeline)
        assert evaluate_train_validation(dataset, protocol) == evaluate_train_validation(
            dataset, protocol
        )

    def test_buy_and_hold_train_matches_hand_computed_accounting(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        dataset = load_dataset(coinbase_pipeline)
        protocol = make_protocol(coinbase_pipeline)
        segments = evaluate_train_validation(dataset, protocol)
        bnh_train = segments[0]
        train = dataset.frame.iloc[:72]
        open_0 = float(train["open"].iloc[0])
        close_t = float(train["close"].iloc[-1])
        # Recompute the engine's arithmetic step by step with the pinned costs.
        fill_price = open_0 * (1.0 + 0.0005)
        traded = 10_000.0 / (fill_price * (1.0 + 0.001))
        gross = traded * fill_price
        fee = gross * 0.001
        cash_after = 10_000.0 - gross - fee
        expected_terminal = cash_after + traded * close_t
        assert bnh_train.terminal_equity == expected_terminal
        assert bnh_train.num_fills == 1
        assert bnh_train.total_traded_notional == gross
        assert bnh_train.turnover == gross / 10_000.0
        expected_liquidation = cash_after + traded * close_t * (1.0 - 0.0005) * (1.0 - 0.001)
        assert bnh_train.terminal_liquidation_equity == expected_liquidation

    def test_split_boundaries_are_exact(self, coinbase_pipeline: CoinbasePipeline) -> None:
        boundaries = split_boundaries(
            load_dataset(coinbase_pipeline), make_protocol(coinbase_pipeline)
        )
        assert [entry.segment for entry in boundaries] == ["train", "validation", "test"]
        train, validation, test = boundaries
        assert (train.first_open_time, train.last_open_time, train.n_bars) == (
            START,
            START + 71 * DAY,
            72,
        )
        assert (validation.first_open_time, validation.last_open_time, validation.n_bars) == (
            START + 72 * DAY,
            START + 95 * DAY,
            24,
        )
        assert (test.first_open_time, test.last_open_time, test.n_bars) == (
            START + 96 * DAY,
            START + 119 * DAY,
            24,
        )

    def test_never_backtests_test_rows(
        self, coinbase_pipeline: CoinbasePipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dataset = load_dataset(coinbase_pipeline)
        protocol = make_protocol(coinbase_pipeline)
        test_first_open = START + 96 * DAY
        seen: list[pd.Timestamp] = []

        def spy(data: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
            seen.append(data.index.max())
            context = kwargs.get("context")
            if context is not None and len(context) > 0:
                seen.append(context.index.max())
            return real_run_backtest(data, *args, **kwargs)

        monkeypatch.setattr(evaluation, "run_backtest", spy)
        evaluate_train_validation(dataset, protocol)
        assert seen, "the spy must have observed backtest calls"
        assert max(seen) < test_first_open

    def test_sma_validation_context_is_exactly_the_trailing_train_rows(
        self, coinbase_pipeline: CoinbasePipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dataset = load_dataset(coinbase_pipeline)
        protocol = make_protocol(coinbase_pipeline)
        contexts: list[pd.DataFrame | None] = []

        def spy(data: pd.DataFrame, *args: Any, **kwargs: Any) -> Any:
            contexts.append(kwargs.get("context"))
            return real_run_backtest(data, *args, **kwargs)

        monkeypatch.setattr(evaluation, "run_backtest", spy)
        evaluate_train_validation(dataset, protocol)
        sma_validation_context = contexts[3]
        assert sma_validation_context is not None
        expected = dataset.frame.iloc[72 - 50 : 72].index
        assert sma_validation_context.index.equals(expected)

    def test_prefix_invariance_when_only_test_rows_change(self, tmp_path: Path) -> None:
        # Two datasets identical through validation; prices shift only from
        # row 96 (the first test row) onward.
        base = build_coinbase_pipeline(tmp_path / "base")
        shifted = build_coinbase_pipeline(tmp_path / "shifted", price_shift_from_row=96)
        assert base.build.manifest.content_fingerprint != shifted.build.manifest.content_fingerprint
        base_segments = evaluate_train_validation(load_dataset(base), make_protocol(base))
        shifted_segments = evaluate_train_validation(load_dataset(shifted), make_protocol(shifted))
        assert base_segments == shifted_segments

    def test_dataset_protocol_mismatch_is_refused(self, tmp_path: Path) -> None:
        base = build_coinbase_pipeline(tmp_path / "base")
        other = build_coinbase_pipeline(tmp_path / "other", price_shift_from_row=0)
        with pytest.raises(EvaluationError, match="dataset/protocol mismatch"):
            evaluate_train_validation(load_dataset(base), make_protocol(other))

    def test_result_assembly_refuses_a_foreign_protocol(self, tmp_path: Path) -> None:
        # Red-team: results must never bind one dataset's segments to a
        # protocol registered for a different dataset.
        base = build_coinbase_pipeline(tmp_path / "base")
        other = build_coinbase_pipeline(tmp_path / "other", price_shift_from_row=0)
        dataset = load_dataset(base)
        segments = evaluate_train_validation(dataset, make_protocol(base))
        with pytest.raises(EvaluationError, match="dataset/protocol mismatch"):
            build_benchmark_results(
                dataset,
                make_protocol(other),
                segments,
                pre_registered_commit_sha="c" * 40,
                test_evaluation_id=None,
            )


class TestResultAssemblyAndRendering:
    def test_train_validation_only_results_render_honestly(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        dataset = load_dataset(coinbase_pipeline)
        protocol = make_protocol(coinbase_pipeline)
        segments = evaluate_train_validation(dataset, protocol)
        results = build_benchmark_results(
            dataset,
            protocol,
            segments,
            pre_registered_commit_sha="c" * 40,
            test_evaluation_id=None,
        )
        raw = results.to_json_bytes()
        assert type(results).from_json_bytes(raw).to_json_bytes() == raw
        markdown = render_benchmark_markdown(results)
        assert "has **not** been evaluated" in markdown
        assert "not investment advice" in markdown
        assert "not evidence of future" in markdown

    def test_results_and_markdown_are_deterministic(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        dataset = load_dataset(coinbase_pipeline)
        protocol = make_protocol(coinbase_pipeline)
        segments = evaluate_train_validation(dataset, protocol)
        first = build_benchmark_results(
            dataset,
            protocol,
            segments,
            pre_registered_commit_sha="c" * 40,
            test_evaluation_id=None,
        )
        second = build_benchmark_results(
            dataset,
            protocol,
            segments,
            pre_registered_commit_sha="c" * 40,
            test_evaluation_id=None,
        )
        assert first.to_json_bytes() == second.to_json_bytes()
        assert render_benchmark_markdown(first) == render_benchmark_markdown(second)

    def test_publication_refuses_tampered_markdown(
        self, coinbase_pipeline: CoinbasePipeline, tmp_path: Path
    ) -> None:
        dataset = load_dataset(coinbase_pipeline)
        protocol = make_protocol(coinbase_pipeline)
        segments = evaluate_train_validation(dataset, protocol)
        results = build_benchmark_results(
            dataset,
            protocol,
            segments,
            pre_registered_commit_sha="c" * 40,
            test_evaluation_id=None,
        )
        with pytest.raises(EvaluationError, match="not the rendering of the results model"):
            publish_benchmark_reports(results, "# hand-edited report\n", tmp_path / "reports")


class TestGuardedOneTimeEvaluation:
    def run(
        self,
        pipeline: CoinbasePipeline,
        ledger: Path,
        output_dir: Path,
        authorization: OneTimeTestAuthorization | None,
        **kwargs: Any,
    ) -> Any:
        return run_authorized_benchmark(
            load_dataset(pipeline),
            make_protocol(pipeline),
            lock=make_lock(pipeline),
            manifest_path=pipeline.build.manifest_path,
            acquisition_evidence_path=pipeline.evidence_path,
            ledger_path=ledger,
            output_dir=output_dir,
            authorization=authorization,
            clock=make_clock(),
            **kwargs,
        )

    def test_refused_by_default(
        self, coinbase_pipeline: CoinbasePipeline, ledger_path: Path, tmp_path: Path
    ) -> None:
        with pytest.raises(EvaluationError, match="refused: no authorization"):
            self.run(coinbase_pipeline, ledger_path, tmp_path / "reports", None)
        assert read_ledger(ledger_path) == ()

    def test_wrong_confirm_token_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="confirm_token must be exactly"):
            OneTimeTestAuthorization(
                evaluation_id="m2b-synthetic-eval-001",
                reason="x",
                code_commit_sha="c" * 40,
                confirm_token="yes please",
            )

    def test_happy_path_records_and_publishes(
        self, coinbase_pipeline: CoinbasePipeline, ledger_path: Path, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "reports"
        run = self.run(coinbase_pipeline, ledger_path, output_dir, make_authorization())
        events = read_ledger(ledger_path)
        assert [event.event for event in events] == ["started", "completed"]
        assert events[0].event_time_utc == T0 + pd.Timedelta(minutes=1)
        assert events[1].event_time_utc == T0 + pd.Timedelta(minutes=2)
        assert events[0].test_first_open_time == START + 96 * DAY
        assert events[0].test_last_open_time == START + 119 * DAY
        published = run.results_path.read_bytes()
        assert events[1].result_report_sha256 == sha256_bytes(published)
        assert run.results.to_json_bytes() == published
        assert run.report_path.read_text(encoding="utf-8") == run.markdown
        assert run.results.test_evaluation_id == "m2b-synthetic-eval-001"
        assert len(run.results.segments) == 6
        assert "exactly once" in run.markdown
        assert "m2b-synthetic-eval-001" in run.markdown

    def test_second_run_is_refused_as_consumed(
        self, coinbase_pipeline: CoinbasePipeline, ledger_path: Path, tmp_path: Path
    ) -> None:
        self.run(coinbase_pipeline, ledger_path, tmp_path / "reports", make_authorization())
        with pytest.raises(EvaluationError, match="already consumed"):
            self.run(
                coinbase_pipeline,
                ledger_path,
                tmp_path / "reports2",
                make_authorization("m2b-synthetic-eval-002"),
            )
        assert len(read_ledger(ledger_path)) == 2

    def test_reused_evaluation_id_is_refused(
        self, coinbase_pipeline: CoinbasePipeline, ledger_path: Path, tmp_path: Path
    ) -> None:
        foreign = LedgerEvent(
            ledger_schema_version=1,
            event="started",
            evaluation_id="m2b-synthetic-eval-001",
            dataset_content_fingerprint="sha256:" + "9" * 64,
            dataset_lock_sha256="8" * 64,
            protocol_sha256="7" * 64,
            code_commit_sha="b" * 40,
            test_first_open_time=START,
            test_last_open_time=START + DAY,
            reason="a previous unrelated evaluation",
            event_time_utc=T0,
            result_report_sha256=None,
            failure_description=None,
        )
        append_event(ledger_path, foreign)
        with pytest.raises(EvaluationError, match="already used"):
            self.run(coinbase_pipeline, ledger_path, tmp_path / "reports", make_authorization())
        assert len(read_ledger(ledger_path)) == 1

    def test_crash_during_test_computation_is_consumed_and_recorded(
        self,
        coinbase_pipeline: CoinbasePipeline,
        ledger_path: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        output_dir = tmp_path / "reports"
        real_run_segment = evaluation._run_segment

        def exploding(frame: Any, context: Any, strategy: Any, protocol: Any, segment: str) -> Any:
            if segment == "test":
                raise RuntimeError("simulated engine crash")
            return real_run_segment(frame, context, strategy, protocol, segment)

        monkeypatch.setattr(evaluation, "_run_segment", exploding)
        with pytest.raises(RuntimeError, match="simulated engine crash"):
            self.run(coinbase_pipeline, ledger_path, output_dir, make_authorization())
        events = read_ledger(ledger_path)
        assert [event.event for event in events] == ["started", "failed"]
        assert events[1].failure_description is not None
        assert "simulated engine crash" in events[1].failure_description
        assert not (output_dir / "benchmark_results.json").exists()
        assert not (output_dir / "benchmark_report.md").exists()
        monkeypatch.undo()
        with pytest.raises(EvaluationError, match="already consumed"):
            self.run(
                coinbase_pipeline,
                ledger_path,
                tmp_path / "reports2",
                make_authorization("m2b-synthetic-eval-002"),
            )

    def test_publication_failure_rolls_back_and_is_consumed(
        self,
        coinbase_pipeline: CoinbasePipeline,
        ledger_path: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        output_dir = tmp_path / "reports"
        real_write_atomic = eth_research._atomic.write_atomic

        def failing(path: Path, data: bytes) -> None:
            if path.suffix == ".json":
                raise OSError("disk full")
            real_write_atomic(path, data)

        monkeypatch.setattr(eth_research._atomic, "write_atomic", failing)
        with pytest.raises(EvaluationError, match="rolled back"):
            self.run(coinbase_pipeline, ledger_path, output_dir, make_authorization())
        monkeypatch.undo()
        events = read_ledger(ledger_path)
        assert [event.event for event in events] == ["started", "failed"]
        assert events[1].failure_description is not None
        assert "rolled back" in events[1].failure_description
        assert not (output_dir / "benchmark_results.json").exists()
        assert not (output_dir / "benchmark_report.md").exists()
        assert list(output_dir.glob("*.tmp")) == []

    def test_existing_reports_refuse_before_consuming_the_access(
        self, coinbase_pipeline: CoinbasePipeline, ledger_path: Path, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "reports"
        output_dir.mkdir()
        (output_dir / "benchmark_results.json").write_bytes(b"{}")
        with pytest.raises(EvaluationError, match="refusing to start"):
            self.run(coinbase_pipeline, ledger_path, output_dir, make_authorization())
        assert read_ledger(ledger_path) == ()

    def test_lock_for_a_different_dataset_is_refused_before_consuming(
        self, tmp_path: Path, ledger_path: Path
    ) -> None:
        base = build_coinbase_pipeline(tmp_path / "base")
        other = build_coinbase_pipeline(tmp_path / "other", price_shift_from_row=0)
        with pytest.raises(DatasetLockError, match="mismatch"):
            run_authorized_benchmark(
                load_dataset(base),
                make_protocol(base),
                lock=make_lock(other),
                manifest_path=base.build.manifest_path,
                acquisition_evidence_path=base.evidence_path,
                ledger_path=ledger_path,
                output_dir=tmp_path / "reports",
                authorization=make_authorization(),
                clock=make_clock(),
            )
        assert read_ledger(ledger_path) == ()
