# Milestone 2B research records

Committable provenance records for the Milestone 2B real-data benchmark.
Market data itself is never committed — raw responses, the derived CSV,
and the canonical Parquet live under the git-ignored `data/` tree; the
files here are metadata, hashes, and the test-access history.

| file | status | meaning |
| --- | --- | --- |
| `test_evaluations.jsonl` | **present, empty — pristine** | Append-only test-access ledger. Empty means **no access to the real test segment has ever occurred**. Any recorded event (`started`, `completed`, or `failed`) permanently consumes the one-time evaluation for its dataset lock + protocol pair. |
| `acquisition_evidence.json` | **pending** | Deterministic record binding every raw Coinbase response (window, hashes, counts, retrieval times) to the derived OHLCV file. Not created yet: this environment's egress policy denies `api.exchange.coinbase.com`, so no real data could be acquired. |
| `dataset_lock.json` | **pending** | Metadata+hash pin of the frozen canonical dataset (identity, content fingerprint, manifest/quality/raw/evidence SHA-256s). Blocked on acquisition. |
| `protocol.json` | **pending** | The pre-registered benchmark protocol bound to the dataset lock. Blocked on acquisition; must be committed with green CI **before** any strategy touches the test segment. |

The exact procedure to produce the pending files is
[`docs/M2B_ACQUISITION.md`](../../docs/M2B_ACQUISITION.md); the design
and the precise definition of test-set access are in
[`docs/M2B_PLAN.md`](../../docs/M2B_PLAN.md).

**Test-set access, in one paragraph.** Before the authorized one-time
evaluation, the whole dataset may be schema-validated, quality-audited,
fingerprinted, counted, and mechanically split — but no strategy signal,
backtest, fill, equity, return, metric, plot, or price summary may be
computed on the test segment, and nobody looks at test rows to change
parameters. Train and validation may be evaluated repeatedly; the SMA
windows stay 20/50 regardless. The one-time evaluation runs only through
`eth_research.evaluation.run_authorized_benchmark`, which verifies the
full provenance chain, writes `started` to this ledger before any test
signal exists, and records completion or failure honestly. Reruns are
refused forever; contamination is recorded, never laundered.
