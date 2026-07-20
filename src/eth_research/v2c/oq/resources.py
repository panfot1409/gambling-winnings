"""V2C section 22: deterministic processing/memory bounds for the qualification.

Wall-clock timing is not reproducible, so the qualification bounds **deterministic** proxies:
the number of processing steps (accepted bars), the number of journal events, and the journal's
serialized byte size (a stand-in for peak memory). All three are exact functions of the fixture, so
they are byte-identical across runs and platforms; a run that exceeds any bound fails the resource
SLO. These are internal offline objectives, not live-production SLAs.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.v2c.oq.harness import InstrumentQualification

#: A generous per-instrument step ceiling (the fixture is ~3.8k bars).
MAX_PROCESSING_STEPS: int = 6000
#: The runner emits a bounded number of journal events per bar (bar/signal/risk/fill + alerts).
MAX_JOURNAL_EVENTS_PER_STEP: int = 8
#: A deterministic memory proxy ceiling: bytes of serialized journal per processing step.
MAX_JOURNAL_BYTES_PER_STEP: int = 4096


@dataclass(frozen=True, slots=True)
class ResourceReport:
    """Deterministic resource measurements for one instrument's qualification run."""

    instrument_symbol: str
    processing_steps: int
    journal_events: int
    journal_bytes: int
    within_bounds: bool
    detail: str


def measure_resources(qualification: InstrumentQualification) -> ResourceReport:
    """Measure and bound the deterministic resource footprint of one qualification run."""
    steps = qualification.result.bars_processed
    events = len(qualification.result.journal.events)
    journal_bytes = len(qualification.result.journal.to_jsonl_bytes())
    problems: list[str] = []
    if steps > MAX_PROCESSING_STEPS:
        problems.append(f"processing steps {steps} exceed {MAX_PROCESSING_STEPS}")
    if steps > 0 and events > steps * MAX_JOURNAL_EVENTS_PER_STEP:
        problems.append(
            f"journal events {events} exceed {MAX_JOURNAL_EVENTS_PER_STEP}/step over {steps} steps"
        )
    if steps > 0 and journal_bytes > steps * MAX_JOURNAL_BYTES_PER_STEP:
        problems.append(f"journal bytes {journal_bytes} exceed {MAX_JOURNAL_BYTES_PER_STEP}/step")
    within = not problems
    detail = "within deterministic resource bounds" if within else "; ".join(problems)
    return ResourceReport(
        instrument_symbol=qualification.instrument_symbol,
        processing_steps=steps,
        journal_events=events,
        journal_bytes=journal_bytes,
        within_bounds=within,
        detail=detail,
    )


__all__ = [
    "MAX_JOURNAL_BYTES_PER_STEP",
    "MAX_JOURNAL_EVENTS_PER_STEP",
    "MAX_PROCESSING_STEPS",
    "ResourceReport",
    "measure_resources",
]
