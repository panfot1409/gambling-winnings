# M4B design — the multi-asset portfolio research simulator

Milestone 4B is an offline, deterministic, causally-correct multi-asset / multi-venue /
multi-currency **long-only portfolio research simulator**. It runs several spot instruments
(`crypto_spot`, `cash_equity`, `fx_spot`) that trade on different venues, are quoted in different
currencies, and are valued in one explicit base currency; it rebalances them into long-only
fractional target weights over a single shared cash pool with a deterministic simultaneous solver,
marks holdings to market with an explicit staleness policy, and attributes every equity change
additively. The whole milestone lives in one isolated package, `src/eth_research/portfolio/`, is
stacked *additively* on the accepted Milestone 4A v1.0 public API (every v1.0 symbol keeps its exact
descriptor), and is versioned `1.1.0`. It never contacts a network, an exchange, a wallet, or a
broker, and every artifact it emits is canonical JSON with a stable SHA-256. See
[M4B_PLAN.md](M4B_PLAN.md) for scope and exclusions, [M4B_EVENT_TIMELINE.md](M4B_EVENT_TIMELINE.md)
for the canonical causal ordering, and [M4B_LIMITATIONS.md](M4B_LIMITATIONS.md) for the honest
scope-and-limitations statement.

## Module map

Every module below is a real file under `src/eth_research/portfolio/`. Each parses and serializes
through one shared strict surface (`validation.py`) built on the accepted canonical-JSON helpers
(`eth_research.api.serialization`), so the M4B strictness surface is identical to the accepted
stack's. The package is read-only on the canonical path: it emits only the additive
`research/m4b/public_api.json` snapshot, and only through the `public_api --write` developer tool.

| Module | Responsibility |
| --- | --- |
| `__init__.py` | The package entry point: the milestone docstring and the pinned `M4B_PACKAGE_VERSION = "1.1.0"` that stamps a committed M4B artifact. |
| `identity.py` | Immutable full-economic `InstrumentId` (asset class, base asset, quote currency, venue, symbol, instrument type, price/quantity units, calendar id) for one spot instrument; spot-only, every derivative kind rejected at construction; carries a domain-separated `instrument_id` hash. |
| `currencies.py` | Structural currency-code validation (3–12 uppercase ASCII letters, case-exact) with no ISO-4217 authority claim, plus `same_currency`. |
| `validation.py` | The shared strict validators (positive/non-negative finite floats, safe NFC-normalized tokens, exact key sets) and the domain-separated `domain_hash` over canonical JSON. |
| `_time.py` | The single UTC-timestamp convention: `iso_utc` serialize / `require_utc_timestamp` parse, round-tripping only the canonical UTC spelling. |
| `tolerances.py` | The pinned binary64 tolerances (cash, quantity, weight, solver, no-trade, notional, max-iterations) that mirror the accepted single-asset engine and are bound into every result and checkpoint. |
| `universe.py` | `UniverseSpec`: the immutable, order-stable, domain-separated binding of base currency, ordered instruments, calendars, bar interval, staleness bound, and the membership / FX / corporate-action / schedule fingerprints. |
| `bars.py` | Strict canonical OHLCV bar-frame validation (`validate_bar_frame`) and the per-instrument bar-frame content fingerprint; nothing is sorted, gap-filled, or repaired. |
| `panel.py` | `MarketPanel`: the immutable instrument → validated-bar-frame mapping over asynchronous calendars (an absent bar is genuinely absent, never an implied zero), with an order-independent fingerprint. |
| `calendar.py` | `TradingCalendar` (`continuous_24_7` / `session_list` / `synthetic_weekday`) and `Session`; fingerprinted, with no real-world holiday-authority claim. |
| `membership.py` | `MembershipInterval` / `MembershipSchedule`: causally-stamped tradability windows with per-instrument non-overlap; mitigates but does not eliminate survivorship bias. |
| `fx.py` | `FxObservation` / `FxEvidence`: causal as-of `quote`-per-`base` lookup — same-currency `1.0`, direct pair, explicit inverse, and predeclared-single-pivot triangulation only. |
| `corporate_actions.py` | `CorporateAction` / `CorporateActionSet`: causally-stamped evidence for split / reverse-split / cash dividend / delisting cash-out, on the raw/unadjusted-price convention. |
| `information.py` | `AsOfView`: the immutable causal information set at τ (prior completed bars, active universe known by τ, current open for fills, causal FX) that never exposes the current bar's high/low/close/volume or any future fact. |
| `targets.py` | `PortfolioTarget` (long-only weights in `[0, 1]`, gross ≤ 1, cash residual) and the three reference policies `cash_target`, `equal_weight_target`, `declared_weights_target`. |
| `protocol.py` | `PortfolioProtocol`: the frozen, fingerprinted non-market declaration (base currency, initial cash, reference policy, declared weights, cost scenario, staleness, tolerances) and the `build_target` dispatch. |
| `schedule.py` | `RebalanceSchedule`: strictly-ascending fixed UTC rebalance timestamps (given explicitly or derived from calendar session opens); no live clock, daemon, or cron. |
| `solver.py` | `solve_shared_cash`: the deterministic, permutation-invariant shared-cash simultaneous solver that bisects the unique post-cost equity fixed point. |
| `costs.py` | `CostParameters` / `trade_cost` / `CostBreakdown`: the contractive per-trade cost decomposition (fee, half-spread, base slippage, lagged-liquidity impact, optional FX conversion). |
| `accounting.py` | `PortfolioState` / `Fill` / `Position`: the immutable long-only, cash-safe ledger whose every transition fails closed on negative cash or negative quantity. |
| `valuation.py` | `mark_instrument` / `latest_close_as_of` / `StalenessPolicy`: causal mark-to-market at the most recent completed close ≤ τ, refusing an over-stale mark. |
| `attribution.py` | `attribute_step` / `StepAttribution`: the exactly-additive equity-change decomposition (local price, FX translation, action cash, cost, honest residual) with per-asset and per-currency splits. |
| `metrics.py` | `compute_portfolio_metrics` / `PortfolioMetrics`: descriptive, reconcilable, JSON-safe run metrics that telescope to the equity change — no alpha/beta/IR/factor/VaR-as-guarantee. |
| `engine.py` | `run_portfolio_simulation` and the shared `run_event` core that executes the canonical event timeline once per rebalance event τ. |
| `streaming.py` | `stream_portfolio_simulation` / `resume_portfolio_simulation` / `PortfolioCheckpoint`: batch-identical streaming and strict canonical checkpoint/resume over the same `run_event` core. |
| `result.py` | `PortfolioResult`, `build_portfolio_result`, `verify_portfolio_result`: the strict, self-identifying result artifact and its full-graph verifier. |
| `trace.py` | `TraceCommitment` / `build_trace_commitment` / `verify_trace_commitment`: the size-bounded event-trace commitment (hash chain + count + endpoints + bounded samples). |
| `scenarios.py` | `Scenario` / `run_scenario` / `run_scenario_batch`: the deterministic, sequential scenario-batch runner with an order-sensitive batch fingerprint. |
| `reference.py` | `build_reference_universe` / `reference_protocol`: the seeded, code-generated synthetic reference universe, marked "synthetic test fixture — not real market data". |
| `public_api.py` | The additive v1.1 public-API snapshot and its `verify` / `verify_additive` drift-and-additivity guards over `research/m4b/public_api.json`. |
| `cli.py` | The offline, read-only `universe inspect|validate` / `portfolio demo|run|verify` command group. |
| `replay.py` | The offline, read-only replay verifier (`--check`) proving batch/streaming/resume agreement, result build-and-verify, and public-API-snapshot currency. |

## Data and identity model

Every economic object is an immutable, canonically-serializable value whose identity is a
**domain-separated SHA-256**. `validation.domain_hash(kind, payload)` prefixes the milestone tag and
the object `kind` (`eth_research.portfolio.v1:<kind>` followed by a NUL byte) ahead of the canonical
JSON bytes, so a bar hash can never collide with a calendar hash of coincidentally-equal bytes and an
identity is stable across runtimes (canonical JSON is byte-identical everywhere). Because the digest
is over canonical JSON with sorted keys and finite floats only, reordering inputs yields the same
identity while changing any one economic field yields a different one.

- **`InstrumentId`** binds nine fields — `asset_class`, `base_asset`, `quote_currency`, `venue`,
  `symbol`, `instrument_type`, `price_unit`, `quantity_unit`, `calendar_id`. Two instruments are the
  same only when every field matches; a symbol reused across venues is a *different* instrument, and
  a bare ticker is never an identity. `asset_class ∈ {cash_equity, crypto_spot, fx_spot}` and
  `instrument_type` is `spot` only — margin, leverage, futures, options, swaps, and perpetuals are
  rejected at construction. A spot instrument's `price_unit` must equal its `quote_currency`, and its
  `base_asset` must differ from the quote (for `fx_spot` the base is itself a validated currency).
- **`UniverseSpec`** is a *binding*, not a copy of the evidence: it carries the base accounting
  currency, the canonically-ordered instrument list, the calendars (by id), the bar-interval
  contract, the staleness bound, and the **fingerprints** of the membership schedule, FX evidence,
  corporate-action set, and rebalance schedule. It fails closed on an empty universe, a duplicate
  economic instrument, or an instrument naming a calendar the spec does not carry. Its aggregate
  `fingerprint` is order-stable and domain-separated.
- **`MarketPanel` / bars.** A bar frame is one instrument's completed OHLCV candles;
  `validate_bar_frame` enforces exactly the required columns, tz-aware UTC `open_time`/`close_time`
  with `open_time < close_time`, strictly increasing `open_time`, positive finite OHLC that bracket
  correctly, and non-negative finite volume — repairing nothing. A `MarketPanel` maps each
  `InstrumentId` to its validated frame; instruments may follow different calendars, so timestamps
  need not align and a missing bar is truly absent. The panel `fingerprint` binds each instrument's
  bar-frame fingerprint in identity-sorted order, independent of insertion order.
- **`TradingCalendar`** is one of three deterministic kinds: `continuous_24_7` (always open, no
  sessions), `session_list`, and `synthetic_weekday` (a fabricated Monday–Friday calendar built from
  arguments alone, no wall-clock read). Session-bearing calendars carry strictly-ordered,
  non-overlapping `Session` windows with tz-aware UTC open/close. The module claims no real-world
  holiday authority.
- **`MembershipSchedule`** collects causally-stamped `MembershipInterval`s. Each interval is a
  half-open `[effective_start, effective_end)` window with a separate `knowledge_time` that must not
  follow `effective_start`, so a decision at τ can only see a membership change once its knowledge
  time has passed. Per-instrument windows may not overlap; `active_universe(τ)` returns the
  instruments known and effective at τ.
- **`FxEvidence`** is a set of directed `FxObservation`s (rate = quote units per one base unit) with
  an optional predeclared triangulation map. `rate_as_of(base, quote, τ)` returns `1.0` for a
  same-currency conversion, else the most-recent direct rate at or before τ, else the explicit
  inverse pair as `1/rate`, else — only if the caller predeclared a single pivot for that exact
  directed pair — the `base → pivot → quote` product of causal legs. Nothing else is ever
  triangulated; there is no dynamic best-path search and no external FX source.
- **`CorporateActionSet`** collects causally-stamped `CorporateAction`s (each with `knowledge_time`,
  `effective_time`, and — for cash events — `payment_time`) for the four supported types. The set is
  carried as *evidence* and its fingerprint is bound into the universe and the result even though the
  engine does not yet apply the actions (see the causal-engine section).

## The causal engine

The engine (`engine.py`) executes one canonical ordering of operations at each rebalance timestamp τ.
That ordering — the contract that makes the simulator causally correct — is documented step by step
in [M4B_EVENT_TIMELINE.md](M4B_EVENT_TIMELINE.md); the summary here describes the mechanisms rather
than restating all eighteen steps.

**The information set (`AsOfView`).** At τ the engine reads through an immutable, defensively-copied
`AsOfView`. It exposes only causal inputs: the active membership universe known by τ, an
instrument's *completed* prior bars (`close_time ≤ τ`), the current bar's **open** (an execution
reference used to price fills, never a signal), and a causal FX rate. It never exposes the current
bar's high/low/close/volume or any future bar, FX, membership, or session result. Because the view
reads only a prefix of the evidence, appending a future fact cannot change any value it reports at an
earlier τ (prefix invariance).

**The shared-cash simultaneous solver.** Given the pre-trade base cash plus each holding's base value
`Vᵢ = qᵢ·pᵢ·fxᵢ` and long-only target weights `wᵢ` (summing to ≤ 1), `solve_shared_cash` finds the
single post-cost base equity `E_post` at which trading every asset to `wᵢ·E_post` at once, and paying
the resulting costs, exactly consumes the equity. It solves one shared pool for all assets, so the
outcome never depends on which asset "spends first" — it is **permutation-invariant** by construction.
The fixed point `E_post = E_pre − total_cost(E_post)` is found by deterministic bounded bisection on
`h(E) = E_pre − total_cost(E) − E`: because the cost parameters are validated *contractive*
(worst-case marginal rate below one), `h` is strictly decreasing with `h(0) > 0` and `h(E_pre) ≤ 0`,
so it has exactly one root, converged to a few ULPs of the pre-trade equity within the pinned
iteration cap. Post-trade cash `E_post·(1 − Σwᵢ) ≥ 0` and each post value `wᵢ·E_post ≥ 0` are
cash-safe and long-only by construction, and the solver asserts these invariants and the cash/equity
reconciliation before returning.

**The cost decomposition.** Every trade's cost is expressed in the base currency and decomposed into
named, separately-reported, non-negative components: `total_cost = fee + spread + slippage + impact +
fx_conversion`. Each is a function of the absolute base notional and predeclared parameters; the
impact term additionally uses a participation rate computed from *lagged* dollar volume (strictly
before the execution bar — never the current bar's volume), and its square-root form is capped. The
parameters are validated at construction to be jointly contractive, which is exactly what lets the
solver prove its fixed point is unique.

**Mark-to-market with staleness.** After fills, each holding is marked at a bar close and translated
to the base currency at the FX rate **as of that close** (the spec's "apply close FX" step). An
instrument trading this step is marked at its own bar's `close[t]` — both the close price and the
close-time FX — matching the accepted single-asset convention; a held-through instrument with no bar
opening at τ is carried at the latest completed close at or before τ (and its close-time FX), while
the `StalenessPolicy` still permits, else the mark is **refused**. Because the mark is a report taken
*after* all fills and consumed only at the *next* event — by which time that close is in the past —
it is causal for consumption and never an input to τ's own decision: the fills themselves price and
convert at the FX as of the execution time τ. A consequence worth stating plainly is that a holding's
end-of-step (and hence the run's terminal) value reflects the close-time price and FX of its final
bar, exactly as an end-of-period mark-to-market NAV does — not the FX as of the last rebalance. The
ledger (`accounting.py`) holds quantities, not values; valuation supplies the causal marks, and
`PortfolioState.apply_fill` fails closed if a transition would take cash or any holding below zero
beyond the pinned tolerance.

**Additive P&L attribution.** Between two events the equity change is decomposed exactly:
`equity_change = local_price_pnl + fx_translation_pnl + action_cash − cost + residual`. For each
held-through instrument the local-price term is `qty·(close_after − close_before)·fx_before` and the
FX-translation term is `qty·close_after·(fx_after − fx_before)` — the standard first-order local/FX
split — retained per asset and rolled up per currency. The residual is the *honest remainder*: it is
zero within tolerance for a held-through step and captures the open→close execution move on newly
traded quantity on a step that trades. `action_cash` is a first-class additive term that is `0.0`
today because corporate actions are not yet applied.

**One shared core.** `run_event` is the single accounting core. The batch driver
(`run_portfolio_simulation`), the streaming driver (`stream_portfolio_simulation`), and the resume
driver (`resume_portfolio_simulation`) all call it over the same loop-carried `StepCarry` (accounting
state plus the previous event's marks, local closes, FX legs, and equity baseline). Because that
carry fully determines every future event, the three interfaces produce byte-identical events, fills,
states, result bytes, and final-state hash, and a checkpoint resumes to a byte-identical continuation.

**Stated limitation — corporate actions are refused in-window, not applied.** Timeline steps 3–4
(split / reverse-split quantity adjustments and dividend / delisting cash payments) are deliberately
deferred. Rather than silently misstate quantities and cash, the engine **fails closed**: when a
`CorporateActionSet` is supplied, `run_portfolio_simulation` refuses the run if any action's
application time — a split/reverse-split `effective_time`, or a cash action's `payment_time` — falls
within `[first_event, last_event]` for a panel instrument. A window carrying no such action proceeds
normally, and the action set's fingerprint is still bound into the universe and the result.

## Result and provenance

**`PortfolioResult`** (`result.py`) is the strict, canonical, self-identifying record of one run. It
binds, by fingerprint, every piece of evidence the run was produced against — `universe_fingerprint`,
`panel_fingerprint`, `protocol_fingerprint`, `membership_fingerprint`, `fx_fingerprint`,
`corporate_action_fingerprint`, `schedule_fingerprint`, and each calendar's fingerprint — together
with the base currency, the initial and terminal equity, the descriptive `PortfolioMetrics`, the
per-asset and per-currency attribution totals, the total cost, the fill count, a size-bounded
`TraceCommitment`, the run-result fingerprint, and the final-state fingerprint. Its `result_id` is a
domain-separated content hash over all of that — deterministic and reproducible, with **no wall-clock
timestamp, no absolute path, and no reference to any gate, holdout, or split**.

**`TraceCommitment`** (`trace.py`) commits to the full ordered event trace in O(1) size: a
domain-separated hash **chain** folded over every event digest (so dropping, reordering, or editing
any event changes the aggregate), the exact `event_count`, the first and last event identity, and a
bounded, deterministic set of evenly-spaced sampled digests (capped at `DEFAULT_MAX_SAMPLES = 64`).
The chain is the integrity mechanism; the samples are a human-readable window.

**Build and verify are symmetric and strict.** `build_portfolio_result` assembles the artifact from a
run and its metrics, cross-checking that the run's own fingerprints agree with the bound universe.
`verify_portfolio_result` is the full-graph verifier: it re-derives the per-asset totals and the
trace commitment from the run, re-checks every bound identity against the universe and the run, and
confirms the attribution roll-ups telescope to `terminal − initial` equity.
`PortfolioResult.from_mapping` is the symmetric parser — it rejects unknown or missing keys,
NaN/Infinity, booleans-as-ints, a `per_currency` that disagrees with the per-asset totals, and any
internally inconsistent cost/fill/attribution total.

## Scenario batch runner, public API, CLI, and replay

**Scenario batch runner (`scenarios.py`).** A `Scenario` is a fully self-contained research load (a
universe plus its panel, protocol, membership, FX, schedule, calendars, and optional corporate
actions). `run_scenario_batch` runs a sequence **sequentially and deterministically** — no threads,
no wall clock, no randomness, no shared mutable state — and returns each scenario's `PortfolioResult`
plus an order-sensitive `batch_fingerprint` over the ordered `(name, result_id)` pairs. Parallel
execution is deliberately deferred. Each scenario's metric annualization basis is derived from its own
universe's bar interval, so the caller supplies no timing.

**Additive v1.1 public API (`public_api.py`).** The M4B surface adds new value models and pure
functions on top of the accepted M4A v1.0 API without changing any v1.0 name. `build_snapshot`
snapshots both layers — the running `eth_research.api.__all__` (v1.0) and the new M4B symbols — into
`research/m4b/public_api.json` keyed by `M4B_API_VERSION = "1.1"`. Two guards protect the contract:
`verify` fails closed when the committed snapshot no longer matches the running package, and
`verify_additive` fails closed when the v1.0 layer no longer byte-matches M4A's committed
`research/m4a/public_api.json`. The M4A snapshot is read, never written.

**Offline CLI (`cli.py`).** A small, non-interactive command group stacked additively on the accepted
M4A CLI, mirroring its argparse structure, exit-code convention, and `--json` determinism. Every
command is **read-only** — it computes and prints, and never writes a file: `universe inspect`
(print the reference universe's identity or full spec), `universe validate` (re-validate a canonical
`UniverseSpec`, or `--demo` the built-in one), `portfolio demo` (alias `portfolio run`; run the
reference universe end to end and print the result identity or full result), and `portfolio verify`
(strict-parse a canonical `PortfolioResult`, where the parse *is* the verification). Human text is
the default and deterministic canonical JSON is emitted on `--json`; exit codes are stable (`0`
success, `2` usage, `4` a failed canonical validation, `70` an unexpected internal error). No
network, credential, telemetry, dynamic code, or wall-clock read enters the output.

**Offline replay verifier + read-only CI.** `python -m eth_research.portfolio.replay --check`
regenerates the synthetic reference universe from code and runs five checks in order: two batch runs
are byte-identical (determinism), streaming reproduces the batch events, checkpoint/resume reproduces
the batch result byte-for-byte, the result artifact builds and verifies, and the committed v1.1 API
snapshot is current and additive. It is fully offline and read-only. The `.github/workflows/`
`m4b-replay.yml` workflow (`contents: read`, SHA-pinned checkout, authoritative CPython 3.12.3 under
a locked `uv` environment) runs the portfolio test suite, the replay verifier, and the public-API
`--check`, and asserts that the three sealed access ledgers stay byte-empty throughout — no secrets,
no writes, no uploads, no publish, no market host.

## Marking convention and single-asset reduction

**Marking convention.** A rebalance step at τ executes at the bar opening at τ and then marks that
holding at *its own bar's close* — `close_time` is the end of the step's bar — exactly as the
accepted single-asset engine marks bar `t` at `close[t]`. This end-of-step mark is a *report*: it is
computed after all fills and is consumed only at the next event (by which time that close is strictly
in the past), so it is never an input to τ's own decision and introduces no look-ahead. A
held-through instrument with **no** bar opening at τ (a market closed at τ per its calendar, or one
that has left the universe) is instead valued at its latest completed close at or before τ — carried,
not force-liquidated — and only while the staleness policy still permits; an over-stale carry is
refused.

**Why single-asset M4B reduces to the accepted fractional engine.** For a one-instrument,
one-currency, continuous-calendar universe under compatible cost settings, M4B reproduces the accepted
fractional engine's holdings, cash, fills, equity, and costs within the accepted binary64 ULP
tolerance. Three properties make this hold: the marking convention is identical (bar `t` valued at
`close[t]`); the shared-cash solver bisects the equity fixed point down to a few ULPs of the equity
(tighter than the reconciliation tolerance) so the single-asset target is resolved essentially
exactly; and `CostParameters.compatibility_v1` pins the exact fee (0.1%) and base-slippage (0.05%)
settings the accepted M4A/M3B compatibility oracle uses, over the same pinned tolerances
(`tolerances.py` mirrors the accepted engine's). The single-asset compatibility oracle in the test
suite (exercised by `m4b-replay.yml`) is what proves the reduction; structural, provenance, and
accounting identities are exact, and only the named floating-point fields carry the narrow ULP
tolerance.
