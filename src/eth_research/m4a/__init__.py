"""Milestone 4A — offline research platform 1.0 release-candidate governance package.

Infrastructure-only and read-only: this package derives and verifies deterministic
release-candidate artifacts (the public-API snapshot and the generated CLI reference). It
runs no backtest, evaluates no strategy, and opens no network connection.

``M4A_PACKAGE_VERSION`` pins the release-candidate version literal so the committed RC
artifacts are reproducible independently of the running package.
"""

from __future__ import annotations

M4A_PACKAGE_VERSION = "1.0.0"

__all__ = ["M4A_PACKAGE_VERSION"]
