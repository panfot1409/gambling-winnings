"""Milestone 3D — prospective evidence governance and future-only data facility.

This package is **data-only and governance-only**. It records the research
program's history as machine-verifiable snapshots, catalogs every strategy
specification and research degree of freedom already exercised, enforces the
research-train exhaustion firewall, and manages a strictly future-only ETH-USD
daily data cohort with append-only, hash-chained, transactional provenance.

It contains **no** strategy, signal, backtest, position, fill, return, metric,
ranking, promotion, or decision code, and it imports no such module. That
isolation is enforced mechanically by ``tests/test_m3d_architecture.py`` (an AST
scan of every module under this package).

The development package version for Milestone 3D is 0.7.0; frozen upstream
milestone identities keep their own recorded versions and are never rewritten.
"""

from __future__ import annotations

# Milestone 3D is complete and its artifacts are frozen at development version
# 0.7.0. Once a later milestone bumps the running package (M3E → 0.8.0), this
# constant must pin the literal 0.7.0 the M3D artifacts already stamp — exactly as
# every prior completed milestone pins its own version (``M3C_PACKAGE_VERSION =
# "0.6.0"``, etc.). The freeze is replay-neutral: every M3D artifact rebuilds
# byte-for-byte and ``m3d-replay`` stays green under the newer running package.
M3D_PACKAGE_VERSION: str = "0.7.0"

__all__ = ["M3D_PACKAGE_VERSION"]
