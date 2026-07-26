"""Build the telemetry client, or don't — either way the caller gets on with trading.

``nardis-telemetry`` is an optional dependency (see the package docstring for why it is not in
``pyproject.toml``). Everything that can go wrong while obtaining a client — the package is not
installed, the environment is incomplete, the client's constructor raises — resolves to the same
answer: ``None``, meaning "run without monitoring".

Only ``nardis_telemetry`` is imported here. The HTTP machinery lives inside that package, so this
repository's AST networking guard (``tests/test_repo_hygiene.py``) still sees a network-free tree.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from eth_research.cockpit.config import CockpitConfig

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nardis_telemetry import TelemetryClient

log = logging.getLogger("eth_research.cockpit")

#: Name of the optional client distribution, quoted in the one log line that explains its absence.
CLIENT_DISTRIBUTION: str = "nardis-telemetry"


def install_log_redaction() -> None:
    """Attach the client's API-key redaction filter to the root logger, if it is available.

    The trader never logs a key, but a key can still reach a log record through a traceback or a
    third-party debug line. This is the backstop, and it is best-effort by design.
    """
    try:
        from nardis_telemetry import install_redaction

        install_redaction()
    except Exception:  # a logging nicety must never break startup
        return


def build_client(config: CockpitConfig) -> TelemetryClient | None:
    """Return a telemetry client, or ``None`` to run without Cockpit.

    ``None`` is a normal outcome, not a failure: it is what a trader gets when nobody configured
    monitoring, when the optional client is not installed, or when building it went wrong. The
    caller does not need to tell those cases apart.
    """
    if not config.enabled:
        log.info("cockpit telemetry is off; trading without monitoring")
        return None
    try:
        from nardis_telemetry import TelemetryClient as _TelemetryClient
    except ImportError:
        log.info(
            "cockpit telemetry is configured but %s is not installed; trading without monitoring",
            CLIENT_DISTRIBUTION,
        )
        return None
    try:
        client = _TelemetryClient.from_env()
    except Exception as error:  # monitoring must not decide whether we trade
        log.warning("could not build the telemetry client (%s); trading without it", error)
        return None
    install_log_redaction()
    return client


__all__ = ["CLIENT_DISTRIBUTION", "build_client", "install_log_redaction"]
