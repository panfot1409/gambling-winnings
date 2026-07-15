"""Two-runner canonical-equality attestation.

The core M3E control: a proposal may proceed only if **two isolated runners**,
each having independently fetched and offline-validated the *same* update window,
produce **byte-identical canonical content**. This module compares two
:class:`~eth_research.m3e.runner_boundary.VerifiedRunner` objects and requires:

* both replayed the *same* update plan (identical ``plan_sha256`` and
  ``idempotency_key``);
* their new-window canonical content is identical — both the domain-separated
  fingerprint *and* the exact canonical rows match;
* they are genuinely **isolated** — a distinct ``runner_identity`` each, so the
  same runner's artifact cannot be replayed as its own witness.

Any disagreement is a **HARD STOP**: no proposal is assembled. This is an offline
integrity/reproducibility control, not a cryptographic attestation of authenticity
against an outside oracle (the future-only candles have none); the two isolated
runners are the strongest offline authenticity signal, and their recorded
identities are the external-audit hook.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_research.m3e.runner_boundary import VerifiedRunner
from eth_research.m3e.validation import (
    M3EValidationError,
    domain_sha256,
)

COMPARISON_DOMAIN = "m3e_acquisition_comparison"


@dataclass(frozen=True)
class AcquisitionComparison:
    """The verified two-runner agreement over a new update window."""

    runner_a_label: str
    runner_b_label: str
    plan_sha256: str
    idempotency_key: str
    new_window_fingerprint: str
    row_count: int
    first_open: str
    last_open: str
    canonical_content_match: bool
    runners_isolated: bool
    runner_a_identity: tuple[str, str, str]
    runner_b_identity: tuple[str, str, str]
    comparison_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner_a_label": self.runner_a_label,
            "runner_b_label": self.runner_b_label,
            "plan_sha256": self.plan_sha256,
            "idempotency_key": self.idempotency_key,
            "new_window_fingerprint": self.new_window_fingerprint,
            "row_count": self.row_count,
            "first_open": self.first_open,
            "last_open": self.last_open,
            "canonical_content_match": self.canonical_content_match,
            "runners_isolated": self.runners_isolated,
            "runner_a_identity": list(self.runner_a_identity),
            "runner_b_identity": list(self.runner_b_identity),
            "comparison_sha256": self.comparison_sha256,
        }


def compare_runners(
    runner_a: VerifiedRunner,
    runner_b: VerifiedRunner,
    *,
    require_distinct_runner_identity: bool = True,
) -> AcquisitionComparison:
    """Require canonical content equality between two isolated runners; HARD STOP otherwise."""
    if runner_a.plan_sha256 != runner_b.plan_sha256:
        raise M3EValidationError("runners replayed different update plans (HARD STOP)")
    if runner_a.idempotency_key != runner_b.idempotency_key:
        raise M3EValidationError("runners carry different idempotency keys (HARD STOP)")

    fingerprint_match = runner_a.new_window_fingerprint == runner_b.new_window_fingerprint
    rows_match = runner_a.canonical_rows == runner_b.canonical_rows
    content_match = fingerprint_match and rows_match
    if not content_match:
        raise M3EValidationError(
            "two runners produced different canonical content for the new window; "
            "refusing to propose (HARD STOP)"
        )

    isolated = runner_a.runner_identity != runner_b.runner_identity
    if require_distinct_runner_identity and not isolated:
        raise M3EValidationError(
            "the two runners share a runner identity; they are not isolated (HARD STOP)"
        )

    comparison_sha256 = domain_sha256(
        COMPARISON_DOMAIN,
        {
            "plan_sha256": runner_a.plan_sha256,
            "idempotency_key": runner_a.idempotency_key,
            "new_window_fingerprint": runner_a.new_window_fingerprint,
            "row_count": runner_a.row_count,
            "first_open": runner_a.first_open,
            "last_open": runner_a.last_open,
            "runner_a_identity": list(runner_a.identity_tuple()),
            "runner_b_identity": list(runner_b.identity_tuple()),
        },
    )
    return AcquisitionComparison(
        runner_a_label=runner_a.runner_label,
        runner_b_label=runner_b.runner_label,
        plan_sha256=runner_a.plan_sha256,
        idempotency_key=runner_a.idempotency_key,
        new_window_fingerprint=runner_a.new_window_fingerprint,
        row_count=runner_a.row_count,
        first_open=runner_a.first_open,
        last_open=runner_a.last_open,
        canonical_content_match=True,
        runners_isolated=isolated,
        runner_a_identity=runner_a.identity_tuple(),
        runner_b_identity=runner_b.identity_tuple(),
        comparison_sha256=comparison_sha256,
    )
