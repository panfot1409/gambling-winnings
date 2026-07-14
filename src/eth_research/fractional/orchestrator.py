"""Fail-closed orchestrator for the one preregistered M3B fractional run.

Two boundaries, each re-proving every precondition from scratch:

* :func:`register_fractional_run` (Phase 18) appends the ``registered`` event —
  the pre-registration — after proving the repository is clean, the running
  source equals the committed source at HEAD, both sealed access ledgers are
  byte-empty, and the registry carries no prior run-001 event.
* :func:`execute_and_publish_fractional_run` (Phase 19) re-proves the same
  preconditions, re-reads the registry to confirm exactly one ``registered``
  event whose bindings still match the committed protocol / partition / dossier
  / frozen commit, appends ``started``, runs the 75-cell experiment on the
  research-train partition (loaded integrity-only), publishes the results, report,
  and manifest as one durable rollback-safe transaction with byte-readback, and
  appends ``completed`` carrying the artifact digests. A failure after ``started``
  records an honest ``failed`` event — the single-use id is then spent.

Nothing here can move money, reach the network, or read a development-gate or
final-holdout row: the loader returns research-train rows only, and the sealed
ledgers must be byte-empty for the orchestrator to run at all.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.development import DEVELOPMENT_PARTITION_RELPATH, FROZEN_M2_DOSSIER_RELPATH
from eth_research.fractional.archive import (
    FRACTIONAL_MANIFEST_RELPATH,
    FRACTIONAL_MANIFEST_SCHEMA_VERSION,
    FractionalArtifactManifest,
    bundle_sha256,
    verify_published_run,
)
from eth_research.fractional.dataset import verify_dataset_integrity_only
from eth_research.fractional.experiment import (
    build_fractional_results,
    compute_fractional_fold_cells,
)
from eth_research.fractional.protocol import (
    EXPERIMENT_FAMILY,
    FRACTIONAL_PROTOCOL_RELPATH,
    RUN_001_EXPERIMENT_ID,
    load_fractional_protocol,
)
from eth_research.fractional.registry import (
    EVENT_COMPLETED,
    EVENT_FAILED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3B_REGISTRY_RELPATH,
    M3B_REGISTRY_SCHEMA_VERSION,
    FractionalRegistryEvent,
    append_registry_event,
    latest_registry_line_sha256,
    read_registry,
)
from eth_research.fractional.results import (
    FRACTIONAL_REPORT_RELPATH,
    FRACTIONAL_RESULTS_RELPATH,
    render_fractional_report,
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
from eth_research.publication import Artifact, publish_batch
from eth_research.walkforward import WALK_FORWARD_PROTOCOL_RELPATH, load_walk_forward_protocol

# The two sealed access ledgers that must stay byte-empty for M3B to run.
DEVELOPMENT_GATE_LEDGER_RELPATH: str = "research/m3a/development_gate_access.jsonl"
FINAL_HOLDOUT_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"
_EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# The pre-registered research question. It is a characterization study — no alpha
# is claimed and nothing is optimized; it is bound into every registry event.
HYPOTHESIS: str = (
    "Characterize how exact fractional long-only ETH execution behaves under a "
    "compatibility cost model and two causal liquidity/impact proxy scenarios "
    "across five fixed strategies and five research-train rolling-origin OOS "
    "folds. No alpha is claimed; no parameter is optimized; this is a "
    "research-only measurement that cannot move money."
)


class OrchestratorError(RuntimeError):
    """A fail-closed fractional orchestration refused to proceed."""


@dataclass(frozen=True)
class RepositoryPreconditions:
    """The run-agnostic, validated repository context for the fractional run."""

    repo_root: Path
    head: str
    source_tree_fingerprint: str
    fractional_protocol_sha256: str
    development_partition_sha256: str
    frozen_m2_dossier_sha256: str
    package_version: str


def _verify_ledgers_byte_empty(root: Path) -> None:
    for relpath in (DEVELOPMENT_GATE_LEDGER_RELPATH, FINAL_HOLDOUT_LEDGER_RELPATH):
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


def verify_repository_preconditions(repo_root: str | Path) -> RepositoryPreconditions:
    """Run every run-agnostic fail-closed pre-check; return the derived context.

    Read-only. Raises :class:`OrchestratorError` on the first violation: canonical
    repo root, running-source == committed-source at a real HEAD, a clean tracked
    tree, both sealed ledgers byte-empty, a real (non-symlink) registry file, and
    a committed fractional protocol whose partition / dossier bindings load.
    """
    try:
        root = resolve_repo_root(repo_root)
    except GitError as exc:
        raise OrchestratorError(f"cannot resolve a git repository root: {exc}") from exc
    package_root = _running_package_root()
    if package_root != (root / "src/eth_research").resolve():
        raise OrchestratorError(
            f"the running package {package_root} is not this repository's src/eth_research"
        )
    if not tracked_tree_is_clean(root):
        raise OrchestratorError("the tracked working tree is dirty; refusing to run")
    head = head_commit(root)
    if not is_commit_object(root, head):
        raise OrchestratorError(f"HEAD {head!r} is not a real commit object")
    try:
        verify_package_source(root, head, package_root)
    except GitError as exc:
        raise OrchestratorError(f"running source does not match HEAD: {exc}") from exc
    fingerprint = source_tree_fingerprint(root, head)

    _verify_ledgers_byte_empty(root)

    registry_path = root / M3B_REGISTRY_RELPATH
    if not registry_path.exists():
        raise OrchestratorError(f"registry {M3B_REGISTRY_RELPATH} is missing")
    if registry_path.is_symlink():
        raise OrchestratorError("the registry must be a real file, not a symlink")

    protocol = load_fractional_protocol(root / FRACTIONAL_PROTOCOL_RELPATH)
    protocol_sha = sha256_file(root / FRACTIONAL_PROTOCOL_RELPATH)
    partition_sha = sha256_file(root / DEVELOPMENT_PARTITION_RELPATH)
    dossier_sha = sha256_file(root / FROZEN_M2_DOSSIER_RELPATH)
    if protocol.development_partition_sha256 != partition_sha:
        raise OrchestratorError("committed protocol does not bind the committed dev partition")
    if protocol.frozen_m2_dossier_sha256 != dossier_sha:
        raise OrchestratorError("committed protocol does not bind the committed frozen M2B dossier")
    if protocol.walk_forward_protocol_sha256 != sha256_file(root / WALK_FORWARD_PROTOCOL_RELPATH):
        raise OrchestratorError("committed protocol does not bind the committed walk-forward proto")

    return RepositoryPreconditions(
        repo_root=root,
        head=head,
        source_tree_fingerprint=fingerprint,
        fractional_protocol_sha256=protocol_sha,
        development_partition_sha256=partition_sha,
        frozen_m2_dossier_sha256=dossier_sha,
        package_version=protocol.package_version,
    )


def _registered_event(
    pre: RepositoryPreconditions, *, previous: str, event_time_utc: pd.Timestamp
) -> FractionalRegistryEvent:
    protocol = load_fractional_protocol(pre.repo_root / FRACTIONAL_PROTOCOL_RELPATH)
    return FractionalRegistryEvent(
        registry_schema_version=M3B_REGISTRY_SCHEMA_VERSION,
        event=EVENT_REGISTERED,
        experiment_id=RUN_001_EXPERIMENT_ID,
        experiment_family=EXPERIMENT_FAMILY,
        hypothesis=HYPOTHESIS,
        strategies=protocol.strategies,
        cost_scenarios=tuple(s.name for s in protocol.cost_scenarios),
        fractional_protocol_path=FRACTIONAL_PROTOCOL_RELPATH,
        fractional_protocol_sha256=pre.fractional_protocol_sha256,
        development_partition_sha256=pre.development_partition_sha256,
        frozen_m2_dossier_sha256=pre.frozen_m2_dossier_sha256,
        package_version=pre.package_version,
        registered_code_commit_sha=pre.head,
        execution_code_commit_sha=pre.head,
        execution_source_tree_fingerprint=pre.source_tree_fingerprint,
        event_time_utc=event_time_utc,
        immutable_results_path=FRACTIONAL_RESULTS_RELPATH,
        immutable_report_path=FRACTIONAL_REPORT_RELPATH,
        artifact_manifest_path=FRACTIONAL_MANIFEST_RELPATH,
        results_json_sha256=None,
        report_markdown_sha256=None,
        result_bundle_sha256=None,
        failure_description=None,
        previous_event_sha256=previous,
    )


def register_fractional_run(
    repo_root: str | Path, *, event_time_utc: pd.Timestamp
) -> FractionalRegistryEvent:
    """Phase 18: pre-register the one fractional run (registry-only append)."""
    pre = verify_repository_preconditions(repo_root)
    registry_path = pre.repo_root / M3B_REGISTRY_RELPATH
    for event in read_registry(registry_path):
        if event.experiment_id == RUN_001_EXPERIMENT_ID:
            raise OrchestratorError(
                f"experiment id {RUN_001_EXPERIMENT_ID!r} already has a {event.event!r} event; "
                "an experiment id is single-use"
            )
    registered = _registered_event(
        pre, previous=latest_registry_line_sha256(registry_path), event_time_utc=event_time_utc
    )
    append_registry_event(registry_path, registered)
    return registered


def _require_matches_registered(
    pre: RepositoryPreconditions, registered: FractionalRegistryEvent
) -> None:
    """The frozen source and content bindings at execution must equal registration.

    The registered execution commit need not equal HEAD: the commit that appends
    the 'registered' line does not touch ``src/eth_research``, so its source-tree
    fingerprint is the one that runs, and that fingerprint (not the commit SHA)
    is the robust binding across the append.
    """
    if registered.execution_source_tree_fingerprint != pre.source_tree_fingerprint:
        raise OrchestratorError(
            "registered source-tree fingerprint disagrees with the running source"
        )
    if not is_commit_object(pre.repo_root, registered.execution_code_commit_sha):
        raise OrchestratorError("registered execution commit is not a real commit object")
    if (
        source_tree_fingerprint(pre.repo_root, registered.execution_code_commit_sha)
        != pre.source_tree_fingerprint
    ):
        raise OrchestratorError(
            "registered execution commit's source tree does not match the running source"
        )
    if registered.fractional_protocol_sha256 != pre.fractional_protocol_sha256:
        raise OrchestratorError("registered protocol digest disagrees with the committed protocol")
    if registered.development_partition_sha256 != pre.development_partition_sha256:
        raise OrchestratorError("registered partition digest disagrees with the committed data")
    if registered.frozen_m2_dossier_sha256 != pre.frozen_m2_dossier_sha256:
        raise OrchestratorError("registered dossier digest disagrees with the committed dossier")


def execute_and_publish_fractional_run(
    repo_root: str | Path, *, event_time_utc: pd.Timestamp
) -> tuple[str, ...]:
    """Phase 19: run the 75-cell experiment once and publish it immutably.

    Returns the replay-verification checks proving the published run is
    internally consistent. Fails closed at every boundary; a failure after the
    ``started`` event is recorded as an honest ``failed`` event.
    """
    pre = verify_repository_preconditions(repo_root)
    root = pre.repo_root
    registry_path = root / M3B_REGISTRY_RELPATH

    run_events = [
        e for e in read_registry(registry_path) if e.experiment_id == RUN_001_EXPERIMENT_ID
    ]
    if [e.event for e in run_events] != [EVENT_REGISTERED]:
        raise OrchestratorError(
            f"run-001 must be exactly 'registered' before execution, found "
            f"{[e.event for e in run_events]!r}"
        )
    registered = run_events[0]
    _require_matches_registered(pre, registered)

    started = dataclasses.replace(
        registered,
        event=EVENT_STARTED,
        event_time_utc=event_time_utc,
        previous_event_sha256=latest_registry_line_sha256(registry_path),
    )
    append_registry_event(registry_path, started)

    try:
        checks = _run_and_publish(root, pre, registered, started, event_time_utc)
    except Exception as exc:
        failed = dataclasses.replace(
            registered,
            event=EVENT_FAILED,
            event_time_utc=event_time_utc,
            failure_description=f"execution/publication failed: {type(exc).__name__}: {exc}"[:2000],
            previous_event_sha256=latest_registry_line_sha256(registry_path),
        )
        append_registry_event(registry_path, failed)
        raise OrchestratorError(
            f"fractional run failed after 'started' and was recorded: {exc}"
        ) from exc
    return checks


def _run_and_publish(
    root: Path,
    pre: RepositoryPreconditions,
    registered: FractionalRegistryEvent,
    started: FractionalRegistryEvent,
    event_time_utc: pd.Timestamp,
) -> tuple[str, ...]:
    protocol = load_fractional_protocol(root / FRACTIONAL_PROTOCOL_RELPATH)
    wf_protocol = load_walk_forward_protocol(root / WALK_FORWARD_PROTOCOL_RELPATH)

    integrity = verify_dataset_integrity_only(root)
    research_train = integrity.research_train

    cells = compute_fractional_fold_cells(
        research_train, wf_protocol, initial_cash=protocol.initial_cash
    )
    results = build_fractional_results(
        fractional_protocol=protocol,
        research_train=research_train,
        fold_cells=cells,
        package_version=registered.package_version,
        # Bind the results to the registry's frozen execution commit (source-
        # identical to the running HEAD by the fingerprint check above), so the
        # registry and the results agree on the execution commit exactly.
        execution_code_commit_sha=registered.execution_code_commit_sha,
        registered_code_commit_sha=registered.registered_code_commit_sha,
        execution_source_tree_fingerprint=pre.source_tree_fingerprint,
        fractional_protocol_sha256=pre.fractional_protocol_sha256,
    )
    results_bytes = results.to_json_bytes()
    report_bytes = render_fractional_report(results).encode("utf-8")
    results_sha = sha256_bytes(results_bytes)
    report_sha = sha256_bytes(report_bytes)
    bundle = bundle_sha256(results_bytes, report_bytes)

    manifest = FractionalArtifactManifest(
        manifest_schema_version=FRACTIONAL_MANIFEST_SCHEMA_VERSION,
        experiment_id=RUN_001_EXPERIMENT_ID,
        experiment_family=EXPERIMENT_FAMILY,
        package_version=registered.package_version,
        results_path=FRACTIONAL_RESULTS_RELPATH,
        results_sha256=results_sha,
        report_path=FRACTIONAL_REPORT_RELPATH,
        report_sha256=report_sha,
        bundle_sha256=bundle,
        registered_event_sha256=sha256_bytes(registered.to_json_line()[:-1]),
        started_event_sha256=sha256_bytes(started.to_json_line()[:-1]),
    )
    manifest_bytes = manifest.to_json_bytes()

    artifacts = [
        Artifact(FRACTIONAL_RESULTS_RELPATH, results_bytes, immutable=True),
        Artifact(FRACTIONAL_REPORT_RELPATH, report_bytes, immutable=True),
        Artifact(
            FRACTIONAL_MANIFEST_RELPATH, manifest_bytes, immutable=True, is_completeness_marker=True
        ),
    ]

    def _readback(published_root: Path) -> None:
        for relpath, expected in (
            (FRACTIONAL_RESULTS_RELPATH, results_bytes),
            (FRACTIONAL_REPORT_RELPATH, report_bytes),
            (FRACTIONAL_MANIFEST_RELPATH, manifest_bytes),
        ):
            if (published_root / relpath).read_bytes() != expected:
                raise OrchestratorError(f"byte-readback mismatch for {relpath}")

    publish_batch(root, artifacts, verify=_readback)

    completed = dataclasses.replace(
        registered,
        event=EVENT_COMPLETED,
        event_time_utc=event_time_utc,
        results_json_sha256=results_sha,
        report_markdown_sha256=report_sha,
        result_bundle_sha256=bundle,
        previous_event_sha256=latest_registry_line_sha256(root / M3B_REGISTRY_RELPATH),
    )
    append_registry_event(root / M3B_REGISTRY_RELPATH, completed)

    return verify_published_run(root)
