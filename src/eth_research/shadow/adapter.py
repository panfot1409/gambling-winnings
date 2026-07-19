"""The execution-adapter interface — defined, but with a paper implementation only.

An execution adapter is the seam where, in a *live* system, an approved intent would be dispatched
to a venue. The shadow platform defines that seam as an abstract interface and ships exactly one
implementation: :class:`PaperExecutionAdapter`, which records the intent in memory and acknowledges
it without contacting anything. There is deliberately **no** live adapter in this package, and the
repository's AST no-network guard makes it impossible to add one that imports a client library
without failing the hygiene gate.

The interface exists so a buyer can see precisely where their own (separately built, separately
governed) live adapter would plug in — and see that this package never does.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from eth_research.shadow.domain import InstrumentId, ShadowDomainError, canonical_timestamp
from eth_research.v2.strict import (
    require_exact_keys,
    require_mapping,
    require_slug,
    require_unit_interval,
)

_INTENT_KEYS = frozenset({"candidate_id", "instrument", "as_of", "approved_weight"})

# The reviewed allowlist of adapter channels the shadow runner will drive. Every shipped adapter is
# non-routing (records intents, contacts nothing); a new one may run only once its channel slug is
# added here, so an adapter that declares a live/venue channel cannot be executed by mistake.
NON_ROUTING_CHANNELS: frozenset[str] = frozenset({"paper"})


class AdapterError(ShadowDomainError):
    """An execution intent or acknowledgement violated its contract."""


@dataclass(frozen=True, slots=True)
class ExecutionIntent:
    """A risk-approved target weight ready to be *observed* — this package sends it nowhere."""

    candidate_id: str
    instrument: InstrumentId
    as_of: str
    approved_weight: float

    @staticmethod
    def create(
        *, candidate_id: str, instrument: InstrumentId, as_of: object, approved_weight: object
    ) -> ExecutionIntent:
        return ExecutionIntent(
            candidate_id=require_slug("candidate_id", candidate_id),
            instrument=instrument,
            as_of=canonical_timestamp("as_of", as_of),
            approved_weight=require_unit_interval("approved_weight", approved_weight),
        )

    @staticmethod
    def parse(label: str, value: object) -> ExecutionIntent:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _INTENT_KEYS)
        return ExecutionIntent(
            candidate_id=require_slug(f"{label}.candidate_id", obj["candidate_id"]),
            instrument=InstrumentId.parse(f"{label}.instrument", obj["instrument"]),
            as_of=canonical_timestamp(f"{label}.as_of", obj["as_of"]),
            approved_weight=require_unit_interval(
                f"{label}.approved_weight", obj["approved_weight"]
            ),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "instrument": self.instrument.to_canonical(),
            "as_of": self.as_of,
            "approved_weight": self.approved_weight,
        }


@dataclass(frozen=True, slots=True)
class IntentAck:
    """A shadow acknowledgement: the intent was recorded (never routed to a venue)."""

    accepted: bool
    channel: str
    note: str

    def to_canonical(self) -> dict[str, object]:
        return {"accepted": self.accepted, "channel": self.channel, "note": self.note}


class ShadowExecutionAdapter(ABC):
    """The abstract dispatch seam. Every implementation is non-routing and declares its channel."""

    @property
    @abstractmethod
    def channel(self) -> str:
        """A stable slug identifying this adapter's (non-live) channel, e.g. ``paper``."""

    @abstractmethod
    def dispatch(self, intent: ExecutionIntent) -> IntentAck:
        """Record/acknowledge the intent. Implementations must never open a network connection."""


@dataclass(slots=True)
class PaperExecutionAdapter(ShadowExecutionAdapter):
    """The only concrete adapter: it appends the intent to an in-memory log and acknowledges it."""

    _log: list[ExecutionIntent] = field(default_factory=list)

    @property
    def channel(self) -> str:
        return "paper"

    @property
    def dispatched(self) -> tuple[ExecutionIntent, ...]:
        return tuple(self._log)

    def dispatch(self, intent: ExecutionIntent) -> IntentAck:
        self._log.append(intent)
        return IntentAck(
            accepted=True,
            channel=self.channel,
            note="recorded to the paper book; no order was placed",
        )
