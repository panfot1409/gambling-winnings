"""Monitoring: pure functions that turn shadow-run state into alert records.

Monitoring never mutates the run; it reads state (the as-of frontier, the latest bar time, equity vs
its peak, a risk decision, the kill switch) and emits :class:`Alert` records the runner journals.
Because each builder is a pure function of its inputs, the alert stream is deterministic and every
alert can be re-derived and checked independently.

The thresholds are configuration, not policy: a critical drawdown alert, for example, is what *lets*
the runner trip the kill switch — monitoring reports, the runner reacts.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.shadow.domain import ShadowDomainError, canonical_timestamp, parse_timestamp
from eth_research.v2.strict import (
    require_choice,
    require_exact_keys,
    require_mapping,
    require_nonempty_str,
    require_nonnegative_int,
    require_positive_real,
    require_slug,
    require_unit_interval,
)

INFO: str = "info"
WARNING: str = "warning"
CRITICAL: str = "critical"
SEVERITIES: frozenset[str] = frozenset({INFO, WARNING, CRITICAL})

STALE_DATA_CODE: str = "stale_market_data"
DRAWDOWN_CODE: str = "drawdown_breach"
RISK_BREACH_CODE: str = "risk_limit_breach"
KILL_SWITCH_CODE: str = "kill_switch_tripped"

_ALERT_KEYS = frozenset({"as_of", "severity", "code", "message"})
_THRESHOLD_KEYS = frozenset({"max_staleness_seconds", "max_drawdown_fraction"})


class MonitoringError(ShadowDomainError):
    """An alert or threshold value violated its contract."""


@dataclass(frozen=True, slots=True)
class Alert:
    """One monitoring observation at an as-of instant."""

    as_of: str
    severity: str
    code: str
    message: str

    @staticmethod
    def parse(label: str, value: object) -> Alert:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _ALERT_KEYS)
        return Alert(
            as_of=canonical_timestamp(f"{label}.as_of", obj["as_of"]),
            severity=require_choice(f"{label}.severity", obj["severity"], SEVERITIES),
            code=require_slug(f"{label}.code", obj["code"]),
            message=require_nonempty_str(f"{label}.message", obj["message"]),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class MonitoringThresholds:
    """When data is considered stale and when a drawdown is a critical alert."""

    max_staleness_seconds: int
    max_drawdown_fraction: float

    @staticmethod
    def parse(label: str, value: object) -> MonitoringThresholds:
        obj = require_mapping(label, value)
        require_exact_keys(label, obj, _THRESHOLD_KEYS)
        return MonitoringThresholds(
            max_staleness_seconds=require_nonnegative_int(
                f"{label}.max_staleness_seconds", obj["max_staleness_seconds"]
            ),
            max_drawdown_fraction=require_unit_interval(
                f"{label}.max_drawdown_fraction", obj["max_drawdown_fraction"]
            ),
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "max_staleness_seconds": self.max_staleness_seconds,
            "max_drawdown_fraction": self.max_drawdown_fraction,
        }


def staleness_alert(
    *, as_of: object, last_bar_time: object, max_staleness_seconds: int
) -> Alert | None:
    """A warning if the newest observed bar is older than the staleness budget."""
    now = parse_timestamp("as_of", as_of)
    last = parse_timestamp("last_bar_time", last_bar_time)
    gap = (now - last).total_seconds()
    if gap > max_staleness_seconds:
        return Alert(
            as_of=canonical_timestamp("as_of", now),
            severity=WARNING,
            code=STALE_DATA_CODE,
            message=f"market data is {gap:.0f}s stale (budget {max_staleness_seconds}s)",
        )
    return None


def drawdown_alert(
    *, as_of: object, equity: float, peak_equity: float, max_drawdown_fraction: float
) -> Alert | None:
    """A critical alert if equity has fallen more than the allowed fraction below its peak."""
    eq = require_positive_real("equity", equity)
    peak = require_positive_real("peak_equity", peak_equity)
    if peak <= 0.0:
        raise MonitoringError("peak equity must be positive to evaluate drawdown")
    drawdown = max(0.0, (peak - eq) / peak)
    if drawdown > max_drawdown_fraction:
        return Alert(
            as_of=canonical_timestamp("as_of", as_of),
            severity=CRITICAL,
            code=DRAWDOWN_CODE,
            message=f"drawdown {drawdown:.4f} exceeds limit {max_drawdown_fraction:.4f}",
        )
    return None


def risk_breach_alert(*, as_of: object, breached_limits: tuple[str, ...]) -> Alert | None:
    """A critical alert naming the hard limits a risk decision breached (if any)."""
    if not breached_limits:
        return None
    return Alert(
        as_of=canonical_timestamp("as_of", as_of),
        severity=CRITICAL,
        code=RISK_BREACH_CODE,
        message=f"risk limits breached: {', '.join(breached_limits)}",
    )


def kill_switch_alert(*, as_of: object, reason: str) -> Alert:
    """A critical alert recording that the latching kill switch tripped."""
    return Alert(
        as_of=canonical_timestamp("as_of", as_of),
        severity=CRITICAL,
        code=KILL_SWITCH_CODE,
        message=f"kill switch tripped: {require_nonempty_str('reason', reason)}",
    )
