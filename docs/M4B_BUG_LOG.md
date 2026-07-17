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

## §41 independent red teams

Three independent read-only red teams (accounting/causality, provenance/forgery,
security/governance/isolation) were run against the pre-freeze package. The accounting core held to
machine precision under a 400-run randomized multi-asset fuzz (worst relative equity-identity error
2.7e-16; cash and quantities never negative; gross exposure ≤ 1; hold-step residual exactly 0), and
the security/isolation/additivity boundary held (668-file manifest identical before/after all
probes, three sealed ledgers byte-empty, M4A snapshot unchanged, v1.1 API byte-additive over v1.0).
Seven genuine but non-hard-stop findings were fixed; each carries a regression test that fails on the
pre-fix code. Note the fixes changed the reference `result_id` (calendar binding widens the run
canonical; the absurd-annualization guard nulls a metric), which is expected and captured freshly by
the R-phase `reference_expected_results.json`.

### R-B1 — the full-graph verifier and the checkpoint did not bind trading calendars (HIGH) — FIXED

Calendars govern tradability, yet `PortfolioRunResult` did not carry them, `verify_portfolio_result`
never reconciled the result's `calendar_fingerprints`, and the checkpoint's `verify_against` omitted
them. Two facets reproduced: (A) a result's `calendar_fingerprints` was a free plug — arbitrary
valid-format lies verified; (D) a run computed under calendar C1 was certified against a universe
declaring a different calendar C2 (same `calendar_id`, different sessions), whose own re-run yields a
different terminal equity (125647.35 vs the certified 125276.84). The same root let an honest
checkpoint be resumed against different calendars and silently diverge.

**Fix:** `PortfolioRunResult` gains a `calendar_fingerprints` field folded into its canonical form
(so `run_result_fingerprint` binds the calendars that governed the run); `build_portfolio_result`
cross-checks the run's calendars against the universe (as it already did for membership/schedule);
`verify_portfolio_result` reconciles run-vs-universe and result-vs-run calendars; and the checkpoint
binds a combined `calendars_fingerprint` that `verify_against` checks, so a resume under different
calendars is refused. Batch = streaming = resume stays byte-identical (the resume canonical gains the
same calendar list). Regression tests in `tests/test_portfolio_result.py` and
`tests/test_portfolio_streaming.py`.

### R-B2 — verify left `base_currency` and `package_version` unbound (MEDIUM) — FIXED

`verify_portfolio_result` never compared the result's stored `base_currency` or `package_version` to
the run / running package, so a USD run relabeled `EUR` (numbers physically USD) and a result stamped
with any package version both verified. **Fix:** verify now binds `result.base_currency` to the run
and `result.package_version` to the running `M4B_PACKAGE_VERSION`. Regression tests in
`tests/test_portfolio_result.py`.

### R-A1 — the corporate-action refusal window missed the terminal marking bar (MEDIUM) — FIXED

The fail-closed window was `[first_event, last_event]`, but an instrument trading at the last event
is marked at *that bar's close* (`last_event + bar_interval`). An action effective in the tail
`(last_event, terminal_close]` was therefore neither refused nor applied, yet landed in the bar that
prices terminal equity — defeating the "never silently misstate" guarantee for the terminal bar
(a 2:1 split at 03:30 on a bar closing 04:00 flipped from refused at 03:00 to silently accepted,
marking terminal equity off the halved close). **Fix:** the refusal upper bound is taken per
instrument as `_bar_close_time_at(frame, last_event)` (the terminal marking-bar close) when a bar
opens at the last event, else `last_event`. The reference run is unaffected (its actions fall past the
terminal close). Regression tests in `tests/test_portfolio_engine.py` (refused in-tail; admitted just
past the terminal bar).

### R-A2 — `sortino_ratio` was finite for a single-event run (LOW) — FIXED

Volatility and Sharpe self-nullify at `n=1` (sample std is NaN), but Sortino's downside deviation
uses a population mean and is finite for one sample, so a single-event *loss* reported a one-sample
"ratio" — contradicting the "None for fewer than two events" contract (the existing n=1 test used a
flat, zero-return series that masked it). **Fix:** Sharpe and Sortino are gated on `n >= 2` alongside
volatility. Regression test in `tests/test_portfolio_metrics.py` (single-event loss).

### R-A3 — `annualized_return` emitted absurd-but-finite values (LOW) — FIXED

`(terminal/initial) ** (periods_per_year/n) - 1` was guarded only against overflow / non-finite
results, so a short run with a modest move produced an astronomically large yet finite figure (the
reference universe's own artifact carried `annualized_return ≈ 4.08e54`), exactly the "absurd number"
the code's comment claimed to suppress. **Fix:** a `_annualized_return` helper reports `None` when the
magnitude exceeds a documented, deliberately loose sanity ceiling (`_MAX_ANNUALIZED_ABS_RETURN =
1e6`), so a meaningless extrapolation is `None` rather than a number, while any plausible figure is
preserved. Regression test in `tests/test_portfolio_metrics.py`.

### R-C1 — the offline-tests firewall scanned by filename prefix, missing a portfolio test (LOW–MED) — FIXED

`test_portfolio_tests_import_no_network_or_ml_client` iterated `glob("test_portfolio_*.py")`, so
`tests/test_m4b_consumer_e2e.py` (which imports `subprocess` to install a wheel) was never scanned —
the guard enforced "files named `test_portfolio_*` are offline", not "portfolio tests are offline".
**Fix:** the scan now covers every `tests/test_*.py` that structurally exercises the portfolio package
(a real `eth_research.portfolio` import *or* a portfolio import inside a driver string — comments do
not count, so a governance test that only names the path is not swept in), with a narrow explicit
allowlist letting the installed-consumer E2E import `subprocess` and nothing else forbidden.

### R-C2 — the AST firewall's docstring overclaimed; no indirection lint (INFO/LOW) — FIXED

The firewall docstring said the AST scan proved "structurally that the package cannot reach" a
network / dynamic execution, but a lexical allow/deny scan cannot model `getattr(os, "sys"+"tem")`,
`importlib.__dict__["import_module"]`, or value-indirection (the shipped source is clean — verified —
so this was wording, not a live escape). **Fix:** the docstring now frames the AST scan as a
best-effort lint with the import-closure as the load-bearing structural proof, and a new
`test_portfolio_runtime_has_no_capability_indirection` flags `getattr` on a sensitive module and any
`__dict__[...]` / `__builtins__` access across the package.

## §42 Q — post-freeze red team of the registration surface

After the R-phase registration landed, a post-freeze adversarial pass over the new
`eth_research.portfolio.registration` verifier confirmed its drift detection holds — a changed
accepted-M4A artifact, an edited portfolio member, and a non-empty sealed ledger are each caught as
`RegistrationDriftError`. One robustness gap was found and fixed.

### R-Q1 — a deleted bound artifact raised a raw `OSError` instead of drift (LOW) — FIXED

`build_source_freeze` binds artifacts it does not itself build (the public-API snapshot, the CLI
reference, the accepted M4A artifacts, the sealed ledgers). Deleting one of those made `verify`
raise a raw `FileNotFoundError` rather than the fail-closed `RegistrationDriftError` its contract
promises. **Fix:** a `_bound_sha256` helper wraps every bound read so a missing/unreadable bound
artifact surfaces as `RegistrationDriftError`. The `verify` loop already fail-closed on the five
built artifacts; this extends the same guarantee to the additionally-bound ones. Regression test in
`tests/test_portfolio_registration.py` (`test_registration_missing_bound_artifact_fails_closed`).
