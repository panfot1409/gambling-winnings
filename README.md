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

## Real-data benchmarks (Milestone 2B)

Milestone 2B turns one real Coinbase Exchange ETH-USD daily history into a
locked, pre-registered benchmark with one-time test-set access. The real
data is **acquired and frozen** — 3702 gap-free daily candles,
2016-05-23 .. 2026-07-11 — and the train/validation benchmark is recorded;
the one-time test evaluation is still pending independent authorization.

- **Clean-room acquisition** (`eth_research.data.acquire_runner`,
  `eth_research.data.acquisition_plan`): the package itself has no
  networking. A tightly scoped GitHub Actions job performed public,
  unauthenticated `GET /products/ETH-USD/candles` requests only (no key,
  wallet, secret, or private endpoint), driven by a committed,
  machine-readable request plan, and committed the exact raw response
  bytes back to the branch. The offline adapter
  (`eth_research.data.coinbase`) enforces the documented
  `[time, low, high, open, close, volume]` format, strictly monotonic
  rows, half-open windows with counted pre-start exclusions, and a
  gap-free daily series — missing candles abort; nothing is filled or
  repaired. The **write-capable acquisition workflow is now retired**: the
  data is frozen, so the frozen branch retains no data-overwrite machine
  and no workflow can contact Coinbase; a future acquisition requires a
  new, separately reviewed workflow commit.
- **Pre-holdout fortress** (`eth_research.holdout`,
  `eth_research.dossier`, `eth_research.discovery`,
  `eth_research.decision`, `eth_research.test_readiness`): the one-time
  holdout is consumed by a durable `HoldoutIdentity` (dataset + test
  content fingerprints, instrument, test window) with a conflict policy
  that refuses a re-run on the same candles even if the protocol, lock,
  version, schema, evaluation id, or wording changes, and refuses an
  overlapping test window on the same instrument. A single
  `verify_frozen_dossier` re-derives the whole graph semantically — every
  artifact anchor, the acquisition receipt with a domain-separated
  raw-bundle fingerprint, the holdout identity recomputed from the
  verified dataset, and the train/validation results, report, and
  decision regenerated byte-for-byte — so forged provenance metadata or
  an edited number is caught (hash-bound and tamper-evident within this
  repository; not cryptographic authentication). The earliest-start
  decision is machine-verified from the raw discovery bytes, and a
  read-only `test_readiness` preflight reports readiness while never
  evaluating the holdout and never computing test performance.
- **Deterministic offline replay** (`eth_research.replay_m2b`): a fresh
  clone rebuilds the git-ignored derived CSV, canonical Parquet, manifest,
  and quality report from the committed raw bytes alone and verifies them
  against the frozen metadata (the reproducibility contract is the content
  fingerprint, never Parquet container bytes).
- **Frozen runtime contract** (`eth_research.environment`): the authorized
  evaluation runs only under the pinned numerical runtime — CPython
  3.12.3, numpy 2.5.1, pandas 3.0.3, pyarrow 25.0.0, bound to the
  committed `uv.lock`/`pyproject.toml`.
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
  one-time evaluation. Before any of that, two structural gates fail
  closed: the running `eth_research` package is proven to be exactly the
  `src/eth_research` tree committed at the authorized `HEAD`
  (`gitcheck.verify_package_source` — not a foreign clone, site-packages
  install, shadow module, or modified copy), and the raw chunk directory
  and derived CSV are **mandatory** so the derived data is always
  re-derived byte-for-byte from the raw responses (acquisition
  verification can never be silently skipped). Train/validation run
  freely and are reconciled exactly against the engine's accounting;
  results serialize deterministically (undefined ratios as JSON `null`)
  and the Markdown report is generated only from the validated JSON model.

Status: **Real data is frozen, independently replayable, and independently
reacquired with a bit-identical canonical content match (audit-002,
GitHub Actions run 29206830064). The fixed SMA(20/50) materially
underperformed buy-and-hold in the validation period (-203.19 pp) and is
recorded `rejected_for_test_promotion` — scientifically ineligible, so the
authorized test is honestly not ready. The holdout remains untouched and
sealed.** The dataset, its full provenance chain
(`acquisition_evidence.json`, `dataset_manifest.json`, `quality_report.json`,
`dataset_lock.json`, `runtime_contract.json`, `holdout_identity.json`,
`discovery_decision.json`, `frozen_dossier.json`,
`reacquisition_audit.json`, `protocol.json`), the train/validation dossier,
and the recorded rejection decision (`validation_decision.json`) are all
committed, and the production evaluator itself verifies the complete
frozen-dossier graph before the ledger boundary. The one-time **test**
evaluation is **not run** — the committed scientific decision refuses it —
and the committed test-access ledger is byte-empty (SHA-256
`e3b0c442…b7852b855`, zero events). See
[research/m2b/README.md](research/m2b/README.md),
[docs/M2B_REAL_DATA_PLAN.md](docs/M2B_REAL_DATA_PLAN.md), and
[docs/M2B_PRE_HOLDOUT_FORTRESS.md](docs/M2B_PRE_HOLDOUT_FORTRESS.md).

## Development research laboratory (Milestone 3A)

Milestone 3A is a rigorous environment for developing **future** ETH
strategy candidates on a walk-forward protocol — without abusing one
validation period and without ever touching the final holdout. It runs the
four fixed strategies over the research-train partition only and records an
honest, byte-reproducible result. No candidate is promoted, and both the
development gate and the final holdout stay sealed (their access ledgers are
byte-empty).

- **Immutable three-level data access** (`eth_research.development`): the
  frozen M2B dataset is split once, chronologically, into research train
  (2016-05-23 .. 2022-06-21, 2221 rows), a sealed development gate
  (2022-06-22 .. 2024-06-30, 740 rows), and the sealed final holdout
  (2024-07-01 .. 2026-07-11, 741 rows). The loader returns research-train
  rows **only**; a firewall rejects any row on or after the development gate
  — and any gap, duplicate, or reordering — before it can reach a strategy
  or the engine. The partition binds the frozen M2 dossier SHA-256.
- **Pre-registered walk-forward** (`eth_research.walkforward`): this is
  **fixed-rule rolling-origin out-of-sample evaluation** — no estimator is
  fit. An expanding window with 1095 initial rows and five contiguous
  out-of-sample folds over the remaining 1126 rows (226, 225, 225, 225,
  225), information gap 0, context ≤ 55 bars, each fold reset to an
  independent 10 000 USD. The expanding "training" row counts are the
  **information/history sets** that define each fold's origin and supply
  indicator context; the fixed strategies (SMA 20/50, Donchian 55/20) are
  never fitted on them. Independent resets are a comparison device, not one
  stitched portfolio.
- **Fixed strategies and predeclared costs** (`eth_research.strategies`,
  `eth_research.costs`): exactly cash, buy-and-hold, SMA(20/50), and
  Donchian(55/20) — **never** optimized; the Donchian channels exclude the
  current bar (`.shift(1)`), so signals are strictly causal. Every strategy
  is evaluated under all three predeclared cost scenarios (base 10/5 bps,
  stressed 20/10 bps, severe 50/25 bps); none is chosen after seeing results.
- **Honest evaluation** (`eth_research.development_evaluation`,
  `eth_research.bootstrap`): three aggregation views that are never
  conflated — an independent-fold summary, a pooled reset-OOS diagnostic
  (not a tradable path), and a full-train in-sample exploratory view — plus
  a deterministic moving-block bootstrap (seed 20260713, block 30, 5000
  resamples) of the mean daily paired excess return versus buy-and-hold.
  Every reported scalar is reconciled against the engine's accounting.
- **Pre-registered experiments through one fail-closed orchestrator**
  (`eth_research.experiment_registry`, `eth_research.development_orchestrator`):
  an append-only `registered → started → completed` registry (schema v1 for
  run-001/002, append-chained schema v2 for the correction) records each
  experiment before any real computation, and the only way to publish real
  research-train artifacts is `run_registered_development_experiment`, which
  runs ordered pre-checks and appends `started` before any strategy/backtest/
  bootstrap. There is no unregistered write path. Publication is a durable,
  rollback-safe batch transaction; results schema v2 identifies each run
  exactly (`experiment_id`, `methodology_id`, source-tree fingerprint).
- **Seam-safe inference.** The historical moving-block bootstrap v1 allowed
  blocks to cross independent-reset fold seams; the corrective run uses a
  fold-stratified bootstrap v2 (blocks strictly within a fold) plus a
  hierarchical sensitivity bootstrap. Historical run-001/002 results are
  archived, hash-verified, and never modified. Five folds are weak evidence
  and every interval is an in-sample research diagnostic.

Status: **the research-train walk-forward is run and recorded; no candidate
is promoted; the development gate and the final holdout are sealed and their
ledgers are byte-empty.** Over the research-train period (an ETH bull
market) buy-and-hold dominates median return, the active strategies beat
buy-and-hold in only ~40% of folds, and under the corrective run's
fold-stratified bootstrap the SMA and Donchian intervals of mean daily excess
return versus buy-and-hold straddle zero — the only interval that excludes
zero is cash, on the underperformance side, which is the opposite of alpha.
No alpha is claimed and nothing was tuned. No live-readiness or profitability
claim is made; this is not investment advice. See
[research/m3a/README.md](research/m3a/README.md),
[docs/M3A_PLAN.md](docs/M3A_PLAN.md), and
[docs/M3A_CLOSURE_REMEDIATION.md](docs/M3A_CLOSURE_REMEDIATION.md).

## Fractional execution-risk laboratory (Milestone 3B)

Milestone 3B is a trustworthy next-generation research engine built **on top of**
the M3A research-train partition, adding exact **fractional long-only** cash/ETH
allocation, causal next-open execution, a transparent execution-cost
decomposition, and strict risk overlays — all under the same sealed-partition
discipline. It runs exactly one preregistered experiment and records an honest,
byte-reproducible result. The goal is **not** to find a profitable strategy; it
is a measurement instrument. Nothing here can move money — the package
(`eth_research.fractional`) has no network client, no exchange authentication, no
wallet or signing, no order routing, and no leverage or short path.

- **Exact fractional accounting + bounded solver** (`fractional.accounting`,
  `fractional.solver`): a pinned-tolerance, bounded-bisection solver hits an
  executable target weight `Q·P / (C + Q·P)` with exact cash/ETH bookkeeping; a
  closed-form buy path makes the frictionless scenario reproduce the binary M3A
  engine bit-for-bit.
- **Causal liquidity + execution-cost decomposition** (`fractional.liquidity`,
  `fractional.cost_model`): liquidity is estimated only from rows strictly before
  the fill bar (no same-bar volume), and each fill's cost decomposes into
  explicit fee, half-spread, base-slippage, and lagged-liquidity market-impact
  terms. The spread/impact proxies are transparent and deterministic — **not**
  venue-calibrated.
- **Fractional engine + risk overlays** (`fractional.engine`, `fractional.risk`,
  `fractional.strategies`): the causal loop executes at the next open with
  deterministic partial fills under a participation cap, then reconciles every
  bar against its primitives. Five fixed strategies (cash, buy-and-hold,
  Donchian 55/20, and two 30-day/50%-annual volatility-target overlays with a
  0.25 turnover limiter) run under three cost scenarios (`compatibility_v1`,
  `causal_proxy_base`, `causal_proxy_stressed`). The drawdown breaker is off.
- **Strict, reconciled results + immutable publication** (`fractional.results`,
  `fractional.registry`, `fractional.archive`, `fractional.orchestrator`): a
  strict, symmetric results model (75 reconciled fold cells + 15 re-derivable
  aggregates, both sealed-ledger event counts pinned at 0), a hash-chained
  `registered → started → completed` registry, and a fail-closed orchestrator
  that publishes results / report / manifest as one durable byte-readback
  transaction. `python -m eth_research.fractional.replay --repo-root . --check`
  reconstructs the research train offline and reproduces the results and report
  byte-for-byte; the `M3B Replay` CI runs it dual-state on 3.12.3 + 3.12/3.13.

Status: **the one preregistered fractional run (run-001) is executed and
recorded; both sealed ledgers stay byte-empty and the development gate and final
holdout are untouched.** Over the research-train window buy-and-hold dominates
fold-median return (~+185%) but carries the deepest drawdown (~-79%); the active
strategies are shallower and mixed, the volatility-target overlays trade and pay
the most, and net return shrinks monotonically as the modeled frictions grow.
No alpha is claimed and nothing was tuned; losing folds are retained verbatim.
This is in-sample research, not live or test performance, and not investment
advice. See [docs/M3B_PLAN.md](docs/M3B_PLAN.md),
[docs/M3B_FINDINGS.md](docs/M3B_FINDINGS.md), and the specs
[docs/M3B_FRACTIONAL_ACCOUNTING_SPEC.md](docs/M3B_FRACTIONAL_ACCOUNTING_SPEC.md),
[docs/M3B_EXECUTION_COST_SPEC.md](docs/M3B_EXECUTION_COST_SPEC.md),
[docs/M3B_RISK_POLICY_SPEC.md](docs/M3B_RISK_POLICY_SPEC.md).

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
- **Targets are binary {0, 1}** (cash / fully long) through Milestone 3A.
  Milestone 3B adds exact **fractional long-only** weights in `[0, 1]`
  (`eth_research.fractional`) with a bounded-bisection solver and causal
  next-open partial fills; leverage (> 1) and shorting (< 0) remain
  unimplemented and are actively gated out.
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
        acquisition_plan.py # machine-readable request plan + receipts + generator CLI
        acquire_runner.py   # offline driver for the clean-room workflow (emit/verify)
        lock.py        # committable dataset lock: metadata and hashes only
        validation.py  # shared strict JSON validators
    splits.py       # chronological splits + warm-up context helpers
    strategies/     # Strategy interface, cash, buy-and-hold, SMA crossover, Donchian channel
    backtest.py     # bar-by-bar portfolio engine: open fills, fees, ledger
    metrics.py      # equity-curve metrics: return, CAGR, Sharpe, Sortino, drawdown
    _json.py        # one strict JSON decoder (dup-key + non-finite rejection)
    protocol.py     # frozen benchmark protocol + deterministic result models
    ledger.py       # append-only one-time test-access ledger
    environment.py  # authoritative runtime contract (CPython/deps/lockfiles)
    evaluation.py   # guarded benchmark evaluator + report generation
    gitcheck.py     # read-only git checks binding the test run + running package source to HEAD
    replay_m2b.py   # offline replay: rebuild + verify derived data from committed raw
    m2b_report.py   # deterministic train/validation-only benchmark dossier
    holdout.py      # durable holdout identity + freshness-conflict policy
    dossier.py      # the frozen research dossier: one hash-bound graph over every artifact
    discovery.py    # machine-verified earliest-continuous-start decision
    decision.py     # recorded validation-stage SMA rejection decision
    test_readiness.py # read-only pre-holdout readiness preflight
    development.py   # M3A three-level data-access firewall (research train only)
    walkforward.py   # M3A expanding-window walk-forward protocol + fold frames
    costs.py         # M3A predeclared cost scenarios (base/stressed/severe)
    development_evaluation.py # M3A walk-forward evaluator, diagnostics, honest aggregation
    bootstrap.py     # M3A deterministic moving-block bootstrap
    experiment_registry.py # M3A append-only experiment registry (registered->started->terminal)
    develop_m3a.py   # M3A research-train experiment publisher + reproduce (--check)
    fractional/      # M3B fractional long-only execution-risk laboratory:
        dataset.py       # integrity-only research-train loader (never a gate/holdout row)
        accounting.py    # exact fractional cash/ETH bookkeeping + pinned tolerances
        solver.py        # bounded-bisection target-weight solver (binary-parity closed form)
        liquidity.py     # causal lagged-liquidity estimator (strict < as-of slice)
        cost_model.py    # fee/spread/slippage/impact decomposition + 3 cost scenarios
        risk.py          # causal max-exposure / vol-target / turnover / drawdown overlays
        strategies.py    # the five fixed fractional strategy configurations
        engine.py        # causal next-open fractional backtest loop
        metrics.py       # reconciled fractional performance metrics
        reconciliation.py# re-derives every reported number from the primitives
        compatibility.py # bit-for-bit parity oracle vs the binary M3A engine
        protocol.py      # frozen fractional pre-registration protocol
        results.py       # strict results model + deterministic report renderer
        registry.py      # hash-chained M3B experiment registry (chained from line 1)
        archive.py       # immutable artifact manifest + replay verifier
        experiment.py    # the 75-cell runner (fold x scenario x strategy)
        orchestrator.py  # fail-closed register + execute + publish lifecycle
        replay.py        # dual-state offline replay (--check)
.github/workflows/
    ci.yml          # lint/type/test on 3.12/3.13 + authoritative-runtime job
    m2b-replay.yml  # fresh-clone reproducibility on authoritative + compat runtimes
    m3a-replay.yml  # M3A results reproduce byte-for-byte; both access ledgers byte-empty
    m3b-replay.yml  # M3B dual-state reproduce byte-for-byte; both ledgers byte-empty
    m3d-replay.yml  # M3D prospective cohort rebuilds byte-exact; three ledgers byte-empty
    m3e-replay.yml  # M3E review-only update facility reproduces byte-exact; no proposal
    m3f-replay.yml  # M3F freeze verifier + recovery drill + independent stdlib verifier
    # (write-capable acquisition workflows are retired: all data is frozen)
.github/scripts/
    verify_m3a_registry.py # CI gate: the registry terminal event binds the published bytes
tools/
    m3f_independent_verify.py # standard-library-only freeze verifier (imports no eth_research)
research/m2b/       # committable provenance records, frozen contracts, raw bytes, ledger
research/m3a/       # M3A partition, walk-forward protocol, registry, results, report, gate ledger
research/m3b/       # M3B fractional protocol, registry, results, report, run-001 manifest
research/m3d/       # M3D research-history governance + frozen prospective ETH-USD cohort (immature)
research/m3f/       # M3F freeze catalog, honest state, inventories, recovery capsule manifest + drill
tests/              # unit, hand-calculated ledger, and look-ahead regression tests
examples/           # runnable end-to-end example
docs/PLAN.md        # milestone plan
docs/M2A_PLAN.md    # Milestone 2A implementation plan
docs/M2B_PLAN.md    # Milestone 2B implementation plan
docs/M2B_REAL_DATA_PLAN.md # Milestone 2B Part B plan (acquisition + freeze)
docs/M2B_ACQUISITION.md # real-data acquisition procedure (GitHub Actions clean room)
docs/M3A_PLAN.md    # Milestone 3A development research laboratory plan
docs/M3B_PLAN.md    # Milestone 3B fractional execution-risk laboratory plan
docs/M3B_FINDINGS.md # Milestone 3B run-001 honest findings
docs/M3D_PLAN.md    # Milestone 3D prospective-evidence governance plan (data-only)
docs/M3D_ACQUISITION.md # M3D prospective cohort acquisition record
docs/M3D_PROSPECTIVE_PROTOCOL.md # M3D cohort protocol + 365-observation maturity rule
docs/M3D_THREAT_MODEL.md # M3D threats to "evaluated nothing" + controls
docs/M3F_PLAN.md    # Milestone 3F independent verification + recovery + supply-chain plan
docs/M3F_THREAT_MODEL.md # M3F assets, adversary, controls, and residual risks
docs/M3F_FREEZE_CATALOG_SPEC.md # M3F freeze catalog schema + verification
docs/M3F_RECOVERY_RUNBOOK.md # M3F recovery capsule reconstruction procedure
docs/M3F_SUPPLY_CHAIN_AUDIT.md # M3F workflow + dependency supply-chain closure
docs/M3F_BUG_LOG.md # M3F reproduced defects (failing-test-first) + fixes
docs/M3F_FINDINGS.md # M3F three-auditor red-team findings + fixes + honest negatives
docs/M3F_TERMINAL_AUDIT.md # M3F terminal verified-state audit + verdict
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

See [docs/PLAN.md](docs/PLAN.md) for the milestone plan,
[docs/M3A_PLAN.md](docs/M3A_PLAN.md) for the development research laboratory,
[docs/M3B_PLAN.md](docs/M3B_PLAN.md) for the fractional execution-risk
laboratory, [docs/M3D_PLAN.md](docs/M3D_PLAN.md) for the data-only
prospective-evidence governance facility,
[docs/M3F_PLAN.md](docs/M3F_PLAN.md) for the independent verification, hermetic
recovery, and supply-chain closure layer, and
[docs/REMEDIATION.md](docs/REMEDIATION.md) for the Milestone 1 correctness
remediation record.
