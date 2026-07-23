"""V2C section 32: the qualification-readiness derivation (sell_ready is *derived* false).

Rather than asserting the programme is not sell-ready, this module **derives** it. Sell-readiness is
the conjunction of a fixed set of gates -- operational qualification, forward evidence, a live
record, a granted license, explicit human authorization, and a security/legal review. Operational
qualification passes offline (section 20-23), but the forward/live/license/authorization/review
gates are unmet, so the conjunction is ``False`` and the standing posture is ``not_sell_ready``. The
derivation is genuine: with every gate met it would return ``True``, and a reviewer can read exactly
which gates block it. The committed inputs pin the unmet gates, and the record fails closed if
``sell_ready`` is ever ``True`` or the posture is anything but ``not_sell_ready``.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2.constitution import STANDING_POSTURE, require_v2a_emittable_status
from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    require_bool,
    require_choice,
    require_exact_keys,
    require_int,
    require_list,
    require_mapping,
    require_nonempty_str,
    require_slug,
)

READINESS_SCHEMA_VERSION: int = 1

# Ordered from least to most mature (same vocabulary as the buyer scorecard).
READINESS_LEVELS: tuple[str, ...] = ("absent", "emerging", "established", "strong")
_LEVELS: frozenset[str] = frozenset(READINESS_LEVELS)

#: The gates whose conjunction *is* sell-readiness, in a fixed order. Sell-readiness is derived as
#: ``all(gates)``; every gate must hold, so any unmet gate blocks it.
SELL_READY_GATES: tuple[str, ...] = (
    "operational_qualification_passed",
    "forward_evidence_exists",
    "live_record_exists",
    "license_granted",
    "human_authorization",
    "security_legal_review_passed",
)

_INPUT_KEYS = frozenset(SELL_READY_GATES)
_DIMENSION_KEYS = frozenset({"dimension_id", "level", "rationale"})
_READINESS_KEYS = frozenset(
    {
        "schema_version",
        "gates",
        "dimensions",
        "blocking_gates",
        "sell_ready",
        "posture",
        "honest_limitation",
    }
)


class ReadinessError(V2ValidationError):
    """A readiness input, dimension, or the derived record violated its contract."""


@dataclass(frozen=True, slots=True)
class ReadinessInputs:
    """The boolean gates whose conjunction is sell-readiness."""

    operational_qualification_passed: bool
    forward_evidence_exists: bool
    live_record_exists: bool
    license_granted: bool
    human_authorization: bool
    security_legal_review_passed: bool

    @staticmethod
    def current() -> ReadinessInputs:
        # Operational qualification passes offline (sections 20-23); every other gate is unmet.
        return ReadinessInputs(
            operational_qualification_passed=True,
            forward_evidence_exists=False,
            live_record_exists=False,
            license_granted=False,
            human_authorization=False,
            security_legal_review_passed=False,
        )

    def as_map(self) -> dict[str, bool]:
        return {gate: bool(getattr(self, gate)) for gate in SELL_READY_GATES}

    def to_canonical(self) -> dict[str, object]:
        return dict(self.as_map())

    @staticmethod
    def parse(label: str, value: object) -> ReadinessInputs:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _INPUT_KEYS)
        values = {gate: require_bool(f"{label}.{gate}", obj[gate]) for gate in SELL_READY_GATES}
        return ReadinessInputs(**values)


def derive_sell_ready(inputs: ReadinessInputs) -> bool:
    """Sell-readiness is the conjunction of every gate; any unmet gate makes it ``False``."""
    return all(inputs.as_map().values())


def blocking_gates(inputs: ReadinessInputs) -> tuple[str, ...]:
    """The gates that are unmet (in fixed order) -- the honest reason sell-readiness is blocked."""
    return tuple(gate for gate in SELL_READY_GATES if not inputs.as_map()[gate])


@dataclass(frozen=True, slots=True)
class ReadinessDimension:
    """One rated readiness dimension with its rationale."""

    dimension_id: str
    level: str
    rationale: str

    @staticmethod
    def parse(label: str, value: object) -> ReadinessDimension:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _DIMENSION_KEYS)
        return ReadinessDimension(
            dimension_id=require_slug(f"{label}.dimension_id", obj["dimension_id"]),
            level=require_choice(f"{label}.level", obj["level"], _LEVELS),
            rationale=require_nonempty_str(f"{label}.rationale", obj["rationale"]),
        )

    def to_canonical(self) -> dict[str, object]:
        return {"dimension_id": self.dimension_id, "level": self.level, "rationale": self.rationale}


@dataclass(frozen=True, slots=True)
class QualificationReadiness:
    """The fixed, derived readiness record: gates -> derived sell_ready (false) + posture."""

    gates: ReadinessInputs
    dimensions: tuple[ReadinessDimension, ...]

    @staticmethod
    def current() -> QualificationReadiness:
        return QualificationReadiness(
            gates=ReadinessInputs.current(),
            dimensions=(
                ReadinessDimension(
                    dimension_id="research_evidence",
                    level="established",
                    rationale=(
                        "Candidates were evaluated on the research-train partition under a "
                        "pre-registered, cost-aware, bootstrapped protocol -- on that partition "
                        "only; there is no out-of-sample or forward evidence."
                    ),
                ),
                ReadinessDimension(
                    dimension_id="reproducibility",
                    level="strong",
                    rationale=(
                        "Every artifact is strict canonical JSON with no wall-clock; results and "
                        "journals are hash-chained and reproduce byte for byte."
                    ),
                ),
                ReadinessDimension(
                    dimension_id="governance",
                    level="strong",
                    rationale=(
                        "Sealed partitions are firewalled with byte-empty access ledgers; the "
                        "candidate-free firewall admits only the all-zero cash_control target."
                    ),
                ),
                ReadinessDimension(
                    dimension_id="operational_qualification",
                    level="established",
                    rationale=(
                        "The offline qualification met its SLOs on a synthetic event stream with a "
                        "fault schedule, including crash/recovery and a kill-switch drill; it "
                        "measures operations, never a strategy, and has no live connectivity."
                    ),
                ),
                ReadinessDimension(
                    dimension_id="forward_evidence",
                    level="absent",
                    rationale=(
                        "No out-of-sample, forward, paper, or live performance record exists; V2C "
                        "evaluates no strategy and creates none."
                    ),
                ),
                ReadinessDimension(
                    dimension_id="commercial_readiness",
                    level="absent",
                    rationale=(
                        "No license, no productized offering, no forward or live evidence. The "
                        "programme is not sell-ready."
                    ),
                ),
            ),
        )

    @property
    def sell_ready(self) -> bool:
        return derive_sell_ready(self.gates)

    @property
    def blocking_gates(self) -> tuple[str, ...]:
        return blocking_gates(self.gates)

    @property
    def posture(self) -> str:
        # Derived: only an all-gates-met record could be anything but not_sell_ready, and no such
        # record can be constructed here. The posture is always the standing not_sell_ready.
        return STANDING_POSTURE

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": READINESS_SCHEMA_VERSION,
            "gates": self.gates.to_canonical(),
            "dimensions": [d.to_canonical() for d in self.dimensions],
            "blocking_gates": list(self.blocking_gates),
            "sell_ready": self.sell_ready,
            "posture": self.posture,
            "honest_limitation": (
                "sell_ready is derived as the conjunction of every gate, not asserted. Operational "
                "qualification passes offline, but the forward-evidence, live-record, license, "
                "authorization, and security/legal-review gates are unmet, so sell_ready is false "
                "and the posture is not_sell_ready. Nothing here establishes forward or live "
                "performance."
            ),
        }

    def fingerprint(self) -> str:
        return canonical_sha256(self.to_canonical())

    @staticmethod
    def parse(raw: object) -> QualificationReadiness:
        obj = require_mapping("qualification_readiness", raw)
        require_exact_keys("qualification_readiness", obj, _READINESS_KEYS)
        if (
            require_int("qualification_readiness.schema_version", obj["schema_version"])
            != READINESS_SCHEMA_VERSION
        ):
            raise ReadinessError("readiness schema_version drifted from the fixed definition")
        gates = ReadinessInputs.parse("qualification_readiness.gates", obj["gates"])
        dimensions = tuple(
            require_list(
                "qualification_readiness.dimensions", obj["dimensions"], ReadinessDimension.parse
            )
        )
        if not dimensions:
            raise ReadinessError("readiness record must have at least one dimension")
        sell_ready = require_bool("qualification_readiness.sell_ready", obj["sell_ready"])
        posture = require_v2a_emittable_status("qualification_readiness.posture", obj["posture"])
        # Fail closed: the derivation must match, sell_ready must be false, posture not_sell_ready.
        if sell_ready != derive_sell_ready(gates):
            raise ReadinessError("sell_ready does not match the derivation from the gates")
        if sell_ready:
            raise ReadinessError("sell_ready must be false; the programme is not sell-ready")
        if posture != STANDING_POSTURE:
            raise ReadinessError(f"posture must be {STANDING_POSTURE!r}")
        record = QualificationReadiness(gates=gates, dimensions=dimensions)
        if list(record.blocking_gates) != list(obj["blocking_gates"]):
            raise ReadinessError("blocking_gates does not match the derivation from the gates")
        expected_limitation = record.to_canonical()["honest_limitation"]
        if (
            require_nonempty_str(
                "qualification_readiness.honest_limitation", obj["honest_limitation"]
            )
            != expected_limitation
        ):
            raise ReadinessError("honest_limitation drifted from the fixed definition")
        if record.fingerprint() != QualificationReadiness.current().fingerprint():
            raise ReadinessError("readiness record drifted from the fixed definition")
        return record


__all__ = [
    "READINESS_LEVELS",
    "READINESS_SCHEMA_VERSION",
    "SELL_READY_GATES",
    "QualificationReadiness",
    "ReadinessDimension",
    "ReadinessError",
    "ReadinessInputs",
    "blocking_gates",
    "derive_sell_ready",
]
