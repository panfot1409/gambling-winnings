"""Milestone 3F — independent verification, hermetic recovery & supply-chain closure.

Infrastructure-only, read-only. This package derives and *verifies* the repository's
committed state; it evaluates no strategy, runs no backtest, computes no performance
metric, touches no sealed partition, appends no ledger, publishes no proposal, and
opens no network connection. It reuses only strategy-free primitives and, for the
independent-verification requirement, is shadowed by a genuinely separate
standard-library verifier (``tools/m3f_independent_verify.py``).

``M3F_PACKAGE_VERSION`` is pinned to the literal development version so committed M3F
artifacts rebuild byte-for-byte even after a later milestone bumps the running package.
"""

from __future__ import annotations

M3F_PACKAGE_VERSION = "0.9.0"

__all__ = ["M3F_PACKAGE_VERSION"]
