"""V2C process-isolated buyer-evaluation boundary (sections 24-27).

Wraps the existing, fingerprint-pinned buyer-evaluation objects (``eth_research.buyer``) across a
**process boundary**: a vendor server serves only redacted artifacts over a length-prefixed JSON
protocol, and a source-free buyer client runs in an isolated temp root with no repository, package
source, or private data. It does not re-define the contract/claims/scorecard/factsheet/diligence
objects -- it serves them.

Honest limitation (V2C_PLAN section 4): the vendor still runs the private implementation. This is a
process-isolation and redaction boundary, **not** independent deployment, and it does not prove the
core IP cannot be reverse engineered.

Modules:

* :mod:`eth_research.v2c.buyer.framing` (24) -- bounded, length-prefixed JSON frames.
* :mod:`eth_research.v2c.buyer.boundary` (24-25) -- request/response envelope, vendor server,
  per-session request quota.
* :mod:`eth_research.v2c.buyer.harness` (27) -- the deterministic, source-free harness builder.
* :mod:`eth_research.v2c.buyer.isolation` (24, 26) -- runs the buyer client in an isolated
  subprocess and proves isolation + vendor non-interference.
"""

from __future__ import annotations

BUYER_BOUNDARY_VERSION: int = 1

__all__ = ["BUYER_BOUNDARY_VERSION"]
