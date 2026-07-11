# Milestone 1 Correctness Remediation — Plan

_2026-07-11. Scope: fix Milestone 1 defects only. No Milestone 2 work, no
history rewrite, no parameter optimization, no ML, and no network, exchange,
wallet, leverage, shorting, or live-trading functionality._

## Defects found on inspection

| # | Defect (as shipped) | Correct behaviour required |
|---|---|---|
| D1 | Fills implied at the **decision bar's close** (close-to-close returns with a shifted position series); open prices never used | Decide from data through `close[t-1]`, fill at `open[t]` with directional slippage, mark equity at `close[t]` |
| D2 | Costs approximated in **returns space** (`turnover × rate` subtracted from returns); no cash/quantity state, no ledger | Deterministic bar-by-bar accounting: cash, ETH quantity, slipped fill price, fee on notional, immutable fill ledger, `equity = cash + qty × close` |
| D3 | Engine advertised fractional positions `[0, 1]` without exact fractional rebalancing | Restrict targets to binary `{0, 1}` (long/cash) and enforce it |
| D4 | Buy-and-hold entry timing implicit (first close via shift) | Explicit, tested ex-ante rule: enters at the **first available open** via `initial_target = 1` |
| D5 | Validation **silently sorted** unsorted data; naive timestamps silently assumed UTC; gaps/irregular spacing accepted | Reject unsorted; naive timestamps raise unless `assume_utc=True`; regular interval required (given or inferred only when all intervals agree); gaps rejected, never filled |
| D6 | Candle timestamp semantics undocumented | Document: timestamp = candle **open time**, candle spans `[t, t+interval)` |
| D7 | CAGR from `len(returns) / median-inferred frequency`; Sharpe/Sortino annualized from median spacing; synthetic `r_0 = 0` prepended | Metrics from the reconciled equity curve; CAGR from recorded start/end times; annualization only from the validated regular interval or an explicit setting; bar 0's return is real (cash committed at `open[0]`) |
| D8 | Metrics tolerated any equity path | Reject non-positive/non-finite equity |
| D9 | No warm-up context: every segment restarted indicators flat | Validation may use trailing train rows, test may use trailing train+validation rows, as signal context only — zero P&L contribution; signal from final context close may fill at first evaluation open |
| D10 | Turnover in position units (`Σ|Δpos|`), trade count from position deltas | Turnover from actual traded notional with a documented formula; trade count = executed fills |
| D11 | Terminal position policy documented but untested; no liquidation figure | Mark-to-market policy tested; hypothetical liquidation value reported |
| D12 | No CI, no dependency lock | GitHub Actions (3.12 + 3.13) running pytest, ruff check, ruff format --check, strict mypy incl. examples, installing from a frozen constraints file |

## Corrective commits (in order)

1. **Strict OHLCV validation** — rewrite `data/schema.py` + `data/load.py`
   (reject unsorted, naive opt-in, interval regularity/gap rejection,
   candle-open-time doc); rewrite `tests/test_schema.py`, `tests/test_load.py`.
2. **Binary strategy contract** — `strategies/`: targets restricted to
   `{0, 1}`; add ex-ante `initial_target` (buy-and-hold = 1); update
   `tests/test_strategies.py`.
3. **Portfolio engine + equity-based metrics** — rewrite `backtest.py`
   (open fills, directional slippage, fee on notional, cash/qty state,
   immutable `Fill` ledger, invariants, terminal policy) and `metrics.py`
   (equity-curve metrics, recorded start/end CAGR, interval-based
   annualization, equity validation). These move together because the
   metrics consume the result type. Hand-calculated ledger tests.
4. **Warm-up context** — engine `context=` parameter; `DataSplits`
   context helpers + `boundaries()`; `tests/test_context.py` proving
   carry-in and zero P&L leakage.
5. **Causality regression tests** — overnight-gap non-capture, same-bar
   fill prohibition, engine prefix invariance, future-mutation invariance,
   sawtooth perfect-foresight bound.
6. **Docs** — README + PLAN updated to the corrected conventions; example
   reports split boundaries and terminal policy.
7. **CI + lock** — `.github/workflows/ci.yml`, `constraints.txt`.

## Acceptance

Every commit keeps `pytest`, `ruff check .`, `ruff format --check .`, and
strict `mypy` green. Final audit re-runs all gates and reports unabridged
output.
