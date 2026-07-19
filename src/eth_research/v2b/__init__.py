"""V2B cross-asset research-reset namespace.

Milestone V2B continues the V2 sell-ready roadmap on top of the **accepted V2A negative result**. It
adds, additively and offline, a cumulative research-memory + family-wise multiplicity governance
layer, a genuinely new information source (research-train-window BTC-USD daily data), at most two
pre-registered cross-asset candidate families, a multi-asset offline shadow extension, and one
governed research-train one-shot. It never modifies an accepted M1-M4 or V2A engine or artifact.

Nothing in this package claims out-of-sample, forward, live, profitable, or sell-ready status; the
reused :mod:`eth_research.v2.constitution` remains the single authority on claims and fails closed
on any reserved status. V2B is the current development milestone; its committed governed artifacts
stamp the live running package version (``2.0.0.dev1``).
"""

from __future__ import annotations

# The milestone this namespace belongs to. Independent of the running package version; it identifies
# the governed research programme, not the wheel.
V2B_MILESTONE: str = "v2b"

# All V2B governed artifacts live under this directory.
V2B_DIR: str = "research/v2b"

__all__ = [
    "V2B_DIR",
    "V2B_MILESTONE",
]
