# V2A Shadow-Operations Runbook

How to run and inspect a **signal-only** shadow run. Everything here is offline and non-live: no
network, no orders, no credentials, no money. The runbook never touches a sealed partition.

## Modes

- `synthetic_demo` — a generated price path (no real data).
- `historical_shadow` — replay committed historical bars as-of each bar.
- `paper_simulation` — the same, accounted as a paper book with a starting cash balance.

Any `live` / `production` / `real_money` / `exchange` mode is rejected fail-closed at the boundary.

## Running a shadow run (in-process)

```python
from eth_research.shadow.domain import ETH_USD, PAPER_SIMULATION
from eth_research.shadow.risk import RiskLimits
from eth_research.shadow.monitoring import MonitoringThresholds
from eth_research.shadow.runner import ShadowConfig, ShadowStep, run_shadow

config = ShadowConfig.create(
    mode=PAPER_SIMULATION,
    instrument=ETH_USD,
    candidate_id="trend_candidate",
    starting_cash=10_000.0,
    limits=RiskLimits(max_target_weight=1.0, max_weight_step=0.25),
    thresholds=MonitoringThresholds(max_staleness_seconds=172_800, max_drawdown_fraction=0.35),
)
# steps: a tuple of ShadowStep(envelope=<MarketDataEnvelope>, signal=<SignalEnvelope>) in time order,
# where each signal.as_of <= its bar's close_time (the runner enforces no look-ahead).
result = run_shadow(config, steps)

print(result.bars_processed, result.kill_tripped, result.final_account.equity(steps[-1].envelope.bar.close))
```

The run is deterministic: the same config + steps produce a byte-identical journal and checkpoint.

## Persisting and inspecting a run

```python
from pathlib import Path
from eth_research.shadow.checkpoint import write_checkpoint

Path("outputs").mkdir(exist_ok=True)
Path("outputs/journal.jsonl").write_bytes(result.journal.to_jsonl_bytes())
write_checkpoint("outputs/checkpoint.json", result.checkpoint)
```

Read-only inspection via the CLI (no network, no run):

```bash
python -m eth_research.shadow.cli verify  --journal outputs/journal.jsonl --checkpoint outputs/checkpoint.json
python -m eth_research.shadow.cli summary --journal outputs/journal.jsonl
```

`verify` re-checks the journal hash chain and that the checkpoint is bound to the journal head;
`summary` prints per-event-type counts and the terminal state.

## Safety behaviour

- A hard risk breach (requested weight above `max_target_weight`) trips the **latching** kill
  switch; from that bar on the book **holds** (no further rebalancing) until an explicit reset.
- A drawdown beyond `max_drawdown_fraction` raises a critical alert and also trips the kill switch.
- The as-of clock refuses to move backwards and refuses to reveal any bar or signal from the future.

## What this is not

A shadow run is an *observation of intent*, not trading. There is no venue, no fill sent anywhere,
and no money. `outputs/` is git-ignored; nothing here is committed.
