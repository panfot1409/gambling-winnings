"""Read-only holdout-readiness report over the shared preparation path.

Answers "could the one-time authorized evaluation run right now?" by
calling :func:`eth_research.evaluation.prepare_authorized_evaluation` —
the *identical* function the production evaluator runs — in read-only
mode. There is no second hand-maintained checklist: a check added to the
shared preparation affects this command and production equally.

The report separates the honest states instead of one ambiguous "ready":

* ``integrity_ready`` — the complete shared preparation succeeded;
* ``holdout_fresh`` — no recorded access conflicts with the holdout;
* ``promotion_decision`` / ``promotion_eligible`` — the committed,
  re-derived scientific decision;
* ``authorized_test_ready`` — all of the above and no output collision.

For the current committed dossier the correct state is integrity-ready,
holdout-fresh, and **not** authorized-test-ready, because the fixed
SMA(20/50) is ``rejected_for_test_promotion``. That is a scientific
finding, not an infrastructure failure — the informational CLI mode exits
zero for it, and ``--require-authorized-test-ready`` exits nonzero.

This command mechanically loads and hashes test candles for integrity
(fingerprints, bounds, counts) but never evaluates the holdout and never
computes test performance; it mutates nothing — the ledger, reports, and
tracked tree are byte-identical afterwards.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from eth_research import __version__
from eth_research.data.coinbase import load_acquisition_evidence
from eth_research.data.provenance import sha256_bytes
from eth_research.evaluation import (
    CANONICAL_LEDGER_RELPATH,
    prepare_authorized_evaluation,
)
from eth_research.gitcheck import head_commit, resolve_repo_root

_CANONICAL_ATTEMPT_RELPATH: str = "research/m2b/raw/coinbase/coinbase-eth-usd-001"


@dataclass(frozen=True)
class PreflightReport:
    """Safe, deterministic readiness facts — never any test performance."""

    integrity_ready: bool
    integrity_failure: str | None
    head_sha: str
    package_version: str
    dossier_verified: bool
    holdout_fresh: bool
    promotion_decision: str | None
    promotion_eligible: bool
    authorized_test_ready: bool
    holdout_id: str | None
    test_content_fingerprint: str | None
    test_first_open_time: str | None
    test_last_open_time: str | None
    test_row_count: int | None
    ledger_byte_count: int
    ledger_sha256: str
    ledger_event_count: int
    output_collision: bool
    train_validation_reproducible: bool

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization — no wall-clock timestamp."""
        payload = {
            "integrity_ready": self.integrity_ready,
            "integrity_failure": self.integrity_failure,
            "head_sha": self.head_sha,
            "package_version": self.package_version,
            "dossier_verified": self.dossier_verified,
            "holdout_fresh": self.holdout_fresh,
            "promotion_decision": self.promotion_decision,
            "promotion_eligible": self.promotion_eligible,
            "authorized_test_ready": self.authorized_test_ready,
            "holdout_id": self.holdout_id,
            "test_content_fingerprint": self.test_content_fingerprint,
            "test_first_open_time": self.test_first_open_time,
            "test_last_open_time": self.test_last_open_time,
            "test_row_count": self.test_row_count,
            "ledger_byte_count": self.ledger_byte_count,
            "ledger_sha256": self.ledger_sha256,
            "ledger_event_count": self.ledger_event_count,
            "output_collision": self.output_collision,
            "train_validation_reproducible": self.train_validation_reproducible,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")


def _running_package_root() -> Path:
    import eth_research

    location = eth_research.__file__
    if location is None:  # pragma: no cover - namespace package, not our layout
        raise RuntimeError("the running eth_research package has no filesystem location")
    return Path(location).resolve().parent


def preflight_authorized_benchmark(
    repo_root: str | Path,
    manifest_path: str | Path,
    output_dir: str | Path = "reports/m2b",
    *,
    raw_chunk_dir: str | Path | None = None,
    derived_csv: str | Path | None = None,
) -> PreflightReport:
    """Run the shared preparation read-only; touch no test row; mutate nothing.

    ``raw_chunk_dir`` defaults to the canonical committed attempt directory
    and ``derived_csv`` to the replay layout beside ``manifest_path``
    (``<work>/<derived name>`` with the dataset under ``<work>/datasets``).
    """
    root = resolve_repo_root(repo_root)
    head = head_commit(root)
    if raw_chunk_dir is None:
        raw_chunk_dir = root / _CANONICAL_ATTEMPT_RELPATH
    if derived_csv is None:
        evidence = load_acquisition_evidence(root / "research/m2b/acquisition_evidence.json")
        derived_csv = Path(manifest_path).resolve().parent.parent / evidence.derived_filename

    ledger_file = root / CANONICAL_LEDGER_RELPATH
    ledger_bytes = ledger_file.read_bytes() if ledger_file.is_file() else b""

    integrity_failure: str | None = None
    prepared = None
    try:
        prepared = prepare_authorized_evaluation(
            repo_root=root,
            manifest_path=manifest_path,
            protocol_path=root / "research/m2b/protocol.json",
            lock_path=root / "research/m2b/dataset_lock.json",
            acquisition_evidence_path=root / "research/m2b/acquisition_evidence.json",
            output_dir=output_dir,
            raw_chunk_dir=raw_chunk_dir,
            derived_csv=derived_csv,
            running_package_root=_running_package_root(),
            authorization_commit=None,
        )
    except Exception as exc:
        integrity_failure = f"{type(exc).__name__}: {exc}"

    if prepared is None:
        return PreflightReport(
            integrity_ready=False,
            integrity_failure=integrity_failure,
            head_sha=head,
            package_version=__version__,
            dossier_verified=False,
            holdout_fresh=False,
            promotion_decision=None,
            promotion_eligible=False,
            authorized_test_ready=False,
            holdout_id=None,
            test_content_fingerprint=None,
            test_first_open_time=None,
            test_last_open_time=None,
            test_row_count=None,
            ledger_byte_count=len(ledger_bytes),
            ledger_sha256=sha256_bytes(ledger_bytes),
            ledger_event_count=ledger_bytes.count(b"\n"),
            output_collision=False,
            train_validation_reproducible=False,
        )

    return PreflightReport(
        integrity_ready=True,
        integrity_failure=None,
        head_sha=prepared.head,
        package_version=__version__,
        dossier_verified=True,
        holdout_fresh=prepared.holdout_fresh,
        promotion_decision=prepared.decision.decision,
        promotion_eligible=prepared.promotion_eligible,
        authorized_test_ready=(
            prepared.holdout_fresh and prepared.promotion_eligible and not prepared.output_collision
        ),
        holdout_id=prepared.holdout.holdout_id,
        test_content_fingerprint=prepared.holdout.test_content_fingerprint,
        test_first_open_time=prepared.holdout.test_first_open_time.isoformat(),
        test_last_open_time=prepared.holdout.test_last_open_time.isoformat(),
        test_row_count=prepared.holdout.test_row_count,
        ledger_byte_count=len(ledger_bytes),
        ledger_sha256=sha256_bytes(ledger_bytes),
        ledger_event_count=len(prepared.events),
        output_collision=prepared.output_collision,
        train_validation_reproducible=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eth_research.test_readiness")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--manifest",
        default="data/m2b/datasets/coinbase-exchange-eth-usd-86400s.manifest.json",
    )
    parser.add_argument("--output-dir", default="reports/m2b")
    parser.add_argument("--raw-chunk-dir", default=None)
    parser.add_argument("--derived-csv", default=None)
    parser.add_argument(
        "--require-authorized-test-ready",
        action="store_true",
        help="exit nonzero unless the dossier is fully authorized-test-ready "
        "(the current committed SMA rejection correctly exits nonzero here)",
    )
    args = parser.parse_args(argv)
    try:
        report = preflight_authorized_benchmark(
            args.repo_root,
            args.manifest,
            args.output_dir,
            raw_chunk_dir=args.raw_chunk_dir,
            derived_csv=args.derived_csv,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"preflight failed to run: {exc}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(report.to_json_bytes())
    if args.require_authorized_test_ready:
        return 0 if report.authorized_test_ready else 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess/CI
    raise SystemExit(main())
