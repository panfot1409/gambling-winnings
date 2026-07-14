# Milestone 3B — Findings (fractional execution-risk laboratory, run-001)

> **Research-only.** These are observations on historical data. They are **not**
> a profitability claim, **not** expected future returns, and **not** investment
> advice. No alpha is claimed and nothing was optimized. The engine described
> here cannot and does not move money: it has no network client, no exchange
> authentication, no wallet, no order routing, and no leverage or short path.

## 1. What was measured

One preregistered experiment — `m3b-fractional-execution-risk-v1-run-001` —
evaluated a **75-cell grid**: 5 fixed strategies × 3 cost scenarios × 5
rolling-origin out-of-sample folds, on the **research-train** partition only
(2016-05-23 … 2022-06-21 UTC, 2221 daily ETH candles). Each cell is an exact
fractional long-only cash/ETH backtest with:

- **causal next-open execution** — the target decided from data through
  `close[t-1]` fills at `open[t]`;
- **lagged liquidity** — the impact estimate uses only rows strictly before the
  fill bar (no same-bar volume);
- **deterministic partial fills** — a participation cap truncates an oversized
  order, and the remainder fills on later bars;
- **transparent cost decomposition** — fee, half-spread, base slippage, and a
  lagged-liquidity market-impact term, each reported separately;
- **exact cash/ETH accounting** — every bar's book re-derives from the previous
  bar plus its single fill, and the `Fill` ledger legs reconcile.

The five strategies are `cash`, `buy_and_hold`, `donchian_55_20`, and two
volatility-target overlays (`vol_target_buy_and_hold_30d_50pct`,
`vol_target_donchian_55_20_30d_50pct`). The three cost scenarios are
`compatibility_v1` (frictionless-parity with the Milestone 3A binary engine),
`causal_proxy_base`, and `causal_proxy_stressed`. All parameters and tolerances
were frozen in `research/m3b/fractional_protocol.json` and committed with green
CI **before** any research-train number was computed.

## 2. Honest findings

Over the research-train window — an ETH bull market bracketed by two drawdowns —
the fold-median marked total returns are:

| strategy | compatibility_v1 | causal_proxy_base | causal_proxy_stressed |
| --- | ---: | ---: | ---: |
| cash | +0.00% | +0.00% | +0.00% |
| buy_and_hold | +184.82% | +184.73% | +184.21% |
| donchian_55_20 | +43.53% | +43.32% | +42.01% |
| vol_target_buy_and_hold_30d_50pct | +123.64% | +123.41% | +121.87% |
| vol_target_donchian_55_20_30d_50pct | +44.33% | +44.16% | +42.99% |

1. **Buy-and-hold dominates median return but carries the deepest drawdown.**
   Its fold-median marked return is the highest of any strategy (~+185%), and its
   worst fold drawdown is also the deepest (~-79%). It never beats *itself* (the
   `> B&H` column is 0%), and it beats `cash` in the three bull folds (60%).
2. **The active strategies are shallower and mixed.** Donchian and both
   vol-target overlays post lower median returns with shallower worst-case
   drawdowns (e.g. `vol_target_donchian` bottoms at ~-22% vs buy-and-hold's
   ~-79%). Each beats buy-and-hold in a minority of folds (40%).
3. **Costs shrink net return monotonically in the modeled frictions.** For every
   non-cash strategy the fold-median marked return decreases from
   `compatibility_v1` → `causal_proxy_base` → `causal_proxy_stressed`. This is an
   *observation at the fold-median level*, not a pre-registered invariant: at the
   single-cell level a higher-cost scenario can occasionally end richer on a
   declining frame because it holds less ETH (documented in
   `docs/M3B_BUG_LOG.md`).
4. **The vol-target overlays trade far more and pay more.** Their median turnover
   is ~4–6× initial capital versus 1× for buy-and-hold and ~2.4× for Donchian, so
   they are the strategies most exposed to the cost scenarios.
5. **Losing folds are retained verbatim.** Folds 0 and 4 (ETH drawdown periods)
   are losses for every non-cash strategy and appear unchanged in the published
   grid; no cell was dropped for being unflattering.

`cash` is flat everywhere by construction (0 fills, 0% return, 0% exposure); its
`> B&H` value of 40% simply reflects the two folds where buy-and-hold lost.

## 3. What this is not

- **Not test performance.** The development gate (2022-06-22 … 2024-06-30) and
  the final holdout (2024-07-01 … 2026-07-11) were **never evaluated**. Both
  sealed access ledgers remain byte-empty
  (`sha256 = e3b0c442…855`); this run appended to neither.
- **Not calibrated costs.** The spread, slippage, and market-impact terms are
  transparent deterministic proxies driven by lagged dollar volume. They are
  **not** fit to any venue's fills and make no empirical-accuracy claim.
- **Not a significance test.** No bootstrap, no confidence interval, and no
  alpha-significance claim was computed. Five folds are weak in-sample evidence.
- **Not a promotion.** No candidate is advanced. The frozen protocol is a
  measurement instrument, not a selection procedure; nothing here was tuned after
  observing an output.

## 4. Compatibility parity

Under `compatibility_v1` the fractional engine reproduces the Milestone 3A binary
`run_backtest` **bit-for-bit** on the binary-equivalent strategies (`cash`,
`buy_and_hold`, `donchian_55_20`), proven by the compatibility oracle
(`tests/test_fractional_compatibility.py`) via a closed-form buy path and
un-clamped accounting. The small, monotone gaps between `compatibility_v1` and
the causal scenarios above are therefore attributable to the added
spread/slippage/impact terms alone.

## 5. Reproducibility

Every published number re-derives from the committed raw Coinbase bytes with no
networking:

- `research/m3b/fractional_results.json` — the strict, symmetric results (75
  reconciled fold cells + 15 re-derivable aggregates), both sealed-ledger event
  counts pinned at 0.
- `research/m3b/fractional_report.md` — the deterministic report, re-rendered
  byte-for-byte from the results.
- `research/m3b/experiments/run-001/manifest.json` — binds the artifact digests
  and the bundle digest to the two chained registry lines.
- `research/m3b/experiment_registry.jsonl` — the hash-chained
  `registered → started → completed` lifecycle; the `completed` event carries the
  artifact and bundle digests.

`python -m eth_research.fractional.replay --repo-root . --check` reconstructs the
research-train partition offline, re-runs the 75-cell experiment, and asserts the
results JSON and report reproduce exactly, then re-verifies the
registry/manifest/bundle chain. The `M3B Replay` CI runs this on CPython 3.12.3
and the 3.12/3.13 compatibility matrix. The check is dual-state, so the same CI
is green both before and after the run.

## 6. Limitations and honest caveats

- Five in-sample folds on a single bull-market regime are weak evidence; the
  active strategies' minority wins over buy-and-hold should not be read as skill.
- The cost proxies are directional and monotone by construction; their
  *magnitudes* are illustrative, not measured.
- Terminal marked equity and modeled terminal-liquidation equity differ only by
  the last-bar liquidation cost; neither is a claim about realizable value.
- The result stands or falls with the frozen protocol. It was computed once; a
  failed run is never re-run under the same id, and no parameter may be changed
  after observing this output.
