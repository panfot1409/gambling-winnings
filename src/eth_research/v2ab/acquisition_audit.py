"""Independent BTC-acquisition acceptance audit (read-only, offline, result-neutral).

This verifier does NOT trust any committed manifest, lock, or receipt on its face. It
re-derives the canonical BTC-USD daily series *from the committed raw candle bytes* for
both the genesis and the independent audit acquisition, and proves:

* each acquisition parses to exactly 2221 canonical daily rows spanning
  ``2016-05-23 .. 2022-06-21`` with zero row at/after the research-cutoff seal
  (``2022-06-22T00:00:00Z``), zero forming candle, no missing/duplicate open, and strict
  86400-second daily steps;
* the two acquisitions are *independent* (distinct ``workflow_run_id`` and distinct
  ``source_commit``) yet reproduce byte/fingerprint-identical canonical candles, and that
  shared fingerprint equals both the committed ``btc_dataset_fingerprint`` in
  ``joint_partition_identity.json`` and the hard-coded accepted anchor frozen at
  acceptance time (so a *fully self-consistent* replacement of the raw bundles is still
  caught);
* every committed receipt's response counts, byte lengths, and SHA-256 values are
  self-consistent with the raw candle files actually present;
* the one-shot acquisition workflow is *retired*: no committed workflow contacts the
  Coinbase endpoint or grants ``contents: write`` / ``id-token: write``, the sentinel is
  consumed, and the governance amendment honestly distinguishes the final-tree state from
  the historical state (it does not claim the workflow never existed).

The raw-root and evidence paths are parameters (:class:`AuditPaths`), so an adversarial
test can point the audit at a tampered *copy* without touching any accepted artifact.
Nothing here makes a network call or writes a byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eth_research.v2.strict import (
    V2ValidationError,
    canonical_json_bytes,
    require_hex64,
    require_int,
    require_mapping,
    require_nonempty_str,
    require_nonnegative_int,
    strict_json_loads,
)
from eth_research.v2b.acquisition import (
    AUDIT_ATTEMPT_ID,
    BTC_GRANULARITY_SECONDS,
    EXPECTED_DAILY_OPENS,
    GENESIS_ATTEMPT_ID,
    RESEARCH_CUTOFF_LAST_OPEN,
    WINDOW_END_EXCLUSIVE,
    WINDOW_START,
    Candle,
    build_btc_acquisition_plan,
    build_plan_bytes,
    build_window_receipt,
    canonical_daily_frame,
    content_fingerprint,
    parse_candles_body,
)
from eth_research.v2b.btc_dataset import (
    ACQUISITION_PLAN_RELPATH,
    DATASET_LOCK_RELPATH,
    build_dataset_lock,
)
from eth_research.v2b.partition import JOINT_PARTITION_IDENTITY_RELPATH

RAW_ROOT_RELPATH: str = "research/v2b/raw/coinbase"
WORKFLOWS_RELPATH: str = ".github/workflows"
ACQUISITION_DOC_RELPATH: str = "docs/V2B_ACQUISITION.md"
ACQUIRE_SENTINEL_RELPATH: str = "research/v2b/acquire.trigger"

#: The accepted canonical BTC daily content fingerprint, frozen at acceptance time. This is
#: the decisive external anchor: it equals ``btc_dataset_fingerprint`` in the committed
#: ``joint_partition_identity.json`` and is what a consistent raw replacement cannot forge.
ACCEPTED_BTC_DATASET_FINGERPRINT: str = (
    "6896e6146d747d3b24295e07371eb8a1b8db4f7d8dbe991f2a797a720c1a39ce"
)

EXPECTED_ROW_COUNT: int = EXPECTED_DAILY_OPENS
CUTOFF_SEAL_ISO: str = "2022-06-22T00:00:00Z"

_ATTEMPT_IDS: tuple[str, str] = (GENESIS_ATTEMPT_ID, AUDIT_ATTEMPT_ID)
_EPOCH_FIRST: int = int(WINDOW_START.timestamp())
_EPOCH_LAST: int = int(RESEARCH_CUTOFF_LAST_OPEN.timestamp())
_EPOCH_SEAL: int = int(WINDOW_END_EXCLUSIVE.timestamp())

# A workflow that matches any of these is *not* retired: it either contacts the Coinbase
# acquisition endpoint or grants a write capability the retired one-shot workflow had.
_COINBASE_ENDPOINT_RE = re.compile(r"api\.exchange\.coinbase\.com")
_CONTENTS_WRITE_RE = re.compile(r"contents\s*:\s*write")
_IDTOKEN_WRITE_RE = re.compile(r"id-token\s*:\s*write")
_PACKAGES_WRITE_RE = re.compile(r"packages\s*:\s*write")
_WRITE_ALL_RE = re.compile(r"permissions\s*:\s*write-all")
_RECEIPT_NAME: str = "acquisition_receipt.json"


class AcquisitionAuditError(V2ValidationError):
    """A BTC-acquisition acceptance invariant failed under independent re-derivation."""


@dataclass(frozen=True, slots=True)
class AuditPaths:
    """Every path the audit reads. Passing a tampered copy re-targets the whole audit."""

    repo_root: Path
    raw_root: Path
    joint_identity: Path
    workflows_dir: Path
    acquisition_doc: Path
    acquire_sentinel: Path

    @classmethod
    def for_repo(cls, repo_root: str | Path) -> AuditPaths:
        root = Path(repo_root)
        return cls(
            repo_root=root,
            raw_root=root / RAW_ROOT_RELPATH,
            joint_identity=root / JOINT_PARTITION_IDENTITY_RELPATH,
            workflows_dir=root / WORKFLOWS_RELPATH,
            acquisition_doc=root / ACQUISITION_DOC_RELPATH,
            acquire_sentinel=root / ACQUIRE_SENTINEL_RELPATH,
        )


@dataclass(frozen=True, slots=True)
class BtcAcquisitionAudit:
    """The independently re-derived facts about the BTC acquisition (plus any problems)."""

    attempt_ids: tuple[str, str]
    row_count: int
    first_open: str
    last_open: str
    genesis_fingerprint: str
    audit_fingerprint: str
    committed_btc_dataset_fingerprint: str
    accepted_btc_dataset_fingerprint: str
    genesis_workflow_run_id: str
    audit_workflow_run_id: str
    genesis_source_commit: str
    audit_source_commit: str
    distinct_workflow_run_ids: bool
    distinct_source_commits: bool
    canonical_candles_identical: bool
    no_row_at_or_after_cutoff: bool
    strict_monotonic_daily: bool
    receipts_self_consistent: bool
    final_tree_acquisition_workflow_absent: bool
    historical_acquisition_attested: bool
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(frozen=True, slots=True)
class _WindowReceipt:
    ordinal: int
    filename: str
    body_sha256: str
    body_bytes: int
    parsed_open_count: int
    first_open_epoch: int
    last_open_epoch: int


@dataclass(frozen=True, slots=True)
class _AttemptReceipt:
    attempt_id: str
    workflow_run_id: str
    source_commit: str
    plan_sha256: str
    package_version: str
    windows: tuple[_WindowReceipt, ...]


@dataclass(frozen=True, slots=True)
class _Derivation:
    receipt: _AttemptReceipt
    fingerprint: str
    times: tuple[int, ...]


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reject_symlink(path: Path) -> None:
    if path.is_symlink():
        raise AcquisitionAuditError(f"symlink is not permitted in the raw tree: {path.name}")


def _reject_escape(repo_root: Path, path: Path) -> None:
    resolved = path.resolve()
    root = repo_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise AcquisitionAuditError(f"path escapes the repository root: {path.name}")


def _list_raw_files(directory: Path, repo_root: Path) -> set[str]:
    """Names directly under ``directory``; reject any symlink, sub-directory, or escape."""
    names: set[str] = set()
    for child in sorted(directory.iterdir()):
        _reject_symlink(child)
        _reject_escape(repo_root, child)
        if not child.is_file():
            raise AcquisitionAuditError(f"unexpected non-file in the raw tree: {child.name}")
        if child.name in names:  # defensive: a real directory cannot list a name twice
            raise AcquisitionAuditError(f"duplicate raw filename: {child.name}")
        names.add(child.name)
    return names


def _read_raw(path: Path, repo_root: Path) -> bytes:
    _reject_symlink(path)
    _reject_escape(repo_root, path)
    return path.read_bytes()


def _parse_receipt(path: Path, attempt_id: str) -> _AttemptReceipt:
    obj = require_mapping(f"{attempt_id}.receipt", strict_json_loads(path.read_bytes()))
    windows_raw = obj.get("windows")
    if not isinstance(windows_raw, list):
        raise AcquisitionAuditError(f"{attempt_id}: receipt windows is not a JSON array")
    windows: list[_WindowReceipt] = []
    for i, raw in enumerate(windows_raw):
        w = require_mapping(f"{attempt_id}.receipt.windows[{i}]", raw)
        windows.append(
            _WindowReceipt(
                ordinal=require_nonnegative_int(f"{attempt_id}.win[{i}].ordinal", w.get("ordinal")),
                filename=require_nonempty_str(f"{attempt_id}.win[{i}].filename", w.get("filename")),
                body_sha256=require_hex64(f"{attempt_id}.win[{i}].sha", w.get("body_sha256")),
                body_bytes=require_int(f"{attempt_id}.win[{i}].bytes", w.get("body_bytes")),
                parsed_open_count=require_int(
                    f"{attempt_id}.win[{i}].opens", w.get("parsed_open_count")
                ),
                first_open_epoch=require_int(
                    f"{attempt_id}.win[{i}].first", w.get("first_open_epoch")
                ),
                last_open_epoch=require_int(
                    f"{attempt_id}.win[{i}].last", w.get("last_open_epoch")
                ),
            )
        )
    return _AttemptReceipt(
        attempt_id=require_nonempty_str(f"{attempt_id}.receipt.attempt_id", obj.get("attempt_id")),
        workflow_run_id=require_nonempty_str(
            f"{attempt_id}.receipt.workflow_run_id", obj.get("workflow_run_id")
        ),
        source_commit=require_nonempty_str(
            f"{attempt_id}.receipt.source_commit", obj.get("source_commit")
        ),
        plan_sha256=require_hex64(f"{attempt_id}.receipt.plan_sha256", obj.get("plan_sha256")),
        package_version=require_nonempty_str(
            f"{attempt_id}.receipt.package_version", obj.get("package_version")
        ),
        windows=tuple(windows),
    )


def _derive_attempt(paths: AuditPaths, attempt_id: str) -> _Derivation:
    """Re-derive one attempt's canonical series + fingerprint from its raw candle bytes."""
    _reject_symlink(paths.raw_root)
    attempt_dir = paths.raw_root / attempt_id
    _reject_symlink(attempt_dir)
    _reject_escape(paths.repo_root, attempt_dir)
    if not attempt_dir.is_dir():
        raise AcquisitionAuditError(f"{attempt_id}: raw attempt directory is missing")

    plan = build_btc_acquisition_plan()
    candle_names = [w.filename for w in plan.windows]
    expected = {_RECEIPT_NAME, *candle_names}
    present = _list_raw_files(attempt_dir, paths.repo_root)
    if present != expected:
        extra = sorted(present - expected)
        missing = sorted(expected - present)
        raise AcquisitionAuditError(
            f"{attempt_id}: raw file set mismatch (extra={extra}, missing={missing})"
        )

    receipt = _parse_receipt(attempt_dir / _RECEIPT_NAME, attempt_id)
    if receipt.attempt_id != attempt_id:
        raise AcquisitionAuditError(f"{attempt_id}: receipt attempt_id disagrees with its dir")
    if receipt.plan_sha256 != plan.plan_sha256():
        raise AcquisitionAuditError(f"{attempt_id}: receipt plan_sha256 != the immutable plan")
    if len(receipt.windows) != len(plan.windows):
        raise AcquisitionAuditError(f"{attempt_id}: receipt window count != the plan")

    rows_by_window: list[list[Candle]] = []
    for window, wr in zip(plan.windows, receipt.windows, strict=True):
        body = _read_raw(attempt_dir / window.filename, paths.repo_root)
        rows = parse_candles_body(body, window)  # rejects any at/after cutoff, dup, misaligned
        local = build_window_receipt(attempt_id, window, body, plan.plan_sha256())
        if (
            wr.ordinal != window.ordinal
            or wr.filename != window.filename
            or local.body_sha256 != wr.body_sha256
            or local.body_bytes != wr.body_bytes
            or local.parsed_open_count != wr.parsed_open_count
            or local.first_open_epoch != wr.first_open_epoch
            or local.last_open_epoch != wr.last_open_epoch
        ):
            raise AcquisitionAuditError(
                f"{attempt_id} window {window.ordinal}: raw bytes drift the committed receipt"
            )
        rows_by_window.append(rows)

    frame = canonical_daily_frame(rows_by_window)  # re-asserts 2221 rows, bounds, no gap
    times = tuple(sorted(r[0] for rows in rows_by_window for r in rows))
    return _Derivation(receipt=receipt, fingerprint=content_fingerprint(frame), times=times)


def _committed_btc_fingerprint(joint_identity: Path) -> str:
    decoded = strict_json_loads(joint_identity.read_bytes())
    obj = require_mapping("joint_partition_identity", decoded)
    return require_hex64(
        "joint_partition_identity.btc_dataset_fingerprint", obj.get("btc_dataset_fingerprint")
    )


def _time_facts(times: tuple[int, ...]) -> tuple[bool, bool]:
    """Return ``(no_row_at_or_after_cutoff, strict_monotonic_daily)`` for a derived open set."""
    if not times:
        return (False, False)
    no_after_cutoff = all(t < _EPOCH_SEAL and t <= _EPOCH_LAST for t in times)
    monotonic = all(
        times[i + 1] - times[i] == BTC_GRANULARITY_SECONDS for i in range(len(times) - 1)
    )
    return (no_after_cutoff, monotonic)


def _scan_workflows(paths: AuditPaths, problems: list[str]) -> bool:
    """Assert the acquisition workflow is retired. Returns whether the final tree is clean."""
    clean = True
    workflows_dir = paths.workflows_dir
    if workflows_dir.is_dir():
        for wf in sorted(workflows_dir.iterdir()):
            if wf.is_symlink():
                problems.append(f"workflow {wf.name} is a symlink")
                clean = False
                continue
            if not wf.is_file() or wf.suffix not in (".yml", ".yaml"):
                continue
            text = wf.read_text(encoding="utf-8", errors="replace")
            if _COINBASE_ENDPOINT_RE.search(text):
                problems.append(f"workflow {wf.name} still contacts the Coinbase endpoint")
                clean = False
            if _CONTENTS_WRITE_RE.search(text):
                problems.append(f"workflow {wf.name} grants contents: write (not retired)")
                clean = False
            if _IDTOKEN_WRITE_RE.search(text) or _PACKAGES_WRITE_RE.search(text):
                problems.append(f"workflow {wf.name} grants a write token (not retired)")
                clean = False
            if _WRITE_ALL_RE.search(text):
                problems.append(f"workflow {wf.name} grants write-all (acquisition not retired)")
                clean = False
            if "acquire" in wf.name.lower():
                problems.append(f"an acquisition workflow ({wf.name}) is still present")
                clean = False
    if paths.acquire_sentinel.exists():
        problems.append("the single-use acquisition sentinel is still present (not consumed)")
        clean = False
    return clean


def _check_governance_amendment(paths: AuditPaths, problems: list[str]) -> None:
    """The amendment must distinguish final-tree state from historical state, honestly."""
    doc = paths.acquisition_doc
    if not doc.is_file():
        problems.append("the acquisition governance amendment doc is missing")
        return
    low = doc.read_text(encoding="utf-8", errors="replace").lower()
    acknowledges_history = "temporary" in low and (
        "acquire" in low or "acquisition workflow" in low
    )
    acknowledges_retirement = "retire" in low or "removed" in low
    if not acknowledges_history:
        problems.append(
            "governance amendment does not acknowledge the historical acquisition workflow"
        )
    if not acknowledges_retirement:
        problems.append("governance amendment does not record the workflow's retirement")


def _audit(paths: AuditPaths) -> BtcAcquisitionAudit:
    """Run the whole audit against ``paths`` and collect every problem (never raises)."""
    problems: list[str] = []

    # (1) The committed BTC governance artifacts reproduce from the raw bundles. The dataset
    #     lock re-derives content_fingerprint + row_count from raw and binds the plan,
    #     manifest, quality report, and reacquisition audit by SHA-256, so one load anchors
    #     the whole btc/ artifact set; the immutable request plan is checked separately.
    try:
        if (paths.repo_root / ACQUISITION_PLAN_RELPATH).read_bytes() != build_plan_bytes():
            problems.append("committed acquisition_plan.json is not the immutable plan")
        committed_lock = (paths.repo_root / DATASET_LOCK_RELPATH).read_bytes()
        if committed_lock != canonical_json_bytes(build_dataset_lock(paths.repo_root)):
            problems.append("committed dataset_lock.json does not reproduce from the raw bundles")
    except (V2ValidationError, OSError) as exc:
        problems.append(f"committed BTC dataset artifacts do not reproduce from raw: {exc}")

    # (2) Independent re-derivation of both acquisitions from the raw candle bytes.
    derivations: dict[str, _Derivation] = {}
    for attempt_id in _ATTEMPT_IDS:
        try:
            derivations[attempt_id] = _derive_attempt(paths, attempt_id)
        except (V2ValidationError, OSError) as exc:
            problems.append(f"{attempt_id}: {exc}")

    genesis = derivations.get(GENESIS_ATTEMPT_ID)
    audit = derivations.get(AUDIT_ATTEMPT_ID)
    receipts_ok = genesis is not None and audit is not None

    # (3) The accepted external anchor + the committed joint fingerprint.
    try:
        committed_fp = _committed_btc_fingerprint(paths.joint_identity)
    except (V2ValidationError, OSError) as exc:
        committed_fp = ""
        problems.append(f"joint_partition_identity.json is unreadable: {exc}")
    if committed_fp and committed_fp != ACCEPTED_BTC_DATASET_FINGERPRINT:
        problems.append(
            "committed joint btc_dataset_fingerprint does not match the accepted anchor"
        )

    genesis_fp = genesis.fingerprint if genesis else ""
    audit_fp = audit.fingerprint if audit else ""
    no_after_cutoff = True
    monotonic = True
    row_count = 0
    first_open = ""
    last_open = ""

    for label, d in (("genesis", genesis), ("audit", audit)):
        if d is None:
            continue
        after_ok, mono_ok = _time_facts(d.times)
        no_after_cutoff = no_after_cutoff and after_ok
        monotonic = monotonic and mono_ok
        if len(d.times) != EXPECTED_ROW_COUNT:
            problems.append(
                f"{label}: derived {len(d.times)} daily rows, expected {EXPECTED_ROW_COUNT}"
            )
        if d.times and d.times[0] != _EPOCH_FIRST:
            problems.append(f"{label}: first open is not {_iso(_EPOCH_FIRST)}")
        if d.times and d.times[-1] != _EPOCH_LAST:
            problems.append(f"{label}: last open is not {_iso(_EPOCH_LAST)}")
        if not after_ok:
            problems.append(f"{label}: a candle lands at/after the research cutoff seal")
        if not mono_ok:
            problems.append(f"{label}: candles are not strict 86400-second daily steps")

    if genesis is not None:
        row_count = len(genesis.times)
        if genesis.times:
            first_open = _iso(genesis.times[0])
            last_open = _iso(genesis.times[-1])

    # (4) Independence: distinct run id + distinct source commit across the two attempts.
    distinct_runs = True
    distinct_commits = True
    if receipts_ok and genesis is not None and audit is not None:
        distinct_runs = genesis.receipt.workflow_run_id != audit.receipt.workflow_run_id
        distinct_commits = genesis.receipt.source_commit != audit.receipt.source_commit
        if not distinct_runs:
            problems.append("genesis and audit share a workflow_run_id (not independent)")
        if not distinct_commits:
            problems.append("genesis and audit share a source_commit (not independent)")

    # (5) Reproducibility: identical canonical candles == committed == accepted anchor.
    canonical_identical = False
    if receipts_ok and genesis is not None and audit is not None:
        canonical_identical = genesis_fp == audit_fp
        if not canonical_identical:
            problems.append("genesis and audit do not reproduce identical canonical candles")
        for label, fp in (("genesis", genesis_fp), ("audit", audit_fp)):
            if fp != ACCEPTED_BTC_DATASET_FINGERPRINT:
                problems.append(f"{label} canonical fingerprint != the accepted BTC dataset anchor")
            if committed_fp and fp != committed_fp:
                problems.append(f"{label} canonical fingerprint != the committed joint fingerprint")

    # (6) The acquisition workflow is retired, and the amendment is honest about history.
    final_tree_clean = _scan_workflows(paths, problems)
    _check_governance_amendment(paths, problems)
    historical_attested = receipts_ok and distinct_runs and distinct_commits

    return BtcAcquisitionAudit(
        attempt_ids=_ATTEMPT_IDS,
        row_count=row_count,
        first_open=first_open,
        last_open=last_open,
        genesis_fingerprint=genesis_fp,
        audit_fingerprint=audit_fp,
        committed_btc_dataset_fingerprint=committed_fp,
        accepted_btc_dataset_fingerprint=ACCEPTED_BTC_DATASET_FINGERPRINT,
        genesis_workflow_run_id=genesis.receipt.workflow_run_id if genesis else "",
        audit_workflow_run_id=audit.receipt.workflow_run_id if audit else "",
        genesis_source_commit=genesis.receipt.source_commit if genesis else "",
        audit_source_commit=audit.receipt.source_commit if audit else "",
        distinct_workflow_run_ids=distinct_runs,
        distinct_source_commits=distinct_commits,
        canonical_candles_identical=canonical_identical,
        no_row_at_or_after_cutoff=no_after_cutoff and receipts_ok,
        strict_monotonic_daily=monotonic and receipts_ok,
        receipts_self_consistent=receipts_ok,
        final_tree_acquisition_workflow_absent=final_tree_clean,
        historical_acquisition_attested=historical_attested,
        problems=tuple(problems),
    )


def audit_btc_acquisition(repo_root: str | Path) -> BtcAcquisitionAudit:
    """Independently re-derive + audit the BTC acquisition from the committed raw bytes."""
    return _audit(AuditPaths.for_repo(repo_root))


def verify_btc_acquisition(repo_root: str | Path) -> list[str]:
    """Return every BTC-acquisition acceptance problem (empty list == the acquisition is sound)."""
    return list(audit_btc_acquisition(repo_root).problems)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Independent V2B BTC-acquisition audit (offline).")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--check", action="store_true", help="Exit non-zero on any problem.")
    args = parser.parse_args(argv)
    problems = verify_btc_acquisition(args.repo_root)
    print(json.dumps({"ok": not problems, "problems": problems}))
    return 1 if problems and args.check else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ACCEPTED_BTC_DATASET_FINGERPRINT",
    "ACQUIRE_SENTINEL_RELPATH",
    "ACQUISITION_DOC_RELPATH",
    "EXPECTED_ROW_COUNT",
    "RAW_ROOT_RELPATH",
    "WORKFLOWS_RELPATH",
    "AcquisitionAuditError",
    "AuditPaths",
    "BtcAcquisitionAudit",
    "audit_btc_acquisition",
    "verify_btc_acquisition",
]
