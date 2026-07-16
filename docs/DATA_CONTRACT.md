# Data contract

The platform operates only on historical OHLCV (open, high, low, close, volume)
data, supplied either from a local file or from the deterministic synthetic
generator. There is no network client: nothing here downloads data. This
document defines the schema every dataset must satisfy and how datasets are
validated, generated, split, and frozen into canonical form.

## OHLCV schema

A raw input is a table with one row per completed candle. It must provide either
a `timestamp` column or a `DatetimeIndex`, plus the five OHLCV columns.

| field | meaning | constraint |
| --- | --- | --- |
| `timestamp` | candle **open time** | ISO-8601 datetime with timezone (or epoch converted before validation) |
| `open` | open price | float, strictly positive |
| `high` | high price | float, `>= max(open, close)` |
| `low` | low price | float, `<= min(open, close)` |
| `close` | close price | float, strictly positive |
| `volume` | traded volume | float, non-negative |

Each timestamp is the candle **open time**; the candle spans
`[t, t + interval)` and its close price is observed at `t + interval`. This
open-time convention is the basis of the execution model
(see [EXECUTION_MODEL.md](EXECUTION_MODEL.md)).

### Canonical form

After validation the frame is returned in a canonical form:

- index: a `DatetimeIndex` named `timestamp`, dtype `datetime64[ns, UTC]`,
  unique, strictly increasing, and regularly spaced;
- columns: `open`, `high`, `low`, `close`, `volume`, all `float64`;
- all values finite; prices strictly positive; volume non-negative;
- `high >= max(open, close)`, `low <= min(open, close)`, and `high >= low`.

## Validation is strict and never repairs data

`validate_dataset(frame, spec, *, require_clean=True)` enforces the schema and a
quality audit. It never silently fixes a problem:

- **Unsorted rows are rejected, never sorted.**
- **Missing candles and gaps are rejected, never filled.** The candle interval
  must be regular. Provide it via `DatasetSpec.interval_seconds`, and validation
  checks every spacing against it.
- **Timezone-naive timestamps are rejected** unless you explicitly opt in with
  `assume_utc=True` — including a single naive value mixed among timezone-aware
  ones (checked element by element). Timezone-aware timestamps, uniform or with
  varying offsets, are converted to UTC, which is unambiguous.
- **Columns outside the OHLCV set are rejected by name** so instrument metadata
  (for example a `symbol` column) cannot silently disappear. Pass
  `allow_extra_columns=True` to drop them explicitly.
- All content problems in a file are reported together, not one at a time.

A schema violation raises `DatasetSchemaError`. With `require_clean=True` (the
default), any error-severity quality finding raises `DatasetIntegrityError`. The
returned `ValidatedDataset` carries the validated frame, a content
`fingerprint`, the row count and interval, the UTC start/end times, and a
serializable `ValidationReport` of the audit (counts and per-code findings, with
no raw data examples).

```python
import pandas as pd
from eth_research.api import validate_dataset, DatasetSpec

frame = pd.read_csv("eth_daily.csv")
dataset = validate_dataset(frame, DatasetSpec(interval_seconds=86400))
print(dataset.fingerprint, dataset.row_count)
```

## Synthetic data

`generate_synthetic_dataset` produces a validated OHLCV dataset with no I/O and
no network. It is deterministic — the same arguments always produce the same
bytes:

```python
from eth_research.api import generate_synthetic_dataset

dataset = generate_synthetic_dataset(
    n_periods=500, interval="1D", start="2020-01-01",
    start_price=1000.0, drift=0.0002, volatility=0.02, seed=0,
)
```

Synthetic data is for demos, tests, and reproducible examples. It is not market
data and carries no claim about real ETH behaviour.

## Chronological splits

`chronological_split(dataset, spec)` divides a validated dataset into
non-overlapping train / validation / test segments in time order, using
`ChronologicalSplitSpec(train_fraction=0.6, validation_fraction=0.2)` (test is
the remainder). The result exposes each segment as a validated handle, plus
warm-up context helpers:

```python
from eth_research.api import chronological_split, ChronologicalSplitSpec

splits = chronological_split(dataset, ChronologicalSplitSpec())
train, validation, test = splits.train, splits.validation, splits.test
warmup = splits.validation_context(30)   # trailing 30 bars of train
```

The context is signal warm-up only: it precedes the evaluated segment and
contributes no profit and loss. See [EXECUTION_MODEL.md](EXECUTION_MODEL.md).

## Canonical datasets

Before real market data enters a study it can be frozen into a canonical
dataset: a parquet file, a quality report, and a manifest that records the
dataset's identity and content fingerprint.

```python
from eth_research.api import build_canonical_dataset, load_canonical_dataset

artifacts = build_canonical_dataset(
    "eth_daily.csv", "canonical/eth",
    symbol="ETH", venue="example", quote_asset="USD",
    interval_seconds=86400, source_description="local daily export",
)
dataset = load_canonical_dataset(artifacts.manifest_path)
```

`build_canonical_dataset` reads only `source_path`, writes only into
`output_dir`, refuses to overwrite existing artifacts unless `overwrite=True`,
and refuses any error-severity quality finding. `load_canonical_dataset`
re-validates the schema, recomputes the content fingerprint, and cross-checks
the quality report before returning; a mismatch raises `DatasetIntegrityError`.

From the CLI:

```bash
eth-research dataset validate --input eth_daily.csv --interval-seconds 86400
eth-research dataset build --input eth_daily.csv --output canonical/eth \
  --symbol ETH --venue example --quote-asset USD \
  --interval-seconds 86400 --source "local daily export"
eth-research dataset inspect --manifest canonical/eth/manifest.json
```

## Fingerprints

The content `fingerprint` is a digest of the validated frame's content. It is
the dataset's stable identity: two datasets with the same fingerprint hold the
same bars. The fingerprint (not the file path) is what a `ResearchResult` and a
`RunReceipt` bind, so a result is tied to the data it was computed on
independently of where that data lives on disk.
