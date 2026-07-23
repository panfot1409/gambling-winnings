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

## C-001 — Committed OQ digest did not re-derive from the frozen source (provenance)

- **Class:** C (robustness / provenance). No scientific impact; no sealed-state impact.
- **Found:** by the post-qualification red team (Auditor A Finding 1; Auditor B item 4, independently),
  against the committed run at `530f182`.
- **Symptom:** the shipped offline verifier (`verify_oq_run_archive`, the `replay`/`verify` CLIs, the
  OQ-Q oracle) proves the published archive is internally consistent, independently accepted, and
  hash-immutable, but never re-executes the frozen source — so it cannot distinguish a genuine run
  from a self-consistent fabrication of `oq_result.json` (with every dependent digest and the registry
  chain recomputed). The certification test pinned the terminal digests only as string literals (a
  self-referential read-back). Auditor A demonstrated a PoC forgery (`accepted_count = 3999`,
  structurally impossible for the frozen source) that passed `replay`(16), `verify`(10), and the
  oracle.
- **Why it is not a hard stop:** no false scientific claim and no sealed-state change. The genuine
  committed run is unaffected; the gap was in *detection strength*, not in the run. Re-executing the
  frozen source at the canonical `slots = 3800` reproduces the committed digests exactly, so the
  committed run is provably genuine.
- **Fix:** `tests/test_v2c_oq_committed_run.py::test_committed_digests_re_derive_from_the_frozen_source`
  registers → starts → executes → `build_oq_archive` from the isolated `pristine_oq_repo` copy of the
  frozen source at `slots = 3800` and asserts the re-derived `result_sha256` / `result_bundle_sha256`
  equal the committed literals. A forged result cannot pass both this and the read-back assertions
  unless the frozen source itself were altered — which `verify_oq_source_freeze` independently
  refuses. The fix is in the test layer because the verifier/CLI/oracle source is frozen and
  unmodifiable post-freeze; it runs on the authoritative CPython 3.12 leg (re-execution requires the
  OQ runtime), while the read-only certification covers 3.13.
- **Regression tests:** the new test above (3.12 → 9 passed; 3.13 → 8 passed, 1 skipped). The whole
  V2C OQ suite stays green on both interpreters.
- **Status:** fixed forward (`a7dee93`); committed after the run, no run artifact changed.

## Post-qualification red team — other findings

Auditors A, B, C, D, E (five independent read-only auditors) raised no other actionable defect. The
remaining items are Low / by-design / document-only and are recorded in `docs/V2C_FINDINGS.md`
(F-2, F-3, F-5, F-6, F-7): the pristine-branch CLIs not flagging an orphaned archive (frozen CLI,
non-forgeable), the fixture's literal relpaths (fail-safe), the frozen narration-vocabulary regex not
stripping zero-width characters (non-exploitable; authoritative gates are the firewall + numeric
zero-exposure), the keyless integrity chain (git-anchored, disclosed), and the branch advancing
during the audit (additive, clean). No Class-A or Class-D defect was found.
