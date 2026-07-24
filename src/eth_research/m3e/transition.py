"""The old → new append-only prospective cohort transition.

An update proposal extends the accepted cohort **only by appending** newly-completed
days. This module re-derives the accepted (old) cohort rows from the committed M3D
evidence, takes the attested new-window rows, and proves the transition is a strict
append:

* the old cohort re-derives from committed M3D bytes and its fingerprint matches the
  accepted base (so the proposal was built against the *current* accepted base);
* the new window's first open is exactly one interval after the old last open — no
  gap, no overlap, no backfill;
* the appended rows are internally contiguous daily candles, all strictly after the
  old last open;
* the proposed cohort is exactly ``old_rows + new_rows`` and begins with the old
  rows unchanged (byte-identical prefix).

It records the old, new-window, and proposed-cohort fingerprints so CI can replay
the *complete* proposed cohort and confirm the extension without trusting any
value it did not re-derive. It computes no strategy quantity — only row identity,
contiguity, and hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from eth_research.m3d.raw_bundle import (
    cohort_canonical_fingerprint,
    combined_canonical_rows,
)
from eth_research.m3d.update_attempts import build_accepted_raw_bundles
from eth_research.m3e.accepted_base import AcceptedProspectiveBase
from eth_research.m3e.acquisition import fingerprint_new_window_rows
from eth_research.m3e.validation import (
    M3EValidationError,
    domain_sha256,
)

PROPOSED_COHORT_DOMAIN = "m3e_proposed_updated_cohort"
TRANSITION_DOMAIN = "m3e_update_transition"
_INTERVAL_SECONDS = 86400
_DAY = pd.Timedelta(days=1)


@dataclass(frozen=True)
class ProspectiveUpdateTransition:
    old_row_count: int
    old_first_open: str
    old_last_open: str
    old_fingerprint: str
    new_window_row_count: int
    new_window_first_open: str
    new_window_last_open: str
    new_window_fingerprint: str
    proposed_row_count: int
    proposed_first_open: str
    proposed_last_open: str
    proposed_cohort_fingerprint: str
    appended_rows: tuple[tuple[Any, ...], ...]
    is_append_only: bool
    transition_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "old_row_count": self.old_row_count,
            "old_first_open": self.old_first_open,
            "old_last_open": self.old_last_open,
            "old_fingerprint": self.old_fingerprint,
            "new_window_row_count": self.new_window_row_count,
            "new_window_first_open": self.new_window_first_open,
            "new_window_last_open": self.new_window_last_open,
            "new_window_fingerprint": self.new_window_fingerprint,
            "proposed_row_count": self.proposed_row_count,
            "proposed_first_open": self.proposed_first_open,
            "proposed_last_open": self.proposed_last_open,
            "proposed_cohort_fingerprint": self.proposed_cohort_fingerprint,
            "is_append_only": self.is_append_only,
            "transition_sha256": self.transition_sha256,
        }


def _require_daily_contiguous(rows: list[list[Any]], label: str) -> None:
    for earlier, later in pairwise(rows):
        if pd.Timestamp(later[0]) - pd.Timestamp(earlier[0]) != _DAY:
            raise M3EValidationError(f"{label} rows are not contiguous daily")


def build_update_transition(
    repo_root: str | Path,
    base: AcceptedProspectiveBase,
    *,
    new_window_rows: list[list[Any]],
    new_window_fingerprint: str,
) -> ProspectiveUpdateTransition:
    """Prove the accepted → proposed transition is a strict append; HARD STOP otherwise."""
    old_bundles, _entries = build_accepted_raw_bundles(repo_root)
    old_rows = combined_canonical_rows(old_bundles)
    if not old_rows:
        raise M3EValidationError("accepted cohort has no rows")
    old_fp = cohort_canonical_fingerprint(old_bundles)
    if old_fp != base.canonical_content_fingerprint:
        raise M3EValidationError("accepted cohort fingerprint drifted from the base (HARD STOP)")

    if not new_window_rows:
        raise M3EValidationError("new window has no rows (nothing to append)")
    if fingerprint_new_window_rows(new_window_rows) != new_window_fingerprint:
        raise M3EValidationError("new-window fingerprint does not match the appended rows")

    _require_daily_contiguous(old_rows, "old cohort")
    _require_daily_contiguous(new_window_rows, "new window")

    old_last = pd.Timestamp(old_rows[-1][0])
    new_first = pd.Timestamp(new_window_rows[0][0])
    if new_first <= old_last:
        raise M3EValidationError("new window overlaps or precedes the accepted cohort (HARD STOP)")
    if new_first != old_last + _DAY:
        raise M3EValidationError("new window is not exactly one interval after the accepted cohort")

    proposed_rows = old_rows + new_window_rows
    if proposed_rows[: len(old_rows)] != old_rows:  # pragma: no cover - defensive
        raise M3EValidationError("proposed cohort does not begin with the accepted rows")
    _require_daily_contiguous(proposed_rows, "proposed cohort")

    proposed_fp = domain_sha256(
        PROPOSED_COHORT_DOMAIN,
        {
            "interval_seconds": _INTERVAL_SECONDS,
            "row_count": len(proposed_rows),
            "first_open": proposed_rows[0][0],
            "last_open": proposed_rows[-1][0],
            "rows": proposed_rows,
        },
    )
    transition_sha256 = domain_sha256(
        TRANSITION_DOMAIN,
        {
            "old_fingerprint": old_fp,
            "old_row_count": len(old_rows),
            "old_last_open": old_rows[-1][0],
            "new_window_fingerprint": new_window_fingerprint,
            "new_window_row_count": len(new_window_rows),
            "new_window_first_open": new_window_rows[0][0],
            "new_window_last_open": new_window_rows[-1][0],
            "proposed_cohort_fingerprint": proposed_fp,
            "proposed_row_count": len(proposed_rows),
        },
    )
    return ProspectiveUpdateTransition(
        old_row_count=len(old_rows),
        old_first_open=old_rows[0][0],
        old_last_open=old_rows[-1][0],
        old_fingerprint=old_fp,
        new_window_row_count=len(new_window_rows),
        new_window_first_open=new_window_rows[0][0],
        new_window_last_open=new_window_rows[-1][0],
        new_window_fingerprint=new_window_fingerprint,
        proposed_row_count=len(proposed_rows),
        proposed_first_open=proposed_rows[0][0],
        proposed_last_open=proposed_rows[-1][0],
        proposed_cohort_fingerprint=proposed_fp,
        appended_rows=tuple(tuple(row) for row in new_window_rows),
        is_append_only=True,
        transition_sha256=transition_sha256,
    )
