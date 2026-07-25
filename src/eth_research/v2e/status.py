"""The one strict proposal-status model, shared by every V2E surface.

Auditor C finding B-3: the dashboard contradicted itself about acceptance. The renderer
carried its own hard-coded ``Pending proposal (unmerged — NOT accepted)`` copy while the
state model had already learned the accepted/pending split, so the real accepted state
rendered a page that simultaneously claimed the proposal was accepted (timeline) and not
accepted (headline, row labels).

The fix is structural rather than editorial:

* :class:`ProposalStatus` is the whole vocabulary — exactly four members;
* the status is derived **once**, in :func:`eth_research.v2e.state.build_dashboard_state`
  (via ``_proposal_panel``), from verified evidence;
* every visible string — headline, badge, acceptance claim, row labels, timeline detail,
  integrity prose, acquisition prose — is read out of :data:`LABELS`, keyed by that one
  status. No surface computes a status of its own or writes its own copy;
* every label maps back to exactly one status (:func:`status_from_heading`,
  :func:`status_from_badge`, :func:`status_from_claim`,
  :func:`status_from_timeline_detail`), so agreement between surfaces is *checkable*
  rather than assumed, and disagreement fails closed with :class:`DashboardStateError`.

The exception type lives here (and is re-exported from
:mod:`eth_research.v2e.state`) so this module stays a dependency-free leaf: state imports
status, render imports both, and nothing imports render.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class DashboardStateError(RuntimeError):
    """The dashboard state could not be derived or displayed honestly; nothing was repaired."""


class ProposalStatus(StrEnum):
    """The complete status vocabulary for a local proposal bundle.

    ``StrEnum`` so the value survives :func:`dataclasses.asdict` into the JSON status
    document unchanged, while the members stay a closed set for exhaustiveness checking.
    """

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


#: The two mutually exclusive acceptance claims. Exactly one of these appears in the
#: proposal panel, and only :data:`ACCEPTED_CLAIM` may accompany
#: :attr:`ProposalStatus.ACCEPTED`. Neither is a substring of the other, so a page can be
#: mechanically checked for "says both" — the exact defect B-3 reported.
ACCEPTED_CLAIM = "Accepted into the cohort (acceptance record verified)"
NOT_ACCEPTED_CLAIM = "Not accepted (no acceptance record)"

#: Used when no local checkout is configured: there is no local proposal to have a
#: status, so the surface makes neither claim rather than guessing one.
UNVERIFIED_CLAIM = "No local proposal bundle; this surface makes no acceptance claim"

#: The timeline row label for the proposal's terminal state.
TIMELINE_LABEL = "Local proposal"

#: A row-count statement must carry one of these, so two counts can never sit adjacent
#: on the page with their relationship left to the reader's imagination.
NON_ADDITIVE_MARKERS: tuple[str, ...] = ("not additive", "not additional")


@dataclass(frozen=True, slots=True)
class StatusLabels:
    """Every visible string for one status. The single source of dashboard copy."""

    status: ProposalStatus | None
    heading: str
    badge: str
    badge_class: str
    claim: str
    identity_label: str
    manifest_label: str
    accepted_manifest_label: str
    accepted_manifest_absent: str
    rows_label: str
    last_open_label: str
    detail: str
    timeline_detail: str
    integrity_verification: str
    acquisition_append_result: str
    two_runner_agreement: str
    #: True only while the proposal is genuinely awaiting review. A rejected or
    #: superseded proposal is finished, not pending; an accepted one has landed.
    pending: bool

    @property
    def claims_acceptance(self) -> bool:
        return self.claim == ACCEPTED_CLAIM


_VERIFIED_AGREEMENT = "two isolated runners agreed byte-for-byte (canonical_content_match)"
_UNVERIFIED_TEXT = "recorded in the proposal bundle (no local checkout configured)"

_PROPOSED = StatusLabels(
    status=ProposalStatus.PROPOSED,
    heading="Pending proposal (unmerged — NOT accepted)",
    badge="pending review — NOT accepted",
    badge_class="blocked",
    claim=NOT_ACCEPTED_CLAIM,
    identity_label="Pending proposal id (NOT accepted)",
    manifest_label="Proposed manifest id (NOT accepted)",
    accepted_manifest_label="Accepted manifest id",
    accepted_manifest_absent="none — this proposal has no acceptance record",
    rows_label="Cohort size if this proposal is accepted",
    last_open_label="Proposed last open (NOT accepted)",
    detail="pending draft proposal verified against the accepted base (unmerged)",
    timeline_detail="one DATA-ONLY draft update proposal verified locally; awaiting review",
    integrity_verification="pending proposal verified (append-only, ancestry-checked)",
    acquisition_append_result="append-only extension verified against the accepted base",
    two_runner_agreement=_VERIFIED_AGREEMENT,
    pending=True,
)

_ACCEPTED = StatusLabels(
    status=ProposalStatus.ACCEPTED,
    heading="Accepted proposal (merged into the cohort above)",
    badge="accepted",
    badge_class="ok",
    claim=ACCEPTED_CLAIM,
    identity_label="Accepted proposal id",
    manifest_label="Checked-out bundle manifest id",
    accepted_manifest_label="Accepted manifest id (from the acceptance record)",
    accepted_manifest_absent="",  # unreachable: acceptance requires the record
    rows_label="Rows of this proposal",
    last_open_label="Accepted last open (contributed by this proposal)",
    detail="accepted proposal: its rows ARE the accepted cohort (acceptance chain verified)",
    timeline_detail=(
        "the local DATA-ONLY proposal has been ACCEPTED into the cohort; "
        "no proposal is pending locally"
    ),
    integrity_verification=(
        "accepted proposal verified (append-only, ancestry-checked, acceptance chain verified)"
    ),
    acquisition_append_result="append-only extension accepted into the cohort",
    two_runner_agreement=_VERIFIED_AGREEMENT,
    pending=False,
)

_REJECTED = StatusLabels(
    status=ProposalStatus.REJECTED,
    heading="Rejected proposal (NOT accepted — not pending)",
    badge="rejected — NOT accepted",
    badge_class="blocked",
    claim=NOT_ACCEPTED_CLAIM,
    identity_label="Rejected proposal id (NOT accepted)",
    manifest_label="Rejected manifest id (NOT accepted)",
    accepted_manifest_label="Accepted manifest id",
    accepted_manifest_absent="none — this proposal was rejected and has no acceptance record",
    rows_label="Rows this proposal would have added (rejected)",
    last_open_label="Rejected proposal last open (NOT accepted)",
    detail="rejected proposal: it was never accepted and is no longer awaiting review",
    timeline_detail="the local DATA-ONLY proposal was REJECTED; nothing was accepted from it",
    integrity_verification="rejected proposal (ancestry-checked; no acceptance record)",
    acquisition_append_result="append-only extension rejected; the accepted cohort is unchanged",
    two_runner_agreement=_VERIFIED_AGREEMENT,
    pending=False,
)

_SUPERSEDED = StatusLabels(
    status=ProposalStatus.SUPERSEDED,
    heading="Superseded proposal (NOT accepted — not pending)",
    badge="superseded — NOT accepted",
    badge_class="blocked",
    claim=NOT_ACCEPTED_CLAIM,
    identity_label="Superseded proposal id (NOT accepted)",
    manifest_label="Superseded manifest id (NOT accepted)",
    accepted_manifest_label="Accepted manifest id",
    accepted_manifest_absent="none — this proposal was superseded and has no acceptance record",
    rows_label="Rows this proposal would have added (superseded)",
    last_open_label="Superseded proposal last open (NOT accepted)",
    detail="superseded proposal: a later proposal replaced it; it is neither pending nor accepted",
    timeline_detail=(
        "the local DATA-ONLY proposal was SUPERSEDED by a later one; it is not pending"
    ),
    integrity_verification="superseded proposal (ancestry-checked; no acceptance record)",
    acquisition_append_result="append-only extension superseded; the accepted cohort is unchanged",
    two_runner_agreement=_VERIFIED_AGREEMENT,
    pending=False,
)

#: No local checkout: there is no local proposal, so there is no status to display.
#: Deliberately outside :class:`ProposalStatus` — "unknown" is not a proposal state.
UNVERIFIED_LABELS = StatusLabels(
    status=None,
    heading="Local proposal (no checkout configured — status not locally verified)",
    badge="not locally verified",
    badge_class="off",
    claim=UNVERIFIED_CLAIM,
    identity_label="Local proposal",
    manifest_label="Proposal manifest id",
    accepted_manifest_label="Accepted manifest id",
    accepted_manifest_absent="not locally verified",
    rows_label="Proposal rows",
    last_open_label="Proposal last open",
    detail=(
        "no proposal checkout configured (pass --proposal-checkout with a local "
        "read-only checkout of the bot proposal branch to display pending-proposal "
        "facts); the pending draft PR remains visible on GitHub"
    ),
    timeline_detail="check GitHub for any pending draft proposal (not locally verified)",
    integrity_verification="no local proposal checkout configured",
    acquisition_append_result=_UNVERIFIED_TEXT,
    two_runner_agreement=_UNVERIFIED_TEXT,
    pending=False,
)

LABELS: Mapping[ProposalStatus, StatusLabels] = MappingProxyType(
    {
        ProposalStatus.PROPOSED: _PROPOSED,
        ProposalStatus.ACCEPTED: _ACCEPTED,
        ProposalStatus.REJECTED: _REJECTED,
        ProposalStatus.SUPERSEDED: _SUPERSEDED,
    }
)

_ALL_LABELS: tuple[StatusLabels, ...] = (*LABELS.values(), UNVERIFIED_LABELS)


def labels_for(status: ProposalStatus | None) -> StatusLabels:
    """The one label set for ``status`` (``None`` = no local checkout configured)."""
    if status is None:
        return UNVERIFIED_LABELS
    if not isinstance(status, ProposalStatus):  # pragma: no cover - defensive, mypy-unreachable
        raise DashboardStateError(f"not a ProposalStatus: {status!r}")
    return LABELS[status]


def _reverse(
    index: Mapping[str, ProposalStatus | None], text: str, what: str
) -> ProposalStatus | None:
    try:
        return index[text]
    except KeyError:
        raise DashboardStateError(
            f"{what} {text!r} does not map to any canonical proposal status; every visible "
            "status string must come from eth_research.v2e.status.LABELS"
        ) from None


def _index(attribute: str) -> Mapping[str, ProposalStatus | None]:
    built: dict[str, ProposalStatus | None] = {}
    for labels in _ALL_LABELS:
        key = str(getattr(labels, attribute))
        if key in built:  # pragma: no cover - guarded by _validate_table at import
            raise DashboardStateError(f"ambiguous {attribute} label {key!r}")
        built[key] = labels.status
    return MappingProxyType(built)


_BY_HEADING = _index("heading")
_BY_BADGE = _index("badge")
_BY_TIMELINE = _index("timeline_detail")
_BY_DETAIL = _index("detail")


def status_from_heading(text: str) -> ProposalStatus | None:
    """The status a rendered section heading claims."""
    return _reverse(_BY_HEADING, text, "proposal section heading")


def status_from_badge(text: str) -> ProposalStatus | None:
    """The status a rendered badge claims."""
    return _reverse(_BY_BADGE, text, "proposal status badge")


def status_from_timeline_detail(text: str) -> ProposalStatus | None:
    """The terminal status the timeline row claims."""
    return _reverse(_BY_TIMELINE, text, "proposal timeline detail")


def status_from_detail(text: str) -> ProposalStatus | None:
    """The status the panel detail sentence claims."""
    return _reverse(_BY_DETAIL, text, "proposal detail")


def status_from_claim(text: str) -> ProposalStatus | None:
    """Whether an acceptance claim asserts acceptance.

    Returns :attr:`ProposalStatus.ACCEPTED` for the accepted claim. The not-accepted
    claim is shared by three statuses, so it returns ``None`` — callers use it to check
    *acceptance*, which is the contradiction B-3 was about, not to recover the member.
    """
    if text == ACCEPTED_CLAIM:
        return ProposalStatus.ACCEPTED
    if text in (NOT_ACCEPTED_CLAIM, UNVERIFIED_CLAIM):
        return None
    raise DashboardStateError(
        f"acceptance claim {text!r} is not one of the two canonical claims; a surface is "
        "writing its own acceptance copy"
    )


def row_count_statement(
    status: ProposalStatus | None,
    *,
    accepted_rows: int,
    proposed_rows: int,
    appended_rows: int,
) -> str:
    """One sentence stating BOTH counts and their exact relationship.

    Finding B-3 also flagged the adjacency of ``Accepted rows 12 / 365`` and
    ``Proposed rows (unmerged) 12``, which invites reading 12 + 12. The two counts are
    therefore never emitted as bare adjacent figures: they only ever appear inside one
    of these statements, each of which names the relationship explicitly.
    """
    if status is ProposalStatus.ACCEPTED:
        return (
            f"{proposed_rows} rows — the SAME rows counted as Accepted rows above "
            f"({appended_rows} of them appended by this proposal); "
            "not additional to the accepted cohort"
        )
    if status is ProposalStatus.PROPOSED:
        return (
            f"{proposed_rows} rows in total if accepted — this REPLACES the {accepted_rows} "
            f"accepted rows above (it already contains them, plus {appended_rows} new day(s)); "
            "the two counts are not additive"
        )
    if status is ProposalStatus.REJECTED:
        return (
            f"{proposed_rows} rows were proposed and rejected; the accepted cohort remains "
            f"{accepted_rows} rows — the two counts are not additive"
        )
    if status is ProposalStatus.SUPERSEDED:
        return (
            f"{proposed_rows} rows were proposed and superseded; the accepted cohort remains "
            f"{accepted_rows} rows — the two counts are not additive"
        )
    return (
        f"not locally verified; the accepted cohort is {accepted_rows} rows and no local "
        "proposal count is displayed — the two counts are not additive"
    )


def _validate_table() -> None:
    """Fail at import if the label table itself could produce a contradictory page."""
    if set(LABELS) != set(ProposalStatus):
        raise DashboardStateError("LABELS does not cover exactly the ProposalStatus members")
    if [s.value for s in ProposalStatus] != ["proposed", "accepted", "rejected", "superseded"]:
        raise DashboardStateError("ProposalStatus members changed; every surface depends on them")
    pending = {labels.status for labels in _ALL_LABELS if labels.pending}
    if pending != {ProposalStatus.PROPOSED}:
        raise DashboardStateError(
            "exactly one status may display as pending; a superseded or rejected proposal "
            "is finished and an accepted one has landed"
        )
    claiming = {labels.status for labels in _ALL_LABELS if labels.claims_acceptance}
    if claiming != {ProposalStatus.ACCEPTED}:
        raise DashboardStateError("only the accepted status may make the acceptance claim")
    if ACCEPTED_CLAIM in NOT_ACCEPTED_CLAIM or NOT_ACCEPTED_CLAIM in ACCEPTED_CLAIM:
        raise DashboardStateError("the two acceptance claims must not overlap textually")
    for labels in _ALL_LABELS:
        if labels.status is not ProposalStatus.ACCEPTED:
            for text in (labels.heading, labels.badge):
                if "NOT accepted" not in text and labels.status is not None:
                    raise DashboardStateError(
                        f"{labels.status} heading/badge must say NOT accepted: {text!r}"
                    )
    for status in (None, *ProposalStatus):
        statement = row_count_statement(status, accepted_rows=1, proposed_rows=2, appended_rows=1)
        if not any(marker in statement for marker in NON_ADDITIVE_MARKERS):
            raise DashboardStateError(
                f"row-count statement for {status} is not marked non-additive"
            )
    # The reverse indexes are built eagerly above; a duplicate label would have raised.


_validate_table()
