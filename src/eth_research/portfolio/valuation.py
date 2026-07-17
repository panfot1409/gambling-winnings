"""Causal mark-to-market valuation with an explicit staleness policy.

At a valuation time ``tau`` a holding is worth its *causally available* close — the close of the
most recent bar whose ``close_time`` is at or before ``tau`` — translated to the base currency at
the FX rate known by ``tau``. A mark is never taken from a future bar, and a stale mark (one whose
closed more than the policy's bound before ``tau``) is refused rather than silently carried: the
simulator would rather fail than value a position at a price the market has long since left behind.
Carrying a prior mark is legitimate only while a market is closed and within the staleness bound;
this module supplies the mark and the staleness, and the engine decides, per its calendar, whether
carrying is permitted.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.validation import require_positive_finite_float

__all__ = ["Mark", "StalenessPolicy", "latest_close_as_of", "mark_instrument"]


@dataclass(frozen=True)
class StalenessPolicy:
    """How old a causal mark may be, relative to the valuation time, before it is refused."""

    max_staleness_seconds: float

    def __post_init__(self) -> None:
        require_positive_finite_float(self.max_staleness_seconds, "staleness.max_staleness_seconds")

    def refuses(self, staleness_seconds: float) -> bool:
        return staleness_seconds > self.max_staleness_seconds


@dataclass(frozen=True)
class Mark:
    """One holding's base-currency value per unit at a valuation time, with its staleness."""

    instrument: InstrumentId
    base_value_per_unit: float
    local_close: float
    fx_rate: float
    mark_close_time: pd.Timestamp
    staleness_seconds: float


def latest_close_as_of(frame: pd.DataFrame, tau: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    """The ``(close_time, close)`` of the most recent bar whose ``close_time <= tau``, or ``None``.

    ``frame`` must be a validated canonical bar frame (strictly increasing ``open_time``, tz-aware
    UTC times). Only bars completed at or before ``tau`` are eligible — a mark is never taken from a
    bar that has not yet closed by the valuation time.
    """
    close_times = frame["close_time"]
    closes = frame["close"]
    best: tuple[pd.Timestamp, float] | None = None
    for index in range(len(frame)):
        close_time = close_times.iloc[index]
        if close_time > tau:
            continue
        candidate = (close_time, float(closes.iloc[index]))
        if best is None or candidate[0] > best[0]:
            best = candidate
    return best


def mark_instrument(
    frame: pd.DataFrame,
    fx_evidence: FxEvidence,
    instrument: InstrumentId,
    base_currency: str,
    tau: pd.Timestamp,
    *,
    staleness: StalenessPolicy,
) -> Mark:
    """The causal base-currency mark for ``instrument`` at ``tau``.

    Finds the most recent completed close at or before ``tau``, refuses it if it is older than the
    staleness policy allows, and converts it to ``base_currency`` at the FX rate known by ``tau``.
    Raises :class:`CanonicalError` if no causal close exists, the mark is over-stale, or the FX rate
    is unavailable.
    """
    latest = latest_close_as_of(frame, tau)
    if latest is None:
        raise CanonicalError(
            f"valuation: no completed bar for {instrument.symbol!r} at or before {tau.isoformat()}"
        )
    close_time, local_close = latest
    staleness_seconds = (tau - close_time).total_seconds()
    if staleness.refuses(staleness_seconds):
        raise CanonicalError(
            f"valuation: mark for {instrument.symbol!r} is stale by {staleness_seconds:.0f}s "
            f"(> {staleness.max_staleness_seconds:.0f}s); refusing to carry it"
        )
    # base per quote: the holding's local value (quote currency) times base-per-quote.
    fx_rate = fx_evidence.rate_as_of(instrument.quote_currency, base_currency, tau)
    return Mark(
        instrument=instrument,
        base_value_per_unit=local_close * fx_rate,
        local_close=local_close,
        fx_rate=fx_rate,
        mark_close_time=close_time,
        staleness_seconds=staleness_seconds,
    )
