# v1.0.0 limitations

This is an honest, complete statement of what the v1.0.0 release candidate does
**not** do. These are deliberate scope boundaries and known gaps, not defects to
be worked around.

## No license yet — not publishable

The repository ships **no `LICENSE` file**. Without one, the distribution is
**not cleared for public or PyPI upload**, and there is intentionally no PyPI
release. Install from a locally built wheel only
(see [INSTALLATION.md](INSTALLATION.md)). Do not invent or add a license to work
around this; it is a tracked limitation.

## Offline only — no live data

There is no network client anywhere in the package: no exchange connectivity, no
authentication, no wallet, no order routing, and no market-data download. The
platform operates only on historical OHLCV data from local files or the
deterministic synthetic generator. There is no live or streaming data path, and
none is planned within this scope.

## No live trading

By design there is no leverage, shorting, margin, or derivatives, and no way to
place an order or move funds. The binary engine is long/cash only; the
fractional engine is long-only with exposure bounded to `[0, 1]`. This is a
research and evaluation tool, not a trading system.

## No optimizer, no ML, no parameter search

The platform runs the backtest you specify and reports its metrics. It does
**not** provide hyperparameter search, grid or random search, walk-forward
optimization, gradient methods, or any machine-learning model or training loop.
Choosing parameters and interpreting results is the researcher's job — done
deliberately, so a cost-free or overfit number can never be produced automatically.

## No new strategies beyond the built-ins

The shipped strategy set is closed: four binary built-ins (`buy_and_hold`,
`cash`, `moving_average_crossover`, `donchian_channel`) and five fractional
built-ins (the `FRACTIONAL_STRATEGY_KINDS`, with no free parameters). The CLI
and the run config accept **built-in kinds only**. Custom strategies are
available for the **binary** engine through the Python API (a `Strategy`
subclass); there is no public extension point for custom **fractional**
strategies in this release (see [CUSTOM_STRATEGIES.md](CUSTOM_STRATEGIES.md)).

## Custom strategies are trusted, not sandboxed

A custom `Strategy` passed to the Python API is trusted caller code. It runs
in-process with your privileges and is **not sandboxed**. There is no plugin
loader, no dynamic import from a path, and no `eval`/`exec` — but equally, there
is no isolation. Never run a strategy object from an untrusted source
(see [SECURITY_MODEL.md](SECURITY_MODEL.md)).

## Single-process

Execution is single-process and in-memory. There is no built-in parallelism,
job scheduler, distributed execution, or persistent run database. Each run is an
independent invocation that publishes a self-contained bundle.

## Cost model is a research proxy

The fractional liquidity-and-impact cost settings are a deterministic causal
research proxy driven by lagged daily dollar volume — **not** a calibrated venue
model. With daily OHLCV and no order-book data, they are transparent and
reproducible but are not an estimate of real execution cost on a live venue
(see [COST_MODEL.md](COST_MODEL.md)).

## Cross-platform byte-identity is not a blanket claim

Results and builds are deterministic and reproducible for a fixed dependency
stack on a given platform. Byte-for-byte identity **across operating systems**
(for example between Linux, macOS, and Windows) is only claimed where it has
actually been demonstrated. It is not asserted here as a general guarantee for
macOS or Windows (see [REPRODUCIBILITY.md](REPRODUCIBILITY.md)).

## Data scope

Validation and the built-in flows are oriented to regularly spaced OHLCV candles
(the demos and cost scenarios use daily bars). The schema is strict and never
repairs data: it rejects gaps, unsorted rows, and timezone-naive timestamps
rather than silently fixing them (see [DATA_CONTRACT.md](DATA_CONTRACT.md)).
