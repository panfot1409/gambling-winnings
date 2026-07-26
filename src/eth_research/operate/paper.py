"""The paced paper-trading loop: genuine bars, genuine signals, the accepted engine.

One iteration is one bar. For bar ``i`` the loop:

1. waits until that bar is due on the operator's own schedule (never on Cockpit's);
2. hands the accepted runner every bar up to and including ``i`` and takes back the authoritative
   :class:`~eth_research.shadow.runner.ShadowRunResult`;
3. reports whatever that result says happened at bar ``i``.

Step 2 re-derives the run from its first bar every iteration rather than mutating a carried state
machine. That is a deliberate choice, and the reason is worth stating plainly: the accepted runner
is a single-pass function whose source is hash-frozen by the V2C qualification freeze, so it has no
resume entry point and may not grow one here. Re-deriving keeps *one* implementation of the
pipeline — no incremental copy to drift out of step with it — and the platform's determinism makes
each re-derivation an exact extension of the last (``tests/test_cockpit_integration.py`` proves the
prefix property, and the runner's own ``test_runner_is_deterministic`` proves the ground for it).
The cost is a re-run per bar, measured and logged on every iteration and reported to the operator;
at the default bar budget it is a small fraction of one bar interval.

Nothing in this module can be influenced by Cockpit. The reporter is called only *after* the result
exists, every reporting call returns ``None``, and the value passed to the runner as its execution
adapter is the platform's own :class:`~eth_research.shadow.adapter.PaperExecutionAdapter`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from eth_research.cockpit.reporter import RUN_FAILED_CODE, CockpitReporter
from eth_research.data.synthetic import make_synthetic_ohlcv
from eth_research.shadow.adapter import PaperExecutionAdapter
from eth_research.shadow.domain import SHADOW_MODES, SYNTHETIC_DEMO, InstrumentId
from eth_research.shadow.journal import (
    ALERT_RAISED,
    FILL_RECORDED,
    RISK_DECIDED,
    SIGNAL_EMITTED,
    JournalEvent,
)
from eth_research.shadow.market_data import MarketDataEnvelope
from eth_research.shadow.monitoring import Alert, MonitoringThresholds
from eth_research.shadow.paper import PaperAccount, PaperFill
from eth_research.shadow.risk import RiskDecision, RiskLimits
from eth_research.shadow.runner import ShadowConfig, ShadowRunResult, ShadowStep, run_shadow
from eth_research.shadow.signal import SignalEnvelope
from eth_research.v2.candidates import (
    MEANREV_SPEC,
    TREND_SPEC,
    V2A_CANDIDATES,
    VOL_SCALED_SPEC,
    CandidateSpecification,
    assert_candidate_set_valid,
    meanrev_signal_at,
    trend_signal_at,
)
from eth_research.v2.strict import (
    V2ValidationError,
    require_mapping,
    require_positive_real,
    require_unit_interval,
)

log = logging.getLogger("eth_research.operate")

#: Candidates whose *complete* exposure is a causal scalar function of trailing closes, and which
#: can therefore be evaluated one bar at a time exactly as the research engine evaluates them.
SUPPORTED_CANDIDATE_IDS: tuple[str, ...] = (MEANREV_SPEC.candidate_id, TREND_SPEC.candidate_id)

#: ``vol_scaled_hold_drawdown_guard`` is excluded on purpose: its signal is "always long" and every
#: bit of its actual exposure comes from the reviewed fractional risk overlay (volatility targeting
#: plus a drawdown breaker), which is a frame-level computation, not a scalar oracle. Emitting its
#: bare signal would report a full position the candidate does not in fact hold.
_UNSUPPORTED_REASON: dict[str, str] = {
    VOL_SCALED_SPEC.candidate_id: (
        "its exposure comes from the fractional risk overlay, not from a scalar signal oracle; "
        "running it bar-by-bar here would misreport its position"
    )
}

#: Daily bars: the frequency the research candidates are pre-registered against.
DEFAULT_BAR_SECONDS: int = 86_400
#: One hour of operation at the default three-second pace. Bounds the per-bar re-derivation cost.
DEFAULT_MAX_BARS: int = 1_200
#: Leading bars replayed at full speed so a dashboard is not empty when an operator first looks.
DEFAULT_BACKFILL_BARS: int = 60
DEFAULT_STARTING_CASH: float = 10_000.0
DEFAULT_INSTRUMENT: str = "eth_usd"
DEFAULT_SOURCE: str = "synthetic"

_WARMUP_MARGIN_BARS: int = 8


class OperatorError(V2ValidationError):
    """The operator was asked for something it cannot honestly run."""


@dataclass(frozen=True, slots=True)
class SignalSource:
    """A pre-registered candidate's causal signal, evaluated one bar at a time."""

    candidate_id: str
    warmup_bars: int
    oracle: Callable[[np.ndarray], float]

    def weight_at(self, closes: np.ndarray) -> float:
        """The candidate's target weight given every close up to and including the latest one."""
        return float(self.oracle(closes))


def _spec_int(spec: CandidateSpecification, key: str) -> int:
    value = spec.fixed_parameters.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise OperatorError(f"candidate {spec.candidate_id!r} parameter {key!r} is not an integer")
    return value


def _spec_float(spec: CandidateSpecification, key: str) -> float:
    value = spec.fixed_parameters.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise OperatorError(f"candidate {spec.candidate_id!r} parameter {key!r} is not a number")
    return float(value)


def build_signal_source(candidate_id: str) -> SignalSource:
    """Bind a pre-registered candidate to its causal oracle, with the candidate's own parameters.

    The parameters are read from the committed :class:`CandidateSpecification`, never restated
    here, so the loop cannot silently run a differently-parameterized strategy than the one that
    was pre-registered. The whole pre-registered set is re-validated first.
    """
    assert_candidate_set_valid(V2A_CANDIDATES)
    reason = _UNSUPPORTED_REASON.get(candidate_id)
    if reason is not None:
        raise OperatorError(f"candidate {candidate_id!r} cannot be operated bar-by-bar: {reason}")
    if candidate_id == MEANREV_SPEC.candidate_id:
        lookback = _spec_int(MEANREV_SPEC, "lookback")
        entry_z = _spec_float(MEANREV_SPEC, "entry_z")

        def _meanrev(closes: np.ndarray) -> float:
            return meanrev_signal_at(closes, lookback=lookback, entry_z=entry_z)

        return SignalSource(
            candidate_id=MEANREV_SPEC.candidate_id, warmup_bars=lookback, oracle=_meanrev
        )
    if candidate_id == TREND_SPEC.candidate_id:
        horizon = _spec_int(TREND_SPEC, "horizon")

        def _trend(closes: np.ndarray) -> float:
            return trend_signal_at(closes, horizon=horizon)

        return SignalSource(
            candidate_id=TREND_SPEC.candidate_id, warmup_bars=horizon, oracle=_trend
        )
    raise OperatorError(
        f"unknown candidate {candidate_id!r}; operable candidates are "
        f"{list(SUPPORTED_CANDIDATE_IDS)}"
    )


@dataclass(frozen=True, slots=True)
class OperatorConfig:
    """Everything the loop needs, all of it fixed before the first bar."""

    candidate_id: str = MEANREV_SPEC.candidate_id
    instrument_symbol: str = DEFAULT_INSTRUMENT
    mode: str = SYNTHETIC_DEMO
    starting_cash: float = DEFAULT_STARTING_CASH
    max_target_weight: float = 1.0
    max_weight_step: float = 1.0
    max_drawdown_fraction: float = 0.5
    bar_seconds: int = DEFAULT_BAR_SECONDS
    max_bars: int = DEFAULT_MAX_BARS
    #: Leading bars replayed at full speed before the loop settles onto its schedule, so an
    #: operator joining a run sees the history that produced the current book rather than an
    #: empty chart. They are the same bars, through the same engine, emitting the same events.
    backfill_bars: int = DEFAULT_BACKFILL_BARS
    interval_seconds: float = 3.0
    seed: int = 1409
    start_price: float = 2_000.0
    volatility: float = 0.02
    drift: float = 0.0002
    series_start: str = "2024-01-01"

    def validate(self) -> None:
        """Refuse a configuration that could not honestly run, before anything starts."""
        if self.mode not in SHADOW_MODES:
            raise OperatorError(f"mode must be one of {sorted(SHADOW_MODES)!r}, got {self.mode!r}")
        if self.max_bars < 1:
            raise OperatorError("max_bars must be at least 1")
        if self.bar_seconds < 1:
            raise OperatorError("bar_seconds must be at least 1")
        if self.interval_seconds < 0.0:
            raise OperatorError("interval_seconds cannot be negative")
        if self.backfill_bars < 0:
            raise OperatorError("backfill_bars cannot be negative")
        if self.backfill_bars > self.max_bars:
            raise OperatorError("backfill_bars cannot exceed max_bars")
        require_positive_real("starting_cash", self.starting_cash)
        require_unit_interval("max_target_weight", self.max_target_weight)
        require_unit_interval("max_weight_step", self.max_weight_step)
        require_unit_interval("max_drawdown_fraction", self.max_drawdown_fraction)

    def shadow_config(self) -> ShadowConfig:
        """The accepted platform's own configuration object, built through its factory."""
        return ShadowConfig.create(
            mode=self.mode,
            instrument=InstrumentId.parse("instrument", self.instrument_symbol),
            candidate_id=self.candidate_id,
            starting_cash=self.starting_cash,
            limits=RiskLimits.parse(
                "limits",
                {
                    "max_target_weight": self.max_target_weight,
                    "max_weight_step": self.max_weight_step,
                },
            ),
            thresholds=MonitoringThresholds.parse(
                "thresholds",
                {
                    # Two bar intervals: a bar that is more than one whole bar late is genuinely
                    # stale, and a bar that arrives on schedule never is.
                    "max_staleness_seconds": 2 * self.bar_seconds,
                    "max_drawdown_fraction": self.max_drawdown_fraction,
                },
            ),
        )


@dataclass(frozen=True, slots=True)
class OperatorOutcome:
    """What the process did, for the caller's exit code and the closing log line."""

    bars_processed: int
    fills: int
    kill_tripped: bool
    final_equity: float
    stopped_early: bool
    slowest_cycle_seconds: float
    slowest_engine_seconds: float
    slowest_report_seconds: float


def build_steps(config: OperatorConfig, source: SignalSource) -> tuple[ShadowStep, ...]:
    """Build the bar series and the candidate's signal for each bar, causally.

    The bars come from the repository's deterministic synthetic generator — the same offline data
    mode the rest of the toolkit runs on, so a run reproduces exactly. The signal for bar ``t`` is
    the candidate's oracle applied to closes ``[0..t]`` and nothing later; the platform's as-of
    clock refuses a signal stamped after the bar anyway, so look-ahead is impossible twice over.
    """
    config.validate()
    warmup = source.warmup_bars + _WARMUP_MARGIN_BARS
    n_periods = config.max_bars + warmup
    frame = make_synthetic_ohlcv(
        n_periods=n_periods,
        freq=f"{config.bar_seconds}s",
        start=config.series_start,
        start_price=config.start_price,
        drift=config.drift,
        volatility=config.volatility,
        seed=config.seed,
    )
    closes = frame["close"].to_numpy(dtype=float)
    steps: list[ShadowStep] = []
    for offset in range(config.max_bars):
        index = warmup + offset
        row = frame.iloc[index]
        stamp = frame.index[index]
        close_time = pd.Timestamp(stamp).isoformat()
        envelope = MarketDataEnvelope.parse(
            f"bar[{offset}]",
            {
                "instrument": config.instrument_symbol,
                "close_time": close_time,
                "source": DEFAULT_SOURCE,
                "sequence": offset,
                "bar": {
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                },
            },
        )
        weight = source.weight_at(closes[: index + 1])
        signal = SignalEnvelope.create(
            candidate_id=source.candidate_id,
            instrument=envelope.instrument,
            as_of=close_time,
            target_weight=weight,
        )
        steps.append(ShadowStep(envelope=envelope, signal=signal))
    return tuple(steps)


def _decision_from_payload(payload: dict[str, object]) -> RiskDecision:
    """Rebuild the risk decision the engine journalled, exactly as it recorded it."""
    obj = require_mapping("risk_decided", payload)
    return RiskDecision(
        requested_weight=require_unit_interval("requested_weight", obj["requested_weight"]),
        approved_weight=require_unit_interval("approved_weight", obj["approved_weight"]),
        breached_limits=_string_tuple(obj.get("breached_limits")),
        throttled_limits=_string_tuple(obj.get("throttled_limits")),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _account_after(fill: PaperFill) -> PaperAccount:
    """The account the fill left behind, exactly as the fill recorded it."""
    return PaperAccount(cash=fill.cash_after, units=fill.units_after)


class BarReporter:
    """Reports one bar's authoritative events, tracking only how far it has already reported."""

    __slots__ = ("_fills_reported", "_journal_reported", "_reporter", "_units_reported")

    def __init__(self, reporter: CockpitReporter) -> None:
        self._reporter = reporter
        self._journal_reported = 0
        self._fills_reported = 0
        self._units_reported: float | None = None

    def report(self, result: ShadowRunResult, step: ShadowStep) -> None:
        """Emit Cockpit events for whatever the latest bar added to the authoritative run."""
        body = result.journal.events[:-1]  # everything but the terminal run_completed
        fresh = body[self._journal_reported :]
        self._journal_reported = len(body)

        # The weight the book was carrying *before* this bar is the target of the last fill it
        # recorded before this bar — read from the platform's own fill records, not mirrored.
        previous_weight = (
            result.fills[self._fills_reported - 1].target_weight
            if self._fills_reported > 0
            else 0.0
        )
        self._fills_reported = len(result.fills)

        decision: RiskDecision | None = None
        for event in fresh:
            if event.event_type == SIGNAL_EMITTED:
                # The journal records what the engine saw; the envelope beside it is the object the
                # candidate produced. They must agree, and if they ever did not, the run is not
                # what it claims to be.
                journalled = require_unit_interval(
                    "signal_emitted.target_weight", event.payload["target_weight"]
                )
                if journalled != step.signal.target_weight:
                    raise OperatorError(
                        f"journalled signal weight {journalled!r} does not match the signal "
                        f"envelope {step.signal.target_weight!r}"
                    )
            elif event.event_type == RISK_DECIDED:
                decision = _decision_from_payload(event.payload)
            elif event.event_type == ALERT_RAISED:
                self._reporter.report_alert(Alert.parse("alert_raised", event.payload))
            elif event.event_type == FILL_RECORDED:
                self._report_fill(event)

        if decision is not None:
            self._reporter.report_signal(
                signal=step.signal, decision=decision, current_weight=previous_weight
            )

        # Equity every bar, marked by the platform's own account at this bar's close. On a bar
        # with a fill this is the fill's equity (a rebalance conserves equity at one price); on a
        # held bar it is the held book's mark. One source, no second model.
        close = step.envelope.bar.close
        self._reporter.report_equity(
            equity=result.final_account.equity(close), as_of=step.envelope.close_time
        )

    def _report_fill(self, event: JournalEvent) -> None:
        fill = PaperFill.parse("fill_recorded", event.payload)
        if fill.traded_units != 0.0:
            # The journal entry hash is unique, tamper-evident, and stable across a redelivery.
            self._reporter.report_trade(fill=fill, trade_id=event.entry_hash)
        if self._units_reported is None or fill.units_after != self._units_reported:
            self._reporter.report_position(
                account=_account_after(fill), price=fill.price, as_of=fill.as_of
            )
            self._units_reported = fill.units_after


def run_operator(
    config: OperatorConfig,
    reporter: CockpitReporter,
    stop: threading.Event,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], bool] | None = None,
) -> OperatorOutcome:
    """Run the paced paper loop until the series ends or the process is asked to stop."""
    config.validate()
    source = build_signal_source(config.candidate_id)
    steps = build_steps(config, source)
    shadow_config = config.shadow_config()
    wait = sleeper if sleeper is not None else stop.wait

    bar_reporter = BarReporter(reporter)
    result: ShadowRunResult | None = None
    started = monotonic()
    slowest_cycle = 0.0
    slowest_engine = 0.0
    slowest_report = 0.0
    processed = 0
    stopped_early = False

    log.info(
        "operating %s on %s: %d bars (%d backfilled), %.1fs pace, mode=%s, starting cash %.2f",
        config.candidate_id,
        config.instrument_symbol,
        len(steps),
        config.backfill_bars,
        config.interval_seconds,
        config.mode,
        config.starting_cash,
    )

    for index in range(len(steps)):
        # Backfill bars are history: they are replayed as fast as the engine can derive them, and
        # only the bars after them are paced onto the operator's schedule.
        paced = max(0, index - config.backfill_bars + 1)
        due = started + paced * config.interval_seconds
        delay = due - monotonic()
        if delay > 0.0 and wait(delay):
            stopped_early = True
            break
        if stop.is_set():
            stopped_early = True
            break

        cycle_started = monotonic()
        try:
            engine_started = monotonic()
            # The accepted runner, unmodified, over every bar so far. A fresh adapter each time:
            # the intents it records belong to this derivation, and it is the platform's own
            # non-routing paper adapter — nothing else is ever driven.
            result = run_shadow(shadow_config, steps[: index + 1], adapter=PaperExecutionAdapter())
            engine_seconds = monotonic() - engine_started
        except Exception as error:
            log.exception("shadow run failed at bar %d", index)
            reporter.report_error(
                code=RUN_FAILED_CODE,
                message=f"{type(error).__name__}: {error}",
                fatal=True,
                context={"bar": index},
            )
            raise

        report_started = monotonic()
        bar = steps[index].envelope
        bar_reporter.report(result, steps[index])
        report_seconds = monotonic() - report_started

        processed = index + 1
        cycle_seconds = monotonic() - cycle_started
        slowest_cycle = max(slowest_cycle, cycle_seconds)
        slowest_engine = max(slowest_engine, engine_seconds)
        slowest_report = max(slowest_report, report_seconds)

        log.info(
            "bar %d | close %.2f | weight %.3f | equity %.2f | engine %.1fms | telemetry %.2fms "
            "| cycle %.1fms | %s",
            processed,
            bar.bar.close,
            steps[index].signal.target_weight,
            result.final_account.equity(bar.bar.close),
            engine_seconds * 1000.0,
            report_seconds * 1000.0,
            cycle_seconds * 1000.0,
            reporter.stats_snapshot(),
        )

        if (
            config.interval_seconds > 0.0
            and index >= config.backfill_bars
            and cycle_seconds > config.interval_seconds
        ):
            # A genuine operational condition: the loop is not keeping up with its own schedule.
            reporter.report_warning(
                code="slow_trading_cycle",
                message=(
                    f"bar {processed} took {cycle_seconds:.3f}s, longer than the "
                    f"{config.interval_seconds:.3f}s bar interval"
                ),
                context={"bar": processed, "cycle_seconds": round(cycle_seconds, 6)},
            )

    final_close = steps[max(0, processed - 1)].envelope.bar.close
    final_equity = (
        result.final_account.equity(final_close) if result is not None else config.starting_cash
    )
    outcome = OperatorOutcome(
        bars_processed=processed,
        fills=len(result.fills) if result is not None else 0,
        kill_tripped=result.kill_tripped if result is not None else False,
        final_equity=final_equity,
        stopped_early=stopped_early,
        slowest_cycle_seconds=slowest_cycle,
        slowest_engine_seconds=slowest_engine,
        slowest_report_seconds=slowest_report,
    )
    log.info(
        "stopped after %d bar(s): %d fill(s), kill_tripped=%s, equity %.2f "
        "(slowest cycle %.1fms, engine %.1fms, telemetry %.2fms)",
        outcome.bars_processed,
        outcome.fills,
        outcome.kill_tripped,
        outcome.final_equity,
        outcome.slowest_cycle_seconds * 1000.0,
        outcome.slowest_engine_seconds * 1000.0,
        outcome.slowest_report_seconds * 1000.0,
    )
    return outcome


__all__ = [
    "DEFAULT_BACKFILL_BARS",
    "DEFAULT_BAR_SECONDS",
    "DEFAULT_INSTRUMENT",
    "DEFAULT_MAX_BARS",
    "DEFAULT_SOURCE",
    "DEFAULT_STARTING_CASH",
    "SUPPORTED_CANDIDATE_IDS",
    "BarReporter",
    "OperatorConfig",
    "OperatorError",
    "OperatorOutcome",
    "SignalSource",
    "build_signal_source",
    "build_steps",
    "run_operator",
]
