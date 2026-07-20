# V2B cross-asset research method (evaluation → nomination)

Preregistered **before any V2B result exists**. This documents the frozen scientific pipeline
that turns the two genuinely-new cross-asset candidate families into at most one nomination for an
*independent* development-gate review. No claim of edge, alpha, validation, out-of-sample evidence,
deployment readiness, or sell-ready status is made anywhere. The real research-train evaluation runs
**exactly once**, in the registered one-shot execution; everything below is machinery, unit-tested
on synthetic panels.

## Absolute scientific firewall

The only authorized performance-evaluation interval is the ETH/BTC research-train,
`2016-05-23T00:00:00Z … 2022-06-21T00:00:00Z` inclusive (2221 daily rows). The first *sealed*
timestamp is `WINDOW_END_EXCLUSIVE = 2022-06-22T00:00:00Z`. Every engine-visible timestamp — a bar
`open_time`, a bar `close_time`, a rebalance event, a mark — is strictly before it: each daily bar
opens at `00:00Z` and closes 23h later, so the greatest timestamp any component sees is
`2022-06-21T23:00:00Z`. The development gate, final holdout, M2B test, M3D prospective cohort, all
M3E machinery, and every post-cutoff observation are never read.

## The aligned partition (`eth_research.v2b.partition`)

ETH (via the accepted firewalled research-train loader) and BTC (via the re-derived canonical
dataset, with genesis↔audit equality re-proven) are aligned on their exact shared daily opens
(2221 rows) and every fingerprint recomputed. The builder takes only `repo_root`, so a caller can
never inject a fabricated frame — the partition is re-derived from committed bytes and the committed
`combined_partition_fingerprint` must reproduce byte-for-byte.

## Engine reuse (`eth_research.v2b.execution`)

The accepted **M4B** multi-asset portfolio engine is reused unmodified. Because its `PortfolioProtocol`
only expresses *static* reference policies, it runs the four passive benchmarks directly, but it
cannot execute a time-varying candidate target in one run. V2B therefore adds one thin per-event
execution basis that reuses the same M4B accounting convention — **trade at the bar opening at the
event, mark at that bar's close** — and reuses the M4B `CostParameters` turnover cost. The basis is a
*separate* vectorized computation proven faithful by a zero-cost reconciliation against
`run_portfolio_simulation` over the full per-event equity path of every benchmark (agreement at
machine epsilon, far inside the 1e-9 contract); under costs it applies the same linear turnover rate
rather than re-deriving the engine's, and any sqrt-impact scenario is refused (routed to the capacity
report) instead of silently under-charged. It is *not* a competing engine: the accepted engine is the
oracle.

## Causality (no look-ahead)

A candidate signal is decided from closes `≤ t` and, per its specification, executes at `open[t+1]`.
The execution basis trades the target it is handed at `open[t]`, so the *executed* path is the raw
signal shifted forward exactly one bar (`apply_latency(raw, 1)`): the target acted on at `open[t]`
depends only on closes strictly before that open. A metamorphic test proves it — perturbing only the
final bar's close changes no earlier executed weight or regime label. The benchmark (a constant
allocation, not a signal) is unshifted; the warm-up rows absorb the one-bar boundary.

## Benchmarks, costs, latency, capacity

- **Benchmarks** (`eth_research.v2b.execution`): cash, ETH buy-and-hold, BTC buy-and-hold, static
  50/50. The primary paired endpoint compares each candidate against **ETH buy-and-hold** — the
  single-asset passive the whole program has measured against since V2A, and the harder of the two
  single-asset holds over the research-train.
- **Cost scenarios** (`eth_research.v2b.scenarios`): five predeclared, contractive per-instrument
  proxy regimes reusing the accepted `CostParameters` — frictionless (reconciliation only), the
  `primary` (accepted `compatibility_v1`: 0.1% fee + 0.05% slippage), a `stressed` regime, and two
  liquidity-impact proxies. The nomination reads `primary` and `stressed`.
- **Latency**: the baseline is already causal (a `t+1`-open execution); a `delayed_one_bar` stress
  adds a further bar of execution delay.
- **Capacity**: causal participation from the *lagged* binding-leg dollar volume of the ETH/BTC pair
  — reported, never silently ignored.

## Walk-forward folds and causal regimes

- **Folds** (`eth_research.v2b.folds`): a 150-bar warm-up (longer than the longest candidate
  lookback) is excluded; the remaining window is split into 6 contiguous, disjoint out-of-sample
  folds. Folds *stratify* the bootstrap so a single lucky regime cannot carry a candidate.
- **Regimes** (`eth_research.v2b.regimes`): a causal BTC trailing-trend label (from `close[t-1]` vs
  its lagged SMA) and a per-regime paired-mean diagnostic — context only, never a gate.

## Sensitivity, bootstrap, Monte-Carlo, multiplicity

- **Sensitivity** (`eth_research.v2b.sensitivity`): a frozen neighborhood of nearby parameter tuples,
  *scored not searched*. A candidate whose edge evaporates one notch away is fragile, not robust.
- **Bootstrap** (reused `eth_research.m3c.statistics`): the fold-stratified moving-block bootstrap
  of the pooled mean paired log-excess, at the fixed 95% interval.
- **Corrected tail + Monte-Carlo** (`eth_research.v2b.statistics`): a bootstrap that *replicates the
  accepted resampling exactly* (proven to reproduce the accepted 95% bounds bit-for-bit) and adds
  the family-wise-corrected one-sided lower bound the multiplicity policy requires, plus a seeded
  **block**-sign-flip permutation p-value — the flip unit is a `floor(n**(1/3))` block within a fold
  (not a whole fold), so it keeps the full-sample resolution to meet the corrected α while preserving
  the within-block autocorrelation the bootstrap respects, and its observed statistic is computed by
  the same reduction as the permutations (no anti-conservative last-ULP dropout).
- **Multiplicity** (`eth_research.v2b.multiplicity`): the cumulative family-wise correction over all
  prior families (M3A/M3B/M3C/V2A) plus V2B — corrected per-family α = `0.05 / total_family_count`.

## Nomination rule (`eth_research.v2b.nomination`)

At most one candidate is nominated, and only if it clears **every** pre-registered gate:

1. primary paired 95% lower bound > 0;
2. stressed-cost 95% lower bound > 0;
3. latency-stressed 95% lower bound > 0;
4. a strict majority of out-of-sample folds beat the benchmark;
5. **the family-wise-corrected one-sided lower bound > 0** (the multiplicity gate);
6. the Monte-Carlo sign-flip p-value ≤ the corrected per-family α;
7. every frozen parameter-neighborhood tuple keeps a primary 95% lower bound > 0.

Among eligible candidates the highest primary point estimate is nominated; an exact tie nominates
none. Nomination forwards a candidate to an **independent** development-gate review — it is not
validation, forward evidence, deployment readiness, capacity, or a performance claim.
