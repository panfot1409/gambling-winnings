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

# V2A is a completed milestone: its committed governed artifacts (pre_registration.json,
# results.json) stamp the version the run was authorized under. Once a later milestone (V2B)
# bumps the active package version, V2A freezes and pins its own recorded version here rather
# than tracking the live ``eth_research.__version__`` — exactly as every prior completed
# milestone pins its own ``*_PACKAGE_VERSION`` (M4B is ``1.1.0``, M3C is ``0.6.0``, …). A running
# version that differs from this frozen constant marks a development ("snapshot") run, never a
# re-authorization of the consumed one-shot.
V2A_PACKAGE_VERSION: str = "2.0.0.dev0"

__all__ = [
    "MAX_CANDIDATE_FAMILIES",
    "MAX_RESEARCH_EXECUTIONS",
    "RESERVED_STATUSES",
    "STANDING_POSTURE",
    "V2A_EMITTABLE_STATUSES",
    "V2A_MILESTONE",
    "V2A_PACKAGE_VERSION",
    "CommercialEvidenceConstitution",
    "OneShotResearchBudget",
]
