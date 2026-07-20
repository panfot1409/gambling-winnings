"""V2C section 17: the offline prospective-update proposal generator.

:func:`generate_offline_proposal` computes a :class:`ProspectiveUpdateProposal` (or a "no update
due" outcome) purely from a cohort descriptor and an **explicit** as-of instant. It reads no wall
clock, opens no socket, fetches no candle, and writes nothing -- it only does calendar arithmetic on
the observation grid. The window it proposes is the completed observations
``[first_missing_open, completed_exclusive_end)``, where ``completed_exclusive_end`` is the current
forming interval's open (floored to the grid anchored at ``cohort_start``), so the forming
observation is always excluded.

A clock that has rewound before the cohort started is a hard error; a clock that simply has nothing
new due yields :data:`OUTCOME_NO_UPDATE_DUE`, never a fabricated proposal. The generator re-checks
that the descriptor keeps evaluation unauthorized before doing anything.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from eth_research.v2c.proposal import ProspectiveUpdateProposal, V2CProposalError
from eth_research.v2c.prospective import (
    ProspectiveCohortDescriptor,
    require_evaluation_not_authorized,
)

#: A proposal was generated (at least one completed observation is due).
OUTCOME_PROPOSAL: str = "update_proposal"
#: Nothing new is due; no proposal is generated (the common steady state).
OUTCOME_NO_UPDATE_DUE: str = "no_update_due"


@dataclass(frozen=True, slots=True)
class ProposalGenerationResult:
    """The outcome of one offline generation: either a proposal, or nothing due."""

    status: str
    proposal: ProspectiveUpdateProposal | None


def _parse_utc(label: str, value: object) -> pd.Timestamp:
    if isinstance(value, pd.Timestamp):
        ts = value
    elif isinstance(value, str):
        try:
            ts = pd.Timestamp(value)
        except (ValueError, TypeError) as exc:
            raise V2CProposalError(f"{label} is not a valid ISO-8601 timestamp: {value!r}") from exc
    else:
        raise V2CProposalError(
            f"{label} must be a timestamp or ISO-8601 string, got {type(value).__name__}"
        )
    if ts.tz is None:
        raise V2CProposalError(f"{label} must be timezone-aware UTC")
    offset = ts.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise V2CProposalError(f"{label} must be in UTC (zero offset), got {ts}")
    return ts


def _require_on_grid(
    label: str, ts: pd.Timestamp, anchor: pd.Timestamp, step: pd.Timedelta
) -> None:
    if (ts - anchor) % step != pd.Timedelta(0):
        raise V2CProposalError(f"{label} {ts} is not aligned to the {step} observation grid")


def generate_offline_proposal(
    descriptor: ProspectiveCohortDescriptor, as_of_utc: object
) -> ProposalGenerationResult:
    """Compute the due update proposal for ``descriptor`` at ``as_of_utc`` (offline, no I/O)."""
    require_evaluation_not_authorized(descriptor)

    step = pd.Timedelta(seconds=descriptor.interval_seconds)
    cohort_start = _parse_utc("cohort_start", descriptor.cohort_start)
    as_of = _parse_utc("as_of_utc", as_of_utc)
    if as_of < cohort_start:
        raise V2CProposalError("clock rewind: as_of precedes the cohort start (hard stop)")

    if descriptor.accumulated_last_open is None:
        first_missing_open = cohort_start
    else:
        accepted_last_open = _parse_utc("accumulated_last_open", descriptor.accumulated_last_open)
        if accepted_last_open < cohort_start:
            raise V2CProposalError("accumulated_last_open precedes the cohort start (hard stop)")
        _require_on_grid("accumulated_last_open", accepted_last_open, cohort_start, step)
        first_missing_open = accepted_last_open + step

    # The current forming interval's open: the largest grid point <= as_of. Everything strictly
    # before it is a completed observation; the forming observation is excluded.
    completed_intervals = (as_of - cohort_start) // step
    completed_exclusive_end = cohort_start + completed_intervals * step

    if completed_exclusive_end <= first_missing_open:
        return ProposalGenerationResult(status=OUTCOME_NO_UPDATE_DUE, proposal=None)

    expected_row_count = (completed_exclusive_end - first_missing_open) // step
    proposal = ProspectiveUpdateProposal(
        base_cohort_id=descriptor.cohort_id,
        base_descriptor_digest=descriptor.descriptor_digest(),
        product=descriptor.product,
        venue=descriptor.venue,
        interval_seconds=descriptor.interval_seconds,
        first_missing_open=first_missing_open.isoformat(),
        completed_exclusive_end=completed_exclusive_end.isoformat(),
        expected_row_count=int(expected_row_count),
    )
    return ProposalGenerationResult(status=OUTCOME_PROPOSAL, proposal=proposal)


__all__ = [
    "OUTCOME_NO_UPDATE_DUE",
    "OUTCOME_PROPOSAL",
    "ProposalGenerationResult",
    "generate_offline_proposal",
]
