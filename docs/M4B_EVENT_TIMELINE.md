# M4B causal event timeline

This document fixes the one canonical ordering of operations the portfolio simulator performs at
each execution timestamp τ. The ordering is the contract that makes the simulator *causally
correct*: at every step, a quantity is computed only from information that is genuinely available at
or before τ, and no later fact — a future bar, a future FX rate, a future corporate action, a future
membership change, or the current bar's own close/high/low/volume — can flow backward into a
decision, a fill, or a holding at τ. The engine implements exactly this order; the information-set
view (`AsOfView`) exposes exactly the inputs each step is permitted to read; and the causality tests
assert that mutating any not-yet-knowable input leaves every output at and before τ unchanged.

## The ordering at execution timestamp τ

1. **Verify fingerprints.** Confirm the universe, panel, calendar, membership, FX-evidence, and
   corporate-action identities bound into the run match the evidence in hand. A mismatch fails
   closed before any accounting.
2. **Determine membership known by τ.** Resolve the set of instruments whose membership interval is
   active at τ *and* whose governing knowledge time is ≤ τ. Future listings/removals are invisible.
3. **Apply corporate actions effective before the open.** Splits/reverse-splits with an effective
   time strictly before τ's open adjust the *held quantities* (never past signals). Only actions
   whose knowledge time is ≤ τ are visible to any decision.
4. **Apply cash payments due before the open.** Dividends and delisting cash-outs whose payment time
   is strictly before τ's open credit base-currency cash (converted at a causal FX rate), before the
   tradable set is priced.
5. **Establish the tradable set.** Intersect the membership-active instruments with those that have
   a valid open bar at τ and a valid causal FX rate. An instrument missing either is not tradable at
   τ.
6. **Read the current opens (fills only).** Load each tradable instrument's open price at τ. The
   open is an *execution reference* — it prices fills — and is never used as a signal input.
7. **Read the causal FX opens.** Load the FX rate for each tradable instrument's quote currency,
   as of τ's execution event (or an earlier permitted observation). Missing or over-stale → fail.
8. **Compute target weights.** Derive the long-only target from information strictly before τ (prior
   completed bars, prior volatility, lagged liquidity, prior FX closes, membership and actions known
   by τ). The current open may be used only as the execution reference in step 9, never as a signal.
9. **Solve the simultaneous post-cost target.** Run the shared-cash solver: one post-cost base
   equity `E_post` at which every asset trades to `w_i·E_post` at once. Permutation-invariant; no
   asset spends the shared cash first.
10. **Generate deterministic fills.** From `E_post`, the per-asset base notional `Δ_i = w_i·E_post −
    V_i` yields a signed local quantity `Δ_i / (fx_i · fill_price_i)`.
11. **Deduct costs.** Charge fee, half-spread, base slippage, lagged-liquidity impact (from volume
    strictly before τ), and any FX-conversion cost — each reported separately.
12. **Assert cash and holding invariants.** Base cash ≥ −tolerance; every holding quantity ≥
    −tolerance; equity = cash + Σ base position values; gross exposure ≤ 1 + tolerance.
13. **Mark assets at causally available closes.** Value each holding at its close known by τ's
    valuation time, converted at the close FX known by then.
14. **Carry prior marks only when permitted.** For an instrument whose market is closed at τ (per its
    calendar), carry the last mark only if the staleness policy still permits it; refuse an
    over-stale mark rather than invent a price.
15. **Apply close FX.** Translate each local mark to the base currency at the causally available
    close FX rate.
16. **Record attribution and commitments.** Decompose the equity change additively (local price P&L,
    FX translation P&L, dividend/action cash, minus costs, plus a residual that is exactly zero
    within tolerance) and append the event's domain-separated trace commitment.
17. **Emit checkpoint.** Persist the post-event state (cash, holdings, marks, FX marks, cumulative
    costs/action-cash/attribution, prior-event hash) as a strict canonical checkpoint.
18. **Only now may close information influence the future.** The close established at τ is a valid
    *signal* input for the next decision event, never for τ's own decision.

## What each step may and may not read

`AsOfView` at τ exposes: prior completed bars; the active universe known by τ; corporate-action
facts with knowledge time ≤ τ; lagged liquidity; prior realized volatility; prior FX closes; and the
current execution-event identity (its open prices, for fills only). It does **not** expose the
current bar's high/low/close/volume, any future bar/FX/action/membership, or any future session
result. Views are immutable defensive copies, and the forbidden columns are poisoned so an attempt
to read them fails loudly rather than silently leaking.

## Batch and streaming agree

The batch engine (over a complete local panel) and the incremental streaming engine (local step
iteration — "streaming" means deterministic local stepping, never a network feed) execute this exact
order and therefore produce identical events, fills, states, result bytes, and final state hash. A
checkpoint taken mid-run resumes to a byte-identical continuation because resuming re-enters the same
ordered pipeline at the recorded next event index with no widened information set.
