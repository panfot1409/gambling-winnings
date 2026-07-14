# Milestone 3B — Fractional Long-Only Accounting & Causal Execution-Risk Lab

Research-only. M3B builds a **trustworthy next-generation research engine** for
exact fractional long-only ETH allocation with causal next-open execution,
deterministic partial fills, lagged-liquidity estimation, transparent cost
decomposition, strict risk overlays, and immutable preregistered records. It is
stacked on the M3A merge-readiness branch (PR #4) and **touches research-train
data only** (2016-05-23 .. 2022-06-21 UTC, 2221 daily rows).

**The goal is not to find a profitable strategy.** It is to build an engine whose
every number is causal, reconciled, and reproducible, and to publish one honest
research-train experiment through it.

This project has **daily OHLCV candles, not quotes or an order book**. Therefore
spread and slippage are *scenario inputs* and volume-based impact is a
*deterministic causal proxy*. No exchange-level execution fidelity is claimed,
and there is **no path that can move money** (no network client, wallet, signing,
auth, leverage, shorting, or live/paper trading).

## Separated concerns (no layer may reach across the timeline)

1. **Signal generation** — a raw target weight in `[0,1]` from strategy state.
2. **Risk transformation** — max-exposure → volatility target → drawdown breaker
   → turnover limiter, each a pure function of state through the prior close.
3. **Execution scheduling** — a single fill at the next open.
4. **Liquidity estimation** — lagged daily dollar volume (rows through `t-1`).
5. **Target-weight solving** — the quantity that reaches the executable target
   subject to cash / inventory / participation / cost constraints.
6. **Fill accounting** — directional fill price + fee → exact cash/ETH update.
7. **Mark-to-market** — equity marked at `close[t]`.
8. **Liquidation reference** — a *hypothetical* cost-inclusive terminal
   liquidation value, never an actual fill.
9. **Metrics** — reconciled against the primitive bar/fill records.
10. **Reporting** — separated views, ruthless failure disclosure.

## Strict information timeline (for evaluated bar `t`)

At/before `close[t-1]` the system may know: OHLCV through `t-1`; strategy state
through `t-1`; equity through `close[t-1]`; lagged liquidity from rows through
`t-1`; risk-control state through `t-1`.

At `open[t]` it may additionally know: `open[t]` — used **solely** as the
execution reference price.

Before the fill it may **not** know: `high[t]`, `low[t]`, `close[t]`,
`volume[t]`, bar `t`'s return, or any later row.

After execution at `open[t]`: the position holds; equity is marked at `close[t]`;
`high[t]`/`low[t]`/`close[t]`/`volume[t]` may affect only **future** decisions,
never the already-completed fill.

## Daily-candle honesty

- fixed spread → a scenario input;
- slippage → a scenario input;
- volume impact → a deterministic proxy of participation vs lagged liquidity;
- participation uses **lagged** daily liquidity (rows through `t-1`);
- language is "deterministic causal liquidity-and-impact research proxy", never
  "realistic Coinbase fill model".

## Package boundary (Phase 3)

Version → `0.5.0`. The existing binary engine (`backtest.run_backtest`) is
**unchanged**; M3B adds a *parallel* fractional interface under
`src/eth_research/fractional/`. No M1/M2/M3A semantics change silently.

## Integrity-only loader (Phase 4)

M3B introduces `verify_dataset_integrity_only(...)` distinct from
`reproduce_historical_research_artifacts(...)`. M3B loading verifies raw/plan/
receipt/evidence/lock/manifest/quality/fingerprints/bounds/dossier anchors,
derives the M3A partition mechanically, and exposes research-train rows only —
**without** ever re-running the M2B train/validation benchmark (the disclosed
M3A `4.1-1` behavior), and without calling any strategy/engine/metric/bootstrap/
report during verification.

## Preregistered experiment (Phases 14–19)

`m3b-fractional-execution-risk-v1-run-001`: **5 strategies × 3 cost scenarios ×
5 research-train OOS folds = 75 fold cells**. Strategies: `cash`,
`buy_and_hold`, `donchian_55_20`, `vol_target_buy_and_hold_30d_50pct`,
`vol_target_donchian_55_20_30d_50pct`. No bootstrap, no alpha-significance claim,
no scenario/cell omitted for being ugly. One execution only; single-use id;
failed ids are never rerun.

## Test discipline

Focused tests during development; full suite only at baseline, pre-registration
freeze (E), and final head. Hand-calculated + metamorphic tests over duplicate
implementations. Every defect: failing reproduction → root cause → minimal fix →
regression test → `docs/M3B_BUG_LOG.md`.

## Hard stops

See `docs/M3B_THREAT_MODEL.md` and the milestone's hard-stop list: any sealed
ledger byte change; any gate/holdout row reaching a computational surface; any
immutable M2B/M3A artifact or registry change; compatibility disagreement without
a fully explained convention difference; negative cash / negative ETH / exposure
> 1 / same-day volume in a fill / future volatility in a target / cost
non-reconciliation / a cost increase improving a fixed order path; a real result
computed before registration; E→R more than one append; source/protocol change
after registration; unrecoverable post-`started` failure; replay divergence; red
CI; any live/wallet/auth/leverage/short functionality.

## Explicit non-goals

No profitability/alpha claim; no gate/holdout evaluation; no optimization/grid/
Bayesian/ML; no config selection after seeing output; no live/paper trading,
exchange auth, API keys, wallet, signing, order routing, leverage, borrowing,
margin, shorting, derivatives, or fractional shorts; no network client in the
package; no merge/undraft/retarget of either PR; no tag; no history rewrite.
