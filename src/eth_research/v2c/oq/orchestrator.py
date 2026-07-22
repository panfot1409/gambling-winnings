"""V2C sections 11 + 12: the fail-closed OQ orchestrator + calculation-before-start proof.

The orchestrator is the only sanctioned path from a frozen, registered qualification to a *started*
one. It enforces an ordered, fail-closed pre-start gate sequence -- the exact order in which every
governance, firewall, identity, freeze, supersession, sealed-partition, and lifecycle precondition
must hold -- and it refuses to move the registry to ``started`` unless every gate passes. Nothing
here runs the qualification, computes an operational count, or evaluates an SLO. It decides only
whether the run may start and, if so, records the durable ``started`` event.

The calculation-before-start guarantee (section 12) is structural, not aspirational. Computation
requires a :class:`StartedToken`, and the only way to obtain one is :func:`start_qualification`,
which runs the full gate sequence, appends the ``started`` event with durable ``fsync`` semantics,
and reads the registry back to confirm it is exactly ``started`` *before* it returns the token. The
Step-4 runner takes a ``StartedToken`` and re-asserts it (:func:`assert_started`) before touching
the harness, so no operational count or SLO runs while the registry is still ``pristine`` or
``registered``. A run that fails any gate never reaches ``started``; a run that reaches ``started``
has provably passed every gate first.

Key refusals (each a named gate, fail-closed): the premature ``e4b3cc3`` freeze can never authorize
(it must be recorded superseded, and the authoritative freeze must NOT be superseded); the OQ source
freeze and the protocol bundle must reproduce byte-for-byte from live source; the identity must bind
the committed protocol/fixture/fault-schedule/SLO/cash-control/source-freeze/runtime artifacts by
their exact byte hash; all three sealed access ledgers must be byte-empty; the firewall must admit
only ``cash_control`` at zero exposure and refuse every legacy candidate id and forbidden request
kind; the runtime must be CPython 3.12; and OQ-E2 CI must be attested terminal-green.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eth_research.environment import CANONICAL_RUNTIME_CONTRACT_RELPATH
from eth_research.m3d.validation import M3DValidationError
from eth_research.v2.strict import V2ValidationError, sha256_bytes
from eth_research.v2c.firewall import (
    CASH_CONTROL_TARGET_ID,
    FORBIDDEN_REQUEST_KINDS,
    KNOWN_LEGACY_CANDIDATE_IDS,
    V2CFirewallError,
    assert_no_candidate_reference,
    guard_request_kind,
    resolve_operational_target,
)
from eth_research.v2c.oq.freeze import (
    OQ_SOURCE_FREEZE_RELPATH,
    verify_oq_source_freeze,
)
from eth_research.v2c.oq.protocol import (
    OQ_CASH_CONTROL_IDENTITY_RELPATH,
    OQ_FAULT_SCHEDULE_RELPATH,
    OQ_FIXTURE_MANIFEST_RELPATH,
    OQ_METHODOLOGY_ID,
    OQ_PROTOCOL_RELPATH,
    OQ_QUALIFICATION_ID,
    OQ_SLO_CONTRACT_RELPATH,
    committed_artifact_sha256,
    verify_oq_protocol_bundle,
)
from eth_research.v2c.oq.registry import (
    OQ_EVENT_REGISTERED,
    OQ_EVENT_STARTED,
    OQEvent,
    QualificationIdentity,
    append_oq_event,
    read_oq_registry,
    registry_state,
)
from eth_research.v2c.oq.supersession import (
    EMPTY_SHA256,
    SEALED_LEDGER_RELPATHS,
    assert_freeze_not_superseded,
    assert_freeze_superseded,
)

#: The premature OQ-E freeze (commit ``e4b3cc3``) that must be recorded superseded before any
#: registration or execution. Bound here so the orchestrator refuses it structurally.
PREMATURE_OQ_FREEZE_COMMIT: str = "e4b3cc3d6ecfa0d58dd4c71c01f06b2e252ba6ee"

#: The runtime the qualification must run on (section 0 of the milestone contract).
REQUIRED_PYTHON_IMPLEMENTATION: str = "cpython"
REQUIRED_PYTHON_MAJOR_MINOR: tuple[int, int] = (3, 12)

#: The registry pre-states each transition requires.
_PRE_STATE_REGISTER: str = "pristine"
_PRE_STATE_START: str = "registered"


class OQOrchestratorError(V2ValidationError):
    """A pre-start gate failed, or a lifecycle transition was attempted out of order."""


@dataclass(frozen=True, slots=True)
class QualificationContext:
    """Everything the orchestrator needs to decide whether the run may start.

    ``registry_path`` is explicit so the canonical registry and disposable test registries are both
    supported; the supersession ledger and every governance artifact are read from ``repo_root``.
    """

    repo_root: Path
    registry_path: Path
    supersession_path: Path
    identity: QualificationIdentity
    source_freeze_id: str
    source_freeze_commit: str
    ci_terminal_success: bool
    premature_freeze_commit: str = PREMATURE_OQ_FREEZE_COMMIT


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """One pre-start gate and whether it held."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """The full ordered pre-start gate evaluation (non-raising; for status/audit)."""

    gates: tuple[GateOutcome, ...]
    passed: bool


@dataclass(frozen=True, slots=True)
class StartedToken:
    """Proof that the registry is durably ``started`` -- the runner's only entry to computation.

    Obtainable only from :func:`start_qualification`, which appends the ``started`` event and reads
    it back before minting the token. The runner re-asserts it via :func:`assert_started` before it
    computes anything, so no operational count or SLO is produced before the durable ``started``.
    """

    qualification_id: str
    registry_path: str
    started_ordinal: int
    started_entry_hash: str


# --------------------------------------------------------------------------- #
# The ordered pre-start gate sequence                                         #
# --------------------------------------------------------------------------- #
def _gate_repo_root_is_directory(ctx: QualificationContext, _expect: str) -> str:
    root = ctx.repo_root
    if root.is_symlink() or not root.is_dir():
        raise OQOrchestratorError(f"repo_root {root} is not a real directory")
    return "repo_root is a real directory"


def _gate_runtime_is_python_3_12(ctx: QualificationContext, _expect: str) -> str:
    impl = sys.implementation.name.lower()
    version = sys.version_info[:2]
    if impl != REQUIRED_PYTHON_IMPLEMENTATION or version != REQUIRED_PYTHON_MAJOR_MINOR:
        raise OQOrchestratorError(
            f"runtime {impl} {version[0]}.{version[1]} is not the required CPython "
            f"{REQUIRED_PYTHON_MAJOR_MINOR[0]}.{REQUIRED_PYTHON_MAJOR_MINOR[1]}"
        )
    return f"runtime is CPython {version[0]}.{version[1]}"


def _gate_runtime_contract_present(ctx: QualificationContext, _expect: str) -> str:
    path = ctx.repo_root / CANONICAL_RUNTIME_CONTRACT_RELPATH
    if path.is_symlink() or not path.is_file():
        raise OQOrchestratorError("the authoritative runtime contract is missing")
    return "authoritative runtime contract present"


def _gate_source_freeze_reproduces(ctx: QualificationContext, _expect: str) -> str:
    verify_oq_source_freeze(ctx.repo_root)
    return "OQ source freeze reproduces from live source"


def _gate_source_freeze_not_superseded(ctx: QualificationContext, _expect: str) -> str:
    assert_freeze_not_superseded(ctx.supersession_path, ctx.source_freeze_commit)
    return "authoritative source freeze is not superseded"


def _gate_premature_freeze_superseded(ctx: QualificationContext, _expect: str) -> str:
    assert_freeze_superseded(ctx.supersession_path, ctx.premature_freeze_commit)
    return "premature e4b3cc3 freeze is recorded superseded"


def _gate_protocol_bundle_reproduces(ctx: QualificationContext, _expect: str) -> str:
    verify_oq_protocol_bundle(ctx.repo_root)
    return "OQ protocol bundle reproduces from live source"


def _bound(ctx: QualificationContext, field: str, relpath: str) -> str:
    got = getattr(ctx.identity, field)
    expected = committed_artifact_sha256(ctx.repo_root, relpath)
    if got != expected:
        raise OQOrchestratorError(
            f"identity.{field} does not bind the committed {relpath} ({got} != {expected})"
        )
    return f"identity.{field} binds committed {relpath}"


def _gate_identity_binds_protocol(ctx: QualificationContext, _expect: str) -> str:
    return _bound(ctx, "protocol_sha256", OQ_PROTOCOL_RELPATH)


def _gate_identity_binds_fixture(ctx: QualificationContext, _expect: str) -> str:
    return _bound(ctx, "fixture_sha256", OQ_FIXTURE_MANIFEST_RELPATH)


def _gate_identity_binds_fault_schedule(ctx: QualificationContext, _expect: str) -> str:
    return _bound(ctx, "fault_schedule_sha256", OQ_FAULT_SCHEDULE_RELPATH)


def _gate_identity_binds_slo_contract(ctx: QualificationContext, _expect: str) -> str:
    return _bound(ctx, "slo_contract_sha256", OQ_SLO_CONTRACT_RELPATH)


def _gate_identity_binds_cash_control(ctx: QualificationContext, _expect: str) -> str:
    return _bound(ctx, "cash_control_identity", OQ_CASH_CONTROL_IDENTITY_RELPATH)


def _gate_identity_binds_source_freeze(ctx: QualificationContext, _expect: str) -> str:
    return _bound(ctx, "source_freeze_sha256", OQ_SOURCE_FREEZE_RELPATH)


def _gate_identity_binds_runtime_contract(ctx: QualificationContext, _expect: str) -> str:
    return _bound(ctx, "runtime_contract_sha256", CANONICAL_RUNTIME_CONTRACT_RELPATH)


def _gate_identity_source_freeze_id_matches(ctx: QualificationContext, _expect: str) -> str:
    if ctx.identity.source_freeze_id != ctx.source_freeze_id:
        raise OQOrchestratorError(
            f"identity.source_freeze_id {ctx.identity.source_freeze_id!r} != "
            f"context source_freeze_id {ctx.source_freeze_id!r}"
        )
    return "identity source_freeze_id matches the authoritative freeze"


def _gate_identity_ids_match_protocol(ctx: QualificationContext, _expect: str) -> str:
    if ctx.identity.qualification_id != OQ_QUALIFICATION_ID:
        raise OQOrchestratorError("identity.qualification_id is not the protocol qualification id")
    if ctx.identity.methodology_id != OQ_METHODOLOGY_ID:
        raise OQOrchestratorError("identity.methodology_id is not the protocol methodology id")
    return "identity qualification/methodology ids match the protocol"


def _gate_sealed_ledgers_byte_empty(ctx: QualificationContext, _expect: str) -> str:
    for relpath in SEALED_LEDGER_RELPATHS:
        path = ctx.repo_root / relpath
        if path.is_symlink() or not path.is_file():
            raise OQOrchestratorError(f"sealed ledger {relpath} is missing or not a real file")
        if sha256_bytes(path.read_bytes()) != EMPTY_SHA256:
            raise OQOrchestratorError(f"sealed ledger {relpath} is not byte-empty")
    return "all three sealed access ledgers are byte-empty"


def _gate_firewall_admits_only_cash_control(ctx: QualificationContext, _expect: str) -> str:
    if guard_request_kind("cash_control_operation") != "cash_control_operation":
        raise OQOrchestratorError("firewall did not admit cash_control_operation")
    if resolve_operational_target(CASH_CONTROL_TARGET_ID).target_id != CASH_CONTROL_TARGET_ID:
        raise OQOrchestratorError("firewall did not resolve the cash_control target")
    for candidate_id in KNOWN_LEGACY_CANDIDATE_IDS:
        try:
            resolve_operational_target(candidate_id)
        except V2CFirewallError:
            continue
        raise OQOrchestratorError(f"firewall failed to refuse legacy candidate id {candidate_id!r}")
    for kind in sorted(FORBIDDEN_REQUEST_KINDS):
        try:
            guard_request_kind(kind)
        except V2CFirewallError:
            continue
        raise OQOrchestratorError(f"firewall failed to refuse forbidden request kind {kind!r}")
    return "firewall admits only cash_control and refuses every candidate/forbidden kind"


def _gate_no_candidate_reference_in_identity(ctx: QualificationContext, _expect: str) -> str:
    for field in (
        "qualification_id",
        "methodology_id",
        "cash_control_identity",
        "source_freeze_id",
    ):
        assert_no_candidate_reference(f"identity.{field}", getattr(ctx.identity, field))
    return "no candidate reference appears in the qualification identity"


def _gate_registry_is_not_symlink(ctx: QualificationContext, _expect: str) -> str:
    if ctx.registry_path.is_symlink():
        raise OQOrchestratorError("the OQ registry path is a symlink")
    return "the OQ registry is not a symlink"


def _gate_registry_state_permits(ctx: QualificationContext, expect: str) -> str:
    state = registry_state(ctx.registry_path)
    if state != expect:
        raise OQOrchestratorError(
            f"registry state {state!r} does not permit this transition (expected {expect!r})"
        )
    return f"registry state is {expect!r}, as required for this transition"


def _gate_ci_terminal_success_attested(ctx: QualificationContext, _expect: str) -> str:
    if ctx.ci_terminal_success is not True:
        raise OQOrchestratorError("OQ-E2 CI is not attested terminal-success")
    return "OQ-E2 CI is attested terminal-success"


#: The ordered pre-start gate sequence. Order is part of the contract: structural preconditions
#: first, then freeze/supersession, then protocol/identity binding, then sealed state, then the
#: firewall, then the registry lifecycle, and finally the external CI attestation.
_GATE_SEQUENCE: tuple[tuple[str, Callable[[QualificationContext, str], str]], ...] = (
    ("repo_root_is_directory", _gate_repo_root_is_directory),
    ("runtime_is_python_3_12", _gate_runtime_is_python_3_12),
    ("runtime_contract_present", _gate_runtime_contract_present),
    ("source_freeze_reproduces", _gate_source_freeze_reproduces),
    ("source_freeze_not_superseded", _gate_source_freeze_not_superseded),
    ("premature_freeze_superseded", _gate_premature_freeze_superseded),
    ("protocol_bundle_reproduces", _gate_protocol_bundle_reproduces),
    ("identity_binds_protocol", _gate_identity_binds_protocol),
    ("identity_binds_fixture", _gate_identity_binds_fixture),
    ("identity_binds_fault_schedule", _gate_identity_binds_fault_schedule),
    ("identity_binds_slo_contract", _gate_identity_binds_slo_contract),
    ("identity_binds_cash_control", _gate_identity_binds_cash_control),
    ("identity_binds_source_freeze", _gate_identity_binds_source_freeze),
    ("identity_binds_runtime_contract", _gate_identity_binds_runtime_contract),
    ("identity_source_freeze_id_matches", _gate_identity_source_freeze_id_matches),
    ("identity_ids_match_protocol", _gate_identity_ids_match_protocol),
    ("sealed_ledgers_byte_empty", _gate_sealed_ledgers_byte_empty),
    ("firewall_admits_only_cash_control", _gate_firewall_admits_only_cash_control),
    ("no_candidate_reference_in_identity", _gate_no_candidate_reference_in_identity),
    ("registry_is_not_symlink", _gate_registry_is_not_symlink),
    ("registry_state_permits", _gate_registry_state_permits),
    ("ci_terminal_success_attested", _gate_ci_terminal_success_attested),
)

#: The ordered gate names, for audit and documentation.
GATE_ORDER: tuple[str, ...] = tuple(name for name, _ in _GATE_SEQUENCE)


def assert_preflight(ctx: QualificationContext, *, expect_state: str) -> tuple[str, ...]:
    """Run the ordered pre-start gates, fail-closed on the first failure.

    Returns the ordered pass details on success; raises :class:`OQOrchestratorError` naming the
    first failing gate otherwise. This is the authoritative gate used by register/start.
    """
    details: list[str] = []
    for name, gate in _GATE_SEQUENCE:
        try:
            details.append(gate(ctx, expect_state))
        except OQOrchestratorError:
            raise
        except (V2ValidationError, M3DValidationError, OSError) as exc:
            # The freeze/protocol errors are V2ValidationError; the supersession and registry
            # errors are M3DValidationError -- a different ValueError tree. Both fail closed.
            raise OQOrchestratorError(f"pre-start gate {name!r} failed: {exc}") from exc
    return tuple(details)


def preflight_report(ctx: QualificationContext, *, expect_state: str) -> PreflightReport:
    """Evaluate every pre-start gate without raising (for read-only status/audit)."""
    outcomes: list[GateOutcome] = []
    for name, gate in _GATE_SEQUENCE:
        try:
            detail = gate(ctx, expect_state)
            outcomes.append(GateOutcome(name, True, detail))
        except (V2ValidationError, M3DValidationError, OSError) as exc:
            outcomes.append(GateOutcome(name, False, str(exc)))
    return PreflightReport(tuple(outcomes), all(outcome.passed for outcome in outcomes))


# --------------------------------------------------------------------------- #
# Lifecycle transitions (OQ-R register; OQ-P start)                           #
# --------------------------------------------------------------------------- #
def register_qualification(
    ctx: QualificationContext, *, event_time_utc: str, reason: str
) -> OQEvent:
    """OQ-R: run the pre-start gates against a pristine registry, then append ``registered``."""
    assert_preflight(ctx, expect_state=_PRE_STATE_REGISTER)
    return append_oq_event(
        ctx.registry_path,
        identity=ctx.identity,
        event=OQ_EVENT_REGISTERED,
        event_time_utc=event_time_utc,
        reason=reason,
    )


def start_qualification(
    ctx: QualificationContext, *, event_time_utc: str, reason: str
) -> StartedToken:
    """OQ-P (start): run the pre-start gates against a registered registry, append ``started``
    durably, read it back, and mint the :class:`StartedToken` the runner requires to compute.

    The gate sequence runs *before* the append, and the token is minted only after the durable
    ``started`` event is read back as the registry's terminal-so-far state -- so computation, which
    requires the token, can never precede the durable ``started``.
    """
    assert_preflight(ctx, expect_state=_PRE_STATE_START)
    started = append_oq_event(
        ctx.registry_path,
        identity=ctx.identity,
        event=OQ_EVENT_STARTED,
        event_time_utc=event_time_utc,
        reason=reason,
    )
    # Read the durable registry back: it must be exactly ``started`` and end on the appended event.
    events = read_oq_registry(ctx.registry_path)
    if registry_state(ctx.registry_path) != "started":
        raise OQOrchestratorError(
            "registry did not read back as 'started' after the durable append"
        )
    if not events or events[-1].entry_hash != started.entry_hash:
        raise OQOrchestratorError("registry tail does not match the appended 'started' event")
    return StartedToken(
        qualification_id=ctx.identity.qualification_id,
        registry_path=str(ctx.registry_path),
        started_ordinal=events[-1].event_ordinal,
        started_entry_hash=started.entry_hash,
    )


def assert_started(token: StartedToken) -> None:
    """Re-assert that the registry named by ``token`` is durably ``started`` on this token's event.

    The Step-4 runner calls this immediately before it computes anything, so a token cannot be used
    against a registry that is not actually ``started`` (or was rolled back), and no operational
    count or SLO can be produced while the registry is ``pristine`` or ``registered``.
    """
    path = Path(token.registry_path)
    if registry_state(path) != "started":
        raise OQOrchestratorError("StartedToken does not correspond to a 'started' registry")
    events = read_oq_registry(path)
    if not events or events[-1].entry_hash != token.started_entry_hash:
        raise OQOrchestratorError("StartedToken entry hash does not match the registry tail")
    if events[-1].event_ordinal != token.started_ordinal:
        raise OQOrchestratorError("StartedToken ordinal does not match the registry tail")


__all__ = [
    "GATE_ORDER",
    "PREMATURE_OQ_FREEZE_COMMIT",
    "GateOutcome",
    "OQOrchestratorError",
    "PreflightReport",
    "QualificationContext",
    "StartedToken",
    "assert_preflight",
    "assert_started",
    "preflight_report",
    "register_qualification",
    "start_qualification",
]
