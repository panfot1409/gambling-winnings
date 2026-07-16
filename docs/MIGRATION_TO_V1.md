# Migration to v1.0.0

## What v1.0.0 establishes

v1.0.0 is the first release with a **stable, supported public surface**: the
`eth_research.api` import root and the `eth-research` CLI. There is no earlier
public release to upgrade from in the SemVer sense — this release *defines* the
contract that future versions will be measured against
(see [VERSIONING_AND_COMPATIBILITY.md](VERSIONING_AND_COMPATIBILITY.md)).

If you have been calling the package's **internal modules** directly (for
example following the older README examples that import from
`eth_research.backtest`, `eth_research.metrics`, and friends), this document is
your migration path onto the supported surface.

## The one rule

> Import only from `eth_research.api`. Everything else under `eth_research` is an
> implementation detail with no compatibility guarantee, and may change or move
> without notice — including the modules listed in the left column below.

The internal modules still exist and still work; they are simply not part of the
public contract. Moving onto `eth_research.api` is what makes your code stable
across future releases, and it is what gives you the immutable results and
tamper-evident receipts the internal engines do not produce on their own.

## Symbol mapping

| Internal (not supported) | Public v1 (`eth_research.api`) |
| --- | --- |
| `eth_research.data.load_ohlcv(...)` | `validate_dataset(frame, DatasetSpec(...))` (you read the file into a frame) or a canonical dataset via `build_canonical_dataset` / `load_canonical_dataset` |
| `eth_research.splits.chronological_split(data)` | `chronological_split(dataset, ChronologicalSplitSpec())` |
| `eth_research.strategies.BuyAndHold()` etc. | `StrategySpec("buy_and_hold")`, or a custom `Strategy` subclass (see [CUSTOM_STRATEGIES.md](CUSTOM_STRATEGIES.md)) |
| `eth_research.backtest.run_backtest(...)` | `run_binary_backtest(dataset, strategy, cost, ...)` |
| `eth_research.fractional.engine.run_fractional_backtest(...)` | `run_fractional_backtest(dataset, strategy, cost, ...)` |
| `eth_research.metrics.summarize(result)` | metrics are on the returned `ResearchResult` — use `result.metric_map()` |
| an ad-hoc `CostModel(...)` | a named `CostSpec(scenario)` (see [COST_MODEL.md](COST_MODEL.md)) |

## Before and after

Internal-module style (unsupported):

```python
from eth_research.backtest import CostModel, run_backtest
from eth_research.metrics import summarize
from eth_research.splits import chronological_split
from eth_research.strategies import MovingAverageCrossover

# data prepared elsewhere as a validated frame
splits = chronological_split(data)
result = run_backtest(
    splits.validation,
    MovingAverageCrossover(fast_window=20, slow_window=50),
    CostModel(fee_rate=0.001, slippage_rate=0.0005),
    initial_cash=10_000.0,
    context=splits.validation_context(50),
)
print(summarize(result))
```

Public v1 surface (supported):

```python
from eth_research.api import (
    validate_dataset, chronological_split, run_binary_backtest,
    DatasetSpec, ChronologicalSplitSpec, StrategySpec, CostSpec,
)

dataset = validate_dataset(frame, DatasetSpec(interval_seconds=86400))
splits = chronological_split(dataset, ChronologicalSplitSpec())
result = run_binary_backtest(
    splits.validation,
    StrategySpec.create("moving_average_crossover", fast_window=20, slow_window=50),
    CostSpec("base"),
    context=splits.validation_context(50),
)
print(result.metric_map())
result_bytes = result.to_json_bytes()   # canonical, hashable, receipt-bindable
```

## What changes for you

- **Costs are named, not hand-specified.** Use a pre-declared `CostSpec`
  scenario matched to the engine, rather than constructing rates yourself.
- **Strategies are a spec or a subclass.** Name a built-in with `StrategySpec`,
  or pass a custom `Strategy` subclass to the Python API. The CLI and config
  accept built-ins only.
- **Results are immutable and serializable.** `run_binary_backtest` /
  `run_fractional_backtest` return a `ResearchResult` you can hash, serialize
  canonically, and bind into a `RunReceipt`.
- **The CLI is the turn-key path.** For an end-to-end run, prefer
  `eth-research backtest run --config …` over wiring the pieces yourself
  (see [QUICKSTART.md](QUICKSTART.md)).

## Errors

Catch the public taxonomy (`EthResearchError` and its subclasses) rather than
internal exception types. See [PUBLIC_API.md](PUBLIC_API.md).
