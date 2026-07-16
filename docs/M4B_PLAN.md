# Milestone 4B — Multi-Asset, Multi-Venue, Multi-Currency Portfolio Research Simulator 1.1

Stacked on the accepted M4A offline research platform (base branch
`claude/m4a-offline-research-platform-rc`). This plan is the first M4B commit and the durable
state of record; if context compacts, resume from here plus the committed commits.

## 1. Problem statement

M4A gave a trustworthy single-asset offline backtest platform. M4B generalizes it into a
general, offline, causally correct **multi-asset portfolio research simulator**: multiple
instruments across multiple venues quoted in multiple currencies, valued in one explicit base
currency, with crypto-spot / cash-equity / fx-spot asset classes, explicit calendars,
listings/delistings, explicit corporate actions, explicit FX evidence, synchronized rebalances
into long-only fractional target weights with residual cash and a shared cash pool, a
deterministic simultaneous shared-cash solver, transparent cost decomposition, mark-to-market
accounting with staleness, additive P&L attribution, batch/streaming equivalence,
checkpoint/resume, strict provenance, a typed public API, a CLI extension, and backward
compatibility with the accepted v1.0 single-asset API.

## 2. Scope

Version `1.1.0`. Branch `claude/m4b-multi-asset-portfolio-simulator`, head stacked on M4A.
New isolated package `src/eth_research/portfolio/`, new governed root `research/m4b/`, new
read-only CI `.github/workflows/m4b-replay.yml`. Simulation-only, offline-only, deterministic,
synthetic-or-caller-supplied evidence only. The reference allocation policies (`cash`,
`static_equal_weight`, `static_declared_weights`) are accounting/plumbing benchmarks — **no
alpha claim, no new predictive strategy, no parameter tuning, no optimizer/ML**.

## 3. Exclusions (hard boundaries)

No live/paper trading, order routing, broker/exchange calibration, exchange credentials,
wallet/signing, transaction creation, runtime network client. No leverage, borrowing, margin,
shorting, derivatives, futures, options, swaps, perpetuals, CFDs, leveraged tokens. No
optimizer/grid/Bayesian/genetic/ML. No new predictive strategy. No accepted real-ETH data used
for M4B financial experiments. No M3E activation, prospective fetch, production proposal, M3D
mutation, M3C re-execution, gate/holdout access, sealed-ledger append. No merge / undraft /
retarget / tag / release / publish / branch-delete / history-rewrite. No M4C.

## 4. Market-data model (§9)

Canonical multi-asset bar: `open_time`, `close_time` (tz-aware UTC, `open_time < close_time`),
`open/high/low/close` (finite, positive, OHLC-consistent), `volume` (finite, ≥0),
`instrument_id`. Per instrument: strictly increasing, non-overlapping bars; no auto-sort, gap
repair, fill, resample, or silent tz-localization; extra columns rejected unless allowed; bars
outside membership / before listing / after delisting rejected (unless explicitly retained as
non-tradable history). A `MarketPanel` is an immutable mapping `InstrumentId -> BarFrame`
supporting asynchronous calendars without pretending absent bars are zero returns. Panel
fingerprint binds universe identity, every instrument identity, every timestamp+OHLCV
(canonical float repr), membership, calendar, FX-evidence, and corporate-action evidence
identities, domain-separated.

## 5. Instrument identity (§7)

Immutable `InstrumentId(asset_class, base_asset, quote_currency, venue, symbol, instrument_type,
price_unit, quantity_unit, calendar_id)`. `asset_class ∈ {crypto_spot, cash_equity, fx_spot}`;
derivatives/margin/leveraged explicitly unsupported. Exact vocabulary, safe normalized
non-empty strings (no path/control chars), currency-like codes uppercase + structurally
validated (no false ISO-authority claim), `base_asset != quote_currency` where meaningful,
venue+symbol required but symbol never trusted as global identity. Canonical identity JSON and
a domain-separated `instrument_id` hash; no filename/ticker-only identity, no silent remap, no
truthiness coercion.

## 6. Universe identity (§8)

Immutable `UniverseSpec` binding: schema version, base accounting currency, canonical ordered
instrument list, calendar identities, membership schedule identity, FX requirements,
corporate-action evidence identity, bar-interval contract, valuation policy, staleness policy,
rebalance-schedule identity, provenance algorithm id. Canonical instrument ordering; duplicate
economic instruments rejected; duplicate symbols across venues allowed only via distinct full
identity; missing/circular FX path rejected; unsupported asset class rejected; empty universe
rejected; aggregate fingerprint order-stable + domain-separated (reordering inputs → identical
identity; changing one economic identity → different fingerprint). Strict JSON round-trip.

## 7. Calendar / session model (§10)

Three calendars: (1) continuous 24/7; (2) explicit session-list; (3) deterministic synthetic
weekday-session (tests/demo). No authoritative-exchange-holiday claim. Session record binds
id/date, open UTC, close UTC, optional early-close flag, source. No overlaps, strict ascending,
open<close, explicit tz→UTC before serialization, no inferred holidays, no wall-clock/internet.
Bar must fit its declared session; a missing expected-session bar is an error; a closed session
requires no bar; calendar change → identity change; DST tested with fixed UTC session evidence.

## 8. Currency / FX model (§12)

Configurable base currency (USD in synthetic references). FX rates as identified `fx_spot`
instruments / strict `FxEvidence`. Explicit pair direction, positive finite rates, tz-aware
observations, causal as-of lookup (no future rate). Trade-open uses the FX open at that
execution event (or earlier permitted); close valuation uses the FX close known at that
valuation time. Missing/over-stale rate fails. Inverse explicit + tested. Triangulation, if
supported, uses a unique predeclared path; ambiguous paths rejected; no dynamic best-path, no
external FX API, no implicit 1:1 except same-currency. FX conversion cost modeled separately if
enabled. All result values report currency. Instantaneous base-currency settlement is a
documented research abstraction, not a broker cash-account model.

## 9. Corporate-action model (§13)

Cash-equity actions: split, reverse split, cash dividend, explicit cash-out/delisting payment.
Complex rights/spin-offs/stock-dividends/mergers/withholding unsupported. Each action binds
schema version, instrument id, action id, type, knowledge time, effective time, payment time
(where applicable), split ratio or cash amount, currency, source. Causal: strategy knows an
action only after `knowledge_time`; accounting applies it only at its explicit effective/payment
event; future action mutation cannot alter earlier signals/fills/holdings/cash/equity. Split
before same-time trading only if the protocol states it; dividend uses a precise ex/record
convention; payment credited only at payment time; FX at payment causal; no auto-reinvestment;
no adjusted-price magic; caller declares raw/unadjusted; adjusted-price + separate actions
rejected (double-count guard). Corporate-action fingerprint bound into results. Literal
hand-calculated tests for 2:1 split, 1:5 reverse, dividend, split+rebalance, foreign-currency
dividend, delisting cash-out, missing action, duplicate action, future-known mutation,
double-adjusted rejection.

## 10. Universe membership & survivorship (§11)

Membership interval binds instrument id, effective start, effective end/open-ended, knowledge
time, reason ∈ {listing, constituent_addition, constituent_removal, delisting,
data_availability_boundary}, source. Knowledge time can't follow a decision using it; intervals
per instrument non-overlapping; membership can't precede listing; a target can't allocate to an
inactive instrument; removal handled by explicit terminal policy (never silent −100% nor
carried forever); future membership changes can't alter past eligible universes/targets/fills;
universe can't infer membership from "data survived." Results bind the membership fingerprint.
Documented: explicit membership mitigates but doesn't eliminate survivorship bias in
caller-supplied data.

## 11. Causal information timeline (§14)

One canonical event ordering at execution timestamp τ (documented in
`docs/M4B_EVENT_TIMELINE.md`):
1 verify fingerprints; 2 determine membership known by τ; 3 apply corporate actions effective
before open; 4 apply cash payments due before open; 5 establish tradable set; 6 read current
opens (fills only); 7 read causal FX opens; 8 compute target weights from info strictly before
τ (current open permitted only as execution reference, never a signal input); 9 solve
simultaneous post-cost target; 10 generate deterministic fills; 11 deduct
fee/spread/slippage/impact/FX cost; 12 assert cash & holdings invariants; 13 mark assets at
causally available closes; 14 carry prior marks only when calendar says closed and staleness
permits; 15 apply close FX; 16 record attribution + commitments; 17 emit checkpoint; 18 only
after close info exists may it influence a future decision.

## 12. Information set / causality (§15)

`AsOfView` exposes at τ: prior completed bars, active universe known by τ, corporate-action
facts with knowledge ≤ τ, lagged liquidity, prior volatility, prior FX closes, current
execution-event identity; **not** current high/low/close/volume, future membership/action/FX,
or future session result. Immutable views / defensive copies. Tests: prefix invariance;
future bar/FX/action/membership mutation inertness; current-close mutation can't change current
open fill; current high/low/volume can't reach target calc; same-open cross-asset future
leakage impossible; asynchronous closed-market data can't leak; context → zero P&L;
checkpoint/resume doesn't widen information. Poison forbidden columns.

## 13. Portfolio target contract (§16)

Long-only weights: one per active instrument, finite, ∈[0,1], Σ≤1 within pinned tolerance,
residual = base cash; inactive can't get positive weight; no missing active weight (unless
protocol defines missing≡0); no duplicate; canonical ordering; immutable. No negative weight,
gross>1, borrowed cash, synthetic short, leverage, offsetting long/short. Fixed reference
policies only: `cash`, `static_equal_weight`, `static_declared_weights` (plumbing, not alpha).
Adapters may let accepted per-instrument strategies supply long-only components via the Python
API — but no new strategy, no tuning, no accepted-real-data eval, no CLI dynamic code loading.

## 14. Rebalance schedule (§17)

`RebalanceSchedule`: fixed explicit timestamps; deterministic calendar rule (synthetic/local);
initial allocation event. No wall-clock scheduler/daemon/cron/live loop. Strict rule: a
rebalance executes only when every instrument whose target would change has a valid tradable
open and a valid causal FX rate. M4B's honest contract: **require common rebalance timestamps**
(every changing instrument tradable at τ), allowing asynchronous valuation between rebalances.
If a desired common event is missing → fail explicitly (partial-universe rebalancing is a
documented deferred extension, not improvised). Schedule identity bound into results.

## 15. Shared-cash simultaneous solver (§18)

Given pre-trade base equity E_pre, base asset values V_i, target weights w_i (Σ≤1), post-cost
equity E_post, desired base values w_i·E_post, trade notional w_i·E_post − V_i, and costs that
depend on absolute trade notional + predeclared causal inputs, solve the fixed point
`E_post = E_pre − total_cost(trades(E_post))` with a deterministic bounded bisection: explicit
lower/upper bounds, pinned tolerance + max iterations, validated monotone cost, unique-solution
requirement, fail on non-monotone/invalid cost. Permutation-invariant (no asset-order / "first
asset spends cash" bias); cash reconciles; no negative cash/quantity beyond tolerance; no gross
>1; zero-target exits when tradable; all quantities finite. Oracles: zero-cost closed form,
one-asset compatibility, two-asset hand, permutation over all small-universe orderings. Not a
general optimizer.

## 16. Cost model (§19)

Per fill components: fee, half-spread, base slippage, lagged-liquidity impact, optional FX
conversion cost — each nonnegative, finite, causally available (impact uses only lagged volume
strictly before execution; never current-bar volume), separately reported, from predeclared
params, reconciled, currency-labelled. `total_cost = fee + spread + slippage + impact +
fx_conversion_cost` at fill/asset/event/portfolio levels. No rebate. Illustrative synthetic
scenarios only; not venue-calibrated.

## 17. Accounting ledger, valuation, attribution, metrics (§20–23)

Immutable `Fill` + `PortfolioState` records with the full field sets in §20; invariants every
event (cash ≥ −tol, qty ≥0, finite, equity = cash + Σ base position values, exposure ≤1+tol
after rebalance, exact cost identities within binary64 tol, immutable ledger, domain-separated
state hash, unique event ids, nondecreasing timestamps, fills canonically ordered independent
of input order). No terminal force-liquidation; report a hypothetical liquidation value
separately. Valuation: close known by timestamp + causal FX; carry prior mark only if calendar
confirms closed and staleness permits; refuse over-stale; never backfill from a future close.
Attribution is exactly additive: `equity_change = Σ local_price_pnl + Σ fx_translation_pnl +
Σ dividend_and_action_cash − Σ cost_components + residual` with residual ≡0 within pinned
tolerance (never hidden). Metrics retain accepted portfolio metrics + descriptive non-alpha
additions (gross exposure, cash weight, max weight, HHI, avg held assets, per-asset/per-currency
contribution, cost drag, dividend/FX contribution, stale-mark count/duration). No alpha/beta/IR/
factor/significance/optimization/VaR-as-guarantee. Every scalar reconciles from event evidence.

## 18. Batch/streaming equivalence + checkpoint/resume (§24–25)

Two interfaces over one accounting core: batch over a complete local panel, and incremental
local step iteration ("streaming" = deterministic local, not networked). Same events/fills/
states/results/report bytes/receipt bytes/final state hash. Strict canonical-JSON checkpoint
(no pickle/code/untrusted deserialization) binding schema version, all input fingerprints,
schedule hash, next event index, cash/holdings/marks/FX marks, cumulative costs/action-cash/
attribution, prior event hash, checkpoint hash; refuses wrong fingerprints/protocol/event
substitution/modified holdings/modified hash/rollback (unless a fresh sim); resume byte-identical;
no future data; no accepted-ledger mutation. Status + recovery CLIs for local M4B outputs only.

## 19. Result schema + provenance (§26–27)

Strict `PortfolioResult` with schema/package versions, protocol/universe/panel/FX/membership/
corporate-action/calendar/schedule fingerprints, base currency, initial/terminal + hypothetical
liquidation equity, portfolio metrics, per-asset & per-currency attribution, cost decomposition,
fills, event/state commitments (size-bounded), checkpoint lineage, runtime identity, deterministic
result id. No test/gate/holdout reference, no absolute paths, no current timestamp in the
deterministic id. Symmetric strict construct/parse that rejects lied totals, missing cells, extra
assets, reordered content, NaN/Infinity, bool-as-int, negative forbidden, contribution/cost
mismatch, wrong currency/universe/event-chain/checkpoint-lineage. `MarketDatasetManifest` +
`PortfolioRunManifest` bind all identities + hashes; one full-graph verifier; no optional param on
the canonical path skips a required evidence check.

## 20. Public API + CLI (§28–29)

Additive v1.1 public API (new models `InstrumentId`, `UniverseSpec`, `TradingCalendar`,
`MembershipSchedule`, `CorporateAction`, `FxEvidence`, `MarketPanel`, `PortfolioTarget`,
`PortfolioProtocol`, `PortfolioResult`, `PortfolioCheckpoint`; new functions
`validate_market_panel`, `build_market_panel`, `run_portfolio_simulation`,
`resume_portfolio_simulation`, `verify_portfolio_result`) — existing v1.0 symbols/signatures
unchanged, new params optional, no hidden behavior change. A v1.1 snapshot under `research/m4b/`
compared to (not mutating) M4A's v1.0 snapshot; classify additive. CLI extension:
`universe validate|build|inspect`, `portfolio run|resume|verify|demo` — offline, no telemetry/
network/credentials, strict config, deterministic `--json`, transactional output, overwrite +
governed-path refusal, no dynamic code, stable exit codes; demo synthetic-only; M4B CLI
reference generated separately (M4A's snapshot untouched).

## 21. Synthetic reference universe + hand oracles (§30–31)

Deterministic synthetic reference universe: one 24/7 USD crypto spot, one USD cash equity, one
EUR cash equity, EUR/USD FX evidence, explicit weekday sessions with one early close, one late
listing, one constituent removal, one 2:1 split, one cash dividend, one delisting cash-out, one
closed-market valuation, one lagged-liquidity cost event — seeded, code-generated, marked
"synthetic test fixture — not real market data", no large binary committed. Plus ≥20 separate
literal hand-calculated oracle scenarios (§31) whose expected numbers are computed by hand, not
by invoking the production solver.

## 22. Compatibility (§32)

For a one-instrument, one-currency, continuous-calendar universe with compatible cost settings,
M4B reproduces the accepted fractional engine's holdings/cash/fills/equity/costs/metrics within
the accepted exact/tolerance contract (differences only from explicit protocol differences).
The single-asset compatibility path maps to a fractional strategy with pass-through risk
(no vol-target/drawdown/turnover, max_exposure 1.0) and a static signal. Accepted M3B result
artifacts unchanged.

## 23. Trace commitments, JSON/file safety, security (§35–37)

Size-bounded trace: per-event domain-separated hash + deterministic aggregate (hash chain),
count, first/last identity, optional bounded samples, optional explicit local full trace
(transactional). Every parser strict (dup-key/non-finite/overflow reject, exact keys, no
coercion, bool≠number, trailing newline, UTF-8, size bounds, safe paths, no symlink-follow for
governed inputs, no unknown schema version, bounded errors). Every multi-file output
precomputed+validated+temp-in-dir+fsync+ordered-replace+marker-last+dir-fsync+readback+rollback.
Security firewall extended across src/tests/examples/tools/workflows: reject network/exchange/
wallet/web3/credential/dynamic-import/eval/exec/shell=True/generic-subprocess/live-paper-order/
leverage/short/margin/derivative/optimizer/ML/publish/tag-release/write-workflow/market-host.
Prove "fills" are simulation records that cannot be routed externally.

## 24. Testing, performance, replay, CI (§33–34, §39, §43–44)

Deterministic sequential scenario-batch API (parallel deferred unless deterministic and
low-risk). Performance guards: 2×1000, 10×10000, 50×5000 synthetic loads; solver iteration cap
enforced; bounded trace/checkpoint; no single unit test >30s; explicit subprocess timeouts; full
suite <30min. Focused test surfaces per §39 with construction/parse/future-mutation/prefix-
invariance/permutation-invariance/malformed/dup-key/non-finite/symlink/traversal/tamper/wrong-
fingerprint/missing-stale-evidence/partial-publication/resume-mismatch coverage.
`python -m eth_research.portfolio.replay --check` regenerates the synthetic universe+protocol,
runs batch+streaming+checkpoint/resume, compares all, verifies hand oracles + trace commitments
+ public-API snapshot + distribution manifest + no prior-artifact drift + ledgers empty + M3D/M3E
unchanged. Cross-runtime tolerance narrowly defined (named fields, finite binary64 ULP cap,
identical decisions/topology, documented+tested); structural/provenance/accounting identities
exact. `.github/workflows/m4b-replay.yml` (`contents: read`, SHA-pinned): authoritative-portfolio,
compat-portfolio (3.12/3.13), portfolio-security, installed-consumer — no secrets/write/upload/
publish/market-host.

## 25. E→R→P→Q freeze (§42)

E source-freeze (all source+tests+docs final, suite green, prior artifacts unchanged, M4A
compat green, reference scenarios green, red teams done, version 1.1.0). R deterministic
registration under `research/m4b/` (`public_api_v1_1.json`, `cli_reference.*`,
`reference_universe.json`, `reference_protocol.json`, `reference_expected_results.json`,
`distribution_manifest.json`, `source_freeze.json`; no executable-source change E..R; push +
CI green). P proof run of the synthetic reference scenarios only (reference/compatibility/batch-
streaming/checkpoint/distribution proofs; no accepted real dataset). Q post-proof red teams +
terminal docs; supersede-E discipline if source changes after E.

## 26. Commit plan (append-only, roughly one concern per commit)

1 plan · 2 version 1.1.0 · 3 portfolio validation+identity(currencies) · 4 instrument+universe ·
5 bars+panel · 6 calendar · 7 membership · 8 fx · 9 corporate-actions · 10 events+information-set ·
11 targets+schedule · 12 cost model · 13 solver · 14 accounting · 15 valuation+attribution ·
16 metrics · 17 engine(batch)+streaming · 18 checkpoint/resume · 19 result schema · 20 provenance+
verifier · 21 public API + snapshot · 22 CLI + reference · 23 synthetic reference universe ·
24 hand oracles · 25 compatibility · 26 trace commitments · 27 scenario runner + perf guards ·
28 security firewall extension · 29 replay + reconciliation CLIs · 30 m4b-replay.yml CI ·
31 docs set · 32 bug-hunt fixes · 33 red-team fixes · E freeze · R register · P proof ·
Q terminal audit. (Grouped/split as work lands.)

## 27. Hard stops (§47)

Per §47: unprovable accepted identity; M4A Class-A affecting accepted outputs; any Class D;
nonempty/changed sealed ledger; accepted-artifact change; M3C/M3D/M3E state change; production
proposal; gate/holdout access; accepted-real-data strategy run; prospective fetch; required
network/credentials; required leverage/short/derivative/borrow; private artifact packaged/
uploaded; write-capable workflow; required force-push/history-rewrite/tag bypass; accounting not
long-only/cash-safe without weakening invariants; cross-runtime replay passable only via broad
tolerance; source-freeze identity unrecoverable. Ordinary defects are not hard stops.

## 28. Terminal criteria (§45–46, §48–49)

Full local battery green; M4A v1 consumer + M4B v1.1 consumer pass; wheel/sdist private-data-safe
+ byte-identical double build; accepted artifacts unchanged; three ledgers empty before/after;
M3C rejected; M3D 3/365 unauthorized; M3E inactive; zero proposals; no network/leverage/short/
dynamic-strategy/real-data-M4B-result/tag; tree clean; branch == remote. Then a **draft** stacked
PR (base `claude/m4a-offline-research-platform-rc`, head M4B, not main), M4B CI terminal-success,
`docs/M4B_TERMINAL_AUDIT.md`, and ABSOLUTE FINAL STOP — nothing merged/undrafted/retargeted/
tagged/released/published/deleted; PR #9/#10/M4B remain open draft.
