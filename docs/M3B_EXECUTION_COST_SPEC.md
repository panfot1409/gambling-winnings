# M3B Execution-Cost Specification

Transparent, directional, **deterministic** execution costs on daily candles.
These are a **deterministic causal liquidity-and-impact research proxy**, not a
calibrated venue model — the project has daily OHLCV only, not quotes or an order
book. No claim of exchange-level fill fidelity is made.

## Inputs

- `P` — reference open price `open[t]` (`P > 0`).
- `x` — executed quantity (ETH, `x >= 0`).
- `lagged_dollar_volume` — median lagged daily dollar volume from rows through
  `t-1` (see `docs/M3B_RISK_POLICY_SPEC.md` liquidity section); `> 0` when
  available.
- scenario parameters (below).

## Formulas

    reference_notional = x * P

    participation      = reference_notional / lagged_dollar_volume      (if liquidity available; else undefined)

    impact_rate        = min(impact_cap, impact_coefficient * sqrt(participation))

    buy_fill_price     = P * (1 + half_spread_rate + base_slippage_rate + impact_rate)
    sell_fill_price    = P * (1 - half_spread_rate - base_slippage_rate - impact_rate)

    fill_notional      = x * fill_price
    fee                = fill_notional * fee_rate

Constraint: `half_spread_rate + base_slippage_rate + impact_rate < 1` (total
directional price concession `< 1`); a scenario or state violating this is a
construction error, never silently clipped beyond `impact_cap`.

## Participation cap

    max_reference_notional = max_participation * lagged_dollar_volume

Equality at the cap **is allowed** (a fill whose `reference_notional ==
max_reference_notional` is permitted). A requested trade exceeding the cap is
truncated to the cap and recorded as a **partial fill**. In a
liquidity-constrained scenario with no lagged liquidity, no fill occurs.

## Cost decomposition (exact identity)

For an executed fill, decompose the implementation shortfall vs the reference
notional into additive, non-overlapping components (each `>= 0`):

    half_spread_cost   = x * P * half_spread_rate
    base_slippage_cost = x * P * base_slippage_rate
    impact_cost        = x * P * impact_rate
    fee_cost           = fee                                   = fill_notional * fee_rate

    # price-concession shortfall vs reference notional (buy pays more, sell receives less):
    price_shortfall    = |fill_notional - reference_notional|
                       = x * P * (half_spread_rate + base_slippage_rate + impact_rate)

    total_cost         = fee_cost + half_spread_cost + base_slippage_cost + impact_cost

**Identity enforced by tests:** `price_shortfall == half_spread_cost +
base_slippage_cost + impact_cost` (exact up to float tolerance `1e-9 * notional`),
and `total_cost == fee_cost + price_shortfall`. Fee is **never** mixed into the
fill price; the fill price carries only spread + slippage + impact.

## Frozen scenarios (predeclared, never changed after seeing results)

### `compatibility_v1` — proves exact parity with the binary engine (no realism claim)

    fee_rate            = 0.001
    half_spread_rate    = 0.0
    base_slippage_rate  = 0.0005
    impact_coefficient  = 0.0
    impact_cap          = 0.0
    liquidity_lookback  = 30
    max_participation   = none      (liquidity_constraint = disabled)

### `causal_proxy_base`

    fee_rate            = 0.001
    half_spread_rate    = 0.00025
    base_slippage_rate  = 0.0005
    impact_coefficient  = 0.01
    impact_cap          = 0.005
    liquidity_lookback  = 30
    liquidity_min_observations = 30
    max_participation   = 0.001

### `causal_proxy_stressed`

    fee_rate            = 0.002
    half_spread_rate    = 0.0005
    base_slippage_rate  = 0.001
    impact_coefficient  = 0.03
    impact_cap          = 0.015
    liquidity_lookback  = 30
    liquidity_min_observations = 30
    max_participation   = 0.0005

## Metamorphic guarantees (enforced by tests)

On a **fixed** order path (fixed quantities/timestamps), raising any of
`fee_rate`, `half_spread_rate`, `base_slippage_rate`, `impact_coefficient`
cannot **improve** terminal equity; reducing `max_participation` cannot
**increase** executed quantity; more lagged liquidity cannot **reduce** feasible
quantity. Zero volume never yields infinite impact (it yields no-fill or an
undefined-participation refusal, per scenario). A NaN/inf volume fails loudly and
never disables the cap.
