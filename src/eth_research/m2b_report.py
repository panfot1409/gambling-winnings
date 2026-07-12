"""Deterministic train/validation-only benchmark dossier for the real dataset.

This computes the Milestone 2B benchmark on **train and validation only** and
renders an honest report. The test segment is split off mechanically but is
never handed to a strategy or the engine: this module calls
:func:`eth_research.evaluation.evaluate_train_validation_from_manifest`, which
structurally evaluates only the train and validation frames. It never calls
:func:`run_authorized_benchmark`, never writes the test-access ledger, and
never computes a test signal, fill, or P&L.

Every number comes from the validated :class:`BenchmarkResults` model
(reconciled bar-by-bar against the engine's accounting); the report is a pure
rendering of that model plus a provenance appendix drawn only from committed
files. Both artifacts are byte-deterministic, so a fresh clone regenerates
them exactly.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from eth_research.data.acquisition_plan import load_acquisition_plan, load_acquisition_receipt
from eth_research.data.builder import load_canonical_dataset
from eth_research.data.provenance import sha256_bytes
from eth_research.environment import load_runtime_contract
from eth_research.evaluation import (
    build_benchmark_results,
    evaluate_train_validation_from_manifest,
    render_benchmark_markdown,
)
from eth_research.protocol import BenchmarkProtocol, BenchmarkResults

RESULTS_RELPATH: str = "research/m2b/train_validation_results.json"
REPORT_RELPATH: str = "research/m2b/train_validation_report.md"
PROTOCOL_RELPATH: str = "research/m2b/protocol.json"
RUNTIME_RELPATH: str = "research/m2b/runtime_contract.json"
PLAN_RELPATH: str = "research/m2b/acquisition_request_plan.json"


def _real_attempt_dir(repo_root: Path) -> Path:
    base = repo_root / "research" / "m2b" / "raw" / "coinbase"
    attempts = [p for p in base.iterdir() if p.is_dir() and p.name != "discovery-001"]
    if len(attempts) != 1:
        raise RuntimeError(f"expected exactly one real acquisition attempt, found {attempts}")
    return attempts[0]


def build_results(
    repo_root: str | Path,
    manifest_path: str | Path,
    *,
    pre_registered_commit_sha: str,
) -> BenchmarkResults:
    """Compute the train/validation-only results from the frozen protocol.

    ``manifest_path`` points at the reproducible canonical manifest (under the
    git-ignored ``data/`` tree, materialized by the replay tool). The dataset
    is reloaded and re-verified internally; the test segment is never
    evaluated (``test_evaluation_id`` is ``None``).
    """
    root = Path(repo_root)
    protocol = BenchmarkProtocol.from_json_bytes((root / PROTOCOL_RELPATH).read_bytes())
    segments = evaluate_train_validation_from_manifest(manifest_path, protocol)
    dataset = load_canonical_dataset(manifest_path)
    return build_benchmark_results(
        dataset,
        protocol,
        segments,
        pre_registered_commit_sha=pre_registered_commit_sha,
        test_evaluation_id=None,
    )


def render_report(repo_root: str | Path, results: BenchmarkResults) -> str:
    """Render the report: the validated model plus a committed-file appendix."""
    root = Path(repo_root)
    core = render_benchmark_markdown(results)
    runtime = load_runtime_contract(root / RUNTIME_RELPATH)
    plan = load_acquisition_plan(root / PLAN_RELPATH)
    attempt_dir = _real_attempt_dir(root)
    receipt = load_acquisition_receipt(attempt_dir / "acquisition_receipt.json")

    lines: list[str] = []
    add = lines.append
    add("## Provenance and authoritative runtime")
    add("")
    add(
        f"- Authoritative benchmark runtime: {runtime.python_implementation} "
        f"{runtime.python_version} ({runtime.python_cache_tag}, {runtime.os_family}/"
        f"{runtime.machine}); numpy {runtime.numpy_version}, pandas "
        f"{runtime.pandas_version}, pyarrow {runtime.pyarrow_version}."
    )
    add(f"- Runtime contract SHA-256: `{sha256_bytes(runtime.to_json_bytes())}`")
    add(f"- Acquisition request-plan SHA-256: `{plan.plan_sha256()}`")
    add(
        f"- Raw acquisition: attempt `{receipt.attempt_id}`, "
        f"{len(receipt.responses)} public GET response(s), workflow run "
        f"`{receipt.workflow_run_id}`, source commit `{receipt.source_commit}`."
    )
    add(
        f"- Windows: {plan.expected_request_count} over [{plan.overall_start.date()}, "
        f"{plan.overall_end.date()})."
    )
    add("")
    add("## Test-set status")
    add("")
    add(
        "Train and validation are now observed; the **test** segment remains "
        "unobserved by any strategy or backtest code. Its boundaries above are "
        "mechanical (timestamps only) — no test price, return, or performance "
        "figure appears anywhere in this dossier. The one-time test evaluation "
        "is still pending independent authorization, and the append-only "
        "test-access ledger remains byte-empty."
    )
    add("")
    return core + "\n" + "\n".join(lines)


def _protocol_commit(repo_root: Path) -> str:
    """The commit that froze the protocol — a fixed, reproducible reference."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "log", "-1", "--format=%H", "--", PROTOCOL_RELPATH],
        capture_output=True,
        text=True,
        check=True,
    )
    sha = result.stdout.strip()
    if len(sha) != 40:
        raise RuntimeError(f"could not resolve the protocol freeze commit, got {sha!r}")
    return sha


def generate(repo_root: str | Path, manifest_path: str | Path) -> tuple[bytes, str]:
    """Return the deterministic (results JSON bytes, report markdown)."""
    root = Path(repo_root)
    commit = _protocol_commit(root)
    results = build_results(root, manifest_path, pre_registered_commit_sha=commit)
    return results.to_json_bytes(), render_report(root, results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eth_research.m2b_report")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--manifest",
        default="data/m2b/datasets/coinbase-exchange-eth-usd-86400s.manifest.json",
    )
    parser.add_argument("--write", action="store_true", help="write the tracked artifacts")
    parser.add_argument("--check", action="store_true", help="compare against committed artifacts")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)

    try:
        results_bytes, report_md = generate(root, args.manifest)
    except (RuntimeError, ValueError) as exc:
        print(f"train/validation report generation failed: {exc}", file=sys.stderr)
        return 1

    if args.check:
        ok = True
        committed_results = root / RESULTS_RELPATH
        committed_report = root / REPORT_RELPATH
        if not committed_results.exists() or committed_results.read_bytes() != results_bytes:
            print("train_validation_results.json does not match", file=sys.stderr)
            ok = False
        if not committed_report.exists() or committed_report.read_text("utf-8") != report_md:
            print("train_validation_report.md does not match", file=sys.stderr)
            ok = False
        print("train/validation report reproducible" if ok else "MISMATCH")
        return 0 if ok else 1

    if args.write:
        (root / RESULTS_RELPATH).write_bytes(results_bytes)
        (root / REPORT_RELPATH).write_text(report_md, encoding="utf-8")
        print(f"wrote {RESULTS_RELPATH} and {REPORT_RELPATH}")
    else:
        print(report_md)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
