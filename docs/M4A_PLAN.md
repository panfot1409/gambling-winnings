# Milestone 4A — Offline Research Platform 1.0 Release Candidate — Plan

## Motivation

The accepted internal ETH research repository (M2B–M3F) is a correct, governed,
byte-reproducible research stack, but it is not yet a *product*. Everything is wired
to the accepted real-data partitions, the internal governance CLIs, and the
repository layout. Milestone 4A turns that stack into a trustworthy, installable,
documented **offline research platform** that an external technically-competent user
can `pip install` and use on *their own* local OHLCV files — without ever touching a
network, an exchange, a wallet, or any private accepted-research byte.

M4A adds a deliberate public boundary *over* the accepted engines; it does not change
the accepted numerical/causal contracts, does not rerun accepted experiments, and does
not expose sealed-governance operations as ordinary commands.

## Scope (in)

- A small, intentional, strictly-typed **public API** under `eth_research.api`.
- A coherent single offline **CLI** `eth-research`.
- Strict versioned **configuration**, **result**, and **run-receipt** schemas.
- A **public error taxonomy** with stable machine-readable codes and CLI exit codes.
- A deterministic **synthetic** quickstart (no external data, no network).
- **Private-data-safe** wheel + sdist with an explicit inclusion allowlist and a scanner.
- **Reproducible** double-build wheel/sdist tooling and a distribution manifest.
- An **installed-wheel consumer** E2E test (out-of-tree, non-editable).
- Public **strategy protocol** (in-process, no plugin loader).
- **Causality/accounting compatibility** proofs vs the accepted engines.
- v1 **documentation** set + generated CLI reference + doc/example tests.
- Read-only **CI** (`m4a-release-candidate.yml`), SHA-pinned, `contents: read`.
- Version bump to **1.0.0**.
- New governed root `research/m4a/` for deterministic RC artifacts.

## Non-goals / hard exclusions

No exchange auth, wallets, signing, order routing, live/paper trading, leverage,
shorting, margin, derivatives; no general network client in the package; no optimizer,
grid, Bayesian/genetic search, or ML; no new research strategy; no packaging/upload of
private raw Coinbase bytes or any recovery capsule; no M3E activation; no production
proposal; no development-gate/final-holdout access; no sealed-ledger append; no PyPI
publish; no tag; no GitHub Release; no branch delete; no history rewrite; no M4B.

## Public API design (`src/eth_research/api/`)

Thin, strictly-typed adapters that **delegate** to the accepted engines (no formula
reimplementation). Modules: `errors`, `models`, `dataset`, `strategies`, `backtest`,
`results`, `receipt`, `serialization`, `config`, `__init__` (allowlisted re-exports).

Public models (frozen dataclasses, canonical-JSON serializable):
`DatasetSpec`, `ValidatedDataset`, `CanonicalDataset`, `ChronologicalSplitSpec`,
`CostSpec`, `BinaryBacktestSpec`, `FractionalBacktestSpec`, `StrategySpec`,
`ResearchRunSpec`, `ResearchResult`, `RunReceipt`, `ValidationFinding`,
`ValidationReport`.

Public functions (delegating to accepted internals):
- `validate_dataset` → `data.schema.validate_ohlcv` + `data.quality`
- `build_canonical_dataset` / `load_canonical_dataset` → `data.builder` / `data.load`
- `chronological_split` → `splits.chronological_split`
- `run_binary_backtest` → `backtest.run_backtest` (BuyAndHold/Cash/MA-crossover/Donchian)
- `run_fractional_backtest` → `fractional.engine.run_fractional_backtest` + `build_strategies`
- `calculate_metrics` → `metrics.summarize`
- `generate_synthetic_dataset` → `data.synthetic.make_synthetic_ohlcv`
- `verify_run_receipt`

Invariants: full strict typing; `py.typed` shipped; no implicit network; no global
mutable config; no env-var credentials; no exchange/order/wallet concepts; no hidden
writes; no default use of accepted M2B/M3D data; no dynamic strategy import from paths;
no `eval`/`exec`/entry-point plugin loading; results immutable; every public symbol has
an honest docstring; public models serialize through strict canonical schemas; parse and
direct-construction share invariants. Snapshot: `research/m4a/public_api.json` + a
`--check` drift guard (`eth_research.m4a.public_api`).

## CLI design (`eth-research`, `src/eth_research/cli/` + `eth_research.m4a`... )

Console entry point in `pyproject.toml`. Command families:
`version`, `doctor`, `demo generate`, `dataset validate|build|inspect`,
`backtest run`, `result verify`, `receipt verify`.
Every command: concise human output + `--json` deterministic machine output + `--help`
+ stable exit codes; no ANSI when non-TTY; no interactive prompt; overwrite refusal by
default; explicit output path; safe atomic writes; no network/telemetry/analytics/home
state/credential lookup; no mutation outside the requested output dir. Internal
governance CLIs (m3*/fractional) remain under their module mains, not exposed as
end-user commands. `backtest run` refuses any `research/m2b|m3a|m3b|m3c|m3d|m3e|m3f`
path, known governed artifacts, sealed-holdout fingerprints, URLs, and dynamic code.

## Package / distribution design

hatchling; **explicit inclusion allowlist** (`force-include`/`packages` + `sdist`
`include`) so the wheel and sdist contain only `eth_research` runtime source + `py.typed`
+ intentional metadata. `research/**`, `.git`, caches, `.env`, tests, tools excluded.
Reproducible: `SOURCE_DATE_EPOCH` derived from the source-freeze commit; sorted members;
normalized timestamps/permissions; locked build backend (`hatchling==1.31.0`); double
build byte-identical on Linux; refuse dirty/untracked/version-drift. `release` module:
`build --check`, `verify-dist <dir>`. Manifest: `research/m4a/distribution_manifest.json`
(no binaries committed). Scanner opens wheel+sdist and enforces member allowlist, safe
paths, no symlinks, no case-collisions, no private roots, no accepted-artifact hashes,
no raw-Coinbase signatures, no ledger names, no absolute paths, no secrets, expected
metadata/entry-point/`py.typed`/pure-python tag.

## Config schema (strict, versioned)

JSON/TOML strict (no YAML). Keys: `config_schema_version`, `dataset`, `strategy`,
`engine`, `costs`, `split`, `output`, `reproducibility`. Exact keys; no unknown values;
no string→number repair; bool≠int; finite only; safe paths; explicit tz/interval/cost
scenario/initial cash/engine kind/strategy kind+fixed params; overwrite default false;
no URL/credentials/shell/module path/code ref/accepted-research path/gate/holdout path/
implicit-latest/clock defaults; deterministic canonical JSON. Examples under
`examples/configs/` (synthetic/placeholder only). Adversarial tests per §8 list.

## Result + deterministic run-receipt

`ResearchResult` (immutable, canonical). `RunReceipt` binds: receipt schema version,
package version, public API version, config SHA-256, canonical dataset fingerprint,
dataset manifest SHA-256 (if any), strategy identity+fixed params, engine identity, cost
identity, split identity, output result SHA-256, report SHA-256 (if any), source-tree or
distribution identity, Python impl/version, numeric dependency versions, deterministic
run id from immutable inputs. Excludes credentials/wallets/keys/full paths/hostname/user/
IP/wall-clock identity/env dumps/command strings. Generated only after result bytes are
finalized and read back; published transactionally with the bundle. Tampering tests per
field + cross-field.

## Transactional publication

One reviewed publisher for multi-file CLI output (`result.json`, `report.md`,
`receipt.json`, `manifest.json`): precompute+validate all bytes; refuse collisions;
reject symlink/traversal; temp files in final dir; flush+fsync; deterministic replace;
completeness marker last; fsync dir; read back + verify; reverse rollback on any failure;
restore overwritten bytes; no residue; never partial success; receipt-fail ⇒ roll back
whole bundle. Do not reuse a research experiment ledger for user runs. Failure-inject
every position.

## Error taxonomy

`EthResearchError` → `ConfigurationError`, `DatasetError`(`DatasetSchemaError`,
`DatasetIntegrityError`), `StrategyError`, `BacktestError`(`AccountingError`,
`CausalityError`), `ResultValidationError`, `ReceiptVerificationError`,
`OutputCollisionError`. Stable codes; `__cause__` preserved; messages never dump data or
user paths into canonical artifacts; input vs internal distinguished; no broad
`except Exception` turning bugs into user errors; CLI exit codes deterministic per class.

## Strategy contract

Typed in-process protocol only; CLI accepts only schema-enumerated built-in ids; custom
Python strategies are Python-API-only and are *trusted caller code* (documented, not
sandboxed). Built-ins wrap accepted strategies unchanged; scalar oracles + contract tests.

## Causality/accounting compatibility

Public adapters produce byte/❨scalar❩-identical results to the internal engines on shared
synthetic fixtures. Pin: UTC open times; target through close[t−1]; execute at open[t];
ex-ante initial target; context strictly predates + zero P&L; fees+directional slippage;
fractional long-only [0,1]; no leverage/shorting; cash/qty/equity reconciliation; terminal
MTM; separate hypothetical liquidation; turnover/fill defs; metric/annualization/drawdown.
No accepted real segment enters these tests.

## Documentation plan

`docs/V1_RELEASE_CANDIDATE_PLAN.md`, `INSTALLATION`, `QUICKSTART`, `PUBLIC_API`,
`CLI_REFERENCE`, `DATA_CONTRACT`, `EXECUTION_MODEL`, `COST_MODEL`, `METRICS`,
`REPRODUCIBILITY`, `SECURITY_MODEL`, `CUSTOM_STRATEGIES`, `RESULT_AND_RECEIPT_SCHEMAS`,
`PACKAGING_AND_PRIVACY`, `VERSIONING_AND_COMPATIBILITY`, `MIGRATION_TO_V1`,
`V1_LIMITATIONS`, `M4A_BUG_LOG`, `M4A_FINDINGS`, `M4A_TERMINAL_AUDIT`,
`research/m4a/README.md`; update root README + roadmap. Generated CLI reference
(`research/m4a/cli_reference.txt`) with `--check`. Doc/example tests execute every shown
command in a temp dir with no network; installed-wheel where applicable.

## Build reproducibility plan

Double-build byte-identity on Linux authoritative (3.12.3) + compat (3.12, 3.13);
semantic identity on macOS/Windows if claimed. `distribution_manifest.json` +
`distribution_dependencies.json`. Never upload artifacts; delete CI-local dist after
verify.

## Consumer-project tests

Out-of-tree disposable project: build wheel → fresh venv → locked deps → non-editable
install → repo root off `sys.path`, cwd outside repo → import installed pkg only →
`version`/`doctor`/`demo generate`/`dataset validate`/`dataset build`/`backtest run`/
`result verify`/`receipt verify` → re-run byte-identical → overwrite refusal + explicit
overwrite transactional → assert no network, no home writes, no repo research read, no
sealed fingerprint accepted, no ledger change, no proposal. Typed consumer + mypy vs
installed pkg (proves `py.typed`). sdist smoke in a second disposable env.

## Cross-platform CI

`m4a-release-candidate.yml`: `authoritative-build`, `compatibility-build` (3.12/3.13),
`platform-smoke` (ubuntu/macos/windows if available — prove only what passes),
`distribution-security`, `release-candidate-state`. All actions full-SHA pinned;
`contents: read`; no upload/publish/release/tag/push/secret/market-host.

## Performance discipline

Deterministic synthetic benchmarks (10k/100k validation, fingerprinting, both engines,
serialization, receipt verify) recorded as diagnostics only (not immutable). Broad
regression budgets to catch catastrophic complexity; no quadratic; bounded input/output;
finite subprocess timeouts; slowest tests identified at audit.

## Security / threat model

Extend the repo scanner over src/tests/examples/tools/build hooks/workflows: fail on
network libs/sockets/exchange SDKs/wallet-signing/web3/dynamic-plugin-import/eval/exec/
shell/unreviewed subprocess/credential-keyring/browser/order-trade-executable/leverage-
short-margin/optimizer-ML/publish/release/tag/branch-delete/write-workflow/dist-or-private
upload. Build backend's own locked behavior is allowed (build tooling ≠ runtime capability).

## Red-team plan

Three independent pre-freeze auditors (A: API+numerical, B: packaging+supply-chain,
C: CLI/security/publication). Reproduce-first; classify A/B/C/D; Class D = hard stop;
fix A/B/C failing-test-first (A that would change accepted financial artifacts = hard stop).

## Source-freeze sequence (E/R/P/Q)

E = source freeze (all code/tests/docs/CI final, full suite green, artifacts unchanged,
snapshots stable, dist reproducible, consumer E2E green, version 1.0.0). R = deterministic
RC artifacts only (`public_api.json`, `cli_reference.*`, `distribution_manifest.json`,
`distribution_dependencies.json`, `release_candidate_state.json`); E..R changes no
executable source. P = installed-distribution proof (`distribution_proof.json`; double
build, consumer E2E, matrices, no private bytes, no import contamination). Q = post-proof
audit + terminal docs; superseded-E discipline if source changes after E.

## Commit plan (append-only, roughly one concern per commit)

1 plan · 2 version 1.0.0 · 3 api errors+models+serialization · 4 api dataset+strategies ·
5 api backtest+results+receipt · 6 config schema · 7 transactional publisher ·
8 CLI (version/doctor/demo) · 9 CLI (dataset/backtest/result/receipt) ·
10 packaging allowlist + dist scanner · 11 release build/verify tooling ·
12 consumer E2E + sdist smoke · 13 public_api snapshot+check · 14 cli_reference gen+check ·
15 compatibility policy + deprecation · 16 docs set · 17 doc/example tests ·
18 perf/logging/security scanner extensions · 19 misuse + cross-platform path tests ·
20 m4a-release-candidate.yml · 21 bug-log/findings · E freeze · R register · P proof ·
Q terminal audit. (Grouped/split as the work actually lands.)

## Terminal acceptance criteria

Full local battery green; both engines compatibility-identical; wheel+sdist double-build
byte-identical (Linux); consumer E2E green; private-data scan clean; snapshots `--check`
clean; accepted artifacts byte-unchanged; ledgers byte-empty before/after; M3C rejected;
M3D 3/365 unauthorized; M3E inactive/0 proposals; all M4A CI green; draft stacked PR open
(base M3F branch), unmerged, unretargeted; no tag/release/publish.

## Hard stops

Per §37 of the milestone spec (sealed access, artifact drift, M3C/M3D/M3E state change,
production proposal, gate/holdout access, private-byte packaging, dist upload, write
workflow, secret/force-push requirement, accepted-financial-artifact change, unexpected
network/wallet/exchange/optimizer capability, Class D red-team finding).

## Absolute final stop

Open the draft stacked PR, verify final CI, write the terminal audit, and stop. Do not
merge/undraft/retarget/tag/release/publish/delete/rewrite; leave M3C/M3D/M3E and the three
sealed ledgers exactly as accepted; begin no M4B.
