# Public API

The supported Python surface is the single import root `eth_research.api`.
Everything re-exported from it (its `__all__`) is public and covered by the
compatibility policy in [VERSIONING_AND_COMPATIBILITY.md](VERSIONING_AND_COMPATIBILITY.md).
Every other module under `eth_research` — including `eth_research.api.*`
submodules — is an implementation detail and may change without notice.

```python
from eth_research import api
# or import individual names:
from eth_research.api import run_binary_backtest, StrategySpec, CostSpec
```

The surface is small and strictly typed: a closed error taxonomy, a set of
frozen value models, a strategy protocol plus a built-in registry, a handful of
pure functions that delegate to the accepted research engines, and a few
constants. No numerical formula is reimplemented in this layer — the functions
call the accepted engines and metrics and record their results.

## Constants

| Name | Value |
| --- | --- |
| `API_VERSION` | `"1.0"` |
| `CONFIG_SCHEMA_VERSION` | `1` |
| `ENGINES` | `("binary", "fractional")` |
| `BINARY_COST_SCENARIOS` | `("base", "stressed", "severe")` |
| `FRACTIONAL_COST_SCENARIOS` | `("compatibility_v1", "causal_proxy_base", "causal_proxy_stressed")` |
| `BINARY_STRATEGY_KINDS` | `("buy_and_hold", "cash", "moving_average_crossover", "donchian_channel")` |
| `FRACTIONAL_STRATEGY_KINDS` | `("cash", "buy_and_hold", "donchian_55_20", "vol_target_buy_and_hold_30d_50pct", "vol_target_donchian_55_20_30d_50pct")` |
| `BINARY_STRATEGY_PARAMS` | built-in binary strategy ids mapped to their fixed integer parameters |

## Error taxonomy

The hierarchy is closed and stable. `EthResearchError` is the single base;
catching it catches exactly the failures the platform promises to raise for bad
input, an unsatisfiable configuration, a malformed dataset, a misbehaving
strategy, or a tampered artifact. Programming bugs are deliberately **not** in
the taxonomy — they propagate unchanged.

Each class carries three class attributes: `code` (a stable machine-readable
string, unique per class), `exit_code` (the CLI process exit code, grouped by
family), and `category` (one of `input`, `execution`, `verification`,
`output`). `.as_dict()` returns the `--json` error envelope
`{"error", "category", "message"}`.

| Exception | `code` | `exit_code` | `category` |
| --- | --- | --- | --- |
| `EthResearchError` (base) | `eth_research_error` | 1 | — |
| `ConfigurationError` | `configuration_error` | 3 | input |
| `DatasetError` | `dataset_error` | 4 | input |
| `DatasetSchemaError` (⊂ `DatasetError`) | `dataset_schema_error` | 4 | input |
| `DatasetIntegrityError` (⊂ `DatasetError`) | `dataset_integrity_error` | 4 | input |
| `StrategyError` | `strategy_error` | 5 | input |
| `BacktestError` | `backtest_error` | 6 | execution |
| `AccountingError` (⊂ `BacktestError`) | `accounting_error` | 6 | execution |
| `CausalityError` (⊂ `BacktestError`) | `causality_error` | 6 | execution |
| `ResultValidationError` | `result_validation_error` | 7 | verification |
| `ReceiptVerificationError` | `receipt_verification_error` | 8 | verification |
| `OutputCollisionError` | `output_collision_error` | 9 | output |

## Value models

All value models are frozen dataclasses. Those that persist to disk are
canonical-JSON serializable through `to_dict` / `from_dict`, and the committed
artifacts additionally expose `to_json_bytes` / `from_json_bytes`. None of them
embed raw market data, absolute paths, or environment identity.

- `DatasetSpec(interval_seconds, assume_utc=False, allow_extra_columns=False)` —
  how to interpret a raw OHLCV frame.
- `ValidatedDataset` — a schema-validated frame plus its identity: `.frame`,
  `.fingerprint`, `.row_count`, `.interval_seconds`, `.start_time`,
  `.end_time`, `.report`.
- `CanonicalDataset` — a dataset loaded from an on-disk manifest; the same
  identity fields plus `.manifest_sha256`.
- `DatasetHandle` — the structural protocol (`.frame`, `.fingerprint`,
  `.interval_seconds`, `.row_count`) that both handles satisfy and that the run
  functions accept.
- `ChronologicalSplitSpec(train_fraction=0.6, validation_fraction=0.2)` — test
  is the remainder.
- `StrategySpec(kind, params)` — a built-in strategy identity. Construct with
  the keyword helper `StrategySpec.create(kind, **int_params)`; read parameters
  with `.param_dict()`.
- `CostSpec(scenario)` — a named cost scenario (the name determines the engine).
- `BinaryBacktestSpec` / `FractionalBacktestSpec(initial_cash=10000.0,
  context_bars=0, risk_free_rate=0.0)` — numeric run parameters.
- `ResearchRunSpec` — the complete serializable description of one run.
- `ResearchResult` — the immutable result (see below).
- `RunReceipt` — the tamper-evident receipt (see below).
- `ValidationFinding`, `ValidationReport` — a dataset-quality audit summary
  (counts and per-code findings, no raw data examples).
- `DataSplitResult` — a train / validation / test split, each a validated
  handle, plus `validation_context(bars)` and `test_context(bars)`.
- `CanonicalDatasetArtifacts` — the on-disk artifacts produced by a canonical
  build.
- `RunConfig` — a parsed, strict run configuration (see
  [DATA_CONTRACT.md](DATA_CONTRACT.md) and the config schema notes below).

### `ResearchResult`

Immutable record of one backtest. Key members:

- `.metric_map()` → `dict[str, float | int | None]`
- `.to_json_bytes()` / `ResearchResult.from_json_bytes(raw)` — canonical bytes,
  a fixed point (`from_json_bytes(x.to_json_bytes())` reproduces `x`).
- `.result_sha256` — SHA-256 of the canonical bytes.

An undefined metric (for example the Sharpe ratio of a zero-volatility cash
strategy) serializes as JSON `null`, so the record stays finite and
deterministic.

### `RunReceipt`

See [RESULT_AND_RECEIPT_SCHEMAS.md](RESULT_AND_RECEIPT_SCHEMAS.md). It binds the
schema/package/API versions, the immutable research inputs, the artifact
digests, a deterministic machine-independent `run_id`, and the recorded
interpreter/dependency versions. It records no credential, wallet, key, absolute
path, hostname, username, IP, wall-clock time, environment dump, or command
string.

## Strategy protocol and registry

- `Strategy` — the accepted abstract base class for a binary (all-in / all-out)
  strategy. A custom subclass is trusted caller code accepted directly by the
  Python API (see [CUSTOM_STRATEGIES.md](CUSTOM_STRATEGIES.md)). There is no
  plugin loader, no dynamic import from a path, and no `eval`/`exec`.
- `FractionalStrategy` — the accepted fractional strategy type; the five
  built-ins take no free parameters.
- `build_binary_strategy(spec)` → `Strategy`
- `build_fractional_strategy(spec)` → `FractionalStrategy`
- `list_binary_strategies()` → `tuple[str, ...]`
- `list_fractional_strategies()` → `tuple[str, ...]`
- `BINARY_STRATEGY_PARAMS` — the built-in binary strategies and their fixed
  integer parameter defaults.

## Functions

Dataset:

```python
validate_dataset(frame, spec, *, require_clean=True) -> ValidatedDataset
generate_synthetic_dataset(*, n_periods=500, interval="1D", start="2020-01-01",
                           start_price=1000.0, drift=0.0002, volatility=0.02,
                           seed=0) -> ValidatedDataset
chronological_split(dataset, spec) -> DataSplitResult
build_canonical_dataset(source_path, output_dir, *, symbol, venue, quote_asset,
                        interval_seconds, source_description, assume_utc=False,
                        allow_extra_columns=False, overwrite=False)
                        -> CanonicalDatasetArtifacts
load_canonical_dataset(manifest_path) -> CanonicalDataset
```

Backtest:

```python
run_binary_backtest(dataset, strategy, cost, *, initial_cash=10000.0,
                    context=None, risk_free_rate=0.0, split=None) -> ResearchResult
run_fractional_backtest(dataset, strategy, cost, *, initial_cash=10000.0,
                        context=None, risk_free_rate=0.0, split=None) -> ResearchResult
calculate_metrics(dataset, strategy, cost, *, initial_cash=10000.0,
                  context=None, risk_free_rate=0.0) -> dict   # binary only
```

Result, receipt, and publication:

```python
build_receipt(result_bytes, *, dataset_manifest_sha256=None, report_bytes=None,
              config_bytes=None) -> RunReceipt
verify_run_receipt(receipt, *, result_bytes, report_bytes=None, config_bytes=None)
publish_bundle(output_dir, files, *, overwrite=False, completeness_marker=None)
               -> dict[str, str]
```

Configuration:

```python
load_config(raw, *, fmt) -> RunConfig          # fmt is "json" or "toml"
load_config_file(path) -> RunConfig            # dispatches on .json / .toml
```

## Stability

`API_VERSION` is `"1.0"` — the version of the public surface, independent of the
package version, bumped only on a breaking change. The package pins `1.0.0`.
See [VERSIONING_AND_COMPATIBILITY.md](VERSIONING_AND_COMPATIBILITY.md).
