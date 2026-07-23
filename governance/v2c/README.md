# `governance/v2c/` — V2C offline-operational-qualification governance

This directory holds the append-only governance record for the V2C candidate-free **offline
operational qualification (OQ)**. Everything here is machine-verifiable; nothing here evaluates a
strategy. See `docs/V2C_OQ_METHOD.md` for the full methodology and `docs/V2C_PLAN.md` for the plan.

## Layout

| Path                                     | Role                                                          |
|------------------------------------------|--------------------------------------------------------------|
| `oq_protocol.json`                       | The OQ protocol bundle (methodology + qualification ids).     |
| `oq_fixture_manifest.json`               | Deterministic synthetic fixture identity.                     |
| `oq_fault_schedule.json`                 | Crash/recovery fault schedule.                                |
| `oq_slo_contract.json`                   | SLO criteria contract.                                        |
| `oq_cash_control_identity.json`          | Identity of the candidate-free cash-control target.           |
| `oq_source_freeze.json`                  | OQ-E2 source freeze (schema 2): the frozen surface + evidence. |
| `oq_e2_activation.json`                  | OQ-E2A activation anchor binding the freeze commit `cea86a5`.  |
| `oq_source_freeze_supersession.jsonl`    | Append-only supersession ledger (records `e4b3cc3` superseded).|
| `oq_registry.jsonl`                      | Append-only, hash-linked run registry (the OQ-R/P/Q chain).   |
| `qualifications/…run_001/`               | The immutable, write-once published run archive.              |
| `inactive_workflow_templates/`           | Inactive (`.yml.inactive`) probe templates — never runnable.  |

## The committed run

`oq_registry.jsonl` records one completed qualification —
`registered → started → completed`, verdict `qualified` — and
`qualifications/v2c_offline_operational_qualification_run_001/` holds its three immutable artifacts
(`oq_result.json`, `oq_report.md`, `oq_archive_manifest.json`). Terminal digests (immutable
governance anchors):

- `result_sha256 = 739cec5dca07b984d6fb624384e490dcab7722c5341053790d5ba8cd1945b897`
- `result_bundle_sha256 = e52308a0ffd048ffe4283b51b052fd65e2aab4a37156e53952c16354a9dcb525`

## Invariants (checked by CI + tests)

- The three sealed ledgers (`research/m2b/test_evaluations.jsonl`,
  `research/m3a/development_gate_access.jsonl`, `research/m3d/prospective_evaluations.jsonl`) stay
  **byte-empty** — the qualification touches no sealed partition.
- The OQ-E2 freeze reproduces; the OQ-E2A anchor re-derives from it; `e4b3cc3` stays superseded.
- The published archive is write-once (immutable paths, never overwritten).
- The committed digests re-derive from the frozen source at the canonical slot count (3800).

## Re-checking

```
python -m eth_research.v2c.oq.cli status  --repo-root .   # -> completed
python -m eth_research.v2c.oq.cli replay  --repo-root .   # -> 16 ordered checks incl. oracle accept
python -m eth_research.v2c.oq.cli verify  --repo-root .   # -> 10 deep-archive checks
```

All are read-only. The `v2c-replay` CI workflow runs them on every push.
