# Milestone 2B Part B — Real Coinbase Data, Runtime Reproducibility, Dataset Freeze, and Train/Validation Dossier

This plan covers real ETH-USD daily data acquisition through a tightly
scoped GitHub Actions clean room, a strict runtime-environment
reproducibility contract, a deterministic offline replay path, the real
dataset freeze, protocol pre-registration, and a train/validation-only
benchmark dossier. The one-time **test** evaluation remains forbidden
throughout — this plan authorizes historical public-data acquisition and
train/validation research only.

Starting HEAD: `933b1a6844fb53b57ab96fe72ad6a4cc10de57c6` on
`claude/m2b-real-data-benchmarks`. The append-only test-access ledger
`research/m2b/test_evaluations.jsonl` is tracked and exactly zero bytes
(SHA-256 `e3b0c442…855`) and must stay that way.

## 1. Objectives and explicit exclusions

### Objectives
1. Prove the numerical runtime (Python, NumPy, pandas, PyArrow, lockfile)
   matches a frozen contract before any authorized evaluation — closing
   the last unbound-environment gap left after C1–C4.
2. Acquire the real Coinbase Exchange ETH-USD daily candle history through
   an auditable GitHub Actions job that performs only public,
   unauthenticated GET requests against one pinned endpoint.
3. Make the raw response bytes a durable, committed source of truth and
   reconstruct every derived artifact deterministically offline.
4. Freeze the real canonical dataset, dataset lock, runtime contract, and
   benchmark protocol, committed and CI-green **before** any performance
   number is computed.
5. Run and record a train/validation-only benchmark with an honest report,
   structurally proving the test segment is never handed to a strategy or
   the engine.

### Exclusions (unchanged, enforced structurally and by tests)
No test evaluation; no live or paper trading; no private/authenticated
exchange APIs, keys, wallets, mnemonics, credentials, or secrets; no order
construction or submission; no leverage; no shorting; no optimization or
parameter search; no machine learning; no network client inside
`src/eth_research`; no new runtime dependency; no synthetic substitute for
real data; no strategy/fee/slippage/split/metric change in response to any
real-data observation. No PR, merge, tag, history rewrite, or branch
deletion. The blocked v0.2.0 remote tag operation stays documented as
release debt and is not retried; no v0.3.0 tag is created.

## 2. Coinbase Exchange API facts (re-checked 2026-07-12)

Documentation (access date 2026-07-12; the docs site returns 403 to this
environment's egress, so facts were re-confirmed via secondary sources and
the existing verified adapter):

- Candles reference:
  `https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles`
- Rate limits: `https://docs.cdp.coinbase.com/exchange/rest-api/rate-limits`

Facts honoured:

- Endpoint: `GET https://api.exchange.coinbase.com/products/ETH-USD/candles`
  — **public and unauthenticated** for historical candles.
- Granularity is one of `{60, 300, 900, 3600, 21600, 86400}`; this project
  uses `86400` (one UTC day) exclusively.
- **At most 300 candles per response**; a start/end/granularity selection
  implying more than 300 points is rejected by Coinbase. Acquisition
  windows stay at most **299** daily buckets (existing cautious limit,
  retained).
- Each response row is `[time, low, high, open, close, volume]` with
  `time` = bucket start in epoch seconds. Responses are usually
  newest-first; a strictly descending response is reversed to chronological
  order as a documented, explicit transformation. Anything not strictly
  monotonic is rejected, never reordered.
- Coinbase warns "Historical rate data may be incomplete" and "No data is
  published for intervals where there are no ticks" — so a missing daily
  candle is a hard error here; nothing is synthesized, filled, or repaired.
- Responses may include candles *preceding* the requested start; those rows
  are excluded and counted, never silently dropped. Rows at/after the
  declared window end are rejected outright.
- Public rate limit is documented at roughly 3–10 requests/second per IP
  (429 on exceed). Acquisition is deliberately throttled to ≈1 request per
  second, far under the limit.

The canonical research identity is fixed: base `ETH`, quote `USD`,
product/symbol `ETH-USD`, venue `coinbase-exchange`, market `spot`,
interval 1 day / 86400 s, UTC candle-open timestamps. If Exchange API
acquisition fails, the source is **not** silently switched to Advanced
Trade, Kraken, Binance, Yahoo, CoinGecko, Kaggle, or any other dataset.

### Architecture decision: why GitHub Actions
- This development container's egress proxy denies the Coinbase host, so
  acquisition cannot run here.
- GitHub Actions is a separate, auditable execution environment. Only
  public historical GET requests to the one pinned endpoint are made; no
  exchange key, account, authentication header, wallet, secret, or trading
  endpoint is used.
- All network activity stays **outside** `src/eth_research`, confined to a
  single workflow. All parsing, validation, transformation, fingerprinting,
  and research logic remain offline and deterministic in the package.

## 3. Dependency / runtime reproducibility design

A clean, committed source tree can still produce different parsing,
floating-point, serialization, or metric behaviour under a different
NumPy/pandas/PyArrow/Python. Before acquiring data, add a strict runtime
contract (`src/eth_research/environment.py`; no new runtime dependency):

- `RuntimeContract` — immutable, strict-JSON model recording:
  `environment_schema_version`; Python implementation (must be CPython);
  the authoritative Python version; cache tag / ABI; OS family; machine
  architecture; `eth_research` version; exact `numpy`/`pandas`/`pyarrow`
  versions; SHA-256 of `uv.lock` and `pyproject.toml`; the authorized git
  commit linkage (via the existing source binding); and an explicit
  authoritative-vs-compatibility statement.
- `RuntimeSnapshot` — the live environment recomputed from `sys`,
  `platform`, and `importlib.metadata`.
- `RuntimeVerificationError` — raised on any mismatch.

Authoritative benchmark runtime: **CPython 3.12.3, Linux, x86_64**,
`numpy 2.5.1`, `pandas 3.0.3`, `pyarrow 25.0.0`, from the committed
`uv.lock` (uv 0.8.17). The existing Python 3.12 and 3.13 CI matrix remains
as *compatibility* coverage; the authorized benchmark runs only under the
exact authoritative contract. This is a **local, single-repository
reproducibility control**, not cryptographic attestation.

Canonical tracked path: `research/m2b/runtime_contract.json`. Verification
recomputes the live snapshot, requires exact agreement with the contract,
requires `uv.lock`/`pyproject.toml` working bytes to equal their committed
HEAD blobs and their recomputed hashes to match the contract, retains the
C1 package-source binding, and runs **before** the ledger is read or
written, before the real dataset is loaded, and before any signal/backtest.

## 4. Acquisition request-plan schema

Ad-hoc curl is replaced by a strict, machine-readable plan parsed through
the shared strict JSON decoder:

- `AcquisitionRequestPlan`: schema version; package version; source/venue/
  product; exact endpoint; `granularity_seconds = 86400`; timestamp
  convention; `overall_start` (inclusive) / `overall_end` (exclusive);
  fixed user-agent; max candles per request (300); internal max window
  (299 days); canonical ordered window list; expected request count; per-
  window output filename; documentation URLs; `no_repair` declaration; a
  reproducible plan SHA-256.
- `AcquisitionWindow`: zero-based ordinal; half-open `window_start`/
  `window_end`; canonical `requested_start`/`requested_end`; expected raw
  filename; fixed endpoint/product/granularity association.
- `AcquisitionAttemptReceipt` / `AcquisitionResponseReceipt`: per-attempt
  and per-response evidence (workflow run id, source commit, curl version,
  HTTP status, allowlisted headers only, byte length, SHA-256, retrieval
  time UTC) — never authorization headers, cookies, tokens, or env dumps.

Validation proves: all timestamps aware UTC; `overall_end` on a UTC day
boundary excluding the forming candle; each window positive and ≤ limit;
windows ordered, contiguous, non-overlapping, gapless, tiling
`[overall_start, overall_end)`; safe basenames; contiguous ordinals; no
arbitrary URL/scheme/host/product/query injection; internally consistent
arithmetic; byte-deterministic serialization. **No free-form shell command
is ever stored in JSON.** An offline plan generator (no networking, no host
override) emits the canonical plan from explicit start/end values only.

## 5. GitHub Actions security model

`.github/workflows/m2b-acquire.yml`, one-shot, tightly scoped:

- **Trigger**: never `pull_request`; never forks; restricted to
  `panfot1409/gambling-winnings` and `claude/m2b-real-data-benchmarks`;
  `workflow_dispatch` preferred, with a one-time branch-push bootstrap
  authorized if dispatch cannot be invoked from here; a bot raw-data commit
  must not retrigger acquisition.
- **Permissions**: default read-only; `contents: write` only on the
  acquisition job if direct branch publication is used; no `id-token`, no
  `packages`, no issues/PR write; no secrets/exchange credentials.
- **Supply chain**: every third-party action pinned to a full commit SHA
  (version documented); the committed `uv.lock`; `uv lock --check` before
  acquisition tooling runs.
- **Concurrency**: single run; no overlapping writer; no force push; fail
  if branch HEAD moves mid-run; run id + source commit in every receipt.
- **curl boundary**: fixed host `api.exchange.coinbase.com`, fixed path
  `/products/ETH-USD/candles`, fixed granularity `86400`, query values only
  from the validated committed plan; no shell eval; no free-form command
  string; no cross-host redirect; require HTTP 200; connect/total timeouts;
  conservative per-response and aggregate byte caps; fixed descriptive
  user-agent; ≈1 request/second; response bodies never printed to logs.
- **Retry**: never silently overwrite a successful response; every attempt/
  status recorded; a rerun has a distinct attempt identity; partial/failed
  attempts never presented as complete.
- **Capture**: body bytes written directly to a staging file (never piped
  through jq/json.tool/pretty-printers); retrieval time UTC; HTTP status;
  allowlisted headers only; byte length + SHA-256; curl version + runner +
  workflow run id; never secrets.
- **Offline validation before publication**: strict JSON parse; reject
  error objects even on HTTP 200; reject empty arrays, malformed widths,
  string/bool/non-finite values, duplicate/reordered/unexpected timestamps;
  validate window binding, file SHA and byte length; require every planned
  window and no extra response; run full semantic continuity + deterministic
  derivation checks.
- **Transactionality**: download to staging; publish nothing until all
  responses and receipts pass; evidence/completeness marker last; on
  failure leave no selected acquisition directory and no misleading marker,
  and upload a body-free/secret-free failure diagnostic.
- **Publication**: a complete verified run may commit raw response bytes and
  safe receipts directly to the feature branch as `github-actions[bot]`
  (run id, source commit, plan SHA, aggregate raw SHA in the message),
  pushed without force (fail rather than rebase if the branch moved), with
  an Actions artifact backup regardless.

Static repository tests prove: no `contents: write` workflow runs on
`pull_request`; the acquisition workflow is pinned to the exact repo/branch;
the only market-data host is the exact Coinbase host; no private endpoint;
no Coinbase secret; actions pinned by full SHA; no `curl | parser` mutation
pipeline; response paths cannot escape staging; branch publication cannot
force-push.

## 6. Earliest-continuous-candle discovery procedure

The final dataset must start at the earliest **defensible** daily candle
from which the series is continuous through the frozen end. `2016-05-18` is
not assumed valid merely because the old runbook used it as an example.

- **Stage A (discovery)**: fix a discovery window beginning no later than
  `2016-05-01` UTC; acquire the early-history response byte-exactly and
  preserve it (and its receipt) separately from the final canonical chunks;
  parse it with the strict offline adapter; determine the first returned
  daily open, all missing early intervals, the last early-history gap, and
  the earliest candidate start after that gap.
- **Stage B (complete-series proof)**: generate a full candidate plan from
  the proposed start to the fixed `overall_end`; acquire every chunk;
  reconstruct the whole series; require exact daily continuity. A **later**
  gap ⇒ stop and report the timestamp/chunk (do not move the start past a
  mid/recent-history gap, do not fill/interpolate/resample/switch sources).
  Gaps **only** in the earliest listing era ⇒ record every rejected start
  candidate and reason, commit the final start decision explicitly, never
  silently discard rows.

Discovery may inspect timestamps and integrity facts across the dataset; it
may not compute strategies, P&L, returns, price summaries, plots, or
test-segment statistics.

Fix `overall_end` before downloading: the first UTC midnight after the last
fully completed daily candle, excluding the forming candle; recorded in the
plan; never replaced with "now" during replay.

## 7. Raw-data durability decision

Raw bytes under an ignored `data/` tree are not durable enough (artifacts
expire; GitHub is the source of truth). For this **private** repo, the exact
raw daily JSON response bodies are committed **only if**: the complete
selected set is ≤ **10 MiB** aggregate; no single file exceeds its cap;
files contain only public candles (no headers/cookies/credentials/tokens/
paths/secrets); each is named and hashed by the plan/receipt; the repo stays
private; and a terms/licensing review is documented as required before any
future public release. Path: `research/m2b/raw/coinbase/<selected-attempt>/`.
Never commit derived CSV, canonical Parquet, arbitrary downloads, partial
directories, unredacted headers, or env dumps. If the cap is exceeded or
privacy cannot be verified, do not auto-commit — stop and document the
durable-storage blocker (do not rely on an expiring artifact).

Repository-hygiene tests move from "no data ever" to an exact allowlist:
only `.json` raw candle bodies under the one canonical M2B path; exact file
count; filenames present in the plan; each SHA/byte count matching its
receipt; aggregate ≤ 10 MiB; no `.csv`/`.parquet`/`.pq` tracked; no raw data
elsewhere; no unexpected extension; no symlink; no LFS pointer; no file
absent from the evidence chain.

## 8. Artifact path layout

Tracked (committable) under `research/m2b/`:
`acquisition_request_plan.json`, `acquisition_receipt.json` (or documented
equivalent), `acquisition_evidence.json`, `quality_report.json`,
`dataset_manifest.json`, `dataset_lock.json`, `runtime_contract.json`,
`protocol.json`, `train_validation_results.json`,
`train_validation_report.md`, `raw/coinbase/<attempt>/*.json`, and the
pristine `test_evaluations.jsonl`. Ignored/reproducible (never committed):
derived CSV, canonical Parquet, all of `data/`, staging directories, and
`reports/m2b/*` test outputs (which are never produced in this milestone).

## 9. Canonical replay procedure

One offline entry point (`python -m eth_research.replay_m2b`, no
networking) reconstructs every derived artifact from the committed plan,
selected raw bodies, safe receipts, reviewed source, and frozen runtime:
strict-parse plan and receipts → re-hash raw bodies → cross-check byte
lengths/hashes → re-parse each chunk against its window → reconstruct the
derived CSV byte-for-byte → build acquisition evidence → semantic raw→
derived verification → build the canonical dataset in a temp/ignored
location → strict schema/interval/identity validation → recompute content
fingerprint → regenerate quality report → regenerate manifest → regenerate/
verify lock and protocol when present → optionally regenerate
train/validation-only results when present → compare every tracked metadata
artifact byte-for-byte (never Parquet container bytes — compare validated
content fingerprints) → emit a compact machine-readable summary of hashes
and pass/fail states, never candle values. Replay is idempotent and never
overwrites tracked artifacts by default, never alters raw responses, never
touches the ledger, never calls the authorized test evaluator, never
generates test signals/fills/P&L/metrics/plots, never repairs candles, and
never accesses the network.

## 10. Data-quality acceptance rules

Zero error-severity findings; strictly ordered unique UTC daily opens;
exactly one-day spacing throughout; no missing daily candle; finite positive
OHLC; non-negative finite volume; OHLC consistency; no silently dropped
columns; no sorting/interpolation/fill/resample/dedup/repair. Every warning
is preserved and reported (code, count, examples), verified against raw
bytes; no rows removed; thresholds are **not** changed after seeing results;
the strategy is never adjusted because of a warning. Integrity errors ⇒ stop
before lock and protocol creation.

## 11. Protocol-freeze sequence

Only after the real dataset passes all integrity checks: build the real
`DatasetLock`; verify the full chain with both mandatory acquisition
arguments (raw chunks → derived CSV → evidence → manifest → quality → lock);
create the runtime contract; build the protocol with the already-pinned
assumptions (60/20/20 positional chronological split; buy-and-hold and
SMA 20/50; binary long/cash; USD 10,000 per independent segment; fee 0.001;
slippage 0.0005; next-open execution; no forced terminal liquidation;
separate hypothetical liquidation equity; pinned context/annualization/
metric set). **No** SMA window, fee, slippage, split fraction, or metric is
altered after seeing any real result. Commit the complete data identity,
runtime contract, lock, and protocol; push; wait for ordinary CI + the
authoritative-runtime replay job to be green; record the green SHA — all
**before** any train/validation number is computed. The ledger stays
byte-empty throughout.

## 12. Train/validation reporting rules

After protocol pre-registration is committed and green, run the benchmark on
train and validation only (repeatable for determinism; no pinned parameter
changes). Allowed: full-dataset schema/integrity validation, fingerprint/
count/mechanical split, exact train/validation boundaries, train/validation
signals+backtests+metrics, deterministic replay. Forbidden: handing any
test frame/context to a strategy; test target positions; running the engine
on test; computing test fills/cash/quantity/equity/returns/metrics/turnover/
trade counts; plotting test data; describing test performance; using test
rows to change behaviour; calling `run_authorized_benchmark` on the real
dataset; writing a `started` ledger event. Evaluation is instrumented so
tests prove no test row reaches `Strategy.target_positions`, `run_backtest`,
metrics, or rendering. Deterministic tracked artifacts
`research/m2b/train_validation_results.json` and `..._report.md` (report
generated only from the validated model) carry dataset identity + all
provenance hashes + runtime identity + source commit; mechanical
train/validation/test boundaries (test bounds only, no test prices or
performance); assumptions; train/validation metrics; SMA−buy-and-hold
comparisons clearly labelled with no profitability claim; every quality
warning; and a prominent honest disclaimer. Terrible results are committed
unchanged.

## 13. Test-set prohibition

The one-time real test evaluation is absolutely forbidden in this
milestone. No real `OneTimeTestAuthorization`; no `started` event; no test
signal/P&L/metric; no `reports/m2b/benchmark_results.json` or
`benchmark_report.md`; no inspection of test performance. Even a
"reproducibility" job must never call the authorized evaluator on the real
manifest. The canonical ledger must remain exactly zero bytes, verified at
the start and end of every job.

## 14. Failure and rollback behaviour

Acquisition is transactional (staging → validate-all → publish
completeness marker last → rollback on any failure with no partial
directory/marker and a body-free diagnostic). Dataset build and metadata
publication reuse the existing atomic, all-or-nothing publication with
in-memory rollback. A failed acquisition is an honest result reported with
the run URL and network evidence — never a synthetic substitute and never a
request for the user to manually download or transform candles. If durable
storage is blocked, stop and document rather than rely on an expiring
artifact. If cross-runtime replay differs, identify the first differing
field/bar/fill, do not mask it with rounding or loose tolerances, pin the
authoritative runtime, and stop if strategy comparison or metrics could be
affected.

## 15. Red-team matrix

After each happy path, actively attack (not merely test the listed cases):
**runtime** (foreign source; wrong dep versions; changed `uv.lock`/
`pyproject`; forged/alternate-path/symlinked contract; 3.13 attempting
authoritative authorization; missing/duplicated metadata; verification
ordered after the ledger; source/runtime restored post-import); **request
plan** (dup keys; NaN/Infinity/1e999; bool-as-int; unknown keys; overlap/
reorder/omit windows; 300/301 off-by-one; evil filename; alternate host/
private path/alternate product; query injection; forming-candle end);
**workflow** (PR trigger; fork; excess permissions; unpinned action;
plan-value shell injection; cross-host redirect; logged body; partial/
timeout/200-error-object/429/500/HTML/oversized/Content-Length-mismatch
responses; branch movement; concurrent run; partial bot commit; force-push;
rerun overwrite; artifact-vs-branch mismatch); **raw/evidence** (one
changed number/timestamp with updated hash; post-validation mutation;
duplicate/missing/extra/renamed file; byte-count mismatch; stale evidence/
manifest; forged pre-window count; non-UTC retrieval; plan/evidence
disagreement); **dataset** (missing/duplicate candle; reversed/shuffled;
non-finite; non-positive price; negative volume; OHLC inconsistency; mixed
zones; numeric-timestamp ambiguity; changed float parsing; Parquet/quality/
manifest tampering; version mismatch); **holdout** (train/val helper
receiving test rows; test metrics in report; renderer touching test frame;
mechanical bounds leaking prices; authorized evaluator during replay;
alternate/copied/refused-run-touched ledger; report collision consuming
access; hidden real test access); **publication** (per-artifact write
failure; unrelated files in bot commit; partial transaction; corrupt failed
overwrite; leftover temp files; early completeness marker; JSON/Markdown
disagreement; oversized raw; stray CSV/Parquet). Each discovered bug is
reproduced with a failing test, root-caused, fixed in a focused commit,
proven to fail before irreversible state, re-gated, and logged.

## 16. Exact commit sequence (adaptable to dependencies)

1. `docs: plan real-data acquisition and benchmark freeze` (this file).
2. `Add strict authoritative runtime contract`.
3. `Bind authorized evaluation to the frozen runtime`.
4. `Add strict acquisition request-plan and receipt models`.
5. `Add offline request-plan generator and replay tooling`.
6. `Add secured one-shot Coinbase acquisition workflow`.
7. `Add workflow security and failure-injection tests`.
8. `Record explicit earliest-continuous-series decision`.
9. `Commit selected raw acquisition and receipts` (may be a bot commit).
10. `Freeze acquisition evidence and canonical dataset metadata`.
11. `Add real dataset lock and runtime contract`.
12. `Pre-register fixed benchmark protocol`.
13. `Add fresh-clone deterministic replay CI`.
14. `Record train/validation-only benchmark results`.
15. `Add honest train/validation research report`.
16. `Red-team the complete acquisition and holdout boundary`.
17. `Document status, limitations, and next authorization step`.

No amend/rebase/squash/force-push/tag/merge/branch-delete/PR. A verified
`github-actions[bot]` raw-data commit is allowed and preserved in history.

## 17. Stop conditions

Stop and report honestly (no overclaim, no synthetic data) if: the branch/
HEAD/ledger/artifacts/cleanliness differ from the required starting state;
GitHub Actions cannot reach Coinbase; the acquired series has an
unresolvable non-early-era gap or any integrity error; durable storage
exceeds the cap or repo privacy cannot be verified; cross-runtime replay
reveals a material numerical discrepancy; or any quality gate or required CI
job is red. At best this milestone ends as "real data acquired, frozen,
protocol pre-registered, and train/validation benchmarks recorded; one-time
test evaluation still pending independent authorization." If acquisition
fails it ends as "infrastructure complete; real-data acquisition remains
blocked." The one-time test evaluation is never run here.
