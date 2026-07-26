"""Turn authoritative shadow-run state into Cockpit events, and nothing else.

Every method here takes values the shadow platform already computed — a signal envelope, a risk
decision, a paper fill, the paper account, an alert — and hands them to the telemetry client. The
reporter derives no exposure, keeps no running balance, and re-prices nothing: there is exactly one
accounting model in this repository (:func:`eth_research.shadow.paper.rebalance`) and the reporter
reads its output rather than shadowing it.

Two properties are load-bearing and are enforced by tests:

* **every method returns ``None``.** The client's emit methods return ``bool``; those returns are
  swallowed here so that no caller can branch on whether monitoring worked.
* **every method swallows every exception.** The shipped client already promises never to raise,
  but a reporter is not the place to find out that a promise was broken.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from eth_research.shadow.monitoring import CRITICAL, WARNING, Alert
from eth_research.shadow.paper import PaperAccount, PaperFill
from eth_research.shadow.risk import RiskDecision
from eth_research.shadow.signal import SignalEnvelope

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nardis_telemetry import PositionSide, SignalAction, TelemetryClient, TradeSide

log = logging.getLogger("eth_research.cockpit")

#: The quote currency of the instruments this platform observes (``eth_usd``, ``btc_usd``).
DEFAULT_CURRENCY: str = "USD"

#: Cockpit codes for the two failure classes the trader reports itself, as opposed to the
#: monitoring alerts the shadow platform raises (which carry their own codes).
RUN_FAILED_CODE: str = "shadow_run_failed"
STARTUP_FAILED_CODE: str = "trader_startup_failed"


def _as_datetime(as_of: str) -> datetime | None:
    """Decode a shadow ``as_of`` stamp so the event carries the run's time, not the wall clock.

    Returns ``None`` — meaning "let the client stamp it" — rather than raising on anything odd.
    """
    try:
        moment = datetime.fromisoformat(as_of)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _signal_action(*, approved_weight: float, current_weight: float) -> SignalAction:
    """What the book is about to do, from the two weights the platform already decided."""
    if approved_weight > current_weight:
        return "buy"
    if approved_weight < current_weight:
        return "sell"
    return "hold"


def _position_side(units: float) -> PositionSide:
    """The platform is long-only, so a position is long or it is flat."""
    return "long" if units > 0.0 else "flat"


def _trade_side(traded_units: float) -> TradeSide:
    return "buy" if traded_units > 0.0 else "sell"


def _decision_reason(decision: RiskDecision) -> str:
    """A one-line record of what the risk engine did, built only from the decision itself."""
    parts = [
        f"requested_weight={decision.requested_weight:.6f}",
        f"approved_weight={decision.approved_weight:.6f}",
    ]
    if decision.breached_limits:
        parts.append(f"breached={','.join(decision.breached_limits)}")
    if decision.throttled_limits:
        parts.append(f"throttled={','.join(decision.throttled_limits)}")
    return " ".join(parts)


class CockpitReporter:
    """Reports a paper run to Cockpit. Inert when built without a client."""

    __slots__ = ("_client", "_currency", "_symbol")

    def __init__(
        self, client: TelemetryClient | None, *, symbol: str, currency: str = DEFAULT_CURRENCY
    ) -> None:
        self._client = client
        self._symbol = symbol
        self._currency = currency

    @staticmethod
    def disabled(*, symbol: str = "") -> CockpitReporter:
        """A reporter that does nothing, for a trader running without Cockpit."""
        return CockpitReporter(None, symbol=symbol)

    @property
    def active(self) -> bool:
        """Whether a client is attached. Informational: no trading path may branch on it."""
        return self._client is not None

    @property
    def dropped_events(self) -> int:
        """How many events the client gave up on, for the operator's own log line."""
        client = self._client
        if client is None:
            return 0
        try:
            return int(client.stats.dropped)
        except Exception:
            return 0

    def stats_snapshot(self) -> dict[str, int]:
        """The client's counters, or an empty mapping when there is no client."""
        client = self._client
        if client is None:
            return {}
        try:
            return {str(name): int(value) for name, value in client.stats.snapshot().items()}
        except Exception:
            return {}

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #
    def register(self) -> None:
        """Identify this bot to Cockpit. A Cockpit that is down is not a startup failure."""
        client = self._client
        if client is None:
            return
        try:
            bot_id = client.register()
        except Exception as error:
            log.warning("telemetry registration failed: %s", error)
            return
        if bot_id is None:
            log.warning("cockpit did not identify this bot yet; telemetry will catch up")
        else:
            log.info("reporting to cockpit as bot %s", bot_id)

    def close(self, timeout: float = 5.0) -> None:
        """Give the client a bounded chance to drain, then let the process exit."""
        client = self._client
        if client is None:
            return
        try:
            client.close(timeout=timeout)
        except Exception as error:
            log.warning("telemetry shutdown was not clean: %s", error)

    # ----------------------------------------------------------------- #
    # Events
    # ----------------------------------------------------------------- #
    def heartbeat(self, *, uptime_seconds: int) -> None:
        """Liveness. Emitted by the independent worker, never by the trading loop."""
        client = self._client
        if client is None:
            return
        try:
            client.heartbeat(uptime_seconds=int(uptime_seconds))
        except Exception as error:
            log.warning("telemetry heartbeat failed: %s", error)

    def report_signal(
        self, *, signal: SignalEnvelope, decision: RiskDecision, current_weight: float
    ) -> None:
        """The candidate's intent and what the risk engine allowed, both as decided."""
        client = self._client
        if client is None:
            return
        try:
            client.signal(
                symbol=self._symbol,
                action=_signal_action(
                    approved_weight=decision.approved_weight, current_weight=current_weight
                ),
                # The candidate's own target weight in [0, 1] — its intended fraction of capital.
                confidence=signal.target_weight,
                strategy=signal.candidate_id,
                reason=_decision_reason(decision),
                at=_as_datetime(signal.as_of),
            )
        except Exception as error:
            log.warning("telemetry signal failed: %s", error)

    def report_trade(self, *, fill: PaperFill, trade_id: str) -> None:
        """One paper fill, exactly as the paper book recorded it.

        ``trade_id`` is the fill's journal entry hash: unique, derived from the hash-chained
        record itself, and stable across a retry, so a redelivery deduplicates rather than
        double-counting.
        """
        client = self._client
        if client is None:
            return
        try:
            client.trade(
                trade_id=trade_id,
                symbol=self._symbol,
                side=_trade_side(fill.traded_units),
                quantity=abs(fill.traded_units),
                price=fill.price,
                # The paper book is a clean mark-to-market baseline: execution costs are a
                # research-layer concept and are deliberately not modelled, so the fee is zero
                # because there is no fee, not because one was dropped.
                fee=0.0,
                order_type="market",
                at=_as_datetime(fill.as_of),
            )
        except Exception as error:
            log.warning("telemetry trade failed: %s", error)

    def report_position(self, *, account: PaperAccount, price: float, as_of: str) -> None:
        """The book's position after the transition, taken from the account itself.

        ``price`` is the close the position was rebalanced at. The paper book holds cash and units
        only — it tracks no cost basis — so the rebalance price *is* the price those units were
        established at; no average is invented here.
        """
        client = self._client
        if client is None:
            return
        try:
            client.position(
                symbol=self._symbol,
                side=_position_side(account.units),
                quantity=account.units,
                average_price=price,
                exposure_value=account.units * price,
                at=_as_datetime(as_of),
            )
        except Exception as error:
            log.warning("telemetry position failed: %s", error)

    def report_equity(self, *, equity: float, as_of: str) -> None:
        """The book's equity, marked by the paper account at the bar's close.

        Realized and unrealized PnL are omitted rather than guessed: the paper book does not
        decompose them, and a reporter that computed its own would be a second accounting model.
        """
        client = self._client
        if client is None:
            return
        try:
            client.equity(equity=equity, currency=self._currency, at=_as_datetime(as_of))
        except Exception as error:
            log.warning("telemetry equity failed: %s", error)

    def report_alert(self, alert: Alert) -> None:
        """A monitoring alert the shadow platform raised, mapped to Cockpit's two severities.

        Cockpit distinguishes warnings from errors. A staleness warning is a warning; a drawdown
        breach, a risk-limit breach, and a kill-switch trip are operational errors — serious, but
        not fatal to the process, which is still running and still correct.
        """
        client = self._client
        if client is None:
            return
        context: dict[str, Any] = {"severity": alert.severity}
        try:
            if alert.severity == WARNING:
                client.warning(
                    code=alert.code,
                    message=alert.message,
                    context=context,
                    at=_as_datetime(alert.as_of),
                )
            elif alert.severity == CRITICAL:
                client.error(
                    code=alert.code,
                    message=alert.message,
                    context=context,
                    fatal=False,
                    at=_as_datetime(alert.as_of),
                )
            else:
                client.warning(
                    code=alert.code,
                    message=alert.message,
                    context=context,
                    at=_as_datetime(alert.as_of),
                )
        except Exception as error:
            log.warning("telemetry alert failed: %s", error)

    def report_warning(self, *, code: str, message: str, context: dict[str, Any] | None) -> None:
        """An operational warning the trader raised itself."""
        client = self._client
        if client is None:
            return
        try:
            client.warning(code=code, message=message, context=context)
        except Exception as error:
            log.warning("telemetry warning failed: %s", error)

    def report_error(
        self, *, code: str, message: str, fatal: bool, context: dict[str, Any] | None = None
    ) -> None:
        """An exception the trader caught, or the one that is about to end the process."""
        client = self._client
        if client is None:
            return
        try:
            client.error(code=code, message=message, context=context, fatal=fatal)
        except Exception as error:
            log.warning("telemetry error report failed: %s", error)


__all__ = [
    "DEFAULT_CURRENCY",
    "RUN_FAILED_CODE",
    "STARTUP_FAILED_CODE",
    "CockpitReporter",
]
