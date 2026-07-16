# Milestone 3F — bug log

Defects discovered while building the M3F verification/recovery layer, each
reproduced by a failing test *before* the fix. Every entry names the reproduction
test, the root cause, the fix, and the blast radius. Only M3F-authored code is
changed here; the frozen, accepted M2B–M3E stack is never modified (a defect found
in accepted code would be recorded in `docs/M3F_FINDINGS.md`, not fixed here).

The reproductions live in `tests/test_m3f_bug_log.py`.

---

## F1 — fail-open production-proposal count (governance)

**Severity:** high — a fail-open on one of the four M3F forever-invariants.

**Reproduction:** `test_f1_compact_proposal_triggers_hard_stop`,
`test_f1_count_created_proposals_is_whitespace_independent`.

**Symptom.** `honest_state.derive_honest_state` and `catalog._derive_expected_state`
counted created production proposals with the substring test
`'"proposal_created": true' in line` — a literal with a space after the colon. The
M3E proposal registry, however, is serialized compactly by
`eth_research.m3d.validation.canonical_jsonl_line`, which uses
`separators=(",", ":")`. A genuine proposal line is therefore
`…"proposal_created":true…` with **no** space, and the substring never matched. A
real production proposal would be counted as zero, so the derivation's
"`production_proposal_count == 0`" HARD STOP — one of the invariants M3F exists to
guarantee — would pass **fail-open** while a proposal sat in the registry.

The clean repository has zero proposals, so the count was coincidentally correct
today; the defect was latent and would have manifested the moment M3E was ever
activated and produced its first proposal — exactly the transition the invariant
is meant to catch.

**Root cause.** Governance-critical state was derived by a whitespace-sensitive
substring scan over serialized bytes instead of by parsing the records. The same
buggy line had been copied into two modules, so the two derivations shared a
common-mode blind spot rather than cross-checking each other.

**Fix.** A single shared, strict helper
`eth_research.m3f.validation.count_created_proposals` parses each JSONL line
(`strict_jsonl_records`) and counts every record whose `proposal_created` is
present and not exactly `false`. It is whitespace-independent (matches the compact
and spaced forms alike) and **fail-closed**: a smuggled truthy non-bool is counted
as a proposal rather than silently ignored. `honest_state` and `catalog` now both
call this one helper, eliminating the duplicated pattern.

**Blast radius.** Contained to M3F-authored code (`honest_state.py`,
`catalog.py`). The accepted M3E registry writer/verifier
(`eth_research.m3e.registry`) already parses `proposal_created` with
`require_bool`, so the accepted stack was never affected.

**Discovered by.** Building the genuinely-independent stdlib verifier, whose
separate JSON-parsing path disagreed with the package's substring scan — the
precise common-mode divergence independent verification is designed to surface.
