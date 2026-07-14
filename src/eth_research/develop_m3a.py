"""Deterministic research-train walk-forward experiment publisher (Milestone 3A).

Reconstructs the canonical dataset from the committed raw Coinbase bytes
(entirely offline), runs the fixed four-strategy walk-forward evaluation on the
**research-train partition only**, and publishes the strict results JSON and
the Markdown report. The development gate and the final holdout are never
evaluated; :mod:`eth_research.development_evaluation` guards every fold frame
and context, and both access ledgers stay byte-empty.

Both artifacts are byte-deterministic. A fresh clone regenerates them exactly
from the committed raw bytes and the provenance commits recorded inside the
results file, so ``--check`` reproduces the frozen files or fails. The
registration commit label is additionally bound to git history (the commit
that froze the walk-forward protocol), so it cannot be quietly repointed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from eth_research import __version__
from eth_research.data.provenance import sha256_bytes
from eth_research.development_evaluation import (
    evaluate_development,
    load_development_results_payload,
    render_development_report,
)
from eth_research.replay_m2b import reconstruct_dataset
from eth_research.walkforward import WALK_FORWARD_PROTOCOL_RELPATH

RESULTS_RELPATH: str = "research/m3a/development_results.json"
REPORT_RELPATH: str = "research/m3a/development_report.md"

EXPERIMENT_FAMILY_ID: str = "m3a-fixed-baseline-comparison-v1"


def _canonical_attempt_id(repo_root: Path) -> str:
    """The single committed real acquisition attempt, pinned by name."""
    from eth_research.dossier import CANONICAL_ATTEMPT_ID

    attempt = repo_root / "research/m2b/raw/coinbase" / CANONICAL_ATTEMPT_ID
    if not attempt.is_dir():
        raise RuntimeError(f"the canonical acquisition attempt directory {attempt} is missing")
    return CANONICAL_ATTEMPT_ID


def registered_commit_from_history(repo_root: str | Path) -> str:
    """The commit that froze the walk-forward protocol, from git history.

    The last commit touching the committed walk-forward protocol — the honest
    registration anchor. ``--check`` requires the value recorded in the
    committed results to equal this, so the registration label cannot be
    quietly repointed at some other commit. Requires full git history
    (CI checkouts fetch with ``fetch-depth: 0``).
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "log",
            "-1",
            "--format=%H",
            "--",
            WALK_FORWARD_PROTOCOL_RELPATH,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    sha = result.stdout.strip()
    if len(sha) != 40:
        raise RuntimeError(f"could not resolve the protocol freeze commit, got {sha!r}")
    return sha


def _commit_exists(repo_root: str | Path, sha: str) -> bool:
    """True if ``sha`` names a real commit object in the repository."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
    )
    return result.returncode == 0


def generate(
    repo_root: str | Path,
    *,
    execution_code_commit_sha: str,
    registered_code_commit_sha: str,
    experiment_family_id: str = EXPERIMENT_FAMILY_ID,
    package_version: str = __version__,
) -> tuple[bytes, str]:
    """Return the deterministic (results JSON bytes, report markdown).

    Reconstructs the dataset from the committed raw bytes into a temporary
    directory (never a tracked path), runs the research-train walk-forward,
    and renders the report purely from the validated results model.

    ``package_version`` defaults to the running version for a fresh generation;
    reproducing a committed v1 experiment binds the version that experiment
    recorded so its bytes stay byte-identical across a later package bump.
    """
    root = Path(repo_root)
    attempt_id = _canonical_attempt_id(root)
    with tempfile.TemporaryDirectory() as tmp:
        manifest = reconstruct_dataset(root, attempt_id, tmp).build.manifest_path
        results = evaluate_development(
            root,
            manifest,
            execution_code_commit_sha=execution_code_commit_sha,
            registered_code_commit_sha=registered_code_commit_sha,
            experiment_family_id=experiment_family_id,
            package_version=package_version,
        )
    return results.to_json_bytes(), render_development_report(results)


def result_bundle_sha256(results_bytes: bytes, report_md: str) -> str:
    """SHA-256 of the results JSON bytes concatenated with the report bytes.

    A pure hashing helper (not a write path); real-data publication happens
    only through the fail-closed orchestrator.
    """
    return sha256_bytes(results_bytes + report_md.encode("utf-8"))


def _committed_provenance(repo_root: Path) -> tuple[str, str, str]:
    """(execution commit, registered commit, family) from the committed results."""
    payload = load_development_results_payload(repo_root / RESULTS_RELPATH)
    return (
        payload["execution_code_commit_sha"],
        payload["registered_code_commit_sha"],
        payload["experiment_family_id"],
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: replay-verify the committed v1 artifacts, preview the report, or run
    a pre-registered experiment through the fail-closed orchestrator.

    There is deliberately **no** unregistered real-data write path (closure
    defect R1): the only way to publish real research-train artifacts is
    ``--run-experiment``, which routes through
    :func:`eth_research.development_orchestrator.run_registered_development_experiment`
    and its registry-gated, transactional publication.
    """
    parser = argparse.ArgumentParser(prog="eth_research.develop_m3a")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--check", action="store_true", help="compare against committed artifacts")
    parser.add_argument(
        "--run-experiment",
        default=None,
        metavar="EXPERIMENT_ID",
        help="run a pre-registered experiment through the fail-closed orchestrator",
    )
    args = parser.parse_args(argv)
    root = Path(args.repo_root)

    if args.run_experiment is not None:
        from eth_research.development_orchestrator import (
            OrchestratorError,
            run_registered_development_experiment,
        )

        try:
            completed = run_registered_development_experiment(root, args.run_experiment)
        except OrchestratorError as exc:
            print(f"orchestrated experiment refused or failed: {exc}", file=sys.stderr)
            return 1
        print(f"completed {completed.experiment_id}")
        print(f"results_json_sha256={completed.results_json_sha256}")
        print(f"report_markdown_sha256={completed.report_markdown_sha256}")
        print(f"return_evidence_sha256={completed.return_evidence_sha256}")
        print(f"result_bundle_sha256={completed.result_bundle_sha256}")
        return 0

    # Dispatch replay on the latest completed experiment's schema: v1 (run-002)
    # reproduces from the v1 evaluator; v2 (run-003) reproduces the v2 archive.
    from eth_research.artifact_errata import ArtifactErrataError, verify_artifact_errata
    from eth_research.replay_m3a_v2 import ReplayV2Error, latest_completed_is_v2, verify_v2_replay

    try:
        is_v2 = latest_completed_is_v2(root)
    except (RuntimeError, ValueError) as exc:
        print(f"development experiment failed: {exc}", file=sys.stderr)
        return 1
    if is_v2:
        if args.check:
            try:
                experiment_id = verify_v2_replay(root)
            except (ReplayV2Error, RuntimeError, ValueError) as exc:
                print(f"{RESULTS_RELPATH} does not match: {exc}", file=sys.stderr)
                print("MISMATCH")
                return 1
            try:
                errata = verify_artifact_errata(root)
            except (ArtifactErrataError, RuntimeError, ValueError) as exc:
                print(f"artifact errata do not verify: {exc}", file=sys.stderr)
                print("MISMATCH")
                return 1
            suffix = f", {len(errata)} verified bound erratum" if errata else ""
            print(f"development experiment reproducible (v2 {experiment_id}{suffix})")
            return 0
        print((root / REPORT_RELPATH).read_text("utf-8"))
        return 0

    # Replay verification / preview of the committed v1 experiment (read-only).
    try:
        execution, registered, family = _committed_provenance(root)
        history_registered = registered_commit_from_history(root)
        if registered != history_registered:
            print(
                f"registered_code_commit_sha {registered} does not equal the protocol "
                f"freeze commit {history_registered}",
                file=sys.stderr,
            )
            return 1
        if not _commit_exists(root, execution):
            print(
                f"execution_code_commit_sha {execution} is not a real commit object",
                file=sys.stderr,
            )
            return 1
        results_bytes, report_md = generate(
            root,
            execution_code_commit_sha=execution,
            registered_code_commit_sha=registered,
            experiment_family_id=family,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"development experiment failed: {exc}", file=sys.stderr)
        return 1

    if args.check:
        ok = True
        committed_results = root / RESULTS_RELPATH
        committed_report = root / REPORT_RELPATH
        if not committed_results.exists() or committed_results.read_bytes() != results_bytes:
            print(f"{RESULTS_RELPATH} does not match", file=sys.stderr)
            ok = False
        if not committed_report.exists() or committed_report.read_text("utf-8") != report_md:
            print(f"{REPORT_RELPATH} does not match", file=sys.stderr)
            ok = False
        print("development experiment reproducible" if ok else "MISMATCH")
        return 0 if ok else 1

    print(report_md)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
