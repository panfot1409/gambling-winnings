"""Auditor C finding B-3: the rendered page must not contradict itself about acceptance.

The defect was in the *rendered page*, not in the dataclass, so every test here parses
the FINAL HTML with :mod:`html.parser` and asserts against what a reader would actually
see. The renderer used to carry its own hard-coded ``Pending proposal (unmerged — NOT
accepted)`` copy and its own ``Proposed rows (unmerged)`` figure, so the accepted state
produced a page that said the proposal was accepted (timeline) and not accepted
(headline, row labels) at the same time, with two ``12``s stacked as if they summed.

Every test below fails against the pre-fix renderer:

* the headline/badge/timeline agreement tests fail because the headline claims
  ``proposed`` while the timeline claims ``accepted`` (and no badge exists at all);
* the claim test fails because the page makes no explicit acceptance claim to check;
* the vocabulary test fails on ``unmerged`` appearing on an accepted page;
* the row-count test fails on the bare ``<dd>12</dd>`` beside ``Accepted rows 12 / 365``;
* the narrow-viewport/escaping test fails because the corrected strings are absent;
* the fail-closed tests fail because the old renderer emitted a page for states no
  surface should ever display.
"""

from __future__ import annotations

import ast
import dataclasses
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from eth_research.v2e import render as render_module
from eth_research.v2e.render import render_html
from eth_research.v2e.state import (
    DashboardState,
    DashboardStateError,
    ProposalPanel,
    build_dashboard_state,
)
from eth_research.v2e.status import (
    ACCEPTED_CLAIM,
    LABELS,
    NON_ADDITIVE_MARKERS,
    NOT_ACCEPTED_CLAIM,
    TIMELINE_LABEL,
    UNVERIFIED_CLAIM,
    UNVERIFIED_LABELS,
    ProposalStatus,
    labels_for,
    status_from_badge,
    status_from_heading,
    status_from_timeline_detail,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_VOID_TAGS = frozenset({"meta", "link", "br", "hr", "img", "input", "source", "col"})

#: Copy that asserts a proposal is still in flight. None of it may appear on a page
#: whose canonical status is ACCEPTED — that co-occurrence *is* finding B-3.
PENDING_VOCABULARY: tuple[str, ...] = (
    "unmerged",
    "NOT accepted",
    "not accepted",
    "awaiting review",
    "Pending proposal",
    "pending review",
)

#: Copy that asserts acceptance. None of it may appear on a page whose canonical status
#: is anything other than ACCEPTED.
ACCEPTANCE_VOCABULARY: tuple[str, ...] = (
    ACCEPTED_CLAIM,
    "has been ACCEPTED into the cohort",
    "merged into the cohort",
    "its rows ARE the accepted cohort",
    "accepted into the cohort",
)


@dataclass
class Block:
    """One ``<h2>``-delimited region of the page, as a reader sees it."""

    heading: str
    pairs: list[tuple[str, str]] = field(default_factory=list)
    badges: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        parts = [self.heading, *self.paragraphs, *self.items, *self.badges]
        parts.extend(f"{k} {v}" for k, v in self.pairs)
        return " ".join(parts)


class DashboardPage(HTMLParser):
    """A minimal, dependency-free reader's view of the emitted markup.

    ``<h2>`` starts a new block, so the proposal region is locatable in the pre-fix page
    too (where it is a bare heading inside the cohort section, with no ``id``) — the
    tests therefore fail on the contradiction itself rather than on a missing attribute.
    """

    def __init__(self, markup: str) -> None:
        super().__init__(convert_charrefs=True)
        self.markup = markup
        self.blocks: list[Block] = [Block(heading="")]
        self._stack: list[tuple[str, dict[str, str | None]]] = []
        self._buffers: list[list[str]] = []
        self._skip = 0
        self._pending_dt = ""
        self.feed(markup)
        self.close()

    # -- parsing ---------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_TAGS:
            return
        if tag in {"style", "title"}:
            self._skip += 1
        self._stack.append((tag, dict(attrs)))
        self._buffers.append([])

    def handle_data(self, data: str) -> None:
        if self._skip or not self._buffers:
            return
        self._buffers[-1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS or not self._stack:
            return
        while self._stack and self._stack[-1][0] != tag:
            self._close_one()
        if self._stack:
            self._close_one()
        if tag in {"style", "title"}:
            self._skip -= 1

    def _close_one(self) -> None:
        name, attrs = self._stack.pop()
        text = " ".join("".join(self._buffers.pop()).split())
        if self._buffers:
            self._buffers[-1].append(f" {text} ")
        current = self.blocks[-1]
        if name == "h2":
            self.blocks.append(Block(heading=text))
        elif name == "dt":
            self._pending_dt = text
        elif name == "dd":
            current.pairs.append((self._pending_dt, text))
        elif name == "p":
            current.paragraphs.append(text)
        elif name == "li":
            current.items.append(text)
        elif name == "span" and "badge" in (attrs.get("class") or ""):
            current.badges.append(text)

    # -- reader's view ---------------------------------------------------------
    @property
    def visible_text(self) -> str:
        return " ".join(block.text for block in self.blocks)

    def proposal_block(self) -> Block:
        """The block whose heading is a proposal-status headline."""
        headings = {labels.heading for labels in (*LABELS.values(), UNVERIFIED_LABELS)}
        found = [block for block in self.blocks if block.heading in headings]
        assert found, (
            "the rendered page has no proposal-status headline drawn from "
            f"eth_research.v2e.status.LABELS; headings were "
            f"{[b.heading for b in self.blocks if b.heading]}"
        )
        assert len(found) == 1, f"more than one proposal headline: {[b.heading for b in found]}"
        return found[0]

    def block_by_heading(self, heading: str) -> Block:
        for block in self.blocks:
            if block.heading == heading:
                return block
        raise AssertionError(f"no block headed {heading!r}")

    def timeline_detail(self) -> str:
        """The proposal's terminal state as the timeline renders it."""
        details = [
            item.split(" — ", 1)[1]
            for block in self.blocks
            for item in block.items
            if item.startswith(f"{TIMELINE_LABEL} — ")
        ]
        assert len(details) == 1, f"expected one {TIMELINE_LABEL!r} timeline row, got {details}"
        return details[0]


@pytest.fixture(scope="module")
def base_state() -> DashboardState:
    """The real repository state (no proposal checkout configured)."""
    return build_dashboard_state(REPO_ROOT)


def _panel(base: DashboardState, status: ProposalStatus, **overrides: Any) -> ProposalPanel:
    accepted_rows = base.cohort.accepted_row_count
    appended = max(1, accepted_rows - 3)
    identity = "a1" * 32
    if status is ProposalStatus.ACCEPTED:
        proposed_rows, last_open = accepted_rows, base.cohort.accepted_last_open
    else:
        proposed_rows, last_open = accepted_rows + appended, "2099-01-01T00:00:00Z"
    fields: dict[str, Any] = {
        "configured": True,
        "detail": labels_for(status).detail,
        "proposal_id": "20990101-20990102-deadbeefdeadbeef",
        "proposal_branch": "bot/m3e-prospective-update/20990101-20990102-deadbeefdeadbeef",
        "proposed_row_count": proposed_rows,
        "new_completed_days": appended,
        "proposed_last_open": last_open,
        "append_only": True,
        "ancestry_verified": True,
        "status": status,
        "manifest_sha256": identity,
        "accepted_manifest_sha256": identity if status is ProposalStatus.ACCEPTED else None,
    }
    fields.update(overrides)
    return ProposalPanel(**fields)


def state_with_status(
    base: DashboardState, status: ProposalStatus, **overrides: Any
) -> DashboardState:
    """A consistent state for ``status``, with every surface read from the one table.

    Building the whole state from the canonical labels is the point: a test that hand-
    wrote the prose would only re-assert its own copy.
    """
    labels = labels_for(status)
    return dataclasses.replace(
        base,
        proposal=_panel(base, status, **overrides),
        integrity=dataclasses.replace(
            base.integrity, proposal_verification=labels.integrity_verification
        ),
        acquisition=dataclasses.replace(
            base.acquisition,
            append_only_result=labels.acquisition_append_result,
            two_runner_agreement=labels.two_runner_agreement,
        ),
        timeline=tuple(
            (label, labels.timeline_detail if label == TIMELINE_LABEL else detail)
            for label, detail in base.timeline
        ),
    )


class TestRenderedStatusAgreement:
    """Invariant 1: headline == badge == timeline terminal state, on the page itself."""

    @pytest.mark.parametrize("status", list(ProposalStatus))
    def test_every_visible_status_label_agrees(
        self, base_state: DashboardState, status: ProposalStatus
    ) -> None:
        page = DashboardPage(render_html(state_with_status(base_state, status)))
        block = page.proposal_block()
        assert status_from_heading(block.heading) is status, (
            f"headline claims {status_from_heading(block.heading)} while the canonical "
            f"DashboardState status is {status}"
        )
        assert len(block.badges) == 1, f"expected exactly one status badge, got {block.badges}"
        assert status_from_badge(block.badges[0]) is status
        assert status_from_timeline_detail(page.timeline_detail()) is status, (
            "the timeline's terminal state disagrees with the headline — this is the "
            "exact shape of finding B-3"
        )

    def test_unconfigured_page_claims_no_status(self, base_state: DashboardState) -> None:
        page = DashboardPage(render_html(base_state))
        block = page.proposal_block()
        assert status_from_heading(block.heading) is None
        assert status_from_badge(block.badges[0]) is None
        assert status_from_timeline_detail(page.timeline_detail()) is None
        assert UNVERIFIED_CLAIM in block.text

    def test_prose_surfaces_track_the_same_status(self, base_state: DashboardState) -> None:
        for status in ProposalStatus:
            labels = labels_for(status)
            text = DashboardPage(render_html(state_with_status(base_state, status))).visible_text
            assert labels.integrity_verification in text
            assert labels.acquisition_append_result in text
            for other in ProposalStatus:
                if other is status:
                    continue
                assert labels_for(other).heading not in text
                assert labels_for(other).timeline_detail not in text


class TestNoContradictoryClaim:
    """Invariant: the page never says both 'accepted' and 'NOT accepted' about it."""

    @pytest.mark.parametrize("status", list(ProposalStatus))
    def test_exactly_one_acceptance_claim(
        self, base_state: DashboardState, status: ProposalStatus
    ) -> None:
        text = DashboardPage(render_html(state_with_status(base_state, status))).visible_text
        made = [claim for claim in (ACCEPTED_CLAIM, NOT_ACCEPTED_CLAIM) if claim in text]
        assert made == [
            ACCEPTED_CLAIM if status is ProposalStatus.ACCEPTED else NOT_ACCEPTED_CLAIM
        ], f"page makes the claims {made} for canonical status {status}"

    def test_accepted_page_carries_no_pending_vocabulary(self, base_state: DashboardState) -> None:
        text = DashboardPage(
            render_html(state_with_status(base_state, ProposalStatus.ACCEPTED))
        ).visible_text
        for phrase in PENDING_VOCABULARY:
            assert phrase not in text, (
                f"an accepted proposal is described with {phrase!r}; the page claims both "
                "accepted and not accepted about the same proposal"
            )

    @pytest.mark.parametrize(
        "status", [ProposalStatus.PROPOSED, ProposalStatus.REJECTED, ProposalStatus.SUPERSEDED]
    )
    def test_unaccepted_page_carries_no_acceptance_vocabulary(
        self, base_state: DashboardState, status: ProposalStatus
    ) -> None:
        block = DashboardPage(render_html(state_with_status(base_state, status))).proposal_block()
        # It must show its OWN status (not a stand-in for one) and claim no acceptance.
        assert status_from_heading(block.heading) is status
        assert len(block.badges) == 1, f"expected exactly one status badge, got {block.badges}"
        assert status_from_badge(block.badges[0]) is status
        for phrase in ACCEPTANCE_VOCABULARY:
            assert phrase not in block.text, f"a {status} proposal is described with {phrase!r}"

    def test_superseded_is_never_displayed_as_pending(self, base_state: DashboardState) -> None:
        block = DashboardPage(
            render_html(state_with_status(base_state, ProposalStatus.SUPERSEDED))
        ).proposal_block()
        assert status_from_heading(block.heading) is ProposalStatus.SUPERSEDED
        for phrase in ("Pending proposal", "pending review", "awaiting review", "unmerged"):
            assert phrase not in block.text


class TestRowCountsAreNeverAdditive:
    """Invariant 4: the two counts can never be interchanged or read as a sum."""

    @pytest.mark.parametrize("status", list(ProposalStatus))
    def test_proposal_panel_shows_no_bare_count(
        self, base_state: DashboardState, status: ProposalStatus
    ) -> None:
        state = state_with_status(base_state, status)
        block = DashboardPage(render_html(state)).proposal_block()
        for label, value in block.pairs:
            assert not value.strip().isdigit(), (
                f"{label!r} renders the bare figure {value!r} in the proposal panel, next to "
                "the accepted cohort count — exactly the additive reading B-3 flagged"
            )

    @pytest.mark.parametrize("status", list(ProposalStatus))
    def test_every_proposal_count_states_its_relationship(
        self, base_state: DashboardState, status: ProposalStatus
    ) -> None:
        state = state_with_status(base_state, status)
        proposed = str(state.proposal.proposed_row_count)
        block = DashboardPage(render_html(state)).proposal_block()
        mentions = [value for _, value in block.pairs if proposed in value]
        assert mentions, "the proposal's row count is not displayed at all"
        for value in mentions:
            assert any(marker in value for marker in NON_ADDITIVE_MARKERS), (
                f"{value!r} shows the proposed count without stating that it is not "
                "additive to the accepted count"
            )

    def test_accepted_count_is_stated_once_in_the_cohort_panel(
        self, base_state: DashboardState
    ) -> None:
        state = state_with_status(base_state, ProposalStatus.ACCEPTED)
        page = DashboardPage(render_html(state))
        cohort = page.block_by_heading("Prospective cohort (accepted on main)")
        assert dict(cohort.pairs)["Accepted rows"] == (
            f"{state.cohort.accepted_row_count} / {state.cohort.target_row_count}"
        )
        # The accepted figure never reappears as a second, separate quantity.
        for label, value in page.proposal_block().pairs:
            assert value.strip() != str(state.cohort.accepted_row_count), label


class TestNarrowViewportAndEscaping:
    """The corrected strings must wrap on a phone and be escaped exactly once."""

    def test_corrected_strings_keep_the_responsive_containers(
        self, base_state: DashboardState
    ) -> None:
        markup = render_html(state_with_status(base_state, ProposalStatus.ACCEPTED))
        labels = labels_for(ProposalStatus.ACCEPTED)
        for text in (labels.heading, labels.badge, labels.claim, labels.detail, labels.rows_label):
            assert text in markup, f"corrected status string missing from the page: {text!r}"
        # The existing responsive envelope is untouched: a capped, centred column; a
        # two-column grid whose label column can never exceed 40% of a 390px viewport;
        # and anywhere-wrapping so the new 64-hex identities break instead of scrolling.
        assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in markup
        assert "main { max-width: 42rem; margin: 0 auto;" in markup
        assert "body { margin: 0; overflow-wrap: anywhere;" in markup
        assert "grid-template-columns: minmax(9rem, 40%) 1fr;" in markup
        assert "@media (min-width: 700px)" in markup
        assert "* { box-sizing: border-box; }" in markup
        # Nothing opts out of wrapping or introduces a horizontally scrolling box.
        for hostile_css in ("white-space: nowrap", "white-space: pre", "overflow-x", "position:"):
            assert hostile_css not in markup
        # The only width constraints remain the fluid column cap and the one breakpoint,
        # so no corrected label can pin the layout wider than the viewport.
        assert markup.count("max-width:") == 1
        assert markup.count("min-width:") == 1
        for wide_tag in ("<pre", "<table", "<iframe"):
            assert wide_tag not in markup

    def test_nothing_is_double_escaped(self, base_state: DashboardState) -> None:
        markup = render_html(state_with_status(base_state, ProposalStatus.ACCEPTED))
        assert labels_for(ProposalStatus.ACCEPTED).heading in markup
        assert "P&amp;L" in markup  # single, correct escape of "P&L"
        for double in ("&amp;lt;", "&amp;gt;", "&amp;amp;", "&amp;quot;", "&amp;#"):
            assert double not in markup

    def test_hostile_identity_is_escaped_exactly_once(self, base_state: DashboardState) -> None:
        state = state_with_status(base_state, ProposalStatus.ACCEPTED, proposal_id='<script>&"x')
        markup = render_html(state)
        block = DashboardPage(markup).proposal_block()
        assert status_from_heading(block.heading) is ProposalStatus.ACCEPTED
        assert "<script>" not in markup
        assert "&lt;script&gt;&amp;&quot;x" in markup
        assert "&amp;lt;" not in markup


class TestFailClosedDisplay:
    """The invariants are enforced in code: an inconsistent state cannot be rendered."""

    def test_accepted_without_an_acceptance_record_refuses(
        self, base_state: DashboardState
    ) -> None:
        state = state_with_status(
            base_state, ProposalStatus.ACCEPTED, accepted_manifest_sha256=None
        )
        with pytest.raises(DashboardStateError, match="acceptance record"):
            render_html(state)

    def test_pending_with_an_acceptance_record_refuses(self, base_state: DashboardState) -> None:
        state = state_with_status(
            base_state, ProposalStatus.PROPOSED, accepted_manifest_sha256="b2" * 32
        )
        with pytest.raises(DashboardStateError, match="acceptance record"):
            render_html(state)

    def test_stale_proposal_can_never_display_accepted(self, base_state: DashboardState) -> None:
        state = state_with_status(base_state, ProposalStatus.ACCEPTED, ancestry_verified=False)
        with pytest.raises(DashboardStateError, match="ancestry"):
            render_html(state)

    def test_accepted_identity_must_be_the_accepted_manifest_identity(
        self, base_state: DashboardState
    ) -> None:
        state = state_with_status(base_state, ProposalStatus.ACCEPTED, manifest_sha256="c3" * 32)
        with pytest.raises(DashboardStateError, match="identity the acceptance record pins"):
            render_html(state)

    def test_interchanged_row_counts_refuse(self, base_state: DashboardState) -> None:
        state = state_with_status(
            base_state,
            ProposalStatus.ACCEPTED,
            proposed_row_count=base_state.cohort.accepted_row_count + 1,
        )
        with pytest.raises(DashboardStateError, match="separate quantities"):
            render_html(state)

    def test_timeline_disagreeing_with_the_headline_refuses(
        self, base_state: DashboardState
    ) -> None:
        accepted = state_with_status(base_state, ProposalStatus.ACCEPTED)
        forged = dataclasses.replace(
            accepted,
            timeline=tuple(
                (
                    label,
                    labels_for(ProposalStatus.PROPOSED).timeline_detail
                    if label == TIMELINE_LABEL
                    else detail,
                )
                for label, detail in accepted.timeline
            ),
        )
        with pytest.raises(DashboardStateError, match="timeline terminal state"):
            render_html(forged)

    def test_integrity_prose_disagreeing_with_the_status_refuses(
        self, base_state: DashboardState
    ) -> None:
        accepted = state_with_status(base_state, ProposalStatus.ACCEPTED)
        forged = dataclasses.replace(
            accepted,
            integrity=dataclasses.replace(
                accepted.integrity,
                proposal_verification=labels_for(ProposalStatus.PROPOSED).integrity_verification,
            ),
        )
        with pytest.raises(DashboardStateError, match="integrity proposal verification"):
            render_html(forged)

    def test_unconfigured_panel_may_not_carry_proposal_facts(
        self, base_state: DashboardState
    ) -> None:
        forged = dataclasses.replace(
            base_state,
            proposal=dataclasses.replace(base_state.proposal, proposal_id="20990101-x"),
        )
        with pytest.raises(DashboardStateError, match="no proposal fact may be displayed"):
            render_html(forged)


class TestRendererOwnsNoStatusCopy:
    """The root cause: the renderer must not be able to drift from the state again."""

    def test_render_module_writes_no_status_copy(self) -> None:
        source = Path(render_module.__file__).read_text("utf-8")
        tree = ast.parse(source)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
        banned = (*PENDING_VOCABULARY, "Proposed rows", "Proposed last open", "accepted")
        offenders = [
            (text, word)
            for text in literals
            for word in banned
            if word in text and "accepted on main" not in text
        ]
        assert not offenders, (
            "render.py writes its own acceptance copy; every status string must come "
            f"from eth_research.v2e.status.LABELS: {offenders}"
        )
