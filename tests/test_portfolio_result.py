"""PortfolioResult: build/verify, symmetric round-trip, tamper rejection, forbidden-ref scan."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pandas as pd
import pytest

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.corporate_actions import CorporateActionSet
from eth_research.portfolio.costs import CostParameters
from eth_research.portfolio.engine import run_portfolio_simulation
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.panel import build_market_panel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.result import (
    PortfolioResult,
    build_portfolio_result,
    verify_portfolio_result,
)
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.universe import UniverseSpec
from eth_research.portfolio.valuation import StalenessPolicy

_CAL_ID = "continuous_24_7"
_CALS = {_CAL_ID: TradingCalendar(_CAL_ID, _CAL_ID, (), "test")}
_FX = FxEvidence(observations=())
_CA = CorporateActionSet(actions=())
_PPY = 8766.0


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def _inst(symbol: str, base: str) -> InstrumentId:
    return InstrumentId(
        "crypto_spot", base, "USD", "synthetic", symbol, "spot", "USD", base, _CAL_ID
    )


A = _inst("A-USD", "AAA")
B = _inst("B-USD", "BBB")


def _moving(opens: Sequence[float], closes: Sequence[float]) -> pd.DataFrame:
    t = pd.date_range("2026-07-14T00:00:00", periods=len(opens), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": t,
            "close_time": t + pd.Timedelta(hours=1),
            "open": [float(o) for o in opens],
            "high": [float(max(o, c)) for o, c in zip(opens, closes, strict=True)],
            "low": [float(min(o, c)) for o, c in zip(opens, closes, strict=True)],
            "close": [float(c) for c in closes],
            "volume": [1000.0] * len(opens),
        }
    )


_MEMBERSHIP = MembershipSchedule(
    intervals=tuple(
        MembershipInterval(
            i, _ts("2026-07-14T00:00:00"), None, _ts("2026-07-14T00:00:00"), "listing", "test"
        )
        for i in (A, B)
    )
)
_SCHEDULE = RebalanceSchedule(
    timestamps=(_ts("2026-07-14T00:00:00"), _ts("2026-07-14T01:00:00"), _ts("2026-07-14T02:00:00"))
)
_PANEL = build_market_panel(
    {
        A: _moving([100.0, 105.0, 103.0, 108.0], [105.0, 103.0, 108.0, 110.0]),
        B: _moving([50.0, 52.0, 55.0, 53.0], [52.0, 55.0, 53.0, 57.0]),
    }
)
_PROTOCOL = PortfolioProtocol(
    base_currency="USD",
    initial_cash=1000.0,
    policy="equal_weight",
    cost_scenario=CostParameters(scenario="zero"),
    staleness=StalenessPolicy(max_staleness_seconds=1_000_000.0),
)
_UNIVERSE = UniverseSpec(
    base_currency="USD",
    instruments=(A, B),
    calendars=_CALS,
    bar_interval_seconds=3600,
    max_staleness_seconds=90000.0,
    membership_fingerprint=_MEMBERSHIP.fingerprint,
    fx_fingerprint=_FX.fingerprint,
    corporate_action_fingerprint=_CA.fingerprint,
    rebalance_schedule_fingerprint=_SCHEDULE.fingerprint,
)


def _built() -> tuple[PortfolioResult, object, object]:
    run = run_portfolio_simulation(_PROTOCOL, _PANEL, _MEMBERSHIP, _FX, _SCHEDULE, calendars=_CALS)
    metrics = compute_portfolio_metrics(run, periods_per_year=_PPY)
    result = build_portfolio_result(run, metrics, _UNIVERSE)
    return result, run, metrics


def test_build_then_verify_passes() -> None:
    result, run, _metrics = _built()
    verify_portfolio_result(result, _UNIVERSE, run)  # type: ignore[arg-type]
    assert len(result.result_id) == 64
    contrib = dict(result.per_currency_contribution)
    assert set(contrib) == {"USD"}
    assert contrib["USD"] == pytest.approx(0.0)


def test_result_is_deterministic() -> None:
    first, _r1, _m1 = _built()
    second, _r2, _m2 = _built()
    assert first.result_id == second.result_id
    assert first.canonical() == second.canonical()


def test_result_round_trips_through_strict_json() -> None:
    result, _run, _metrics = _built()
    payload = json.loads(json.dumps(result.canonical(), allow_nan=False))
    restored = PortfolioResult.from_mapping(payload)
    assert restored.canonical() == result.canonical()
    assert restored.result_id == result.result_id


def test_result_has_no_gate_holdout_or_path_reference() -> None:
    result, _run, _metrics = _built()
    blob = json.dumps(result.canonical())
    for forbidden in ("gate", "holdout", "/home/", "/tmp/", "test_split"):
        assert forbidden not in blob


def test_from_mapping_rejects_a_lied_cost_total() -> None:
    result, _run, _metrics = _built()
    payload = result.canonical()
    payload["cost_total"] = payload["cost_total"] + 5.0  # inconsistent with the metrics
    with pytest.raises(CanonicalError, match="cost_total"):
        PortfolioResult.from_mapping(payload)


def test_from_mapping_rejects_a_lied_asset_total() -> None:
    # An injected asset with a non-zero contribution breaks the reconciliation the parse enforces.
    result, _run, _metrics = _built()
    payload = result.canonical()
    payload["per_asset_contribution"].append(
        {
            "instrument_id": "z" * 64,
            "quote_currency": "USD",
            "local_price_pnl": 5.0,
            "fx_translation_pnl": 0.0,
        }
    )
    with pytest.raises(CanonicalError, match="local totals disagree"):
        PortfolioResult.from_mapping(payload)


def test_verify_rejects_a_structurally_extra_asset() -> None:
    # The full-graph verifier compares the per-asset set to the run, so even a zero extra is caught.
    result, run, _metrics = _built()
    padded = (
        *result.per_asset_contribution,
        type(result.per_asset_contribution[0])("z" * 64, "USD", 0.0, 0.0),
    )
    from dataclasses import replace

    tampered = replace(result, per_asset_contribution=padded)
    with pytest.raises(CanonicalError, match="per-asset attribution does not match"):
        verify_portfolio_result(tampered, _UNIVERSE, run)  # type: ignore[arg-type]


def test_verify_rejects_a_forged_terminal_equity_and_metrics() -> None:
    # A result that overstates terminal equity — bumping cumulative_residual to keep its own
    # internal roll-up balanced and inventing a Sharpe — must be refused. verify binds the headline
    # equity and the whole metrics block to the run, not merely to the free-residual roll-up.
    from dataclasses import replace

    result, run, _metrics = _built()
    forge = 50_000.0
    forged_metrics = replace(
        result.metrics,
        terminal_equity=result.metrics.terminal_equity + forge,
        total_return=(result.terminal_equity + forge) / result.initial_equity - 1.0,
        cumulative_residual=result.metrics.cumulative_residual + forge,
        sharpe_ratio=9.99,
    )
    forged = replace(result, terminal_equity=result.terminal_equity + forge, metrics=forged_metrics)
    with pytest.raises(CanonicalError, match="terminal equity does not match the run"):
        verify_portfolio_result(forged, _UNIVERSE, run)  # type: ignore[arg-type]

    # A forge that keeps terminal equity honest but invents a single metric is caught by the
    # metrics recomputation from the run.
    metrics_only = replace(result, metrics=replace(result.metrics, sharpe_ratio=9.99))
    with pytest.raises(CanonicalError, match="metrics do not match the run"):
        verify_portfolio_result(metrics_only, _UNIVERSE, run)  # type: ignore[arg-type]


def test_from_mapping_rejects_metrics_equity_disagreeing_with_the_result() -> None:
    # Parse-layer defense: the result's headline terminal equity must agree with the metrics block
    # it carries, so a load that bumps only one of the two is rejected before any run is consulted.
    result, _run, _metrics = _built()
    payload = result.canonical()
    payload["terminal_equity"] = payload["terminal_equity"] + 1000.0
    with pytest.raises(CanonicalError, match="terminal_equity"):
        PortfolioResult.from_mapping(payload)


def test_verify_rejects_forged_calendar_fingerprints() -> None:
    # The result's calendar_fingerprints must equal the run's — not be an unchecked free plug.
    # Replacing them with valid-format lies (leaving the universe fingerprint intact) must be
    # refused.
    from dataclasses import replace

    result, run, _metrics = _built()
    forged = replace(result, calendar_fingerprints=((_CAL_ID, "a" * 64),))
    with pytest.raises(CanonicalError, match="calendar fingerprints do not match the run"):
        verify_portfolio_result(forged, _UNIVERSE, run)  # type: ignore[arg-type]


def test_build_rejects_a_run_under_a_different_calendar() -> None:
    # A run produced under one calendar must not be certified against a universe declaring another
    # (same calendar_id, different source -> different fingerprint -> a materially different run).
    # The membership / schedule / base all match, so only the calendar cross-check can catch it.
    _result, run, metrics = _built()
    other = UniverseSpec(
        base_currency="USD",
        instruments=(A, B),
        calendars={_CAL_ID: TradingCalendar(_CAL_ID, _CAL_ID, (), "other")},
        bar_interval_seconds=3600,
        max_staleness_seconds=90000.0,
        membership_fingerprint=_MEMBERSHIP.fingerprint,
        fx_fingerprint=_FX.fingerprint,
        corporate_action_fingerprint=_CA.fingerprint,
        rebalance_schedule_fingerprint=_SCHEDULE.fingerprint,
    )
    with pytest.raises(CanonicalError, match="run calendars do not match the universe"):
        build_portfolio_result(run, metrics, other)  # type: ignore[arg-type]


def test_verify_rejects_a_relabeled_base_currency() -> None:
    # The equity / PnL numbers are USD; relabeling the artifact's base_currency to EUR must not
    # verify.
    from dataclasses import replace

    result, run, _metrics = _built()
    forged = replace(result, base_currency="EUR")
    with pytest.raises(CanonicalError, match="base currency does not match the run"):
        verify_portfolio_result(forged, _UNIVERSE, run)  # type: ignore[arg-type]


def test_verify_rejects_a_forged_package_version() -> None:
    # package_version is bound provenance, not a free label: a result stamped with a foreign version
    # must not verify against the running package.
    from dataclasses import replace

    result, run, _metrics = _built()
    forged = replace(result, package_version="9.9.9-forged")
    with pytest.raises(CanonicalError, match="package version does not match"):
        verify_portfolio_result(forged, _UNIVERSE, run)  # type: ignore[arg-type]


def test_verify_rejects_a_substituted_universe() -> None:
    result, run, _metrics = _built()
    other = UniverseSpec(
        base_currency="USD",
        instruments=(A, B),
        calendars=_CALS,
        bar_interval_seconds=7200,  # different interval -> different universe fingerprint
        max_staleness_seconds=90000.0,
        membership_fingerprint=_MEMBERSHIP.fingerprint,
        fx_fingerprint=_FX.fingerprint,
        corporate_action_fingerprint=_CA.fingerprint,
        rebalance_schedule_fingerprint=_SCHEDULE.fingerprint,
    )
    with pytest.raises(CanonicalError, match="universe fingerprint"):
        verify_portfolio_result(result, other, run)  # type: ignore[arg-type]


def test_build_rejects_universe_schedule_mismatch() -> None:
    run = run_portfolio_simulation(_PROTOCOL, _PANEL, _MEMBERSHIP, _FX, _SCHEDULE, calendars=_CALS)
    metrics = compute_portfolio_metrics(run, periods_per_year=_PPY)
    wrong = UniverseSpec(
        base_currency="USD",
        instruments=(A, B),
        calendars=_CALS,
        bar_interval_seconds=3600,
        max_staleness_seconds=90000.0,
        membership_fingerprint=_MEMBERSHIP.fingerprint,
        fx_fingerprint=_FX.fingerprint,
        corporate_action_fingerprint=_CA.fingerprint,
        rebalance_schedule_fingerprint="f" * 64,  # not the run's schedule
    )
    with pytest.raises(CanonicalError, match="schedule fingerprint does not match"):
        build_portfolio_result(run, metrics, wrong)
