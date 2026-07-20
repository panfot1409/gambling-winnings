"""V2C offline operational qualification (OQ) -- sections 20-23.

A deterministic, virtual-time qualification of the offline shadow-operations platform under a
synthetic ETH/BTC event stream carrying a full fault taxonomy. It is **candidate-free**: the only
operational target is ``cash_control`` (zero risky exposure), and the qualification computes no
market performance and is not a forward record.

Modules:

* :mod:`eth_research.v2c.oq.events` (section 20) -- the synthetic event-stream builder + the
  event-acceptance ingestion gate the shadow runner lacks.
* :mod:`eth_research.v2c.oq.slo` (section 21) -- the offline SLO / qualification-criteria contract.
* :mod:`eth_research.v2c.oq.resources` (section 22) -- deterministic processing/memory bounds.
* :mod:`eth_research.v2c.oq.recovery` (section 23) -- the crash/recovery campaign.
* :mod:`eth_research.v2c.oq.harness` -- the orchestrator that drives cash_control through the
  shadow platform and evaluates every SLO.

This subpackage imports the shadow platform (which it qualifies) but no candidate/strategy/
evaluator/engine module.
"""

from __future__ import annotations

OQ_PACKAGE_VERSION: int = 1

__all__ = ["OQ_PACKAGE_VERSION"]
