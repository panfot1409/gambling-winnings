# Quickstart

This walks through a complete offline research run: generate a demo dataset and
config, run a backtest, inspect the published bundle, and verify the run
receipt. Everything runs locally with no network access.

## Install

There is no PyPI release yet, so `pip install eth-research` does not work today.
Build a wheel and install it (see [INSTALLATION.md](INSTALLATION.md)):

```bash
uv build
pip install dist/eth_research-1.0.0-py3-none-any.whl
```

Confirm the CLI is available:

```bash
eth-research version
```

## 1. Generate a demo

`demo generate` writes a deterministic synthetic dataset and a matching run
config into a directory you name:

```bash
eth-research demo generate --output demo
```

This creates:

```
demo/config.json          # a strict run config (binary SMA crossover, base costs)
demo/synthetic_eth.csv    # a synthetic OHLCV dataset
```

The generated `config.json` uses a moving-average crossover on the chronological
validation segment with a 30-bar warm-up context. You can regenerate with more
bars or a different seed:

```bash
eth-research demo generate --output demo --periods 800 --seed 1 --overwrite
```

## 2. Run the backtest

Point `backtest run` at the config. Paths inside a config are resolved relative
to the config file's own directory, so the dataset and output directory are
found next to `config.json`:

```bash
eth-research backtest run --config demo/config.json
```

It prints the deterministic run id, the result digest, and the files it
published:

```
published run c92eb35b...6500 to demo/results
result sha256: 5cbf46e7...4f53
files: manifest.json, receipt.json, report.md, result.json
```

## 3. Inspect the output bundle

The run publishes a four-file bundle into the config's output directory:

```bash
ls demo/results
# manifest.json  receipt.json  report.md  result.json
```

- `result.json` — the immutable, canonical record of the run and its metrics.
- `report.md` — a human-readable Markdown summary of the same run.
- `receipt.json` — a tamper-evident receipt binding the digests of the above.
- `manifest.json` — the completeness marker, written last, listing each file's
  SHA-256.

See [RESULT_AND_RECEIPT_SCHEMAS.md](RESULT_AND_RECEIPT_SCHEMAS.md) for the field
definitions and [METRICS.md](METRICS.md) for what each metric means.

## 4. Verify the artifacts

`result verify` re-parses the result and confirms it is in canonical form:

```bash
eth-research result verify --result demo/results/result.json
```

`receipt verify` re-checks the receipt against the artifacts it claims to bind.
Pass the optional report and config so their digests are checked too:

```bash
eth-research receipt verify \
  --receipt demo/results/receipt.json \
  --result demo/results/result.json \
  --report demo/results/report.md \
  --config demo/config.json
```

A successful verification prints the run id and exits 0; any mismatch exits 8
(`receipt_verification_error`). Every command also accepts `--json` for
deterministic machine-readable output.

## The same run from Python

The public API mirrors the CLI. This generates a dataset, splits it
chronologically, runs a binary backtest on the validation segment with a warm-up
context, and serializes the immutable result to canonical bytes:

```python
from eth_research.api import (
    generate_synthetic_dataset,
    chronological_split,
    run_binary_backtest,
    ChronologicalSplitSpec,
    StrategySpec,
    CostSpec,
)

dataset = generate_synthetic_dataset(n_periods=400, seed=0)
splits = chronological_split(dataset, ChronologicalSplitSpec())  # 0.6 / 0.2 / test

result = run_binary_backtest(
    splits.validation,
    StrategySpec.create("moving_average_crossover", fast_window=10, slow_window=30),
    CostSpec("base"),
    context=splits.validation_context(30),  # warm-up bars, no P&L
)

print(result.metric_map()["terminal_equity"])
result_bytes = result.to_json_bytes()  # canonical JSON; stable SHA-256
```

`generate_synthetic_dataset` is deterministic: the same arguments always produce
the same bytes, so `result.to_json_bytes()` and `result.result_sha256` are
reproducible on any machine (see [REPRODUCIBILITY.md](REPRODUCIBILITY.md)).

## What this platform does not do

It is research-only and offline by design: no exchange connectivity, no
authentication, no wallet, no order routing, and no leverage, shorting, margin,
or derivatives. It operates only on historical OHLCV data from local files or
the synthetic generator. See [SECURITY_MODEL.md](SECURITY_MODEL.md).
