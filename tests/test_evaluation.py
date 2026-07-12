"""Benchmark evaluator: reconciliation, test discipline, reporting."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import eth_research
import eth_research._atomic
from conftest import CoinbasePipeline, build_coinbase_pipeline
from eth_research import evaluation
from eth_research.backtest import run_backtest as real_run_backtest
from eth_research.data.builder import (
    DatasetVerificationError,
    LoadedDataset,
    load_canonical_dataset,
)
from eth_research.data.coinbase import write_acquisition_evidence
from eth_research.data.lock import (
    DatasetLock,
    DatasetLockError,
    build_dataset_lock,
    verify_dataset_lock,
)
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.environment import (
    AUTHORITATIVE_RUNTIME_ROLE,
    ENVIRONMENT_SCHEMA_VERSION,
    RuntimeContract,
    current_runtime_snapshot,
)
from eth_research.evaluation import (
    CANONICAL_LEDGER_RELPATH,
    EVALUATION_CONFIRM_TOKEN,
    EvaluationError,
    OneTimeTestAuthorization,
    build_benchmark_results,
    compute_result_bundle_sha256,
    evaluate_train_validation,
    evaluate_train_validation_from_manifest,
    publish_benchmark_reports,
    render_benchmark_markdown,
    run_authorized_benchmark,
    split_boundaries,
)
from eth_research.ledger import LEDGER_SCHEMA_VERSION, LedgerEvent, append_event, read_ledger
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


def make_authorization(
    evaluation_id: str = "m2b-synthetic-eval-001", *, code_commit_sha: str = "c" * 40
) -> OneTimeTestAuthorization:
    return OneTimeTestAuthorization(
        evaluation_id=evaluation_id,
        reason="synthetic fixture end-to-end exercise of the guarded path",
        code_commit_sha=code_commit_sha,
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


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@dataclass
class GitPipeline:
    """An isolated git repo with committed M2B artifacts and ignored data."""

    repo_root: Path
    manifest_path: Path
    protocol_path: Path
    lock_path: Path
    evidence_path: Path
    ledger_path: Path
    output_dir: Path
    raw_chunk_dir: Path
    derived_csv: Path
    head: str
    protocol: BenchmarkProtocol
    lock: DatasetLock


def make_git_pipeline(root: Path) -> GitPipeline:
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test Researcher")
    (repo / ".gitignore").write_text("data/\nreports/\n", encoding="utf-8")

    pipe = build_coinbase_pipeline(repo / "data")
    research = repo / "research" / "m2b"
    research.mkdir(parents=True)

    evidence_path = research / "acquisition_evidence.json"
    write_acquisition_evidence(pipe.evidence, evidence_path)
    lock = build_dataset_lock(
        pipe.build.manifest,
        manifest_sha256=pipe.manifest_sha256,
        acquisition_evidence_sha256=sha256_file(evidence_path),
    )
    lock_path = research / "dataset_lock.json"
    lock_path.write_bytes(lock.to_json_bytes())
    protocol = build_benchmark_protocol(lock, package_version=eth_research.__version__)
    protocol_path = research / "protocol.json"
    protocol_path.write_bytes(protocol.to_json_bytes())
    # A committed runtime contract so the guarded path can record its SHA in
    # the ledger (the inner path hashes it for provenance; semantic runtime
    # verification is the public wrapper's job, tested separately).
    snap = current_runtime_snapshot()
    contract = RuntimeContract(
        environment_schema_version=ENVIRONMENT_SCHEMA_VERSION,
        runtime_role=AUTHORITATIVE_RUNTIME_ROLE,
        package_version=snap.package_version,
        python_implementation=snap.python_implementation,
        python_version=snap.python_version,
        python_cache_tag=snap.python_cache_tag,
        os_family=snap.os_family,
        machine=snap.machine,
        numpy_version=snap.numpy_version,
        pandas_version=snap.pandas_version,
        pyarrow_version=snap.pyarrow_version,
        uv_lock_sha256="0" * 64,
        pyproject_sha256="0" * 64,
    )
    (research / "runtime_contract.json").write_bytes(contract.to_json_bytes())
    ledger_path = research / "test_evaluations.jsonl"
    ledger_path.write_bytes(b"")

    _git(repo, "add", ".gitignore", "research")
    _git(repo, "commit", "-q", "-m", "pre-register benchmark protocol")
    head = _git(repo, "rev-parse", "HEAD")
    return GitPipeline(
        repo_root=repo,
        manifest_path=pipe.build.manifest_path,
        protocol_path=protocol_path,
        lock_path=lock_path,
        evidence_path=evidence_path,
        ledger_path=ledger_path,
        output_dir=repo / "reports" / "m2b",
        raw_chunk_dir=pipe.chunk_dir,
        derived_csv=pipe.derived_csv,
        head=head,
        protocol=protocol,
        lock=lock,
    )


@pytest.fixture
def git_pipeline(tmp_path: Path) -> GitPipeline:
    return make_git_pipeline(tmp_path)


def run_git(
    gp: GitPipeline,
    authorization: OneTimeTestAuthorization | None,
    **overrides: Any,
) -> Any:
    # Downstream behaviour tests target the inner function directly: the
    # synthetic git_pipeline is not a checkout of the running package, so the
    # public run_authorized_benchmark's package-source binding (C1) would
    # reject it. The source binding has its own dedicated tests, including a
    # genuine real-checkout integration test.
    kwargs: dict[str, Any] = {
        "repo_root": gp.repo_root,
        "manifest_path": gp.manifest_path,
        "protocol_path": gp.protocol_path,
        "lock_path": gp.lock_path,
        "acquisition_evidence_path": gp.evidence_path,
        "output_dir": gp.output_dir,
        "authorization": authorization,
        "raw_chunk_dir": gp.raw_chunk_dir,
        "derived_csv": gp.derived_csv,
        "clock": make_clock(),
    }
    kwargs.update(overrides)
    return evaluation._run_bound_benchmark(**kwargs)


def head_auth(
    gp: GitPipeline, evaluation_id: str = "m2b-synthetic-eval-001"
) -> OneTimeTestAuthorization:
    return make_authorization(evaluation_id, code_commit_sha=gp.head)


class TestGuardedOneTimeEvaluation:
    def test_refused_by_default(self, git_pipeline: GitPipeline) -> None:
        with pytest.raises(EvaluationError, match="refused: no authorization"):
            run_git(git_pipeline, None)
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_wrong_confirm_token_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="confirm_token must be exactly"):
            OneTimeTestAuthorization(
                evaluation_id="m2b-synthetic-eval-001",
                reason="x",
                code_commit_sha="c" * 40,
                confirm_token="yes please",
            )

    def test_happy_path_records_and_publishes(self, git_pipeline: GitPipeline) -> None:
        run = run_git(git_pipeline, head_auth(git_pipeline))
        events = read_ledger(git_pipeline.ledger_path)
        assert [event.event for event in events] == ["started", "completed"]
        assert events[0].test_first_open_time == START + 96 * DAY
        assert events[0].test_last_open_time == START + 119 * DAY
        assert events[0].code_commit_sha == git_pipeline.head
        published = run.results_path.read_bytes()
        report_bytes = run.report_path.read_bytes()
        assert events[1].results_json_sha256 == sha256_bytes(published)
        assert events[1].report_markdown_sha256 == sha256_bytes(report_bytes)
        assert events[1].result_bundle_sha256 == compute_result_bundle_sha256(
            published, report_bytes
        )
        # The holdout identity is recorded on both events and is stable.
        assert events[0].holdout_id == events[1].holdout_id
        assert events[0].test_content_fingerprint.startswith("sha256:")
        assert events[0].test_row_count == 24
        assert run.results.to_json_bytes() == published
        assert run.report_path.read_text(encoding="utf-8") == run.markdown
        assert run.results.test_evaluation_id == "m2b-synthetic-eval-001"
        assert run.results.pre_registered_commit_sha == git_pipeline.head
        assert len(run.results.segments) == 6
        assert "exactly once" in run.markdown

    def test_reused_evaluation_id_is_refused(self, git_pipeline: GitPipeline) -> None:
        # A prior event for a *different* holdout (different instrument and
        # candles) but the same evaluation id: it must not be a holdout
        # conflict, so the refusal is specifically the reused-id guard.
        foreign = LedgerEvent(
            ledger_schema_version=LEDGER_SCHEMA_VERSION,
            event="started",
            evaluation_id="m2b-synthetic-eval-001",
            holdout_id="9" * 64,
            dataset_content_fingerprint="sha256:" + "9" * 64,
            test_content_fingerprint="sha256:" + "8" * 64,
            symbol="BTC-USD",
            venue="OtherVenue",
            candle_interval=DAY,
            test_first_open_time=START,
            test_last_open_time=START + DAY,
            test_row_count=2,
            dataset_lock_sha256="8" * 64,
            protocol_sha256="7" * 64,
            runtime_contract_sha256="6" * 64,
            code_commit_sha="b" * 40,
            reason="a previous unrelated evaluation",
            event_time_utc=T0,
            results_json_sha256=None,
            report_markdown_sha256=None,
            result_bundle_sha256=None,
            failure_description=None,
        )
        # Write into the tracked ledger and re-commit so the tree stays clean.
        append_event(git_pipeline.ledger_path, foreign)
        _git(git_pipeline.repo_root, "add", "research")
        _git(git_pipeline.repo_root, "commit", "-q", "-m", "record prior access")
        new_head = _git(git_pipeline.repo_root, "rev-parse", "HEAD")
        with pytest.raises(EvaluationError, match="already used"):
            run_git(
                git_pipeline,
                head_auth(git_pipeline).__class__(
                    evaluation_id="m2b-synthetic-eval-001",
                    reason="x",
                    code_commit_sha=new_head,
                    confirm_token=EVALUATION_CONFIRM_TOKEN,
                ),
            )
        assert len(read_ledger(git_pipeline.ledger_path)) == 1

    def test_crash_during_test_computation_is_consumed_and_recorded(
        self, git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_run_segment = evaluation._run_segment

        def exploding(frame: Any, context: Any, strategy: Any, protocol: Any, segment: str) -> Any:
            if segment == "test":
                raise RuntimeError("simulated engine crash")
            return real_run_segment(frame, context, strategy, protocol, segment)

        monkeypatch.setattr(evaluation, "_run_segment", exploding)
        with pytest.raises(RuntimeError, match="simulated engine crash"):
            run_git(git_pipeline, head_auth(git_pipeline))
        events = read_ledger(git_pipeline.ledger_path)
        assert [event.event for event in events] == ["started", "failed"]
        assert events[1].failure_description is not None
        assert "simulated engine crash" in events[1].failure_description
        assert not (git_pipeline.output_dir / "benchmark_results.json").exists()

    def test_publication_failure_rolls_back_and_is_consumed(
        self, git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_write_atomic = eth_research._atomic.write_atomic

        def failing(path: Path, data: bytes) -> None:
            if path.suffix == ".json":
                raise OSError("disk full")
            real_write_atomic(path, data)

        monkeypatch.setattr(eth_research._atomic, "write_atomic", failing)
        with pytest.raises(EvaluationError, match="rolled back"):
            run_git(git_pipeline, head_auth(git_pipeline))
        monkeypatch.undo()
        events = read_ledger(git_pipeline.ledger_path)
        assert [event.event for event in events] == ["started", "failed"]
        assert events[1].failure_description is not None
        assert "rolled back" in events[1].failure_description
        assert not (git_pipeline.output_dir / "benchmark_results.json").exists()
        assert list(git_pipeline.output_dir.glob("*.tmp")) == []

    def test_existing_reports_refuse_before_consuming(self, git_pipeline: GitPipeline) -> None:
        git_pipeline.output_dir.mkdir(parents=True)
        (git_pipeline.output_dir / "benchmark_results.json").write_bytes(b"{}")
        with pytest.raises(EvaluationError, match="refusing to start"):
            run_git(git_pipeline, head_auth(git_pipeline))
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_verify_after_publish_catches_corruption_and_consumes(
        self, git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Corrupt the authoritative JSON after publication; the read-back
        # verification must fail and leave the holdout consumed (started+failed).
        real_publish = evaluation.publish_benchmark_reports

        def corrupting(
            results: Any, markdown: str, directory: Any, *, overwrite: bool = False
        ) -> Any:
            results_path, report_path = real_publish(
                results, markdown, directory, overwrite=overwrite
            )
            results_path.write_bytes(results_path.read_bytes() + b" ")
            return results_path, report_path

        monkeypatch.setattr(evaluation, "publish_benchmark_reports", corrupting)
        with pytest.raises(EvaluationError, match="after publication"):
            run_git(git_pipeline, head_auth(git_pipeline))
        events = read_ledger(git_pipeline.ledger_path)
        assert [event.event for event in events] == ["started", "failed"]

    def test_overwrite_never_bypasses_a_consumed_holdout(self, git_pipeline: GitPipeline) -> None:
        run_git(git_pipeline, head_auth(git_pipeline))
        _git(git_pipeline.repo_root, "add", "research")
        _git(git_pipeline.repo_root, "commit", "-q", "-m", "record consumed access")
        new_head = _git(git_pipeline.repo_root, "rev-parse", "HEAD")
        # Even with overwrite=True and a fresh evaluation id, the same holdout
        # is refused before any output is touched.
        with pytest.raises(EvaluationError, match="already consumed"):
            run_git(
                git_pipeline,
                make_authorization("m2b-synthetic-eval-002", code_commit_sha=new_head),
                overwrite=True,
            )


class TestGitRevisionBinding:
    """R3: bind the evaluation to the real, clean, pre-registered revision."""

    def test_forty_zero_sha_is_rejected(self, git_pipeline: GitPipeline) -> None:
        with pytest.raises(EvaluationError, match="not a real commit"):
            run_git(
                git_pipeline,
                head_auth(git_pipeline).__class__(
                    evaluation_id="m2b-synthetic-eval-001",
                    reason="x",
                    code_commit_sha="0" * 40,
                    confirm_token=EVALUATION_CONFIRM_TOKEN,
                ),
            )
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_valid_but_foreign_commit_is_rejected(self, git_pipeline: GitPipeline) -> None:
        # A real commit object that is not HEAD.
        _git(git_pipeline.repo_root, "commit", "-q", "--allow-empty", "-m", "later")
        foreign = _git(git_pipeline.repo_root, "rev-parse", "HEAD")
        _git(git_pipeline.repo_root, "reset", "--hard", "-q", git_pipeline.head)
        assert foreign != git_pipeline.head
        with pytest.raises(EvaluationError, match="not the repository HEAD"):
            run_git(git_pipeline, make_authorization(code_commit_sha=foreign))
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_dirty_tracked_source_is_rejected(self, git_pipeline: GitPipeline) -> None:
        # Modify a tracked file in the working tree.
        git_pipeline.lock_path.write_bytes(git_pipeline.lock_path.read_bytes() + b"\n")
        with pytest.raises(EvaluationError, match="tracked working tree is not clean"):
            run_git(git_pipeline, head_auth(git_pipeline))
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_uncommitted_alternate_protocol_is_rejected(self, git_pipeline: GitPipeline) -> None:
        # A protocol file that is not committed at HEAD (untracked path).
        alt = git_pipeline.protocol_path.with_name("protocol_alt.json")
        alt.write_bytes(git_pipeline.protocol_path.read_bytes())
        with pytest.raises(EvaluationError, match="not committed at the pre-registered"):
            run_git(git_pipeline, head_auth(git_pipeline), protocol_path=alt)
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_evidence_outside_repository_is_rejected(
        self, git_pipeline: GitPipeline, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside_evidence.json"
        outside.write_bytes(git_pipeline.evidence_path.read_bytes())
        with pytest.raises(EvaluationError, match="not inside the repository"):
            run_git(git_pipeline, head_auth(git_pipeline), acquisition_evidence_path=outside)
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_not_a_git_repository_is_rejected(self, tmp_path: Path) -> None:
        gp = make_git_pipeline(tmp_path)
        with pytest.raises(EvaluationError, match="could not establish the repository revision"):
            run_authorized_benchmark(
                repo_root=tmp_path / "not-a-repo",
                manifest_path=gp.manifest_path,
                protocol_path=gp.protocol_path,
                lock_path=gp.lock_path,
                acquisition_evidence_path=gp.evidence_path,
                output_dir=tmp_path / "out",
                raw_chunk_dir=gp.raw_chunk_dir,
                derived_csv=gp.derived_csv,
                authorization=head_auth(gp),
                clock=make_clock(),
            )


class TestCanonicalLedger:
    """R2: the ledger is the canonical tracked file, not caller-selected."""

    def test_alternate_ledger_path_is_rejected(
        self, git_pipeline: GitPipeline, tmp_path: Path
    ) -> None:
        alt = tmp_path / "other_ledger.jsonl"
        alt.write_bytes(b"")
        with pytest.raises(EvaluationError, match="not the canonical tracked ledger"):
            run_git(git_pipeline, head_auth(git_pipeline), ledger_path=alt)
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_canonical_relpath_constant(self) -> None:
        assert CANONICAL_LEDGER_RELPATH == "research/m2b/test_evaluations.jsonl"

    def test_symlinked_canonical_ledger_is_rejected(
        self, git_pipeline: GitPipeline, tmp_path: Path
    ) -> None:
        # Commit the canonical ledger as a symlink pointing outside the repo,
        # so the tree is clean but the ledger is not a real tracked file.
        external = tmp_path / "external.jsonl"
        external.write_bytes(b"")
        git_pipeline.ledger_path.unlink()
        git_pipeline.ledger_path.symlink_to(external)
        _git(git_pipeline.repo_root, "add", "research")
        _git(git_pipeline.repo_root, "commit", "-q", "-m", "symlink ledger")
        new_head = _git(git_pipeline.repo_root, "rev-parse", "HEAD")
        with pytest.raises(EvaluationError, match="must be a real tracked file, not a symlink"):
            run_git(git_pipeline, make_authorization(code_commit_sha=new_head))

    def test_second_evaluation_after_committing_the_ledger_is_refused_as_consumed(
        self, git_pipeline: GitPipeline
    ) -> None:
        # The two-ledgers-double-evaluation attack (possible at head 172253b)
        # is closed: the ledger is the one canonical tracked file, so after the
        # access is consumed and committed, a second run at the new HEAD is
        # refused because the same holdout (these candles) is already consumed —
        # a fresh evaluation id does not launder it.
        run_git(git_pipeline, head_auth(git_pipeline))
        _git(git_pipeline.repo_root, "add", "research")
        _git(git_pipeline.repo_root, "commit", "-q", "-m", "record consumed access")
        new_head = _git(git_pipeline.repo_root, "rev-parse", "HEAD")
        with pytest.raises(EvaluationError, match="already consumed"):
            run_git(
                git_pipeline,
                make_authorization("m2b-synthetic-eval-002", code_commit_sha=new_head),
                output_dir=git_pipeline.repo_root / "reports2",
            )


class TestInternalDatasetReverification:
    """R4: the evaluator reloads and re-verifies the dataset itself."""

    def test_forged_quality_report_beside_manifest_is_rejected(
        self, git_pipeline: GitPipeline
    ) -> None:
        # Tamper the quality report next to the manifest: load_canonical_dataset
        # (invoked internally) must reject it before the ledger is consumed.
        manifest = json.loads(git_pipeline.manifest_path.read_bytes())
        quality_path = git_pipeline.manifest_path.with_name(manifest["quality_report_filename"])
        tampered = quality_path.read_bytes().replace(b'"row_count"', b'"row_kount"', 1)
        assert tampered != quality_path.read_bytes()
        quality_path.write_bytes(tampered)
        with pytest.raises(DatasetVerificationError, match="quality report"):
            run_git(git_pipeline, head_auth(git_pipeline))
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_raw_chunk_change_breaks_semantic_verification(self, git_pipeline: GitPipeline) -> None:
        # Change a raw candle so the derived CSV no longer re-derives; the
        # semantic acquisition check (R1) invoked in the guarded path fails.
        chunk = next(iter(git_pipeline.raw_chunk_dir.glob("*.json")))
        chunk.write_bytes(chunk.read_bytes().replace(b"100.0", b"123.0", 1))
        with pytest.raises(
            (EvaluationError, DatasetLockError), match=r"acquisition|SHA-256|derive"
        ):
            run_git(git_pipeline, head_auth(git_pipeline))
        assert read_ledger(git_pipeline.ledger_path) == ()


class TestTrainValidationFromManifest:
    """R4: high-level train/validation path loads the verified dataset itself."""

    def test_from_manifest_matches_direct(self, coinbase_pipeline: CoinbasePipeline) -> None:
        protocol = make_protocol(coinbase_pipeline)
        direct = evaluate_train_validation(load_dataset(coinbase_pipeline), protocol)
        from_manifest = evaluate_train_validation_from_manifest(
            coinbase_pipeline.build.manifest_path, protocol
        )
        assert from_manifest == direct

    def test_forged_hand_built_loaded_dataset_is_rejected(
        self, coinbase_pipeline: CoinbasePipeline
    ) -> None:
        # A LoadedDataset whose frame does not match its manifest fingerprint.
        import dataclasses as _dc

        good = load_dataset(coinbase_pipeline)
        broken_frame = good.frame.copy()
        closes = broken_frame["close"].to_numpy().copy()
        closes[0] += 1.0
        broken_frame["close"] = closes
        forged = _dc.replace(good, frame=broken_frame)
        with pytest.raises(EvaluationError, match="does not recompute to its manifest"):
            evaluate_train_validation(forged, make_protocol(coinbase_pipeline))


class TestActiveRedTeam:
    """Extra adversarial cases from the required red-team pass."""

    @pytest.mark.parametrize("target", ["protocol_path", "lock_path", "evidence_path"])
    def test_dirty_tracked_input_is_rejected(self, git_pipeline: GitPipeline, target: str) -> None:
        path: Path = getattr(git_pipeline, target)
        path.write_bytes(path.read_bytes() + b"\n")  # tracked modification
        with pytest.raises(EvaluationError, match="tracked working tree is not clean"):
            run_git(git_pipeline, head_auth(git_pipeline))
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_failure_recording_completed_leaves_started_consumed(
        self, git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A failure appending the 'completed' event (after the report is
        # published) leaves a consumed 'started' access — never a silent rerun.
        real_append = append_event

        def failing(path: Any, event: Any) -> None:
            if event.event == "completed":
                raise OSError("ledger append failed")
            real_append(path, event)

        monkeypatch.setattr(evaluation, "append_event", failing)
        with pytest.raises(OSError, match="ledger append failed"):
            run_git(git_pipeline, head_auth(git_pipeline))
        events = read_ledger(git_pipeline.ledger_path)
        assert [event.event for event in events] == ["started"]  # access consumed
        assert (git_pipeline.output_dir / "benchmark_results.json").exists()

    def test_second_repository_root_is_an_independent_ledger_documented_limitation(
        self, tmp_path: Path
    ) -> None:
        # The per-repo control cannot stop a second clone from evaluating the
        # same protocol against its own pristine ledger. This is the honest,
        # documented single-repository limitation — asserted here, not hidden.
        from eth_research import gitcheck

        assert "single-repository" in (gitcheck.__doc__ or "")
        repo_a = make_git_pipeline(tmp_path / "a")
        repo_b = make_git_pipeline(tmp_path / "b")
        run_git(repo_a, make_authorization(code_commit_sha=repo_a.head))
        run_git(repo_b, make_authorization(code_commit_sha=repo_b.head))
        assert len(read_ledger(repo_a.ledger_path)) == 2
        assert len(read_ledger(repo_b.ledger_path)) == 2


class TestPackageSourceBindingRepro:
    """C1 reproduction: a repo with committed metadata but no package source
    currently performs an authorized evaluation using code from a foreign
    checkout. It must be rejected."""

    def test_metadata_without_source_is_rejected(self, git_pipeline: GitPipeline) -> None:
        # git_pipeline commits research/m2b/* but no src/eth_research; the
        # running package is imported from the real repo, not this checkout.
        with pytest.raises(EvaluationError, match="source"):
            run_authorized_benchmark(
                repo_root=git_pipeline.repo_root,
                manifest_path=git_pipeline.manifest_path,
                protocol_path=git_pipeline.protocol_path,
                lock_path=git_pipeline.lock_path,
                acquisition_evidence_path=git_pipeline.evidence_path,
                output_dir=git_pipeline.output_dir,
                authorization=head_auth(git_pipeline),
                raw_chunk_dir=git_pipeline.raw_chunk_dir,
                derived_csv=git_pipeline.derived_csv,
                clock=make_clock(),
            )
        assert read_ledger(git_pipeline.ledger_path) == ()


# --- C1 source-binding: negatives in-process + a real-checkout integration test ---

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]


def _git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def make_real_checkout(tmp_path: Path) -> GitPipeline:
    """A self-contained clone of the running repository with committed M2B
    artifacts, so its own src/eth_research is the authorized package."""
    clone = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "--quiet", "--local", "--no-hardlinks", str(REPO_ROOT), str(clone)],
        capture_output=True,
        text=True,
        check=True,
    )
    _git_out(clone, "config", "user.email", "test@example.com")
    _git_out(clone, "config", "user.name", "Test Researcher")
    # Overlay the working-tree source so the integration test exercises the
    # *current* package (which may carry uncommitted changes), not merely the
    # last commit; the clone then commits it as its own authorized source.
    shutil.copytree(
        REPO_ROOT / "src",
        clone / "src",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )

    # The real repo now carries frozen M2B artifacts; drop them from the clone
    # so this integration checkout stands on its own synthetic dataset.
    research = clone / "research" / "m2b"
    if research.exists():
        shutil.rmtree(research)
    research.mkdir(parents=True)

    pipe = build_coinbase_pipeline(clone / "data")
    evidence_path = research / "acquisition_evidence.json"
    write_acquisition_evidence(pipe.evidence, evidence_path)
    lock = build_dataset_lock(
        pipe.build.manifest,
        manifest_sha256=pipe.manifest_sha256,
        acquisition_evidence_sha256=sha256_file(evidence_path),
    )
    lock_path = research / "dataset_lock.json"
    lock_path.write_bytes(lock.to_json_bytes())
    protocol = build_benchmark_protocol(lock, package_version=eth_research.__version__)
    protocol_path = research / "protocol.json"
    protocol_path.write_bytes(protocol.to_json_bytes())
    # The frozen runtime contract, generated from this checkout's own lockfiles
    # under the running interpreter, so the runtime gate passes in-checkout.
    runtime_contract_path = research / "runtime_contract.json"
    runtime_contract_path.write_bytes(RuntimeContract.for_current_runtime(clone).to_json_bytes())
    (research / "test_evaluations.jsonl").write_bytes(b"")  # pristine, already tracked

    _git_out(clone, "add", "-A", "src", "research/m2b")
    _git_out(clone, "commit", "--quiet", "-m", "sync source and pre-register benchmark protocol")
    head = _git_out(clone, "rev-parse", "HEAD")
    return GitPipeline(
        repo_root=clone,
        manifest_path=pipe.build.manifest_path,
        protocol_path=protocol_path,
        lock_path=lock_path,
        evidence_path=evidence_path,
        ledger_path=research / "test_evaluations.jsonl",
        output_dir=clone / "reports" / "m2b",
        raw_chunk_dir=pipe.chunk_dir,
        derived_csv=pipe.derived_csv,
        head=head,
        protocol=protocol,
        lock=lock,
    )


_DRIVER = """
import json, sys
sys.path.insert(0, {src!r})
import eth_research
from eth_research.evaluation import (
    EVALUATION_CONFIRM_TOKEN, OneTimeTestAuthorization, run_authorized_benchmark,
)
{prelude}
out = {{"package_file": eth_research.__file__}}
try:
    run = run_authorized_benchmark(
        repo_root={repo!r},
        manifest_path={manifest!r},
        protocol_path={protocol!r},
        lock_path={lock!r},
        acquisition_evidence_path={evidence!r},
        output_dir={outdir!r},
        raw_chunk_dir={raw!r},
        derived_csv={derived!r},
        authorization=OneTimeTestAuthorization(
            evaluation_id="m2b-integration-eval-001",
            reason="genuine real-checkout integration test",
            code_commit_sha={head!r},
            confirm_token=EVALUATION_CONFIRM_TOKEN,
        ),
    )
    out["ok"] = True
    out["results_path"] = str(run.results_path)
    out["test_evaluation_id"] = run.results.test_evaluation_id
except Exception as exc:  # noqa: BLE001
    out["ok"] = False
    out["error"] = type(exc).__name__
    out["msg"] = str(exc)
print(json.dumps(out))
"""


def run_in_checkout(gp: GitPipeline, *, prelude: str = "") -> dict[str, Any]:
    driver = _DRIVER.format(
        src=str(gp.repo_root / "src"),
        prelude=prelude,
        repo=str(gp.repo_root),
        manifest=str(gp.manifest_path),
        protocol=str(gp.protocol_path),
        lock=str(gp.lock_path),
        evidence=str(gp.evidence_path),
        outdir=str(gp.output_dir),
        raw=str(gp.raw_chunk_dir),
        derived=str(gp.derived_csv),
        head=gp.head,
    )
    script = gp.repo_root / "_driver.py"
    script.write_text(driver, encoding="utf-8")
    env = {"PYTHONPATH": str(gp.repo_root / "src"), "PATH": os.environ.get("PATH", "")}
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(gp.repo_root),
        env=env,
        check=False,
    )
    script.unlink()
    assert result.returncode == 0, f"driver crashed: {result.stderr}"
    return dict(json.loads(result.stdout.strip().splitlines()[-1]))


class TestPackageSourceBinding:
    """C1: prove the running package is the code committed at the authorized HEAD."""

    def test_metadata_without_source_is_rejected(self, git_pipeline: GitPipeline) -> None:
        with pytest.raises(EvaluationError, match="metadata but not the package source"):
            run_authorized_benchmark(
                repo_root=git_pipeline.repo_root,
                manifest_path=git_pipeline.manifest_path,
                protocol_path=git_pipeline.protocol_path,
                lock_path=git_pipeline.lock_path,
                acquisition_evidence_path=git_pipeline.evidence_path,
                output_dir=git_pipeline.output_dir,
                raw_chunk_dir=git_pipeline.raw_chunk_dir,
                derived_csv=git_pipeline.derived_csv,
                authorization=head_auth(git_pipeline),
                clock=make_clock(),
            )
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_foreign_checkout_same_version_is_rejected(
        self, git_pipeline: GitPipeline, tmp_path: Path
    ) -> None:
        # A temp repo that DOES contain a committed copy of the package source
        # (same __version__), but the running package is imported from the real
        # repo — a different checkout.
        foreign = tmp_path / "foreign"
        (foreign / "src").mkdir(parents=True)
        shutil.copytree(REPO_ROOT / "src" / "eth_research", foreign / "src" / "eth_research")
        _git_out(foreign, "init", "-q")
        _git_out(foreign, "config", "user.email", "t@example.com")
        _git_out(foreign, "config", "user.name", "T")
        # bring the M2B artifacts over so only the source-identity check can fail
        shutil.copytree(git_pipeline.repo_root / "research", foreign / "research")
        (foreign / ".gitignore").write_text("data/\nreports/\n", encoding="utf-8")
        _git_out(foreign, "add", "-A")
        _git_out(foreign, "commit", "-q", "-m", "foreign checkout")
        foreign_head = _git_out(foreign, "rev-parse", "HEAD")
        with pytest.raises(EvaluationError, match=r"different checkouts|imported from"):
            run_authorized_benchmark(
                repo_root=foreign,
                manifest_path=git_pipeline.manifest_path,
                protocol_path=foreign / "research" / "m2b" / "protocol.json",
                lock_path=foreign / "research" / "m2b" / "dataset_lock.json",
                acquisition_evidence_path=foreign
                / "research"
                / "m2b"
                / "acquisition_evidence.json",
                output_dir=foreign / "reports" / "m2b",
                raw_chunk_dir=git_pipeline.raw_chunk_dir,
                derived_csv=git_pipeline.derived_csv,
                authorization=make_authorization(code_commit_sha=foreign_head),
                clock=make_clock(),
            )

    def test_source_binding_happens_before_any_backtest(
        self, git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = {"n": 0}

        def spy(*args: Any, **kwargs: Any) -> Any:
            called["n"] += 1
            return real_run_backtest(*args, **kwargs)

        monkeypatch.setattr(evaluation, "run_backtest", spy)
        with pytest.raises(EvaluationError, match="package source binding failed"):
            run_authorized_benchmark(
                repo_root=git_pipeline.repo_root,
                manifest_path=git_pipeline.manifest_path,
                protocol_path=git_pipeline.protocol_path,
                lock_path=git_pipeline.lock_path,
                acquisition_evidence_path=git_pipeline.evidence_path,
                output_dir=git_pipeline.output_dir,
                raw_chunk_dir=git_pipeline.raw_chunk_dir,
                derived_csv=git_pipeline.derived_csv,
                authorization=head_auth(git_pipeline),
                clock=make_clock(),
            )
        assert called["n"] == 0  # no strategy/backtest was reached
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_real_checkout_executes_its_own_package_successfully(self, tmp_path: Path) -> None:
        gp = make_real_checkout(tmp_path)
        out = run_in_checkout(gp)
        assert out["ok"] is True, out
        # the executed code really came from the checkout, not the parent repo
        assert str(gp.repo_root) in out["package_file"]
        assert out["test_evaluation_id"] == "m2b-integration-eval-001"
        events = read_ledger(gp.ledger_path)
        assert [event.event for event in events] == ["started", "completed"]
        assert (gp.output_dir / "benchmark_results.json").exists()

    def test_real_checkout_with_dirty_package_source_is_rejected(self, tmp_path: Path) -> None:
        gp = make_real_checkout(tmp_path)
        # Modify a tracked package source file in the checkout's working tree.
        target = gp.repo_root / "src" / "eth_research" / "evaluation.py"
        target.write_bytes(target.read_bytes() + b"\n# tampered\n")
        out = run_in_checkout(gp)
        assert out["ok"] is False
        assert "not clean" in out["msg"] or "differs from its bytes" in out["msg"]
        assert read_ledger(gp.ledger_path) == ()


class TestRuntimeEnvironmentBinding:
    """Runtime gate: the numerical environment must match the frozen contract,
    verified before the ledger / dataset / any backtest."""

    def _runtime_contract_path(self, gp: GitPipeline) -> Path:
        return gp.repo_root / "research" / "m2b" / "runtime_contract.json"

    def _recommit(self, gp: GitPipeline, message: str) -> None:
        _git_out(gp.repo_root, "add", "-A")
        _git_out(gp.repo_root, "commit", "--quiet", "-m", message)
        gp.head = _git_out(gp.repo_root, "rev-parse", "HEAD")

    def test_verify_runtime_environment_passes_on_real_checkout(self, tmp_path: Path) -> None:
        gp = make_real_checkout(tmp_path)
        # The helper returns None (no raise) on a faithful checkout.
        evaluation._verify_runtime_environment(gp.repo_root, gp.head)

    def test_missing_runtime_contract_is_rejected(self, tmp_path: Path) -> None:
        gp = make_real_checkout(tmp_path)
        self._runtime_contract_path(gp).unlink()
        self._recommit(gp, "drop runtime contract")
        with pytest.raises(EvaluationError, match=r"runtime contract .* does not exist"):
            evaluation._verify_runtime_environment(gp.repo_root, gp.head)

    def test_dirty_uv_lock_is_rejected(self, tmp_path: Path) -> None:
        gp = make_real_checkout(tmp_path)
        uv_lock = gp.repo_root / "uv.lock"
        uv_lock.write_bytes(uv_lock.read_bytes() + b"\n# tampered\n")  # working != committed
        with pytest.raises(EvaluationError, match=r"uv.lock .* differs from its bytes"):
            evaluation._verify_runtime_environment(gp.repo_root, gp.head)

    def test_symlinked_runtime_contract_is_rejected(self, tmp_path: Path) -> None:
        gp = make_real_checkout(tmp_path)
        contract = self._runtime_contract_path(gp)
        external = tmp_path / "external_contract.json"
        external.write_bytes(contract.read_bytes())
        contract.unlink()
        contract.symlink_to(external)
        self._recommit(gp, "symlink runtime contract")
        with pytest.raises(EvaluationError, match="must be a real tracked file, not a symlink"):
            evaluation._verify_runtime_environment(gp.repo_root, gp.head)

    def test_wrong_dependency_version_is_rejected(self, tmp_path: Path) -> None:
        gp = make_real_checkout(tmp_path)
        contract = self._runtime_contract_path(gp)
        good = RuntimeContract.from_json_bytes(contract.read_bytes())
        contract.write_bytes(dataclasses.replace(good, numpy_version="1.0.0").to_json_bytes())
        self._recommit(gp, "forge runtime contract numpy version")
        with pytest.raises(EvaluationError, match="runtime mismatch on numpy_version"):
            evaluation._verify_runtime_environment(gp.repo_root, gp.head)

    def test_wrong_runtime_contract_rejected_before_ledger_via_public_entry(
        self, tmp_path: Path
    ) -> None:
        # Full public entry, in a real checkout subprocess: a forged runtime
        # contract must be refused after source binding and before the ledger.
        gp = make_real_checkout(tmp_path)
        contract = self._runtime_contract_path(gp)
        good = RuntimeContract.from_json_bytes(contract.read_bytes())
        contract.write_bytes(dataclasses.replace(good, pandas_version="0.0.1").to_json_bytes())
        self._recommit(gp, "forge runtime contract pandas version")
        out = run_in_checkout(gp)
        assert out["ok"] is False
        assert "runtime" in out["msg"]
        assert read_ledger(gp.ledger_path) == ()
        assert not (gp.output_dir / "benchmark_results.json").exists()


class TestMandatoryAcquisitionVerification:
    """C2: raw_chunk_dir and derived_csv are mandatory; verification cannot be skipped."""

    def test_omitting_both_is_a_type_error(self, git_pipeline: GitPipeline) -> None:
        # Both are required parameters — they cannot be omitted from the call.
        with pytest.raises(TypeError):
            run_authorized_benchmark(  # type: ignore[call-arg]
                repo_root=git_pipeline.repo_root,
                manifest_path=git_pipeline.manifest_path,
                protocol_path=git_pipeline.protocol_path,
                lock_path=git_pipeline.lock_path,
                acquisition_evidence_path=git_pipeline.evidence_path,
                output_dir=git_pipeline.output_dir,
                authorization=head_auth(git_pipeline),
                clock=make_clock(),
            )

    def test_explicit_none_is_refused_at_runtime(self, git_pipeline: GitPipeline) -> None:
        with pytest.raises(EvaluationError, match="requires both raw_chunk_dir and derived_csv"):
            run_git(git_pipeline, head_auth(git_pipeline), raw_chunk_dir=None)
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_explicit_none_derived_csv_is_refused(self, git_pipeline: GitPipeline) -> None:
        with pytest.raises(EvaluationError, match="requires both raw_chunk_dir and derived_csv"):
            run_git(git_pipeline, head_auth(git_pipeline), derived_csv=None)
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_mutated_raw_chunk_is_refused(self, git_pipeline: GitPipeline) -> None:
        chunk = next(iter(git_pipeline.raw_chunk_dir.glob("*.json")))
        chunk.write_bytes(chunk.read_bytes().replace(b"100.0", b"123.0", 1))
        with pytest.raises((EvaluationError, DatasetLockError), match=r"acquisition|derive|SHA"):
            run_git(git_pipeline, head_auth(git_pipeline))
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_missing_chunk_directory_is_refused(
        self, git_pipeline: GitPipeline, tmp_path: Path
    ) -> None:
        with pytest.raises((EvaluationError, DatasetLockError)):
            run_git(git_pipeline, head_auth(git_pipeline), raw_chunk_dir=tmp_path / "nope")
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_non_reconstructing_derived_csv_is_refused(self, git_pipeline: GitPipeline) -> None:
        git_pipeline.derived_csv.write_bytes(
            git_pipeline.derived_csv.read_bytes().replace(b"105.0", b"106.0", 1)
        )
        with pytest.raises((EvaluationError, DatasetLockError), match=r"derive|SHA|does not"):
            run_git(git_pipeline, head_auth(git_pipeline))
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_valid_chain_still_succeeds(self, git_pipeline: GitPipeline) -> None:
        run = run_git(git_pipeline, head_auth(git_pipeline))
        assert (git_pipeline.output_dir / "benchmark_results.json").exists()
        assert run.results.test_evaluation_id == "m2b-synthetic-eval-001"


class TestVerifyDatasetLockXor:
    """C2: verify_dataset_lock rejects exactly one acquisition argument."""

    def test_only_chunk_dir_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        lock = make_lock(coinbase_pipeline)
        with pytest.raises(DatasetLockError, match="must be supplied together"):
            verify_dataset_lock(
                lock,
                manifest_path=coinbase_pipeline.build.manifest_path,
                acquisition_evidence_path=coinbase_pipeline.evidence_path,
                raw_chunk_dir=coinbase_pipeline.chunk_dir,
            )

    def test_only_derived_csv_is_rejected(self, coinbase_pipeline: CoinbasePipeline) -> None:
        lock = make_lock(coinbase_pipeline)
        with pytest.raises(DatasetLockError, match="must be supplied together"):
            verify_dataset_lock(
                lock,
                manifest_path=coinbase_pipeline.build.manifest_path,
                acquisition_evidence_path=coinbase_pipeline.evidence_path,
                derived_csv=coinbase_pipeline.derived_csv,
            )


# --- C4: every pre-authorization refusal is inert (no backtest, no ledger or
# output mutation). Each scenario starts from a byte-empty canonical ledger and
# must fail strictly before the `started` event — which is the only point at
# which the one-time access is consumed and the only writer of the ledger. ---


def _scn_no_authorization(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    return None, {}


def _scn_explicit_none_raw_chunk_dir(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    return head_auth(gp), {"raw_chunk_dir": None}


def _scn_explicit_none_derived_csv(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    return head_auth(gp), {"derived_csv": None}


def _scn_zero_commit_sha(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    return make_authorization(code_commit_sha="0" * 40), {}


def _scn_foreign_commit_sha(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    _git(gp.repo_root, "commit", "-q", "--allow-empty", "-m", "later")
    foreign = _git(gp.repo_root, "rev-parse", "HEAD")
    _git(gp.repo_root, "reset", "--hard", "-q", gp.head)
    return make_authorization(code_commit_sha=foreign), {}


def _scn_dirty_tracked_tree(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    gp.lock_path.write_bytes(gp.lock_path.read_bytes() + b"\n")
    return head_auth(gp), {}


def _scn_alternate_ledger_path(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    alt = tmp_path / "other_ledger.jsonl"
    alt.write_bytes(b"")
    return head_auth(gp), {"ledger_path": alt}


def _scn_evidence_outside_repository(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    outside = tmp_path / "outside_evidence.json"
    outside.write_bytes(gp.evidence_path.read_bytes())
    return head_auth(gp), {"acquisition_evidence_path": outside}


def _scn_uncommitted_protocol_path(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    alt = gp.protocol_path.with_name("protocol_alt.json")
    alt.write_bytes(gp.protocol_path.read_bytes())
    return head_auth(gp), {"protocol_path": alt}


def _scn_mutated_raw_chunk(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    chunk = next(iter(gp.raw_chunk_dir.glob("*.json")))
    chunk.write_bytes(chunk.read_bytes().replace(b"100.0", b"123.0", 1))
    return head_auth(gp), {}


def _scn_non_reconstructing_derived_csv(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    gp.derived_csv.write_bytes(gp.derived_csv.read_bytes().replace(b"105.0", b"106.0", 1))
    return head_auth(gp), {}


def _scn_forged_quality_report(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    manifest = json.loads(gp.manifest_path.read_bytes())
    quality_path = gp.manifest_path.with_name(manifest["quality_report_filename"])
    quality_path.write_bytes(quality_path.read_bytes().replace(b'"row_count"', b'"row_kount"', 1))
    return head_auth(gp), {}


def _scn_missing_chunk_directory(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    return head_auth(gp), {"raw_chunk_dir": tmp_path / "nope"}


def _scn_existing_reports_collision(
    gp: GitPipeline, tmp_path: Path
) -> tuple[OneTimeTestAuthorization | None, dict[str, Any]]:
    gp.output_dir.mkdir(parents=True)
    (gp.output_dir / "benchmark_results.json").write_bytes(b"{}")
    return head_auth(gp), {}


_PREAUTH_REFUSALS: tuple[
    tuple[str, Any],
    ...,
] = (
    ("no_authorization", _scn_no_authorization),
    ("explicit_none_raw_chunk_dir", _scn_explicit_none_raw_chunk_dir),
    ("explicit_none_derived_csv", _scn_explicit_none_derived_csv),
    ("zero_commit_sha", _scn_zero_commit_sha),
    ("foreign_commit_sha", _scn_foreign_commit_sha),
    ("dirty_tracked_tree", _scn_dirty_tracked_tree),
    ("alternate_ledger_path", _scn_alternate_ledger_path),
    ("evidence_outside_repository", _scn_evidence_outside_repository),
    ("uncommitted_protocol_path", _scn_uncommitted_protocol_path),
    ("mutated_raw_chunk", _scn_mutated_raw_chunk),
    ("non_reconstructing_derived_csv", _scn_non_reconstructing_derived_csv),
    ("forged_quality_report", _scn_forged_quality_report),
    ("missing_chunk_directory", _scn_missing_chunk_directory),
    ("existing_reports_collision", _scn_existing_reports_collision),
)


class TestPreauthorizationSideEffects:
    """C4: no pre-authorization refusal may run a strategy/backtest, touch the
    canonical ledger, or write a report. Instruments the engine to prove no
    backtest is reached and snapshots the ledger and output on every path."""

    @pytest.mark.parametrize(
        "setup", [scn for _, scn in _PREAUTH_REFUSALS], ids=[name for name, _ in _PREAUTH_REFUSALS]
    )
    def test_refusal_runs_no_backtest_and_leaves_ledger_and_output_unchanged(
        self,
        git_pipeline: GitPipeline,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        setup: Any,
    ) -> None:
        called = {"n": 0}

        def spy(*args: Any, **kwargs: Any) -> Any:
            called["n"] += 1
            return real_run_backtest(*args, **kwargs)

        monkeypatch.setattr(evaluation, "run_backtest", spy)

        results_file = git_pipeline.output_dir / "benchmark_results.json"
        report_file = git_pipeline.output_dir / "benchmark_report.md"
        auth, overrides = setup(git_pipeline, tmp_path)
        ledger_before = git_pipeline.ledger_path.read_bytes()
        results_before = results_file.read_bytes() if results_file.exists() else None

        with pytest.raises((EvaluationError, DatasetLockError, DatasetVerificationError)):
            run_git(git_pipeline, auth, **overrides)

        # No signal was ever generated: the engine was never entered.
        assert called["n"] == 0
        # The canonical ledger is byte-for-byte unchanged (still empty here).
        assert git_pipeline.ledger_path.read_bytes() == ledger_before == b""
        assert read_ledger(git_pipeline.ledger_path) == ()
        # No authoritative report was produced (and a pre-existing decoy, if
        # the scenario planted one, is left byte-identical).
        results_after = results_file.read_bytes() if results_file.exists() else None
        assert results_after == results_before
        assert not report_file.exists()
