# Result and receipt schemas

A `backtest run` publishes a four-file bundle: `result.json`, `report.md`,
`receipt.json`, and `manifest.json`. This document defines each artifact and the
strict run-config schema that drives a run. All JSON artifacts are in canonical
form (sorted keys, two-space indent, one trailing newline) and each has a stable
SHA-256 (see [REPRODUCIBILITY.md](REPRODUCIBILITY.md)).

## `result.json` — the research result

The immutable record of one run: schema/package/API versions, the full run
spec, the dataset identity, the evaluated window, and the delegated metrics.

```json
{
  "api_version": "1.0",
  "dataset_fingerprint": "sha256:58c1412b...a86347",
  "dataset_row_count": 80,
  "end_time": "2020-11-15T00:00:00+00:00",
  "evaluated_row_count": 80,
  "metrics": {
    "cagr": 0.04239326503300744,
    "initial_equity": 10000.0,
    "max_drawdown": -0.09058000230682206,
    "n_periods": 80,
    "num_trades": 2,
    "periods_per_year": 365.25,
    "sharpe": 0.30534146733206613,
    "sortino": 0.5970808425783248,
    "terminal_equity": 10091.353637760463,
    "total_return": 0.00913536377604629,
    "total_traded_notional": 20091.46508286331,
    "turnover": 2.009146508286331
  },
  "package_version": "1.0.0",
  "result_schema_version": 1,
  "run_spec": {
    "context_bars": 30,
    "cost": {"scenario": "base"},
    "dataset": {"allow_extra_columns": false, "assume_utc": false, "interval_seconds": 86400},
    "engine": "binary",
    "initial_cash": 10000.0,
    "risk_free_rate": 0.0,
    "split": {"train_fraction": 0.6, "validation_fraction": 0.2},
    "strategy": {"kind": "moving_average_crossover", "params": {"fast_window": 10, "slow_window": 30}}
  },
  "start_time": "2020-08-28T00:00:00+00:00"
}
```

Field notes:

- `dataset_fingerprint` is the dataset's content identity (with a `sha256:`
  prefix), not a file path.
- `dataset_row_count` is the row count of the dataset handle the run evaluated
  (after a split, that is the evaluated segment).
- `evaluated_row_count` is the number of bars in the produced equity curve.
- `metrics` values are delegated verbatim from the engine; an undefined metric
  is `null` (see [METRICS.md](METRICS.md)).

Load, validate, and hash a result in Python:

```python
from eth_research.api import ResearchResult

result = ResearchResult.from_json_bytes(open("result.json", "rb").read())
print(result.result_sha256)
print(result.metric_map()["terminal_equity"])
```

`ResearchResult.from_json_bytes(x.to_json_bytes())` reproduces `x` exactly.

## `receipt.json` — the run receipt

A tamper-evident receipt generated after the result bytes are finalized. It
binds versions, the immutable research inputs, the artifact digests, a
deterministic `run_id`, and the recorded interpreter/dependency versions.

```json
{
  "api_version": "1.0",
  "config_sha256": "1df70e7d...c17b7",
  "context_bars": 30,
  "cost_scenario": "base",
  "dataset_fingerprint": "sha256:58c1412b...a86347",
  "dataset_manifest_sha256": null,
  "engine": "binary",
  "initial_cash": 10000.0,
  "numpy_version": "2.5.1",
  "package_version": "1.0.0",
  "pandas_version": "3.0.3",
  "pyarrow_version": "25.0.0",
  "python_implementation": "CPython",
  "python_version": "3.12.3",
  "receipt_schema_version": 1,
  "report_sha256": "1dfb57be...d2fcf4",
  "result_sha256": "5cbf46e7...30e4f53",
  "risk_free_rate": 0.0,
  "run_id": "c92eb35b...946500",
  "strategy": {"kind": "moving_average_crossover", "params": {"fast_window": 10, "slow_window": 30}}
}
```

- `run_id` is the SHA-256 of the immutable research inputs alone (engine,
  dataset fingerprint, strategy identity, cost scenario, initial cash, context
  bars, risk-free rate). It is machine-independent.
- `dataset_manifest_sha256`, `report_sha256`, and `config_sha256` are `null`
  when that artifact was not bound.
- The receipt records **no** credential, wallet, key, absolute path, hostname,
  username, IP, wall-clock time, environment dump, or command string. The
  interpreter and dependency versions are recorded as facts and are not
  re-checked against the verifying machine.

Verify a receipt against its artifacts:

```python
from eth_research.api import RunReceipt, verify_run_receipt

receipt = RunReceipt.from_json_bytes(open("receipt.json", "rb").read())
verify_run_receipt(
    receipt,
    result_bytes=open("result.json", "rb").read(),
    report_bytes=open("report.md", "rb").read(),
    config_bytes=open("config.json", "rb").read(),
)  # raises ReceiptVerificationError on any mismatch
```

Or from the CLI: `eth-research receipt verify --receipt ... --result ...`.

## `report.md` — the human report

A deterministic Markdown summary of the same run: the engine, strategy and
parameters, cost scenario, run parameters, dataset fingerprint, evaluated
window, versions, and a metrics table. It contains no wall-clock time or host
identity. It is written unless `output.write_report=false`, in which case the
receipt's `report_sha256` is `null`.

## `manifest.json` — the completeness marker

Written last, transactionally. It lists the SHA-256 of every other file in the
bundle, so a present bundle is always complete and consistent.

```json
{
  "api_version": "1.0",
  "files": {
    "receipt.json": "4edbc84a...73ad47",
    "report.md": "1dfb57be...d2fcf4",
    "result.json": "5cbf46e7...30e4f53"
  },
  "manifest_schema_version": 1,
  "package_version": "1.0.0",
  "run_id": "c92eb35b...946500"
}
```

## Run config schema

A run config is a JSON or TOML document, parsed strictly (unknown keys rejected,
no coercion, finite numbers only). Top-level keys:

| key | meaning |
| --- | --- |
| `config_schema_version` | must be `1` |
| `dataset` | the data source (see below) |
| `engine` | `"binary"` or `"fractional"` |
| `strategy` | `{ "kind": <id>, "params": { … } }` |
| `costs` | `{ "scenario": <name> }` — must match the engine |
| `split` | `{ enabled=false, train_fraction=0.6, validation_fraction=0.2, evaluate="validation"|"train"|"test", context_bars=0 }` |
| `run` | `{ initial_cash=10000.0, risk_free_rate=0.0 }` |
| `output` | `{ directory, overwrite=false, write_report=true }` |

The `dataset` block is one of:

```json
{ "source": "synthetic",
  "synthetic": { "n_periods": 500, "interval": "1D", "start": "2020-01-01",
                 "start_price": 1000.0, "drift": 0.0002, "volatility": 0.02, "seed": 0 } }
```

```json
{ "source": "file",
  "file": { "path": "eth.csv", "interval_seconds": 86400,
            "assume_utc": false, "allow_extra_columns": false } }
```

Strict rules: exact keys only; no string-to-number coercion; `bool` is not
`int`; numbers must be finite; the cost scenario must belong to the chosen
engine; a `path` or `output.directory` must be a relative, traversal-free local
path — never absolute, a URL, a `.git` path, or under the governed `research/`
roots. Relative paths resolve against the **config file's own directory**.

Load a config in Python:

```python
from eth_research.api import load_config_file

config = load_config_file("config.json")   # or load_config(raw, fmt="json"|"toml")
```

## Schema versions

Each artifact and the config carry an explicit integer schema version, all `1`
in this release: `result_schema_version`, `receipt_schema_version`,
`manifest_schema_version`, `config_schema_version`, and the validation report's
`schema_version`. See
[VERSIONING_AND_COMPATIBILITY.md](VERSIONING_AND_COMPATIBILITY.md).
