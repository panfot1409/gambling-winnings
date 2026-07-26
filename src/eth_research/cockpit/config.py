"""Whether to report to Cockpit at all, decided from the environment and nowhere else.

Connection details — the Cockpit URL, the bot key, timeouts, retry and queue sizing — are read by
the ``nardis-telemetry`` client from the same ``NARDIS_*`` environment variables and are *not*
duplicated here. This module answers two trader-side questions only: is telemetry switched on, and
how often should the independent heartbeat beat?

The bot key is never stored, returned, rendered, or logged by this module. It is tested for
presence and discarded on the same line.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

#: Set to a falsey value to run the trader with telemetry off even when a key is present.
TELEMETRY_ENABLED_ENV: str = "NARDIS_TELEMETRY_ENABLED"
#: The per-bot ingest key. Absent or empty means telemetry is off — never an error.
BOT_API_KEY_ENV: str = "NARDIS_BOT_API_KEY"
#: Read by the client, listed here so the operator documentation has one home.
COCKPIT_URL_ENV: str = "NARDIS_COCKPIT_URL"
#: Seconds between heartbeats from the independent worker.
HEARTBEAT_INTERVAL_ENV: str = "NARDIS_HEARTBEAT_INTERVAL_SECONDS"

#: Comfortably below Cockpit's 45s "online" threshold, so one lost beat is not a status change.
DEFAULT_HEARTBEAT_INTERVAL_SECONDS: float = 15.0
#: A heartbeat faster than this would be pointless chatter; slower than 40s risks a false
#: "delayed" reading. Values outside the range are clamped rather than rejected: a misconfigured
#: dashboard must never stop a trader from starting.
MIN_HEARTBEAT_INTERVAL_SECONDS: float = 1.0
MAX_HEARTBEAT_INTERVAL_SECONDS: float = 40.0

_FALSEY: frozenset[str] = frozenset({"0", "false", "no", "off"})


def _flag(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().casefold() not in _FALSEY


def _interval(env: Mapping[str, str], name: str, *, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        # A typo in a dashboard setting is not a trading fault: fall back and carry on.
        return default
    if value != value:  # NaN
        return default
    return min(max(value, MIN_HEARTBEAT_INTERVAL_SECONDS), MAX_HEARTBEAT_INTERVAL_SECONDS)


@dataclass(frozen=True, slots=True)
class CockpitConfig:
    """The trader-side telemetry switch. Holds no secret and no connection detail."""

    enabled: bool
    heartbeat_interval_seconds: float

    @staticmethod
    def disabled() -> CockpitConfig:
        """The configuration a trader runs under when nobody asked for monitoring."""
        return CockpitConfig(
            enabled=False, heartbeat_interval_seconds=DEFAULT_HEARTBEAT_INTERVAL_SECONDS
        )

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None) -> CockpitConfig:
        """Read the switch from the environment. Never raises, never reports a missing key.

        Telemetry is on only when it was not switched off *and* a bot key is present. A trader
        started without Cockpit configuration is a normal, fully supported way to run.
        """
        source = os.environ if env is None else env
        has_key = bool(source.get(BOT_API_KEY_ENV, "").strip())
        return CockpitConfig(
            enabled=_flag(source, TELEMETRY_ENABLED_ENV, default=True) and has_key,
            heartbeat_interval_seconds=_interval(
                source, HEARTBEAT_INTERVAL_ENV, default=DEFAULT_HEARTBEAT_INTERVAL_SECONDS
            ),
        )


__all__ = [
    "BOT_API_KEY_ENV",
    "COCKPIT_URL_ENV",
    "DEFAULT_HEARTBEAT_INTERVAL_SECONDS",
    "HEARTBEAT_INTERVAL_ENV",
    "MAX_HEARTBEAT_INTERVAL_SECONDS",
    "MIN_HEARTBEAT_INTERVAL_SECONDS",
    "TELEMETRY_ENABLED_ENV",
    "CockpitConfig",
]
