"""The portfolio run result artifact and its full-graph verifier (Milestone 4B, §26-27).

A :class:`PortfolioResult` is the strict, canonical, self-identifying record of one simulation run.
It binds — by fingerprint — every piece of evidence the run was produced against (the universe, the
market panel, the protocol, the membership schedule, the FX evidence, the corporate-action set, the
rebalance schedule, and each calendar), together with the base currency, the initial and terminal
equity, the descriptive metrics, the per-asset and per-currency attribution totals, the total cost,
the fill count, and a size-bounded per-event state commitment (tau, equity, cash, state hash). Its
``result_id`` is a domain-separated content hash over all of that — deterministic and reproducible,
with no wall-clock timestamp, no absolute path, and no reference to any gate, holdout, or split.

:func:`build_portfolio_result` assembles the artifact from a run and its metrics, cross-checking
that the run's own fingerprints agree with the bound universe. :func:`verify_portfolio_result` is
the full-graph verifier: it re-derives the per-asset totals and event commitments from the run,
re-checks every identity against the universe and the run, confirms the attribution roll-ups
telescope to the equity change, and refuses a result edited to disagree with its evidence.
Construction and parsing are symmetric and strict — :meth:`PortfolioResult.from_mapping` rejects
unknown or missing keys, NaN/Infinity, booleans-as-ints, and internally inconsistent totals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_research.api.serialization import (
    CanonicalError,
    require_finite_float,
    require_int,
    require_list,
    require_mapping,
    require_sha256_hex,
    require_str,
)
from eth_research.portfolio import M4B_PACKAGE_VERSION
from eth_research.portfolio._time import iso_utc
from eth_research.portfolio.currencies import require_currency_code
from eth_research.portfolio.engine import PortfolioRunResult
from eth_research.portfolio.metrics import PortfolioMetrics
from eth_research.portfolio.universe import UniverseSpec
from eth_research.portfolio.validation import domain_hash, exact_keys

__all__ = [
    "RESULT_SCHEMA_VERSION",
    "AssetTotal",
    "EventCommitment",
    "PortfolioResult",
    "build_portfolio_result",
    "verify_portfolio_result",
]

RESULT_SCHEMA_VERSION = 1
_RECONCILE_TOLERANCE = 1e-6

_RESULT_FIELDS = {
    "schema_version",
    "package_version",
    "universe_fingerprint",
    "panel_fingerprint",
    "protocol_fingerprint",
    "membership_fingerprint",
    "fx_fingerprint",
    "corporate_action_fingerprint",
    "schedule_fingerprint",
    "calendar_fingerprints",
    "base_currency",
    "initial_equity",
    "terminal_equity",
    "metrics",
    "per_asset_contribution",
    "per_currency_contribution",
    "cost_total",
    "num_fills",
    "event_commitments",
    "run_result_fingerprint",
    "final_state_fingerprint",
}


@dataclass(frozen=True)
class AssetTotal:
    """One instrument's run-total local-price and FX-translation attribution."""

    instrument_id: str
    quote_currency: str
    local_price_pnl: float
    fx_translation_pnl: float

    def canonical(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "quote_currency": self.quote_currency,
            "local_price_pnl": self.local_price_pnl,
            "fx_translation_pnl": self.fx_translation_pnl,
        }


@dataclass(frozen=True)
class EventCommitment:
    """A size-bounded commitment to one event: its time, equity, cash, and state hash."""

    tau: str
    equity: float
    cash: float
    state_fingerprint: str

    def canonical(self) -> dict[str, Any]:
        return {
            "tau": self.tau,
            "equity": self.equity,
            "cash": self.cash,
            "state_fingerprint": self.state_fingerprint,
        }


def _aggregate_per_asset(run_result: PortfolioRunResult) -> tuple[AssetTotal, ...]:
    totals: dict[str, list[Any]] = {}
    for event in run_result.events:
        for contribution in event.attribution.per_asset:
            acc = totals.setdefault(
                contribution.instrument_id, [contribution.quote_currency, 0.0, 0.0]
            )
            acc[1] += contribution.local_price_pnl
            acc[2] += contribution.fx_translation_pnl
    return tuple(
        AssetTotal(
            instrument_id=instrument_id,
            quote_currency=acc[0],
            local_price_pnl=acc[1],
            fx_translation_pnl=acc[2],
        )
        for instrument_id, acc in sorted(totals.items())
    )


def _per_currency(per_asset: tuple[AssetTotal, ...]) -> tuple[tuple[str, float], ...]:
    totals: dict[str, float] = {}
    for asset in per_asset:
        totals[asset.quote_currency] = (
            totals.get(asset.quote_currency, 0.0) + asset.fx_translation_pnl
        )
    return tuple(sorted(totals.items()))


def _event_commitments(run_result: PortfolioRunResult) -> tuple[EventCommitment, ...]:
    return tuple(
        EventCommitment(
            tau=iso_utc(event.tau),
            equity=event.equity,
            cash=event.cash,
            state_fingerprint=event.state_fingerprint,
        )
        for event in run_result.events
    )


@dataclass(frozen=True)
class PortfolioResult:
    """The immutable, fingerprinted, self-identifying record of one simulation run."""

    package_version: str
    universe_fingerprint: str
    panel_fingerprint: str
    protocol_fingerprint: str
    membership_fingerprint: str
    fx_fingerprint: str
    corporate_action_fingerprint: str
    schedule_fingerprint: str
    calendar_fingerprints: tuple[tuple[str, str], ...]
    base_currency: str
    initial_equity: float
    terminal_equity: float
    metrics: PortfolioMetrics
    per_asset_contribution: tuple[AssetTotal, ...]
    cost_total: float
    num_fills: int
    event_commitments: tuple[EventCommitment, ...]
    run_result_fingerprint: str
    final_state_fingerprint: str

    @property
    def per_currency_contribution(self) -> tuple[tuple[str, float], ...]:
        return _per_currency(self.per_asset_contribution)

    def canonical(self) -> dict[str, Any]:
        """The canonical, JSON-safe result mapping (deterministic; no wall-clock, no paths)."""
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "package_version": self.package_version,
            "universe_fingerprint": self.universe_fingerprint,
            "panel_fingerprint": self.panel_fingerprint,
            "protocol_fingerprint": self.protocol_fingerprint,
            "membership_fingerprint": self.membership_fingerprint,
            "fx_fingerprint": self.fx_fingerprint,
            "corporate_action_fingerprint": self.corporate_action_fingerprint,
            "schedule_fingerprint": self.schedule_fingerprint,
            "calendar_fingerprints": [
                {"calendar_id": calendar_id, "fingerprint": fingerprint}
                for calendar_id, fingerprint in self.calendar_fingerprints
            ],
            "base_currency": self.base_currency,
            "initial_equity": self.initial_equity,
            "terminal_equity": self.terminal_equity,
            "metrics": self.metrics.canonical(),
            "per_asset_contribution": [asset.canonical() for asset in self.per_asset_contribution],
            "per_currency_contribution": [
                {"currency": currency, "fx_translation_pnl": value}
                for currency, value in self.per_currency_contribution
            ],
            "cost_total": self.cost_total,
            "num_fills": self.num_fills,
            "event_commitments": [event.canonical() for event in self.event_commitments],
            "run_result_fingerprint": self.run_result_fingerprint,
            "final_state_fingerprint": self.final_state_fingerprint,
        }

    @property
    def result_id(self) -> str:
        """The deterministic, domain-separated identity of this result artifact."""
        return domain_hash("portfolio_result", self.canonical())

    @classmethod
    def from_mapping(cls, data: Any, *, field: str = "portfolio_result") -> PortfolioResult:
        """Rebuild from an untrusted canonical mapping, rejecting unknown/missing keys and NaN."""
        mapping = require_mapping(data, field)
        exact_keys(mapping, _RESULT_FIELDS, field)
        if (
            require_int(mapping["schema_version"], f"{field}.schema_version")
            != RESULT_SCHEMA_VERSION
        ):
            raise CanonicalError(f"{field}.schema_version: unsupported")
        calendars = tuple(
            (
                require_str(
                    require_mapping(row, f"{field}.calendar_fingerprints[{i}]")["calendar_id"],
                    f"{field}.calendar_fingerprints[{i}].calendar_id",
                ),
                require_sha256_hex(
                    require_mapping(row, f"{field}.calendar_fingerprints[{i}]")["fingerprint"],
                    f"{field}.calendar_fingerprints[{i}].fingerprint",
                ),
            )
            for i, row in enumerate(
                require_list(mapping["calendar_fingerprints"], f"{field}.calendar_fingerprints")
            )
        )
        per_asset = tuple(
            _asset_from_mapping(row, f"{field}.per_asset_contribution[{i}]")
            for i, row in enumerate(
                require_list(mapping["per_asset_contribution"], f"{field}.per_asset_contribution")
            )
        )
        events = tuple(
            _event_from_mapping(row, f"{field}.event_commitments[{i}]")
            for i, row in enumerate(
                require_list(mapping["event_commitments"], f"{field}.event_commitments")
            )
        )
        result = cls(
            package_version=require_str(mapping["package_version"], f"{field}.package_version"),
            universe_fingerprint=require_sha256_hex(
                mapping["universe_fingerprint"], f"{field}.universe_fingerprint"
            ),
            panel_fingerprint=require_sha256_hex(
                mapping["panel_fingerprint"], f"{field}.panel_fingerprint"
            ),
            protocol_fingerprint=require_sha256_hex(
                mapping["protocol_fingerprint"], f"{field}.protocol_fingerprint"
            ),
            membership_fingerprint=require_sha256_hex(
                mapping["membership_fingerprint"], f"{field}.membership_fingerprint"
            ),
            fx_fingerprint=require_sha256_hex(mapping["fx_fingerprint"], f"{field}.fx_fingerprint"),
            corporate_action_fingerprint=require_sha256_hex(
                mapping["corporate_action_fingerprint"], f"{field}.corporate_action_fingerprint"
            ),
            schedule_fingerprint=require_sha256_hex(
                mapping["schedule_fingerprint"], f"{field}.schedule_fingerprint"
            ),
            calendar_fingerprints=calendars,
            base_currency=require_currency_code(
                require_str(mapping["base_currency"], f"{field}.base_currency"),
                f"{field}.base_currency",
            ),
            initial_equity=require_finite_float(
                mapping["initial_equity"], f"{field}.initial_equity"
            ),
            terminal_equity=require_finite_float(
                mapping["terminal_equity"], f"{field}.terminal_equity"
            ),
            metrics=PortfolioMetrics.from_mapping(mapping["metrics"], field=f"{field}.metrics"),
            per_asset_contribution=per_asset,
            cost_total=require_finite_float(mapping["cost_total"], f"{field}.cost_total"),
            num_fills=require_int(mapping["num_fills"], f"{field}.num_fills"),
            event_commitments=events,
            run_result_fingerprint=require_sha256_hex(
                mapping["run_result_fingerprint"], f"{field}.run_result_fingerprint"
            ),
            final_state_fingerprint=require_sha256_hex(
                mapping["final_state_fingerprint"], f"{field}.final_state_fingerprint"
            ),
        )
        _check_internal_consistency(result, field)
        # The stored per_currency must match what the per-asset totals imply (no lied totals).
        stored_currency = [
            (
                require_str(
                    require_mapping(row, f"{field}.per_currency_contribution[{i}]")["currency"],
                    f"{field}.per_currency_contribution[{i}].currency",
                ),
                require_finite_float(
                    require_mapping(row, f"{field}.per_currency_contribution[{i}]")[
                        "fx_translation_pnl"
                    ],
                    f"{field}.per_currency_contribution[{i}].fx",
                ),
            )
            for i, row in enumerate(
                require_list(
                    mapping["per_currency_contribution"], f"{field}.per_currency_contribution"
                )
            )
        ]
        if tuple(stored_currency) != result.per_currency_contribution:
            raise CanonicalError(
                f"{field}.per_currency_contribution: does not match the per-asset totals"
            )
        return result


def _asset_from_mapping(data: Any, field: str) -> AssetTotal:
    mapping = require_mapping(data, field)
    exact_keys(
        mapping,
        {"instrument_id", "quote_currency", "local_price_pnl", "fx_translation_pnl"},
        field,
    )
    return AssetTotal(
        instrument_id=require_str(mapping["instrument_id"], f"{field}.instrument_id"),
        quote_currency=require_str(mapping["quote_currency"], f"{field}.quote_currency"),
        local_price_pnl=require_finite_float(
            mapping["local_price_pnl"], f"{field}.local_price_pnl"
        ),
        fx_translation_pnl=require_finite_float(
            mapping["fx_translation_pnl"], f"{field}.fx_translation_pnl"
        ),
    )


def _event_from_mapping(data: Any, field: str) -> EventCommitment:
    mapping = require_mapping(data, field)
    exact_keys(mapping, {"tau", "equity", "cash", "state_fingerprint"}, field)
    return EventCommitment(
        tau=require_str(mapping["tau"], f"{field}.tau"),
        equity=require_finite_float(mapping["equity"], f"{field}.equity"),
        cash=require_finite_float(mapping["cash"], f"{field}.cash"),
        state_fingerprint=require_sha256_hex(
            mapping["state_fingerprint"], f"{field}.state_fingerprint"
        ),
    )


def _check_internal_consistency(result: PortfolioResult, field: str) -> None:
    metrics = result.metrics
    if abs(result.cost_total - metrics.total_cost) > _RECONCILE_TOLERANCE:
        raise CanonicalError(f"{field}.cost_total: disagrees with the metrics total cost")
    if result.num_fills != metrics.num_fills:
        raise CanonicalError(f"{field}.num_fills: disagrees with the metrics fill count")
    local_total = sum(asset.local_price_pnl for asset in result.per_asset_contribution)
    fx_total = sum(asset.fx_translation_pnl for asset in result.per_asset_contribution)
    if abs(local_total - metrics.cumulative_local_price_pnl) > _RECONCILE_TOLERANCE:
        raise CanonicalError(f"{field}.per_asset_contribution: local totals disagree with metrics")
    if abs(fx_total - metrics.cumulative_fx_translation_pnl) > _RECONCILE_TOLERANCE:
        raise CanonicalError(f"{field}.per_asset_contribution: FX totals disagree with metrics")
    change = (
        metrics.cumulative_local_price_pnl
        + metrics.cumulative_fx_translation_pnl
        + metrics.cumulative_action_cash
        - metrics.cumulative_cost
        + metrics.cumulative_residual
    )
    if abs(change - (result.terminal_equity - result.initial_equity)) > _RECONCILE_TOLERANCE:
        raise CanonicalError(
            f"{field}: attribution roll-up does not reconcile to the equity change"
        )


def build_portfolio_result(
    run_result: PortfolioRunResult,
    metrics: PortfolioMetrics,
    universe: UniverseSpec,
    *,
    package_version: str = M4B_PACKAGE_VERSION,
) -> PortfolioResult:
    """Assemble the result artifact, cross-checking the run's fingerprints against the universe."""
    if run_result.base_currency != universe.base_currency:
        raise CanonicalError("result: run base currency does not match the universe")
    if run_result.membership_fingerprint != universe.membership_fingerprint:
        raise CanonicalError("result: run membership fingerprint does not match the universe")
    if run_result.schedule_fingerprint != universe.rebalance_schedule_fingerprint:
        raise CanonicalError("result: run schedule fingerprint does not match the universe")
    per_asset = _aggregate_per_asset(run_result)
    result = PortfolioResult(
        package_version=package_version,
        universe_fingerprint=universe.fingerprint,
        panel_fingerprint=run_result.panel_fingerprint,
        protocol_fingerprint=run_result.protocol_fingerprint,
        membership_fingerprint=run_result.membership_fingerprint,
        fx_fingerprint=universe.fx_fingerprint,
        corporate_action_fingerprint=universe.corporate_action_fingerprint,
        schedule_fingerprint=run_result.schedule_fingerprint,
        calendar_fingerprints=tuple(
            (calendar_id, universe.calendars[calendar_id].fingerprint)
            for calendar_id in sorted(universe.calendars)
        ),
        base_currency=run_result.base_currency,
        initial_equity=run_result.initial_equity,
        terminal_equity=run_result.terminal_equity,
        metrics=metrics,
        per_asset_contribution=per_asset,
        cost_total=metrics.total_cost,
        num_fills=run_result.all_fills,
        event_commitments=_event_commitments(run_result),
        run_result_fingerprint=run_result.result_fingerprint,
        final_state_fingerprint=run_result.final_state_fingerprint,
    )
    _check_internal_consistency(result, "portfolio_result")
    return result


def verify_portfolio_result(
    result: PortfolioResult,
    universe: UniverseSpec,
    run_result: PortfolioRunResult,
) -> None:
    """Full-graph verify: fail closed unless the result agrees with the universe and the run.

    Re-derives the per-asset totals and event commitments from ``run_result``, re-checks every bound
    identity against ``universe`` and ``run_result``, and confirms the attribution roll-ups
    reconcile. Raises :class:`CanonicalError` on the first disagreement.
    """
    if result.universe_fingerprint != universe.fingerprint:
        raise CanonicalError("verify: universe fingerprint does not match the supplied universe")
    if result.panel_fingerprint != run_result.panel_fingerprint:
        raise CanonicalError("verify: panel fingerprint does not match the run")
    if result.protocol_fingerprint != run_result.protocol_fingerprint:
        raise CanonicalError("verify: protocol fingerprint does not match the run")
    if result.membership_fingerprint != run_result.membership_fingerprint:
        raise CanonicalError("verify: membership fingerprint does not match the run")
    if result.schedule_fingerprint != run_result.schedule_fingerprint:
        raise CanonicalError("verify: schedule fingerprint does not match the run")
    if result.fx_fingerprint != universe.fx_fingerprint:
        raise CanonicalError("verify: FX fingerprint does not match the universe")
    if result.corporate_action_fingerprint != universe.corporate_action_fingerprint:
        raise CanonicalError("verify: corporate-action fingerprint does not match the universe")
    if result.run_result_fingerprint != run_result.result_fingerprint:
        raise CanonicalError("verify: run-result fingerprint does not match the run")
    if result.final_state_fingerprint != run_result.final_state_fingerprint:
        raise CanonicalError("verify: final-state fingerprint does not match the run")
    if result.per_asset_contribution != _aggregate_per_asset(run_result):
        raise CanonicalError("verify: per-asset attribution does not match the run")
    if result.event_commitments != _event_commitments(run_result):
        raise CanonicalError("verify: event commitments do not match the run")
    _check_internal_consistency(result, "verify")
