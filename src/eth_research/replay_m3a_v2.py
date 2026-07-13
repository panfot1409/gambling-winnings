"""Byte-exact replay of the latest completed v2 experiment (Section 12, State B).

Once run-003 is completed and the compatibility aliases are migrated to schema
v2, ``develop_m3a --check`` and the CI registry verifier must reproduce the v2
archive rather than crash on the v1 parser. This module regenerates the v2
results and report **from the committed raw Coinbase bytes and the recorded
commit identities** (offline) and byte-compares them to the committed v2
compatibility aliases and immutable archive.

The regeneration mirrors the orchestrator's own evaluation + publication build:
the reconstructed :class:`~eth_research.development_orchestrator.PreparedRun` uses
the run-head commit and source fingerprint recorded *inside* the committed
results, and the registered event's methodology-freeze commit and family, so a
faithful re-run yields the exact published bytes. The recorded commit identities
themselves are checked against git history by the registry verifier; here we
prove deterministic reproduction. Read-only: it appends nothing and touches no
ledger.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from eth_research.development_results_v2 import load_development_results_v2
from eth_research.experiment_registry import (
    EVENT_COMPLETED,
    EVENT_REGISTERED,
    EXPERIMENT_REGISTRY_RELPATH,
    ExperimentEventV2,
    read_registry,
)


class ReplayV2Error(RuntimeError):
    """The committed v2 experiment did not reproduce from the committed inputs."""


def latest_completed_is_v2(root: str | Path) -> bool:
    """True iff the registry's most recent completed experiment is schema v2."""
    events = read_registry(Path(root) / EXPERIMENT_REGISTRY_RELPATH)
    completed = [e for e in events if e.event == EVENT_COMPLETED]
    if not completed:
        raise ReplayV2Error("no completed experiment in the registry")
    return isinstance(completed[-1], ExperimentEventV2)


def verify_v2_replay(root: str | Path) -> str:
    """Regenerate the latest completed v2 archive and byte-compare it. Returns the id.

    Raises :class:`ReplayV2Error` on any mismatch. Reproduces the results, report,
    and return evidence from the committed raw bytes + recorded identities and
    compares them to both the v2 compatibility aliases and the immutable archive.
    """
    from eth_research.develop_m3a import REPORT_RELPATH, RESULTS_RELPATH, _canonical_attempt_id
    from eth_research.development_evaluation import evaluate_development_detailed
    from eth_research.development_orchestrator import PreparedRun
    from eth_research.development_publication import render_run_artifacts
    from eth_research.replay_m2b import reconstruct_dataset

    root = Path(root)
    events = read_registry(root / EXPERIMENT_REGISTRY_RELPATH)
    completed = [e for e in events if e.event == EVENT_COMPLETED]
    if not completed:
        raise ReplayV2Error("no completed experiment in the registry")
    latest = completed[-1]
    if not isinstance(latest, ExperimentEventV2):
        raise ReplayV2Error("the latest completed experiment is not schema v2")
    registered = next(
        (
            e
            for e in events
            if e.experiment_id == latest.experiment_id and e.event == EVENT_REGISTERED
        ),
        None,
    )
    if not isinstance(registered, ExperimentEventV2):
        raise ReplayV2Error("the v2 completed experiment has no v2 registered event")

    committed = load_development_results_v2(root / RESULTS_RELPATH)
    if committed.experiment_id != latest.experiment_id:
        raise ReplayV2Error("the committed v2 alias is not the latest completed experiment")

    # Reconstruct the run context exactly as it was published: the run-head commit
    # and source fingerprint recorded inside the committed results, and the
    # registered event's methodology-freeze commit + family.
    prep = PreparedRun(
        repo_root=root,
        head=committed.run_head_commit_sha,
        source_tree_fingerprint=committed.execution_source_tree_fingerprint,
        registered_event=registered,
        registry_relpath=EXPERIMENT_REGISTRY_RELPATH,
        previous_line_sha256="0" * 64,  # unused by the artifact builder
    )
    attempt_id = _canonical_attempt_id(root)
    with tempfile.TemporaryDirectory() as tmp:
        manifest = reconstruct_dataset(root, attempt_id, tmp).build.manifest_path
        detail = evaluate_development_detailed(
            root,
            manifest,
            execution_code_commit_sha=prep.head,
            registered_code_commit_sha=registered.registered_code_commit_sha,
            experiment_family_id=registered.experiment_family,
        )
    artifacts = render_run_artifacts(prep, detail)

    comparisons = (
        ("v2 results alias", RESULTS_RELPATH, artifacts.results_bytes),
        ("v2 report alias", REPORT_RELPATH, artifacts.report_bytes),
        ("immutable results", registered.immutable_results_path, artifacts.results_bytes),
        ("immutable report", registered.immutable_report_path, artifacts.report_bytes),
        (
            "immutable return evidence",
            registered.return_evidence_path,
            artifacts.return_evidence_bytes,
        ),
    )
    for label, relpath, expected in comparisons:
        actual = (root / relpath).read_bytes()
        if actual != expected:
            raise ReplayV2Error(
                f"regenerated {label} does not match the committed bytes at {relpath}"
            )
    return latest.experiment_id
