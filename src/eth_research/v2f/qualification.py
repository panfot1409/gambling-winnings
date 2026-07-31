"""Kill-switch and monitoring qualification — the two open implementation requirements.

``derive_requirements`` treats ``kill_switch_qualified`` and ``monitoring_qualified`` as satisfied
when a plain non-symlink JSON **object** exists at each qualification path. That check is a
presence check, and a presence check is trivially satisfiable by writing ``{}``.

This module refuses to let that be how those requirements get met. Each qualification runs a
truth table of probes against the real mechanism and **raises** if any probe misbehaves; the
record is written only from probes that actually ran, and it embeds their observed outcomes. A
mechanism that regresses produces no record, so the requirement goes back to false rather than
staying true on a stale file.

Every probe carries its opposite. A kill switch that blocked everything would pass every
"blocks when tripped" assertion while being useless, so each group also proves the permissive
case. That is the same discipline the rest of V2F uses: a guard is only proven by watching it
say yes to the valid case and no to the invalid one.

Deterministic and offline: fixed timestamps, no wall clock, no network, no market data, no money.
Nothing here reads a research partition or a sealed ledger.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eth_research.shadow.kill_switch import KillSwitchTripped, LatchingKillSwitch
from eth_research.shadow.monitoring import (
    CRITICAL,
    DRAWDOWN_CODE,
    KILL_SWITCH_CODE,
    RISK_BREACH_CODE,
    STALE_DATA_CODE,
    WARNING,
    drawdown_alert,
    kill_switch_alert,
    risk_breach_alert,
    staleness_alert,
)
from eth_research.v2e.paper import (
    KILL_SWITCH_QUALIFICATION_RELPATH,
    MONITORING_QUALIFICATION_RELPATH,
)

QUALIFICATION_SCHEMA_VERSION: int = 1

#: Fixed instants. A wall clock would make the same bytes qualify differently on different days.
_T0 = "2026-07-29T00:00:00Z"
_T1 = "2026-07-29T00:10:00Z"


class QualificationError(RuntimeError):
    """A qualification probe did not behave as the requirement demands."""


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise QualificationError(detail)


def qualify_kill_switch() -> dict[str, Any]:
    """Exercise the latching kill switch as a truth table; raise if any probe misbehaves.

    The property that matters for paper activation is **latching**: once tripped, the switch must
    keep blocking even after the triggering condition clears on its own. A switch that
    auto-re-arms would let a run resume into the same fault.
    """
    probes: list[dict[str, Any]] = []

    # Control: a fresh switch must PERMIT. Without this every "blocks" probe below is vacuous.
    switch = LatchingKillSwitch.armed()
    _require(switch.is_tripped is False, "a fresh kill switch reported itself tripped")
    switch.require_clear()  # must not raise
    probes.append({"probe": "armed_switch_permits", "observed": "require_clear() returned"})

    # Trip: must block, and must name why.
    switch.trip("synthetic risk breach (qualification probe)")
    _require(switch.is_tripped is True, "trip() did not latch")
    try:
        switch.require_clear()
    except KillSwitchTripped as exc:
        probes.append({"probe": "tripped_switch_blocks", "observed": type(exc).__name__})
    else:  # pragma: no cover - reaching here is the defect this probe exists to catch
        raise QualificationError("a tripped kill switch permitted an intent")
    _require(bool(switch.reason), "a tripped switch reported no reason")

    # Latching: the condition "clearing" must NOT re-arm it. Only an explicit reset may.
    first_reason = switch.reason
    switch.trip("a second, different reason")
    _require(
        switch.reason == first_reason,
        "a re-trip overwrote the first trip reason; the story of the original fault was lost",
    )
    _require(switch.trip_count == 2, f"trip_count was {switch.trip_count}, expected 2")
    _require(switch.is_tripped is True, "the switch un-latched without an explicit reset")
    probes.append(
        {
            "probe": "latches_and_preserves_first_reason",
            "observed": f"trip_count={switch.trip_count}, first reason preserved",
        }
    )

    # Reset requires a stated reason, and an empty reason must be refused.
    try:
        switch.reset(reason="")
    except Exception as exc:
        probes.append({"probe": "reset_requires_a_reason", "observed": type(exc).__name__})
    else:  # pragma: no cover
        raise QualificationError("reset accepted an empty reason")

    # Control: a proper reset must genuinely re-arm, or the switch is a one-way brick.
    switch.reset(reason="qualification probe complete")
    _require(switch.is_tripped is False, "an explicit reset did not re-arm the switch")
    _require(switch.reset_count == 1, f"reset_count was {switch.reset_count}, expected 1")
    switch.require_clear()  # must not raise
    probes.append({"probe": "explicit_reset_rearms", "observed": "require_clear() returned"})

    return {
        "mechanism": "eth_research.shadow.kill_switch.LatchingKillSwitch",
        "properties_qualified": [
            "armed switch permits",
            "tripped switch blocks every intent",
            "latches: a re-trip does not un-latch and does not overwrite the first reason",
            "reset refuses an empty reason",
            "explicit reset re-arms",
        ],
        "probes": probes,
        "probe_count": len(probes),
    }


def qualify_monitoring() -> dict[str, Any]:
    """Exercise every alert generator at, below and above its boundary; raise on misbehaviour.

    Each generator is checked in BOTH directions. A monitor that alerted on everything would
    satisfy every "alerts when bad" assertion and be useless in production, because an operator
    learns to ignore it.
    """
    probes: list[dict[str, Any]] = []

    # --- staleness: strictly greater than the budget alerts; exactly at the budget does not ---
    healthy = staleness_alert(as_of=_T1, last_bar_time=_T0, max_staleness_seconds=600)
    _require(healthy is None, "staleness alerted at exactly the budget (600s); boundary not strict")
    stale = staleness_alert(as_of=_T1, last_bar_time=_T0, max_staleness_seconds=599)
    _require(stale is not None, "staleness did not alert one second past the budget")
    assert stale is not None
    _require(stale.code == STALE_DATA_CODE, f"wrong code {stale.code}")
    _require(stale.severity == WARNING, f"staleness severity was {stale.severity}, want warning")
    probes.append(
        {
            "probe": "staleness_boundary_is_strict",
            "observed": f"600s->None, 599s->{stale.code}/{stale.severity}",
        }
    )

    # --- drawdown: equal to the limit does not alert; beyond it does, and is critical ---
    at_limit = drawdown_alert(as_of=_T0, equity=90.0, peak_equity=100.0, max_drawdown_fraction=0.10)
    _require(at_limit is None, "drawdown alerted at exactly the limit; boundary not strict")
    breached = drawdown_alert(as_of=_T0, equity=89.0, peak_equity=100.0, max_drawdown_fraction=0.10)
    _require(breached is not None, "drawdown did not alert past the limit")
    assert breached is not None
    _require(breached.code == DRAWDOWN_CODE, f"wrong code {breached.code}")
    _require(breached.severity == CRITICAL, f"drawdown severity was {breached.severity}")
    recovered = drawdown_alert(
        as_of=_T0, equity=100.0, peak_equity=100.0, max_drawdown_fraction=0.10
    )
    _require(recovered is None, "drawdown alerted at the peak with no loss at all")
    probes.append(
        {
            "probe": "drawdown_boundary_is_strict_and_critical",
            "observed": "10%->None, 11%->drawdown_breach/critical, 0%->None",
        }
    )

    # --- risk breach: no breached limits means silence; named limits appear in the message ---
    quiet = risk_breach_alert(as_of=_T0, breached_limits=())
    _require(quiet is None, "risk breach alerted with no limits breached")
    noisy = risk_breach_alert(as_of=_T0, breached_limits=("max_gross_exposure", "max_turnover"))
    _require(noisy is not None, "risk breach did not alert with two limits breached")
    assert noisy is not None
    _require(noisy.code == RISK_BREACH_CODE, f"wrong code {noisy.code}")
    _require(noisy.severity == CRITICAL, f"risk severity was {noisy.severity}")
    _require(
        "max_gross_exposure" in noisy.message and "max_turnover" in noisy.message,
        "the risk alert did not name the limits it breached; an unnamed breach is unactionable",
    )
    probes.append(
        {
            "probe": "risk_breach_names_every_breached_limit",
            "observed": noisy.message,
        }
    )

    # --- kill-switch alert: always produced, always critical, and carries the reason ---
    tripped = kill_switch_alert(as_of=_T0, reason="synthetic qualification trip")
    _require(tripped.code == KILL_SWITCH_CODE, f"wrong code {tripped.code}")
    _require(tripped.severity == CRITICAL, f"kill-switch severity was {tripped.severity}")
    _require(
        "synthetic qualification trip" in tripped.message,
        "the kill-switch alert dropped the trip reason",
    )
    probes.append(
        {
            "probe": "kill_switch_alert_is_critical_and_carries_reason",
            "observed": tripped.message,
        }
    )

    # --- every alert must round-trip through its own strict parser ---
    for alert in (stale, breached, noisy, tripped):
        reparsed = type(alert).parse("qualification", alert.to_canonical())
        _require(
            reparsed == alert,
            f"alert {alert.code} did not survive a canonical round-trip through its parser",
        )
    probes.append({"probe": "alerts_round_trip_through_the_strict_parser", "observed": "4/4 exact"})

    return {
        "mechanism": "eth_research.shadow.monitoring",
        "properties_qualified": [
            "staleness alerts strictly past the budget, not at it",
            "drawdown alerts strictly past the limit, not at it, and is critical",
            "risk breach is silent with nothing breached and names every breached limit",
            "kill-switch alert is critical and preserves the trip reason",
            "every alert round-trips through the strict parser unchanged",
        ],
        "probes": probes,
        "probe_count": len(probes),
    }


def build_qualification_records(repo_root: str | Path, *, write: bool = False) -> dict[str, Any]:
    """Run both qualifications and optionally write their records.

    Writing happens only after every probe has passed, so a record can never describe a
    qualification that did not run. There is no ``force`` and no way to write an empty record.
    """
    root = Path(repo_root)
    records = {
        KILL_SWITCH_QUALIFICATION_RELPATH: {
            "kind": "v2f_kill_switch_qualification",
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
            "qualified_on": "2026-07-29",
            "determinism": "fixed timestamps; no wall clock, no network, no market data",
            "money_at_risk": False,
            **qualify_kill_switch(),
        },
        MONITORING_QUALIFICATION_RELPATH: {
            "kind": "v2f_monitoring_qualification",
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
            "qualified_on": "2026-07-29",
            "determinism": "fixed timestamps; no wall clock, no network, no market data",
            "money_at_risk": False,
            **qualify_monitoring(),
        },
    }
    if write:
        for relpath, record in records.items():
            path = root / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return records


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    records = build_qualification_records(args.repo_root, write=args.write)
    summary = {
        relpath: {"kind": rec["kind"], "probe_count": rec["probe_count"]}
        for relpath, rec in records.items()
    }
    print(json.dumps({"ok": True, "qualifications": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
