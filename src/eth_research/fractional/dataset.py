"""Integrity-only research-train loader for the Milestone 3B fractional lab.

M3B loads the research-train partition through byte / hash / fingerprint / bound
verification **only**. Unlike the Milestone 2B dossier verifier
(:func:`eth_research.dossier.verify_frozen_dossier`) and the Milestone 3A
partition builder (:func:`eth_research.development.build_development_partition`),
this path never re-runs the M2B train/validation benchmark — the disclosed M3A
``4.1-1`` behaviour that pushes the M2 validation segment (which *is* the
development gate) through the engine — and never calls any strategy, execution
engine, cost model, risk overlay, liquidity estimator, metric, bootstrap, or
report while verifying.

:func:`verify_dataset_integrity_only` reconstructs the derived + canonical
dataset from the committed raw bytes (a pure data transform), binds every
committed dataset-provenance artifact to the frozen M2B dossier's recorded
anchors, cross-checks the lock ↔ manifest ↔ evidence chain, mechanically
re-derives the three-level M3A partition with the engine-free
:func:`eth_research.development.derive_development_partition`, and hands back the
**research-train rows only** (2016-05-23 .. 2022-06-21 UTC, 2221 daily rows).

Sealed development-gate and final-holdout rows never reach a computational
surface: only their opaque integrity fingerprints, counts, and time bounds are
inspected while deriving the partition, and they are never returned.

Version safety mirrors the frozen dossier: when the running package version
differs from the dossier's recorded version (``snapshot`` mode) the two root
lockfiles (``uv.lock`` / ``pyproject.toml``) have legitimately advanced and are
*not* re-hashed here (they are byte-pinned via git in replay/hygiene); every
frozen data artifact is still bound, and the committed version chain must be
internally consistent.

Failures raise :class:`DatasetIntegrityError` for a violated dossier anchor /
fingerprint / bound / partition-recompute, and propagate the underlying
verifier's own exception (``AcquisitionError``, ``LockError``, ``ProtocolError``,
``DevelopmentAccessError``) for a failed re-derivation or a forbidden-row guard,
so every attack fails for its own explicit reason.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from eth_research import __version__
from eth_research.data.acquisition_plan import load_acquisition_plan, load_acquisition_receipt
from eth_research.data.builder import load_canonical_dataset
from eth_research.data.coinbase import load_acquisition_evidence
from eth_research.data.lock import load_dataset_lock, verify_dataset_lock
from eth_research.data.provenance import DatasetManifest, sha256_file
from eth_research.development import (
    DEVELOPMENT_PARTITION_RELPATH,
    FROZEN_M2_DOSSIER_RELPATH,
    DevelopmentDataset,
    DevelopmentPartition,
    derive_development_partition,
    load_development_partition,
)
from eth_research.dossier import (
    CANONICAL_ATTEMPT_ID,
    FrozenResearchDossier,
    load_frozen_dossier,
    raw_bundle_fingerprint,
)
from eth_research.protocol import load_benchmark_protocol, verify_protocol
from eth_research.replay_m2b import (
    EVIDENCE_RELPATH,
    LOCK_RELPATH,
    PLAN_RELPATH,
    PROTOCOL_RELPATH,
    RAW_ROOT_RELPATH,
    reconstruct_dataset,
)

RESEARCH_DIR_RELPATH: str = "research/m2b"
MANIFEST_RELPATH: str = "research/m2b/dataset_manifest.json"
QUALITY_RELPATH: str = "research/m2b/quality_report.json"
RECEIPT_NAME: str = "acquisition_receipt.json"


class DatasetIntegrityError(Exception):
    """An integrity-only research-train load failed a hash / bound / derivation check."""


@dataclass(frozen=True)
class DatasetIntegrityResult:
    """Outcome of a successful integrity-only research-train load.

    Carries the research-train :class:`DevelopmentDataset` (frame + committed
    partition), the frozen M2B dossier whose anchors were bound, the committed
    three-level partition, and the ordered list of passed integrity checks.
    """

    dataset: DevelopmentDataset
    dossier: FrozenResearchDossier
    partition: DevelopmentPartition
    checks: tuple[str, ...]

    @property
    def research_train(self) -> pd.DataFrame:
        """The research-train rows only (never a gate or holdout row)."""
        return self.dataset.frame

    @property
    def research_train_last_open_time(self) -> pd.Timestamp:
        """The immutable research-train boundary (2022-06-21 UTC)."""
        return self.dataset.research_train_last_open_time


def _require(condition: bool, label: str, detail: str) -> None:
    if not condition:
        raise DatasetIntegrityError(f"{label}: {detail}")


def verify_dataset_integrity_only(
    repo_root: str | Path, *, work_dir: str | Path | None = None
) -> DatasetIntegrityResult:
    """Verify dataset integrity and return the research-train rows only.

    Reconstructs and binds the committed dataset to the frozen M2B dossier and
    mechanically re-derives the M3A partition — **without** re-running the M2B
    benchmark or calling any strategy / engine / metric / bootstrap / report.
    ``work_dir`` (default: a private temporary directory) receives the
    reconstructed derived CSV and canonical Parquet; it is never a tracked path.
    """
    root = Path(repo_root)
    if work_dir is None:
        with tempfile.TemporaryDirectory() as tmp:
            return _verify(root, Path(tmp))
    return _verify(root, Path(work_dir))


def _verify(root: Path, work: Path) -> DatasetIntegrityResult:
    checks: list[str] = []
    raw_dir = root / RAW_ROOT_RELPATH / CANONICAL_ATTEMPT_ID

    # The committed frozen M2B dossier is the anchor source of truth.
    dossier = load_frozen_dossier(root / FROZEN_M2_DOSSIER_RELPATH)
    snapshot = dossier.package_version != __version__
    checks.append("snapshot_mode" if snapshot else "live_mode")

    # 1. Reconstruct derived + canonical dataset from the committed raw bytes.
    #    reconstruct_dataset re-hashes every raw body against the receipt,
    #    re-derives the CSV, and runs the semantic acquisition verification —
    #    a pure data transform that never touches the engine.
    recon = reconstruct_dataset(root, CANONICAL_ATTEMPT_ID, work)
    checks.append("raw_to_derived_reconstructed")

    dataset = load_canonical_dataset(recon.build.manifest_path)
    checks.append("canonical_ohlcv_revalidated")

    # 2. Bind every committed dataset-provenance artifact to its dossier anchor.
    anchors: dict[str, tuple[Path, str]] = {
        "acquisition_request_plan": (
            root / PLAN_RELPATH,
            dossier.acquisition_request_plan_sha256,
        ),
        "acquisition_receipt": (raw_dir / RECEIPT_NAME, dossier.acquisition_receipt_sha256),
        "acquisition_evidence": (root / EVIDENCE_RELPATH, dossier.acquisition_evidence_sha256),
        "dataset_manifest": (root / MANIFEST_RELPATH, dossier.dataset_manifest_sha256),
        "quality_report": (root / QUALITY_RELPATH, dossier.quality_report_sha256),
        "dataset_lock": (root / LOCK_RELPATH, dossier.dataset_lock_sha256),
        "protocol": (root / PROTOCOL_RELPATH, dossier.protocol_sha256),
    }
    for name, (path, expected) in anchors.items():
        _require(
            sha256_file(path) == expected,
            f"anchor:{name}",
            f"committed {path.name} does not hash to the frozen dossier anchor",
        )
        checks.append(f"anchor:{name}")

    # Raw response bytes re-fingerprint to the dossier anchor.
    primary_receipt = load_acquisition_receipt(raw_dir / RECEIPT_NAME)
    _require(
        raw_bundle_fingerprint(primary_receipt, raw_dir) == dossier.raw_bundle_fingerprint,
        "anchor:raw_bundle_fingerprint",
        "reconstructed raw bundle fingerprint disagrees with the frozen dossier",
    )
    checks.append("anchor:raw_bundle_fingerprint")

    # The reconstructed dataset's opaque content fingerprint and derived CSV
    # digest bind to the dossier (the fingerprint is toolchain-independent).
    _require(
        dataset.manifest.content_fingerprint == dossier.dataset_content_fingerprint,
        "anchor:dataset_content_fingerprint",
        "reconstructed content fingerprint disagrees with the frozen dossier",
    )
    checks.append("anchor:dataset_content_fingerprint")
    _require(
        recon.evidence.derived_sha256 == dossier.derived_csv_sha256,
        "anchor:derived_csv",
        "reconstructed derived CSV digest disagrees with the frozen dossier",
    )
    checks.append("anchor:derived_csv")

    # 3. Cross-check the lock ↔ manifest ↔ evidence chain and re-derive raw→
    #    derived once more through the lock (all engine-free).
    lock = load_dataset_lock(root / LOCK_RELPATH)
    verify_dataset_lock(
        lock,
        manifest_path=root / MANIFEST_RELPATH,
        acquisition_evidence_path=root / EVIDENCE_RELPATH,
        raw_chunk_dir=raw_dir,
        derived_csv=recon.derived_csv,
    )
    checks.append("dataset_lock_chain")

    protocol = load_benchmark_protocol(root / PROTOCOL_RELPATH)
    verify_protocol(protocol, lock)
    checks.append("protocol_verified")

    # 4. One version chain over the committed data artifacts (mirrors the frozen
    #    dossier's discipline). Every committed artifact reports the dossier's
    #    recorded version; the running interpreter is included only in live mode.
    committed_manifest = DatasetManifest.from_json_bytes((root / MANIFEST_RELPATH).read_bytes())
    evidence = load_acquisition_evidence(root / EVIDENCE_RELPATH)
    plan = load_acquisition_plan(root / PLAN_RELPATH)
    versions = {
        plan.package_version,
        primary_receipt.package_version,
        evidence.package_version,
        committed_manifest.package_version,
        lock.package_version,
        protocol.package_version,
        dossier.package_version,
    }
    if not snapshot:
        versions.add(__version__)
    _require(
        versions == {dossier.package_version},
        "version_chain",
        f"committed package versions disagree: {sorted(versions)} "
        f"(expected {dossier.package_version!r})",
    )
    checks.append("version_chain")

    # 5. Mechanically re-derive the three-level M3A partition (engine-free twin
    #    of build_development_partition) and require the committed bytes.
    committed_partition = load_development_partition(root / DEVELOPMENT_PARTITION_RELPATH)
    dossier_sha = sha256_file(root / FROZEN_M2_DOSSIER_RELPATH)
    recomputed = derive_development_partition(
        dataset,
        protocol,
        frozen_m2_dossier_sha256=dossier_sha,
        package_version=committed_partition.package_version,
    )
    _require(
        recomputed.to_json_bytes() == committed_partition.to_json_bytes(),
        "partition_recomputed",
        "the committed development partition does not recompute from the verified M2 dataset",
    )
    checks.append("partition_recomputed")
    _require(
        committed_partition.frozen_m2_dossier_sha256 == dossier_sha,
        "partition_binds_dossier",
        "the committed partition does not bind the committed frozen M2B dossier",
    )
    checks.append("partition_binds_dossier")

    # 6. Expose the research-train rows ONLY. The DevelopmentDataset guard
    #    re-validates OHLCV, rejects any forbidden row, and re-checks the
    #    research-train fingerprint; a gate or holdout row is never returned.
    boundary = committed_partition.research_train.last_open_time
    research_train = dataset.frame.loc[dataset.frame.index <= boundary].copy()
    dev_dataset = DevelopmentDataset(frame=research_train, partition=committed_partition)
    checks.append("research_train_exposed")

    return DatasetIntegrityResult(
        dataset=dev_dataset,
        dossier=dossier,
        partition=committed_partition,
        checks=tuple(checks),
    )
