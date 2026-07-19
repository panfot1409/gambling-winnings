"""The V2A commercial-evidence constitution: what may be claimed, and the rails that bound it.

This module is the single authority for the V2A **claim-status vocabulary**. Commercial evidence
is only worth anything if it never overclaims, so the constitution fixes exactly which claim
statuses V2A may emit and which are reserved for later, sealed, or forward milestones — and it
fails closed on any artifact that reaches for a reserved status.

V2A may emit only:

* ``research_only_observation`` — a descriptive observation on the authorized research-train
  partition, asserting nothing about out-of-sample behaviour.
* ``research_stage_supported`` — a candidate met its *pre-registered* research-train rule; this is
  a research-stage signal only, explicitly **not** an out-of-sample, forward, or live claim.
* ``research_stage_rejected`` — a candidate failed its pre-registered rule (a valid outcome).
* ``eligible_for_development_gate_review`` — at most one candidate may carry this: it is a request
  for a *later, independent* development-gate review, not a statement that the gate passed.
* ``not_sell_ready`` — the standing, honest posture of the whole programme.

Reserved (V2A must reject any artifact claiming them): ``development_gate_supported``,
``development_gate_rejected``, ``final_holdout_supported``, ``final_holdout_rejected``,
``forward_shadow_immature``, ``forward_shadow_supported``, ``paper_record_supported``,
``live_record_supported``, ``sell_ready``.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_bool,
    require_exact_keys,
    require_mapping,
    require_nonempty_str,
)

CONSTITUTION_SCHEMA_VERSION: int = 1

# The only claim statuses a V2A artifact may assert.
V2A_EMITTABLE_STATUSES: frozenset[str] = frozenset(
    {
        "research_only_observation",
        "research_stage_supported",
        "research_stage_rejected",
        "eligible_for_development_gate_review",
        "not_sell_ready",
    }
)

# Statuses reserved for later, sealed, or forward milestones. V2A must never emit these; an
# artifact that claims one is a governance violation and is rejected fail-closed.
RESERVED_STATUSES: frozenset[str] = frozenset(
    {
        "development_gate_supported",
        "development_gate_rejected",
        "final_holdout_supported",
        "final_holdout_rejected",
        "forward_shadow_immature",
        "forward_shadow_supported",
        "paper_record_supported",
        "live_record_supported",
        "sell_ready",
    }
)

ALL_KNOWN_STATUSES: frozenset[str] = V2A_EMITTABLE_STATUSES | RESERVED_STATUSES

# The standing programme posture. V2A can never move off this.
STANDING_POSTURE: str = "not_sell_ready"

# The immutable governing principles carried into every V2A artifact. Stored as an ordered tuple of
# (id, statement) so the constitution serializes to stable bytes and can be committed + verified.
PRINCIPLES: tuple[tuple[str, str], ...] = (
    (
        "no_overclaim",
        "No V2A artifact may assert a claim status outside the V2A-emittable set; research-train "
        "inference never establishes out-of-sample, forward, or live performance.",
    ),
    (
        "evidence_traceable",
        "Every emitted claim must trace, through the lineage graph, to committed evidence whose "
        "bytes are hashed; a claim with no supporting evidence is rejected.",
    ),
    (
        "one_shot_research",
        "The governed candidate programme is evaluated exactly once on the authorized "
        "research-train partition; a started run consumes the one-shot budget even if it fails.",
    ),
    (
        "sealed_gates_untouched",
        "The development gate, the final holdout, and the M3D prospective cohort are never "
        "accessed for strategy evaluation; any such access is a hard stop.",
    ),
    (
        "standing_not_sell_ready",
        "The whole programme's standing posture is not_sell_ready; V2A cannot and does not "
        "establish sell-readiness, profitability, or production-readiness.",
    ),
)


class ConstitutionError(V2ValidationError):
    """A claim or artifact violated the commercial-evidence constitution."""


def require_v2a_emittable_status(label: str, value: object) -> str:
    """Return ``value`` iff it is a V2A-emittable claim status; reject reserved / unknown ones.

    Reserved statuses get a distinct, explicit message because emitting one is the exact
    overclaim the constitution exists to prevent.
    """
    text = require_nonempty_str(label, value)
    if text in RESERVED_STATUSES:
        raise ConstitutionError(
            f"{label} claims the reserved status {text!r}, which V2A must never emit "
            f"(reserved for a later, sealed, or forward milestone)"
        )
    if text not in V2A_EMITTABLE_STATUSES:
        raise ConstitutionError(
            f"{label} is not a known claim status: {text!r}; "
            f"V2A-emittable statuses are {sorted(V2A_EMITTABLE_STATUSES)!r}"
        )
    return text


@dataclass(frozen=True, slots=True)
class CommercialEvidenceConstitution:
    """The committed, hashable statement of what V2A may claim and the rails that bound it."""

    schema_version: int
    standing_posture: str
    emittable_statuses: tuple[str, ...]
    reserved_statuses: tuple[str, ...]
    principles: tuple[tuple[str, str], ...]

    @staticmethod
    def current() -> CommercialEvidenceConstitution:
        return CommercialEvidenceConstitution(
            schema_version=CONSTITUTION_SCHEMA_VERSION,
            standing_posture=STANDING_POSTURE,
            emittable_statuses=tuple(sorted(V2A_EMITTABLE_STATUSES)),
            reserved_statuses=tuple(sorted(RESERVED_STATUSES)),
            principles=PRINCIPLES,
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "standing_posture": self.standing_posture,
            "emittable_statuses": list(self.emittable_statuses),
            "reserved_statuses": list(self.reserved_statuses),
            "principles": [{"id": pid, "statement": text} for pid, text in self.principles],
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())


def parse_constitution(raw: object) -> CommercialEvidenceConstitution:
    """Strictly decode a committed constitution artifact and re-assert its invariants."""
    obj = require_mapping("constitution", raw)
    require_exact_keys(
        "constitution",
        obj,
        frozenset(
            {
                "schema_version",
                "standing_posture",
                "emittable_statuses",
                "reserved_statuses",
                "principles",
            }
        ),
    )
    if obj["schema_version"] != CONSTITUTION_SCHEMA_VERSION:
        raise ConstitutionError(
            f"constitution.schema_version must be {CONSTITUTION_SCHEMA_VERSION}, "
            f"got {obj['schema_version']!r}"
        )
    posture = require_nonempty_str("constitution.standing_posture", obj["standing_posture"])
    if posture != STANDING_POSTURE:
        raise ConstitutionError(
            f"constitution.standing_posture must be {STANDING_POSTURE!r}, got {posture!r}"
        )

    emittable = _require_status_set("constitution.emittable_statuses", obj["emittable_statuses"])
    if emittable != V2A_EMITTABLE_STATUSES:
        raise ConstitutionError("constitution.emittable_statuses does not match the fixed V2A set")
    reserved = _require_status_set("constitution.reserved_statuses", obj["reserved_statuses"])
    if reserved != RESERVED_STATUSES:
        raise ConstitutionError(
            "constitution.reserved_statuses does not match the fixed reserved set"
        )

    principles = _require_principles(obj["principles"])
    parsed = CommercialEvidenceConstitution(
        schema_version=CONSTITUTION_SCHEMA_VERSION,
        standing_posture=posture,
        emittable_statuses=tuple(sorted(emittable)),
        reserved_statuses=tuple(sorted(reserved)),
        principles=principles,
    )
    if parsed.fingerprint() != CommercialEvidenceConstitution.current().fingerprint():
        raise ConstitutionError("constitution content drifted from the fixed V2A constitution")
    return parsed


def _require_status_set(label: str, value: object) -> frozenset[str]:
    if not isinstance(value, list):
        raise ConstitutionError(f"{label} must be a JSON array")
    items = [require_nonempty_str(f"{label}[{i}]", v) for i, v in enumerate(value)]
    if len(set(items)) != len(items):
        raise ConstitutionError(f"{label} contains duplicate statuses")
    return frozenset(items)


def _require_principles(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise ConstitutionError("constitution.principles must be a JSON array")
    parsed: list[tuple[str, str]] = []
    for i, entry in enumerate(value):
        obj = require_mapping(f"constitution.principles[{i}]", entry)
        require_exact_keys(f"constitution.principles[{i}]", obj, frozenset({"id", "statement"}))
        pid = require_nonempty_str(f"constitution.principles[{i}].id", obj["id"])
        text = require_nonempty_str(f"constitution.principles[{i}].statement", obj["statement"])
        parsed.append((pid, text))
    if tuple(parsed) != PRINCIPLES:
        raise ConstitutionError("constitution.principles drifted from the fixed principles")
    return tuple(parsed)


def is_reserved_status(text: str) -> bool:
    """True iff ``text`` is a reserved (non-emittable) status."""
    return text in RESERVED_STATUSES


def assert_no_reserved_status(label: str, statuses: object) -> None:
    """Fail closed if any status in the iterable ``statuses`` is reserved.

    Used by whole-artifact scanners (results, factsheets, publications) to guarantee no reserved
    status leaks into any V2A output, wherever it appears.
    """
    if not isinstance(statuses, (list, tuple, set, frozenset)):
        raise ConstitutionError(f"{label} must be an iterable of statuses")
    for i, status in enumerate(statuses):
        text = require_nonempty_str(f"{label}[{i}]", status)
        if text in RESERVED_STATUSES:
            raise ConstitutionError(
                f"{label}[{i}] is the reserved status {text!r}; V2A must never emit it"
            )


def constitution_flag() -> bool:
    """Cheap import-time truthy marker (kept for symmetry with sibling governance modules)."""
    return require_bool("constitution_flag", True)
