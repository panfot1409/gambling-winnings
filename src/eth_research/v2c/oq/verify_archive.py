"""V2C section 21: the deep, read-only verifier for a published OQ run archive.

One entry point re-proves the whole published-run surface without re-executing the qualification:

* the OQ registry is a real file whose hash chain and lifecycle validate to exactly
  ``registered`` -> ``started`` -> ``completed`` for the run, every event sharing one identity;
* the ``completed`` event's five terminal hashes match the published archive -- ``result_sha256`` /
  ``report_sha256`` / ``archive_manifest_sha256`` are the byte hashes of the three files,
  ``evidence_sha256`` is the result's own semantic digest, and ``result_bundle_sha256`` re-derives
  from the four;
* ``oq_result.json`` parses, re-scans free of financial-performance vocabulary, re-derives its own
  digest, and reports exactly zero risky exposure (zero risky intents/fills/turnover, book at zero);
* ``oq_report.md`` re-renders byte-for-byte from the result;
* ``oq_archive_manifest.json`` re-derives its digest and binds the result and report;
* both non-empty and the third sealed access ledger are byte-empty, there is no pending completion
  intent, and the archive directory holds exactly the three real (non-symlink) files.

It evaluates no strategy, reads no market data, mutates no byte, and computes no market performance.
"""

from __future__ import annotations

from pathlib import Path

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_sha256,
    sha256_bytes,
    strict_json_loads,
)
from eth_research.v2c.oq.archive import (
    OQ_ARCHIVE_DIR,
    OQ_ARCHIVE_MANIFEST_RELNAME,
    OQ_ARCHIVE_REPORT_RELNAME,
    OQ_ARCHIVE_RESULT_RELNAME,
    archive_relpath,
)
from eth_research.v2c.oq.completion import OQ_COMPLETION_INTENT_RELPATH
from eth_research.v2c.oq.registry import (
    OQ_EVENT_COMPLETED,
    OQ_EVENT_REGISTERED,
    OQ_EVENT_STARTED,
    read_oq_registry,
)
from eth_research.v2c.oq.result import build_oq_report, scan_for_forbidden_vocabulary
from eth_research.v2c.oq.supersession import EMPTY_SHA256, SEALED_LEDGER_RELPATHS


class OQRunArchiveError(V2ValidationError):
    """The comprehensive OQ run-archive verification failed a structural check."""


def _read_archive_file(repo_root: Path, relname: str) -> bytes:
    raw = repo_root / archive_relpath(relname)
    if raw.is_symlink():
        raise OQRunArchiveError(f"archive artifact {relname} is a symlink")
    if not raw.is_file():
        raise OQRunArchiveError(f"archive artifact {relname} is missing")
    return raw.read_bytes()


def verify_oq_run_archive(repo_root: str | Path, registry_path: str | Path) -> tuple[str, ...]:
    """Re-prove the entire published-run surface (read-only). Returns the ordered passed checks.

    Raises :class:`OQRunArchiveError` (or the underlying typed error) on the first violation.
    """
    root = Path(repo_root)
    checks: list[str] = []

    # 1. The registry is a real file; its chain + lifecycle validate registered->started->completed.
    reg = Path(registry_path)
    if reg.is_symlink() or not reg.is_file():
        raise OQRunArchiveError("the OQ registry is missing or not a real file")
    events = read_oq_registry(reg)
    stages = [event.event for event in events]
    if stages != [OQ_EVENT_REGISTERED, OQ_EVENT_STARTED, OQ_EVENT_COMPLETED]:
        raise OQRunArchiveError(
            f"registry lifecycle is not registered->started->completed: {stages}"
        )
    identities = {event.identity.as_map()["qualification_id"] for event in events}
    if len(identities) != 1:
        raise OQRunArchiveError("registry events do not share one qualification identity")
    checks.append("registry_lifecycle_registered_started_completed")
    completed = events[-1]

    # 2. Read the three published artifacts (real files, not symlinks).
    result_bytes = _read_archive_file(root, OQ_ARCHIVE_RESULT_RELNAME)
    report_bytes = _read_archive_file(root, OQ_ARCHIVE_REPORT_RELNAME)
    manifest_bytes = _read_archive_file(root, OQ_ARCHIVE_MANIFEST_RELNAME)
    checks.append("archive_artifacts_present")

    # 3. The completed event's terminal hashes match the published bytes.
    result_sha256 = sha256_bytes(result_bytes)
    report_sha256 = sha256_bytes(report_bytes)
    archive_manifest_sha256 = sha256_bytes(manifest_bytes)
    if completed.result_sha256 != result_sha256:
        raise OQRunArchiveError("completed event result_sha256 does not match oq_result.json")
    if completed.report_sha256 != report_sha256:
        raise OQRunArchiveError("completed event report_sha256 does not match oq_report.md")
    if completed.archive_manifest_sha256 != archive_manifest_sha256:
        raise OQRunArchiveError(
            "completed event archive_manifest_sha256 does not match the manifest"
        )
    checks.append("terminal_hashes_match_published_bytes")

    # 4. The result parses, re-scans clean, re-derives its own digest, and reports zero exposure.
    result = strict_json_loads(result_bytes)
    if not isinstance(result, dict):
        raise OQRunArchiveError("oq_result.json is not a JSON object")
    scan_for_forbidden_vocabulary("oq_result", result)
    recorded_digest = result.get("result_digest")
    body = {key: value for key, value in result.items() if key != "result_digest"}
    if canonical_sha256(body) != recorded_digest:
        raise OQRunArchiveError("oq_result.json result_digest does not re-derive")
    if completed.evidence_sha256 != recorded_digest:
        raise OQRunArchiveError("completed event evidence_sha256 is not the result digest")
    if result.get("verdict") != completed.verdict:
        raise OQRunArchiveError("oq_result.json verdict disagrees with the completed event")
    counts = result.get("operational_counts")
    if not isinstance(counts, dict):
        raise OQRunArchiveError("oq_result.json has no operational_counts")
    for field in ("risky_intent_count", "risky_fill_count", "turnover", "terminal_book_units"):
        if counts.get(field) != 0 and counts.get(field) != 0.0:
            raise OQRunArchiveError(
                f"operational_counts.{field} is not zero: {counts.get(field)!r}"
            )
    checks.append("result_rescans_clean_and_zero_exposure")

    # 5. The aggregate result bundle re-derives from the four content/marker digests.
    result_bundle_sha256 = canonical_sha256(
        {
            "result_sha256": result_sha256,
            "report_sha256": report_sha256,
            "evidence_sha256": recorded_digest,
            "archive_manifest_sha256": archive_manifest_sha256,
        }
    )
    if completed.result_bundle_sha256 != result_bundle_sha256:
        raise OQRunArchiveError("completed event result_bundle_sha256 does not re-derive")
    checks.append("result_bundle_re_derives")

    # 6. The report re-renders byte-for-byte from the result.
    if build_oq_report(result).encode("utf-8") != report_bytes:
        raise OQRunArchiveError("oq_report.md does not re-render from oq_result.json")
    checks.append("report_re_renders")

    # 7. The manifest re-derives its digest and binds the result + report.
    manifest = strict_json_loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise OQRunArchiveError("oq_archive_manifest.json is not a JSON object")
    manifest_body = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if canonical_sha256(manifest_body) != manifest.get("manifest_digest"):
        raise OQRunArchiveError("oq_archive_manifest.json manifest_digest does not re-derive")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise OQRunArchiveError("oq_archive_manifest.json has no artifacts map")
    if artifacts.get(OQ_ARCHIVE_RESULT_RELNAME) != result_sha256:
        raise OQRunArchiveError("manifest does not bind oq_result.json")
    if artifacts.get(OQ_ARCHIVE_REPORT_RELNAME) != report_sha256:
        raise OQRunArchiveError("manifest does not bind oq_report.md")
    if manifest.get("evidence_sha256") != recorded_digest:
        raise OQRunArchiveError("manifest evidence_sha256 disagrees with the result digest")
    checks.append("manifest_re_derives_and_binds")

    # 8. All three sealed access ledgers are byte-empty.
    for relpath in SEALED_LEDGER_RELPATHS:
        path = root / relpath
        if (
            path.is_symlink()
            or not path.is_file()
            or sha256_bytes(path.read_bytes()) != EMPTY_SHA256
        ):
            raise OQRunArchiveError(f"sealed ledger {relpath} is missing or not byte-empty")
    checks.append("sealed_ledgers_byte_empty")

    # 9. No pending completion intent, and the archive directory holds exactly the three files.
    intent_path = root / OQ_COMPLETION_INTENT_RELPATH
    if intent_path.is_symlink() or intent_path.exists():
        raise OQRunArchiveError("a pending completion intent is present (run is unfinalized)")
    checks.append("no_pending_completion_intent")
    entries = sorted(p.name for p in (root / OQ_ARCHIVE_DIR).iterdir())
    if entries != sorted(
        (OQ_ARCHIVE_RESULT_RELNAME, OQ_ARCHIVE_REPORT_RELNAME, OQ_ARCHIVE_MANIFEST_RELNAME)
    ):
        raise OQRunArchiveError(f"archive directory holds unexpected entries: {entries}")
    checks.append("archive_directory_shape")

    return tuple(checks)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    from eth_research.v2c.oq.registry import OQ_REGISTRY_PATH

    parser = argparse.ArgumentParser(description="V2C OQ run-archive deep verify (read-only)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--registry", default=None, help="path to the OQ registry (default: canonical)"
    )
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    registry = Path(args.registry) if args.registry else root / OQ_REGISTRY_PATH
    try:
        checks = verify_oq_run_archive(root, registry)
    except (OSError, V2ValidationError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps({"ok": True, "checks": list(checks)}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "OQRunArchiveError",
    "verify_oq_run_archive",
]
