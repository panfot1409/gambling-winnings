# Execution model

This document defines exactly when a strategy decides, when the engine executes,
and what an execution may and may not do. The model is identical for both
engines; they differ only in the set of positions a strategy may target.

## Timing: decide on close, execute on the next open

Every dataset is indexed by candle **open time**. A bar `t` spans
`[t, t + interval)`, and its close price is the value observed at `t + interval`.

- A strategy's target for bar `t` is decided **after observing the close of bar
  `t`** — equivalently, it may use information only through `close[t-1]` when
  choosing the position it will hold entering bar `t`.
- The engine **executes that target at the open of bar `t`** (`open[t]`).

A strategy must never use any information at or after the point it is deciding
for. Looking ahead — letting a decision depend on data it could not have
observed yet — is a causality violation and is rejected by the engine with a
`CausalityError`.

## The ex-ante initial target

At the very first evaluated open there are no earlier observations to act on
(unless a warm-up context is supplied). The position established there is the
**ex-ante initial target**: a fixed, pre-declared value that must not depend on
any observed price. Buy-and-hold declares an initial target of 1 (enter long);
data-driven strategies keep the default of 0 (start in cash) until their signal
has data to act on.

## Warm-up context

A strategy that needs history before it can produce a signal (a moving average,
a Donchian channel) can be given a **context**: a contiguous block of bars that
strictly precedes and abuts the evaluated segment. The context feeds indicator
warm-up only — it produces no fills and no profit or loss. After a chronological
split, `validation_context(bars)` and `test_context(bars)` return the trailing
rows of the earlier segments for exactly this purpose.

The number of context bars actually supplied is recorded on the run as
`context_bars`, and it is part of the identity a receipt binds.

## Costs

Each executed fill carries cost. Under both engines the cost is
directional — it depends on whether the fill buys or sells — and consists of a
proportional fee on the fill notional plus slippage applied to the execution
price. The fractional engine adds a causal liquidity and participation proxy on
top. Cost scenarios are named and pre-declared; see [COST_MODEL.md](COST_MODEL.md).

## Binary engine

The binary engine is all-in / all-out: a strategy targets exactly `0` (hold
cash) or `1` (hold ETH) for each bar. It rebalances fully between those two
states. Short selling and leverage are out of scope and are rejected.

```python
from eth_research.api import run_binary_backtest, StrategySpec, CostSpec

result = run_binary_backtest(dataset, StrategySpec("buy_and_hold"), CostSpec("base"))
```

## Fractional engine

The fractional engine supports continuous exposure: a target weight in the
closed interval `[0, 1]`. It is long-only and unleveraged — exposure never
exceeds 1 and is never negative. On top of the timing and cost rules above, the
fractional engine models liquidity and participation causally: the tradable
size at bar `t` is bounded using information available only through `t-1`, so a
fill can be partial (or, under a participation constraint with no prior
liquidity, absent) rather than assuming unlimited depth.

```python
from eth_research.api import run_fractional_backtest, StrategySpec, CostSpec

result = run_fractional_backtest(
    dataset, StrategySpec("buy_and_hold"), CostSpec("causal_proxy_base"),
)
```

## Accounting invariants

The engines reconcile cash, quantity, and equity every bar. If a reconciliation
invariant is violated, the run stops with an `AccountingError` rather than
reporting a silently inconsistent result. Both `AccountingError` and
`CausalityError` are execution-category failures (exit code 6).

## Delegation

The public `run_binary_backtest` and `run_fractional_backtest` functions do not
reimplement the engines or the metrics — they resolve the strategy and cost
scenario, call the accepted engine, and record its output verbatim into an
immutable `ResearchResult`. The performance numbers are exactly what the
accepted metrics produced. See [METRICS.md](METRICS.md).
