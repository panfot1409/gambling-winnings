"""The dashboard may not display a claim its derivation does not support.

The directive names four claims: **approved**, **eligible**, **paper active**, **sell ready**.
This module proves, for each, that the rendered page shows the affirmative form if and only if
the state says so — and that the state itself can only say so if ``derive_paper_readiness`` and
``derive_requirements`` say so.

Why the controls matter more than the refusals here. "The page never says approved" is trivially
satisfied by a page that cannot say approved at all, and that is not the property anyone wants:
a surface that under-reports is still a surface an operator cannot trust. So every negative below
is paired with a positive that renders the affirmative form from a synthetic state. Without the
pair, the negatives prove nothing.

Two literals in ``render.py`` used to break this and are pinned here so they cannot come back:

* ``Visibility: private / local-only`` was unconditional. That is the same shape as the defect
  V2F already corrected once — ``repository_private`` read a PyPI classifier and returned True
  while the repository was verifiably public. A dashboard asserting privacy without checking is
  the exact surface that would reassure an operator mid-breach.
* ``Paper system: blocked — no eligible candidate`` was unconditional. Stated precisely, because
  overclaiming a defect is itself a recorded V2F error: this was **never a live inversion**.
  ``build_dashboard_state`` refuses outright when an eligible candidate exists, so the literal
  was never displayed beside a contradicting value in a real render. It was a correctness gap —
  the render layer made a claim it did not verify, and its truth depended entirely on a guard in
  a different module. Relax that guard and the page lies with no test failing.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from eth_research.v2e.render import render_html
from eth_research.v2e.state import (
    DashboardState,
    build_dashboard_state,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The affirmative renderings. Each is the exact substring an operator would read as "yes".
_AFFIRMATIVE = {
    "sell_ready": '<dt>Sell-ready</dt><dd><span class="ok">true</span></dd>',
    "eligible": '<dt>Eligible candidate</dt><dd><span class="ok">true</span></dd>',
    "approved": '<dt>Paper activation authorized</dt><dd><span class="ok">true</span></dd>',
    "paper_active": '<dt>Paper trading active</dt><dd><span class="ok">true</span></dd>',
}


@pytest.fixture(scope="module")
def real_state() -> DashboardState:
    return build_dashboard_state(REPO_ROOT, now="2026-07-29T00:00:00Z")


def _with_candidate(state: DashboardState, name: str, value: bool = True) -> DashboardState:
    """Set exactly one boolean on the candidate panel, dispatched explicitly.

    Written as four named branches rather than ``**{name: value}`` so the substitution is
    type-checked. A ``**kwargs`` splat over a dataclass with non-bool fields type-erases to
    ``Any``, and a silently-mistyped field name would build a panel that proves nothing while
    the test still passes.
    """
    panel = state.candidate
    if name == "sell_ready":
        panel = dataclasses.replace(panel, sell_ready=value)
    elif name == "eligible_candidate_present":
        panel = dataclasses.replace(panel, eligible_candidate_present=value)
    elif name == "paper_activation_authorized":
        panel = dataclasses.replace(panel, paper_activation_authorized=value)
    elif name == "paper_trading_active":
        panel = dataclasses.replace(panel, paper_trading_active=value)
    else:
        raise AssertionError(f"{name!r} is not one of the four claim fields")
    return dataclasses.replace(state, candidate=panel)


# --- the four claims, in both directions ------------------------------------------------------


@pytest.mark.parametrize("claim", sorted(_AFFIRMATIVE))
def test_the_real_page_makes_none_of_the_four_claims(
    real_state: DashboardState, claim: str
) -> None:
    assert _AFFIRMATIVE[claim] not in render_html(real_state)


@pytest.mark.parametrize(
    ("claim", "field"),
    [
        ("sell_ready", "sell_ready"),
        ("eligible", "eligible_candidate_present"),
        ("approved", "paper_activation_authorized"),
        ("paper_active", "paper_trading_active"),
    ],
)
def test_control_each_claim_is_reachable_when_the_state_says_so(
    real_state: DashboardState, claim: str, field: str
) -> None:
    """The passing control. Without it the test above could pass on an unreadable page.

    This renders a *synthetic* state; it authorizes nothing. It proves only that the affirmative
    string is producible, which is what makes its absence from the real page meaningful.
    """
    page = render_html(_with_candidate(real_state, field))
    assert _AFFIRMATIVE[claim] in page


@pytest.mark.parametrize(
    ("claim", "field"),
    [
        ("sell_ready", "sell_ready"),
        ("eligible", "eligible_candidate_present"),
        ("approved", "paper_activation_authorized"),
        ("paper_active", "paper_trading_active"),
    ],
)
def test_each_claim_tracks_exactly_its_own_field(
    real_state: DashboardState, claim: str, field: str
) -> None:
    """Setting one field must not light up a different claim — no shared rendering by accident."""
    page = render_html(_with_candidate(real_state, field))
    for other, affirmative in _AFFIRMATIVE.items():
        if other != claim:
            assert affirmative not in page, f"{field}=True also displayed {other!r}"


# --- the two literals that used to be unbound -------------------------------------------------


def test_the_visibility_line_follows_the_gate(real_state: DashboardState) -> None:
    """Reproduction of the first defect, now inverted into a regression."""
    private = render_html(real_state)
    assert "private / local-only" in private

    public = dataclasses.replace(
        real_state, identity=dataclasses.replace(real_state.identity, private_local_only=False)
    )
    page = render_html(public)
    assert "private / local-only" not in page
    assert "NOT PRIVATE" in page


def test_the_paper_system_line_follows_the_candidate_panel(real_state: DashboardState) -> None:
    """Reproduction of the second defect, now inverted into a regression."""
    assert "blocked — no eligible candidate" in render_html(real_state)

    eligible = render_html(_with_candidate(real_state, "eligible_candidate_present"))
    assert "blocked — no eligible candidate" not in eligible
    assert "eligible candidate, activation unmet" in eligible

    authorized = render_html(_with_candidate(real_state, "paper_activation_authorized"))
    assert "activation authorized — not yet started" in authorized

    active = render_html(_with_candidate(real_state, "paper_trading_active"))
    assert "PAPER TRADING ACTIVE" in active


def test_the_paper_system_line_reports_the_most_severe_state_first(
    real_state: DashboardState,
) -> None:
    """With several true at once the operator must see the strongest, not the first-listed."""
    state = real_state
    for name in (
        "eligible_candidate_present",
        "paper_activation_authorized",
        "paper_trading_active",
    ):
        state = _with_candidate(state, name)
    page = render_html(state)
    assert "PAPER TRADING ACTIVE" in page
    assert "blocked — no eligible candidate" not in page


# --- the state cannot claim what the derivation does not support ------------------------------


def test_the_real_state_is_negative_on_all_four(real_state: DashboardState) -> None:
    assert real_state.candidate.sell_ready is False
    assert real_state.candidate.eligible_candidate_present is False
    assert real_state.candidate.paper_activation_authorized is False
    assert real_state.candidate.paper_trading_active is False
    assert real_state.paper_engine.lifecycle_state == "disabled"


def test_visibility_is_derived_from_the_readiness_gate(real_state: DashboardState) -> None:
    """The value must come from the gate, not from a constant that happens to agree with it.

    The first version of this test compared the two values and passed — because both are
    ``True`` today, it passed just as happily against a hard-coded ``private_local_only=True``.
    A test that agrees with a constant is not a test of derivation. It now *flips the gate* and
    demands the state follow, which is the only version a mutation can fail.
    """
    from eth_research.v2.fable5.paper_readiness import derive_paper_readiness

    readiness = derive_paper_readiness(REPO_ROOT)
    assert readiness.gates.get("repository_private") is True
    assert real_state.identity.private_local_only is True

    flipped = dataclasses.replace(readiness, gates={**readiness.gates, "repository_private": False})
    monkeypatched = _build_with_readiness(flipped)
    assert monkeypatched.identity.private_local_only is False, (
        "the visibility value ignored a False repository_private gate"
    )
    assert "NOT PRIVATE" in render_html(monkeypatched)


def _build_with_readiness(readiness: object) -> DashboardState:
    """Build the dashboard state against a substituted readiness derivation.

    ``build_dashboard_state`` verifies the committed readiness artifact and then re-derives it,
    refusing if the two disagree. Both paths are substituted together so the substitution reaches
    the identity block instead of tripping that consistency check.
    """
    import eth_research.v2e.state as state_mod

    patcher = pytest.MonkeyPatch()
    try:
        patcher.setattr(state_mod, "_verified_paper_readiness", lambda _root: readiness)
        patcher.setattr(state_mod, "derive_paper_readiness", lambda _root: readiness)
        return build_dashboard_state(REPO_ROOT, now="2026-07-29T00:00:00Z")
    finally:
        patcher.undo()


def test_no_unbound_affirmative_literal_survives_in_the_template() -> None:
    """The durable control: a future edit cannot reintroduce an asserted claim.

    Scanning source is a blunt instrument, so this is deliberately narrow — it checks only that
    the four claim labels are rendered through ``_flag``/a derivation helper rather than as
    literal ``ok`` spans. It is not a proof that every string on the page is derived; the three
    remaining descriptive literals (Honest state, Data collection, Schedule) are outside the four
    claims this module is responsible for and are recorded as such in the error-correction log.
    """
    source = (REPO_ROOT / "src/eth_research/v2e/render.py").read_text(encoding="utf-8")
    for label in (
        "Sell-ready",
        "Eligible candidate",
        "Paper activation authorized",
        "Paper trading active",
    ):
        index = source.index(f'"{label}"')
        window = source[index : index + 220]
        assert "_flag(" in window, f"{label} is no longer rendered through _flag"
        assert '<span class="ok">' not in window, f"{label} gained a literal affirmative span"
