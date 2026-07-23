"""V2C section 15: the strict prospective-cohort schema + lifecycle state machine.

This formalizes -- but does not activate -- the lifecycle a future prospective ETH/BTC data cohort
would follow. It is **candidate-free and data-only**: a cohort names a market *data product* (e.g.
``ETH-USD``), never a strategy, and no state it can reach authorizes evaluating a candidate.

Two decoupled tracks:

* **Data-availability track** (:data:`COHORT_LIFECYCLE_STATES`): ``declared -> accumulating ->
  data_mature``. This tracks only whether enough completed observations exist. "Mature" means data
  is *available*, nothing more.
* **Proposal track** (:data:`PROPOSAL_LIFECYCLE_STATES`): ``no_proposal -> prepared -> under_review
  -> accepted|rejected``. ``accepted`` means a reviewed *data update* was accepted -- never that a
  strategy may be evaluated.

Across every state, :data:`ProspectiveCohortDescriptor.evaluation_authorization` is permanently
``False`` and re-checked by :func:`require_evaluation_not_authorized`: accepting data, or data
becoming mature, never flips it. Authorizing evaluation is a *separate future human decision* under
its own governance, which V2C does not make. The invariant is enforced structurally in
``__post_init__`` and again at every transition, so a smuggled ``True`` is a hard error.

Reuses the strategy-free ``eth_research.m3d.validation`` strict/canonical surface (the same one M3E
reuses), and the V2C firewall to refuse any candidate reference in a product/venue field.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.m3d.validation import (
    M3DValidationError,
    domain_sha256,
    require_bool,
    require_exact,
    require_mapping,
    require_nonempty_str,
    require_nonnegative_int,
    require_positive_int,
)
from eth_research.v2c.firewall import assert_no_candidate_reference

SCHEMA_VERSION: int = 1
_DESCRIPTOR_DOMAIN: str = "v2c/prospective_cohort_descriptor.v1"

#: Data-availability lifecycle. Tracks only whether enough completed observations exist.
COHORT_LIFECYCLE_STATES: tuple[str, ...] = ("declared", "accumulating", "data_mature")

#: Proposal lifecycle. ``accepted`` means a reviewed *data* update was accepted, never a strategy.
PROPOSAL_LIFECYCLE_STATES: tuple[str, ...] = (
    "no_proposal",
    "prepared",
    "under_review",
    "accepted",
    "rejected",
)

#: Allowed forward cohort-state transitions (monotone; no reopening of a matured cohort here).
_COHORT_TRANSITIONS: dict[str, frozenset[str]] = {
    "declared": frozenset({"declared", "accumulating"}),
    "accumulating": frozenset({"accumulating", "data_mature"}),
    "data_mature": frozenset({"data_mature"}),
}

#: Allowed proposal-state transitions. ``accepted`` / ``rejected`` are terminal.
_PROPOSAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "no_proposal": frozenset({"no_proposal", "prepared"}),
    "prepared": frozenset({"prepared", "under_review"}),
    "under_review": frozenset({"accepted", "rejected"}),
    "accepted": frozenset({"accepted"}),
    "rejected": frozenset({"rejected"}),
}

_DESCRIPTOR_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "cohort_id",
        "product",
        "venue",
        "interval_seconds",
        "cohort_start",
        "accumulated_last_open",
        "row_count",
        "minimum_maturity_rows",
        "cohort_state",
        "proposal_state",
        "evaluation_authorization",
        "descriptor_digest",
    }
)


class V2CProspectiveError(M3DValidationError):
    """A prospective-cohort descriptor was malformed, or a lifecycle invariant was violated."""


def derive_cohort_state(row_count: int, minimum_maturity_rows: int) -> str:
    """The data-availability state implied by the accumulated row count.

    ``0`` rows is ``declared``; below the maturity floor is ``accumulating``; at or above it is
    ``data_mature``. Maturity here is data availability only -- it does not authorize evaluation.
    """
    rows = require_nonnegative_int("row_count", row_count)
    floor = require_positive_int("minimum_maturity_rows", minimum_maturity_rows)
    if rows == 0:
        return "declared"
    if rows < floor:
        return "accumulating"
    return "data_mature"


@dataclass(frozen=True, slots=True)
class ProspectiveCohortDescriptor:
    """A strict, candidate-free descriptor of a prospective market-*data* cohort and its lifecycle.

    ``evaluation_authorization`` is always ``False``; construction refuses any other value.
    """

    cohort_id: str
    product: str
    venue: str
    interval_seconds: int
    cohort_start: str
    accumulated_last_open: str | None
    row_count: int
    minimum_maturity_rows: int
    cohort_state: str
    proposal_state: str
    evaluation_authorization: bool

    def __post_init__(self) -> None:
        require_nonempty_str("cohort_id", self.cohort_id)
        # A cohort names a data product / venue, never a candidate/strategy.
        assert_no_candidate_reference("cohort.product", self.product)
        assert_no_candidate_reference("cohort.venue", self.venue)
        require_nonempty_str("product", self.product)
        require_nonempty_str("venue", self.venue)
        require_positive_int("interval_seconds", self.interval_seconds)
        require_nonempty_str("cohort_start", self.cohort_start)
        if self.accumulated_last_open is not None:
            require_nonempty_str("accumulated_last_open", self.accumulated_last_open)
        require_nonnegative_int("row_count", self.row_count)
        require_positive_int("minimum_maturity_rows", self.minimum_maturity_rows)
        if self.cohort_state not in COHORT_LIFECYCLE_STATES:
            raise V2CProspectiveError(f"unknown cohort_state {self.cohort_state!r}")
        if self.proposal_state not in PROPOSAL_LIFECYCLE_STATES:
            raise V2CProspectiveError(f"unknown proposal_state {self.proposal_state!r}")
        # The data-availability state must equal what the row count implies (no hand-set maturity).
        implied = derive_cohort_state(self.row_count, self.minimum_maturity_rows)
        if self.cohort_state != implied:
            raise V2CProspectiveError(
                f"cohort_state {self.cohort_state!r} disagrees with the row count "
                f"(implied {implied!r} from {self.row_count} rows)"
            )
        # A cohort with zero rows cannot carry an accumulated last-open, and vice versa.
        if (self.row_count == 0) != (self.accumulated_last_open is None):
            raise V2CProspectiveError("accumulated_last_open must be present iff row_count > 0")
        # The permanent invariant: V2C never authorizes evaluation.
        if not isinstance(self.evaluation_authorization, bool):
            raise V2CProspectiveError("evaluation_authorization must be a boolean")
        if self.evaluation_authorization is not False:
            raise V2CProspectiveError(
                "evaluation_authorization must be False; V2C authorizes no strategy evaluation"
            )

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "cohort_id": self.cohort_id,
            "product": self.product,
            "venue": self.venue,
            "interval_seconds": self.interval_seconds,
            "cohort_start": self.cohort_start,
            "accumulated_last_open": self.accumulated_last_open,
            "row_count": self.row_count,
            "minimum_maturity_rows": self.minimum_maturity_rows,
            "cohort_state": self.cohort_state,
            "proposal_state": self.proposal_state,
            "evaluation_authorization": self.evaluation_authorization,
        }

    def descriptor_digest(self) -> str:
        """Domain-separated SHA-256 self-digest binding every descriptor field."""
        return domain_sha256(_DESCRIPTOR_DOMAIN, self._body())

    def to_canonical(self) -> dict[str, object]:
        body = self._body()
        body["descriptor_digest"] = self.descriptor_digest()
        return body

    @staticmethod
    def from_mapping(label: str, value: object) -> ProspectiveCohortDescriptor:
        obj = require_mapping(label, value)
        extra = set(obj) - _DESCRIPTOR_KEYS
        missing = _DESCRIPTOR_KEYS - set(obj)
        if extra or missing:
            raise V2CProspectiveError(
                f"{label} keys mismatch (unexpected={sorted(extra)}, missing={sorted(missing)})"
            )
        require_exact(f"{label}.schema_version", obj["schema_version"], SCHEMA_VERSION)
        last_open_raw = obj["accumulated_last_open"]
        last_open = (
            None
            if last_open_raw is None
            else require_nonempty_str(f"{label}.accumulated_last_open", last_open_raw)
        )
        descriptor = ProspectiveCohortDescriptor(
            cohort_id=require_nonempty_str(f"{label}.cohort_id", obj["cohort_id"]),
            product=require_nonempty_str(f"{label}.product", obj["product"]),
            venue=require_nonempty_str(f"{label}.venue", obj["venue"]),
            interval_seconds=require_positive_int(
                f"{label}.interval_seconds", obj["interval_seconds"]
            ),
            cohort_start=require_nonempty_str(f"{label}.cohort_start", obj["cohort_start"]),
            accumulated_last_open=last_open,
            row_count=require_nonnegative_int(f"{label}.row_count", obj["row_count"]),
            minimum_maturity_rows=require_positive_int(
                f"{label}.minimum_maturity_rows", obj["minimum_maturity_rows"]
            ),
            cohort_state=require_nonempty_str(f"{label}.cohort_state", obj["cohort_state"]),
            proposal_state=require_nonempty_str(f"{label}.proposal_state", obj["proposal_state"]),
            evaluation_authorization=require_bool(
                f"{label}.evaluation_authorization", obj["evaluation_authorization"]
            ),
        )
        committed = require_nonempty_str(f"{label}.descriptor_digest", obj["descriptor_digest"])
        if descriptor.descriptor_digest() != committed:
            raise V2CProspectiveError(
                f"{label}.descriptor_digest does not bind the descriptor body"
            )
        return descriptor


def require_evaluation_not_authorized(descriptor: ProspectiveCohortDescriptor) -> None:
    """Fail closed unless the descriptor keeps evaluation unauthorized (defense in depth)."""
    if descriptor.evaluation_authorization is not False:
        raise V2CProspectiveError(
            "cohort claims evaluation_authorization True; V2C authorizes no evaluation"
        )


def advance_cohort_state(current: str, target: str) -> str:
    """Return ``target`` if the cohort-state transition is allowed, else raise (fail closed)."""
    if current not in _COHORT_TRANSITIONS:
        raise V2CProspectiveError(f"unknown cohort_state {current!r}")
    if target not in _COHORT_TRANSITIONS[current]:
        raise V2CProspectiveError(f"cohort transition {current!r} -> {target!r} is not allowed")
    return target


def advance_proposal_state(current: str, target: str) -> str:
    """Return ``target`` if the proposal-state transition is allowed, else raise (fail closed).

    Note: no transition here authorizes evaluation; ``accepted`` accepts a *data* update only.
    """
    if current not in _PROPOSAL_TRANSITIONS:
        raise V2CProspectiveError(f"unknown proposal_state {current!r}")
    if target not in _PROPOSAL_TRANSITIONS[current]:
        raise V2CProspectiveError(f"proposal transition {current!r} -> {target!r} is not allowed")
    return target


__all__ = [
    "COHORT_LIFECYCLE_STATES",
    "PROPOSAL_LIFECYCLE_STATES",
    "SCHEMA_VERSION",
    "ProspectiveCohortDescriptor",
    "V2CProspectiveError",
    "advance_cohort_state",
    "advance_proposal_state",
    "derive_cohort_state",
    "require_evaluation_not_authorized",
]
