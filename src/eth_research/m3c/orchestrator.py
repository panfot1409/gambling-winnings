"""Fail-closed orchestrator for the one preregistered M3C candidate run.

Two boundaries, each re-proving every precondition from scratch:

* :func:`register_m3c_run` appends the ``registered`` event — the
  pre-registration — after proving the repository is clean, the running source
  equals the committed source at HEAD, both sealed access ledgers are byte-empty,
  the committed protocol binds the committed lineage / budget / partition /
  dossier, and the registry carries no prior run-001 event.
* :func:`execute_and_publish_m3c_run` re-proves the same preconditions, re-reads
  the registry to confirm exactly one ``registered`` event whose bindings still
  match, appends ``started``, runs the 75-cell grid on the research-train
  partition (loaded integrity-only), reduces it through the one shared pipeline,
  proves determinism by an independent second rebuild (the mechanical P6 gate),
  evaluates the frozen promotion rule, renders the report, and publishes the
  results, decision, report, and manifest as one durable rollback-safe transaction
  with byte-readback, then appends ``completed`` carrying the four digests and the
  promotion verdict. A failure after ``started`` records an honest ``failed``
  event unless the run already durably published (then it is finalizable
  calculation-free), so a published success is never mislabeled a failure.

Nothing here can move money, reach the network, or read a development-gate or
final-holdout row: the loader returns research-train rows only, and both sealed
ledgers must be byte-empty for the orchestrator to run at all.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from eth_research import __version__
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.development import DEVELOPMENT_PARTITION_RELPATH, FROZEN_M2_DOSSIER_RELPATH
from eth_research.fractional.dataset import verify_dataset_integrity_only
from eth_research.gitcheck import (
    GitError,
    head_commit,
    is_commit_object,
    resolve_repo_root,
    source_tree_fingerprint,
    tracked_tree_is_clean,
    verify_package_source,
)
from eth_research.m3c.archive import (
    M3C_MANIFEST_RELPATH,
    M3C_MANIFEST_SCHEMA_VERSION,
    M3CArtifactManifest,
    bundle_sha256,
    verify_published_run,
)
from eth_research.m3c.candidate import CANDIDATE_FINGERPRINT, M3C_CANDIDATE_ID
from eth_research.m3c.completion import (
    CompletionArtifact,
    CompletionIntent,
    clear_completion_intent,
    write_completion_intent,
)
from eth_research.m3c.decision import M3C_DECISION_RELPATH, evaluate_candidate_decision
from eth_research.m3c.pipeline import reproduce_results
from eth_research.m3c.protocol import M3CProtocol, build_m3c_protocol, load_m3c_protocol
from eth_research.m3c.recovery import STATE_ALREADY_FINALIZED, STATE_FINALIZABLE
from eth_research.m3c.recovery import assess as assess_recovery
from eth_research.m3c.registry import (
    EVENT_COMPLETED,
    EVENT_FAILED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3C_REGISTRY_RELPATH,
    M3C_REGISTRY_SCHEMA_VERSION,
    M3CRegistryError,
    M3CRegistryEvent,
    append_registry_event,
    latest_registry_line_sha256,
    read_registry,
)
from eth_research.m3c.results import (
    M3C_EXPERIMENT_FAMILY,
    M3C_EXPERIMENT_ID,
    M3C_LINEAGE_RELPATH,
    M3C_PROTOCOL_RELPATH,
    M3C_REPORT_RELPATH,
    M3C_RESULTS_RELPATH,
    render_m3c_report,
)
from eth_research.publication import Artifact, durable_write_bytes, publish_batch
from eth_research.walkforward import WALK_FORWARD_PROTOCOL_RELPATH, load_walk_forward_protocol

# The two sealed access ledgers that must stay byte-empty for M3C to run.
DEVELOPMENT_GATE_LEDGER_RELPATH: str = "research/m3a/development_gate_access.jsonl"
FINAL_HOLDOUT_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"
_EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

M3C_BUDGET_RELPATH: str = "research/m3c/research_budget.json"

# The pre-registered research question. It is a characterization study of one
# adaptively motivated candidate — no alpha is claimed and nothing is optimized;
# it is bound into every registry event.
HYPOTHESIS: str = (
    "Characterize whether the dual-horizon trend-consensus candidate "
    "(63/252-day momentum with a 30-day 50% volatility target) beats buy-and-hold "
    "on the fixed research-train rolling-origin OOS folds under a causal execution "
    "proxy, using a preregistered fold-seam-aware bootstrap and a mechanical "
    "seven-part promotion rule. The candidate is adaptively motivated by prior "
    "trend results, so a passing primary yields only eligibility for an independent "
    "development-gate review; no alpha is claimed, no parameter is optimized, and "
    "this research-only measurement cannot move money."
)


class M3COrchestratorError(RuntimeError):
    """A fail-closed M3C orchestration refused to proceed."""


@dataclass(frozen=True)
class RepositoryPreconditions:
    """The run-agnostic, validated repository context for the M3C run."""

    repo_root: Path
    head: str
    source_tree_fingerprint: str
    protocol: M3CProtocol
    protocol_sha256: str
    lineage_sha256: str
    budget_sha256: str
    development_partition_sha256: str
    frozen_m2_dossier_sha256: str
    research_train_content_fingerprint: str
    package_version: str


def _verify_ledgers_byte_empty(root: Path) -> None:
    for relpath in (DEVELOPMENT_GATE_LEDGER_RELPATH, FINAL_HOLDOUT_LEDGER_RELPATH):
        path = root / relpath
        if not path.exists():
            raise M3COrchestratorError(f"sealed ledger {relpath} is missing")
        if path.is_symlink():
            raise M3COrchestratorError(
                f"sealed ledger {relpath} must be a real file, not a symlink"
            )
        if sha256_file(path) != _EMPTY_SHA256:
            raise M3COrchestratorError(
                f"sealed ledger {relpath} is not byte-empty — refusing to run"
            )


def _running_package_root() -> Path:
    import eth_research

    location = eth_research.__file__
    if location is None:  # pragma: no cover - namespace package, not our layout
        raise M3COrchestratorError("the running eth_research package has no filesystem location")
    return Path(location).resolve().parent


def verify_repository_preconditions(repo_root: str | Path) -> RepositoryPreconditions:
    """Run every run-agnostic fail-closed pre-check; return the derived context.

    Read-only. Raises :class:`M3COrchestratorError` on the first violation: canonical
    repo root, running-source == committed-source at a real HEAD, a clean tracked
    tree, both sealed ledgers byte-empty, a real (non-symlink) registry file, and a
    committed M3C protocol whose lineage / budget / partition / dossier bindings all
    equal the committed artifacts.
    """
    try:
        root = resolve_repo_root(repo_root)
    except GitError as exc:
        raise M3COrchestratorError(f"cannot resolve a git repository root: {exc}") from exc
    package_root = _running_package_root()
    if package_root != (root / "src/eth_research").resolve():
        raise M3COrchestratorError(
            f"the running package {package_root} is not this repository's src/eth_research"
        )
    if not tracked_tree_is_clean(root):
        raise M3COrchestratorError("the tracked working tree is dirty; refusing to run")
    head = head_commit(root)
    if not is_commit_object(root, head):
        raise M3COrchestratorError(f"HEAD {head!r} is not a real commit object")
    try:
        verify_package_source(root, head, package_root)
    except GitError as exc:
        raise M3COrchestratorError(f"running source does not match HEAD: {exc}") from exc
    fingerprint = source_tree_fingerprint(root, head)

    _verify_ledgers_byte_empty(root)

    registry_path = root / M3C_REGISTRY_RELPATH
    if not registry_path.exists():
        raise M3COrchestratorError(f"registry {M3C_REGISTRY_RELPATH} is missing")
    if registry_path.is_symlink():
        raise M3COrchestratorError("the registry must be a real file, not a symlink")

    protocol = load_m3c_protocol(root / M3C_PROTOCOL_RELPATH)
    protocol_sha = sha256_file(root / M3C_PROTOCOL_RELPATH)
    lineage_sha = sha256_file(root / M3C_LINEAGE_RELPATH)
    budget_sha = sha256_file(root / M3C_BUDGET_RELPATH)
    partition_sha = sha256_file(root / DEVELOPMENT_PARTITION_RELPATH)
    dossier_sha = sha256_file(root / FROZEN_M2_DOSSIER_RELPATH)
    if protocol.lineage_sha256 != lineage_sha:
        raise M3COrchestratorError("committed protocol does not bind the committed lineage")
    if protocol.budget_sha256 != budget_sha:
        raise M3COrchestratorError("committed protocol does not bind the committed budget")
    if protocol.development_partition_sha256 != partition_sha:
        raise M3COrchestratorError("committed protocol does not bind the committed dev partition")
    if protocol.frozen_m2_dossier_sha256 != dossier_sha:
        raise M3COrchestratorError("committed protocol does not bind the committed frozen dossier")

    return RepositoryPreconditions(
        repo_root=root,
        head=head,
        source_tree_fingerprint=fingerprint,
        protocol=protocol,
        protocol_sha256=protocol_sha,
        lineage_sha256=lineage_sha,
        budget_sha256=budget_sha,
        development_partition_sha256=partition_sha,
        frozen_m2_dossier_sha256=dossier_sha,
        research_train_content_fingerprint=protocol.research_train_content_fingerprint,
        package_version=protocol.package_version,
    )


def _registered_event(
    pre: RepositoryPreconditions, *, previous: str, event_time_utc: pd.Timestamp
) -> M3CRegistryEvent:
    return M3CRegistryEvent(
        registry_schema_version=M3C_REGISTRY_SCHEMA_VERSION,
        event=EVENT_REGISTERED,
        experiment_id=M3C_EXPERIMENT_ID,
        experiment_family=M3C_EXPERIMENT_FAMILY,
        hypothesis=HYPOTHESIS,
        candidate_id=M3C_CANDIDATE_ID,
        candidate_fingerprint=CANDIDATE_FINGERPRINT,
        strategies=pre.protocol.strategies,
        cost_scenarios=pre.protocol.cost_scenarios,
        protocol_path=M3C_PROTOCOL_RELPATH,
        protocol_sha256=pre.protocol_sha256,
        lineage_path=M3C_LINEAGE_RELPATH,
        lineage_sha256=pre.lineage_sha256,
        research_budget_path=M3C_BUDGET_RELPATH,
        research_budget_sha256=pre.budget_sha256,
        development_partition_sha256=pre.development_partition_sha256,
        frozen_m2_dossier_sha256=pre.frozen_m2_dossier_sha256,
        research_train_content_fingerprint=pre.research_train_content_fingerprint,
        package_version=pre.package_version,
        registered_code_commit_sha=pre.head,
        execution_code_commit_sha=pre.head,
        execution_source_tree_fingerprint=pre.source_tree_fingerprint,
        event_time_utc=event_time_utc,
        immutable_results_path=M3C_RESULTS_RELPATH,
        immutable_report_path=M3C_REPORT_RELPATH,
        immutable_decision_path=M3C_DECISION_RELPATH,
        artifact_manifest_path=M3C_MANIFEST_RELPATH,
        results_json_sha256=None,
        report_markdown_sha256=None,
        decision_json_sha256=None,
        result_bundle_sha256=None,
        promotion_status=None,
        failure_description=None,
        previous_event_sha256=previous,
    )


def register_m3c_run(repo_root: str | Path, *, event_time_utc: pd.Timestamp) -> M3CRegistryEvent:
    """Pre-register the one M3C candidate run (registry-only append)."""
    pre = verify_repository_preconditions(repo_root)
    registry_path = pre.repo_root / M3C_REGISTRY_RELPATH
    for event in read_registry(registry_path):
        if event.experiment_id == M3C_EXPERIMENT_ID:
            raise M3COrchestratorError(
                f"experiment id {M3C_EXPERIMENT_ID!r} already has a {event.event!r} event; "
                "an experiment id is single-use"
            )
    registered = _registered_event(
        pre, previous=latest_registry_line_sha256(registry_path), event_time_utc=event_time_utc
    )
    append_registry_event(registry_path, registered)
    return registered


def _require_matches_registered(pre: RepositoryPreconditions, registered: M3CRegistryEvent) -> None:
    """The frozen source and content bindings at execution must equal registration.

    The registered execution commit need not equal HEAD: the commit that appends
    the 'registered' line does not touch ``src/eth_research``, so its source-tree
    fingerprint is the one that runs, and that fingerprint (not the commit SHA) is
    the robust binding across the append.
    """
    if registered.execution_source_tree_fingerprint != pre.source_tree_fingerprint:
        raise M3COrchestratorError(
            "registered source-tree fingerprint disagrees with the running source"
        )
    if not is_commit_object(pre.repo_root, registered.execution_code_commit_sha):
        raise M3COrchestratorError("registered execution commit is not a real commit object")
    if (
        source_tree_fingerprint(pre.repo_root, registered.execution_code_commit_sha)
        != pre.source_tree_fingerprint
    ):
        raise M3COrchestratorError(
            "registered execution commit's source tree does not match the running source"
        )
    for label, got, want in (
        ("protocol", registered.protocol_sha256, pre.protocol_sha256),
        ("lineage", registered.lineage_sha256, pre.lineage_sha256),
        ("budget", registered.research_budget_sha256, pre.budget_sha256),
        ("partition", registered.development_partition_sha256, pre.development_partition_sha256),
        ("dossier", registered.frozen_m2_dossier_sha256, pre.frozen_m2_dossier_sha256),
    ):
        if got != want:
            raise M3COrchestratorError(
                f"registered {label} digest disagrees with the committed {label}"
            )


def execute_and_publish_m3c_run(
    repo_root: str | Path, *, event_time_utc: pd.Timestamp
) -> tuple[str, ...]:
    """Run the 75-cell grid once and publish the candidate run immutably.

    Returns the archive-verification checks proving the published run is internally
    consistent. Fails closed at every boundary; a failure after the ``started``
    event is recorded as an honest ``failed`` event unless the run already durably
    published (then it is finalizable calculation-free).
    """
    pre = verify_repository_preconditions(repo_root)
    root = pre.repo_root
    registry_path = root / M3C_REGISTRY_RELPATH

    run_events = [e for e in read_registry(registry_path) if e.experiment_id == M3C_EXPERIMENT_ID]
    if [e.event for e in run_events] != [EVENT_REGISTERED]:
        raise M3COrchestratorError(
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
        _run_and_publish(root, registered, started, event_time_utc)
    except Exception as exc:
        # Never mislabel a published success as 'failed'. If publication durably
        # landed — the completion intent is present and every recorded artifact is
        # verified on disk — the run is finalizable calculation-free, so refuse to
        # record 'failed' and direct the operator to the recovery finalizer.
        recovery = assess_recovery(root)
        if recovery.state in (STATE_FINALIZABLE, STATE_ALREADY_FINALIZED):
            raise M3COrchestratorError(
                f"run published but 'completed' was not appended before the failure ({exc}); "
                "finalize calculation-free with "
                "`python -m eth_research.m3c.recovery --repo-root <root> --finalize`"
            ) from exc
        # A genuine pre-publication failure: discard any unfulfilled intent and
        # record an honest 'failed' event, consuming the single-use id.
        clear_completion_intent(root)
        failed = dataclasses.replace(
            registered,
            event=EVENT_FAILED,
            event_time_utc=event_time_utc,
            failure_description=f"execution/publication failed: {type(exc).__name__}: {exc}"[:2000],
            previous_event_sha256=latest_registry_line_sha256(registry_path),
        )
        try:
            append_registry_event(registry_path, failed)
        except (M3CRegistryError, OSError) as append_exc:
            raise M3COrchestratorError(
                f"M3C run failed after 'started' and the failure record could not be appended "
                f"({append_exc}): {exc}"
            ) from exc
        raise M3COrchestratorError(
            f"M3C run failed after 'started' and was recorded: {exc}"
        ) from exc

    # Verify OUTSIDE the try: a post-completion consistency failure must surface its
    # own diagnostic, not be misrouted into the failure machinery.
    return verify_published_run(root)


def _run_and_publish(
    root: Path,
    registered: M3CRegistryEvent,
    started: M3CRegistryEvent,
    event_time_utc: pd.Timestamp,
) -> None:
    # Build the results from committed inputs bound to the registered provenance,
    # then prove determinism (the mechanical P6 gate) by an independent second
    # rebuild that must reproduce the exact same bytes.
    results = reproduce_results(root, registered)
    results_bytes = results.to_json_bytes()
    verification = reproduce_results(root, registered)
    verification_passed = verification.to_json_bytes() == results_bytes

    decision = evaluate_candidate_decision(results, verification_passed=verification_passed)
    decision_bytes = decision.to_json_bytes()
    report_bytes = render_m3c_report(results, decision).encode("utf-8")
    results_sha = sha256_bytes(results_bytes)
    report_sha = sha256_bytes(report_bytes)
    decision_sha = sha256_bytes(decision_bytes)
    bundle = bundle_sha256(results_bytes, report_bytes, decision_bytes)

    manifest = M3CArtifactManifest(
        manifest_schema_version=M3C_MANIFEST_SCHEMA_VERSION,
        experiment_id=M3C_EXPERIMENT_ID,
        experiment_family=M3C_EXPERIMENT_FAMILY,
        package_version=registered.package_version,
        results_path=M3C_RESULTS_RELPATH,
        results_sha256=results_sha,
        report_path=M3C_REPORT_RELPATH,
        report_sha256=report_sha,
        decision_path=M3C_DECISION_RELPATH,
        decision_sha256=decision_sha,
        bundle_sha256=bundle,
        promotion_status=decision.outcome,
        registered_event_sha256=sha256_bytes(registered.to_json_line()[:-1]),
        started_event_sha256=sha256_bytes(started.to_json_line()[:-1]),
    )
    manifest_bytes = manifest.to_json_bytes()

    artifacts = [
        Artifact(M3C_RESULTS_RELPATH, results_bytes, immutable=True),
        Artifact(M3C_DECISION_RELPATH, decision_bytes, immutable=True),
        Artifact(M3C_REPORT_RELPATH, report_bytes, immutable=True),
        Artifact(M3C_MANIFEST_RELPATH, manifest_bytes, immutable=True, is_completeness_marker=True),
    ]

    def _readback(published_root: Path) -> None:
        for relpath, expected in (
            (M3C_RESULTS_RELPATH, results_bytes),
            (M3C_DECISION_RELPATH, decision_bytes),
            (M3C_REPORT_RELPATH, report_bytes),
            (M3C_MANIFEST_RELPATH, manifest_bytes),
        ):
            if (published_root / relpath).read_bytes() != expected:
                raise M3COrchestratorError(f"byte-readback mismatch for {relpath}")

    # The 'completed' event chains onto the 'started' line (nothing appends between).
    started_line_sha = sha256_bytes(started.to_json_line()[:-1])
    completed = dataclasses.replace(
        registered,
        event=EVENT_COMPLETED,
        event_time_utc=event_time_utc,
        results_json_sha256=results_sha,
        report_markdown_sha256=report_sha,
        decision_json_sha256=decision_sha,
        result_bundle_sha256=bundle,
        promotion_status=decision.outcome,
        previous_event_sha256=started_line_sha,
    )

    # Record a durable completion intent BEFORE publishing: a crash after
    # publication but before the 'completed' append is then finalizable
    # calculation-free from the recorded event bytes and artifact digests.
    intent = CompletionIntent(
        experiment_id=M3C_EXPERIMENT_ID,
        completed_event_line=completed.to_json_line()[:-1],
        previous_event_sha256=started_line_sha,
        artifacts=(
            CompletionArtifact(M3C_RESULTS_RELPATH, results_sha),
            CompletionArtifact(M3C_DECISION_RELPATH, decision_sha),
            CompletionArtifact(M3C_REPORT_RELPATH, report_sha),
            CompletionArtifact(M3C_MANIFEST_RELPATH, sha256_bytes(manifest_bytes)),
        ),
    )
    write_completion_intent(root, intent)

    publish_batch(root, artifacts, verify=_readback)

    append_registry_event(root / M3C_REGISTRY_RELPATH, completed)
    clear_completion_intent(root)


def freeze_protocol(repo_root: str | Path, *, package_version: str = __version__) -> M3CProtocol:
    """Generate ``research/m3c/protocol.json`` and an empty registry (freeze step E).

    Derives the frozen protocol from the committed lineage / budget / partition /
    dossier and the research-train partition, writes it canonically, and creates the
    empty append-only registry file if it does not already exist. This is a one-time
    build action run before the freeze commit; it computes no strategy result.
    """
    root = resolve_repo_root(repo_root)
    research_train = verify_dataset_integrity_only(root).research_train
    wf_protocol = load_walk_forward_protocol(root / WALK_FORWARD_PROTOCOL_RELPATH)
    protocol = build_m3c_protocol(
        research_train=research_train,
        wf_protocol=wf_protocol,
        package_version=package_version,
        lineage_sha256=sha256_file(root / M3C_LINEAGE_RELPATH),
        budget_sha256=sha256_file(root / M3C_BUDGET_RELPATH),
        frozen_m2_dossier_sha256=sha256_file(root / FROZEN_M2_DOSSIER_RELPATH),
        development_partition_sha256=sha256_file(root / DEVELOPMENT_PARTITION_RELPATH),
    )
    durable_write_bytes(root / M3C_PROTOCOL_RELPATH, protocol.to_json_bytes())
    registry_path = root / M3C_REGISTRY_RELPATH
    if not registry_path.exists():
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        durable_write_bytes(registry_path, b"")
    return protocol


def _parse_event_time(value: str | None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp.now(tz="UTC")
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise M3COrchestratorError("--event-time must be timezone-aware (include a UTC offset)")
    return ts


def main(argv: list[str] | None = None) -> int:
    """CLI: freeze the protocol, pre-register, or execute-and-publish the run."""
    parser = argparse.ArgumentParser(
        prog="eth_research.m3c.orchestrator",
        description="Fail-closed lifecycle driver for the one preregistered M3C candidate run.",
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--event-time", default=None, help="ISO-8601 UTC event time (default: now)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", action="store_true", help="write the protocol + empty registry")
    group.add_argument("--register", action="store_true", help="append the 'registered' event")
    group.add_argument(
        "--execute", action="store_true", help="run once and publish the candidate artifacts"
    )
    args = parser.parse_args(argv)
    try:
        if args.freeze:
            protocol = freeze_protocol(args.repo_root)
            print(f"froze protocol for {protocol.experiment_id} ({M3C_PROTOCOL_RELPATH})")
            return 0
        event_time = _parse_event_time(args.event_time)
        if args.register:
            registered = register_m3c_run(args.repo_root, event_time_utc=event_time)
            print(f"registered {registered.experiment_id}")
            return 0
        checks = execute_and_publish_m3c_run(args.repo_root, event_time_utc=event_time)
        print(f"completed {M3C_EXPERIMENT_ID} — archive verified ({len(checks)} checks)")
        return 0
    except (M3COrchestratorError, M3CRegistryError, ValueError, GitError) as exc:
        print(f"orchestration refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
