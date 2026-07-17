# M4B limitations

This document states, plainly and without softening, what the Milestone 4B portfolio simulator is
*not* and what it does *not* do. M4B is a research instrument: it makes the accounting, causality,
and provenance of a multi-asset long-only rebalance auditable over synthetic or caller-supplied
evidence. It is not a trading system, not a strategy, and not a source of real-market claims. The
constraints below are deliberate design boundaries, not defects; where a capability is deferred it
fails closed rather than approximating. See [M4B_DESIGN.md](M4B_DESIGN.md) for the architecture,
[M4B_PLAN.md](M4B_PLAN.md) for scope, and [M4B_EVENT_TIMELINE.md](M4B_EVENT_TIMELINE.md) for the
causal ordering.

## Simulation-only and offline-only

M4B never contacts a network, an exchange, a wallet, or a broker. There is **no** live or paper
trading, no order routing, no broker or exchange calibration, no exchange credentials, no wallet or
transaction signing, no transaction creation, and no runtime network client anywhere in the package.
Everything it consumes is either synthetically generated in-process or supplied by the caller as
local evidence, and every artifact it emits is a local canonical-JSON file.

A `Fill` is an **inert simulation record** — an immutable accounting row describing a hypothetical
executed trade in local and base-currency terms. It carries no venue connection, no order id, and no
routing path; it cannot be sent anywhere, and nothing in the package can turn one into a real order.

## The reference policies are plumbing, not alpha

The three reference allocation policies — `cash` (hold everything as base cash),
`static_equal_weight` (`1/N` over the active tradable set), and `static_declared_weights` (the
caller's fixed weights over the active set) — exist to exercise the accounting, solver, and
attribution machinery against hand-computable numbers. They make **no alpha claim**. There is no
predictive strategy, no parameter tuning, no fitting to data, and no optimizer, grid, Bayesian,
genetic, or machine-learning search anywhere in the milestone. The weights are fixed by declaration
or by a trivial `1/N` split, and the CLI never loads caller-named strategy code.

## Long-only, cash-safe, fully-funded

The accounting is structurally long-only and cash-safe: target weights are constrained to `[0, 1]`
with gross ≤ 1 and a base-currency cash residual, the shared-cash solver produces non-negative
post-trade cash and non-negative post-trade holding values, and every ledger transition fails closed
if it would drive cash or a holding negative beyond a pinned float tolerance. Consequently there is
**no leverage, no borrowing, no margin, and no shorting**, and **no derivatives of any kind** —
futures, options, swaps, perpetuals, CFDs, and leveraged tokens are all out of scope, and non-spot
instrument types are rejected at construction. A portfolio can never go gross above one or hold a
negative quantity.

## Instantaneous base-currency settlement is a research abstraction

Trades and marks convert between the quote and base currency at the causally-available FX rate as a
single instantaneous step. This is a **documented research abstraction**, not a model of a real
broker cash account: there is no settlement latency, no per-currency cash sub-account, no wire or
custody delay, and no financing of an FX position. It is a simplification appropriate to an offline
accounting simulator and should not be read as a claim about real-world execution or settlement.

## Membership handling mitigates but does not eliminate survivorship bias

Modeling universe membership explicitly — causally-stamped listing, addition, removal, delisting, and
data-availability windows — removes the bias that would come from treating a delisted or
not-yet-listed instrument as tradable. It **cannot** correct a caller-supplied dataset that silently
omits the instruments that failed: if the evidence never mentions a delisted name, no schedule can
resurrect it. Survivorship-free results still require survivorship-free inputs; M4B makes the
membership assumption auditable, not automatically correct.

## The synthetic reference universe is a test fixture, not real data

`build_reference_universe` is a seeded, code-generated fixture, explicitly marked "synthetic test
fixture — not real market data" throughout. Every timestamp is a fixed UTC literal and every price,
volume, and FX rate is a fixed seeded constant; nothing reads a wall clock, a network, or a random
source. **No accepted real ETH dataset is used for any M4B financial experiment.** The reference
universe exists to exercise the full M4B surface in miniature and to make the replay verifier
reproducible — it is not, and does not claim to be, representative of any real market.

## Costs are illustrative, not venue-calibrated

The cost model decomposes each trade into fee, half-spread, base slippage, lagged-liquidity impact,
and an optional FX-conversion charge, all in the base currency. The parameters are **illustrative
synthetic scenarios**, validated only to be non-negative and jointly contractive (so the shared-cash
equity solve has a unique fixed point). They are **not** calibrated to any real venue's fee schedule,
spread, or market-impact curve, and the numbers they produce are not estimates of real trading cost.

## Corporate actions are limited — and, for now, evidence-only

Corporate-action support covers exactly four types — `split`, `reverse_split`, `cash_dividend`, and
`delisting_cash_out`. Rights issues, spin-offs, stock dividends, mergers, and dividend withholding tax
are deliberately **unsupported** rather than approximated.

Beyond that vocabulary limit, there is a further, stricter constraint that must not be glossed over:
the engine does **not yet apply** corporate actions at all. The four supported types are validated,
fingerprinted **evidence** that binds into the universe and result identity, but quantity adjustments
(splits/reverse-splits) and cash payments (dividends/delistings) are deferred to a later milestone.
Rather than misstate quantities or cash, `run_portfolio_simulation` **fails closed** on any supplied
action whose application time falls within the run's event window for a panel instrument. A run is
therefore only admitted when its schedule window carries no pending action; the attribution term
`action_cash` is consequently `0.0` in every current result.

Relatedly, the rebalance contract only trades instruments that are tradable at the event τ (an active
member with a bar opening at τ and a causal FX rate). A held instrument whose market is closed at τ,
or that has left the universe, is carried and marked — never force-liquidated and never force-traded.
Partial-universe rebalancing beyond this is a documented deferred extension.

## FX uses explicit, predeclared evidence only

Currency conversion is causal and conservative. `rate_as_of` returns `1.0` for a same-currency
conversion, the most-recent direct observation at or before the decision time, or the *explicit*
inverse pair as `1/rate`. Any indirect conversion requires the caller to **predeclare a single
pivot** for that exact directed pair; the engine then computes `base → pivot → quote` from causal
legs and nothing else. There is **no dynamic best-path search**, no implicit `1:1` fallback except
same-currency, and **no external FX API** — an unbounded search over pivots would make a rate depend
on an arbitrary, unstated choice of intermediary, and that is refused. A missing or over-stale rate
fails the run rather than being invented.

## Cross-runtime reproducibility carries a narrow, named tolerance

Structural, provenance, and accounting identities are **exact**: canonical JSON is byte-identical
across runtimes, every fingerprint and `result_id` is a domain-separated SHA-256 over those bytes,
and the checkpoint/trace hash chains reproduce exactly. The engine's decisions and topology (which
instruments trade, the fill sides, the event ordering) are identical everywhere. The **only** latitude
is in the named floating-point value fields (equity, cash, costs, attribution terms, marks): across
CPython runtimes these may differ by at most a narrow, finite binary64 ULP amount from the same
arithmetic evaluated differently. That tolerance is explicitly bounded and tested; it is never a
license to pass a run that differs in any structural, provenance, or accounting identity.

## Descriptive metrics only

`PortfolioMetrics` reports descriptions of the run's own equity curve and event evidence — returns,
drawdown, exposure and concentration summaries, cost drag, attribution roll-ups, and staleness counts.
It deliberately reports **no** alpha, beta, information ratio, factor loading, significance test,
optimization objective, or value-at-risk sold as a guarantee. Every scalar reconciles from the event
records, and any ratio that is undefined for a run is reported as `null`, never as a fabricated or
non-finite number.

The reported `terminal_equity` is a mark-to-market value (each holding at its final bar's close price
and FX). It is **not** net of the cost of actually liquidating those holdings: the simulator never
force-liquidates, and it does not report a separate *hypothetical liquidation* value. Doing so
faithfully would require choosing a hypothetical-exit liquidity model (the participation and
market-impact of unwinding the whole book at once), which is a modeling decision this offline
accounting simulator deliberately leaves to the caller rather than fixing to a possibly-misleading
default. Reporting a hypothetical liquidation value is a documented deferred extension.

## Deferred CLI subcommands — the Python API is the complete surface

The offline command group (`universe inspect|validate`, `portfolio demo|run|verify`) is read-only by
design: it computes and prints, and never writes a file. The plan also lists a `universe build` and a
`portfolio resume` subcommand; these are deferred. `portfolio resume` consumes a
`PortfolioCheckpoint`, but a read-only CLI has no path to *produce* one (that would require file
output, with the governed-path and transactional-write machinery that the read-only posture avoids),
so checkpoints are produced and consumed through the Python API
(`stream_portfolio_simulation` / `resume_portfolio_simulation`), which is complete and tested.
`universe build` is likewise deferred: a research universe is constructed in code (or parsed from a
canonical `UniverseSpec` via `universe validate --in`), not assembled from CLI flags. Neither
deferral removes any capability — the full simulate / stream / resume / build / verify surface is
available and covered through the public API.
