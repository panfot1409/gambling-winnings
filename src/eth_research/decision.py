"""Recorded scientific decision on validation-stage test promotion.

Milestone completion pressure is itself a risk to the one-time holdout: it
is tempting to "just run the test" to close the milestone. This module
records the honest alternative as a strict, immutable artifact — the fixed
SMA(20/50) specification is **rejected for test promotion** because it
materially underperformed buy-and-hold in the validation period, so the
test is deliberately *not* consumed.

The decision is made entirely from train/validation observations; its
``test_accessed`` flag is structurally ``False``. It preserves the frozen
protocol (an honest pre-registration record, not something to be rewritten
after the fact), makes no parameter change, and claims nothing about moving
averages in general — only about this one fixed specification on this one
validation period. Buy-and-hold is used as a benchmark, not asserted as an
alpha strategy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.provenance import (
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
)
from eth_research.data.validation import (
    require_commit_sha,
    require_fingerprint,
    require_finite_float,
)
from eth_research.protocol import BenchmarkResults

DECISION_SCHEMA_VERSION: int = 1

REJECTED_FOR_TEST_PROMOTION: str = "rejected_for_test_promotion"
ELIGIBLE_FOR_TEST_PROMOTION: str = "eligible_for_test_promotion"
_ALLOWED_DECISIONS: tuple[str, ...] = (REJECTED_FOR_TEST_PROMOTION, ELIGIBLE_FOR_TEST_PROMOTION)

CANDIDATE_STRATEGY: str = "sma_20_50"
BENCHMARK_STRATEGY: str = "buy_and_hold"

PROMOTION_CRITERION: str = (
    "Promote the fixed SMA(20/50) specification to the one-time test only if it does "
    "not materially underperform buy-and-hold in the validation period. This criterion "
    "is fixed before any test access and no parameter is tuned."
)

_REJECTION_RATIONALE: str = (
    "This fixed SMA specification materially underperformed buy-and-hold in the "
    "validation period, so it is not promoted to the one-time test. This is a "
    "statement about one fixed specification on one validation period only — not a "
    "claim that moving-average strategies fail in general, and not a claim that "
    "buy-and-hold is itself an alpha strategy (it is the benchmark)."
)

_ELIGIBLE_RATIONALE: str = (
    "This fixed SMA specification did not underperform buy-and-hold in the "
    "validation period, so under the pre-declared criterion it is eligible for the "
    "one-time test, pending independent authorization. Eligibility is not a "
    "profitability claim; buy-and-hold remains the benchmark, not an alpha strategy."
)

_DECISION_KEYS: frozenset[str] = frozenset(
    {
        "decision_schema_version",
        "subject",
        "decision",
        "criterion",
        "rationale",
        "validation_benchmark_return",
        "validation_candidate_return",
        "validation_gap_pp",
        "parameter_changes",
        "test_accessed",
        "protocol_sha256",
        "dataset_content_fingerprint",
        "pre_registered_commit_sha",
    }
)


class ResearchDecisionError(RuntimeError):
    """A research decision is invalid or disagrees with the results it cites."""


@dataclass(frozen=True)
class ResearchDecision:
    """A strict, immutable validation-stage test-promotion decision.

    Every field is validated in ``__post_init__`` — the single shared
    validation path for constructed and parsed decisions alike.
    """

    decision_schema_version: int
    subject: str
    decision: str
    criterion: str
    rationale: str
    validation_benchmark_return: float
    validation_candidate_return: float
    validation_gap_pp: float
    parameter_changes: str
    test_accessed: bool
    protocol_sha256: str
    dataset_content_fingerprint: str
    pre_registered_commit_sha: str

    def __post_init__(self) -> None:
        version = require_int("decision_schema_version", self.decision_schema_version)
        if version != DECISION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported decision schema version {version!r}; "
                f"this package reads version {DECISION_SCHEMA_VERSION}"
            )
        if require_str("subject", self.subject) != CANDIDATE_STRATEGY:
            raise ValueError(f"subject is pinned to {CANDIDATE_STRATEGY!r}, got {self.subject!r}")
        if require_str("decision", self.decision) not in _ALLOWED_DECISIONS:
            raise ValueError(f"decision must be one of {_ALLOWED_DECISIONS}, got {self.decision!r}")
        require_nonempty_str("criterion", self.criterion)
        require_nonempty_str("rationale", self.rationale)
        benchmark = require_finite_float(
            "validation_benchmark_return", self.validation_benchmark_return
        )
        candidate = require_finite_float(
            "validation_candidate_return", self.validation_candidate_return
        )
        gap = require_finite_float("validation_gap_pp", self.validation_gap_pp)
        expected_gap = (candidate - benchmark) * 100.0
        if gap != expected_gap:
            raise ValueError(
                f"validation_gap_pp {gap!r} does not equal "
                f"(candidate - benchmark) * 100 ({expected_gap!r})"
            )
        if require_str("parameter_changes", self.parameter_changes) != "none":
            raise ValueError(
                f"parameter_changes is pinned to 'none' (no tuning), got {self.parameter_changes!r}"
            )
        if not isinstance(self.test_accessed, bool):
            raise ValueError("test_accessed must be a boolean")
        if self.test_accessed:
            raise ValueError(
                "test_accessed must be false: this is a validation-stage decision made "
                "before any test access"
            )
        if self.decision == REJECTED_FOR_TEST_PROMOTION and candidate >= benchmark:
            raise ValueError(
                "a rejected_for_test_promotion decision requires the candidate to "
                "underperform the benchmark in validation"
            )
        if self.decision == ELIGIBLE_FOR_TEST_PROMOTION and candidate < benchmark:
            raise ValueError(
                "an eligible_for_test_promotion decision requires the candidate not to "
                "underperform the benchmark in validation"
            )
        require_hex64("protocol_sha256", self.protocol_sha256)
        require_fingerprint("dataset_content_fingerprint", self.dataset_content_fingerprint)
        require_commit_sha("pre_registered_commit_sha", self.pre_registered_commit_sha)

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "decision_schema_version": self.decision_schema_version,
            "subject": self.subject,
            "decision": self.decision,
            "criterion": self.criterion,
            "rationale": self.rationale,
            "validation_benchmark_return": self.validation_benchmark_return,
            "validation_candidate_return": self.validation_candidate_return,
            "validation_gap_pp": self.validation_gap_pp,
            "parameter_changes": self.parameter_changes,
            "test_accessed": self.test_accessed,
            "protocol_sha256": self.protocol_sha256,
            "dataset_content_fingerprint": self.dataset_content_fingerprint,
            "pre_registered_commit_sha": self.pre_registered_commit_sha,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> ResearchDecision:
        """Strict parse feeding the shared constructor validation."""
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"research decision is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("research decision JSON must be an object")
        keys = set(payload)
        if keys != _DECISION_KEYS:
            unknown = sorted(keys - _DECISION_KEYS)
            missing = sorted(_DECISION_KEYS - keys)
            raise ValueError(
                f"research decision keys do not match schema: unknown={unknown}, missing={missing}"
            )
        return cls(
            decision_schema_version=payload["decision_schema_version"],
            subject=payload["subject"],
            decision=payload["decision"],
            criterion=payload["criterion"],
            rationale=payload["rationale"],
            validation_benchmark_return=payload["validation_benchmark_return"],
            validation_candidate_return=payload["validation_candidate_return"],
            validation_gap_pp=payload["validation_gap_pp"],
            parameter_changes=payload["parameter_changes"],
            test_accessed=payload["test_accessed"],
            protocol_sha256=payload["protocol_sha256"],
            dataset_content_fingerprint=payload["dataset_content_fingerprint"],
            pre_registered_commit_sha=payload["pre_registered_commit_sha"],
        )


def _validation_return(results: BenchmarkResults, strategy: str) -> float:
    for entry in results.segments:
        if entry.strategy == strategy and entry.segment == "validation":
            return entry.total_return
    raise ResearchDecisionError(f"no validation segment for strategy {strategy!r} in the results")


def build_research_decision_from_results(results: BenchmarkResults) -> ResearchDecision:
    """Deterministically derive the promotion decision from the results.

    Reads the exact validation total returns for the candidate and the
    benchmark straight from the validated results model, so every number is
    preserved bit-for-bit; applies the pre-declared criterion (rejected if
    and only if the candidate underperformed the benchmark in validation);
    computes the percentage-point gap; and binds the protocol, dataset
    fingerprint, and pre-registered commit the results already carry.
    There is no discretionary input: the same results always rebuild the
    same decision bytes, so an edited verdict can never match a rebuild.
    """
    if results.test_evaluation_id is not None:
        raise ResearchDecisionError(
            "the validation-stage decision must be built from train/validation-only results"
        )
    benchmark = _validation_return(results, BENCHMARK_STRATEGY)
    candidate = _validation_return(results, CANDIDATE_STRATEGY)
    rejected = candidate < benchmark
    return ResearchDecision(
        decision_schema_version=DECISION_SCHEMA_VERSION,
        subject=CANDIDATE_STRATEGY,
        decision=REJECTED_FOR_TEST_PROMOTION if rejected else ELIGIBLE_FOR_TEST_PROMOTION,
        criterion=PROMOTION_CRITERION,
        rationale=_REJECTION_RATIONALE if rejected else _ELIGIBLE_RATIONALE,
        validation_benchmark_return=benchmark,
        validation_candidate_return=candidate,
        validation_gap_pp=(candidate - benchmark) * 100.0,
        parameter_changes="none",
        test_accessed=False,
        protocol_sha256=results.protocol_sha256,
        dataset_content_fingerprint=results.dataset_content_fingerprint,
        pre_registered_commit_sha=results.pre_registered_commit_sha,
    )


def render_research_decision(decision: ResearchDecision) -> str:
    """Render the decision as Markdown, purely from the validated model."""
    benchmark_pct = f"{decision.validation_benchmark_return * 100:+.2f}%"
    candidate_pct = f"{decision.validation_candidate_return * 100:+.2f}%"
    gap = f"{decision.validation_gap_pp:+.2f} pp"
    title = (
        "# Validation-stage decision: fixed SMA(20/50) eligible for the one-time test"
        if decision.decision == ELIGIBLE_FOR_TEST_PROMOTION
        else "# Validation-stage decision: fixed SMA(20/50) not promoted to test"
    )
    lines = [
        title,
        "",
        f"- Subject: `{decision.subject}` (fixed 20/50 windows — nothing tuned)",
        f"- Decision: **{decision.decision}**",
        f"- Test accessed to reach this decision: {str(decision.test_accessed).lower()}",
        f"- Parameter changes made: {decision.parameter_changes}",
        "",
        "## Criterion (fixed before any test access)",
        "",
        decision.criterion,
        "",
        "## Validation evidence",
        "",
        f"- Buy-and-hold (benchmark) validation return: {benchmark_pct}",
        f"- SMA(20/50) (candidate) validation return: {candidate_pct}",
        f"- Gap (candidate minus benchmark): {gap}",
        "",
        "## Rationale",
        "",
        decision.rationale,
        "",
        "## Provenance",
        "",
        f"- Protocol SHA-256: `{decision.protocol_sha256}`",
        f"- Dataset content fingerprint: `{decision.dataset_content_fingerprint}`",
        f"- Pre-registered code commit: `{decision.pre_registered_commit_sha}`",
        "",
        "The pre-registered protocol is preserved unchanged as an honest record. "
        "The one-time test holdout remains untouched and sealed.",
        "",
    ]
    return "\n".join(lines)


def load_research_decision(path: str | Path) -> ResearchDecision:
    """Strictly parse a research-decision file."""
    file = Path(path)
    try:
        return ResearchDecision.from_json_bytes(file.read_bytes())
    except ValueError as exc:
        raise ResearchDecisionError(f"invalid research decision {file.name!r}: {exc}") from exc
