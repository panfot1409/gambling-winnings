"""V2C section 19: the prospective-data maturity policy.

Maturity in V2C means one thing only: **enough completed observations exist** for a future,
separately-authorized evaluation milestone to be *possible*. It is a data-availability signal, not a
go-ahead. Three invariants are pinned here and re-checked in code:

1. Maturity never authorizes evaluation. ``evaluation_authorized`` is ``False`` in every assessment,
   even when the cohort is data-mature.
2. Maturity never depends on a strategy outcome -- it is a pure function of the row count against a
   fixed floor, with no reference to returns, metrics, or a candidate.
3. Turning a mature cohort into an actual evaluation requires a **separate future human
   authorization** under its own governance, which V2C does not grant.

:func:`assess_prospective_maturity` derives the availability signal; :func:`verify_maturity_policy`
guards the pinned policy constant against tampering.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.m3d.validation import M3DValidationError
from eth_research.v2c.prospective import (
    ProspectiveCohortDescriptor,
    require_evaluation_not_authorized,
)

#: The pinned, non-negotiable maturity policy. Every flag is a governance commitment; a build that
#: flips one is a hard error (see :func:`verify_maturity_policy`).
MATURITY_POLICY: dict[str, object] = {
    "policy_id": "v2c_prospective_maturity_policy_v1",
    "maturity_means_data_availability_only": True,
    "maturity_authorizes_evaluation": False,
    "evaluation_requires_separate_future_human_authorization": True,
    "maturity_depends_on_strategy_outcome": False,
    "maturity_rule": "row_count >= minimum_maturity_rows",
}


class V2CMaturityError(M3DValidationError):
    """The maturity policy was tampered with, or an assessment tried to authorize evaluation."""


@dataclass(frozen=True, slots=True)
class MaturityAssessment:
    """The data-availability verdict for a cohort. ``evaluation_authorized`` is always ``False``."""

    cohort_id: str
    row_count: int
    minimum_maturity_rows: int
    remaining_rows: int
    is_data_mature: bool
    evaluation_authorized: bool

    def __post_init__(self) -> None:
        if self.evaluation_authorized is not False:
            raise V2CMaturityError(
                "a maturity assessment must never authorize evaluation "
                "(evaluation_authorized must be False)"
            )


def assess_prospective_maturity(descriptor: ProspectiveCohortDescriptor) -> MaturityAssessment:
    """Derive the data-availability verdict for ``descriptor`` (never authorizes evaluation).

    ``is_data_mature`` is ``row_count >= minimum_maturity_rows`` -- a pure count comparison with no
    reference to any strategy outcome. Whether or not the cohort is mature,
    ``evaluation_authorized`` is ``False``: authorizing evaluation is a separate future human
    decision V2C does not make.
    """
    require_evaluation_not_authorized(descriptor)
    is_mature = descriptor.row_count >= descriptor.minimum_maturity_rows
    remaining = max(0, descriptor.minimum_maturity_rows - descriptor.row_count)
    return MaturityAssessment(
        cohort_id=descriptor.cohort_id,
        row_count=descriptor.row_count,
        minimum_maturity_rows=descriptor.minimum_maturity_rows,
        remaining_rows=remaining,
        is_data_mature=is_mature,
        evaluation_authorized=False,
    )


def verify_maturity_policy() -> list[str]:
    """Return the list of policy violations (empty == OK). Guards the pinned commitments."""
    problems: list[str] = []
    expected: dict[str, object] = {
        "maturity_means_data_availability_only": True,
        "maturity_authorizes_evaluation": False,
        "evaluation_requires_separate_future_human_authorization": True,
        "maturity_depends_on_strategy_outcome": False,
    }
    for key, want in expected.items():
        got = MATURITY_POLICY.get(key)
        if got is not want:
            problems.append(f"maturity policy {key!r} must be {want!r}, got {got!r}")
    return problems


__all__ = [
    "MATURITY_POLICY",
    "MaturityAssessment",
    "V2CMaturityError",
    "assess_prospective_maturity",
    "verify_maturity_policy",
]
