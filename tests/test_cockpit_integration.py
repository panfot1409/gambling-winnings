"""Nardis Cockpit integration: the trader must not be able to tell whether anyone is watching.

The properties proved here are the ones that matter when this code runs beside real capital:

* with telemetry off the loop's outcome is byte-identical to the loop with telemetry on;
* a client that fails, or one whose transport hangs, changes neither the result nor the timing;
* every event Cockpit receives is a value the shadow platform itself computed;
* the heartbeat is tied to the process, not to the trading loop, and shuts down cleanly.

The re-derivation the operator relies on — that running the accepted runner over ``steps[:n]`` is
an exact extension of running it over ``steps[:n-1]`` — is proved first, because everything the
reporter says about position and equity depends on it.
"""

from __future__ import annotations

import inspect
import logging
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd
import pytest

from eth_research.cockpit.client import build_client
from eth_research.cockpit.config import (
    BOT_API_KEY_ENV,
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    HEARTBEAT_INTERVAL_ENV,
    MAX_HEARTBEAT_INTERVAL_SECONDS,
    TELEMETRY_ENABLED_ENV,
    CockpitConfig,
)
from eth_research.cockpit.heartbeat import HeartbeatWorker
from eth_research.cockpit.reporter import RUN_FAILED_CODE, CockpitReporter
from eth_research.operate import paper as operate_paper
from eth_research.operate.__main__ import main as operate_main
from eth_research.operate.paper import (
    BarReporter,
    OperatorConfig,
    OperatorError,
    build_signal_source,
    build_steps,
    run_operator,
)
from eth_research.shadow.domain import ETH_USD, PAPER_SIMULATION, SYNTHETIC_DEMO
from eth_research.shadow.market_data import MarketBar, MarketDataEnvelope
from eth_research.shadow.monitoring import MonitoringThresholds
from eth_research.shadow.risk import RiskLimits
from eth_research.shadow.runner import ShadowConfig, ShadowRunResult, ShadowStep, run_shadow
from eth_research.shadow.signal import SignalEnvelope
from eth_research.v2.candidates import MEANREV_SPEC, TREND_SPEC, VOL_SCALED_SPEC

_T0 = pd.Timestamp("2024-01-01T00:00:00Z")


# --------------------------------------------------------------------------- #
# Doubles
# --------------------------------------------------------------------------- #
@dataclass
class Emitted:
    """One call the reporter made, captured verbatim."""

    kind: str
    kwargs: dict[str, Any]


@dataclass
class RecordingStats:
    enqueued: int = 0
    sent: int = 0
    dropped_queue_full: int = 0
    dropped_rejected: int = 0

    @property
    def dropped(self) -> int:
        return self.dropped_queue_full + self.dropped_rejected

    def snapshot(self) -> dict[str, int]:
        return {"enqueued": self.enqueued, "sent": self.sent}


@dataclass
class RecordingClient:
    """A stand-in with the shipped client's emit surface, recording what it is handed."""

    calls: list[Emitted] = field(default_factory=list)
    stats: RecordingStats = field(default_factory=RecordingStats)
    registered: int = 0
    closed: int = 0

    def _record(self, kind: str, **kwargs: Any) -> bool:
        self.calls.append(Emitted(kind=kind, kwargs=kwargs))
        self.stats.enqueued += 1
        return True

    def register(self) -> str | None:
        self.registered += 1
        return "bot-1"

    def close(self, timeout: float = 5.0) -> None:
        self.closed += 1

    def heartbeat(self, **kwargs: Any) -> bool:
        return self._record("heartbeat", **kwargs)

    def signal(self, **kwargs: Any) -> bool:
        return self._record("signal", **kwargs)

    def position(self, **kwargs: Any) -> bool:
        return self._record("position", **kwargs)

    def trade(self, **kwargs: Any) -> bool:
        return self._record("trade", **kwargs)

    def equity(self, **kwargs: Any) -> bool:
        return self._record("equity", **kwargs)

    def warning(self, **kwargs: Any) -> bool:
        return self._record("warning", **kwargs)

    def error(self, **kwargs: Any) -> bool:
        return self._record("error", **kwargs)

    def of(self, kind: str) -> list[Emitted]:
        return [call for call in self.calls if call.kind == kind]


class ExplodingClient:
    """Every method raises. The trader must not notice."""

    stats: Any = None

    def _boom(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("cockpit exploded")

    register = _boom
    close = _boom
    heartbeat = _boom
    signal = _boom
    position = _boom
    trade = _boom
    equity = _boom
    warning = _boom
    error = _boom


def _reporter(client: Any) -> CockpitReporter:
    return CockpitReporter(client, symbol="eth_usd")


@pytest.fixture
def shipped_client() -> Any:
    """Borrow the real ``nardis_telemetry`` for one test, then put ``sys.modules`` back.

    The client brings ``httpx`` in with it, and ``eth-research doctor`` reports — correctly, and
    in-process — that a network client is imported whenever it finds one in ``sys.modules``. This
    integration is optional and sits outside the offline platform's import closure, so a test that
    borrows the client must not leave it behind for the rest of the session to trip over. (The same
    snapshot-and-restore pattern the platform's own closure tests use.)
    """
    before = set(sys.modules)
    module = pytest.importorskip("nardis_telemetry")
    try:
        yield module
    finally:
        for name in set(sys.modules) - before:
            del sys.modules[name]


# --------------------------------------------------------------------------- #
# Deterministic hand-built runs (for the alert paths the synthetic series does not hit)
# --------------------------------------------------------------------------- #
def _ts(days: int) -> str:
    return (_T0 + pd.Timedelta(days=days)).isoformat()


def _env(seq: int, days: int, close: float) -> MarketDataEnvelope:
    return MarketDataEnvelope(
        instrument=ETH_USD,
        close_time=_ts(days),
        source="synthetic",
        sequence=seq,
        bar=MarketBar(open=close, high=close * 1.01, low=close * 0.99, close=close, volume=1000.0),
    )


def _sig(days: int, weight: float) -> SignalEnvelope:
    return SignalEnvelope.create(
        candidate_id="trend_candidate", instrument=ETH_USD, as_of=_ts(days), target_weight=weight
    )


def _hand_config(*, max_dd: float = 0.9, staleness_seconds: int = 172_800) -> ShadowConfig:
    return ShadowConfig.create(
        mode=PAPER_SIMULATION,
        instrument=ETH_USD,
        candidate_id="trend_candidate",
        starting_cash=10_000.0,
        limits=RiskLimits(max_target_weight=1.0, max_weight_step=1.0),
        thresholds=MonitoringThresholds(
            max_staleness_seconds=staleness_seconds, max_drawdown_fraction=max_dd
        ),
    )


def _drive(
    config: ShadowConfig, steps: tuple[ShadowStep, ...], reporter: CockpitReporter
) -> ShadowRunResult:
    """Drive the run the way the operator does: one bar at a time, reporting as it goes."""
    cursor = BarReporter(reporter)
    result = run_shadow(config, steps[:1])
    for index in range(len(steps)):
        result = run_shadow(config, steps[: index + 1])
        cursor.report(result, steps[index])
    return result


# --------------------------------------------------------------------------- #
# The foundation: re-derivation is an exact extension
# --------------------------------------------------------------------------- #
def _quiet_run() -> tuple[ShadowConfig, tuple[ShadowStep, ...]]:
    steps = tuple(
        ShadowStep(envelope=_env(i, i, 100.0 + i), signal=_sig(i, 0.2 * (i % 5))) for i in range(24)
    )
    return _hand_config(), steps


def _tripping_run() -> tuple[ShadowConfig, tuple[ShadowStep, ...]]:
    """A run that trips the latching kill switch part way through.

    The kill switch is the most plausible source of path dependence in the pipeline, so the
    prefix property has to hold across the trip, not just on a quiet run.
    """
    prices = [100.0, 104.0, 108.0, 40.0, 41.0, 42.0, 39.0, 44.0]
    steps = tuple(
        ShadowStep(envelope=_env(i, i, price), signal=_sig(i, 1.0))
        for i, price in enumerate(prices)
    )
    return _hand_config(max_dd=0.1), steps


@pytest.mark.parametrize("build", [_quiet_run, _tripping_run], ids=["quiet", "kill-switch"])
def test_growing_prefix_reruns_extend_rather_than_diverge(
    build: Any,
) -> None:
    """`BarReporter`'s watermark is sound only if each bar's journal body extends the last.

    The *full* event list is deliberately not prefix-stable — every run appends its own terminal
    `run_completed` — so the reporter slices that terminal event off. This asserts the property the
    slice relies on, over the chained entry hashes, so a future change to the runner that reorders
    or inserts an event fails here rather than silently making the dashboard skip or duplicate a
    trade. (`shadow/runner.py` is hash-frozen by the V2C qualification freeze, but a freeze pins
    bytes, not this semantic.)
    """
    config, steps = build()
    previous_fills: tuple[Any, ...] = ()
    previous_body: list[Any] = []
    previous_alerts: tuple[Any, ...] = ()
    for n in range(1, len(steps) + 1):
        result = run_shadow(config, steps[:n])
        assert result.bars_processed == n
        # Every fill and alert the shorter run recorded is still there, unchanged, in the longer.
        assert result.fills[: len(previous_fills)] == previous_fills
        assert result.alerts[: len(previous_alerts)] == previous_alerts
        body = [(e.seq, e.event_type, e.as_of, e.entry_hash) for e in result.journal.events[:-1]]
        assert body[: len(previous_body)] == previous_body, f"journal body diverged at bar {n}"
        previous_fills = result.fills
        previous_alerts = result.alerts
        previous_body = body


def test_the_terminal_event_is_the_only_thing_the_reporter_must_skip() -> None:
    """Guards the `[:-1]` slice itself: the last event of a run is always `run_completed`."""
    config, steps = _quiet_run()
    for n in (1, 5, len(steps)):
        events = run_shadow(config, steps[:n]).journal.events
        assert events[-1].event_type == "run_completed"
        assert all(event.event_type != "run_completed" for event in events[:-1])


# --------------------------------------------------------------------------- #
# Telemetry cannot influence the trader
# --------------------------------------------------------------------------- #
def test_disabled_and_enabled_runs_produce_identical_engine_state() -> None:
    config = _hand_config()
    steps = tuple(
        ShadowStep(envelope=_env(i, i, 100.0 + i), signal=_sig(i, 0.2 * (i % 5))) for i in range(10)
    )
    silent = _drive(config, steps, CockpitReporter.disabled())
    client = RecordingClient()
    watched = _drive(config, steps, _reporter(client))

    assert silent.journal.to_jsonl_bytes() == watched.journal.to_jsonl_bytes()
    assert silent.checkpoint.fingerprint() == watched.checkpoint.fingerprint()
    assert silent.fills == watched.fills
    assert silent.final_account == watched.final_account
    assert silent.peak_equity == watched.peak_equity
    assert client.calls  # and the watched run really did report


def test_operator_outcome_is_the_same_with_a_client_a_broken_client_and_none() -> None:
    config = OperatorConfig(max_bars=40, backfill_bars=40, interval_seconds=0.0)
    outcomes = [
        run_operator(config, _reporter(None), threading.Event()),
        run_operator(config, _reporter(RecordingClient()), threading.Event()),
        run_operator(config, _reporter(ExplodingClient()), threading.Event()),
    ]
    first = outcomes[0]
    for other in outcomes[1:]:
        assert other.bars_processed == first.bars_processed
        assert other.fills == first.fills
        assert other.kill_tripped == first.kill_tripped
        assert other.final_equity == first.final_equity


def test_every_reporter_method_returns_none() -> None:
    """No caller can branch on whether monitoring worked, because there is nothing to branch on."""
    reporting = [
        name
        for name in dir(CockpitReporter)
        if (name.startswith("report_") or name in {"heartbeat", "register", "close"})
        and callable(getattr(CockpitReporter, name, None))
    ]
    assert len(reporting) == 10, sorted(reporting)
    for name in reporting:
        annotation = inspect.signature(getattr(CockpitReporter, name)).return_annotation
        assert annotation in {None, "None"}, f"{name} returns {annotation!r}, not None"

    # mypy enforces the annotation; calling every method here proves the bodies agree with it
    # (a stray `return True` would be a type error, and a raised exception would fail this test).
    client = RecordingClient()
    reporter = _reporter(client)
    fill = run_shadow(
        _hand_config(), (ShadowStep(envelope=_env(0, 0, 100.0), signal=_sig(0, 0.5)),)
    ).fills[0]
    reporter.register()
    reporter.heartbeat(uptime_seconds=1)
    reporter.report_trade(fill=fill, trade_id="abc")
    reporter.report_equity(equity=1.0, as_of=_ts(0))
    reporter.report_warning(code="c", message="m", context=None)
    reporter.report_error(code="c", message="m", fatal=False)
    reporter.close()
    assert len(client.calls) == 5


def test_reporter_swallows_every_client_failure() -> None:
    reporter = _reporter(ExplodingClient())
    fill = run_shadow(
        _hand_config(), (ShadowStep(envelope=_env(0, 0, 100.0), signal=_sig(0, 0.5)),)
    ).fills[0]
    reporter.register()
    reporter.heartbeat(uptime_seconds=3)
    reporter.report_trade(fill=fill, trade_id="abc")
    reporter.report_equity(equity=1.0, as_of=_ts(0))
    reporter.report_warning(code="c", message="m", context=None)
    reporter.report_error(code="c", message="m", fatal=True)
    reporter.close()
    assert reporter.dropped_events == 0
    assert reporter.stats_snapshot() == {}


def test_a_disabled_reporter_emits_nothing_at_all() -> None:
    client = RecordingClient()
    CockpitReporter.disabled()
    reporter = CockpitReporter(None, symbol="eth_usd")
    reporter.heartbeat(uptime_seconds=1)
    reporter.report_equity(equity=1.0, as_of=_ts(0))
    assert reporter.active is False
    assert client.calls == []


# --------------------------------------------------------------------------- #
# Event payloads come from authoritative state
# --------------------------------------------------------------------------- #
def _operate(
    client: Any, *, bars: int = 80
) -> tuple[OperatorConfig, tuple[ShadowStep, ...], ShadowRunResult]:
    config = OperatorConfig(max_bars=bars, backfill_bars=bars, interval_seconds=0.0)
    run_operator(config, _reporter(client), threading.Event())
    steps = build_steps(config, build_signal_source(config.candidate_id))
    return config, steps, run_shadow(config.shadow_config(), steps)


def test_signals_carry_the_candidates_own_envelope_and_the_risk_decision() -> None:
    client = RecordingClient()
    _config, steps, _result = _operate(client)
    signals = client.of("signal")
    assert len(signals) == len(steps)
    for step, call in zip(steps, signals, strict=True):
        assert call.kwargs["symbol"] == "eth_usd"
        assert call.kwargs["confidence"] == step.signal.target_weight
        assert call.kwargs["strategy"] == step.signal.candidate_id == MEANREV_SPEC.candidate_id
        assert call.kwargs["action"] in {"buy", "sell", "hold"}
        assert "approved_weight=" in call.kwargs["reason"]
        at = call.kwargs["at"]
        assert isinstance(at, datetime)
        assert at.isoformat() == step.signal.as_of


def test_trades_carry_the_paper_fill_and_a_journal_bound_identifier() -> None:
    client = RecordingClient()
    _config, _steps, result = _operate(client)
    trades = client.of("trade")
    traded = [fill for fill in result.fills if fill.traded_units != 0.0]
    assert trades, "the pre-registered candidate must actually trade in this window"
    assert len(trades) == len(traded)

    hashes = {
        event.entry_hash for event in result.journal.events if event.event_type == "fill_recorded"
    }
    for fill, call in zip(traded, trades, strict=True):
        assert call.kwargs["quantity"] == abs(fill.traded_units)
        assert call.kwargs["price"] == fill.price
        assert call.kwargs["side"] == ("buy" if fill.traded_units > 0 else "sell")
        assert call.kwargs["fee"] == 0.0
        assert call.kwargs["order_type"] == "market"
        assert call.kwargs["trade_id"] in hashes
    # Idempotency: a redelivered trade must not look like a second trade.
    assert len({call.kwargs["trade_id"] for call in trades}) == len(trades)


def test_positions_match_the_authoritative_paper_account() -> None:
    client = RecordingClient()
    _config, _steps, result = _operate(client)
    positions = client.of("position")
    assert positions
    last = positions[-1].kwargs
    assert last["quantity"] == result.final_account.units
    assert last["side"] == ("long" if result.final_account.units > 0 else "flat")
    assert last["exposure_value"] == pytest.approx(last["quantity"] * last["average_price"])
    # Every reported quantity is a units_after the paper book actually recorded.
    recorded = {fill.units_after for fill in result.fills}
    for call in positions:
        assert call.kwargs["quantity"] in recorded


def test_equity_matches_the_authoritative_paper_account_on_every_bar() -> None:
    client = RecordingClient()
    _config, steps, _result = _operate(client)
    equities = client.of("equity")
    assert len(equities) == len(steps)
    config = OperatorConfig(max_bars=len(steps), backfill_bars=len(steps), interval_seconds=0.0)
    shadow_config = config.shadow_config()
    for index, call in enumerate(equities):
        authoritative = run_shadow(shadow_config, steps[: index + 1])
        expected = authoritative.final_account.equity(steps[index].envelope.bar.close)
        assert call.kwargs["equity"] == expected
        assert call.kwargs["currency"] == "USD"
        # PnL is not decomposed by the paper book, so it is omitted rather than invented.
        assert call.kwargs.get("realized_pnl") is None
        assert call.kwargs.get("unrealized_pnl") is None


def test_equity_on_a_fill_bar_equals_the_fills_own_equity() -> None:
    client = RecordingClient()
    _config, _steps, result = _operate(client, bars=30)
    by_stamp = {
        call.kwargs["at"].isoformat(): call.kwargs["equity"] for call in client.of("equity")
    }
    for fill in result.fills:
        assert by_stamp[fill.as_of] == pytest.approx(fill.equity_after)


# --------------------------------------------------------------------------- #
# Warnings and errors come from real paths
# --------------------------------------------------------------------------- #
def test_a_genuinely_stale_bar_reaches_cockpit_as_a_warning() -> None:
    client = RecordingClient()
    # A four-day gap against a two-day staleness budget: the platform's own staleness alert.
    steps = (
        ShadowStep(envelope=_env(0, 0, 100.0), signal=_sig(0, 0.5)),
        ShadowStep(envelope=_env(1, 4, 101.0), signal=_sig(4, 0.5)),
    )
    _drive(_hand_config(staleness_seconds=172_800), steps, _reporter(client))
    warnings = client.of("warning")
    assert [call.kwargs["code"] for call in warnings] == ["stale_market_data"]
    assert "stale" in warnings[0].kwargs["message"]
    assert warnings[0].kwargs["context"] == {"severity": "warning"}


def test_a_genuine_drawdown_breach_reaches_cockpit_as_an_error() -> None:
    client = RecordingClient()
    prices = [100.0, 100.0, 40.0, 40.0]
    steps = tuple(
        ShadowStep(envelope=_env(i, i, price), signal=_sig(i, 1.0))
        for i, price in enumerate(prices)
    )
    result = _drive(_hand_config(max_dd=0.1), steps, _reporter(client))
    assert result.kill_tripped
    codes = [call.kwargs["code"] for call in client.of("error")]
    assert "drawdown_breach" in codes
    assert "kill_switch_tripped" in codes
    assert all(call.kwargs["fatal"] is False for call in client.of("error"))


def test_a_genuine_risk_breach_reaches_cockpit_as_an_error() -> None:
    client = RecordingClient()
    config = ShadowConfig.create(
        mode=PAPER_SIMULATION,
        instrument=ETH_USD,
        candidate_id="trend_candidate",
        starting_cash=10_000.0,
        limits=RiskLimits(max_target_weight=0.3, max_weight_step=1.0),
        thresholds=MonitoringThresholds(max_staleness_seconds=172_800, max_drawdown_fraction=0.9),
    )
    steps = (ShadowStep(envelope=_env(0, 0, 100.0), signal=_sig(0, 0.9)),)
    _drive(config, steps, _reporter(client))
    codes = [call.kwargs["code"] for call in client.of("error")]
    assert "risk_limit_breach" in codes


def test_an_engine_failure_is_reported_fatal_and_still_raises_into_the_trader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RecordingClient()

    def _boom(*_args: Any, **_kwargs: Any) -> ShadowRunResult:
        raise RuntimeError("engine gave up")

    monkeypatch.setattr(operate_paper, "run_shadow", _boom)
    with pytest.raises(RuntimeError, match="engine gave up"):
        run_operator(
            OperatorConfig(max_bars=3, backfill_bars=3, interval_seconds=0.0),
            _reporter(client),
            threading.Event(),
        )
    errors = client.of("error")
    assert [call.kwargs["code"] for call in errors] == [RUN_FAILED_CODE]
    assert errors[0].kwargs["fatal"] is True
    assert "engine gave up" in errors[0].kwargs["message"]


def test_a_slow_cycle_is_reported_as_an_operational_warning() -> None:
    client = RecordingClient()
    # A one-microsecond bar interval: every real cycle overruns it, which is exactly the
    # operational condition the warning exists to report.
    run_operator(
        OperatorConfig(max_bars=4, backfill_bars=0, interval_seconds=1e-6),
        _reporter(client),
        threading.Event(),
    )
    codes = [call.kwargs["code"] for call in client.of("warning")]
    assert codes
    assert set(codes) == {"slow_trading_cycle"}


# --------------------------------------------------------------------------- #
# Heartbeat lifecycle
# --------------------------------------------------------------------------- #
def test_heartbeat_starts_beats_and_stops_cleanly() -> None:
    client = RecordingClient()
    worker = HeartbeatWorker(_reporter(client), interval_seconds=0.02)
    idle_before_start = worker.running
    worker.start()
    running_after_start = worker.running
    deadline = time.monotonic() + 5.0
    while worker.beats < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    assert idle_before_start is False
    assert running_after_start is True
    assert worker.running is False
    beats = client.of("heartbeat")
    assert len(beats) >= 3
    assert beats[0].kwargs["uptime_seconds"] == 0
    assert all(call.kwargs["uptime_seconds"] >= 0 for call in beats)
    # Stopped means stopped: nothing more arrives.
    settled = len(client.of("heartbeat"))
    time.sleep(0.1)
    assert len(client.of("heartbeat")) == settled


def test_starting_the_heartbeat_twice_does_not_make_two_workers() -> None:
    worker = HeartbeatWorker(_reporter(RecordingClient()), interval_seconds=0.05)
    worker.start()
    first = threading.active_count()
    worker.start()
    assert threading.active_count() == first
    worker.stop()
    assert worker.running is False


def test_the_heartbeat_thread_is_a_daemon_and_cannot_hold_the_process_open() -> None:
    worker = HeartbeatWorker(_reporter(RecordingClient()), interval_seconds=0.05)
    worker.start()
    threads = [t for t in threading.enumerate() if t.name == "eth-research-cockpit-heartbeat"]
    assert len(threads) == 1
    assert threads[0].daemon is True
    worker.stop()


def test_the_heartbeat_survives_a_client_that_always_fails() -> None:
    worker = HeartbeatWorker(_reporter(ExplodingClient()), interval_seconds=0.02)
    worker.start()
    time.sleep(0.1)
    survived = worker.running
    worker.stop()
    assert survived is True
    assert worker.running is False


def test_the_heartbeat_reports_dropped_events_through_the_client() -> None:
    client = RecordingClient()
    client.stats.dropped_rejected = 4
    reporter = _reporter(client)
    assert reporter.dropped_events == 4


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def test_telemetry_is_off_without_a_key_and_that_is_not_an_error() -> None:
    config = CockpitConfig.from_env({})
    assert config.enabled is False
    assert config.heartbeat_interval_seconds == DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    assert build_client(config) is None


def test_telemetry_is_off_when_explicitly_switched_off_even_with_a_key() -> None:
    env = {BOT_API_KEY_ENV: "nardis_" + "x" * 24, TELEMETRY_ENABLED_ENV: "false"}
    assert CockpitConfig.from_env(env).enabled is False


def test_telemetry_is_on_with_a_key() -> None:
    env = {BOT_API_KEY_ENV: "nardis_" + "x" * 24}
    assert CockpitConfig.from_env(env).enabled is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5", 5.0), ("0.1", 1.0), ("9999", MAX_HEARTBEAT_INTERVAL_SECONDS), ("nonsense", 15.0)],
)
def test_heartbeat_interval_is_clamped_never_rejected(raw: str, expected: float) -> None:
    env = {BOT_API_KEY_ENV: "nardis_" + "x" * 24, HEARTBEAT_INTERVAL_ENV: raw}
    assert CockpitConfig.from_env(env).heartbeat_interval_seconds == expected


def test_the_config_never_returns_the_key() -> None:
    env = {BOT_API_KEY_ENV: "nardis_" + "s" * 24}
    rendered = repr(CockpitConfig.from_env(env))
    assert "nardis_" not in rendered


# --------------------------------------------------------------------------- #
# The operator's own contract
# --------------------------------------------------------------------------- #
def test_the_operator_runs_a_pre_registered_candidate_with_its_pinned_parameters() -> None:
    source = build_signal_source(MEANREV_SPEC.candidate_id)
    assert source.candidate_id == MEANREV_SPEC.candidate_id
    assert source.warmup_bars == MEANREV_SPEC.fixed_parameters["lookback"]
    trend = build_signal_source(TREND_SPEC.candidate_id)
    assert trend.warmup_bars == TREND_SPEC.fixed_parameters["horizon"]


def test_the_overlay_candidate_is_refused_rather_than_misreported() -> None:
    with pytest.raises(OperatorError, match="risk overlay"):
        build_signal_source(VOL_SCALED_SPEC.candidate_id)


def test_the_operator_refuses_a_live_mode() -> None:
    with pytest.raises(OperatorError, match="mode must be one of"):
        OperatorConfig(mode="live").validate()


def test_the_operator_drives_only_the_platforms_non_routing_paper_adapter() -> None:
    config = OperatorConfig(max_bars=5, backfill_bars=5, interval_seconds=0.0)
    assert config.shadow_config().mode == SYNTHETIC_DEMO
    outcome = run_operator(config, CockpitReporter.disabled(), threading.Event())
    assert outcome.bars_processed == 5


def test_the_operator_stops_promptly_when_asked() -> None:
    stop = threading.Event()
    stop.set()
    outcome = run_operator(
        OperatorConfig(max_bars=50, backfill_bars=0, interval_seconds=10.0),
        CockpitReporter.disabled(),
        stop,
    )
    assert outcome.bars_processed == 0
    assert outcome.stopped_early is True


def test_signals_are_causal_by_construction() -> None:
    config = OperatorConfig(max_bars=12, backfill_bars=12, interval_seconds=0.0)
    steps = build_steps(config, build_signal_source(config.candidate_id))
    for step in steps:
        assert step.signal.as_of == step.envelope.close_time
    # The platform's as-of clock refuses a signal stamped after its bar; this run is accepted.
    assert run_shadow(config.shadow_config(), steps).bars_processed == len(steps)


# --------------------------------------------------------------------------- #
# A Cockpit that is slow or unreachable must cost the loop nothing.
# This exercises the shipped client end to end, so it is the real guarantee, not a mock's.
# --------------------------------------------------------------------------- #
def _slow_client(delay: float) -> Any:
    """The shipped client, wired to a transport that takes `delay` seconds to answer anything."""
    from nardis_telemetry import TelemetryClient, TelemetryConfig
    from nardis_telemetry.transport import Response

    class GlacialTransport:
        def request(self, *_args: Any, **_kwargs: Any) -> Response:
            time.sleep(delay)
            return Response(status_code=0, error="TimeoutException")

        def close(self) -> None:
            return

    config = TelemetryConfig(base_url="http://127.0.0.1:1", api_key="nardis_" + "t" * 24)
    return TelemetryClient(config, transport=GlacialTransport())


@pytest.mark.usefixtures("shipped_client")
def test_a_glacial_cockpit_does_not_slow_the_trading_loop() -> None:
    client = _slow_client(2.0)
    try:
        started = time.monotonic()
        outcome = run_operator(
            OperatorConfig(max_bars=30, backfill_bars=30, interval_seconds=0.0),
            _reporter(client),
            threading.Event(),
        )
        elapsed = time.monotonic() - started
    finally:
        client.close(timeout=0.1)
    assert outcome.bars_processed == 30
    # 30 bars, each reporting several events into a transport that takes two seconds a request.
    # Anything close to a blocking client would be well over a minute.
    assert elapsed < 5.0, f"the loop took {elapsed:.2f}s, which means telemetry blocked it"
    assert outcome.slowest_report_seconds < 0.5


@pytest.mark.usefixtures("shipped_client")
def test_an_unreachable_cockpit_does_not_stop_the_trader() -> None:
    from nardis_telemetry import TelemetryClient, TelemetryConfig

    # Port 1 on loopback: connection refused, immediately and repeatedly.
    client = TelemetryClient(
        TelemetryConfig(
            base_url="http://127.0.0.1:1",
            api_key="nardis_" + "u" * 24,
            connect_timeout=0.05,
            read_timeout=0.05,
            max_attempts=1,
        )
    )
    reporter = _reporter(client)
    try:
        reporter.register()
        outcome = run_operator(
            OperatorConfig(max_bars=20, backfill_bars=20, interval_seconds=0.0),
            reporter,
            threading.Event(),
        )
    finally:
        reporter.close(timeout=0.2)
    silent = run_operator(
        OperatorConfig(max_bars=20, backfill_bars=20, interval_seconds=0.0),
        CockpitReporter.disabled(),
        threading.Event(),
    )
    assert outcome.bars_processed == silent.bars_processed
    assert outcome.final_equity == silent.final_equity
    assert outcome.kill_tripped == silent.kill_tripped


def test_the_shipped_client_satisfies_the_surface_the_reporter_calls(shipped_client: Any) -> None:
    """If the client's API ever moves, this fails here rather than silently in production."""
    TelemetryClient = shipped_client.TelemetryClient

    for name in (
        "register",
        "close",
        "heartbeat",
        "signal",
        "position",
        "trade",
        "equity",
        "warning",
        "error",
    ):
        assert callable(getattr(TelemetryClient, name)), name


def test_reporter_failures_are_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    reporter = _reporter(ExplodingClient())
    with caplog.at_level(logging.WARNING, logger="eth_research.cockpit"):
        reporter.report_equity(equity=1.0, as_of=_ts(0))
    assert any("telemetry equity failed" in record.message for record in caplog.records)


# --------------------------------------------------------------------------- #
# The process entry point
# --------------------------------------------------------------------------- #
@pytest.fixture
def _restore_signal_handlers() -> Any:
    """``main`` installs SIGINT/SIGTERM handlers; put pytest's back afterwards."""
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


@pytest.mark.usefixtures("_restore_signal_handlers")
def test_the_cli_runs_a_whole_series_without_cockpit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BOT_API_KEY_ENV, raising=False)
    monkeypatch.delenv("NARDIS_COCKPIT_URL", raising=False)
    assert operate_main(["--interval", "0", "--bars", "6", "--backfill", "6"]) == 0


@pytest.mark.usefixtures("_restore_signal_handlers")
def test_the_cli_refuses_an_impossible_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BOT_API_KEY_ENV, raising=False)
    assert operate_main(["--bars", "5", "--backfill", "50"]) == 2


def test_the_cli_will_not_even_parse_a_live_mode() -> None:
    """argparse refuses it before any trading code runs; the domain would refuse it again."""
    with pytest.raises(SystemExit):
        operate_main(["--mode", "live"])
