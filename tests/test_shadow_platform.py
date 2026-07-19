"""Tests for the signal-only shadow-operations platform (§7-18).

Coverage: the mode boundary fails closed on any live/production mode; the as-of clock forbids
backwards moves and look-ahead reads; market-data/signal/risk/paper/journal/checkpoint value types
round-trip strictly and enforce their invariants; the latching kill switch latches; the
deterministic runner produces a byte-identical journal on a re-run, halts on a risk breach, and
rejects a look-ahead signal; and the read-only CLI verifies a produced journal + checkpoint.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from eth_research.shadow.adapter import (
    ExecutionIntent,
    IntentAck,
    PaperExecutionAdapter,
    ShadowExecutionAdapter,
)
from eth_research.shadow.checkpoint import CheckpointError, recover, write_checkpoint
from eth_research.shadow.clock import AsOfClock, ShadowClockError
from eth_research.shadow.domain import (
    ETH_USD,
    HISTORICAL_SHADOW,
    PAPER_SIMULATION,
    SYNTHETIC_DEMO,
    InstrumentId,
    ShadowDomainError,
    require_shadow_mode,
)
from eth_research.shadow.journal import (
    FILL_RECORDED,
    KILL_TRIPPED,
    JournalError,
    ShadowJournal,
)
from eth_research.shadow.kill_switch import KillSwitchTripped, LatchingKillSwitch
from eth_research.shadow.market_data import MarketBar, MarketDataEnvelope, MarketDataError
from eth_research.shadow.monitoring import MonitoringThresholds, drawdown_alert, staleness_alert
from eth_research.shadow.paper import PaperAccount, PaperError, rebalance
from eth_research.shadow.risk import RiskLimitEngine, RiskLimits
from eth_research.shadow.runner import (
    ShadowConfig,
    ShadowRunError,
    ShadowStep,
    run_shadow,
)
from eth_research.shadow.signal import SignalEnvelope
from eth_research.v2.strict import V2ValidationError

_T0 = pd.Timestamp("2024-01-01T00:00:00Z")


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


def _sig(days: int, weight: float, candidate: str = "trend_candidate") -> SignalEnvelope:
    return SignalEnvelope.create(
        candidate_id=candidate, instrument=ETH_USD, as_of=_ts(days), target_weight=weight
    )


def _config(*, max_weight: float = 1.0, max_step: float = 1.0, max_dd: float = 0.9) -> ShadowConfig:
    return ShadowConfig.create(
        mode=PAPER_SIMULATION,
        instrument=ETH_USD,
        candidate_id="trend_candidate",
        starting_cash=10_000.0,
        limits=RiskLimits(max_target_weight=max_weight, max_weight_step=max_step),
        thresholds=MonitoringThresholds(
            max_staleness_seconds=172_800, max_drawdown_fraction=max_dd
        ),
    )


# --- domain: the mode boundary fails closed -----------------------------------


@pytest.mark.parametrize("mode", [SYNTHETIC_DEMO, HISTORICAL_SHADOW, PAPER_SIMULATION])
def test_supported_modes_accepted(mode: str) -> None:
    assert require_shadow_mode("mode", mode) == mode


@pytest.mark.parametrize(
    "mode", ["live", "production", "production_live", "real_money", "exchange", "mainnet", "prod"]
)
def test_live_modes_rejected_fail_closed(mode: str) -> None:
    with pytest.raises(ShadowDomainError, match="signal-only"):
        require_shadow_mode("mode", mode)


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ShadowDomainError):
        require_shadow_mode("mode", "backtest")


def test_instrument_parse_roundtrip() -> None:
    assert InstrumentId.parse("i", "eth_usd") == ETH_USD
    # An invalid slug is rejected by the shared strict decoder (the base V2 validation class).
    with pytest.raises(V2ValidationError):
        InstrumentId.parse("i", "ETH-USD")


# --- clock: monotonic, no look-ahead ------------------------------------------


def test_clock_advances_forward_only() -> None:
    clock = AsOfClock.unstarted()
    clock.advance_to(_ts(0))
    clock.advance_to(_ts(1))
    with pytest.raises(ShadowClockError, match="backwards"):
        clock.advance_to(_ts(0))


def test_clock_require_visible_rejects_future() -> None:
    clock = AsOfClock.at(_ts(1))
    assert clock.require_visible("x", _ts(1)) == pd.Timestamp(_ts(1))
    with pytest.raises(ShadowClockError, match="look-ahead"):
        clock.require_visible("x", _ts(2))


# --- market data --------------------------------------------------------------


def test_market_bar_rejects_inconsistent_ohlc() -> None:
    with pytest.raises(MarketDataError):
        MarketBar.parse("bar", {"open": 10, "high": 9, "low": 8, "close": 8.5, "volume": 1})


def test_envelope_reveal_requires_visibility() -> None:
    env = _env(0, 1, 100.0)
    clock = AsOfClock.at(_ts(0))
    with pytest.raises(ShadowClockError):
        env.reveal_under(clock)
    clock.advance_to(_ts(1))
    assert env.reveal_under(clock).close == 100.0


def test_envelope_roundtrip() -> None:
    env = _env(3, 2, 123.0)
    assert MarketDataEnvelope.parse("e", env.to_canonical()) == env


# --- risk ---------------------------------------------------------------------


def test_risk_clamps_exposure_as_breach() -> None:
    engine = RiskLimitEngine(RiskLimits(max_target_weight=0.5, max_weight_step=1.0))
    decision = engine.evaluate(requested_weight=1.0, current_weight=0.0)
    assert decision.approved_weight == 0.5
    assert decision.is_breach


def test_risk_throttles_step_without_breach() -> None:
    engine = RiskLimitEngine(RiskLimits(max_target_weight=1.0, max_weight_step=0.1))
    decision = engine.evaluate(requested_weight=1.0, current_weight=0.0)
    assert decision.approved_weight == pytest.approx(0.1)
    assert not decision.is_breach
    assert decision.throttled_limits == ("max_weight_step",)


# --- kill switch --------------------------------------------------------------


def test_kill_switch_latches_and_keeps_first_reason() -> None:
    kill = LatchingKillSwitch.armed()
    kill.trip("first")
    kill.trip("second")
    assert kill.is_tripped
    assert kill.reason == "first"
    assert kill.trip_count == 2
    with pytest.raises(KillSwitchTripped):
        kill.require_clear()


def test_kill_switch_reset_rearms() -> None:
    kill = LatchingKillSwitch.armed()
    kill.trip("boom")
    kill.reset(reason="operator cleared")
    assert not kill.is_tripped
    assert kill.reason is None
    assert kill.reset_count == 1


# --- paper accounting ---------------------------------------------------------


def test_rebalance_hits_target_weight() -> None:
    account = PaperAccount.opening(10_000.0)
    new_account, fill = rebalance(account, as_of=_ts(0), price=100.0, target_weight=0.5)
    # 50% of 10k equity at price 100 -> 50 units, 5000 cash.
    assert fill.units_after == pytest.approx(50.0)
    assert new_account.cash == pytest.approx(5_000.0)
    assert fill.equity_after == pytest.approx(10_000.0)


def test_rebalance_rejects_insolvent_book() -> None:
    with pytest.raises(PaperError):
        rebalance(PaperAccount(cash=-1.0, units=0.0), as_of=_ts(0), price=100.0, target_weight=0.5)


# --- journal ------------------------------------------------------------------


def test_journal_chain_roundtrips_and_detects_tamper() -> None:
    journal = ShadowJournal.empty()
    journal.append("run_started", as_of=_ts(0), payload={"mode": PAPER_SIMULATION})
    journal.append("bar_observed", as_of=_ts(1), payload={"close": 100.0})
    raw = journal.to_jsonl_bytes()
    parsed = ShadowJournal.parse(raw)
    assert parsed.to_jsonl_bytes() == raw
    assert parsed.head_hash == journal.head_hash
    tampered = raw.replace(b'"close":100.0', b'"close":999.0')
    with pytest.raises(JournalError):
        ShadowJournal.parse(tampered)


# --- monitoring ---------------------------------------------------------------


def test_staleness_and_drawdown_alerts() -> None:
    stale = staleness_alert(as_of=_ts(3), last_bar_time=_ts(0), max_staleness_seconds=3600)
    assert stale is not None
    assert stale.severity == "warning"
    fresh = staleness_alert(as_of=_ts(0), last_bar_time=_ts(0), max_staleness_seconds=3600)
    assert fresh is None
    dd = drawdown_alert(as_of=_ts(0), equity=80.0, peak_equity=100.0, max_drawdown_fraction=0.1)
    assert dd is not None
    assert dd.severity == "critical"


# --- adapter ------------------------------------------------------------------


def test_paper_adapter_records_and_acks() -> None:
    adapter = PaperExecutionAdapter()
    intent = ExecutionIntent.create(
        candidate_id="trend_candidate", instrument=ETH_USD, as_of=_ts(0), approved_weight=0.3
    )
    ack = adapter.dispatch(intent)
    assert isinstance(ack, IntentAck)
    assert ack.accepted
    assert ack.channel == "paper"
    assert adapter.dispatched == (intent,)


def test_execution_adapter_is_abstract() -> None:
    with pytest.raises(TypeError):
        ShadowExecutionAdapter()  # type: ignore[abstract]


# --- runner: determinism, halting, look-ahead ---------------------------------


def _clean_steps() -> tuple[ShadowStep, ...]:
    prices = [100.0, 101.0, 102.0, 101.5, 103.0]
    weights = [0.2, 0.4, 0.6, 0.5, 0.5]
    return tuple(
        ShadowStep(envelope=_env(i, i, p), signal=_sig(i, w))
        for i, (p, w) in enumerate(zip(prices, weights, strict=True))
    )


def test_runner_is_deterministic() -> None:
    config, steps = _config(), _clean_steps()
    first = run_shadow(config, steps)
    second = run_shadow(config, steps)
    assert first.journal.to_jsonl_bytes() == second.journal.to_jsonl_bytes()
    assert first.checkpoint.fingerprint() == second.checkpoint.fingerprint()
    assert not first.kill_tripped
    assert len(first.fills) == len(steps)


def test_runner_checkpoint_binds_journal_head() -> None:
    result = run_shadow(_config(), _clean_steps())
    assert recover(result.checkpoint, result.journal) is result.checkpoint
    empty = ShadowJournal.empty()
    with pytest.raises(CheckpointError):
        recover(result.checkpoint, empty)


def test_runner_halts_on_risk_breach() -> None:
    # A hard exposure cap of 0.3 with a request of 0.6 breaches and trips the kill switch.
    config = _config(max_weight=0.3)
    result = run_shadow(config, _clean_steps())
    assert result.kill_tripped
    kinds = [e.event_type for e in result.journal.events]
    assert KILL_TRIPPED in kinds
    # Once tripped, the book holds: no fills are recorded after the trip index.
    trip_index = kinds.index(KILL_TRIPPED)
    assert FILL_RECORDED not in kinds[trip_index:]


def test_runner_rejects_lookahead_signal() -> None:
    bad = (ShadowStep(envelope=_env(0, 0, 100.0), signal=_sig(1, 0.2)),)
    with pytest.raises(ShadowClockError):
        run_shadow(_config(), bad)


def test_runner_rejects_empty_and_mismatched() -> None:
    with pytest.raises(ShadowRunError):
        run_shadow(_config(), ())
    mismatched = (ShadowStep(envelope=_env(0, 0, 100.0), signal=_sig(0, 0.2, candidate="other")),)
    with pytest.raises(ShadowRunError):
        run_shadow(_config(), mismatched)


def test_runner_revalidates_mode_fail_closed() -> None:
    # Sh-C1: a config built *without* the create() factory can carry a live mode. run_shadow
    # re-validates it at entry and fails closed before touching any step.
    live_config = ShadowConfig(
        mode="live",
        instrument=ETH_USD,
        candidate_id="trend_candidate",
        starting_cash=10_000.0,
        limits=RiskLimits(max_target_weight=1.0, max_weight_step=1.0),
        thresholds=MonitoringThresholds(max_staleness_seconds=172_800, max_drawdown_fraction=0.9),
    )
    with pytest.raises(ShadowDomainError, match="signal-only"):
        run_shadow(live_config, _clean_steps())


class _RogueChannelAdapter(ShadowExecutionAdapter):
    """An adapter that declares a non-allowlisted channel; the runner must refuse to drive it."""

    @property
    def channel(self) -> str:
        return "venue_live"

    def dispatch(self, intent: ExecutionIntent) -> IntentAck:
        return IntentAck(accepted=True, channel="venue_live", note="should never be reached")


def test_runner_refuses_non_allowlisted_adapter_channel() -> None:
    # Sh-C2: only reviewed non-routing channels may run. A rogue channel is refused before the loop.
    with pytest.raises(ShadowRunError, match="non-routing"):
        run_shadow(_config(), _clean_steps(), adapter=_RogueChannelAdapter())


def test_runner_raises_staleness_warning_between_far_apart_bars() -> None:
    # Sh-C3: a gap between consecutive bars beyond the staleness budget raises a warning (which does
    # not halt the run). _config()'s budget is 2 days; these bars are 5 days apart.
    steps = (
        ShadowStep(envelope=_env(0, 0, 100.0), signal=_sig(0, 0.2)),
        ShadowStep(envelope=_env(1, 5, 101.0), signal=_sig(5, 0.3)),
    )
    result = run_shadow(_config(), steps)
    assert any(a.code == "stale_market_data" and a.severity == "warning" for a in result.alerts)
    assert not result.kill_tripped  # a staleness warning never trips the kill switch
    assert len(result.fills) == 2  # ...and never halts the run


def test_runner_drawdown_breaker_holds_book_before_fill() -> None:
    # Sh-C4: a drawdown breach is evaluated on the held (pre-trade) book and trips the kill switch
    # BEFORE any rebalance, so the breaching bar holds instead of executing one last fill.
    config = _config(max_dd=0.3)
    steps = (
        ShadowStep(envelope=_env(0, 0, 100.0), signal=_sig(0, 1.0)),  # go fully long
        ShadowStep(envelope=_env(1, 1, 50.0), signal=_sig(1, 0.0)),  # -50%: try to flatten
    )
    result = run_shadow(config, steps)
    assert result.kill_tripped
    assert any(a.code == "drawdown_breach" for a in result.alerts)
    # Only the first bar filled; the drawdown bar held rather than rebalancing to flat.
    assert len(result.fills) == 1
    assert result.final_account.units == pytest.approx(100.0)


# --- CLI ----------------------------------------------------------------------


def test_cli_verify_and_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from eth_research.shadow import cli

    result = run_shadow(_config(), _clean_steps())
    journal_path = tmp_path / "journal.jsonl"
    checkpoint_path = tmp_path / "checkpoint.json"
    journal_path.write_bytes(result.journal.to_jsonl_bytes())
    write_checkpoint(checkpoint_path, result.checkpoint)

    assert (
        cli.main(["verify", "--journal", str(journal_path), "--checkpoint", str(checkpoint_path)])
        == 0
    )
    assert "verify: OK" in capsys.readouterr().out
    assert cli.main(["summary", "--journal", str(journal_path)]) == 0
    assert "terminal:" in capsys.readouterr().out
