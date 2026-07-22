"""V2C sections 19-20: the operational-qualification result + report models.

Serializes a :class:`~eth_research.v2c.oq.run.QualificationOutcome` into a canonical, self-digesting
result and a human-readable report. Both are **operational** evidence: per-criterion pass/fail,
event acceptance and fault counts, deterministic resource measurements, crash/recovery outcomes, the
governing zero-exposure counts (risky intents, risky fills, turnover, terminal book units -- all
zero). They record **no** market performance.

That prohibition is enforced structurally: :func:`scan_for_forbidden_vocabulary` recursively screens
every key and string value of the result and every line of the report for financial-performance
vocabulary (return, equity, PnL, CAGR, Sharpe, Sortino, drawdown, alpha, profit, ROI, benchmark). A
forbidden term anywhere -- even smuggled in through an upstream detail string -- fails the build
closed, so a result that computed or narrated market performance can never be published.
"""

from __future__ import annotations

import re
from typing import Any

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    canonical_sha256,
)
from eth_research.v2c.oq.registry import (
    OQ_VERDICT_NOT_QUALIFIED,
    OQ_VERDICT_QUALIFIED,
    QualificationIdentity,
)
from eth_research.v2c.oq.run import QualificationOutcome

OQ_RESULT_SCHEMA_VERSION: int = 1

#: Financial-performance vocabulary that must never appear in an operational-qualification result or
#: report. Matched case-insensitively on word boundaries (``returns?`` covers return/returns). These
#: are the metrics V2C may not compute (milestone scope section 0); the qualification measures event
#: acceptance, durability, recovery, and zero exposure, none of which needs this vocabulary.
FORBIDDEN_PERFORMANCE_TERMS: tuple[str, ...] = (
    "returns?",
    "equity",
    "pnl",
    "cagr",
    "sharpe",
    "sortino",
    "calmar",
    "drawdown",
    "alpha",
    "profit",
    "roi",
    "benchmark",
)

_FORBIDDEN_RE = re.compile(r"\b(?:" + "|".join(FORBIDDEN_PERFORMANCE_TERMS) + r")\b", re.IGNORECASE)

_RESULT_STATEMENT = (
    "This is an offline operational-qualification result. It reports event-acceptance, durability, "
    "resource, and crash/recovery outcomes and the governing zero-exposure counts for the "
    "candidate-free cash_control target. It evaluates no strategy and computes no market "
    "performance: every risky intent, risky fill, and unit of turnover is zero and the paper book "
    "holds 100% cash throughout."
)


class ForbiddenVocabularyError(V2ValidationError):
    """A financial-performance term appeared in an operational-qualification result or report."""


def _collect_strings(obj: Any) -> list[str]:
    """Flatten every string key and value in a nested dict/list into one list."""
    found: list[str] = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str):
                found.append(key)
            found.extend(_collect_strings(value))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found.extend(_collect_strings(item))
    return found


def scan_for_forbidden_vocabulary(label: str, payload: Any) -> None:
    """Refuse any financial-performance vocabulary anywhere in ``payload`` (a str or nested dict).

    Fail-closed: the first forbidden term found raises :class:`ForbiddenVocabularyError` naming it.
    """
    for text in _collect_strings(payload):
        match = _FORBIDDEN_RE.search(text)
        if match is not None:
            raise ForbiddenVocabularyError(
                f"{label} contains forbidden financial-performance vocabulary "
                f"{match.group(0)!r} in {text!r}"
            )


def _instrument_summary(outcome: QualificationOutcome) -> dict[str, Any]:
    resource_by_symbol = {r.instrument_symbol: r for r in outcome.resource_reports}
    recovery_by_symbol = {r.instrument_symbol: r for r in outcome.recovery_reports}
    summary: dict[str, Any] = {}
    for qual in outcome.run.instruments:
        symbol = qual.instrument_symbol
        resource = resource_by_symbol[symbol]
        recovery = recovery_by_symbol[symbol]
        fills = qual.result.fills
        summary[symbol] = {
            "accepted_count": len(qual.acceptance.accepted),
            "fixture_digest": qual.fixture_manifest["fixture_digest"],
            "processing_steps": resource.processing_steps,
            "journal_events": resource.journal_events,
            "journal_bytes": resource.journal_bytes,
            "within_resource_bounds": resource.within_bounds,
            "recovery_passed": recovery.passed,
            "recovery_checks": [
                {"name": check.name, "passed": check.passed} for check in recovery.checks
            ],
            # The governing zero-exposure counts, measured from the actual run.
            "risky_intent_count": sum(
                1 for intent in qual.dispatched_intents if intent.approved_weight != 0.0
            ),
            "risky_fill_count": sum(1 for fill in fills if fill.traded_units != 0.0),
            "turnover": sum(abs(fill.traded_units) for fill in fills),
            "terminal_book_units": abs(qual.result.final_account.units),
            "total_cash_control_instructions": len(qual.dispatched_intents),
        }
    return summary


def _operational_counts(instruments: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_cash_control_instructions": sum(
            i["total_cash_control_instructions"] for i in instruments.values()
        ),
        "requested_risky_exposure": 0.0,  # cash_control requests exactly zero by construction
        "approved_risky_exposure": 0.0,
        "risky_intent_count": sum(i["risky_intent_count"] for i in instruments.values()),
        "risky_fill_count": sum(i["risky_fill_count"] for i in instruments.values()),
        "turnover": sum(i["turnover"] for i in instruments.values()),
        "terminal_book_units": sum(i["terminal_book_units"] for i in instruments.values()),
    }


def build_oq_result(
    outcome: QualificationOutcome, *, identity: QualificationIdentity
) -> dict[str, Any]:
    """Build the canonical operational-qualification result, screened for forbidden vocabulary."""
    verdict = OQ_VERDICT_QUALIFIED if outcome.verdict.passed else OQ_VERDICT_NOT_QUALIFIED
    instruments = _instrument_summary(outcome)
    body: dict[str, Any] = {
        "schema_version": OQ_RESULT_SCHEMA_VERSION,
        "artifact_id": "v2c_oq_result",
        "qualification_id": identity.qualification_id,
        "methodology_id": identity.methodology_id,
        "package_version": identity.package_version,
        "verdict": verdict,
        "slots": outcome.slots,
        "criteria": [
            {"criterion": result.criterion, "passed": result.passed, "detail": result.detail}
            for result in outcome.verdict.results
        ],
        "instruments": instruments,
        "operational_counts": _operational_counts(instruments),
        "statement": _RESULT_STATEMENT,
    }
    body["result_digest"] = canonical_sha256(body)
    # Fail closed if any financial-performance vocabulary reached the result (e.g. via a detail
    # string): an operational qualification must narrate no market performance.
    scan_for_forbidden_vocabulary("oq_result", body)
    return body


def render_oq_result_bytes(result: dict[str, Any]) -> bytes:
    """Serialize the result to canonical JSON bytes (sorted keys, trailing newline)."""
    return canonical_json_bytes(result)


def oq_result_digest(result: dict[str, Any]) -> str:
    digest = result["result_digest"]
    assert isinstance(digest, str)
    return digest


def build_oq_report(result: dict[str, Any]) -> str:
    """Render the result as a human-readable Markdown report, screened for forbidden vocabulary."""
    counts = result["operational_counts"]
    lines: list[str] = [
        "# V2C Offline Operational Qualification -- Result",
        "",
        f"- Qualification: `{result['qualification_id']}`",
        f"- Methodology: `{result['methodology_id']}`",
        f"- Package version: `{result['package_version']}`",
        f"- Verdict: **{result['verdict']}**",
        f"- Result digest: `{result['result_digest']}`",
        "",
        "## Governing zero-exposure counts",
        "",
        f"- Cash-control instructions processed: {counts['total_cash_control_instructions']}",
        f"- Requested risky exposure: {counts['requested_risky_exposure']}",
        f"- Approved risky exposure: {counts['approved_risky_exposure']}",
        f"- Risky intents: {counts['risky_intent_count']}",
        f"- Risky fills: {counts['risky_fill_count']}",
        f"- Turnover: {counts['turnover']}",
        f"- Terminal book units: {counts['terminal_book_units']}",
        "",
        "The paper book held 100% cash throughout; no market performance was computed.",
        "",
        "## Qualification criteria",
        "",
        "| Criterion | Passed | Detail |",
        "| --- | --- | --- |",
    ]
    for criterion in result["criteria"]:
        detail = str(criterion["detail"]).replace("|", "/")
        lines.append(f"| {criterion['criterion']} | {criterion['passed']} | {detail} |")
    lines.extend(["", "## Instruments", ""])
    for symbol, summary in sorted(result["instruments"].items()):
        lines.append(
            f"- `{symbol}`: accepted {summary['accepted_count']}, "
            f"steps {summary['processing_steps']}, recovery passed {summary['recovery_passed']}, "
            f"risky fills {summary['risky_fill_count']}, turnover {summary['turnover']}"
        )
    report = "\n".join(lines) + "\n"
    scan_for_forbidden_vocabulary("oq_report", report)
    return report


__all__ = [
    "FORBIDDEN_PERFORMANCE_TERMS",
    "OQ_RESULT_SCHEMA_VERSION",
    "ForbiddenVocabularyError",
    "build_oq_report",
    "build_oq_result",
    "oq_result_digest",
    "render_oq_result_bytes",
    "scan_for_forbidden_vocabulary",
]
