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
3. **Corporate-action quantity adjustments (deferred; refused in-window).** Applying splits/reverse-
   splits to *held quantities* — and, in particular, attributing a split's value change exactly when
   raw prices halve while quantity doubles — is deferred to a later milestone. Rather than silently
   misstate, the engine **fails closed**: if the supplied corporate-action set contains a split or
   reverse-split whose effective time falls within the run's event window for a panel instrument, the
   run is refused. A window without such an action proceeds normally.
4. **Corporate-action cash payments (deferred; refused in-window).** Likewise, dividend and delisting
   cash-outs are not credited; a cash action whose payment time falls within the run window for a
   panel instrument causes the run to be refused rather than credited late or approximately. Both
   guards preserve the causal, never-silently-wrong contract until full application lands.
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
13. **Mark each holding at its end-of-step close.** Value an instrument trading at τ at the close of
    the very bar it trades into (the step's own bar, whose `close_time` is the end of the step),
    exactly as the accepted single-asset engine marks bar *t* at `close[t]`. This end-of-step close
    is a *report*: it is computed after all fills and is consumed only at the next event (step 18),
    so it is never an input to τ's own decision and introduces no look-ahead.
14. **Carry prior marks only when permitted.** A held-through instrument with no bar opening at τ (a
    market closed at τ per its calendar, or one that has left the universe) is instead valued at its
    latest completed close at or before τ — carried, not force-liquidated — and only if the staleness
    policy still permits it; an over-stale mark is refused rather than invented.
15. **Apply close FX.** Translate each local mark to the base currency at the causally available
    close FX rate.
16. **Record attribution and commitments.** Decompose the equity change additively (local price P&L,
    FX translation P&L, dividend/action cash, minus costs, plus a residual). The decomposition is
    additive by construction — the residual is the honest remainder, reported and never forced. For a
    held-through step it is zero within tolerance; on a step that trades, it captures the open→close
    execution move on the newly traded quantity. Append the event's domain-separated trace commitment.
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
