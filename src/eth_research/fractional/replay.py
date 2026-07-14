"""Version-independent fresh-clone replay of the one fractional run (Phase 21).

``check_replay`` is dual-state, so the same CI is green before and after the run:

* **pristine** — the registry carries no run-001 event and none of the three
  immutable artifacts exist. The only guarantees are the two byte-empty sealed
  ledgers and the absent outputs.
* **completed** — the registry carries ``registered`` → ``started`` →
  ``completed``. From the committed raw Coinbase bytes alone the research-train
  partition is reconstructed offline, the 75-cell experiment is re-run, and the
  results JSON and report Markdown are re-derived and compared **byte-for-byte**
  to the committed artifacts; then :func:`verify_published_run` re-checks the
  registry/manifest/bundle chain. The rebuild binds the *recorded* provenance
  from the registered event (version, commits, source fingerprint), so a later
  package-version bump leaves the committed bytes reproducible.

Both sealed ledgers must be byte-empty in every state. No networking; no sealed
row is ever read (the loader returns research-train rows only).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eth_research.data.provenance import sha256_file
from eth_research.fractional.archive import (
    FRACTIONAL_MANIFEST_RELPATH,
    verify_published_run,
)
from eth_research.fractional.dataset import verify_dataset_integrity_only
from eth_research.fractional.experiment import (
    build_fractional_results,
    compute_fractional_fold_cells,
)
from eth_research.fractional.protocol import (
    FRACTIONAL_PROTOCOL_RELPATH,
    RUN_001_EXPERIMENT_ID,
    load_fractional_protocol,
)
from eth_research.fractional.registry import (
    EVENT_COMPLETED,
    EVENT_REGISTERED,
    EVENT_STARTED,
    M3B_REGISTRY_RELPATH,
    FractionalRegistryEvent,
    read_registry,
)
from eth_research.fractional.results import (
    FRACTIONAL_REPORT_RELPATH,
    FRACTIONAL_RESULTS_RELPATH,
    render_fractional_report,
)
from eth_research.walkforward import WALK_FORWARD_PROTOCOL_RELPATH, load_walk_forward_protocol

_GATE_LEDGER_RELPATH: str = "research/m3a/development_gate_access.jsonl"
_HOLDOUT_LEDGER_RELPATH: str = "research/m2b/test_evaluations.jsonl"
_EMPTY_SHA256: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_ARTIFACTS: tuple[str, ...] = (
    FRACTIONAL_RESULTS_RELPATH,
    FRACTIONAL_REPORT_RELPATH,
    FRACTIONAL_MANIFEST_RELPATH,
)


class ReplayError(RuntimeError):
    """The fractional replay found the committed state inconsistent."""


def _require_ledgers_byte_empty(root: Path) -> None:
    for relpath in (_GATE_LEDGER_RELPATH, _HOLDOUT_LEDGER_RELPATH):
        path = root / relpath
        if not path.exists() or sha256_file(path) != _EMPTY_SHA256:
            raise ReplayError(f"sealed ledger {relpath} is not byte-empty")


def reproduce_artifacts(root: Path, registered: FractionalRegistryEvent) -> tuple[bytes, bytes]:
    """Recompute the results + report bytes from committed inputs alone.

    Binds the *recorded* provenance from the ``registered`` event so the rebuild
    is version-independent: the committed bytes reproduce even after a later
    package-version bump.
    """
    protocol = load_fractional_protocol(root / FRACTIONAL_PROTOCOL_RELPATH)
    wf_protocol = load_walk_forward_protocol(root / WALK_FORWARD_PROTOCOL_RELPATH)
    research_train = verify_dataset_integrity_only(root).research_train
    cells = compute_fractional_fold_cells(
        research_train, wf_protocol, initial_cash=protocol.initial_cash
    )
    results = build_fractional_results(
        fractional_protocol=protocol,
        research_train=research_train,
        fold_cells=cells,
        package_version=registered.package_version,
        execution_code_commit_sha=registered.execution_code_commit_sha,
        registered_code_commit_sha=registered.registered_code_commit_sha,
        execution_source_tree_fingerprint=registered.execution_source_tree_fingerprint,
        fractional_protocol_sha256=registered.fractional_protocol_sha256,
    )
    return results.to_json_bytes(), render_fractional_report(results).encode("utf-8")


def check_replay(repo_root: str | Path) -> tuple[str, ...]:
    """Dual-state replay check; returns ``(state, *checks)``. Raises on any drift."""
    root = Path(repo_root)
    _require_ledgers_byte_empty(root)

    run_events = [
        e
        for e in read_registry(root / M3B_REGISTRY_RELPATH)
        if e.experiment_id == RUN_001_EXPERIMENT_ID
    ]
    lifecycle = [e.event for e in run_events]
    artifacts_present = [rel for rel in _ARTIFACTS if (root / rel).exists()]

    if not run_events:
        if artifacts_present:
            raise ReplayError(
                f"registry has no run-001 event but artifacts exist: {artifacts_present}"
            )
        return ("pristine", "ledgers_byte_empty", "no_run_no_artifacts")

    if lifecycle != [EVENT_REGISTERED, EVENT_STARTED, EVENT_COMPLETED]:
        raise ReplayError(f"run-001 is mid-lifecycle {lifecycle!r}; not pristine or completed")
    if len(artifacts_present) != len(_ARTIFACTS):
        missing = [rel for rel in _ARTIFACTS if rel not in artifacts_present]
        raise ReplayError(f"completed run is missing published artifacts: {missing}")

    registered = run_events[0]
    results_bytes, report_bytes = reproduce_artifacts(root, registered)
    if results_bytes != (root / FRACTIONAL_RESULTS_RELPATH).read_bytes():
        raise ReplayError("reproduced results JSON does not match the committed bytes")
    if report_bytes != (root / FRACTIONAL_REPORT_RELPATH).read_bytes():
        raise ReplayError("reproduced report Markdown does not match the committed bytes")
    verify_published_run(root)
    return (
        "completed",
        "ledgers_byte_empty",
        "results_reproduced",
        "report_reproduced",
        "archive_verified",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dual-state replay of the M3B fractional run.")
    parser.add_argument("--repo-root", default=".", help="repository root (default: .)")
    parser.add_argument(
        "--check", action="store_true", help="verify committed state (default action)"
    )
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
