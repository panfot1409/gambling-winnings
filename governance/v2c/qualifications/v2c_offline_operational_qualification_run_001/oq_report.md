# V2C Offline Operational Qualification -- Result

- Qualification: `v2c_offline_operational_qualification_run_001`
- Methodology: `v2c_offline_operational_qualification`
- Package version: `2.0.0.dev2`
- Verdict: **qualified**
- Result digest: `216c14473ec0f23e31326e9f62082586e746d4706a0e7b3251e8f9abcbbdd103`

## Governing zero-exposure counts

- Cash-control instructions processed: 7514
- Requested risky exposure: 0.0
- Approved risky exposure: 0.0
- Risky intents: 0
- Risky fills: 0
- Turnover: 0.0
- Terminal book units: 0.0

The paper book held 100% cash throughout; no market performance was computed.

## Qualification criteria

| Criterion | Passed | Detail |
| --- | --- | --- |
| qualification_coverage | True | 2 instrument(s) each covered by a resource and a recovery report |
| event_acceptance_correctness | True | every accepted stream monotonic/unique; rejections map to their fault; all flags fired |
| duplicate_suppression | True | exact duplicates suppressed on every instrument |
| conflicting_duplicate_detection | True | conflicting duplicates rejected and alerted 1:1 |
| journal_durability | True | journal_durability held |
| checkpoint_consistency | True | checkpoint_consistency held |
| recovery_idempotency | True | restart_determinism held |
| kill_switch_trip_latency | True | kill_switch_trip_drill held |
| alert_completeness | True | every runner alert is journaled |
| state_reconstruction | True | journal + checkpoint reconstruct exactly |
| bounded_processing_memory | True | within deterministic resource bounds |
| zero_risky_exposure | True | every fill/intent is zero-exposure; book stays 100% cash |

## Instruments

- `btc_usd`: accepted 3757, steps 3757, recovery passed True, risky fills 0, turnover 0.0
- `eth_usd`: accepted 3757, steps 3757, recovery passed True, risky fills 0, turnover 0.0
