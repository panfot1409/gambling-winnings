"""Buyer-evaluation boundary: what a prospective buyer may see, and the redaction guaranteeing it.

This package assembles a *source-free*, redacted diligence bundle a buyer can evaluate — a claims
catalogue, a factsheet, and a commercial-readiness scorecard — behind a redaction policy + scanner
that fails closed on secrets, embedded source, or sealed research data, and a reference evaluation
gateway that serves only what the contract allows. It never ships source, never exposes a sealed
partition, and never makes a forward or live claim: the standing posture is ``not_sell_ready``.
"""

from __future__ import annotations

BUYER_PACKAGE_VERSION: int = 1
