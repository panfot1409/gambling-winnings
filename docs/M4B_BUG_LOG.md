# M4B bug log

The record of the Milestone 4B self-directed adversarial bug-hunt (§40) over
`src/eth_research/portfolio/`. Each finding was reproduced against the installed package before any
fix, and each fix carries a regression test that fails on the pre-fix code. Two genuine defects were
fixed; one reported item was assessed as a spec-compliant design choice and the documentation was
corrected to describe it accurately. The broad set of invariants that held under the hunt
(determinism, batch = streaming = resume, cash-safety and the equity identity, additive attribution,
strictly-future-evidence inertness, trace-chain tamper rejection, corporate-action fail-closed,
parser strictness) is not repeated here.

## F1 — `verify_portfolio_result` accepted a forged terminal equity and metrics (HIGH) — FIXED

`verify_portfolio_result` bound the per-asset attribution, the trace chain, and the evidence
fingerprints, but never bound the result's headline `initial_equity` / `terminal_equity` or the
descriptive-metrics block to the run. The only tie was the internal roll-up
`change == terminal − initial`, whose `cumulative_residual` term is an unchecked free plug. A result
that added 50,000 to `terminal_equity`, added the same 50,000 to `cumulative_residual` to keep the
roll-up balanced, and invented a Sharpe of 9.99 therefore parsed **and** verified — while the trace
commitment (which verify re-derives from the run) still carried the true terminal equity.

**Fix:** verify now binds `initial_equity` / `terminal_equity` / `num_fills` to the run and
recomputes the entire `PortfolioMetrics` block from the run — annualized on the universe's own bar
interval, exactly as every M4B caller computes `periods_per_year` — requiring an exact match. As
parse-layer defense in depth, `_check_internal_consistency` binds the result's headline equities to
the metrics block it carries. No schema change (the annualization basis is derived from the universe),
so the reference `result_id` and the committed public-API snapshot are unchanged and the replay
verifier still passes all five checks. Regression tests in `tests/test_portfolio_result.py`.

## F2 — the mark-to-market FX leg uses the bar-close time (MEDIUM) — NOT A DEFECT; documentation corrected

The end-of-step mark values a holding at its bar's `close[t]` and translates it at the FX rate **as
of that close** (the spec's step-15 "apply close FX"), consistent with marking the *price* at
`close[t]`. The hunt observed that an FX observation timestamped in `(τ, close_time]` changes that
recorded mark, and that the run's terminal value reflects the close-time FX of the final bar rather
than the FX as of the last rebalance. This is the accepted marking convention, not a look-ahead
defect: the mark is a report taken *after* fills and consumed only at the *next* event (by which time
the close is in the past), and the fills themselves price and convert at the FX as of the execution
time τ. It is standard end-of-period mark-to-market. The only genuine problem was that
`docs/M4B_DESIGN.md` imprecisely said the mark was translated "at the FX rate known by τ"; the
mark-to-market paragraph now states the close-time FX behavior and the causal reasoning plainly.

## F3 — `solve_shared_cash` was not exactly permutation-invariant for ≥3 assets (MEDIUM) — FIXED

The solver documents that its result is permutation-invariant, but the pre-trade-equity, gross-weight,
and total-cost sums were left folds over the input tuple, and floating-point addition is not
associative, so reordering the same assets perturbed those sums (and the bisection bracket) at the
ULP level (~2e-9 on a six-asset case). The existing test used only two assets, where `+` is trivially
commutative. End-to-end runs were never affected because the engine feeds inputs in canonical
`instrument_id` order; only direct callers of the public solver that passed unsorted inputs were.

**Fix:** the solver canonicalizes the input order (`sorted` by `instrument_id`) before summing, so
every sum is order-independent. End-to-end runs are byte-identical (the replay verifier's determinism
and result checks still pass, and the reference `result_id` is unchanged). A six-asset regression test
in `tests/test_portfolio_solver.py` asserts three reorderings reproduce the equity, cost, residual,
and per-asset notionals exactly.
