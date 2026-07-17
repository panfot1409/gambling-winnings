# Custom strategies

The platform ships a closed set of built-in strategies, named by a
`StrategySpec` and accepted by both the CLI and the config. Beyond those, the
**Python API** accepts a custom binary strategy you write yourself, as a
subclass of the public `Strategy` base class.

> Custom strategies are a Python-API capability only. The CLI and the run config
> accept **built-in strategy kinds only** — a custom strategy cannot be named in
> a config. And a custom strategy is trusted, in-process code: it is not
> sandboxed. See [SECURITY_MODEL.md](SECURITY_MODEL.md).

## The `Strategy` base class

A binary strategy subclasses `Strategy` and implements one method:

```python
import pandas as pd
from eth_research.api import Strategy


class AbovePriorClose(Strategy):
    """Hold ETH next bar when this bar closed above the previous close."""

    initial_target = 0  # ex-ante position at the first evaluated open (0 or 1)

    def target_positions(self, data: pd.DataFrame) -> "pd.Series[float]":
        signal = (data["close"] > data["close"].shift(1)).astype(float)
        return signal.reindex(data.index).fillna(0.0)
```

Contract:

- `target_positions(data)` returns one value per input row, aligned to
  `data.index`, each exactly `0.0` (hold cash) or `1.0` (hold ETH). Fractional
  weights are not supported by the binary engine.
- The value at row `t` is the target decided **after observing the close of bar
  `t`**; the engine executes it at the **open of bar `t + 1`**. A strategy must
  never use rows after `t` to compute the value at `t` — doing so is look-ahead
  and is rejected with a `CausalityError`.
- `initial_target` is the class-level ex-ante position established at the very
  first evaluated open when no warm-up context exists. It must not depend on
  observed prices — set it to `1` for a strategy that starts long, otherwise
  leave the default `0` (start in cash).
- `name` (a property, defaulting to the class name) identifies the strategy in
  results and reports.
- Short selling and leverage are out of scope and are rejected by the engine.

## Running a custom strategy

Pass the instance straight to `run_binary_backtest` (or `calculate_metrics`):

```python
from eth_research.api import generate_synthetic_dataset, run_binary_backtest, CostSpec

dataset = generate_synthetic_dataset(n_periods=200, seed=7)
result = run_binary_backtest(dataset, AbovePriorClose(), CostSpec("stressed"))

print(result.run_spec.strategy.kind)   # "custom:AbovePriorClose"
print(result.metric_map()["num_trades"])
```

The result records the strategy as `custom:<name>` so it is distinguishable from
a built-in in the result and receipt. Everything else — costs, accounting,
metrics, canonical serialization — is identical to a built-in run.

## Warm-up context

If your strategy needs history before it can signal (an indicator lookback),
supply a warm-up `context`: a contiguous block of bars that strictly precedes
the evaluated segment. It drives warm-up only and produces no profit or loss.
After a chronological split, use `splits.validation_context(bars)` or
`splits.test_context(bars)`. See [EXECUTION_MODEL.md](EXECUTION_MODEL.md).

## Fractional strategies

Custom fractional strategies are **not** a public extension point in v1. The
fractional engine exposes exactly five built-in strategies (the
`FRACTIONAL_STRATEGY_KINDS`), each with no free parameters. There is no
supported public way to compose a new fractional strategy in this release; see
[V1_LIMITATIONS.md](V1_LIMITATIONS.md).
