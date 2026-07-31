"""Paper activation is decided by an exact required-gate set, never by a vacuous reduction.

``authorized = all(gates[g] for g in PAPER_ACTIVATION_GATES)`` reads correctly and is wrong
in one specific way: ``all(())`` is ``True``. Rebinding the module-level sequence to ``()``
produced ``paper_activation_authorized = True`` with ``blocking_gates = ()`` while the gate
vector still honestly reported six unmet gates — an authorization that contradicted its own
evidence. Reducing over replaceable data makes the *collection* the authority. Naming the
requirement makes the *requirement* the authority.

Scope, stated because overclaiming here would repeat an earlier mistake: this does NOT make
the module safe against arbitrary in-process code execution. An attacker who can rebind
``PAPER_ACTIVATION_GATES`` can rebind ``_authorized`` itself. What it does is remove a
failure mode reachable by replacing one innocuous-looking constant, and make the two
directions (authorization, and the list of what is blocking) provably describe the same set.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import eth_research.v2.fable5.paper_readiness as pr
from eth_research.v2.fable5.paper_readiness import (
    PAPER_ACTIVATION_GATES,
    REQUIRED_PAPER_ACTIVATION_GATES,
    derive_paper_readiness,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _honest_gates() -> dict[str, bool]:
    """A gate vector with every required key present and true."""
    return dict.fromkeys(REQUIRED_PAPER_ACTIVATION_GATES, True)


# --- controls: the valid case must still authorize, and the real repo must not -----------


def test_control_a_complete_true_vector_authorizes() -> None:
    """Without this, every refusal below could be a check that rejects everything."""
    assert pr._authorized(_honest_gates()) is True


def test_control_the_real_repository_does_not_authorize() -> None:
    state = derive_paper_readiness(REPO_ROOT)
    assert state.paper_activation_authorized is False
    assert state.blocking_gates, "blocking_gates must name why, not be silently empty"


def test_the_two_gate_collections_describe_the_same_set() -> None:
    """Ordering tuple and required set must not drift apart."""
    assert set(PAPER_ACTIVATION_GATES) == REQUIRED_PAPER_ACTIVATION_GATES
    assert len(PAPER_ACTIVATION_GATES) == len(REQUIRED_PAPER_ACTIVATION_GATES), "duplicate name"


# --- the vacuous-reduction bypass ---------------------------------------------------------


def test_an_empty_ordering_tuple_cannot_authorize(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact reproduction: ``all(())`` is True, so an empty sequence authorized.

    Reproduced against the pre-fix module as ``authorized=True, blocking_gates=()`` while the
    gate vector still showed unmet gates.
    """
    monkeypatch.setattr(pr, "PAPER_ACTIVATION_GATES", ())
    assert derive_paper_readiness(REPO_ROOT).paper_activation_authorized is False


def test_an_empty_requirement_authorizes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Emptying the requirement itself must also refuse, not authorize vacuously."""
    monkeypatch.setattr(pr, "REQUIRED_PAPER_ACTIVATION_GATES", frozenset())
    assert pr._authorized(_honest_gates()) is False
    assert pr._authorized({}) is False


def test_a_shortened_ordering_tuple_cannot_authorize(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dropping the inconvenient gates from the sequence must not narrow the requirement."""
    monkeypatch.setattr(pr, "PAPER_ACTIVATION_GATES", ("repository_private",))
    assert derive_paper_readiness(REPO_ROOT).paper_activation_authorized is False


# --- exact key-set discipline -------------------------------------------------------------


@pytest.mark.parametrize("missing", sorted(REQUIRED_PAPER_ACTIVATION_GATES))
def test_every_single_omitted_gate_refuses(missing: str) -> None:
    """Each required name is load-bearing on its own — no gate is decorative."""
    gates = _honest_gates()
    del gates[missing]
    assert pr._authorized(gates) is False, f"omitting {missing} still authorized"


@pytest.mark.parametrize("falsified", sorted(REQUIRED_PAPER_ACTIVATION_GATES))
def test_every_single_false_gate_refuses(falsified: str) -> None:
    gates = _honest_gates()
    gates[falsified] = False
    assert pr._authorized(gates) is False, f"{falsified}=False still authorized"


def test_an_extra_gate_refuses() -> None:
    """An unrecognized key means the caller is not speaking the validated schema."""
    gates = _honest_gates()
    gates["some_new_gate_nobody_validated"] = True
    assert pr._authorized(gates) is False


def test_an_empty_gate_vector_refuses() -> None:
    assert pr._authorized({}) is False


# --- strict boolean discipline ------------------------------------------------------------


@pytest.mark.parametrize(
    "truthy",
    [1, 1.0, "true", "yes", [1], {"v": 1}, object()],
    ids=["int", "float", "str-true", "str-yes", "list", "dict", "object"],
)
def test_a_truthy_non_bool_refuses(truthy: object) -> None:
    """``is True``, not truthiness — the same conflation fixed elsewhere in this module."""
    gates = _honest_gates()
    gates["repository_private"] = truthy  # type: ignore[assignment]
    assert pr._authorized(gates) is False, f"{truthy!r} was accepted as True"


@pytest.mark.parametrize(
    "falsy", [0, 0.0, "", None, [], {}], ids=["0", "0.0", "empty", "None", "list", "dict"]
)
def test_a_falsy_non_bool_refuses(falsy: object) -> None:
    gates = _honest_gates()
    gates["repository_private"] = falsy  # type: ignore[assignment]
    assert pr._authorized(gates) is False


# --- the derived state stays self-consistent ----------------------------------------------


def test_authorization_agrees_with_blocking_gates() -> None:
    """A state that authorizes while naming blockers, or blocks while naming none, is a lie."""
    state = derive_paper_readiness(REPO_ROOT)
    assert state.paper_activation_authorized == (not state.blocking_gates)


def test_blocking_gates_are_exactly_the_false_required_gates() -> None:
    state = derive_paper_readiness(REPO_ROOT)
    expected = {name for name in REQUIRED_PAPER_ACTIVATION_GATES if state.gates[name] is not True}
    assert set(state.blocking_gates) == expected
