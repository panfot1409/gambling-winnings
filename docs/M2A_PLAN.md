# Milestone 2A Plan — Dataset Provenance and Quality

_2026-07-11. Base: `main` at merge commit `11349efc` (tag `v0.1.0`).
Scope: an offline layer that turns a user-supplied local ETH OHLCV file into
an audited, fingerprinted canonical dataset. No real-data download (that is
Milestone 2B), no strategy/engine changes, no optimization, no fractional
weights, no ML, no network clients, no committed market data._

## 1. Why

Milestone 2B will freeze real ETH market data. Before any real data enters
the research loop, we need to be able to say — verifiably — *what* a dataset
is (asset, venue, interval, conventions), *where it came from* (raw-file
hash), *whether it is intact* (content fingerprint, manifest cross-checks),
and *what is wrong with it* (a quality audit that reports, never repairs).

## 2. Deliverables and design

### 2.1 `data/provenance.py` — identity, manifest, fingerprint

- `DatasetIdentity` (frozen): `base_asset` (must be `"ETH"`), `quote_asset`,
  `symbol` (exact venue symbol), `venue`, `market_type` (`"spot"` only),
  `interval` (`pd.Timedelta`), `source` (free-text description). Validated
  in `__post_init__`; derives a filesystem-safe `slug`.
- `DatasetManifest` (frozen): manifest schema version (`1`), package
  version (`eth_research.__version__`), the identity fields, the UTC
  open-time convention string, `raw_filename` + `raw_file_sha256`,
  `fingerprint_algorithm` + `content_fingerprint`, `row_count`,
  `first_open_time`, `last_open_time`, `canonical_filename`.
  Deterministic serialization: sorted-key, 2-space-indent JSON + trailing
  newline; identical inputs produce byte-identical manifests (no build
  timestamp on purpose). Strict parsing: unknown/missing keys or an
  unsupported schema version are rejected.
- **Fingerprint `ohlcv-fp-v1/sha256`**: SHA-256 over
  `b"eth-research ohlcv-fp-v1\n"` followed, for each candle of the
  *validated canonical frame* in chronological order, by one ASCII line
  `"<epoch-ns>|<open>|<high>|<low>|<close>|<volume>\n"` with floats rendered
  via `float.hex()` (negative zero normalized). Bit-exact,
  locale-independent, container-independent: equivalent CSV and Parquet
  inputs fingerprint identically while their `raw_file_sha256` differ.
- `sha256_file()` — streaming SHA-256 of the raw source bytes.

### 2.2 `data/quality.py` — offline audit (reports, never repairs)

- `QualityThresholds` (frozen): `extreme_return` (|close/close−1|, default
  0.25) and `extreme_range` ((high−low)/open, default 0.25). Thresholds are
  diagnostics only — findings never authorize modifying data.
- `QualityFinding` (frozen): `code`, `severity` (`error`/`warning`),
  exact `count`, `description`, up to 3 `first_examples`.
- `QualityReport` (frozen): schema version, row count, expected interval,
  thresholds, findings (sorted by code), error/warning counts,
  deterministic JSON serialization.
- `audit_frame()` checks, on the raw parsed frame:
  *errors* — duplicated column names, missing/unexpected columns
  (unexpected is a warning only when dropping is explicitly allowed),
  unparseable / timezone-naive (without opt-in) / missing timestamps,
  duplicate timestamps, out-of-order timestamps, missing candle intervals
  vs the identity interval, non-numeric values, missing (NaN) values,
  non-finite values, non-positive prices, negative volume, OHLC violations
  (high < max(open, close), low > min(open, close), high < low);
  *warnings* — zero-volume candles, longest consecutive zero-volume run,
  extreme close-to-close returns, suspicious candle ranges (outlier checks
  run only when no integrity errors exist, since they would be meaningless
  on broken data).

### 2.3 `data/builder.py` — deterministic canonical builder

- `build_canonical_dataset(source_path, identity, output_dir, ...)`:
  local CSV/Parquet only; URL-like sources rejected (offline by design);
  raw file opened read-only and never modified; audit first — **any
  error-severity finding refuses the build** (no sorting, filling,
  clipping, dropping, or repair, ever); then strict `validate_ohlcv`
  against the identity interval; fingerprint; write three artifacts:
  `<slug>.canonical.parquet`, `<slug>.quality.json`,
  `<slug>.manifest.json` (manifest last, as the completeness marker).
- Atomic writes: content goes to a `*.tmp` file in the target directory,
  fsynced, then `os.replace`d; failures unlink the temp file.
- Overwrite refusal: existing artifacts abort the build unless
  `overwrite=True` is passed explicitly.
- Artifacts live under the git-ignored `data/` directory by convention;
  tests use temporary directories; no dataset is ever committed.
- `audit_ohlcv_file()` — standalone audit of a raw file (for inspecting
  inputs the builder refuses).
- `load_canonical_dataset(manifest_path)` — verification-on-read: strict
  manifest parse, canonical Parquet re-validated, fingerprint recomputed
  and compared, row count and first/last open times cross-checked;
  any mismatch raises `DatasetVerificationError`.

### 2.4 Tests (focused)

- Fingerprint: single-value modification changes it; CSV vs Parquet
  equivalence; rebuild determinism (byte-identical manifest); canonical
  frame required.
- Ordering: unsorted input is refused (audited + build error), never
  repaired.
- Tampering: edited manifest fields, edited Parquet values, unknown
  manifest keys, wrong schema version — all detected on load.
- Quality: one dirty fixture per finding code with exact counts and first
  examples; thresholds respected; outliers skipped on broken data.
- Filesystem: raw file byte-identical after build; overwrite refusal;
  no temp files left behind; artifacts land only in the target directory.

### 2.5 Docs

- `docs/PLAN.md`: split the oversized Milestone 2 into 2A (this work),
  2B (acquire/freeze real ETH data, run untouched benchmarks), and later
  work (walk-forward, parameter grids, fractional weights, richer costs,
  new baselines, coverage threshold, CLI).
- README: short "canonical datasets" section.

## 3. Commit plan

1. `docs: Milestone 2A plan; split Milestone 2 into 2A/2B/later`
2. `Add dataset identity, manifest, and content fingerprint`
3. `Add offline OHLCV quality audit`
4. `Add deterministic canonical dataset builder with verification`
5. `Document the canonical dataset workflow`

Every commit keeps `pytest`, `ruff check`, `ruff format --check`, strict
`mypy`, and `uv lock --check` green in the frozen environment (no new
dependencies: hashing/serialization use the standard library; Parquet I/O
uses the existing pyarrow pin).

## 4. Non-goals (hard exclusions for 2A)

No real-data download, no strategies or backtest-engine changes, no
optimization/walk-forward/parameter grids, no fractional weights, no ML,
no live/paper trading, no wallets/exchanges/credentials/network clients,
and no committed market datasets.

## 5. Remediation record (same branch, pre-acceptance)

Review of the initial 2A implementation found five provenance/publication
defects, fixed in order:

1. **Unique software version** — the package moved to 0.2.0 (pyproject,
   `__version__`, `uv.lock` together); a test pins installed metadata to
   `__version__` so they cannot drift, and manifests can no longer claim
   the foreign `v0.1.0` tag's version.
2. **Genuinely strict manifests** — schema version 1 was extended in place
   (no released manifests existed): every field validates in the
   `DatasetManifest` constructor, the single shared path for built and
   parsed manifests. Exact JSON types (no `str(...)` repair), bool rejected
   where integers are required, locked `base_asset`/`market_type`/
   `timestamp_convention`, 64-lowercase-hex hashes, `sha256:<64 hex>`
   fingerprints, positive finite interval, ordered timezone-aware time
   bounds consistent with `first + (row_count − 1) × interval`, and safe
   basenames for all filenames. Adversarial tests cover every rejection.
3. **Audit evidence bound to the dataset** — the manifest now records
   `quality_report_filename`, `quality_report_sha256`, `assume_utc`, and
   `allow_extra_columns`; the quality report records the same flags and
   parses strictly; loading requires the report beside the manifest,
   verifies its exact SHA-256, parses it strictly, cross-checks row count,
   interval, and flags, and returns it in `LoadedDataset`.
4. **Raw hash bound to parsed bytes** — the source is read once into an
   immutable snapshot that is both hashed and parsed; the on-disk file is
   re-hashed just before publication and any mid-build change aborts with
   nothing written.
5. **Failure-safe publication** — all artifact bytes are precomputed;
   writes are atomic with the manifest last; any failure rolls back so a
   fresh build leaves no artifacts and a failed overwrite leaves the
   previous dataset byte-identical, with no temporary or backup files.
   Failure-injection tests cover each artifact on fresh and overwrite
   paths.
