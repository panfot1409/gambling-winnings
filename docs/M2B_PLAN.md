# Milestone 2B Plan — Real ETH Data, Frozen Benchmarks, Test Discipline

_2026-07-11. Base: `main` at merge commit `4014532e` (Milestone 2A).
Release note: the `v0.2.0` annotated tag for that merge commit exists
locally but could not be published from this environment — the egress
proxy denies tag ref writes (HTTP 403 on `git push origin refs/tags/v0.2.0`
and on the REST tag-object endpoint). **Remote `v0.2.0` annotated tag is
pending due to an environment ref-write restriction** — recorded here as
explicit release-administration debt. `claude/m2-dataset-provenance` is
retained as the undeleted fallback until the tag exists remotely. Nothing
in this milestone assumes the remote tag exists._

## 0. Environment reality discovered in preflight (honest stop condition #1)

Milestone 2B's centrepiece is a real Coinbase Exchange ETH-USD daily
dataset. This environment **cannot reach the data source**: the egress
proxy answers `403` to `CONNECT api.exchange.coinbase.com:443` (and
`api.coinbase.com:443`) — an organizational policy denial, which the proxy
documentation instructs must be reported, not retried or worked around.
The only other fetch channel available to the agent is model-mediated
(a summarizing fetch tool) and is categorically unfit for byte-exact
market-data provenance.

Consequently this milestone follows its pre-agreed honest branch:

1. **Build and test all possible infrastructure** — acquisition-evidence
   model, offline adapter, dataset lock, benchmark protocol, guarded
   test-access ledger, evaluator, deterministic reporting — exercised
   end-to-end on synthetic fixtures that are always labelled synthetic.
2. **Stop with Milestone 2B explicitly incomplete**: no real dataset is
   frozen, no `dataset_lock.json` / `protocol.json` values exist, the
   committed test-access ledger stays empty (pristine), and no benchmark
   results are published. Synthetic data is never substituted for a real
   benchmark, and no third-party dataset is silently swapped in.
3. **Provide exact manual download instructions** (`docs/M2B_ACQUISITION.md`)
   that produce ignored local raw files this code can then freeze,
   pre-register, and evaluate — one time — in a follow-up session with
   network access or user-supplied files.

## 1. Scope and exclusions

Milestone 2B adds, inside the existing research-only boundary:

- offline historical-data **acquisition evidence** (a strict, deterministic
  record of what was downloaded, when, from where, and its exact hashes);
- a strict **offline Coinbase source adapter** (parses already-downloaded
  response files; contains no networking);
- a compact tracked **dataset lock** (metadata and hashes only);
- a **pre-registered benchmark protocol** model (deterministic, strict);
- a guarded, append-only **test-access ledger**;
- a deterministic **benchmark evaluator and reporting** layer on top of the
  unchanged Milestone 1 engine;
- version bump to **0.3.0**.

It must not add (hard exclusions, unchanged from the project charter):
live or paper trading; wallets, signing, private keys, custody, or
on-chain execution; order creation/routing/cancellation or exchange
account operations; API keys, authentication, credentials, or secrets;
WebSockets, polling services, daemons, or background jobs; a network
client inside the package or a committed acquisition downloader; leverage,
margin, borrowing, shorting, or derivatives; fractional target weights;
parameter optimization, automated searches, walk-forward selection, or ML;
new strategies beyond `BuyAndHold` and `MovingAverageCrossover(20, 50)`;
silent sorting, filling, clipping, interpolation, gap repair, or outlier
deletion; committed raw or canonical market data; a general CLI; new
dependencies (none are needed — hashing, JSON, and CSV use the standard
library and the existing pins).

The Milestone 1 backtest engine, metrics, strategies, and split
conventions remain unchanged. If active auditing finds a genuine
pre-existing correctness defect: reproduce it with the smallest failing
test, explain the impact, fix it in a separate focused commit, and stop
for review before any real test-segment evaluation if a documented
convention changed.

## 2. Threat model and likely failure modes

The adversary is not an attacker with repo access; it is **us** — sloppy
acquisition, silent data repair, test-set leakage, and overstated claims.
Failure modes this design must make structurally hard:

- **Acquisition lies**: truncated/malformed JSON accepted; API error
  objects with HTTP 200 parsed as candles; wrong field order silently
  transposing open/low; booleans or numeric strings passing as numbers;
  shuffled or duplicated rows accepted; gaps forward-filled; the currently
  forming candle included; raw files edited after hashing; path traversal
  via chunk filenames; overlapping request windows double-counting rows.
- **Provenance lies**: dataset/manifest/lock/evidence hashes that don't
  actually bind each other; a correct-looking manifest paired with the
  wrong Parquet; a quality report re-hashed by an attacker; bool-as-int
  fields; unknown fields silently ignored.
- **Evaluation lies**: test rows touched before authorization; off-by-one
  split or context boundaries; context rows contributing P&L; signals
  filling at their own close; segment equity curves stitched into a fake
  continuous portfolio; fill counts derived from signal flips instead of
  the ledger; turnover denominators drifting; NaN/Infinity smuggled into
  JSON; dict ordering changing published bytes; reports disagreeing with
  the `BacktestResult` they claim to summarize; the one-time test run
  silently repeated after a "surprising" number.
- **Process lies**: a failed test evaluation erased; a crash after the
  ledger reservation treated as "never happened"; partial report files
  left behind; documentation describing the milestone as more complete
  than it is.

## 3. Data source and its documented limitations

- Venue: **Coinbase Exchange**; market: **ETH-USD spot**; interval:
  **1 day (86,400 s)**; timestamps: **UTC candle open times**.
- Official documentation:
  <https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles>
- Endpoint: `https://api.exchange.coinbase.com/products/ETH-USD/candles`
- Response rows are arrays `[time, low, high, open, close, volume]` with
  `time` = bucket start in epoch seconds; responses are typically
  newest-first (strictly descending).
- Documented limitations honoured by the design: at most 300 candles per
  response (we use fixed, non-overlapping half-open windows of at most
  299 daily buckets); responses may include candles preceding the
  requested start (filtered and counted, never silently); **no candle is
  published for a bucket with no trades** (any missing day is therefore a
  hard abort, never a fill); historical data may be incomplete (the
  overall start must be chosen at a candle from which the series is
  continuous through the end boundary — an explicit, recorded decision);
  the end boundary is a fixed completed UTC day, never the forming candle.

Acquisition itself is one-time, unauthenticated `curl` outside the
package, producing ignored local raw files only. No downloader, HTTP
dependency, SDK, auth header, or reusable network code is committed —
`docs/M2B_ACQUISITION.md` records the exact commands instead. A source
change (different venue/product/API) requires explicit approval first.

## 4. Acquisition evidence and deterministic transformation

New module `src/eth_research/data/coinbase.py` (no networking, stdlib +
existing pins only):

- `parse_candles_chunk(raw_bytes, window_start, window_end)` — strict
  parse of one saved response body: top-level JSON array; each row an
  array of exactly 6 JSON numbers (bool rejected everywhere; strings,
  null, NaN/Infinity rejected; prices > 0, finite; volume ≥ 0, finite);
  epoch timestamps must align exactly to 86,400-second UTC boundaries;
  rows must be strictly ascending or strictly descending (a strictly
  descending response is reversed as an explicit, documented
  source-format transformation; anything else — shuffles, duplicates —
  is rejected); rows before `window_start` are excluded and counted;
  rows at/after `window_end` are rejected outright; an empty response is
  rejected (it always implies a missing day under the tiling rule).
- `derive_daily_ohlcv(chunk_requests, overall_start, overall_end,
  output_csv)` — chunk windows must exactly tile
  `[overall_start, overall_end)` half-open, each ≤ 299 days, no overlap,
  no gap; each raw file is read once into an immutable snapshot that is
  both hashed and parsed; chunks combine deterministically in
  chronological order; the combined series must be strictly ascending,
  gap-free at exactly 1-day steps, starting exactly at `overall_start`
  and ending exactly at `overall_end − 1 day`; every missing daily candle
  is a hard error (never synthesized/forward-filled); output is a
  deterministic CSV (`timestamp,open,high,low,close,volume`, ISO-8601 UTC
  timestamps, `repr`-round-trip floats, trailing newline) written
  atomically, suitable for the existing M2A builder (which re-parses CSV
  floats with round-trip precision). Raw response files are never
  modified.
- `AcquisitionChunk` / `AcquisitionEvidence` — frozen, constructor-
  validated models (single shared validation path, like M2A manifests)
  binding: schema version, package version, product (`ETH-USD`), venue
  (`coinbase-exchange`), granularity (86,400), documentation URL and
  endpoint (exact expected values), adapter algorithm/version
  (`coinbase-candles-v1`), overall start/end, and per chunk: declared
  half-open window, exact request parameters, retrieval time (UTC), raw
  basename (safe), raw SHA-256, response row count, and excluded
  pre-start row count; plus derived CSV basename/SHA-256/row count,
  first/last open time, the exact ordered transformation list, and an
  explicit `no_repair: true` confirmation. Cross-field invariants:
  chunks tile the overall window; contributed rows sum to the derived
  row count; derived row count equals the day span. Unknown/missing
  fields, wrong JSON types, bool-as-int, invalid hashes, unsafe
  filenames, inconsistent bounds, duplicate/overlapping windows, and
  evidence/data mismatches are rejected. Serialization is deterministic
  and round-trips byte-identically.
- `verify_acquisition_evidence(evidence, chunk_dir, derived_csv_path)` —
  re-hashes every referenced file and re-checks counts/bounds, so
  tampering after evidence creation is detected.

## 5. Freezing the real dataset (blocked this session; design final)

When the raw files exist, the derived CSV is frozen through the untouched
M2A builder with the exact identity: base `ETH`, quote `USD`, symbol
`ETH-USD`, venue `coinbase-exchange`, spot, interval 1D, source text tied
to the acquisition evidence. Requirements: zero schema/quality errors;
any missing candle aborts the milestone; warnings are reported and
explained, never removed; `load_canonical_dataset` must verify after
freezing; an independent rebuild from the same inputs must reproduce the
identical content fingerprint and manifest bytes (Parquet container bytes
are *not* claimed stable across toolchains).

Tracked lock `research/m2b/dataset_lock.json` (module
`src/eth_research/data/lock.py`): metadata and hashes only — identity
fields, interval, content fingerprint, manifest SHA-256, quality-report
SHA-256, derived-raw SHA-256, acquisition-evidence SHA-256, row count,
first/last open times, package version. Never market rows, never
filesystem paths. Strict single-path validation, deterministic
byte-identical round trip, and a `verify_dataset_lock` cross-check
against the local manifest and acquisition evidence.

## 6. Frozen benchmark protocol

`research/m2b/protocol.json`, parsed by a strict `BenchmarkProtocol`
model. Protocol schema version 1 **is** the frozen protocol — every
non-dataset value is pinned by the validator to exactly:

- split: `train_fraction = 0.60`, `validation_fraction = 0.20`, test =
  remainder, positional floor semantics (`int(n × fraction)` boundaries,
  the existing `chronological_split` behaviour);
- strategies: exactly `buy_and_hold` (no parameters) and
  `moving_average_crossover(fast_window=20, slow_window=50)` — no
  alternatives, duplicates rejected, unsupported parameters rejected;
- initial cash 10,000.00 USD **per segment** (each segment starts
  independently with the same initial cash and pays its own entry costs;
  segment equity curves are never stitched);
- fee 10 bps (0.001) and directional slippage 5 bps (0.0005) per fill;
- SMA warm-up context: 50 preceding bars (validation from train, test
  from train+validation; train has none); buy-and-hold: ex-ante entry at
  the first evaluated open, no context;
- terminal positions marked to market with hypothetical liquidation
  equity separately reported;
- metrics: total return, CAGR, Sharpe, Sortino, max drawdown, total
  traded notional, turnover, fill count, terminal mark-to-market equity,
  hypothetical terminal liquidation equity — annualized only from the
  validated interval (365.25-day year), with exact start/end metadata;
- risk-free rate 0.0; no strategy selection on test results; no
  frictionless headline numbers.

The dataset-binding fields (content fingerprint, manifest SHA-256, lock
SHA-256, acquisition-evidence SHA-256) are the only per-dataset values.
Wrong types, bool-as-number, unknown/missing keys, unsafe identifiers,
non-default semantics, negative costs, and lock mismatches are rejected;
serialization round-trips byte-identically. The protocol file must be
committed before any strategy is run on the test segment. **This session
commits no `protocol.json`** because there is no real dataset to bind.

## 7. Exact definition of test-set access

Allowed on the whole dataset before authorization: schema validation,
quality audit, fingerprinting/manifest verification, row counts and
timestamp boundaries, mechanical chronological splitting.

Forbidden on the test segment before authorization: strategy signal
generation, backtesting, fills/positions/cash/equity/return computation,
metric calculation, plotting, price/return summaries, and manual
inspection used to change parameters or strategy behaviour.

Train and validation may be evaluated repeatedly; the SMA windows stay
20/50 regardless of what those runs show.

## 8. One-time test-evaluation workflow

Append-only ledger `research/m2b/test_evaluations.jsonl` (module
`src/eth_research/ledger.py`), committed **empty** this session (pristine:
no test access has occurred). Each line is one strict, deterministic JSON
event binding: schema version, event (`started`/`completed`/`failed`),
unique evaluation id, dataset content fingerprint, dataset-lock SHA-256,
protocol SHA-256, exact pre-registered code commit SHA, exact test
boundaries, reason, UTC event time, result-report SHA-256 (completed
only), failure description (failed only).

The guarded evaluator refuses test evaluation by default; requires an
explicit confirmation token; verifies dataset lock, protocol, manifest,
and quality evidence first; refuses reused evaluation ids; refuses any
prior started/completed/failed access for the same (lock, protocol);
writes `started` before computing any test signal or P&L; appends
completion/failure honestly with atomic single-write fsynced appends; and
treats a crash after `started` as a consumed access. A malformed or
partial ledger line is loud contamination evidence, never skipped. If a
bug is discovered after test values were computed, the test is no longer
pristine: record the contamination and stop — no silent rerun presented
as the original.

Required order once real data exists: freeze dataset → lock → protocol →
all gates green → push → branch CI green on 3.12 and 3.13 → record that
commit SHA in the authorization → clean tree → run the test segment
exactly once → publish results and ledger events → re-run gates without
re-running the test → commit artifacts.

## 9. Result schemas and publication paths

`src/eth_research/evaluation.py`:

- accepts only a verified `LoadedDataset` plus a validated
  `BenchmarkProtocol` (fingerprint cross-checked);
- runs train/validation without touching test strategy values (the
  segment runner only ever receives the segment frame and its warm-up
  context; a spy test proves no test row reaches a strategy or the
  engine before authorization);
- reconciles every reported segment against its `BacktestResult`:
  `equity = cash + quantity × close` at every bar, fill count = ledger
  length, turnover = traded notional / initial cash, terminal equity =
  last equity mark, and segment boundaries = protocol boundaries;
- rejects non-finite report values; genuinely undefined Sharpe/Sortino
  (zero volatility / no downside) serialize as JSON `null`, never NaN or
  Infinity (`allow_nan=False` everywhere);
- serializes results deterministically (sorted keys, 2-space indent,
  trailing newline) and generates Markdown **only** from the validated
  JSON model; weak or negative results are shown without euphemism;
  synthetic/train/validation output is never labelled test output.

Tracked outputs after the authorized run only:
`reports/m2b/benchmark_results.json` and `reports/m2b/benchmark_report.md`
(atomic, transactional publication with rollback — a failed publication
leaves no partial files and never corrupts prior reports). **This session
publishes neither** (no real data). The report contents are specified to
include: dataset identity and every provenance hash, exact candle range
and row count, quality warnings, split boundaries and bar counts,
protocol hash and pre-registered commit SHA, cost assumptions, strategy
parameters, per-segment metrics for both strategies, SMA-vs-buy-and-hold
differences, trade counts and turnover, mark-to-market vs liquidation
equity, the one-time test evaluation id, explicit statements that each
segment resets capital and that the test set was evaluated once, and the
standing limitations (one venue; one daily dataset; one fixed SMA;
simplified constant slippage; no spread/impact/liquidity model;
close-marked drawdown misses intrabar troughs; annualized ratios assume
serial independence; historical results are not evidence of future
profitability). A positive number is not a profitability claim.

## 10. Active bug-hunting plan

After each major component, an explicit red-team pass attempts the full
attack list: acquisition (truncated/malformed JSON, error objects with
HTTP success, wrong candle width/field order, boolean timestamps/prices,
NaN/Infinity strings, descending/ascending/shuffled/partially shuffled
chunks, identical and conflicting duplicate timestamps, overlapping
windows, missing days, unaligned epochs, pre-start and post-end rows,
forming final candle, modified raw bytes after evidence creation, source
mutation between hash and parse, unsafe filenames/path traversal,
reordered chunk declarations); provenance (lock/evidence hash mismatches,
manifest paired with wrong dataset, re-hashed tampered quality report,
wrong venue/symbol/interval/bounds, boolean int fields, unknown/missing
fields, duplicate identities, inconsistent row counts); evaluation
(accidental test computation, off-by-one split boundaries, test rows in
validation context, context P&L contribution, close-signal filling early,
future-mutation changing earlier outputs, buy-and-hold entering before
the first open, SMA warm-up using future rows, concatenated segment
equities, test-result-driven configuration, wrong bps conversion,
mark-to-market vs liquidation confusion, signal-flip trade counts,
turnover denominator drift, non-standard JSON, dict-order-dependent
bytes, report/BacktestResult disagreement, duplicate test invocation,
crash after ledger reservation, failure mid-publication, partial files,
overwrite corruption). Every discovered bug gets: recorded symptom and
impact, the smallest failing regression test, a root-cause fix in a
clearly named separate commit, focused re-runs, full gate re-runs, and an
entry in the final audit. Financial arithmetic is validated against
hand-calculated fixtures, never against a second copy of the production
algorithm.

## 11. Test plan

Focused tests (all synthetic/hand-built; the existing 294 tests are
retained): strict acquisition-record construction and parsing;
byte-identical evidence round trip; Coinbase field mapping against
literal hand data; strict ascending/descending handling and
arbitrary-order rejection; boundary filtering with exact counts; gap and
duplicate rejection; raw-chunk tampering detection; deterministic derived
CSV bytes; dataset-lock strict parsing and cross-checks; protocol strict
parsing, pinning, and lock cross-checks; result-model strict parsing;
JSON `null` for undefined ratios; `allow_nan=False`; deterministic result
bytes; Markdown generated from the validated model; a spy proof that the
train/validation path never backtests test rows; exact split/context
boundaries; report-level future-mutation/prefix invariance; duplicate
test-authorization rejection; started-then-crashed access counted as
consumed; atomic/failure-injected report and ledger publication; version
0.3.0 consistency; no committed market-data files; and an AST-based scan
proving no network/exchange/auth imports exist in `src`, `tests`, or
`examples`.

## 12. Commit plan

1. `docs: Milestone 2B plan` (this file)
2. `Bump development version to 0.3.0`
3. `Add strict offline Coinbase acquisition evidence and adapter`
4. `Add verified dataset lock`
5. `Add deterministic benchmark protocol and result models`
6. `Add guarded test-access ledger`
7. `Add benchmark evaluator and report generation`
8. `Harden M2B with adversarial and failure-injection tests`
   (plus separate, clearly named fix commits for any bug found)
9. `Document manual Coinbase acquisition; record pristine ledger`
10. `Document Milestone 2B status, findings, and limitations`

The spec's commits for freezing real data, pre-registering the test, and
recording the one-time result are **deferred** (honest stop): they exist
in this plan and in `docs/M2B_ACQUISITION.md` as the exact follow-up
procedure. v0.3.0 is not tagged; no PR is opened; nothing is merged.

## 13. Honest stop conditions

Milestone 2B is **not complete** if any of the following hold — and this
session already knows the first one holds:

- real data could not be acquired (egress policy denial — the case here);
- the acquired data contains unresolved gaps or integrity errors;
- the one-time test evaluation was rerun, contaminated, or undocumented;
- published reports are not reproducible from the locked inputs;
- any quality gate (pytest, ruff check, ruff format, strict mypy,
  `uv lock --check`, CI on 3.12/3.13) is failing.

The milestone therefore ends this session as: **infrastructure complete
and hardened; real-data freeze, protocol pre-registration, and the
one-time test evaluation pending on data acquisition.**

## 14. Trust-boundary remediation rounds (R1–R7, C1–C4)

Two independent executable red-team passes on the pristine infrastructure
found trust-boundary failures that were each reproduced with a failing
test before being fixed. Rounds R1–R7 are recorded in the commit history;
this section documents the final closure round (C1–C4) and the standing
audit that keeps it honest.

### C1 — the running package is bound to the authorized commit

`run_authorized_benchmark` verified that `authorization.code_commit_sha`
is the repository `HEAD`, but nothing proved the *executing* `eth_research`
code came from that repository at that commit. A checkout carrying only
committed provenance metadata (no `src/eth_research`) could authorize an
evaluation run by code from an entirely different clone.

`gitcheck.verify_package_source(repo_root, head, package_root)` closes this
as the **first** gate in the public entry point, before the ledger is
read, the dataset is loaded, or any signal is computed. Its algorithm:

1. reject a symlinked `src/eth_research` directory, or a repository that
   has no such directory at all (metadata-only checkout);
2. reject unless the package was imported from exactly
   `<repo_root>/src/eth_research` (a foreign clone or a site-packages /
   editable install resolves elsewhere);
3. list the `*.py` tree committed under `src/eth_research` at `head`;
   reject if empty (no committed source at the authorized revision);
4. enumerate the working `*.py` files (skipping `__pycache__`, rejecting
   symlinked files); reject any untracked shadow module and any committed
   file missing from the working tree;
5. for every committed source file, reject unless its working bytes equal
   its blob at `head`.

This is a single-repository, single-researcher operational control: it
cannot attest a remote, a cryptographic identity, or a concurrent clone.
That limitation is stated in `gitcheck`'s module docstring and asserted by
a test. Because in-process `eth_research.__file__` is fixed to the running
checkout, the binding is exercised by dedicated unit tests
(`tests/test_gitcheck.py`), in-process negatives, and one genuine
integration test that clones the repository, imports that clone's own
package in a subprocess, and evaluates successfully — proving the gate
admits the real thing, not only that it rejects impostors.

### C2 — raw acquisition re-derivation is mandatory

`raw_chunk_dir` and `derived_csv` were optional on the one-time path;
omitting both silently skipped the semantic raw→derived acquisition
verification. They are now **required parameters** of
`run_authorized_benchmark` (omitting either is a `TypeError`), defensively
re-checked for `None` at runtime, and `verify_dataset_lock` now rejects
supplying exactly one (an all-or-nothing XOR guard) so a caller can never
downgrade to the metadata-only cross-check on the authorized path.

### C3 — impossible serialized accounting is rejected

`SegmentMetrics` accepted physically impossible combinations. The shared
constructor/parser now enforces, identically on construct and on parse:
zero fills iff zero traded notional and zero turnover; any fill requires
strictly positive traded notional and turnover; and
`0 < terminal_liquidation_equity <= terminal_equity` (a costed liquidation
can never exceed the marked equity). The exact turnover and total-return
identities are retained.

### C4 — standing audit of every optional / conditional trust input

Every optional argument and trust-relevant conditional branch across the
authorized path was audited for whether omitting or substituting it can
skip a mandatory verification. Trust-critical optionals are fail-closed;
the remainder are benign (they cannot skip a check) and are documented as
such rather than removed.

| Surface | Optional / branch | Omit or substitute → skips a check? | Disposition |
| --- | --- | --- | --- |
| `run_authorized_benchmark` | `authorization=None` | Yes — would run the test unauthorized | **Fail-closed**: refused by default |
| `run_authorized_benchmark` | `raw_chunk_dir`, `derived_csv` | Previously yes (C2) | **Fail-closed**: required params; `None` refused at runtime |
| `run_authorized_benchmark` | package-source binding (C1) | Previously yes | **Fail-closed**: first gate; foreign/modified/shadow source refused |
| `run_authorized_benchmark` | `ledger_path=None` | No | Defaults to the canonical tracked ledger; a non-canonical path is **refused**, never used |
| `run_authorized_benchmark` | `clock=None` | No | Benign timestamp source only; cannot skip a verification (at worst a bad clock fails its own `completed` append, leaving an honest consumed `started`) |
| `run_authorized_benchmark` | `overwrite=False` | No | Governs output-collision only; a second access for a consumed (lock, protocol) pair is refused regardless, so it cannot enable re-evaluation |
| `verify_dataset_lock` | `raw_chunk_dir`/`derived_csv` both `None` | Yes, on *that* call | Metadata-only mode is retained for standalone use, but the authorized path always passes both; **exactly one is refused** (XOR) |
| `verify_acquisition_evidence` | — | No optionals | All arguments mandatory; full semantic re-derivation always runs |
| `load_canonical_dataset` | — | No optionals | Manifest parse, schema re-validation, fingerprint recompute, and quality-report cross-check are unconditional |
| result assembly | `test_evaluation_id=None` | No | Controls only the "test discipline" report text; the dataset/protocol fingerprint match is unconditional |
| ledger handling | `append_event` sequencing | No | Whole ledger is re-validated before every append; `started` is the single writer and lives after every verification |

The audit found no additional bypass. The finding it hardened against is a
*coverage* gap, not a new hole: pre-authorization refusals were proven
inert only case by case. `tests/test_evaluation.py::TestPreauthorizationSideEffects`
now sweeps fourteen refusal scenarios (no authorization; explicit `None`
raw/derived; zero and foreign commit SHAs; dirty tree; alternate ledger;
evidence outside the repo; uncommitted protocol; mutated raw chunk;
non-reconstructing derived CSV; forged quality report; missing chunk
directory; existing-report collision), and for **each** proves — with the
backtest engine instrumented — that no strategy or backtest was ever
reached, the canonical ledger stayed byte-for-byte empty, and no report
was written. The one-time access is consumed only at the `started` event,
which is structurally the last thing before test signals exist.
