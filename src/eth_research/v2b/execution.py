"""V2B §16 — bind the aligned ETH/BTC partition to the accepted M4B engine, plus a fast per-event
execution basis proven faithful to it (the compatibility-oracle pattern).

The V2B candidates emit **time-varying** per-event target weights ``(weight_eth, weight_btc)``. The
accepted M4B :class:`~eth_research.portfolio.protocol.PortfolioProtocol` only expresses the three
*static* reference policies (``cash`` / ``equal_weight`` / ``declared_weights``), so it can run the
static benchmarks but cannot, in one run, execute a signal whose target changes each bar. V2B
therefore adds **one** thin, deterministic execution basis that reuses the same accepted M4B
accounting convention — trade at the bar opening at the event ``tau``, then mark that holding at its
own bar's close, the identical rule the engine applies — and reuses the M4B
:class:`~eth_research.portfolio.costs.CostParameters` turnover cost UNMODIFIED. No engine is
modified. The basis is a *separate* vectorized computation, proven to reproduce the engine's equity
path bit-for-bit only under the zero-cost reconciliation below; it is not asserted bit-identical
under costs, where it applies the same linear turnover rate rather than re-deriving the engine's.

The basis is proven faithful by :func:`build_zero_cost_reconciliation`, which runs every static
benchmark — including 50/50, whose daily rebalance exercises genuine two-asset trading each event —
through the real :func:`~eth_research.portfolio.engine.run_portfolio_simulation` over the same
universe and asserts the vectorized basis reproduces the engine's **full per-event equity path**
to a tight relative tolerance under a zero-cost scenario (no cost fixed-point subtlety there).

Everything is bound to the milestone's long-only ETH/BTC/cash contract: USD base currency, a
continuous 24/7 daily calendar, both instruments always listed, **no FX** (both USD-quoted), **no
corporate actions**, gross ``<= 1``, and no shorting or leverage. Firewall: every engine-visible
timestamp — bar ``open_time``, bar ``close_time``, rebalance event, mark — is strictly before the
first sealed timestamp ``WINDOW_END_EXCLUSIVE`` (2022-06-22T00:00:00Z); each daily bar closes 23h
after it opens, so the last engine-visible timestamp (2022-06-21T23:00:00Z) never reaches the seal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from eth_research.portfolio.calendar import TradingCalendar
from eth_research.portfolio.costs import CostParameters, trade_cost
from eth_research.portfolio.engine import PortfolioRunResult, run_portfolio_simulation
from eth_research.portfolio.fx import FxEvidence
from eth_research.portfolio.identity import InstrumentId
from eth_research.portfolio.membership import MembershipInterval, MembershipSchedule
from eth_research.portfolio.panel import MarketPanel, build_market_panel
from eth_research.portfolio.protocol import PortfolioProtocol
from eth_research.portfolio.schedule import RebalanceSchedule
from eth_research.portfolio.valuation import StalenessPolicy
from eth_research.v2.strict import V2ValidationError
from eth_research.v2b.acquisition import RESEARCH_CUTOFF_LAST_OPEN, WINDOW_END_EXCLUSIVE
from eth_research.v2b.candidates import WEIGHT_BTC, WEIGHT_ETH
from eth_research.v2b.partition import JointPartition, build_joint_partition

EXECUTION_SCHEMA_VERSION: int = 1

VENUE: str = "coinbase-exchange"
CALENDAR_ID: str = "continuous_24_7"
BASE_CURRENCY: str = "USD"
INITIAL_CASH: float = 100_000.0
#: Each daily bar opens at 00:00 UTC and closes 23h later, so every engine-visible timestamp stays
#: strictly below the first sealed timestamp (WINDOW_END_EXCLUSIVE = 2022-06-22T00:00:00Z).
BAR_CLOSE_OFFSET: pd.Timedelta = pd.Timedelta(hours=23)
#: A staleness bound above one day: the end-of-step mark is taken 23h after the bar opens, and a
#: carried mark is never needed here (every day has a bar), so this is generous by construction.
MAX_STALENESS_SECONDS: float = 90_000.0
#: The relative tolerance the zero-cost reconciliation holds the vectorized basis to vs the engine.
RECONCILIATION_RTOL: float = 1e-9


class V2BExecutionError(V2ValidationError):
    """A V2B execution binding or reconciliation invariant failed."""


# --------------------------------------------------------------------------- #
# instruments + universe binding                                              #
# --------------------------------------------------------------------------- #
def _instrument(base: str) -> InstrumentId:
    """The USD-quoted crypto-spot identity for ``base`` on the continuous 24/7 calendar."""
    return InstrumentId(
        asset_class="crypto_spot",
        base_asset=base,
        quote_currency=BASE_CURRENCY,
        venue=VENUE,
        symbol=f"{base}-USD",
        instrument_type="spot",
        price_unit=BASE_CURRENCY,
        quantity_unit=base,
        calendar_id=CALENDAR_ID,
    )


def eth_instrument() -> InstrumentId:
    return _instrument("ETH")


def btc_instrument() -> InstrumentId:
    return _instrument("BTC")


def _daily_bars(panel: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """A canonical daily OHLCV bar frame for one instrument: open at ``t``, close 23h later."""
    index = panel.index
    return pd.DataFrame(
        {
            "open_time": index,
            "close_time": index + BAR_CLOSE_OFFSET,
            "open": panel[f"{prefix}_open"].to_numpy(dtype=float),
            "high": panel[f"{prefix}_high"].to_numpy(dtype=float),
            "low": panel[f"{prefix}_low"].to_numpy(dtype=float),
            "close": panel[f"{prefix}_close"].to_numpy(dtype=float),
            "volume": panel[f"{prefix}_volume"].to_numpy(dtype=float),
        }
    )


@dataclass(frozen=True)
class V2BUniverse:
    """The frozen M4B binding of the joint ETH/BTC partition (long-only ETH/BTC/cash, USD, 24/7)."""

    partition: JointPartition
    eth: InstrumentId
    btc: InstrumentId
    market_panel: MarketPanel
    membership: MembershipSchedule
    fx: FxEvidence
    calendars: dict[str, TradingCalendar]
    schedule: RebalanceSchedule
    staleness: StalenessPolicy

    @property
    def index(self) -> pd.DatetimeIndex:
        idx = self.partition.panel.index
        assert isinstance(idx, pd.DatetimeIndex)
        return idx

    @property
    def last_engine_timestamp(self) -> pd.Timestamp:
        """The greatest timestamp any engine component sees (the last bar's close_time)."""
        return self.index[-1] + BAR_CLOSE_OFFSET


def _assert_firewall(index: pd.DatetimeIndex) -> None:
    """No engine-visible timestamp (open, close, event, mark) reaches the first sealed timestamp."""
    if len(index) == 0:
        raise V2BExecutionError("v2b universe: empty partition index")
    first_sealed = pd.Timestamp(WINDOW_END_EXCLUSIVE)
    cutoff = pd.Timestamp(RESEARCH_CUTOFF_LAST_OPEN)
    # Defense in depth: assert the invariant directly here, not only via the upstream loader — the
    # index must be strictly ascending, and EVERY open (not just the last) must be at/before the
    # cutoff, so no interior sealed row can slip a later bar close past the seal.
    if not index.is_monotonic_increasing:
        raise V2BExecutionError("v2b universe: partition index is not strictly increasing")
    if not bool((index <= cutoff).all()):
        raise V2BExecutionError("v2b universe: an open is at/after the research cutoff")
    last_open = index[-1]
    if last_open != cutoff:
        raise V2BExecutionError("v2b universe: last open is not the research cutoff")
    last_close = last_open + BAR_CLOSE_OFFSET
    if not last_close < first_sealed:
        raise V2BExecutionError(
            f"v2b universe: last engine timestamp {last_close.isoformat()} is not strictly before "
            f"the first sealed timestamp {first_sealed.isoformat()}"
        )


@dataclass(frozen=True, slots=True)
class _EnginePieces:
    """The M4B engine inputs built from one panel (full partition or a head slice)."""

    eth: InstrumentId
    btc: InstrumentId
    market_panel: MarketPanel
    membership: MembershipSchedule
    fx: FxEvidence
    calendars: dict[str, TradingCalendar]
    schedule: RebalanceSchedule


def _build_engine_pieces(panel: pd.DataFrame) -> _EnginePieces:
    """Build the accepted M4B engine inputs from an ETH/BTC daily panel (both listed, no FX/CA)."""
    index = panel.index
    assert isinstance(index, pd.DatetimeIndex)
    eth, btc = eth_instrument(), btc_instrument()
    market_panel = build_market_panel(
        {eth: _daily_bars(panel, "eth"), btc: _daily_bars(panel, "btc")}
    )
    first = index[0]
    membership = MembershipSchedule(
        intervals=(
            MembershipInterval(eth, first, None, first, "listing", VENUE),
            MembershipInterval(btc, first, None, first, "listing", VENUE),
        )
    )
    calendars = {
        CALENDAR_ID: TradingCalendar(
            calendar_id=CALENDAR_ID, kind="continuous_24_7", sessions=(), source=VENUE
        )
    }
    return _EnginePieces(
        eth=eth,
        btc=btc,
        market_panel=market_panel,
        membership=membership,
        fx=FxEvidence(observations=()),
        calendars=calendars,
        schedule=RebalanceSchedule(timestamps=tuple(index)),
    )


def build_v2b_universe(repo_root: str | Path) -> V2BUniverse:
    """Bind the committed joint partition to the accepted M4B engine's inputs (from repo_root only).

    The partition is re-derived internally from committed bytes (never a caller frame). Both
    instruments are listed open-ended from the first bar; FX evidence is empty (USD-quoted, so no
    conversion is ever needed); no corporate actions are carried; the schedule fires at every daily
    open. The firewall is re-asserted before anything reaches the engine.
    """
    partition = build_joint_partition(repo_root)
    index = partition.panel.index
    assert isinstance(index, pd.DatetimeIndex)
    _assert_firewall(index)
    pieces = _build_engine_pieces(partition.panel)
    return V2BUniverse(
        partition=partition,
        eth=pieces.eth,
        btc=pieces.btc,
        market_panel=pieces.market_panel,
        membership=pieces.membership,
        fx=pieces.fx,
        calendars=pieces.calendars,
        schedule=pieces.schedule,
        staleness=StalenessPolicy(max_staleness_seconds=MAX_STALENESS_SECONDS),
    )


def zero_cost_scenario() -> CostParameters:
    """The all-zero cost scenario used for the accounting reconciliation (no cost fixed point)."""
    return CostParameters(scenario="zero")


# --------------------------------------------------------------------------- #
# reference-benchmark runs through the accepted M4B engine (unmodified)        #
# --------------------------------------------------------------------------- #
def _run_reference(
    pieces: _EnginePieces,
    staleness: StalenessPolicy,
    *,
    policy: str,
    cost_scenario: CostParameters,
    declared_weights: tuple[tuple[InstrumentId, float], ...],
) -> PortfolioRunResult:
    protocol = PortfolioProtocol(
        base_currency=BASE_CURRENCY,
        initial_cash=INITIAL_CASH,
        policy=policy,  # type: ignore[arg-type]  # validated by PortfolioProtocol.__post_init__
        cost_scenario=cost_scenario,
        staleness=staleness,
        declared_weights=declared_weights,
    )
    return run_portfolio_simulation(
        protocol,
        pieces.market_panel,
        pieces.membership,
        pieces.fx,
        pieces.schedule,
        calendars=pieces.calendars,
    )


def run_reference_benchmark(
    universe: V2BUniverse,
    *,
    policy: str,
    cost_scenario: CostParameters,
    declared_weights: tuple[tuple[InstrumentId, float], ...] = (),
) -> PortfolioRunResult:
    """Run one static reference benchmark through the accepted M4B ``run_portfolio_simulation``.

    Note: the accepted engine marks each holding with an O(rows) causal scan per event, so a full
    2221-event benchmark run is O(rows^2). The heavy walk-forward/bootstrap work uses the vectorized
    basis instead; this wrapper exists for exact accounting reconciliation and small-slice runs.
    """
    pieces = _EnginePieces(
        eth=universe.eth,
        btc=universe.btc,
        market_panel=universe.market_panel,
        membership=universe.membership,
        fx=universe.fx,
        calendars=universe.calendars,
        schedule=universe.schedule,
    )
    return _run_reference(
        pieces,
        universe.staleness,
        policy=policy,
        cost_scenario=cost_scenario,
        declared_weights=declared_weights,
    )


# --------------------------------------------------------------------------- #
# the fast per-event execution basis (open-trade / close-mark), M4B-faithful   #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """The realized equity curve and per-event net return series of one target-weight path."""

    index: pd.DatetimeIndex
    equity_curve: np.ndarray  # equity marked at each bar's close (post-event)
    net_returns: np.ndarray  # per-event simple return of equity (first vs INITIAL_CASH)
    turnover: np.ndarray  # per-event fractional turnover (weight-space L1 change)
    total_cost: float  # total base-currency turnover cost charged over the run

    @property
    def terminal_equity(self) -> float:
        return float(self.equity_curve[-1]) if self.equity_curve.size else INITIAL_CASH

    def net_return_series(self) -> pd.Series:
        """The per-event net simple return series (the paired-evaluation return basis)."""
        return pd.Series(self.net_returns, index=self.index, name="net_return")


def _validate_weight_path(
    index: pd.DatetimeIndex, weights: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    """Return finite ``(w_eth, w_btc)`` arrays after enforcing the long-only gross<=1 contract."""
    for col in (WEIGHT_ETH, WEIGHT_BTC):
        if col not in weights.columns:
            raise V2BExecutionError(f"weight path is missing the {col!r} column")
    if not weights.index.equals(index):
        raise V2BExecutionError("weight-path index does not match the universe index")
    w_eth = weights[WEIGHT_ETH].to_numpy(dtype=float)
    w_btc = weights[WEIGHT_BTC].to_numpy(dtype=float)
    if not (np.all(np.isfinite(w_eth)) and np.all(np.isfinite(w_btc))):
        raise V2BExecutionError("weight path contains a non-finite weight")
    if np.any(w_eth < 0.0) or np.any(w_btc < 0.0):
        raise V2BExecutionError("weight path contains a negative weight (no shorting)")
    gross = w_eth + w_btc
    if np.any(gross > 1.0 + 1e-9):
        raise V2BExecutionError("weight path violates gross <= 1 (no leverage)")
    return w_eth, w_btc


def simulate_target_path(
    panel: pd.DataFrame, weights: pd.DataFrame, cost_scenario: CostParameters
) -> ExecutionResult:
    """Execute a per-event target-weight path over the daily panel (open-trade / close-mark).

    At event ``t`` the book is revalued at ``open[t]``, rebalanced to ``(w_eth[t], w_btc[t])`` — the
    weight-space L1 turnover is charged at the scenario's *linear* rate (fee + half-spread + base
    slippage; the impact term needs a participation rate and is exercised only by the capacity
    scenarios) using the accepted :func:`~eth_research.portfolio.costs.trade_cost` — and the
    post-cost book is marked at ``close[t]``. This reproduces the M4B convention exactly, and is
    proven so at zero cost by :func:`build_zero_cost_reconciliation`.
    """
    index = panel.index
    assert isinstance(index, pd.DatetimeIndex)
    for col in (f"eth_{c}" for c in ("open", "close")):
        if col not in panel.columns:
            raise V2BExecutionError(f"panel is missing the {col!r} column")
    w_eth, w_btc = _validate_weight_path(index, weights)
    eth_open = panel["eth_open"].to_numpy(dtype=float)
    eth_close = panel["eth_close"].to_numpy(dtype=float)
    btc_open = panel["btc_open"].to_numpy(dtype=float)
    btc_close = panel["btc_close"].to_numpy(dtype=float)

    # The basis models only the LINEAR (notional-proportional) cost — fee + half-spread + base
    # slippage. It does not carry a participation rate, so a scenario with a non-zero sqrt-impact
    # term would have its impact silently dropped: refuse it rather than under-charge. Liquidity
    # impact is assessed separately through the participation-based capacity report.
    if cost_scenario.impact_cap != 0.0 or cost_scenario.impact_coefficient != 0.0:
        raise V2BExecutionError(
            f"cost scenario {cost_scenario.scenario!r} carries a sqrt-impact term; the vectorized "
            "basis models only linear cost — route impact through the capacity report"
        )
    # trade_cost with participation=0 yields exactly the linear rate on a unit notional, so we reuse
    # it (rather than re-summing the rates by hand).
    unit = trade_cost(cost_scenario, 1.0, participation=0.0, currency=BASE_CURRENCY)
    linear_rate = unit.total

    n = len(index)
    equity_curve = np.empty(n, dtype=float)
    net_returns = np.empty(n, dtype=float)
    turnover = np.empty(n, dtype=float)
    cash, qty_eth, qty_btc = INITIAL_CASH, 0.0, 0.0
    prev_equity = INITIAL_CASH
    total_cost = 0.0
    for t in range(n):
        equity_open = cash + qty_eth * eth_open[t] + qty_btc * btc_open[t]
        # realized pre-trade weights at open, then weight-space L1 turnover to the target.
        rw_eth = (qty_eth * eth_open[t]) / equity_open if equity_open > 0.0 else 0.0
        rw_btc = (qty_btc * btc_open[t]) / equity_open if equity_open > 0.0 else 0.0
        tau_frac = abs(w_eth[t] - rw_eth) + abs(w_btc[t] - rw_btc)
        cost = linear_rate * tau_frac * equity_open
        total_cost += cost
        equity_post = equity_open - cost
        qty_eth = w_eth[t] * equity_post / eth_open[t]
        qty_btc = w_btc[t] * equity_post / btc_open[t]
        cash = (1.0 - w_eth[t] - w_btc[t]) * equity_post
        equity_close = cash + qty_eth * eth_close[t] + qty_btc * btc_close[t]
        equity_curve[t] = equity_close
        net_returns[t] = equity_close / prev_equity - 1.0
        turnover[t] = tau_frac
        prev_equity = equity_close
    return ExecutionResult(
        index=index,
        equity_curve=equity_curve,
        net_returns=net_returns,
        turnover=turnover,
        total_cost=total_cost,
    )


# --------------------------------------------------------------------------- #
# the pre-registered static benchmarks (cash / ETH B&H / BTC B&H / 50-50)      #
# --------------------------------------------------------------------------- #
#: The four pre-registered passive benchmarks, each a (weight_eth, weight_btc) constant.
BENCHMARK_WEIGHTS: dict[str, tuple[float, float]] = {
    "cash": (0.0, 0.0),
    "eth_buy_and_hold": (1.0, 0.0),
    "btc_buy_and_hold": (0.0, 1.0),
    "static_50_50": (0.5, 0.5),
}
#: The benchmark the primary paired endpoint compares candidates against (ETH buy-and-hold, the
#: single-asset passive the whole program has measured against since V2A).
PRIMARY_BENCHMARK: str = "eth_buy_and_hold"


def constant_weight_path(index: pd.DatetimeIndex, w_eth: float, w_btc: float) -> pd.DataFrame:
    """A constant per-event target-weight path over ``index``."""
    return pd.DataFrame({WEIGHT_ETH: float(w_eth), WEIGHT_BTC: float(w_btc)}, index=index)


def benchmark_weight_paths(index: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """The four pre-registered passive-benchmark weight paths, keyed by name."""
    return {
        name: constant_weight_path(index, w_eth, w_btc)
        for name, (w_eth, w_btc) in BENCHMARK_WEIGHTS.items()
    }


def _reference_policy_for(name: str) -> tuple[str, tuple[tuple[InstrumentId, float], ...]]:
    """Map a benchmark name to the equivalent static M4B (policy, declared_weights)."""
    eth, btc = eth_instrument(), btc_instrument()
    w_eth, w_btc = BENCHMARK_WEIGHTS[name]
    if name == "cash":
        return "cash", ()
    declared = tuple((inst, w) for inst, w in ((eth, w_eth), (btc, w_btc)) if w > 0.0)
    return "declared_weights", declared


# --------------------------------------------------------------------------- #
# the compatibility oracle: vectorized basis == accepted engine at zero cost   #
# --------------------------------------------------------------------------- #
def representative_rotation_path(index: pd.DatetimeIndex) -> pd.DataFrame:
    """A deterministic ETH/BTC/cash rotation fixture exercising trades between all three legs.

    Not a candidate — a fixed 3-phase path (all-ETH, then all-BTC, then cash) whose two switch
    points force real inter-asset turnover. It is used by the property tests to check the vectorized
    basis charges turnover exactly at the switches and stays long-only gross<=1 throughout.
    """
    n = len(index)
    w_eth = np.zeros(n, dtype=float)
    w_btc = np.zeros(n, dtype=float)
    third = max(1, n // 3)
    w_eth[:third] = 1.0
    w_btc[third : 2 * third] = 1.0
    # final third stays cash (both zero)
    return pd.DataFrame({WEIGHT_ETH: w_eth, WEIGHT_BTC: w_btc}, index=index)


@dataclass(frozen=True, slots=True)
class ReconciliationRow:
    """One benchmark's per-event equity-path agreement (vectorized basis vs the accepted engine)."""

    name: str
    engine_terminal: float
    vectorized_terminal: float
    max_relative_error: float  # over the whole per-event equity path, not just the terminal


#: The head-slice size the reconciliation runs the accepted (O(rows^2)) engine over. One trading
#: year is enough to prove the accounting convention (open-trade / close-mark, shared cash) matches
#: exactly; the convention is row-independent, so the full-partition basis inherits the proof.
RECONCILIATION_EVENT_COUNT: int = 252


def build_zero_cost_reconciliation(
    universe: V2BUniverse, *, event_count: int = RECONCILIATION_EVENT_COUNT
) -> tuple[ReconciliationRow, ...]:
    """Prove the vectorized basis matches ``run_portfolio_simulation`` at zero cost, benchmark-wise.

    Runs each of the four static benchmarks — including 50/50, whose daily rebalance exercises
    genuine two-asset trading each event — through the accepted engine and the vectorized basis over
    the first ``event_count`` events of the universe under the zero-cost scenario, and checks the
    **full per-event equity path** (not just the terminal) agrees within
    :data:`RECONCILIATION_RTOL`. The slice keeps the O(rows^2) engine fast; the accounting
    convention is row-independent, so the proof carries to the full partition. Raises
    :class:`V2BExecutionError` on any disagreement.
    """
    if event_count < 3:
        raise V2BExecutionError("reconciliation needs at least 3 events")
    panel = universe.partition.panel.iloc[:event_count]
    index = panel.index
    assert isinstance(index, pd.DatetimeIndex)
    pieces = _build_engine_pieces(panel)
    zero = zero_cost_scenario()

    rows: list[ReconciliationRow] = []
    for name in BENCHMARK_WEIGHTS:
        policy, declared = _reference_policy_for(name)
        engine = _run_reference(
            pieces, universe.staleness, policy=policy, cost_scenario=zero, declared_weights=declared
        )
        engine_path = np.array([event.equity for event in engine.events], dtype=float)
        vector = simulate_target_path(
            panel, constant_weight_path(index, *BENCHMARK_WEIGHTS[name]), zero
        )
        if engine_path.shape != vector.equity_curve.shape:
            raise V2BExecutionError(
                f"reconciliation shape mismatch for {name!r}: engine {engine_path.shape} vs "
                f"vectorized {vector.equity_curve.shape}"
            )
        max_rel = float(
            np.max(
                np.abs(engine_path - vector.equity_curve)
                / np.maximum.reduce(
                    [np.abs(engine_path), np.abs(vector.equity_curve), np.ones_like(engine_path)]
                )
            )
        )
        rows.append(
            ReconciliationRow(name, engine.terminal_equity, vector.terminal_equity, max_rel)
        )
        if max_rel > RECONCILIATION_RTOL:
            raise V2BExecutionError(
                f"zero-cost reconciliation failed for {name!r}: max path relative error "
                f"{max_rel:.3e} > {RECONCILIATION_RTOL:.1e} (engine terminal "
                f"{engine.terminal_equity!r} vs vectorized {vector.terminal_equity!r})"
            )
    return tuple(rows)
