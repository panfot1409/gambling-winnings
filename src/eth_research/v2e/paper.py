"""Paper-execution activation harness — mechanical, fail-closed, and currently disabled.

The lifecycle is ``disabled → eligible → frozen → approved → active → paused → stopped``.
Every forward step is gated on committed evidence; nothing here can start paper trading:

* :class:`PaperActivationRequirements` derives seventeen booleans exclusively from the
  accepted fable5 paper-readiness derivation (:mod:`eth_research.v2.fable5.paper_readiness`)
  plus two dedicated qualification artifacts that do not exist yet (kill-switch and
  monitoring qualification). Absent evidence is ``False`` — the gate is consumed, never
  weakened or re-derived here.
* :func:`derive_resting_state` maps requirements to the lifecycle's resting state and can
  never return ``active``: activation is not a derivable fact, it is an explicit,
  token-gated transition.
* :func:`transition` enforces the edge set and per-stage prerequisites; entering
  ``active`` additionally requires an :class:`ActivationToken` that only
  :func:`request_activation_token` can mint, and only while every requirement holds.
  There is no flag, environment variable, keyword argument, subclass, or alternate
  constructor that skips these checks (the token constructor verifies a module-private
  sentinel and ``transition`` verifies the token's exact type).

With zero nominated candidates the resting state is ``disabled`` and every blocking
reason is reported verbatim for the dashboard to display.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

from eth_research.v2.fable5.paper_readiness import PaperReadinessState, derive_paper_readiness

#: Lifecycle states in canonical order.
LIFECYCLE_STATES: tuple[str, ...] = (
    "disabled",
    "eligible",
    "frozen",
    "approved",
    "active",
    "paused",
    "stopped",
)

#: The complete legal edge set. Anything absent here is refused.
_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "disabled": ("eligible",),
    "eligible": ("frozen", "disabled"),
    "frozen": ("approved", "disabled"),
    "approved": ("active", "disabled"),
    "active": ("paused", "stopped"),
    "paused": ("active", "stopped"),
    "stopped": (),
}

#: Qualification artifacts that must exist (and be objects) before the kill-switch and
#: monitoring requirements can hold. Neither exists today; their absence is honest evidence.
KILL_SWITCH_QUALIFICATION_RELPATH = "governance/v2e/kill_switch_qualification.json"
MONITORING_QUALIFICATION_RELPATH = "governance/v2e/monitoring_qualification.json"


class PaperGateError(RuntimeError):
    """A paper-lifecycle transition or activation-token request was refused."""


@dataclass(frozen=True, slots=True)
class PaperActivationRequirements:
    """Seventeen activation requirements, each derived fail-closed from committed evidence."""

    eligible_nominated_candidate: bool
    immutable_candidate_fingerprint: bool
    valid_lineage: bool
    candidate_not_previously_rejected: bool
    paper_protocol_preregistered: bool
    risk_parameters_frozen: bool
    data_feed_configuration_frozen: bool
    cost_model_frozen: bool
    execution_simulator_frozen: bool
    fable5_acceptance: bool
    no_unresolved_class_abd_defect: bool
    paper_release_source_freeze: bool
    human_approval_artifact: bool
    kill_switch_qualified: bool
    monitoring_qualified: bool
    sealed_ledgers_intact: bool
    repository_private: bool

    @property
    def unmet(self) -> tuple[str, ...]:
        return tuple(f.name for f in fields(self) if getattr(self, f.name) is not True)

    @property
    def all_satisfied(self) -> bool:
        return not self.unmet


def _qualification_present(repo_root: Path, relpath: str) -> bool:
    """A qualification artifact counts only as a plain, non-symlink JSON object file."""
    path = repo_root / relpath
    if path.is_symlink() or not path.is_file():
        return False
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    import json

    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(doc, dict)


def derive_requirements(
    repo_root: str | Path, readiness: PaperReadinessState | None = None
) -> PaperActivationRequirements:
    """Derive the seventeen requirements from the accepted readiness gates + artifacts.

    ``readiness`` may be injected when the caller has already derived (and verified) it,
    so the dashboard consumes one consistent snapshot per refresh.
    """
    root = Path(repo_root)
    state = readiness if readiness is not None else derive_paper_readiness(root)
    gates = state.gates

    def gate(name: str) -> bool:
        return gates.get(name) is True

    candidate = state.eligible_paper_candidate_present is True
    release_frozen = gate("paper_release_candidate_frozen")
    return PaperActivationRequirements(
        eligible_nominated_candidate=candidate,
        immutable_candidate_fingerprint=gate("strategy_specification_immutable"),
        valid_lineage=gate("candidate_lineage_valid"),
        # With no candidate there is nothing to be "not previously rejected": fail closed.
        candidate_not_previously_rejected=candidate,
        paper_protocol_preregistered=gate("paper_duration_and_success_criteria_preregistered"),
        # The four frozen-configuration requirements all ride the paper-release freeze
        # artifact (risk, data feed, costs, simulator are sections of that one freeze).
        risk_parameters_frozen=release_frozen,
        data_feed_configuration_frozen=release_frozen,
        cost_model_frozen=release_frozen,
        execution_simulator_frozen=release_frozen,
        fable5_acceptance=gate("platform_audit_complete") and gate("platform_hardened"),
        no_unresolved_class_abd_defect=gate("no_unresolved_class_abd_finding"),
        paper_release_source_freeze=release_frozen,
        human_approval_artifact=gate("human_activation_approval_recorded"),
        kill_switch_qualified=_qualification_present(root, KILL_SWITCH_QUALIFICATION_RELPATH),
        monitoring_qualified=_qualification_present(root, MONITORING_QUALIFICATION_RELPATH),
        sealed_ledgers_intact=gate("sealed_partitions_untouched"),
        repository_private=gate("repository_private"),
    )


#: Requirements that must hold before each resting stage is reachable. ``active`` is
#: deliberately absent: it is never a resting/derived state, only a token-gated transition.
_STAGE_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "eligible": (
        "eligible_nominated_candidate",
        "immutable_candidate_fingerprint",
        "valid_lineage",
        "candidate_not_previously_rejected",
    ),
    "frozen": (
        "paper_protocol_preregistered",
        "risk_parameters_frozen",
        "data_feed_configuration_frozen",
        "cost_model_frozen",
        "execution_simulator_frozen",
        "paper_release_source_freeze",
    ),
    "approved": ("human_approval_artifact",),
}


def _stage_satisfied(stage: str, requirements: PaperActivationRequirements) -> bool:
    return all(getattr(requirements, name) is True for name in _STAGE_PREREQUISITES[stage])


def derive_resting_state(requirements: PaperActivationRequirements) -> tuple[str, tuple[str, ...]]:
    """Map requirements to the lifecycle resting state (never ``active``) + blockers."""
    if not _stage_satisfied("eligible", requirements):
        return "disabled", requirements.unmet
    if not _stage_satisfied("frozen", requirements):
        return "eligible", requirements.unmet
    if not _stage_satisfied("approved", requirements):
        return "frozen", requirements.unmet
    return "approved", requirements.unmet


_TOKEN_SENTINEL: object = object()


class ActivationToken:
    """Proof that every activation requirement held when the token was minted.

    Constructible only by :func:`request_activation_token` (the constructor demands the
    module-private sentinel object); subclasses are refused at use time by an exact
    ``type`` check in :func:`transition`.
    """

    __slots__ = ("_requirements",)

    def __init__(self, sentinel: object, requirements: PaperActivationRequirements) -> None:
        if sentinel is not _TOKEN_SENTINEL:
            raise PaperGateError("activation tokens are minted only by request_activation_token")
        if not requirements.all_satisfied:
            raise PaperGateError("activation token refused: unmet requirements")
        self._requirements = requirements

    @property
    def requirements(self) -> PaperActivationRequirements:
        return self._requirements


def request_activation_token(requirements: PaperActivationRequirements) -> ActivationToken:
    """Mint an activation token — refused unless every requirement is satisfied."""
    if not requirements.all_satisfied:
        raise PaperGateError(
            "paper activation refused; unmet requirements: " + ", ".join(requirements.unmet)
        )
    return ActivationToken(_TOKEN_SENTINEL, requirements)


def transition(
    current: str,
    target: str,
    requirements: PaperActivationRequirements,
    *,
    token: ActivationToken | None = None,
) -> str:
    """Perform one mechanical lifecycle transition, failing closed on any doubt."""
    if current not in _TRANSITIONS:
        raise PaperGateError(f"unknown lifecycle state {current!r}")
    if target not in LIFECYCLE_STATES:
        raise PaperGateError(f"unknown lifecycle state {target!r}")
    if target not in _TRANSITIONS[current]:
        raise PaperGateError(f"illegal transition {current!r} -> {target!r}")
    if target in _STAGE_PREREQUISITES and not _stage_satisfied(target, requirements):
        raise PaperGateError(
            f"transition to {target!r} refused; unmet: " + ", ".join(requirements.unmet)
        )
    if target == "active":
        if token is None or type(token) is not ActivationToken:
            raise PaperGateError("entering 'active' requires a genuine activation token")
        if not token.requirements.all_satisfied or not requirements.all_satisfied:
            raise PaperGateError("entering 'active' refused: requirements no longer hold")
    return target
