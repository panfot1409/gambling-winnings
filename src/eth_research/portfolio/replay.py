"""Deterministic offline replay verifier for the M4B portfolio simulator (Milestone 4B, §43).

``python -m eth_research.portfolio.replay --check`` regenerates the synthetic reference universe and
protocol from code, runs the simulation three ways — batch, streaming, and checkpoint/resume — and
fails closed unless they agree byte-for-byte, then builds and verifies the result artifact and
checks the committed public-API snapshot is current and additive. It is fully offline and read-only:
it reads only the committed public-API snapshots, writes nothing, and touches no network, clock, or
randomness. A green run is a reproducibility proof; a red run names the first check that failed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eth_research.api.serialization import CanonicalError, canonical_json_bytes
from eth_research.portfolio import public_api
from eth_research.portfolio.engine import PortfolioRunResult, run_portfolio_simulation
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.reference import (
    ReferenceUniverse,
    build_reference_universe,
    reference_protocol,
)
from eth_research.portfolio.result import build_portfolio_result, verify_portfolio_result
from eth_research.portfolio.streaming import (
    resume_portfolio_simulation,
    stream_portfolio_simulation,
)

_SECONDS_PER_YEAR = 365.25 * 24.0 * 3600.0


class ReplayError(RuntimeError):
    """A replay check failed: the simulator did not reproduce itself, or an artifact drifted."""


def _run_batch(reference: ReferenceUniverse) -> PortfolioRunResult:
    return run_portfolio_simulation(
        reference_protocol(),
        reference.panel,
        reference.membership,
        reference.fx,
        reference.run_schedule,
        calendars=reference.calendars,
        corporate_actions=reference.corporate_actions,
    )


def _check_determinism(reference: ReferenceUniverse) -> None:
    first = _run_batch(reference)
    second = _run_batch(reference)
    if first.result_fingerprint != second.result_fingerprint:
        raise ReplayError("two batch runs produced different result fingerprints")
    if first.canonical() != second.canonical():
        raise ReplayError("two batch runs produced different canonical results")


def _check_streaming_matches_batch(reference: ReferenceUniverse) -> None:
    batch = _run_batch(reference)
    streamed = [
        record.canonical()
        for record, _checkpoint in stream_portfolio_simulation(
            reference_protocol(),
            reference.panel,
            reference.membership,
            reference.fx,
            reference.run_schedule,
            calendars=reference.calendars,
            corporate_actions=reference.corporate_actions,
        )
    ]
    if streamed != [event.canonical() for event in batch.events]:
        raise ReplayError("streaming events do not match the batch events")


def _check_resume_matches_batch(reference: ReferenceUniverse) -> None:
    batch = _run_batch(reference)
    pairs = list(
        stream_portfolio_simulation(
            reference_protocol(),
            reference.panel,
            reference.membership,
            reference.fx,
            reference.run_schedule,
            calendars=reference.calendars,
            corporate_actions=reference.corporate_actions,
        )
    )
    if not pairs:
        raise ReplayError("the reference run produced no events")
    checkpoint = pairs[min(1, len(pairs) - 1)][1]
    resumed = resume_portfolio_simulation(
        checkpoint,
        reference_protocol(),
        reference.panel,
        reference.membership,
        reference.fx,
        reference.run_schedule,
        calendars=reference.calendars,
        corporate_actions=reference.corporate_actions,
    )
    if canonical_json_bytes(resumed.canonical_result) != canonical_json_bytes(batch.canonical()):
        raise ReplayError("a resumed run does not reproduce the batch result byte-for-byte")


def _check_result_artifact(reference: ReferenceUniverse) -> None:
    batch = _run_batch(reference)
    periods_per_year = _SECONDS_PER_YEAR / reference.universe_spec.bar_interval_seconds
    metrics = compute_portfolio_metrics(batch, periods_per_year=periods_per_year)
    result = build_portfolio_result(batch, metrics, reference.universe_spec)
    verify_portfolio_result(result, reference.universe_spec, batch)
    # the result must be canonical-JSON-safe (no NaN / Infinity)
    canonical_json_bytes(result.canonical())


def _check_public_api(repo_root: Path) -> None:
    try:
        public_api.verify(repo_root)
    except public_api.PublicAPIDriftError as exc:
        raise ReplayError(str(exc)) from exc


_CHECKS: tuple[tuple[str, str], ...] = (
    ("determinism", "two batch runs are byte-identical"),
    ("streaming", "streaming reproduces the batch events"),
    ("resume", "checkpoint/resume reproduces the batch result"),
    ("result", "the result artifact builds and verifies"),
    ("public_api", "the committed v1.1 API snapshot is current and additive"),
)


def run_checks(repo_root: str | Path = ".") -> list[tuple[str, str]]:
    """Run every replay check in order, returning ``(name, detail)`` for each pass.

    Raises :class:`ReplayError` (naming the check) on the first failure.
    """
    root = Path(repo_root)
    reference = build_reference_universe()
    passed: list[tuple[str, str]] = []
    _check_determinism(reference)
    passed.append(_CHECKS[0])
    _check_streaming_matches_batch(reference)
    passed.append(_CHECKS[1])
    _check_resume_matches_batch(reference)
    passed.append(_CHECKS[2])
    _check_result_artifact(reference)
    passed.append(_CHECKS[3])
    _check_public_api(root)
    passed.append(_CHECKS[4])
    return passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline, read-only M4B replay verifier over the synthetic reference universe."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--check", action="store_true", help="run all replay checks (the default)")
    args = parser.parse_args(argv)
    try:
        passed = run_checks(args.repo_root)
    except (ReplayError, CanonicalError) as exc:
        sys.stderr.write(f"replay: FAILED — {exc}\n")
        return 1
    for name, detail in passed:
        sys.stdout.write(f"replay: ok   {name:<12} {detail}\n")
    sys.stdout.write(f"replay: all {len(passed)} checks passed\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
