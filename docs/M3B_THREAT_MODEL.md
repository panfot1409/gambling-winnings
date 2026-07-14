# M3B Threat Model

M3B is a research engine that must be **incapable of moving money** and must
never let a sealed-partition value influence any computation. This document
enumerates the boundaries, the attack surfaces, and the hard stops.

## Sealed partitions (never reach a computational surface)

| partition | dates (UTC) | rows | status |
| --- | --- | --- | --- |
| research train | 2016-05-23 .. 2022-06-21 | 2221 | **permitted** (this milestone) |
| development gate | 2022-06-22 .. 2024-06-30 | 740 | sealed |
| final holdout | 2024-07-01 .. 2026-07-11 | 741 | sealed |

Forbidden-partition market values must never reach a strategy, execution engine,
cost model, risk overlay, liquidity estimator, metric, bootstrap, report, or
descriptive-statistics routine. Integrity-only handling (bytes, hashes, schema,
counts, interval regularity, time bounds, opaque fingerprints) is permitted on
the complete dataset. Both access ledgers
(`research/m3a/development_gate_access.jsonl`,
`research/m2b/test_evaluations.jsonl`) stay **byte-empty** throughout.

The M3B loader is `verify_dataset_integrity_only(...)`, explicitly **not**
`reproduce_historical_research_artifacts(...)` — M3B loading never re-runs the
M2B train/validation benchmark (the disclosed M3A `4.1-1` behaviour) and never
calls a strategy/engine/metric/bootstrap/report while verifying. Poison spies on
those callbacks must remain unfired during integrity-only loading.

## Prohibited functionality (proven absent by AST + tree tests)

No `requests`/`httpx`/`aiohttp`/`urllib`/`socket`/`websocket`/`ccxt`/Coinbase
SDK/`web3`/`eth_account` imports; no wallet/MetaMask; no signing; no private-key
or mnemonic handling; no exchange credentials/API keys/secrets/`.env`/PEM; no
order placement/routing; no live or paper mode; no leverage/borrowing/margin/
shorting/derivatives/fractional-shorts; no ML; no optimizer/grid/Bayesian search;
no config selection after observing output; no network client in the package; no
tracked CSV/Parquet market-data; no symlinked research artifacts.

## Causality attack surface (Phase 13 + 22)

Future close/open/volume mutation; current-bar high/low/close/volume before the
fill; centered windows; backward fill; full-sample normalization; same-bar
volatility/liquidity/drawdown; risk state leaking across folds; context including
an OOS/gate/holdout bar; target from full data then sliced; volume estimate
before the shift; solver using the final bar's volume. Invariant: **the maximum
timestamp reaching any computational surface at the fill of bar `t` is `<=`
`open[t]` for the reference price and `<= t-1` for every estimate.**

## Accounting attack surface

Negative cash; negative ETH; achieved exposure > 1; buy creating cash; sell
creating ETH; partial fill treated as full; achieved substituted for requested
(or vice versa) in reporting/P&L; fee double-counted; spread/slippage/impact
overlap; negative-zero; float overflow; hidden target error; a cost increase
improving a fixed order path; costs decreasing as size increases; dust retained
at target 0 without disclosure; tiny-rebalance float-noise trades.

## Registry / publication / recovery / replay attack surface

Altered registration; reordered event; broken previous-hash; missing/extra
archive file; alias mismatch; output symlink; path traversal; tampered/duplicate
completion intent; repeated finalization; rerun of a consumed id; recovery that
touches calculation; fresh/shallow clone; path with spaces; absent ignored files;
3.13 runtime; one raw/protocol/evidence/result byte changed; a ledger byte
appended. Every attack must fail for its intended reason.

## Hard stops (stop and report; never conceal with a tolerance/rerun/doc edit)

PR #4 changes; the M3A branch moves due to this work; either sealed ledger
changes by a byte; a gate/holdout row reaches a computational surface; an
immutable M2B/M3A artifact or the M3A registry changes; old vs new engine
disagree in compatibility mode without a fully explained convention difference;
materially negative cash; negative ETH; achieved exposure > 1; same-day volume in
a fill; future volatility in a target; costs that do not reconcile; a cost
increase improving a fixed order path; a real M3B result computed before
registration; `E→R` with more than one registry append; source/protocol change
after registration; a post-`started` failure that cannot be calculation-free
recovered; a post-run defect that changes financial bytes; replay divergence
across authoritative runs; final CI red; any live/wallet/auth/leverage/short
functionality appearing.

Governance/docs-only fixes may be applied forward if the financial bytes remain
valid; a financial-output defect is a hard stop that leaves the PR draft for
independent review and never reuses the run-001 id.
