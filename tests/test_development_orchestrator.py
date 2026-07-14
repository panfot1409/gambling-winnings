"""Fail-closed development-experiment orchestrator: no real work before 'started'."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import eth_research
from eth_research.data.provenance import sha256_file
from eth_research.development_orchestrator import (
    _CONTEXT_SENTINEL,
    OrchestratorError,
    StartedRunContext,
    _resolve_registered_only,
    _verify_started_run_context,
    run_registered_development_experiment,
)
from eth_research.experiment_registry import (
    EXPERIMENT_REGISTRY_RELPATH,
    read_registry,
)

REPO_ROOT = Path(eth_research.__file__).resolve().parents[2]
_REGISTRY = REPO_ROOT / EXPERIMENT_REGISTRY_RELPATH
_GATE_LEDGER = REPO_ROOT / "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER = REPO_ROOT / "research/m2b/test_evaluations.jsonl"
_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class TestStartedRunContextIsRegistryVerified:
    """N1: the started-run context is a convenience carrier, not a capability.

    The sentinel only catches accidental construction; the real boundary is
    :func:`_verify_started_run_context`, which re-reads the canonical registry
    and refuses any carrier the registry does not corroborate — even one built
    with this module's genuine sentinel. (Hostile in-process monkeypatching of
    the verifier itself is out of the single-repository threat model.)
    """

    def test_sentinel_catches_accidental_construction(self) -> None:
        with pytest.raises(OrchestratorError, match="internal carrier"):
            StartedRunContext(
                experiment_id="m3a-fixed-baseline-comparison-v2-run-003",
                run_head_commit_sha="a" * 40,
                source_tree_fingerprint="b" * 64,
                started_event_sha256="c" * 64,
                _token=object(),  # not the module sentinel
            )

    def test_sentinel_valid_carrier_is_refused_when_registry_has_no_started_run(self) -> None:
        # A carrier built with the *real* sentinel authorizes nothing: the
        # canonical registry has no registered→started run-003, so the boundary
        # refuses it before any calculation.
        forged = StartedRunContext(
            experiment_id="m3a-fixed-baseline-comparison-v2-run-003",
            run_head_commit_sha="a" * 40,
            source_tree_fingerprint="b" * 64,
            started_event_sha256="c" * 64,
            _token=_CONTEXT_SENTINEL,
        )
        with pytest.raises(OrchestratorError, match="not corroborated by the canonical registry"):
            _verify_started_run_context(REPO_ROOT, forged)

    def test_sentinel_valid_carrier_for_a_completed_id_is_refused(self) -> None:
        # Even naming a genuinely registered id fails unless it is *exactly*
        # registered→started: run-002 is already completed.
        forged = StartedRunContext(
            experiment_id="m3a-fixed-baseline-comparison-v1-run-002",
            run_head_commit_sha="a" * 40,
            source_tree_fingerprint="b" * 64,
            started_event_sha256="c" * 64,
            _token=_CONTEXT_SENTINEL,
        )
        with pytest.raises(OrchestratorError, match="not corroborated by the canonical registry"):
            _verify_started_run_context(REPO_ROOT, forged)


class TestResolveRegisteredOnly:
    def test_unknown_id_is_refused(self) -> None:
        with pytest.raises(OrchestratorError, match="no registered experiment"):
            _resolve_registered_only((), "m3a-nope-001")

    def test_already_terminal_v1_id_is_refused(self) -> None:
        # The committed registry's run-001/002 are v1 and already completed.
        events = read_registry(_REGISTRY)
        with pytest.raises(OrchestratorError, match="not awaiting execution"):
            _resolve_registered_only(events, "m3a-fixed-baseline-comparison-v1-run-001")


class TestFailClosedPreStart:
    """Before 'started', a refused run appends nothing and touches no sealed file."""

    def _snapshot(self) -> tuple[str, str, str, int]:
        return (
            sha256_file(_REGISTRY),
            sha256_file(_GATE_LEDGER),
            sha256_file(_HOLDOUT_LEDGER),
            len(read_registry(_REGISTRY)),
        )

    def test_no_registered_v2_experiment_refuses_without_side_effects(self) -> None:
        before = self._snapshot()
        assert before[1] == before[2] == _EMPTY  # both sealed ledgers byte-empty
        # A deliberately never-registered v2 id — this must never name run-003's
        # real id, so an already-registered run-003 can never be executed here.
        with pytest.raises(OrchestratorError):
            run_registered_development_experiment(
                REPO_ROOT,
                "m3a-unregistered-probe-experiment",
                clock=lambda: pd.Timestamp("2026-07-13T17:00:00+00:00"),
            )
        after = self._snapshot()
        # Nothing appended; both sealed ledgers still byte-empty.
        assert after == before
        assert after[1] == after[2] == _EMPTY

    def test_running_an_already_completed_v1_id_refuses(self) -> None:
        before = self._snapshot()
        with pytest.raises(OrchestratorError):
            run_registered_development_experiment(
                REPO_ROOT,
                "m3a-fixed-baseline-comparison-v1-run-002",
                clock=lambda: pd.Timestamp("2026-07-13T17:00:00+00:00"),
            )
        assert self._snapshot() == before
