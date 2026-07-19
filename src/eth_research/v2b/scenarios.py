"""V2B §17-18 — pre-registered cost / latency / capacity scenarios for the ETH/BTC/cash program.

All frictions are declared here, **before** the one-shot run, and reuse the accepted M4B primitives
(``eth_research.portfolio.costs.CostParameters`` and ``trade_cost``) unmodified. Nothing is fitted
to data.

* **Cost scenarios** (:data:`COST_SCENARIOS`) — five predeclared, contractive per-instrument proxy
  cost regimes: a ``frictionless`` baseline (reconciliation only), the ``primary`` regime the paired
  endpoint is decided under (the accepted ``compatibility_v1``: 0.1% fee + 0.05% slippage), a
  ``stressed`` regime (higher linear frictions + half-spread), and two liquidity-impact proxies
  (``proxy_impact_moderate`` / ``proxy_impact_severe``) that switch on the sqrt-impact term so the
  capacity analysis has a non-trivial marginal cost. The nomination rule reads ``primary`` and
  ``stressed``; the rest are robustness context.
* **Latency scenarios** (:data:`LATENCY_SCENARIOS`) — the baseline is already causal: a signal
  decided from closes ``<= t`` executes at ``open[t+1]`` (a full bar later). The stress
  (``delayed_one_bar``) shifts the target one extra bar forward, so a candidate must survive an
  extra day of execution delay.
* **Capacity** (:func:`capacity_report`) — turns a per-event fractional-turnover path and a capital
  base into the causal participation rate (traded dollars over the *lagged* dollar volume of the
  bar being traded), and reports the worst-case participation. High participation means the strategy
  could not be run at that size without material impact; this is reported, never silently ignored.

Every scenario is frozen into ``research/v2b/execution_scenarios.json`` with a content fingerprint
so the one-shot run and the replay CI use exactly these declarations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from eth_research.portfolio.costs import CostParameters
from eth_research.v2.strict import V2ValidationError, canonical_json_bytes, canonical_sha256
from eth_research.v2b.candidates import WEIGHT_BTC, WEIGHT_ETH

SCENARIOS_SCHEMA_VERSION: int = 1
EXECUTION_SCENARIOS_RELPATH = "research/v2b/execution_scenarios.json"

#: The primary and stressed cost-scenario names the nomination rule reads.
PRIMARY_COST: str = "primary"
STRESSED_COST: str = "stressed"


class V2BScenarioError(V2ValidationError):
    """A V2B scenario declaration or capacity computation was invalid."""


# --------------------------------------------------------------------------- #
# cost scenarios (>= 4 non-trivial, all reusing the accepted CostParameters)   #
# --------------------------------------------------------------------------- #
def _cost_scenarios() -> dict[str, CostParameters]:
    return {
        # A frictionless baseline used only to reconcile the vectorized basis against the engine.
        "frictionless": CostParameters(scenario="frictionless"),
        # The primary regime: the accepted single-asset compatibility_v1 (0.1% fee + 0.05% slip).
        "primary": CostParameters.compatibility_v1(),
        # A stressed regime: heavier linear frictions plus a half-spread.
        "stressed": CostParameters(
            scenario="stressed",
            fee_rate=0.002,
            half_spread=0.0005,
            base_slippage=0.0015,
        ),
        # A moderate liquidity-impact proxy: the sqrt-impact term switches on (capped small).
        "proxy_impact_moderate": CostParameters(
            scenario="proxy_impact_moderate",
            fee_rate=0.001,
            base_slippage=0.0005,
            impact_coefficient=0.1,
            impact_cap=0.01,
        ),
        # A severe liquidity-impact proxy: a larger coefficient and cap.
        "proxy_impact_severe": CostParameters(
            scenario="proxy_impact_severe",
            fee_rate=0.001,
            base_slippage=0.0005,
            impact_coefficient=0.25,
            impact_cap=0.03,
        ),
    }


#: The five predeclared cost scenarios, keyed by name.
COST_SCENARIOS: dict[str, CostParameters] = _cost_scenarios()

#: The predeclared latency scenarios, name -> extra execution-lag bars beyond the causal t+1 open.
LATENCY_SCENARIOS: dict[str, int] = {
    "causal_t_plus_1_open": 0,
    "delayed_one_bar": 1,
}


def apply_latency(weights: pd.DataFrame, extra_lag_bars: int) -> pd.DataFrame:
    """Shift a target-weight path forward by ``extra_lag_bars`` (flat during the warm-up gap).

    The baseline convention already executes a close-``<=t`` signal at ``open[t+1]``; shifting the
    path forward by ``k`` extra bars models ``k`` additional bars of execution delay. The leading
    ``k`` rows become flat (all-cash), never a forward-filled future weight.
    """
    if extra_lag_bars < 0:
        raise V2BScenarioError("extra_lag_bars must be non-negative")
    if extra_lag_bars == 0:
        return weights.copy(deep=True)
    shifted = weights.shift(extra_lag_bars)
    shifted.iloc[:extra_lag_bars] = 0.0
    return shifted


# --------------------------------------------------------------------------- #
# capacity: causal participation from lagged dollar volume                     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CapacityReport:
    """The worst-case causal participation of a turnover path at one capital base."""

    capital_base: float
    max_participation: float  # traded dollars / lagged dollar volume, worst event
    mean_participation: float
    max_participation_timestamp: str

    def to_canonical(self) -> dict[str, Any]:
        return {
            "capital_base": self.capital_base,
            "max_participation": self.max_participation,
            "mean_participation": self.mean_participation,
            "max_participation_timestamp": self.max_participation_timestamp,
        }


def _lagged_dollar_volume(panel: pd.DataFrame) -> np.ndarray:
    """Per-event min lagged dollar volume across ETH and BTC (the binding liquidity of the pair).

    Dollar volume is ``close * volume``; the *lagged* value (bar ``t-1``) is what a decision at the
    open of bar ``t`` could have known. The first bar has no lag, so its participation is reported
    as zero-volume (infinite participation is clamped to a large finite proxy by the caller).
    """
    eth_dollar = panel["eth_close"].to_numpy(dtype=float) * panel["eth_volume"].to_numpy(
        dtype=float
    )
    btc_dollar = panel["btc_close"].to_numpy(dtype=float) * panel["btc_volume"].to_numpy(
        dtype=float
    )
    pair = np.minimum(eth_dollar, btc_dollar)
    lagged: np.ndarray = np.empty(pair.shape[0], dtype=float)
    lagged[0] = np.nan
    lagged[1:] = pair[:-1]
    return lagged


def capacity_report(
    panel: pd.DataFrame, turnover: np.ndarray, index: pd.DatetimeIndex, *, capital_base: float
) -> CapacityReport:
    """The causal participation of a fractional-turnover path deployed at ``capital_base`` dollars.

    ``turnover[t]`` is the weight-space L1 turnover at event ``t`` (from
    :class:`~eth_research.v2b.execution.ExecutionResult`); traded dollars are ``turnover[t] *
    capital_base``, and participation is that over the lagged dollar volume of the pair. The first
    event (no lag) and any zero-volume bar are skipped rather than counted as infinite.
    """
    if capital_base <= 0.0:
        raise V2BScenarioError("capital_base must be positive")
    if turnover.shape[0] != len(index):
        raise V2BScenarioError("turnover and index lengths differ")
    lagged = _lagged_dollar_volume(panel)
    traded = turnover * capital_base
    participation = np.full(turnover.shape, np.nan)
    ok = np.isfinite(lagged) & (lagged > 0.0)
    participation[ok] = traded[ok] / lagged[ok]
    finite = participation[np.isfinite(participation)]
    if finite.size == 0:
        raise V2BScenarioError("no event had a positive lagged dollar volume")
    argmax = int(np.nanargmax(participation))
    return CapacityReport(
        capital_base=float(capital_base),
        max_participation=float(np.nanmax(participation)),
        mean_participation=float(np.mean(finite)),
        max_participation_timestamp=pd.Timestamp(index[argmax]).isoformat().replace("+00:00", "Z"),
    )


# --------------------------------------------------------------------------- #
# frozen scenario declaration artifact                                         #
# --------------------------------------------------------------------------- #
def build_scenario_declaration() -> dict[str, Any]:
    """The frozen, byte-reproducible cost/latency/capacity scenario declaration."""
    return {
        "schema_version": SCENARIOS_SCHEMA_VERSION,
        "kind": "v2b_execution_scenarios",
        "primary_cost": PRIMARY_COST,
        "stressed_cost": STRESSED_COST,
        "cost_scenarios": {
            name: params.canonical() for name, params in sorted(COST_SCENARIOS.items())
        },
        "latency_scenarios": dict(sorted(LATENCY_SCENARIOS.items())),
        "capacity_method": {
            "participation": "traded_dollars_over_lagged_pair_min_dollar_volume",
            "dollar_volume": "close_times_volume",
            "lag_bars": 1,
        },
        "weight_columns": [WEIGHT_ETH, WEIGHT_BTC],
    }


def scenario_declaration_fingerprint() -> str:
    return canonical_sha256(build_scenario_declaration())


def render_scenario_declaration_bytes() -> bytes:
    doc = build_scenario_declaration()
    doc["declaration_fingerprint"] = scenario_declaration_fingerprint()
    return canonical_json_bytes(doc)


def verify_scenario_declaration(repo_root: str | Path) -> None:
    """The committed scenario declaration reproduces byte-for-byte from the running package."""
    committed = (Path(repo_root) / EXECUTION_SCENARIOS_RELPATH).read_bytes()
    if committed != render_scenario_declaration_bytes():
        raise V2BScenarioError(
            "committed execution_scenarios.json does not reproduce from the running package"
        )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wrapper
    import argparse
    import json

    parser = argparse.ArgumentParser(description="V2B execution scenarios (offline)")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.repo_root) / EXECUTION_SCENARIOS_RELPATH
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render_scenario_declaration_bytes())
        print(f"wrote {EXECUTION_SCENARIOS_RELPATH}")
        return 0
    try:
        verify_scenario_declaration(args.repo_root)
    except (OSError, V2ValidationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
