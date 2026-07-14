"""Build and transactionally publish the corrected run-003 artifacts (Phase 6/7).

Given the authorized, already-``started`` run context and its detailed
evaluation, this module assembles the v2 development results (reusing run-002's
per-fold financial cells verbatim, so they stay bit-identical), the fold-aware
bootstrap v2 cells, the per-run return evidence, and the Markdown report; then
it publishes the immutable run archive (results / report / return-evidence /
manifest), the updated experiment index, and the compatibility aliases as one
durable :func:`~eth_research.publication.publish_batch` transaction, reads them
back, strictly parses them, reconciles the return evidence, and verifies every
hash before the orchestrator appends ``completed``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from eth_research import __version__
from eth_research.bootstrap_v2 import (
    FoldAwareBootstrapConfig,
    fold_stratified_moving_block_bootstrap,
    hierarchical_fold_block_bootstrap,
    paired_excess_returns_from_folds,
)
from eth_research.data.provenance import sha256_bytes, sha256_file
from eth_research.development_evaluation import DevelopmentEvaluationDetail
from eth_research.development_results_v2 import (
    DEVELOPMENT_RESULTS_SCHEMA_VERSION_V2,
    BootstrapCellV2,
    DevelopmentResultsV2,
    load_development_results_v2,
    reconcile_results_v2_with_evidence,
    render_development_report_v2,
)
from eth_research.experiment_archive import (
    ARCHIVE_SCHEMA_VERSION,
    EXPERIMENT_INDEX_RELPATH,
    MATERIALIZATION_ORIGINAL,
    ArtifactManifest,
    ExperimentIndex,
    ExperimentIndexEntry,
    bundle_sha256,
    load_experiment_index,
)
from eth_research.experiment_registry import ExperimentEventV2, read_registry
from eth_research.methodology_v2 import METHODOLOGY_PROTOCOL_V2_RELPATH
from eth_research.publication import Artifact, publish_batch
from eth_research.return_evidence import ReturnEvidence, build_return_evidence
from eth_research.walkforward import WALK_FORWARD_PROTOCOL_RELPATH

if TYPE_CHECKING:
    from eth_research.development_orchestrator import PreparedRun

_ALIAS_RESULTS_RELPATH: str = "research/m3a/development_results.json"
_ALIAS_REPORT_RELPATH: str = "research/m3a/development_report.md"
_BUY_AND_HOLD: str = "buy_and_hold"


class PublicationBuildError(RuntimeError):
    """Building or verifying the run-003 artifacts failed."""


@dataclass(frozen=True)
class RunArtifacts:
    """The built, not-yet-published run bytes and their hashes."""

    results: DevelopmentResultsV2
    results_bytes: bytes
    report_bytes: bytes
    return_evidence: ReturnEvidence
    return_evidence_bytes: bytes
    results_sha256: str
    report_sha256: str
    return_evidence_sha256: str
    bundle_sha256: str


def _build_bootstrap_cells(
    detail: DevelopmentEvaluationDetail, strategies: tuple[str, ...], scenarios: tuple[str, ...]
) -> tuple[BootstrapCellV2, ...]:
    config = FoldAwareBootstrapConfig()
    cells: list[BootstrapCellV2] = []
    for sc in scenarios:
        bnh_folds = tuple(detail.fold_returns[(_BUY_AND_HOLD, sc)])
        for st in strategies:
            if st == _BUY_AND_HOLD:
                continue
            fold_excess = paired_excess_returns_from_folds(
                tuple(detail.fold_returns[(st, sc)]), bnh_folds
            )
            cells.append(
                BootstrapCellV2(
                    strategy=st,
                    cost_scenario=sc,
                    primary=fold_stratified_moving_block_bootstrap(fold_excess, config),
                    sensitivity=hierarchical_fold_block_bootstrap(fold_excess, config),
                )
            )
    return tuple(cells)


def render_run_artifacts(prep: PreparedRun, detail: DevelopmentEvaluationDetail) -> RunArtifacts:
    """Assemble the v2 results, return evidence, and report (no I/O to tracked paths)."""
    registered = prep.registered_event
    v1 = detail.results
    strategies = v1.strategies
    scenarios = v1.cost_scenarios

    evidence = build_return_evidence(
        experiment_id=registered.experiment_id,
        periods_per_year=detail.periods_per_year,
        research_train_last_open_time=detail.research_train_last_open_time,
        strategies=strategies,
        cost_scenarios=scenarios,
        fold_returns=detail.fold_returns,
    )
    evidence_bytes = evidence.to_json_bytes()

    methodology_sha = sha256_file(prep.repo_root / METHODOLOGY_PROTOCOL_V2_RELPATH)
    results = DevelopmentResultsV2(
        development_results_schema_version=DEVELOPMENT_RESULTS_SCHEMA_VERSION_V2,
        experiment_id=registered.experiment_id,
        experiment_family_id=registered.experiment_family,
        methodology_id=registered.methodology_id,
        package_version=__version__,
        # N8: distinct, unambiguous git-identity fields. The registered event's
        # execution commit (E) is the source whose tree runs; the run HEAD (R)
        # is the clean checkout the run started from (also the registration
        # container for run-003 — the registry-only commit does not change src,
        # so source fingerprints agree); the registered code commit froze the
        # methodology/protocol.
        execution_source_commit_sha=registered.execution_code_commit_sha,
        run_head_commit_sha=prep.head,
        methodology_freeze_commit_sha=registered.registered_code_commit_sha,
        execution_source_tree_fingerprint=prep.source_tree_fingerprint,
        frozen_m2_dossier_sha256=v1.frozen_m2_dossier_sha256,
        development_partition_sha256=v1.development_partition_sha256,
        walk_forward_protocol_path=WALK_FORWARD_PROTOCOL_RELPATH,
        walk_forward_protocol_sha256=v1.walk_forward_protocol_sha256,
        methodology_protocol_path=METHODOLOGY_PROTOCOL_V2_RELPATH,
        methodology_protocol_sha256=methodology_sha,
        dataset_content_fingerprint=v1.dataset_content_fingerprint,
        research_train_content_fingerprint=v1.research_train_content_fingerprint,
        strategies=strategies,
        cost_scenarios=scenarios,
        fold_results=v1.fold_results,
        independent_fold_summaries=v1.independent_fold_summaries,
        pooled_reset_oos=v1.pooled_reset_oos,
        full_train_exploratory=v1.full_train_exploratory,
        bootstrap_cells=_build_bootstrap_cells(detail, strategies, scenarios),
        return_evidence_path=registered.return_evidence_path,
        return_evidence_sha256=evidence.content_sha256(),
        development_gate_event_count=0,
        final_holdout_event_count=0,
    )
    results_bytes = results.to_json_bytes()
    report_bytes = render_development_report_v2(results).encode("utf-8")
    return RunArtifacts(
        results=results,
        results_bytes=results_bytes,
        report_bytes=report_bytes,
        return_evidence=evidence,
        return_evidence_bytes=evidence_bytes,
        results_sha256=sha256_bytes(results_bytes),
        report_sha256=sha256_bytes(report_bytes),
        return_evidence_sha256=sha256_bytes(evidence_bytes),
        bundle_sha256=bundle_sha256(results_bytes, report_bytes),
    )


def _build_manifest(
    prep: PreparedRun,
    artifacts: RunArtifacts,
    completed_event: ExperimentEventV2,
    position: int,
) -> ArtifactManifest:
    registered = prep.registered_event
    return ArtifactManifest(
        artifact_schema_version=ARCHIVE_SCHEMA_VERSION,
        experiment_id=registered.experiment_id,
        experiment_family=registered.experiment_family,
        results_schema_version=DEVELOPMENT_RESULTS_SCHEMA_VERSION_V2,
        materialization=MATERIALIZATION_ORIGINAL,
        source_commit=prep.head,
        results_relpath=registered.immutable_results_path,
        report_relpath=registered.immutable_report_path,
        return_evidence_relpath=registered.return_evidence_path,
        results_sha256=artifacts.results_sha256,
        report_sha256=artifacts.report_sha256,
        return_evidence_sha256=artifacts.return_evidence_sha256,
        bundle_sha256=artifacts.bundle_sha256,
        registry_event_position=position,
        registry_completed_event_sha256=sha256_bytes(completed_event.to_json_line()),
    )


def _updated_index(prep: PreparedRun, manifest: ArtifactManifest, position: int) -> ExperimentIndex:
    existing = load_experiment_index(prep.repo_root / EXPERIMENT_INDEX_RELPATH)
    manifest_bytes = manifest.to_json_bytes()
    entry = ExperimentIndexEntry(
        experiment_id=manifest.experiment_id,
        experiment_family=manifest.experiment_family,
        manifest_relpath=prep.registered_event.artifact_manifest_path,
        manifest_sha256=sha256_bytes(manifest_bytes),
        results_sha256=manifest.results_sha256,
        report_sha256=manifest.report_sha256,
        registry_event_position=position,
    )
    entries = sorted((*existing.entries, entry), key=lambda e: e.registry_event_position)
    return ExperimentIndex(archive_schema_version=ARCHIVE_SCHEMA_VERSION, entries=tuple(entries))


@dataclass(frozen=True)
class PreparedPublication:
    """The fully-built publication batch plus what the verify phase needs.

    Built before any bytes are written so the orchestrator can record a durable
    crash-recovery completion intent over the exact per-file bytes (N6) *before*
    it commits them.
    """

    artifacts: RunArtifacts
    batch: tuple[Artifact, ...]
    manifest_bytes: bytes


def build_publication_batch(
    prep: PreparedRun,
    artifacts: RunArtifacts,
    completed_event: ExperimentEventV2,
    position: int,
) -> PreparedPublication:
    """Assemble the immutable archive, aliases, manifest, and index as a batch.

    No I/O to tracked paths: it only builds the bytes and the ordered
    :class:`~eth_research.publication.Artifact` list that
    :func:`publish_prepared_batch` publishes transactionally.
    """
    registered = prep.registered_event
    manifest = _build_manifest(prep, artifacts, completed_event, position)
    manifest_bytes = manifest.to_json_bytes()
    index_bytes = _updated_index(prep, manifest, position).to_json_bytes()
    batch = (
        Artifact(registered.immutable_results_path, artifacts.results_bytes, immutable=True),
        Artifact(registered.immutable_report_path, artifacts.report_bytes, immutable=True),
        Artifact(registered.return_evidence_path, artifacts.return_evidence_bytes, immutable=True),
        Artifact(_ALIAS_RESULTS_RELPATH, artifacts.results_bytes, immutable=False),
        Artifact(_ALIAS_REPORT_RELPATH, artifacts.report_bytes, immutable=False),
        Artifact(
            registered.artifact_manifest_path,
            manifest_bytes,
            immutable=True,
            is_completeness_marker=True,
        ),
        Artifact(
            EXPERIMENT_INDEX_RELPATH, index_bytes, immutable=False, is_completeness_marker=True
        ),
    )
    return PreparedPublication(artifacts=artifacts, batch=batch, manifest_bytes=manifest_bytes)


def publish_prepared_batch(prep: PreparedRun, prepared: PreparedPublication) -> None:
    """Publish a prepared batch as one durable transaction, then verify it.

    Verify runs inside the transaction, before commit: a read-back / strict-parse
    / reconciliation failure rolls the whole publication back to the prior bytes
    (N4) instead of leaving a finished-looking archive and migrated aliases.
    """
    publish_batch(
        prep.repo_root,
        list(prepared.batch),
        verify=lambda _root: _verify_published(prep, prepared.artifacts, prepared.manifest_bytes),
    )


def _verify_published(prep: PreparedRun, artifacts: RunArtifacts, manifest_bytes: bytes) -> None:
    root = prep.repo_root
    registered = prep.registered_event
    checks = (
        (registered.immutable_results_path, artifacts.results_bytes),
        (registered.immutable_report_path, artifacts.report_bytes),
        (registered.return_evidence_path, artifacts.return_evidence_bytes),
        (registered.artifact_manifest_path, manifest_bytes),
        (_ALIAS_RESULTS_RELPATH, artifacts.results_bytes),
        (_ALIAS_REPORT_RELPATH, artifacts.report_bytes),
    )
    for relpath, expected in checks:
        if (root / relpath).read_bytes() != expected:
            raise PublicationBuildError(f"published {relpath} failed read-back verification")
    reloaded = load_development_results_v2(root / registered.immutable_results_path)
    if reloaded != artifacts.results:
        raise PublicationBuildError("published results v2 did not reparse to the built model")
    evidence = ReturnEvidence.from_json_bytes((root / registered.return_evidence_path).read_bytes())
    reconcile_results_v2_with_evidence(reloaded, evidence)
    # The registry must still parse cleanly with the run's registered event intact.
    read_registry(root / "research/m3a/experiment_registry.jsonl")
