"""Optional, observation-only reporting of a paper run to a self-hosted Nardis Cockpit.

Cockpit is a monitoring dashboard the operator runs beside the trader. This package is the
*only* place the trader knows about it, and it is deliberately a dead end in the call graph:

* nothing here is imported by the shadow platform, the research engines, or any governed
  module — the accepted, hash-frozen qualification source (``governance/v2c/oq_source_freeze.json``)
  is untouched, so Cockpit cannot sit on the trading path even by accident;
* every reporting function returns ``None``. There is no value a strategy, a risk limit, an
  order decision, or an accounting step could branch on;
* every reporting function swallows every exception. A broken, slow, or absent Cockpit is
  indistinguishable from a working one as far as the trader is concerned;
* the transport, queue, retry, circuit breaker, authentication, event model, and log redaction
  all live in the third-party ``nardis-telemetry`` client. None of it is reimplemented here.

The client is an *optional* dependency and is deliberately **not** declared in
``pyproject.toml``: this repository's locked dependency inventory
(:mod:`eth_research.m3f.dependency_inventory`) fails closed on any non-registry package source, and
the offline posture forbids a networking dependency in the default install. An operator who wants
Cockpit installs the pinned client alongside the package (see ``docs/COCKPIT_TELEMETRY.md``); when
it is absent, or when the environment does not name a bot key, telemetry is simply off and the
trader behaves exactly as it did before.
"""

from __future__ import annotations

from eth_research.cockpit.client import build_client, install_log_redaction
from eth_research.cockpit.config import (
    BOT_API_KEY_ENV,
    COCKPIT_URL_ENV,
    HEARTBEAT_INTERVAL_ENV,
    TELEMETRY_ENABLED_ENV,
    CockpitConfig,
)
from eth_research.cockpit.heartbeat import HeartbeatWorker
from eth_research.cockpit.reporter import CockpitReporter

COCKPIT_PACKAGE_VERSION: int = 1

__all__ = [
    "BOT_API_KEY_ENV",
    "COCKPIT_PACKAGE_VERSION",
    "COCKPIT_URL_ENV",
    "HEARTBEAT_INTERVAL_ENV",
    "TELEMETRY_ENABLED_ENV",
    "CockpitConfig",
    "CockpitReporter",
    "HeartbeatWorker",
    "build_client",
    "install_log_redaction",
]
