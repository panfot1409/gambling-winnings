"""The single fail-closed development-experiment orchestrator (M3A closure R1).

Milestone 3A's original publisher (``develop_m3a --write``) reached the real
research-train evaluation and wrote the tracked artifacts with **no** consult
of the experiment registry — governance lived beside the write path, not
inside it (closure defect R1). This module replaces that split with one public
high-level operation, :func:`run_registered_development_experiment`, which is
the *only* way real research-train artifacts are ever published.

Before any real calculation the orchestrator runs an ordered set of fail-closed
pre-checks (repository identity and clean tree, running-source and numerical
runtime binding, frozen dossier / partition / protocol / methodology
verification, both sealed ledgers byte-empty, the canonical tracked registry,
exactly one registered-only v2 experiment whose bound fields all agree, and no
output collision). Only then does it append a durable ``started`` event and
mint an unforgeable :class:`DevelopmentRunAuthorization`; the real evaluation
and the transactional publication both require that token, so no strategy,
backtest, metric, or bootstrap can run — and nothing can be published — before
``started`` exists. On success it publishes the immutable run artifacts and the
compatibility aliases as one durable batch, reads them back, strictly parses
them, reconciles the return evidence, and appends ``completed``; on any failure
after ``started`` it appends ``failed`` and the experiment id stays consumed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research import __version__
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.development import DEVELOPMENT_PARTITION_RELPATH, load_development_partition
from eth_research.development_evaluation import (
    DevelopmentEvaluationDetail,
    evaluate_development_detailed,
)
from eth_research.development_ledger import DEVELOPMENT_GATE_LEDGER_RELPATH
from eth_research.dossier import FROZEN_DOSSIER_RELPATH, load_frozen_dossier
from eth_research.environment import RuntimeVerificationError
from eth_research.experiment_registry import (
    EVENT_COMPLETED,
    EVENT_FAILED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    EXPERIMENT_REGISTRY_RELPATH,
    ExperimentEventV2,
    RegistryError,
    append_registry_event,
    latest_registry_line_sha256,
    read_registry,
)
from eth_research.gitcheck import (
    GitError,
    head_commit,
    is_commit_object,
    resolve_repo_root,
    source_tree_fingerprint,
    tracked_tree_is_clean,
    verify_package_source,
)
from eth_research.methodology_v2 import METHODOLOGY_PROTOCOL_V2_RELPATH, load_methodology_v2
from eth_research.walkforward import WALK_FORWARD_PROTOCOL_RELPATH

# The M2B final-holdout ledger; must also stay byte-empty in Milestone 3A.
_HOLDOUT_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"
_EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class OrchestratorError(RuntimeError):
    """A fail-closed development-experiment orchestration refused to proceed."""


# An unforgeable capability: only this module holds the sentinel, so a
# DevelopmentRunAuthorization cannot be constructed outside the orchestrator.
_AUTH_SENTINEL: object = object()


@dataclass(frozen=True)
class DevelopmentRunAuthorization:
    """Proof that a ``started`` event was durably appended for this experiment.

    The real evaluation and the publication both require this object; it can
    be minted only inside :func:`run_registered_development_experiment`, after
    the ``started`` event exists, so no real research-train calculation or
    artifact publication can occur before the registry records the run.
    """

    experiment_id: str
    execution_code_commit_sha: str
    source_tree_fingerprint: str
    started_event_sha256: str
    _token: object

    def __post_init__(self) -> None:
        if self._token is not _AUTH_SENTINEL:
            raise OrchestratorError(
                "DevelopmentRunAuthorization cannot be forged; it is minted only after a durable "
                "'started' event by the orchestrator"
            )


@dataclass(frozen=True)
class PreparedRun:
    """The validated, read-only pre-start context of a registered experiment."""

    repo_root: Path
    head: str
    source_tree_fingerprint: str
    registered_event: ExperimentEventV2
    registry_relpath: str
    previous_line_sha256: str


def _verify_ledgers_byte_empty(root: Path) -> None:
    for relpath in (DEVELOPMENT_GATE_LEDGER_RELPATH, _HOLDOUT_LEDGER_RELPATH):
        path = root / relpath
        if not path.exists():
            raise OrchestratorError(f"sealed ledger {relpath} is missing")
        if path.is_symlink():
            raise OrchestratorError(f"sealed ledger {relpath} must be a real file, not a symlink")
        if sha256_file(path) != _EMPTY_SHA256:
            raise OrchestratorError(f"sealed ledger {relpath} is not byte-empty — refusing to run")


def _running_package_root() -> Path:
    import eth_research

    location = eth_research.__file__
    if location is None:  # pragma: no cover - namespace package, not our layout
        raise OrchestratorError("the running eth_research package has no filesystem location")
    return Path(location).resolve().parent


def _preflight(repo_root: str | Path, experiment_id: str) -> PreparedRun:
    """Run every fail-closed pre-check and return the validated context.

    Read-only: it resolves and verifies the repository, runtime, frozen data,
    protocols, ledgers, and registry, and locates exactly one registered-only
    v2 experiment matching ``experiment_id`` whose bound fields all agree and
    whose output paths do not yet exist. It appends nothing.
    """
    # 1-2. Canonical repository root; refuse a symlinked/foreign package tree.
    try:
        root = resolve_repo_root(repo_root)
    except GitError as exc:
        raise OrchestratorError(f"cannot resolve a git repository root: {exc}") from exc
    package_root = _running_package_root()
    if package_root != (root / "src/eth_research").resolve():
        raise OrchestratorError(
            f"the running package {package_root} is not this repository's src/eth_research"
        )
    # 3. Working tree clean (untracked market data is ignored by tracked_tree_is_clean).
    if not tracked_tree_is_clean(root):
        raise OrchestratorError("the tracked working tree is dirty; refusing to run")
    # 4. Real HEAD commit.
    head = head_commit(root)
    if not is_commit_object(root, head):
        raise OrchestratorError(f"HEAD {head!r} is not a real commit object")
    # 5. Running source == committed source at HEAD; take its fingerprint.
    try:
        verify_package_source(root, head, package_root)
    except GitError as exc:
        raise OrchestratorError(f"running source does not match HEAD: {exc}") from exc
    fingerprint = source_tree_fingerprint(root, head)
    # 6. Frozen numerical runtime (snapshot-aware: the frozen M2B contract is a
    #    superseded snapshot under the advanced 0.4.0 package, verified read-only).
    _verify_runtime(root)
    # 7-8. Committed development partition; the frozen M2B dossier's committed
    #    bytes must match the partition's binding, and it must strictly parse.
    #    (The full reconstruction-based dossier verification runs inside the
    #    authorized evaluation, after 'started'.)
    partition = load_development_partition(root / DEVELOPMENT_PARTITION_RELPATH)
    partition_sha = sha256_file(root / DEVELOPMENT_PARTITION_RELPATH)
    dossier_sha = sha256_file(root / FROZEN_DOSSIER_RELPATH)
    if dossier_sha != partition.frozen_m2_dossier_sha256:
        raise OrchestratorError(
            "frozen M2B dossier committed bytes disagree with the development partition binding"
        )
    load_frozen_dossier(root / FROZEN_DOSSIER_RELPATH)
    protocol_sha = sha256_file(root / WALK_FORWARD_PROTOCOL_RELPATH)
    # Immutable v2 methodology artifact (binds the v1 protocol + bootstrap v2).
    methodology = load_methodology_v2(root / METHODOLOGY_PROTOCOL_V2_RELPATH)
    methodology_sha = sha256_file(root / METHODOLOGY_PROTOCOL_V2_RELPATH)
    if methodology.base_walk_forward_protocol_sha256 != protocol_sha:
        raise OrchestratorError("methodology does not bind the committed v1 protocol")
    if methodology.development_partition_sha256 != partition_sha:
        raise OrchestratorError("methodology does not bind the committed development partition")
    # 10. Both sealed ledgers byte-empty.
    _verify_ledgers_byte_empty(root)
    # 11-12. Canonical tracked registry only (no alternate/symlinked path).
    registry_path = root / EXPERIMENT_REGISTRY_RELPATH
    if registry_path.is_symlink():
        raise OrchestratorError(
            "the experiment registry must be a real tracked file, not a symlink"
        )
    events = read_registry(registry_path)
    # 13. Exactly one registered v2 experiment with no started/terminal event.
    registered = _resolve_registered_only(events, experiment_id)
    # 14. Bound fields agree with the committed inputs.
    if registered.execution_source_tree_fingerprint != fingerprint:
        raise OrchestratorError(
            "registered execution source-tree fingerprint disagrees with the running source"
        )
    if registered.execution_code_commit_sha != head:
        raise OrchestratorError("registered execution commit is not HEAD")
    if registered.development_partition_sha256 != partition_sha:
        raise OrchestratorError("registered partition SHA disagrees with the committed partition")
    if registered.walk_forward_protocol_path != WALK_FORWARD_PROTOCOL_RELPATH:
        raise OrchestratorError("registered walk-forward protocol path is not the canonical path")
    if registered.walk_forward_protocol_sha256 != methodology_sha:
        raise OrchestratorError(
            "registered walk_forward_protocol_sha256 must bind the v2 methodology artifact"
        )
    if registered.methodology_id != methodology.methodology_id:
        raise OrchestratorError("registered methodology id disagrees with the methodology artifact")
    # 15. Refuse output collisions before consuming the experiment.
    for relpath in (
        registered.immutable_results_path,
        registered.immutable_report_path,
        registered.return_evidence_path,
        registered.artifact_manifest_path,
    ):
        if (root / relpath).exists():
            raise OrchestratorError(f"output collision: {relpath} already exists")
    previous = latest_registry_line_sha256(registry_path)
    if previous is None:  # pragma: no cover - registry always has the v1 prefix
        raise OrchestratorError("registry is empty; cannot chain a v2 event")
    return PreparedRun(
        repo_root=root,
        head=head,
        source_tree_fingerprint=fingerprint,
        registered_event=registered,
        registry_relpath=EXPERIMENT_REGISTRY_RELPATH,
        previous_line_sha256=previous,
    )


def _verify_runtime(root: Path) -> None:
    """Verify the numerical runtime against the frozen contract (snapshot-aware).

    The runtime contract, ``uv.lock``, and ``pyproject.toml`` are already
    proven to equal their HEAD bytes by the clean-tree pre-check. When the
    running package version equals the contract's the live runtime is attested
    exactly; when it differs (M3A 0.4.0 over the frozen 0.3.0 contract) only
    the version-independent numerical identity is attested.
    """
    from eth_research.environment import (
        CANONICAL_RUNTIME_CONTRACT_RELPATH,
        load_runtime_contract,
        verify_runtime_contract,
        verify_runtime_snapshot,
    )

    contract_path = root / CANONICAL_RUNTIME_CONTRACT_RELPATH
    if contract_path.is_symlink():
        raise OrchestratorError("the runtime contract must be a real tracked file, not a symlink")
    try:
        contract = load_runtime_contract(contract_path)
        if contract.snapshot.package_version == __version__:
            verify_runtime_contract(contract, repo_root=root)
        else:
            verify_runtime_snapshot(contract)
    except RuntimeVerificationError as exc:
        raise OrchestratorError(f"frozen numerical runtime failed verification: {exc}") from exc


def _resolve_registered_only(events: tuple[Any, ...], experiment_id: str) -> ExperimentEventV2:
    """Find the single v2 experiment that is registered with no later event."""
    by_id: dict[str, list[Any]] = {}
    for event in events:
        by_id.setdefault(event.experiment_id, []).append(event)
    if experiment_id not in by_id:
        raise OrchestratorError(
            f"no registered experiment {experiment_id!r} in the canonical registry"
        )
    history = by_id[experiment_id]
    stages = [e.event for e in history]
    if stages != [EVENT_REGISTERED]:
        raise OrchestratorError(
            f"experiment {experiment_id!r} is not awaiting execution (stages={stages}); an "
            "experiment id is single-use and cannot be re-run"
        )
    registered = history[0]
    if not isinstance(registered, ExperimentEventV2):
        raise OrchestratorError(
            f"experiment {experiment_id!r} is not a v2 registration; the orchestrator runs only "
            "v2 experiments"
        )
    return registered


def run_registered_development_experiment(
    repo_root: str | Path,
    experiment_id: str,
    *,
    clock: Callable[[], pd.Timestamp] | None = None,
) -> ExperimentEventV2:
    """Fail-closed: verify, append ``started``, run, publish, append ``completed``.

    Returns the ``completed`` event. Raises :class:`OrchestratorError` on any
    pre-start refusal (nothing is appended) or, after ``started``, appends a
    ``failed`` event and re-raises. The experiment id is single-use: a consumed
    id is never re-run.
    """
    now = clock if clock is not None else (lambda: pd.Timestamp.now(tz="UTC"))
    prep = _preflight(repo_root, experiment_id)
    registered = prep.registered_event

    # 16. Append and fsync 'started' before any real calculation.
    started = _event_with(registered, EVENT_STARTED, now(), prep.previous_line_sha256)
    append_registry_event(prep.repo_root / prep.registry_relpath, started)
    started_sha = sha256_bytes(started.to_json_line()[:-1])
    authorization = DevelopmentRunAuthorization(
        experiment_id=experiment_id,
        execution_code_commit_sha=prep.head,
        source_tree_fingerprint=prep.source_tree_fingerprint,
        started_event_sha256=started_sha,
        _token=_AUTH_SENTINEL,
    )
    try:
        detail = _evaluate_authorized(prep, authorization)
        completed = _publish_and_complete(prep, detail, authorization, now)
    except Exception as exc:
        _append_failed(prep, now, exc)
        raise OrchestratorError(
            f"experiment {experiment_id!r} failed after 'started': {exc}"
        ) from exc
    return completed


def _evaluate_authorized(
    prep: PreparedRun, authorization: DevelopmentRunAuthorization
) -> DevelopmentEvaluationDetail:
    """Reconstruct the dataset and run the walk-forward — requires authorization."""
    if not isinstance(authorization, DevelopmentRunAuthorization):  # pragma: no cover - defensive
        raise OrchestratorError("real-data evaluation requires a DevelopmentRunAuthorization")
    import tempfile

    from eth_research.develop_m3a import _canonical_attempt_id
    from eth_research.replay_m2b import reconstruct_dataset

    root = prep.repo_root
    attempt_id = _canonical_attempt_id(root)
    with tempfile.TemporaryDirectory() as tmp:
        manifest = reconstruct_dataset(root, attempt_id, tmp).build.manifest_path
        return evaluate_development_detailed(
            root,
            manifest,
            execution_code_commit_sha=prep.head,
            registered_code_commit_sha=prep.registered_event.registered_code_commit_sha,
            experiment_family_id=prep.registered_event.experiment_family,
        )


def _event_with(
    base: ExperimentEventV2,
    event: str,
    when: pd.Timestamp,
    previous_sha: str,
    *,
    results_json_sha256: str | None = None,
    report_markdown_sha256: str | None = None,
    return_evidence_sha256: str | None = None,
    result_bundle_sha256: str | None = None,
    failure_description: str | None = None,
) -> ExperimentEventV2:
    """A lifecycle event copying the registration's bound fields."""
    return ExperimentEventV2(
        registry_schema_version=base.registry_schema_version,
        event=event,
        experiment_id=base.experiment_id,
        experiment_family=base.experiment_family,
        corrects_experiment_id=base.corrects_experiment_id,
        correction_kind=base.correction_kind,
        hypothesis=base.hypothesis,
        strategies=base.strategies,
        cost_scenarios=base.cost_scenarios,
        methodology_id=base.methodology_id,
        development_partition_sha256=base.development_partition_sha256,
        walk_forward_protocol_path=base.walk_forward_protocol_path,
        walk_forward_protocol_sha256=base.walk_forward_protocol_sha256,
        package_version=base.package_version,
        registered_code_commit_sha=base.registered_code_commit_sha,
        execution_code_commit_sha=base.execution_code_commit_sha,
        execution_source_tree_fingerprint=base.execution_source_tree_fingerprint,
        event_time_utc=when,
        immutable_results_path=base.immutable_results_path,
        immutable_report_path=base.immutable_report_path,
        return_evidence_path=base.return_evidence_path,
        artifact_manifest_path=base.artifact_manifest_path,
        results_json_sha256=results_json_sha256,
        report_markdown_sha256=report_markdown_sha256,
        return_evidence_sha256=return_evidence_sha256,
        result_bundle_sha256=result_bundle_sha256,
        failure_description=failure_description,
        previous_event_sha256=previous_sha,
    )


def _append_failed(prep: PreparedRun, now: Callable[[], pd.Timestamp], exc: Exception) -> None:
    """Append a concise deterministic 'failed' event; the id stays consumed."""
    try:
        registry_path = prep.repo_root / prep.registry_relpath
        previous = latest_registry_line_sha256(registry_path)
        if previous is None:  # pragma: no cover
            return
        description = f"{type(exc).__name__}: {exc}"[:500]
        failed = _event_with(
            prep.registered_event, EVENT_FAILED, now(), previous, failure_description=description
        )
        append_registry_event(registry_path, failed)
    except (RegistryError, OrchestratorError, OSError):  # pragma: no cover - best effort
        # If the terminal append itself fails, 'started' remains and the id is
        # still consumed; a recovery verifier may finalize byte-identical output.
        return


def _publish_and_complete(
    prep: PreparedRun,
    detail: DevelopmentEvaluationDetail,
    authorization: DevelopmentRunAuthorization,
    now: Callable[[], pd.Timestamp],
) -> ExperimentEventV2:
    """Build, publish transactionally, verify, and append 'completed'.

    The completed event is built (from the artifact hashes) *before* the
    manifest, so the manifest can bind the exact completed-event bytes; the
    same event is appended after publication succeeds and verifies.
    """
    if not isinstance(authorization, DevelopmentRunAuthorization):  # pragma: no cover - defensive
        raise OrchestratorError("publication requires a DevelopmentRunAuthorization")
    from eth_research.development_publication import publish_run_artifacts, render_run_artifacts

    artifacts = render_run_artifacts(prep, detail)
    registry_path = prep.repo_root / prep.registry_relpath
    position = len(read_registry(registry_path)) + 1  # the completed event's 1-based line number
    previous = latest_registry_line_sha256(registry_path)
    if previous is None:  # pragma: no cover
        raise OrchestratorError("registry vanished before the completed append")
    completed = _event_with(
        prep.registered_event,
        EVENT_COMPLETED,
        now(),
        previous,
        results_json_sha256=artifacts.results_sha256,
        report_markdown_sha256=artifacts.report_sha256,
        return_evidence_sha256=artifacts.return_evidence_sha256,
        result_bundle_sha256=artifacts.bundle_sha256,
    )
    publish_run_artifacts(prep, artifacts, completed, position)
    append_registry_event(registry_path, completed)
    return completed
