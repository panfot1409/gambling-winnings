"""One strict, immutable dashboard state, derived only from canonical committed artifacts.

:func:`build_dashboard_state` is the single entry point. It consumes the existing
canonical parsers — never ad-hoc re-parsing — and fails closed with
:class:`DashboardStateError` on any inconsistency: malformed or duplicate-key JSON,
symlinked artifacts, unexpectedly nonempty sealed ledgers, accepted/proposed conflation,
a proposal checkout whose ancestry does not chain to the accepted base on disk, missing
required files, or any conflict between derived governance facts. It never repairs state.

The pending-proposal panel is populated only when the caller supplies
``proposal_checkout`` — a local read-only checkout (for example a git worktree) of the
bot proposal branch. Its ancestry is verified byte-for-byte: the proposal manifest's
``accepted_base_sha256``/``accepted_base_fingerprint`` must match the accepted base that
is committed in the served repository, and the recorded transition must be append-only
and arithmetically consistent. Anything else is a stale or wrong-parent proposal and the
whole build refuses.

The JSON status document (:func:`to_status_document`) contains only approved status
facts: no raw candles, no prices, no strategy internals, no environment values, no
filesystem paths, and no source text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eth_research._json import StrictJSONError
from eth_research.m3e.acceptance import AcceptanceError, load_acceptance_chain
from eth_research.m3e.accepted_base import AcceptedProspectiveBase, verify_accepted_base
from eth_research.m3e.cutoff import plan_update_window
from eth_research.m3e.proposal import load_proposal_manifest
from eth_research.m3e.status import build_status
from eth_research.m3e.validation import M3EValidationError
from eth_research.m3f.validation import (
    M3FValidationError,
    load_canonical_json,
    strict_jsonl_records,
)
from eth_research.v2.fable5.paper_readiness import (
    PAPER_READINESS_RELPATH,
    PaperReadinessError,
    PaperReadinessState,
    derive_paper_readiness,
    verify_paper_readiness,
)
from eth_research.v2d.activation import (
    ANCHOR_RELPATH,
    AUTHORIZED_REPOSITORY,
    V2DActivationError,
    load_activation_anchor,
)
from eth_research.v2e.paper import (
    PaperActivationRequirements,
    derive_requirements,
    derive_resting_state,
)
from eth_research.v2e.status import (
    NON_ADDITIVE_MARKERS,
    TIMELINE_LABEL,
    DashboardStateError,
    ProposalStatus,
    labels_for,
    row_count_statement,
    status_from_badge,
    status_from_claim,
    status_from_detail,
    status_from_heading,
    status_from_timeline_detail,
)

__all__ = [
    "REHEARSAL_BANNER",
    "SCHEMA_VERSION",
    "TARGET_ROWS",
    "DashboardState",
    "DashboardStateError",
    "ProposalStatus",
    "build_dashboard_state",
    "enforce_display_invariants",
    "to_status_document",
]

SCHEMA_VERSION = 1
TARGET_ROWS = 365

#: The exact rehearsal banner required by the V2E directive.
REHEARSAL_BANNER = "UI/OPERATIONS REHEARSAL — NOT PAPER TRADING"

_SEALED_LEDGERS: tuple[str, ...] = (
    "research/m2b/test_evaluations.jsonl",
    "research/m3a/development_gate_access.jsonl",
    "research/m3d/prospective_evaluations.jsonl",
)

_LIMITATIONS: tuple[str, ...] = (
    "Operational platform only — this dashboard displays governance state; it runs nothing.",
    "No eligible strategy candidate exists; nothing is nominated for paper trading.",
    "No paper-trading record exists; P&L is unavailable, which is absence of record, "
    "not zero performance.",
    "No live-trading record exists and no live capital is connected.",
    "No profitability claim is made anywhere on this surface.",
    "V2 is not sell-ready (sell_ready derives false).",
)


def _fail(label: str, exc: Exception) -> DashboardStateError:
    return DashboardStateError(f"{label}: {exc.__class__.__name__}: {exc}")


def _require_regular_file(root: Path, rel: str) -> Path:
    path = root / rel
    if path.is_symlink():
        raise DashboardStateError(f"{rel} is a symlink; canonical artifacts must be regular files")
    if not path.is_file():
        raise DashboardStateError(f"required canonical artifact missing: {rel}")
    return path


def _read_git_commit(repo_root: Path) -> str:
    """Resolve HEAD textually (no subprocess, no git execution)."""
    git = repo_root / ".git"
    if git.is_symlink():
        raise DashboardStateError(".git is a symlink; refusing")
    if git.is_file():  # worktree layout: "gitdir: <path>"
        pointer = git.read_text(encoding="utf-8").strip()
        if not pointer.startswith("gitdir: "):
            raise DashboardStateError("unrecognized .git file layout")
        git = (repo_root / pointer[len("gitdir: ") :]).resolve()
    head_path = git / "HEAD"
    if not head_path.is_file():
        raise DashboardStateError("git HEAD is unreadable; commit identity unavailable")
    head = head_path.read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return _require_sha(head)
    ref = head[len("ref: ") :].strip()
    loose = git / ref
    if loose.is_file():
        return _require_sha(loose.read_text(encoding="utf-8").strip())
    packed = git / "packed-refs"
    # A worktree's gitdir keeps packed-refs in the shared commondir.
    if not packed.is_file() and (git / "commondir").is_file():
        common = (git / (git / "commondir").read_text(encoding="utf-8").strip()).resolve()
        packed = common / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref) and not line.startswith("#"):
                return _require_sha(line.split(" ", 1)[0])
    raise DashboardStateError(f"git ref {ref!r} could not be resolved textually")


def _require_sha(value: str) -> str:
    if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise DashboardStateError("git HEAD did not resolve to a 40-hex commit id")
    return value


def _require_digest(value: object, label: str) -> str:
    """A 64-hex digest, validated rather than coerced.

    Bare ``str()`` would turn a malformed record field into a harmless-looking string
    that simply fails to compare; an anchor that cannot be parsed must fail loudly.
    """
    if not isinstance(value, str) or len(value) != 64:
        raise DashboardStateError(f"{label} is not a 64-hex digest")
    if any(c not in "0123456789abcdef" for c in value):
        raise DashboardStateError(f"{label} is not a 64-hex digest")
    return value


@dataclass(frozen=True, slots=True)
class RepoIdentity:
    repository: str
    version: str
    commit: str
    private_local_only: bool


@dataclass(frozen=True, slots=True)
class CohortPanel:
    accepted_row_count: int
    target_row_count: int
    progress_percent: str
    accepted_first_open: str
    accepted_last_open: str
    remaining_rows: int
    maturity_state: str
    evaluation_authorized: bool
    accepted_fingerprint: str


@dataclass(frozen=True, slots=True)
class ProposalPanel:
    configured: bool
    detail: str
    proposal_id: str | None = None
    proposal_branch: str | None = None
    proposed_row_count: int | None = None
    new_completed_days: int | None = None
    proposed_last_open: str | None = None
    append_only: bool | None = None
    ancestry_verified: bool | None = None
    #: THE canonical status. Derived exactly once (in :func:`_proposal_panel`) from
    #: verified evidence; every surface reads this value and none computes its own.
    #: ``None`` only when no proposal checkout is configured — there is then no local
    #: proposal to have a status, which is not the same as "pending".
    status: ProposalStatus | None = None
    #: Identity of the bundle actually on disk (its self-hashed manifest).
    manifest_sha256: str | None = None
    #: Identity the verified acceptance record pins. Present if and only if the status
    #: is :attr:`ProposalStatus.ACCEPTED`; equal to :attr:`manifest_sha256` when so.
    accepted_manifest_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionPanel:
    schedule_enabled: bool
    standing_workflow: str
    last_registry_entry_kind: str
    last_live_run: str
    last_live_outcome: str
    two_runner_agreement: str
    append_only_result: str
    next_due_status: str
    direct_main_writes: bool
    draft_review_required: bool


@dataclass(frozen=True, slots=True)
class IntegrityPanel:
    sealed_ledgers: dict[str, str]
    accepted_base_verified: bool
    v2a_results_verified: bool
    v2b_results_verified: bool
    v2c_oq_registry: str
    fable5_paper_readiness_verified: bool
    v2d_activation_anchor_valid: bool
    source_freeze_present: bool
    proposal_verification: str


@dataclass(frozen=True, slots=True)
class CandidatePanel:
    nominated_candidate: str
    eligible_candidate_present: bool
    paper_release_candidate_frozen: bool
    human_activation_approval: bool
    paper_activation_authorized: bool
    paper_trading_active: bool
    sell_ready: bool
    blocking_gates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PaperEnginePanel:
    engine_status: str
    mode: str
    exposure: str
    open_positions: int
    pending_orders: int
    fills: int
    pnl: str
    kill_switch: str
    lifecycle_state: str
    blocking_requirements: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class DashboardState:
    schema_version: int
    generated_at: str
    identity: RepoIdentity
    cohort: CohortPanel
    proposal: ProposalPanel
    acquisition: AcquisitionPanel
    integrity: IntegrityPanel
    candidate: CandidatePanel
    paper_engine: PaperEnginePanel
    timeline: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...] = field(default=_LIMITATIONS)


def _sealed_ledger_facts(root: Path) -> dict[str, str]:
    facts: dict[str, str] = {}
    for rel in _SEALED_LEDGERS:
        path = _require_regular_file(root, rel)
        size = path.stat().st_size
        if size != 0:
            raise DashboardStateError(
                f"sealed ledger {rel} is unexpectedly nonempty ({size} bytes); refusing"
            )
        facts[rel] = "byte-empty (0 bytes)"
    return facts


def _verified_paper_readiness(root: Path) -> PaperReadinessState:
    committed_path = _require_regular_file(root, PAPER_READINESS_RELPATH)
    try:
        committed = load_canonical_json(committed_path.read_bytes(), PAPER_READINESS_RELPATH)
    except (M3FValidationError, StrictJSONError, ValueError) as exc:
        raise _fail(PAPER_READINESS_RELPATH, exc) from exc
    if not isinstance(committed, dict):
        raise DashboardStateError(f"{PAPER_READINESS_RELPATH} is not a JSON object")
    try:
        return verify_paper_readiness(root, committed)
    except PaperReadinessError as exc:
        raise _fail("paper-readiness verification", exc) from exc


def _load_strict_object(root: Path, rel: str) -> dict[str, Any]:
    path = _require_regular_file(root, rel)
    try:
        doc = load_canonical_json(path.read_bytes(), rel)
    except (M3FValidationError, StrictJSONError, ValueError) as exc:
        raise _fail(rel, exc) from exc
    if not isinstance(doc, dict):
        raise DashboardStateError(f"{rel} is not a JSON object")
    return doc


def _require_strict_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DashboardStateError(f"{label} must be a JSON integer")
    return value


def _require_subset(embedded: dict[str, Any], on_disk: dict[str, Any], label: str) -> None:
    """Every field the self-hashed manifest embeds must match the side file byte-for-byte."""
    for key, value in embedded.items():
        if on_disk.get(key) != value:
            raise DashboardStateError(
                f"proposal {label} file disagrees with the self-hashed manifest at {key!r}"
            )


def _acceptance_anchor(root: Path, proposal_id: str) -> dict[str, Any] | None:
    """The verified acceptance anchors for ``proposal_id``, or ``None`` if still pending.

    Loading the chain re-verifies it (hash chain, per-record self-hashes, and the
    read-time semantic re-derivation), so a resealed or forged record fails here rather
    than being displayed as an accepted cohort.
    """
    try:
        entries = load_acceptance_chain(root)
    except (AcceptanceError, M3EValidationError, StrictJSONError, OSError, ValueError) as exc:
        raise _fail("acceptance chain", exc) from exc
    for entry in entries:
        if entry.proposal_id != proposal_id:
            continue
        try:
            previous = entry.record["previous_accepted"]
            new = entry.record["new_accepted"]
            return {
                "base_sha256": str(previous["base_sha256"]),
                "canonical_content_fingerprint": str(previous["canonical_content_fingerprint"]),
                "row_count": _require_strict_int(previous["row_count"], "previous.row_count"),
                "last_open": str(previous["last_open"]),
                "new_base_sha256": _require_digest(new["base_sha256"], "new_accepted.base_sha256"),
                "new_fingerprint": _require_digest(
                    new["canonical_content_fingerprint"], "new_accepted.fingerprint"
                ),
                # Bundle identity. Without these the ONLY link between the bundle on
                # disk and the acceptance record is the proposal directory NAME, so a
                # substituted or stale bundle rendered as "accepted, chain verified".
                "proposal_manifest_sha256": _require_digest(
                    entry.record["proposal_manifest_sha256"], "proposal_manifest_sha256"
                ),
                "proposed_cohort_fingerprint": _require_digest(
                    entry.record["proposed_cohort_fingerprint"], "proposed_cohort_fingerprint"
                ),
                "transition_sha256": _require_digest(
                    entry.record["transition_sha256"], "transition_sha256"
                ),
            }
        except (KeyError, TypeError) as exc:
            raise DashboardStateError(
                f"acceptance record for {proposal_id} is missing required anchors: {exc}"
            ) from exc
    return None


def _proposal_panel(
    root: Path, accepted: AcceptedProspectiveBase, checkout: Path | None
) -> ProposalPanel:
    if checkout is None:
        return ProposalPanel(configured=False, detail=labels_for(None).detail, status=None)
    checkout = Path(checkout)
    if checkout.is_symlink() or not checkout.is_dir():
        raise DashboardStateError("proposal checkout must be a real local directory")
    proposals_dir = checkout / "research/m3e/proposals"
    if (
        proposals_dir.is_symlink()
        or (checkout / "research").is_symlink()
        or (checkout / "research/m3e").is_symlink()
    ):
        raise DashboardStateError("proposal checkout path contains a symlink; refusing")
    if not proposals_dir.is_dir():
        raise DashboardStateError("proposal checkout has no research/m3e/proposals directory")
    entries = sorted(proposals_dir.iterdir())
    if any(entry.is_symlink() for entry in entries):
        raise DashboardStateError("proposal checkout contains a symlinked proposal entry")
    entries = [entry for entry in entries if entry.is_dir()]
    if len(entries) != 1:
        raise DashboardStateError(
            f"expected exactly one proposal in the checkout, found {len(entries)}"
        )
    pdir = entries[0]
    rel = f"research/m3e/proposals/{pdir.name}"
    try:
        manifest = dict(load_proposal_manifest(pdir / "proposal_manifest.json"))
    except (M3EValidationError, StrictJSONError, OSError, ValueError) as exc:
        raise _fail(f"{rel}/proposal_manifest.json", exc) from exc
    transition = _load_strict_object(checkout, f"{rel}/update_transition.json")
    comparison = _load_strict_object(checkout, f"{rel}/acquisition_comparison.json")

    # A proposal is either still pending or already accepted, and the two are checked
    # against DIFFERENT exact anchors -- never against a loose "anything newer is fine"
    # rule. Pending: the proposal must chain to the base accepted right now. Accepted:
    # it must chain to the exact pre-acceptance base pinned in its acceptance record AND
    # its proposed state must equal the base accepted right now, exactly. The accepted
    # branch is therefore strictly more binding: it pins both ends of the transition.
    prior = _acceptance_anchor(root, pdir.name)

    try:
        if manifest.get("kind") != "prospective_update_proposal":
            raise DashboardStateError("proposal manifest kind is not a prospective update")
        flags = manifest["governance_flags"]
        if not isinstance(flags, dict) or any(value is not False for value in flags.values()):
            raise DashboardStateError("proposal manifest governance flags are not all false")
        review = manifest["review_policy"]
        if not isinstance(review, dict) or review.get("draft_required") is not True:
            raise DashboardStateError("proposal review policy does not require a draft")
        if review.get("auto_merge_forbidden") is not True:
            raise DashboardStateError("proposal review policy does not forbid auto-merge")
        if prior is not None:
            # IDENTITY FIRST. The directory name is not identity: bind the bundle on
            # disk to the artifact the acceptance record actually pins, before any
            # claim of acceptance is made about it. A forger who edits the bundle and
            # re-seals `manifest_sha256` (as any forger would) is caught here.
            if manifest.get("manifest_sha256") != prior["proposal_manifest_sha256"]:
                raise DashboardStateError(
                    "proposal bundle is not the artifact this acceptance record accepted: "
                    "its manifest hash does not match the record's pinned "
                    "proposal_manifest_sha256"
                )
            if (
                transition.get("proposed_cohort_fingerprint")
                != prior["proposed_cohort_fingerprint"]
            ):
                raise DashboardStateError(
                    "accepted proposal's cohort fingerprint does not match the acceptance record"
                )
            if transition.get("transition_sha256") != prior["transition_sha256"]:
                raise DashboardStateError(
                    "accepted proposal's transition hash does not match the acceptance record"
                )
        # The base this proposal must declare as its parent.
        parent_sha = accepted.base_sha256 if prior is None else prior["base_sha256"]
        parent_fingerprint = (
            accepted.canonical_content_fingerprint
            if prior is None
            else prior["canonical_content_fingerprint"]
        )
        parent_rows = accepted.row_count if prior is None else prior["row_count"]
        parent_last_open = accepted.last_open if prior is None else prior["last_open"]
        if manifest.get("accepted_base_sha256") != parent_sha:
            raise DashboardStateError(
                "stale or wrong-parent proposal: its accepted_base_sha256 does not match the "
                + (
                    "accepted base committed in this repository"
                    if prior is None
                    else "pre-acceptance base pinned in its acceptance record"
                )
            )
        if manifest.get("accepted_base_fingerprint") != parent_fingerprint:
            raise DashboardStateError("proposal ancestry fingerprint mismatch; refusing")
        embedded_transition = manifest["transition"]
        embedded_comparison = manifest["comparison"]
        if not isinstance(embedded_transition, dict) or not isinstance(embedded_comparison, dict):
            raise DashboardStateError("proposal manifest transition/comparison blocks malformed")
        # The side files are display sources; the self-hashed manifest is the authority.
        _require_subset(embedded_transition, transition, "transition")
        _require_subset(embedded_comparison, comparison, "comparison")
        if transition.get("is_append_only") is not True:
            raise DashboardStateError("proposal transition is not append-only; refusing")
        if comparison.get("canonical_content_match") is not True:
            raise DashboardStateError("proposal runner comparison does not record a byte match")
        if comparison.get("runners_isolated") is not True:
            raise DashboardStateError("proposal runner comparison does not record isolated runners")
        old_rows = _require_strict_int(transition["old_row_count"], "old_row_count")
        new_rows = _require_strict_int(transition["new_window_row_count"], "new_window_row_count")
        proposed_rows = _require_strict_int(transition["proposed_row_count"], "proposed_row_count")
        proposed_last_open = str(transition["proposed_last_open"])
        if transition.get("old_fingerprint") != parent_fingerprint:
            raise DashboardStateError("proposal transition old fingerprint mismatch; refusing")
        if transition.get("old_last_open") != parent_last_open:
            raise DashboardStateError("proposal transition old last-open mismatch; refusing")
        if new_rows < 1 or old_rows != parent_rows or old_rows + new_rows != proposed_rows:
            raise DashboardStateError(
                "proposal row arithmetic conflates accepted and proposed state"
            )
        if proposed_last_open <= parent_last_open:
            raise DashboardStateError("proposal does not extend the cohort forward in time")
        if prior is not None:
            # Accepted: the proposed state must BE the accepted state, exactly. Anything
            # else means the tree and the acceptance record disagree about what landed.
            if proposed_rows != accepted.row_count:
                raise DashboardStateError(
                    "accepted proposal row count does not equal the accepted cohort on disk"
                )
            if proposed_last_open != accepted.last_open:
                raise DashboardStateError(
                    "accepted proposal last-open does not equal the accepted cohort on disk"
                )
            if prior["new_base_sha256"] != accepted.base_sha256:
                raise DashboardStateError(
                    "acceptance record's resulting base does not match the accepted base on disk"
                )
            if prior["new_fingerprint"] != accepted.canonical_content_fingerprint:
                raise DashboardStateError(
                    "acceptance record's resulting fingerprint does not match the accepted base"
                )
        branch = str(manifest["proposal_branch"])
        bundle_identity = _require_digest(manifest.get("manifest_sha256"), "proposal manifest hash")
    except KeyError as exc:
        raise DashboardStateError(f"proposal bundle is missing required field {exc}") from exc

    # THE SINGLE DERIVATION of proposal status in the whole program. Every surface —
    # headline, badge, acceptance claim, row labels, timeline, integrity and acquisition
    # prose — reads this one value through eth_research.v2e.status.LABELS. A verified
    # acceptance record (checked above, identity-bound) is the only thing that can
    # produce ACCEPTED; its absence is exactly what PROPOSED means. Rejection and
    # supersession have no committed evidence source today, so they are never derived
    # here: an unrecognised ancestry fails closed above rather than being guessed at.
    status = ProposalStatus.PROPOSED if prior is None else ProposalStatus.ACCEPTED
    return ProposalPanel(
        configured=True,
        detail=labels_for(status).detail,
        proposal_id=pdir.name,
        proposal_branch=branch,
        proposed_row_count=proposed_rows,
        new_completed_days=new_rows,
        proposed_last_open=proposed_last_open,
        append_only=True,
        ancestry_verified=True,
        status=status,
        manifest_sha256=bundle_identity,
        accepted_manifest_sha256=None if prior is None else prior["proposal_manifest_sha256"],
    )


def _acquisition_panel(
    root: Path,
    status: dict[str, Any],
    accepted: AcceptedProspectiveBase,
    proposal: ProposalPanel,
    now_utc: str,
) -> AcquisitionPanel:
    posture = status.get("workflow_posture")
    if not isinstance(posture, dict) or posture.get("active") is not True:
        raise DashboardStateError("workflow posture is not active; V2D anchor state conflict")
    registry = status.get("registry")
    if not isinstance(registry, dict):
        raise DashboardStateError("m3e status registry block malformed")
    try:
        window = plan_update_window(accepted, now_utc)
    except (M3EValidationError, ValueError) as exc:
        raise _fail("next-due computation", exc) from exc
    if window.is_noop:
        next_due = f"nothing due yet ({window.reason})"
    else:
        next_due = (
            f"update due now: {window.expected_new_buckets} completed day(s) through "
            f"{window.window_end}"
        )
    # Read from the canonical status; never re-decide acceptance on this surface.
    labels = labels_for(proposal.status)
    agreement = labels.two_runner_agreement
    append_result = labels.acquisition_append_result
    return AcquisitionPanel(
        schedule_enabled=True,
        standing_workflow=str(posture.get("standing_update_workflow", "")),
        last_registry_entry_kind=str(registry.get("last_entry_kind", "")),
        last_live_run=str(posture.get("last_live_run", "")),
        last_live_outcome=str(posture.get("last_live_outcome", "")),
        two_runner_agreement=agreement,
        append_only_result=append_result,
        next_due_status=next_due,
        direct_main_writes=False,
        draft_review_required=True,
    )


def _integrity_panel(
    root: Path,
    sealed: dict[str, str],
    readiness_verified: bool,
    proposal: ProposalPanel,
) -> IntegrityPanel:
    for rel in ("research/v2a/results.json", "research/v2b/v2b_results.json"):
        _load_strict_object(root, rel)
    oq_path = _require_regular_file(root, "governance/v2c/oq_registry.jsonl")
    try:
        records = strict_jsonl_records(oq_path.read_bytes(), "oq_registry")
    except (M3FValidationError, StrictJSONError, ValueError) as exc:
        raise _fail("governance/v2c/oq_registry.jsonl", exc) from exc
    try:
        load_activation_anchor(root)
    except V2DActivationError as exc:
        raise _fail(ANCHOR_RELPATH, exc) from exc
    _require_regular_file(root, "governance/v2/fable5_source_freeze.json")
    # Read from the canonical status; never re-decide acceptance on this surface.
    proposal_verification = labels_for(proposal.status).integrity_verification
    return IntegrityPanel(
        sealed_ledgers=sealed,
        accepted_base_verified=True,
        v2a_results_verified=True,
        v2b_results_verified=True,
        v2c_oq_registry=f"chained registry parses strictly ({len(records)} record(s))",
        fable5_paper_readiness_verified=readiness_verified,
        v2d_activation_anchor_valid=True,
        source_freeze_present=True,
        proposal_verification=proposal_verification,
    )


def _candidate_panel(readiness: PaperReadinessState) -> CandidatePanel:
    if readiness.eligible_paper_candidate_present:
        raise DashboardStateError(
            "an eligible candidate is recorded but this dashboard release asserts none exist; "
            "refusing to render a stale surface (update V2E deliberately)"
        )
    if readiness.paper_activation_authorized or readiness.paper_trading_active:
        raise DashboardStateError("paper state conflicts with paper-readiness derivation")
    if readiness.sell_ready:
        raise DashboardStateError("sell_ready conflicts with its derivation; refusing")
    gates = readiness.gates
    return CandidatePanel(
        nominated_candidate="none",
        eligible_candidate_present=readiness.eligible_paper_candidate_present,
        paper_release_candidate_frozen=gates.get("paper_release_candidate_frozen") is True,
        human_activation_approval=gates.get("human_activation_approval_recorded") is True,
        paper_activation_authorized=readiness.paper_activation_authorized,
        paper_trading_active=readiness.paper_trading_active,
        sell_ready=readiness.sell_ready,
        blocking_gates=readiness.blocking_gates,
    )


def _paper_engine_panel(
    requirements: PaperActivationRequirements, readiness: PaperReadinessState
) -> PaperEnginePanel:
    lifecycle_state, blocking = derive_resting_state(requirements)
    if lifecycle_state != "disabled" and not readiness.eligible_paper_candidate_present:
        raise DashboardStateError("paper lifecycle conflicts with candidate governance; refusing")
    return PaperEnginePanel(
        engine_status="disabled",
        mode="no candidate",
        exposure="zero (the engine is disabled; no position can exist)",
        open_positions=0,
        pending_orders=0,
        fills=0,
        pnl=(
            "UNAVAILABLE — no paper trading has ever run; this is the absence of a record, "
            "not zero performance"
        ),
        kill_switch="ENGAGED BY POLICY",
        lifecycle_state=lifecycle_state,
        blocking_requirements=blocking,
        explanation=(
            "Activation is blocked because no eligible nominated candidate exists and the "
            "activation requirements above are unmet. There is no control on this dashboard "
            "that can activate paper trading."
        ),
    )


def _timeline(
    anchor: dict[str, Any], accepted: AcceptedProspectiveBase, proposal: ProposalPanel
) -> tuple[tuple[str, str], ...]:
    return (
        ("V1 offline research platform", "accepted milestones M1-M4B merged and verified"),
        ("V2A/V2B research resets", "negative results accepted; no candidate promoted"),
        ("V2C operational qualification", "candidate-free OQ accepted (ready, not active)"),
        ("Fable 5 full-system audit", "accepted; paper readiness derives blocked"),
        (
            "V2D DATA-ONLY activation",
            f"anchor authorized on {anchor.get('authorized_on', 'unknown')}; "
            f"accepted cohort {accepted.row_count} rows through {accepted.last_open}",
        ),
        # The timeline's terminal state for the proposal, read from the canonical
        # status. enforce_display_invariants maps this string back to a status and
        # requires it to equal the headline's and the badge's.
        (TIMELINE_LABEL, labels_for(proposal.status).timeline_detail),
        ("Strategy events", "none — no strategy has ever been evaluated"),
        ("Paper events", "none — paper trading has never started"),
    )


def _require_int(value: int | None, label: str) -> int:
    if value is None:
        raise DashboardStateError(f"{label} is absent on a configured proposal panel")
    return value


def enforce_display_invariants(state: DashboardState) -> None:
    """Fail closed unless every surface agrees about acceptance (Auditor C, B-3).

    Called at the end of :func:`build_dashboard_state` *and* again by
    :func:`eth_research.v2e.render.render_html`, so a state that was assembled or
    replaced field-by-field outside the builder cannot reach a page either. Each block
    below is one of the invariants the finding requires:

    1. headline status == badge status == timeline terminal state (and the panel detail,
       integrity prose and acquisition prose, which are the other places the old page
       disagreed with itself);
    2. ACCEPTED requires a verified, identity-bound acceptance record; every other status
       requires the absence of one;
    3. a stale proposal (ancestry unverified) can never display accepted, and only the
       PROPOSED status may display as pending — so a superseded or rejected one cannot;
    4. accepted and proposed row counts are never interchanged, and never rendered as two
       bare adjacent figures that a reader could sum;
    5. the accepted identity displayed is the accepted manifest identity, and a proposed
       identity is a separate, separately labelled field.
    """
    proposal = state.proposal
    status = proposal.status
    labels = labels_for(status)

    # (1) One status, everywhere it is visible.
    for text, reverse, what in (
        (labels.heading, status_from_heading, "headline"),
        (labels.badge, status_from_badge, "badge"),
        (proposal.detail, status_from_detail, "panel detail"),
    ):
        if reverse(text) is not status:
            raise DashboardStateError(f"proposal {what} disagrees with the canonical status")
    timeline_details = [detail for label, detail in state.timeline if label == TIMELINE_LABEL]
    if len(timeline_details) != 1:
        raise DashboardStateError(
            f"the timeline must carry exactly one {TIMELINE_LABEL!r} row, found "
            f"{len(timeline_details)}"
        )
    if status_from_timeline_detail(timeline_details[0]) is not status:
        raise DashboardStateError("timeline terminal state disagrees with the canonical status")
    if (status_from_claim(labels.claim) is ProposalStatus.ACCEPTED) is not (
        status is ProposalStatus.ACCEPTED
    ):
        raise DashboardStateError("the acceptance claim disagrees with the canonical status")
    if state.integrity.proposal_verification != labels.integrity_verification:
        raise DashboardStateError("integrity proposal verification disagrees with the status")
    if state.acquisition.append_only_result != labels.acquisition_append_result:
        raise DashboardStateError("acquisition append-only result disagrees with the status")
    if state.acquisition.two_runner_agreement != labels.two_runner_agreement:
        raise DashboardStateError("acquisition runner agreement disagrees with the status")

    if proposal.configured is not (status is not None):
        raise DashboardStateError(
            "a configured proposal panel must carry a status and an unconfigured one must not"
        )
    if status is None:
        stale_facts = (
            proposal.proposal_id,
            proposal.proposal_branch,
            proposal.proposed_row_count,
            proposal.new_completed_days,
            proposal.proposed_last_open,
            proposal.manifest_sha256,
            proposal.accepted_manifest_sha256,
        )
        if any(fact is not None for fact in stale_facts):
            raise DashboardStateError(
                "no proposal checkout is configured, so no proposal fact may be displayed"
            )
        return

    # (2) Acceptance requires the record; everything else requires its absence.
    has_record = proposal.accepted_manifest_sha256 is not None
    if has_record is not (status is ProposalStatus.ACCEPTED):
        raise DashboardStateError(
            "status 'accepted' requires a verified acceptance record and no other status may "
            f"have one (status={status}, acceptance record present={has_record})"
        )

    # (3) Stale can never read accepted; only PROPOSED may read pending.
    if proposal.ancestry_verified is not True and status is ProposalStatus.ACCEPTED:
        raise DashboardStateError(
            "a proposal whose ancestry is not verified can never be displayed as accepted"
        )
    if labels.pending is not (status is ProposalStatus.PROPOSED):
        raise DashboardStateError(
            f"status {status} may not be displayed as pending; only a proposed one is pending"
        )

    # (4) Row counts are never interchanged and never additive on the page.
    accepted_rows = state.cohort.accepted_row_count
    proposed_rows = _require_int(proposal.proposed_row_count, "proposed row count")
    appended_rows = _require_int(proposal.new_completed_days, "appended day count")
    if appended_rows < 1 or proposed_rows < 1:
        raise DashboardStateError("proposal row counts must be positive")
    if status is ProposalStatus.ACCEPTED:
        if proposed_rows != accepted_rows:
            raise DashboardStateError(
                "an accepted proposal's rows ARE the accepted cohort; a different proposed "
                "count means the two are being displayed as separate quantities"
            )
        if appended_rows >= proposed_rows:
            raise DashboardStateError("appended days cannot equal or exceed the accepted cohort")
        if proposal.proposed_last_open != state.cohort.accepted_last_open:
            raise DashboardStateError("accepted proposal last-open is not the accepted last-open")
    elif status is ProposalStatus.PROPOSED:
        if proposed_rows != accepted_rows + appended_rows:
            raise DashboardStateError("pending proposal row arithmetic does not close")
        if proposed_rows == accepted_rows:
            raise DashboardStateError("accepted and proposed row counts must not be interchanged")
        if not (proposal.proposed_last_open or "") > state.cohort.accepted_last_open:
            raise DashboardStateError("a pending proposal must extend the cohort forward in time")
    statement = row_count_statement(
        status,
        accepted_rows=accepted_rows,
        proposed_rows=proposed_rows,
        appended_rows=appended_rows,
    )
    if not any(marker in statement for marker in NON_ADDITIVE_MARKERS):
        raise DashboardStateError(
            "the row-count statement does not state that the two counts are not additive"
        )

    # (5) Accepted identity is the accepted manifest identity; proposed identity is separate.
    bundle_identity = proposal.manifest_sha256
    if bundle_identity is None or not proposal.proposal_id or not proposal.proposal_branch:
        raise DashboardStateError(
            "a configured proposal panel must display its identity (proposal id, branch and "
            "self-hashed manifest digest)"
        )
    if bundle_identity == state.cohort.accepted_fingerprint:
        raise DashboardStateError(
            "the proposal manifest identity and the accepted cohort fingerprint are distinct "
            "identities; displaying one as the other conflates accepted and proposed state"
        )
    if status is ProposalStatus.ACCEPTED and proposal.accepted_manifest_sha256 != bundle_identity:
        raise DashboardStateError(
            "the accepted identity displayed must be the identity the acceptance record pins"
        )


def build_dashboard_state(
    repo_root: str | Path,
    *,
    proposal_checkout: str | Path | None = None,
    now: str | None = None,
) -> DashboardState:
    """Build the one immutable dashboard state, failing closed on any inconsistency."""
    root = Path(repo_root)
    if root.is_symlink() or not root.is_dir():
        raise DashboardStateError("repo root must be a real directory")
    generated_at = now if now is not None else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # The sealed ledgers are the most critical invariant: check them first so a
    # violated seal is reported as exactly that, not as a downstream byte mismatch.
    sealed = _sealed_ledger_facts(root)
    try:
        accepted = verify_accepted_base(root)
    except (M3EValidationError, StrictJSONError, OSError, ValueError) as exc:
        raise _fail("accepted base verification", exc) from exc
    try:
        status = build_status(root)
    except (M3EValidationError, StrictJSONError, OSError, ValueError) as exc:
        raise _fail("m3e status derivation", exc) from exc
    try:
        anchor = load_activation_anchor(root)
    except V2DActivationError as exc:
        raise _fail("V2D activation anchor", exc) from exc

    readiness = _verified_paper_readiness(root)
    try:
        fresh = derive_paper_readiness(root)
    except OSError as exc:  # pragma: no cover - filesystem race
        raise _fail("paper-readiness derivation", exc) from exc
    if fresh.to_canonical() != readiness.to_canonical():
        raise DashboardStateError("paper-readiness derivation is unstable; refusing")

    accepted_block = status.get("accepted_base")
    if not isinstance(accepted_block, dict):
        raise DashboardStateError("m3e status accepted_base block malformed")
    maturity = str(accepted_block.get("maturity_state"))
    if maturity not in {"immature", "mature"}:
        raise DashboardStateError(f"unknown maturity state {maturity!r}; refusing")
    if accepted_block.get("evaluation_authorized") is not False:
        raise DashboardStateError("evaluation_authorized must be false; governance conflict")
    if int(str(accepted_block.get("row_count"))) != accepted.row_count:
        raise DashboardStateError("status/accepted-base row-count conflict; refusing")

    requirements = derive_requirements(root, readiness)
    proposal = _proposal_panel(
        root, accepted, Path(proposal_checkout) if proposal_checkout is not None else None
    )

    progress = 100.0 * accepted.row_count / TARGET_ROWS
    cohort = CohortPanel(
        accepted_row_count=accepted.row_count,
        target_row_count=TARGET_ROWS,
        progress_percent=f"{progress:.1f}",
        accepted_first_open=accepted.first_open,
        accepted_last_open=accepted.last_open,
        remaining_rows=TARGET_ROWS - accepted.row_count,
        maturity_state=maturity,
        evaluation_authorized=False,
        accepted_fingerprint=accepted.canonical_content_fingerprint,
    )

    built = DashboardState(
        schema_version=SCHEMA_VERSION,
        generated_at=generated_at,
        identity=RepoIdentity(
            repository=AUTHORIZED_REPOSITORY,
            version=_package_version(),
            commit=_read_git_commit(root),
            private_local_only=True,
        ),
        cohort=cohort,
        proposal=proposal,
        acquisition=_acquisition_panel(root, status, accepted, proposal, generated_at),
        integrity=_integrity_panel(root, sealed, True, proposal),
        candidate=_candidate_panel(readiness),
        paper_engine=_paper_engine_panel(requirements, readiness),
        timeline=_timeline(anchor, accepted, proposal),
    )
    # Nothing leaves the builder that any surface could render as a contradiction.
    enforce_display_invariants(built)
    return built


def _package_version() -> str:
    import eth_research

    return str(eth_research.__version__)


_FORBIDDEN_KEY_FRAGMENTS = ("secret", "token", "credential", "password", "env", "candle", "price")


# The PEM marker is assembled non-contiguously so the tracked-tree secret scanner
# does not flag this detector constant as key material itself.
_FORBIDDEN_VALUE_MARKERS = ("/home/", "/root/", "-----" + "BEGIN", "\x00")


def _assert_publishable(node: Any, trail: str) -> None:
    if isinstance(node, str):
        for marker in _FORBIDDEN_VALUE_MARKERS:
            if marker in node:
                raise DashboardStateError(f"forbidden status value at {trail}")
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            for fragment in _FORBIDDEN_KEY_FRAGMENTS:
                if fragment in lowered:
                    raise DashboardStateError(f"forbidden status key {trail}.{key}")
            _assert_publishable(value, f"{trail}.{key}")
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            _assert_publishable(value, f"{trail}[{index}]")


def to_status_document(state: DashboardState) -> dict[str, Any]:
    """The JSON status endpoint body: approved status facts only."""
    doc = asdict(state)
    document: dict[str, Any] = {
        "kind": "v2e_dashboard_status",
        **doc,
    }
    _assert_publishable(document, "$")
    return document
