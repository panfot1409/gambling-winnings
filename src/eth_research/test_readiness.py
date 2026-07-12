"""Read-only holdout-readiness preflight.

Answers "could the one-time authorized evaluation run right now?" **without
ever touching the test set**. It composes the same verification functions
the authorized evaluator uses — package-source binding, runtime contract,
the complete provenance-v2 graph, dataset lock, holdout identity and
conflict policy, the canonical ledger, and a train/validation-only
regeneration — and emits only integrity facts: hashes, fingerprints, the
opaque holdout id, the test window bounds and row count, and the ledger's
byte/hash/event counts.

Every operation here is read-only and structurally test-free: it runs the
train/validation segments and the integrity-only holdout fingerprint, but
never instantiates a strategy for test, runs the engine on a test row, or
computes a test return, metric, or summary. It mutates nothing — the
ledger, reports, and tracked tree are byte-identical afterwards.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from eth_research import __version__
from eth_research.data.provenance import sha256_bytes
from eth_research.environment import (
    CANONICAL_RUNTIME_CONTRACT_RELPATH,
    load_runtime_contract,
    verify_runtime_contract,
)
from eth_research.evaluation import (
    CANONICAL_LEDGER_RELPATH,
    RESULTS_FILENAME,
    evaluate_train_validation_from_manifest,
    split_boundaries,
)
from eth_research.gitcheck import (
    head_commit,
    resolve_repo_root,
    tracked_tree_is_clean,
    verify_package_source,
)
from eth_research.holdout import build_holdout_identity, find_holdout_conflicts
from eth_research.ledger import read_ledger
from eth_research.protocol import BenchmarkProtocol
from eth_research.provenance_v2 import verify_provenance_graph

PROTOCOL_RELPATH: str = "research/m2b/protocol.json"


@dataclass(frozen=True)
class PreflightCheck:
    """One read-only readiness check and its outcome."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    """Safe, deterministic readiness facts — never any test performance."""

    ready: bool
    head_sha: str
    package_version: str
    provenance_graph_ok: bool
    ledger_byte_count: int
    ledger_sha256: str
    ledger_event_count: int
    holdout_id: str | None
    test_content_fingerprint: str | None
    test_first_open_time: str | None
    test_last_open_time: str | None
    test_row_count: int | None
    output_collision: bool
    train_validation_ran: bool
    checks: tuple[PreflightCheck, ...]

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization — no wall-clock timestamp."""
        payload = {
            "ready": self.ready,
            "head_sha": self.head_sha,
            "package_version": self.package_version,
            "provenance_graph_ok": self.provenance_graph_ok,
            "ledger_byte_count": self.ledger_byte_count,
            "ledger_sha256": self.ledger_sha256,
            "ledger_event_count": self.ledger_event_count,
            "holdout_id": self.holdout_id,
            "test_content_fingerprint": self.test_content_fingerprint,
            "test_first_open_time": self.test_first_open_time,
            "test_last_open_time": self.test_last_open_time,
            "test_row_count": self.test_row_count,
            "output_collision": self.output_collision,
            "train_validation_ran": self.train_validation_ran,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")


def preflight_authorized_benchmark(
    repo_root: str | Path,
    manifest_path: str | Path,
    output_dir: str | Path = "reports/m2b",
) -> PreflightReport:
    """Run every read-only readiness check; touch no test row; mutate nothing."""
    checks: list[PreflightCheck] = []

    def record(name: str, ok: bool, detail: str = "") -> bool:
        checks.append(PreflightCheck(name=name, passed=ok, detail=detail))
        return ok

    root = resolve_repo_root(repo_root)
    head = head_commit(root)

    try:
        import eth_research

        location = eth_research.__file__
        if location is None:  # pragma: no cover - namespace package, not our layout
            raise RuntimeError("the running eth_research package has no filesystem location")
        verify_package_source(root, head, Path(location).resolve().parent)
        record("package_source_bound_to_head", True)
    except Exception as exc:
        record("package_source_bound_to_head", False, str(exc))

    try:
        record("tracked_tree_clean", tracked_tree_is_clean(root))
    except Exception as exc:
        record("tracked_tree_clean", False, str(exc))

    try:
        contract = load_runtime_contract(root / CANONICAL_RUNTIME_CONTRACT_RELPATH)
        verify_runtime_contract(contract, repo_root=root)
        record("runtime_contract", True)
    except Exception as exc:
        record("runtime_contract", False, str(exc))

    graph_ok = False
    try:
        graph = verify_provenance_graph(root)
        graph_ok = graph.ok
        record("provenance_graph", graph.ok, "" if graph.ok else "; ".join(graph.errors))
    except Exception as exc:
        record("provenance_graph", False, str(exc))

    # Canonical ledger: byte count, hash, and strict, non-conflicting history.
    ledger_path = root / CANONICAL_LEDGER_RELPATH
    ledger_bytes = ledger_path.read_bytes() if ledger_path.is_file() else b""
    events = read_ledger(ledger_path)
    record("ledger_readable", True, f"{len(events)} event(s)")

    protocol = BenchmarkProtocol.from_json_bytes((root / PROTOCOL_RELPATH).read_bytes())

    holdout_id: str | None = None
    test_fp: str | None = None
    test_first: str | None = None
    test_last: str | None = None
    test_rows: int | None = None
    train_validation_ran = False
    try:
        from eth_research.data.builder import load_canonical_dataset

        dataset = load_canonical_dataset(manifest_path)
        holdout = build_holdout_identity(dataset, protocol)
        holdout_id = holdout.holdout_id
        test_fp = holdout.test_content_fingerprint
        test_first = holdout.test_first_open_time.isoformat()
        test_last = holdout.test_last_open_time.isoformat()
        test_rows = holdout.test_row_count
        record("holdout_identity", True)
        conflicts = find_holdout_conflicts(events, holdout)
        record(
            "no_conflicting_holdout",
            not conflicts,
            "" if not conflicts else f"consumed by {conflicts[0].evaluation_id}",
        )
        bounds = split_boundaries(dataset, protocol)
        record("split_boundaries", bounds[2].n_bars == holdout.test_row_count)
    except Exception as exc:
        record("holdout_identity", False, str(exc))

    try:
        segments = evaluate_train_validation_from_manifest(manifest_path, protocol)
        train_validation_ran = all(entry.segment in ("train", "validation") for entry in segments)
        record("train_validation_regenerates", train_validation_ran)
    except Exception as exc:
        record("train_validation_regenerates", False, str(exc))

    directory = Path(output_dir)
    collision = (directory / RESULTS_FILENAME).exists()
    record("no_existing_output", not collision)

    ready = all(check.passed for check in checks)
    return PreflightReport(
        ready=ready,
        head_sha=head,
        package_version=__version__,
        provenance_graph_ok=graph_ok,
        ledger_byte_count=len(ledger_bytes),
        ledger_sha256=sha256_bytes(ledger_bytes),
        ledger_event_count=len(events),
        holdout_id=holdout_id,
        test_content_fingerprint=test_fp,
        test_first_open_time=test_first,
        test_last_open_time=test_last,
        test_row_count=test_rows,
        output_collision=collision,
        train_validation_ran=train_validation_ran,
        checks=tuple(checks),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eth_research.test_readiness")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--manifest",
        default="data/m2b/datasets/coinbase-exchange-eth-usd-86400s.manifest.json",
    )
    parser.add_argument("--output-dir", default="reports/m2b")
    args = parser.parse_args(argv)
    try:
        report = preflight_authorized_benchmark(args.repo_root, args.manifest, args.output_dir)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"preflight failed to run: {exc}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(report.to_json_bytes())
    return 0 if report.ready else 1


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
