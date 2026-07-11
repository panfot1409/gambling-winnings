# Milestone 2B — Manual Coinbase Acquisition Procedure

_This session's environment cannot reach `api.exchange.coinbase.com`
(egress policy denies the CONNECT; policy denials must be reported, not
worked around), so the real-data steps below are **pending**. They are the
exact, complete procedure to finish Milestone 2B from a machine with
ordinary network access. Everything they rely on is already implemented
and tested on this branch. No downloader is committed by design — the
commands below are one-time, unauthenticated, manual `curl` requests
executed outside the package._

Hard rules carried over from the milestone charter:

- the data source is pinned: Coinbase Exchange, `ETH-USD` spot, 1-day
  candles from `https://api.exchange.coinbase.com/products/ETH-USD/candles`
  (documented at
  <https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles>).
  Switching source, venue, or product requires explicit approval first;
- raw responses and derived files live under the git-ignored `data/`
  tree and are **never committed**; only metadata/hash records
  (`research/m2b/*.json`) and, after the one-time test run,
  `reports/m2b/*` are tracked;
- never substitute synthetic data for a real benchmark;
- the real test segment is evaluated **exactly once**, and only after the
  protocol is committed and branch CI is green at the pre-registered
  commit.

## 0. Preconditions

```bash
git checkout claude/m2b-real-data-benchmarks
uv sync --locked --all-extras
uv run --no-sync pytest          # must pass before touching real data
mkdir -p data/raw/coinbase data/derived data/datasets/m2b
```

## 1. Fix the end boundary (once, before downloading)

Pick the last **completed** UTC day and freeze it. If today is
`2026-07-12` (UTC), the last completed day opened at
`2026-07-11T00:00:00Z`, and the overall half-open window ends at
`OVERALL_END=2026-07-12T00:00:00Z` (exclusive). The currently forming
candle is never included. Write the chosen value down; every later step
uses it verbatim.

## 2. Discover the earliest reliably available candle

ETH-USD order books opened on Coinbase Exchange in May 2016, but the
earliest era may contain days without published candles (no candle is
published for a bucket with no trades) and the adapter refuses every
missing day. Probe the early history:

```bash
curl -sS --fail \
  -H 'User-Agent: eth-research-manual-acquisition/0.3.0' \
  'https://api.exchange.coinbase.com/products/ETH-USD/candles?granularity=86400&start=2016-05-01T00:00:00Z&end=2016-10-25T00:00:00Z' \
  | python3 -m json.tool | head
```

Choose `OVERALL_START` = the earliest daily bucket from which the series
is continuous through `OVERALL_END`. You do not need to determine
continuity by eye: run the derivation in step 5 — it aborts listing the
first missing days — and move `OVERALL_START` to the day after the last
gap, re-deriving until it passes. **Each move of `OVERALL_START` is an
explicit, recorded decision** (it ends up in the committed acquisition
evidence), never a silent repair. If gaps appear in recent data (not just
the early era), stop and report instead: the milestone requires a
gap-free daily series, and recent gaps mean the source is not delivering
one.

## 3. Download fixed, non-overlapping windows

Windows tile `[OVERALL_START, OVERALL_END)` contiguously, each at most
299 daily buckets. The API's `start`/`end` parameters are *inclusive*
bucket opens, so for a half-open window `[W, W_END)` request
`start=W` and `end=W_END - 1 day`. One request per window, saved
byte-exact, never modified afterwards:

```bash
cd data/raw/coinbase
python3 - <<'EOF'
# Prints the exact per-window curl commands (it performs no networking).
# Set the two boundaries you fixed above:
import datetime as dt
OVERALL_START = dt.datetime(2016, 5, 18, tzinfo=dt.UTC)   # <- your value
OVERALL_END = dt.datetime(2026, 7, 12, tzinfo=dt.UTC)     # <- your value
DAY = dt.timedelta(days=1)
index = 0
window = OVERALL_START
while window < OVERALL_END:
    window_end = min(window + 299 * DAY, OVERALL_END)
    name = f"chunk_{index:03d}_{window:%Y%m%d}_{window_end:%Y%m%d}.json"
    start = window.strftime("%Y-%m-%dT%H:%M:%SZ")
    last = (window_end - DAY).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(
        "curl -sS --fail --retry 4 --retry-delay 2 "
        "-H 'User-Agent: eth-research-manual-acquisition/0.3.0' "
        f"'https://api.exchange.coinbase.com/products/ETH-USD/candles"
        f"?granularity=86400&start={start}&end={last}' "
        f"-o {name} && date -u +'{name} retrieved_at=%Y-%m-%dT%H:%M:%SZ' "
        f">> retrieval_log.txt && sleep 1"
    )
    # start/last are exactly the canonical UTC request strings the adapter
    # requires: requested_start == window start, requested_end == window
    # end minus one day (both YYYY-MM-DDTHH:MM:SSZ). retrieved_at must be
    # UTC (the `date -u` above), not a local-zone timestamp.
    index += 1
    window = window_end
EOF
```

Run the printed commands one by one (or paste the block into a shell).
They throttle to ~1 request/second — far under Coinbase's public rate
limit — and append each file's retrieval time to `retrieval_log.txt`
(kept, git-ignored, as the source for `retrieved_at`). If any request
fails, re-run just that request; do not hand-edit response files, and do
not re-download a window that already succeeded.

## 4. Sanity-check the raw files

- every file is a JSON array of arrays (`python3 -m json.tool` parses);
- no file is an error object (`{"message": ...}`);
- file count equals the printed window count.

## 5. Derive the canonical CSV and the acquisition evidence

```python
# uv run --no-sync python  (from the repository root)
from datetime import UTC
from pathlib import Path

import pandas as pd

from eth_research.data.coinbase import ChunkRequest, publish_acquisition

OVERALL_START = pd.Timestamp("2016-05-18T00:00:00Z")   # <- your value
OVERALL_END = pd.Timestamp("2026-07-12T00:00:00Z")     # <- your value
DAY = pd.Timedelta(days=1)

retrieved = {}
for line in Path("data/raw/coinbase/retrieval_log.txt").read_text().splitlines():
    name, _, stamp = line.partition(" retrieved_at=")
    retrieved[name] = pd.Timestamp(stamp)

requests = []
window = OVERALL_START
index = 0
while window < OVERALL_END:
    window_end = min(window + 299 * DAY, OVERALL_END)
    name = f"chunk_{index:03d}_{window:%Y%m%d}_{window_end:%Y%m%d}.json"
    requests.append(
        ChunkRequest(
            path=Path("data/raw/coinbase") / name,
            window_start=window,
            window_end=window_end,
            requested_start=window.strftime("%Y-%m-%dT%H:%M:%SZ"),
            requested_end=(window_end - DAY).strftime("%Y-%m-%dT%H:%M:%SZ"),
            retrieved_at=retrieved[name],
        )
    )
    index += 1
    window = window_end

# Transactional publication: the derived CSV and its evidence are written
# together (evidence last as the completeness marker); a failure rolls back
# so no orphan CSV without evidence can be left behind.
evidence = publish_acquisition(
    requests,
    overall_start=OVERALL_START,
    overall_end=OVERALL_END,
    derived_csv="data/derived/coinbase-eth-usd-1d.csv",
    evidence_path="research/m2b/acquisition_evidence.json",
)
print(evidence.derived_row_count, evidence.first_open_time, evidence.last_open_time)
print("pre-start rows excluded:", evidence.total_rows_before_window)
```

If this aborts on missing candles, adjust `OVERALL_START` per step 2 and
repeat. The evidence file is **tracked** (metadata and hashes only).

## 6. Freeze through the Milestone 2A builder and verify

```python
import pandas as pd

from eth_research.data import DatasetIdentity, build_canonical_dataset, load_canonical_dataset
from eth_research.data.provenance import sha256_file

identity = DatasetIdentity(
    quote_asset="USD",
    symbol="ETH-USD",
    venue="coinbase-exchange",
    interval=pd.Timedelta(days=1),
    source=(
        "Coinbase Exchange GET /products/ETH-USD/candles, granularity 86400; "
        "acquired per docs/M2B_ACQUISITION.md; evidence "
        "research/m2b/acquisition_evidence.json sha256 "
        + sha256_file("research/m2b/acquisition_evidence.json")
    ),
)
build = build_canonical_dataset(
    "data/derived/coinbase-eth-usd-1d.csv", identity, "data/datasets/m2b"
)
print(build.manifest.content_fingerprint, build.manifest.row_count)
for finding in build.quality_report.findings:
    print(finding.severity, finding.code, finding.count, finding.first_examples)
loaded = load_canonical_dataset(build.manifest_path)   # verification-on-read

# Semantic acquisition check: the derived CSV must re-derive byte-for-byte
# from the raw chunks (not merely match independently recorded hashes).
from eth_research.data.coinbase import verify_acquisition_evidence

verify_acquisition_evidence(
    evidence, chunk_dir="data/raw/coinbase", derived_csv="data/derived/coinbase-eth-usd-1d.csv"
)
```

Requirements: zero error-severity findings (any missing candle already
aborted in step 5); every warning (zero-volume candles are the likely
ones) is inspected and explained in the final report, never removed.
Then rebuild independently (fresh output directory) from the same inputs
and require the identical `content_fingerprint` and byte-identical
manifest apart from filenames — Parquet container bytes are *not*
claimed stable across toolchains.

## 7. Commit the dataset lock

```python
from eth_research.data.lock import build_dataset_lock, verify_dataset_lock
from eth_research.data.provenance import sha256_file
from eth_research._atomic import write_atomic
from pathlib import Path

lock = build_dataset_lock(
    build.manifest,
    manifest_sha256=sha256_file(build.manifest_path),
    acquisition_evidence_sha256=sha256_file("research/m2b/acquisition_evidence.json"),
)
verify_dataset_lock(
    lock,
    manifest_path=build.manifest_path,
    acquisition_evidence_path="research/m2b/acquisition_evidence.json",
)
write_atomic(Path("research/m2b/dataset_lock.json"), lock.to_json_bytes())
```

## 8. Pre-register the protocol, push, wait for CI

```python
from eth_research import __version__
from eth_research.protocol import build_benchmark_protocol, verify_protocol

protocol = build_benchmark_protocol(lock, package_version=__version__)
verify_protocol(protocol, lock)
write_atomic(Path("research/m2b/protocol.json"), protocol.to_json_bytes())
```

Commit `research/m2b/acquisition_evidence.json`, `dataset_lock.json`,
and `protocol.json` (message: `Freeze real ETH dataset metadata and
pre-register the benchmark protocol`), run every gate (`pytest`,
`ruff check .`, `ruff format --check .`, `mypy src tests examples`,
`uv lock --check`), push, and wait for branch CI to be green on both
Python 3.12 and 3.13. Record that commit SHA — it is the
`code_commit_sha` of the one-time authorization. The working tree must
be clean before proceeding.

Train/validation may be evaluated freely now
(`eth_research.evaluation.evaluate_train_validation`); the SMA windows
stay 20/50 no matter what those runs show.

## 9. The one-time test evaluation

Only after everything above, once, from the clean pre-registered commit:

```python
from eth_research.data.builder import load_canonical_dataset
from eth_research.data.lock import load_dataset_lock
from eth_research.evaluation import (
    EVALUATION_CONFIRM_TOKEN,
    OneTimeTestAuthorization,
    run_authorized_benchmark,
)
from eth_research.protocol import load_benchmark_protocol

dataset = load_canonical_dataset("data/datasets/m2b/coinbase-exchange-eth-usd-86400s.manifest.json")
lock = load_dataset_lock("research/m2b/dataset_lock.json")
protocol = load_benchmark_protocol("research/m2b/protocol.json")
run = run_authorized_benchmark(
    dataset,
    protocol,
    lock=lock,
    manifest_path="data/datasets/m2b/coinbase-exchange-eth-usd-86400s.manifest.json",
    acquisition_evidence_path="research/m2b/acquisition_evidence.json",
    ledger_path="research/m2b/test_evaluations.jsonl",
    output_dir="reports/m2b",
    authorization=OneTimeTestAuthorization(
        evaluation_id="m2b-coinbase-eth-usd-test-001",
        reason="authorized one-time Milestone 2B test evaluation",
        code_commit_sha="<the pre-registered commit SHA>",
        confirm_token=EVALUATION_CONFIRM_TOKEN,
    ),
)
print(run.results_path, run.report_path)
```

This writes the `started` ledger event before any test signal exists,
publishes `reports/m2b/benchmark_results.json` and
`benchmark_report.md` atomically, and appends `completed` with the
results' SHA-256. Re-run the test suite and static gates (without
re-running the test), then commit the two reports **and** the ledger
(message: `Record the one-time test result and honest benchmark
report`), push, and verify final CI.

**Never rerun.** A crash or failure after `started` is a consumed
access: the guard will refuse any further attempt for this dataset lock
and protocol. If a bug is discovered after test values were computed,
record the contamination and stop — a future holdout protocol must be
designed and independently reviewed; a rerun is never presented as the
original test.
