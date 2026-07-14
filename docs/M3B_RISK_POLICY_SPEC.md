# M3B Risk-Policy & Liquidity Specification

All policies are pure, deterministic, and **causal** — every estimate at the
execution open of bar `t` uses only rows/returns/state through `close[t-1]`.
Each records a full trace (pre- and post- values, activation flags, reasons); no
silent mutation. Undefined ratios serialize as `null`.

## Causal liquidity estimator (Phase 7)

At open `t`, using only candles through `t-1`:

    lookback bars       = 30
    min_observations    = 30
    daily_dollar_volume = close * volume        (per bar, rows <= t-1 only)
    statistic           = median of the last `lookback` lagged daily dollar volumes
    base_volume_stat    = median of the last `lookback` lagged daily base volumes

Records: as-of timestamp (open `t`), oldest & newest contributing timestamp
(both `<= t-1`), observation count, `base_volume_stat`, `dollar_volume_stat`,
`sufficient` flag, and a typed reason if unavailable. **Current-bar volume and
current-bar close are forbidden inputs.** No change at or after `t` may alter the
estimate used at open `t` (prefix-invariance + future-mutation tests are
mandatory). Zero-volume runs, NaN/inf volume, irregular/unsorted timestamps,
insufficient warm-up, and single extreme outliers are each attacked and handled.

## Fixed policy order (frozen)

    raw strategy target
      → maximum exposure
      → volatility target        (if enabled)
      → drawdown breaker         (if enabled)
      → turnover limiter
      → execution solver

The trace retains **every** intermediate value.

### Maximum exposure

Exact cap `m in [0, 1]`: `post = min(pre, m)`. Records pre/post; no silent
mutation. For the real experiment, `m = 1.0` for all strategies.

### Volatility target (frozen for the real experiment)

    lookback            = 30 daily returns
    min_observations    = 30
    return type         = simple close-to-close
    std                 = sample std, ddof = 1
    annualization       = sqrt(365.25)
    annual_vol_target   = 0.50
    vol_denominator_floor = 0.10
    max_target_weight   = 1.0
    min_target_weight   = 0.0

    estimated_vol   = std(simple_returns[-30:], ddof=1) * sqrt(365.25)
    volatility_scale = min(1.0, 0.50 / max(estimated_vol, 0.10))
    adjusted_target  = clip(raw_target * volatility_scale, 0.0, 1.0)

The returns end no later than `close[t-1]`. Before 30 observations exist:
`adjusted_target = 0`, reason `insufficient_volatility_history`. No backfill from
future data. Reported separately from **realized** volatility — requesting a
volatility target never implies it was achieved.

### Turnover limiter (frozen)

    max_abs_weight_change_per_bar = 0.25

Applied **after** volatility targeting. The reference is the **prior achieved
exposure** (partial fills matter), fixed here before any results:

    delta   = target_in - prior_achieved_exposure
    target_out = prior_achieved_exposure + clip(delta, -0.25, +0.25)

Records input target, prior achieved exposure, cap, output target, activation.

### Drawdown circuit breaker (built + tested; DISABLED in the real experiment)

Stateful, causal. On the decision **after** equity draws down past the threshold
from its running peak (using equity through `close[t-1]` only), forces target `0`
until a cooldown elapses and recovery is observed. Reset per fold. Tests:
threshold crossing, next-decision activation, cooldown, recovery, no future
equity access, fold reset, prefix invariance, no gate/holdout access. Its
existence is infrastructure, **not** evidence that its parameters improve
returns; it is not enabled for run-001.

## Real-experiment strategy configurations

| id | raw strategy | max exposure | vol target | turnover limit | drawdown breaker |
| --- | --- | --- | --- | --- | --- |
| `cash` | cash | 1.0 | off | off* | off |
| `buy_and_hold` | buy-and-hold | 1.0 | off | off* | off |
| `donchian_55_20` | Donchian(55/20) | 1.0 | off | off* | off |
| `vol_target_buy_and_hold_30d_50pct` | buy-and-hold | 1.0 | on | 0.25 | off |
| `vol_target_donchian_55_20_30d_50pct` | Donchian(55/20) | 1.0 | on | 0.25 | off |

\* strategies 1–3 use max-exposure only; the turnover limiter is applied only
where required for a uniform interface and is a no-op at these targets (documented
in the protocol). Strategies 4–5 additionally apply the 30d/50% volatility target
then the 0.25 turnover limit.
