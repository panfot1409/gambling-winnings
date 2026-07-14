"""Deterministic run-003 registration CLI (Section 9 / N8).

Appends **exactly one** ``registered`` schema-v2 event for the corrective
research-train experiment ``m3a-fixed-baseline-comparison-v2-run-003`` to the
canonical experiment registry — and nothing else. It never evaluates market
data, never publishes run artifacts, and never touches either sealed access
ledger::

    python -m eth_research.m3a_register --repo-root . --check
    python -m eth_research.m3a_register --repo-root . --append

``--check`` is read-only: it re-verifies every run-agnostic precondition
(:func:`eth_research.development_orchestrator.verify_repository_preconditions`,
the exact checks the run itself will re-prove), builds the registered event
deterministically, verifies its bindings, and prints a preview plus the event's
line hash and the previous-line hash it chains onto. ``--append`` additionally
appends that one event with a single fsynced ``O_APPEND`` write and then proves
the only tracked change is that one appended registry line.

Commit-identity (see ``docs/M3A_RUN003_TERMINAL_PLAN.md``):

* ``E`` — the execution-source commit whose ``src/eth_research`` tree runs; it
  is HEAD at registration and is recorded as ``execution_code_commit_sha``.
* ``registered_code_commit_sha`` — the methodology/protocol freeze commit
  (the last commit touching the v2 methodology artifact).
* ``R`` — the registry-only commit that will *contain* this appended event. It
  is a real descendant of ``E`` derived from git history **after** committing,
  never written into the event (a commit cannot contain its own SHA).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from eth_research import __version__
from eth_research.costs import COST_SCENARIOS
from eth_research.data.provenance import sha256_bytes
from eth_research.development_orchestrator import (
    OrchestratorError,
    RepositoryPreconditions,
    verify_repository_preconditions,
)
from eth_research.experiment_archive import verify_experiment_archive
from eth_research.experiment_registry import (
    CORRECTION_METHODOLOGY_GOVERNANCE,
    EVENT_COMPLETED,
    EVENT_REGISTERED,
    EXPERIMENT_REGISTRY_RELPATH,
    REGISTRY_SCHEMA_VERSION_V2,
    ExperimentEventV2,
    append_registry_event,
    latest_registry_line_sha256,
    read_registry,
)
from eth_research.gitcheck import is_commit_object
from eth_research.methodology_v2 import (
    EXPERIMENT_FAMILY_V2,
    METHODOLOGY_PROTOCOL_V2_RELPATH,
)
from eth_research.walkforward import STRATEGY_NAMES, WALK_FORWARD_PROTOCOL_RELPATH

RUN_003_EXPERIMENT_ID: str = "m3a-fixed-baseline-comparison-v2-run-003"
RUN_003_CORRECTS: str = "m3a-fixed-baseline-comparison-v1-run-002"
_EXPERIMENTS_RELDIR: str = "research/m3a/experiments"
# The immutable six-line v1 registry prefix's SHA-256; the append must not alter it.
_REGISTRY_PREFIX_SHA256: str = "7920d9fdf4e936ef6c6d79dfd1c10cdd12dcb9b2db264b9ab9d5640332e9af67"

_HYPOTHESIS: str = (
    "Methodology-and-publication-governance correction of the fixed-baseline "
    "comparison. The financial strategies, parameters, transaction costs, folds, "
    "data, and accounting are unchanged from run-002; run-003 corrects the "
    "bootstrap fold-seam handling (fold-stratified and hierarchical resampling), "
    "records the exact effective RNG seeds and distinct commit-identity fields, "
    "and republishes through the fail-closed transactional publication path. It "
    "is not a new alpha hypothesis, authorizes no development-gate or "
    "final-holdout access, and can promote no candidate."
)


class RegistrationError(RuntimeError):
    """Deterministic run-003 registration refused to proceed."""


def _freeze_commit(repo_root: Path, relpath: str) -> str:
    """The last commit that touched ``relpath`` (the artifact's freeze commit).

    Requires full git history (CI checkouts fetch with ``fetch-depth: 0``).
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "log", "-1", "--format=%H", "--", relpath],
        capture_output=True,
        text=True,
        check=True,
    )
    sha = result.stdout.strip()
    if len(sha) != 40:
        raise RegistrationError(f"could not resolve the freeze commit for {relpath!r}, got {sha!r}")
    return sha


def build_run003_registration(
    repo_root: str | Path,
    *,
    experiment_id: str = RUN_003_EXPERIMENT_ID,
    corrects: str = RUN_003_CORRECTS,
    clock: Callable[[], pd.Timestamp] | None = None,
) -> ExperimentEventV2:
    """Verify every precondition and build the exact ``registered`` event.

    Read-only. Raises :class:`RegistrationError` on any refusal. This is the
    single source of the run-003 registered event; the CLI's ``--check`` and
    ``--append`` both build through it so the previewed and appended bytes are
    identical.
    """
    if experiment_id != RUN_003_EXPERIMENT_ID:
        raise RegistrationError(
            f"this tool registers only {RUN_003_EXPERIMENT_ID!r}, not {experiment_id!r}"
        )
    if corrects != RUN_003_CORRECTS:
        raise RegistrationError(f"run-003 corrects only {RUN_003_CORRECTS!r}, not {corrects!r}")
    now = clock if clock is not None else (lambda: pd.Timestamp.now(tz="UTC"))

    # Run-agnostic repository preconditions — the exact checks the run re-proves.
    try:
        pre = verify_repository_preconditions(repo_root)
    except OrchestratorError as exc:
        raise RegistrationError(f"repository preconditions failed: {exc}") from exc
    root = pre.repo_root

    # The whole archive (run-001, run-002) must verify against the registry.
    try:
        verify_experiment_archive(root)
    except (ValueError, RuntimeError, OSError) as exc:
        raise RegistrationError(f"existing experiment archive failed verification: {exc}") from exc

    # The canonical registry: strict read (validates the whole append chain).
    registry_path = root / EXPERIMENT_REGISTRY_RELPATH
    events = read_registry(registry_path)
    by_id: dict[str, list[str]] = {}
    for event in events:
        by_id.setdefault(event.experiment_id, []).append(event.event)
    if experiment_id in by_id:
        raise RegistrationError(
            f"experiment id {experiment_id!r} is already present (stages={by_id[experiment_id]}); "
            "an experiment id is single-use"
        )
    if by_id.get(corrects, [])[-1:] != [EVENT_COMPLETED]:
        raise RegistrationError(f"correction parent {corrects!r} has no completed event to correct")

    # Commit identity: E = HEAD (execution source); the methodology freeze commit
    # is a real ancestor commit that last touched the v2 methodology artifact.
    execution_commit = pre.head
    methodology_freeze_commit = _freeze_commit(root, METHODOLOGY_PROTOCOL_V2_RELPATH)
    if not is_commit_object(root, methodology_freeze_commit):
        raise RegistrationError("the methodology freeze commit is not a real commit object")

    previous = latest_registry_line_sha256(registry_path)
    if previous is None:  # pragma: no cover - registry always has the v1 prefix
        raise RegistrationError("registry is empty; cannot chain a v2 event")

    archive_dir = f"{_EXPERIMENTS_RELDIR}/{experiment_id}"
    event = ExperimentEventV2(
        registry_schema_version=REGISTRY_SCHEMA_VERSION_V2,
        event=EVENT_REGISTERED,
        experiment_id=experiment_id,
        experiment_family=EXPERIMENT_FAMILY_V2,
        corrects_experiment_id=corrects,
        correction_kind=CORRECTION_METHODOLOGY_GOVERNANCE,
        hypothesis=_HYPOTHESIS,
        strategies=STRATEGY_NAMES,
        cost_scenarios=tuple(scenario.name for scenario in COST_SCENARIOS),
        methodology_id=pre.methodology_id,
        development_partition_sha256=pre.partition_sha256,
        walk_forward_protocol_path=WALK_FORWARD_PROTOCOL_RELPATH,
        walk_forward_protocol_sha256=pre.methodology_artifact_sha256,
        package_version=__version__,
        registered_code_commit_sha=methodology_freeze_commit,
        execution_code_commit_sha=execution_commit,
        execution_source_tree_fingerprint=pre.source_tree_fingerprint,
        event_time_utc=now(),
        immutable_results_path=f"{archive_dir}/development_results.json",
        immutable_report_path=f"{archive_dir}/development_report.md",
        return_evidence_path=f"{archive_dir}/return_evidence.json",
        artifact_manifest_path=f"{archive_dir}/artifact_manifest.json",
        results_json_sha256=None,
        report_markdown_sha256=None,
        return_evidence_sha256=None,
        result_bundle_sha256=None,
        failure_description=None,
        previous_event_sha256=previous,
    )
    _verify_event_bindings(pre, event)
    return event


def _verify_event_bindings(pre: RepositoryPreconditions, event: ExperimentEventV2) -> None:
    """Re-prove the built event satisfies the run's binding checks (belt & braces).

    Mirrors :func:`eth_research.development_orchestrator._preflight` check 14 so a
    registration that ``--check`` accepts cannot later be refused at run time.
    """
    if event.execution_source_tree_fingerprint != pre.source_tree_fingerprint:
        raise RegistrationError(
            "execution source-tree fingerprint disagrees with the running source"
        )
    if event.development_partition_sha256 != pre.partition_sha256:
        raise RegistrationError("partition SHA disagrees with the committed partition")
    if event.walk_forward_protocol_path != WALK_FORWARD_PROTOCOL_RELPATH:
        raise RegistrationError("walk-forward protocol path is not the canonical path")
    if event.walk_forward_protocol_sha256 != pre.methodology_artifact_sha256:
        raise RegistrationError(
            "walk_forward_protocol_sha256 must bind the v2 methodology artifact"
        )
    if event.methodology_id != pre.methodology_id:
        raise RegistrationError("methodology id disagrees with the methodology artifact")


def _tracked_diff_paths(repo_root: Path) -> list[str]:
    """Repo-relative paths of every changed tracked file (porcelain)."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line[3:] for line in result.stdout.splitlines() if line.strip()]


def append_run003_registration(repo_root: str | Path, event: ExperimentEventV2) -> None:
    """Append the one registered event and prove the only tracked change is it.

    The append is the registry's single fsynced ``O_APPEND`` write. Afterward the
    immutable six-line prefix must be byte-unchanged and the sole tracked diff
    must be ``experiment_registry.jsonl``.
    """
    root = Path(repo_root)
    registry_path = root / EXPERIMENT_REGISTRY_RELPATH
    append_registry_event(registry_path, event)
    # The immutable v1 prefix must be byte-identical after the append.
    lines = registry_path.read_bytes().split(b"\n")[:-1]
    prefix_bytes = b"\n".join(lines[:6]) + b"\n"
    if sha256_bytes(prefix_bytes) != _REGISTRY_PREFIX_SHA256:
        raise RegistrationError("the immutable six-line registry prefix changed — refusing")
    changed = _tracked_diff_paths(root)
    if changed != [EXPERIMENT_REGISTRY_RELPATH]:
        raise RegistrationError(
            f"registration must change only {EXPERIMENT_REGISTRY_RELPATH}; changed: {changed}"
        )


def main(argv: list[str] | None = None) -> int:
    """CLI: preview (``--check``) or append (``--append``) the run-003 registration."""
    parser = argparse.ArgumentParser(
        prog="eth_research.m3a_register",
        description="Deterministically register the corrective run-003 experiment.",
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--experiment-id", default=RUN_003_EXPERIMENT_ID)
    parser.add_argument("--corrects", default=RUN_003_CORRECTS)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="read-only preview and verification")
    group.add_argument("--append", action="store_true", help="append the one registered event")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)

    try:
        event = build_run003_registration(
            root, experiment_id=args.experiment_id, corrects=args.corrects
        )
    except (RegistrationError, OrchestratorError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"registration refused: {exc}", file=sys.stderr)
        return 1

    line = event.to_json_line()[:-1]
    print(f"experiment_id={event.experiment_id}")
    print(f"corrects={event.corrects_experiment_id} ({event.correction_kind})")
    print(f"execution_code_commit_sha={event.execution_code_commit_sha}")
    print(f"registered_code_commit_sha={event.registered_code_commit_sha}")
    print(f"execution_source_tree_fingerprint={event.execution_source_tree_fingerprint}")
    print(f"previous_event_sha256={event.previous_event_sha256}")
    print(f"registered_event_sha256={sha256_bytes(line)}")
    print(f"registered_event_line={line.decode('utf-8')}")

    if args.check:
        print("check: registration is ready to append (nothing written)")
        return 0

    try:
        append_run003_registration(root, event)
    except (RegistrationError, ValueError, subprocess.CalledProcessError, OSError) as exc:
        print(f"append refused: {exc}", file=sys.stderr)
        return 1
    print(f"appended {event.experiment_id} (only {EXPERIMENT_REGISTRY_RELPATH} changed)")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
