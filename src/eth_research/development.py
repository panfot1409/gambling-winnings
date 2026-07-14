"""The Milestone 3A development data firewall.

Three immutable, contiguous, non-overlapping access levels partition the
frozen Milestone 2B dataset. The M2 chronological 60/20/20 split derives
them exactly:

* **research train** — the M2 *train* segment (2221 rows,
  2016-05-23 .. 2022-06-21 UTC). The only partition M3A may evaluate.
* **development gate** — the M2 *validation* segment (740 rows,
  2022-06-22 .. 2024-06-30 UTC). Forbidden in M3A; spent later through a
  separate pre-registered append-only process.
* **final holdout** — the M2 *test* segment (741 rows,
  2024-07-01 .. 2026-07-11 UTC). Absolutely forbidden.

The firewall hands the downstream **M3A walk-forward** the research-train
rows **only**. It never passes the full dataset and trusts callers to slice:
every frame and every warm-up context handed to an M3A strategy or the M3A
backtest engine is checked, and a single row on or after 2022-06-22 — or a
gap, duplicate, shuffle, or fingerprint mismatch — is *rejected*, never
silently truncated. There is no arbitrary date-range or ``segment="test"``
escape hatch, so no forbidden market value ever reaches an M3A walk-forward
strategy, fold, bootstrap, report, or the engine driven by
:func:`evaluate_development`.

One integrity re-derivation is disclosed for precision. Loading the dataset
first re-verifies the frozen M2B dossier, which recomputes M2B's *already
published* train+validation benchmark to prove it reproduces byte-for-byte
(see :func:`build_development_partition`). By construction that re-simulation
runs the M2 *validation* segment — which is the M3A development gate
(2022-06-22 .. 2024-06-30) — through the engine. It re-derives public M2B
numbers that are hash-compared and discarded, records **no** development-gate
access-ledger event, reveals nothing new to M3A development, and **never**
touches the final holdout (>= 2024-07-01). The research-train frame M3A
actually evaluates is sliced (``index <= 2022-06-21``), re-guarded, and
fingerprint-checked independently of that check. Permitted operations on the
forbidden partitions are otherwise integrity-only (schema validation,
mechanical splitting, counts, bounds, opaque content fingerprints).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research import __version__
from eth_research._json import StrictJSONError, strict_json_loads
from eth_research.data.builder import LoadedDataset, load_canonical_dataset
from eth_research.data.provenance import (
    content_fingerprint,
    require_hex64,
    require_int,
    require_nonempty_str,
    require_str,
    sha256_file,
)
from eth_research.data.schema import OHLCV_COLUMNS, validate_ohlcv
from eth_research.data.validation import (
    require_fingerprint,
    require_positive_int,
    require_utc_timestamp,
)
from eth_research.protocol import BenchmarkProtocol
from eth_research.splits import chronological_split

PARTITION_SCHEMA_VERSION: int = 1
DEVELOPMENT_PARTITION_RELPATH: str = "research/m3a/development_partition.json"
FROZEN_M2_DOSSIER_RELPATH: str = "research/m2b/frozen_dossier.json"

RESEARCH_TRAIN: str = "research_train"
DEVELOPMENT_GATE: str = "development_gate"
FINAL_HOLDOUT: str = "final_holdout"
_PARTITION_NAMES: tuple[str, ...] = (RESEARCH_TRAIN, DEVELOPMENT_GATE, FINAL_HOLDOUT)

SPLIT_SEMANTICS: str = "m2b-chronological-60-20-20-positional-floor"

_SUMMARY_KEYS: frozenset[str] = frozenset(
    {"name", "content_fingerprint", "row_count", "first_open_time", "last_open_time"}
)
_PARTITION_KEYS: frozenset[str] = frozenset(
    {
        "partition_schema_version",
        "package_version",
        "frozen_m2_dossier_sha256",
        "split_semantics",
        "dataset_content_fingerprint",
        "dataset_row_count",
        "dataset_first_open_time",
        "dataset_last_open_time",
        "partitions",
    }
)


class DevelopmentAccessError(RuntimeError):
    """A forbidden partition row (or a malformed frame) reached the firewall."""


@dataclass(frozen=True)
class PartitionSummary:
    """Opaque integrity summary of one partition — never any market value."""

    name: str
    content_fingerprint: str
    row_count: int
    first_open_time: pd.Timestamp
    last_open_time: pd.Timestamp

    def __post_init__(self) -> None:
        if self.name not in _PARTITION_NAMES:
            raise ValueError(f"name must be one of {_PARTITION_NAMES}, got {self.name!r}")
        require_fingerprint("content_fingerprint", self.content_fingerprint)
        require_positive_int("row_count", self.row_count)
        require_utc_timestamp("first_open_time", self.first_open_time)
        require_utc_timestamp("last_open_time", self.last_open_time)
        if self.first_open_time > self.last_open_time:
            raise ValueError("first_open_time must not be after last_open_time")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content_fingerprint": self.content_fingerprint,
            "row_count": self.row_count,
            "first_open_time": self.first_open_time.isoformat(),
            "last_open_time": self.last_open_time.isoformat(),
        }

    @classmethod
    def from_json_dict(cls, payload: Any) -> PartitionSummary:
        if not isinstance(payload, dict):
            raise ValueError("partition summary must be an object")
        keys = set(payload)
        if keys != _SUMMARY_KEYS:
            unknown = sorted(keys - _SUMMARY_KEYS)
            missing = sorted(_SUMMARY_KEYS - keys)
            raise ValueError(
                f"partition summary keys do not match: unknown={unknown}, missing={missing}"
            )
        return cls(
            name=require_str("name", payload["name"]),
            content_fingerprint=payload["content_fingerprint"],
            row_count=require_int("row_count", payload["row_count"]),
            first_open_time=_parse_ts("first_open_time", payload["first_open_time"]),
            last_open_time=_parse_ts("last_open_time", payload["last_open_time"]),
        )


def _parse_ts(label: str, value: object) -> pd.Timestamp:
    text = require_str(label, value)
    try:
        ts = pd.Timestamp(text)
    except ValueError as exc:
        raise ValueError(f"{label} is unparseable: {text!r}") from exc
    return require_utc_timestamp(label, ts)


@dataclass(frozen=True)
class DevelopmentPartition:
    """Strict, byte-reproducible manifest of the three-level access model."""

    partition_schema_version: int
    package_version: str
    frozen_m2_dossier_sha256: str
    split_semantics: str
    dataset_content_fingerprint: str
    dataset_row_count: int
    dataset_first_open_time: pd.Timestamp
    dataset_last_open_time: pd.Timestamp
    partitions: tuple[PartitionSummary, ...]

    def __post_init__(self) -> None:
        version = require_int("partition_schema_version", self.partition_schema_version)
        if version != PARTITION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported partition schema version {version!r}; this package reads "
                f"{PARTITION_SCHEMA_VERSION}"
            )
        require_nonempty_str("package_version", self.package_version)
        require_hex64("frozen_m2_dossier_sha256", self.frozen_m2_dossier_sha256)
        if self.split_semantics != SPLIT_SEMANTICS:
            raise ValueError(f"split_semantics is pinned to {SPLIT_SEMANTICS!r}")
        require_fingerprint("dataset_content_fingerprint", self.dataset_content_fingerprint)
        require_positive_int("dataset_row_count", self.dataset_row_count)
        require_utc_timestamp("dataset_first_open_time", self.dataset_first_open_time)
        require_utc_timestamp("dataset_last_open_time", self.dataset_last_open_time)
        names = tuple(summary.name for summary in self.partitions)
        if names != _PARTITION_NAMES:
            raise ValueError(f"partitions must be exactly {_PARTITION_NAMES} in order, got {names}")
        total = sum(summary.row_count for summary in self.partitions)
        if total != self.dataset_row_count:
            raise ValueError(
                f"partition rows {total} do not sum to dataset rows {self.dataset_row_count}"
            )
        # Contiguity: each partition begins one bar after the previous ends,
        # with no overlap or gap, and the union spans the whole dataset.
        first = self.partitions[0]
        last = self.partitions[-1]
        if first.first_open_time != self.dataset_first_open_time:
            raise ValueError("first partition must start at the dataset start")
        if last.last_open_time != self.dataset_last_open_time:
            raise ValueError("last partition must end at the dataset end")

    @property
    def research_train(self) -> PartitionSummary:
        return self.partitions[0]

    @property
    def development_gate(self) -> PartitionSummary:
        return self.partitions[1]

    @property
    def final_holdout(self) -> PartitionSummary:
        return self.partitions[2]

    def to_json_bytes(self) -> bytes:
        payload = {
            "partition_schema_version": self.partition_schema_version,
            "package_version": self.package_version,
            "frozen_m2_dossier_sha256": self.frozen_m2_dossier_sha256,
            "split_semantics": self.split_semantics,
            "dataset_content_fingerprint": self.dataset_content_fingerprint,
            "dataset_row_count": self.dataset_row_count,
            "dataset_first_open_time": self.dataset_first_open_time.isoformat(),
            "dataset_last_open_time": self.dataset_last_open_time.isoformat(),
            "partitions": [summary.to_json_dict() for summary in self.partitions],
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> DevelopmentPartition:
        try:
            payload: Any = strict_json_loads(raw)
        except StrictJSONError as exc:
            raise ValueError(f"development partition is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("development partition JSON must be an object")
        keys = set(payload)
        if keys != _PARTITION_KEYS:
            unknown = sorted(keys - _PARTITION_KEYS)
            missing = sorted(_PARTITION_KEYS - keys)
            raise ValueError(
                f"development partition keys do not match: unknown={unknown}, missing={missing}"
            )
        raw_partitions = payload["partitions"]
        if not isinstance(raw_partitions, list):
            raise ValueError("partitions must be a list")
        return cls(
            partition_schema_version=require_int(
                "partition_schema_version", payload["partition_schema_version"]
            ),
            package_version=require_str("package_version", payload["package_version"]),
            frozen_m2_dossier_sha256=payload["frozen_m2_dossier_sha256"],
            split_semantics=require_str("split_semantics", payload["split_semantics"]),
            dataset_content_fingerprint=payload["dataset_content_fingerprint"],
            dataset_row_count=require_int("dataset_row_count", payload["dataset_row_count"]),
            dataset_first_open_time=_parse_ts(
                "dataset_first_open_time", payload["dataset_first_open_time"]
            ),
            dataset_last_open_time=_parse_ts(
                "dataset_last_open_time", payload["dataset_last_open_time"]
            ),
            partitions=tuple(PartitionSummary.from_json_dict(item) for item in raw_partitions),
        )


@dataclass(frozen=True)
class DevelopmentDataset:
    """The research-train rows handed downstream — never a forbidden row.

    Constructed only by :func:`load_development_dataset`, which verifies the
    frozen M2 dossier and the committed partition first. ``frame`` is
    exactly the research-train partition; ``research_train_last_open_time``
    is the immutable firewall boundary (2022-06-21 UTC).
    """

    frame: pd.DataFrame
    partition: DevelopmentPartition

    @property
    def research_train_last_open_time(self) -> pd.Timestamp:
        return self.partition.research_train.last_open_time

    def __post_init__(self) -> None:
        # Structural guarantee: the handed frame is exactly research train.
        guard_research_train_frame(self.frame, self.research_train_last_open_time)
        if len(self.frame) != self.partition.research_train.row_count:
            raise DevelopmentAccessError("development dataset frame is not the research-train size")
        if content_fingerprint(self.frame) != self.partition.research_train.content_fingerprint:
            raise DevelopmentAccessError(
                "development dataset frame does not match the research-train fingerprint"
            )


def _partition_summary(name: str, frame: pd.DataFrame) -> PartitionSummary:
    checked = validate_ohlcv(frame)
    return PartitionSummary(
        name=name,
        content_fingerprint=content_fingerprint(checked),
        row_count=len(checked),
        first_open_time=checked.index[0],
        last_open_time=checked.index[-1],
    )


def derive_development_partition(
    dataset: LoadedDataset,
    protocol: BenchmarkProtocol,
    *,
    frozen_m2_dossier_sha256: str,
    package_version: str = __version__,
) -> DevelopmentPartition:
    """Mechanically derive the three-level partition from verified M2 data.

    Uses the frozen M2 protocol's chronological 60/20/20 split: the M2
    train segment is the research-train partition, the M2 validation
    segment is the development gate, and the M2 test segment is the final
    holdout — no new split scheme, no new fractions.

    ``package_version`` defaults to the running package version (fresh creation
    stamps this code's version). Verification of an already-committed partition
    passes the committed version so the recompute is byte-identical across a
    later package bump — the partition content (dates, counts, fingerprints,
    dossier hash) is version-independent, exactly like the frozen M2 dossier's
    version-independent numerical reproduction.
    """
    frame = dataset.frame
    splits = chronological_split(
        frame,
        train_fraction=protocol.train_fraction,
        validation_fraction=protocol.validation_fraction,
    )
    partitions = (
        _partition_summary(RESEARCH_TRAIN, splits.train),
        _partition_summary(DEVELOPMENT_GATE, splits.validation),
        _partition_summary(FINAL_HOLDOUT, splits.test),
    )
    return DevelopmentPartition(
        partition_schema_version=PARTITION_SCHEMA_VERSION,
        package_version=package_version,
        frozen_m2_dossier_sha256=frozen_m2_dossier_sha256,
        split_semantics=SPLIT_SEMANTICS,
        dataset_content_fingerprint=content_fingerprint(frame),
        dataset_row_count=len(frame),
        dataset_first_open_time=frame.index[0],
        dataset_last_open_time=frame.index[-1],
        partitions=partitions,
    )


def build_development_partition(
    repo_root: str | Path,
    manifest_path: str | Path,
    *,
    package_version: str = __version__,
) -> DevelopmentPartition:
    """Verify the frozen M2 dossier (snapshot) then derive the partition.

    The dataset must be a reconstructed canonical dataset (materialized by
    the replay tool under the git-ignored ``data/`` tree); the frozen M2
    dossier is verified before any partition is derived. ``package_version``
    is forwarded to the derivation (see :func:`derive_development_partition`).
    """
    from eth_research.dossier import verify_frozen_dossier

    root = Path(repo_root)
    dossier_sha = sha256_file(root / FROZEN_M2_DOSSIER_RELPATH)
    verification = verify_frozen_dossier(
        root,
        manifest_path=manifest_path,
        raw_chunk_dir=root / "research/m2b/raw/coinbase/coinbase-eth-usd-001",
        derived_csv=Path(manifest_path).parent.parent / "coinbase-eth-usd-1d.csv",
    )
    verification.raise_for_status()
    if verification.protocol is None or verification.dataset is None:  # pragma: no cover
        raise DevelopmentAccessError("frozen M2 dossier verification returned no dataset/protocol")
    return derive_development_partition(
        verification.dataset,
        verification.protocol,
        frozen_m2_dossier_sha256=dossier_sha,
        package_version=package_version,
    )


def load_development_partition(path: str | Path) -> DevelopmentPartition:
    """Strictly parse a committed development-partition file."""
    file = Path(path)
    try:
        return DevelopmentPartition.from_json_bytes(file.read_bytes())
    except ValueError as exc:
        raise DevelopmentAccessError(f"invalid development partition {file.name!r}: {exc}") from exc


def load_development_dataset(
    repo_root: str | Path, manifest_path: str | Path
) -> DevelopmentDataset:
    """Return the research-train rows only, after verifying the whole chain.

    Verifies the frozen M2 dossier and the committed development partition
    (recomputed byte-for-byte), then slices the research-train partition and
    hands it back — never the full dataset, never a forbidden row.
    """
    root = Path(repo_root)
    committed_path = root / DEVELOPMENT_PARTITION_RELPATH
    committed = load_development_partition(committed_path)
    # Recompute with the committed partition's recorded version: the partition
    # content is version-independent, so binding the committed version keeps the
    # byte-for-byte recompute stable across a later package bump (e.g. the M3B
    # 0.5.0 package verifying the committed 0.4.0 M3A partition). Every other
    # field is still recomputed from the verified M2 dataset and must match.
    recomputed = build_development_partition(
        root, manifest_path, package_version=committed.package_version
    )
    if recomputed.to_json_bytes() != committed.to_json_bytes():
        raise DevelopmentAccessError(
            "the committed development partition does not recompute from the verified M2 dataset"
        )
    dataset = load_canonical_dataset(manifest_path)
    boundary = committed.research_train.last_open_time
    research_train = dataset.frame.loc[dataset.frame.index <= boundary].copy()
    return DevelopmentDataset(frame=research_train, partition=committed)


def guard_research_train_frame(frame: pd.DataFrame, research_train_last_open: pd.Timestamp) -> None:
    """Reject a frame carrying any forbidden row, gap, duplicate, or shuffle.

    The single boundary rule: **no open time after
    ``research_train_last_open``** (2022-06-21 UTC). A frame is rejected —
    never truncated — if it postdates the boundary, is empty, is not a
    validated OHLCV frame, or is out of order.
    """
    if not isinstance(frame, pd.DataFrame):
        raise DevelopmentAccessError("expected a DataFrame")
    if len(frame) == 0:
        raise DevelopmentAccessError("refusing an empty research-train frame")
    if tuple(frame.columns) != OHLCV_COLUMNS:
        raise DevelopmentAccessError(f"frame must have exactly the columns {OHLCV_COLUMNS}")
    try:
        checked = validate_ohlcv(frame)
    except (ValueError, TypeError) as exc:
        raise DevelopmentAccessError(f"frame failed strict OHLCV validation: {exc}") from exc
    latest = checked.index.max()
    if latest > research_train_last_open:
        raise DevelopmentAccessError(
            f"forbidden partition access: row {latest.isoformat()} is after the research-train "
            f"boundary {research_train_last_open.isoformat()} (development gate / final holdout "
            "must never reach a strategy or the engine)"
        )


def guard_context(context: pd.DataFrame | None, research_train_last_open: pd.Timestamp) -> None:
    """Reject warm-up context that crosses the research-train boundary."""
    if context is None or len(context) == 0:
        return
    guard_research_train_frame(context, research_train_last_open)


def verify_development_partition(repo_root: str | Path, manifest_path: str | Path) -> None:
    """Require the committed partition to recompute byte-for-byte.

    Binds the committed partition's recorded ``package_version`` (the content is
    version-independent) so the recompute stays byte-identical across a later
    package bump; every other field is recomputed from the verified M2 dataset.
    """
    root = Path(repo_root)
    committed = load_development_partition(root / DEVELOPMENT_PARTITION_RELPATH)
    recomputed = build_development_partition(
        root, manifest_path, package_version=committed.package_version
    )
    if recomputed.to_json_bytes() != committed.to_json_bytes():
        raise DevelopmentAccessError(
            "the committed development partition does not recompute from the verified M2 dataset"
        )
