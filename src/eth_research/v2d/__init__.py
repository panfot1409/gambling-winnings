"""V2D — separately governed DATA-ONLY prospective-collection activation.

This package is the governance layer for the V2D milestone: the explicit, committed,
self-hashed activation anchor that authorizes the standing update workflow to fetch
new completed daily candles and open review-only draft update proposals — and the
fail-closed runtime verifier the workflow must pass **before any network step**.

V2D activates data collection only. It contains no strategy, candidate, metric,
evaluation, trading, or publication capability, and its verifier re-asserts at
runtime that evaluation stays unauthorized and every sealed ledger stays byte-empty.
"""

from __future__ import annotations

V2D_PACKAGE_VERSION = "1.0.0"

__all__ = ["V2D_PACKAGE_VERSION"]
