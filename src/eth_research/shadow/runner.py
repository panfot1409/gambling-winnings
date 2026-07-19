"""The deterministic shadow runner: the one place the whole signal-only pipeline is wired together.

Given a config and a sequence of ``(market-data envelope, signal)`` steps, the runner processes each
step strictly in time order:

1. advance the as-of clock to the bar's close (never backwards);
2. reveal the bar and require the signal to be valid at or before the frontier (no look-ahead);
3. clamp the signal through the risk engine; a hard breach trips the latching kill switch;
4. while the kill switch is clear, dispatch the approved intent to the (paper) adapter and rebalance
   the paper book; while it is tripped, hold — no new exposure;
5. run monitoring (staleness, drawdown) and let a critical drawdown trip the kill switch;
6. journal every step into the append-only hash chain.

Every input is explicit and every step is a pure transition, so a run is byte-reproducible and its
journal + final checkpoint fully describe what happened. Nothing here connects, orders, or settles.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_research.shadow.adapter import (
    ExecutionIntent,
    PaperExecutionAdapter,
    ShadowExecutionAdapter,
)
from eth_research.shadow.checkpoint import ShadowCheckpoint
from eth_research.shadow.clock import AsOfClock
from eth_research.shadow.domain import (
    InstrumentId,
    ShadowDomainError,
    require_shadow_mode,
)
from eth_research.shadow.journal import (
    ALERT_RAISED,
    BAR_OBSERVED,
    FILL_RECORDED,
    KILL_TRIPPED,
    RISK_DECIDED,
    RUN_COMPLETED,
    RUN_STARTED,
    SIGNAL_EMITTED,
    ShadowJournal,
)
from eth_research.shadow.kill_switch import LatchingKillSwitch
from eth_research.shadow.market_data import MarketDataEnvelope
from eth_research.shadow.monitoring import (
    Alert,
    MonitoringThresholds,
    drawdown_alert,
    kill_switch_alert,
    risk_breach_alert,
)
from eth_research.shadow.paper import PaperAccount, PaperFill, rebalance
from eth_research.shadow.risk import RiskLimitEngine, RiskLimits
from eth_research.shadow.signal import SignalEnvelope
from eth_research.v2.strict import require_positive_real, require_slug


class ShadowRunError(ShadowDomainError):
    """A shadow run could not proceed (mismatched instrument, empty steps, etc.)."""


@dataclass(frozen=True, slots=True)
class ShadowConfig:
    """Everything a run needs that is fixed before it starts."""

    mode: str
    instrument: InstrumentId
    candidate_id: str
    starting_cash: float
    limits: RiskLimits
    thresholds: MonitoringThresholds

    @staticmethod
    def create(
        *,
        mode: str,
        instrument: InstrumentId,
        candidate_id: str,
        starting_cash: float,
        limits: RiskLimits,
        thresholds: MonitoringThresholds,
    ) -> ShadowConfig:
        return ShadowConfig(
            mode=require_shadow_mode("mode", mode),
            instrument=instrument,
            candidate_id=require_slug("candidate_id", candidate_id),
            starting_cash=require_positive_real("starting_cash", starting_cash),
            limits=limits,
            thresholds=thresholds,
        )


@dataclass(frozen=True, slots=True)
class ShadowStep:
    """One aligned observation: the bar the operator sees and the signal valid as-of it."""

    envelope: MarketDataEnvelope
    signal: SignalEnvelope


@dataclass(frozen=True, slots=True)
class ShadowRunResult:
    """The full, reproducible outcome of a shadow run."""

    journal: ShadowJournal
    final_account: PaperAccount
    peak_equity: float
    bars_processed: int
    kill_tripped: bool
    fills: tuple[PaperFill, ...]
    alerts: tuple[Alert, ...]
    checkpoint: ShadowCheckpoint


def _raise_and_journal_alert(journal: ShadowJournal, alerts: list[Alert], alert: Alert) -> None:
    alerts.append(alert)
    journal.append(ALERT_RAISED, as_of=alert.as_of, payload=alert.to_canonical())


def run_shadow(
    config: ShadowConfig,
    steps: tuple[ShadowStep, ...],
    *,
    adapter: ShadowExecutionAdapter | None = None,
) -> ShadowRunResult:
    """Run the signal-only pipeline over ``steps``; return the journalled, reproducible result."""
    if not steps:
        raise ShadowRunError("a shadow run needs at least one step")
    exec_adapter = adapter if adapter is not None else PaperExecutionAdapter()

    clock = AsOfClock.unstarted()
    kill = LatchingKillSwitch.armed()
    engine = RiskLimitEngine(config.limits)
    journal = ShadowJournal.empty()
    account = PaperAccount.opening(config.starting_cash)
    peak_equity = config.starting_cash
    current_weight = 0.0
    fills: list[PaperFill] = []
    alerts: list[Alert] = []

    first_as_of = steps[0].envelope.close_time
    journal.append(
        RUN_STARTED,
        as_of=first_as_of,
        payload={
            "mode": config.mode,
            "instrument": config.instrument.to_canonical(),
            "candidate_id": config.candidate_id,
            "starting_cash": config.starting_cash,
            "adapter_channel": exec_adapter.channel,
        },
    )

    for index, step in enumerate(steps):
        envelope, signal = step.envelope, step.signal
        if envelope.instrument != config.instrument:
            raise ShadowRunError(f"step[{index}] instrument does not match the run instrument")
        if signal.instrument != config.instrument:
            raise ShadowRunError(f"step[{index}] signal instrument does not match the run")
        if signal.candidate_id != config.candidate_id:
            raise ShadowRunError(f"step[{index}] signal candidate does not match the run")

        clock.advance_to(envelope.close_time)
        bar = envelope.reveal_under(clock)
        clock.require_visible("signal.as_of", signal.as_of)
        stamp = envelope.close_time

        journal.append(
            BAR_OBSERVED,
            as_of=stamp,
            payload={"sequence": envelope.sequence, "close": bar.close},
        )
        journal.append(SIGNAL_EMITTED, as_of=stamp, payload={"target_weight": signal.target_weight})

        decision = engine.evaluate(
            requested_weight=signal.target_weight, current_weight=current_weight
        )
        journal.append(RISK_DECIDED, as_of=stamp, payload=decision.to_canonical())
        if decision.is_breach:
            _raise_and_journal_alert(
                journal,
                alerts,
                risk_breach_alert(as_of=stamp, breached_limits=decision.breached_limits)
                or Alert(as_of=stamp, severity="critical", code="risk_limit_breach", message=""),
            )
            if not kill.is_tripped:
                kill.trip(f"risk breach: {', '.join(decision.breached_limits)}")
                journal.append(KILL_TRIPPED, as_of=stamp, payload={"reason": kill.reason or ""})
                _raise_and_journal_alert(
                    journal, alerts, kill_switch_alert(as_of=stamp, reason=kill.reason or "")
                )

        if kill.is_tripped:
            # Latched: hold the current book, place no intent, mark equity at the new close.
            equity = account.equity(bar.close)
        else:
            intent = ExecutionIntent.create(
                candidate_id=config.candidate_id,
                instrument=config.instrument,
                as_of=stamp,
                approved_weight=decision.approved_weight,
            )
            exec_adapter.dispatch(intent)
            account, fill = rebalance(
                account, as_of=stamp, price=bar.close, target_weight=decision.approved_weight
            )
            fills.append(fill)
            current_weight = decision.approved_weight
            equity = fill.equity_after
            journal.append(FILL_RECORDED, as_of=stamp, payload=fill.to_canonical())

        peak_equity = max(peak_equity, equity)
        drawdown = drawdown_alert(
            as_of=stamp,
            equity=equity,
            peak_equity=peak_equity,
            max_drawdown_fraction=config.thresholds.max_drawdown_fraction,
        )
        if drawdown is not None:
            _raise_and_journal_alert(journal, alerts, drawdown)
            if not kill.is_tripped:
                kill.trip("drawdown breach")
                journal.append(KILL_TRIPPED, as_of=stamp, payload={"reason": kill.reason or ""})

    last_stamp = steps[-1].envelope.close_time
    journal.append(
        RUN_COMPLETED,
        as_of=last_stamp,
        payload={
            "bars_processed": len(steps),
            "kill_tripped": kill.is_tripped,
            "final_equity": account.equity(steps[-1].envelope.bar.close),
        },
    )
    # Build the checkpoint after the completion event so its journal head hash equals the returned
    # journal's head — recover(checkpoint, result.journal) is then internally consistent.
    checkpoint = ShadowCheckpoint(
        mode=config.mode,
        instrument=config.instrument,
        as_of=last_stamp,
        account=account,
        peak_equity=peak_equity,
        kill_tripped=kill.is_tripped,
        kill_reason=kill.reason or "",
        bars_processed=len(steps),
        journal_head_hash=journal.head_hash,
    )

    return ShadowRunResult(
        journal=journal,
        final_account=account,
        peak_equity=peak_equity,
        bars_processed=len(steps),
        kill_tripped=kill.is_tripped,
        fills=tuple(fills),
        alerts=tuple(alerts),
        checkpoint=checkpoint,
    )
