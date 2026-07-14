"""Fractional long-only backtest engine (Milestone 3B, Phase 9).

The causal execution loop for one segment: at each bar ``t`` it takes the raw
strategy target decided from data through ``close[t-1]``, runs the frozen risk
pipeline (maximum exposure → volatility target → drawdown breaker → turnover
limiter, all causal), estimates lagged liquidity (rows through ``t-1``), solves
for the fill at ``open[t]``, applies the exact accounting, and marks equity at
``close[t]``. Nothing bar ``t``'s ``high``/``low``/``close``/``volume`` is read
before the fill; the maximum timestamp reaching any estimate is ``t-1`` and the
only bar-``t`` input is ``open[t]`` as the execution reference price.

A ``context`` frame (warm-up) is prepended for signal, liquidity, and volatility
estimation only; equity accrues over the evaluated ``frame`` starting from
``initial_cash``. The terminal position is marked at the last close and **never
force-liquidated**; a separate hypothetical cost-inclusive liquidation value is
reported alongside (it adds no fill and is excluded from trade counts).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pandas.api.types as pdt

from eth_research.data.schema import SchemaError, frame_interval, validate_ohlcv
from eth_research.fractional.accounting import (
    DEFAULT_TOLERANCES,
    Fill,
    PortfolioState,
    Side,
    Tolerances,
    equity_at,
    weight_at_reference,
)
from eth_research.fractional.cost_model import CostScenario, fill_price, solver_prices
from eth_research.fractional.liquidity import estimate_liquidity
from eth_research.fractional.risk import (
    DEFAULT_DRAWDOWN_CONFIG,
    DrawdownBreakerConfig,
    apply_max_exposure,
    apply_turnover_limit,
    apply_volatility_target,
    initial_drawdown_state,
    step_drawdown_breaker,
)
from eth_research.fractional.solver import solve_target_weight
from eth_research.fractional.strategies import FractionalStrategy


class EngineError(Exception):
    """The fractional engine received a malformed segment or context."""


@dataclass(frozen=True)
class BarRecord:
    """The full causal record of one evaluated bar (primitive + derived)."""

    timestamp: pd.Timestamp
    reference_open: float
    close: float
    raw_target: float
    executable_target: float
    volatility_scale: float | None
    drawdown_tripped: bool
    prior_achieved_exposure: float
    lagged_dollar_volume: float | None
    participation_cap: float
    side: Side | None
    executed_quantity: float
    fill_price: float | None
    fee: float
    partial: bool
    reason: str
    cash_after: float
    quantity_after: float
    achieved_exposure: float
    equity: float


@dataclass(frozen=True)
class FractionalBacktestResult:
    """Outcome of one fractional segment run (all series indexed by the frame)."""

    strategy_name: str
    scenario_name: str
    initial_cash: float
    context_bars: int
    bars: tuple[BarRecord, ...]
    fills: tuple[Fill, ...]
    cash: pd.Series
    quantity: pd.Series
    equity: pd.Series
    terminal_liquidation_equity: float

    @property
    def terminal_equity(self) -> float:
        return float(self.equity.iloc[-1])

    @property
    def total_return(self) -> float:
        return self.terminal_equity / self.initial_cash - 1.0

    @property
    def num_fills(self) -> int:
        return len(self.fills)

    @property
    def final_quantity(self) -> float:
        return float(self.quantity.iloc[-1])


def _simple_returns_through(closes: np.ndarray, count: int) -> np.ndarray:
    """Simple close-to-close returns over ``closes[:count]`` (through ``t-1``)."""
    prefix = closes[:count]
    if prefix.size < 2:
        return np.empty(0, dtype="float64")
    returns: np.ndarray = prefix[1:] / prefix[:-1] - 1.0
    return returns


def _require_canonical(label: str, frame: pd.DataFrame) -> None:
    """Reject a frame that is not strict canonical OHLCV (never repair it)."""
    try:
        validate_ohlcv(frame)
    except (SchemaError, ValueError, TypeError) as exc:
        raise EngineError(f"{label} is not canonical OHLCV: {exc}") from exc


def _validate_context(context: pd.DataFrame, frame: pd.DataFrame) -> None:
    """The warm-up context must be strictly-past, same-schema, and contiguous.

    A strictly-past prefix stops any future / out-of-sample row entering signal,
    liquidity, or volatility estimation; the same interval + contiguous seam stop
    a silently-gapped or mis-scaled context from perturbing the warm-up.
    """
    _require_canonical("context", context)
    if context.index.max() >= frame.index.min():
        raise EngineError(
            "context must be strictly before the frame "
            "(context.index.max() must be < frame.index.min())"
        )
    try:
        interval = frame_interval(frame)
    except (ValueError, TypeError) as exc:
        # A single-row evaluation frame cannot pin the interval that the seam /
        # same-interval checks below require; refuse it as a typed engine error
        # rather than leaking the schema's bare ValueError past the boundary.
        raise EngineError(
            f"cannot determine the evaluation interval to validate the context: {exc}"
        ) from exc
    if len(context) >= 2 and frame_interval(context) != interval:
        raise EngineError("context interval must match the evaluation interval")
    if frame.index[0] - context.index[-1] != interval:
        raise EngineError("context must be contiguous with the evaluation frame at the seam")


def _validate_signal(signal: object, full_index: pd.Index) -> np.ndarray:
    """Validate a strategy's target series against the full-frame index.

    The high-priority guarantee: a Series with the right length but a different
    (e.g. shuffled) index is **refused**, never applied positionally. The index
    is validated *before* the values are ever read as an array.
    """
    if not isinstance(signal, pd.Series):
        raise EngineError(f"strategy must return a pandas Series, got {type(signal).__name__}")
    if len(signal) != len(full_index):
        raise EngineError("signal length must equal the frame length")
    if not signal.index.equals(full_index):
        raise EngineError(
            "signal index must be identical to the frame index (no positional application)"
        )
    if pdt.is_bool_dtype(signal) or not pdt.is_numeric_dtype(signal):
        raise EngineError("signal must be a finite numeric Series")
    values: np.ndarray = signal.to_numpy(dtype="float64")
    if not np.isfinite(values).all():
        raise EngineError("signal has non-finite values")
    if (values < 0.0).any() or (values > 1.0).any():
        raise EngineError("signal targets must be within [0, 1]")
    return values


def run_fractional_backtest(
    frame: pd.DataFrame,
    strategy: FractionalStrategy,
    scenario: CostScenario,
    *,
    initial_cash: float = 10_000.0,
    context: pd.DataFrame | None = None,
    drawdown_config: DrawdownBreakerConfig = DEFAULT_DRAWDOWN_CONFIG,
    tol: Tolerances = DEFAULT_TOLERANCES,
) -> FractionalBacktestResult:
    """Run one causal fractional segment and return its reconciled records."""
    if frame.empty:
        raise EngineError("cannot backtest an empty frame")
    if initial_cash <= 0.0:
        raise EngineError(f"initial_cash must be positive, got {initial_cash!r}")
    _require_canonical("evaluation frame", frame)
    if context is not None and not context.empty:
        _validate_context(context, frame)

    full = frame if context is None or context.empty else pd.concat([context, frame])
    context_bars = len(full) - len(frame)

    signals = _validate_signal(strategy.signal.target_positions(full), full.index)
    initial_target = float(strategy.signal.initial_target)
    if not np.isfinite(initial_target) or initial_target < 0.0 or initial_target > 1.0:
        raise EngineError(f"initial target must be within [0, 1], got {initial_target!r}")
    opens = frame["open"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")
    full_closes = full["close"].to_numpy(dtype="float64")
    index = frame.index

    state = PortfolioState(cash=initial_cash, quantity=0.0)
    prior_equity = initial_cash
    breaker_state = initial_drawdown_state(initial_cash)

    records: list[BarRecord] = []
    fills: list[Fill] = []
    cash_by_bar: list[float] = []
    quantity_by_bar: list[float] = []
    equity_by_bar: list[float] = []
    last_liquidity: float | None = None

    for t in range(len(frame)):
        info_pos = context_bars + t
        raw = initial_target if info_pos == 0 else float(signals[info_pos - 1])
        reference_open = float(opens[t])
        # Exposure entering the bar, marked at the prior close (never bar t's).
        # The first evaluated bar is definitionally all-cash (exposure 0).
        if info_pos == 0:
            prior_achieved = 0.0
        else:
            prior_achieved = weight_at_reference(state, float(full_closes[info_pos - 1]))

        # --- Risk pipeline (causal; state through close[t-1]). ---------------
        target = apply_max_exposure(raw, strategy.risk.max_exposure).adjusted_target
        volatility_scale: float | None = None
        if strategy.risk.volatility_target:
            recent = _simple_returns_through(full_closes, info_pos)
            vt = apply_volatility_target(target, recent)
            target = vt.adjusted_target
            volatility_scale = vt.volatility_scale
        drawdown_tripped = False
        if strategy.risk.drawdown_breaker:
            target, breaker_state, dbt = step_drawdown_breaker(
                breaker_state, prior_equity, target, drawdown_config
            )
            drawdown_tripped = dbt.tripped
        if strategy.risk.turnover_limit is not None:
            target = apply_turnover_limit(
                target, prior_achieved, max_abs_weight_change=strategy.risk.turnover_limit
            ).adjusted_target
        executable = target

        # --- Lagged liquidity (rows strictly before open[t]). ----------------
        estimate = estimate_liquidity(
            full,
            index[t],
            lookback=scenario.liquidity_lookback,
            min_observations=scenario.liquidity_min_observations,
        )
        lagged_dv = estimate.dollar_volume_stat if estimate.available else None
        last_liquidity = lagged_dv

        # --- Solve + execute the fill at open[t]. ----------------------------
        buy_price, sell_price, fee_rate, cap = solver_prices(scenario, reference_open, lagged_dv)
        solved = solve_target_weight(
            state,
            reference_open,
            executable,
            buy_price=buy_price,
            sell_price=sell_price,
            fee_rate=fee_rate,
            participation_quantity_cap=cap,
            requested_target=raw,
            tol=tol,
        )
        state = solved.state_after
        if solved.fill is not None:
            fills.append(solved.fill)

        # --- Mark to market at close[t]. -------------------------------------
        close_t = float(closes[t])
        equity = equity_at(state, close_t)
        prior_equity = equity

        records.append(
            BarRecord(
                timestamp=index[t],
                reference_open=reference_open,
                close=close_t,
                raw_target=raw,
                executable_target=executable,
                volatility_scale=volatility_scale,
                drawdown_tripped=drawdown_tripped,
                prior_achieved_exposure=prior_achieved,
                lagged_dollar_volume=lagged_dv,
                participation_cap=cap,
                side=solved.side,
                executed_quantity=solved.executed_quantity,
                fill_price=solved.fill.fill_price if solved.fill is not None else None,
                fee=solved.fill.fee if solved.fill is not None else 0.0,
                partial=solved.partial,
                reason=solved.reason,
                cash_after=state.cash,
                quantity_after=state.quantity,
                achieved_exposure=solved.achieved_target,
                equity=equity,
            )
        )
        cash_by_bar.append(state.cash)
        quantity_by_bar.append(state.quantity)
        equity_by_bar.append(equity)

    terminal = _terminal_liquidation_equity(
        state, float(closes[-1]), last_liquidity, scenario, fee_rate=scenario.fee_rate
    )
    return FractionalBacktestResult(
        strategy_name=strategy.name,
        scenario_name=scenario.name,
        initial_cash=initial_cash,
        context_bars=context_bars,
        bars=tuple(records),
        fills=tuple(fills),
        cash=pd.Series(cash_by_bar, index=index, name="cash"),
        quantity=pd.Series(quantity_by_bar, index=index, name="quantity"),
        equity=pd.Series(equity_by_bar, index=index, name="equity"),
        terminal_liquidation_equity=terminal,
    )


def _terminal_liquidation_equity(
    state: PortfolioState,
    last_close: float,
    lagged_dollar_volume: float | None,
    scenario: CostScenario,
    *,
    fee_rate: float,
) -> float:
    """Hypothetical: sell all ETH at the last close, cost-inclusive (no fill).

    Uses the last causally-available lagged liquidity for impact; adds no actual
    fill and is excluded from trade counts. Mirrors the binary engine's terminal
    liquidation under the compatibility scenario.
    """
    if state.quantity <= 0.0:
        return state.cash
    sell_price = fill_price(scenario, last_close, "sell", state.quantity, lagged_dollar_volume)
    gross = state.quantity * sell_price
    fee = gross * fee_rate
    return state.cash + gross - fee
