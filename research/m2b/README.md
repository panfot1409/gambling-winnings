# Milestone 2B research records

Committable provenance records for the Milestone 2B real-data benchmark.
Market data itself is committed **only** as the exact raw public Coinbase
candle responses under `raw/coinbase/<attempt>/`; the derived CSV and the
canonical Parquet are reproducible and live under the git-ignored `data/`
tree. The remaining files here are metadata, hashes, the frozen contracts,
the train/validation dossier, and the test-access history.

## Status: real data acquired and frozen; test evaluation still pending

Real ETH-USD daily history was acquired through a tightly scoped GitHub
Actions clean room (public, unauthenticated `GET /products/ETH-USD/candles`
only — no key, wallet, or private endpoint), then verified and frozen
entirely offline. **3 702** daily candles, **2016-05-23 .. 2026-07-11**,
gap-free.

| file | status | meaning |
| --- | --- | --- |
| `test_evaluations.jsonl` | **present, empty — pristine** | Append-only test-access ledger. Empty means **no access to the real test segment has ever occurred**. Any recorded event permanently consumes the one-time evaluation for its dataset lock + protocol pair. |
| `acquisition_request_plan.json` | **frozen** | The 13-window request plan tiling `[2016-05-23, 2026-07-12)`; plan SHA-256 `f8f77ddb…ebf83`. |
| `raw/coinbase/<attempt>/` | **committed** | Exact raw public candle responses + a signed `acquisition_receipt.json` per attempt (`discovery-001` early-history probe; `coinbase-eth-usd-001` the 13-chunk full history). Aggregate well under the 10 MiB cap. |
| `EARLIEST_CONTINUOUS_DECISION.md` | **recorded** | The evidence-based choice of the 2016-05-23 start (first candle after the last early-history gap) and the 2026-07-12 end. |
| `acquisition_evidence.json` | **frozen** | Deterministic record binding every raw response to the derived OHLCV file; evidence SHA-256 `27ba6a60…bbbd2d0b`. |
| `dataset_lock.json` | **frozen** | Metadata+hash pin of the canonical dataset — content fingerprint `sha256:273f89eb…dd5718`, 3702 rows. |
| `runtime_contract.json` | **frozen** | The authoritative benchmark runtime — CPython 3.12.3, numpy 2.5.1, pandas 3.0.3, pyarrow 25.0.0 — pinned to the committed `uv.lock`/`pyproject.toml`. |
| `protocol.json` | **pre-registered** | The pinned benchmark protocol bound to the dataset lock; protocol SHA-256 `a75a9cf5…f26a81`. Committed with green CI **before** any train/validation number was computed. |
| `train_validation_results.json` / `train_validation_report.md` | **recorded** | The train/validation-only benchmark (both strategies), generated purely from the validated result model. The test segment is reported only by its mechanical boundaries. |

## Reproduce the ignored derived data on a fresh clone

```bash
uv sync --locked --all-extras --python 3.12.3
uv run --no-sync python -m eth_research.replay_m2b --repo-root . --work-dir data/m2b --check
uv run --no-sync python -m eth_research.m2b_report --repo-root . --check
```

This rebuilds the derived CSV, canonical Parquet, manifest, and quality
report from the committed raw bytes and verifies them against the frozen
metadata (the reproducibility contract is the content fingerprint, never
Parquet container bytes). The `M2B Replay` workflow runs the same checks on
the authoritative runtime and on Python 3.12 / 3.13.

## Test-set access, in one paragraph

Before the authorized one-time evaluation, the whole dataset may be
schema-validated, quality-audited, fingerprinted, counted, and mechanically
split — but no strategy signal, backtest, fill, equity, return, metric,
plot, or price summary may be computed on the test segment, and nobody
looks at test rows to change parameters. Train and validation may be
evaluated repeatedly; the SMA windows stay 20/50 regardless. The one-time
evaluation runs only through
`eth_research.evaluation.run_authorized_benchmark`, which proves the running
package and numerical runtime match the frozen commit and contract, verifies
the full provenance chain, writes `started` to this ledger before any test
signal exists, and records completion or failure honestly. Reruns are
refused forever; contamination is recorded, never laundered.

**Next step, requiring independent authorization:** review this frozen
dossier, then — and only then — run the one-time test evaluation. It is not
run here. The v0.2.0 remote-tag restriction remains recorded release debt
and is unrelated to the data work.
