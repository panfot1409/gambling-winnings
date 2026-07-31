"""The reported paper lifecycle state must never outrun the requirements it reports on.

``_stage_satisfied`` reduced over ``_STAGE_PREREQUISITES[stage]``. ``all(())`` is ``True``, so
that rebindable module dict was the authority on what a stage requires. Emptying it made
``derive_resting_state`` report ``"approved"`` while all seventeen requirements were ``False``
**and all seventeen were still listed as blockers** — a state contradicting its own evidence.
The same shape as V2F-EC-001, in a different module.

Scope, stated precisely because overclaiming here would repeat a mistake this project has
already made and corrected: **this was never an authorization bypass.** Authorization lives in
``request_activation_token`` and ``transition``, both of which reduce over the dataclass's own
``fields()`` via ``all_satisfied`` — that cannot be widened by editing a separate constant, and
the reproduction confirmed the token was still refused with the stage table emptied. What was
broken was *reporting*, and reporting still matters here because the human who decides whether
to approve reads this state.

Every group carries a passing control: a state machine that reports ``"disabled"`` for every
input would satisfy each refusal below while being useless.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

import eth_research.v2e.paper as paper
from eth_research.v2e.paper import (
    PaperActivationRequirements,
    PaperGateError,
    derive_resting_state,
    request_activation_token,
)

_FIELD_NAMES = tuple(f.name for f in fields(PaperActivationRequirements))


def _requirements(**overrides: bool) -> PaperActivationRequirements:
    values = dict.fromkeys(_FIELD_NAMES, False)
    values.update(overrides)
    return PaperActivationRequirements(**values)


def _all_true() -> PaperActivationRequirements:
    return PaperActivationRequirements(**dict.fromkeys(_FIELD_NAMES, True))


# --- controls: the machine must be able to say both yes and no ------------------------------


def test_control_nothing_met_rests_disabled() -> None:
    assert derive_resting_state(_requirements())[0] == "disabled"


def test_control_everything_met_reaches_approved() -> None:
    """Without this, every refusal below could be a state machine stuck at 'disabled'."""
    assert derive_resting_state(_all_true())[0] == "approved"


def test_control_the_real_repository_rests_disabled() -> None:
    from pathlib import Path

    from eth_research.v2e.paper import derive_requirements

    repo_root = Path(__file__).resolve().parents[1]
    state, blockers = derive_resting_state(derive_requirements(repo_root))
    assert state == "disabled"
    assert blockers, "a disabled state must name why"


# --- the vacuous-reduction bypass, and its neighbourhood -------------------------------------


@pytest.mark.parametrize(
    "table",
    [
        pytest.param({"eligible": (), "frozen": (), "approved": ()}, id="all-stages-emptied"),
        pytest.param({}, id="table-emptied"),
        pytest.param({"eligible": (), "frozen": ("cost_model_frozen",)}, id="stage-missing"),
        pytest.param(
            {"eligible": ("nope",), "frozen": ("nope",), "approved": ("nope",)},
            id="unknown-field-names",
        ),
    ],
)
def test_a_degraded_stage_table_cannot_advance_the_reported_state(
    monkeypatch: pytest.MonkeyPatch, table: dict[str, tuple[str, ...]]
) -> None:
    """Reproduction plus its neighbourhood. Pre-fix, the first case reported 'approved'."""
    monkeypatch.setattr(paper, "_STAGE_PREREQUISITES", table)
    assert derive_resting_state(_requirements())[0] == "disabled"


def test_an_extra_stage_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stage set must be exactly the required one — extra as well as missing."""
    extended = dict(paper._STAGE_PREREQUISITES, sneaky_shortcut=())
    monkeypatch.setattr(paper, "_STAGE_PREREQUISITES", extended)
    assert derive_resting_state(_all_true())[0] == "disabled"


# --- reporting must not outrun authorization -------------------------------------------------


@pytest.mark.parametrize("withheld", _FIELD_NAMES)
def test_a_single_unmet_requirement_forbids_the_top_state(withheld: str) -> None:
    """Every one of the seventeen is load-bearing for 'approved'; none is decorative.

    This is the check that ties reporting to authorization: whatever the stage table says, the
    top resting state is unreachable while ``all_satisfied`` is False.
    """
    requirements = _all_true()
    values = {name: getattr(requirements, name) for name in _FIELD_NAMES}
    values[withheld] = False
    degraded = PaperActivationRequirements(**values)

    state, blockers = derive_resting_state(degraded)
    assert state != "approved", f"{withheld}=False still reported 'approved'"
    assert withheld in blockers


def test_the_reported_state_and_the_blocker_list_never_contradict() -> None:
    """'approved' with a non-empty blocker list is a lie, in either direction."""
    for requirements in (_requirements(), _all_true(), _requirements(valid_lineage=True)):
        state, blockers = derive_resting_state(requirements)
        assert (state == "approved") == (not blockers)


# --- the authorization path was, and remains, unaffected -------------------------------------


def test_the_activation_token_is_refused_even_with_the_stage_table_emptied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the scope claim: emptying the stage table never minted a token.

    If this ever starts passing a token, the defect was an authorization bypass after all and
    the record in the error-correction log understates it.
    """
    monkeypatch.setattr(
        paper, "_STAGE_PREREQUISITES", {"eligible": (), "frozen": (), "approved": ()}
    )
    with pytest.raises(PaperGateError, match="unmet requirements"):
        request_activation_token(_requirements())


def test_control_a_fully_satisfied_requirement_set_does_mint_a_token() -> None:
    """The authorization control: the gate can say yes, so its refusals mean something.

    Uses a synthetic all-true requirement object; it authorizes nothing in the real repository,
    where ``derive_requirements`` reports every one of the seventeen unmet.
    """
    token = request_activation_token(_all_true())
    assert token.requirements.all_satisfied is True


def test_derive_resting_state_never_returns_active() -> None:
    """'active' is a token-gated transition, never a derived resting state."""
    for requirements in (_requirements(), _all_true()):
        assert derive_resting_state(requirements)[0] != "active"


# --- the coverage gap, made explicit ---------------------------------------------------------
#
# The mutation proof surfaced this and it is the more serious half of V2F-EC-003: the stage
# table names only 11 of the 17 requirements. The other six reach the reported state solely
# through the final ``all_satisfied`` check.


def test_the_stage_table_covers_exactly_the_expected_eleven() -> None:
    """Pins the split: moving a requirement in or out is a failure, not a silent change."""
    covered = {name for names in paper._STAGE_PREREQUISITES.values() for name in names}
    assert covered | paper._STAGE_UNCOVERED_REQUIREMENTS == set(_FIELD_NAMES)
    assert covered & paper._STAGE_UNCOVERED_REQUIREMENTS == set()
    assert len(covered) == 11
    assert len(paper._STAGE_UNCOVERED_REQUIREMENTS) == 6


@pytest.mark.parametrize("uncovered", sorted(paper._STAGE_UNCOVERED_REQUIREMENTS))
def test_a_stage_uncovered_requirement_still_forbids_approved(uncovered: str) -> None:
    """These six are exactly the ones no stage would have caught.

    ``repository_private`` and ``sealed_ledgers_intact`` are in this set, which is why the gap
    mattered: a reported "approved" with the repository public is precisely the state that would
    mislead a human into approving.
    """
    values = dict.fromkeys(_FIELD_NAMES, True)
    values[uncovered] = False
    degraded = PaperActivationRequirements(**values)

    # Every stage is satisfied — the stage table alone would say "approved".
    for stage in paper._REQUIRED_STAGES:
        assert paper._stage_satisfied(stage, degraded) is True, (
            f"{uncovered} unexpectedly belongs to stage {stage}; update the coverage split"
        )

    assert derive_resting_state(degraded)[0] == "frozen"


def test_the_two_safety_requirements_are_among_the_uncovered_six() -> None:
    """Stated as its own assertion because it is the reason this gap was worth fixing."""
    assert "repository_private" in paper._STAGE_UNCOVERED_REQUIREMENTS
    assert "sealed_ledgers_intact" in paper._STAGE_UNCOVERED_REQUIREMENTS
