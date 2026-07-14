"""Milestone 3B fractional long-only research lab (parallel to the binary engine).

Research-only. This sub-package is the *parallel* Milestone 3B interface: exact
fractional long-only ETH accounting, causal next-open execution, lagged-liquidity
impact proxies, strict risk overlays, reconciled metrics, and an integrity-only
research-train loader. It deliberately does **not** modify the original binary
engine (:func:`eth_research.backtest.run_backtest`) or any M1/M2/M3A semantics.

No live-trading, exchange authentication, wallet, transaction signing, order
routing, leverage, borrowing, margin, shorting, or network functionality exists
here or anywhere in :mod:`eth_research`; the lab operates exclusively on the
committed historical research-train partition loaded from local files.
"""

from __future__ import annotations

from eth_research.fractional.dataset import (
    DatasetIntegrityError,
    DatasetIntegrityResult,
    verify_dataset_integrity_only,
)

__all__ = [
    "DatasetIntegrityError",
    "DatasetIntegrityResult",
    "verify_dataset_integrity_only",
]
