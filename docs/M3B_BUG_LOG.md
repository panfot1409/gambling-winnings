# Milestone 3B — Bug Log (pre-registration red team, Phase 13)

Before freezing the fractional execution-risk protocol for the one preregistered
research-train run, the engine and its estimators were red-teamed by **three
independent read-only auditors** (causality/look-ahead; accounting/solver;
metamorphic/prohibited-functionality/oracle/reconciliation) and by a dedicated
engine-level adversarial test suite (`tests/test_fractional_redteam.py`).

Every genuine finding was reproduced as a failing test, fixed with a minimal
change, and covered by a regression test. No CRITICAL or HIGH finding was found;
the substantive items were MEDIUM correctness/robustness gaps that could bite
only at small equity or on the two `vol_target_*` strategies (which have no
binary-parity cross-check). Areas cleared clean are recorded so the freeze rests
on an explicit basis.

## Cleared clean (no defect)

- **Causality / look-ahead** (Auditor 1). The fill of bar `t` reads only
  `open[t]` and estimates through `t-1`. Verified: signal `signals[info_pos-1]`
  (no off-by-one), strict `< as_of` liquidity slice, trailing volatility window
  ending at `close[t-1]`, prior exposure/equity at `close[t-1]`, mark-to-market
  `close[t]` affecting only future bars, fresh per-call state (no cross-fold
  leakage), no `center=`/`ffill`/`bfill`/`shift(-n)` anywhere. `run_backtest`'s
  Donchian `.shift(1)` excludes the current bar from its own breakout.
- **Prohibited functionality** (Auditor 3). No network/wallet/signing/credential/
  order-routing/leverage/short/ML/optimizer import anywhere in the package;
  runtime deps are numpy/pandas/pyarrow only. The lone `coinbase` import is an
  offline parser that rejects URL schemes.
- **Strategy wiring** (Auditor 3). All five configs match
  `docs/M3B_RISK_POLICY_SPEC.md` exactly (max-exposure-only for 1-3; vol target +
  0.25 turnover for 4-5; breaker off everywhere).
- **Accounting/solver core** (Auditor 2). Cash never accumulates below
  `-cash_tolerance`; buy never creates cash / sell never creates ETH; fee is
  separate and never double-counted; cost decomposition reconciles; bisection
  brackets a true sign change; the participation cap is inclusive-at / truncating-
  above; zero/NaN/inf liquidity never yields infinite impact; the fixed-order-path
  metamorphic guarantees hold.

## Findings and resolutions

### B1 — MEDIUM — dust-drop reported `partial=False` while missing the target by > `weight_tolerance`
Auditor 2 F1. The dust floor is on USD notional (`notional_epsilon`, 1e-6) while
the honesty guarantee is on the weight scale (`weight_tolerance`, 1e-9); below
~$1000 equity a genuine partial was mislabeled a non-partial, which made the
engine's own reconciler (`converged_reaches_executable`) raise. Reachable in a
deep-drawdown fold.
**Fix:** `solver.py` gates dust honesty on the untraded weight gap — a dropped
sub-notional trade is `partial=True` (`partial_dust_below_notional_floor`) iff
`|w0 - executable| > weight_tolerance`, else a clean `no_trade_dust`.
**Test:** `test_fractional_solver.py::test_dust_below_notional_floor_is_an_honest_partial`,
`::test_within_band_target_is_a_clean_no_trade`.

### B2 — MEDIUM — `weight_at_reference` could return exposure outside `[0, 1]` beyond tolerance
Auditor 2 F2. A `validate_state`-legal within-tolerance negative cash/quantity (a
float artifact of the bit-exact, un-clamped accounting) pushed the raw ratio a
hair above 1 / below 0, which the reconciler's exposure-bound check rejects at
small equity, and could have produced spurious tiny churn at the full-investment
boundary.
**Fix:** `accounting.py` `weight_at_reference` validates the state, then clamps
the definitionally long-only exposure to `[0, 1]`; an out-of-tolerance state is
rejected (not clamped). Bit-for-bit compatibility parity is preserved (exposure
is not part of the cash/ETH/equity series).
**Test:** `test_fractional_accounting.py::TestExposureClamp` (3 cases).

### B3 — MEDIUM — reconciliation gaps (false assurance + un-reconciled numbers)
Auditor 3 Item 4. (a) the `terminal_equity_path` check was a mathematical
tautology (`previous * (equity/previous) == equity`) that could never fire while
advertising a check; (b) `terminal_liquidation_equity` was never re-derived; (c)
no inter-bar transition / fill-ledger reconciliation existed — the cash/ETH series
were trusted as primitives, so a systematic ledger bug flowing consistently into
cash/equity/exposure reconciled cleanly. Most material for the `vol_target_*`
strategies, which have no binary oracle.
**Fix:** `reconciliation.py` replaces the tautology with (i) an **inter-bar
transition** check that re-derives each bar's cash/ETH from the previous bar plus
its fill and cross-checks the `Fill` ledger legs (`cash_before/after`,
`quantity_before/after`, fee, price, quantity), requiring one fill per executed
bar, and (ii) a **terminal-liquidation** re-derivation from the final book, last
close, and last lagged liquidity.
**Test:** `test_fractional_reconciliation.py::test_tampered_fill_ledger_is_caught`,
`::test_tampered_terminal_liquidation_is_caught`.

### B4 — LOW (defense-in-depth) — under-guarded cost scenario / breakdown / context
Auditor 2 F3 + Auditor 1 hardening. (a) `cost_breakdown` lacked the `quantity>=0`
guard `fill_price` has; (b) `CostScenario` did not validate non-negative finite
rates, concession `< 1`, positive lookback, or positive/None participation — a
mis-specified scenario with a negative `impact_cap` would break price
monotonicity (on which the solver's closed-form cash path relies); (c) the engine
trusted its caller to pass a strictly-past `context`.
**Fix:** `cost_model.py` adds `CostScenario.__post_init__` validation and a
`cost_breakdown` quantity guard; `engine.py` rejects a `context` whose max
timestamp is not `< frame.index.min()`.
**Test:** `test_fractional_cost_model.py::TestScenarioValidation` (4 cases);
`test_fractional_engine.py::test_context_not_strictly_before_frame_is_rejected`.

## Accepted caveats (documented, not defects)

- **Vacuous `cash` parity** (Auditor 3, LOW). The compatibility oracle for the
  all-cash `cash` strategy is trivially satisfied (constant equity). This is
  legitimate — `cash` genuinely never trades — and non-vacuity is covered at the
  suite level by the `buy_and_hold`/`donchian` comparisons and
  `test_donchian_actually_trades` (`num_fills >= 2`).
- **`np.array_equal` ignores the index** (Auditor 3, LOW). The oracle compares
  values; both series are built from the same `frame`, so the index is shared by
  construction.
- **Cross-scenario terminal-equity ordering is NOT a metamorphic invariant**
  (Auditor 3). Because the participation cap and cost are both scenario-dependent,
  a higher-cost scenario can end richer (it holds less ETH, more cash) on a
  declining frame. This is economically correct and is deliberately **not**
  asserted or pre-registered; the engine-level metamorphic test isolates a single
  fee bump on a fixed order path (`test_fractional_redteam.py`).

## Note on tolerance coupling (root cause of B1/B2)

Both B1 and B2 trace to mixing a USD-absolute tolerance (`cash_tolerance =
notional_epsilon = 1e-6`) with a weight-scale tolerance (`weight_tolerance =
no_trade_epsilon = 1e-9`), consistent only for equity ≳ $1000. The fixes make the
guarantees hold independent of capital (weight-scale dust honesty; clamped
exposure). The preregistered run additionally uses an initial capital that keeps
equity well above this regime across the research-train period.
