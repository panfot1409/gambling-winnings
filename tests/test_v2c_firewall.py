"""V2C section 14: the candidate-free execution firewall proves V2C evaluates no strategy.

These tests hold the line that makes V2C data-only:

* ``cash_control`` is the *only* operational target the firewall resolves, and every intent it
  emits is exactly zero exposure/notional/fills/turnover.
* Every candidate id, callable, module, candidate-marked object, and forbidden request kind is
  refused fail-closed.
* The firewall module imports **no** candidate/strategy/evaluator/engine module (proven in a fresh
  interpreter), and the cash-control operational path reaches **none** of the candidate/engine entry
  points (proven by arming every one of them as a tripwire).
* The hard-coded legacy candidate id set is cross-checked against the real candidate modules so it
  cannot silently drift.
"""

from __future__ import annotations

import json
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest

from eth_research.v2c.firewall import (
    ALLOWED_REQUEST_KINDS,
    CASH_CONTROL_TARGET_ID,
    FORBIDDEN_REQUEST_KINDS,
    KNOWN_LEGACY_CANDIDATE_IDS,
    CashControl,
    CashControlIntent,
    V2CFirewallError,
    assert_no_candidate_reference,
    guard_request_kind,
    resolve_operational_target,
)

_AS_OF = "2024-03-01T00:00:00Z"
_AS_OF_CANONICAL = "2024-03-01T00:00:00+00:00"


# --------------------------------------------------------------------------- #
# The one allowed target, and its always-zero intent                          #
# --------------------------------------------------------------------------- #
def test_cash_control_is_the_only_resolvable_target() -> None:
    target = resolve_operational_target("cash_control")
    assert isinstance(target, CashControl)
    assert target.target_id == CASH_CONTROL_TARGET_ID == "cash_control"


def test_cash_control_intent_is_exactly_zero_exposure() -> None:
    target = resolve_operational_target("cash_control")
    intent = target.intent(as_of=_AS_OF)
    assert intent.risky_target_weight == 0.0
    assert intent.requested_notional == 0.0
    assert intent.requested_fills == 0
    assert intent.requested_turnover == 0.0
    # as_of is decoded and re-emitted canonically (UTC, ``...+00:00``).
    assert intent.as_of == _AS_OF_CANONICAL
    assert intent.to_canonical() == {
        "as_of": _AS_OF_CANONICAL,
        "risky_target_weight": 0.0,
        "requested_notional": 0.0,
        "requested_fills": 0,
        "requested_turnover": 0.0,
    }


def test_cash_control_intent_rejects_naive_or_non_utc_as_of() -> None:
    for bad in ("2024-03-01T00:00:00", "2024-03-01T00:00:00-05:00", "not-a-timestamp", 123):
        with pytest.raises(V2CFirewallError):
            CashControlIntent.zero(bad)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("risky_target_weight", 0.01),
        ("requested_notional", 1.0),
        ("requested_turnover", 0.5),
        ("requested_fills", 1),
    ],
)
def test_cash_control_intent_refuses_any_nonzero_field(field: str, value: object) -> None:
    kwargs: dict[str, Any] = {
        "as_of": _AS_OF_CANONICAL,
        "risky_target_weight": 0.0,
        "requested_notional": 0.0,
        "requested_fills": 0,
        "requested_turnover": 0.0,
    }
    kwargs[field] = value
    with pytest.raises(V2CFirewallError):
        CashControlIntent(**kwargs)


def test_cash_control_intent_refuses_bool_fills() -> None:
    # ``True`` is an int subclass equal to 1; it must not masquerade as a fill count.
    with pytest.raises(V2CFirewallError):
        CashControlIntent(
            as_of=_AS_OF_CANONICAL,
            risky_target_weight=0.0,
            requested_notional=0.0,
            requested_fills=True,
            requested_turnover=0.0,
        )


def test_cash_control_cannot_be_constructed_outside_the_firewall() -> None:
    with pytest.raises(V2CFirewallError):
        CashControl(_token=object())
    with pytest.raises(TypeError):
        CashControl()  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# Refusals: candidate ids, callables, modules, and other names                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("candidate_id", sorted(KNOWN_LEGACY_CANDIDATE_IDS))
def test_resolve_refuses_every_known_legacy_candidate_id(candidate_id: str) -> None:
    with pytest.raises(V2CFirewallError, match="legacy candidate id"):
        resolve_operational_target(candidate_id)


@pytest.mark.parametrize("name", ["", "   ", "buy_and_hold", "eth_trend", "cash", "cash_control "])
def test_resolve_refuses_non_cash_names(name: str) -> None:
    with pytest.raises(V2CFirewallError):
        resolve_operational_target(name)


def test_resolve_refuses_callables_modules_and_non_strings() -> None:
    def a_signal_function(_prices: object) -> float:  # a stand-in strategy/signal callable
        return 1.0

    for bad in (
        a_signal_function,
        json,
        sys,
        3,
        3.5,
        None,
        ["cash_control"],
        {"t": "cash_control"},
    ):
        with pytest.raises(V2CFirewallError):
            resolve_operational_target(bad)


# --------------------------------------------------------------------------- #
# The structural candidate-reference screen                                   #
# --------------------------------------------------------------------------- #
def test_assert_no_candidate_reference_passes_plain_data() -> None:
    for ok in ("cash_control", "any_non_candidate_string", 0, 1.0, None, [1, 2, 3], {"k": "v"}):
        assert_no_candidate_reference("input", ok)  # does not raise


def test_assert_no_candidate_reference_refuses_callables_and_modules() -> None:
    with pytest.raises(V2CFirewallError):
        assert_no_candidate_reference("input", lambda: 0.0)
    with pytest.raises(V2CFirewallError):
        assert_no_candidate_reference("input", json)


def test_assert_no_candidate_reference_refuses_marked_objects() -> None:
    class _CandidateLike:
        candidate_id = "cross_asset_btc_confirmed_eth_trend"

    class _StrategyLike:
        def generate_signals(self) -> None:  # a marker method
            return None

    for marked in (_CandidateLike(), _StrategyLike()):
        with pytest.raises(V2CFirewallError, match="candidate/strategy markers"):
            assert_no_candidate_reference("input", marked)


def test_assert_no_candidate_reference_refuses_known_id_strings() -> None:
    for candidate_id in KNOWN_LEGACY_CANDIDATE_IDS:
        with pytest.raises(V2CFirewallError, match="legacy candidate id"):
            assert_no_candidate_reference("input", candidate_id)


# --------------------------------------------------------------------------- #
# Request-kind allowlist                                                       #
# --------------------------------------------------------------------------- #
def test_guard_request_kind_admits_only_cash_control_operation() -> None:
    assert frozenset({"cash_control_operation"}) == ALLOWED_REQUEST_KINDS
    assert guard_request_kind("cash_control_operation") == "cash_control_operation"


@pytest.mark.parametrize("kind", sorted(FORBIDDEN_REQUEST_KINDS))
def test_guard_request_kind_refuses_every_forbidden_kind(kind: str) -> None:
    with pytest.raises(V2CFirewallError, match="forbidden"):
        guard_request_kind(kind)


def test_guard_request_kind_refuses_unknown_and_empty() -> None:
    for bad in ("evaluate", "", "run_backtest", 5, None):
        with pytest.raises(V2CFirewallError):
            guard_request_kind(bad)


def test_forbidden_request_kinds_are_the_thirteen_documented_kinds() -> None:
    assert (
        frozenset(
            {
                "candidate_id",
                "candidate_fingerprint",
                "strategy_callable",
                "signal_callable",
                "candidate_module",
                "research_protocol",
                "financial_data_endpoint",
                "nomination_rule",
                "return_metric",
                "equity_metric",
                "benchmark",
                "optimization_request",
                "market_performance_report",
            }
        )
        == FORBIDDEN_REQUEST_KINDS
    )
    assert len(FORBIDDEN_REQUEST_KINDS) == 13


# --------------------------------------------------------------------------- #
# Anti-drift: the hard-coded id set equals the real candidate modules' ids    #
# --------------------------------------------------------------------------- #
def test_known_legacy_candidate_ids_match_the_real_candidate_modules() -> None:
    # This test may import candidate modules; the firewall itself must not (proven separately).
    from eth_research.v2.candidates import MEANREV_SPEC, TREND_SPEC, VOL_SCALED_SPEC
    from eth_research.v2b.candidates import CANDIDATE_A, CANDIDATE_B

    real_ids = {
        MEANREV_SPEC.candidate_id,
        VOL_SCALED_SPEC.candidate_id,
        TREND_SPEC.candidate_id,
        CANDIDATE_A.candidate_id,
        CANDIDATE_B.candidate_id,
    }
    assert real_ids == KNOWN_LEGACY_CANDIDATE_IDS


# --------------------------------------------------------------------------- #
# The firewall imports no candidate/strategy/evaluator/engine module          #
# --------------------------------------------------------------------------- #
_BANNED_MODULES = (
    "eth_research.v2.candidates",
    "eth_research.v2.evaluator",
    "eth_research.v2.orchestrator",
    "eth_research.v2b.candidates",
    "eth_research.v2b.evaluation",
    "eth_research.v2b.execution",
    "eth_research.portfolio.engine",
    "eth_research.fractional.engine",
)


def test_firewall_imports_no_candidate_or_engine_module() -> None:
    banned = list(_BANNED_MODULES)
    code = (
        "import sys, json\n"
        "import eth_research.v2c.firewall as fw\n"
        f"banned = {banned!r}\n"
        "loaded = sorted(m for m in banned if m in sys.modules)\n"
        "t = fw.resolve_operational_target('cash_control')\n"
        "i = t.intent(as_of='2024-01-01T00:00:00Z')\n"
        "print(json.dumps({'loaded': loaded, 'weight': i.risky_target_weight}))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    payload = json.loads(proc.stdout)
    assert payload["loaded"] == [], payload["loaded"]
    assert payload["weight"] == 0.0


# --------------------------------------------------------------------------- #
# The cash-control path reaches no candidate/engine entry point               #
# --------------------------------------------------------------------------- #
def test_cash_control_path_reaches_no_candidate_or_engine_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import eth_research.portfolio.engine as engine
    import eth_research.v2.candidates as v2_candidates
    import eth_research.v2.evaluator as v2_evaluator
    import eth_research.v2.orchestrator as v2_orchestrator
    import eth_research.v2b.evaluation as v2b_evaluation

    tripped: list[str] = []

    def _make_tripwire(name: str) -> Any:
        def _tripwire(*_args: object, **_kwargs: object) -> Any:
            tripped.append(name)
            raise AssertionError(f"candidate/engine entry point reached: {name}")

        return _tripwire

    entry_points: tuple[tuple[ModuleType, str], ...] = (
        (v2_candidates, "build_all_fractional_strategies"),
        (v2_candidates, "build_fractional_strategy"),
        (v2_candidates, "build_buy_and_hold_benchmark"),
        (v2_candidates, "meanrev_signal_at"),
        (v2_candidates, "always_long_signal_at"),
        (v2_candidates, "trend_signal_at"),
        (v2_evaluator, "evaluate_program"),
        (v2_evaluator, "summarize_candidate"),
        (v2_orchestrator, "execute_evaluation"),
        (v2b_evaluation, "evaluate_candidate"),
        (engine, "run_portfolio_simulation"),
    )
    for module, attr in entry_points:
        monkeypatch.setattr(module, attr, _make_tripwire(f"{module.__name__}.{attr}"))

    # Sanity: the tripwires are actually armed (guards against a vacuous pass).
    with pytest.raises(AssertionError):
        v2_candidates.build_all_fractional_strategies()
    tripped.clear()  # discard the intentional sanity trip

    # Exercise a full candidate-free operational cycle through the firewall.
    guard_request_kind("cash_control_operation")
    target = resolve_operational_target("cash_control")
    for day in range(1, 6):
        intent = target.intent(as_of=f"2024-03-0{day}T00:00:00Z")
        assert intent.risky_target_weight == 0.0
        assert intent.requested_fills == 0
    assert_no_candidate_reference("operational_config", {"target": "cash_control", "steps": 5})

    # No candidate/engine entry point was reached by the cash-control path.
    assert tripped == []
