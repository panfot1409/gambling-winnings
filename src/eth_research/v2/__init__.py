"""V2A commercial-evidence, governed-research, and shadow-operations namespace.

This package is the isolated home of the V2 sell-ready roadmap's first milestone (V2A). It never
modifies an accepted M1-M4 engine; it composes additive, strict, offline modules under a single
namespace so the research evidence, the signal-only operational runtime, and the buyer-facing
projections stay separable and independently auditable.

Nothing in this package claims out-of-sample, forward, live, profitable, or sell-ready status. The
:mod:`eth_research.v2.constitution` module is the single authority on what may be claimed, and it
fails closed on any reserved status.
"""

from __future__ import annotations

from eth_research.v2.budget import (
    MAX_CANDIDATE_FAMILIES,
    MAX_RESEARCH_EXECUTIONS,
    OneShotResearchBudget,
)
from eth_research.v2.constitution import (
    RESERVED_STATUSES,
    STANDING_POSTURE,
    V2A_EMITTABLE_STATUSES,
    CommercialEvidenceConstitution,
)

# The milestone this namespace belongs to. Independent of the running package version; it identifies
# the governed research programme, not the wheel.
V2A_MILESTONE: str = "v2a"

__all__ = [
    "MAX_CANDIDATE_FAMILIES",
    "MAX_RESEARCH_EXECUTIONS",
    "RESERVED_STATUSES",
    "STANDING_POSTURE",
    "V2A_EMITTABLE_STATUSES",
    "V2A_MILESTONE",
    "CommercialEvidenceConstitution",
    "OneShotResearchBudget",
]
