# M3B Fractional Long-Only Accounting Specification

Exact, deterministic single-asset (ETH/cash) long-only portfolio accounting.
All quantities are `float`; every identity below is enforced by construction and
by reconciliation tests. No borrowing, leverage, or shorting exists.

## State

At the execution open of bar `t`:

- `P`  = reference open price `open[t]` (`P > 0`)
- `C0` = cash before trade (`C0 >= 0`)
- `Q0` = ETH quantity before trade (`Q0 >= 0`)
- `E0` = `C0 + Q0 * P` (reference-marked pre-trade equity, `E0 > 0`)

## Target weight

The target weight `w*` in `[0, 1]` is the ETH reference value divided by
post-trade reference-marked equity **after execution costs**:

    achieved_weight = Q1 * P / (C1 + Q1 * P)

where `Q1`, `C1` are the post-trade quantity and cash. Note `P` (the reference
open), **not** the fill price, marks the ETH leg in the weight — costs enter only
through `C1`.

## Fill mechanics

Let `x >= 0` be the executed **quantity** and `f_buy`, `f_sell` the directional
fill prices from `docs/M3B_EXECUTION_COST_SPEC.md` (`f_buy >= P >= f_sell > 0`).
`fill_notional = x * f`, `fee = fill_notional * fee_rate`.

**Buy** (`x` ETH):

    Q1 = Q0 + x
    C1 = C0 - x * f_buy - fee_buy      (require C1 >= -cash_tolerance)

**Sell** (`x` ETH):

    Q1 = Q0 - x                        (require Q1 >= -qty_tolerance)
    C1 = C0 + x * f_sell - fee_sell

**No-trade**: `x = 0`, `Q1 = Q0`, `C1 = C0`.

## Exact identities (reconciliation targets)

- `Q1 >= 0` and `C1 >= -cash_tolerance` (treated as `0` within tolerance).
- Buy consumes cash and never creates cash; sell reduces ETH and never creates
  ETH.
- `achieved_weight` in `[0, 1]` within `weight_tolerance`.
- Marked equity at `close[t]`: `E_mark = C1 + Q1 * close[t]`.
- Gross vs net return per bar are reported separately (see cost spec).
- Cost decomposition sums exactly to the implementation shortfall vs the
  reference-notional benchmark (cost spec identity).

## Solver (Phase 6)

Find `x` reaching `w*` by **bounded bisection** on a monotone residual.

- **Direction**: compare `w*` to the current reference weight
  `w0 = Q0 * P / E0`. If `w* > w0 + no_trade_epsilon` → buy; if
  `w* < w0 - no_trade_epsilon` → sell; else **no trade**.
- **Buy bracket**: `x in [0, x_buy_max]` where `x_buy_max` is the largest buy the
  cash *and* participation cap allow (cash: the `x` that drives `C1` to `0`
  including fee at `f_buy`; participation: `max_reference_notional / P`). Take the
  binding minimum.
- **Sell bracket**: `x in [0, min(Q0, participation_qty_cap)]`.
- **Residual** `g(x) = achieved_weight(x) - w*` is monotone in `x` (buy: strictly
  increasing in achieved weight; sell: strictly decreasing), so bisection
  converges. Pinned: `weight_tolerance = 1e-12`, `max_iterations = 100`,
  endpoints evaluated first (if the target lies beyond the feasible endpoint,
  execute the endpoint and record a **partial fill** with the residual target
  error).
- **No-trade epsilon**: `no_trade_epsilon = 1e-9` on the weight scale; a solved
  `|x * P| < notional_epsilon = 1e-6` is treated as no trade (avoids float-noise
  churn).
- **Feasibility/monotonicity failure** → a typed error; never a silent clip.

Partial fills record: `requested_target`, `executable_target` (post-risk),
`achieved_target`, `target_error = achieved - executable`, and a typed reason.
A liquidity-constrained scenario with **no** lagged liquidity makes **no fill**
and records a typed no-fill reason; same-day volume is never substituted.

## Terminal policy

The final position is **marked** at the last `close`, never force-liquidated.
A *separate* hypothetical liquidation equity is reported: sell all `Q_final` at
the last bar's sell fill price computed from a **conservative causally-available
lagged** liquidity estimate (the estimate as of the final open), inclusive of
spread + slippage + impact + fee. Liquidation adds **no** actual fill and is not
counted in trade/fill counts.

## Tolerances (pinned)

    cash_tolerance    = 1e-6   (USD; |negative cash| within this is treated 0)
    qty_tolerance     = 1e-12  (ETH)
    weight_tolerance  = 1e-9   (achieved-vs-target reporting/validation)
    solver_tolerance  = 1e-12  (bisection residual)
    no_trade_epsilon  = 1e-9   (weight scale)
    notional_epsilon  = 1e-6   (USD; below this a solved trade is dropped)
    max_iterations    = 100
