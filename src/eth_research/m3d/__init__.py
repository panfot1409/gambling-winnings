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

from eth_research import __version__ as _PACKAGE_VERSION

# The M3D governance/data artifacts stamp the running development package
# version; kept as a named constant so a single import point identifies the
# milestone without every module reaching back into the top-level package.
M3D_PACKAGE_VERSION: str = _PACKAGE_VERSION

__all__ = ["M3D_PACKAGE_VERSION"]
