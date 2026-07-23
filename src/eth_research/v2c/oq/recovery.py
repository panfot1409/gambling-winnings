"""V2C section 23: the crash / recovery campaign.

Exercises the shadow platform's durability and safety machinery without taking any exposure:

* **Restart determinism** -- re-running the instrument from scratch yields a byte-identical journal
  and an identical checkpoint fingerprint (the shadow platform has no mid-run resume, so a restart
  is a clean re-run compared against the original).
* **Journal durability + tamper detection** -- the journal round-trips through its canonical bytes,
  and a single flipped byte is rejected by the hash chain.
* **Checkpoint consistency** -- the checkpoint persists atomically, reloads, and ``recover`` accepts
  it only against the journal head that produced it (an empty/other journal is refused).
* **Corruption rejection** -- a corrupted checkpoint (bad schema version) is refused on parse.
* **Disk-write failure** -- an unwritable target fails closed with no partial checkpoint remaining.
* **Kill-switch trip drill** -- a synthetic risk breach (a probe request above a zero exposure cap)
  trips the latching kill switch on the breaching bar (latency 0 steps), holds every later bar (zero
  fills, so **no exposure is ever taken**), and re-arms on reset.

The drill's probe is a labelled operational-safety stimulus, not a candidate or a strategy: the risk
cap refuses it before any fill, so the book stays 100% cash. No market performance is computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eth_research.shadow.checkpoint import (
    CheckpointError,
    load_checkpoint,
    recover,
    write_checkpoint,
)
from eth_research.shadow.domain import SYNTHETIC_DEMO, InstrumentId
from eth_research.shadow.journal import JournalError, ShadowJournal
from eth_research.shadow.kill_switch import LatchingKillSwitch
from eth_research.shadow.market_data import MarketBar, MarketDataEnvelope
from eth_research.shadow.monitoring import MonitoringThresholds
from eth_research.shadow.risk import RiskLimits
from eth_research.shadow.runner import ShadowConfig, ShadowStep, run_shadow
from eth_research.shadow.signal import SignalEnvelope
from eth_research.v2c.oq.events import OQ_FIXTURE_COHORT_START, OQ_INTERVAL_SECONDS
from eth_research.v2c.oq.harness import qualify_instrument

_KILL_TRIPPED_EVENT: str = "kill_tripped"
_FILL_RECORDED_EVENT: str = "fill_recorded"
_BAR_OBSERVED_EVENT: str = "bar_observed"

#: The kill-switch drill uses a labelled safety probe -- not a candidate, not a strategy.
_SAFETY_PROBE_ID: str = "operational_safety_probe"
_PROBE_WEIGHT: float = 0.5


@dataclass(frozen=True, slots=True)
class RecoveryCheck:
    """One recovery/safety check and whether it held."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """The crash/recovery campaign outcome."""

    instrument_symbol: str
    checks: tuple[RecoveryCheck, ...]
    passed: bool


def _slot_iso(index: int) -> str:
    import pandas as pd

    ts = pd.Timestamp(OQ_FIXTURE_COHORT_START) + pd.Timedelta(seconds=OQ_INTERVAL_SECONDS) * index
    return str(ts.isoformat())


def _drill_steps(instrument: InstrumentId, *, bars: int) -> tuple[ShadowStep, ...]:
    steps: list[ShadowStep] = []
    for index in range(bars):
        close = 1000.0 + float(index)
        envelope = MarketDataEnvelope.parse(
            "env",
            {
                "instrument": instrument.to_canonical(),
                "close_time": _slot_iso(index),
                "source": "oq_drill",
                "sequence": index,
                "bar": MarketBar.parse(
                    "bar",
                    {
                        "open": close,
                        "high": close * 1.01,
                        "low": close * 0.99,
                        "close": close,
                        "volume": 1000.0,
                    },
                ).to_canonical(),
            },
        )
        signal = SignalEnvelope.create(
            candidate_id=_SAFETY_PROBE_ID,
            instrument=instrument,
            as_of=_slot_iso(index),
            target_weight=_PROBE_WEIGHT,
        )
        steps.append(ShadowStep(envelope=envelope, signal=signal))
    return tuple(steps)


def _kill_switch_trip_drill(symbol: str) -> RecoveryCheck:
    instrument = InstrumentId(symbol)
    config = ShadowConfig.create(
        mode=SYNTHETIC_DEMO,
        instrument=instrument,
        candidate_id=_SAFETY_PROBE_ID,
        starting_cash=10_000.0,
        # A zero exposure cap: the probe's positive request is a breach the risk engine refuses
        # BEFORE any fill, so no exposure is ever taken.
        limits=RiskLimits.parse("limits", {"max_target_weight": 0.0, "max_weight_step": 0.0}),
        thresholds=MonitoringThresholds.parse(
            "thresholds",
            {"max_staleness_seconds": 10 * OQ_INTERVAL_SECONDS, "max_drawdown_fraction": 0.5},
        ),
    )
    result = run_shadow(config, _drill_steps(instrument, bars=4))
    kinds = [event.event_type for event in result.journal.events]
    if _KILL_TRIPPED_EVENT not in kinds:
        return RecoveryCheck("kill_switch_trip_drill", False, "the kill switch never tripped")
    trip = kinds.index(_KILL_TRIPPED_EVENT)
    # Latency in BARS: bars fully processed before the breaching bar (0 == trips on the same bar).
    bars_up_to_trip = sum(1 for kind in kinds[: trip + 1] if kind == _BAR_OBSERVED_EVENT)
    latency_bars = bars_up_to_trip - 1
    fills = len(result.fills)
    # The trip must occur on the first (breaching) bar, hold every later bar, and record no fill.
    if not result.kill_tripped or fills != 0 or latency_bars != 0:
        return RecoveryCheck(
            "kill_switch_trip_drill",
            False,
            f"trip={result.kill_tripped} fills={fills} latency_bars={latency_bars}",
        )
    # Reset re-arms the (independent) primitive.
    switch = LatchingKillSwitch.armed()
    switch.trip(reason="drill")
    tripped = switch.is_tripped
    switch.reset(reason="drill_cleared")
    if not tripped or switch.is_tripped or switch.reset_count != 1:
        return RecoveryCheck("kill_switch_trip_drill", False, "latch/reset semantics failed")
    return RecoveryCheck(
        "kill_switch_trip_drill",
        True,
        f"tripped on the breaching bar (latency {latency_bars} bars), 0 fills, held; reset re-arms",
    )


def run_recovery_campaign(symbol: str, *, workdir: str | Path, slots: int) -> RecoveryReport:
    """Run the whole crash/recovery + kill-switch campaign for one instrument."""
    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    checks: list[RecoveryCheck] = []

    original = qualify_instrument(symbol, slots=slots, starting_cash=10_000.0)
    result = original.result

    # 1. Restart determinism (clean re-run == original).
    replay = qualify_instrument(symbol, slots=slots, starting_cash=10_000.0)
    same_journal = result.journal.to_jsonl_bytes() == replay.result.journal.to_jsonl_bytes()
    same_fp = result.checkpoint.fingerprint() == replay.result.checkpoint.fingerprint()
    checks.append(
        RecoveryCheck(
            "restart_determinism",
            same_journal and same_fp,
            "byte-identical journal + checkpoint on re-run"
            if (same_journal and same_fp)
            else f"journal_equal={same_journal} checkpoint_equal={same_fp}",
        )
    )

    # 2. Journal durability + tamper detection.
    raw = result.journal.to_jsonl_bytes()
    roundtrip_ok = ShadowJournal.parse(raw).head_hash == result.journal.head_hash
    tamper_detected = False
    if raw:
        corrupted = bytearray(raw)
        corrupted[len(corrupted) // 2] ^= 0x01
        try:
            ShadowJournal.parse(bytes(corrupted))
        except JournalError:
            tamper_detected = True
    checks.append(
        RecoveryCheck(
            "journal_durability",
            roundtrip_ok and tamper_detected,
            "round-trips and rejects a flipped byte"
            if (roundtrip_ok and tamper_detected)
            else f"roundtrip={roundtrip_ok} tamper_detected={tamper_detected}",
        )
    )

    # 3. Checkpoint persistence + head-bound recovery.
    cp_path = root / f"{symbol}_checkpoint.json"
    write_checkpoint(cp_path, result.checkpoint)
    reloaded = load_checkpoint(cp_path)
    recovered = recover(reloaded, result.journal)
    binding_ok = recovered.fingerprint() == result.checkpoint.fingerprint()
    empty_refused = False
    try:
        recover(reloaded, ShadowJournal.empty())
    except CheckpointError:
        empty_refused = True
    checks.append(
        RecoveryCheck(
            "checkpoint_consistency",
            binding_ok and empty_refused,
            "recovers against its own journal head; refuses an empty journal"
            if (binding_ok and empty_refused)
            else f"binding={binding_ok} empty_refused={empty_refused}",
        )
    )

    # 4. Corrupted checkpoint rejected on parse.
    from eth_research.shadow.checkpoint import ShadowCheckpoint

    bad = dict(result.checkpoint.to_canonical())
    bad["schema_version"] = 999
    corrupt_refused = False
    try:
        ShadowCheckpoint.parse("checkpoint", bad)
    except CheckpointError:
        corrupt_refused = True
    checks.append(
        RecoveryCheck(
            "corrupted_checkpoint_rejected",
            corrupt_refused,
            "a bad schema_version is refused" if corrupt_refused else "corruption was NOT refused",
        )
    )

    # 5. Disk-write failure fails closed (parent path is a file -> no checkpoint written).
    blocker = root / "blocker"
    blocker.write_bytes(b"not a directory")
    blocked_path = blocker / "checkpoint.json"
    write_failed = False
    try:
        write_checkpoint(blocked_path, result.checkpoint)
    except OSError:
        write_failed = True
    checks.append(
        RecoveryCheck(
            "disk_write_failure_fail_closed",
            write_failed and not blocked_path.exists(),
            "an unwritable target fails closed with no partial checkpoint"
            if (write_failed and not blocked_path.exists())
            else f"write_failed={write_failed}",
        )
    )

    # 6. Kill-switch trip drill.
    checks.append(_kill_switch_trip_drill(symbol))

    return RecoveryReport(symbol, tuple(checks), all(check.passed for check in checks))


__all__ = [
    "RecoveryCheck",
    "RecoveryReport",
    "run_recovery_campaign",
]
