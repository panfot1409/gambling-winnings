# Cost model

Every backtest runs under a named, pre-declared cost scenario. Scenarios are
fixed constants, never tuned to a result, and each belongs to exactly one
engine. A `CostSpec(scenario)` names the scenario; passing a scenario that does
not belong to the engine being run is a `ConfigurationError`.

There is deliberately no frictionless headline scenario for the binary engine,
so a cost-free number can never become the reported result.

## Binary cost scenarios

The binary engine applies a proportional **fee** on the fill notional plus
directional **slippage** on the execution price. Three scenarios are pinned, in
increasing severity:

| scenario | fee rate | slippage rate |
| --- | --- | --- |
| `base` | 0.001 (10 bps) | 0.0005 (5 bps) |
| `stressed` | 0.002 (20 bps) | 0.001 (10 bps) |
| `severe` | 0.005 (50 bps) | 0.0025 (25 bps) |

```python
from eth_research.api import run_binary_backtest, StrategySpec, CostSpec

result = run_binary_backtest(dataset, StrategySpec("buy_and_hold"), CostSpec("stressed"))
```

## Fractional cost scenarios

The fractional engine keeps the fee and slippage and adds a **half-spread** and
a **volume-impact** term, plus an optional **participation** (liquidity)
constraint. Costs are directional and transparent: the fee is applied to the
fill notional and is never mixed into the price; the fill price carries only
spread, base slippage, and the impact proxy.

The impact and participation terms are computed causally, using the lagged
(through `t-1`) liquidity estimate. A participation constraint with no prior
liquidity yields no fill, never an infinite impact.

| scenario | fee | half-spread | base slippage | impact coef | impact cap | max participation |
| --- | --- | --- | --- | --- | --- | --- |
| `compatibility_v1` | 0.001 | 0.0 | 0.0005 | 0.0 | 0.0 | none |
| `causal_proxy_base` | 0.001 | 0.00025 | 0.0005 | 0.01 | 0.005 | 0.001 |
| `causal_proxy_stressed` | 0.002 | 0.0005 | 0.001 | 0.03 | 0.015 | 0.0005 |

All three use a 30-bar liquidity lookback with a 30-observation minimum.
`compatibility_v1` disables the spread, impact, and participation terms so it
reproduces the binary engine's cost treatment exactly — it exists for parity
checking, not as a realistic scenario.

```python
from eth_research.api import run_fractional_backtest, StrategySpec, CostSpec

result = run_fractional_backtest(
    dataset, StrategySpec("buy_and_hold"), CostSpec("causal_proxy_stressed"),
)
```

## A causal research proxy, not a calibrated venue model

> The fractional liquidity-and-impact settings are a **deterministic causal
> research proxy, not a calibrated venue model.** This platform has daily OHLCV
> only — no quotes and no order book — so the impact and participation terms are
> a transparent, reproducible proxy driven by lagged daily dollar volume. They
> are not fitted to any exchange's microstructure and must not be read as an
> estimate of real execution cost on a live venue.

## Scenario / engine matching

`BINARY_COST_SCENARIOS` and `FRACTIONAL_COST_SCENARIOS` are disjoint. The
scenario you name must match the engine:

- binary: `base`, `stressed`, `severe`;
- fractional: `compatibility_v1`, `causal_proxy_base`, `causal_proxy_stressed`.

The strict run-config parser enforces the same rule at load time (see the config
schema in [DATA_CONTRACT.md](DATA_CONTRACT.md) and
[RESULT_AND_RECEIPT_SCHEMAS.md](RESULT_AND_RECEIPT_SCHEMAS.md)).
