"""Deterministic sequential scenario-batch runner for the M4B portfolio simulator (§33).

A :class:`Scenario` is a fully self-contained research load: a universe plus the market panel,
protocol, membership, FX evidence, rebalance schedule, calendars, and (optional) corporate actions
it is run against. :func:`run_scenario_batch` runs a sequence of scenarios **sequentially and
deterministically** — no threads, no wall clock, no randomness, no shared mutable state between
scenarios — and returns each scenario's :class:`PortfolioResult` together with an order-sensitive
``batch_fingerprint`` over the ``(name, result_id)`` pairs. Re-running the same ordered scenarios
reproduces the batch fingerprint exactly.

Parallel execution is deliberately deferred: it would only be admissible if it were provably
deterministic and side-effect-free, and the sequential runner already saturates the offline research
use case. The annualization basis for each scenario's descriptive metrics is derived from its own
universe's bar interval, so the caller supplies no timing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from eth_research.api.serialization import CanonicalError
from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.corporate_actions import CorporateActionSet
from eth_research.portfolio.engine import PortfolioRunResult, run_portfolio_simulation
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.membership import MembershipSchedule
from eth_research.portfolio.metrics import compute_portfolio_metrics
from eth_research.portfolio.panel import MarketPanel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.result import PortfolioResult, build_portfolio_result
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.universe import UniverseSpec
from eth_research.portfolio.validation import domain_hash

__all__ = [
    "Scenario",
    "ScenarioBatchResult",
    "ScenarioOutcome",
    "run_scenario",
    "run_scenario_batch",
]

#: 365.25 days x 24 hours x 3600 seconds — the same year length the metrics layer uses.
_SECONDS_PER_YEAR = 365.25 * 24.0 * 3600.0


@dataclass(frozen=True)
class Scenario:
    """One self-contained research load: a universe and every input the engine runs it against."""

    name: str
    universe: UniverseSpec
    protocol: PortfolioProtocol
    panel: MarketPanel
    membership: MembershipSchedule
    fx: FxEvidence
    schedule: RebalanceSchedule
    calendars: Mapping[str, TradingCalendar]
    corporate_actions: CorporateActionSet | None = field(default=None)


@dataclass(frozen=True)
class ScenarioOutcome:
    """One scenario's run: its name, the fingerprinted run, and the built result artifact."""

    name: str
    run_result: PortfolioRunResult
    result: PortfolioResult

    def canonical(self) -> dict[str, Any]:
        return {"name": self.name, "result_id": self.result.result_id}


@dataclass(frozen=True)
class ScenarioBatchResult:
    """The deterministic outcome of a sequential scenario batch, order-sensitive by construction."""

    outcomes: tuple[ScenarioOutcome, ...]

    def canonical(self) -> dict[str, Any]:
        return {"outcomes": [outcome.canonical() for outcome in self.outcomes]}

    @property
    def batch_fingerprint(self) -> str:
        """A domain-separated hash over the ordered ``(name, result_id)`` pairs."""
        return domain_hash("portfolio_scenario_batch", self.canonical())


def run_scenario(scenario: Scenario) -> ScenarioOutcome:
    """Run one scenario end to end: simulate, compute descriptive metrics, build the result.

    The metrics' annualization basis is derived from the scenario's own universe bar interval, so no
    timing is passed in. :func:`build_portfolio_result` cross-checks the run's fingerprints against
    the bound universe and fails closed on any mismatch.
    """
    run = run_portfolio_simulation(
        scenario.protocol,
        scenario.panel,
        scenario.membership,
        scenario.fx,
        scenario.schedule,
        calendars=dict(scenario.calendars),
        corporate_actions=scenario.corporate_actions,
    )
    periods_per_year = _SECONDS_PER_YEAR / scenario.universe.bar_interval_seconds
    metrics = compute_portfolio_metrics(run, periods_per_year=periods_per_year)
    result = build_portfolio_result(run, metrics, scenario.universe)
    return ScenarioOutcome(name=scenario.name, run_result=run, result=result)


def run_scenario_batch(scenarios: Iterable[Scenario]) -> ScenarioBatchResult:
    """Run a sequence of scenarios sequentially and deterministically.

    Scenario names must be unique and non-empty (the batch fingerprint keys on them). Scenarios are
    run strictly in order; each is fully independent, so the batch carries no shared mutable state.
    """
    ordered: Sequence[Scenario] = list(scenarios)
    seen: set[str] = set()
    outcomes: list[ScenarioOutcome] = []
    for index, scenario in enumerate(ordered):
        if not scenario.name:
            raise CanonicalError(f"scenario[{index}]: name must be non-empty")
        if scenario.name in seen:
            raise CanonicalError(f"scenario[{index}]: duplicate name {scenario.name!r}")
        seen.add(scenario.name)
        outcomes.append(run_scenario(scenario))
    return ScenarioBatchResult(outcomes=tuple(outcomes))
