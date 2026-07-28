"""V2E paper-activation harness: mechanical lifecycle, fail-closed gate, no bypass."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from eth_research.v2e.paper import (
    LIFECYCLE_STATES,
    ActivationToken,
    PaperActivationRequirements,
    PaperGateError,
    derive_requirements,
    derive_resting_state,
    request_activation_token,
    transition,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_ALL_TRUE = PaperActivationRequirements(
    **dict.fromkeys((f.name for f in dataclasses.fields(PaperActivationRequirements)), True)
)
_ALL_FALSE = dataclasses.replace(
    _ALL_TRUE, **dict.fromkeys((f.name for f in dataclasses.fields(_ALL_TRUE)), False)
)


class TestDerivation:
    def test_real_repo_rests_disabled_with_exact_blockers(self) -> None:
        requirements = derive_requirements(REPO_ROOT)
        state, blocking = derive_resting_state(requirements)
        assert state == "disabled"
        assert "eligible_nominated_candidate" in blocking
        assert "human_approval_artifact" in blocking
        assert "kill_switch_qualified" in blocking
        assert "monitoring_qualified" in blocking
        # The two invariants that DO hold today:
        assert requirements.sealed_ledgers_intact is True
        # repository_private still derives True — but for a different and honest
        # reason. Until V2F-R it read the PyPI classifier "Private :: Do Not Upload",
        # which governs PyPI uploads, not GitHub visibility, and returned True while
        # the repository was verifiably public. It now derives from a committed
        # GitHub API observation recording private=true.
        assert requirements.repository_private is True
        assert "repository_private" not in blocking

    def test_derivation_can_never_yield_active(self) -> None:
        state, _ = derive_resting_state(_ALL_TRUE)
        assert state == "approved"  # active is a transition, never a resting derivation
        assert "active" in LIFECYCLE_STATES


class TestTransitions:
    def test_legal_chain_to_active_requires_token(self) -> None:
        token = request_activation_token(_ALL_TRUE)
        state = "disabled"
        for target in ("eligible", "frozen", "approved"):
            state = transition(state, target, _ALL_TRUE)
        assert transition(state, "active", _ALL_TRUE, token=token) == "active"
        assert transition("active", "paused", _ALL_TRUE) == "paused"
        assert transition("paused", "stopped", _ALL_TRUE) == "stopped"

    def test_illegal_edges_refuse(self) -> None:
        with pytest.raises(PaperGateError, match="illegal transition"):
            transition("disabled", "active", _ALL_TRUE, token=None)
        with pytest.raises(PaperGateError, match="illegal transition"):
            transition("stopped", "active", _ALL_TRUE)
        with pytest.raises(PaperGateError, match="unknown lifecycle state"):
            transition("disabled", "turbo", _ALL_TRUE)

    def test_stage_prerequisites_fail_closed(self) -> None:
        with pytest.raises(PaperGateError, match="unmet"):
            transition("disabled", "eligible", _ALL_FALSE)
        partial = dataclasses.replace(
            _ALL_FALSE,
            eligible_nominated_candidate=True,
            immutable_candidate_fingerprint=True,
            valid_lineage=True,
            candidate_not_previously_rejected=True,
        )
        assert transition("disabled", "eligible", partial) == "eligible"
        with pytest.raises(PaperGateError, match="unmet"):
            transition("eligible", "frozen", partial)


class TestBypassResistance:
    def test_token_cannot_be_constructed_directly(self) -> None:
        with pytest.raises(PaperGateError, match="minted only"):
            ActivationToken(object(), _ALL_TRUE)

    def test_token_refused_while_requirements_unmet(self) -> None:
        with pytest.raises(PaperGateError, match="unmet requirements"):
            request_activation_token(_ALL_FALSE)

    def test_subclassed_token_is_refused_by_exact_type_check(self) -> None:
        real = request_activation_token(_ALL_TRUE)

        class Forged(ActivationToken):
            def __init__(self) -> None:  # bypasses the sentinel check entirely
                pass

        forged = Forged()
        with pytest.raises(PaperGateError, match="genuine activation token"):
            transition("approved", "active", _ALL_TRUE, token=forged)
        # And a stale token cannot activate once requirements degrade.
        degraded = dataclasses.replace(_ALL_TRUE, sealed_ledgers_intact=False)
        with pytest.raises(PaperGateError):
            transition("approved", "active", degraded, token=real)

    def test_subclassed_requirements_cannot_lie_via_properties(self) -> None:
        # auditor-5 F2: a requirements subclass overriding all_satisfied/unmet must be
        # refused by exact-type checks at minting and at the active transition.
        class Liar(PaperActivationRequirements):
            @property
            def all_satisfied(self) -> bool:
                return True

            @property
            def unmet(self) -> tuple[str, ...]:
                return ()

        liar = Liar(**{f.name: False for f in dataclasses.fields(PaperActivationRequirements)})
        with pytest.raises(PaperGateError, match="exact PaperActivationRequirements"):
            request_activation_token(liar)
        real_token = request_activation_token(_ALL_TRUE)
        with pytest.raises(PaperGateError, match="exact PaperActivationRequirements"):
            transition("approved", "active", liar, token=real_token)

    def test_environment_variables_do_not_exist_as_a_bypass(self) -> None:
        os.environ["V2E_PAPER_FORCE"] = "1"
        try:
            with pytest.raises(PaperGateError):
                transition("approved", "active", _ALL_FALSE, token=None)
            state, _ = derive_resting_state(derive_requirements(REPO_ROOT))
            assert state == "disabled"
        finally:
            del os.environ["V2E_PAPER_FORCE"]

    def test_requirements_are_immutable(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            _ALL_TRUE.sealed_ledgers_intact = False  # type: ignore[misc]

    def test_qualification_artifacts_must_be_json_objects_not_symlinks(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path
        rel = "governance/v2e/kill_switch_qualification.json"
        target = root / rel
        target.parent.mkdir(parents=True)
        target.write_text("[]\n", "utf-8")  # a list is not a qualification object
        from eth_research.v2e.paper import _qualification_present

        assert _qualification_present(root, rel) is False
        target.unlink()
        real = target.with_name("real.json")
        real.write_text("{}\n", "utf-8")
        target.symlink_to(real.name)
        assert _qualification_present(root, rel) is False
