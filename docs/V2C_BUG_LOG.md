# V2C Bug Log

Defects found and corrected during the V2C offline-operations qualification. Each entry records the
class, the impact on scientific results and sealed state, and the fix. Class-B (governance) and
Class-C (robustness) defects are fixed forward; a Class-A (scientific) or Class-D (sealed-state /
irreversible-governance) defect is a terminal stop.

## B-001 — Premature OQ source freeze (sequencing)

- **Class:** B (governance / provenance). No scientific impact; no sealed-state impact.
- **Found:** at the OQ-E → OQ-R handoff, before any registry mutation.
- **Symptom:** commit `e4b3cc3d6ecfa0d58dd4c71c01f06b2e252ba6ee` was recorded as the OQ-E source
  freeze, but it froze only the qualification-*defining* source (firewall, synthetic event stream and
  fault schedule, virtual-time harness, resource/recovery campaigns, SLO contract, OQ registry,
  prospective governance, inactive activation template, buyer boundary, readiness). It did **not**
  freeze the execution scaffold (protocol, orchestrator, virtual-time runner, transactional
  publication, calculation-free recovery, immutable archive, the independent OQ-Q oracle, the replay
  surface), which did not yet exist. Because OQ-R must add no executable source, `e4b3cc3` could not
  honestly remain the source freeze that authorizes qualification execution.
- **Why it is not a hard stop:** the OQ registry was byte-empty and the qualification budget
  unconsumed at discovery. No `registered` event existed, no qualification started, no strategy ran,
  and all three sealed access ledgers (`research/m2b/test_evaluations.jsonl`,
  `research/m3a/development_gate_access.jsonl`, `research/m3d/prospective_evaluations.jsonl`) remained
  byte-empty. Nothing false was stamped; the defect was caught at exactly the checkpoint intended to
  catch it.
- **Fix:** an append-only, hash-chained supersession ledger
  (`governance/v2c/oq_source_freeze_supersession.jsonl`, module
  `eth_research.v2c.oq.supersession`) records `e4b3cc3` as superseded while the registry is still
  pristine. `assert_freeze_not_superseded` refuses a superseded freeze from authorizing registration
  or execution; `assert_freeze_superseded` detects a deleted/absent supersession record. A
  supersession is admissible only while the OQ registry is byte-empty and every sealed ledger is
  byte-empty (checked against live state, never caller-supplied), so the ledger cannot rewrite
  history after a qualification begins. The original `e4b3cc3` freeze bytes are preserved in git
  history; the replacement OQ-E2 freeze (which binds the complete executable surface) will reference
  the supersession record.
- **Regression tests:** `tests/test_v2c_oq_supersession.py` — the superseded freeze cannot authorize
  registration or execution; deletion, reason change, and a tampered started-flag are detected; a
  replacement status of `active` is refused; a non-empty registry or a non-empty sealed ledger at
  supersession is refused; symlink substitution, duplicate ids, and a bound replacement that is
  itself superseded are refused; the live-state recorder binds the real registry/sealed-ledger SHAs.
- **Status:** fixed; committed before the first registry mutation.
