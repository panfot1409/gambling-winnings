"""V2C section 22: the independent OQ-Q acceptance oracle.

Independently re-derives the qualification verdict from the archived evidence and refuses any result
whose claimed verdict disagrees with that evidence -- a forged result can never be accepted. It is
deliberately **independent**: it shares no helper with the runner's SLO evaluation
(:mod:`eth_research.v2c.oq.slo`) or the result builder (:mod:`eth_research.v2c.oq.result`). It
carries its own copy of the expected criteria, the accepted-event floor, and the forbidden-vocab
and re-derives the acceptance rule (verdict is ``qualified`` iff every criterion held) and the
zero-exposure invariant from first principles over the archived JSON. A drift test cross-checks the
oracle's independent copies against the authoritative source, so independence never silently rots.

The oracle accepts a result only when its claimed verdict equals the independently-derived verdict
and every integrity, zero-exposure, floor, and vocabulary check passes -- so it accepts an honest
``qualified`` or ``not_qualified`` result and refuses any result that overclaims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    sha256_bytes,
    strict_json_loads,
)
from eth_research.v2c.oq.registry import (
    OQ_EVENT_COMPLETED,
    OQ_VERDICT_NOT_QUALIFIED,
    OQ_VERDICT_QUALIFIED,
    read_oq_registry,
)

#: The oracle's OWN copy of the twelve qualification criteria (cross-checked by a drift test).
OQ_ORACLE_CRITERIA: tuple[str, ...] = (
    "qualification_coverage",
    "event_acceptance_correctness",
    "duplicate_suppression",
    "conflicting_duplicate_detection",
    "journal_durability",
    "checkpoint_consistency",
    "recovery_idempotency",
    "kill_switch_trip_latency",
    "alert_completeness",
    "state_reconstruction",
    "bounded_processing_memory",
    "zero_risky_exposure",
)

#: The oracle's OWN copy of the accepted-event floor (cross-checked by a drift test).
OQ_ORACLE_MIN_ACCEPTED_EVENTS: int = 3500

#: The oracle's OWN forbidden financial-performance vocabulary (independent of result.py).
_ORACLE_FORBIDDEN = (
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
_ORACLE_FORBIDDEN_RE = re.compile(r"\b(?:" + "|".join(_ORACLE_FORBIDDEN) + r")\b", re.IGNORECASE)

_ZERO_EXPOSURE_FIELDS: tuple[str, ...] = (
    "risky_intent_count",
    "risky_fill_count",
    "turnover",
    "terminal_book_units",
)


class OQOracleError(V2ValidationError):
    """The independent OQ-Q oracle refused a result, or could not read the archive/registry."""


@dataclass(frozen=True, slots=True)
class OQOracleVerdict:
    """The oracle's independent acceptance decision."""

    accepted: bool
    derived_verdict: str
    findings: tuple[str, ...]


def _oracle_strings(obj: Any) -> list[str]:
    found: list[str] = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str):
                found.append(key)
            found.extend(_oracle_strings(value))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found.extend(_oracle_strings(item))
    return found


def _is_zero(value: object) -> bool:
    """True only for a real numeric zero (int 0 or float 0.0); a bool never counts."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0


def oq_oracle_verdict(result: object) -> OQOracleVerdict:
    """Independently re-derive the verdict from an archived result and decide acceptance.

    Pure over the parsed result JSON. Accumulates findings; accepts only when there are none and the
    claimed verdict equals the independently-derived verdict.
    """
    findings: list[str] = []
    if not isinstance(result, dict):
        return OQOracleVerdict(False, OQ_VERDICT_NOT_QUALIFIED, ("result is not a JSON object",))

    # Integrity: the self-digest must re-derive from the body.
    recorded_digest = result.get("result_digest")
    body = {key: value for key, value in result.items() if key != "result_digest"}
    if canonical_sha256(body) != recorded_digest:
        findings.append("result_digest does not re-derive from the result body")

    # Forbidden financial-performance vocabulary (the oracle's own screen).
    for text in _oracle_strings(result):
        match = _ORACLE_FORBIDDEN_RE.search(text)
        if match is not None:
            findings.append(f"forbidden financial-performance vocabulary {match.group(0)!r}")
            break

    # The criteria set and per-criterion pass flags.
    criteria = result.get("criteria")
    pass_by_name: dict[str, bool] = {}
    names: tuple[str, ...] = ()
    if isinstance(criteria, list) and all(isinstance(c, dict) for c in criteria):
        names = tuple(str(c.get("criterion")) for c in criteria)
        pass_by_name = {str(c.get("criterion")): bool(c.get("passed")) for c in criteria}
    if names != OQ_ORACLE_CRITERIA:
        findings.append(f"criteria set does not match the expected twelve: {names}")

    # The zero-exposure invariant, re-derived from the operational counts.
    counts = result.get("operational_counts")
    zero_exposure_holds = isinstance(counts, dict) and all(
        _is_zero(counts.get(field)) for field in _ZERO_EXPOSURE_FIELDS
    )
    if not zero_exposure_holds:
        findings.append("operational_counts do not show exactly zero risky exposure")
    # The zero_risky_exposure criterion's own flag must agree with the derived invariant.
    if "zero_risky_exposure" in pass_by_name and pass_by_name["zero_risky_exposure"] != (
        zero_exposure_holds
    ):
        findings.append("zero_risky_exposure criterion flag disagrees with the operational counts")

    # Every instrument must clear the accepted-event floor.
    instruments = result.get("instruments")
    floors_ok = isinstance(instruments, dict) and len(instruments) >= 1
    if isinstance(instruments, dict):
        for symbol, summary in instruments.items():
            accepted_count = summary.get("accepted_count") if isinstance(summary, dict) else None
            if (
                not isinstance(accepted_count, int)
                or accepted_count < OQ_ORACLE_MIN_ACCEPTED_EVENTS
            ):
                floors_ok = False
                findings.append(f"instrument {symbol} does not clear the accepted-event floor")
    else:
        findings.append("result has no instruments map")

    # Re-derive the verdict: qualified iff the criteria set matches, every flag is true, exposure is
    # zero, and the floors hold.
    all_pass = (
        names == OQ_ORACLE_CRITERIA
        and all(pass_by_name.get(name, False) for name in OQ_ORACLE_CRITERIA)
        and zero_exposure_holds
        and floors_ok
    )
    derived_verdict = OQ_VERDICT_QUALIFIED if all_pass else OQ_VERDICT_NOT_QUALIFIED

    claimed = result.get("verdict")
    if claimed != derived_verdict:
        findings.append(
            f"claimed verdict {claimed!r} disagrees with the derived {derived_verdict!r}"
        )

    return OQOracleVerdict(not findings, derived_verdict, tuple(findings))


def independently_accept_archive(
    repo_root: str | Path, registry_path: str | Path
) -> OQOracleVerdict:
    """Read the archived result, run the oracle, and cross-check the registry's completed verdict.

    Raises :class:`OQOracleError` if the archive/registry cannot be read or the completed event's
    verdict disagrees with the archived result. Returns the oracle verdict otherwise.
    """
    from eth_research.v2c.oq.archive import OQ_ARCHIVE_RESULT_RELNAME, archive_relpath

    root = Path(repo_root)
    result_path = root / archive_relpath(OQ_ARCHIVE_RESULT_RELNAME)
    if result_path.is_symlink() or not result_path.is_file():
        raise OQOracleError("archived oq_result.json is missing or not a real file")
    result = strict_json_loads(result_path.read_bytes())

    events = read_oq_registry(registry_path)
    completed = next((event for event in events if event.event == OQ_EVENT_COMPLETED), None)
    if completed is None:
        raise OQOracleError("the registry has no completed event to cross-check")
    if isinstance(result, dict) and result.get("verdict") != completed.verdict:
        raise OQOracleError("archived result verdict disagrees with the registry completed event")
    # The completed event's evidence hash must be this result's self-digest.
    if isinstance(result, dict) and completed.evidence_sha256 != result.get("result_digest"):
        raise OQOracleError("registry evidence_sha256 is not the archived result digest")
    if isinstance(result, dict) and completed.result_sha256 != sha256_bytes(
        result_path.read_bytes()
    ):
        raise OQOracleError("registry result_sha256 does not match the archived result bytes")
    return oq_oracle_verdict(result)


def assert_independent_acceptance(
    repo_root: str | Path, registry_path: str | Path
) -> OQOracleVerdict:
    """Run the oracle over the archive and raise unless it independently accepts the result."""
    verdict = independently_accept_archive(repo_root, registry_path)
    if not verdict.accepted:
        raise OQOracleError(
            "the independent OQ-Q oracle refused the result: " + "; ".join(verdict.findings)
        )
    return verdict


__all__ = [
    "OQ_ORACLE_CRITERIA",
    "OQ_ORACLE_MIN_ACCEPTED_EVENTS",
    "OQOracleError",
    "OQOracleVerdict",
    "assert_independent_acceptance",
    "independently_accept_archive",
    "oq_oracle_verdict",
]
