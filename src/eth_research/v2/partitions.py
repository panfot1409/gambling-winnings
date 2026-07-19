"""The V2A partition firewall: candidate evaluation may see ONLY the research-train partition.

The M3A three-way split is ``research_train`` (2016-05-23 … 2022-06-21 UTC, 2221 rows) plus two
sealed partitions — ``development_gate`` (740 rows) and ``final_holdout`` (741 rows). V2A strategy
code is allowed to touch the research-train rows and nothing else. This module is the single door
through which candidate evaluation obtains price data, and it fails closed:

* it reuses the reviewed :func:`eth_research.fractional.verify_dataset_integrity_only`, which
  reconstructs the dataset from committed raw bytes and returns only the research-train frame;
* it re-applies the reviewed :func:`eth_research.development.guard_research_train_frame` boundary
  guard, so a row on or after 2022-06-22 UTC can never appear;
* it pins the research-train row count and last-open timestamp; and
* :func:`require_research_train_partition` rejects, by name, any attempt to route a sealed partition
  through the evaluation path.

The M3D prospective cohort is a separate, immature dataset that is never loaded here at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from eth_research.development import guard_research_train_frame
from eth_research.fractional import verify_dataset_integrity_only
from eth_research.v2.strict import V2ValidationError

# The only partition V2A strategy code may evaluate on.
RESEARCH_TRAIN: str = "research_train"

# Sealed partitions. V2A never routes these through evaluation; any attempt is a hard stop.
SEALED_PARTITIONS: frozenset[str] = frozenset({"development_gate", "final_holdout"})

# Pinned research-train identity (cross-checked against the reconstructed dataset).
RESEARCH_TRAIN_ROW_COUNT: int = 2221
RESEARCH_TRAIN_FIRST_OPEN: str = "2016-05-23T00:00:00+00:00"
RESEARCH_TRAIN_LAST_OPEN: str = "2022-06-21T00:00:00+00:00"


class PartitionFirewallError(V2ValidationError):
    """A partition-firewall invariant failed (row leak, count/bound drift, or sealed access)."""


@dataclass(frozen=True, slots=True)
class ResearchTrainView:
    """The firewalled research-train frame plus the identity it was checked against.

    ``frame`` is exactly the 2221 research-train rows (DatetimeIndex named ``timestamp``, UTC,
    columns open/high/low/close/volume as float64). No sealed-partition row is ever included.
    """

    frame: pd.DataFrame
    first_open_time: pd.Timestamp
    last_open_time: pd.Timestamp
    row_count: int
    content_fingerprint: str


def require_research_train_partition(label: str, name: object) -> str:
    """Return ``name`` iff it is exactly ``research_train``; reject sealed / unknown partitions.

    This is the name-level gate: any code that selects a partition for strategy evaluation must pass
    the chosen name through here, so a sealed partition can never be selected even by mistake.
    """
    if not isinstance(name, str):
        raise PartitionFirewallError(
            f"{label} partition name must be a string, got {type(name).__name__}"
        )
    if name in SEALED_PARTITIONS:
        raise PartitionFirewallError(
            f"{label} requested the sealed partition {name!r}; V2A evaluation may only use "
            f"{RESEARCH_TRAIN!r} (the development gate and final holdout are never accessed)"
        )
    if name != RESEARCH_TRAIN:
        raise PartitionFirewallError(
            f"{label} requested an unknown partition {name!r}; the only evaluable partition is "
            f"{RESEARCH_TRAIN!r}"
        )
    return name


def load_research_train_only(repo_root: str | Path) -> ResearchTrainView:
    """Load and firewall the research-train partition; raise on any leak or identity drift.

    Reuses the accepted integrity verifier (no accepted engine is modified) and then re-asserts,
    from scratch, that what comes back is exactly the research-train partition and nothing later.
    """
    integrity = verify_dataset_integrity_only(repo_root)
    frame = integrity.research_train
    last_open = integrity.research_train_last_open_time

    # Boundary guard (reviewed): no row on/after the research-train cutoff may be present.
    guard_research_train_frame(frame, last_open)

    if len(frame) != RESEARCH_TRAIN_ROW_COUNT:
        raise PartitionFirewallError(
            f"research-train frame has {len(frame)} rows, expected {RESEARCH_TRAIN_ROW_COUNT}"
        )

    first_open = frame.index[0]
    expected_first = pd.Timestamp(RESEARCH_TRAIN_FIRST_OPEN)
    expected_last = pd.Timestamp(RESEARCH_TRAIN_LAST_OPEN)
    if first_open != expected_first:
        raise PartitionFirewallError(
            f"research-train first open {first_open} != expected {expected_first}"
        )
    if last_open != expected_last:
        raise PartitionFirewallError(
            f"research-train last open {last_open} != expected {expected_last}"
        )

    # Cross-check the manifest's research-train summary (row count) as a second, independent anchor.
    summary = integrity.partition.research_train
    if summary.row_count != RESEARCH_TRAIN_ROW_COUNT:
        raise PartitionFirewallError(
            f"partition manifest research_train row_count {summary.row_count} "
            f"!= {RESEARCH_TRAIN_ROW_COUNT}"
        )

    return ResearchTrainView(
        frame=frame,
        first_open_time=first_open,
        last_open_time=last_open,
        row_count=len(frame),
        content_fingerprint=summary.content_fingerprint,
    )
