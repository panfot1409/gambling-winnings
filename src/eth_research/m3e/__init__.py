"""Milestone 3E — review-only prospective update automation.

This package is **data-only, governance-only, and review-only**. It lets the
accepted M3D prospective ETH-USD daily cohort grow *only* through
independently-verified, append-only update **proposals** that are always opened as
**draft** pull requests for human review — never auto-applied, never auto-merged,
never pushed to an accepted branch.

It contains **no** strategy, signal, backtest, position, fill, fee, return,
metric, ranking, promotion, decision, or money-movement code, and it imports no
such module. It opens no socket and holds no key: the network boundary lives
entirely in a hardened, read-only workflow ``curl`` step, and every byte a runner
returns is re-derived offline from committed evidence. That isolation is enforced
mechanically by ``tests/test_m3e_architecture.py`` (an AST scan of every module
under this package) and re-asserted by ``verify_m3e_program``.

The development package version for Milestone 3E is 0.8.0; frozen upstream
milestone identities (M2B 0.3.0, M3A 0.4.0, M3B 0.5.0, M3C 0.6.0, M3D 0.7.0) keep
their own recorded versions and are never rewritten.
"""

from __future__ import annotations

# Milestone 3E is complete and its artifacts are frozen at development version
# 0.8.0. This constant pins the literal 0.8.0 that every committed M3E artifact
# (accepted_base.json, the proposal registry, and any proposal manifest) already
# stamps — exactly as every prior completed milestone pins its own version
# (``M3D_PACKAGE_VERSION = "0.7.0"``, ``M3C_PACKAGE_VERSION = "0.6.0"``, …). The
# freeze is replay-neutral: the pinned value equals the live package version at
# freeze time, so every M3E artifact rebuilds byte-for-byte and ``m3e-replay``
# stays green even after a later milestone bumps the running package to 0.9.0.
M3E_PACKAGE_VERSION: str = "0.8.0"

__all__ = ["M3E_PACKAGE_VERSION"]
