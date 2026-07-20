"""The signal envelope: a candidate's intended exposure, stamped with its as-of provenance.

A shadow signal is the platform's unit of *intent*, not action. It carries the candidate that
produced it, the instrument, the as-of instant it is valid from, and a long-only target weight in
``[0, 1]`` (the same exposure convention the research candidates emit). It is deliberately not an
order: it names an intended fraction of capital, and the risk engine downstream may reduce it, but
nothing here can be sent anywhere.

Signals are strict and hashable so a shadow run's intent stream is byte-reproducible and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.shadow.domain import InstrumentId, ShadowDomainError, canonical_timestamp
from eth_research.v2.strict import (
    require_exact_keys,
    require_mapping,
    require_slug,
    require_unit_interval,
)

_SIGNAL_KEYS = frozenset({"candidate_id", "instrument", "as_of", "target_weight"})


class SignalError(ShadowDomainError):
    """A signal envelope failed its strict contract (bad weight, missing provenance, etc.)."""


@dataclass(frozen=True, slots=True)
class SignalEnvelope:
    """A candidate's long-only target weight for an instrument, valid as-of a given instant."""

    candidate_id: str
    instrument: InstrumentId
    as_of: str
    target_weight: float

    @staticmethod
    def create(
        *, candidate_id: str, instrument: InstrumentId, as_of: object, target_weight: object
    ) -> SignalEnvelope:
        return SignalEnvelope(
            candidate_id=require_slug("candidate_id", candidate_id),
            instrument=instrument,
            as_of=canonical_timestamp("as_of", as_of),
            target_weight=require_unit_interval("target_weight", target_weight),
        )

    @staticmethod
    def parse(label: str, value: object) -> SignalEnvelope:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _SIGNAL_KEYS)
        return SignalEnvelope(
            candidate_id=require_slug(f"{label}.candidate_id", obj["candidate_id"]),
            instrument=InstrumentId.parse(f"{label}.instrument", obj["instrument"]),
            as_of=canonical_timestamp(f"{label}.as_of", obj["as_of"]),
            target_weight=require_unit_interval(f"{label}.target_weight", obj["target_weight"]),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "instrument": self.instrument.to_canonical(),
            "as_of": self.as_of,
            "target_weight": self.target_weight,
        }
