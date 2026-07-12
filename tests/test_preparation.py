"""One shared fail-closed preparation gate for production and readiness.

Regression suite for the closure defects: the dossier graph is now a
production gate (B1), production and readiness run the identical shared
preparation (B2), the committed holdout identity must recompute exactly
(B3, production side), and the committed scientific rejection refuses the
evaluator before any strategy, signal, or backtest (B4).
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from conftest import GitPipeline, _git
from eth_research import evaluation, test_readiness
from eth_research.backtest import run_backtest as real_run_backtest
from eth_research.dossier import DossierError
from eth_research.dossier import verify_frozen_dossier as real_verify_graph
from eth_research.evaluation import EvaluationError
from eth_research.ledger import read_ledger
from test_evaluation import head_auth, make_authorization, prepare_git, run_git


def _commit_all(gp: GitPipeline, message: str) -> str:
    _git(gp.repo_root, "add", "-A")
    _git(gp.repo_root, "commit", "-q", "-m", message)
    return _git(gp.repo_root, "rev-parse", "HEAD")


def _engine_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    called = {"n": 0}

    def spy(*args: Any, **kwargs: Any) -> Any:
        called["n"] += 1
        return real_run_backtest(*args, **kwargs)

    monkeypatch.setattr(evaluation, "run_backtest", spy)
    return called


class TestForgedReceiptStopsProduction:
    """B1: a forged committed receipt now stops the production evaluator."""

    def test_production_refuses_before_any_ledger_append_or_backtest(
        self, git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        receipt = (
            git_pipeline.repo_root
            / "research/m2b/raw/coinbase/coinbase-eth-usd-001/acquisition_receipt.json"
        )
        payload = json.loads(receipt.read_bytes())
        payload["workflow_run_id"] = "9999999999"
        receipt.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        head = _commit_all(git_pipeline, "forge receipt metadata")

        called = _engine_spy(monkeypatch)
        with pytest.raises(EvaluationError, match="frozen dossier verification failed"):
            run_git(git_pipeline, make_authorization(code_commit_sha=head))
        assert called["n"] == 0
        assert git_pipeline.ledger_path.read_bytes() == b""
        assert read_ledger(git_pipeline.ledger_path) == ()


class TestSharedGateArchitecture:
    """B2: both public entry points execute the same preparation function."""

    def test_production_and_readiness_hit_the_same_verifier(
        self, git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def counting(root: Any, **kwargs: Any) -> Any:
            calls["n"] += 1
            return real_verify_graph(root, **kwargs)

        monkeypatch.setattr(evaluation, "verify_frozen_dossier", counting)

        # Readiness path.
        with mock.patch.object(
            test_readiness,
            "_running_package_root",
            return_value=git_pipeline.package_source_root,
        ):
            report = test_readiness.preflight_authorized_benchmark(
                git_pipeline.repo_root,
                git_pipeline.manifest_path,
                git_pipeline.output_dir,
                raw_chunk_dir=git_pipeline.raw_chunk_dir,
                derived_csv=git_pipeline.derived_csv,
            )
        assert report.integrity_ready is True
        assert calls["n"] == 1

        # Production path (same fixture, full guarded run).
        run_git(git_pipeline, head_auth(git_pipeline))
        assert calls["n"] == 2

    def test_a_check_added_to_the_shared_gate_affects_both_paths(
        self, git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def poisoned(root: Any, **kwargs: Any) -> Any:
            raise DossierError("injected shared-gate check")

        monkeypatch.setattr(evaluation, "verify_frozen_dossier", poisoned)

        with mock.patch.object(
            test_readiness,
            "_running_package_root",
            return_value=git_pipeline.package_source_root,
        ):
            report = test_readiness.preflight_authorized_benchmark(
                git_pipeline.repo_root,
                git_pipeline.manifest_path,
                git_pipeline.output_dir,
                raw_chunk_dir=git_pipeline.raw_chunk_dir,
                derived_csv=git_pipeline.derived_csv,
            )
        assert report.integrity_ready is False
        assert report.integrity_failure is not None
        assert "injected shared-gate check" in report.integrity_failure

        with pytest.raises(EvaluationError, match="injected shared-gate check"):
            run_git(git_pipeline, head_auth(git_pipeline))
        assert read_ledger(git_pipeline.ledger_path) == ()

    def test_prepare_is_side_effect_free(self, git_pipeline: GitPipeline) -> None:
        ledger_before = git_pipeline.ledger_path.read_bytes()
        prepared = prepare_git(git_pipeline)
        assert prepared.holdout_fresh is True
        assert prepared.promotion_eligible is True
        assert git_pipeline.ledger_path.read_bytes() == ledger_before == b""
        assert not (git_pipeline.output_dir / "benchmark_results.json").exists()


class TestHoldoutIdentityMustRecompute:
    """B3 (production side): hashing the committed identity is not enough."""

    def test_forged_identity_with_refreshed_anchor_is_refused(
        self, git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from eth_research.dossier import build_frozen_dossier

        holdout_file = git_pipeline.repo_root / "research/m2b/holdout_identity.json"
        payload = json.loads(holdout_file.read_bytes())
        payload["test_content_fingerprint"] = "sha256:" + "f" * 64
        holdout_file.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        # The attacker also refreshes the dossier so every hash check passes.
        anchor = git_pipeline.repo_root / "research/m2b/frozen_dossier.json"
        anchor.write_bytes(build_frozen_dossier(git_pipeline.repo_root).to_json_bytes())
        head = _commit_all(git_pipeline, "forge holdout identity + refresh dossier")

        called = _engine_spy(monkeypatch)
        with pytest.raises(EvaluationError, match="does not recompute"):
            run_git(git_pipeline, make_authorization(code_commit_sha=head))
        assert called["n"] == 0
        assert read_ledger(git_pipeline.ledger_path) == ()


class TestScientificRejectionIsEnforced:
    """B4/D2: the committed rejection refuses production before any engine work."""

    def test_rejected_decision_refuses_with_valid_authorization(
        self, rejected_git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = _engine_spy(monkeypatch)
        with pytest.raises(EvaluationError, match="scientifically ineligible"):
            run_git(rejected_git_pipeline, head_auth(rejected_git_pipeline))
        # Refused before ANY strategy, signal, or backtest — including the
        # otherwise-permitted train/validation regeneration.
        assert called["n"] == 0
        assert rejected_git_pipeline.ledger_path.read_bytes() == b""
        assert read_ledger(rejected_git_pipeline.ledger_path) == ()

    def test_editing_the_verdict_to_eligible_is_refused_by_the_rebuild(
        self, rejected_git_pipeline: GitPipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # D3: flip rejected -> eligible in the committed decision. The strict
        # model itself refuses an eligible verdict over underperforming
        # numbers, so the forgery dies during preparation, before started.
        gp = rejected_git_pipeline
        decision_file = gp.repo_root / "research/m2b/validation_decision.json"
        payload = json.loads(decision_file.read_bytes())
        payload["decision"] = "eligible_for_test_promotion"
        decision_file.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        head = _commit_all(gp, "forge decision verdict")

        called = _engine_spy(monkeypatch)
        with pytest.raises(EvaluationError, match="invalid committed validation decision"):
            run_git(gp, make_authorization(code_commit_sha=head))
        assert called["n"] == 0
        assert read_ledger(gp.ledger_path) == ()

    def test_eligible_fixture_still_reaches_the_guarded_run(
        self, git_pipeline: GitPipeline
    ) -> None:
        # The gate keys on the committed decision, not on a hardcoded refusal:
        # a genuinely eligible dossier proceeds through started -> completed.
        run = run_git(git_pipeline, head_auth(git_pipeline))
        events = read_ledger(git_pipeline.ledger_path)
        assert [event.event for event in events] == ["started", "completed"]
        assert run.results.test_evaluation_id == "m2b-synthetic-eval-001"
