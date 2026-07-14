"""Version-independent fresh-clone replay of the one M3C candidate run.

``check_replay`` accepts exactly four committed checkpoints, so the same CI is
green at each:

* **pristine** — the registry carries no run-001 event and none of the four
  immutable artifacts exist. The only guarantees are the two byte-empty sealed
  ledgers and the absent outputs.
* **registered** — the registry carries exactly ``registered`` (the committed
  pre-registration) and no artifacts exist yet. Every one of the five recorded
  inputs — protocol, lineage, budget, development partition, and frozen dossier —
  must equal the committed file, so a registration cannot bind a stale or tampered
  input while staying green.
* **completed** — the registry carries ``registered`` → ``started`` →
  ``completed``. From the committed raw Coinbase bytes alone the research-train
  partition is reconstructed offline, the 75-cell grid is re-run and reduced
  through the one shared pipeline, and the results JSON, the decision JSON, and the
  report Markdown are re-derived and compared **byte-for-byte** to the committed
  artifacts; then :func:`verify_published_run` re-checks the
  registry/decision/report/manifest/bundle chain and re-binds the five inputs.
* **failed** — the registry carries ``registered`` → ``started`` → ``failed``: the
  single-use id was honestly consumed by a run that did not complete, with no
  artifacts published. This is a real committed state (not a mid-lifecycle
  inconsistency), so an honest failure does not brick CI.

Both sealed ledgers must be byte-empty in every state. No networking; no sealed row
is ever read (the loader returns research-train rows only).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eth_research.data.provenance import sha256_file
from eth_research.development import DEVELOPMENT_PARTITION_RELPATH, FROZEN_M2_DOSSIER_RELPATH
from eth_research.m3c.archive import (
    M3C_MANIFEST_RELPATH,
    rederive_committed_decision,
    verify_published_run,
)
from eth_research.m3c.decision import M3C_DECISION_RELPATH, CandidateDecision
from eth_research.m3c.pipeline import reproduce_results
from eth_research.m3c.registry import (
    EVENT_COMPLETED,
    EVENT_FAILED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3C_REGISTRY_RELPATH,
    M3CRegistryEvent,
    read_registry,
)
from eth_research.m3c.results import (
    M3C_EXPERIMENT_ID,
    M3C_LINEAGE_RELPATH,
    M3C_PROTOCOL_RELPATH,
    M3C_REPORT_RELPATH,
    M3C_RESULTS_RELPATH,
    render_m3c_report,
)

_GATE_LEDGER_RELPATH: str = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"
_BUDGET_RELPATH: str = "research/m3c/research_budget.json"
_EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_ARTIFACTS: tuple[str, ...] = (
    M3C_RESULTS_RELPATH,
    M3C_DECISION_RELPATH,
    M3C_REPORT_RELPATH,
    M3C_MANIFEST_RELPATH,
)


class M3CReplayError(RuntimeError):
    """The M3C replay found the committed state inconsistent."""


def _require_ledgers_byte_empty(root: Path) -> None:
    for relpath in (_GATE_LEDGER_RELPATH, _HOLDOUT_LEDGER_RELPATH):
        path = root / relpath
        if not path.exists() or sha256_file(path) != _EMPTY_SHA256:
            raise M3CReplayError(f"sealed ledger {relpath} is not byte-empty")


def _require_registration_binds_inputs(root: Path, registered: M3CRegistryEvent) -> None:
    """Every committed input file must match the digest the run registered.

    Binds all five recorded inputs — protocol, lineage, budget, development
    partition, and frozen dossier — so a registered (or failed) checkpoint cannot
    silently carry a tampered or stale input while CI stays green.
    """
    for label, relpath, recorded in (
        ("protocol", M3C_PROTOCOL_RELPATH, registered.protocol_sha256),
        ("lineage", M3C_LINEAGE_RELPATH, registered.lineage_sha256),
        ("budget", _BUDGET_RELPATH, registered.research_budget_sha256),
        (
            "development partition",
            DEVELOPMENT_PARTITION_RELPATH,
            registered.development_partition_sha256,
        ),
        ("frozen dossier", FROZEN_M2_DOSSIER_RELPATH, registered.frozen_m2_dossier_sha256),
    ):
        if sha256_file(root / relpath) != recorded:
            raise M3CReplayError(
                f"registered {label} digest disagrees with the committed {relpath}"
            )


def check_replay(repo_root: str | Path) -> tuple[str, ...]:
    """Tri-state replay check; returns ``(state, *checks)``. Raises on any drift."""
    root = Path(repo_root)
    _require_ledgers_byte_empty(root)

    run_events = [
        e
        for e in read_registry(root / M3C_REGISTRY_RELPATH)
        if e.experiment_id == M3C_EXPERIMENT_ID
    ]
    lifecycle = [e.event for e in run_events]
    artifacts_present = [rel for rel in _ARTIFACTS if (root / rel).exists()]

    if not run_events:
        if artifacts_present:
            raise M3CReplayError(
                f"registry has no run-001 event but artifacts exist: {artifacts_present}"
            )
        return ("pristine", "ledgers_byte_empty", "no_run_no_artifacts")

    if lifecycle == [EVENT_REGISTERED]:
        if artifacts_present:
            raise M3CReplayError(
                f"run-001 is only registered but artifacts exist: {artifacts_present}"
            )
        registered = run_events[0]
        _require_registration_binds_inputs(root, registered)
        return (
            "registered",
            "ledgers_byte_empty",
            "preregistered_no_artifacts",
            "registration_binds_committed_inputs",
        )

    if lifecycle == [EVENT_REGISTERED, EVENT_STARTED, EVENT_FAILED]:
        # A legitimately recorded one-shot failure: the single-use id is spent and no
        # artifacts were published. This is a real committed checkpoint (CI must stay
        # green), not a mid-lifecycle inconsistency — the run honestly did not complete.
        if artifacts_present:
            raise M3CReplayError(
                f"failed run must not have published artifacts: {artifacts_present}"
            )
        _require_registration_binds_inputs(root, run_events[0])
        return ("failed", "ledgers_byte_empty", "run_failed_no_artifacts")

    if lifecycle != [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]:
        raise M3CReplayError(f"run-001 is mid-lifecycle {lifecycle!r}; not a committed state")
    missing = [rel for rel in _ARTIFACTS if rel not in artifacts_present]
    if missing:
        raise M3CReplayError(f"completed run is missing published artifacts: {missing}")

    registered = run_events[0]
    results = reproduce_results(root, registered)
    if results.to_json_bytes() != (root / M3C_RESULTS_RELPATH).read_bytes():
        raise M3CReplayError("reproduced results JSON does not match the committed bytes")
    committed_decision = CandidateDecision.from_json_bytes(
        (root / M3C_DECISION_RELPATH).read_bytes()
    )
    decision = rederive_committed_decision(results, committed_decision)
    if (
        render_m3c_report(results, decision).encode("utf-8")
        != (root / M3C_REPORT_RELPATH).read_bytes()
    ):
        raise M3CReplayError("reproduced report Markdown does not match the committed bytes")
    verify_published_run(root)
    return (
        "completed",
        "ledgers_byte_empty",
        "results_reproduced",
        "decision_reproduced",
        "report_reproduced",
        "archive_verified",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tri-state replay of the M3C candidate run.")
    parser.add_argument("--repo-root", default=".", help="repository root (default: .)")
    parser.add_argument("--check", action="store_true", help="verify committed state (default)")
    args = parser.parse_args(argv)
    try:
        state, *checks = check_replay(args.repo_root)
    except Exception as exc:  # CLI boundary: any failure is a non-zero exit
        print(f"REPLAY FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"replay OK [{state}]: {', '.join(checks)}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
