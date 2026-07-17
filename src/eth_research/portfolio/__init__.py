"""Milestone 4B — the multi-asset, multi-venue, multi-currency portfolio research simulator.

This package is an isolated, offline, deterministic research layer stacked additively on the
accepted Milestone 4A single-asset platform. It never contacts a network, an exchange, a wallet,
or a broker; it never routes an order or moves money; it supports long-only fractional target
weights over a shared cash pool with no leverage, shorting, margin, or derivatives. Everything it
consumes is either synthetically generated or supplied by the caller as local evidence, and every
artifact it emits is canonical JSON with a stable SHA-256.

The package deliberately reuses the accepted canonical-serialization and atomic-publication
helpers (``eth_research.api.serialization``, ``eth_research._json``, ``eth_research._atomic``) so
the M4B strictness surface is identical to the accepted stack's.
"""

from __future__ import annotations

#: The literal version whose running package first shipped this portfolio layer. Mirrors the
#: milestone-pinning convention of ``eth_research.m3c``…``eth_research.m4a``: a committed M4B
#: artifact stamps this version, and a running package whose ``__version__`` differs marks a
#: development ("snapshot") run rather than a re-authorization of a frozen one.
M4B_PACKAGE_VERSION = "1.1.0"

__all__ = ["M4B_PACKAGE_VERSION"]
