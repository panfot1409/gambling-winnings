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

## Post-run red team (Phase 22)

After the one preregistered run (`m3b-fractional-execution-risk-v1-run-001`) was
executed and published, **three independent read-only auditors** re-verified the
committed result: (1) causality / look-ahead on the exact engine that produced
it, (2) prohibited functionality and the absolute scope boundaries, and (3)
reproducibility and provenance integrity.

### Cleared clean (no defect)

- **Causality / look-ahead** (Auditor 1). Verified against the published-run code
  path: the fill of bar `t` reads only `open[t]`; the signal is `signals[info_pos-1]`
  (no off-by-one); the liquidity slice is strict `< as_of`; the volatility window
  ends at `close[t-1]`; prior exposure/equity are marked at `close[t-1]`; per-fold
  warm-up context is strictly before the OOS block and creates no P&L; no
  `center=`/`ffill`/`bfill`/`shift(-n)` anywhere; all engine callers feed the same
  strictly-past context.
- **Prohibited functionality / scope** (Auditor 2). No network / wallet / signing /
  exchange-auth / order-routing / leverage / short / margin / derivatives / ML /
  optimizer import anywhere in the fractional package; runtime imports are stdlib +
  numpy/pandas + intra-package. Long-only is positively enforced (solver rejects a
  target outside `[0, 1]`; accounting rejects negative cash/quantity). Both sealed
  ledgers are byte-empty; the results declare zero forbidden access; no git tag was
  created; the M3A branch and every M2B/M3A immutable artifact are untouched.
- **Reproducibility / integrity** (Auditor 3). Independently (re-deriving digests
  with `hashlib` and re-deriving the aggregates in plain Python): the registry
  hash-chain, the manifest bindings, the 75-cell/15-aggregate model, the
  byte-exact results/report reproduction, and the sealed-ledger emptiness all
  verify. `replay --check` prints `completed: results_reproduced, report_reproduced,
  archive_verified`.

### Findings and resolutions

#### F1 — MEDIUM — the orchestrator E2E rehearsal went red after publication (test-state coupling, not artifact drift)
Auditor 3. Once run-001 is committed to the real repository,
`tests/test_fractional_orchestrator.py` failed (1 failure + 6 setup errors)
because `make_m3a_checkout` clones the now-completed real repo, so the rehearsal
could not register the single-use id and a "fresh" clone replayed as `completed`
rather than `pristine`. **Artifact integrity was never in question** — the
production `replay.py` is deliberately dual-state and every binding verified
independently; only the test module was stale.
**Fix:** the rehearsal (and the pristine-replay test) now restore the clone's
`research/m3b` tree to pristine (empty registry, no artifacts) before driving the
lifecycle, mirroring the M3A standing E2E, so it registers/executes/replays the id
inside the throwaway clone regardless of the real repo's published state.
**Test:** `tests/test_fractional_orchestrator.py` (the rehearsal itself is the
regression test; green again on the completed tree).

### Accepted (no change)

- The fold-median cost monotonicity observed in the findings is an *observation*,
  not a pre-registered invariant; per-cell cross-scenario ordering is deliberately
  not asserted (see the "Accepted caveats" above).
- A post-run `ruff format` reformatted four non-computation files (archive/replay
  + two tests); the published results are unaffected and still reproduce
  byte-for-byte (they record the code-freeze commit's fingerprint, and formatting
  changes no computation).

---

## Trust-boundary closure (R1–R11)

A closure/hardening pass over the committed run-001, closing engineering and
provenance weaknesses **without changing any published financial result**. Every
change is additive or validation-only; `python -m eth_research.fractional.replay
--repo-root . --check` reports `completed: results_reproduced, report_reproduced,
archive_verified` after every commit, and the results/report/manifest bytes are
untouched. Each defect below was reproduced (as a failing test or an enumerated
fact) before it was fixed.

| id | defect | fix | verified by |
| --- | --- | --- | --- |
| R1 | a crash after publication but before the `completed` append had no durable recovery, and the blanket `except` recorded `failed` — mislabeling a published success | durable `CompletionIntent` written before publish + calculation-free `recovery` finalizer; the failure path now distinguishes a published-but-unfinalized run (recoverable, never `failed`) from a genuine pre-publication failure | `tests/test_fractional_recovery.py` (crash-injection matrix) |
| R2 | the "archive" was only a manifest pointing at the mutable singletons — no independent immutable body | additive `experiments/run-001/immutable-v2/` with byte-identical copies + `archive_v2.json`; `verify_archive_v2` proves byte-identity to the singletons and the manifest/registry bindings | `tests/test_fractional_archive_v2.py` |
| R3 | the manifest parser coerced digests via `str()` | strict `require_hex64` / `require_safe_relative_path` decode at the parse site | `tests/test_m3b_closure_repro.py::TestR3ManifestParserStrictness` |
| R4 | the results parser repaired values via `int()/float()/str()` | `FractionalAggregate.from_dict` and `FractionalResults.from_json_bytes` decode through the shared `require_*` surface; parsing never repairs | `TestR4ResultsParserStrictness` |
| R5 | invalid accounting values (NaN via `<` comparisons) could cross the boundary | `_finite` guards (bool/non-real/non-finite) before every sign comparison in accounting; strict `__post_init__` on the domain models | `TestR5AccountingStrictness` |
| R6 | invalid cost/risk/liquidity configs were silently accepted | finiteness/bool/int guards on `CostScenario`, `CostBreakdown`, `RiskConfig`, `FractionalStrategy`, `DrawdownBreakerConfig`, and the liquidity `as_of` | `TestR6LiquidityStrictness` + cost/risk suites |
| R7 | the public engine applied a signal positionally (a shuffled index leaked) | `_validate_signal` requires the signal's index to equal the frame's before `.to_numpy()`; OHLCV/context canonicality + contiguity enforced | `TestR7EngineBoundaryStrictness` |
| R8 | the archive verifier did not fully verify the tree | `verify_m3b_run_archive` — a 24-check (25 with `--deep`) aggregate over every closure verifier | `tests/test_fractional_verify_run_archive.py` |
| R9 | the `started` and `completed` lifecycle timestamps were identical | documented as a run-001 legacy artifact; lifecycle-v2 fixtures prove the registry supports (and validates) strictly increasing, distinct timestamps | `tests/test_fractional_lifecycle_v2.py` |
| R10 | the report overstated cost monotonicity as universal (true only of fold medians) | append-only erratum with the exact statement hash + the complete full-precision cell-wise counterexample set (donchian_55_20 fold 1: base +90.668795% < stressed +91.348557%) | `tests/test_fractional_report_erratum.py` |
| R11 | insufficient per-run return evidence (only aggregate summaries) | size-bounded, replay-reconstructible `execution_trace_commitments.json` committing every cell's per-bar trace digest | `tests/test_fractional_execution_trace.py` |

### Additive artifacts (never modify a frozen byte)

- `research/m3b/experiments/run-001/immutable-v2/` — byte-identical results/report copies + `archive_v2.json` (R2)
- `research/m3b/execution_trace_commitments.json` — per-cell trace digests (R11)
- `research/m3b/run001_legacy_completion_audit.json` — records run-001 predates the completion-intent mechanism (R1)
- `research/m3b/artifact_annotations.jsonl` — hash-chained index of the above
- `research/m3b/errata/` + `research/m3b/artifact_errata.jsonl` — the append-only report erratum (R10)

All are indexed and re-verified by `python -m eth_research.fractional.verify_run_archive --repo-root . --deep`.

### Closure red team (3 independent adversarial audit passes)

Three independent read-only auditors reviewed the closure modules (recovery/R1;
archive-v2/trace/annotations/R2/R11; erratum/verifier/strict-validation/R10/R3/R4).
No auditor found an exploitable defect in the financial results, the crash-recovery
core, or the R10 counterexample-completeness invariant. Every surfaced gap was in
what a *verifier* enforced, not a data-tampering bypass; all genuine ones are fixed
and regression-tested (commits `5ce9bbf`, `dfd2a94`).

| # | pass | severity | finding | disposition |
| --- | --- | --- | --- | --- |
| A1 | archive | MEDIUM | `verify_archive_v2` anchored the archived copies only to the mutable manifest; a coordinated singleton+copy+manifest+record tamper (registry untouched) passed the standalone verifier | **fixed** — it now checks each copy's digest against the immutable, hash-chained `completed` event's certified digests |
| A2 | recovery | LOW | `verify_published_run` ran inside the publish `try`; a post-completion failure was misrouted into the failure machinery | **fixed** — verify moved outside the `try` |
| A3 | recovery | LOW | `recovery` CLI didn't catch field-level `ValueError` on a corrupt intent | **fixed** — CLI now catches it and fails closed cleanly |
| A4 | recovery | LOW | the intent's artifact digests weren't cross-bound to the embedded `completed` event's certified digests | **fixed** — `CompletionIntent.__post_init__` cross-binds them |
| A5 | recovery | LOW | the `failed` append wasn't best-effort | **fixed** — best-effort; the real cause always surfaces |
| A6 | erratum | (gap) | `verify_m3b_run_archive` did not require the erratum to exist | **fixed** — the run-001 erratum is now mandatory |
| A7 | erratum | (gap) | the "statement present verbatim" check accepted any report substring | **fixed** — `erroneous_statement` is pinned to the one canonical overbroad claim |
| A8 | erratum | nit | the counterexample float guard didn't reject NaN/Inf | **fixed** — now rejects non-finite |
| B1 | archive | LOW | `require_canonical_file_bytes` enforces only a trailing newline, not full canonical formatting | **accepted** — pre-existing shared helper; where used without a re-render (manifest load) the exact bytes are still pinned via `archive_v2.json`'s `manifest_sha256`, and every re-render verifier gates on byte-equality |
| B2 | annotations | LOW | an append-only log's last line is unanchored, and an empty registry verifies vacuously | **accepted** — inherent to append-only logs (git-anchored); every annotated artifact is *independently* required and verified by the aggregate verifier, and the erratum is now mandatory, so no closure artifact can go missing undetected via the annotation index |
