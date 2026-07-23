"""The V2D activation anchor — the single committed switch for DATA-ONLY collection.

``governance/v2d/prospective_activation.json`` is a pure-constant, self-hashed record
of the human V2D authorization: which workflow may fetch, in which repository, with
which two job-scoped permission grants, over which cohort identity, under which
standing requirements and exclusions. :func:`verify_activation` is the fail-closed
runtime gate the standing update workflow runs **before any network step**:

* the committed anchor must be byte-identical to the constant rebuild (any tamper,
  weakening, or omission fails — there is no partially-valid anchor);
* the anchor must name exactly the running workflow basename and repository;
* the accepted prospective base must re-verify end-to-end from committed M3D bytes
  (:func:`eth_research.m3e.accepted_base.verify_accepted_base`);
* the base identity must match the anchored cohort identity, its row count must be
  at least the genesis row count, and the committed segment chain's genesis segment
  must still carry the anchored genesis fingerprint (growth may only append);
* evaluation must remain unauthorized, maturity lawful, and the three sealed
  ledgers byte-empty.

Static workflow-security guards define the reviewed *shape* of the mechanism; this
anchor is the runtime *switch*. Reverting the activation PR removes the anchor and
the wiring together (rollback). This module opens no socket, evaluates nothing,
and mutates nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eth_research.m3d.chain import load_and_verify_chain
from eth_research.m3d.segment import SEGMENTS_PATH
from eth_research.m3e.accepted_base import AcceptedProspectiveBase, verify_accepted_base
from eth_research.m3e.validation import (
    canonical_json_bytes,
    domain_sha256,
    load_canonical_json_bytes,
    require_mapping,
    require_str,
)

ANCHOR_RELPATH = "governance/v2d/prospective_activation.json"
ANCHOR_SCHEMA_VERSION = 1
ANCHOR_KIND = "v2d_prospective_activation"
ANCHOR_DOMAIN = "v2d_prospective_activation_anchor"

#: The one workflow this authorization activates, and where it may run.
AUTHORIZED_WORKFLOW_BASENAME = "m3e-prospective-update.yml"
AUTHORIZED_REPOSITORY = "panfot1409/gambling-winnings"

#: The immutable genesis identity of the accepted cohort this authorization grows.
GENESIS_CONTENT_FINGERPRINT = "bb6dd3921fa31915496806349ca21254e05070c94a97b30982030673b7966507"
GENESIS_ROW_COUNT = 3
_COHORT_START = "2026-07-12T00:00:00Z"
_PRODUCT = "ETH-USD"
_VENUE = "coinbase-exchange"
_INTERVAL_SECONDS = 86400
_MINIMUM_MATURITY_ROWS = 365

#: What the V2D authorization explicitly does NOT permit (verbatim scope items).
AUTHORIZATION_EXCLUSIONS: tuple[str, ...] = (
    "strategy or candidate creation",
    "backtesting or optimization",
    "reading any sealed partition",
    "evaluating prospective values",
    "paper, shadow, or live trading",
    "broker or exchange authentication",
    "order routing",
    "wallet access",
    "candidate nomination",
    "changing any historical result",
    "forcing paper_activation_authorized or sell_ready",
    "public publication",
)

#: The only two write grants the mechanism may hold, each scoped to one job.
JOB_PERMISSION_GRANTS: dict[str, tuple[str, ...]] = {
    "assemble_and_publish_bot_branch": ("contents: write",),
    "open_draft_pull_request": ("pull-requests: write",),
}

_SEALED_LEDGERS: tuple[str, ...] = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)


class V2DActivationError(RuntimeError):
    """The activation anchor is absent, tampered, weakened, or its gates do not hold."""


def build_activation_anchor_document() -> dict[str, Any]:
    """The activation anchor as a pure function of reviewed constants (no inputs)."""
    document: dict[str, Any] = {
        "schema_version": ANCHOR_SCHEMA_VERSION,
        "kind": ANCHOR_KIND,
        "milestone": "v2d",
        "authorized_on": "2026-07-23",
        "authorized_by": "repository owner — explicit V2D DATA-ONLY activation directive",
        "authorization_scope": (
            "Activate DATA-ONLY prospective collection: the minimum reviewed "
            "acquisition/proposal mechanism required to grow the accepted prospective "
            "cohort through independently attested, append-only, draft-reviewed update "
            "proposals. Nothing else."
        ),
        "authorization_exclusions": list(AUTHORIZATION_EXCLUSIONS),
        "cohort_identity": {
            "product": _PRODUCT,
            "venue": _VENUE,
            "interval_seconds": _INTERVAL_SECONDS,
            "cohort_start": _COHORT_START,
            "minimum_maturity_rows": _MINIMUM_MATURITY_ROWS,
            "genesis_row_count": GENESIS_ROW_COUNT,
            "genesis_content_fingerprint": GENESIS_CONTENT_FINGERPRINT,
        },
        "mechanism": {
            "workflow_basename": AUTHORIZED_WORKFLOW_BASENAME,
            "repository": AUTHORIZED_REPOSITORY,
            "job_permission_grants": {
                job: list(grants) for job, grants in sorted(JOB_PERMISSION_GRANTS.items())
            },
            "two_runner_independence_required": True,
            "artifact_transport_between_runner_jobs": True,
            "endpoint_from_committed_plan_only": True,
        },
        "review_policy": {
            "draft_required": True,
            "human_review_required": True,
            "auto_merge_forbidden": True,
            "retarget_forbidden": True,
            "modifies_accepted_branch": False,
        },
        "standing_requirements": {
            "append_only_growth_only": True,
            "evaluation_authorized_must_remain_false": True,
            "sealed_ledgers_must_remain_byte_empty": True,
            "strategy_evaluation_permanently_disabled": True,
            "values_never_exposed_to_strategy_code": True,
        },
    }
    document["anchor_sha256"] = domain_sha256(ANCHOR_DOMAIN, document)
    return document


def render_anchor_bytes() -> bytes:
    """Canonical committed bytes of the activation anchor."""
    return canonical_json_bytes(build_activation_anchor_document())


def load_activation_anchor(repo_root: str | Path) -> dict[str, Any]:
    """Strictly load the committed anchor and prove it byte-identical to the rebuild.

    Byte identity against the pure-constant rebuild is the strongest possible check:
    a tampered self-hash, a weakened flag, an added field, or a reworded exclusion
    all fail here. Raises :class:`V2DActivationError` on any problem.
    """
    path = Path(repo_root) / ANCHOR_RELPATH
    if not path.is_file():
        raise V2DActivationError(f"activation anchor missing: {ANCHOR_RELPATH} (NOT ACTIVATED)")
    try:
        raw, doc = load_canonical_json_bytes(path, "v2d_activation_anchor")
    except Exception as exc:
        raise V2DActivationError(f"activation anchor unreadable: {exc}") from exc
    mapping = require_mapping("v2d_activation_anchor", doc)
    if raw != render_anchor_bytes():
        raise V2DActivationError(
            "committed activation anchor does not match the reviewed constant rebuild"
        )
    body = {k: v for k, v in mapping.items() if k != "anchor_sha256"}
    if require_str("anchor_sha256", mapping.get("anchor_sha256")) != domain_sha256(
        ANCHOR_DOMAIN, body
    ):
        raise V2DActivationError("activation anchor self-hash does not match its content")
    return dict(mapping)


def _genesis_segment_fingerprint(repo_root: str | Path) -> tuple[str, str]:
    """(canonical fingerprint, first_open) of the committed chain's genesis segment."""
    try:
        _raw, records = load_and_verify_chain(repo_root, SEGMENTS_PATH)
    except Exception as exc:
        raise V2DActivationError(f"segment chain failed verification: {exc}") from exc
    if len(records) < 2:
        raise V2DActivationError("segment chain has no genesis segment")
    segment = require_mapping("genesis segment", records[1])
    return (
        require_str("canonical_content_fingerprint", segment.get("canonical_content_fingerprint")),
        require_str("first_open", segment.get("first_open")),
    )


def verify_activation(
    repo_root: str | Path,
    *,
    workflow_basename: str,
    repository: str,
) -> tuple[dict[str, Any], AcceptedProspectiveBase]:
    """The fail-closed runtime activation gate; raises before any fetch may proceed.

    Returns ``(anchor, verified_base)`` only when every gate holds. Called by the
    standing update workflow with its own basename + repository, and by tests.
    """
    root = Path(repo_root)
    anchor = load_activation_anchor(root)

    mechanism = require_mapping("mechanism", anchor["mechanism"])
    if require_str("workflow_basename", mechanism.get("workflow_basename")) != workflow_basename:
        raise V2DActivationError(
            f"anchor authorizes {mechanism.get('workflow_basename')!r}, "
            f"not the running workflow {workflow_basename!r}"
        )
    if workflow_basename != AUTHORIZED_WORKFLOW_BASENAME:
        raise V2DActivationError(f"workflow {workflow_basename!r} is not the authorized mechanism")
    if require_str("repository", mechanism.get("repository")) != repository:
        raise V2DActivationError(
            f"anchor authorizes repository {mechanism.get('repository')!r}, not {repository!r}"
        )
    if repository != AUTHORIZED_REPOSITORY:
        raise V2DActivationError(f"repository {repository!r} is not authorized")
    workflow_path = root / ".github/workflows" / workflow_basename
    if not workflow_path.is_file():
        raise V2DActivationError(f"authorized workflow file missing: {workflow_basename}")

    # The accepted base must re-verify end-to-end from committed M3D bytes.
    try:
        base = verify_accepted_base(root)
    except Exception as exc:
        raise V2DActivationError(f"accepted base failed verification: {exc}") from exc

    identity = require_mapping("cohort_identity", anchor["cohort_identity"])
    base_identity = require_mapping("identity", base.document["identity"])
    for field, expected in (
        ("product", identity["product"]),
        ("venue", identity["venue"]),
        ("interval_seconds", identity["interval_seconds"]),
    ):
        if base_identity.get(field) != expected:
            raise V2DActivationError(f"accepted base identity.{field} drifted from the anchor")
    if base.document["cohort_start"] != identity["cohort_start"]:
        raise V2DActivationError("accepted base cohort_start drifted from the anchor")
    if base.document["minimum_maturity_rows"] != identity["minimum_maturity_rows"]:
        raise V2DActivationError("accepted base maturity floor drifted from the anchor")
    if base.row_count < GENESIS_ROW_COUNT:
        raise V2DActivationError("accepted base row count fell below the genesis row count")

    # Growth may only append: the committed genesis segment still carries the
    # anchored genesis fingerprint and starts at the anchored cohort start.
    genesis_fp, genesis_first_open = _genesis_segment_fingerprint(root)
    if genesis_fp != GENESIS_CONTENT_FINGERPRINT:
        raise V2DActivationError("genesis segment fingerprint drifted from the anchored genesis")
    if genesis_first_open != identity["cohort_start"]:
        raise V2DActivationError("genesis segment does not start at the anchored cohort start")

    # Data-only invariants, re-asserted at runtime.
    if bool(base.document["evaluation_authorized"]):
        raise V2DActivationError("evaluation_authorized is true (HARD STOP — data-only)")
    maturity = require_str("maturity_state", base.document["maturity_state"])
    if maturity != "immature" and base.row_count < _MINIMUM_MATURITY_ROWS:
        raise V2DActivationError(f"unlawful maturity state {maturity!r} below the 365 floor")
    for rel in _SEALED_LEDGERS:
        ledger = root / rel
        if not ledger.is_file() or ledger.stat().st_size != 0:
            raise V2DActivationError(f"sealed ledger not byte-empty: {rel} (HARD STOP)")

    requirements = require_mapping("standing_requirements", anchor["standing_requirements"])
    for flag, value in requirements.items():
        if value is not True:
            raise V2DActivationError(f"standing requirement {flag!r} is weakened in the anchor")

    return anchor, base
