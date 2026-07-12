"""Provenance-v2 graph: one authenticated chain over every dossier fact.

The dataset lock authenticates the *data* (content fingerprint, derived
file, and — via the acquisition evidence — a byte-exact raw→derived
re-derivation), but it does not authenticate the acquisition **receipt** or
the other provenance facts the dossier displays. So ``workflow_run_id``,
``source_commit``, ``curl_version``, ``runner``, ``user_agent``, and each
response's ``byte_length`` could be forged while every replay/lock check
stayed true (reproduced as ``FORGED_RECEIPT_ACCEPTED = True``).

This module closes that gap with an **additive** anchor —
``research/m2b/provenance_v2.json`` — that binds the SHA-256 of every
committed artifact plus a domain-separated raw-bundle fingerprint, and a
single :func:`verify_provenance_graph` that always runs the *complete*
chain: it re-hashes each artifact, re-derives the raw-bundle fingerprint
from the actual raw bytes (re-checking every file's length and hash so a
forged ``byte_length`` is caught), and cross-checks the plan, receipt,
evidence, manifest, quality report, lock, runtime contract, holdout
identity, discovery decision, and protocol against each other and against
the running package version. No existing schema changes; the anchor sits
alongside the artifacts it authenticates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_research import __version__
from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.acquisition_plan import (
    AcquisitionAttemptReceipt,
    load_acquisition_plan,
    load_acquisition_receipt,
    require_safe_json_filename,
)
from eth_research.data.coinbase import load_acquisition_evidence
from eth_research.data.lock import load_dataset_lock
from eth_research.data.provenance import (
    DatasetManifest,
    require_hex64,
    require_int,
    require_nonempty_str,
    sha256_file,
)
from eth_research.data.validation import require_fingerprint
from eth_research.discovery import load_discovery_decision
from eth_research.environment import load_runtime_contract
from eth_research.holdout import HoldoutIdentity
from eth_research.protocol import BenchmarkProtocol

PROVENANCE_SCHEMA_VERSION: int = 2

_RAW_BUNDLE_HEADER: bytes = b"eth-research raw-bundle-v1\n"
RAW_BUNDLE_AGGREGATE_CAP_BYTES: int = 10 * 1024 * 1024

_PROVENANCE_RELPATH: str = "research/m2b/provenance_v2.json"
_PLAN_RELPATH: str = "research/m2b/acquisition_request_plan.json"
_EVIDENCE_RELPATH: str = "research/m2b/acquisition_evidence.json"
_MANIFEST_RELPATH: str = "research/m2b/dataset_manifest.json"
_QUALITY_RELPATH: str = "research/m2b/quality_report.json"
_LOCK_RELPATH: str = "research/m2b/dataset_lock.json"
_RUNTIME_RELPATH: str = "research/m2b/runtime_contract.json"
_HOLDOUT_RELPATH: str = "research/m2b/holdout_identity.json"
_DISCOVERY_RELPATH: str = "research/m2b/discovery_decision.json"
_PROTOCOL_RELPATH: str = "research/m2b/protocol.json"

_PROVENANCE_KEYS: frozenset[str] = frozenset(
    {
        "provenance_schema_version",
        "package_version",
        "selected_attempt_id",
        "dataset_content_fingerprint",
        "acquisition_request_plan_sha256",
        "acquisition_receipt_sha256",
        "acquisition_evidence_sha256",
        "raw_bundle_fingerprint",
        "dataset_manifest_sha256",
        "quality_report_sha256",
        "dataset_lock_sha256",
        "runtime_contract_sha256",
        "holdout_identity_sha256",
        "discovery_decision_sha256",
        "protocol_sha256",
    }
)


class ProvenanceV2Error(RuntimeError):
    """The provenance graph is invalid or an artifact disagrees with it."""


def raw_bundle_fingerprint(receipt: AcquisitionAttemptReceipt, attempt_dir: str | Path) -> str:
    """Domain-separated fingerprint of the exact raw response files.

    Over canonical ordered ``ordinal|filename|byte_length|raw_sha256``
    records, re-checking every file's actual length and hash so a forged
    ``byte_length`` (or a swapped body) is caught. Ordinals must be exactly
    ``0..N-1``, filenames unique and safe, no symlinks, and the aggregate
    must stay under the raw cap.
    """
    directory = Path(attempt_dir)
    responses = sorted(receipt.responses, key=lambda response: response.ordinal)
    if [response.ordinal for response in responses] != list(range(len(responses))):
        raise ProvenanceV2Error("receipt ordinals must be contiguous 0..N-1")
    if len({response.filename for response in responses}) != len(responses):
        raise ProvenanceV2Error("receipt filenames must be unique")
    hasher = hashlib.sha256()
    hasher.update(_RAW_BUNDLE_HEADER)
    aggregate = 0
    for response in responses:
        require_safe_json_filename("raw filename", response.filename)
        path = directory / response.filename
        if path.is_symlink():
            raise ProvenanceV2Error(f"raw body {response.filename} must not be a symlink")
        if not path.is_file():
            raise ProvenanceV2Error(f"raw body {response.filename} is missing")
        actual_length = path.stat().st_size
        if actual_length != response.byte_length:
            raise ProvenanceV2Error(
                f"raw body {response.filename} length {actual_length} != receipt "
                f"byte_length {response.byte_length}"
            )
        actual_sha = sha256_file(path)
        if actual_sha != response.sha256:
            raise ProvenanceV2Error(
                f"raw body {response.filename} SHA-256 does not match the receipt"
            )
        aggregate += actual_length
        if aggregate > RAW_BUNDLE_AGGREGATE_CAP_BYTES:
            raise ProvenanceV2Error("raw bundle exceeds the aggregate byte cap")
        hasher.update(
            f"{response.ordinal}|{response.filename}|{response.byte_length}|{response.sha256}\n".encode(
                "ascii"
            )
        )
    return "sha256:" + hasher.hexdigest()


@dataclass(frozen=True)
class ProvenanceV2:
    """Strict anchor binding the SHA-256 of every committed provenance artifact."""

    provenance_schema_version: int
    package_version: str
    selected_attempt_id: str
    dataset_content_fingerprint: str
    acquisition_request_plan_sha256: str
    acquisition_receipt_sha256: str
    acquisition_evidence_sha256: str
    raw_bundle_fingerprint: str
    dataset_manifest_sha256: str
    quality_report_sha256: str
    dataset_lock_sha256: str
    runtime_contract_sha256: str
    holdout_identity_sha256: str
    discovery_decision_sha256: str
    protocol_sha256: str

    def __post_init__(self) -> None:
        version = require_int("provenance_schema_version", self.provenance_schema_version)
        if version != PROVENANCE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported provenance schema version {version!r}; "
                f"this package reads version {PROVENANCE_SCHEMA_VERSION}"
            )
        require_nonempty_str("package_version", self.package_version)
        require_nonempty_str("selected_attempt_id", self.selected_attempt_id)
        require_fingerprint("dataset_content_fingerprint", self.dataset_content_fingerprint)
        require_fingerprint("raw_bundle_fingerprint", self.raw_bundle_fingerprint)
        for label in (
            "acquisition_request_plan_sha256",
            "acquisition_receipt_sha256",
            "acquisition_evidence_sha256",
            "dataset_manifest_sha256",
            "quality_report_sha256",
            "dataset_lock_sha256",
            "runtime_contract_sha256",
            "holdout_identity_sha256",
            "discovery_decision_sha256",
            "protocol_sha256",
        ):
            require_hex64(label, getattr(self, label))

    def to_json_bytes(self) -> bytes:
        """Deterministic serialization: sorted keys, indent 2, trailing newline."""
        payload = {
            "provenance_schema_version": self.provenance_schema_version,
            "package_version": self.package_version,
            "selected_attempt_id": self.selected_attempt_id,
            "dataset_content_fingerprint": self.dataset_content_fingerprint,
            "acquisition_request_plan_sha256": self.acquisition_request_plan_sha256,
            "acquisition_receipt_sha256": self.acquisition_receipt_sha256,
            "acquisition_evidence_sha256": self.acquisition_evidence_sha256,
            "raw_bundle_fingerprint": self.raw_bundle_fingerprint,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "quality_report_sha256": self.quality_report_sha256,
            "dataset_lock_sha256": self.dataset_lock_sha256,
            "runtime_contract_sha256": self.runtime_contract_sha256,
            "holdout_identity_sha256": self.holdout_identity_sha256,
            "discovery_decision_sha256": self.discovery_decision_sha256,
            "protocol_sha256": self.protocol_sha256,
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> ProvenanceV2:
        """Strict parse feeding the shared constructor validation."""
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"provenance graph is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("provenance graph JSON must be an object")
        keys = set(payload)
        if keys != _PROVENANCE_KEYS:
            unknown = sorted(keys - _PROVENANCE_KEYS)
            missing = sorted(_PROVENANCE_KEYS - keys)
            raise ValueError(
                f"provenance graph keys do not match schema: unknown={unknown}, missing={missing}"
            )
        return cls(**{key: payload[key] for key in _PROVENANCE_KEYS})


def _real_attempt_dir(repo_root: Path) -> Path:
    base = repo_root / "research" / "m2b" / "raw" / "coinbase"
    attempts = [p for p in base.iterdir() if p.is_dir() and p.name != "discovery-001"]
    canonical = [p for p in attempts if p.name == "coinbase-eth-usd-001"]
    if len(canonical) != 1:
        raise ProvenanceV2Error(f"expected the canonical attempt directory, found {attempts}")
    return canonical[0]


def build_provenance_v2(repo_root: str | Path) -> ProvenanceV2:
    """Compute the provenance anchor from the committed artifacts."""
    root = Path(repo_root)
    attempt = _real_attempt_dir(root)
    receipt = load_acquisition_receipt(attempt / "acquisition_receipt.json")
    manifest = DatasetManifest.from_json_bytes((root / _MANIFEST_RELPATH).read_bytes())
    return ProvenanceV2(
        provenance_schema_version=PROVENANCE_SCHEMA_VERSION,
        package_version=__version__,
        selected_attempt_id=receipt.attempt_id,
        dataset_content_fingerprint=manifest.content_fingerprint,
        acquisition_request_plan_sha256=sha256_file(root / _PLAN_RELPATH),
        acquisition_receipt_sha256=sha256_file(attempt / "acquisition_receipt.json"),
        acquisition_evidence_sha256=sha256_file(root / _EVIDENCE_RELPATH),
        raw_bundle_fingerprint=raw_bundle_fingerprint(receipt, attempt),
        dataset_manifest_sha256=sha256_file(root / _MANIFEST_RELPATH),
        quality_report_sha256=sha256_file(root / _QUALITY_RELPATH),
        dataset_lock_sha256=sha256_file(root / _LOCK_RELPATH),
        runtime_contract_sha256=sha256_file(root / _RUNTIME_RELPATH),
        holdout_identity_sha256=sha256_file(root / _HOLDOUT_RELPATH),
        discovery_decision_sha256=sha256_file(root / _DISCOVERY_RELPATH),
        protocol_sha256=sha256_file(root / _PROTOCOL_RELPATH),
    )


@dataclass(frozen=True)
class ProvenanceGraphResult:
    """Structured outcome of the complete provenance-graph verification."""

    ok: bool
    checks: tuple[str, ...]
    errors: tuple[str, ...]

    def raise_for_status(self) -> None:
        if not self.ok:
            raise ProvenanceV2Error(
                "provenance graph verification failed: " + "; ".join(self.errors)
            )


def verify_provenance_graph(repo_root: str | Path) -> ProvenanceGraphResult:
    """Run the complete provenance chain and return a structured result.

    Re-hashes every committed artifact against the anchor, re-derives the
    raw-bundle fingerprint from the actual raw bytes, and cross-checks the
    plan/receipt/evidence/manifest/lock/runtime/holdout/discovery/protocol
    against each other and the running package version. Never a set of
    silently-optional partial checks: every equality is recorded and any
    failure sets ``ok = False``.
    """
    root = Path(repo_root)
    checks: list[str] = []
    errors: list[str] = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append(name)
        if not condition:
            errors.append(f"{name}: {detail}")

    anchor = ProvenanceV2.from_json_bytes((root / _PROVENANCE_RELPATH).read_bytes())
    attempt = _real_attempt_dir(root)
    receipt = load_acquisition_receipt(attempt / "acquisition_receipt.json")
    plan = load_acquisition_plan(root / _PLAN_RELPATH)
    evidence = load_acquisition_evidence(root / _EVIDENCE_RELPATH)
    manifest = DatasetManifest.from_json_bytes((root / _MANIFEST_RELPATH).read_bytes())
    lock = load_dataset_lock(root / _LOCK_RELPATH)
    runtime = load_runtime_contract(root / _RUNTIME_RELPATH)
    holdout = HoldoutIdentity.from_json_bytes((root / _HOLDOUT_RELPATH).read_bytes())
    discovery = load_discovery_decision(root / _DISCOVERY_RELPATH)
    protocol = BenchmarkProtocol.from_json_bytes((root / _PROTOCOL_RELPATH).read_bytes())

    # --- artifact bytes hash to the anchor ---
    hashed = {
        "acquisition_request_plan_sha256": sha256_file(root / _PLAN_RELPATH),
        "acquisition_receipt_sha256": sha256_file(attempt / "acquisition_receipt.json"),
        "acquisition_evidence_sha256": sha256_file(root / _EVIDENCE_RELPATH),
        "dataset_manifest_sha256": sha256_file(root / _MANIFEST_RELPATH),
        "quality_report_sha256": sha256_file(root / _QUALITY_RELPATH),
        "dataset_lock_sha256": sha256_file(root / _LOCK_RELPATH),
        "runtime_contract_sha256": sha256_file(root / _RUNTIME_RELPATH),
        "holdout_identity_sha256": sha256_file(root / _HOLDOUT_RELPATH),
        "discovery_decision_sha256": sha256_file(root / _DISCOVERY_RELPATH),
        "protocol_sha256": sha256_file(root / _PROTOCOL_RELPATH),
    }
    for field, actual in hashed.items():
        check(f"anchor:{field}", getattr(anchor, field) == actual, "artifact bytes changed")

    # --- raw bundle re-derived from the actual bytes (catches forged length) ---
    try:
        actual_bundle = raw_bundle_fingerprint(receipt, attempt)
        check("raw_bundle_fingerprint", actual_bundle == anchor.raw_bundle_fingerprint, "mismatch")
    except ProvenanceV2Error as exc:
        check("raw_bundle_fingerprint", False, str(exc))

    # --- receipt / plan cross-checks (C6) ---
    check("receipt_plan_sha", receipt.plan_sha256 == plan.plan_sha256(), "receipt cites wrong plan")
    check(
        "plan_user_agent",
        receipt.user_agent == plan.user_agent,
        "receipt user-agent != plan user-agent",
    )
    check(
        "response_count",
        len(receipt.responses) == len(plan.windows),
        "receipt response count != plan window count",
    )
    windows = {window.ordinal: window for window in plan.windows}
    ordinals_ok = True
    for response in receipt.responses:
        window = windows.get(response.ordinal)
        if window is None or window.filename != response.filename:
            ordinals_ok = False
    check("response_windows", ordinals_ok, "a receipt response has no matching plan window")

    # --- identity / selection cross-checks ---
    check(
        "selected_attempt",
        receipt.attempt_id == anchor.selected_attempt_id,
        "receipt attempt id != anchor selected attempt",
    )
    check(
        "dataset_fingerprint",
        manifest.content_fingerprint
        == anchor.dataset_content_fingerprint
        == lock.content_fingerprint
        == protocol.dataset_content_fingerprint
        == holdout.dataset_content_fingerprint,
        "content fingerprint disagrees across artifacts",
    )
    check(
        "evidence_derived",
        evidence.derived_sha256 == manifest.raw_file_sha256,
        "evidence derived SHA != manifest raw file SHA",
    )
    check(
        "lock_manifest",
        lock.manifest_sha256 == anchor.dataset_manifest_sha256,
        "lock manifest SHA != anchor",
    )
    check(
        "lock_quality",
        lock.quality_report_sha256 == anchor.quality_report_sha256,
        "lock quality SHA != anchor",
    )
    check(
        "protocol_lock",
        protocol.dataset_lock_sha256 == anchor.dataset_lock_sha256,
        "protocol lock SHA != anchor",
    )
    check(
        "discovery_start",
        discovery.chosen_start == manifest.first_open_time,
        "discovery chosen start != dataset first open",
    )
    check(
        "holdout_last_open",
        holdout.test_last_open_time == manifest.last_open_time,
        "holdout test end != dataset last open",
    )

    # --- version chain (C6) ---
    versions = {
        "plan": plan.package_version,
        "receipt": receipt.package_version,
        "evidence": evidence.package_version,
        "manifest": manifest.package_version,
        "lock": lock.package_version,
        "runtime": runtime.package_version,
        "protocol": protocol.package_version,
        "anchor": anchor.package_version,
        "running": __version__,
    }
    check(
        "version_chain",
        len(set(versions.values())) == 1,
        f"package versions disagree: {versions}",
    )

    return ProvenanceGraphResult(ok=not errors, checks=tuple(checks), errors=tuple(errors))


def load_provenance_v2(path: str | Path) -> ProvenanceV2:
    """Strictly parse a provenance-graph file."""
    file = Path(path)
    try:
        return ProvenanceV2.from_json_bytes(file.read_bytes())
    except ValueError as exc:
        raise ProvenanceV2Error(f"invalid provenance graph {file.name!r}: {exc}") from exc
