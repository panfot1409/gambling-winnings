"""The update-proposal bundle: assembled offline, reviewed as a draft.

A proposal directory is the self-describing, reviewable evidence for one append-only
cohort extension. Two runner artifacts (staged by the two isolated runner jobs) sit
under ``runner_a/`` and ``runner_b/``; this module derives — entirely offline — the
three bound evidence documents:

* ``acquisition_comparison.json`` — the two-runner canonical-equality attestation;
* ``update_transition.json`` — the old → new append-only transition;
* ``proposal_manifest.json`` — the completeness marker binding the accepted base,
  the update plan + idempotency, the deterministic proposal branch, the comparison
  and transition hashes, the proposed-cohort fingerprint, the review policy
  (draft-only, human-required, no auto-merge, no retarget), and the explicit false
  governance flags (no strategy evaluated, no candidate, no metric, no promotion, no
  money moved).

Everything is a deterministic function of the runner artifacts and the committed
accepted base, so :func:`eth_research.m3e.verify_m3e_program.verify_update_proposal`
rebuilds it and requires a byte-for-byte match. This module computes no strategy
quantity and moves no money.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.m3e import M3E_PACKAGE_VERSION
from eth_research.m3e.accepted_base import AcceptedProspectiveBase, verify_accepted_base
from eth_research.m3e.comparison import AcquisitionComparison, compare_runners
from eth_research.m3e.lease import acquire_proposal_lease
from eth_research.m3e.runner_boundary import load_and_verify_runner
from eth_research.m3e.transition import ProspectiveUpdateTransition, build_update_transition
from eth_research.m3e.validation import (
    M3EValidationError,
    canonical_json_bytes,
    domain_sha256,
    require_mapping,
)

PROPOSAL_MANIFEST_NAME = "proposal_manifest.json"
COMPARISON_NAME = "acquisition_comparison.json"
TRANSITION_NAME = "update_transition.json"
RUNNER_A_DIR = "runner_a"
RUNNER_B_DIR = "runner_b"
PROPOSAL_MANIFEST_KIND = "prospective_update_proposal"
PROPOSAL_MANIFEST_SCHEMA_VERSION = 1
PROPOSAL_MANIFEST_DOMAIN = "m3e_update_proposal_manifest"

# The review policy every proposal declares. Formalized + guarded in
# eth_research.m3e.review_policy; embedded here so the manifest is self-describing.
REVIEW_POLICY = {
    "draft_required": True,
    "human_review_required": True,
    "auto_merge_forbidden": True,
    "retarget_forbidden": True,
    "modifies_accepted_branch": False,
}
# Explicit false governance flags: M3E evaluates nothing and moves no money.
GOVERNANCE_FLAGS = {
    "strategy_evaluated": False,
    "candidate_declared": False,
    "performance_metrics_computed": False,
    "promotion_decision_exists": False,
    "money_moved": False,
}


@dataclass(frozen=True)
class AssembledProposal:
    proposal_dir: Path
    comparison: AcquisitionComparison
    transition: ProspectiveUpdateTransition
    proposal_branch: str
    idempotency_key: str
    manifest_document: dict[str, Any]
    blobs: list[tuple[str, bytes]]


def _build_manifest_document(
    *,
    base: AcceptedProspectiveBase,
    comparison: AcquisitionComparison,
    transition: ProspectiveUpdateTransition,
    proposal_branch: str,
    lease_id: str,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": PROPOSAL_MANIFEST_SCHEMA_VERSION,
        "kind": PROPOSAL_MANIFEST_KIND,
        "package_version": M3E_PACKAGE_VERSION,
        "accepted_base_sha256": base.base_sha256,
        "accepted_base_fingerprint": base.canonical_content_fingerprint,
        "update_plan_sha256": comparison.plan_sha256,
        "idempotency_key": comparison.idempotency_key,
        "proposal_branch": proposal_branch,
        "lease_id": lease_id,
        "new_window": {
            "first_open": comparison.first_open,
            "last_open": comparison.last_open,
            "row_count": comparison.row_count,
            "fingerprint": comparison.new_window_fingerprint,
        },
        "comparison": {
            "comparison_sha256": comparison.comparison_sha256,
            "runners_isolated": comparison.runners_isolated,
            "runner_a_identity": list(comparison.runner_a_identity),
            "runner_b_identity": list(comparison.runner_b_identity),
        },
        "transition": {
            "transition_sha256": transition.transition_sha256,
            "old_row_count": transition.old_row_count,
            "old_last_open": transition.old_last_open,
            "new_window_row_count": transition.new_window_row_count,
            "proposed_row_count": transition.proposed_row_count,
            "proposed_last_open": transition.proposed_last_open,
            "proposed_cohort_fingerprint": transition.proposed_cohort_fingerprint,
            "is_append_only": transition.is_append_only,
        },
        "review_policy": dict(REVIEW_POLICY),
        "governance_flags": dict(GOVERNANCE_FLAGS),
    }
    document["manifest_sha256"] = domain_sha256(PROPOSAL_MANIFEST_DOMAIN, document)
    return document


def assemble_proposal(repo_root: str | Path, proposal_dir: str | Path) -> AssembledProposal:
    """Derive the comparison, transition, and manifest for a staged proposal directory.

    ``proposal_dir`` must already contain ``runner_a/`` and ``runner_b/`` (each a
    complete runner artifact). Returns the derived evidence and the ordered
    ``(relpath, bytes)`` blob list (manifest last, as the completeness marker).
    Purely offline; writes nothing.
    """
    root = Path(repo_root)
    directory = Path(proposal_dir)
    base = verify_accepted_base(root)

    runner_a = load_and_verify_runner(directory / RUNNER_A_DIR, runner_label="a")
    runner_b = load_and_verify_runner(
        directory / RUNNER_B_DIR, runner_label="b", expected_plan_sha256=runner_a.plan_sha256
    )
    comparison = compare_runners(runner_a, runner_b)
    transition = build_update_transition(
        root,
        base,
        new_window_rows=runner_a.canonical_rows,
        new_window_fingerprint=comparison.new_window_fingerprint,
    )
    lease = acquire_proposal_lease(
        idempotency_key=comparison.idempotency_key,
        plan_sha256=comparison.plan_sha256,
        first_missing_open=transition.new_window_first_open,
        completed_day_exclusive_end=_exclusive_end(transition),
    )
    manifest = _build_manifest_document(
        base=base,
        comparison=comparison,
        transition=transition,
        proposal_branch=lease.branch_name,
        lease_id=lease.lease_id,
    )
    blobs: list[tuple[str, bytes]] = [
        (COMPARISON_NAME, canonical_json_bytes(comparison.to_dict())),
        (TRANSITION_NAME, canonical_json_bytes(transition.to_dict())),
        (PROPOSAL_MANIFEST_NAME, canonical_json_bytes(manifest)),
    ]
    return AssembledProposal(
        proposal_dir=directory,
        comparison=comparison,
        transition=transition,
        proposal_branch=lease.branch_name,
        idempotency_key=comparison.idempotency_key,
        manifest_document=manifest,
        blobs=blobs,
    )


def _exclusive_end(transition: ProspectiveUpdateTransition) -> str:
    """The completed-day exclusive end = proposed last open + 1 day (ISO Z)."""
    import pandas as pd

    return (pd.Timestamp(transition.proposed_last_open) + pd.Timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def load_proposal_manifest(path: str | Path) -> dict[str, Any]:
    """Strictly load a committed proposal manifest and re-check its self-hash."""
    from eth_research.m3e.validation import load_canonical_json_bytes, require_str

    _raw, doc = load_canonical_json_bytes(Path(path), "proposal_manifest")
    mapping = require_mapping("proposal_manifest", doc)
    body = {k: v for k, v in mapping.items() if k != "manifest_sha256"}
    expected = domain_sha256(PROPOSAL_MANIFEST_DOMAIN, body)
    if require_str("manifest_sha256", mapping.get("manifest_sha256")) != expected:
        raise M3EValidationError("proposal manifest_sha256 does not match its content")
    return dict(mapping)
