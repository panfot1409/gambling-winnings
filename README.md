# ETH Trading Research

A research-only Python toolkit for developing and evaluating Ethereum (ETH)
trading algorithms on historical OHLCV data.

> **Research only — by design.** This project contains **no** live trading,
> **no** exchange connectivity or API authentication, **no** wallet
> integration, and **no** leverage, margin, or short selling. It loads
> historical data from local files and evaluates strategies offline. Nothing
> here places orders or touches funds, and the backtest engine rejects
> anything other than binary long/cash targets.

## Requirements

- Python 3.12+

## Installation

With [uv](https://docs.astral.sh/uv/) (recommended — installs the exact
locked versions from `uv.lock`, the same environment CI verifies):

```bash
uv sync --locked --all-extras
```

Or with pip (floating versions within the `pyproject.toml` bounds):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quickstart

Run the end-to-end example — buy-and-hold benchmark vs an SMA crossover,
with fees and directional slippage, on a chronological validation segment
with indicator warm-up context:

```bash
python examples/run_sma_backtest.py                              # synthetic demo data
python examples/run_sma_backtest.py data/eth_daily.csv           # your own OHLCV file
python examples/run_sma_backtest.py --fast 10 --slow 30 --segment test
```

Typical output:

```
Split boundaries (candle open times):
  train      2020-01-01 00:00:00+00:00 .. 2021-03-13 00:00:00+00:00
  validation 2021-03-14 00:00:00+00:00 .. 2021-08-06 00:00:00+00:00
  test       2021-08-07 00:00:00+00:00 .. 2021-12-30 00:00:00+00:00

Data:    synthetic demo data (730 daily bars, seed 42)
Segment: validation (146 bars)
Context: 50 warm-up bars (signals only, no P&L)
Costs:   10.0 bps fee + 5.0 bps slippage per fill

buy_and_hold
  window            2021-03-14 00:00:00+00:00 .. 2021-08-07 00:00:00+00:00
  n_periods         146
  initial_equity    10,000.00
  terminal_equity   9,477.02
  total_return      -5.23%
  sharpe            -0.16
  max_drawdown      -22.44%
  num_trades        1
  ...
```

Or from Python:

```python
from eth_research.backtest import CostModel, run_backtest
from eth_research.data import load_ohlcv
from eth_research.metrics import summarize
from eth_research.splits import chronological_split
from eth_research.strategies import BuyAndHold, MovingAverageCrossover

data = load_ohlcv("data/eth_daily.csv")  # strict: sorted, regular, tz-aware
splits = chronological_split(data)       # 60% train / 20% validation / 20% test

result = run_backtest(
    splits.validation,
    MovingAverageCrossover(fast_window=20, slow_window=50),
    CostModel(fee_rate=0.001, slippage_rate=0.0005),
    initial_cash=10_000.0,
    context=splits.validation_context(50),  # indicator warm-up only, no P&L
)
print(summarize(result))
print(result.fills)  # immutable trade ledger
```

## Data format

`load_ohlcv` reads `.csv`, `.parquet`, or `.pq` files with one row per
completed candle:

| column      | type                                                  |
|-------------|-------------------------------------------------------|
| `timestamp` | candle **open time**, ISO-8601 datetime with timezone |
| `open`      | float, > 0                                            |
| `high`      | float, >= max(open, close)                            |
| `low`       | float, <= min(open, close)                            |
| `close`     | float, > 0                                            |
| `volume`    | float, >= 0                                           |

Validation is strict and never repairs data:

- unsorted rows are **rejected, never sorted**;
- timezone-naive timestamps are rejected unless you opt in explicitly with
  `assume_utc=True` — including single naive values mixed among
  timezone-aware ones (checked element by element); varying UTC offsets are
  unambiguous and normalize to UTC; epoch timestamps
  (`timestamp_unit="ms"`, …) are unambiguous UTC and need no opt-in;
- columns outside the OHLCV set are **rejected by name** (so instrument
  metadata such as a `symbol` column cannot silently disappear); pass
  `allow_extra_columns=True` to drop them explicitly;
- the candle interval must be regular — pass `expected_interval="1D"` to
  check against a known interval, or let it be inferred, which succeeds
  only when every spacing agrees; **missing candles and gaps are rejected,
  never filled**;
- all problems in a file are reported together.

Data files live in the git-ignored `data/` directory — market data is never
committed.

## Canonical datasets (Milestone 2A)

Before real market data enters the research loop, a raw local file is frozen
into an audited, fingerprinted canonical dataset — fully offline:

```python
import pandas as pd
from eth_research.data import (
    DatasetIdentity,
    audit_ohlcv_file,
    build_canonical_dataset,
    load_canonical_dataset,
)

identity = DatasetIdentity(
    quote_asset="USD",
    symbol="ETHUSD",
    venue="examplevenue",
    interval=pd.Timedelta("1D"),
    source="manually exported OHLCV CSV, obtained 2026-07-10",
)
result = build_canonical_dataset("data/raw/ethusd.csv", identity, "data/datasets")
# -> data/datasets/examplevenue-ethusd-86400s.canonical.parquet
#                                            .manifest.json
#                                            .quality.json

dataset = load_canonical_dataset(result.manifest_path)  # verifies on read
report = audit_ohlcv_file("data/raw/ethusd.csv", expected_interval=identity.interval)
```

- The **quality audit** reports — and never repairs — duplicates, ordering
  problems, missing candles, missing/non-finite/non-positive values, OHLC
  violations, zero-volume candles and runs, and outlier returns/ranges,
  each with exact counts and first examples. Any integrity error refuses
  the build; the raw file is never modified, sorted, filled, or clipped.
- The **manifest** records what the data claims to be (ETH spot only:
  exact symbol, venue, candle interval, UTC open-time convention, source
  description), the SHA-256 of the exact raw bytes that were parsed (one
  immutable snapshot — a mid-build source change aborts the build), a
  container-independent content fingerprint (`ohlcv-fp-v1/sha256` —
  equivalent CSV and Parquet inputs fingerprint identically), the package
  version that built it, the two build flags (`assume_utc`,
  `allow_extra_columns`), and the quality report's filename and SHA-256 —
  the audit evidence is bound to the dataset. Manifests validate through
  one strict shared path (exact JSON types, no repair; safe basenames;
  64-lowercase-hex hashes; consistent time bounds).
- `load_canonical_dataset` re-verifies everything: fingerprint, row count,
  time bounds, and the quality report (exact hash, strict parse, and
  cross-checked row count / interval / build flags). Missing, edited,
  malformed, or mismatched artifacts are rejected.
- Publication is **transactional**: artifact bytes are precomputed, writes
  are atomic with the manifest last as the completeness marker, and a
  failure mid-publication rolls back — a fresh build leaves nothing behind
  and a failed overwrite leaves the previous dataset byte-identical.
  Existing artifacts are never overwritten without an explicit
  `overwrite=True`. No network access: acquiring real ETH data is
  Milestone 2B.

## Real-data benchmarks (Milestone 2B — infrastructure)

Milestone 2B turns one real Coinbase Exchange ETH-USD daily history into
a locked, pre-registered benchmark with one-time test-set access:

- **Offline acquisition adapter** (`eth_research.data.coinbase`): parses
  already-downloaded candle responses (no networking in the package;
  acquisition is one-time manual `curl` per
  [docs/M2B_ACQUISITION.md](docs/M2B_ACQUISITION.md)), enforces the
  documented `[time, low, high, open, close, volume]` format, strictly
  monotonic rows, half-open request windows with counted pre-start
  exclusions, and a gap-free daily series — missing candles abort, and
  nothing is ever filled or repaired. Output is a deterministic CSV plus
  byte-reproducible acquisition evidence.
- **Dataset lock** (`research/m2b/dataset_lock.json`): a committable
  metadata+hash pin chaining acquisition evidence → derived file →
  canonical dataset → audit report; never market rows, never paths.
- **Frozen protocol** (`eth_research.protocol`): schema v1 admits exactly
  one value for every non-dataset choice — 60/20/20 chronological floor
  split, buy-and-hold and SMA(20, 50) only, 10 bps fee + 5 bps slippage,
  10,000 USD per independent segment (curves are never stitched), 50-bar
  SMA warm-up, the pinned metric set — so `protocol.json` can only bind a
  dataset, not tune anything.
- **One-time test discipline** (`eth_research.ledger`,
  `eth_research.evaluation`): the test segment runs only through a
  guarded evaluator — refused by default, explicit confirmation token,
  full provenance re-verification, `started` written to the append-only
  ledger before any test signal exists, completion/failure recorded
  honestly, and any access (including a crash) permanently consumes the
  one-time evaluation. Train/validation run freely and are reconciled
  exactly against the engine's accounting; results serialize
  deterministically (undefined ratios as JSON `null`) and the Markdown
  report is generated only from the validated JSON model.

Status: the real dataset, `dataset_lock.json`, `protocol.json`, and
`reports/m2b/` are **pending** — this environment cannot reach the
Coinbase endpoints, and synthetic data is never substituted for a real
benchmark. The committed test-access ledger is empty (pristine). See
[research/m2b/README.md](research/m2b/README.md).

## Conventions

- **Timestamps are candle open times**, UTC (`datetime64[ns, UTC]`); a
  candle spans `[t, t + interval)`.
- **Execution.** The target decided from data through `close[t-1]` fills at
  `open[t]`: buys at `open[t] * (1 + slippage_rate)`, sells at
  `open[t] * (1 - slippage_rate)`; fee = fill notional × `fee_rate`. Equity
  is marked at `close[t]`. A signal derived from `close[t]` can never fill
  at that close or capture the `close[t] -> open[t+1]` gap.
- **Accounting.** Exact long/cash bookkeeping: cash balance and ETH
  quantity per bar, an immutable fill ledger, and
  `equity = cash + quantity * close`. Cash can never go materially
  negative, quantity never negative — no borrowing, no hidden leverage.
- **Targets are binary {0, 1}** (cash / fully long) in Milestone 1;
  fractional weights are not offered because fractional rebalancing is not
  implemented.
- **Buy-and-hold enters ex ante** at the first available open, using no
  observed data (tested behaviour, not an accident of implementation).
- **Warm-up context.** Validation may use trailing train rows and test may
  use trailing train/validation rows as indicator context — signals only,
  zero P&L contribution; a signal from the final context close may fill at
  the first evaluation open.
- **Terminal policy.** Final positions are marked to market at the last
  close, never force-liquidated; the hypothetical liquidation value (sell
  at the last close with slippage and fee) is reported as
  `terminal_liquidation_equity`.
- **Metrics** derive from the reconciled equity curve. Total return =
  terminal / initial − 1; CAGR uses the recorded start (first open) and end
  (last close) times; Sharpe/Sortino annualize only from the validated
  regular interval (365.25-day year) or an explicit `periods_per_year`.
  Turnover = total traded notional / initial cash; trade count = executed
  fills. Invalid (non-positive) equity is rejected.
- **Costs are on by default** — frictionless runs require an explicit
  `CostModel(0.0, 0.0)`.

## Project layout

```
src/eth_research/
    data/
        schema.py      # strict OHLCV schema -> canonical frame format
        load.py        # CSV/Parquet -> validated frame
        synthetic.py   # deterministic synthetic OHLCV for tests/examples
        provenance.py  # dataset identity, manifest, content fingerprint
        quality.py     # offline data-quality audit (reports, never repairs)
        builder.py     # audited canonical dataset builder + verification
        coinbase.py    # offline Coinbase response adapter + acquisition evidence
        lock.py        # committable dataset lock: metadata and hashes only
        validation.py  # shared strict JSON validators
    splits.py       # chronological splits + warm-up context helpers
    strategies/     # Strategy interface, buy-and-hold, SMA crossover
    backtest.py     # bar-by-bar portfolio engine: open fills, fees, ledger
    metrics.py      # equity-curve metrics: return, CAGR, Sharpe, Sortino, drawdown
    protocol.py     # frozen benchmark protocol + deterministic result models
    ledger.py       # append-only one-time test-access ledger
    evaluation.py   # guarded benchmark evaluator + report generation
research/m2b/       # committable provenance records + pristine test ledger
tests/              # unit, hand-calculated ledger, and look-ahead regression tests
examples/           # runnable end-to-end example
docs/PLAN.md        # milestone plan
docs/M2A_PLAN.md    # Milestone 2A implementation plan
docs/M2B_PLAN.md    # Milestone 2B implementation plan
docs/M2B_ACQUISITION.md # manual real-data acquisition procedure (pending)
docs/REMEDIATION.md # Milestone 1 correctness remediation record
```

## Development

```bash
pytest                    # run the test suite
ruff format --check .     # formatting
ruff check .              # lint
mypy src tests examples   # strict type checking
uv lock --check           # uv.lock must stay in sync with pyproject.toml
```

Dependencies are frozen in `uv.lock` (runtime, dev extras, and
platform-conditional transitives, hash-pinned across Python 3.12/3.13);
the build backend is pinned via `[tool.uv] build-constraint-dependencies`.
CI installs with `uv sync --locked` and fails if the lock and
`pyproject.toml` disagree.

## Roadmap

See [docs/PLAN.md](docs/PLAN.md) for the milestone plan and
[docs/REMEDIATION.md](docs/REMEDIATION.md) for the Milestone 1 correctness
remediation record.
