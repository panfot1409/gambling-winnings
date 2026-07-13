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
import os
import subprocess
import sys
import tempfile
from pathlib import Path

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
) -> tuple[bytes, str]:
    """Return the deterministic (results JSON bytes, report markdown).

    Reconstructs the dataset from the committed raw bytes into a temporary
    directory (never a tracked path), runs the research-train walk-forward,
    and renders the report purely from the validated results model.
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
        )
    return results.to_json_bytes(), render_development_report(results)


def result_bundle_sha256(results_bytes: bytes, report_md: str) -> str:
    """SHA-256 of the results JSON bytes concatenated with the report bytes."""
    return sha256_bytes(results_bytes + report_md.encode("utf-8"))


def _atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a temp file and an atomic rename."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _committed_provenance(repo_root: Path) -> tuple[str, str, str]:
    """(execution commit, registered commit, family) from the committed results."""
    payload = load_development_results_payload(repo_root / RESULTS_RELPATH)
    return (
        payload["execution_code_commit_sha"],
        payload["registered_code_commit_sha"],
        payload["experiment_family_id"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eth_research.develop_m3a")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--execution-commit",
        default=None,
        help="the pre-registration code commit whose code produces the results (write mode)",
    )
    parser.add_argument("--write", action="store_true", help="write the tracked artifacts")
    parser.add_argument("--check", action="store_true", help="compare against committed artifacts")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)

    try:
        if args.check:
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
        else:
            registered = registered_commit_from_history(root)
            execution = args.execution_commit
            if execution is None:
                print("--execution-commit is required in write mode", file=sys.stderr)
                return 1
            family = EXPERIMENT_FAMILY_ID
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

    if args.write:
        results_path = root / RESULTS_RELPATH
        report_path = root / REPORT_RELPATH
        # Transactional publish: write both artifacts, then read both back,
        # strict-parse the results, regenerate from the recorded provenance,
        # and require byte-exact reproduction before reporting success.
        _atomic_write(results_path, results_bytes)
        _atomic_write(report_path, report_md.encode("utf-8"))
        execution2, registered2, family2 = _committed_provenance(root)
        regen_bytes, regen_md = generate(
            root,
            execution_code_commit_sha=execution2,
            registered_code_commit_sha=registered2,
            experiment_family_id=family2,
        )
        if results_path.read_bytes() != regen_bytes or report_path.read_text("utf-8") != regen_md:
            print("published artifacts failed read-back verification", file=sys.stderr)
            return 1
        print(f"wrote and verified {RESULTS_RELPATH} and {REPORT_RELPATH}")
        print(f"results_json_sha256={sha256_bytes(regen_bytes)}")
        print(f"report_markdown_sha256={sha256_bytes(regen_md.encode('utf-8'))}")
        print(f"result_bundle_sha256={result_bundle_sha256(regen_bytes, regen_md)}")
    else:
        print(report_md)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
