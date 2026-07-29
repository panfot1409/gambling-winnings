"""The kill-switch and monitoring qualifications must be earned, not asserted.

``derive_requirements`` satisfies ``kill_switch_qualified`` and ``monitoring_qualified`` from a
*presence* check: a plain non-symlink JSON object at each path. ``echo '{}' > …`` would satisfy
that. What makes the requirement mean something is not the file — it is that the only supported
way to produce the file runs a truth table against the real mechanism and raises instead of
writing when any probe misbehaves.

So the tests that matter here are the refusals. Each mutation below breaks exactly one property
of the real mechanism and asserts that (a) the qualification raises, and (b) **nothing is
written** — a regressed mechanism must take the requirement back to false rather than leave a
stale record standing.

Every group carries its passing control: a qualifier that raised unconditionally would satisfy
every refusal below while qualifying nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import eth_research.v2f.qualification as qual
from eth_research.shadow import monitoring
from eth_research.shadow.kill_switch import LatchingKillSwitch
from eth_research.v2.strict import require_nonempty_str
from eth_research.v2e.paper import (
    KILL_SWITCH_QUALIFICATION_RELPATH,
    MONITORING_QUALIFICATION_RELPATH,
    derive_requirements,
    derive_resting_state,
)
from eth_research.v2f.qualification import (
    QualificationError,
    build_qualification_records,
    qualify_kill_switch,
    qualify_monitoring,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_RELPATHS = (KILL_SWITCH_QUALIFICATION_RELPATH, MONITORING_QUALIFICATION_RELPATH)


# --- controls: both qualifications pass against the real, unmodified mechanisms --------------


def test_control_the_real_kill_switch_qualifies() -> None:
    """Without this, every refusal below could be a qualifier that always raises."""
    record = qualify_kill_switch()
    assert record["probe_count"] == 5
    assert record["mechanism"] == "eth_research.shadow.kill_switch.LatchingKillSwitch"


def test_control_the_real_monitoring_qualifies() -> None:
    record = qualify_monitoring()
    assert record["probe_count"] == 5
    assert record["mechanism"] == "eth_research.shadow.monitoring"


@pytest.mark.parametrize("relpath", _RELPATHS)
def test_control_a_clean_build_writes_both_records(tmp_path: Path, relpath: str) -> None:
    build_qualification_records(tmp_path, write=True)
    doc = json.loads((tmp_path / relpath).read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    assert doc["probes"], "a record with no probes describes no qualification"
    assert doc["probe_count"] == len(doc["probes"])
    assert doc["money_at_risk"] is False


def test_every_probe_records_what_it_observed() -> None:
    """A probe list of bare names would be a checklist, not evidence."""
    for record in build_qualification_records(REPO_ROOT, write=False).values():
        for probe in record["probes"]:
            assert probe["probe"], "a probe with no name"
            assert probe["observed"], f"{probe['probe']} recorded no observation"


# --- kill-switch mutations: each breaks one property, each must be refused -------------------


class _NonLatchingSwitch(LatchingKillSwitch):
    """Mutation: a re-trip overwrites the first reason (the original fault's story is lost)."""

    @staticmethod
    def armed() -> _NonLatchingSwitch:
        return _NonLatchingSwitch(_tripped=False, _reason=None, _trip_count=0, _reset_count=0)

    def trip(self, reason: str) -> None:
        self._tripped = True
        self._reason = reason
        self._trip_count += 1


class _NeverBlocksSwitch(LatchingKillSwitch):
    """Mutation: ``require_clear`` is a no-op — the switch trips but stops nothing."""

    @staticmethod
    def armed() -> _NeverBlocksSwitch:
        return _NeverBlocksSwitch(_tripped=False, _reason=None, _trip_count=0, _reset_count=0)

    def require_clear(self) -> None:
        return None


class _AlwaysBlocksSwitch(LatchingKillSwitch):
    """Mutation: blocks even when armed — the useless-but-'safe' failure the control catches."""

    @staticmethod
    def armed() -> _AlwaysBlocksSwitch:
        return _AlwaysBlocksSwitch(_tripped=True, _reason="stuck", _trip_count=0, _reset_count=0)


class _BrickedResetSwitch(LatchingKillSwitch):
    """Mutation: an explicit reset does not re-arm — a one-way brick, not a kill switch.

    The reason check is kept, deliberately. Dropping it too would break a *second* property and
    the earlier "reset requires a reason" probe would fire first, so the test would no longer
    prove that the re-arm probe is the one doing the work.
    """

    @staticmethod
    def armed() -> _BrickedResetSwitch:
        return _BrickedResetSwitch(_tripped=False, _reason=None, _trip_count=0, _reset_count=0)

    def reset(self, *, reason: str) -> None:
        require_nonempty_str("reason", reason)
        self._reset_count += 1


class _SilentEmptyResetSwitch(LatchingKillSwitch):
    """Mutation: reset accepts an empty reason — an unattributed re-arm."""

    @staticmethod
    def armed() -> _SilentEmptyResetSwitch:
        return _SilentEmptyResetSwitch(_tripped=False, _reason=None, _trip_count=0, _reset_count=0)

    def reset(self, *, reason: str) -> None:
        self._tripped = False
        self._reason = None
        self._reset_count += 1


@pytest.mark.parametrize(
    ("double", "expected"),
    [
        pytest.param(_NonLatchingSwitch, "overwrote the first trip reason", id="non-latching"),
        pytest.param(_NeverBlocksSwitch, "permitted an intent", id="never-blocks"),
        pytest.param(_AlwaysBlocksSwitch, "fresh kill switch reported itself tripped", id="stuck"),
        pytest.param(_BrickedResetSwitch, "did not re-arm", id="bricked-reset"),
        pytest.param(_SilentEmptyResetSwitch, "accepted an empty reason", id="empty-reset"),
    ],
)
def test_a_broken_kill_switch_is_refused(
    monkeypatch: pytest.MonkeyPatch, double: type[LatchingKillSwitch], expected: str
) -> None:
    monkeypatch.setattr(qual, "LatchingKillSwitch", double)
    with pytest.raises(QualificationError, match=expected):
        qualify_kill_switch()


# --- monitoring mutations --------------------------------------------------------------------


def _non_strict_staleness(
    *, as_of: object, last_bar_time: object, max_staleness_seconds: int
) -> monitoring.Alert | None:
    """Mutation: alerts *at* the budget, not strictly past it."""
    return monitoring.staleness_alert(
        as_of=as_of, last_bar_time=last_bar_time, max_staleness_seconds=max_staleness_seconds - 1
    )


def _mute_staleness(
    *, as_of: object, last_bar_time: object, max_staleness_seconds: int
) -> monitoring.Alert | None:
    """Mutation: never alerts — stale data passes silently."""
    return None


def _non_strict_drawdown(
    *, as_of: object, equity: float, peak_equity: float, max_drawdown_fraction: float
) -> monitoring.Alert | None:
    """Mutation: alerts *at* the limit, not strictly past it."""
    return monitoring.drawdown_alert(
        as_of=as_of,
        equity=equity,
        peak_equity=peak_equity,
        max_drawdown_fraction=max_drawdown_fraction * 0.999,
    )


def _warning_drawdown(
    *, as_of: object, equity: float, peak_equity: float, max_drawdown_fraction: float
) -> monitoring.Alert | None:
    """Mutation: a breached drawdown downgraded to a warning."""
    alert = monitoring.drawdown_alert(
        as_of=as_of,
        equity=equity,
        peak_equity=peak_equity,
        max_drawdown_fraction=max_drawdown_fraction,
    )
    if alert is None:
        return None
    return monitoring.Alert(
        as_of=alert.as_of, severity=monitoring.WARNING, code=alert.code, message=alert.message
    )


def _unnamed_risk(*, as_of: object, breached_limits: tuple[str, ...]) -> monitoring.Alert | None:
    """Mutation: alerts without naming which limits broke — an unactionable page."""
    if not breached_limits:
        return None
    return monitoring.risk_breach_alert(as_of=as_of, breached_limits=("a limit",))


def _always_noisy_risk(
    *, as_of: object, breached_limits: tuple[str, ...]
) -> monitoring.Alert | None:
    """Mutation: alerts with nothing breached — the monitor an operator learns to ignore."""
    limits = breached_limits or ("phantom",)
    return monitoring.risk_breach_alert(as_of=as_of, breached_limits=limits)


def _reasonless_kill_switch_alert(*, as_of: object, reason: str) -> monitoring.Alert:
    """Mutation: the alert drops the trip reason."""
    return monitoring.kill_switch_alert(as_of=as_of, reason="unspecified")


@pytest.mark.parametrize(
    ("name", "double", "expected"),
    [
        pytest.param(
            "staleness_alert", _non_strict_staleness, "boundary not strict", id="stale-at-budget"
        ),
        pytest.param("staleness_alert", _mute_staleness, "did not alert", id="staleness-mute"),
        pytest.param(
            "drawdown_alert", _non_strict_drawdown, "boundary not strict", id="drawdown-at-limit"
        ),
        pytest.param("drawdown_alert", _warning_drawdown, "severity was", id="drawdown-downgraded"),
        pytest.param(
            "risk_breach_alert", _unnamed_risk, "did not name the limits", id="risk-unnamed"
        ),
        pytest.param(
            "risk_breach_alert", _always_noisy_risk, "with no limits breached", id="risk-always-on"
        ),
        pytest.param(
            "kill_switch_alert",
            _reasonless_kill_switch_alert,
            "dropped the trip reason",
            id="kill-switch-reasonless",
        ),
    ],
)
def test_a_broken_monitor_is_refused(
    monkeypatch: pytest.MonkeyPatch, name: str, double: Any, expected: str
) -> None:
    monkeypatch.setattr(qual, name, double)
    with pytest.raises(QualificationError, match=expected):
        qualify_monitoring()


def test_a_lying_alert_parser_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation: the strict parser no longer reconstructs what it was given.

    An alert that does not survive its own canonical round-trip cannot be trusted in a journal,
    which is the only place an operator sees it after the fact.
    """
    monkeypatch.setattr(
        monitoring.Alert,
        "parse",
        staticmethod(
            lambda label, value: monitoring.Alert(
                as_of="2026-07-29T00:00:00Z",
                severity=monitoring.CRITICAL,
                code="something_else",
                message="not what was parsed",
            )
        ),
    )
    with pytest.raises(QualificationError, match="did not survive a canonical round-trip"):
        qualify_monitoring()


# --- a refused qualification must write nothing -----------------------------------------------


@pytest.mark.parametrize(
    ("attr", "double"),
    [
        pytest.param("LatchingKillSwitch", _NeverBlocksSwitch, id="kill-switch-broken"),
        pytest.param("drawdown_alert", _non_strict_drawdown, id="monitoring-broken"),
    ],
)
def test_a_refused_qualification_leaves_no_record_behind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, attr: str, double: Any
) -> None:
    """The requirement must go back to false, not stay true on a file written before the check.

    This is the property that stops a partially-written record from qualifying a mechanism that
    has since regressed: both qualifications run to completion before anything touches the disk.
    """
    monkeypatch.setattr(qual, attr, double)
    with pytest.raises(QualificationError):
        build_qualification_records(tmp_path, write=True)
    for relpath in _RELPATHS:
        assert not (tmp_path / relpath).exists(), f"{relpath} was written by a failed run"


def test_write_false_touches_nothing(tmp_path: Path) -> None:
    build_qualification_records(tmp_path, write=False)
    for relpath in _RELPATHS:
        assert not (tmp_path / relpath).exists()


def test_the_build_is_deterministic(tmp_path: Path) -> None:
    """A wall clock would make identical mechanisms qualify differently on different days."""
    first = build_qualification_records(tmp_path, write=True)
    first_bytes = {p: (tmp_path / p).read_bytes() for p in _RELPATHS}
    second = build_qualification_records(tmp_path, write=True)
    assert first == second
    assert {p: (tmp_path / p).read_bytes() for p in _RELPATHS} == first_bytes


# --- the committed records must still describe the live mechanisms ----------------------------


@pytest.mark.parametrize("relpath", _RELPATHS)
def test_the_committed_record_matches_a_fresh_qualification(relpath: str) -> None:
    """Drift check: if a mechanism regresses, the committed record stops matching and this fails.

    Without it the records are historical claims. With it they are pinned to the code that is
    actually importable right now.
    """
    committed = json.loads((REPO_ROOT / relpath).read_text(encoding="utf-8"))
    fresh = build_qualification_records(REPO_ROOT, write=False)[relpath]
    assert committed == fresh


# --- what the records do, and do not, unlock --------------------------------------------------


def test_the_two_requirements_are_now_satisfied_in_this_repository() -> None:
    requirements = derive_requirements(REPO_ROOT)
    assert requirements.kill_switch_qualified is True
    assert requirements.monitoring_qualified is True


def test_qualifying_them_does_not_authorize_paper_activation() -> None:
    """The point of the matrix: closing the two implementation items unlocks nothing by itself.

    Eleven requirements remain unmet — nine of them because no one-shot has nominated a
    candidate, one because no human has signed the activation, one because no release freeze
    exists for a candidate that does not exist.
    """
    requirements = derive_requirements(REPO_ROOT)
    assert requirements.all_satisfied is False
    assert derive_resting_state(requirements)[0] == "disabled"
    assert "kill_switch_qualified" not in requirements.unmet
    assert "monitoring_qualified" not in requirements.unmet
    assert "human_approval_artifact" in requirements.unmet
    assert "eligible_nominated_candidate" in requirements.unmet


def test_the_records_claim_nothing_about_data_money_or_evaluation() -> None:
    """A qualification record is not a place to smuggle a capability claim."""
    for relpath in _RELPATHS:
        raw = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        doc = json.loads(raw)
        assert doc["money_at_risk"] is False
        lowered = raw.lower()
        for forbidden in ("api_key", "order", "exchange", "wallet", "capital", "live"):
            assert forbidden not in lowered, f"{relpath} mentions {forbidden!r}"
