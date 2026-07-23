"""V2C sections 28-31: the private commercial-truth pack (data only, candidate-free).

Four fixed, fingerprint-pinned records that describe the programme's commercial and packaging
posture honestly, without evaluating any strategy or disclosing any IP:

* :mod:`eth_research.v2c.commercial.deployment` (28) -- the **inactive** offline-operations
  deployment blueprint (activates nothing; every gate an unmet external human decision).
* :mod:`eth_research.v2c.commercial.sbom` (29) -- the **private** CycloneDX SBOM for the V2C
  development distribution, derived deterministically from ``uv.lock``.
* :mod:`eth_research.v2c.commercial.ip_dossier` (30) -- an IP **catalog** (not disclosure) carrying
  the honest reverse-engineering exposure.
* :mod:`eth_research.v2c.commercial.options` (31) -- the honest commercial-options record, with
  ``sell_ready`` derived from the constitution's ``not_sell_ready`` posture.

The committed artifacts live under ``governance/v2c/commercial/`` -- outside the frozen
``research/`` and ``release/`` roots pinned by the V2A-V2B freeze table -- and reproduce
byte-for-byte via :func:`eth_research.v2c.commercial.evidence.check`. Nothing here is published; the
programme is not sell-ready and the repository is private.
"""

from __future__ import annotations

COMMERCIAL_PACK_VERSION: int = 1

__all__ = ["COMMERCIAL_PACK_VERSION"]
