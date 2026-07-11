"""Benchmark evaluator: reconciliation, test discipline, reporting."""

from __future__ import annotations

import json
import subprocess
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
from eth_research.data.lock import DatasetLock, DatasetLockError, build_dataset_lock
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.evaluation import (
    CANONICAL_LEDGER_RELPATH,
    EVALUATION_CONFIRM_TOKEN,
    EvaluationError,
    OneTimeTestAuthorization,
    build_benchmark_results,
    evaluate_train_validation,
    evaluate_train_validation_from_manifest,
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
    repo.mkdir()
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
    return run_authorized_benchmark(**kwargs)


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
        assert events[1].result_report_sha256 == sha256_bytes(published)
        assert run.results.to_json_bytes() == published
        assert run.report_path.read_text(encoding="utf-8") == run.markdown
        assert run.results.test_evaluation_id == "m2b-synthetic-eval-001"
        assert run.results.pre_registered_commit_sha == git_pipeline.head
        assert len(run.results.segments) == 6
        assert "exactly once" in run.markdown

    def test_reused_evaluation_id_is_refused(self, git_pipeline: GitPipeline) -> None:
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
        # refused because the (dataset lock, protocol) pair is already consumed.
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
