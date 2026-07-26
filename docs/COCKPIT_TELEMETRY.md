# Reporting a paper run to Nardis Cockpit

Nardis Cockpit is a self-hosted, read-only dashboard for watching a trading process you already
operate. This document describes the optional integration between it and this repository's
signal-only shadow platform: what it sends, what it deliberately does not do, and how to run it.

The short version: **the trader cannot tell whether anyone is watching.** Turn Cockpit off, or
uninstall its client, or point it at a host that does not exist, and the loop produces the same
bars, the same fills, the same book, and the same journal.

## What this is not

- It is **not** live trading. The shadow platform has exactly three non-live modes
  (`synthetic_demo`, `historical_shadow`, `paper_simulation`), refuses any live/production mode
  fail-closed, and drives only its own non-routing paper adapter.
- It is **not** a paper-trading *activation*. The V2E activation gate
  (`python -m eth_research.v2.fable5 verify-paper`) still derives
  `paper_activation_authorized = false`, and nothing here touches it.
- It is **not** a control channel. Cockpit is receive-only from the trader's side. There is no
  endpoint, flag, or event that lets a dashboard change a signal, a limit, a size, or a decision.

## What the trader sends

Every value is one the shadow platform itself computed. Nothing is re-derived, re-priced, or
estimated by the reporting layer.

| Cockpit event | Source in the run |
|---|---|
| `heartbeat` | An independent worker thread, on the process's clock (see below) |
| `signal_generated` | The candidate's `SignalEnvelope` plus the `RiskDecision` the risk engine journalled |
| `trade_executed` | A `PaperFill`, identified by its journal entry hash |
| `position_updated` | The `PaperAccount` the fill left behind, at the rebalance price |
| `equity_updated` | `PaperAccount.equity(close)` — the fill's own equity on a fill bar, the held book's mark otherwise |
| `warning` | A `warning`-severity monitoring `Alert` (stale market data), or a slow trading cycle |
| `error` | A `critical`-severity `Alert` (drawdown breach, risk-limit breach, kill-switch trip) as non-fatal; a caught or uncaught trader exception as fatal |

Two deliberate omissions, both to avoid inventing numbers:

- **Fees are zero because there are none.** The paper book is a clean mark-to-market baseline;
  execution costs are a research-layer concept and are not modelled in it.
- **Realized and unrealized PnL are omitted.** The paper book holds cash and units and does not
  decompose them. A reporter that computed its own split would be a second accounting model.

For the same reason, `average_price` on a position is the close the book was rebalanced at — the
price those units were established at. The paper book tracks no cost basis, so there is no average
to report and none is fabricated.

## Heartbeats are tied to the process, not to the loop

Cockpit calls a bot offline when its last heartbeat is more than 90 seconds old. This platform's
loop is *bar-driven*: it can legitimately wait far longer than that between iterations. A heartbeat
emitted from inside the loop would therefore report a healthy trader as dead.

So `eth_research.cockpit.HeartbeatWorker` beats on its own clock, from one daemon thread that:
starts only after the trader has initialised; stops explicitly at shutdown; never blocks the loop;
never keeps the process alive; tolerates a Cockpit outage; refuses to start twice; and reports
uptime and the client's dropped-event count.

## Why the client is not in `pyproject.toml`

`nardis-telemetry` is installed **alongside** this package, not as a dependency of it. Two reasons,
both structural:

1. `eth_research.m3f.dependency_inventory` fails closed on any locked distribution whose source is
   not a hash-pinned registry artifact or this project's own editable install. A `git+https://`
   dependency has no such identity and is refused by design.
2. The default install stays network-free. `tests/test_repo_hygiene.py` AST-scans `src`, `tests`
   and `examples` for networking imports; `eth_research.cockpit` imports `nardis_telemetry` and
   nothing else, so the HTTP machinery lives entirely outside the scanned tree.

When the client is absent, `eth_research.cockpit` still imports, still type-checks, and reports
nothing. That is the supported way to run without Cockpit.

## Installing the client

Install the pinned client into the same environment as `eth-research`:

```bash
pip install "nardis-telemetry @ git+https://github.com/panfot1409/nardis-cockpit@ee51cd28e206157c85d8f1d19448685b6fb857de#subdirectory=clients/python"
```

The commit is pinned on purpose. A branch reference would let the wire contract change underneath a
running trader.

> **`uv sync` will remove it again.** Because the client is deliberately absent from `uv.lock`, a
> plain `uv sync --locked --all-extras` treats it — and its `httpx` dependency tree — as extraneous
> and prunes it. That is the documented setup command in `CONTRIBUTING.md` and the first step of
> every CI workflow, so on a developer machine it will bite. Either sync without pruning:
>
> ```bash
> uv sync --locked --all-extras --inexact
> ```
>
> or reinstall the client after each sync. Nothing breaks when it disappears — the trader simply
> stops reporting — which is exactly why this is worth writing down rather than discovering.

## Running it

Provision a bot on the Cockpit host and take the key it prints once:

```bash
python -m app.admin_cli create-bot --slug eth-paper-1 --name "Nardis ETH Paper"
```

Then run the operator with the key in the environment — never on the command line, never in a
committed file:

```bash
export NARDIS_COCKPIT_URL=https://cockpit.example.internal
export NARDIS_BOT_API_KEY=...      # the value the admin CLI printed
python -m eth_research.operate --interval 3 --bars 1200 --backfill 60
```

| Variable | Meaning | Default |
|---|---|---|
| `NARDIS_COCKPIT_URL` | Where Cockpit is | `http://127.0.0.1:8000` |
| `NARDIS_BOT_API_KEY` | This bot's ingest key. **Absent means telemetry is off**, which is not an error | unset |
| `NARDIS_TELEMETRY_ENABLED` | Set to `false` to run with telemetry off even when a key is present | `true` |
| `NARDIS_HEARTBEAT_INTERVAL_SECONDS` | Heartbeat cadence, clamped to 1–40s | `15` |
| `NARDIS_TELEMETRY_CONNECT_TIMEOUT` / `_READ_TIMEOUT` / `_MAX_ATTEMPTS` / `_QUEUE_SIZE` / `_BREAKER_COOLDOWN` | Delivery tuning, read by the client | short, bounded |

To run without Cockpit, set nothing:

```bash
python -m eth_research.operate --interval 3 --bars 1200
```

## Cost to the trading loop

The reporting layer hands each event to a bounded in-memory queue and returns; one daemon thread in
the client does all the HTTP. Reporting a bar is measured on every iteration and logged next to the
engine time:

```
bar 61 | close 2409.79 | weight 1.000 | equity 10000.00 | engine 8.6ms | telemetry 0.04ms | ...
```

The loop re-derives the run from its first bar each iteration — see `eth_research.operate.paper`
for why — so `engine` grows linearly with the bar count while `telemetry` stays flat. At the
default 1200-bar budget the engine's worst iteration is a small fraction of one bar interval, and
`--bars` bounds it.

## What is proved, and where

`tests/test_cockpit_integration.py` proves, on every run of the suite:

- re-deriving the run each bar extends the journal rather than diverging from it — asserted over
  the chained entry hashes, on a quiet run and on one that trips the kill switch. Everything the
  reporter says about position and equity rests on this, and a freeze pins the runner's bytes but
  not this semantic;
- an enabled run and a disabled run produce a byte-identical journal, checkpoint, fills and account;
- a client whose every method raises changes neither the outcome nor the control flow;
- signal, trade, position and equity payloads equal the platform's own values;
- staleness, drawdown, risk-breach and engine-failure events come from the real code paths;
- the heartbeat starts, beats, stops, refuses to double-start, and runs as a daemon;
- every reporting method is annotated `-> None`, so nothing can branch on monitoring;
- reporting work per bar stays bounded by what happened at that bar, and the engine is derived
  exactly once per bar — counted rather than timed, so they cannot flake.

Three of them drive the shipped client rather than a double, because "a slow Cockpit does not
block the loop" is only worth asserting against the thing that would actually block:

- a transport that takes two seconds per request does not slow the loop;
- an unreachable Cockpit leaves bars, equity and kill-switch state identical to a silent run;
- the client still exposes the surface the reporter calls.

**These three skip in CI**, and it is worth being plain about why: `nardis-telemetry` is an optional
install and is deliberately absent from `uv.lock`, so CI has no client to borrow. They run for a
developer who followed the install instructions above. If that trade ever stops being acceptable,
the fix is to make the client available to CI — not to weaken the tests into something a mock could
satisfy.
